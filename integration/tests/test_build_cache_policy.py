from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integration import controller


ROOT = Path(__file__).resolve().parents[2]


class AndroidBuildCachePolicyTests(unittest.TestCase):
    def test_explicit_prewarmed_home_is_selected_and_recorded(self):
        with tempfile.TemporaryDirectory(prefix="prewarmed-gradle-home-") as temporary:
            root = Path(temporary)
            warm_home = root / "runner-temp" / "native-contract-gradle-home"
            warm_home.mkdir(parents=True)

            selected, provenance = controller._select_android_gradle_home(
                root / "ledger" / "candidate-android",
                {"GRADLE_USER_HOME": str(warm_home)},
            )

        self.assertEqual(selected, warm_home.resolve())
        self.assertEqual(provenance, {
            "path": str(warm_home.resolve()),
            "policy": "prewarmed-environment",
        })

    def test_missing_environment_uses_an_explicit_owned_output_cache(self):
        with tempfile.TemporaryDirectory(prefix="owned-gradle-home-") as temporary:
            output = Path(temporary) / "candidate-android"

            selected, provenance = controller._select_android_gradle_home(output, {})

            self.assertEqual(selected, (output / "gradle-home").resolve())
            self.assertTrue(selected.is_dir())
            self.assertEqual(provenance, {
                "path": str(selected),
                "policy": "owned-output",
            })

    def test_configured_prewarmed_home_must_exist_instead_of_silently_falling_back(self):
        with tempfile.TemporaryDirectory(prefix="missing-gradle-home-") as temporary:
            missing = Path(temporary) / "runner-temp" / "native-contract-gradle-home"

            with self.assertRaisesRegex(ValueError, "prewarmed GRADLE_USER_HOME does not exist"):
                controller._select_android_gradle_home(
                    Path(temporary) / "candidate-android",
                    {"GRADLE_USER_HOME": str(missing)},
                )

    def test_android_candidate_build_uses_environment_cache_and_records_provenance(self):
        with tempfile.TemporaryDirectory(prefix="candidate-android-cache-") as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            output = root / "stage" / "candidate-android"
            warm_home = root / "runner-temp" / "native-contract-gradle-home"
            warm_home.mkdir(parents=True)
            calls = []

            def fake_stream(argv, *, cwd, environment, output_directory, timeout_seconds, **kwargs):
                calls.append({"argv": argv, "environment": dict(environment)})
                artifacts = [
                    candidate / "apps/android-demo/app/build/outputs/apk/debug/app-debug.apk",
                    candidate / "apps/android-demo/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk",
                    candidate / "apps/android-demo/app/build/contract-async/libs/contract-async-1.0.0.jar",
                ]
                for path in artifacts:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"owned build output")
                return {"argv": argv, "exitCode": 0, "timedOut": False}

            with patch.object(controller, "run_streaming_command", side_effect=fake_stream):
                result = controller._build_android_candidate(
                    candidate,
                    output,
                    {"GRADLE_USER_HOME": str(warm_home)},
                    30,
                    run_candidate_unit_tests=False,
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["environment"]["GRADLE_USER_HOME"], str(warm_home.resolve()))
        self.assertEqual(result["gradleCache"], {
            "path": str(warm_home.resolve()),
            "policy": "prewarmed-environment",
        })

    def test_control_mutant_builds_share_the_pre_warmed_environment_cache(self):
        controls_path = ROOT / "integration/control-scenarios.json"
        controls = json.loads(controls_path.read_text())["controls"]
        build_calls = []

        def prepare(**kwargs):
            return {
                "workspaceSourceSha256": "a" * 64,
                "matrixSha256": "b" * 64,
                "patchManifest": {"mutationId": kwargs["mutation_id"]},
                "patchedPlatformSource": {"path": "coordinator", "materializedSha256": "c" * 64},
                "helper": None,
                "candidateUnitTestPolicy": {"execution": "skipped-for-mutant-witness-build"},
            }

        def build(candidate, output, environment, timeout_seconds, *, gradle_home, gradle_home_policy, run_candidate_unit_tests):
            build_calls.append((Path(gradle_home), gradle_home_policy, run_candidate_unit_tests))
            return {
                "buildHash": "d" * 64,
                "appApk": "/owned/app.apk",
                "testApk": "/owned/test.apk",
                "libraryJar": "/owned/library.jar",
                "testApkHash": "e" * 64,
                "libraryJarHash": "f" * 64,
                "gradleCache": {"path": str(Path(gradle_home).resolve()), "policy": gradle_home_policy},
            }

        def run_group(**kwargs):
            rows = kwargs["scenario_rows"]
            cases = [{
                "scenarioId": row["id"], "variantId": None, "classification": "SEMANTIC_FAIL",
                "violations": [], "missingObservations": [],
                "traceBinding": {"scenarioId": row["id"], "variantId": None, "buildHash": "sha256:" + "d" * 64},
            } for row in rows]
            return {
                "classification": "SEMANTIC_FAIL",
                "requiredScenarioIds": [row["id"] for row in rows],
                "completedScenarioIds": [row["id"] for row in rows],
                "missingScenarioIds": [],
                "traceBindings": [],
                "_caseResults": cases,
                "_traceRows": [], "_serverRows": [], "_uiRows": [],
                "_controllerRows": [], "_screenshotRows": [],
            }

        with tempfile.TemporaryDirectory(prefix="mutant-prewarmed-gradle-") as temporary:
            root = Path(temporary)
            warm_home = root / "runner-temp" / "native-contract-gradle-home"
            warm_home.mkdir(parents=True)

            def install(argv, **kwargs):
                return {"argv": list(argv), "exitCode": 0, "timedOut": False}

            with patch.dict(os.environ, {"GRADLE_USER_HOME": str(warm_home)}), \
                 patch.object(controller, "prepare_mutation_workspace", side_effect=prepare), \
                 patch.object(controller, "_probe_android_acceptance_device", return_value=([], {"apiLevel": "35", "abi": "x86_64"})), \
                 patch.object(controller, "_build_android_candidate", side_effect=build), \
                 patch.object(controller, "_run_native_platform", side_effect=run_group), \
                 patch.object(controller, "run_streaming_command", side_effect=install):
                result = controller._run_mutation_control_platform(
                    platform="android",
                    candidate=ROOT,
                    output=root / "ledger" / "integration-controls" / "android",
                    device="emulator-owned",
                    stage_id="integration-controls",
                    attempt_id="cache-attempt",
                    scenario_rows=controls,
                    scenario_path=controls_path,
                    scenario_bytes=controls_path.read_bytes(),
                    base_result={"version": 1, "platform": "android", "deviceId": "emulator-owned", "commands": [], "requiredScenarioIds": [row["id"] for row in controls]},
                    command_runner=subprocess.run,
                    timeout_seconds=300,
                )
            warm_home_preserved = warm_home.is_dir()

        self.assertTrue(build_calls)
        self.assertTrue(all(path == warm_home.resolve() for path, _, _ in build_calls))
        self.assertTrue(all(policy == "prewarmed-environment" for _, policy, _ in build_calls))
        self.assertTrue(all(run_unit_tests is False for _, _, run_unit_tests in build_calls))
        self.assertTrue(warm_home_preserved, "the controller must never delete the caller's pre-warmed cache")
        self.assertTrue(all(row.get("gradleCache", {}).get("path") == str(warm_home.resolve()) for row in result["mutationBuilds"]))
        self.assertTrue(all(row.get("gradleCache", {}).get("policy") == "prewarmed-environment" for row in result["mutationBuilds"]))


if __name__ == "__main__":
    unittest.main()
