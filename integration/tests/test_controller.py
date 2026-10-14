import json
import hashlib
import os
import sys
import threading
from urllib.request import Request, urlopen
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest

from integration import controller
from integration.tests._history_fixtures import make_app02_trace


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


def synthetic_local_device_scope(root: Path):
    root = Path(root)
    integration_root = root / "integration"
    integration_root.mkdir(parents=True, exist_ok=True)
    avd_home = root / "owned-avd-home"
    avd_home.mkdir(parents=True, exist_ok=True)
    ios_path = root / "owned-ios.json"
    android_path = root / "owned-android.json"
    readiness_path = root / "android-readiness.json"
    ios = {
        "owned": True,
        "platform": "ios",
        "udid": "A1B2C3D4-0000-4000-8000-0000000000A1",
        "runtimeVersion": "18.6",
        "runtimeBuild": "22G86",
        "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-6",
    }
    android = {
        "owned": True,
        "platform": "android",
        "imagePackage": "system-images;android-35;google_apis;arm64-v8a",
        "imageRevision": "9.0.0",
        "avdHome": str(avd_home),
        "name": "native_contract_test_avd",
    }
    readiness = {
        "classification": "READY",
        "serial": "emulator-5580",
        "avdName": android["name"],
        "apiLevel": "35",
        "abi": "arm64-v8a",
    }
    ios_path.write_text(json.dumps(ios, sort_keys=True))
    android_path.write_text(json.dumps(android, sort_keys=True))
    readiness_path.write_text(json.dumps(readiness, sort_keys=True))
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    toolchain = {
        "acceptancePins": {"ios": {"xcode": "16.2"}, "android": {"apiLevel": "35", "abi": "x86_64"}},
        "localValidationScope": {
            "id": "local-observed",
            "classification": "LOCAL_VALIDATION_ONLY",
            "acceptedByCiAggregate": False,
            "ios": {
                "xcode": "27.1", "runtimeVersion": "18.6", "runtimeBuild": "22G86",
                "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-6",
                "ownedDeviceEvidence": "owned-ios.json", "ownedDeviceEvidenceSha256": sha(ios_path),
            },
            "android": {
                "apiLevel": 35, "abi": "arm64-v8a",
                "imagePackage": android["imagePackage"], "imageRevision": "9.0.0",
                "ownedDeviceEvidence": "owned-android.json", "ownedDeviceEvidenceSha256": sha(android_path),
                "readinessEvidence": "android-readiness.json", "readinessEvidenceSha256": sha(readiness_path),
            },
        },
    }
    (integration_root / "toolchain.json").write_text(json.dumps(toolchain, sort_keys=True))
    return ios_path, android_path, android


def setUpModule():
    (ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


class PlatformControllerTests(unittest.TestCase):
    def test_xcresult_attachment_export_uses_only_pinned_documented_paths(self):
        argv = controller.xcresult_export_attachments_argv("case.xcresult", "screenshots")

        self.assertEqual(argv[:4], ["/usr/bin/xcrun", "xcresulttool", "export", "attachments"])
        self.assertIn("--path", argv)
        self.assertIn("--output-path", argv)
        self.assertNotIn("--filter", argv)

    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((ROOT / "integration/contract.json").read_text())
        cls.scenarios = {row["id"]: row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]}

    def evidence(self, directory, *, missing_delivery=False):
        trace, server, observations = make_app02_trace(missing_delivery=missing_delivery)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "trace.json").write_text(json.dumps(trace))
        (directory / "server-events.json").write_text(json.dumps(server))
        (directory / "ui-observations.json").write_text(json.dumps(observations))
        return directory

    def test_missing_ui_evidence_not_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.evidence(Path(temporary) / "APP-02")
            observations = json.loads((directory / "ui-observations.json").read_text())
            (directory / "ui-observations.json").write_text(json.dumps([row for row in observations if row["kind"] != "renderedView"]))

            result = controller.evaluate_scenario(
                self.contract, self.scenarios["APP-02"], directory, server_exit=0
            )

        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertTrue(result["missingObservations"])

    def test_server_exit_infra_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.evidence(Path(temporary) / "APP-02")

            result = controller.evaluate_scenario(
                self.contract, self.scenarios["APP-02"], directory, server_exit=1
            )

        self.assertEqual(result["classification"], "INFRA_FAILURE")

    def test_owned_device_evidence_binds_exact_simulator_or_avd_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            directory = Path(temporary)
            ios_path = directory / "ios-owned.json"
            ios_path.write_text(json.dumps({"version": 1, "platform": "ios", "owned": True, "udid": "OWNED-UUID"}))
            readiness_path = directory / "android-ready.json"
            readiness_path.write_text(json.dumps({
                "classification": "READY",
                "avdName": "owned-api35-avd",
                "serial": "emulator-5580",
            }))
            android_path = directory / "android-owned.json"
            android_path.write_text(json.dumps({
                "version": 1,
                "platform": "android",
                "owned": True,
                "name": "owned-api35-avd",
                "avdHome": "/owned/avd/home",
                "readinessEvidence": {"classification": "READY", "path": str(readiness_path)},
            }))

            ios_match = controller._owned_device_evidence_error("ios", "OWNED-UUID", ios_path, candidate=ROOT)
            ios_casefold_match = controller._owned_device_evidence_error("ios", "owned-uuid", ios_path, candidate=ROOT)
            ios_mismatch = controller._owned_device_evidence_error("ios", "OTHER-UUID", ios_path, candidate=ROOT)
            with patch.dict(os.environ, {"ANDROID_AVD_HOME": "/owned/avd/home"}):
                android_match = controller._owned_device_evidence_error("android", "emulator-5580", android_path, candidate=ROOT)
                android_mismatch = controller._owned_device_evidence_error("android", "emulator-5554", android_path, candidate=ROOT)

        self.assertIsNone(ios_match)
        self.assertIsNone(ios_casefold_match)
        self.assertIsNotNone(ios_mismatch)
        self.assertIsNone(android_match)
        self.assertIsNotNone(android_mismatch)

    def test_no_late_delivery_inconclusive_or_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = self.evidence(Path(temporary) / "APP-02", missing_delivery=True)

            result = controller.evaluate_scenario(
                self.contract, self.scenarios["APP-02"], directory, server_exit=0
            )

        self.assertIn(result["classification"], {"INCONCLUSIVE", "INVALID_HISTORY"})
        self.assertNotEqual(result["classification"], "PASS")
        self.assertNotEqual(result["classification"], "SEMANTIC_FAIL")

    def test_foreign_device_not_erased(self):
        commands = []

        def fake_runner(argv, **kwargs):
            commands.append(argv)
            devices = {"devices": {"Available": [{"name": "Foreign", "udid": "FOREIGN-UUID", "state": "Booted"}]}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(devices), stderr="")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            result = controller.run_platform(
                "ios",
                candidate=ROOT,
                output=Path(temporary) / "candidate-ios",
                device="OTHER-UUID",
                scenarios=ROOT / "integration/scenarios.json",
                command_runner=fake_runner,
            )

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertEqual(commands, [["xcrun", "simctl", "list", "devices", "--json"]])
        self.assertFalse(any(any(token in {"delete", "shutdown", "erase", "uninstall", "clear"} for token in command) for command in commands))

    def test_candidate_runtime_placeholders_remain_not_run_after_explicit_inventory(self):
        commands = []

        def fake_runner(argv, **kwargs):
            commands.append(argv)
            devices = {"devices": {"Available": [{"name": "Owned test simulator", "udid": "OWNED-UUID", "state": "Booted", "isAvailable": True}]}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(devices), stderr="")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            # An empty candidate tree models absent runtime sources independently of
            # whether this repository's own candidate has been implemented.
            placeholder_candidate = Path(temporary) / "placeholder-candidate"
            placeholder_candidate.mkdir()
            result = controller.run_platform(
                "ios",
                candidate=placeholder_candidate,
                output=Path(temporary) / "candidate-ios" / "ios",
                device="OWNED-UUID",
                scenarios=ROOT / "integration/scenarios.json",
                command_runner=fake_runner,
            )
            scenario_results_exists = (Path(temporary) / "candidate-ios" / "ios" / "scenario-results.json").is_file()

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertIn("SessionCoordinator.swift", result["detail"])
        self.assertEqual(commands, [["xcrun", "simctl", "list", "devices", "--json"]])
        self.assertTrue(scenario_results_exists)

    def test_ios_lowercase_owned_uuid_resolves_to_inventory_canonical_case(self):
        canonical = "A1B2C3D4-0000-4000-8000-0000000000A1"

        def fake_runner(argv, **kwargs):
            devices = {"devices": {"iOS 18.6": [{"name": "Owned", "udid": canonical, "state": "Booted", "isAvailable": True}]}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(devices), stderr="")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            placeholder_candidate = Path(temporary) / "placeholder-candidate"
            placeholder_candidate.mkdir()
            result = controller.run_platform(
                "ios",
                candidate=placeholder_candidate,
                output=Path(temporary) / "candidate-ios" / "ios",
                device=canonical.lower(),
                scenarios=ROOT / "integration/scenarios.json",
                command_runner=fake_runner,
            )

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertEqual(result["deviceId"], canonical)

    def _run_ios_inventory(self, hangs):
        # Hosted macOS runners sometimes never answer `simctl list devices`; a fresh call succeeds.
        canonical = "A1B2C3D4-0000-4000-8000-0000000000A1"
        calls = []

        def fake_runner(argv, **kwargs):
            calls.append(kwargs.get("timeout"))
            if len(calls) <= hangs:
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            devices = {"devices": {"iOS 18.2": [{"name": "Owned", "udid": canonical, "state": "Booted", "isAvailable": True}]}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(devices), stderr="")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            placeholder_candidate = Path(temporary) / "placeholder-candidate"
            placeholder_candidate.mkdir()
            result = controller.run_platform(
                "ios",
                candidate=placeholder_candidate,
                output=Path(temporary) / "candidate-ios" / "ios",
                device=canonical,
                scenarios=ROOT / "integration/scenarios.json",
                command_runner=fake_runner,
            )
        return result, calls

    def test_ios_inventory_retries_a_hung_simctl(self):
        result, calls = self._run_ios_inventory(hangs=2)

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertIn("SessionCoordinator.swift", result["detail"])
        self.assertEqual(calls, [60, 60, 60])

    def test_ios_inventory_reports_infra_failure_after_bounded_retries(self):
        result, calls = self._run_ios_inventory(hangs=3)

        self.assertEqual(result["classification"], "INFRA_FAILURE")
        self.assertIn("device inventory failed", result["detail"])
        self.assertEqual(calls, [60, 60, 60])

    def test_refresh_server_start_tolerates_a_slow_runner(self):
        # Five control cases on one hosted macOS run each missed a 10 s readiness window.
        import inspect

        default = inspect.signature(controller.LoopbackRun.start).parameters["timeout_seconds"].default
        self.assertGreaterEqual(default, 60)


class ValidationScopeTests(unittest.TestCase):
    def test_ci_runtime_rejects_local_tuple_while_explicit_local_probe_accepts_exact_tuple(self):
        def fake_runner(argv, **kwargs):
            if argv == ["xcodebuild", "-version"]:
                return subprocess.CompletedProcess(argv, 0, stdout="Xcode 27.1\nBuild version 27A9269\n", stderr="")
            if argv[:4] == ["xcrun", "simctl", "list", "runtimes"]:
                document = {"runtimes": [{
                    "version": "18.6",
                    "buildversion": "22G86",
                    "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-6",
                    "isAvailable": True,
                }]}
                return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(document), stderr="")
            raise AssertionError(argv)

        with self.assertRaisesRegex(ValueError, "acceptance pin 16.2"):
            controller._probe_ios_acceptance_runtime(ROOT, fake_runner, validation_scope="ci")
        commands, runtime = controller._probe_ios_acceptance_runtime(
            ROOT, fake_runner, validation_scope="local-observed"
        )

        self.assertEqual(runtime["version"], "18.6")
        self.assertEqual(runtime["buildversion"], "22G86")
        self.assertEqual(len(commands), 2)

    def test_local_owned_device_evidence_must_match_the_recorded_toolchain_tuple(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-local-device-scope-") as temporary:
            candidate = Path(temporary)
            ios_path, android_path, android = synthetic_local_device_scope(candidate)
            ios = json.loads(ios_path.read_text())
            with patch.dict(os.environ, {"ANDROID_AVD_HOME": android["avdHome"]}):
                self.assertIsNone(controller._validation_scope_evidence_error(
                    "ios", ios["udid"], ios_path, candidate=candidate, validation_scope="local-observed"
                ))
                self.assertIsNone(controller._validation_scope_evidence_error(
                    "android", "emulator-5580", android_path, candidate=candidate, validation_scope="local-observed"
                ))
                self.assertIsNotNone(controller._validation_scope_evidence_error(
                    "ios", "another-device", ios_path, candidate=candidate, validation_scope="local-observed"
                ))
                self.assertIsNotNone(controller._validation_scope_evidence_error(
                    "android", "emulator-5554", android_path, candidate=candidate, validation_scope="local-observed"
                ))

    def test_android_probe_selects_only_the_explicit_scope_abi(self):
        def fake_runner(argv, **kwargs):
            prop = argv[-1]
            value = "35" if prop == "ro.build.version.sdk" else "arm64-v8a"
            return subprocess.CompletedProcess(argv, 0, stdout=value + "\n", stderr="")

        with tempfile.TemporaryDirectory(prefix="synthetic-android-device-scope-") as temporary:
            candidate = Path(temporary)
            _, evidence_path, evidence = synthetic_local_device_scope(candidate)
            with patch.dict(os.environ, {
                "NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE": str(evidence_path),
                "ANDROID_AVD_HOME": evidence["avdHome"],
            }, clear=False):
                commands, values = controller._probe_android_acceptance_device(
                    "emulator-5580", fake_runner, candidate=candidate, validation_scope="local-observed"
                )
            self.assertEqual(values, {"apiLevel": "35", "abi": "arm64-v8a"})
            self.assertEqual(len(commands), 2)
            with self.assertRaisesRegex(ValueError, "x86_64"):
                controller._probe_android_acceptance_device(
                    "emulator-5580",
                    lambda argv, **kwargs: subprocess.CompletedProcess(
                        argv, 0, stdout=("35\n" if argv[-1] == "ro.build.version.sdk" else "arm64-v8a\n"), stderr=""
                    ),
                    candidate=candidate,
                    validation_scope="ci",
                )

    def test_ios_build_uses_ad_hoc_simulator_signing_without_parallel_clones(self):
        calls = []

        with tempfile.TemporaryDirectory(prefix="ios-signing-args-") as temporary:
            output = Path(temporary)

            def build_stream(argv, *, cwd, environment, output_directory, timeout_seconds, **kwargs):
                calls.append(argv)
                output_directory = Path(output_directory)
                output_directory.mkdir(parents=True)
                (output_directory / "stdout.log").write_text("fixture build\n")
                (output_directory / "stderr.log").write_text("")
                if "build-for-testing" in argv:
                    app = output / "derived-data/Build/Products/Debug-iphonesimulator/NativeContractDemo.app"
                    app.mkdir(parents=True)
                    (app / "Info.plist").write_bytes(b"synthetic signed app artifact")
                    xctestrun = output / "derived-data/Build/Products/NativeContractDemo.xctestrun"
                    xctestrun.parent.mkdir(parents=True, exist_ok=True)
                    xctestrun.write_text("fixture xctestrun\n")
                return {"argv": argv, "exitCode": 0, "timedOut": False}

            with patch("integration.controller.run_streaming_command", side_effect=build_stream):
                result = controller._build_ios_candidate(ROOT, output, "OWNED-UUID", {}, 120)

        self.assertTrue(result["buildHash"])
        self.assertEqual(len(calls), 2)
        for argv in calls:
            self.assertIn("-parallel-testing-enabled", argv)
            self.assertIn("NO", argv)
            self.assertIn("CODE_SIGNING_ALLOWED=YES", argv)
            self.assertIn("CODE_SIGN_IDENTITY=-", argv)
            self.assertNotIn("DEVELOPMENT_TEAM", argv)


class MutationBuildRoutingTests(unittest.TestCase):
    def test_mutant_builds_skip_candidate_unit_test_commands(self):
        calls = []

        def fake_stream(argv, *, cwd, environment, output_directory, timeout_seconds):
            calls.append(list(argv))
            output = Path(output_directory)
            output.mkdir(parents=True, exist_ok=True)
            if "build-for-testing" in argv:
                derived = Path(argv[argv.index("-derivedDataPath") + 1])
                app = derived / "Build/Products/Debug-iphonesimulator/NativeContractDemo.app"
                app.mkdir(parents=True)
                (derived / "Build/Products/NativeContractDemo.xctestrun").write_text("fixture")
            if any("assembleDebug" in argument for argument in argv):
                app_apk = Path(cwd) / "apps/android-demo/app/build/outputs/apk/debug/app-debug.apk"
                test_apk = Path(cwd) / "apps/android-demo/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
                library_jar = Path(cwd) / "apps/android-demo/app/build/contract-async/libs/contract-async-1.0.0.jar"
                for path in (app_apk, test_apk, library_jar):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"build fixture")
            return {"exitCode": 0, "timedOut": False}

        with tempfile.TemporaryDirectory(prefix="mutant-build-policy-") as temporary:
            root = Path(temporary)
            ios_output = root / "ios-output"
            with patch.object(controller, "run_streaming_command", side_effect=fake_stream):
                controller._build_ios_candidate(
                    root, ios_output, "owned-ios", {}, 20, run_candidate_unit_tests=False
                )
                android = controller._build_android_candidate(
                    root, root / "android-output", {}, 20,
                    gradle_home=root / "gradle-home", run_candidate_unit_tests=False,
                )

        ios_commands = [argv for argv in calls if "-project" in argv]
        android_commands = [argv for argv in calls if "-p" in argv]
        self.assertEqual(len(ios_commands), 1)
        self.assertIn("build-for-testing", ios_commands[0])
        self.assertNotIn("test", ios_commands[0])
        self.assertEqual(len(android_commands), 1)
        self.assertNotIn(":app:testDebugUnitTest", android_commands[0])
        self.assertTrue(android["appApk"].endswith("app-debug.apk"))

    def test_controls_build_once_per_mutation_and_bind_actual_hash_per_control(self):
        controls = json.loads((ROOT / "integration/control-scenarios.json").read_text())["controls"]
        build_hashes = {
            "N1-stale-payload-commit": "1" * 64,
            "N2-duplicate-deferred-clear": "2" * 64,
            "N3-unverified-auth-publication": "3" * 64,
            "N4-false-logout-ack": "4" * 64,
        }
        build_calls = []
        run_calls = []

        def prepare(**kwargs):
            return {
                "mutationId": kwargs["mutation_id"],
                "platform": kwargs["platform"],
                "workspaceSourceSha256": "f" * 64,
                "matrixSha256": "e" * 64,
                "patchManifest": {"mutationId": kwargs["mutation_id"]},
                "patchedPlatformSource": {"path": "coordinator", "materializedSha256": "d" * 64},
                "helper": None,
                "candidateUnitTestPolicy": {"workspaceSourceTests": "included", "execution": "skipped-for-mutant-witness-build"},
            }

        def build(candidate, output, device, environment, timeout_seconds, *, run_candidate_unit_tests):
            mutation_id = Path(output).name
            build_calls.append((mutation_id, run_candidate_unit_tests))
            return {"buildHash": build_hashes[mutation_id]}

        def run_group(**kwargs):
            mutation_id = kwargs["mutation_id"]
            group = kwargs["scenario_rows"]
            run_calls.append((mutation_id, [row["id"] for row in group]))
            digest = "sha256:" + build_hashes[mutation_id]
            cases = [
                {
                    "scenarioId": row["id"],
                    "variantId": None,
                    "classification": "SEMANTIC_FAIL",
                    "violations": [],
                    "missingObservations": [],
                    "traceBinding": {"scenarioId": row["id"], "variantId": None, "buildHash": digest},
                }
                for row in group
            ]
            return {
                "classification": "SEMANTIC_FAIL",
                "requiredScenarioIds": [row["id"] for row in group],
                "completedScenarioIds": [row["id"] for row in group],
                "missingScenarioIds": [],
                "traceBindings": [
                    {"platform": "ios", "scenarioId": row["id"], "variantId": None, "buildHash": digest}
                    for row in group
                ],
                "_caseResults": cases,
                "_traceRows": [],
                "_serverRows": [],
                "_uiRows": [],
                "_controllerRows": [],
                "_screenshotRows": [],
            }

        base_result = {
            "version": 1,
            "platform": "ios",
            "deviceId": "owned-ios",
            "deviceHash": "a" * 64,
            "deviceDetails": {"udid": "owned-ios"},
            "requiredScenarioIds": [row["id"] for row in controls],
            "commands": [],
        }
        with tempfile.TemporaryDirectory(prefix="control-mutation-routing-") as temporary:
            output = Path(temporary) / "ios"
            output.mkdir()
            with patch.object(controller, "prepare_mutation_workspace", side_effect=prepare), patch.object(
                controller, "_build_ios_candidate", side_effect=build
            ), patch.object(controller, "_run_native_platform", side_effect=run_group), patch.object(
                controller, "_probe_ios_acceptance_runtime",
                return_value=([], {
                    "version": "18.2",
                    "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-2",
                    "isAvailable": True,
                }),
            ):
                result = controller._run_mutation_control_platform(
                    platform="ios",
                    candidate=ROOT,
                    output=output,
                    device="owned-ios",
                    stage_id="integration-controls",
                    attempt_id="control-attempt",
                    scenario_rows=controls,
                    scenario_path=ROOT / "integration/control-scenarios.json",
                    scenario_bytes=(ROOT / "integration/control-scenarios.json").read_bytes(),
                    base_result=base_result,
                    command_runner=subprocess.run,
                    timeout_seconds=300,
                )
            report = json.loads((output / "platform-report.json").read_text())
            case_rows = json.loads((output / "scenario-results.json").read_text())["cases"]

        self.assertEqual({mutation_id for mutation_id, _ in build_calls}, set(build_hashes))
        self.assertTrue(all(run_candidate_tests is False for _, run_candidate_tests in build_calls))
        self.assertEqual(len(build_calls), 4)
        self.assertEqual(len(run_calls), 4)
        n1_controls = {control_id for mutation_id, control_ids in run_calls if mutation_id == "N1-stale-payload-commit" for control_id in control_ids}
        self.assertEqual(n1_controls, {"CTRL-N1-LOGOUT", "CTRL-N1-NEW-LOGIN"})
        self.assertIsNone(result["buildHash"])
        self.assertEqual(result["scenarioBuildHashes"]["CTRL-N1-LOGOUT"], result["scenarioBuildHashes"]["CTRL-N1-NEW-LOGIN"])
        self.assertEqual(
            result["scenarioBuildHashes"]["CTRL-N2-LATE-CLEAR"],
            "sha256:" + build_hashes["N2-duplicate-deferred-clear"],
        )
        self.assertEqual(report["buildHash"], None)
        self.assertEqual({row["scenarioId"]: row["buildHash"] for row in case_rows}, result["scenarioBuildHashes"])
        self.assertEqual(report["mutationBuilds"][0]["classification"], "BUILD_READY")
        self.assertEqual(
            report["mutationBuilds"][0]["candidateUnitTestPolicy"],
            {"workspaceSourceTests": "included", "execution": "skipped-for-mutant-witness-build"},
        )
        self.assertNotIn("unit-tests", report["mutationBuilds"][0]["buildCommands"])

    def test_only_owned_processes_stopped(self):
        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
                self.terminated = False
                self.waited = False
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True

            def wait(self, timeout):
                self.waited = True
                self.returncode = 0
                return 0

        owned = FakeProcess(101)
        unrelated = FakeProcess(202)

        controller.stop_owned_processes([owned])

        self.assertTrue(owned.terminated)
        self.assertTrue(owned.waited)
        self.assertFalse(unrelated.terminated)


class NativeStatusStreamTests(unittest.TestCase):
    def status(self, **overrides):
        payload = {
            "scenarioId": "APP-02",
            "processInstanceId": "attempt-01/APP-02/p1",
            "checkpointName": "APP-02-after-logout-store",
            "phase": "probeCaptured",
            "command": "Logout",
            "lastProcessedCommandId": "4",
            "lastProcessedProcessInstanceId": "attempt-01/APP-02/p1",
            "redactedObservation": '{"kind":"Absent"}',
        }
        payload.update(overrides)
        return payload

    def test_ios_status_line_is_parsed_with_strict_identity_and_redaction(self):
        payload = self.status()
        line = "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(payload, sort_keys=True)

        parsed = controller.parse_ios_status_line(
            line,
            expected_scenario_id="APP-02",
            expected_process_instance_id="attempt-01/APP-02/p1",
        )

        self.assertEqual(parsed, payload)
        with self.assertRaises(ValueError):
            controller.parse_ios_status_line(
                line,
                expected_scenario_id="APP-02",
                expected_process_instance_id="attempt-01/APP-02/p2",
            )
        with self.assertRaises(ValueError):
            controller.parse_ios_status_line(
                "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(self.status(redactedObservation='{"kind":"Absent","token":"demo-A-v4"}')),
                expected_scenario_id="APP-02",
                expected_process_instance_id="attempt-01/APP-02/p1",
            )

    def test_ios_probe_envelope_is_process_bound_without_matching_the_host_step_id(self):
        process_id = "attempt-01/APP-02/p1"
        payload = self.status(
            checkpointName="storeProbe.APP-02-after-logout-store",
            redactedObservation=json.dumps({
                "probeId": "native-probe-7",
                "processInstanceId": process_id,
                "observation": {"kind": "Absent"},
            }),
        )
        parsed = controller.parse_ios_status_line(
            "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(payload, sort_keys=True),
            expected_scenario_id="APP-02",
            expected_process_instance_id=process_id,
        )
        self.assertEqual(parsed["checkpointName"], "storeProbe.APP-02-after-logout-store")

        ui_source = (ROOT / "apps/ios-demo/NativeContractDemoUITests/ScenarioUITests.swift").read_text()
        capture_start = ui_source.index("private func captureStoreProbe(")
        capture_end = ui_source.index("@discardableResult", capture_start)
        capture = ui_source[capture_start:capture_end]
        self.assertNotIn("value.contains(probeID)", capture)
        self.assertIn("validRedactedProbeEnvelope", capture)
        self.assertIn("previousProbeID", capture)
        self.assertIn("probeIDsByProcess", capture)
        # E7: an empty-string value (iOS 18 SwiftUI static text) must fall back to the label.
        self.assertIn("(state.value as? String).flatMap { $0.isEmpty ? nil : $0 } ?? state.label", ui_source)
        self.assertNotIn("state.value as? String ?? state.label", ui_source)

    def test_ios_probe_progress_rejects_reused_id_until_a_new_probe_arrives(self):
        process_id = "attempt-01/APP-02/p1"
        bridge = controller.NativeProgressBridge(
            platform="ios",
            run=object(),
            device="owned-simulator",
            attempt_id="attempt-01",
            scenario={"id": "APP-02"},
            variant=None,
            controller_events=[],
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/native-probe-freshness-test",
        )
        status = self.status(
            processInstanceId=process_id,
            redactedObservation=json.dumps({
                "probeId": "native-probe-1",
                "processInstanceId": process_id,
                "observation": {"kind": "Absent"},
            }),
        )
        self.assertEqual(bridge._accept_new_probe_id(status), "native-probe-1")
        with self.assertRaisesRegex(ValueError, "probeId was reused"):
            bridge._accept_new_probe_id(status)
        status["redactedObservation"] = json.dumps({
            "probeId": "native-probe-2",
            "processInstanceId": process_id,
            "observation": {"kind": "Present", "account": "A", "version": 0},
        })
        self.assertEqual(bridge._accept_new_probe_id(status), "native-probe-2")

    def test_hook_release_binds_only_to_the_observed_native_event_reference(self):
        process_id = "attempt-01/APP-12-SAVED/p2"
        events = []
        bridge = controller.NativeProgressBridge(
            platform="ios",
            run=object(),
            device="owned-simulator",
            attempt_id="attempt-01",
            scenario={"id": "APP-12-SAVED"},
            variant=None,
            controller_events=events,
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/native-hook-link-test",
        )
        bridge._record_hook_status({
            "processInstanceId": process_id,
            "hookPoint": "beforeBootstrapClear",
            "hookPhase": "released",
            "hookArmSequence": "37",
            "authMailboxPaused": True,
        })
        release = events[0]
        self.assertNotIn("eventRef", release)

        bridge.bind_native_events([{
            "kind": "hookEvent",
            "processInstanceId": process_id,
            "localSequence": 37,
            "launchOrdinal": 2,
            "actionId": 37,
            "point": "beforeBootstrapClear",
            "phase": "released",
            "target": "bootstrap",
        }])

        self.assertEqual(release["eventRef"], {"processInstanceId": process_id, "localSequence": 37})

    def test_bound_hook_arrival_events_stay_within_the_checker_controller_schema(self):
        from integration import check

        process_id = "attempt-01/APP-12-SAVED/p2"
        events = []
        bridge = controller.NativeProgressBridge(
            platform="android",
            run=object(),
            device="emulator-5580",
            attempt_id="attempt-01",
            scenario={"id": "APP-12-SAVED"},
            variant=None,
            controller_events=events,
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/native-hook-arrival-schema-test",
        )
        bridge._record_hook_status({
            "processInstanceId": process_id,
            "hookPoint": "beforeBootstrapClear",
            "hookPhase": "arrived",
            "hookArmSequence": "1",
            "authMailboxPaused": "true",
        })
        bridge.bind_native_events([{
            "kind": "hookEvent",
            "processInstanceId": process_id,
            "localSequence": 5,
            "launchOrdinal": 2,
            "actionId": 1,
            "point": "beforeBootstrapClear",
            "phase": "arrived",
            "target": "bootstrap",
            "commandRef": {"processInstanceId": process_id, "id": 1},
        }])

        self.assertEqual(["hookArrived", "bootstrapHookArrived"], [event["kind"] for event in events])
        self.assertEqual({"processInstanceId": process_id, "localSequence": 5}, events[0]["eventRef"])
        for event in events:
            required, allowed = check.CONTROLLER_FIELDS[event["kind"]]
            self.assertTrue(required <= set(event), event)
            self.assertEqual(set(), set(event) - allowed, event)
            self.assertIs(True, event["authMailboxPaused"])

    def test_android_status_field_glued_to_the_runner_class_banner_is_not_dropped(self):
        parser = controller.AndroidInstrumentationStatusParser(
            expected_scenario_id="APP-12-SAVED",
            expected_process_instance_id="attempt-01/APP-12-SAVED/p2",
        )
        # Observed `am instrument -w` output: the first status field of a run is
        # printed on the same line as the test class banner.
        lines = [
            "nativecontract.demo.ScenarioInstrumentedTest:INSTRUMENTATION_STATUS: authMailboxPaused=true\n",
            "INSTRUMENTATION_STATUS: scenarioId=APP-12-SAVED\n",
            "INSTRUMENTATION_STATUS: processInstanceId=attempt-01/APP-12-SAVED/p2\n",
            "INSTRUMENTATION_STATUS: checkpointName=hookArrived.beforeBootstrapClear\n",
            "INSTRUMENTATION_STATUS: phase=hookArrived\n",
            "INSTRUMENTATION_STATUS: hookPoint=beforeBootstrapClear\n",
            "INSTRUMENTATION_STATUS: hookPhase=arrived\n",
            "INSTRUMENTATION_STATUS: hookTarget=bootstrap\n",
            "INSTRUMENTATION_STATUS: hookArmSequence=1\n",
            "INSTRUMENTATION_STATUS_CODE: 2\n",
        ]

        results = [result for line in lines if (result := parser.feed(line)) is not None]

        self.assertEqual(1, len(results))
        self.assertEqual("true", results[0]["authMailboxPaused"])

    def test_receipt_status_has_no_placeholder_event_ref_before_native_binding(self):
        process_id = "attempt-01/APP-02/p1"
        events = []
        bridge = controller.NativeProgressBridge(
            platform="ios",
            run=object(),
            device="owned-simulator",
            attempt_id="attempt-01",
            scenario={"id": "APP-02"},
            variant=None,
            controller_events=events,
            observations=[],
            process_artifact_directory=ROOT / "reports/standalone/native-receipt-link-test",
        )
        bridge({
            "scenarioId": "APP-02",
            "processInstanceId": process_id,
            "checkpointName": "receipt.1",
            "phase": "receiptObserved",
            "lastProcessedCommandId": "1",
        })
        self.assertNotIn("eventRef", events[0])

        bridge.bind_native_events([{
            "kind": "commandReceipt",
            "processInstanceId": process_id,
            "localSequence": 43,
            "commandRef": {"processInstanceId": process_id, "id": 1},
        }])
        self.assertEqual(events[0]["eventRef"], {"processInstanceId": process_id, "localSequence": 43})

    def test_android_instrumentation_status_blocks_stream_redacted_payload(self):
        parser = controller.AndroidInstrumentationStatusParser(
            expected_scenario_id="APP-02",
            expected_process_instance_id="attempt-01/APP-02/p1",
        )
        lines = [
            "INSTRUMENTATION_STATUS: class=nativecontract.demo.ScenarioInstrumentedTest\n",
            "INSTRUMENTATION_STATUS: scenarioId=APP-02\n",
            "INSTRUMENTATION_STATUS: processInstanceId=attempt-01/APP-02/p1\n",
            "INSTRUMENTATION_STATUS: checkpointName=APP-02-after-logout-store\n",
            "INSTRUMENTATION_STATUS: phase=probeRequested\n",
            "INSTRUMENTATION_STATUS: command=Logout\n",
            "INSTRUMENTATION_STATUS: lastProcessedCommandId=4\n",
            "INSTRUMENTATION_STATUS: lastProcessedProcessInstanceId=attempt-01/APP-02/p1\n",
            "INSTRUMENTATION_STATUS: redactedProbe={\"kind\":\"Absent\"}\n",
            "INSTRUMENTATION_STATUS_CODE: 2\n",
        ]

        results = [result for line in lines if (result := parser.feed(line)) is not None]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["phase"], "probeRequested")
        self.assertEqual(results[0]["redactedProbe"], '{"kind":"Absent"}')

    def test_effect_wait_status_requires_references_and_host_ack_binds_live_readback(self):
        process_id = "attempt-01/CTRL-N2-LATE-CLEAR/p1"
        origin = {"processInstanceId": process_id, "id": 4}
        status = {
            "scenarioId": "CTRL-N2-LATE-CLEAR",
            "processInstanceId": process_id,
            "checkpointName": "detachedEffectAwaited.late-clear-1",
            "phase": "effectAwaitRequested",
            "effectId": "late-clear-1",
            "effectOriginCommandRef": json.dumps(origin, sort_keys=True),
        }
        parsed = controller.parse_ios_status_line(
            "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(status, sort_keys=True),
            expected_scenario_id="CTRL-N2-LATE-CLEAR",
            expected_process_instance_id=process_id,
        )
        self.assertEqual(parsed, status)
        invalid = dict(status, effectOriginCommandRef=json.dumps({"processInstanceId": process_id, "id": 0}))
        with self.assertRaisesRegex(ValueError, "process-scoped command"):
            controller.parse_ios_status_line(
                "NATIVE_CONTRACT_STATUS_V1 " + json.dumps(invalid),
                expected_scenario_id="CTRL-N2-LATE-CLEAR",
                expected_process_instance_id=process_id,
            )

        events = [
            {"kind": "commandEnqueued", "processInstanceId": process_id, "commandRef": origin, "name": "Logout"},
            {"kind": "detachedStoreMutation", "processInstanceId": process_id, "localSequence": 18,
             "effectId": "late-clear-1", "originCommandRef": origin, "operation": "clear",
             "before": {"kind": "Present", "account": "B", "version": 0}, "after": {"kind": "Absent"}},
            {"kind": "detachedStoreReadback", "processInstanceId": process_id, "localSequence": 19,
             "effectId": "late-clear-1", "originCommandRef": origin, "operation": "clear",
             "observation": {"kind": "Absent"}},
        ]

        class FakeRun:
            def __init__(self):
                self.checkpoints = []

            def publish_checkpoint(self, process_instance_id, name, *, timeout=5):
                self.checkpoints.append((process_instance_id, name))

        fake_run = FakeRun()
        controller_events = []
        with patch("integration.controller.read_live_native_events", return_value=events):
            bridge = controller.NativeProgressBridge(
                platform="ios",
                run=fake_run,
                device="OWNED-UUID",
                attempt_id="attempt-01",
                scenario={"effects": [{"effectId": "late-clear-1", "originCommandRef": {"command": "Logout", "launchOrdinal": 1}}]},
                variant=None,
                controller_events=controller_events,
                observations=[],
                process_artifact_directory=ROOT / "reports/standalone/task3/native-effect-test",
            )
            bridge(status)
        self.assertEqual(fake_run.checkpoints, [(process_id, "detachedEffectAwaited.late-clear-1")])
        acknowledgement = controller_events[0]
        self.assertEqual(acknowledgement["kind"], "detachedEffectAwaited")
        self.assertEqual(acknowledgement["mutationEventRef"]["localSequence"], 18)
        self.assertEqual(acknowledgement["readbackEventRef"]["localSequence"], 19)

    def test_streaming_command_parses_status_and_redacts_subprocess_output(self):
        payload = self.status()
        code = (
            "import json; "
            f"print('NATIVE_CONTRACT_STATUS_V1 ' + json.dumps({payload!r}, sort_keys=True), flush=True); "
            "print('accessToken=demo-' + 'A-v7', flush=True)"
        )
        observed = []
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            result = controller.run_streaming_command(
                [sys.executable, "-c", code],
                cwd=ROOT,
                environment=os.environ.copy(),
                output_directory=Path(temporary) / "command",
                timeout_seconds=5,
                status_parser=lambda line: controller.parse_ios_status_line(
                    line,
                    expected_scenario_id="APP-02",
                    expected_process_instance_id="attempt-01/APP-02/p1",
                ),
                on_status=observed.append,
            )
            stdout = (Path(result["stdoutPath"])).read_text()

        self.assertEqual(result["exitCode"], 0)
        self.assertFalse(result["timedOut"])
        self.assertEqual(observed, [payload])
        self.assertNotIn("demo-A-v7", stdout)
        self.assertIn("<redacted>", stdout)

    def test_owned_loopback_run_keeps_control_capability_out_of_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            output = Path(temporary) / "case"
            with controller.LoopbackRun(
                candidate=ROOT,
                output=output,
                platform="ios",
                scenario_id="APP-12-SAVED",
                attempt_id="attempt-01",
            ) as run:
                process_id = "attempt-01/APP-12-SAVED/p2"
                self.assertEqual(run.base_url, f"http://127.0.0.1:{run.port}")
                published = run.publish_checkpoint(process_id, "bootstrapStoreProbed")
                self.assertEqual(published, {"version": 1, "ready": True})
                events, body_digests = run.events()
                self.assertEqual([event["kind"] for event in events], ["checkpointPublished"])
                self.assertEqual(body_digests, [])
                control_key = run._control_key

            self.assertIsNone(run._control_key)
            persisted = b"".join(
                path.read_bytes() for path in output.rglob("*") if path.is_file()
            )
            self.assertNotIn(control_key.encode("utf-8"), persisted)

    def test_loopback_delivery_releases_only_matching_held_request(self):
        clients = []
        client_results = {}
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            with controller.LoopbackRun(
                candidate=ROOT,
                output=Path(temporary) / "case",
                platform="ios",
                scenario_id="APP-02",
                attempt_id="attempt-01",
            ) as run:
                process_id = "attempt-01/APP-02/p1"
                def request_refresh(issuance_id, request_id):
                    request_tag = process_id + f":refresh:{issuance_id}"
                    request_body = json.dumps({
                        "version": 1,
                        "runId": run.run_id,
                        "requestTag": request_tag,
                        "requestId": str(request_id),
                        "account": "A",
                        "refreshToken": "demo-A-v0",
                    }).encode("utf-8")
                    request = Request(run._url("/v1/refresh"), data=request_body, headers={"Content-Type": "application/json"})
                    try:
                        with urlopen(request, timeout=5) as response:
                            response.read()
                            client_results[issuance_id] = response.status
                    except Exception as error:
                        client_results[issuance_id] = getattr(error, "code", type(error).__name__)

                for issuance_id, request_id in ((3, 1), (4, 2)):
                    client = threading.Thread(target=request_refresh, args=(issuance_id, request_id), daemon=True)
                    client.start()
                    clients.append(client)
                controller_events = []
                known_server_sequences = set()
                selected_tag, server_events = controller.release_pending_delivery(
                    run,
                    command="Deliver(current,success)",
                    variant=None,
                    process_instance_id=process_id,
                    wire_tag=process_id + ":refresh:4",
                    controller_events=controller_events,
                    known_server_sequences=known_server_sequences,
                )
                clients[1].join(timeout=5)
                self.assertFalse(clients[1].is_alive())
                self.assertEqual(client_results[4], 200)
                self.assertEqual(selected_tag, process_id + ":refresh:4")
                self.assertEqual(
                    [event["kind"] for event in controller_events],
                    ["requestHeld", "requestHeld", "releaseRequested", "releaseAccepted", "responseWritten"],
                )
                self.assertEqual([event["kind"] for event in server_events], ["requestHeld", "requestHeld", "releaseAccepted", "responseWritten"])
                self.assertEqual([row["requestTag"] for row in run.pending()], [process_id + ":refresh:3"])
        for client in clients:
            client.join(timeout=5)
        self.assertFalse(any(client.is_alive() for client in clients))

    def test_delivery_slot_selection_uses_exact_wire_tag_and_fails_ambiguous_current(self):
        p1 = "attempt-01/APP-07/p1"
        p2 = "attempt-01/APP-07/p2"
        native_events = [
            {"kind": "slotIssued", "processInstanceId": p1, "localSequence": 1, "commandRef": {"processInstanceId": p1, "id": 3}, "slotId": "slot-A1", "wireTag": p1 + ":refresh:3"},
            {"kind": "slotIssued", "processInstanceId": p1, "localSequence": 2, "commandRef": {"processInstanceId": p1, "id": 4}, "slotId": "slot-A2", "wireTag": p1 + ":refresh:4"},
            {"kind": "slotIssued", "processInstanceId": p2, "localSequence": 1, "commandRef": {"processInstanceId": p2, "id": 3}, "slotId": "slot-A1", "wireTag": p2 + ":refresh:3"},
        ]

        self.assertEqual(
            controller._wire_tag_for_delivery(
                native_events,
                process_instance_id=p1,
                scenario={"expectedDeliveries": [{"slotId": "slot-A1", "outcome": "success"}]},
                variant=None,
                command="Deliver(current,success)",
            ),
            p1 + ":refresh:3",
        )
        with self.assertRaises(ValueError):
            controller._wire_tag_for_delivery(
                native_events,
                process_instance_id=p1,
                scenario={},
                variant=None,
                command="Deliver(current,success)",
            )

    def test_bootstrap_probe_is_saved_before_server_checkpoint_ack(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            output = Path(temporary) / "case"
            with controller.LoopbackRun(
                candidate=ROOT,
                output=output,
                platform="ios",
                scenario_id="APP-12-SAVED",
                attempt_id="attempt-01",
            ) as run:
                process_id = "attempt-01/APP-12-SAVED/p2"
                status = {
                    "scenarioId": "APP-12-SAVED",
                    "processInstanceId": process_id,
                    "checkpointName": "bootstrapStoreProbed",
                    "phase": "probeCaptured",
                    "command": "",
                    "redactedObservation": json.dumps({"probeId": "bootstrapStoreProbed", "processInstanceId": process_id, "observation": {"kind": "Present", "account": "A", "version": 0}}),
                }
                observations = []
                events = []
                known = set()
                row = controller.capture_probe_status(
                    run,
                    platform="ios",
                    serial="unused-ios-uuid",
                    attempt_id="attempt-01",
                    status=status,
                    required_probe_ids=["APP-12-p2-before-bootstrap-clear"],
                    observations=observations,
                    controller_events=events,
                    known_server_sequences=known,
                    process_artifact_directory=output / "APP-12-SAVED" / "p2",
                )
                self.assertEqual(row["observation"], {"kind": "Present", "account": "A", "version": 0})
                saved = (output / "APP-12-SAVED" / "p2" / "ui.jsonl").read_text()
                self.assertIn("APP-12-p2-before-bootstrap-clear", saved)
                self.assertEqual([event["kind"] for event in events], ["probeCaptured", "checkpointPublished"])
                self.assertTrue(run._request(
                    "GET",
                    f"/v1/checkpoints?runId={run.run_id}&processInstanceId={process_id}&name=bootstrapStoreProbed",
                )["ready"])

    def test_rendered_status_maps_accessible_projection_and_revision(self):
        raw = json.dumps({
            "session-state": "Signed in · demo-A",
            "credential-status": "demo-A version 0",
            "view-process-id": "attempt-01/APP-02/p1",
            "view-revision": "4",
            "last-command-id": "4",
            "last-command-status": "Completed",
        })

        projection = controller.parse_rendered_state(raw, process_instance_id="attempt-01/APP-02/p1")

        self.assertEqual(projection, {"phase": "SignedIn", "account": "A", "revision": 4})

    def test_rendered_view_binds_by_revision_phase_and_account_not_stale_last_command(self):
        process_id = "attempt-01/CTRL-N3-EARLY-PUBLISH/p1"
        rendered = json.dumps({
            "session-state": "Refreshing · demo-A",
            "credential-status": "Refresh pending for demo-A",
            "view-process-id": process_id,
            "view-revision": "4",
            "last-command-id": "3",
            "last-command-status": "Completed",
        })
        observations = []
        with tempfile.TemporaryDirectory(prefix="rendered-view-provenance-") as temporary:
            bridge = controller.NativeProgressBridge(
                platform="ios",
                run=object(),
                device="owned-simulator",
                attempt_id="attempt-01",
                scenario={"id": "CTRL-N3-EARLY-PUBLISH"},
                variant=None,
                controller_events=[],
                observations=observations,
                process_artifact_directory=Path(temporary),
            )
            bridge({
                "scenarioId": "CTRL-N3-EARLY-PUBLISH",
                "processInstanceId": process_id,
                "checkpointName": "renderedView.CTRL-N3-rendered-a1",
                "phase": "rendered",
                "renderedState": rendered,
            })
            bridge.bind_native_events([{
                "kind": "uiPublishAck",
                "processInstanceId": process_id,
                "localSequence": 44,
                "commandRef": {"processInstanceId": process_id, "id": 4},
                "revision": 4,
                "view": {"phase": "Refreshing", "account": "A"},
            }])

        self.assertEqual(observations[0]["eventRef"], {"processInstanceId": process_id, "localSequence": 44})


class IndependentAndroidProbeTests(unittest.TestCase):
    def runner_for(self, filenames, payload=b"", *, cat_exit=0):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if "ls" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="\n".join(filenames), stderr="")
            return subprocess.CompletedProcess(argv, cat_exit, stdout=payload, stderr="")

        return run, calls

    def test_android_host_probe_reads_owned_atomicfile_and_discards_raw_blob(self):
        raw = b'{"account":"A","version":7,"accessToken":"demo-A-v7","refreshToken":"demo-A-v7"}'
        runner, calls = self.runner_for(["credential.json"], raw)

        observation = controller.read_android_storage_probe(
            serial="emulator-owned", attempt_id="attempt-01", scenario_id="APP-02", command_runner=runner
        )

        self.assertEqual(observation, {"kind": "Present", "account": "A", "version": 7})
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(any("attempt-01" in token for token in call) for call in calls))
        self.assertFalse(any("demo-A-v7" in token for call in calls for token in call))

    def test_android_host_probe_distinguishes_absent_from_atomic_sidecars(self):
        empty_runner, _ = self.runner_for([])
        sidecar_runner, _ = self.runner_for(["credential.json.bak"])

        absent = controller.read_android_storage_probe(
            serial="emulator-owned", attempt_id="attempt-01", scenario_id="APP-02", command_runner=empty_runner
        )
        sidecar = controller.read_android_storage_probe(
            serial="emulator-owned", attempt_id="attempt-01", scenario_id="APP-02", command_runner=sidecar_runner
        )

        self.assertEqual(absent, {"kind": "Absent"})
        self.assertEqual(sidecar, {"kind": "Unknown", "errorCode": "atomicSidecarPresent"})


class AndroidApp12ControllerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.scenario = next(
            row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
            if row["id"] == "APP-12-SAVED"
        )
        self.plan = controller.build_android_app12_plan(
            serial="emulator-owned-35",
            app_apk="/attempt/app-debug.apk",
            test_apk="/attempt/app-debug-androidTest.apk",
            attempt_id="attempt-01",
            run_id="run-opaque",
            base_url="http://10.0.2.2:43217",
            scenario=self.scenario,
            scenario_inventory_sha256=hashlib.sha256((ROOT / "integration/scenarios.json").read_bytes()).hexdigest(),
            control_inventory_sha256=hashlib.sha256((ROOT / "integration/control-scenarios.json").read_bytes()).hexdigest(),
        )

    def test_app12_installs_once_and_never_pm_clears(self):
        install = self.plan["installationCommands"]
        launches = self.plan["launches"]

        self.assertEqual(len(install), 2)
        self.assertTrue(all(command[:5] == ["adb", "-s", "emulator-owned-35", "install", "-r"] for command in install))
        self.assertEqual([command[-1] for command in install], ["/attempt/app-debug.apk", "/attempt/app-debug-androidTest.apk"])
        self.assertEqual(len(launches), 2)
        all_lifecycle_commands = [*install, launches[0]["argv"], self.plan["forceStopCommand"], self.plan["pidofCommand"], launches[1]["argv"]]
        rendered = [" ".join(command) for command in all_lifecycle_commands]
        self.assertEqual(sum(command[:4] == ["adb", "-s", "emulator-owned-35", "install"] for command in all_lifecycle_commands), 2)
        self.assertFalse(any("pm clear" in command or "uninstall" in command for command in rendered))
        self.assertIn("force-stop", self.plan["forceStopCommand"])

    def test_instrumentation_exit_is_not_process_death_evidence(self):
        result = controller.android_process_termination_evidence(
            instrumentation_exit_code=0,
            force_stop_exit_code=None,
            pidof_exit_code=None,
            pidof_stdout=None,
        )

        self.assertFalse(result["terminated"])
        self.assertIn("force-stop acknowledgement", result["missing"])
        self.assertIn("empty pidof result", result["missing"])

        confirmed = controller.android_process_termination_evidence(
            instrumentation_exit_code=0,
            force_stop_exit_code=0,
            pidof_exit_code=0,
            pidof_stdout="\n",
        )
        self.assertTrue(confirmed["terminated"])

    def test_app12_new_process_namespace_keeps_store_namespace(self):
        p1, p2 = self.plan["launches"]

        self.assertEqual((p1["launchOrdinal"], p2["launchOrdinal"]), (1, 2))
        self.assertNotEqual(p1["processInstanceId"], p2["processInstanceId"])
        self.assertEqual(p1["processInstanceId"], "attempt-01/APP-12-SAVED/p1")
        self.assertEqual(p2["processInstanceId"], "attempt-01/APP-12-SAVED/p2")
        self.assertEqual(p1["storageNamespace"], "test-attempt-01/APP-12-SAVED")
        self.assertEqual(p1["storageNamespace"], p2["storageNamespace"])
        self.assertEqual((p1["scenarioPhase"], p2["scenarioPhase"]), ("seed", "resume"))
        self.assertEqual(p2["armPoint"], "beforeBootstrapClear")
        self.assertIn("scenarioInventorySha256", p1["argv"])
        self.assertIn("controlInventorySha256", p1["argv"])
        self.assertEqual(p1["argv"][p1["argv"].index("scenarioInventorySha256") + 1], hashlib.sha256((ROOT / "integration/scenarios.json").read_bytes()).hexdigest())


    def test_bootstrap_probe_precedes_clear_release(self):
        p2 = self.plan["launches"][1]["processInstanceId"]
        events = [
            {"sequence": 1, "kind": "bootstrapHookArrived", "processInstanceId": p2},
            {"sequence": 2, "kind": "probeCaptured", "processInstanceId": p2, "stepId": "APP-12-p2-before-bootstrap-clear", "observation": {"kind": "Present", "account": "A", "version": 0}},
            {"sequence": 3, "kind": "checkpointPublished", "processInstanceId": p2, "name": "bootstrapStoreProbed"},
            {"sequence": 4, "kind": "hookReleased", "processInstanceId": p2, "point": "beforeBootstrapClear", "releaseChannel": "DebugScenarioControl", "authMailboxPaused": True, "bootstrapReceiptObserved": False},
            {"sequence": 5, "kind": "bootstrapCleared", "processInstanceId": p2},
        ]

        result = controller.validate_app12_bootstrap_protocol(events, p2)

        self.assertEqual(result["classification"], "PASS")
        reversed_events = [events[0], events[3], events[1], events[2], events[4]]
        reversed_result = controller.validate_app12_bootstrap_protocol(reversed_events, p2)
        self.assertEqual(reversed_result["classification"], "INVALID_HISTORY")

    def test_control_release_bypasses_paused_mailbox(self):
        p2 = self.plan["launches"][1]["processInstanceId"]
        events = [
            {"sequence": 1, "kind": "bootstrapHookArrived", "processInstanceId": p2, "authMailboxPaused": True},
            {"sequence": 2, "kind": "hookReleased", "processInstanceId": p2, "point": "beforeBootstrapClear", "releaseChannel": "DebugScenarioControl", "authMailboxPaused": True, "bootstrapReceiptObserved": False},
        ]

        result = controller.validate_app12_bootstrap_protocol(events, p2)

        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertIn("independent probe is missing", result["missingObservations"][0])

        complete = [
            events[0],
            {"sequence": 2, "kind": "probeCaptured", "processInstanceId": p2, "stepId": "APP-12-p2-before-bootstrap-clear", "observation": {"kind": "Present", "account": "A", "version": 0}},
            {"sequence": 3, "kind": "checkpointPublished", "processInstanceId": p2, "name": "bootstrapStoreProbed"},
            events[1] | {"sequence": 4},
            {"sequence": 5, "kind": "bootstrapCleared", "processInstanceId": p2},
        ]
        accepted = controller.validate_app12_bootstrap_protocol(complete, p2)
        self.assertEqual(accepted["classification"], "PASS")

        queued_release = [
            complete[0], complete[1], complete[2],
            complete[3] | {"releaseChannel": "AuthMailboxCommand", "authMailboxPaused": False},
            complete[4],
        ]
        rejected = controller.validate_app12_bootstrap_protocol(queued_release, p2)
        self.assertEqual(rejected["classification"], "INVALID_HISTORY")


class AndroidScenarioArgumentTests(unittest.TestCase):
    def test_instrumentation_argv_binds_hashed_inventories_and_selected_variant(self):
        scenario_digest = "a" * 64
        control_digest = "b" * 64
        argv = controller._android_instrumentation_argv(
            serial="emulator-owned",
            scenario_id="APP-13",
            run_id="run-opaque",
            process_instance_id="attempt-13/APP-13/p1",
            launch_ordinal=1,
            base_url="http://10.0.2.2:43217",
            scenario_phase="single",
            cancel_mode="disabled",
            scenario_inventory_sha256=scenario_digest,
            control_inventory_sha256=control_digest,
            variant_id="wrong-correlation-current",
            store_fault="none",
        )

        values = {
            argv[index + 1]: argv[index + 2]
            for index, value in enumerate(argv[:-2])
            if value == "-e"
        }
        self.assertEqual(values["scenarioInventorySha256"], scenario_digest)
        self.assertEqual(values["controlInventorySha256"], control_digest)
        self.assertEqual(values["cancelMode"], "disabled")
        self.assertEqual(values["variantId"], "wrong-correlation-current")
        self.assertEqual(values["storeFault"], "none")
        self.assertEqual(values["processInstanceId"], "attempt-13/APP-13/p1")
        self.assertEqual(argv[-1], "dev.nativecontract.demo.android.test/nativecontract.demo.DemoTestRunner")

    def test_ios_environment_binds_frozen_inventory_paths_and_variant(self):
        environment = controller._ios_launch_environment(
            scenario_id="APP-13",
            run_id="run-opaque",
            process_instance_id="attempt-13/APP-13/p1",
            launch_ordinal=1,
            base_url="http://127.0.0.1:43217",
            scenario_phase="single",
            cancel_mode="disabled",
            scenario_inventory_path=ROOT / "integration/scenarios.json",
            scenario_inventory_sha256="a" * 64,
            control_inventory_path=ROOT / "integration/control-scenarios.json",
            control_inventory_sha256="b" * 64,
            variant_id="wrong-correlation-current",
            store_fault=None,
        )

        self.assertEqual(environment["TEST_RUNNER_NATIVE_CONTRACT_SCENARIO_ID"], "APP-13")
        self.assertEqual(environment["TEST_RUNNER_NATIVE_CONTRACT_VARIANT_ID"], "wrong-correlation-current")
        self.assertEqual(environment["TEST_RUNNER_NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256"], "b" * 64)
        self.assertEqual(environment["TEST_RUNNER_NATIVE_CONTRACT_CANCEL_MODE"], "disabled")
        self.assertFalse(any(key.startswith("NATIVE_CONTRACT_") for key in environment))
        self.assertNotIn("CONTROL_KEY", "".join(environment))


class VariantCaseNamespaceTests(unittest.TestCase):
    def test_screenshot_rows_are_rebased_through_unique_variant_directories(self):
        local_path = "APP-09/p1/screenshots/APP-09-final-view.png"
        rows = []
        with tempfile.TemporaryDirectory(prefix="variant-screenshot-root-") as temporary:
            platform_root = Path(temporary) / "ios"
            for variant in ("clear-before", "clear-after-before-verify"):
                case_root = controller.case_artifact_directory(platform_root.parent, "ios", "APP-09", variant)
                screenshot = case_root / local_path
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(variant.encode("ascii"))
                digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
                rows.extend(controller.platform_screenshot_rows(
                    platform_root,
                    case_root,
                    [{"path": local_path, "sha256": digest}],
                ))

        self.assertEqual(
            [row["path"] for row in rows],
            [
                "APP-09/variants/clear-before/APP-09/p1/screenshots/APP-09-final-view.png",
                "APP-09/variants/clear-after-before-verify/APP-09/p1/screenshots/APP-09-final-view.png",
            ],
        )
        self.assertEqual(len({row["path"] for row in rows}), 2)

    def test_frozen_variant_cases_have_unique_attempt_process_and_artifact_namespaces(self):
        rows = json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
        attempt_ids = []
        process_ids = []
        artifact_roots = []
        for platform in ("ios", "android"):
            for scenario in rows:
                for variant in scenario.get("variants", []):
                    attempt_id = controller.case_attempt_id(
                        "attempt-01", platform, scenario["id"], variant["id"]
                    )
                    self.assertLessEqual(len(attempt_id), 64)
                    self.assertRegex(attempt_id, r"\A[A-Za-z0-9_-]{1,64}\Z")
                    attempt_ids.append(attempt_id)
                    process_ids.append(
                        controller.android_process_instance_id(attempt_id, scenario["id"], 1)
                    )
                    artifact_roots.append(
                        controller.case_artifact_directory(
                            Path("attempt-output"), platform, scenario["id"], variant["id"]
                        )
                    )

        self.assertEqual(len(attempt_ids), len(set(attempt_ids)))
        self.assertEqual(len(process_ids), len(set(process_ids)))
        self.assertEqual(len(artifact_roots), len(set(artifact_roots)))

    def test_nonvariant_app12_restarts_keep_one_case_storage_namespace(self):
        scenario = next(
            row for row in json.loads((ROOT / "integration/scenarios.json").read_text())["scenarios"]
            if row["id"] == "APP-12-SAVED"
        )
        attempt_id = controller.case_attempt_id("attempt-01", "android", scenario["id"])
        self.assertEqual(attempt_id, "attempt-01")
        self.assertEqual(
            controller.case_artifact_directory(Path("attempt-output"), "android", scenario["id"]),
            Path("attempt-output/android/APP-12-SAVED"),
        )
        plan = controller.build_android_app12_plan(
            serial="owned-serial",
            app_apk="app.apk",
            test_apk="test.apk",
            attempt_id=attempt_id,
            run_id="run-case",
            base_url="http://10.0.2.2:43217",
            scenario=scenario,
            scenario_inventory_sha256=hashlib.sha256((ROOT / "integration/scenarios.json").read_bytes()).hexdigest(),
            control_inventory_sha256=hashlib.sha256((ROOT / "integration/control-scenarios.json").read_bytes()).hexdigest(),
        )
        p1, p2 = plan["launches"]
        self.assertNotEqual(p1["processInstanceId"], p2["processInstanceId"])
        self.assertEqual(p1["storageNamespace"], p2["storageNamespace"])


if __name__ == "__main__":
    unittest.main()
