"""End-to-end control trace production through the real control checker."""

from __future__ import annotations

import hashlib
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integration import controller
from integration.tests._history_fixtures import make_ctrl_n4_trace


ROOT = Path(__file__).resolve().parents[2]


class ControlTraceProducerTests(unittest.TestCase):
    def test_run_case_emits_control_identity_and_real_checker_finds_n4_witness(self):
        controls_doc = json.loads((ROOT / "integration/control-scenarios.json").read_text())
        control = next(row for row in controls_doc["controls"] if row["id"] == "CTRL-N4-FALSE-LOGOUT")
        contract = json.loads((ROOT / "integration/contract.json").read_text())
        fixture_trace, _, _ = make_ctrl_n4_trace()
        process_id = fixture_trace["processInstances"][0]["processInstanceId"]
        native_events = fixture_trace["events"]
        run_id = fixture_trace["runId"]

        class FakeRun:
            def __init__(self, **kwargs):
                self.run_id = run_id
                self.base_url = "http://127.0.0.1:43217"

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def events(self, *, timeout=5):
                return [], []

            def publish_checkpoint(self, _process_instance_id, _checkpoint, *, timeout=5):
                return {"status": "checkpointPublished"}

        def fake_run_streaming_command(argv, *, output_directory, on_status=None, **_kwargs):
            Path(output_directory).mkdir(parents=True, exist_ok=True)
            if "--output-path" in argv:
                exported = Path(argv[argv.index("--output-path") + 1])
                image = exported / "nested" / "image-payload"
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL9sAAAAASUVORK5CYII="))
                (exported / "manifest.json").write_text(json.dumps([{
                    "testIdentifier": "ScenarioUITests/testFrozenScenarioHarness()",
                    "attachments": [{"exportedFileName": "nested/image-payload", "suggestedHumanReadableName": "screen-final_0_fixture.png"}],
                }]))
            if on_status is not None:
                receipts = sorted(
                    (event for event in native_events if event.get("kind") == "commandReceipt"),
                    key=lambda event: event["commandRef"]["id"],
                )
                for receipt in receipts:
                    command_id = receipt["commandRef"]["id"]
                    on_status({
                        "scenarioId": control["id"],
                        "processInstanceId": process_id,
                        "checkpointName": f"receipt.{command_id}",
                        "phase": "receiptObserved",
                        "lastProcessedCommandId": str(command_id),
                    })
                step_id = control["requiredProbes"][0]
                snapshot = {
                    "version": 1,
                    "processInstanceId": process_id,
                    "launchOrdinal": 1,
                    "controlRevision": 0,
                    "storeIoActive": False,
                    "hooks": [],
                }
                on_status({
                    "scenarioId": control["id"],
                    "processInstanceId": process_id,
                    "checkpointName": f"storeProbe.{step_id}",
                    "phase": "probeRequested",
                    "controlSnapshotJSON": json.dumps(snapshot),
                })
                envelope = {
                    "probeId": "ctrl-n4-independent-probe-1",
                    "processInstanceId": process_id,
                    "observation": {"kind": "Absent"},
                }
                on_status({
                    "scenarioId": control["id"],
                    "processInstanceId": process_id,
                    "checkpointName": f"storeProbe.{step_id}",
                    "phase": "probeCaptured",
                    "lastProcessedCommandId": "3",
                    "redactedObservation": json.dumps(envelope),
                })
                on_status({
                    "scenarioId": control["id"],
                    "processInstanceId": process_id,
                    "checkpointName": "processEndAcknowledged",
                    "phase": "processEndAcknowledged",
                    "processEndAckJSON": json.dumps({
                        "processInstanceId": process_id,
                        "eventRef": {
                            "processInstanceId": process_id,
                            "localSequence": next(event["localSequence"] for event in native_events if event["kind"] == "processEnd"),
                        },
                    }),
                })
                on_status({
                    "scenarioId": control["id"],
                    "processInstanceId": process_id,
                    "checkpointName": "scenarioHarnessFinished",
                    "phase": "end",
                })
            return {"argv": argv, "exitCode": 0, "timedOut": False, "durationSeconds": 0.0}

        def fake_terminate(_device, current_process, ordinal, controller_events, **_kwargs):
            controller._append_controller_event(
                controller_events, "forceStopped", current_process, pidAbsent=True
            )
            controller._append_controller_event(
                controller_events, "terminated", current_process, launchOrdinal=ordinal
            )
            return {"argv": ["fake-owned-termination"], "exitCode": 0}

        scenario_path = ROOT / "integration/scenarios.json"
        control_path = ROOT / "integration/control-scenarios.json"
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            output = Path(temporary) / "candidate-ios" / "ios"
            with (
                patch.object(controller, "LoopbackRun", FakeRun),
                patch.object(controller, "run_streaming_command", fake_run_streaming_command),
                patch.object(
                    controller,
                    "_copy_ios_process_artifacts",
                    return_value=(native_events, "CTRL-N4-FALSE-LOGOUT/p1/native.jsonl", []),
                ),
                patch.object(controller, "_ios_terminate_app", fake_terminate),
                patch.object(controller, "read_live_native_events", return_value=native_events),
            ):
                result, trace, screenshots = controller._run_case(
                    platform="ios",
                    candidate=ROOT,
                    output=output,
                    device="OWNED-UUID",
                    scenario=control,
                    resolved_scenario=control,
                    variant=None,
                    attempt_base="attempt-01",
                    contract=contract,
                    build_hash="b" * 64,
                    app_paths={"xctestrunPath": "frozen.xctestrun"},
                    scenario_path=scenario_path,
                    control_path=control_path,
                    scenario_digest=digest(scenario_path),
                    control_digest=digest(control_path),
                    timeout_seconds=30,
                    command_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
                        argv, 0, stdout="", stderr=""
                    ),
                )

        self.assertIsNotNone(trace)
        self.assertEqual(trace["scenarioId"], control["id"])
        self.assertEqual(trace["controlId"], control["id"])
        self.assertNotIn("variantId", trace)
        self.assertEqual(result["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I5", "I8"} <= {row["invariant"] for row in result["violations"]})
        self.assertEqual(len(screenshots), 1)
        self.assertTrue(screenshots[0]["path"].endswith("/screenshots/nested/image-payload"))


if __name__ == "__main__":
    unittest.main()
