import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import controller


ROOT = Path(__file__).resolve().parents[2]


class _FakeRun:
    run_id = "owned-run"
    base_url = "http://127.0.0.1:43129"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def events(self, *, timeout=5):
        return [], []


class _FakeBridge:
    known_server_sequences = set()
    end_seen = set()

    def __init__(self, **kwargs):
        pass

    def bind_native_events(self, events):
        pass


class NativeLaunchFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {
            row["id"]: row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
        }

    def fault_scenarios(self):
        for scenario_id, variant_id in (
            ("APP-09", "replace-before"),
            ("APP-10", "clear-before"),
            ("APP-10-RECOVER-OLD", None),
        ):
            scenario = self.scenarios[scenario_id]
            if variant_id is None:
                yield scenario, scenario, None
                continue
            variant = next(row for row in scenario["variants"] if row["id"] == variant_id)
            resolved, selected, error = controller._resolve_scenario_variant(
                scenario, {"variantId": variant_id}, variant_id
            )
            self.assertIsNone(error)
            self.assertEqual(selected, variant)
            self.assertIsNotNone(resolved.get("fault"))
            yield scenario, resolved, selected

    def test_inventory_faults_are_not_armed_at_process_launch(self):
        scenario_inventory = ROOT / "integration/scenarios.json"
        control_inventory = ROOT / "integration/control-scenarios.json"
        contract = json.loads((ROOT / "integration/contract.json").read_text())
        attempt = 0

        for platform in ("ios", "android"):
            for scenario, resolved, variant in self.fault_scenarios():
                attempt += 1
                captured = []

                def run_command(argv, **kwargs):
                    captured.append((list(argv), dict(kwargs["environment"])))
                    return {"argv": list(argv), "exitCode": 0, "timedOut": False}

                with tempfile.TemporaryDirectory(prefix="launch-fault-boundary-") as temporary:
                    output = Path(temporary) / "stage" / platform
                    with (
                        patch.object(controller, "LoopbackRun", return_value=_FakeRun()),
                        patch.object(controller, "NativeProgressBridge", _FakeBridge),
                        patch.object(controller, "run_streaming_command", side_effect=run_command),
                        patch.object(controller, "append_server_controller_events", return_value=[]),
                        patch.object(controller, "_copy_ios_process_artifacts", return_value=([], f"{scenario['id']}/p1/native.jsonl", [])),
                        patch.object(controller, "_copy_android_process_artifacts", return_value=([], f"{scenario['id']}/p1/native.jsonl", [])),
                        patch.object(controller, "_ios_terminate_app", return_value={"exitCode": 0}),
                        patch.object(controller, "_android_force_stop", return_value=[]),
                        patch.object(controller, "check_trace", return_value={
                            "classification": "INCONCLUSIVE", "violations": [], "missingObservations": []
                        }),
                    ):
                        controller._run_case(
                            platform=platform,
                            candidate=ROOT,
                            output=output,
                            device="owned-device",
                            scenario=scenario,
                            resolved_scenario=resolved,
                            variant=variant,
                            attempt_base=f"fault-attempt-{attempt}",
                            contract=contract,
                            build_hash="a" * 64,
                            app_paths={"xctestrunPath": "/owned/test.xctestrun"},
                            scenario_path=scenario_inventory,
                            control_path=control_inventory,
                            scenario_digest="b" * 64,
                            control_digest="c" * 64,
                            timeout_seconds=30,
                            command_runner=lambda *args, **kwargs: self.fail("unexpected native command"),
                        )

                runner_calls = [row for row in captured if row[0][0] != "/usr/bin/xcrun" or "xcresulttool" not in row[0]]
                self.assertEqual(len(runner_calls), 1, scenario["id"])
                argv, environment = runner_calls[0]
                if platform == "ios":
                    self.assertFalse(any(key.endswith("STORE_FAULT") for key in environment), scenario["id"])
                else:
                    self.assertFalse(any(argv[index:index + 2] == ["-e", "storeFault"] for index in range(len(argv) - 1)), scenario["id"])
                self.assertTrue(resolved.get("fault"), scenario["id"])


if __name__ == "__main__":
    unittest.main()
