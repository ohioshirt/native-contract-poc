"""Process-end acknowledgement must identify the actual final native row."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from integration import controller
from integration.check import check_control_trace
from integration.tests._history_fixtures import make_app12_trace, make_ctrl_n4_trace


ROOT = Path(__file__).resolve().parents[2]


def _acknowledge_before_teardown(trace, *, local_sequence=None, process_id=None):
    process = trace["processInstances"][0]["processInstanceId"]
    trace["controllerEvents"] = [
        row for row in trace["controllerEvents"]
        if not (row.get("kind") == "processEndAcknowledged" and row.get("processInstanceId") == process)
    ]
    for sequence, row in enumerate(trace["controllerEvents"], start=1):
        row["sequence"] = sequence
    terminal = next(event for event in trace["events"] if event["kind"] == "processEnd")
    event_process = process if process_id is None else process_id
    reference = {
        "processInstanceId": event_process,
        "localSequence": terminal["localSequence"] if local_sequence is None else local_sequence,
    }
    old = trace["controllerEvents"]
    updated = []
    inserted = False
    for event in old:
        if not inserted and event["kind"] == "terminated":
            updated.append({
                "sequence": event["sequence"],
                "kind": "processEndAcknowledged",
                "processInstanceId": process,
                "eventRef": reference,
            })
            inserted = True
        row = dict(event)
        if inserted:
            row["sequence"] += 1
        updated.append(row)
    if not inserted:
        updated.append({
            "sequence": max((row["sequence"] for row in old), default=0) + 1,
            "kind": "processEndAcknowledged",
            "processInstanceId": process,
            "eventRef": reference,
        })
    trace["controllerEvents"] = updated
    return reference


class ProcessEndCheckerTests(unittest.TestCase):
    def setUp(self):
        self.controls = json.loads((ROOT / "integration/control-scenarios.json").read_text())["controls"]
        self.control = next(row for row in self.controls if row["id"] == "CTRL-N4-FALSE-LOGOUT")
        self.contract = json.loads((ROOT / "integration/contract.json").read_text())

    def result(self, trace):
        return check_control_trace(self.contract, self.control, trace, [], [
            {"kind": "storageProbe", "stepId": "CTRL-N4-FALSE-LOGOUT-independent-probe",
             "processInstanceId": trace["processInstances"][0]["processInstanceId"],
             "commandRef": trace["commandInventory"][-1]["commandRef"], "controllerSequence": 3,
             "observation": {"kind": "Absent"}},
        ])

    def test_missing_process_end_ack_is_inconclusive_before_n4_semantics(self):
        trace, _, _ = make_ctrl_n4_trace()
        trace["controllerEvents"] = [row for row in trace["controllerEvents"] if row["kind"] != "processEndAcknowledged"]
        for sequence, row in enumerate(trace["controllerEvents"], start=1):
            row["sequence"] = sequence

        report = self.result(trace)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertIn("process end acknowledgement is missing in launch 1", report["missingObservations"])
        self.assertEqual(report["violations"], [])

    def test_valid_process_end_ack_preserves_complete_n4_semantic_witness(self):
        trace, _, _ = make_ctrl_n4_trace()
        _acknowledge_before_teardown(trace)

        report = self.result(trace)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertEqual(report["missingObservations"], [])
        self.assertTrue({"I5", "I8"} <= {row["invariant"] for row in report["violations"]})

    def test_process_end_ack_must_reference_the_actual_terminal_row(self):
        trace, _, _ = make_ctrl_n4_trace()
        terminal = next(event for event in trace["events"] if event["kind"] == "processEnd")
        _acknowledge_before_teardown(trace, local_sequence=terminal["localSequence"] + 1)

        report = self.result(trace)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("processEnd" in row["actual"] for row in report["violations"]))

    def test_native_event_after_process_end_invalidates_history(self):
        trace, _, _ = make_ctrl_n4_trace()
        _acknowledge_before_teardown(trace)
        process_id = trace["processInstances"][0]["processInstanceId"]
        trace["events"].append({
            "processInstanceId": process_id,
            "launchOrdinal": 1,
            "localSequence": trace["events"][-1]["localSequence"] + 1,
            "kind": "hookEvent",
            "actionId": 19,
            "point": "afterManaged",
            "phase": "armed",
            "target": "nextCommand",
        })

        report = self.result(trace)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("after processEnd" in row["actual"] for row in report["violations"]))

    def test_duplicate_process_end_ack_is_invalid_history(self):
        trace, _, _ = make_ctrl_n4_trace()
        _acknowledge_before_teardown(trace)
        first = next(event for event in trace["controllerEvents"] if event["kind"] == "processEndAcknowledged")
        trace["controllerEvents"].append({**first, "sequence": max(row["sequence"] for row in trace["controllerEvents"]) + 1})

        report = self.result(trace)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_added_terminal_ack_keeps_restart_probe_controller_references_bound(self):
        trace, _, observations = make_app12_trace()

        for observation in observations:
            if observation.get("kind") != "storageProbe":
                continue
            matching = [
                event for event in trace["controllerEvents"]
                if event.get("kind") == "probeCaptured"
                and event.get("processInstanceId") == observation.get("processInstanceId")
                and event.get("stepId") == observation.get("stepId")
            ]
            if matching:
                self.assertEqual(observation.get("controllerSequence"), matching[0]["sequence"])


class ProcessEndControllerHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.trace, _, _ = make_ctrl_n4_trace()
        self.process_id = self.trace["processInstances"][0]["processInstanceId"]
        self.end_event = next(event for event in self.trace["events"] if event["kind"] == "processEnd")
        self.controller_events = []
        self.bridge = controller.NativeProgressBridge(
            platform="ios",
            run=SimpleNamespace(),
            device="OWNED-UUID",
            attempt_id="attempt-01",
            scenario={"id": "CTRL-N4-FALSE-LOGOUT"},
            variant=None,
            controller_events=self.controller_events,
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/process-end-bridge-test",
        )

    def status(self, *, process_id=None, local_sequence=None):
        ack = {
            "processInstanceId": self.process_id if process_id is None else process_id,
            "eventRef": {
                "processInstanceId": self.process_id if process_id is None else process_id,
                "localSequence": self.end_event["localSequence"] if local_sequence is None else local_sequence,
            },
        }
        return {
            "scenarioId": "CTRL-N4-FALSE-LOGOUT",
            "processInstanceId": self.process_id,
            "checkpointName": "processEndAcknowledged",
            "phase": "processEndAcknowledged",
            "processEndAckJSON": json.dumps(ack, sort_keys=True),
        }

    def test_controller_binds_ack_only_to_synced_terminal_event(self):
        with patch.object(
            self.bridge,
            "_read_native_events_until",
            side_effect=lambda _process_id, select, **_kwargs: select(self.trace["events"]),
        ):
            self.bridge(self.status())

        ack = next(event for event in self.controller_events if event["kind"] == "processEndAcknowledged")
        self.assertEqual(ack["eventRef"], {
            "processInstanceId": self.process_id,
            "localSequence": self.end_event["localSequence"],
        })

    def test_controller_rejects_ack_for_another_native_process_end(self):
        with patch.object(
            self.bridge,
            "_read_native_events_until",
            side_effect=lambda _process_id, select, **_kwargs: select(self.trace["events"]),
        ):
            with self.assertRaisesRegex(ValueError, "processEnd acknowledgement"):
                self.bridge(self.status(local_sequence=self.end_event["localSequence"] + 1))

    def test_controller_rejects_native_rows_after_terminal_end(self):
        events = [*self.trace["events"], {
            "processInstanceId": self.process_id,
            "launchOrdinal": 1,
            "localSequence": self.end_event["localSequence"] + 1,
            "kind": "hookEvent",
            "actionId": 20,
            "point": "afterManaged",
            "phase": "armed",
            "target": "nextCommand",
        }]
        with patch.object(
            self.bridge,
            "_read_native_events_until",
            side_effect=lambda _process_id, select, **_kwargs: select(events),
        ):
            with self.assertRaisesRegex(ValueError, "after processEnd"):
                self.bridge(self.status())

    def test_process_end_status_requires_exact_process_bound_reference(self):
        good = self.status()
        line = controller._IOS_STATUS_PREFIX + json.dumps(good, sort_keys=True)
        parsed = controller.parse_ios_status_line(
            line,
            expected_scenario_id="CTRL-N4-FALSE-LOGOUT",
            expected_process_instance_id=self.process_id,
        )
        self.assertEqual(parsed["phase"], "processEndAcknowledged")

        bad = self.status(process_id="attempt-01/CTRL-N4-FALSE-LOGOUT/p2")
        with self.assertRaisesRegex(ValueError, "processEnd acknowledgement"):
            controller.parse_ios_status_line(
                controller._IOS_STATUS_PREFIX + json.dumps(bad),
                expected_scenario_id="CTRL-N4-FALSE-LOGOUT",
                expected_process_instance_id=self.process_id,
            )


class HookSnapshotOrderTests(unittest.TestCase):
    def snapshot(self, hooks):
        return {
            "version": 1,
            "processInstanceId": "attempt-01/APP-11/p1",
            "launchOrdinal": 1,
            "controlRevision": 4,
            "lastActionId": 4,
            "lastActionStatus": "applied",
            "lastEnqueuedCommandRef": {"processInstanceId": "attempt-01/APP-11/p1", "id": 6},
            "lastProcessedCommandRef": {"processInstanceId": "attempt-01/APP-11/p1", "id": 6},
            "storeIoActive": False,
            "hooks": hooks,
            "lastProbe": None,
        }

    @staticmethod
    def hook(arm_sequence, point, phase="released"):
        return {
            "armSequence": arm_sequence,
            "point": point,
            "phase": phase,
            "target": "nextDelivery",
            "arrivalCommandRef": {"processInstanceId": "attempt-01/APP-11/p1", "id": 4},
        }

    def test_snapshot_retains_released_hooks_in_arm_sequence_order(self):
        value = self.snapshot([
            self.hook(1, "beforeStore"),
            self.hook(2, "beforePublish"),
        ])

        decoded = controller._decode_control_snapshot(
            json.dumps(value), expected_process_instance_id="attempt-01/APP-11/p1"
        )

        self.assertEqual([row["armSequence"] for row in decoded["hooks"]], [1, 2])
        self.assertEqual([row["phase"] for row in decoded["hooks"]], ["released", "released"])

class StableAuditRetryWindowTests(unittest.TestCase):
    def test_stable_audit_error_stops_at_fifteen_seconds_even_with_long_stage(self):
        now = [0.0]
        attempts = []

        def clock():
            return now[0]

        def sleep(_duration):
            now[0] += 5.0

        def malformed(**_kwargs):
            attempts.append(now[0])
            raise ValueError("native audit line is persistently malformed")

        bridge = controller.NativeProgressBridge(
            platform="ios",
            run=SimpleNamespace(),
            device="OWNED-UUID",
            attempt_id="attempt-01",
            scenario={"id": "APP-01"},
            variant=None,
            controller_events=[],
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/process-end-retry-test",
            deadline=100.0,
        )
        with patch("integration.controller.time.monotonic", side_effect=clock), patch(
            "integration.controller.time.sleep", side_effect=sleep
        ), patch("integration.controller.read_live_native_events", side_effect=malformed):
            with self.assertRaisesRegex(TimeoutError, "stable error window"):
                bridge._read_native_events_until(
                    "attempt-01/APP-01/p1", lambda events: events,
                    description="terminal process event",
                )

        self.assertLessEqual(now[0], 15.0)
        self.assertLessEqual(len(attempts), 4)


if __name__ == "__main__":
    unittest.main()
