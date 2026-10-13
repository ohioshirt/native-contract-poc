"""Create and remove only per-run iOS Simulator/Android AVD resources."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time


class DeviceBootstrapError(RuntimeError):
    pass


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}\Z")
_UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z")
_AVD_NAME = re.compile(r"native_contract_[A-Za-z0-9_]{1,48}\Z")


def _check_port_vacant(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.bind(("127.0.0.1", port))


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _properties(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _device_rows(document: dict) -> list[dict]:
    devices = document.get("devices") if isinstance(document, dict) else None
    if not isinstance(devices, dict):
        raise DeviceBootstrapError("simctl device inventory has no devices map")
    rows = []
    for runtime, group in devices.items():
        if not isinstance(runtime, str) or not isinstance(group, list):
            raise DeviceBootstrapError("simctl device inventory has an invalid runtime group")
        for row in group:
            if not isinstance(row, dict):
                raise DeviceBootstrapError("simctl device inventory has an invalid device row")
            rows.append({**row, "runtimeIdentifier": runtime})
    return rows


def _runtime_row(document: dict) -> dict:
    runtimes = document.get("runtimes") if isinstance(document, dict) else None
    if not isinstance(runtimes, list):
        raise DeviceBootstrapError("simctl runtime inventory has no runtimes array")
    matches = [
        row for row in runtimes
        if isinstance(row, dict)
        and row.get("version") == "18.2"
        and row.get("isAvailable") is True
        and row.get("identifier") == "com.apple.CoreSimulator.SimRuntime.iOS-18-2"
    ]
    if len(matches) != 1:
        raise DeviceBootstrapError("exact available iOS 18.2 runtime is missing or ambiguous")
    return matches[0]


class CiDeviceBootstrap:
    """Injectable command runner for auditable per-job CI device ownership."""

    def __init__(
        self,
        *,
        output: Path,
        run_id: str,
        platform: str,
        timeout_seconds: float = 900,
        android_port: int = 5580,
        runner=subprocess.run,
        popen=subprocess.Popen,
        sleeper=time.sleep,
        clock=time.monotonic,
        host_platform=sys.platform,
        environment=None,
        process_killer=None,
        port_checker=None,
    ):
        if not isinstance(platform, str) or platform not in {"ios", "android"}:
            raise DeviceBootstrapError("platform must be ios or android")
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise DeviceBootstrapError("run ID must be a unique bounded ASCII label")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise DeviceBootstrapError("device bootstrap timeout must be positive")
        if type(android_port) is not int or android_port < 5554 or android_port > 5682 or android_port % 2:
            raise DeviceBootstrapError("Android emulator port must be an even console port in 5554..5682")
        self.output = Path(output).absolute()
        self.run_id = run_id
        self.platform = platform
        self.timeout_seconds = timeout_seconds
        self.android_port = android_port
        self.runner = runner
        self.popen = popen
        self.sleeper = sleeper
        self.clock = clock
        self.host_platform = host_platform
        self.environment = dict(os.environ if environment is None else environment)
        self.process_killer = process_killer or self._kill_process_group
        self.port_checker = port_checker or _check_port_vacant
        self.commands = []
        self.command_log_name = "commands.json"
        self.resources = {}
        self.started = 0.0
        self.deadline = 0.0

    def _remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise DeviceBootstrapError("device bootstrap deadline expired")
        return remaining

    def _record(self, argv, *, cwd, environment, stdout, stderr, exit_code, timed_out=False):
        row = {
            "argv": list(argv),
            "cwd": str(Path(cwd).resolve()),
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timedOut": bool(timed_out),
        }
        safe_environment = {
            key: value for key, value in environment.items()
            if key in {"ANDROID_AVD_HOME", "ANDROID_SDK_ROOT", "ANDROID_HOME"}
        }
        if safe_environment:
            row["environment"] = safe_environment
        self.commands.append(row)
        _write_json(self.output / self.command_log_name, {"commands": self.commands})
        return row

    def _run(self, argv, *, environment=None, timeout_seconds=None, check=True):
        env = dict(self.environment)
        if environment:
            env.update(environment)
        timeout = min(self._remaining(), timeout_seconds or 30)
        try:
            completed = self.runner(
                list(argv),
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            self._record(argv, cwd=Path.cwd(), environment=env, stdout=stdout, stderr=stderr, exit_code=None, timed_out=True)
            raise DeviceBootstrapError("owned device command timed out") from exc
        row = self._record(
            argv,
            cwd=Path(__file__).resolve().parents[1],
            environment=env,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
        if check and completed.returncode != 0:
            raise DeviceBootstrapError(f"owned device command failed with exit {completed.returncode}: {argv[0]}")
        return row

    def _save_ownership(self):
        _write_json(self.output / "ownership.json", {
            "version": 1,
            "runId": self.run_id,
            "resources": self.resources,
        })

    def prepare(self, github_env: Path | None = None) -> dict:
        if self.output.exists() or self.output.is_symlink():
            raise DeviceBootstrapError("device evidence output must be a fresh directory")
        expected_host = "darwin" if self.platform == "ios" else "linux"
        if self.host_platform != expected_host:
            raise DeviceBootstrapError(f"{self.platform} device bootstrap requires a {expected_host} runner")
        self.output.mkdir(parents=True, mode=0o700)
        self.started = self.clock()
        self.deadline = self.started + self.timeout_seconds
        self._save_ownership()
        try:
            evidence = self._prepare_ios() if self.platform == "ios" else self._prepare_android()
            evidence_path = self.output / f"{self.platform}-device.json"
            _write_json(evidence_path, evidence)
            self._save_ownership()
            environment_name = (
                "NATIVE_CONTRACT_OWNED_IOS_DEVICE_EVIDENCE"
                if self.platform == "ios"
                else "NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE"
            )
            env_values = {
                environment_name: str(evidence_path.resolve()),
            }
            if self.platform == "ios":
                env_values["IOS_SIMULATOR_UDID"] = evidence["udid"]
            else:
                env_values["ANDROID_SERIAL"] = evidence["serial"]
                env_values["ANDROID_AVD_HOME"] = evidence["avdHome"]
            if github_env is not None:
                self._append_github_env(Path(github_env), env_values)
            report = {
                "classification": "READY",
                "platform": self.platform,
                "evidencePath": str(evidence_path.resolve()),
                "evidence": evidence,
                "commands": self.commands,
            }
            _write_json(self.output / "prepare-report.json", report)
            return report
        except Exception as exc:
            _write_json(self.output / "prepare-report.json", {
                "classification": "INFRA_FAILURE",
                "platform": self.platform,
                "detail": str(exc),
                "commands": self.commands,
            })
            raise

    def _append_github_env(self, path, values):
        if not path.is_file() or path.is_symlink():
            raise DeviceBootstrapError("GitHub environment file is absent or unsafe")
        lines = []
        for key, value in values.items():
            if not isinstance(value, str) or "\n" in value or "\r" in value:
                raise DeviceBootstrapError("GitHub environment value is invalid")
            lines.append(f"{key}={value}\n")
        with path.open("a", encoding="utf-8") as handle:
            handle.writelines(lines)

    def _prepare_ios(self) -> dict:
        version = self._run(["xcodebuild", "-version"])["stdout"]
        if re.search(r"(?m)^Xcode 16\.2$", version) is None:
            raise DeviceBootstrapError("iOS owned simulator requires Xcode 16.2")
        runtime_doc = json.loads(self._run(["xcrun", "simctl", "list", "runtimes", "--json"])["stdout"])
        runtime = _runtime_row(runtime_doc)
        name = f"NativeContract-{self.run_id}"
        device_type = "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
        created = self._run(["xcrun", "simctl", "create", name, device_type, runtime["identifier"]])
        udid = created["stdout"].strip()
        if _UUID.fullmatch(udid) is None:
            raise DeviceBootstrapError("simctl create did not return a canonical simulator UUID")
        resource = {
            "platform": "ios",
            "owned": True,
            "udid": udid,
            "name": name,
            "runtimeIdentifier": runtime["identifier"],
        }
        self.resources["ios"] = resource
        self._save_ownership()
        self._run(["xcrun", "simctl", "boot", udid])
        self._run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout_seconds=self._remaining())
        devices_doc = json.loads(self._run(["xcrun", "simctl", "list", "devices", "--json"])["stdout"])
        rows = [row for row in _device_rows(devices_doc) if row.get("udid", "").casefold() == udid.casefold()]
        if len(rows) != 1:
            raise DeviceBootstrapError("created simulator is absent or ambiguous in simctl inventory")
        row = rows[0]
        if row.get("name") != name or row.get("state") != "Booted" or row.get("runtimeIdentifier") != runtime["identifier"]:
            raise DeviceBootstrapError("created simulator identity or boot state does not match its ownership record")
        resource.update({"udid": row["udid"], "runtimeVersion": runtime["version"], "deviceType": device_type})
        return resource

    def _prepare_android(self) -> dict:
        sdk_root_value = self.environment.get("ANDROID_SDK_ROOT") or self.environment.get("ANDROID_HOME")
        if not isinstance(sdk_root_value, str) or not sdk_root_value:
            raise DeviceBootstrapError("Android SDK root is not configured")
        sdk_root = Path(sdk_root_value).resolve()
        image_package = "system-images;android-35;google_apis;x86_64"
        image_properties_path = sdk_root / "system-images" / "android-35" / "google_apis" / "x86_64" / "source.properties"
        platform_properties_path = sdk_root / "platforms" / "android-35" / "source.properties"
        build_tools_properties_path = sdk_root / "build-tools" / "35.0.0" / "source.properties"
        for required in (image_properties_path, platform_properties_path, build_tools_properties_path):
            if not required.is_file():
                raise DeviceBootstrapError(f"required Android SDK package is absent: {required.relative_to(sdk_root)}")
        image_properties = _properties(image_properties_path)
        platform_properties = _properties(platform_properties_path)
        build_tools_properties = _properties(build_tools_properties_path)
        if image_properties.get("Pkg.Revision") is None:
            raise DeviceBootstrapError("Android x86_64 system image has no recorded package revision")
        if platform_properties.get("AndroidVersion.ApiLevel") != "35":
            raise DeviceBootstrapError("installed Android platform is not API 35")
        if build_tools_properties.get("Pkg.Revision") != "35.0.0":
            raise DeviceBootstrapError("installed Android Build Tools are not 35.0.0")

        suffix = self.run_id.replace("-", "_").replace(".", "_")
        name = f"native_contract_{suffix}"
        if _AVD_NAME.fullmatch(name) is None:
            raise DeviceBootstrapError("derived Android AVD name is invalid")
        avd_home = self.output / "android" / "avd-home"
        avd_home.mkdir(parents=True, mode=0o700)
        avd_path = avd_home / f"{name}.avd"
        avd_environment = {
            "ANDROID_AVD_HOME": str(avd_home.resolve()),
            "ANDROID_SDK_ROOT": str(sdk_root),
        }
        avdmanager = sdk_root / "cmdline-tools" / "latest" / "bin" / "avdmanager"
        emulator = sdk_root / "emulator" / "emulator"
        adb = sdk_root / "platform-tools" / "adb"
        if not avdmanager.is_file() or not emulator.is_file() or not adb.is_file():
            raise DeviceBootstrapError("Android emulator, adb, or avdmanager executable is absent")
        serial = f"emulator-{self.android_port}"
        inventory = self._run([str(adb), "devices", "-l"], environment=avd_environment)["stdout"]
        if any(line.split()[0:1] == [serial] for line in inventory.splitlines()):
            raise DeviceBootstrapError("requested Android serial is already occupied")
        try:
            self.port_checker(self.android_port)
            self.port_checker(self.android_port + 1)
        except OSError as exc:
            raise DeviceBootstrapError("requested Android console or adb port is occupied") from exc
        resource = {
            "platform": "android",
            "owned": True,
            "name": name,
            "avdName": name,
            "avdHome": str(avd_home.resolve()),
            "avdPath": str(avd_path.resolve()),
            "serial": serial,
            "port": self.android_port,
            "pid": None,
            "imagePackage": image_package,
            "imageRevision": image_properties["Pkg.Revision"],
            "abi": "x86_64",
            "sourcePropertiesPath": str(image_properties_path.resolve()),
            "sdkRoot": str(sdk_root),
        }
        self.resources["android"] = resource
        self._save_ownership()
        self._run([
            str(avdmanager), "create", "avd", "--name", name,
            "--package", image_package, "--device", "pixel_7", "--path", str(avd_path),
        ], environment=avd_environment, timeout_seconds=120)
        if not avd_path.is_dir() or avd_path.is_symlink():
            raise DeviceBootstrapError("avdmanager did not create the declared owned AVD directory")
        emulator_argv = [
            str(emulator), "-avd", name, "-port", str(self.android_port),
            "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot",
            "-gpu", "swiftshader",
        ]
        emulator_log = self.output / "android" / "emulator.log"
        emulator_log.parent.mkdir(parents=True, exist_ok=True)
        with emulator_log.open("wb") as log:
            process = self.popen(
                emulator_argv,
                cwd=Path(__file__).resolve().parents[1],
                env={**self.environment, **avd_environment},
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        resource.update({"pid": process.pid, "argv": emulator_argv, "emulatorLog": str(emulator_log.resolve())})
        self._save_ownership()
        self._run([str(adb), "-s", serial, "wait-for-device"], environment=avd_environment, timeout_seconds=120)
        avd_name_row = self._run([str(adb), "-s", serial, "emu", "avd", "name"], environment=avd_environment)
        observed_name = next((line.strip() for line in avd_name_row["stdout"].splitlines() if line.strip() and line.strip() != "OK"), None)
        if observed_name != name or process.poll() is not None:
            raise DeviceBootstrapError("booted Android emulator identity/API/ABI differs from the pinned AVD")
        while True:
            self._remaining()
            if process.poll() is not None:
                raise DeviceBootstrapError("owned Android emulator exited before boot completed")
            boot = self._run(
                [str(adb), "-s", serial, "shell", "getprop", "sys.boot_completed"],
                environment=avd_environment,
                timeout_seconds=5,
                check=False,
            )
            if boot["exitCode"] == 0 and boot["stdout"].strip() == "1":
                break
            self.sleeper(min(2, self._remaining()))
        avd_name_row = self._run([str(adb), "-s", serial, "emu", "avd", "name"], environment=avd_environment)
        observed_name = next((line.strip() for line in avd_name_row["stdout"].splitlines() if line.strip() and line.strip() != "OK"), None)
        api_row = self._run([str(adb), "-s", serial, "shell", "getprop", "ro.build.version.sdk"], environment=avd_environment)
        abi_row = self._run([str(adb), "-s", serial, "shell", "getprop", "ro.product.cpu.abi"], environment=avd_environment)
        if observed_name != name or api_row["stdout"].strip() != "35" or abi_row["stdout"].strip() != "x86_64":
            raise DeviceBootstrapError("booted Android emulator identity/API/ABI differs from the pinned AVD")
        readiness_path = self.output / "android" / "readiness.json"
        readiness = {
            "classification": "READY",
            "platform": "android",
            "serial": serial,
            "avdName": name,
            "apiLevel": 35,
            "abi": "x86_64",
            "imagePackage": image_package,
            "imageRevision": image_properties["Pkg.Revision"],
            "pid": process.pid,
            "port": self.android_port,
            "commandsPath": str((self.output / "commands.json").resolve()),
        }
        _write_json(readiness_path, readiness)
        resource["readinessEvidence"] = {"classification": "READY", "path": str(readiness_path.resolve())}
        return resource

    @staticmethod
    def _kill_process_group(pid):
        os.killpg(pid, signal.SIGTERM)

    def cleanup(self) -> dict:
        ownership_path = self.output / "ownership.json"
        if not ownership_path.is_file() or ownership_path.is_symlink():
            return {"classification": "INFRA_FAILURE", "detail": "owned-device manifest is missing or unsafe"}
        self.started = self.clock()
        self.deadline = self.started + self.timeout_seconds
        self.command_log_name = "cleanup-commands.json"
        try:
            manifest = json.loads(ownership_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or set(manifest) != {"version", "runId", "resources"} or type(manifest["version"]) is not int or manifest["version"] != 1:
                raise DeviceBootstrapError("owned-device manifest has an invalid shape")
            if manifest["runId"] != self.run_id:
                raise DeviceBootstrapError("owned-device manifest belongs to a different run")
            resources = manifest["resources"]
            if not isinstance(resources, dict):
                raise DeviceBootstrapError("owned-device resources are invalid")
            if "ios" in resources:
                self._cleanup_ios(resources["ios"])
            if "android" in resources:
                self._cleanup_android(resources["android"])
            report = {"classification": "PASS", "runId": manifest["runId"], "commands": self.commands}
        except Exception as exc:
            report = {"classification": "INFRA_FAILURE", "detail": str(exc), "commands": self.commands}
        _write_json(self.output / "cleanup-report.json", report)
        return report

    def _cleanup_ios(self, resource):
        if not isinstance(resource, dict) or resource.get("platform") != "ios" or resource.get("owned") is not True:
            raise DeviceBootstrapError("refusing to clean an unowned simulator")
        udid, name = resource.get("udid"), resource.get("name")
        if not isinstance(udid, str) or _UUID.fullmatch(udid) is None or not isinstance(name, str):
            raise DeviceBootstrapError("owned simulator identity is malformed")
        runtime = "com.apple.CoreSimulator.SimRuntime.iOS-18-2"
        if name != f"NativeContract-{self.run_id}" or resource.get("runtimeIdentifier") != runtime:
            raise DeviceBootstrapError("owned simulator name/runtime is not bound to this run")
        preparation = self.output / "commands.json"
        if preparation.exists():
            if preparation.is_symlink() or not preparation.is_file():
                raise DeviceBootstrapError("simulator creation evidence is unsafe")
            document = json.loads(preparation.read_text(encoding="utf-8"))
            commands = document.get("commands") if isinstance(document, dict) else None
            expected = ["xcrun", "simctl", "create", name, "com.apple.CoreSimulator.SimDeviceType.iPhone-16", runtime]
            if not isinstance(commands, list) or not any(
                isinstance(row, dict) and row.get("argv") == expected and row.get("exitCode") == 0
                and isinstance(row.get("stdout"), str) and row["stdout"].strip().casefold() == udid.casefold()
                for row in commands
            ):
                raise DeviceBootstrapError("simulator creation evidence does not match its ownership record")
        inventory = json.loads(self._run(["xcrun", "simctl", "list", "devices", "--json"]) ["stdout"])
        matching = [row for row in _device_rows(inventory) if row.get("udid", "").casefold() == udid.casefold()]
        if not matching:
            return
        if len(matching) != 1 or matching[0].get("name") != name or matching[0].get("runtimeIdentifier") != runtime:
            raise DeviceBootstrapError("simulator UUID no longer resolves to the owned device name")
        udid = matching[0]["udid"]
        if matching[0].get("state") == "Booted":
            self._run(["xcrun", "simctl", "shutdown", udid], check=False)
        self._run(["xcrun", "simctl", "delete", udid])

    def _cleanup_android(self, resource):
        if not isinstance(resource, dict) or resource.get("platform") != "android" or resource.get("owned") is not True:
            raise DeviceBootstrapError("refusing to clean an unowned AVD")
        name, avd_home_value, avd_path_value = resource.get("avdName"), resource.get("avdHome"), resource.get("avdPath")
        pid, port = resource.get("pid"), resource.get("port")
        if (
            not isinstance(name, str) or _AVD_NAME.fullmatch(name) is None
            or not isinstance(avd_home_value, str) or not isinstance(avd_path_value, str)
            or (pid is not None and (type(pid) is not int or pid <= 1)) or type(port) is not int
        ):
            raise DeviceBootstrapError("owned AVD identity is malformed")
        avd_home = Path(avd_home_value).resolve()
        avd_path = Path(avd_path_value).resolve()
        output_root = self.output.resolve()
        if avd_home != output_root / "android" / "avd-home" or avd_path != avd_home / f"{name}.avd":
            raise DeviceBootstrapError("owned AVD path escapes its per-run evidence root")
        configured_avd_home = self.environment.get("ANDROID_AVD_HOME")
        if configured_avd_home is not None and configured_avd_home != str(avd_home):
            raise DeviceBootstrapError("ANDROID_AVD_HOME differs from the owned AVD record")
        if pid is not None:
            ps = self._run(["ps", "-p", str(pid), "-o", "command="], check=False)
            command = ps["stdout"].strip()
            if ps["exitCode"] == 0:
                if not command:
                    raise DeviceBootstrapError("emulator PID exists but its command line is unreadable")
                try:
                    tokens = shlex.split(command)
                except ValueError as exc:
                    raise DeviceBootstrapError("emulator process command cannot be safely parsed") from exc
                if not _contains_pair(tokens, "-avd", name) or not _contains_pair(tokens, "-port", str(port)):
                    raise DeviceBootstrapError("recorded emulator PID no longer belongs to the owned AVD")
                self.process_killer(pid)
                deadline = self.clock() + 30
                while self.clock() < deadline:
                    check = self._run(["ps", "-p", str(pid), "-o", "command="], check=False)
                    if check["exitCode"] == 1 and not check["stdout"].strip():
                        break
                    if check["exitCode"] != 0:
                        raise DeviceBootstrapError("cannot verify owned emulator process termination")
                    self.sleeper(0.5)
                else:
                    raise DeviceBootstrapError("owned Android emulator did not stop within cleanup deadline")
            elif ps["exitCode"] != 1 or command:
                raise DeviceBootstrapError("cannot verify whether the recorded emulator process still exists")
        if avd_path.exists():
            if avd_path.is_symlink() or not avd_path.is_dir():
                raise DeviceBootstrapError("owned AVD path is not a regular directory")
            shutil.rmtree(avd_path)
        ini_path = avd_home / f"{name}.ini"
        if ini_path.exists():
            if ini_path.is_symlink() or not ini_path.is_file():
                raise DeviceBootstrapError("owned AVD ini path is unsafe")
            ini_path.unlink()
        if avd_home.exists():
            avd_home.rmdir()


def _contains_pair(tokens, key, value):
    return any(tokens[index:index + 2] == [key, value] for index in range(max(0, len(tokens) - 1)))
