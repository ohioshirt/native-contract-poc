import json
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest

from integration import aggregate, controller, protocol_config
from verification import change_protocol as protocol


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "d2ce1847cb2644252f7c4d069ef9e36142bb327b"


class PortableAttemptTests(unittest.TestCase):
    def setUp(self):
        self.manifest = protocol_config.build_config(
            ROOT, ROOT / "reports" / "standalone" / "attempts" / "portable-aggregate-config", BASELINE
        )
        self.stage_id = "legacy-full"
        self.stage = self.manifest["stages"][self.stage_id]
        self.manifest_digest = "a" * 64
        self.candidate_digest = "b" * 64

    def make_attempt(self, root):
        attempt_id = "auto-" + self.stage_id
        output = Path(root) / attempt_id
        output.mkdir(parents=True)
        producer_root = "/home/runner/work/native-contract/native-contract"
        producer_output = str(Path(producer_root) / self.manifest["outputRoot"] / attempt_id)
        argv = aggregate._substitute_argv(self.stage, producer_root, producer_output)
        started_ns = time.time_ns() - 1_000_000_000
        protocol.write_json(output / "command.json", {"argv": argv, "cwd": producer_root})
        (output / "stdout.log").write_text("verified full gate\n")
        (output / "stderr.log").write_text("")
        (output / "legacy-full" / "report.md").parent.mkdir(parents=True)
        (output / "legacy-full" / "report.md").write_text("Overall: PASS\n")
        artifacts = protocol.read_artifacts(output, self.stage, started_ns)
        result = {
            "manifestDigest": self.manifest_digest,
            "candidateDigest": self.candidate_digest,
            "stageId": self.stage_id,
            "attemptId": attempt_id,
            "outputDirectory": producer_output,
            "argv": argv,
            "cwd": producer_root,
            "verdictProtocol": self.stage["verdictProtocol"],
            "metadata": self.manifest["metadata"],
            "startedUtc": "2026-10-12T00:00:00+00:00",
            "startedNs": started_ns,
            "exitCode": 0,
            "timedOut": False,
            "artifacts": artifacts,
            "evidence": protocol.captured_evidence(output, argv, producer_root),
            "classification": "PASS",
            "endedUtc": "2026-10-12T00:00:01+00:00",
            "durationSeconds": 1.0,
        }
        protocol.write_json(output / "result.json", result)
        suite_row = {
            "stageId": self.stage_id,
            "attemptId": attempt_id,
            "classification": "PASS",
            "manifestDigest": self.manifest_digest,
            "candidateDigest": self.candidate_digest,
            "outputDirectory": producer_output,
            "argv": argv,
            "cwd": producer_root,
            "verdictProtocol": self.stage["verdictProtocol"],
            "bindingClassification": "PASS",
            "bindingResult": {
                "bindingClassification": "PASS",
                "manifestDigest": self.manifest_digest,
                "candidateDigest": self.candidate_digest,
            },
        }
        return output, result, suite_row

    def test_artifacts_relocate_across_runner_workspaces_without_rewriting_execution_record(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-imported-ledger-") as directory:
            _, _, suite_row = self.make_attempt(directory)
            result, _, _ = aggregate._portable_attempt(
                directory,
                ROOT,
                self.manifest,
                self.manifest_digest,
                self.stage_id,
                suite_row,
                self.candidate_digest,
            )
        self.assertEqual(result["cwd"], "/home/runner/work/native-contract/native-contract")
        self.assertEqual(result["classification"], "PASS")

    def test_reimported_artifact_mtime_is_not_misreported_as_producer_freshness(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-extracted-ledger-") as directory:
            output, _, suite_row = self.make_attempt(directory)
            artifact = output / "legacy-full" / "report.md"
            old_ns = max(1, output.joinpath("result.json").stat().st_mtime_ns - 10_000_000_000)
            os.utime(artifact, ns=(old_ns, old_ns))
            result, _, _ = aggregate._portable_attempt(
                directory,
                ROOT,
                self.manifest,
                self.manifest_digest,
                self.stage_id,
                suite_row,
                self.candidate_digest,
            )
        self.assertEqual(result["classification"], "PASS")

    def test_tampered_frozen_command_path_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-tampered-command-") as directory:
            output, result, suite_row = self.make_attempt(directory)
            result["cwd"] = "/home/runner/other-checkout"
            protocol.write_json(output / "result.json", result)
            with self.assertRaisesRegex(aggregate.AggregateError, "output binding"):
                aggregate._portable_attempt(
                    directory, ROOT, self.manifest, self.manifest_digest, self.stage_id, suite_row, self.candidate_digest
                )

    def test_tampered_frozen_argv_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-tampered-argv-") as directory:
            output, result, suite_row = self.make_attempt(directory)
            result["argv"][-1] = "reports/standalone/not-the-output/report.md"
            protocol.write_json(output / "result.json", result)
            with self.assertRaisesRegex(aggregate.AggregateError, "frozen run"):
                aggregate._portable_attempt(
                    directory, ROOT, self.manifest, self.manifest_digest, self.stage_id, suite_row, self.candidate_digest
                )

    def test_changed_candidate_digest_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-source-mismatch-") as directory:
            _, _, suite_row = self.make_attempt(directory)
            with self.assertRaisesRegex(aggregate.AggregateError, "frozen run"):
                aggregate._portable_attempt(
                    directory, ROOT, self.manifest, self.manifest_digest, self.stage_id, suite_row, "c" * 64
                )

    def test_tampered_artifact_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-tampered-artifact-") as directory:
            output, _, suite_row = self.make_attempt(directory)
            (output / "legacy-full" / "report.md").write_text("Overall: FAIL\n")
            with self.assertRaisesRegex(aggregate.AggregateError, "artifacts changed"):
                aggregate._portable_attempt(
                    directory, ROOT, self.manifest, self.manifest_digest, self.stage_id, suite_row, self.candidate_digest
                )


class PartialControlAggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = protocol_config.build_config(
            ROOT, ROOT / "reports" / "standalone" / "attempts" / "partial-control-aggregate-config", BASELINE
        )
        cls.stage = config["stages"]["integration-controls"]

    def report(self, platform):
        other = "android" if platform == "ios" else "ios"
        ids = list(self.stage["requiredScenarioIds"])
        report = {
            "classification": "NOT_RUN",
            "platformResults": [
                {
                    "platform": platform,
                    "classification": "PASS",
                    "validationScope": "ci",
                    "completedScenarioIds": ids,
                    "missingScenarioIds": [],
                    "deviceHash": "a" * 64,
                    "buildHash": None,
                    "scenarioBuildHashes": {control_id: "sha256:" + "b" * 64 for control_id in ids},
                },
                {
                    "platform": other,
                    "classification": "NOT_RUN",
                    "validationScope": "not-run",
                    "completedScenarioIds": [],
                    "missingScenarioIds": ids,
                    "deviceHash": None,
                    "buildHash": None,
                    "scenarioBuildHashes": {},
                },
            ],
            "controlResults": [
                {
                    "platform": platform,
                    "controlId": control_id,
                    "classification": "DETECTED",
                    "observedWitnesses": self.stage["expectedControlWitnesses"][control_id],
                }
                for control_id in ids
            ],
            "traceBindings": [
                {
                    "platform": platform,
                    "scenarioId": row["scenarioId"],
                    "variantId": row["variantId"],
                }
                for row in self.stage["expectedTraceBindings"] if row["platform"] == platform
            ],
        }
        return report

    def test_complete_partial_platform_report_is_accepted(self):
        row = aggregate.validate_partial_control_report(self.report("ios"), self.stage, "ios")
        self.assertEqual(row["classification"], "PASS")

    def test_missing_platform_is_rejected(self):
        report = self.report("ios")
        report["platformResults"] = report["platformResults"][:1]
        with self.assertRaisesRegex(aggregate.AggregateError, "partial NOT_RUN"):
            aggregate.validate_partial_control_report(report, self.stage, "ios")

    def test_selected_infra_or_not_run_platform_is_rejected(self):
        for classification in ("INFRA_FAILURE", "NOT_RUN"):
            with self.subTest(classification=classification):
                report = self.report("ios")
                report["platformResults"][0]["classification"] = classification
                with self.assertRaises(aggregate.AggregateError):
                    aggregate.validate_partial_control_report(report, self.stage, "ios")

    def test_missing_control_witness_is_rejected(self):
        report = self.report("ios")
        report["controlResults"].pop()
        with self.assertRaisesRegex(aggregate.AggregateError, "every named control witness"):
            aggregate.validate_partial_control_report(report, self.stage, "ios")


class PortableLedgerOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.digest = "a" * 64
        self.candidate_digest = "b" * 64
        self.stages = ["integration-red", "candidate-ios"]

    def make_root(self, root):
        root = Path(root)
        for stage_id in self.stages:
            (root / ("auto-" + stage_id)).mkdir(parents=True)
        suite = {
            "version": 1,
            "classification": "PASS",
            "manifest": "/producer/manifest.json",
            "manifestDigest": self.digest,
            "selectedStages": self.stages,
            "stageResults": [],
        }
        protocol.write_json(root / "suite-report.json", suite)
        protocol.write_json(root / "ledger-owner.json", {
            "version": 1,
            "manifestDigest": self.digest,
            "manifestOwnerSha256": hashlib.sha256((self.digest + "\n").encode()).hexdigest(),
            "selectedStages": self.stages,
            "attemptIds": ["auto-" + row for row in self.stages],
            "candidateDigests": [self.candidate_digest],
        })
        return root, suite

    def test_visible_owner_binds_relocated_manifest_without_hidden_files(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-ledger-owner-") as temporary:
            root, suite = self.make_root(Path(temporary) / "ledger")
            aggregate._verify_ledger_root(
                root, suite, self.digest, self.candidate_digest, self.stages, "ios"
            )

    def test_unlisted_attempt_directory_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-ledger-extra-attempt-") as temporary:
            root, suite = self.make_root(Path(temporary) / "ledger")
            (root / "auto-unlisted-retry").mkdir()
            with self.assertRaisesRegex(aggregate.AggregateError, "unexpected or missing attempt"):
                aggregate._verify_ledger_root(
                    root, suite, self.digest, self.candidate_digest, self.stages, "ios"
                )

    def test_mismatched_visible_owner_or_candidate_digest_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="aggregate-ledger-owner-mismatch-") as temporary:
            root, suite = self.make_root(Path(temporary) / "ledger")
            owner = json.loads((root / "ledger-owner.json").read_text())
            owner["candidateDigests"] = ["c" * 64]
            protocol.write_json(root / "ledger-owner.json", owner)
            with self.assertRaisesRegex(aggregate.AggregateError, "visible ledger owner"):
                aggregate._verify_ledger_root(
                    root, suite, self.digest, self.candidate_digest, self.stages, "ios"
                )


class PlatformScreenshotManifestTests(unittest.TestCase):
    def test_variant_screenshot_paths_resolve_from_platform_root_without_collisions(self):
        local_path = "APP-09/p1/screenshots/APP-09-final-view.png"
        with tempfile.TemporaryDirectory(prefix="variant-screenshot-roundtrip-") as temporary:
            platform_root = Path(temporary) / "ios"
            rows = []
            for variant in ("clear-before", "clear-after-before-verify"):
                case_root = controller.case_artifact_directory(platform_root.parent, "ios", "APP-09", variant)
                screenshot = case_root / local_path
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(variant.encode("ascii"))
                row = {"path": local_path, "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()}
                rows.extend(controller.platform_screenshot_rows(platform_root, case_root, [row]))
            (platform_root / "screenshots").mkdir(parents=True, exist_ok=True)
            protocol.write_json(platform_root / "screenshots" / "manifest.json", {"screenshots": rows})

            verified = aggregate._verify_screenshot_manifest(platform_root)

        self.assertEqual(verified, rows)
        self.assertEqual(len({row["path"] for row in verified}), 2)

if __name__ == "__main__":
    unittest.main()
