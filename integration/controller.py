"""Explicit-device controller primitives for frozen native integration attempts."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from integration import progress
from integration.check import _resolve_scenario_variant, check_control_trace, check_trace, control_inventory_errors
from integration.mutation_installation import mutation_for_control, prepare_mutation_workspace
from integration.mutations import validate_control_bindings
from verification.change_protocol import IOS_SHARD_STAGES, digest_bytes, encode, write_json


_ANDROID_LABEL = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_ANDROID_COMPONENT = "dev.nativecontract.demo.android.test/nativecontract.demo.DemoTestRunner"
_ANDROID_TEST_METHOD = "nativecontract.demo.ScenarioInstrumentedTest#runScenario"
_IOS_STATUS_PREFIX = "NATIVE_CONTRACT_STATUS_V1 "
_SENSITIVE_TEXT = re.compile(r"(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)")


def launch_inventory_digests(candidate):
    """Digests of the two packaged inventories, whichever inventory a stage runs.

    Both native harnesses verify the packaged scenarios.json against the scenario
    digest and control-scenarios.json against the control digest; the controls
    stage must therefore not substitute its own inventory bytes for the former.
    """
    root = Path(candidate) / "integration"
    return (
        digest_bytes((root / "scenarios.json").read_bytes()),
        digest_bytes((root / "control-scenarios.json").read_bytes()),
    )


class _NativeStageDeadlineExceeded(TimeoutError):
    """A controller-side operation exhausted the shared native-stage budget."""
_STATUS_REQUIRED = {"scenarioId", "processInstanceId", "checkpointName", "phase"}
_STATUS_OPTIONAL = {
    "command", "redactedObservation", "redactedProbe", "renderedState",
    "lastProcessedCommandId", "lastProcessedProcessInstanceId", "lastEnqueuedCommandId",
    "hookPoint", "hookPhase", "hookTarget", "hookCommandId", "authMailboxPaused",
    "bootstrapReceiptObserved", "deliverReceiptObserved",
    "effectId", "effectOriginCommandRef",
    "replayActionId", "controlSnapshotJSON",
    "processEndAckJSON", "hookArmSequence",
}
_STATUS_PHASES = {
    "probeCaptured", "probeRequested", "receiptObserved", "rendered",
    "releaseRequested", "releaseReady", "replayScheduled", "hookArrived", "hookReleased", "hookArmed", "end",
    "effectAwaitRequested", "processEndAcknowledged", "restartCheckpoint",
}


def _safe_store_observation(value):
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return False
    if value["kind"] == "Absent":
        return set(value) == {"kind"}
    if value["kind"] == "Present":
        return (
            set(value) == {"kind", "account", "version"}
            and value.get("account") in {"A", "B"}
            and type(value.get("version")) is int
            and 0 <= value["version"] <= (1 << 63) - 1
        )
    if value["kind"] == "Unknown":
        return set(value) == {"kind", "errorCode"} and isinstance(value.get("errorCode"), str) and bool(value["errorCode"])
    return False


def _decode_control_snapshot(raw, *, expected_process_instance_id):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("native control snapshot is malformed JSON") from exc
    required = {"version", "processInstanceId", "launchOrdinal", "controlRevision", "storeIoActive", "hooks"}
    optional = {"lastActionId", "lastActionStatus", "lastEnqueuedCommandRef", "lastProcessedCommandRef", "lastProbe"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - (required | optional):
        raise ValueError("native control snapshot has an invalid field set")
    process = value.get("processInstanceId")
    parts = process.split("/") if isinstance(process, str) else []
    if process != expected_process_instance_id or len(parts) != 3:
        raise ValueError("native control snapshot process identity differs")
    if (
        type(value.get("version")) is not int or value["version"] != 1
        or type(value.get("launchOrdinal")) is not int
        or not 1 <= value["launchOrdinal"] <= (1 << 63) - 1
        or parts[-1] != f"p{value['launchOrdinal']}"
        or type(value.get("controlRevision")) is not int
        or not 0 <= value["controlRevision"] <= (1 << 63) - 1
        or type(value.get("storeIoActive")) is not bool
        or not isinstance(value.get("hooks"), list)
    ):
        raise ValueError("native control snapshot has invalid values")
    action_id = value.get("lastActionId")
    action_status = value.get("lastActionStatus")
    if (action_id is None) != (action_status is None) or (
        action_id is not None and (type(action_id) is not int or not 1 <= action_id <= (1 << 63) - 1)
    ) or (action_status is not None and action_status not in {"applied", "scheduled"}):
        raise ValueError("native control snapshot action acknowledgement is invalid")
    for key in ("lastEnqueuedCommandRef", "lastProcessedCommandRef"):
        ref = value.get(key)
        if ref is not None and (
            not isinstance(ref, dict) or set(ref) != {"processInstanceId", "id"}
            or ref.get("processInstanceId") != process or type(ref.get("id")) is not int
            or not 1 <= ref["id"] <= (1 << 63) - 1
        ):
            raise ValueError(f"native control snapshot {key} is invalid")
    hook_arm_sequences = []
    hook_points = set()
    for hook in value["hooks"]:
        if (
            not isinstance(hook, dict)
            or set(hook) - {"armSequence", "point", "phase", "target", "arrivalCommandRef"}
            or not {"armSequence", "point", "phase", "target"} <= set(hook)
            or type(hook.get("armSequence")) is not int
            or not 1 <= hook["armSequence"] <= (1 << 63) - 1
            or hook.get("point") not in {"beforeBootstrapClear", "afterManaged", "beforeStore", "beforePublish", "afterPublishAck", "afterLogoutReceipt", "ingressHeld", "beforeDeferredControlClear"}
            or hook.get("phase") not in {"armed", "arrived", "released"}
            or hook.get("target") not in {"bootstrap", "nextCommand", "nextDelivery"}
            or hook.get("point") in hook_points
        ):
            raise ValueError("native control snapshot hook row is invalid")
        hook_points.add(hook["point"])
        hook_arm_sequences.append(hook["armSequence"])
        ref = hook.get("arrivalCommandRef")
        if ref is not None and (
            not isinstance(ref, dict) or set(ref) != {"processInstanceId", "id"}
            or ref.get("processInstanceId") != process or type(ref.get("id")) is not int
            or not 1 <= ref["id"] <= (1 << 63) - 1
        ):
            raise ValueError("native control snapshot hook command reference is invalid")
    if hook_arm_sequences != sorted(hook_arm_sequences) or len(hook_arm_sequences) != len(set(hook_arm_sequences)):
        raise ValueError("native control snapshot hooks are not retained in unique arm sequence order")
    probe = value.get("lastProbe")
    if probe is not None and (
        not isinstance(probe, dict) or set(probe) != {"probeId", "processInstanceId", "observation"}
        or not isinstance(probe.get("probeId"), str) or not probe["probeId"]
        or probe.get("processInstanceId") != process
        or not _safe_store_observation(probe.get("observation"))
    ):
        raise ValueError("native control snapshot lastProbe is invalid")
    return value


def _validated_status(value, *, expected_scenario_id, expected_process_instance_id):
    if not isinstance(value, dict) or not _STATUS_REQUIRED <= set(value) or set(value) - (_STATUS_REQUIRED | _STATUS_OPTIONAL):
        raise ValueError("native controller status has an invalid field set")
    if value["scenarioId"] != expected_scenario_id or value["processInstanceId"] != expected_process_instance_id:
        raise ValueError("native controller status belongs to another scenario or process")
    if not isinstance(value["checkpointName"], str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value["checkpointName"]) is None:
        raise ValueError("native controller checkpoint name is invalid")
    if value["phase"] not in _STATUS_PHASES:
        raise ValueError("native controller status phase is outside the frozen set")
    for key in ("command", "redactedObservation", "redactedProbe", "renderedState", "controlSnapshotJSON", "processEndAckJSON"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"native controller status {key} must be a string")
        if key in value and _SENSITIVE_TEXT.search(value[key]):
            raise ValueError("native controller status contains credential text")
    hook_fields = {key for key in _STATUS_OPTIONAL if key.startswith("hook")}
    if any(key in value for key in hook_fields):
        if not {"hookPoint", "hookPhase", "hookArmSequence"} <= set(value):
            raise ValueError("native controller hook status is incomplete")
        if value["hookPoint"] not in {
            "beforeBootstrapClear", "afterManaged", "beforeStore", "beforePublish",
            "afterPublishAck", "afterLogoutReceipt", "ingressHeld", "beforeDeferredControlClear",
        } or value["hookPhase"] not in {"armed", "arrived", "released"}:
            raise ValueError("native controller hook status is outside the frozen inventory")
        if "hookTarget" in value and value["hookTarget"] not in {"bootstrap", "nextCommand", "nextDelivery"}:
            raise ValueError("native controller hook target is outside the frozen set")
        if "hookCommandId" in value and re.fullmatch(r"[1-9][0-9]{0,18}", value["hookCommandId"]) is None:
            raise ValueError("native controller hook command reference is invalid")
        if re.fullmatch(r"[1-9][0-9]{0,18}", value["hookArmSequence"]) is None or int(value["hookArmSequence"]) > (1 << 63) - 1:
            raise ValueError("native controller hook arm sequence is invalid")
        for key in ("authMailboxPaused", "bootstrapReceiptObserved", "deliverReceiptObserved"):
            if key in value and type(value[key]) is not bool and value[key] not in {"true", "false"}:
                raise ValueError(f"native controller {key} must be a boolean string")
    for key in ("lastProcessedCommandId", "lastEnqueuedCommandId", "replayActionId"):
        if key in value and re.fullmatch(r"[1-9][0-9]{0,18}", value[key]) is None:
            raise ValueError(f"native controller status {key} is not a canonical positive signed64 identifier")
        if key in value and int(value[key]) > (1 << 63) - 1:
            raise ValueError(f"native controller status {key} is outside signed64")
    if "controlSnapshotJSON" in value:
        _decode_control_snapshot(value["controlSnapshotJSON"], expected_process_instance_id=expected_process_instance_id)
    if value["phase"] == "replayScheduled" and not {"replayActionId", "lastEnqueuedCommandId"} <= set(value):
        raise ValueError("replay status lacks its Debug action and enqueued command references")
    if value["phase"] == "processEndAcknowledged":
        if value["checkpointName"] != "processEndAcknowledged":
            raise ValueError("processEnd acknowledgement checkpoint is invalid")
        raw_ack = value.get("processEndAckJSON")
        if not isinstance(raw_ack, str):
            raise ValueError("processEnd acknowledgement is missing its JSON envelope")
        try:
            acknowledgement = json.loads(raw_ack)
        except json.JSONDecodeError as exc:
            raise ValueError("processEnd acknowledgement JSON is malformed") from exc
        if (
            not isinstance(acknowledgement, dict)
            or set(acknowledgement) != {"processInstanceId", "eventRef"}
            or acknowledgement.get("processInstanceId") != expected_process_instance_id
            or not isinstance(acknowledgement.get("eventRef"), dict)
            or set(acknowledgement["eventRef"]) != {"processInstanceId", "localSequence"}
            or acknowledgement["eventRef"].get("processInstanceId") != expected_process_instance_id
            or type(acknowledgement["eventRef"].get("localSequence")) is not int
            or not 1 <= acknowledgement["eventRef"]["localSequence"] <= (1 << 63) - 1
        ):
            raise ValueError("processEnd acknowledgement is not bound to this process and a positive event reference")
    elif "processEndAckJSON" in value:
        raise ValueError("processEnd acknowledgement appeared outside its acknowledgement phase")
    if value["phase"] == "restartCheckpoint" and value["checkpointName"] != "restartCheckpoint":
        raise ValueError("restart checkpoint status name is invalid")
    if value.get("lastProcessedProcessInstanceId", expected_process_instance_id) != expected_process_instance_id:
        raise ValueError("native controller processed reference belongs to another process")
    effect_fields = {"effectId", "effectOriginCommandRef"} & set(value)
    if value["phase"] == "effectAwaitRequested":
        if effect_fields != {"effectId", "effectOriginCommandRef"}:
            raise ValueError("detached-effect wait status lacks its effect identity")
        if not isinstance(value["effectId"], str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value["effectId"]) is None:
            raise ValueError("detached-effect wait status has an invalid effect ID")
        if not isinstance(value["effectOriginCommandRef"], str):
            raise ValueError("detached-effect wait origin must be a JSON string")
        try:
            origin = json.loads(value["effectOriginCommandRef"])
        except json.JSONDecodeError as exc:
            raise ValueError("detached-effect wait origin is malformed JSON") from exc
        if (
            not isinstance(origin, dict) or set(origin) != {"processInstanceId", "id"}
            or origin.get("processInstanceId") != expected_process_instance_id
            or type(origin.get("id")) is not int or not 1 <= origin["id"] <= (1 << 63) - 1
        ):
            raise ValueError("detached-effect wait origin is not a process-scoped command reference")
    elif effect_fields:
        raise ValueError("detached-effect identity appeared outside an await request")
    for key in ("redactedObservation", "redactedProbe"):
        if key not in value:
            continue
        try:
            decoded = json.loads(value[key])
        except json.JSONDecodeError as exc:
            raise ValueError(f"native controller {key} is not JSON") from exc
        if isinstance(decoded, dict) and set(decoded) == {"probeId", "processInstanceId", "observation"}:
            if decoded["processInstanceId"] != expected_process_instance_id or not isinstance(decoded["probeId"], str) or not decoded["probeId"]:
                raise ValueError(f"native controller {key} has invalid probe identity")
            decoded = decoded["observation"]
        if not _safe_store_observation(decoded):
            raise ValueError(f"native controller {key} is not a redacted store observation")
    return value


def parse_ios_status_line(line, *, expected_scenario_id, expected_process_instance_id):
    """Decode one protected XCTest progress record; unrelated xcodebuild output is ignored."""
    if not isinstance(line, str) or not line.startswith(_IOS_STATUS_PREFIX):
        return None
    try:
        value = json.loads(line[len(_IOS_STATUS_PREFIX):])
    except json.JSONDecodeError as exc:
        raise ValueError("XCTest controller status JSON is malformed") from exc
    return _validated_status(
        value,
        expected_scenario_id=expected_scenario_id,
        expected_process_instance_id=expected_process_instance_id,
    )


def _redact_log_line(line):
    """Keep subprocess logs useful while excluding the demo credential labels."""
    return _SENSITIVE_TEXT.sub("<redacted>", line)


# Diagnostic only: where an xcodebuild test run spends its time before the test body starts.
_COMMAND_MILESTONES = {
    "[Default] Running tests...": "test-runner-launched",
    "Test Suite 'Selected tests' started": "tests-started",
}


def run_streaming_command(
    argv,
    *,
    cwd,
    environment,
    output_directory,
    timeout_seconds,
    status_parser=None,
    on_status=None,
    process_factory=subprocess.Popen,
):
    """Run one owned native command, persist redacted logs, and stream status records."""
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError("native command must be a nonempty argv array")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("native command timeout must be positive")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    stdout_path = output_directory / "stdout.log"
    stderr_path = output_directory / "stderr.log"
    started = time.monotonic()
    # The last path parts name the step (`ios/build-for-testing`, `APP-01/runner/p1`).
    step = "/".join(output_directory.parts[-3:])
    progress.event("command-start", step=step, program=Path(argv[0]).name)
    process = process_factory(
        argv,
        cwd=Path(cwd),
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )
    lines = queue.Queue()

    def pump(label, stream):
        try:
            for line in iter(stream.readline, ""):
                lines.put((label, line))
        finally:
            lines.put((label, None))

    readers = [
        threading.Thread(target=pump, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=pump, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    ended_streams = set()
    timed_out = False
    parse_error = None
    unseen_milestones = dict(_COMMAND_MILESTONES)
    deadline = started + timeout_seconds
    with stdout_path.open("w", encoding="utf-8") as stdout_log, stderr_path.open("w", encoding="utf-8") as stderr_log:
        logs = {"stdout": stdout_log, "stderr": stderr_log}
        while len(ended_streams) < 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()
                break
            try:
                label, line = lines.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if process.poll() is not None and all(not reader.is_alive() for reader in readers):
                    break
                continue
            if line is None:
                ended_streams.add(label)
                continue
            logs[label].write(_redact_log_line(line))
            logs[label].flush()
            for marker, milestone in list(unseen_milestones.items()):
                if marker in line:
                    del unseen_milestones[marker]
                    progress.event("command-milestone", step=step, milestone=milestone,
                                   seconds=time.monotonic() - started)
            if label == "stdout" and status_parser is not None:
                try:
                    status = status_parser(line)
                    if status is not None and on_status is not None:
                        on_status(status)
                except Exception as exc:
                    parse_error = exc
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        process.kill()
                    break
    if timed_out or parse_error is not None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    else:
        process.wait()
    for reader in readers:
        reader.join(timeout=1)
    process.stdout.close()
    process.stderr.close()
    progress.event("command-end", step=step, exitCode=process.returncode, timedOut=timed_out,
                   seconds=time.monotonic() - started)
    if parse_error is not None:
        raise ValueError(f"native controller status stream was rejected: {parse_error}") from parse_error
    return {
        "argv": list(argv),
        "cwd": str(Path(cwd).resolve()),
        "exitCode": process.returncode,
        "timedOut": timed_out,
        "durationSeconds": time.monotonic() - started,
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
    }


class AndroidInstrumentationStatusParser:
    """Collect one Android `sendStatus` Bundle at a time from am-instrument output."""

    def __init__(self, *, expected_scenario_id, expected_process_instance_id):
        self.expected_scenario_id = expected_scenario_id
        self.expected_process_instance_id = expected_process_instance_id
        self._fields = {}

    def feed(self, line):
        prefix = "INSTRUMENTATION_STATUS: "
        # `am instrument -w` prints a run's first status field on the same line as
        # the test-class banner ("<class>:INSTRUMENTATION_STATUS: key=value").
        start = line.find(prefix)
        if start >= 0:
            field = line[start + len(prefix):].rstrip("\r\n")
            if "=" not in field:
                raise ValueError("Android instrumentation status field is malformed")
            key, value = field.split("=", 1)
            if key in self._fields:
                raise ValueError("Android instrumentation status repeats a field")
            if key in (_STATUS_REQUIRED | _STATUS_OPTIONAL):
                self._fields[key] = value
            return None
        if line.startswith("INSTRUMENTATION_STATUS_CODE: "):
            code = line.split(":", 1)[1].strip()
            fields, self._fields = self._fields, {}
            if code != "2" or "checkpointName" not in fields:
                return None
            return _validated_status(
                fields,
                expected_scenario_id=self.expected_scenario_id,
                expected_process_instance_id=self.expected_process_instance_id,
            )
        return None


class LoopbackRun:
    """Own one refresh-server process and keep its control capability in memory."""

    def __init__(self, *, candidate, output, platform, scenario_id, attempt_id, process=subprocess.Popen):
        self.candidate = Path(candidate).resolve()
        self.output = Path(output)
        self.platform = platform
        self.scenario_id = scenario_id
        self.attempt_id = attempt_id
        self.process = process
        self.server_root = self.output / "server"
        self.server_root.mkdir(parents=True)
        self.ready_path = self.server_root / "server-ready.json"
        self.stdout_path = self.server_root / "stdout.log"
        self.stderr_path = self.server_root / "stderr.log"
        self.process_handle = None
        self.port = None
        self.run_id = None
        self._control_key = None
        self._closed = False

    def _url(self, path):
        if self.port is None:
            raise RuntimeError("server is not ready")
        return f"http://127.0.0.1:{self.port}{path}"

    def _request(self, method, path, *, body=None, authenticated=False, timeout=5):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if authenticated:
            if not isinstance(self._control_key, str) or not self._control_key:
                raise RuntimeError("control capability is unavailable")
            headers["X-Demo-Control-Key"] = self._control_key
        request = Request(self._url(path), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(1_048_577)
                if len(payload) > 1_048_576:
                    raise ValueError("refresh server response exceeds the controller limit")
                document = json.loads(payload)
                if not isinstance(document, dict):
                    raise ValueError("refresh server response is not an object")
                return document
        except HTTPError as exc:
            payload = exc.read(65537)
            raise ValueError(f"refresh server returned HTTP {exc.code}: {payload[:512]!r}") from exc
        except URLError as exc:
            raise OSError(f"refresh server request failed: {exc.reason}") from exc

    def start(self, *, timeout_seconds=60):
        if self.process_handle is not None:
            raise RuntimeError("refresh server was already started")
        started = time.monotonic()
        argv = [
            sys.executable, "-m", "integration.server",
            "--bind", "127.0.0.1", "--port", "0", "--output", str(self.server_root),
        ]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.candidate)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with self.stdout_path.open("wb") as stdout, self.stderr_path.open("wb") as stderr:
            self.process_handle = self.process(
                argv,
                cwd=self.candidate,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.process_handle.poll() is not None:
                raise RuntimeError(f"refresh server exited before binding: {self.process_handle.returncode}")
            if self.ready_path.is_file():
                try:
                    ready = json.loads(self.ready_path.read_text())
                    if (
                        set(ready) != {"version", "bindAddress", "port", "pid"}
                        or ready.get("version") != 1
                        or ready.get("bindAddress") not in {"127.0.0.1", "::1"}
                        or type(ready.get("port")) is not int
                        or not 1 <= ready["port"] <= 65535
                        or ready.get("pid") != self.process_handle.pid
                    ):
                        raise ValueError("refresh server readiness record is invalid or unowned")
                    self.port = ready["port"]
                    health = self._request("GET", "/health")
                    if health != {"version": 1, "ready": True}:
                        raise RuntimeError("refresh server health check failed")
                    created = self._request(
                        "POST", "/control/runs",
                        body={"version": 1, "attemptId": self.attempt_id, "scenarioId": self.scenario_id, "platform": self.platform},
                    )
                    if set(created) != {"version", "runId", "controlKey"} or created.get("version") != 1:
                        raise ValueError("refresh server run response is invalid")
                    if _ANDROID_LABEL.fullmatch(created.get("runId", "")) is None:
                        raise ValueError("refresh server run ID is invalid")
                    key = created.get("controlKey")
                    if not isinstance(key, str) or len(key) < 32:
                        raise ValueError("refresh server control capability is invalid")
                    self.run_id = created["runId"]
                    self._control_key = key
                    progress.event("server-ready", scenario=self.scenario_id, seconds=time.monotonic() - started)
                    return ready
                except Exception:
                    self.stop()
                    raise
            time.sleep(0.05)
        self.stop()
        raise TimeoutError("refresh server did not publish its readiness record")

    @property
    def base_url(self):
        if self.port is None:
            raise RuntimeError("server is not ready")
        host = "10.0.2.2" if self.platform == "android" else "127.0.0.1"
        return f"http://{host}:{self.port}"

    def events(self, *, timeout=5):
        if self.run_id is None:
            raise RuntimeError("run is not initialized")
        result = self._request(
            "GET", f"/control/runs/{self.run_id}/events", authenticated=True, timeout=timeout
        )
        if set(result) != {"version", "runId", "events", "bodyDigests"} or result.get("runId") != self.run_id:
            raise ValueError("refresh server event response is invalid")
        return result["events"], result["bodyDigests"]

    def pending(self, *, timeout=5):
        if self.run_id is None:
            raise RuntimeError("run is not initialized")
        result = self._request(
            "GET", f"/control/runs/{self.run_id}/pending", authenticated=True, timeout=timeout
        )
        if set(result) != {"version", "runId", "pending"} or result.get("runId") != self.run_id or not isinstance(result.get("pending"), list):
            raise ValueError("refresh server pending response is invalid")
        return result["pending"]

    def release(self, request_tag, outcome, *, timeout=5):
        if self.run_id is None:
            raise RuntimeError("run is not initialized")
        return self._request(
            "POST", f"/control/runs/{self.run_id}/release",
            body={"version": 1, "requestTag": request_tag, **outcome},
            authenticated=True, timeout=timeout,
        )

    def publish_checkpoint(self, process_instance_id, name, *, timeout=5):
        if self.run_id is None:
            raise RuntimeError("run is not initialized")
        return self._request(
            "POST", f"/control/runs/{self.run_id}/checkpoints",
            body={"version": 1, "processInstanceId": process_instance_id, "name": name},
            authenticated=True, timeout=timeout,
        )

    def stop(self, *, timeout_seconds=5):
        if self._closed:
            return
        self._closed = True
        started = time.monotonic()
        if self.run_id is not None and self._control_key is not None:
            try:
                self._request("DELETE", f"/control/runs/{self.run_id}", authenticated=True)
            except (OSError, ValueError, RuntimeError):
                pass
        self._control_key = None
        if self.process_handle is not None and self.process_handle.poll() is None:
            self.process_handle.terminate()
            try:
                self.process_handle.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process_handle.kill()
                self.process_handle.wait(timeout=timeout_seconds)
        progress.event("server-stopped", scenario=self.scenario_id, seconds=time.monotonic() - started)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop()
        return False


def _append_controller_event(events, kind, process_instance_id, **values):
    row = {
        "sequence": len(events) + 1,
        "kind": kind,
        "processInstanceId": process_instance_id,
        **values,
    }
    events.append(row)
    return row


def _decode_store_status(raw):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("redacted store probe status is not JSON") from exc
    if isinstance(value, dict) and set(value) == {"probeId", "processInstanceId", "observation"}:
        value = value["observation"]
    if not _safe_store_observation(value):
        raise ValueError("redacted store probe status does not match the frozen value schema")
    return value


def parse_rendered_state(raw, *, process_instance_id):
    """Convert protected accessibility fields into a redacted rendered projection."""
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("rendered UI status is not JSON") from exc
    required = {
        "session-state", "credential-status", "view-process-id", "view-revision",
    }
    allowed = required | {"last-command-id", "last-command-status", "control-status-json", "store-probe-result"}
    if not isinstance(values, dict) or not required <= set(values) or set(values) - allowed:
        raise ValueError("rendered UI status has an invalid field set")
    if values["view-process-id"] != process_instance_id:
        raise ValueError("rendered UI process identity differs from the active launch")
    text_values = [value for value in values.values() if isinstance(value, str)]
    if any(_SENSITIVE_TEXT.search(value) for value in text_values):
        raise ValueError("rendered UI status contains credential text")
    revision = values["view-revision"]
    if isinstance(revision, str) and re.fullmatch(r"[1-9][0-9]{0,18}", revision):
        revision = int(revision)
    if type(revision) is not int or not 1 <= revision <= (1 << 63) - 1:
        raise ValueError("rendered UI revision is not a positive signed64 integer")
    label = values["session-state"].strip()
    lowered = label.lower()
    if lowered == "booting":
        phase = "Booting"
    elif lowered == "signed out":
        phase = "SignedOut"
    elif lowered == "signing out":
        phase = "SigningOut"
    elif lowered in {"cleanup failed", "fault locked"}:
        phase = "FaultLocked"
    elif lowered.startswith("signed in"):
        phase = "SignedIn"
    elif lowered.startswith("refreshing"):
        phase = "Refreshing"
    else:
        raise ValueError("rendered UI session-state label is outside the frozen set")
    account_match = re.search(r"(?:demo-)?([AB])(?:$|[^A-Za-z0-9])", label)
    account = account_match.group(1) if account_match else None
    if phase in {"SignedIn", "Refreshing"}:
        if account not in {"A", "B"}:
            raise ValueError("authenticated rendered UI lacks its account label")
    elif account is not None:
        raise ValueError("unauthenticated rendered UI contains an account label")
    if not isinstance(values["credential-status"], str) or not values["credential-status"]:
        raise ValueError("rendered UI credential-status label is missing")
    return {"phase": phase, "account": account, "revision": revision}


def _append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if _SENSITIVE_TEXT.search(encoded):
        raise ValueError("redacted controller artifact would contain credential text")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def capture_probe_status(
    run,
    *,
    platform,
    serial,
    attempt_id,
    status,
    required_probe_ids,
    observations,
    controller_events,
    known_server_sequences,
    process_artifact_directory,
    previous_command_ref=None,
    command_ref=None,
    timeout_seconds=15,
    deadline=None,
):
    """Persist an independent redacted probe before acknowledging its server barrier."""
    process_id = status["processInstanceId"]
    checkpoint = status["checkpointName"]
    if checkpoint == "bootstrapStoreProbed":
        step_ids = [step for step in required_probe_ids if "before-bootstrap-clear" in step]
        if len(step_ids) != 1:
            raise ValueError("Bootstrap checkpoint does not map to one frozen pre-clear probe")
        step_id = step_ids[0]
    elif checkpoint.startswith("storeProbe."):
        step_id = checkpoint.removeprefix("storeProbe.")
        if step_id not in required_probe_ids:
            raise ValueError("host probe checkpoint names an undeclared inventory step")
    else:
        raise ValueError("native progress named an undeclared storage checkpoint")
    if platform == "android":
        observation = read_android_storage_probe(
            serial=serial,
            attempt_id=attempt_id,
            scenario_id=status["scenarioId"],
            timeout_seconds=timeout_seconds,
            deadline=deadline,
        )
        supplemental = status.get("redactedProbe")
        if supplemental is not None:
            supplemental_observation = _decode_store_status(supplemental)
            if observation.get("kind") != "Unknown" and supplemental_observation != observation:
                raise ValueError("Android independent app probe disagrees with the host filesystem probe")
    elif platform == "ios":
        raw = status.get("redactedObservation")
        if raw is None:
            raise ValueError("iOS native storage probe omitted its frozen redacted observation")
        observation = _decode_store_status(raw)
    else:
        raise ValueError("probe platform is outside the frozen set")

    next_sequence = len(controller_events) + 1
    row = {
        "kind": "storageProbe",
        "stepId": step_id,
        "processInstanceId": process_id,
        "controllerSequence": next_sequence,
        "observation": observation,
    }
    if command_ref is not None:
        if (
            not isinstance(command_ref, dict)
            or set(command_ref) != {"processInstanceId", "id"}
            or command_ref.get("processInstanceId") != process_id
            or type(command_ref.get("id")) is not int
            or not 1 <= command_ref["id"] <= (1 << 63) - 1
        ):
            raise ValueError("independent probe command reference is invalid")
        row["commandRef"] = command_ref
    else:
        command_id = status.get("lastProcessedCommandId")
        if command_id is not None:
            if not re.fullmatch(r"[1-9][0-9]{0,18}", str(command_id)) or int(command_id) > (1 << 63) - 1:
                raise ValueError("probe status command ID is invalid")
            row["commandRef"] = {"processInstanceId": process_id, "id": int(command_id)}
        elif previous_command_ref is not None:
            row["commandRef"] = previous_command_ref
    _append_jsonl(Path(process_artifact_directory) / "ui.jsonl", row)
    observations.append(row)
    _append_controller_event(controller_events, "probeCaptured", process_id, stepId=step_id)
    checkpoint_timeout = min(5, timeout_seconds)
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _NativeStageDeadlineExceeded("native platform stage deadline exhausted before probe checkpoint")
        checkpoint_timeout = min(checkpoint_timeout, remaining)
    run.publish_checkpoint(process_id, checkpoint, timeout=checkpoint_timeout)
    server_timeout = min(5, timeout_seconds)
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _NativeStageDeadlineExceeded("native platform stage deadline exhausted before probe event capture")
        server_timeout = min(server_timeout, remaining)
    append_server_controller_events(
        run, known_server_sequences, controller_events, timeout_seconds=server_timeout
    )
    return row


def record_rendered_status(status, *, observations, process_artifact_directory):
    checkpoint = status["checkpointName"]
    if not checkpoint.startswith("renderedView."):
        raise ValueError("rendered UI status has no frozen observation step ID")
    step_id = checkpoint.removeprefix("renderedView.")
    projection = parse_rendered_state(status.get("renderedState"), process_instance_id=status["processInstanceId"])
    row = {
        "kind": "renderedView",
        "stepId": step_id,
        "processInstanceId": status["processInstanceId"],
        "revision": projection["revision"],
        "phase": projection["phase"],
        "account": projection["account"],
    }
    observations.append(row)
    return row


def append_server_controller_events(run, known_sequences, controller_events, *, timeout_seconds=None):
    """Translate each newly observed server boundary to one controller event."""
    if timeout_seconds is None:
        server_events, _ = run.events()
    else:
        server_events, _ = run.events(timeout=min(5, timeout_seconds))
    for event in server_events:
        server_sequence = event.get("sequence")
        if type(server_sequence) is not int or server_sequence in known_sequences:
            continue
        known_sequences.add(server_sequence)
        kind = event.get("kind")
        if kind in {"requestHeld", "releaseAccepted", "responseWritten", "disconnected", "wrongCorrelation"}:
            request_tag = event.get("requestTag")
            if not isinstance(request_tag, str) or ":refresh:" not in request_tag:
                raise ValueError("server event has no owned refresh process tag")
            process_instance_id = request_tag.rsplit(":refresh:", 1)[0]
            values = {"requestTag": request_tag}
            if kind in {"releaseAccepted", "responseWritten", "disconnected", "wrongCorrelation"}:
                values["serverSequence"] = server_sequence
            if kind == "wrongCorrelation":
                values["echoedRequestTag"] = event["echoedRequestTag"]
            _append_controller_event(controller_events, kind, process_instance_id, **values)
        elif kind == "checkpointPublished":
            _append_controller_event(
                controller_events,
                kind,
                event["processInstanceId"],
                name=event["name"],
                serverSequence=server_sequence,
            )
    return server_events


def _release_outcome(command, variant):
    match = re.fullmatch(r"Deliver\((?:slot-[AB][1-9][0-9]*|current),([A-Za-z]+)\)", command or "")
    if match is None:
        raise ValueError("release status does not name one frozen Deliver command")
    label = match.group(1)
    selected = variant if isinstance(variant, dict) else {}
    outcome = selected.get("outcome")
    if outcome is None:
        outcome = {
            "success": "success",
            "failure": "failure",
            "serverError": "http500",
            "malformed": "malformed",
            "disconnected": "disconnect",
            "correlationMismatch": "wrongCorrelation",
        }.get(label)
    if outcome == "success":
        return {"outcome": "success", "credentialVersion": 1}
    if outcome == "failure":
        return {"outcome": "failure", "failure": "rejected"}
    if outcome in {"http500", "malformed", "disconnect"}:
        return {"outcome": outcome}
    if outcome == "wrongCorrelation":
        return {"outcome": outcome, "credentialVersion": 1}
    raise ValueError("frozen Deliver command has no supported server outcome")


def release_pending_delivery(
    run,
    *,
    command,
    variant,
    process_instance_id,
    wire_tag,
    controller_events,
    known_server_sequences,
    timeout_seconds=10,
):
    """Release only the held issuance named by the frozen Deliver action."""
    if not isinstance(wire_tag, str) or not wire_tag.startswith(process_instance_id + ":refresh:"):
        raise ValueError("Deliver release requires the native-issued process wireTag")
    deadline = time.monotonic() + timeout_seconds
    pending = []
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        append_server_controller_events(
            run, known_server_sequences, controller_events, timeout_seconds=remaining
        )
        pending_remaining = deadline - time.monotonic()
        if pending_remaining <= 0:
            break
        pending = run.pending(timeout=min(5, pending_remaining))
        selected = [row for row in pending if row.get("requestTag") == wire_tag]
        if len(selected) == 1:
            break
        if len(selected) > 1:
            raise ValueError("native wireTag identifies multiple held requests")
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    else:
        raise TimeoutError("no held response matches the native-issued wireTag before the controller deadline")
    request_tag = selected[0]["requestTag"]
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("held response expired before the release request could be sent")
    server_events = append_server_controller_events(
        run, known_server_sequences, controller_events, timeout_seconds=remaining
    )
    if not any(event.get("kind") == "requestHeld" and event.get("requestTag") == request_tag for event in server_events):
        raise ValueError("selected pending request lacks its server requestHeld event")
    _append_controller_event(controller_events, "releaseRequested", process_instance_id, requestTag=request_tag)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("held response expired before the release request could be sent")
    response = run.release(request_tag, _release_outcome(command, variant), timeout=min(5, remaining))
    if response.get("status") != "releaseAccepted" or response.get("requestTag") != request_tag:
        raise ValueError("refresh server did not accept the selected response release")
    terminal_kinds = {"responseWritten", "disconnected"}
    # One status operation may not spend a fresh timeout after server acceptance.
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server_events = append_server_controller_events(
            run, known_server_sequences, controller_events, timeout_seconds=remaining
        )
        matching = [event for event in server_events if event.get("requestTag") == request_tag and event.get("kind") in terminal_kinds]
        if matching:
            return request_tag, server_events
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise TimeoutError("released response did not reach a terminal transport event")


def _native_events_from_bytes(raw_bytes, *, process_instance_id):
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise ValueError("native audit file is missing or empty")
    text = raw_bytes.decode("utf-8", errors="strict")
    if _SENSITIVE_TEXT.search(text):
        raise ValueError("native audit stream contains credential text")
    events = []
    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"native audit line {line_number} is malformed JSON") from exc
        if not isinstance(event, dict) or event.get("processInstanceId") != process_instance_id:
            raise ValueError(f"native audit line {line_number} belongs to another process")
        events.append(event)
    sequences = [event.get("localSequence") for event in events]
    if any(type(value) is not int or value <= 0 for value in sequences) or sequences != list(range(1, len(sequences) + 1)):
        raise ValueError("native audit local sequences are not contiguous")
    return events


def read_live_native_events(
    *, platform, device, attempt_id, process_instance_id, command_runner=subprocess.run, timeout_seconds=15
):
    """Read the frozen process-scoped audit file without exposing credential bytes."""
    parts = process_instance_id.split("/")
    if len(parts) != 3 or parts[0] != attempt_id or not re.fullmatch(r"p[1-9][0-9]*", parts[2]):
        raise ValueError("native audit identity is outside the current attempt namespace")
    relative = f"native-harness/{attempt_id}/{parts[1]}/{parts[2]}/native-events.jsonl"
    if platform == "android":
        android_relative = f"no_backup/{relative}"
        argv = ["adb", "-s", device, "exec-out", "run-as", "dev.nativecontract.demo.android", "cat", android_relative]
        result = command_runner(argv, capture_output=True, text=False, timeout=timeout_seconds)
        if result.returncode != 0:
            raise OSError("owned Android native audit file is unavailable")
        return _native_events_from_bytes(result.stdout, process_instance_id=process_instance_id)
    if platform == "ios":
        container = command_runner(
            ["xcrun", "simctl", "get_app_container", device, "dev.nativecontract.demo.ios", "data"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if container.returncode != 0 or not isinstance(container.stdout, str) or not container.stdout.strip():
            raise OSError("owned iOS simulator app container is unavailable")
        path = Path(container.stdout.strip()) / "Documents" / relative
        try:
            return _native_events_from_bytes(path.read_bytes(), process_instance_id=process_instance_id)
        except OSError as exc:
            raise OSError("owned iOS native audit file is unavailable") from exc
    raise ValueError("platform is outside the frozen set")


def _resolve_delivery_slot_id(scenario, variant, command):
    match = re.fullmatch(r"Deliver\((slot-[AB][1-9][0-9]*|current),[A-Za-z]+\)", command or "")
    if match is None:
        raise ValueError("release status does not name a frozen Deliver command")
    direct = match.group(1)
    if direct != "current":
        return direct
    selected = variant if isinstance(variant, dict) else {}
    candidates = []
    for key in ("requiredDelivery", "expectedDeliveries"):
        value = selected.get(key, scenario.get(key))
        if isinstance(value, dict) and isinstance(value.get("slotId"), str):
            candidates.append(value["slotId"])
        elif isinstance(value, list):
            candidates.extend(item["slotId"] for item in value if isinstance(item, dict) and isinstance(item.get("slotId"), str))
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else None


def _wire_tag_for_delivery(native_events, *, process_instance_id, scenario, variant, command):
    slot_id = _resolve_delivery_slot_id(scenario, variant, command)
    issued = [
        event for event in native_events
        if event.get("kind") == "slotIssued"
        and event.get("processInstanceId") == process_instance_id
        and (slot_id is None or event.get("slotId") == slot_id)
    ]
    received_tags = {
        event.get("requestTag") for event in native_events
        if event.get("kind") == "transportReceived" and event.get("processInstanceId") == process_instance_id
    }
    issued = [event for event in issued if event.get("wireTag") not in received_tags]
    if len(issued) != 1:
        raise ValueError("native slotIssued history does not identify one unconsumed Deliver slot")
    event = issued[0]
    tag = event.get("wireTag")
    command_ref = event.get("commandRef")
    if (
        not isinstance(tag, str)
        or not tag.startswith(process_instance_id + ":refresh:")
        or not isinstance(command_ref, dict)
        or command_ref.get("processInstanceId") != process_instance_id
        or tag != f"{process_instance_id}:refresh:{command_ref.get('id')}"
    ):
        raise ValueError("native slot wireTag is inconsistent with its process/issuance command")
    return tag


class NativeProgressBridge:
    """Apply the frozen host probes and server controls to streamed test progress."""

    def __init__(
        self,
        *,
        platform,
        run,
        device,
        attempt_id,
        scenario,
        variant,
        controller_events,
        observations,
        process_artifact_directory,
        command_runner=subprocess.run,
        deadline=None,
    ):
        self.platform = platform
        self.run = run
        self.device = device
        self.attempt_id = attempt_id
        self.scenario = scenario
        self.variant = variant
        self.controller_events = controller_events
        self.observations = observations
        self.case_artifact_directory = Path(process_artifact_directory)
        self.known_server_sequences = set()
        self.last_command_ref = {}
        self.receipt_statuses = []
        self.probe_ids_seen = set()
        self.probe_preflight_by_process = {}
        self.process_artifact_directories = {}
        self.command_runner = command_runner
        self.deadline = deadline
        self.end_seen = set()
        self.process_end_ack_seen = set()
        self.hook_status_seen = set()
        self.hook_arm_sequence_by_point = {}
        self.bootstrap_probe_command_refs = {}

    @staticmethod
    def _boolean(value):
        return value is True or value == "true"

    def _remaining_timeout(self, maximum, *, deadline=None):
        target = self.deadline if deadline is None else deadline
        if target is None:
            return maximum
        remaining = target - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("native platform stage deadline exhausted")
        return min(maximum, remaining)

    def _read_native_events_until(self, process_id, select, *, description):
        started = time.monotonic()
        retry_deadline = started + 15
        if self.deadline is not None:
            retry_deadline = min(retry_deadline, self.deadline)
        last_error = None
        while True:
            remaining = retry_deadline - time.monotonic()
            if remaining <= 0:
                detail = f": {last_error}" if last_error is not None else ""
                reason = "stable error window" if last_error is not None else "retry window"
                raise TimeoutError(f"{description} was not visible before the 15-second audit {reason}{detail}") from last_error
            try:
                events = read_live_native_events(
                    platform=self.platform,
                    device=self.device,
                    attempt_id=self.attempt_id,
                    process_instance_id=process_id,
                    command_runner=self.command_runner,
                    timeout_seconds=min(15, remaining),
                )
                selected = select(events)
                return selected
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                last_error = exc
            remaining = retry_deadline - time.monotonic()
            if remaining <= 0:
                detail = f": {last_error}" if last_error is not None else ""
                reason = "stable error window" if last_error is not None else "retry window"
                raise TimeoutError(f"{description} was not visible before the 15-second audit {reason}{detail}") from last_error
            time.sleep(min(0.05, remaining))

    def _bootstrap_probe_command_ref(self, status, snapshot=None):
        process_id = status["processInstanceId"]
        if self.platform == "ios":
            snapshot = snapshot or _decode_control_snapshot(
                status.get("controlSnapshotJSON"), expected_process_instance_id=process_id
            )
            requested_ref = snapshot.get("lastEnqueuedCommandRef")
        else:
            command_id = status.get("lastEnqueuedCommandId")
            if not re.fullmatch(r"[1-9][0-9]{0,18}", str(command_id)):
                raise ValueError("Bootstrap probe snapshot omitted its enqueued command ID")
            requested_ref = {"processInstanceId": process_id, "id": int(command_id)}
        if (
            not isinstance(requested_ref, dict)
            or set(requested_ref) != {"processInstanceId", "id"}
            or requested_ref.get("processInstanceId") != process_id
            or requested_ref.get("id") != 1
        ):
            raise ValueError("pre-clear probe is not bound to process-local Bootstrap command 1")

        def select(events):
            enqueued = [
                event for event in events
                if event.get("kind") == "commandEnqueued"
                and event.get("commandRef") == requested_ref
                and event.get("name") == "Bootstrap"
            ]
            started = [
                event for event in events
                if event.get("kind") == "commandStarted" and event.get("commandRef") == requested_ref
            ]
            if len(enqueued) != 1 or len(started) != 1:
                raise ValueError("paused pre-clear probe has no unique enqueued and started Bootstrap record")
            if any(event.get("kind") == "commandReceipt" and event.get("commandRef") == requested_ref for event in events):
                raise ValueError("pre-clear Bootstrap probe occurred after its receipt")
            return requested_ref

        command_ref = self._read_native_events_until(
            process_id, select, description="started Bootstrap command reference"
        )
        return command_ref

    def _record_hook_status(self, status):
        if "hookPoint" not in status:
            return
        process_id = status["processInstanceId"]
        point = status["hookPoint"]
        phase = status["hookPhase"]
        arm_sequence = int(status["hookArmSequence"])
        hook_key = (process_id, point)
        previous_arm_sequence = self.hook_arm_sequence_by_point.get(hook_key)
        if previous_arm_sequence is not None and previous_arm_sequence != arm_sequence:
            raise ValueError("native hook arm sequence changed across its lifecycle")
        self.hook_arm_sequence_by_point[hook_key] = arm_sequence
        key = (process_id, point, phase)
        if key in self.hook_status_seen:
            return
        self.hook_status_seen.add(key)
        if phase == "armed":
            _append_controller_event(
                self.controller_events,
                "hookArmed",
                process_id,
                point=point,
                target=status.get("hookTarget", "nextCommand"),
            )
        elif phase == "arrived":
            kwargs = {"point": point, "authMailboxPaused": self._boolean(status.get("authMailboxPaused", False))}
            _append_controller_event(self.controller_events, "hookArrived", process_id, **kwargs)
            if point == "beforeBootstrapClear":
                _append_controller_event(self.controller_events, "bootstrapHookArrived", process_id, **kwargs)
        elif phase == "released":
            _append_controller_event(
                self.controller_events,
                "hookReleased",
                process_id,
                point=point,
                releaseChannel="DebugScenarioControl",
                authMailboxPaused=self._boolean(status.get("authMailboxPaused", True)),
                bootstrapReceiptObserved=self._boolean(status.get("bootstrapReceiptObserved", False)),
                deliverReceiptObserved=self._boolean(status.get("deliverReceiptObserved", False)),
            )

    @staticmethod
    def _process_end_reference(status, process_id):
        try:
            acknowledgement = json.loads(status["processEndAckJSON"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("processEnd acknowledgement JSON is malformed") from exc
        reference = acknowledgement.get("eventRef") if isinstance(acknowledgement, dict) else None
        if (
            not isinstance(acknowledgement, dict)
            or acknowledgement.get("processInstanceId") != process_id
            or not isinstance(reference, dict)
            or set(reference) != {"processInstanceId", "localSequence"}
            or reference.get("processInstanceId") != process_id
            or type(reference.get("localSequence")) is not int
            or not 1 <= reference["localSequence"] <= (1 << 63) - 1
        ):
            raise ValueError("processEnd acknowledgement is not bound to this process")
        return reference

    def _accept_new_probe_id(self, status):
        process_id = status.get("processInstanceId")
        raw = status.get("redactedObservation")
        if raw is None:
            raw = status.get("redactedProbe")
        if raw is None:
            if self.platform == "ios":
                raise ValueError("iOS store probe omitted its fresh probeId envelope")
            return None
        try:
            envelope = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("native store probe envelope is malformed") from exc
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"probeId", "processInstanceId", "observation"}
            or envelope.get("processInstanceId") != process_id
            or not isinstance(envelope.get("probeId"), str)
            or not envelope["probeId"]
            or not _safe_store_observation(envelope.get("observation"))
        ):
            raise ValueError("native store probe envelope has invalid process identity or observation")
        key = (process_id, envelope["probeId"])
        if key in self.probe_ids_seen:
            raise ValueError("native store probe probeId was reused in one process")
        self.probe_ids_seen.add(key)
        return envelope["probeId"]

    def _await_detached_effect(self, status):
        process_id = status["processInstanceId"]
        effect_id = status["effectId"]
        declared = [
            effect for effect in self.scenario.get("effects", [])
            if isinstance(effect, dict) and effect.get("effectId") == effect_id
        ]
        if len(declared) != 1:
            raise ValueError("detached-effect wait does not match one frozen effect")
        expected_origin = declared[0].get("originCommandRef")
        origin = json.loads(status["effectOriginCommandRef"])
        launch_match = re.fullmatch(r".*/p([1-9][0-9]*)", process_id)
        if (
            not isinstance(expected_origin, dict)
            or not launch_match
            or type(expected_origin.get("launchOrdinal")) is not int
            or expected_origin["launchOrdinal"] != int(launch_match.group(1))
            or origin.get("processInstanceId") != process_id
        ):
            raise ValueError("detached-effect wait has a mismatched frozen origin")

        deadline = time.monotonic() + 60
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        last_read_error = None
        while time.monotonic() < deadline:
            try:
                events = read_live_native_events(
                    platform=self.platform,
                    device=self.device,
                    attempt_id=self.attempt_id,
                    process_instance_id=process_id,
                    command_runner=self.command_runner,
                    timeout_seconds=min(15, deadline - time.monotonic()),
                )
                last_read_error = None
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                last_read_error = exc
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                continue

            origin_rows = [
                event for event in events
                if event.get("kind") == "commandEnqueued"
                and event.get("commandRef") == origin
                and event.get("name") == expected_origin.get("command")
            ]
            if len(origin_rows) != 1:
                if any(event.get("commandRef") == origin for event in events if event.get("kind") == "commandEnqueued"):
                    raise ValueError("detached-effect origin command does not match the frozen inventory")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
                continue

            mutations = [event for event in events if event.get("kind") == "detachedStoreMutation" and event.get("effectId") == effect_id]
            readbacks = [event for event in events if event.get("kind") == "detachedStoreReadback" and event.get("effectId") == effect_id]
            if mutations and readbacks:
                mutation = mutations[0]
                readback = readbacks[0]
                observed_origin = mutation.get("originCommandRef")
                if not isinstance(observed_origin, dict):
                    raise ValueError("detached mutation has no origin command reference")
                _append_controller_event(
                    self.controller_events,
                    "detachedEffectAwaited",
                    process_id,
                    effectId=effect_id,
                    originCommandRef=observed_origin,
                    mutationEventRef={"processInstanceId": process_id, "localSequence": mutation.get("localSequence")},
                    readbackEventRef={"processInstanceId": process_id, "localSequence": readback.get("localSequence")},
                )
                checkpoint = f"detachedEffectAwaited.{effect_id}"
                checkpoint_timeout = self._remaining_timeout(5, deadline=deadline)
                self.run.publish_checkpoint(process_id, checkpoint, timeout=checkpoint_timeout)
                return
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        detail = f": {last_read_error}" if last_read_error is not None else ""
        raise TimeoutError(f"detached effect {effect_id} did not reach mutation/readback completion{detail}")

    def __call__(self, status):
        process_id = status["processInstanceId"]
        process_parts = process_id.split("/")
        if len(process_parts) != 3 or re.fullmatch(r"p[1-9][0-9]*", process_parts[2]) is None:
            raise ValueError("native progress process ID is outside the frozen namespace")
        process_artifact_directory = self.case_artifact_directory / process_parts[2]
        self.process_artifact_directories[process_id] = process_artifact_directory
        phase = status["phase"]
        if process_id in self.process_end_ack_seen and phase != "end":
            raise ValueError("native controller progress continued after processEnd acknowledgement")
        if phase == "processEndAcknowledged":
            if process_id in self.process_end_ack_seen or process_id in self.end_seen:
                raise ValueError("processEnd acknowledgement was duplicated or arrived after harness end")
            reference = self._process_end_reference(status, process_id)

            def select_terminal_end(events):
                process_events = [event for event in events if event.get("processInstanceId") == process_id]
                end_rows = [event for event in process_events if event.get("kind") == "processEnd"]
                if not end_rows:
                    raise ValueError("processEnd event is not yet visible")
                if len(end_rows) != 1:
                    raise ValueError("processEnd event is duplicated")
                end_row = end_rows[0]
                if end_row.get("localSequence") != reference["localSequence"]:
                    raise ValueError("processEnd acknowledgement references a different native event")
                if not process_events or process_events[-1] is not end_row:
                    raise ValueError("native event appears after processEnd")
                return {"processInstanceId": process_id, "localSequence": end_row["localSequence"]}

            actual_reference = self._read_native_events_until(
                process_id, select_terminal_end, description="synced terminal processEnd event"
            )
            _append_controller_event(
                self.controller_events,
                "processEndAcknowledged",
                process_id,
                eventRef=actual_reference,
            )
            self.process_end_ack_seen.add(process_id)
            return
        if process_id in self.process_end_ack_seen and phase == "end":
            self.end_seen.add(process_id)
            return
        self._record_hook_status(status)
        if status["phase"] == "receiptObserved":
            checkpoint_id = status["checkpointName"].rsplit(".", 1)[-1]
            command_id = status.get("lastProcessedCommandId") or checkpoint_id
            if not re.fullmatch(r"[1-9][0-9]{0,18}", str(command_id)):
                raise ValueError("receipt progress lacks a positive command ID")
            command_ref = {"processInstanceId": process_id, "id": int(command_id)}
            event = _append_controller_event(
                self.controller_events,
                "receiptObserved",
                process_id,
                commandRef=command_ref,
            )
            self.receipt_statuses.append((event, command_ref))
            self.last_command_ref[process_id] = command_ref
        elif status["phase"] == "probeRequested":
            bootstrap_command_ref = None
            if self.platform == "ios":
                raw_snapshot = status.get("controlSnapshotJSON")
                if raw_snapshot is None:
                    raise ValueError("iOS host probe omitted the independent control snapshot preflight")
                snapshot = _decode_control_snapshot(raw_snapshot, expected_process_instance_id=process_id)
                if snapshot["storeIoActive"]:
                    raise ValueError("iOS host probe requested while native store I/O is active")
                previous_probe = snapshot.get("lastProbe")
                self.probe_preflight_by_process[process_id] = previous_probe.get("probeId") if previous_probe else None
                if status.get("checkpointName") == "bootstrapStoreProbed":
                    bootstrap_command_ref = self._bootstrap_probe_command_ref(status, snapshot)
                    self.bootstrap_probe_command_refs[process_id] = bootstrap_command_ref
                return
            if status.get("checkpointName") == "bootstrapStoreProbed":
                bootstrap_command_ref = self._bootstrap_probe_command_ref(status)
            capture_probe_status(
                self.run,
                platform=self.platform,
                serial=self.device,
                attempt_id=self.attempt_id,
                status=status,
                required_probe_ids=self.scenario.get("requiredProbes", []),
                observations=self.observations,
                controller_events=self.controller_events,
                known_server_sequences=self.known_server_sequences,
                process_artifact_directory=process_artifact_directory,
                previous_command_ref=self.last_command_ref.get(process_id),
                command_ref=bootstrap_command_ref,
                timeout_seconds=self._remaining_timeout(15),
                deadline=self.deadline,
            )
        elif status["phase"] == "probeCaptured":
            if self.platform == "ios":
                if process_id not in self.probe_preflight_by_process:
                    raise ValueError("iOS store probe capture has no idle control snapshot preflight")
                previous_probe_id = self.probe_preflight_by_process[process_id]
                current_probe_id = self._accept_new_probe_id(status)
                if current_probe_id == previous_probe_id:
                    self.probe_ids_seen.discard((process_id, current_probe_id))
                    raise ValueError("iOS store probe probeId did not advance from the preflight snapshot")
                self.probe_preflight_by_process.pop(process_id)
            bootstrap_command_ref = None
            if status.get("checkpointName") == "bootstrapStoreProbed":
                bootstrap_command_ref = self.bootstrap_probe_command_refs.pop(process_id, None)
                if bootstrap_command_ref is None:
                    raise ValueError("pre-clear probe has no observed Bootstrap command reference")
            capture_probe_status(
                self.run,
                platform=self.platform,
                serial=self.device,
                attempt_id=self.attempt_id,
                status=status,
                required_probe_ids=self.scenario.get("requiredProbes", []),
                observations=self.observations,
                controller_events=self.controller_events,
                known_server_sequences=self.known_server_sequences,
                process_artifact_directory=process_artifact_directory,
                previous_command_ref=self.last_command_ref.get(process_id),
                command_ref=bootstrap_command_ref,
                timeout_seconds=self._remaining_timeout(15),
                deadline=self.deadline,
            )
        elif status["phase"] == "rendered":
            record_rendered_status(
                status,
                observations=self.observations,
                process_artifact_directory=process_artifact_directory,
            )
        elif status["phase"] == "effectAwaitRequested":
            self._await_detached_effect(status)
        elif status["phase"] == "replayScheduled":
            self._record_replay_status(status)
        elif status["phase"] == "releaseRequested":
            command = status.get("command", "")
            if not command.startswith("Deliver(replay,"):
                wire_tag = self._read_native_events_until(
                    process_id,
                    lambda native_events: _wire_tag_for_delivery(
                        native_events,
                        process_instance_id=process_id,
                        scenario=self.scenario,
                        variant=self.variant,
                        command=command,
                    ),
                    description="unconsumed native Deliver slot",
                )
                release_pending_delivery(
                    self.run,
                    command=command,
                    variant=self.variant,
                    process_instance_id=process_id,
                    wire_tag=wire_tag,
                    controller_events=self.controller_events,
                    known_server_sequences=self.known_server_sequences,
                    timeout_seconds=self._remaining_timeout(10),
                )
        elif status["phase"] == "end":
            self.end_seen.add(process_id)

    def bind_native_events(self, events):
        by_command = {
            (event["commandRef"]["processInstanceId"], event["commandRef"]["id"]): event
            for event in events
            if event.get("kind") == "commandReceipt" and isinstance(event.get("commandRef"), dict)
        }
        by_event_ref = {
            (event.get("processInstanceId"), event.get("localSequence")): event
            for event in events
            if isinstance(event.get("processInstanceId"), str) and type(event.get("localSequence")) is int
        }
        for controller_event, command_ref in self.receipt_statuses:
            receipt = by_command.get((command_ref["processInstanceId"], command_ref["id"]))
            if receipt is not None:
                controller_event["eventRef"] = {
                    "processInstanceId": receipt["processInstanceId"],
                    "localSequence": receipt["localSequence"],
                }
        for event in self.controller_events:
            # bootstrapHookArrived has no eventRef in the checker schema; its paired
            # hookArrived carries the native binding and arm-sequence check.
            if event.get("kind") not in {"hookArrived", "hookReleased"}:
                continue
            wanted_phase = "released" if event["kind"] == "hookReleased" else "arrived"
            matches = [
                native for native in events
                if native.get("kind") == "hookEvent"
                and native.get("processInstanceId") == event.get("processInstanceId")
                and native.get("point") == event.get("point")
                and native.get("phase") == wanted_phase
            ]
            if len(matches) == 1:
                match = matches[0]
                event["eventRef"] = {"processInstanceId": match["processInstanceId"], "localSequence": match["localSequence"]}
            elif len(matches) > 1 or event.get("kind") == "hookReleased":
                raise ValueError("controller hook status does not bind to one native hookEvent")
            arm_sequence = self.hook_arm_sequence_by_point.get((event.get("processInstanceId"), event.get("point")))
            if arm_sequence is not None and len(matches) == 1 and matches[0].get("actionId") != arm_sequence:
                raise ValueError("controller hook snapshot arm sequence does not match the native hook action")
        for event in self.controller_events:
            if event.get("kind") != "processEndAcknowledged":
                continue
            reference = event.get("eventRef")
            terminal = by_event_ref.get((reference.get("processInstanceId"), reference.get("localSequence"))) if isinstance(reference, dict) else None
            if terminal is None or terminal.get("kind") != "processEnd":
                raise ValueError("controller processEnd acknowledgement does not bind to the native terminal event")
        for observation in self.observations:
            if observation.get("kind") != "renderedView":
                continue
            process_id = observation["processInstanceId"]
            matches = [
                event for event in events
                if event.get("kind") == "uiPublishAck"
                and event.get("processInstanceId") == process_id
                and event.get("revision") == observation.get("revision")
                and event.get("view", {}).get("phase") == observation.get("phase")
                and event.get("view", {}).get("account") == observation.get("account")
            ]
            if len(matches) == 1:
                observation["eventRef"] = {
                    "processInstanceId": process_id,
                    "localSequence": matches[0]["localSequence"],
                }
            elif len(matches) > 1:
                raise ValueError("rendered view does not bind to one native publication revision")
        for process_id, directory in self.process_artifact_directories.items():
            process_observations = [
                row for row in self.observations
                if row.get("processInstanceId") == process_id
            ]
            target = Path(directory) / "ui.jsonl"
            temporary = target.with_name(".ui.jsonl.tmp")
            target.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as stream:
                for row in process_observations:
                    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    if _SENSITIVE_TEXT.search(encoded):
                        raise ValueError("redacted UI observation would contain credential text")
                    stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        existing = {
            (event.get("commandRef", {}).get("processInstanceId"), event.get("commandRef", {}).get("id"))
            for event in self.controller_events
            if event.get("kind") == "completionProcessedObserved"
        }
        for native in events:
            if native.get("kind") != "completionProcessed":
                continue
            ref = native.get("commandRef")
            key = (ref.get("processInstanceId"), ref.get("id")) if isinstance(ref, dict) else None
            if key is None or key in existing:
                continue
            _append_controller_event(
                self.controller_events,
                "completionProcessedObserved",
                key[0],
                commandRef={"processInstanceId": key[0], "id": key[1]},
                eventRef={"processInstanceId": native["processInstanceId"], "localSequence": native["localSequence"]},
            )
            existing.add(key)
        return events

    def _record_replay_status(self, status):
        process_id = status["processInstanceId"]
        action_id_text = status.get("replayActionId")
        target_id_text = status.get("lastEnqueuedCommandId")
        if not re.fullmatch(r"[1-9][0-9]{0,18}", str(action_id_text)) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(target_id_text)):
            raise ValueError("replay status lacks its observed Debug action and enqueued command IDs")
        action_id, target_id = int(action_id_text), int(target_id_text)
        if action_id > (1 << 63) - 1 or target_id > (1 << 63) - 1:
            raise ValueError("replay status IDs exceed signed64")
        slot_id, target_ref, source_ref = self._read_native_events_until(
            process_id,
            lambda native_events: self._replay_status_binding(
                status, native_events, process_id=process_id, action_id=action_id, target_id=target_id
            ),
            description="replay enqueue and source completion history",
        )
        _append_controller_event(
            self.controller_events,
            "replayRequested",
            process_id,
            slotId=slot_id,
            actionId=action_id,
            commandRef=target_ref,
            sourceCommandRef=source_ref,
        )

    @staticmethod
    def _replay_status_binding(status, native_events, *, process_id, action_id, target_id):
        target_ref = {"processInstanceId": process_id, "id": target_id}
        target_enqueues = [
            event for event in native_events
            if event.get("kind") == "commandEnqueued" and event.get("commandRef") == target_ref
        ]
        if len(target_enqueues) != 1:
            raise ValueError("replay status does not identify one actual enqueued command")
        target_name = target_enqueues[0].get("name")
        match = re.fullmatch(r"Deliver\((slot-[AB][1-9][0-9]*),([A-Za-z]+)\)", target_name or "")
        preceding = [
            event for event in native_events
            if event.get("kind") == "completionProcessed"
            and event.get("processInstanceId") == process_id
            and event.get("localSequence", (1 << 63) - 1) < target_enqueues[0].get("localSequence", 0)
        ]
        source = max(preceding, key=lambda event: event.get("localSequence", 0), default=None)
        if match is None or source is None:
            raise ValueError("replay status has no concrete delivery target or prior completed source")
        slot_id = match.group(1)
        source_ref = source.get("commandRef")
        if source.get("slotId") != slot_id or not isinstance(source_ref, dict):
            raise ValueError("replay target slot differs from the latest native completed source")
        if not any(
            event.get("kind") == "transportReceived"
            and event.get("commandRef") == source_ref
            and event.get("slotId") == slot_id
            for event in native_events
        ):
            raise ValueError("replay source has no actual transport receipt for its slot")
        return slot_id, target_ref, source_ref


def android_process_instance_id(attempt_id: str, scenario_id: str, launch_ordinal: int) -> str:
    """Build the frozen process identity used by one Android instrumentation launch."""
    if not isinstance(attempt_id, str) or _ANDROID_LABEL.fullmatch(attempt_id) is None:
        raise ValueError("attemptId must be a frozen ASCII label")
    if not isinstance(scenario_id, str) or _ANDROID_LABEL.fullmatch(scenario_id) is None:
        raise ValueError("scenarioId must be a frozen ASCII label")
    if type(launch_ordinal) is not int or launch_ordinal <= 0:
        raise ValueError("launchOrdinal must be a positive integer")
    return f"{attempt_id}/{scenario_id}/p{launch_ordinal}"


def android_storage_namespace(process_instance_id: str) -> str:
    """Return the attempt/scenario namespace, deliberately excluding process ordinal."""
    if not isinstance(process_instance_id, str):
        raise ValueError("processInstanceId must be a string")
    match = re.fullmatch(r"([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_-]{1,64})/p([1-9][0-9]*)", process_instance_id)
    if match is None:
        raise ValueError("processInstanceId must encode attempt/scenario/positive ordinal")
    return f"test-{match.group(1)}/{match.group(2)}"


def case_attempt_id(base_attempt_id: str, platform: str, scenario_id: str, variant_id: str | None = None) -> str:
    """Give each platform/base-scenario/variant launch a distinct server/process namespace.

    Non-variant cases keep their existing attempt ID so multi-launch cases such as
    APP-12 retain one scenario storage namespace across p1 and p2.
    """
    for name, value in (("attemptId", base_attempt_id), ("scenarioId", scenario_id)):
        if not isinstance(value, str) or _ANDROID_LABEL.fullmatch(value) is None:
            raise ValueError(f"{name} must be a frozen ASCII label")
    if platform not in {"ios", "android"}:
        raise ValueError("platform must be ios or android")
    if variant_id is None:
        return base_attempt_id
    if not isinstance(variant_id, str) or _ANDROID_LABEL.fullmatch(variant_id) is None:
        raise ValueError("variantId must be a frozen ASCII label")
    identity = "\0".join((base_attempt_id, platform, scenario_id, variant_id)).encode("ascii")
    suffix = hashlib.sha256(identity).hexdigest()[:32]
    result = f"{base_attempt_id[:12]}-{platform}-{suffix}"
    if _ANDROID_LABEL.fullmatch(result) is None:
        raise ValueError("derived variant attemptId is outside the server label domain")
    return result


def case_artifact_directory(output: Path, platform: str, scenario_id: str, variant_id: str | None = None) -> Path:
    """Return a disjoint output folder for one platform/scenario/variant case."""
    if platform not in {"ios", "android"}:
        raise ValueError("platform must be ios or android")
    if not isinstance(scenario_id, str) or _ANDROID_LABEL.fullmatch(scenario_id) is None:
        raise ValueError("scenarioId must be a frozen ASCII label")
    case_root = Path(output) / platform / scenario_id
    if variant_id is None:
        return case_root
    if not isinstance(variant_id, str) or _ANDROID_LABEL.fullmatch(variant_id) is None:
        raise ValueError("variantId must be a frozen ASCII label")
    return case_root / "variants" / variant_id


def platform_screenshot_rows(platform_root: Path, case_root: Path, rows: list[dict]) -> list[dict]:
    """Rebase case-local screenshot names into the platform manifest namespace."""
    platform_root = Path(platform_root).resolve()
    case_root = Path(case_root).resolve()
    try:
        prefix = case_root.relative_to(platform_root)
    except ValueError as exc:
        raise ValueError("screenshot case directory is outside its platform root") from exc
    output = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ValueError("case screenshot row has an invalid shape")
        local = PurePosixPath(row["path"])
        if (
            not isinstance(row["path"], str) or not row["path"]
            or local.is_absolute() or ".." in local.parts or "." in local.parts
            or str(local) != row["path"]
            or not isinstance(row["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
        ):
            raise ValueError("case screenshot path or digest is malformed")
        output.append({"path": (PurePosixPath(prefix.as_posix()) / local).as_posix(), "sha256": row["sha256"]})
    return output


def _android_instrumentation_argv(
    *, serial, scenario_id, run_id, process_instance_id, launch_ordinal,
    base_url, scenario_phase, cancel_mode, scenario_inventory_sha256, control_inventory_sha256,
    variant_id=None, store_fault=None, arm_point=None, arm_target=None,
):
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("an explicit Android serial is required")
    if not isinstance(run_id, str) or _ANDROID_LABEL.fullmatch(run_id) is None:
        raise ValueError("runId must be a frozen ASCII label")
    expected_process = android_process_instance_id(
        process_instance_id.split("/", 1)[0] if isinstance(process_instance_id, str) else "",
        scenario_id,
        launch_ordinal,
    )
    if process_instance_id != expected_process:
        raise ValueError("processInstanceId disagrees with scenario and launchOrdinal")
    parsed = urlsplit(base_url) if isinstance(base_url, str) else None
    if (
        parsed is None or parsed.scheme != "http" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        raise ValueError("baseUrl must be a plain HTTP origin")
    if scenario_phase not in {"seed", "resume", "single"}:
        raise ValueError("scenarioPhase is outside the frozen set")
    if cancel_mode != "disabled":
        raise ValueError("cancelMode is outside the frozen set")
    for name, value in (
        ("scenarioInventorySha256", scenario_inventory_sha256),
        ("controlInventorySha256", control_inventory_sha256),
    ):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    if variant_id is not None and _ANDROID_LABEL.fullmatch(variant_id) is None:
        raise ValueError("variantId must be a frozen ASCII label")
    if store_fault is not None and store_fault not in {
        "none", "replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify",
    }:
        raise ValueError("storeFault is outside the frozen set")
    if (arm_point is None) != (arm_target is None):
        raise ValueError("armPoint and armTarget must be supplied together")
    if arm_point is not None and (arm_point != "beforeBootstrapClear" or arm_target != "bootstrap"):
        raise ValueError("APP-12 only permits beforeBootstrapClear/bootstrap on resume")
    argv = [
        "adb", "-s", serial, "shell", "am", "instrument", "-w",
        "-e", "class", _ANDROID_TEST_METHOD,
        "-e", "scenarioId", scenario_id,
        "-e", "runId", run_id,
        "-e", "processInstanceId", process_instance_id,
        "-e", "launchOrdinal", str(launch_ordinal),
        "-e", "baseUrl", base_url,
        "-e", "scenarioPhase", scenario_phase,
        "-e", "cancelMode", cancel_mode,
        "-e", "scenarioInventorySha256", scenario_inventory_sha256,
        "-e", "controlInventorySha256", control_inventory_sha256,
    ]
    if variant_id is not None:
        argv.extend(["-e", "variantId", variant_id])
    if store_fault is not None:
        argv.extend(["-e", "storeFault", store_fault])
    if arm_point is not None:
        argv.extend(["-e", "armPoint", arm_point, "-e", "armTarget", arm_target])
    argv.append(_ANDROID_COMPONENT)
    return argv


def build_android_app12_plan(
    *, serial: str, app_apk: str, test_apk: str, attempt_id: str,
    run_id: str, base_url: str, scenario: dict,
    scenario_inventory_sha256: str, control_inventory_sha256: str,
) -> dict:
    """Freeze one APP-12 install plus its two process-scoped test launches."""
    if not isinstance(scenario, dict) or scenario.get("id") not in {"APP-12-SAVED", "APP-12-LOGGED-OUT"}:
        raise ValueError("scenario must be one of the frozen APP-12 variants")
    launch_inventory = scenario.get("launches")
    if not isinstance(launch_inventory, list) or [row.get("ordinal") for row in launch_inventory if isinstance(row, dict)] != [1, 2]:
        raise ValueError("APP-12 inventory must declare exactly launches 1 and 2")
    if not isinstance(app_apk, str) or not app_apk or not isinstance(test_apk, str) or not test_apk:
        raise ValueError("both candidate and instrumentation APK paths are required")
    if not isinstance(attempt_id, str) or _ANDROID_LABEL.fullmatch(attempt_id) is None:
        raise ValueError("attemptId must be a frozen ASCII label")

    scenario_id = scenario["id"]
    install_prefix = ["adb", "-s", serial, "install", "-r"]
    launches = []
    for ordinal, phase in ((1, "seed"), (2, "resume")):
        process_id = android_process_instance_id(attempt_id, scenario_id, ordinal)
        arm_point, arm_target = ("beforeBootstrapClear", "bootstrap") if ordinal == 2 else (None, None)
        launches.append({
            "launchOrdinal": ordinal,
            "processInstanceId": process_id,
            "storageNamespace": android_storage_namespace(process_id),
            "scenarioPhase": phase,
            "armPoint": arm_point,
            "armTarget": arm_target,
            "argv": _android_instrumentation_argv(
                serial=serial,
                scenario_id=scenario_id,
                run_id=run_id,
                process_instance_id=process_id,
                launch_ordinal=ordinal,
                base_url=base_url,
                scenario_phase=phase,
                cancel_mode=scenario["cancelMode"],
                scenario_inventory_sha256=scenario_inventory_sha256,
                control_inventory_sha256=control_inventory_sha256,
                arm_point=arm_point,
                arm_target=arm_target,
            ),
        })
    return {
        "scenarioId": scenario_id,
        "deviceId": serial,
        "storageNamespace": launches[0]["storageNamespace"],
        "installationCommands": [
            [*install_prefix, app_apk],
            [*install_prefix, test_apk],
        ],
        "launches": launches,
        "forceStopCommand": ["adb", "-s", serial, "shell", "am", "force-stop", "dev.nativecontract.demo.android"],
        "pidofCommand": ["adb", "-s", serial, "shell", "pidof", "dev.nativecontract.demo.android"],
        "noCleanupBetweenLaunches": True,
    }


def _ios_launch_environment(
    *, scenario_id, run_id, process_instance_id, launch_ordinal, base_url,
    scenario_phase, cancel_mode, scenario_inventory_path, scenario_inventory_sha256,
    control_inventory_path, control_inventory_sha256, variant_id=None,
    store_fault=None, arm_point=None, arm_target=None,
):
    if process_instance_id != android_process_instance_id(
        process_instance_id.split("/", 1)[0] if isinstance(process_instance_id, str) else "",
        scenario_id,
        launch_ordinal,
    ):
        raise ValueError("processInstanceId disagrees with scenario and launchOrdinal")
    if not isinstance(run_id, str) or _ANDROID_LABEL.fullmatch(run_id) is None:
        raise ValueError("runId must be a frozen ASCII label")
    if scenario_phase not in {"single", "seed", "resume"}:
        raise ValueError("scenarioPhase is outside the frozen set")
    if cancel_mode != "disabled":
        raise ValueError("cancelMode is outside the frozen set")
    for name, value in (("scenarioInventorySHA256", scenario_inventory_sha256), ("controlInventorySHA256", control_inventory_sha256)):
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    parsed = urlsplit(base_url) if isinstance(base_url, str) else None
    if (
        parsed is None or parsed.scheme != "http" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        raise ValueError("baseUrl must be a plain HTTP origin")
    if variant_id is not None and _ANDROID_LABEL.fullmatch(variant_id) is None:
        raise ValueError("variantId must be a frozen ASCII label")
    if store_fault is not None and store_fault not in {"none", "replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"}:
        raise ValueError("storeFault is outside the frozen set")
    if (arm_point is None) != (arm_target is None):
        raise ValueError("armPoint and armTarget must be supplied together")
    native_environment = {
        "NATIVE_CONTRACT_SCENARIO_ID": scenario_id,
        "NATIVE_CONTRACT_RUN_ID": run_id,
        "NATIVE_CONTRACT_PROCESS_INSTANCE_ID": process_instance_id,
        "NATIVE_CONTRACT_LAUNCH_ORDINAL": str(launch_ordinal),
        "NATIVE_CONTRACT_BASE_URL": base_url,
        "NATIVE_CONTRACT_SCENARIO_PHASE": scenario_phase,
        "NATIVE_CONTRACT_CANCEL_MODE": cancel_mode,
        "NATIVE_CONTRACT_SCENARIO_INVENTORY_PATH": str(Path(scenario_inventory_path).resolve()),
        "NATIVE_CONTRACT_SCENARIO_INVENTORY_SHA256": scenario_inventory_sha256,
        "NATIVE_CONTRACT_CONTROL_INVENTORY_PATH": str(Path(control_inventory_path).resolve()),
        "NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256": control_inventory_sha256,
    }
    optional = {
        "NATIVE_CONTRACT_VARIANT_ID": variant_id,
        "NATIVE_CONTRACT_STORE_FAULT": store_fault,
        "NATIVE_CONTRACT_ARM_POINT": arm_point,
        "NATIVE_CONTRACT_ARM_TARGET": arm_target,
    }
    native_environment.update({key: value for key, value in optional.items() if value is not None})
    return {"TEST_RUNNER_" + key: value for key, value in native_environment.items()}


def android_process_termination_evidence(
    *, instrumentation_exit_code, force_stop_exit_code, pidof_exit_code, pidof_stdout,
) -> dict:
    """Require an owned force-stop and empty PID observation; instrumentation exit is separate."""
    missing = []
    if force_stop_exit_code != 0:
        missing.append("force-stop acknowledgement")
    if pidof_exit_code not in {0, 1} or not isinstance(pidof_stdout, str) or pidof_stdout.strip():
        missing.append("empty pidof result")
    return {
        "instrumentationExitCode": instrumentation_exit_code,
        "forceStopExitCode": force_stop_exit_code,
        "pidofExitCode": pidof_exit_code,
        "pidofStdout": pidof_stdout,
        "terminated": not missing,
        "missing": missing,
    }


def redact_android_credential_blob(raw_bytes):
    """Validate an AtomicFile credential blob, returning only account/version metadata."""
    if not isinstance(raw_bytes, bytes):
        return {"kind": "Unknown", "errorCode": "invalidBlob"}
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"kind": "Unknown", "errorCode": "invalidBlob"}
    if not isinstance(value, dict) or set(value) != {"account", "version", "accessToken", "refreshToken"}:
        return {"kind": "Unknown", "errorCode": "invalidBlob"}
    account, version = value.get("account"), value.get("version")
    if account not in {"A", "B"} or type(version) is not int or not 0 <= version <= (1 << 63) - 1:
        return {"kind": "Unknown", "errorCode": "invalidVersion"}
    token = f"demo-{account}-v{version}"
    if value.get("accessToken") != token or value.get("refreshToken") != token:
        return {"kind": "Unknown", "errorCode": "tokenMismatch"}
    return {"kind": "Present", "account": account, "version": version}


def read_android_storage_probe(
    *, serial, attempt_id, scenario_id, command_runner=subprocess.run, timeout_seconds=15, deadline=None
):
    """Read only the owned app-private AtomicFile namespace and redact bytes in memory."""
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError("an explicit Android serial is required")
    namespace = android_storage_namespace(f"{attempt_id}/{scenario_id}/p1")
    relative_directory = f"no_backup/demo-session/{namespace}"
    base_name = "credential.json"
    allowed_names = {base_name, base_name + ".bak", base_name + ".new"}

    def command_timeout():
        if deadline is None:
            return timeout_seconds
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _NativeStageDeadlineExceeded("native platform stage deadline exhausted during Android probe")
        return min(timeout_seconds, remaining)

    def stage_timeout_after(exc):
        if deadline is not None and time.monotonic() >= deadline:
            raise _NativeStageDeadlineExceeded("native platform stage deadline exhausted during Android probe") from exc

    list_argv = ["adb", "-s", serial, "shell", "run-as", "dev.nativecontract.demo.android", "ls", "-A", relative_directory]
    try:
        listing = command_runner(list_argv, capture_output=True, text=True, timeout=command_timeout())
    except _NativeStageDeadlineExceeded:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        stage_timeout_after(exc)
        return {"kind": "Unknown", "errorCode": "probeCommandFailed"}
    if listing.returncode != 0:
        if "no such file or directory" in (listing.stderr or "").casefold():
            return {"kind": "Unknown", "errorCode": "probeNamespaceMissing"}
        return {"kind": "Unknown", "errorCode": "probeReadFailed"}
    names = {line.strip() for line in listing.stdout.splitlines() if line.strip()}
    if not names:
        return {"kind": "Absent"}
    if not names <= allowed_names:
        return {"kind": "Unknown", "errorCode": "unexpectedStoreFiles"}
    if base_name not in names:
        return {"kind": "Unknown", "errorCode": "atomicSidecarPresent"}
    cat_argv = ["adb", "-s", serial, "exec-out", "run-as", "dev.nativecontract.demo.android", "cat", f"{relative_directory}/{base_name}"]
    try:
        captured = command_runner(cat_argv, capture_output=True, text=False, timeout=command_timeout())
    except _NativeStageDeadlineExceeded:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        stage_timeout_after(exc)
        return {"kind": "Unknown", "errorCode": "probeCommandFailed"}
    if captured.returncode != 0:
        return {"kind": "Unknown", "errorCode": "probeReadFailed"}
    return redact_android_credential_blob(captured.stdout)


def validate_app12_bootstrap_protocol(events: list[dict], process_instance_id: str) -> dict:
    """Check probe/checkpoint/direct-release/clear order for a resumed APP-12 process."""
    required = ("bootstrapHookArrived", "probeCaptured", "checkpointPublished", "hookReleased", "bootstrapCleared")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        return {"classification": "INVALID_HISTORY", "violations": ["controller events must be objects"], "missingObservations": []}
    sequences = [event.get("sequence") for event in events]
    if any(type(value) is not int or value <= 0 for value in sequences) or sequences != sorted(set(sequences)):
        return {"classification": "INVALID_HISTORY", "violations": ["controller event sequence is invalid or out of order"], "missingObservations": []}
    by_kind = {}
    for event in events:
        by_kind.setdefault(event.get("kind"), []).append(event)
    missing = [kind for kind in required if kind not in by_kind]
    if missing:
        human = {
            "bootstrapHookArrived": "Bootstrap hook arrival",
            "probeCaptured": "independent probe",
            "checkpointPublished": "independent probe checkpoint",
            "hookReleased": "direct hook release",
            "bootstrapCleared": "bootstrap clear completion",
        }
        return {"classification": "INCONCLUSIVE", "violations": [], "missingObservations": [f"{human[kind]} is missing" for kind in missing]}
    selected = [by_kind[kind][0] for kind in required]
    if any(event.get("processInstanceId") != process_instance_id for event in selected):
        return {"classification": "INVALID_HISTORY", "violations": ["APP-12 bootstrap event belongs to another process"], "missingObservations": []}
    if [event["sequence"] for event in selected] != sorted(event["sequence"] for event in selected):
        return {"classification": "INVALID_HISTORY", "violations": ["probe/checkpoint/release/clear order is reversed"], "missingObservations": []}
    probe, checkpoint, release, cleared = selected[1:]
    if "before-bootstrap-clear" not in str(probe.get("stepId", "")):
        return {"classification": "INVALID_HISTORY", "violations": ["bootstrap probe step is not the frozen pre-clear observation"], "missingObservations": []}
    if not isinstance(probe.get("observation"), dict) or probe["observation"].get("kind") not in {"Present", "Absent"}:
        return {"classification": "INCONCLUSIVE", "violations": [], "missingObservations": ["redacted physical store observation is unavailable"]}
    if checkpoint.get("name") != "bootstrapStoreProbed":
        return {"classification": "INVALID_HISTORY", "violations": ["wrong process-scoped checkpoint was published"], "missingObservations": []}
    if release.get("point") != "beforeBootstrapClear" or release.get("releaseChannel") != "DebugScenarioControl":
        return {"classification": "INVALID_HISTORY", "violations": ["bootstrap hook release did not use the independent control plane"], "missingObservations": []}
    if release.get("authMailboxPaused") is not True or release.get("bootstrapReceiptObserved") is not False:
        return {"classification": "INVALID_HISTORY", "violations": ["control release was not acknowledged while Bootstrap remained paused"], "missingObservations": []}
    if cleared["sequence"] <= release["sequence"]:
        return {"classification": "INVALID_HISTORY", "violations": ["bootstrap clear occurred before direct hook release"], "missingObservations": []}
    return {"classification": "PASS", "violations": [], "missingObservations": []}


def evaluate_scenario(contract, scenario, artifacts: Path, *, server_exit=0):
    """Classify one native result; missing observations never become semantic RED."""
    if server_exit != 0:
        return {
            "classification": "INFRA_FAILURE",
            "scenarioId": scenario.get("id", "unknown"),
            "violations": [],
            "missingObservations": [],
            "detail": f"refresh server exited with status {server_exit}",
        }
    artifacts = Path(artifacts)
    paths = {name: artifacts / name for name in ("trace.json", "server-events.json", "ui-observations.json")}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        return {
            "classification": "INCONCLUSIVE",
            "scenarioId": scenario.get("id", "unknown"),
            "violations": [],
            "missingObservations": [f"artifact {name} is missing" for name in missing],
        }
    try:
        trace = json.loads(paths["trace.json"].read_text())
        server_events = json.loads(paths["server-events.json"].read_text())
        ui_observations = json.loads(paths["ui-observations.json"].read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": scenario.get("id", "unknown"),
            "violations": [],
            "missingObservations": [],
            "detail": f"native artifact cannot be decoded: {exc}",
        }
    return check_trace(contract, scenario, trace, server_events, ui_observations)


def stop_owned_processes(processes, *, timeout_seconds=5):
    """Stop only process handles owned by this controller attempt."""
    for process in processes:
        if process.poll() is not None:
            continue
        process.terminate()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout_seconds)


def _ios_device_rows(document):
    devices = document.get("devices") if isinstance(document, dict) else None
    if not isinstance(devices, dict):
        return []
    rows = []
    for group in devices.values():
        if isinstance(group, list):
            rows.extend(row for row in group if isinstance(row, dict))
    return rows


def _android_device_rows(output):
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and parts[0] != "List":
            attributes = {}
            for item in parts[2:]:
                if ":" in item:
                    key, value = item.split(":", 1)
                    attributes[key] = value
            rows.append({"serial": parts[0], "state": parts[1], "attributes": attributes})
    return rows


def _report(output, result):
    write_json(output / "platform-report.json", result)
    return result


def _candidate_runtime_required_files(platform):
    if platform == "ios":
        return [
            "apps/ios-demo/NativeContractDemo/App/DemoEnvironment.swift",
            "apps/ios-demo/NativeContractDemo/Coordinator/DemoTypes.swift",
            "apps/ios-demo/NativeContractDemo/Coordinator/SessionCoordinator.swift",
            "apps/ios-demo/NativeContractDemo/Coordinator/RefreshSlot.swift",
            "apps/ios-demo/NativeContractDemo/Coordinator/ScenarioHooks.swift",
            "apps/ios-demo/NativeContractDemo/Coordinator/AuditRecorder.swift",
            "apps/ios-demo/NativeContractDemo/Storage/CredentialStore.swift",
            "apps/ios-demo/NativeContractDemo/Storage/KeychainCredentialStore.swift",
            "apps/ios-demo/NativeContractDemo/Transport/RefreshTransport.swift",
            "apps/ios-demo/NativeContractDemo/Transport/URLSessionRefreshTransport.swift",
            "apps/ios-demo/NativeContractDemo/Transport/RefreshWire.swift",
            "apps/ios-demo/NativeContractDemo/UI/DemoViewModel.swift",
            "apps/ios-demo/NativeContractDemo/UI/DemoView.swift",
            "apps/ios-demo/NativeContractDemo/NativeContractDemoApp.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DefaultDebugScenarioControl.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DebugScenarioHooks.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DemoIngress.swift",
            "apps/ios-demo/NativeContractDemo/Debug/JSONLAuditRecorder.swift",
            "apps/ios-demo/NativeContractDemoTests/CoordinatorTests.swift",
            "apps/ios-demo/NativeContractDemoTests/KeychainStoreTests.swift",
            "apps/ios-demo/NativeContractDemoTests/TransportTests.swift",
        ]
    return [
            "apps/android-demo/app/src/main/java/nativecontract/demo/DemoApplication.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/MainActivity.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/DemoTypes.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/SessionCoordinator.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/RefreshSlot.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/ScenarioHooks.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/AuditRecorder.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/storage/CredentialStore.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/storage/AtomicFileCredentialStore.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/transport/RefreshTransport.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/transport/UrlConnectionRefreshTransport.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/transport/RefreshWire.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/ui/DemoViewModel.kt",
            "apps/android-demo/app/src/main/java/nativecontract/demo/ui/DemoScreen.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugDemoApplication.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DefaultDebugScenarioControl.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioHooks.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DemoIngress.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/JSONLAuditRecorder.kt",
            "apps/android-demo/app/src/test/java/nativecontract/demo/CoordinatorTest.kt",
            "apps/android-demo/app/src/test/java/nativecontract/demo/TransportTest.kt",
            "apps/android-demo/app/src/androidTest/java/nativecontract/demo/AtomicFileStoreTest.kt",
        ]


def _candidate_runtime_missing(platform, candidate):
    marker = "Source path reserved by the standalone app plan. Implementation pending."
    missing = []
    for relative in _candidate_runtime_required_files(platform):
        path = Path(candidate) / relative
        try:
            content = path.read_text()
        except OSError:
            missing.append(relative)
            continue
        if marker in content:
            missing.append(relative)
    return missing


def _owned_device_evidence_error(platform, device, evidence_path, *, candidate):
    if evidence_path is None:
        return "owned-device evidence path is not assigned"
    try:
        evidence_path = Path(evidence_path).resolve()
        document = json.loads(evidence_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "owned-device evidence is missing or malformed"
    if not isinstance(document, dict) or document.get("platform") != platform or document.get("owned") is not True:
        return "device evidence does not attest controller ownership"
    if platform == "ios":
        identity = document.get("udid", document.get("deviceId"))
        if not isinstance(identity, str) or identity.casefold() != device.casefold():
            return "iOS ownership evidence names a different simulator UUID"
        return None
    if platform == "android":
        avd_home = document.get("avdHome")
        if not isinstance(avd_home, str) or not avd_home or os.environ.get("ANDROID_AVD_HOME") != avd_home:
            return "ANDROID_AVD_HOME does not match the owned AVD evidence"
        if document.get("serial") == device and isinstance(document.get("avdName"), str) and document["avdName"]:
            return None
        readiness = document.get("readinessEvidence")
        if not isinstance(readiness, dict) or readiness.get("classification") != "READY":
            return "Android AVD ownership lacks matching ready-emulator evidence"
        path_value = readiness.get("path")
        if not isinstance(path_value, str) or not path_value:
            return "Android readiness evidence path is missing"
        readiness_path = Path(path_value)
        if not readiness_path.is_absolute():
            candidates = (Path(candidate) / readiness_path, evidence_path.parent / readiness_path)
            readiness_path = next((path for path in candidates if path.is_file()), candidates[0])
        try:
            ready = json.loads(readiness_path.read_text())
        except (OSError, json.JSONDecodeError):
            return "Android ready-emulator evidence cannot be read"
        if (
            not isinstance(ready, dict)
            or ready.get("classification") != "READY"
            or ready.get("serial") != device
            or ready.get("avdName") != document.get("name")
        ):
            return "Android ready-emulator evidence names a different serial or AVD"
        return None
    return "device platform is outside the ownership contract"


def _validation_scope_evidence_error(platform, device, evidence_path, *, candidate, validation_scope):
    try:
        scope = _toolchain_scope(candidate, validation_scope)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return f"validation scope is not frozen: {exc}"
    if validation_scope == "ci":
        return None
    if evidence_path is None:
        return "local-observed scope requires its recorded owned-device evidence"
    expected = scope.get(platform)
    if not isinstance(expected, dict):
        return f"local-observed scope has no frozen {platform} tuple"
    expected_evidence_path = (Path(candidate) / expected.get("ownedDeviceEvidence", "")).resolve()
    try:
        actual_evidence_path = Path(evidence_path).resolve(strict=True)
        evidence = json.loads(actual_evidence_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return f"local-observed owned-device evidence is unavailable: {exc}"
    if actual_evidence_path != expected_evidence_path:
        return "local-observed scope evidence path differs from its frozen toolchain record"
    if _sha256_file(actual_evidence_path) != expected.get("ownedDeviceEvidenceSha256"):
        return "local-observed owned-device evidence hash differs from the frozen toolchain record"
    if platform == "ios":
        if (
            evidence.get("owned") is not True
            or evidence.get("platform") != "ios"
            or str(evidence.get("udid", "")).casefold() != device.casefold()
            or evidence.get("runtimeVersion") != expected.get("runtimeVersion")
            or evidence.get("runtimeBuild") != expected.get("runtimeBuild")
            or evidence.get("runtimeIdentifier") != expected.get("runtimeIdentifier")
        ):
            return "owned simulator differs from the frozen local iOS tuple"
        return None
    if (
        evidence.get("owned") is not True
        or evidence.get("platform") != "android"
        or evidence.get("imagePackage") != expected.get("imagePackage")
        or evidence.get("imageRevision") != expected.get("imageRevision")
        or os.environ.get("ANDROID_AVD_HOME") != evidence.get("avdHome")
    ):
        return "owned AVD differs from the frozen local Android tuple"
    readiness_path = (Path(candidate) / expected.get("readinessEvidence", "")).resolve()
    if not readiness_path.is_file() or _sha256_file(readiness_path) != expected.get("readinessEvidenceSha256"):
        return "local-observed Android readiness evidence hash differs from the frozen toolchain record"
    try:
        readiness = json.loads(readiness_path.read_text())
    except json.JSONDecodeError:
        return "local-observed Android readiness evidence is malformed"
    if (
        readiness.get("classification") != "READY"
        or readiness.get("serial") != device
        or readiness.get("avdName") != evidence.get("name")
        or str(readiness.get("apiLevel")) != str(expected.get("apiLevel"))
        or readiness.get("abi") != expected.get("abi")
    ):
        return "owned emulator differs from the frozen local Android readiness record"
    return None


def _write_platform_artifact_shell(output, *, platform, stage_id, scenario_rows, result):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    filenames = (
        "device.json", "build.json", "scenario-results.json", "native-trace.jsonl",
        "server-events.json", "ui-observations.json", "controller-events.json",
        "screenshots/manifest.json", "platform-report.json",
    )
    required_artifacts = [f"{stage_id}/{platform}/{name}" for name in filenames]
    result["requiredArtifacts"] = required_artifacts
    result.setdefault("completedScenarioIds", [])
    result.setdefault("missingScenarioIds", result["requiredScenarioIds"])
    result.setdefault("deviceHash", None)
    result.setdefault("buildHash", None)
    result.setdefault("scenarioBuildHashes", {})
    result.setdefault("validationScope", "ci")
    write_json(output / "device.json", {
        "classification": result["classification"],
        "deviceId": result["deviceId"],
        "deviceHash": result["deviceHash"],
        "device": result.get("deviceDetails"),
        "detail": result.get("detail"),
    })
    write_json(output / "build.json", {
        "classification": result["classification"],
        "buildHash": result["buildHash"],
        "scenarioBuildHashes": result["scenarioBuildHashes"],
        "detail": result.get("detail"),
    })
    cases = []
    for row in scenario_rows:
        variants = row.get("variants", [])
        cases.extend({"scenarioId": row["id"], "variantId": variant["id"], "classification": "NOT_RUN"} for variant in variants)
        if not variants:
            cases.append({"scenarioId": row["id"], "variantId": None, "classification": "NOT_RUN"})
    write_json(output / "scenario-results.json", {"platform": platform, "classification": result["classification"], "cases": cases, "detail": result.get("detail")})
    (output / "native-trace.jsonl").write_text(json.dumps({"classification": result["classification"], "evidence": "native trace unavailable"}, sort_keys=True) + "\n")
    write_json(output / "server-events.json", {"classification": result["classification"], "cases": []})
    write_json(output / "ui-observations.json", {"classification": result["classification"], "cases": []})
    write_json(output / "controller-events.json", {"classification": result["classification"], "cases": []})
    (output / "screenshots").mkdir(parents=True, exist_ok=True)
    write_json(output / "screenshots" / "manifest.json", {"classification": result["classification"], "screenshots": []})
    write_json(output / "platform-report.json", result)
    return result


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_tree(path):
    root = Path(path)
    if root.is_file():
        return _sha256_file(root)
    digest = hashlib.sha256()
    for child in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if child.is_symlink():
            relative = child.relative_to(root).as_posix().encode("utf-8")
            target = os.readlink(child)
            resolved = (child.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("build artifact symlink escapes its bundle") from exc
            target_bytes = target.encode("utf-8")
            digest.update(b"L")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(target_bytes).to_bytes(8, "big"))
            digest.update(target_bytes)
            continue
        if not child.is_file():
            continue
        relative = child.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = child.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _case_inventory(scenario_rows):
    for scenario in scenario_rows:
        if isinstance(scenario, dict) and isinstance(scenario.get("id"), str) and scenario["id"].startswith("CTRL-"):
            errors = control_inventory_errors(scenario)
            if errors:
                raise ValueError(f"invalid frozen control inventory for {scenario['id']}: {'; '.join(errors)}")
            yield scenario, scenario, None
            continue
        variants = scenario.get("variants") or [None]
        for variant in variants:
            variant_id = variant.get("id") if isinstance(variant, dict) else None
            trace_selector = {"variantId": variant_id} if variant_id is not None else {}
            resolved, selected, error = _resolve_scenario_variant(scenario, trace_selector, variant_id)
            if error:
                raise ValueError(f"invalid frozen variant inventory for {scenario['id']}: {error}")
            yield scenario, resolved, selected


def _launch_rows(scenario):
    launches = scenario.get("launches")
    if isinstance(launches, list) and launches:
        return launches
    commands = scenario.get("commands")
    if isinstance(commands, list) and commands:
        return [{"ordinal": 1, "commands": commands}]
    raise ValueError(f"scenario {scenario.get('id')} has no launch inventory")


def _read_android_private_file(serial, relative, *, command_runner=subprocess.run):
    if (
        not isinstance(relative, str) or relative.startswith("/")
        or ".." in Path(relative).parts or not relative.startswith("no_backup/")
    ):
        raise ValueError("Android private-file path is not a safe relative path")
    argv = ["adb", "-s", serial, "exec-out", "run-as", "dev.nativecontract.demo.android", "cat", relative]
    result = command_runner(argv, capture_output=True, text=False, timeout=15)
    if result.returncode != 0:
        return None
    if not isinstance(result.stdout, bytes):
        raise ValueError("Android file capture did not return bytes")
    return result.stdout


def _copy_android_process_artifacts(serial, attempt_id, scenario_id, ordinal, case_root, *, command_runner=subprocess.run):
    process_id = android_process_instance_id(attempt_id, scenario_id, ordinal)
    relative_dir = f"no_backup/native-harness/{attempt_id}/{scenario_id}/p{ordinal}"
    raw_events = _read_android_private_file(serial, f"{relative_dir}/native-events.jsonl", command_runner=command_runner)
    events = _native_events_from_bytes(raw_events, process_instance_id=process_id)
    events_relative = Path(scenario_id) / f"p{ordinal}" / "native.jsonl"
    event_path = Path(case_root) / events_relative
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events))
    instrumentation = _read_android_private_file(serial, f"{relative_dir}/instrumentation-evidence.jsonl", command_runner=command_runner)
    if instrumentation is not None:
        text = instrumentation.decode("utf-8", errors="strict")
        if _SENSITIVE_TEXT.search(text):
            raise ValueError("instrumentation evidence contains credential text")
        evidence_path = Path(case_root) / Path(scenario_id) / f"p{ordinal}" / "instrumentation-evidence.jsonl"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(instrumentation)
    screenshot_dir = f"{relative_dir}/screenshots"
    listing_argv = ["adb", "-s", serial, "shell", "run-as", "dev.nativecontract.demo.android", "ls", "-A", screenshot_dir]
    listing = command_runner(listing_argv, capture_output=True, text=True, timeout=15)
    screenshots = []
    if listing.returncode == 0:
        for filename in listing.stdout.splitlines():
            filename = filename.strip()
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,160}\.png", filename) is None:
                raise ValueError("Android screenshot directory contains an invalid filename")
            raw = _read_android_private_file(serial, f"{screenshot_dir}/{filename}", command_runner=command_runner)
            if not raw or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Android screenshot is missing or malformed")
            target = Path(case_root) / Path(scenario_id) / f"p{ordinal}" / "screenshots" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            screenshots.append({"path": (Path(scenario_id) / f"p{ordinal}" / "screenshots" / filename).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()})
    elif listing.returncode not in {1}:
        raise OSError("Android screenshot directory cannot be read")
    return events, events_relative.as_posix(), screenshots


def xcresult_export_attachments_argv(result_bundle, output_path):
    """Use the Xcode 16-compatible attachment export arguments without an unpinned filter option."""
    return [
        "/usr/bin/xcrun", "xcresulttool", "export", "attachments",
        "--path", str(result_bundle),
        "--output-path", str(output_path),
    ]


def ios_screenshot_rows(directory, *, scenario_id, ordinal,
                        expected_test_identifier="ScenarioUITests/testFrozenScenarioHarness()",
                        required_names=("screen-final",)):
    """Bind exported screen evidence through xcresult's attachment manifest.

    Export names may be nested or have no extension. The declared human name,
    selected test identity and actual PNG bytes determine screen membership.
    """
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if not isinstance(manifest, list) or any(not isinstance(row, dict) for row in manifest):
        raise ValueError("xcresult attachment manifest is malformed")
    selected = [row for row in manifest if row.get("testIdentifier") == expected_test_identifier]
    if len(selected) != 1 or not isinstance(selected[0].get("attachments"), list):
        raise ValueError("xcresult attachment manifest does not identify the completed scenario test")
    rows, seen_files, found_names = [], set(), set()
    for attachment in selected[0]["attachments"]:
        if not isinstance(attachment, dict):
            raise ValueError("xcresult attachment entry is malformed")
        name = attachment.get("suggestedHumanReadableName")
        if not isinstance(name, str) or not name.startswith("screen-"):
            continue
        filename = attachment.get("exportedFileName")
        if not isinstance(filename, str) or not filename or "\\" in filename:
            raise ValueError("xcresult screen attachment filename is invalid")
        relative = PurePosixPath(filename)
        if relative.is_absolute() or ".." in relative.parts or filename in seen_files:
            raise ValueError("xcresult screen attachment path escapes or duplicates evidence")
        image = directory / relative
        if any((directory / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)):
            raise ValueError("xcresult screen attachment traverses a symlink")
        data = image.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("xcresult declared screen attachment is not PNG data")
        seen_files.add(filename)
        found_names.update(expected for expected in required_names if name == expected or name.startswith(expected + "_"))
        rows.append({"path": (Path(scenario_id) / f"p{ordinal}" / "screenshots" / Path(*relative.parts)).as_posix(), "sha256": hashlib.sha256(data).hexdigest()})
    if not rows or not set(required_names) <= found_names:
        raise ValueError("xcresult export omits required scenario screenshots")
    return sorted(rows, key=lambda row: row["path"])


def _copy_ios_process_artifacts(device, process_id, ordinal, scenario_id, case_root, *, command_runner=subprocess.run):
    attempt_id = process_id.split("/", 1)[0]
    relative = f"Documents/native-harness/{attempt_id}/{scenario_id}/p{ordinal}/native-events.jsonl"
    container = command_runner(
        ["xcrun", "simctl", "get_app_container", device, "dev.nativecontract.demo.ios", "data"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if container.returncode != 0 or not container.stdout.strip():
        raise OSError("owned iOS app container is unavailable for trace export")
    source = Path(container.stdout.strip()) / relative
    events = _native_events_from_bytes(source.read_bytes(), process_instance_id=process_id)
    relative_path = Path(scenario_id) / f"p{ordinal}" / "native.jsonl"
    target = Path(case_root) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events))
    return events, relative_path.as_posix(), []


def _toolchain_scope(candidate, scope):
    toolchain = json.loads((Path(candidate) / "integration/toolchain.json").read_text())
    if scope == "ci":
        return toolchain["acceptancePins"]
    if scope == "local-observed":
        local = toolchain.get("localValidationScope")
        if not isinstance(local, dict) or local.get("id") != "local-observed" or local.get("acceptedByCiAggregate") is not False:
            raise ValueError("explicit local-only validation scope is not frozen")
        return local
    raise ValueError("validationScope must explicitly select ci or local-observed")


def _probe_ios_acceptance_runtime(candidate, command_runner, *, validation_scope="ci"):
    commands = []
    scope = _toolchain_scope(candidate, validation_scope)

    def invoke(argv):
        runtime_inventory = argv == ['xcrun', 'simctl', 'list', 'runtimes', '-j']
        attempts = 3 if runtime_inventory else 1
        timeout = 60 if runtime_inventory else 30
        for attempt in range(attempts):
            try:
                result = command_runner(argv, cwd=candidate, capture_output=True, text=True, timeout=timeout)
                break
            except subprocess.TimeoutExpired:
                commands.append({'argv': argv, 'exitCode': None, 'stdout': '',
                                 'stderr': 'runtime inventory timed out', 'timedOut': True,
                                 'timeoutSeconds': timeout})
                if attempt == attempts - 1:
                    raise
        commands.append({"argv": argv, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0:
            raise OSError(f"iOS acceptance runtime command failed: {argv[0]}")
        return result.stdout

    version = invoke(["xcodebuild", "-version"])
    expected_xcode = scope["ios"]["xcode"]
    if version.splitlines()[:1] != [f"Xcode {expected_xcode}"]:
        pin_label = "acceptance pin" if validation_scope == "ci" else "local scope pin"
        raise ValueError(f"selected Xcode does not match {pin_label} {expected_xcode}")
    document = json.loads(invoke(["xcrun", "simctl", "list", "runtimes", "-j"]))
    rows = document.get("runtimes") if isinstance(document, dict) else None
    if validation_scope == "ci":
        expected_version = "18.2"
        expected_identifier = "com.apple.CoreSimulator.SimRuntime.iOS-18-2"
        expected_build = None
    else:
        expected_version = scope["ios"]["runtimeVersion"]
        expected_identifier = scope["ios"]["runtimeIdentifier"]
        expected_build = scope["ios"]["runtimeBuild"]
    matches = [row for row in rows or [] if isinstance(row, dict)
               and row.get("version") == expected_version and row.get("isAvailable") is True
               and row.get("identifier") == expected_identifier
               and (expected_build is None or row.get("buildversion", row.get("buildVersion")) == expected_build)]
    if len(matches) != 1:
        raise ValueError(f"exact available iOS runtime for {validation_scope} scope is absent")
    return commands, matches[0]


def _probe_android_acceptance_device(serial, command_runner, *, candidate=None, validation_scope="ci"):
    commands = []
    values = {}
    scope = _toolchain_scope(candidate or Path(__file__).resolve().parents[1], validation_scope)
    for name, prop in (("apiLevel", "ro.build.version.sdk"), ("abi", "ro.product.cpu.abi")):
        argv = ["adb", "-s", serial, "shell", "getprop", prop]
        result = command_runner(argv, capture_output=True, text=True, timeout=15)
        commands.append({"argv": argv, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0:
            raise OSError(f"Android device property read failed: {prop}")
        values[name] = result.stdout.strip()
    expected_api = "35"
    expected_abi = "x86_64" if validation_scope == "ci" else scope["android"]["abi"]
    if values["apiLevel"] != expected_api or values["abi"] != expected_abi:
        raise ValueError(
            f"Android device differs from explicit {validation_scope} API35/ABI scope: "
            f"expected API {expected_api} and ABI {expected_abi}, got API {values['apiLevel']} and ABI {values['abi']}"
        )
    if validation_scope == "local-observed":
        evidence_path = os.environ.get("NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE")
        error = _validation_scope_evidence_error(
            "android", serial, evidence_path, candidate=candidate or Path(__file__).resolve().parents[1],
            validation_scope=validation_scope,
        )
        if error is not None:
            raise ValueError(error)
    return commands, values


def _build_ios_candidate(candidate, output, device, environment, timeout_seconds, *, run_candidate_unit_tests=True):
    project = "apps/ios-demo/NativeContractDemo.xcodeproj"
    scheme = "NativeContractDemo"
    derived = Path(output) / "derived-data"
    derived.mkdir(parents=True, exist_ok=True)
    common = [
        "/usr/bin/xcodebuild", "-project", project, "-scheme", scheme,
        "-configuration", "Debug", "-destination", f"id={device}",
        "-derivedDataPath", str(derived), "-parallel-testing-enabled", "NO",
        "CODE_SIGNING_ALLOWED=YES", "CODE_SIGN_IDENTITY=-",
    ]
    if run_candidate_unit_tests:
        unit_result = run_streaming_command(
            [*common, "-only-testing:NativeContractDemoTests", "test"],
            cwd=candidate,
            environment=environment,
            output_directory=Path(output) / "unit-tests",
            timeout_seconds=timeout_seconds,
        )
        if unit_result["exitCode"] != 0 or unit_result["timedOut"]:
            raise OSError("iOS candidate unit-test target failed")
    build_result = run_streaming_command(
        [*common, "build-for-testing"],
        cwd=candidate,
        environment=environment,
        output_directory=Path(output) / "build-for-testing",
        timeout_seconds=timeout_seconds,
    )
    if build_result["exitCode"] != 0 or build_result["timedOut"]:
        raise OSError("iOS candidate build-for-testing failed")
    app = derived / "Build" / "Products" / "Debug-iphonesimulator" / "NativeContractDemo.app"
    xctestruns = sorted((derived / "Build" / "Products").glob("*.xctestrun"))
    if not app.is_dir() or len(xctestruns) != 1:
        raise OSError("iOS app bundle or unique xctestrun artifact was not produced")
    return {"appPath": str(app), "xctestrunPath": str(xctestruns[0]), "buildHash": _sha256_tree(app), "derivedData": str(derived)}


def _select_android_gradle_home(output, environment, *, requested=None, requested_policy=None):
    """Honor an existing explicitly configured cache, with a visible owned fallback."""
    if requested is not None:
        selected = Path(requested).expanduser()
        policy = requested_policy or "caller-supplied"
    else:
        configured = environment.get("GRADLE_USER_HOME") if isinstance(environment, dict) else None
        if isinstance(configured, str) and configured.strip():
            selected = Path(configured).expanduser()
            if not selected.is_dir():
                raise ValueError("prewarmed GRADLE_USER_HOME does not exist as a directory")
            policy = "prewarmed-environment"
        else:
            selected = Path(output) / "gradle-home"
            policy = "owned-output"
    selected = selected.resolve()
    selected.mkdir(parents=True, exist_ok=True)
    return selected, {"path": str(selected), "policy": policy}


# Must agree with the :contract-async buildDirectory in apps/android-demo/settings.gradle.kts
# (integration/tests/test_evaluator_wiring.py checks the two files against each other).
ANDROID_CONTRACT_ASYNC_JAR = "apps/android-demo/app/build/contract-async/libs/contract-async-1.0.0.jar"


def _build_android_candidate(
    candidate, output, environment, timeout_seconds, *, gradle_home=None,
    gradle_home_policy=None, run_candidate_unit_tests=True
):
    gradle_home, gradle_cache = _select_android_gradle_home(
        output, environment, requested=gradle_home, requested_policy=gradle_home_policy
    )
    build_environment = dict(environment)
    build_environment["GRADLE_USER_HOME"] = str(gradle_home)
    argv = ["./apps/android-demo/gradlew", "-p", "apps/android-demo", ":contract-async:jar"]
    if run_candidate_unit_tests:
        argv.append(":app:testDebugUnitTest")
    argv.extend([":app:assembleDebug", ":app:assembleDebugAndroidTest"])
    build_result = run_streaming_command(
        argv,
        cwd=candidate,
        environment=build_environment,
        output_directory=Path(output) / "build",
        timeout_seconds=timeout_seconds,
    )
    if build_result["exitCode"] != 0 or build_result["timedOut"]:
        if run_candidate_unit_tests:
            raise OSError("Android candidate build or unit-test target failed")
        raise OSError("Android mutant build failed")
    app_apk = Path(candidate) / "apps/android-demo/app/build/outputs/apk/debug/app-debug.apk"
    test_apk = Path(candidate) / "apps/android-demo/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
    library_jar = Path(candidate) / ANDROID_CONTRACT_ASYNC_JAR
    if not app_apk.is_file() or not test_apk.is_file() or not library_jar.is_file():
        raise OSError("Android candidate or instrumentation APK/JVM jar is missing")
    return {
        "appApk": str(app_apk),
        "testApk": str(test_apk),
        "libraryJar": str(library_jar),
        "buildHash": _sha256_file(app_apk),
        "testApkHash": _sha256_file(test_apk),
        "libraryJarHash": _sha256_file(library_jar),
        "gradleCache": gradle_cache,
    }


def _android_force_stop(serial, process_id, launch_ordinal, controller_events, command_runner=subprocess.run, timeout_seconds=15):
    package = "dev.nativecontract.demo.android"
    force_argv = ["adb", "-s", serial, "shell", "am", "force-stop", package]
    try:
        forced = command_runner(force_argv, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError(f"owned Android app force-stop failed: {exc}") from exc
    pid_argv = ["adb", "-s", serial, "shell", "pidof", package]
    deadline = time.monotonic() + timeout_seconds
    pid_result = None
    while time.monotonic() < deadline:
        pid_result = command_runner(pid_argv, capture_output=True, text=True, timeout=5)
        if pid_result.returncode == 1 and not pid_result.stdout.strip():
            break
        if pid_result.returncode == 0 and not pid_result.stdout.strip():
            break
        time.sleep(0.1)
    if pid_result is None:
        raise TimeoutError("Android app process termination deadline expired")
    evidence = android_process_termination_evidence(
        instrumentation_exit_code=0,
        force_stop_exit_code=forced.returncode,
        pidof_exit_code=pid_result.returncode,
        pidof_stdout=pid_result.stdout,
    )
    if not evidence["terminated"]:
        raise OSError("Android owned app process termination was not confirmed: " + ", ".join(evidence["missing"]))
    _append_controller_event(controller_events, "forceStopped", process_id, pidAbsent=True)
    _append_controller_event(controller_events, "terminated", process_id, launchOrdinal=launch_ordinal)
    return [
        {"argv": force_argv, "exitCode": forced.returncode, "stdout": forced.stdout, "stderr": forced.stderr},
        {"argv": pid_argv, "exitCode": pid_result.returncode, "stdout": pid_result.stdout, "stderr": pid_result.stderr},
    ]


def _ios_terminate_app(device, process_id, launch_ordinal, controller_events, command_runner=subprocess.run):
    package = "dev.nativecontract.demo.ios"
    argv = ["xcrun", "simctl", "terminate", device, package]
    result = command_runner(argv, capture_output=True, text=True, timeout=15)
    # XCUITest may already have torn down its application. This specific OS
    # response is acceptable only with a successful independent absence probe.
    already_stopped = (
        result.returncode == 3
        and "domain=NSPOSIXErrorDomain, code=3" in result.stderr
        and "found nothing to terminate" in result.stderr
    )
    if result.returncode != 0 and not already_stopped:
        raise OSError("owned iOS app termination was not confirmed")
    probe_argv = ["xcrun", "simctl", "spawn", device, "launchctl", "list"]
    probe = command_runner(probe_argv, capture_output=True, text=True, timeout=15)
    lines = probe.stdout.splitlines()
    if probe.returncode != 0 or not lines or lines[0].split() != ["PID", "Status", "Label"]:
        raise OSError("owned iOS app process absence probe failed")
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 3 or (fields[0] != "-" and not fields[0].isdigit()):
            raise OSError("owned iOS app process absence probe is malformed")
        if fields[0] != "-" and package in fields[2]:
            raise OSError("owned iOS app process is still running")
    _append_controller_event(controller_events, "forceStopped", process_id, pidAbsent=True)
    _append_controller_event(controller_events, "terminated", process_id, launchOrdinal=launch_ordinal)
    return [
        {"argv": argv, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        {"argv": probe_argv, "exitCode": probe.returncode, "stdout": probe.stdout, "stderr": probe.stderr},
    ]


def _remaining_seconds(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("native platform stage deadline exhausted")
    return remaining


def _android_scenario_argv(
    *, serial, scenario_id, run_id, process_id, ordinal, base_url, phase,
    cancel_mode, scenario_digest, control_digest, variant_id, store_fault,
):
    arm_point, arm_target = ("beforeBootstrapClear", "bootstrap") if ordinal == 2 and scenario_id.startswith("APP-12-") else (None, None)
    return _android_instrumentation_argv(
        serial=serial,
        scenario_id=scenario_id,
        run_id=run_id,
        process_instance_id=process_id,
        launch_ordinal=ordinal,
        base_url=base_url,
        scenario_phase=phase,
        cancel_mode=cancel_mode,
        scenario_inventory_sha256=scenario_digest,
        control_inventory_sha256=control_digest,
        variant_id=variant_id,
        store_fault=store_fault,
        arm_point=arm_point,
        arm_target=arm_target,
    )


def _launch_environment(
    *, platform, candidate, scenario_id, run_id, process_id, ordinal, base_url,
    cancel_mode, variant_id, store_fault, scenario_digest, control_digest,
):
    phase = "single"
    if scenario_id.startswith("APP-12-"):
        phase = "seed" if ordinal == 1 else "resume"
    if platform == "ios":
        arm_point, arm_target = ("beforeBootstrapClear", "bootstrap") if ordinal == 2 and scenario_id.startswith("APP-12-") else (None, None)
        return _ios_launch_environment(
            scenario_id=scenario_id,
            run_id=run_id,
            process_instance_id=process_id,
            launch_ordinal=ordinal,
            base_url=base_url,
            scenario_phase=phase,
            cancel_mode=cancel_mode,
            scenario_inventory_path=Path(candidate) / "integration" / "scenarios.json",
            scenario_inventory_sha256=scenario_digest,
            control_inventory_path=Path(candidate) / "integration" / "control-scenarios.json",
            control_inventory_sha256=control_digest,
            variant_id=variant_id,
            store_fault=store_fault,
            arm_point=arm_point,
            arm_target=arm_target,
        )
    return {}


def _build_case_trace(
    *, run_id, scenario, variant, platform, build_hash, process_instances,
    events, controller_events, artifact_paths,
):
    command_inventory = [
        {"commandRef": event["commandRef"], "name": event["name"]}
        for event in events if event.get("kind") == "commandEnqueued"
    ]
    trace = {
        "version": 1,
        "runId": run_id,
        "scenarioId": scenario["id"],
        "platform": platform,
        "buildHash": "sha256:" + build_hash,
        "processInstances": process_instances,
        "controllerEvents": controller_events,
        "commandInventory": command_inventory,
        "events": events,
        "artifactPaths": sorted(set(artifact_paths)),
    }
    if scenario["id"].startswith("CTRL-"):
        trace["controlId"] = scenario["id"]
    elif variant is not None:
        trace["variantId"] = variant["id"]
    return trace


def _run_case(
    *, platform, candidate, output, device, scenario, resolved_scenario, variant,
    attempt_base, contract, build_hash, app_paths, scenario_path, control_path,
    scenario_digest, control_digest, timeout_seconds, command_runner,
):
    scenario_id = scenario["id"]
    variant_id = variant.get("id") if isinstance(variant, dict) else None
    attempt_id = case_attempt_id(attempt_base, platform, scenario_id, variant_id)
    case_root = case_artifact_directory(Path(output).parent, platform, scenario_id, variant_id)
    case_root.mkdir(parents=True, exist_ok=False)
    controller_events = []
    observations = []
    native_events = []
    process_instances = []
    terminated_process_ids = set()
    artifact_paths = []
    runner_results = []
    lifecycle_results = []
    screenshot_rows = []
    case_started = time.monotonic()
    deadline = case_started + timeout_seconds
    commands = _launch_rows(resolved_scenario)
    # Fault selection comes from the hash-bound inventory and is injected by
    # the native harness immediately before its target command. Never arm it
    # in the app or instrumentation process at launch.
    store_fault = None
    cancel_mode = resolved_scenario.get("cancelMode")
    status_bridge = None
    server_events = []
    body_digests = []
    infra_detail = None

    with LoopbackRun(
        candidate=candidate,
        output=case_root,
        platform=platform,
        scenario_id=scenario_id,
        attempt_id=attempt_id,
    ) as run:
        status_bridge = NativeProgressBridge(
            platform=platform,
            run=run,
            device=device,
            attempt_id=attempt_id,
            scenario=resolved_scenario,
            variant=variant,
            controller_events=controller_events,
            observations=observations,
            process_artifact_directory=case_root / scenario_id,
            command_runner=command_runner,
            deadline=deadline,
        )
        for launch in commands:
            ordinal = launch.get("ordinal")
            if type(ordinal) is not int or ordinal <= 0 or not isinstance(launch.get("commands"), list):
                raise ValueError("scenario launch inventory is malformed")
            process_id = android_process_instance_id(attempt_id, scenario_id, ordinal)
            process_instances.append({"processInstanceId": process_id, "launchOrdinal": ordinal})
            _append_controller_event(controller_events, "launch", process_id, launchOrdinal=ordinal)
            phase = "single"
            if scenario_id.startswith("APP-12-"):
                phase = "seed" if ordinal == 1 else "resume"
            if platform == "android":
                argv = _android_scenario_argv(
                    serial=device,
                    scenario_id=scenario_id,
                    run_id=run.run_id,
                    process_id=process_id,
                    ordinal=ordinal,
                    base_url=run.base_url,
                    phase=phase,
                    cancel_mode=cancel_mode,
                    scenario_digest=scenario_digest,
                    control_digest=control_digest,
                    variant_id=variant_id,
                    store_fault=store_fault,
                )
                parser = AndroidInstrumentationStatusParser(
                    expected_scenario_id=scenario_id,
                    expected_process_instance_id=process_id,
                )
            else:
                argv = [
                    "/usr/bin/xcodebuild", "test-without-building",
                    "-xctestrun", app_paths["xctestrunPath"],
                    "-destination", f"id={device}",
                    "-parallel-testing-enabled", "NO",
                    "-resultBundlePath", str(case_root / "runner" / f"p{ordinal}.xcresult"),
                    "-only-testing:NativeContractDemoUITests/ScenarioUITests/testXcodeForwardsFrozenRunnerEnvironment",
                    "-only-testing:NativeContractDemoUITests/ScenarioUITests/testFrozenScenarioHarness",
                ]
                parser = lambda line, scenario_id=scenario_id, process_id=process_id: parse_ios_status_line(
                    line,
                    expected_scenario_id=scenario_id,
                    expected_process_instance_id=process_id,
                )
            if platform == "ios":
                environment = os.environ.copy()
                environment.update(_launch_environment(
                    platform=platform,
                    candidate=candidate,
                    scenario_id=scenario_id,
                    run_id=run.run_id,
                    process_id=process_id,
                    ordinal=ordinal,
                    base_url=run.base_url,
                    cancel_mode=cancel_mode,
                    variant_id=variant_id,
                    store_fault=store_fault,
                    scenario_digest=scenario_digest,
                    control_digest=control_digest,
                ))
            else:
                environment = os.environ.copy()
            runner_output = case_root / "runner" / f"p{ordinal}"
            progress.event("launch-runner-start", scenario=scenario_id, variant=variant_id, launch=ordinal)
            runner_started = time.monotonic()
            try:
                runner_result = run_streaming_command(
                    argv,
                    cwd=candidate,
                    environment=environment,
                    output_directory=runner_output,
                    timeout_seconds=_remaining_seconds(deadline),
                    status_parser=parser.feed if platform == "android" else parser,
                    on_status=status_bridge,
                )
                runner_results.append(runner_result)
                progress.event(
                    "launch-runner-end", scenario=scenario_id, variant=variant_id, launch=ordinal,
                    exitCode=runner_result["exitCode"], timedOut=runner_result["timedOut"],
                    seconds=time.monotonic() - runner_started,
                )
            except (OSError, ValueError, TimeoutError) as exc:
                infra_detail = f"native test runner failed for launch {ordinal}: {exc}"
                progress.event("launch-runner-error", scenario=scenario_id, variant=variant_id, launch=ordinal,
                               seconds=time.monotonic() - runner_started, detail=exc)
                break
            artifacts_started = time.monotonic()

            try:
                if platform == "android":
                    process_events, native_relative, screenshots = _copy_android_process_artifacts(
                        device, attempt_id, scenario_id, ordinal, case_root, command_runner=command_runner
                    )
                else:
                    process_events, native_relative, screenshots = _copy_ios_process_artifacts(
                        device, process_id, ordinal, scenario_id, case_root, command_runner=command_runner
                    )
                    progress.event("launch-copy-end", scenario=scenario_id, variant=variant_id, launch=ordinal,
                                   seconds=time.monotonic() - artifacts_started)
                    screenshot_directory = case_root / scenario_id / f"p{ordinal}" / "screenshots"
                    attachment_result = run_streaming_command(
                        xcresult_export_attachments_argv(
                            case_root / "runner" / f"p{ordinal}.xcresult",
                            screenshot_directory,
                        ),
                        cwd=candidate,
                        environment=os.environ.copy(),
                        output_directory=case_root / "runner" / f"p{ordinal}" / "attachment-export",
                        timeout_seconds=_remaining_seconds(deadline),
                    )
                    if attachment_result["exitCode"] != 0 or attachment_result["timedOut"]:
                        raise OSError("iOS screenshot attachment export failed")
                    required_screens = ["screen-final"]
                    if any("rendered-a1" in step for step in resolved_scenario.get("requiredRenderedViews", [])):
                        required_screens.append("screen-render-at-barrier")
                    screenshots = ios_screenshot_rows(
                        screenshot_directory, scenario_id=scenario_id, ordinal=ordinal,
                        required_names=required_screens,
                    )
                native_events.extend(process_events)
                artifact_paths.extend([
                    native_relative,
                    (Path(scenario_id) / f"p{ordinal}" / "ui.jsonl").as_posix(),
                    *[item["path"] for item in screenshots],
                ])
                screenshot_rows.extend(platform_screenshot_rows(Path(output), case_root, screenshots))
            except (OSError, ValueError) as exc:
                infra_detail = f"native evidence export failed for launch {ordinal}: {exc}"
                break

            if platform == "android":
                try:
                    result_rows = _android_force_stop(device, process_id, ordinal, controller_events, command_runner=command_runner)
                    lifecycle_results.extend(result_rows)
                    terminated_process_ids.add(process_id)
                except (OSError, TimeoutError) as exc:
                    infra_detail = f"Android app termination was not confirmed for launch {ordinal}: {exc}"
                    break
            else:
                try:
                    lifecycle_results.append(_ios_terminate_app(device, process_id, ordinal, controller_events, command_runner=command_runner))
                    terminated_process_ids.add(process_id)
                except OSError as exc:
                    infra_detail = f"iOS app termination was not confirmed for launch {ordinal}: {exc}"
                    break
            progress.event("launch-evidence-end", scenario=scenario_id, variant=variant_id, launch=ordinal,
                           seconds=time.monotonic() - artifacts_started)

        for process in reversed(process_instances):
            process_id = process["processInstanceId"]
            if process_id in terminated_process_ids:
                continue
            ordinal = process["launchOrdinal"]
            try:
                if platform == "android":
                    lifecycle_results.extend(_android_force_stop(device, process_id, ordinal, controller_events, command_runner=command_runner))
                else:
                    lifecycle_results.append(_ios_terminate_app(device, process_id, ordinal, controller_events, command_runner=command_runner))
                terminated_process_ids.add(process_id)
            except (OSError, TimeoutError) as exc:
                infra_detail = infra_detail or f"owned app cleanup failed for launch {ordinal}: {exc}"

        server_evidence_started = time.monotonic()
        try:
            server_events, body_digests = run.events(timeout=min(5, _remaining_seconds(deadline)))
            append_server_controller_events(
                run,
                status_bridge.known_server_sequences,
                controller_events,
                timeout_seconds=_remaining_seconds(deadline),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            infra_detail = infra_detail or f"refresh server evidence capture failed: {exc}"
        progress.event("case-server-evidence-end", scenario=scenario_id, variant=variant_id,
                       seconds=time.monotonic() - server_evidence_started)

    if infra_detail:
        return {
            "scenarioId": scenario_id,
            "variantId": variant_id,
            "classification": "INFRA_FAILURE",
            "violations": [],
            "missingObservations": [],
            "detail": infra_detail,
            "runnerCommands": runner_results,
            "lifecycleCommands": lifecycle_results,
        }, None, screenshot_rows

    status_bridge.bind_native_events(native_events)
    trace = _build_case_trace(
        run_id=run.run_id,
        scenario=scenario,
        variant=variant,
        platform=platform,
        build_hash=build_hash,
        process_instances=process_instances,
        events=native_events,
        controller_events=controller_events,
        artifact_paths=artifact_paths,
    )
    trace_path = case_root / "trace.json"
    write_json(trace_path, trace)
    write_json(case_root / "server-events.json", server_events)
    write_json(case_root / "server-body-digests.json", body_digests)
    write_json(case_root / "ui-observations.json", observations)
    write_json(case_root / "controller-events.json", controller_events)
    write_json(case_root / "screenshots-manifest.json", {"screenshots": screenshot_rows})
    if scenario_id.startswith("CTRL-"):
        report = check_control_trace(contract, scenario, trace, server_events, observations)
    else:
        report = check_trace(contract, scenario, trace, server_events, observations)
    report_path = case_root / "report.json"
    write_json(report_path, report)
    classification = report["classification"]
    if classification == "PASS" and any(row.get("exitCode") != 0 or row.get("timedOut") for row in runner_results if "argv" in row):
        classification = "INFRA_FAILURE"
    result = {
        "scenarioId": scenario_id,
        "variantId": variant_id,
        "classification": classification,
        "violations": report.get("violations", []),
        "missingObservations": report.get("missingObservations", []),
        "tracePath": str(trace_path),
        "reportPath": str(report_path),
        "runnerCommands": runner_results,
        "lifecycleCommands": lifecycle_results,
        "requiredControllerEndMarkers": sorted(status_bridge.end_seen),
        "serverEvents": server_events,
        "serverBodyDigests": body_digests,
        "uiObservations": observations,
        "controllerEvents": controller_events,
    }
    if classification in {"PASS", "SEMANTIC_FAIL"}:
        result["traceBinding"] = {"scenarioId": scenario_id, "variantId": variant_id, "buildHash": "sha256:" + build_hash}
    return result, trace, screenshot_rows


def _run_native_platform(
    *, platform, candidate, output, device, stage_id, attempt_id, scenario_rows,
    scenario_path, scenario_bytes, result, command_runner, timeout_seconds,
    prepared_build=None, mutation_id=None, mutation_provenance=None, write_artifacts=True,
    validation_scope="ci",
):
    started = time.monotonic()
    deadline = started + timeout_seconds
    control_path = Path(candidate) / "integration" / "control-scenarios.json"
    scenario_digest, control_digest = launch_inventory_digests(candidate)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if prepared_build is not None:
        app_paths = prepared_build
    elif platform == "ios":
        runtime_commands, runtime = _probe_ios_acceptance_runtime(
            candidate, command_runner, validation_scope=validation_scope
        )
        result["commands"].extend(runtime_commands)
        result["deviceDetails"] = {
            "device": result.get("deviceDetails"),
            "runtime": runtime,
            "validationScope": validation_scope,
        }
        result["deviceHash"] = digest_bytes(json.dumps(result["deviceDetails"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
        app_paths = _build_ios_candidate(candidate, output, device, environment, _remaining_seconds(deadline))
    else:
        device_commands, device_runtime = _probe_android_acceptance_device(
            device, command_runner, candidate=candidate, validation_scope=validation_scope
        )
        result["commands"].extend(device_commands)
        result["deviceDetails"] = {
            "device": result.get("deviceDetails"),
            "runtime": device_runtime,
            "validationScope": validation_scope,
        }
        result["deviceHash"] = digest_bytes(json.dumps(result["deviceDetails"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
        app_paths = _build_android_candidate(candidate, output, environment, _remaining_seconds(deadline))
        for name, apk in (("candidate-install", app_paths["appApk"]), ("instrumentation-install", app_paths["testApk"])):
            install = run_streaming_command(
                ["adb", "-s", device, "install", "-r", apk],
                cwd=candidate,
                environment=environment,
                output_directory=Path(output) / name,
                timeout_seconds=_remaining_seconds(deadline),
            )
            result["commands"].append(install)
            if install["exitCode"] != 0 or install["timedOut"]:
                raise OSError(f"Android {name} failed")
    result["buildHash"] = app_paths["buildHash"]
    result["buildDetails"] = app_paths
    case_results = []
    trace_rows = []
    server_rows = []
    ui_rows = []
    controller_rows = []
    screenshot_rows = []
    trace_bindings = []
    for base_scenario, resolved, variant in _case_inventory(scenario_rows):
        remaining = _remaining_seconds(deadline)
        case_variant = variant.get("id") if isinstance(variant, dict) else None
        progress.event("case-start", platform=platform, mutation=mutation_id, scenario=base_scenario["id"],
                       variant=case_variant, remainingSeconds=remaining)
        case_started = time.monotonic()
        try:
            case_result, trace, case_screenshots = _run_case(
                platform=platform,
                candidate=candidate,
                output=output,
                device=device,
                scenario=base_scenario,
                resolved_scenario=resolved,
                variant=variant,
                attempt_base=attempt_id,
                contract=json.loads((Path(candidate) / "integration" / "contract.json").read_text()),
                build_hash=app_paths["buildHash"],
                app_paths=app_paths,
                scenario_path=scenario_path,
                control_path=control_path,
                scenario_digest=scenario_digest,
                control_digest=control_digest,
                timeout_seconds=remaining,
                command_runner=command_runner,
            )
        except (OSError, ValueError, TimeoutError, KeyError, TypeError) as exc:
            case_result = {
                "scenarioId": base_scenario["id"],
                "variantId": variant.get("id") if isinstance(variant, dict) else None,
                "classification": "INFRA_FAILURE",
                "violations": [],
                "missingObservations": [],
                "detail": f"native case orchestration failed: {exc}",
            }
            trace = None
            case_screenshots = []
        progress.event(
            "case-end", platform=platform, mutation=mutation_id, scenario=base_scenario["id"], variant=case_variant,
            classification=case_result.get("classification"), seconds=time.monotonic() - case_started,
            detail=case_result.get("detail"),
        )
        if mutation_id is not None:
            case_result["mutationId"] = mutation_id
            case_result["buildHash"] = "sha256:" + app_paths["buildHash"]
            case_result["workspaceSourceSha256"] = mutation_provenance["workspaceSourceSha256"]
        case_results.append(case_result)
        screenshot_rows.extend(case_screenshots)
        if trace is not None:
            trace_rows.append({
                "scenarioId": base_scenario["id"],
                "variantId": case_result.get("variantId"),
                "trace": trace,
            })
            case_root = Path(case_result["tracePath"]).parent
            server_rows.append({
                "scenarioId": base_scenario["id"],
                "variantId": case_result.get("variantId"),
                "runId": trace["runId"],
                "events": json.loads((case_root / "server-events.json").read_text()),
                "bodyDigests": json.loads((case_root / "server-body-digests.json").read_text()),
            })
            ui_rows.append({
                "scenarioId": base_scenario["id"],
                "variantId": case_result.get("variantId"),
                "observations": json.loads((case_root / "ui-observations.json").read_text()),
            })
            controller_rows.append({
                "scenarioId": base_scenario["id"],
                "variantId": case_result.get("variantId"),
                "events": json.loads((case_root / "controller-events.json").read_text()),
            })
        binding = case_result.get("traceBinding")
        if binding is not None:
            trace_bindings.append({"platform": platform, **binding})

    required = set(result["requiredScenarioIds"])
    variants_by_scenario = {}
    for row in scenario_rows:
        variants_by_scenario[row["id"]] = len(row.get("variants") or [None])
    complete_case_counts = {}
    for case in case_results:
        if case["classification"] in {"PASS", "SEMANTIC_FAIL", "NOT_DETECTED"}:
            complete_case_counts[case["scenarioId"]] = complete_case_counts.get(case["scenarioId"], 0) + 1
    completed = [
        scenario_id for scenario_id in result["requiredScenarioIds"]
        if complete_case_counts.get(scenario_id) == variants_by_scenario.get(scenario_id)
    ]
    missing = [scenario_id for scenario_id in result["requiredScenarioIds"] if scenario_id not in completed]
    statuses = [case["classification"] for case in case_results]
    if "INFRA_FAILURE" in statuses:
        classification = "INFRA_FAILURE"
    elif "INVALID_HISTORY" in statuses:
        classification = "INVALID_HISTORY"
    elif "NOT_RUN" in statuses:
        classification = "NOT_RUN"
    elif "INCONCLUSIVE" in statuses or "NOT_DETECTED" in statuses or missing:
        classification = "INCONCLUSIVE"
    elif "SEMANTIC_FAIL" in statuses:
        classification = "SEMANTIC_FAIL"
    else:
        classification = "PASS"
    result.update(
        classification=classification,
        completedScenarioIds=completed,
        missingScenarioIds=missing,
        violations=[violation for case in case_results for violation in case.get("violations", [])],
        traceBindings=trace_bindings,
    )
    if mutation_id is not None:
        result["scenarioBuildHashes"] = {
            row["scenarioId"]: row["buildHash"]
            for row in case_results if isinstance(row.get("buildHash"), str)
        }
        result["mutationId"] = mutation_id
        result["mutationProvenance"] = mutation_provenance
    if not write_artifacts:
        result["_caseResults"] = case_results
        result["_traceRows"] = trace_rows
        result["_serverRows"] = server_rows
        result["_uiRows"] = ui_rows
        result["_controllerRows"] = controller_rows
        result["_screenshotRows"] = screenshot_rows
        return result
    filenames = (
        "device.json", "build.json", "scenario-results.json", "native-trace.jsonl",
        "server-events.json", "ui-observations.json", "controller-events.json",
        "screenshots/manifest.json", "platform-report.json",
    )
    result["requiredArtifacts"] = [f"{stage_id}/{platform}/{name}" for name in filenames]
    write_json(Path(output) / "device.json", {
        "classification": classification,
        "deviceId": device,
        "deviceHash": result["deviceHash"],
        "device": result.get("deviceDetails"),
    })
    write_json(Path(output) / "build.json", {
        "classification": classification,
        "buildHash": result["buildHash"],
        "scenarioBuildHashes": result.get("scenarioBuildHashes", {}),
        "build": result.get("buildDetails"),
    })
    write_json(Path(output) / "scenario-results.json", {"platform": platform, "classification": classification, "cases": case_results})
    native_path = Path(output) / "native-trace.jsonl"
    native_path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in trace_rows))
    write_json(Path(output) / "server-events.json", {"cases": server_rows})
    write_json(Path(output) / "ui-observations.json", {"cases": ui_rows})
    write_json(Path(output) / "controller-events.json", {"cases": controller_rows})
    (Path(output) / "screenshots").mkdir(parents=True, exist_ok=True)
    write_json(Path(output) / "screenshots" / "manifest.json", {"screenshots": screenshot_rows})
    write_json(Path(output) / "platform-report.json", result)
    return result


def _run_mutation_control_platform(
    *, platform, candidate, output, device, stage_id, attempt_id, scenario_rows,
    scenario_path, scenario_bytes, base_result, command_runner, timeout_seconds,
    validation_scope="ci",
):
    """Build one isolated copied mutant per frozen control mutation group."""
    candidate = Path(candidate).resolve()
    output = Path(output)
    matrix_path = candidate / "integration" / "mutation_matrix.json"
    control_path = candidate / "integration" / "control-scenarios.json"
    validate_control_bindings(matrix_path, control_path)
    controls_by_mutation = {}
    for control in scenario_rows:
        mutation_id = mutation_for_control(control_id=control["id"], matrix_path=matrix_path)
        controls_by_mutation.setdefault(mutation_id, []).append(control)

    started = time.monotonic()
    deadline = started + timeout_seconds
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        if platform == "ios":
            runtime_commands, runtime = _probe_ios_acceptance_runtime(
                candidate, command_runner, validation_scope=validation_scope
            )
            base_result["commands"].extend(runtime_commands)
        else:
            runtime_commands, runtime = _probe_android_acceptance_device(
                device, command_runner, candidate=candidate, validation_scope=validation_scope
            )
            base_result["commands"].extend(runtime_commands)
            shared_gradle_home, shared_gradle_cache = _select_android_gradle_home(
                output / "mutation-builds", environment
            )
            base_result["gradleCache"] = shared_gradle_cache
        base_result["deviceDetails"] = {
            "device": base_result.get("deviceDetails"),
            "runtime": runtime,
            "validationScope": validation_scope,
        }
        base_result["deviceHash"] = digest_bytes(
            json.dumps(base_result["deviceDetails"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
        base_result.update(classification="INFRA_FAILURE", detail=f"platform runtime pin check failed: {exc}")
        return _write_platform_artifact_shell(
            output,
            platform=platform,
            stage_id=stage_id,
            scenario_rows=scenario_rows,
            result=base_result,
        )
    group_results = []
    mutation_builds = []
    install_commands = []
    cases = []
    trace_rows = []
    server_rows = []
    ui_rows = []
    controller_rows = []
    screenshot_rows = []
    trace_bindings = []
    case_build_hashes = {}
    if platform != "android":
        shared_gradle_home = None
        shared_gradle_cache = None

    for mutation_id, group_controls in controls_by_mutation.items():
        build_output = output / "mutation-builds" / mutation_id
        build_output.mkdir(parents=True, exist_ok=False)
        workspace_parent = Path(tempfile.mkdtemp(prefix="native-contract-mutant-workspace-"))
        workspace = workspace_parent / "candidate-copy"
        provenance = None
        app_paths = None
        group_record = {
            "mutationId": mutation_id,
            "controlIds": [row["id"] for row in group_controls],
            "classification": "INFRA_FAILURE",
        }
        if shared_gradle_cache is not None:
            group_record["gradleCache"] = shared_gradle_cache
        try:
            provenance = prepare_mutation_workspace(
                candidate=candidate,
                workspace=workspace,
                mutation_id=mutation_id,
                platform=platform,
                matrix_path=matrix_path,
            )
            group_record["candidateUnitTestPolicy"] = provenance["candidateUnitTestPolicy"]
            build_budget = _remaining_seconds(deadline)
            if platform == "ios":
                app_paths = _build_ios_candidate(
                    workspace, build_output, device, environment, build_budget,
                    run_candidate_unit_tests=False,
                )
            else:
                app_paths = _build_android_candidate(
                    workspace,
                    build_output,
                    environment,
                    build_budget,
                    gradle_home=shared_gradle_home,
                    gradle_home_policy=shared_gradle_cache["policy"],
                    run_candidate_unit_tests=False,
                )
                for name, apk in (("candidate-install", app_paths["appApk"]), ("instrumentation-install", app_paths["testApk"])):
                    installed = run_streaming_command(
                        ["adb", "-s", device, "install", "-r", apk],
                        cwd=workspace,
                        environment=environment,
                        output_directory=build_output / name,
                        timeout_seconds=_remaining_seconds(deadline),
                    )
                    install_commands.append({"mutationId": mutation_id, **installed})
                    if installed["exitCode"] != 0 or installed["timedOut"]:
                        raise OSError(f"Android mutant {name} failed")

            mutation_build = {
                "mutationId": mutation_id,
                "controlIds": [row["id"] for row in group_controls],
                "classification": "BUILD_READY",
                "platform": platform,
                "workspaceSourceSha256": provenance["workspaceSourceSha256"],
                "matrixSha256": provenance["matrixSha256"],
                "patchManifest": provenance["patchManifest"],
                "patchedPlatformSource": provenance["patchedPlatformSource"],
                "helper": provenance["helper"],
                "candidateUnitTestPolicy": provenance["candidateUnitTestPolicy"],
                "buildHash": "sha256:" + app_paths["buildHash"],
                **({"gradleCache": app_paths["gradleCache"]} if isinstance(app_paths.get("gradleCache"), dict) else {}),
                "artifactHashes": {
                    key: "sha256:" + app_paths[key]
                    for key in ("testApkHash", "libraryJarHash")
                    if isinstance(app_paths.get(key), str)
                },
                "buildCommands": {
                    name: {
                        "stdoutSha256": _sha256_file(build_output / name / "stdout.log"),
                        "stderrSha256": _sha256_file(build_output / name / "stderr.log"),
                    }
                    for name in ("unit-tests", "build-for-testing", "build")
                    if (build_output / name / "stdout.log").is_file()
                    and (build_output / name / "stderr.log").is_file()
                },
                "installCommands": [row for row in install_commands if row["mutationId"] == mutation_id],
            }
            group_result = {
                **base_result,
                "requiredScenarioIds": [row["id"] for row in group_controls],
                "deviceHash": base_result.get("deviceHash"),
                "deviceDetails": base_result.get("deviceDetails"),
                "commands": list(base_result.get("commands", [])),
            }
            group_result = _run_native_platform(
                platform=platform,
                candidate=candidate,
                output=output,
                device=device,
                stage_id=stage_id,
                attempt_id=attempt_id,
                scenario_rows=group_controls,
                scenario_path=scenario_path,
                scenario_bytes=scenario_bytes,
                result=group_result,
                command_runner=command_runner,
                timeout_seconds=_remaining_seconds(deadline),
                prepared_build=app_paths,
                mutation_id=mutation_id,
                mutation_provenance=provenance,
                write_artifacts=False,
                validation_scope=validation_scope,
            )
            group_record["classification"] = group_result["classification"]
            for case in group_result["_caseResults"]:
                case_id = case.get("scenarioId")
                case["mutationId"] = mutation_id
                case["buildHash"] = "sha256:" + app_paths["buildHash"]
                case["workspaceSourceSha256"] = provenance["workspaceSourceSha256"]
                if case_id and case.get("classification") in {"PASS", "SEMANTIC_FAIL", "NOT_DETECTED"}:
                    case_build_hashes[case_id] = case["buildHash"]
            cases.extend(group_result["_caseResults"])
            trace_rows.extend(group_result["_traceRows"])
            server_rows.extend(group_result["_serverRows"])
            ui_rows.extend(group_result["_uiRows"])
            controller_rows.extend(group_result["_controllerRows"])
            screenshot_rows.extend(group_result["_screenshotRows"])
            trace_bindings.extend(group_result["traceBindings"])
            mutation_builds.append(mutation_build)
        except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
            group_record["detail"] = f"mutant source preparation/build/install failed: {exc}"
            for control in group_controls:
                cases.append({
                    "scenarioId": control["id"],
                    "variantId": None,
                    "classification": "INFRA_FAILURE",
                    "violations": [],
                    "missingObservations": [],
                    "mutationId": mutation_id,
                    "detail": group_record["detail"],
                })
            mutation_builds.append(group_record)
        finally:
            shutil.rmtree(workspace_parent, ignore_errors=True)
            if platform == "ios":
                shutil.rmtree(build_output / "derived-data", ignore_errors=True)

    if platform == "android" and shared_gradle_cache["policy"] == "owned-output":
        shutil.rmtree(shared_gradle_home, ignore_errors=True)

    required = [row["id"] for row in scenario_rows]
    variants_by_scenario = {row["id"]: len(row.get("variants") or [None]) for row in scenario_rows}
    complete_counts = {}
    for case in cases:
        if case.get("classification") in {"PASS", "SEMANTIC_FAIL", "NOT_DETECTED"}:
            complete_counts[case["scenarioId"]] = complete_counts.get(case["scenarioId"], 0) + 1
    completed = [
        scenario_id for scenario_id in required
        if complete_counts.get(scenario_id) == variants_by_scenario.get(scenario_id)
    ]
    missing = [scenario_id for scenario_id in required if scenario_id not in completed]
    statuses = [case.get("classification") for case in cases]
    if "INFRA_FAILURE" in statuses:
        classification = "INFRA_FAILURE"
    elif "INVALID_HISTORY" in statuses:
        classification = "INVALID_HISTORY"
    elif "NOT_RUN" in statuses:
        classification = "NOT_RUN"
    elif "INCONCLUSIVE" in statuses or "NOT_DETECTED" in statuses or missing:
        classification = "INCONCLUSIVE"
    elif "SEMANTIC_FAIL" in statuses:
        classification = "SEMANTIC_FAIL"
    else:
        classification = "PASS"

    result = {
        **base_result,
        "version": 1,
        "classification": classification,
        "platform": platform,
        "deviceId": device,
        "requiredScenarioIds": required,
        "completedScenarioIds": completed,
        "missingScenarioIds": missing,
        "deviceHash": base_result.get("deviceHash"),
        "buildHash": None,
        "scenarioBuildHashes": case_build_hashes,
        "buildDetails": {"mutations": mutation_builds},
        "mutationBuilds": mutation_builds,
        "installCommands": install_commands,
        "violations": [row for case in cases for row in case.get("violations", [])],
        "traceBindings": trace_bindings,
    }
    filenames = (
        "device.json", "build.json", "scenario-results.json", "native-trace.jsonl",
        "server-events.json", "ui-observations.json", "controller-events.json",
        "screenshots/manifest.json", "platform-report.json",
    )
    result["requiredArtifacts"] = [f"{stage_id}/{platform}/{name}" for name in filenames]
    write_json(output / "device.json", {
        "classification": classification,
        "deviceId": device,
        "deviceHash": result["deviceHash"],
        "device": result.get("deviceDetails"),
    })
    write_json(output / "build.json", {
        "classification": classification,
        "buildHash": None,
        "scenarioBuildHashes": case_build_hashes,
        "mutations": mutation_builds,
    })
    write_json(output / "scenario-results.json", {
        "platform": platform,
        "classification": classification,
        "cases": cases,
    })
    (output / "native-trace.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in trace_rows)
    )
    write_json(output / "server-events.json", {"cases": server_rows})
    write_json(output / "ui-observations.json", {"cases": ui_rows})
    write_json(output / "controller-events.json", {"cases": controller_rows})
    (output / "screenshots").mkdir(parents=True, exist_ok=True)
    write_json(output / "screenshots" / "manifest.json", {"screenshots": screenshot_rows})
    write_json(output / "platform-report.json", result)
    return result


def run_platform(
    platform: str,
    *,
    candidate: Path,
    output: Path,
    device: str,
    scenarios: Path,
    command_runner=subprocess.run,
    stage_id: str | None = None,
    attempt_id: str | None = None,
    required_scenario_ids: list[str] | None = None,
    owned_device_evidence: Path | None = None,
    timeout_seconds: float = 1200,
    validation_scope: str | None = None,
    scenario_subset: bool = False,
) -> dict:
    """Inspect and run one native platform using only the explicitly named device.

    The status bridge, independent probes and report shell are available before
    candidate behavior; absent candidate runtime sources remain NOT_RUN.
    """
    if platform not in {"ios", "android"}:
        raise ValueError("platform must be ios or android")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise ValueError("device identifier must be a nonempty explicit ID or omitted")
    candidate = Path(candidate).resolve()
    validation_scope = validation_scope or os.environ.get("NATIVE_CONTRACT_VALIDATION_SCOPE", "ci")
    output = Path(output).absolute()
    if output.exists():
        return {"classification": "INFRA_FAILURE", "detail": "output path already exists"}
    scenario_path = Path(scenarios)
    try:
        scenario_bytes = scenario_path.read_bytes()
        scenario_document = json.loads(scenario_bytes)
        inventory_key = "controls" if "controls" in scenario_document and "scenarios" not in scenario_document else "scenarios"
        scenario_rows = scenario_document[inventory_key]
        if (
            not isinstance(scenario_rows, list)
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in scenario_rows)
            or len({row["id"] for row in scenario_rows}) != len(scenario_rows)
        ):
            raise ValueError("inventory rows must have unique scenario IDs")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"classification": "INFRA_FAILURE", "detail": f"scenario inventory unavailable: {exc}"}

    subset_error = None
    if scenario_subset:
        if (
            platform != 'ios' or stage_id not in IOS_SHARD_STAGES or inventory_key != 'scenarios'
            or not isinstance(required_scenario_ids, list) or not required_scenario_ids
            or any(not isinstance(value, str) for value in required_scenario_ids)
            or len(set(required_scenario_ids)) != len(required_scenario_ids)
            or [row['id'] for row in scenario_rows if row['id'] in required_scenario_ids] != required_scenario_ids
        ):
            subset_error = 'invalid iOS shard subset or inventory order'
        else:
            scenario_rows = [row for row in scenario_rows if row['id'] in required_scenario_ids]
            scenario_document[inventory_key] = scenario_rows
            scenario_bytes = encode(scenario_document)

    output.mkdir(parents=True)
    inventory_copy = output / ("control-scenarios.json" if inventory_key == "controls" else "scenarios.json")
    inventory_copy.write_bytes(scenario_bytes)
    ids = [row["id"] for row in scenario_rows]
    if subset_error or (required_scenario_ids is not None and ids != required_scenario_ids):
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id or f"candidate-{platform}", scenario_rows=scenario_rows, result={
            "version": 1, "classification": "INVALID_HISTORY", "platform": platform, "deviceId": device,
            "requiredScenarioIds": list(required_scenario_ids or []), "scenarioIds": ids,
            "scenarioDigest": digest_bytes(scenario_bytes), "deviceHash": None, "buildHash": None,
            "completedScenarioIds": [], "missingScenarioIds": list(required_scenario_ids or []),
            "violations": ["provided scenario inventory differs from the required frozen IDs"],
            "missingObservations": [], "commands": [], "detail": subset_error or "scenario inventory ID mismatch",
        })
    required_ids = list(required_scenario_ids) if required_scenario_ids is not None else ids
    if stage_id is None:
        stage_id = f"candidate-{platform}"
    if attempt_id is None:
        attempt_id = output.parent.name if _ANDROID_LABEL.fullmatch(output.parent.name) else "attempt-01"
    if _ANDROID_LABEL.fullmatch(attempt_id) is None:
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result={
            "version": 1, "classification": "INFRA_FAILURE", "platform": platform, "deviceId": device,
            "requiredScenarioIds": required_ids, "scenarioIds": ids, "scenarioDigest": digest_bytes(scenario_bytes),
            "deviceHash": None, "buildHash": None, "completedScenarioIds": [], "missingScenarioIds": required_ids,
            "violations": [], "missingObservations": [], "commands": [], "detail": "attempt ID is not a frozen ASCII label",
        })
    result = {
        "version": 1,
        "classification": "NOT_RUN",
        "platform": platform,
        "deviceId": device,
        "scenarioIds": ids,
        "requiredScenarioIds": required_ids,
        "scenarioDigest": digest_bytes(scenario_bytes),
        "validationScope": validation_scope,
        "deviceHash": None,
        "buildHash": None,
        "completedScenarioIds": [],
        "missingScenarioIds": required_ids,
        "violations": [],
        "missingObservations": [],
        "commands": [],
    }

    if device is None:
        result["detail"] = "no explicitly owned device was assigned to this platform stage"
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    if platform == "ios":
        argv = ["xcrun", "simctl", "list", "devices", "--json"]
    else:
        argv = ["adb", "devices", "-l"]
    # Hosted macOS runners sometimes never answer `simctl list devices`; a fresh call succeeds.
    for attempt in range(1, 4):
        try:
            completed = command_runner(argv, cwd=candidate, capture_output=True, text=True, timeout=60)
            break
        except subprocess.TimeoutExpired as exc:
            if attempt == 3:
                result.update(classification="INFRA_FAILURE", detail=f"device inventory failed: {exc}")
                return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)
        except OSError as exc:
            result.update(classification="INFRA_FAILURE", detail=f"device inventory failed: {exc}")
            return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)
    result["commands"].append({"argv": argv, "exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
    if completed.returncode != 0:
        result.update(classification="INFRA_FAILURE", detail="device inventory command failed")
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)
    try:
        if platform == "ios":
            rows = _ios_device_rows(json.loads(completed.stdout))
            owned_device = next((row for row in rows if isinstance(row.get("udid"), str) and row["udid"].casefold() == device.casefold()), None)
            ready = owned_device is not None and owned_device.get("state") == "Booted"
        else:
            rows = _android_device_rows(completed.stdout)
            owned_device = next((row for row in rows if row.get("serial") == device), None)
            ready = owned_device is not None
    except json.JSONDecodeError as exc:
        result.update(classification="INFRA_FAILURE", detail=f"device inventory JSON is invalid: {exc}")
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    result["deviceDetails"] = owned_device
    if owned_device is not None:
        if platform == "ios":
            device = owned_device["udid"]
            result["deviceId"] = device
        result["deviceHash"] = digest_bytes(json.dumps(owned_device, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if not ready:
        result["detail"] = "the explicitly requested device is absent or not booted"
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    missing_sources = _candidate_runtime_missing(platform, candidate)
    if missing_sources:
        result["detail"] = "candidate runtime implementation is absent: " + ", ".join(missing_sources)
        result["missingSources"] = missing_sources
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    ownership_error = _owned_device_evidence_error(platform, device, owned_device_evidence, candidate=candidate)
    if ownership_error:
        result.update(classification="INFRA_FAILURE", detail=ownership_error)
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    if platform == "android":
        try:
            ownership_document = json.loads(Path(owned_device_evidence).read_text())
            expected_avd_name = ownership_document.get("name", ownership_document.get("avdName"))
            argv = ["adb", "-s", device, "emu", "avd", "name"]
            avd_name = command_runner(argv, cwd=candidate, capture_output=True, text=True, timeout=15)
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            result.update(classification="INFRA_FAILURE", detail=f"owned AVD verification failed: {exc}")
            return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)
        result["commands"].append({"argv": argv, "exitCode": avd_name.returncode, "stdout": avd_name.stdout, "stderr": avd_name.stderr})
        observed_avd_name = next((line.strip() for line in avd_name.stdout.splitlines() if line.strip() and line.strip() != "OK"), None)
        if avd_name.returncode != 0 or not isinstance(expected_avd_name, str) or observed_avd_name != expected_avd_name:
            result.update(classification="INFRA_FAILURE", detail="adb serial does not resolve to the controller-owned AVD")
            return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    scope_error = _validation_scope_evidence_error(
        platform,
        device,
        owned_device_evidence,
        candidate=candidate,
        validation_scope=validation_scope,
    )
    if scope_error:
        result.update(classification="INFRA_FAILURE", detail=scope_error)
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)

    try:
        if inventory_key == "controls":
            return _run_mutation_control_platform(
                platform=platform,
                candidate=candidate,
                output=output,
                device=device,
                stage_id=stage_id,
                attempt_id=attempt_id,
                scenario_rows=scenario_rows,
                scenario_path=scenario_path,
                scenario_bytes=scenario_bytes,
                base_result=result,
                command_runner=command_runner,
                timeout_seconds=timeout_seconds,
                validation_scope=validation_scope,
            )
        return _run_native_platform(
            platform=platform,
            candidate=candidate,
            output=output,
            device=device,
            stage_id=stage_id,
            attempt_id=attempt_id,
            scenario_rows=scenario_rows,
            scenario_path=scenario_path,
            scenario_bytes=scenario_bytes,
            result=result,
            command_runner=command_runner,
            timeout_seconds=timeout_seconds,
            validation_scope=validation_scope,
        )
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired, KeyError, TypeError) as exc:
        result.update(classification="INFRA_FAILURE", detail=f"native platform stage failed: {exc}")
        return _write_platform_artifact_shell(output, platform=platform, stage_id=stage_id, scenario_rows=scenario_rows, result=result)
