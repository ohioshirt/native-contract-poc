"""Regression tests for live native history and independent probe attribution."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from integration.check import check_trace
from integration import controller
from integration.tests._history_fixtures import make_app02_trace, make_app06_trace, make_app12_trace


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


class NativeAuditRetryTests(unittest.TestCase):
    def _ios_audit_after_container_timeout(self, *, always_hangs=False):
        process_id = 'attempt-01/APP-02/p1'
        clock = [0.0]
        timeouts = []
        with tempfile.TemporaryDirectory() as temporary:
            container = Path(temporary)
            source = container / 'Documents/native-harness/attempt-01/APP-02/p1/native-events.jsonl'
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({'kind': 'slotIssued', 'processInstanceId': process_id, 'localSequence': 1}) + '\n')

            def runner(argv, **kwargs):
                self.assertEqual(argv, ['xcrun', 'simctl', 'get_app_container', 'OWNED-UUID', 'dev.nativecontract.demo.ios', 'data'])
                timeouts.append(kwargs['timeout'])
                if len(timeouts) == 1 or always_hangs:
                    clock[0] += kwargs['timeout']
                    raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
                return subprocess.CompletedProcess(argv, 0, stdout=str(container), stderr='')

            bridge = controller.NativeProgressBridge(
                platform='ios', run=SimpleNamespace(), device='OWNED-UUID', attempt_id='attempt-01',
                scenario={'id': 'APP-02'}, variant=None, controller_events=[], observations=[],
                process_artifact_directory=container, command_runner=runner,
            )
            with patch.object(controller.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(controller.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
                if always_hangs:
                    with self.assertRaisesRegex(TimeoutError, '15-second audit stable error window'):
                        bridge._read_native_events_until(process_id, lambda events: events[-1]['kind'], description='slot')
                    result = None
                else:
                    result = bridge._read_native_events_until(process_id, lambda events: events[-1]['kind'], description='slot')
        return result, timeouts, clock[0]

    def test_ios_container_timeout_leaves_time_for_a_fresh_query_within_audit_window(self):
        result, timeouts, elapsed = self._ios_audit_after_container_timeout()
        self.assertEqual(result, 'slotIssued')
        self.assertEqual(timeouts, [5, 5])
        self.assertLess(elapsed, 15)

    def test_ios_container_retries_cannot_extend_the_fifteen_second_audit_window(self):
        _, timeouts, elapsed = self._ios_audit_after_container_timeout(always_hangs=True)
        self.assertEqual(len(timeouts), 3)
        self.assertEqual(timeouts[:2], [5, 5])
        self.assertLess(timeouts[-1], 5)
        self.assertEqual(elapsed, 15)

    def test_release_requested_retries_a_torn_audit_before_selecting_slot(self):
        process_id = "attempt-01/APP-02/p1"
        wire_tag = process_id + ":refresh:4"
        slot_event = {
            "kind": "slotIssued",
            "processInstanceId": process_id,
            "localSequence": 1,
            "commandRef": {"processInstanceId": process_id, "id": 4},
            "slotId": "slot-A1",
            "wireTag": wire_tag,
        }
        payloads = iter((b'{"kind":', (json.dumps(slot_event) + "\n").encode()))
        calls = []

        def command_runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=next(payloads), stderr=b"")

        release = Mock(return_value=(wire_tag, []))
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=SimpleNamespace(),
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-02", "requiredDelivery": {"slotId": "slot-A1", "outcome": "success"}},
                variant=None,
                controller_events=[],
                observations=[],
                process_artifact_directory=Path(temporary),
                command_runner=command_runner,
            )
            status = {
                "scenarioId": "APP-02",
                "processInstanceId": process_id,
                "checkpointName": "delivery.4",
                "phase": "releaseRequested",
                "command": "Deliver(current,success)",
            }
            with patch("integration.controller.release_pending_delivery", release):
                bridge(status)

        self.assertEqual(len(calls), 2)
        self.assertEqual(release.call_args.kwargs["wire_tag"], wire_tag)

    def test_replay_status_retries_a_torn_audit_before_binding_source(self):
        trace, _, _ = make_app06_trace()
        process_id = trace["processInstances"][0]["processInstanceId"]
        complete = ("\n".join(json.dumps(row, sort_keys=True) for row in trace["events"]) + "\n").encode()
        payloads = iter((b'{"kind":', complete))

        def command_runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=next(payloads), stderr=b"")

        with tempfile.TemporaryDirectory() as temporary:
            controller_events = []
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=SimpleNamespace(),
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-06", "requiredProbes": []},
                variant=None,
                controller_events=controller_events,
                observations=[],
                process_artifact_directory=Path(temporary),
                command_runner=command_runner,
            )
            bridge._record_replay_status({
                "processInstanceId": process_id,
                "replayActionId": "19",
                "lastEnqueuedCommandId": "5",
            })

        replay = next(event for event in controller_events if event["kind"] == "replayRequested")
        self.assertEqual(replay["sourceCommandRef"], {"processInstanceId": process_id, "id": 4})
        self.assertEqual(replay["commandRef"], {"processInstanceId": process_id, "id": 5})


class BootstrapProbeProvenanceTests(unittest.TestCase):
    def test_preclear_probe_uses_started_bootstrap_command_reference(self):
        process_id = "attempt-01/APP-12-SAVED/p2"
        bootstrap_ref = {"processInstanceId": process_id, "id": 1}
        events = [
            {"kind": "commandEnqueued", "processInstanceId": process_id, "localSequence": 1, "commandRef": bootstrap_ref, "name": "Bootstrap"},
            {"kind": "commandStarted", "processInstanceId": process_id, "localSequence": 2, "commandRef": bootstrap_ref},
        ]
        run = SimpleNamespace(publish_checkpoint=lambda *_args, timeout=5: None)
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            observations = []
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=run,
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-12-SAVED", "requiredProbes": ["APP-12-p2-before-bootstrap-clear"]},
                variant=None,
                controller_events=[],
                observations=observations,
                process_artifact_directory=Path(temporary),
            )
            status = {
                "scenarioId": "APP-12-SAVED",
                "processInstanceId": process_id,
                "checkpointName": "bootstrapStoreProbed",
                "phase": "probeRequested",
                "lastEnqueuedCommandId": "1",
                "redactedProbe": json.dumps({"kind": "Present", "account": "A", "version": 0}),
            }
            with (
                patch("integration.controller.read_live_native_events", return_value=events),
                patch("integration.controller.read_android_storage_probe", return_value={"kind": "Present", "account": "A", "version": 0}),
                patch("integration.controller.append_server_controller_events", return_value=[]),
            ):
                bridge(status)

        self.assertEqual(observations[0]["commandRef"], bootstrap_ref)

    def test_ios_preclear_probe_uses_started_bootstrap_command_reference(self):
        process_id = "attempt-01/APP-12-SAVED/p2"
        bootstrap_ref = {"processInstanceId": process_id, "id": 1}
        events = [
            {"kind": "commandEnqueued", "processInstanceId": process_id, "localSequence": 1, "commandRef": bootstrap_ref, "name": "Bootstrap"},
            {"kind": "commandStarted", "processInstanceId": process_id, "localSequence": 2, "commandRef": bootstrap_ref},
        ]
        snapshot = {
            "version": 1,
            "processInstanceId": process_id,
            "launchOrdinal": 2,
            "controlRevision": 2,
            "lastEnqueuedCommandRef": bootstrap_ref,
            "lastProcessedCommandRef": None,
            "storeIoActive": False,
            "hooks": [],
            "lastProbe": None,
        }
        run = SimpleNamespace(publish_checkpoint=lambda *_args, timeout=5: None)
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            observations = []
            bridge = controller.NativeProgressBridge(
                platform="ios",
                run=run,
                device="OWNED-UUID",
                attempt_id="attempt-01",
                scenario={"id": "APP-12-SAVED", "requiredProbes": ["APP-12-p2-before-bootstrap-clear"]},
                variant=None,
                controller_events=[],
                observations=observations,
                process_artifact_directory=Path(temporary),
            )
            requested = {
                "scenarioId": "APP-12-SAVED",
                "processInstanceId": process_id,
                "checkpointName": "bootstrapStoreProbed",
                "phase": "probeRequested",
                "controlSnapshotJSON": json.dumps(snapshot),
            }
            captured = {
                "scenarioId": "APP-12-SAVED",
                "processInstanceId": process_id,
                "checkpointName": "bootstrapStoreProbed",
                "phase": "probeCaptured",
                "redactedObservation": json.dumps({
                    "probeId": "fresh-probe-1",
                    "processInstanceId": process_id,
                    "observation": {"kind": "Present", "account": "A", "version": 0},
                }),
            }
            with patch("integration.controller.read_live_native_events", return_value=events), patch(
                "integration.controller.append_server_controller_events", return_value=[]
            ):
                bridge(requested)
                bridge(captured)

        self.assertEqual(observations[0]["commandRef"], bootstrap_ref)

    def test_missing_namespace_with_supplemental_absent_probe_records_unknown(self):
        process_id = "attempt-01/APP-02/p1"
        run = SimpleNamespace(publish_checkpoint=lambda *_args, timeout=5: None)
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            observations = []
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=run,
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-02", "requiredProbes": ["APP-02-after-logout-store"]},
                variant=None,
                controller_events=[],
                observations=observations,
                process_artifact_directory=Path(temporary),
            )
            status = {
                "scenarioId": "APP-02",
                "processInstanceId": process_id,
                "checkpointName": "storeProbe.APP-02-after-logout-store",
                "phase": "probeRequested",
                "redactedProbe": json.dumps({"kind": "Absent"}),
            }
            with (
                patch("integration.controller.read_android_storage_probe", return_value={"kind": "Unknown", "errorCode": "probeNamespaceMissing"}),
                patch("integration.controller.append_server_controller_events", return_value=[]),
            ):
                bridge(status)

        self.assertEqual(observations[0]["observation"], {"kind": "Unknown", "errorCode": "probeNamespaceMissing"})


class ProbeClassificationTests(unittest.TestCase):
    def test_mismatching_p2_preclear_probe_with_bootstrap_ref_is_semantic_i9(self):
        contract = json.loads((ROOT / "integration/contract.json").read_text())
        scenario = next(
            row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
            if row["id"] == "APP-12-SAVED"
        )
        trace, server, observations = make_app12_trace()
        p2 = next(row["processInstanceId"] for row in trace["processInstances"] if row["launchOrdinal"] == 2)
        bootstrap_ref = next(
            row["commandRef"] for row in trace["commandInventory"]
            if row["commandRef"]["processInstanceId"] == p2 and row["name"] == "Bootstrap"
        )
        preclear = next(row for row in observations if "before-bootstrap-clear" in row["stepId"])
        preclear["commandRef"] = bootstrap_ref
        preclear["observation"] = {"kind": "Absent"}

        report = check_trace(contract, scenario, trace, server, observations)

        self.assertEqual(report["classification"], "SEMANTIC_FAIL", report)
        self.assertIn("I9", {row["invariant"] for row in report["violations"]})

    def test_unknown_required_host_probe_is_inconclusive(self):
        contract = json.loads((ROOT / "integration/contract.json").read_text())
        scenario = next(
            row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
            if row["id"] == "APP-02"
        )
        trace, server, observations = make_app02_trace()
        final_probe = next(row for row in observations if row["stepId"] == "APP-02-final-probe")
        final_probe["observation"] = {"kind": "Unknown", "errorCode": "probeNamespaceMissing"}

        report = check_trace(contract, scenario, trace, server, observations)

        self.assertEqual(report["classification"], "INCONCLUSIVE", report)
        self.assertTrue(any("Unknown, not a verified state" in row for row in report["missingObservations"]))


class InnerDeadlineTests(unittest.TestCase):
    def test_release_pending_delivery_uses_one_deadline_across_accept_and_terminal_wait(self):
        class Clock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = Clock()
        process_id = "attempt-01/APP-02/p1"
        wire_tag = process_id + ":refresh:4"

        class Run:
            def __init__(self):
                self.server_events = [{"sequence": 1, "kind": "requestHeld", "requestTag": wire_tag}]

            def events(self, *, timeout=5):
                return self.server_events, len(self.server_events)

            def pending(self, *, timeout=5):
                return [{"requestTag": wire_tag}]

            def release(self, request_tag, outcome, *, timeout=5):
                clock.now += 0.75
                self.server_events.append({"sequence": 2, "kind": "releaseAccepted", "requestTag": request_tag})
                return {"status": "releaseAccepted", "requestTag": request_tag}

        run = Run()
        with patch("integration.controller.time.monotonic", side_effect=clock.monotonic), patch(
            "integration.controller.time.sleep", side_effect=clock.sleep
        ):
            with self.assertRaisesRegex(TimeoutError, "terminal transport event"):
                controller.release_pending_delivery(
                    run,
                    command="Deliver(current,success)",
                    variant=None,
                    process_instance_id=process_id,
                    wire_tag=wire_tag,
                    controller_events=[],
                    known_server_sequences=set(),
                    timeout_seconds=1.0,
                )

        self.assertLessEqual(clock.now, 1.01)

    def test_native_audit_read_timeout_is_capped_to_remaining_stage_budget(self):
        process_id = "attempt-01/APP-02/p1"
        wire_tag = process_id + ":refresh:4"
        event = {
            "kind": "slotIssued",
            "processInstanceId": process_id,
            "localSequence": 1,
            "commandRef": {"processInstanceId": process_id, "id": 4},
            "slotId": "slot-A1",
            "wireTag": wire_tag,
        }
        calls = []

        def command_runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=(json.dumps(event) + "\n").encode(), stderr=b"")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=SimpleNamespace(),
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-02", "requiredDelivery": {"slotId": "slot-A1", "outcome": "success"}},
                variant=None,
                controller_events=[],
                observations=[],
                process_artifact_directory=Path(temporary),
                command_runner=command_runner,
                deadline=100.25,
            )
            with patch("integration.controller.time.monotonic", return_value=100.0), patch(
                "integration.controller.release_pending_delivery", return_value=(wire_tag, [])
            ):
                bridge({
                    "scenarioId": "APP-02",
                    "processInstanceId": process_id,
                    "checkpointName": "delivery.4",
                    "phase": "releaseRequested",
                    "command": "Deliver(current,success)",
                })

        self.assertEqual(calls[0][1]["timeout"], 0.25)

    def test_android_probe_read_timeout_is_capped_to_remaining_stage_budget(self):
        process_id = "attempt-01/APP-02/p1"
        run = SimpleNamespace(publish_checkpoint=lambda *_args, timeout=5: None)
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            bridge = controller.NativeProgressBridge(
                platform="android",
                run=run,
                device="emulator-5580",
                attempt_id="attempt-01",
                scenario={"id": "APP-02", "requiredProbes": ["APP-02-after-logout-store"]},
                variant=None,
                controller_events=[],
                observations=[],
                process_artifact_directory=Path(temporary),
                deadline=100.25,
            )
            with patch("integration.controller.time.monotonic", return_value=100.0), patch(
                "integration.controller.read_android_storage_probe", return_value={"kind": "Absent"}
            ) as probe, patch("integration.controller.append_server_controller_events", return_value=[]):
                bridge({
                    "scenarioId": "APP-02",
                    "processInstanceId": process_id,
                    "checkpointName": "storeProbe.APP-02-after-logout-store",
                    "phase": "probeRequested",
                    "redactedProbe": json.dumps({"kind": "Absent"}),
                })

        self.assertEqual(probe.call_args.kwargs["timeout_seconds"], 0.25)

    def test_android_storage_probe_recomputes_deadline_between_listing_and_cat(self):
        class Clock:
            now = 100.0

            def monotonic(self):
                return self.now

        clock = Clock()
        calls = []
        raw = b'{"account":"A","version":0,"accessToken":"demo-A-v0","refreshToken":"demo-A-v0"}'

        def command_runner(argv, **kwargs):
            calls.append((argv, kwargs))
            if "ls" in argv:
                clock.now += 0.20
                return subprocess.CompletedProcess(argv, 0, stdout="credential.json", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout=raw, stderr=b"")

        with patch("integration.controller.time.monotonic", side_effect=clock.monotonic):
            observation = controller.read_android_storage_probe(
                serial="emulator-5580",
                attempt_id="attempt-01",
                scenario_id="APP-02",
                command_runner=command_runner,
                timeout_seconds=15,
                deadline=100.25,
            )

        self.assertEqual(observation, {"kind": "Present", "account": "A", "version": 0})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["timeout"], 0.25)
        self.assertAlmostEqual(calls[1][1]["timeout"], 0.05)

    def test_android_storage_probe_raises_when_stage_expires_between_listing_and_cat(self):
        class Clock:
            now = 100.0

            def monotonic(self):
                return self.now

        clock = Clock()

        def command_runner(argv, **kwargs):
            clock.now = 100.25
            return subprocess.CompletedProcess(argv, 0, stdout="credential.json", stderr="")

        with patch("integration.controller.time.monotonic", side_effect=clock.monotonic):
            with self.assertRaisesRegex(TimeoutError, "stage deadline exhausted"):
                controller.read_android_storage_probe(
                    serial="emulator-5580",
                    attempt_id="attempt-01",
                    scenario_id="APP-02",
                    command_runner=command_runner,
                    timeout_seconds=15,
                    deadline=100.25,
                )


if __name__ == "__main__":
    unittest.main()
