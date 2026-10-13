import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import protocol_config, reproduce
from integration.controller import _write_platform_artifact_shell
from verification import change_protocol


ROOT = Path(__file__).resolve().parents[2]


class IntegrationControlsStageTests(unittest.TestCase):
    def test_control_is_not_detected_when_only_part_of_its_frozen_witness_is_present(self):
        config = protocol_config.build_config(
            ROOT,
            ROOT / "reports" / "standalone" / "attempts" / "controls-witness-config",
            "d2ce1847cb2644252f7c4d069ef9e36142bb327b",
        )
        controls_path = ROOT / "integration" / "control-scenarios.json"
        controls = json.loads(controls_path.read_text())["controls"]
        with tempfile.TemporaryDirectory(prefix="integration-control-witness-") as directory:
            output = Path(directory)
            ios_output = output / "ios"
            ios_output.mkdir()
            cases = [
                {
                    "scenarioId": row["id"],
                    "classification": "SEMANTIC_FAIL",
                    "violations": [{"invariant": invariant} for invariant in row["witnessInvariants"]],
                }
                for row in controls
            ]
            n4 = next(row for row in cases if row["scenarioId"] == "CTRL-N4-FALSE-LOGOUT")
            n4["violations"] = [{"invariant": "I5"}]
            (ios_output / "scenario-results.json").write_text(json.dumps({"cases": cases}))
            result = {
                "completedScenarioIds": [row["id"] for row in controls],
            }

            rows = reproduce._control_observations(
                "ios",
                result,
                output,
                [row["id"] for row in controls],
                config["stages"]["integration-controls"]["expectedControlWitnesses"],
            )

        n4_result = next(row for row in rows if row["controlId"] == "CTRL-N4-FALSE-LOGOUT")
        self.assertEqual(n4_result["classification"], "NOT_DETECTED")
        self.assertEqual(n4_result["observedWitnesses"], ["I5"])

    def test_controls_stage_runs_both_owned_platforms_and_binds_each_witness(self):
        config = protocol_config.build_config(
            ROOT,
            ROOT / "reports" / "standalone" / "attempts" / "controls-run-config",
            "d2ce1847cb2644252f7c4d069ef9e36142bb327b",
        )
        stage = config["stages"]["integration-controls"]
        controls_path = ROOT / "integration" / "control-scenarios.json"
        controls = json.loads(controls_path.read_text())["controls"]
        calls = []

        def run_platform(platform, **kwargs):
            calls.append((platform, kwargs))
            output = Path(kwargs["output"])
            result = {
                "classification": "SEMANTIC_FAIL",
                "platform": platform,
                "deviceId": "owned-" + platform,
                "requiredScenarioIds": list(stage["requiredScenarioIds"]),
                "completedScenarioIds": list(stage["requiredScenarioIds"]),
                "missingScenarioIds": [],
                "deviceHash": "sha256:" + "a" * 64,
                "buildHash": "sha256:" + "b" * 64,
                "scenarioBuildHashes": {
                    row["id"]: "sha256:" + ("c" if platform == "ios" else "d") * 64
                    for row in controls
                },
                "detail": "fixture carries expected mutation witnesses",
            }
            _write_platform_artifact_shell(
                output,
                platform=platform,
                stage_id="integration-controls",
                scenario_rows=controls,
                result=result,
            )
            cases = []
            for control in controls:
                cases.append({
                    "scenarioId": control["id"],
                    "variantId": None,
                    "classification": "SEMANTIC_FAIL",
                    "violations": [
                        {"invariant": invariant}
                        for invariant in control["witnessInvariants"]
                    ],
                    "missingObservations": [],
                })
            (output / "scenario-results.json").write_text(json.dumps({"platform": platform, "classification": "SEMANTIC_FAIL", "cases": cases}))
            result["traceBindings"] = [
                {
                    "platform": platform,
                    "scenarioId": row["scenarioId"],
                    "variantId": row["variantId"],
                    "buildHash": result["scenarioBuildHashes"][row["scenarioId"]],
                }
                for row in protocol_config._trace_bindings([platform], controls)
            ]
            return result

        environment = {
            "IOS_SIMULATOR_UDID": "owned-ios",
            "ANDROID_SERIAL": "owned-android",
            "NATIVE_CONTRACT_OWNED_IOS_DEVICE_EVIDENCE": "/tmp/owned-ios.json",
            "NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE": "/tmp/owned-android.json",
        }
        with tempfile.TemporaryDirectory(prefix="integration-controls-stage-", dir=ROOT / "reports" / "standalone") as directory:
            output = Path(directory) / "integration-controls"
            with patch.dict(os.environ, environment, clear=False), patch("integration.controller.run_platform", side_effect=run_platform):
                result = reproduce.stage(candidate=ROOT, stage_id="integration-controls", output=output)

            self.assertEqual([platform for platform, _ in calls], ["ios", "android"])
            self.assertTrue(all(call["scenarios"] == controls_path for _, call in calls))
            self.assertEqual(
                [call["owned_device_evidence"] for _, call in calls],
                ["/tmp/owned-ios.json", "/tmp/owned-android.json"],
            )
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["classification"], "PASS")
            self.assertEqual(len(report["controlResults"]), 10)
            self.assertTrue(all(row["classification"] == "DETECTED" for row in report["controlResults"]))
            self.assertEqual(len(report["traceBindings"]), len(stage["expectedTraceBindings"]))
            change_protocol.integration_report(output / "report.json", stage)

    def test_selected_platform_controls_remain_an_explicit_partial_not_run_ledger(self):
        config = protocol_config.build_config(
            ROOT,
            ROOT / "reports" / "standalone" / "attempts" / "controls-partial-config",
            "d2ce1847cb2644252f7c4d069ef9e36142bb327b",
        )
        stage = config["stages"]["integration-controls"]
        controls = json.loads((ROOT / "integration" / "control-scenarios.json").read_text())["controls"]

        def run_platform(platform, **kwargs):
            output = Path(kwargs["output"])
            result = {
                "classification": "SEMANTIC_FAIL",
                "platform": platform,
                "deviceId": "owned-ios",
                "requiredScenarioIds": list(stage["requiredScenarioIds"]),
                "completedScenarioIds": list(stage["requiredScenarioIds"]),
                "missingScenarioIds": [],
                "deviceHash": "sha256:" + "a" * 64,
                "buildHash": "sha256:" + "b" * 64,
                "scenarioBuildHashes": {
                    row["id"]: "sha256:" + "c" * 64 for row in controls
                },
            }
            _write_platform_artifact_shell(
                output,
                platform=platform,
                stage_id="integration-controls",
                scenario_rows=controls,
                result=result,
            )
            cases = [
                {
                    "scenarioId": row["id"],
                    "variantId": None,
                    "classification": "SEMANTIC_FAIL",
                    "violations": [{"invariant": invariant} for invariant in row["witnessInvariants"]],
                    "missingObservations": [],
                }
                for row in controls
            ]
            (output / "scenario-results.json").write_text(json.dumps({"cases": cases}))
            result["traceBindings"] = [
                {
                    "platform": platform,
                    "buildHash": result["scenarioBuildHashes"][binding["scenarioId"]],
                    **binding,
                }
                for binding in protocol_config._trace_bindings([platform], controls)
            ]
            return result

        environment = {
            "NATIVE_CONTRACT_CONTROL_PLATFORMS": "ios",
            "IOS_SIMULATOR_UDID": "owned-ios",
            "NATIVE_CONTRACT_OWNED_IOS_DEVICE_EVIDENCE": "/tmp/owned-ios.json",
        }
        with tempfile.TemporaryDirectory(
            prefix="integration-controls-partial-", dir=ROOT / "reports" / "standalone"
        ) as directory:
            output = Path(directory) / "integration-controls"
            with patch.dict(os.environ, environment, clear=False), patch(
                "integration.controller.run_platform", side_effect=run_platform
            ):
                result = reproduce.stage(candidate=ROOT, stage_id="integration-controls", output=output)

            report = json.loads((output / "report.json").read_text())
            self.assertEqual(result["classification"], "NOT_RUN")
            self.assertEqual(
                {row["platform"]: row["classification"] for row in report["platformResults"]},
                {"ios": "PASS", "android": "NOT_RUN"},
            )
            self.assertEqual({row["platform"] for row in report["controlResults"]}, {"ios"})
            self.assertEqual({row["platform"] for row in report["traceBindings"]}, {"ios"})
            change_protocol.integration_report(output / "report.json", stage)


if __name__ == "__main__":
    unittest.main()
