from pathlib import Path
import subprocess
import sys
import json
import tempfile
from unittest.mock import Mock
import unittest

from integration.ci_devices import CiDeviceBootstrap, DeviceBootstrapError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci-native-devices.py"


class FakeProcess:
    pid = 23456

    def poll(self):
        return None


class FakeNativeTools:
    udid = "A1B2C3D4-0000-4000-8000-0000000000A1"

    def __init__(self, avd_name_mismatch=False):
        self.device_name = None
        self.device_state = "Shutdown"
        self.device_deleted = False
        self.avd_name = None
        self.avd_name_mismatch = avd_name_mismatch
        self.argv = []
        self.pid_alive = True
        self.occupied_serial = False
        self.spawned = []

    def run(self, argv, **kwargs):
        self.argv.append(list(argv))
        stdout = ""
        if argv[:2] == ["xcodebuild", "-version"]:
            stdout = "Xcode 16.2\nBuild version 16C5032a\n"
        elif argv[:4] == ["xcrun", "simctl", "list", "runtimes"]:
            stdout = json.dumps({"runtimes": [{
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-2",
                "version": "18.2",
                "isAvailable": True,
            }]})
        elif argv[:3] == ["xcrun", "simctl", "create"]:
            self.device_name = argv[3]
            return subprocess.CompletedProcess(argv, 0, self.udid + "\n", "")
        elif argv[:3] == ["xcrun", "simctl", "boot"]:
            self.device_state = "Booted"
        elif argv[:3] == ["xcrun", "simctl", "bootstatus"]:
            pass
        elif argv[:3] == ["xcrun", "simctl", "shutdown"]:
            self.device_state = "Shutdown"
        elif argv[:3] == ["xcrun", "simctl", "delete"]:
            self.device_deleted = True
        elif argv[:4] == ["xcrun", "simctl", "list", "devices"]:
            stdout = json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-2": [{
                "udid": self.udid,
                "name": self.device_name,
                "state": self.device_state,
            }]}})
        elif Path(argv[0]).name == "avdmanager":
            self.avd_name = argv[argv.index("--name") + 1]
            avd_path = Path(argv[argv.index("--path") + 1])
            avd_path.mkdir(parents=True)
            avd_path.with_suffix(".ini").write_text("path=" + str(avd_path) + "\n")
        elif Path(argv[0]).name == "adb":
            if argv[1:] == ["devices", "-l"]:
                stdout = "List of devices attached\n"
                if self.occupied_serial:
                    stdout += "emulator-5580\tdevice product:foreign\n"
            elif "wait-for-device" in argv:
                pass
            elif "emu" in argv and "avd" in argv:
                stdout = ("wrong_avd" if self.avd_name_mismatch else self.avd_name) + "\nOK\n"
            elif "getprop" in argv:
                prop = argv[-1]
                stdout = {
                    "sys.boot_completed": "1\n",
                    "ro.build.version.sdk": "35\n",
                    "ro.product.cpu.abi": "x86_64\n",
                }[prop]
            else:
                raise AssertionError(f"unexpected adb command {argv}")
        elif argv[0] == "ps":
            if self.pid_alive:
                stdout = f"/sdk/emulator -avd {self.avd_name} -port 5580 -no-window\n"
            else:
                return subprocess.CompletedProcess(argv, 1, "", "")
        else:
            raise AssertionError(f"unexpected native command {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    def popen(self, argv, **kwargs):
        self.argv.append(list(argv))
        self.spawned.append(list(argv))
        return FakeProcess()


class CiNativeDeviceCliTests(unittest.TestCase):
    def test_prepare_and_cleanup_commands_are_available(self):
        for command in ("prepare", "cleanup"):
            with self.subTest(command=command):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), command, "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--output", completed.stdout)

    def test_cleanup_removes_only_recorded_avd_when_boot_never_started(self):
        with tempfile.TemporaryDirectory(prefix="ci-owned-avd-cleanup-") as directory:
            output = Path(directory)
            avd_home = output / "android" / "avd-home"
            avd_path = avd_home / "native_contract_unit_test.avd"
            avd_path.mkdir(parents=True)
            environment = {"ANDROID_AVD_HOME": str(avd_home.resolve())}
            ownership = {
                "version": 1,
                "runId": "unit-test",
                "resources": {
                    "android": {
                        "platform": "android",
                        "owned": True,
                        "avdName": "native_contract_unit_test",
                        "avdHome": str(avd_home),
                        "avdPath": str(avd_path),
                        "serial": "emulator-5580",
                        "port": 5580,
                        "pid": None,
                    }
                },
            }
            (output / "ownership.json").write_text(json.dumps(ownership))
            runner = Mock(side_effect=AssertionError("a never-started emulator must not be signalled"))
            manager = CiDeviceBootstrap(
                output=output,
                run_id="unit-test",
                platform="android",
                host_platform="linux",
                environment=environment,
                runner=runner,
            )

            result = manager.cleanup()

            self.assertEqual(result["classification"], "PASS", result)
            self.assertFalse(avd_path.exists())
            self.assertFalse(avd_home.exists())
            runner.assert_not_called()

    def test_cleanup_shuts_down_and_deletes_only_the_recorded_simulator(self):
        tools = FakeNativeTools()
        tools.device_name = "NativeContract-unit-test"
        tools.device_state = "Booted"
        with tempfile.TemporaryDirectory(prefix="ci-owned-simulator-cleanup-") as directory:
            output = Path(directory)
            ownership = {
                "version": 1,
                "runId": "unit-test",
                "resources": {
                    "ios": {
                        "platform": "ios",
                        "owned": True,
                        "udid": FakeNativeTools.udid,
                        "name": tools.device_name,
                        "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-2",
                    }
                },
            }
            (output / "ownership.json").write_text(json.dumps(ownership))
            manager = CiDeviceBootstrap(
                output=output,
                run_id="unit-test",
                platform="ios",
                host_platform="darwin",
                environment={},
                runner=tools.run,
            )

            result = manager.cleanup()

            self.assertEqual(result["classification"], "PASS", result)
            self.assertIn(["xcrun", "simctl", "shutdown", FakeNativeTools.udid], tools.argv)
            self.assertIn(["xcrun", "simctl", "delete", FakeNativeTools.udid], tools.argv)
            self.assertTrue(tools.device_deleted)

    def test_cleanup_signals_only_a_pid_whose_command_matches_owned_avd_and_port(self):
        tools = FakeNativeTools()
        tools.avd_name = "native_contract_unit_test"
        with tempfile.TemporaryDirectory(prefix="ci-owned-live-avd-cleanup-") as directory:
            output = Path(directory)
            avd_home = output / "android" / "avd-home"
            avd_path = avd_home / f"{tools.avd_name}.avd"
            avd_path.mkdir(parents=True)
            (avd_home / f"{tools.avd_name}.ini").write_text("owned\n")
            (output / "ownership.json").write_text(json.dumps({
                "version": 1,
                "runId": "unit-test",
                "resources": {"android": {
                    "platform": "android",
                    "owned": True,
                    "avdName": tools.avd_name,
                    "avdHome": str(avd_home.resolve()),
                    "avdPath": str(avd_path.resolve()),
                    "serial": "emulator-5580",
                    "port": 5580,
                    "pid": FakeProcess.pid,
                }},
            }))
            killed = []

            def kill_owned(pid):
                killed.append(pid)
                tools.pid_alive = False

            manager = CiDeviceBootstrap(
                output=output,
                run_id="unit-test",
                platform="android",
                host_platform="linux",
                environment={"ANDROID_AVD_HOME": str(avd_home.resolve())},
                runner=tools.run,
                process_killer=kill_owned,
            )

            result = manager.cleanup()

            self.assertEqual(result["classification"], "PASS", result)
            self.assertEqual(killed, [FakeProcess.pid])
            self.assertFalse(avd_path.exists())
            self.assertFalse(avd_home.exists())

    def test_cleanup_refuses_to_delete_avd_when_process_ownership_cannot_be_checked(self):
        tools = FakeNativeTools()
        avd_name = "native_contract_unit_test"
        with tempfile.TemporaryDirectory(prefix="ci-owned-avd-uncertain-cleanup-") as directory:
            output = Path(directory)
            avd_home = output / "android" / "avd-home"
            avd_path = avd_home / f"{avd_name}.avd"
            avd_path.mkdir(parents=True)
            (output / "ownership.json").write_text(json.dumps({
                "version": 1,
                "runId": "unit-test",
                "resources": {"android": {
                    "platform": "android",
                    "owned": True,
                    "avdName": avd_name,
                    "avdHome": str(avd_home.resolve()),
                    "avdPath": str(avd_path.resolve()),
                    "serial": "emulator-5580",
                    "port": 5580,
                    "pid": FakeProcess.pid,
                }},
            }))

            def missing_ps(argv, **kwargs):
                if argv[0] == "ps":
                    return subprocess.CompletedProcess(argv, 127, "", "ps unavailable")
                return tools.run(argv, **kwargs)

            manager = CiDeviceBootstrap(
                output=output,
                run_id="unit-test",
                platform="android",
                host_platform="linux",
                environment={"ANDROID_AVD_HOME": str(avd_home.resolve())},
                runner=missing_ps,
            )

            result = manager.cleanup()

            self.assertEqual(result["classification"], "INFRA_FAILURE")
            self.assertTrue(avd_path.is_dir(), "cleanup must preserve an AVD while process ownership is uncertain")

    def test_ios_prepare_binds_exact_runtime_uuid_and_ready_state(self):
        tools = FakeNativeTools()
        with tempfile.TemporaryDirectory(prefix="ci-ios-bootstrap-") as directory:
            output = Path(directory) / "ios"
            manager = CiDeviceBootstrap(
                output=output,
                run_id="workflow-123-1",
                platform="ios",
                host_platform="darwin",
                environment={},
                runner=tools.run,
            )
            env_file = Path(directory) / "github-env"
            env_file.write_text("")

            result = manager.prepare(github_env=env_file)

            evidence = result["evidence"]
            self.assertEqual(result["classification"], "READY")
            self.assertEqual(evidence["udid"], FakeNativeTools.udid)
            self.assertEqual(evidence["runtimeVersion"], "18.2")
            self.assertEqual((output / "ios-device.json").is_file(), True)
            self.assertIn(f"IOS_SIMULATOR_UDID={FakeNativeTools.udid}", env_file.read_text())

    def test_android_prepare_verifies_own_avd_serial_api_and_abi(self):
        tools = FakeNativeTools()
        with tempfile.TemporaryDirectory(prefix="ci-android-bootstrap-") as directory:
            root = Path(directory)
            sdk = root / "sdk"
            image = sdk / "system-images" / "android-35" / "google_apis" / "x86_64"
            platform = sdk / "platforms" / "android-35"
            build_tools = sdk / "build-tools" / "35.0.0"
            for path in (image, platform, build_tools):
                path.mkdir(parents=True)
            (image / "source.properties").write_text("Pkg.Revision=9.0.0\n")
            (platform / "source.properties").write_text("AndroidVersion.ApiLevel=35\n")
            (build_tools / "source.properties").write_text("Pkg.Revision=35.0.0\n")
            sdk_bins = (
                sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager",
                sdk / "emulator" / "emulator",
                sdk / "platform-tools" / "adb",
            )
            for executable in sdk_bins:
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("owned fake executable\n")
            output = root / "android"
            manager = CiDeviceBootstrap(
                output=output,
                run_id="workflow-123-1",
                platform="android",
                host_platform="linux",
                environment={"ANDROID_SDK_ROOT": str(sdk)},
                runner=tools.run,
                popen=tools.popen,
            )
            manager.port_checker = lambda port: None
            env_file = root / "github-env"
            env_file.write_text("")

            result = manager.prepare(github_env=env_file)

            evidence = result["evidence"]
            self.assertEqual(result["classification"], "READY")
            self.assertEqual(evidence["serial"], "emulator-5580")
            self.assertEqual(evidence["avdName"], "native_contract_workflow_123_1")
            self.assertEqual(evidence["imagePackage"], "system-images;android-35;google_apis;x86_64")
            self.assertEqual(evidence["imageRevision"], "9.0.0")
            self.assertEqual(evidence["abi"], "x86_64")
            self.assertIn("ANDROID_SERIAL=emulator-5580", env_file.read_text())
            self.assertIn(f"ANDROID_AVD_HOME={evidence['avdHome']}", env_file.read_text())

    def test_android_prepare_rejects_a_serial_that_reports_another_avd(self):
        tools = FakeNativeTools(avd_name_mismatch=True)
        with tempfile.TemporaryDirectory(prefix="ci-android-mismatch-") as directory:
            root = Path(directory)
            sdk = root / "sdk"
            image = sdk / "system-images" / "android-35" / "google_apis" / "x86_64"
            platform = sdk / "platforms" / "android-35"
            build_tools = sdk / "build-tools" / "35.0.0"
            for path in (image, platform, build_tools):
                path.mkdir(parents=True)
            (image / "source.properties").write_text("Pkg.Revision=9.0.0\n")
            (platform / "source.properties").write_text("AndroidVersion.ApiLevel=35\n")
            (build_tools / "source.properties").write_text("Pkg.Revision=35.0.0\n")
            for executable in (
                sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager",
                sdk / "emulator" / "emulator",
                sdk / "platform-tools" / "adb",
            ):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("owned fake executable\n")
            manager = CiDeviceBootstrap(
                output=root / "android",
                run_id="workflow-123-1",
                platform="android",
                host_platform="linux",
                environment={"ANDROID_SDK_ROOT": str(sdk)},
                runner=tools.run,
                popen=tools.popen,
            )

            manager.port_checker = lambda port: None
            with self.assertRaisesRegex(Exception, "identity/API/ABI"):
                manager.prepare()



def fake_android_sdk(root):
    sdk = root / "sdk"
    for path, content in [
        (sdk / "system-images/android-35/google_apis/x86_64/source.properties", "Pkg.Revision=9.0.0\n"),
        (sdk / "platforms/android-35/source.properties", "AndroidVersion.ApiLevel=35\n"),
        (sdk / "build-tools/35.0.0/source.properties", "Pkg.Revision=35.0.0\n"),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for name in ["cmdline-tools/latest/bin/avdmanager", "emulator/emulator", "platform-tools/adb"]:
        path = sdk / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fake executable\n")
    return sdk


class BootstrapSafetyTests(unittest.TestCase):
    def test_nonfinite_deadlines_are_rejected_before_resource_creation(self):
        for value in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(DeviceBootstrapError):
                    CiDeviceBootstrap(output=Path(directory)/"fresh", run_id="unit-test", platform="ios", timeout_seconds=value)

    def test_existing_serial_is_rejected_before_avd_creation_or_spawn(self):
        tools = FakeNativeTools()
        tools.occupied_serial = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = fake_android_sdk(root)
            manager = CiDeviceBootstrap(output=root/"owned", run_id="unit-test", platform="android", host_platform="linux", environment={"ANDROID_SDK_ROOT":str(sdk)}, runner=tools.run, popen=tools.popen)
            manager.port_checker = lambda port: None
            with self.assertRaises(DeviceBootstrapError):
                manager.prepare()
            self.assertEqual(tools.spawned, [])
            self.assertFalse(any(Path(a[0]).name == "avdmanager" for a in tools.argv))

    def test_busy_port_is_rejected_before_avd_creation_or_spawn(self):
        tools = FakeNativeTools()
        checked = []
        def busy(port):
            checked.append(port)
            raise OSError("port occupied")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = fake_android_sdk(root)
            manager = CiDeviceBootstrap(output=root/"owned", run_id="unit-test", platform="android", host_platform="linux", environment={"ANDROID_SDK_ROOT":str(sdk)}, runner=tools.run, popen=tools.popen)
            manager.port_checker = busy
            with self.assertRaises(DeviceBootstrapError):
                manager.prepare()
            self.assertEqual(checked, [5580])
            self.assertEqual(tools.spawned, [])

    def test_avd_identity_is_verified_before_any_shell_property_query(self):
        tools = FakeNativeTools(avd_name_mismatch=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = fake_android_sdk(root)
            manager = CiDeviceBootstrap(output=root/"owned", run_id="unit-test", platform="android", host_platform="linux", environment={"ANDROID_SDK_ROOT":str(sdk)}, runner=tools.run, popen=tools.popen)
            manager.port_checker = lambda port: None
            with self.assertRaises(DeviceBootstrapError):
                manager.prepare()
            self.assertFalse(any("getprop" in a for a in tools.argv))

    def test_cleanup_refuses_mismatched_run_name_or_runtime_before_delete(self):
        for mismatch in ["run", "name", "runtime"]:
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                tools = FakeNativeTools()
                name = "Foreign-user-device" if mismatch == "name" else "NativeContract-unit-test"
                tools.device_name = name
                resource = {"platform":"ios", "owned":True, "udid":tools.udid, "name":name, "runtimeIdentifier":"com.apple.CoreSimulator.SimRuntime.iOS-18-6" if mismatch == "runtime" else "com.apple.CoreSimulator.SimRuntime.iOS-18-2"}
                (output/"ownership.json").write_text(json.dumps({"version":1,"runId":"another-run" if mismatch == "run" else "unit-test","resources":{"ios":resource}}))
                manager = CiDeviceBootstrap(output=output, run_id="unit-test", platform="ios", host_platform="darwin", environment={}, runner=tools.run)
                self.assertEqual(manager.cleanup()["classification"], "INFRA_FAILURE")
                self.assertFalse(tools.device_deleted)

    def test_cleanup_preserves_preparation_command_evidence(self):
        tools = FakeNativeTools()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"owned"
            preparation = CiDeviceBootstrap(output=output, run_id="unit-test", platform="ios", host_platform="darwin", environment={}, runner=tools.run)
            preparation.prepare()
            before = (output/"commands.json").read_bytes()
            cleanup = CiDeviceBootstrap(output=output, run_id="unit-test", platform="ios", host_platform="darwin", environment={}, runner=tools.run)
            self.assertEqual(cleanup.cleanup()["classification"], "PASS")
            self.assertEqual((output/"commands.json").read_bytes(), before)

if __name__ == "__main__":
    unittest.main()
