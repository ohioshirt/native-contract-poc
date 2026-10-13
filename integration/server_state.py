"""Bounded, synchronized state for controllable refresh HTTP runs."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import threading
from pathlib import Path

from integration.wire import MAX_BODY_BYTES, MAX_SIGNED64, WireError


MAX_RUNS = 16
MAX_PENDING_PER_RUN = 8
MAX_CHECKPOINTS_PER_RUN = 32
HOLD_SECONDS = 60
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_ISSUANCE_ID = re.compile(r"[1-9][0-9]{0,18}\Z", re.ASCII)


class ServerError(ValueError):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code


class PendingRequest:
    """One held response, independently synchronized from server state."""

    def __init__(self, request: dict):
        self.request = request
        self._condition = threading.Condition()
        self._outcome = None

    def resolve(self, outcome: dict):
        with self._condition:
            if self._outcome is None:
                self._outcome = deepcopy(outcome)
                self._condition.notify_all()

    def wait(self, timeout: float):
        with self._condition:
            if not self._condition.wait_for(lambda: self._outcome is not None, timeout):
                return {"kind": "timeout"}
            return deepcopy(self._outcome)


@dataclass
class _Run:
    run_id: str
    control_key: str
    scenario_id: str
    platform: str
    attempt_id: str
    process_ids: set[str]
    checkpoint_names: set[str]
    pending: OrderedDict = field(default_factory=OrderedDict)
    used_tags: set[str] = field(default_factory=set)
    checkpoints: set[tuple[str, str]] = field(default_factory=set)
    event_rows: list[dict] = field(default_factory=list)
    body_digests: list[dict] = field(default_factory=list)
    next_sequence: int = 1
    closed: bool = False


class ServerState:
    def __init__(self, scenarios_path=None, controls_path=None):
        root = Path(__file__).resolve().parents[1]
        scenarios_path = Path(scenarios_path) if scenarios_path else root / "integration" / "scenarios.json"
        controls_path = Path(controls_path) if controls_path else root / "integration" / "control-scenarios.json"
        scenarios_doc = json.loads(scenarios_path.read_text())
        controls_doc = json.loads(controls_path.read_text())
        self._scenarios = {row["id"]: row for row in scenarios_doc["scenarios"]}
        self._controls = {row["id"]: row for row in controls_doc["controls"]}
        self._lock = threading.RLock()
        self._runs: dict[str, _Run] = {}

    @staticmethod
    def _valid_label(value):
        return isinstance(value, str) and _LABEL.fullmatch(value) is not None

    def create_run(self, scenario_id: str, platform: str, attempt_id: str) -> dict:
        if not self._valid_label(attempt_id) or not self._valid_label(scenario_id):
            raise ServerError(400, "invalid_label", "attemptId and scenarioId must be ASCII labels of length 1..64")
        if platform not in {"ios", "android"}:
            raise ServerError(400, "invalid_platform", "platform must be ios or android")
        row = self._scenarios.get(scenario_id)
        if row is not None:
            if platform not in row.get("platforms", ["ios", "android"]):
                raise ServerError(400, "scenario_platform_mismatch", "platform is not declared for this scenario")
            command_variants = {}
            for launch in row.get("launches", []):
                command_variants.setdefault(launch["ordinal"], []).append(launch["commands"])
            if not command_variants:
                variants = row.get("variants", [])
                command_variants[1] = [variant["commands"] for variant in variants] or [[]]
            checkpoint_names = {"bootstrapStoreProbed"}
            required_probes = list(row.get("requiredProbes", []))
            for variant in row.get("variants", []):
                required_probes.extend(variant.get("requiredProbes", []))
            checkpoint_names.update(f"storeProbe.{step}" for step in required_probes)
        else:
            control = self._controls.get(scenario_id)
            if control is None:
                raise ServerError(400, "unknown_scenario", "scenarioId is not declared in the frozen inventory")
            command_variants = {1: [control.get("commands", [])]}
            checkpoint_names = {"bootstrapStoreProbed"}
            checkpoint_names.update(f"storeProbe.{step}" for step in control.get("requiredProbes", []))
            checkpoint_names.update(
                f"detachedEffectAwaited.{action['effectId']}"
                for action in control.get("controlActions", [])
                if isinstance(action, dict) and action.get("action") == "awaitDetachedEffect"
                and isinstance(action.get("effectId"), str)
            )

        ordinals = sorted(command_variants)

        with self._lock:
            if len(self._runs) >= MAX_RUNS:
                raise ServerError(429, "run_capacity", "the bounded run capacity is full")
            run_id = "run-" + secrets.token_hex(12)
            control_key = secrets.token_urlsafe(32)
            process_ids = {f"{attempt_id}/{scenario_id}/p{ordinal}" for ordinal in ordinals}
            self._runs[run_id] = _Run(
                run_id=run_id,
                control_key=control_key,
                scenario_id=scenario_id,
                platform=platform,
                attempt_id=attempt_id,
                process_ids=process_ids,
                checkpoint_names=checkpoint_names,
            )
            return {"version": 1, "runId": run_id, "controlKey": control_key}

    def _run(self, run_id: str) -> _Run:
        run = self._runs.get(run_id)
        if run is None or run.closed:
            raise ServerError(404, "unknown_run", "run does not exist")
        return run

    @staticmethod
    def _valid_request_tag(run: _Run, tag: str) -> bool:
        for process_id in run.process_ids:
            prefix = process_id + ":refresh:"
            if not tag.startswith(prefix):
                continue
            issuance_id = tag[len(prefix):]
            if _ISSUANCE_ID.fullmatch(issuance_id) is None:
                return False
            return int(issuance_id) <= MAX_SIGNED64
        return False

    def authenticate(self, run_id: str, control_key: str) -> _Run:
        with self._lock:
            run = self._run(run_id)
            if not isinstance(control_key, str) or not hmac.compare_digest(run.control_key, control_key):
                raise ServerError(403, "forbidden", "control key is invalid")
            return run

    def hold(self, request: dict) -> PendingRequest:
        if not isinstance(request, dict):
            raise ServerError(400, "invalid_envelope", "refresh request is invalid")
        run_id, tag = request.get("runId"), request.get("requestTag")
        if not isinstance(run_id, str) or not isinstance(tag, str):
            raise ServerError(400, "invalid_envelope", "refresh request lacks runId or requestTag")
        sanitized = {key: request[key] for key in ("runId", "requestTag", "requestId", "account")}
        digest = request.get("_bodyDigest")
        if isinstance(digest, str):
            sanitized["_bodyDigest"] = digest
        with self._lock:
            run = self._run(run_id)
            if not self._valid_request_tag(run, tag):
                raise ServerError(400, "undeclared_request_tag", "requestTag must name an owned process and canonical signed64 issuance ID")
            if tag in run.used_tags:
                raise ServerError(409, "duplicate_request_tag", "requestTag has already been used in this run")
            held_count = sum(1 for item in run.pending.values() if item["status"] == "held")
            if held_count >= MAX_PENDING_PER_RUN:
                raise ServerError(429, "pending_capacity", "the per-run held-request capacity is full")
            pending = PendingRequest(sanitized)
            run.pending[tag] = {"status": "held", "pending": pending}
            run.used_tags.add(tag)
            sequence = self._record(run, "requestHeld", requestTag=tag, requestId=request["requestId"])
            if isinstance(digest, str):
                run.body_digests.append({"sequence": sequence, "sha256": digest})
            return pending

    def release(self, run_id: str, request_tag: str, outcome: dict) -> dict:
        if not isinstance(request_tag, str) or not isinstance(outcome, dict):
            raise ServerError(400, "invalid_release", "release requires a requestTag and outcome object")
        normalized = self._validate_outcome(outcome)
        with self._lock:
            run = self._run(run_id)
            entry = run.pending.get(request_tag)
            if entry is None or entry["status"] != "held":
                raise ServerError(409, "release_conflict", "request is unknown or has already been released")
            entry["status"] = "releaseAccepted"
            entry["outcome"] = normalized
            pending = entry["pending"]
            self._record(run, "releaseAccepted", requestTag=request_tag, outcome=normalized["outcome"])
        pending.resolve(normalized)
        return {"version": 1, "requestTag": request_tag, "status": "releaseAccepted"}

    def expire(self, run_id: str, request_tag: str) -> dict:
        """Atomically time out a held response or return a racing release."""
        pending_to_resolve = None
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.closed:
                return {"kind": "closed"}
            entry = run.pending.get(request_tag)
            if entry is None:
                return {"kind": "closed"}
            if entry["status"] == "releaseAccepted":
                return deepcopy(entry["outcome"])
            if entry["status"] == "timedOut":
                return {"kind": "timeout"}
            if entry["status"] != "held":
                return {"kind": "closed"}
            entry["status"] = "timedOut"
            pending_to_resolve = entry["pending"]
            self._record(run, "disconnected", requestTag=request_tag, outcome="timeout")
        pending_to_resolve.resolve({"kind": "timeout"})
        return {"kind": "timeout"}

    @staticmethod
    def _validate_outcome(outcome: dict) -> dict:
        kind = outcome.get("outcome")
        if kind == "success" and set(outcome) == {"outcome", "credentialVersion"}:
            version = outcome["credentialVersion"]
            if type(version) is int and 0 <= version <= MAX_SIGNED64:
                return {"outcome": kind, "credentialVersion": version}
        elif kind == "failure" and set(outcome) == {"outcome", "failure"} and outcome.get("failure") == "rejected":
            return {"outcome": kind, "failure": "rejected"}
        elif kind in {"http500", "malformed", "disconnect"} and set(outcome) == {"outcome"}:
            return {"outcome": kind}
        elif kind == "wrongCorrelation" and set(outcome) == {"outcome", "credentialVersion"}:
            version = outcome["credentialVersion"]
            if type(version) is int and 0 <= version <= MAX_SIGNED64:
                return {"outcome": kind, "credentialVersion": version}
        raise ServerError(400, "invalid_outcome", "release outcome is outside the frozen response envelope")

    def pending(self, run_id: str) -> list[dict]:
        with self._lock:
            run = self._run(run_id)
            return [
                {"requestTag": tag, "requestId": entry["pending"].request["requestId"], "status": "held"}
                for tag, entry in run.pending.items()
                if entry["status"] == "held"
            ]

    def events(self, run_id: str) -> list[dict]:
        with self._lock:
            return deepcopy(self._run(run_id).event_rows)

    def body_digests(self, run_id: str) -> list[dict]:
        with self._lock:
            return deepcopy(self._run(run_id).body_digests)

    def response_written(self, run_id: str, request_tag: str, outcome: str):
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and not run.closed:
                self._record(run, "responseWritten", requestTag=request_tag, outcome=outcome)

    def disconnected(self, run_id: str, request_tag: str, outcome: str = "disconnect"):
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and not run.closed:
                self._record(run, "disconnected", requestTag=request_tag, outcome=outcome)

    def fault_response(self, run_id: str, request_tag: str, kind: str, *, echoed_request_tag: str | None = None):
        if kind not in {"http500", "malformed", "wrongCorrelation"}:
            raise ValueError("invalid fault response event")
        if kind == "wrongCorrelation" and (
            not isinstance(echoed_request_tag, str) or not echoed_request_tag or echoed_request_tag == request_tag
        ):
            raise ValueError("wrongCorrelation requires a distinct echoed requestTag")
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and not run.closed:
                if kind == "wrongCorrelation":
                    self._record(run, kind, requestTag=request_tag, echoedRequestTag=echoed_request_tag)
                else:
                    self._record(run, kind, requestTag=request_tag)

    def close_run(self, run_id: str) -> dict:
        with self._lock:
            run = self._run(run_id)
            run.closed = True
            pending = [entry["pending"] for entry in run.pending.values() if entry["status"] == "held"]
            del self._runs[run_id]
        for request in pending:
            request.resolve({"kind": "closed"})
        return {"version": 1, "runId": run_id, "status": "closed"}

    def publish_checkpoint(self, run_id: str, process_id: str, name: str) -> dict:
        with self._lock:
            run = self._run(run_id)
            key = self._checkpoint_key(run, process_id, name)
            if key not in run.checkpoints:
                if len(run.checkpoints) >= MAX_CHECKPOINTS_PER_RUN:
                    raise ServerError(429, "checkpoint_capacity", "the per-run checkpoint capacity is full")
                run.checkpoints.add(key)
                self._record(run, "checkpointPublished", processInstanceId=process_id, name=name)
            return {"version": 1, "ready": True}

    def checkpoint_ready(self, run_id: str, process_id: str, name: str) -> dict:
        with self._lock:
            run = self._run(run_id)
            key = self._checkpoint_key(run, process_id, name)
            return {"version": 1, "ready": key in run.checkpoints}

    @staticmethod
    def _checkpoint_key(run: _Run, process_id: str, name: str) -> tuple[str, str]:
        if not isinstance(process_id, str) or process_id not in run.process_ids:
            raise ServerError(400, "undeclared_process", "processInstanceId is not declared for this run")
        if not isinstance(name, str) or name not in run.checkpoint_names:
            raise ServerError(400, "undeclared_checkpoint", "checkpoint name is not declared in the frozen inventory")
        return process_id, name

    @staticmethod
    def _record(run: _Run, kind: str, **fields) -> int:
        sequence = run.next_sequence
        run.next_sequence += 1
        run.event_rows.append({"runId": run.run_id, "sequence": sequence, "kind": kind, **fields})
        return sequence
