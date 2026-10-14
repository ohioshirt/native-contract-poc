"""Cross-file wiring checks between frozen evaluator inputs.

These compare real repository files with each other. They exist because fake
subprocess tests could not see that the controller and the Gradle settings
disagreed on the contract-async jar path (E1), or that an inventory control
label was outside the frozen Android harness vocabulary (E2).
"""
import json
import re
import unittest
from pathlib import Path

from integration import controller

ROOT = Path(__file__).resolve().parents[2]


class EvaluatorWiringTests(unittest.TestCase):
    def test_gradle_settings_build_contract_async_where_the_controller_reads_the_jar(self):
        settings = (ROOT / "apps/android-demo/settings.gradle.kts").read_text()
        match = re.search(
            r'if \(path == ":contract-async"\) \{\s*layout\.buildDirectory\.set\(rootProject\.layout\.projectDirectory\.dir\("([^"]+)"\)\)',
            settings,
        )
        self.assertIsNotNone(match, "contract-async build directory must be an explicit project-relative path")
        build_directory = Path("apps/android-demo") / match.group(1)
        expected_jar = Path(controller.ANDROID_CONTRACT_ASYNC_JAR)
        self.assertEqual(build_directory / "libs" / expected_jar.name, expected_jar)

    def test_every_inventory_control_label_is_accepted_by_the_frozen_android_harness(self):
        harness = (ROOT / "apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt").read_text()
        match = re.search(
            r"require\(declaredControls\.all \{\s*it in setOf\(([^)]*)\)\s*\}\) \{ \"frozen controls contains an unsupported operation\" \}",
            harness,
        )
        self.assertIsNotNone(match, "frozen Android control vocabulary was not found")
        accepted = set(re.findall(r'"([^"]+)"', match.group(1)))
        labels = set()
        for name, key in (("scenarios.json", "scenarios"), ("control-scenarios.json", "controls")):
            for row in json.loads((ROOT / "integration" / name).read_text())[key]:
                labels.update(row.get("controls", []))
                for variant in row.get("variants", []):
                    labels.update(variant.get("controls", []))
        self.assertTrue(labels)
        self.assertEqual(set(), labels - accepted)


    def test_launch_inventory_digests_name_each_packaged_file_for_every_stage_inventory(self):
        # Both harnesses verify the packaged scenarios.json against the scenario digest
        # and control-scenarios.json against the control digest, even in the controls stage.
        import hashlib

        expected = (
            hashlib.sha256((ROOT / "integration/scenarios.json").read_bytes()).hexdigest(),
            hashlib.sha256((ROOT / "integration/control-scenarios.json").read_bytes()).hexdigest(),
        )
        self.assertNotEqual(expected[0], expected[1])
        self.assertEqual(expected, controller.launch_inventory_digests(ROOT))
        source = (ROOT / "integration/controller.py").read_text()
        self.assertNotIn("scenario_digest = digest_bytes(scenario_bytes)", source)
        # _run_native_platform is the one place that builds per-case launch arguments.
        self.assertEqual(1, source.count("scenario_digest, control_digest = launch_inventory_digests(candidate)"))


if __name__ == "__main__":
    unittest.main()
