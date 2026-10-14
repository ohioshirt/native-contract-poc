import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from integration.check import check_control_trace, check_trace
from integration import controller
from integration.tests._history_fixtures import make_app01_trace, make_app06_trace, make_ctrl_n3_trace


ROOT = Path(__file__).resolve().parents[2]


def _set_native_command_name(trace, command_id, name):
    """Represent what a native recorder actually emits, not the host action label."""
    process_id = trace["processInstances"][0]["processInstanceId"]
    ref = {"processInstanceId": process_id, "id": command_id}
    inventory = [row for row in trace["commandInventory"] if row["commandRef"] == ref]
    enqueue = [
        row for row in trace["events"]
        if row.get("kind") == "commandEnqueued" and row.get("commandRef") == ref
    ]
    if len(inventory) != 1 or len(enqueue) != 1:
        raise AssertionError(f"expected one command inventory/enqueue pair for {ref}")
    inventory[0]["name"] = name
    enqueue[0]["name"] = name


class NativeCommandAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "integration/contract.json").read_text())
        cls.scenarios = {
            row["id"]: row
            for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
        }
        cls.controls = {
            row["id"]: row
            for row in json.loads((ROOT / "integration/control-scenarios.json").read_text())["controls"]
        }

    def test_native_login_and_current_delivery_labels_bind_to_actual_seed_and_slot(self):
        trace, server, observations = make_app01_trace()
        _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")

        report = check_trace(self.contract, self.scenarios["APP-01"], trace, server, observations)

        self.assertEqual(report["classification"], "PASS")
        self.assertEqual(
            trace["commandInventory"][-1],
            {"commandRef": {"processInstanceId": "attempt-01/APP-01/p1", "id": 4}, "name": "Deliver(slot-A1,success)"},
        )
        self.assertEqual(
            next(event["slotId"] for event in trace["events"] if event["kind"] == "transportReceived"),
            "slot-A1",
        )

    def test_ctrl_n3_native_names_preserve_fault_receipt_and_i6_witness(self):
        control = self.controls["CTRL-N3-EARLY-PUBLISH"]
        trace, server, observations = make_ctrl_n3_trace()
        _set_native_command_name(trace, 2, "Login(A)")
        _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I6", {row["invariant"] for row in report["violations"]})
        delivery_ref = {"processInstanceId": trace["processInstances"][0]["processInstanceId"], "id": 4}
        fault = next(event for event in trace["events"] if event["kind"] == "storeFault")
        receipt = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"] == delivery_ref)
        self.assertEqual(fault["commandRef"], delivery_ref)
        self.assertEqual(receipt["commandRef"], delivery_ref)
        self.assertEqual(fault["fault"], "replaceBefore")
        self.assertEqual(receipt["status"], "FaultLocked")

    def test_current_alias_rejects_a_slot_outside_the_frozen_delivery(self):
        trace, server, observations = make_app01_trace()
        _set_native_command_name(trace, 4, "Deliver(slot-A2,success)")

        report = check_trace(self.contract, self.scenarios["APP-01"], trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_current_alias_rejects_an_outcome_that_disagrees_with_native_transport(self):
        trace, server, observations = make_app01_trace()
        _set_native_command_name(trace, 4, "Deliver(slot-A1,failure)")

        report = check_trace(self.contract, self.scenarios["APP-01"], trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_replay_alias_requires_debug_action_bound_to_source_and_new_command(self):
        trace, server, observations = make_app06_trace()
        _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")
        _set_native_command_name(trace, 5, "Deliver(slot-A1,success)")
        replay = next(event for event in trace["controllerEvents"] if event["kind"] == "replayRequested")
        process_id = trace["processInstances"][0]["processInstanceId"]
        replay.update({
            "actionId": 19,
            "commandRef": {"processInstanceId": process_id, "id": 5},
            "sourceCommandRef": {"processInstanceId": process_id, "id": 4},
        })

        report = check_trace(self.contract, self.scenarios["APP-06"], trace, server, observations)

        self.assertEqual(report["classification"], "PASS")
        self.assertNotEqual(replay["commandRef"], replay["sourceCommandRef"])
        self.assertEqual(replay["slotId"], "slot-A1")

    def test_replay_alias_without_debug_action_provenance_is_invalid(self):
        trace, server, observations = make_app06_trace()
        _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")
        _set_native_command_name(trace, 5, "Deliver(slot-A1,success)")
        trace["controllerEvents"] = [row for row in trace["controllerEvents"] if row["kind"] != "replayRequested"]

        report = check_trace(self.contract, self.scenarios["APP-06"], trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_replay_alias_rejects_a_different_slot_or_source_command(self):
        for changed in ("slot", "source"):
            with self.subTest(changed=changed):
                trace, server, observations = make_app06_trace()
                _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")
                _set_native_command_name(trace, 5, "Deliver(slot-A1,success)")
                replay = next(event for event in trace["controllerEvents"] if event["kind"] == "replayRequested")
                process_id = trace["processInstances"][0]["processInstanceId"]
                replay.update({
                    "actionId": 19,
                    "commandRef": {"processInstanceId": process_id, "id": 5},
                    "sourceCommandRef": {"processInstanceId": process_id, "id": 4},
                })
                if changed == "slot":
                    replay["slotId"] = "slot-A2"
                else:
                    replay["sourceCommandRef"] = {"processInstanceId": process_id, "id": 3}

                report = check_trace(self.contract, self.scenarios["APP-06"], trace, server, observations)

                self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_replay_status_producer_binds_ack_to_actual_enqueued_and_completed_commands(self):
        trace, _, _ = make_app06_trace()
        process_id = trace["processInstances"][0]["processInstanceId"]
        controller_events = []
        with tempfile.TemporaryDirectory() as temporary:
            bridge = controller.NativeProgressBridge(
                platform="ios",
                run=SimpleNamespace(),
                device="owned-simulator",
                attempt_id="attempt-01",
                scenario={"id": "APP-06", "requiredProbes": []},
                variant=None,
                controller_events=controller_events,
                observations=[],
                process_artifact_directory=Path(temporary),
            )
            with patch("integration.controller.read_live_native_events", return_value=trace["events"]):
                bridge._record_replay_status({
                    "processInstanceId": process_id,
                    "replayActionId": "19",
                    "lastEnqueuedCommandId": "5",
                })

        self.assertEqual(controller_events, [{
            "sequence": 1,
            "kind": "replayRequested",
            "processInstanceId": process_id,
            "slotId": "slot-A1",
            "actionId": 19,
            "commandRef": {"processInstanceId": process_id, "id": 5},
            "sourceCommandRef": {"processInstanceId": process_id, "id": 4},
        }])

    def test_ctrl_n3_inventory_matches_after_publish_ack_fail_before_replace_contract(self):
        control = self.controls["CTRL-N3-EARLY-PUBLISH"]
        fault = next(action for action in control["controlActions"] if action["action"] == "injectStoreFault")
        armed = next(action for action in control["controlActions"] if action["action"] == "arm")
        self.assertEqual(fault, {
            "action": "injectStoreFault",
            "command": "Deliver(current,success)",
            "fault": "replaceBefore",
        })
        self.assertEqual(armed, {
            "action": "arm",
            "point": "afterPublishAck",
            "target": "nextDelivery",
        })

    def test_ctrl_n3_witness_has_early_signed_in_ack_while_a0_is_still_physical(self):
        control = self.controls["CTRL-N3-EARLY-PUBLISH"]
        trace, server, observations = make_ctrl_n3_trace()
        _set_native_command_name(trace, 2, "Login(A)")
        _set_native_command_name(trace, 4, "Deliver(slot-A1,success)")
        process_id = trace["processInstances"][0]["processInstanceId"]
        preprobe = next(row for row in observations if row["stepId"] == "CTRL-N3-store-probe-a0")
        rendered = next(row for row in observations if row["stepId"] == "CTRL-N3-rendered-a1")
        early_ack = next(
            row for row in trace["events"]
            if row["kind"] == "uiPublishAck" and row["commandRef"]["id"] == 4 and row["view"]["phase"] == "SignedIn"
        )
        arrival = next(
            row for row in trace["events"]
            if row["kind"] == "hookEvent" and row["phase"] == "arrived" and row["point"] == "afterPublishAck"
        )
        released = next(
            row for row in trace["events"]
            if row["kind"] == "hookEvent" and row["phase"] == "released" and row["point"] == "afterPublishAck"
        )
        store_fault = next(row for row in trace["events"] if row["kind"] == "storeFault")
        self.assertEqual(preprobe["observation"], {"kind": "Present", "account": "A", "version": 0})
        self.assertEqual((rendered["phase"], rendered["account"]), ("SignedIn", "A"))
        self.assertEqual(early_ack["view"]["credentialVersion"], 1)
        self.assertLess(early_ack["localSequence"], arrival["localSequence"])
        self.assertLess(arrival["localSequence"], released["localSequence"])
        self.assertLess(released["localSequence"], store_fault["localSequence"])
        self.assertEqual(store_fault["fault"], "replaceBefore")
        self.assertFalse(store_fault["mutationApplied"])
        self.assertEqual(store_fault["commandRef"]["processInstanceId"], process_id)


if __name__ == "__main__":
    unittest.main()
