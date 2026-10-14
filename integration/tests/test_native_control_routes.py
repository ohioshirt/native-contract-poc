import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import controller


ROOT = Path(__file__).resolve().parents[2]


class NativeControlRouteTests(unittest.TestCase):
    def test_native_platform_routes_real_control_inventory_to_control_cases(self):
        control_path = ROOT / "integration" / "control-scenarios.json"
        inventory = json.loads(control_path.read_text())
        controls = inventory["controls"]
        self.assertTrue(controls)

        case_calls = []

        def run_case(**kwargs):
            control = kwargs["scenario"]
            self.assertEqual(kwargs["resolved_scenario"], control)
            self.assertIsNone(kwargs["variant"])
            case_calls.append(control["id"])
            return ({
                "scenarioId": control["id"],
                "variantId": None,
                "classification": "PASS",
                "violations": [],
                "missingObservations": [],
            }, None, [])

        result = {
            "requiredScenarioIds": [row["id"] for row in controls],
            "commands": [],
        }
        with tempfile.TemporaryDirectory(prefix="control-route-") as temporary:
            with patch.object(controller, "_run_case", side_effect=run_case):
                routed = controller._run_native_platform(
                    platform="android",
                    candidate=ROOT,
                    output=Path(temporary) / "platform",
                    device="emulator-owned",
                    stage_id="integration-controls",
                    attempt_id="test-controls",
                    scenario_rows=controls,
                    scenario_path=control_path,
                    scenario_bytes=control_path.read_bytes(),
                    result=result,
                    command_runner=lambda *args, **kwargs: self.fail("unexpected device command"),
                    timeout_seconds=30,
                    prepared_build={"buildHash": "a" * 64},
                    write_artifacts=False,
                )

        self.assertEqual(case_calls, [row["id"] for row in controls])
        self.assertEqual(routed["classification"], "PASS")
        self.assertEqual(routed["completedScenarioIds"], [row["id"] for row in controls])
        self.assertEqual(routed["missingScenarioIds"], [])


if __name__ == "__main__":
    unittest.main()
