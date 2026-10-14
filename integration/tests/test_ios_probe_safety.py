import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from integration import controller


PROCESS_ID = "attempt-01/APP-01/p1"
SCENARIO_ID = "APP-01"


def _control_snapshot(*, process_id=PROCESS_ID, store_io_active=False, revision=7):
    return {
        "version": 1,
        "processInstanceId": process_id,
        "launchOrdinal": 1,
        "controlRevision": revision,
        "lastActionId": 6,
        "lastActionStatus": "applied",
        "lastEnqueuedCommandRef": {"processInstanceId": process_id, "id": 3},
        "lastProcessedCommandRef": {"processInstanceId": process_id, "id": 2},
        "storeIoActive": store_io_active,
        "hooks": [],
        "lastProbe": None,
    }


def _ios_status(phase, *, snapshot=None, probe=None, checkpoint="storeProbe.APP-01-final-probe"):
    row = {
        "scenarioId": SCENARIO_ID,
        "processInstanceId": PROCESS_ID,
        "checkpointName": checkpoint,
        "phase": phase,
    }
    if snapshot is not None:
        row["controlSnapshotJSON"] = json.dumps(snapshot, sort_keys=True)
    if probe is not None:
        row["redactedObservation"] = json.dumps(probe, sort_keys=True)
    return "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(row, sort_keys=True)


class IOSProbeSafetyTests(unittest.TestCase):
    def _parse(self, line):
        try:
            return controller.parse_ios_status_line(
                line,
                expected_scenario_id=SCENARIO_ID,
                expected_process_instance_id=PROCESS_ID,
            )
        except ValueError as exc:
            self.fail(f"valid process-bound controller status was rejected: {exc}")

    def test_probe_safety_status_accepts_only_process_bound_idle_snapshot(self):
        line = _ios_status("probeRequested", snapshot=_control_snapshot())

        parsed = self._parse(line)

        self.assertEqual(json.loads(parsed["controlSnapshotJSON"])["storeIoActive"], False)

    def test_probe_safety_status_rejects_a_foreign_snapshot(self):
        snapshot = _control_snapshot(process_id="attempt-02/APP-01/p1")
        with self.assertRaises(ValueError):
            controller.parse_ios_status_line(
                _ios_status("probeRequested", snapshot=snapshot),
                expected_scenario_id=SCENARIO_ID,
                expected_process_instance_id=PROCESS_ID,
            )

    def _bridge(self, temporary):
        return controller.NativeProgressBridge(
            platform="ios",
            run=SimpleNamespace(),
            device="owned-simulator",
            attempt_id="attempt-01",
            scenario={"id": SCENARIO_ID, "requiredProbes": ["APP-01-final-probe"]},
            variant=None,
            controller_events=[],
            observations=[],
            process_artifact_directory=Path(temporary),
        )

    def test_active_store_io_blocks_probe_before_host_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = self._bridge(temporary)
            status = self._parse(_ios_status("probeRequested", snapshot=_control_snapshot(store_io_active=True)))
            with patch("integration.controller.capture_probe_status") as capture:
                with self.assertRaisesRegex(ValueError, "store I/O is active"):
                    bridge(status)
            capture.assert_not_called()

    def test_probe_capture_cannot_skip_idle_preflight_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = self._bridge(temporary)
            status = {
                "scenarioId": SCENARIO_ID,
                "processInstanceId": PROCESS_ID,
                "checkpointName": "storeProbe.APP-01-final-probe",
                "phase": "probeCaptured",
                "redactedObservation": json.dumps({
                    "probeId": "probe-1",
                    "processInstanceId": PROCESS_ID,
                    "observation": {"kind": "Absent"},
                }),
            }
            with patch("integration.controller.capture_probe_status") as capture:
                with self.assertRaises(ValueError):
                    bridge(status)
            capture.assert_not_called()

    def test_stale_probe_envelope_is_rejected_until_a_fresh_id_arrives(self):
        snapshot = _control_snapshot()
        snapshot["lastProbe"] = {
            "probeId": "probe-old",
            "processInstanceId": PROCESS_ID,
            "observation": {"kind": "Absent"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            bridge = self._bridge(temporary)
            requested = self._parse(_ios_status("probeRequested", snapshot=snapshot))
            bridge(requested)
            stale = {
                "scenarioId": SCENARIO_ID,
                "processInstanceId": PROCESS_ID,
                "checkpointName": "storeProbe.APP-01-final-probe",
                "phase": "probeCaptured",
                "redactedObservation": json.dumps({
                    "probeId": "probe-old",
                    "processInstanceId": PROCESS_ID,
                    "observation": {"kind": "Absent"},
                }),
            }
            with patch("integration.controller.capture_probe_status") as capture:
                with self.assertRaisesRegex(ValueError, "did not advance"):
                    bridge(stale)
            capture.assert_not_called()
            fresh = dict(stale)
            fresh["redactedObservation"] = json.dumps({
                "probeId": "probe-new",
                "processInstanceId": PROCESS_ID,
                "observation": {"kind": "Absent"},
            })
            with patch("integration.controller.capture_probe_status") as capture:
                bridge(fresh)
            capture.assert_called_once()

    def test_replay_progress_requires_debug_action_and_native_command_references(self):
        line = "NATIVE_CONTRACT_STATUS_V1 " + json.dumps({
            "scenarioId": "APP-06",
            "processInstanceId": "attempt-01/APP-06/p1",
            "checkpointName": "replayScheduled.5",
            "phase": "replayScheduled",
            "replayActionId": "19",
            "lastEnqueuedCommandId": "5",
        }, sort_keys=True)

        parsed = controller.parse_ios_status_line(
            line,
            expected_scenario_id="APP-06",
            expected_process_instance_id="attempt-01/APP-06/p1",
        )

        self.assertEqual(parsed["replayActionId"], "19")
        self.assertEqual(parsed["lastEnqueuedCommandId"], "5")


if __name__ == "__main__":
    unittest.main()
