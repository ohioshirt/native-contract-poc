"""Exact Android no_backup/run-as command contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from integration import controller


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)
PACKAGE = "dev.nativecontract.demo.android"
PROCESS_ID = "attempt-01/APP-02/p1"
NATIVE_ROOT = "no_backup/native-harness/attempt-01/APP-02/p1"
STORE_ROOT = "no_backup/demo-session/test-attempt-01/APP-02"


class AndroidPrivatePathTests(unittest.TestCase):
    def test_live_native_event_read_uses_exact_no_backup_exec_out_argv(self):
        expected = [
            "adb", "-s", "emulator-5580", "exec-out", "run-as", PACKAGE,
            "cat", f"{NATIVE_ROOT}/native-events.jsonl",
        ]
        event_bytes = (json.dumps({
            "kind": "processStart",
            "processInstanceId": PROCESS_ID,
            "localSequence": 1,
        }) + "\n").encode()
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout=event_bytes, stderr=b"")

        events = controller.read_live_native_events(
            platform="android",
            device="emulator-5580",
            attempt_id="attempt-01",
            process_instance_id=PROCESS_ID,
            command_runner=run,
        )

        self.assertEqual(events[0]["kind"], "processStart")
        self.assertEqual(calls, [(expected, {"capture_output": True, "text": False, "timeout": 15})])

    def test_live_ios_native_event_read_keeps_documents_namespace_without_no_backup(self):
        relative = "native-harness/attempt-01/APP-02/p1/native-events.jsonl"
        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            container = Path(temporary)
            source = container / "Documents" / relative
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({
                "kind": "processStart",
                "processInstanceId": PROCESS_ID,
                "localSequence": 1,
            }) + "\n")
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, stdout=str(container), stderr="")

            events = controller.read_live_native_events(
                platform="ios",
                device="OWNED-UUID",
                attempt_id="attempt-01",
                process_instance_id=PROCESS_ID,
                command_runner=run,
            )

        expected = [
            ["xcrun", "simctl", "get_app_container", "OWNED-UUID", "dev.nativecontract.demo.ios", "data"],
            {"capture_output": True, "text": True, "timeout": 15},
        ]
        self.assertEqual(events[0]["kind"], "processStart")
        self.assertEqual(calls, [tuple(expected)])

    def test_android_artifact_export_uses_no_backup_for_jsonl_and_screenshot(self):
        instrumentation_path = f"{NATIVE_ROOT}/instrumentation-evidence.jsonl"
        native_path = f"{NATIVE_ROOT}/native-events.jsonl"
        screenshots = f"{NATIVE_ROOT}/screenshots"
        png_path = f"{screenshots}/view.png"
        expected_calls = [
            ["adb", "-s", "emulator-5580", "exec-out", "run-as", PACKAGE, "cat", native_path],
            ["adb", "-s", "emulator-5580", "exec-out", "run-as", PACKAGE, "cat", instrumentation_path],
            ["adb", "-s", "emulator-5580", "shell", "run-as", PACKAGE, "ls", "-A", screenshots],
            ["adb", "-s", "emulator-5580", "exec-out", "run-as", PACKAGE, "cat", png_path],
        ]
        native_bytes = (json.dumps({
            "kind": "processStart",
            "processInstanceId": PROCESS_ID,
            "localSequence": 1,
        }) + "\n").encode()
        png_bytes = b"\x89PNG\r\n\x1a\nfixture"
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if "ls" in argv:
                stdout = "view.png" if argv[-1] == screenshots else "credential.json"
                return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
            if argv[-1] == native_path:
                stdout = native_bytes
            elif argv[-1] == instrumentation_path:
                stdout = b'{"evidence":"redacted"}\n'
            elif argv[-1] == png_path:
                stdout = png_bytes
            else:
                raise AssertionError(f"unexpected Android private path: {argv[-1]}")
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

        with tempfile.TemporaryDirectory(dir=ROOT / "reports/standalone") as temporary:
            case_root = Path(temporary) / "case"
            events, relative, screenshot_rows = controller._copy_android_process_artifacts(
                "emulator-5580", "attempt-01", "APP-02", 1, case_root, command_runner=run
            )
            self.assertTrue((case_root / relative).is_file())
            self.assertEqual((case_root / "APP-02/p1/instrumentation-evidence.jsonl").read_bytes(), b'{"evidence":"redacted"}\n')
            self.assertEqual((case_root / "APP-02/p1/screenshots/view.png").read_bytes(), png_bytes)

        self.assertEqual(calls, expected_calls)
        self.assertEqual(events[0]["processInstanceId"], PROCESS_ID)
        self.assertEqual(screenshot_rows[0]["path"], "APP-02/p1/screenshots/view.png")

    def test_missing_android_storage_namespace_is_unknown_not_absent(self):
        expected = ["adb", "-s", "emulator-5580", "shell", "run-as", PACKAGE, "ls", "-A", STORE_ROOT]
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="ls: no such file or directory")

        observation = controller.read_android_storage_probe(
            serial="emulator-5580",
            attempt_id="attempt-01",
            scenario_id="APP-02",
            command_runner=run,
        )

        self.assertEqual(observation, {"kind": "Unknown", "errorCode": "probeNamespaceMissing"})
        self.assertEqual(calls, [(expected, {"capture_output": True, "text": True, "timeout": 15})])

    def test_android_host_store_cat_uses_exec_out_no_backup_path(self):
        list_argv = ["adb", "-s", "emulator-5580", "shell", "run-as", PACKAGE, "ls", "-A", STORE_ROOT]
        cat_argv = ["adb", "-s", "emulator-5580", "exec-out", "run-as", PACKAGE, "cat", f"{STORE_ROOT}/credential.json"]
        raw = b'{"account":"A","version":7,"accessToken":"demo-A-v7","refreshToken":"demo-A-v7"}'
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv == list_argv:
                return subprocess.CompletedProcess(argv, 0, stdout="credential.json", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout=raw, stderr=b"")

        observation = controller.read_android_storage_probe(
            serial="emulator-5580",
            attempt_id="attempt-01",
            scenario_id="APP-02",
            command_runner=run,
        )

        self.assertEqual(observation, {"kind": "Present", "account": "A", "version": 7})
        self.assertEqual(calls, [
            (list_argv, {"capture_output": True, "text": True, "timeout": 15}),
            (cat_argv, {"capture_output": True, "text": False, "timeout": 15}),
        ])


if __name__ == "__main__":
    unittest.main()
