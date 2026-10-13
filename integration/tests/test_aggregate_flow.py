"""Synthetic artifact round-trip, not execution evidence for native apps.

Use small trusted-stage fixtures and a full frozen incomplete-evidence ledger,
without mocking the reader, model validators, mutation installer or checker.
Native traces and build/device records are explicitly fabricated test inputs.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from integration import aggregate, model, protocol_config, reproduce
from integration.check import check_trace, check_control_trace
from integration.mutation_installation import prepare_mutation_workspace
from integration.tests import _history_fixtures as histories
from integration.tests.test_mutation_installation import _candidate_source
from verification import change_protocol as protocol


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "d2ce1847cb2644252f7c4d069ef9e36142bb327b"


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    protocol.write_json(Path(path), value)


class SyntheticAggregateFlowTests(unittest.TestCase):
    def make_candidate(self, root, *, small=True):
        config = protocol_config.build_config(ROOT, "reports/fixture-ledger", BASELINE)
        for relative in protocol.snapshot(ROOT, config):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        # Only read Git history. This fixture never runs a Git mutation.
        (root / ".git").write_text("gitdir: " + str(ROOT / ".git") + "\n")
        self.scenario = next(row for row in json.loads((root / "integration/scenarios.json").read_text())["scenarios"] if row["id"] == "APP-01")
        self.control = next(row for row in json.loads((root / "integration/control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N4-FALSE-LOGOUT")
        if small:
            write(root / "integration/scenarios.json", {"version": 1, "scenarios": [self.scenario]})
            write(root / "integration/control-scenarios.json", {"version": 1, "controls": [self.control]})
        matrix_path = root / "integration/mutation_matrix.json"
        matrix = json.loads(matrix_path.read_text())
        if small:
            matrix["mutations"] = [row for row in matrix["mutations"] if row["id"] == "N4-false-logout-ack"]
        write(matrix_path, matrix)
        for language, anchor in matrix["mutations"][0]["anchors"].items():
            (root / anchor["path"]).write_text(_candidate_source(language))
        # The public frozen protocol retains its complete inventory. Smaller
        # stages below are private unit inputs, never acceptance manifests.
        return config if small else protocol_config.build_config(root, "reports/fixture-ledger", BASELINE)

    def native_platform(self, output, stage_id, platform, stage, candidate, temporary):
        controls = "expectedControlWitnesses" in stage
        item = self.control if controls else self.scenario
        trace, server, observations = histories.make_ctrl_n4_trace() if controls else histories.make_app01_trace()
        trace = copy.deepcopy(trace)
        trace["platform"] = platform
        raw_hash = ("e" if controls else "d") * 64
        build_hash = "sha256:" + raw_hash
        trace["buildHash"] = build_hash
        checked = (check_control_trace if controls else check_trace)(
            json.loads((candidate / "integration/contract.json").read_text()), item, trace, server, observations
        )
        self.assertEqual(checked["classification"], "SEMANTIC_FAIL" if controls else "PASS", checked)
        platform_root = output / stage_id / platform
        write(platform_root / "device.json", {"deviceHash": "c" * 64, "syntheticFixture": True})
        write(platform_root / "build.json", {"buildHash": None if controls else raw_hash, "scenarioBuildHashes": {item["id"]: build_hash} if controls else {}, "syntheticFixture": True})
        case = {"scenarioId": item["id"], "variantId": None, **{key: checked[key] for key in ("classification", "violations", "missingObservations")}}
        platform_report = {"buildHash": None if controls else raw_hash, "scenarioBuildHashes": {item["id"]: build_hash} if controls else {}, "syntheticFixture": True}
        if controls:
            mutation = "N4-false-logout-ack"
            provenance = prepare_mutation_workspace(candidate=candidate, workspace=temporary / (platform + "-mutation"), mutation_id=mutation, platform=platform, matrix_path=candidate / "integration/mutation_matrix.json")
            case.update(mutationId=mutation, buildHash=build_hash, workspaceSourceSha256=provenance["workspaceSourceSha256"])
            platform_report["mutationBuilds"] = [{**provenance, "classification": "BUILD_READY", "platform": platform, "buildHash": build_hash, "controlIds": [item["id"]], "buildCommands": {"syntheticFixture": True}}]
        write(platform_root / "platform-report.json", platform_report)
        write(platform_root / "scenario-results.json", {"platform": platform, "cases": [case]})
        (platform_root / "native-trace.jsonl").write_text(json.dumps({"scenarioId": item["id"], "variantId": None, "trace": trace}) + "\n")
        write(platform_root / "server-events.json", {"cases": [{"scenarioId": item["id"], "variantId": None, "runId": trace["runId"], "events": server}]})
        write(platform_root / "ui-observations.json", {"cases": [{"scenarioId": item["id"], "variantId": None, "observations": observations}]})
        write(platform_root / "controller-events.json", {"syntheticFixture": True})
        write(platform_root / "screenshots/manifest.json", {"screenshots": []})
        return {
            "platform": platform, "classification": "PASS", "requiredScenarioIds": [item["id"]],
            "completedScenarioIds": [item["id"]], "missingScenarioIds": [], "deviceHash": "sha256:" + "c" * 64,
            "buildHash": None if controls else build_hash, "validationScope": "ci",
            "requiredArtifacts": [row["path"] for row in stage["requiredArtifacts"] if row["path"].startswith(stage_id + "/" + platform + "/")],
            **({"scenarioBuildHashes": {item["id"]: build_hash}} if controls else {}),
        }, {"platform": platform, "scenarioId": item["id"], "variantId": None, "buildHash": build_hash}

    def fill_stage(self, output, stage_id, platform, stage, candidate, temporary):
        if stage_id == "legacy-full":
            target = output / "legacy-full/report.md"
            target.parent.mkdir(parents=True)
            target.write_text("Overall: PASS\nSynthetic unit fixture; no native execution.\n")
            return 0
        if stage_id == "integration-red":
            reproduce.stage(candidate=ROOT, stage_id=stage_id, output=output / stage_id)
            return 1
        if getattr(self, "native_not_run", False):
            # Use the actual producers over the complete protected inventory.
            # No device means no OS command; shell cases remain explicitly
            # NOT_RUN, never fabricated completed native histories.
            with patch.dict("os.environ", {}, clear=True):
                result = reproduce.stage(candidate=candidate, stage_id=stage_id, output=output / stage_id)
            self.assertEqual(result["classification"], "NOT_RUN")
            return result["exitCode"]
        row, binding = self.native_platform(output, stage_id, platform, stage, candidate, temporary)
        controls = stage_id == "integration-controls"
        row.update(requiredScenarioIds=stage["requiredScenarioIds"], completedScenarioIds=stage["requiredScenarioIds"])
        if controls:
            row["scenarioBuildHashes"] = {name: binding["buildHash"] for name in stage["requiredScenarioIds"]}
        rows = [row]
        if controls:
            peer = "android" if platform == "ios" else "ios"
            from integration.controller import _write_platform_artifact_shell
            shell = _write_platform_artifact_shell(output / stage_id / peer, platform=peer, stage_id=stage_id, scenario_rows=[self.control], result={"platform": peer, "classification": "NOT_RUN", "deviceId": None, "requiredScenarioIds": [self.control["id"]]})
            rows.append({"platform": peer, "classification": "NOT_RUN", "requiredScenarioIds": stage["requiredScenarioIds"], "completedScenarioIds": [], "missingScenarioIds": stage["requiredScenarioIds"], "deviceHash": None, "buildHash": None, "validationScope": "not-run", "requiredArtifacts": shell["requiredArtifacts"], "scenarioBuildHashes": {}})
            rows.sort(key=lambda item: stage["expectedPlatforms"].index(item["platform"]))
            model.explore(output=output / stage_id / "model/baseline")
            for mutant in stage["requiredMutantWitnesses"]:
                model.explore(output=output / stage_id / "model/mutants" / mutant, mutant=mutant)
        bindings = [{**b, "buildHash": binding["buildHash"]} for b in stage["expectedTraceBindings"] if b["platform"] == platform]
        report = {"version": 1, "stageId": stage_id, "classification": "NOT_RUN" if controls else "PASS", "requiredScenarioIds": stage["requiredScenarioIds"], "platformResults": rows, "violations": [], "deviceHashes": {r["platform"]: r["deviceHash"] for r in rows}, "buildHashes": {r["platform"]: r["buildHash"] for r in rows}, "requiredArtifacts": [r["path"] for r in stage["requiredArtifacts"] if r["validator"] != "integration-report"], "traceBindings": bindings}
        if controls:
            report["controlResults"] = [{"platform": platform, "controlId": name, "classification": "DETECTED", "observedWitnesses": stage["expectedControlWitnesses"][name]} for name in stage["requiredScenarioIds"]]
        write(output / stage_id / "report.json", report)
        return 3 if controls else 0

    def ledger(self, root, platform, stages, manifest, digest, candidate, temporary):
        rows = []
        candidate_digest = protocol.check_sources(manifest, candidate)
        for stage_id in stages:
            stage = manifest["stages"][stage_id]
            attempt = "auto-" + stage_id
            output = root / attempt
            output.mkdir(parents=True)
            producer_output = candidate / manifest["outputRoot"] / attempt
            argv = aggregate._substitute_argv(stage, candidate, producer_output)
            started = time.time_ns()
            write(output / "command.json", {"argv": argv, "cwd": str(candidate)})
            (output / "stdout.log").write_text("Synthetic unit fixture: declared argv was NOT executed.\n")
            (output / "stderr.log").write_text("")
            code = self.fill_stage(output, stage_id, platform, stage, candidate, temporary)
            artifacts = protocol.read_artifacts(output, stage, started)
            classification = protocol.classify(stage, code, False, output)
            result = {"manifestDigest": digest, "candidateDigest": candidate_digest, "stageId": stage_id, "attemptId": attempt, "outputDirectory": str(producer_output), "argv": argv, "cwd": str(candidate), "verdictProtocol": stage["verdictProtocol"], "metadata": manifest["metadata"], "startedUtc": datetime.now(timezone.utc).isoformat(), "startedNs": started, "exitCode": code, "timedOut": False, "artifacts": artifacts, "evidence": protocol.captured_evidence(output, argv, str(candidate)), "classification": classification, "endedUtc": datetime.now(timezone.utc).isoformat(), "durationSeconds": 1.0}
            write(output / "result.json", result)
            rows.append({**result, "bindingClassification": "PASS", "bindingResult": {"bindingClassification": "PASS", "manifestDigest": digest, "candidateDigest": candidate_digest}})
        summary = reproduce.aggregate_suite_results(rows, stages)
        write(root / "suite-report.json", {"version": 1, "classification": summary["classification"], "manifest": str(candidate / "reports/manifest.json"), "manifestDigest": digest, "selectedStages": stages, "stageResults": summary["stageResults"]})
        write(root / "ledger-owner.json", {"version": 1, "manifestDigest": digest, "manifestOwnerSha256": hashlib.sha256((digest + "\n").encode()).hexdigest(), "selectedStages": stages, "attemptIds": ["auto-" + name for name in stages], "candidateDigests": [candidate_digest]})

    def small_stage(self, config, name):
        stage = copy.deepcopy(config["stages"][name])
        identifier = self.control["id"] if name == "integration-controls" else self.scenario["id"]
        stage["requiredScenarioIds"] = [identifier]
        stage["expectedTraceBindings"] = [row for row in stage["expectedTraceBindings"] if row["scenarioId"] == identifier]
        if name == "integration-controls":
            stage["expectedControlWitnesses"] = {identifier: stage["expectedControlWitnesses"][identifier]}
        return stage

    def test_complete_candidate_history_and_partial_control_replay_without_mocks(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            candidate = temporary / "candidate"
            candidate.mkdir()
            config = self.make_candidate(candidate)
            for name in ("candidate-ios", "integration-controls"):
                with self.subTest(stage=name):
                    stage = self.small_stage(config, name)
                    output = temporary / name
                    output.mkdir()
                    self.fill_stage(output, name, "ios", stage, candidate, temporary)
                    _, _, checked = aggregate._verify_native_stage(
                        output, stage, "ios", candidate=candidate,
                        partial_controls=name == "integration-controls",
                    )
                    self.assertEqual(checked[0]["classification"], "SEMANTIC_FAIL" if name == "integration-controls" else "PASS")

    def test_public_aggregate_rejects_incomplete_case_data_despite_full_pass_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            candidate = temporary / "candidate"
            candidate.mkdir()
            config = self.make_candidate(candidate, small=False)
            manifest_path = candidate / "reports/manifest.json"
            digest = protocol.freeze(candidate, config, manifest_path)
            manifest = protocol.read_manifest(manifest_path, digest)
            ios, android = temporary / "ios-ledger", temporary / "android-ledger"
            self.ledger(ios, "ios", aggregate.IOS_STAGES, manifest, digest, candidate, temporary)
            self.ledger(android, "android", aggregate.ANDROID_STAGES, manifest, digest, candidate, temporary)
            with self.assertRaisesRegex(aggregate.AggregateError, "native case membership differs"):
                aggregate.aggregate_ledgers(candidate=candidate, manifest_path=manifest_path, manifest_digest=digest, ios_ledger=ios, android_ledger=android)

    def test_full_inventory_not_run_ledgers_reach_public_aggregate_verdict(self):
        self.native_not_run = True
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            candidate = temporary / "candidate"
            candidate.mkdir()
            config = self.make_candidate(candidate, small=False)
            manifest_path = candidate / "reports/manifest.json"
            digest = protocol.freeze(candidate, config, manifest_path)
            manifest = protocol.read_manifest(manifest_path, digest)
            ios, android = temporary / "ios-ledger", temporary / "android-ledger"
            self.ledger(ios, "ios", aggregate.IOS_STAGES, manifest, digest, candidate, temporary)
            self.ledger(android, "android", aggregate.ANDROID_STAGES, manifest, digest, candidate, temporary)
            result = aggregate.aggregate_ledgers(candidate=candidate, manifest_path=manifest_path, manifest_digest=digest, ios_ledger=ios, android_ledger=android)
            self.assertEqual(result["classification"], "NOT_RUN")
            self.assertEqual(result["derivedIntegrationControls"]["classification"], "NOT_RUN")
            for ledger, stage_id, platform in ((ios, "candidate-ios", "ios"), (android, "candidate-android", "android"), (ios, "integration-controls", "ios"), (android, "integration-controls", "android")):
                rows = json.loads((ledger / ("auto-" + stage_id) / stage_id / platform / "scenario-results.json").read_text())["cases"]
                wanted = {(row["scenarioId"], row["variantId"]) for row in manifest["stages"][stage_id]["expectedTraceBindings"] if row["platform"] == platform}
                self.assertEqual({(row["scenarioId"], row["variantId"]) for row in rows}, wanted)
                self.assertTrue(all(row["classification"] == "NOT_RUN" for row in rows))
