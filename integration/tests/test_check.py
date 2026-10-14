import json
import tempfile
import unittest
from collections import defaultdict
from copy import deepcopy
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from integration import check as check_module
from integration import model as integration_model
from integration.check import _managed_ok, check_control_trace, check_trace
from integration.tests._history_fixtures import (
    make_app02_trace,
    make_app01_trace,
    make_app06_trace,
    make_app08_trace,
    make_app05_trace,
    make_app09_trace,
    make_app10_trace,
    make_app10_recover_old_trace,
    make_app11_trace,
    make_app13_trace,
    make_app12_trace,
    make_ctrl_n2_trace,
    make_ctrl_n3_trace,
    make_ctrl_n4_trace,
)
from integration.fixtures.unsafe_adapter import generate as generate_unsafe_adapter


INTEGRATION = Path(__file__).resolve().parents[1]


class IndependentCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((INTEGRATION / "contract.json").read_text())
        cls.scenario_rows = json.loads((INTEGRATION / "scenarios.json").read_text())["scenarios"]
        cls.scenarios = {row["id"]: row for row in cls.scenario_rows}

    def check(self, scenario_id, trace, server_events, observations):
        return check_trace(
            self.contract,
            self.scenarios[scenario_id],
            trace,
            server_events,
            observations,
        )

    def test_stale_success_is_semantic_red(self):
        trace, server, observations = make_app02_trace(unsafe_success=True)
        stale = next(event for event in trace["events"] if event["kind"] == "managedReduced" and event["event"]["event"] == "RefreshSucceeded")
        self.assertEqual(
            stale["result"],
            {
                "ownerId": "owner-1",
                "state": "Unauthenticated",
                "pendingRequestId": None,
                "nextRequestId": 2,
                "effects": [],
                "rejection": None,
            },
        )
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I2", {item["invariant"] for item in report["violations"]})
        self.assertIn("I3", {item["invariant"] for item in report["violations"]})

    def test_fault_variant_is_selected_before_shape_and_semantics(self):
        trace, server, observations = make_app09_trace("replace-before")
        deliver = next(
            event for event in trace["events"]
            if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 4
        )
        deliver["status"] = "Completed"
        deliver["observation"]["view"]["lastCommandStatus"] = "Completed"

        report = self.check("APP-09", trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertEqual(set(report), {"classification", "scenarioId", "violations", "missingObservations"})
        self.assertEqual(trace["variantId"], "replace-before")
        self.assertIn("I8", {row["invariant"] for row in report["violations"]})

    def test_variant_without_or_with_unknown_selector_is_invalid(self):
        trace, server, observations = make_app01_trace()
        trace["scenarioId"] = "APP-09"
        missing = self.check("APP-09", trace, server, observations)
        self.assertEqual(missing["classification"], "INVALID_HISTORY")

        trace["variantId"] = "not-frozen"
        unknown = self.check("APP-09", trace, server, observations)
        self.assertEqual(unknown["classification"], "INVALID_HISTORY")

    def test_control_n1_requires_and_reports_its_named_witness(self):
        controls = json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"]
        control = next(row for row in controls if row["id"] == "CTRL-N1-LOGOUT")
        trace, server, observations = make_app02_trace(unsafe_success=True)

        def rename(value):
            if isinstance(value, str):
                return value.replace("APP-02", control["id"])
            if isinstance(value, list):
                return [rename(item) for item in value]
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            return value

        trace, server, observations = rename(trace), rename(server), rename(observations)
        trace["scenarioId"] = control["id"]
        trace["controlId"] = control["id"]

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I2", "I3"} <= {row["invariant"] for row in report["violations"]})

    def test_control_without_its_mutation_witness_is_not_detected_not_infra(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N1-LOGOUT")
        trace, server, observations = make_app02_trace(unsafe_success=False)

        def rename(value):
            if isinstance(value, str):
                return value.replace("APP-02", control["id"])
            if isinstance(value, list):
                return [rename(item) for item in value]
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            return value

        trace, server, observations = rename(trace), rename(server), rename(observations)
        trace["scenarioId"] = control["id"]
        trace["controlId"] = control["id"]

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "NOT_DETECTED")
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["missingObservations"], [])

    def test_control_n1_new_login_requires_login_b_witness(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N1-NEW-LOGIN")
        with tempfile.TemporaryDirectory() as temporary:
            generate_unsafe_adapter(Path(temporary))
            directory=Path(temporary)/"APP-04"
            trace=json.loads((directory/"trace.json").read_text())
            server=json.loads((directory/"server-events.json").read_text())
            observations=json.loads((directory/"ui-observations.json").read_text())

        def rename(value):
            if isinstance(value,str): return value.replace("APP-04",control["id"])
            if isinstance(value,list): return [rename(item) for item in value]
            if isinstance(value,dict): return {key:rename(item) for key,item in value.items()}
            return value
        trace,server,observations=rename(trace),rename(server),rename(observations)
        trace["scenarioId"]=control["id"]
        trace["controlId"]=control["id"]

        report=check_control_trace(self.contract,control,trace,server,observations)

        self.assertEqual(report["classification"],"SEMANTIC_FAIL")
        self.assertTrue({"I2","I4"} <= {row["invariant"] for row in report["violations"]})

    def test_control_trace_identity_must_match_frozen_control(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N1-LOGOUT")
        trace, server, observations = make_app02_trace(unsafe_success=True)
        trace["scenarioId"] = control["id"]
        trace["controlId"] = "CTRL-N1-NEW-LOGIN"

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_store_fault_control_action_must_name_the_consuming_command(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N3-EARLY-PUBLISH")
        fault_action = next(action for action in control["controlActions"] if action["action"] == "injectStoreFault")
        fault_action["command"] = "Login(A0)"

        errors = check_module.control_inventory_errors(control)

        self.assertTrue(any("fault target command" in error for error in errors), errors)

    def test_store_fault_event_must_be_at_the_frozen_deliver_command(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N3-EARLY-PUBLISH")
        trace, server, observations = make_ctrl_n3_trace()
        fault_event = next(event for event in trace["events"] if event.get("kind") == "storeFault")
        login_ref = next(row["commandRef"] for row in trace["commandInventory"] if row["name"] == "Login(A)")
        fault_event["commandRef"] = login_ref

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("frozen target command" in row["actual"] for row in report["violations"]))

    def test_control_n2_detached_effect_has_independent_origin_provenance(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N2-LATE-CLEAR")
        trace, server, observations = make_ctrl_n2_trace()

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I4", {row["invariant"] for row in report["violations"]})
        effect = next(event for event in trace["events"] if event["kind"] == "detachedStoreMutation")
        self.assertEqual(effect["effectId"], "late-clear-1")
        self.assertEqual(effect["originCommandRef"], next(row["commandRef"] for row in trace["commandInventory"] if row["name"] == "Logout"))
        self.assertNotIn("slotId", effect)
        release = next(event for event in trace["controllerEvents"] if event["kind"] == "hookReleased" and event["point"] == "beforeDeferredControlClear")
        native_release = next(event for event in trace["events"] if event["kind"] == "hookEvent" and event["phase"] == "released" and event["point"] == release["point"])
        self.assertEqual(effect["releaseActionId"], native_release["actionId"])
        self.assertEqual(release["eventRef"], {"processInstanceId": native_release["processInstanceId"], "localSequence": native_release["localSequence"]})
        self.assertNotIn("releaseControllerSequence", effect)

    def test_control_n2_missing_declared_effect_is_inconclusive(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N2-LATE-CLEAR")
        trace, server, observations = make_ctrl_n2_trace(detached_clear=False)

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("late-clear-1" in item for item in report["missingObservations"]))

    def test_control_n2_requires_a_host_ack_after_matching_effect_readback(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N2-LATE-CLEAR")
        trace, server, observations = make_ctrl_n2_trace(effect_ack=False)

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("acknowledgement" in item and "late-clear-1" in item for item in report["missingObservations"]))

    def test_control_n2_effect_ack_must_reference_its_actual_readback(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N2-LATE-CLEAR")
        trace, server, observations = make_ctrl_n2_trace(bad_effect_ack=True)

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("detachedEffectAwaited" in row["actual"] for row in report["violations"]))

    def test_control_n4_false_logout_uses_failed_readback_and_physical_probe(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N4-FALSE-LOGOUT")
        trace, server, observations = make_ctrl_n4_trace()

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I5", "I8"} <= {row["invariant"] for row in report["violations"]})
        self.assertFalse(any(row["name"] == "RetryCleanup" for row in trace["commandInventory"]))
        self.assertFalse(any(event["kind"] == "storeReadback" and event["commandRef"]["id"] == 3 for event in trace["events"]))
        self.assertEqual(observations[0]["observation"], {"kind": "Absent"})

    def test_control_n3_catches_render_before_verified_store(self):
        control = next(row for row in json.loads((INTEGRATION / "control-scenarios.json").read_text())["controls"] if row["id"] == "CTRL-N3-EARLY-PUBLISH")
        trace, server, observations = make_ctrl_n3_trace()

        report = check_control_trace(self.contract, control, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I6", {row["invariant"] for row in report["violations"]})

    def test_all_app13_variants_bind_transport_failure_codes_and_final_state(self):
        scenario = self.scenarios["APP-13"]
        for variant in scenario["variants"]:
            with self.subTest(variant=variant["id"]):
                trace, server, observations = make_app13_trace(variant["id"])
                report = check_trace(self.contract, scenario, trace, server, observations)
                self.assertEqual(report["classification"], "PASS")

        trace, server, observations = make_app13_trace("http500-current")
        received = next(event for event in trace["events"] if event["kind"] == "transportReceived")
        received["failureCode"] = "malformed"
        mismatch = check_trace(self.contract, scenario, trace, server, observations)
        self.assertEqual(mismatch["classification"], "SEMANTIC_FAIL")
        self.assertIn("I8", {item["invariant"] for item in mismatch["violations"]})

        trace, server, observations = make_app13_trace("http500-current")
        received = next(event for event in trace["events"] if event["kind"] == "transportReceived")
        received.pop("failureCode")
        malformed = check_trace(self.contract, scenario, trace, server, observations)
        self.assertEqual(malformed["classification"], "INVALID_HISTORY")

    def test_all_app09_variants_require_fault_receipt_and_store_expectation(self):
        scenario = self.scenarios["APP-09"]
        for variant in scenario["variants"]:
            with self.subTest(variant=variant["id"]):
                trace, server, observations = make_app09_trace(variant["id"])
                report = check_trace(self.contract, scenario, trace, server, observations)
                self.assertEqual(report["classification"], "PASS")

        trace, server, observations = make_app09_trace("replace-before")
        deliver = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 4)
        deliver["status"] = "Completed"
        deliver["observation"]["view"]["lastCommandStatus"] = "Completed"
        report = check_trace(self.contract, scenario, trace, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I8", {item["invariant"] for item in report["violations"]})

        wrong_fault_readback = deepcopy(scenario)
        selected = next(row for row in wrong_fault_readback["variants"] if row["id"] == "replace-before")
        selected["faultObservation"] = {"kind": "Absent"}
        trace, server, observations = make_app09_trace("replace-before")
        mismatch = check_trace(self.contract, wrong_fault_readback, trace, server, observations)
        self.assertEqual(mismatch["classification"], "SEMANTIC_FAIL")
        self.assertIn("I8", {item["invariant"] for item in mismatch["violations"]})

    def test_all_app10_variants_verify_pre_retry_fault_and_recovery(self):
        scenario = self.scenarios["APP-10"]
        for variant in scenario["variants"]:
            with self.subTest(variant=variant["id"]):
                trace, server, observations = make_app10_trace(variant["id"])
                report = check_trace(self.contract, scenario, trace, server, observations)
                self.assertEqual(report["classification"], "PASS")

        trace, server, observations = make_app10_trace("clear-before")
        logout = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 3)
        logout["status"] = "Completed"
        report = check_trace(self.contract, scenario, trace, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I8", {item["invariant"] for item in report["violations"]})

    def test_app10_clear_after_separates_receipt_unknown_from_independent_absence(self):
        trace, server, observations = make_app10_trace("clear-after-before-verify")
        logout = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 3)
        probe = next(item for item in observations if item["stepId"] == "APP-10-after-failed-logout")

        self.assertEqual(logout["observation"]["store"], {"kind": "Unknown", "errorCode": "readFailed"})
        self.assertEqual(probe["observation"], {"kind": "Absent"})
        self.assertEqual(self.check("APP-10", trace, server, observations)["classification"], "PASS")

    def test_app09_and_app10_require_the_declared_store_fault_event(self):
        cases = [
            ("APP-09", "replace-before", make_app09_trace("replace-before")),
            ("APP-10", "clear-before", make_app10_trace("clear-before")),
        ]
        for scenario_id, variant_id, (trace, server, observations) in cases:
            with self.subTest(scenario=scenario_id, variant=variant_id):
                removed = next(event for event in trace["events"] if event["kind"] == "storeFault")
                process_id, removed_sequence = removed["processInstanceId"], removed["localSequence"]
                trace["events"].remove(removed)

                def compact_event_refs(value):
                    if isinstance(value, dict):
                        if value.get("processInstanceId") == process_id and type(value.get("localSequence")) is int and value["localSequence"] > removed_sequence:
                            value["localSequence"] -= 1
                        for child in value.values():
                            compact_event_refs(child)
                    elif isinstance(value, list):
                        for child in value:
                            compact_event_refs(child)

                compact_event_refs(trace)
                compact_event_refs(observations)
                report = self.check(scenario_id, trace, server, observations)
                self.assertEqual(report["classification"], "INCONCLUSIVE")
                self.assertTrue(any("required store fault" in item for item in report["missingObservations"]))

    def test_app10_recover_old_uses_foreign_owner_noop_then_login_b(self):
        scenario = self.scenarios["APP-10-RECOVER-OLD"]
        trace, server, observations = make_app10_recover_old_trace()

        report = self.check("APP-10-RECOVER-OLD", trace, server, observations)

        self.assertEqual(report["classification"], "PASS")
        self.assertTrue(any(row["name"] == "Logout" for row in trace["commandInventory"]))
        delivery = next(event for event in trace["events"] if event["kind"] == "managedReduced" and event.get("slotId") == "slot-A1")
        self.assertEqual(delivery["pre"]["ownerId"], "owner-2")
        self.assertEqual(delivery["requestOwnerId"], "owner-1")
        self.assertEqual(delivery["result"]["rejection"], "ForeignRequest")

        unsafe, server, observations = make_app10_recover_old_trace(unsafe_owner_ignored=True)
        unsafe_report = self.check("APP-10-RECOVER-OLD", unsafe, server, observations)
        self.assertEqual(unsafe_report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I2", "I4"} <= {row["invariant"] for row in unsafe_report["violations"]})

        missing_owner, server, observations = make_app10_recover_old_trace()
        old_delivery = next(event for event in missing_owner["events"] if event["kind"] == "managedReduced" and event.get("slotId") == "slot-A1")
        old_delivery.pop("requestOwnerId")
        self.assertEqual(self.check("APP-10-RECOVER-OLD", missing_owner, server, observations)["classification"], "INVALID_HISTORY")

    def test_base_scenario_fault_requires_a_frozen_store_fault_event(self):
        scenario = self.scenarios["APP-10-RECOVER-OLD"]
        trace, _, _ = make_app10_recover_old_trace()

        resolved, _, error = check_module._resolve_scenario_variant(scenario, trace)

        self.assertIsNone(error)
        self.assertEqual(resolved["requiredStoreFault"], {
            "command": "Logout(failed)",
            "operation": "clear",
            "fault": "clearBefore",
            "mutationApplied": False,
            "verification": "notAttempted",
        })

    def test_scenario_inventory_requires_cancel_mode_and_rejects_unknown_fields(self):
        scenario = deepcopy(self.scenarios["APP-01"])
        scenario.pop("cancelMode")

        missing_mode = check_module._scenario_inventory_errors(scenario)
        self.assertTrue(any("cancelMode" in error for error in missing_mode))

        scenario["cancelMode"] = "disabled"
        self.assertFalse(check_module._scenario_inventory_errors(scenario))

        scenario["cancellOnLogout"] = False
        errors = check_module._scenario_inventory_errors(scenario)
        self.assertTrue(any("unknown scenario inventory field" in error for error in errors))

    def test_app07_issuance_and_server_request_counts_are_frozen_together(self):
        scenario = deepcopy(self.scenarios["APP-07"])
        self.assertFalse(check_module._scenario_inventory_errors(scenario))

        scenario["requiredServerRequestCount"] = 1
        errors = check_module._scenario_inventory_errors(scenario)
        self.assertTrue(any("requiredServerRequestCount" in error for error in errors))

    def test_cancel_refresh_ignores_late_delivery_after_verified_cleanup(self):
        good, server, observations = make_app08_trace()
        report = self.check("APP-08", good, server, observations)
        self.assertEqual(report["classification"], "PASS")

        unexpected_cancel = deepcopy(good)
        received = next(event for event in unexpected_cancel["events"] if event["kind"] == "transportReceived")
        received["outcome"] = "failure"
        received["failureCode"] = "disconnected"
        report = self.check("APP-08", unexpected_cancel, server, observations)
        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("required transport response" in item for item in report["missingObservations"]))

        bad, server, observations = make_app08_trace(unsafe_success=True)
        report = self.check("APP-08", bad, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I2", "I3"} & {item["invariant"] for item in report["violations"]})

    def test_app11_pause_variants_prove_fifo_queue_and_release_channel(self):
        scenario = self.scenarios["APP-11"]
        for variant in scenario["variants"]:
            with self.subTest(variant=variant["id"]):
                trace, server, observations = make_app11_trace(variant["id"])
                report = check_trace(self.contract, scenario, trace, server, observations)
                self.assertEqual(report["classification"], "PASS")

        trace, server, observations = make_app11_trace("store-pause", reverse_queued_order=True)
        report = check_trace(self.contract, scenario, trace, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I1", {item["invariant"] for item in report["violations"]})

    def test_general_native_start_order_must_follow_enqueue_order(self):
        scenario = self.scenarios["APP-11"]
        trace, server, observations = make_app11_trace("store-pause")
        names = {
            (row["commandRef"]["processInstanceId"], row["commandRef"]["id"]): row["name"]
            for row in trace["commandInventory"]
        }
        enqueues = [
            event for event in trace["events"]
            if event["kind"] == "commandEnqueued"
            and names[(event["commandRef"]["processInstanceId"], event["commandRef"]["id"])] in {"Logout", "Login(B)"}
        ]
        self.assertEqual(len(enqueues), 2)
        enqueues[0]["localSequence"], enqueues[1]["localSequence"] = enqueues[1]["localSequence"], enqueues[0]["localSequence"]

        resolved, _, error = check_module._resolve_scenario_variant(scenario, trace)
        self.assertIsNone(error)
        structural = check_module._shape_errors(self.contract, resolved, trace, server, observations)

        self.assertTrue(any(error.startswith("command start order violates FIFO enqueue order") for error in structural))

    def test_complete_unsafe_adapter_records_real_stale_noop_then_mutates(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generate_unsafe_adapter(output)
            directory = output / "APP-02"
            trace = json.loads((directory / "trace.json").read_text())
            server = json.loads((directory / "server-events.json").read_text())
            observations = json.loads((directory / "ui-observations.json").read_text())
            manifest = json.loads((output / "fixture.json").read_text())

        self.assertEqual(manifest["evidenceKind"], "evaluator-fixture")
        stale = next(
            event for event in trace["events"]
            if event["kind"] == "managedReduced" and event["commandRef"]["id"] == 5
        )
        self.assertEqual(stale["pre"], {key: stale["result"][key] for key in ("ownerId", "state", "pendingRequestId", "nextRequestId")})
        self.assertEqual(stale["result"]["state"], "Unauthenticated")
        self.assertEqual(stale["result"]["pendingRequestId"], None)
        self.assertEqual(stale["result"]["nextRequestId"], 2)
        self.assertEqual(stale["result"]["effects"], [])
        self.assertIsNone(stale["result"]["rejection"])

        report = self.check("APP-02", trace, server, observations)
        self.assertEqual(set(report), {"classification", "scenarioId", "violations", "missingObservations"})
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I2", "I3"} <= {item["invariant"] for item in report["violations"]})
        for violation in report["violations"]:
            self.assertGreater(violation["commandRef"]["id"], 0)
            self.assertGreater(violation["eventRef"]["localSequence"], 0)

    def test_complete_unsafe_adapter_preserves_managed_login_b_but_overwrites_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generate_unsafe_adapter(output)
            directory = output / "APP-04"
            trace = json.loads((directory / "trace.json").read_text())
            server = json.loads((directory / "server-events.json").read_text())
            observations = json.loads((directory / "ui-observations.json").read_text())

        stale = next(
            event for event in trace["events"]
            if event["kind"] == "managedReduced" and event["commandRef"]["id"] == 6
        )
        expected_managed = {"ownerId": "owner-1", "state": "Authenticated", "pendingRequestId": None, "nextRequestId": 2}
        self.assertEqual(stale["pre"], expected_managed)
        self.assertEqual(
            stale["result"],
            {**expected_managed, "effects": [], "rejection": None},
        )

        report = self.check("APP-04", trace, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        invariants = {item["invariant"] for item in report["violations"]}
        self.assertTrue({"I2", "I4"} <= invariants)
        self.assertNotIn("I3", invariants)
        for violation in report["violations"]:
            self.assertGreater(violation["commandRef"]["id"], 0)
            self.assertGreater(violation["eventRef"]["localSequence"], 0)

    def test_late_failure_preserves_new_login(self):
        good, server, observations = make_app05_trace()
        self.assertEqual(self.check("APP-05", good, server, observations)["classification"], "PASS")

        bad, server, observations = make_app05_trace(unsafe_clear_b=True)
        report = self.check("APP-05", bad, server, observations)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I4", {item["invariant"] for item in report["violations"]})

    def test_missing_delivery_not_pass(self):
        trace, server, observations = make_app02_trace(missing_delivery=True)
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(report["missingObservations"])

    def test_wrong_run_or_duplicate_command_invalid(self):
        trace, server, observations = make_app02_trace()
        server[0]["runId"] = "different-run"
        wrong_run = self.check("APP-02", trace, server, observations)
        self.assertEqual(wrong_run["classification"], "INVALID_HISTORY")

        trace, server, observations = make_app02_trace()
        duplicate = dict(trace["commandInventory"][0])
        trace["commandInventory"].append(duplicate)
        duplicate_ref = self.check("APP-02", trace, server, observations)
        self.assertEqual(duplicate_ref["classification"], "INVALID_HISTORY")

    def test_response_release_requires_logout_receipt_and_independent_probe(self):
        trace, server, observations = make_app02_trace()
        release = next(event for event in trace["controllerEvents"] if event["kind"] == "releaseRequested")
        receipt = next(event for event in trace["controllerEvents"] if event["kind"] == "receiptObserved")
        probe = next(event for event in trace["controllerEvents"] if event.get("stepId") == "APP-02-after-logout-store")
        release["sequence"] = 3
        receipt["sequence"] = 4
        probe["sequence"] = 5
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_ui_ack_is_not_render_observation(self):
        trace, server, observations = make_app02_trace()
        observations[:] = [row for row in observations if row["kind"] != "renderedView"]
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("render" in item.lower() for item in report["missingObservations"]))

    def test_unknown_storage_is_not_absent(self):
        trace, server, observations = make_app02_trace()
        probe = next(row for row in observations if row["kind"] == "storageProbe" and row["commandRef"]["id"] == 4)
        probe["observation"] = {"kind": "Unknown", "errorCode": "readFailed"}
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("storage" in item.lower() for item in report["missingObservations"]))

    def test_out_of_order_publication_rejected(self):
        trace, server, observations = make_app02_trace()
        receipt = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 5)
        old_publication = next(event for event in trace["events"] if event["kind"] == "uiPublishAck" and event["commandRef"]["id"] == 3)
        old_publication["localSequence"] = receipt["localSequence"] + 1
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_ignored_delivery_metadata_changes_without_auth_projection_change(self):
        trace, server, observations = make_app02_trace()
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "PASS")
        logout = next(event for event in trace["events"] if event["kind"] == "uiPublishAck" and event["commandRef"]["id"] == 4 and event["view"]["phase"] == "SignedOut")
        ignored = next(event for event in trace["events"] if event["kind"] == "uiPublishAck" and event["commandRef"]["id"] == 5)
        self.assertGreater(ignored["revision"], logout["revision"])
        self.assertEqual(ignored["view"]["phase"], logout["view"]["phase"])
        self.assertEqual(ignored["view"]["account"], logout["view"]["account"])

    def test_process_restart_allows_local_id_reset_with_new_namespace(self):
        trace, server, observations = make_app12_trace(reuse_process_id=False)
        report = self.check("APP-12-SAVED", trace, server, observations)

        self.assertEqual(report["classification"], "PASS")

    def test_app12_bootstrap_release_uses_native_action_id_not_host_sequence(self):
        trace, server, observations = make_app12_trace()
        report = self.check("APP-12-SAVED", trace, server, observations)

        mutation = next(event for event in trace["events"] if event.get("kind") == "storeMutation" and event.get("cause") == "Bootstrap" and event.get("processInstanceId", "").endswith("/p2"))
        release = next(event for event in trace["controllerEvents"] if event.get("kind") == "hookReleased" and event.get("point") == "beforeBootstrapClear")
        native_release = next(event for event in trace["events"] if event.get("kind") == "hookEvent" and event.get("phase") == "released" and event.get("processInstanceId") == release["processInstanceId"])
        self.assertEqual(report["classification"], "PASS")
        self.assertEqual(release["eventRef"], {"processInstanceId": native_release["processInstanceId"], "localSequence": native_release["localSequence"]})
        self.assertEqual(mutation["releaseActionId"], native_release["actionId"])
        self.assertNotIn("releaseControllerSequence", mutation)
        self.assertNotEqual(mutation["releaseActionId"], release["sequence"])

    def test_app12_bootstrap_release_action_id_must_bind_to_real_native_release(self):
        trace, server, observations = make_app12_trace()
        mutation = next(event for event in trace["events"] if event.get("kind") == "storeMutation" and event.get("cause") == "Bootstrap" and event.get("processInstanceId", "").endswith("/p2"))
        mutation["releaseActionId"] = 999

        report = self.check("APP-12-SAVED", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("released hook" in row["actual"] for row in report["violations"]))

    def test_app12_bootstrap_receipt_before_hook_release_is_semantic_i9(self):
        scenario = self.scenarios["APP-12-SAVED"]
        trace, server, observations = make_app12_trace()
        process_id = next(row["processInstanceId"] for row in trace["processInstances"] if row["launchOrdinal"] == 2)
        bootstrap_ref = next(
            row["commandRef"] for row in trace["commandInventory"]
            if row["commandRef"]["processInstanceId"] == process_id and row["name"] == "Bootstrap"
        )
        receipt = next(
            row for row in trace["controllerEvents"]
            if row["kind"] == "receiptObserved" and row["commandRef"] == bootstrap_ref
        )
        release = next(
            row for row in trace["controllerEvents"]
            if row["kind"] == "hookReleased" and row["point"] == "beforeBootstrapClear"
        )
        trace["controllerEvents"].remove(receipt)
        trace["controllerEvents"].insert(trace["controllerEvents"].index(release), receipt)
        for sequence, event in enumerate(trace["controllerEvents"], start=1):
            event["sequence"] = sequence
        report = check_trace(self.contract, scenario, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL", report)
        self.assertIn("I9", {row["invariant"] for row in report["violations"]})

    def test_reused_process_instance_invalid(self):
        trace, server, observations = make_app12_trace(reuse_process_id=True)
        report = self.check("APP-12-SAVED", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_every_restart_requires_bootstrap_clear_and_readback(self):
        trace, server, observations = make_app12_trace(reuse_process_id=False)
        second = trace["processInstances"][1]["processInstanceId"]
        bootstrap = next(row["commandRef"] for row in trace["commandInventory"] if row["commandRef"]["processInstanceId"] == second)
        trace["events"] = [
            event for event in trace["events"]
            if not (
                event.get("processInstanceId") == second
                and event.get("commandRef") == bootstrap
                and event.get("kind") in {"storeMutation", "storeReadback"}
            )
        ]
        surviving = defaultdict(int)
        remap = {}
        for event in trace["events"]:
            pid, old = event["processInstanceId"], event["localSequence"]
            surviving[pid] += 1
            remap[(pid, old)] = surviving[pid]
        def renumber(value):
            if isinstance(value, list):
                return [renumber(item) for item in value]
            if isinstance(value, dict):
                if set(value) == {"processInstanceId", "localSequence"}:
                    return {"processInstanceId": value["processInstanceId"], "localSequence": remap[(value["processInstanceId"], value["localSequence"])]}
                copied = {key: renumber(item) for key, item in value.items()}
                if {"processInstanceId", "localSequence"} <= set(copied) and isinstance(copied.get("kind"), str):
                    copied["localSequence"] = remap[(copied["processInstanceId"], copied["localSequence"])]
                return copied
            return value
        trace["events"] = renumber(trace["events"])
        trace["controllerEvents"] = renumber(trace["controllerEvents"])
        observations = renumber(observations)

        report = self.check("APP-12-SAVED", trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertTrue(any("Bootstrap" in missing and "readback" in missing for missing in report["missingObservations"]))

    def test_event_array_must_follow_native_sequence(self):
        trace, server, observations = make_app01_trace()
        trace["events"][2], trace["events"][3] = trace["events"][3], trace["events"][2]

        report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("serialized" in violation["actual"] for violation in report["violations"]))

    def test_ui_ack_after_its_command_receipt_is_rejected(self):
        trace, server, observations = make_app01_trace()
        process = trace["processInstances"][0]
        deliver_ref = next(row["commandRef"] for row in trace["commandInventory"] if row["name"] == "Deliver(slot-A1,success)")
        end = next(event for event in trace["events"] if event["kind"] == "processEnd")
        extra = {
            "processInstanceId": process["processInstanceId"],
            "launchOrdinal": 1,
            "localSequence": end["localSequence"],
            "kind": "uiPublishAck",
            "commandRef": deliver_ref,
            "revision": 5,
            "view": {"phase":"SignedIn","account":"A","credentialVersion":1,"pendingRequestId":None,"lastCompletedCommandId":4,"lastCommandStatus":"Completed"},
        }
        end["localSequence"] += 1
        trace["events"].insert(-1, extra)

        report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("outside its active command" in row["actual"] for row in report["violations"]))

    def test_ui_ack_for_older_open_command_is_rejected_during_reentrant_start(self):
        trace, server, observations = make_app01_trace()
        events = trace["events"]
        enqueue_two = next(event for event in events if event["kind"] == "commandEnqueued" and event["commandRef"]["id"] == 2)
        start_two = next(event for event in events if event["kind"] == "commandStarted" and event["commandRef"]["id"] == 2)
        ack_one = next(event for event in events if event["kind"] == "uiPublishAck" and event["commandRef"]["id"] == 1)
        events.remove(enqueue_two)
        events.remove(start_two)
        ack_position = events.index(ack_one)
        events[ack_position:ack_position] = [enqueue_two, start_two]

        remap = {}
        for sequence, event in enumerate(events, start=1):
            remap[event["localSequence"]] = sequence
        for event in events:
            event["localSequence"] = remap[event["localSequence"]]
        for collection in (events, trace["controllerEvents"], observations):
            for item in collection:
                for value in _walk_dicts(item):
                    if set(value) == {"processInstanceId", "localSequence"}:
                        value["localSequence"] = remap[value["localSequence"]]

        report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("currently executing command" in row["actual"] for row in report["violations"]))

    def test_restart_exports_do_not_overwrite(self):
        trace, server, observations = make_app12_trace(reuse_process_id=False)
        trace["artifactPaths"][1] = trace["artifactPaths"][0]
        report = self.check("APP-12-SAVED", trace, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_incomplete_mutant_never_semantic_fail(self):
        trace, server, observations = make_app02_trace(unsafe_success=True)
        observations[:] = [row for row in observations if row.get("stepId") != "APP-02-final-probe"]
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertEqual(report["violations"], [])

    def test_current_refresh_commit_follows_managed_acceptance(self):
        trace, server, observations = make_app01_trace()
        report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "PASS")

    def test_valid_duplicate_replay_does_not_count_as_second_commit(self):
        trace, server, observations = make_app06_trace()
        report = self.check("APP-06", trace, server, observations)

        self.assertEqual(report["classification"], "PASS")

        duplicate_response = deepcopy(server)
        response = next(event for event in duplicate_response if event["kind"] == "responseWritten")
        duplicate_response.append({**response, "sequence": max(event["sequence"] for event in duplicate_response) + 1})
        report = self.check("APP-06", trace, duplicate_response, observations)
        self.assertEqual(report["classification"], "INVALID_HISTORY")
        self.assertTrue(any("server response count" in row["actual"] for row in report["violations"]))

    def test_reentrant_consumer_cannot_start_before_prior_receipt(self):
        trace, server, observations = make_app01_trace()
        events = trace["events"]
        enqueue = next(event for event in events if event["kind"] == "commandEnqueued" and event["commandRef"]["id"] == 2)
        start = next(event for event in events if event["kind"] == "commandStarted" and event["commandRef"]["id"] == 2)
        events.remove(enqueue)
        events.remove(start)
        receipt = next(i for i, event in enumerate(events) if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 1)
        events[receipt:receipt] = [enqueue, start]
        old_to_new = {}
        for index, event in enumerate(events, start=1):
            old_to_new[event["localSequence"]] = index
        for event in events:
            event["localSequence"] = old_to_new[event["localSequence"]]
        for collection in (events, trace["controllerEvents"], observations):
            for item in collection:
                for value in _walk_dicts(item):
                    if set(value) == {"processInstanceId", "localSequence"}:
                        value["localSequence"] = old_to_new[value["localSequence"]]
        report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertIn("I1", {item["invariant"] for item in report["violations"]})

    def test_managed_snapshots_chain_to_prior_receipt(self):
        trace, server, observations = make_app01_trace()
        mutated = deepcopy(trace)
        login = next(event for event in mutated["events"] if event["kind"] == "managedReduced" and event["commandRef"]["id"] == 2)
        login["pre"] = {"ownerId": "owner-1", "state": "Authenticated", "pendingRequestId": None, "nextRequestId": 1}
        login["result"] = {
            "ownerId": "owner-1",
            "state": "Authenticated",
            "pendingRequestId": None,
            "nextRequestId": 1,
            "effects": [{"effect": "ClearCredentials"}],
            "rejection": None,
        }
        report = self.check("APP-01", mutated, server, observations)

        self.assertEqual(report["classification"], "INVALID_HISTORY")

    def test_completed_logout_cannot_claim_unknown_store_is_absent(self):
        trace, server, observations = make_app02_trace()
        logout_write = next(event for event in trace["events"] if event["kind"] == "storeMutation" and event["cause"] == "Logout")
        logout_read = next(event for event in trace["events"] if event["kind"] == "storeReadback" and event["commandRef"]["id"] == 4)
        logout_receipt = next(event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 4)
        unknown = {"kind": "Unknown", "errorCode": "readFailed"}
        logout_write["after"] = unknown
        logout_read["observation"] = unknown
        logout_receipt["observation"]["store"] = unknown
        later_receipts = [event for event in trace["events"] if event["kind"] == "commandReceipt" and event["commandRef"]["id"] > 4]
        for receipt in later_receipts:
            receipt["observation"]["store"] = unknown
        report = self.check("APP-02", trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertTrue({"I5", "I8"} <= {item["invariant"] for item in report["violations"]})

    def test_required_observation_mismatch_invariants_are_explicit_inventory(self):
        trace, server, observations = make_app02_trace()
        for key in ("probeExpectationInvariants", "renderExpectationInvariants"):
            with self.subTest(key=key):
                scenario = deepcopy(self.scenarios["APP-02"])
                scenario[key].pop(next(iter(scenario[key])))

                report = check_trace(self.contract, scenario, trace, server, observations)

                self.assertEqual(report["classification"], "INVALID_HISTORY")
                self.assertTrue(any("declare one frozen mismatch invariant" in row["actual"] for row in report["violations"]))

    def test_missing_managed_oracle_is_infrastructure_failure(self):
        trace, server, observations = make_app01_trace()
        with tempfile.TemporaryDirectory(prefix="missing-managed-oracle-") as directory:
            with patch("integration.check.ROOT", Path(directory)):
                report = self.check("APP-01", trace, server, observations)

        self.assertEqual(report["classification"], "INFRA_FAILURE")
        self.assertEqual(report["violations"], [])
        self.assertTrue(any("managed oracle cannot be loaded" in item for item in report["missingObservations"]))

    def test_foreign_request_rejection_is_a_valid_managed_result_shape(self):
        snapshot = {
            "ownerId": "owner-2",
            "state": "Authenticated",
            "pendingRequestId": None,
            "nextRequestId": 2,
            "effects": [],
            "rejection": "ForeignRequest",
        }
        self.assertTrue(_managed_ok(snapshot, result=True))


class HistorySchemaContractTests(unittest.TestCase):
    def test_schema_closes_and_matches_every_native_and_controller_event(self):
        schema = json.loads((INTEGRATION / "history.schema.json").read_text())

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]) - set(schema["required"]), check_module.TOP_OPTIONAL_KEYS)
        for selector in check_module.TOP_OPTIONAL_KEYS:
            self.assertEqual(schema["properties"][selector], {"type": "string", "minLength": 1})
        self.assertEqual(schema["properties"]["buildHash"]["pattern"], r"^sha256:[0-9a-f]{64}$")

        for definition, contracts in (
            ("nativeEvent", check_module.EVENT_FIELDS),
            ("controllerEvent", check_module.CONTROLLER_FIELDS),
        ):
            branches = schema["$defs"][definition]["oneOf"]
            actual = {}
            for branch in branches:
                self.assertFalse(branch["additionalProperties"])
                kind = branch["properties"]["kind"]["const"]
                actual[kind] = (set(branch["required"]), set(branch["properties"]))
            expected = {kind: (set(required), set(allowed)) for kind, (required, allowed) in contracts.items()}
            self.assertEqual(actual, expected)
        self.assertIn("uiPublishAck", check_module.EVENT_FIELDS)

    def test_schema_observation_values_match_their_native_event_semantics(self):
        schema = json.loads((INTEGRATION / "history.schema.json").read_text())
        branches = {
            branch["properties"]["kind"]["const"]: branch
            for branch in schema["$defs"]["nativeEvent"]["oneOf"]
        }

        reset = branches["managedInstanceReset"]["properties"]
        self.assertEqual(reset["before"], {"$ref": "#/$defs/managedSnapshot"})
        self.assertEqual(reset["after"], {"$ref": "#/$defs/managedSnapshot"})
        self.assertEqual(
            branches["commandReceipt"]["properties"]["observation"],
            {"$ref": "#/$defs/receiptObservation"},
        )
        for kind in ("storeReadback", "storeFault", "detachedStoreReadback"):
            self.assertEqual(
                branches[kind]["properties"]["observation"],
                {"$ref": "#/$defs/storeObservation"},
            )
        self.assertEqual(
            set(branches["storeFault"]["properties"]["verification"]["enum"]),
            {"failed", "notAttempted"},
        )

    def test_contract_and_bounded_model_use_the_same_owner_bound(self):
        contract = json.loads((INTEGRATION / "contract.json").read_text())
        self.assertEqual(contract["bounds"], integration_model.BOUNDS)

    def test_schema_has_no_open_controller_or_native_event_objects(self):
        schema = json.loads((INTEGRATION / "history.schema.json").read_text())
        for name in ("nativeEvent", "controllerEvent"):
            for branch in schema["$defs"][name]["oneOf"]:
                self.assertFalse(branch["additionalProperties"])


if __name__ == "__main__":
    unittest.main()


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)
