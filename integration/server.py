"""Real loopback HTTP server with an explicit test-only release control plane."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from integration.server_state import HOLD_SECONDS, ServerError, ServerState
from integration.wire import MAX_BODY_BYTES, WireError, parse_json_object, parse_refresh


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Leave room for eight held data connections plus concurrent control-plane
    # polls/releases; TCPServer's default accept backlog is only five.
    request_queue_size = 64

    def __init__(self, address, handler, state, output, hold_timeout_seconds):
        self.server_state = state
        self.output = Path(output)
        self.ready = True
        self.server_pid = os.getpid()
        self.hold_timeout_seconds = hold_timeout_seconds
        super().__init__(address, handler)

    def server_bind(self):
        # HTTPServer.server_bind resolves socket.getfqdn(host) only to fill
        # server_name, which nothing here reads. A slow resolver turns that
        # reverse lookup of the loopback address into a startup stall.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def _bind_address_is_explicitly_safe(bind: str) -> bool:
    if bind == "localhost":
        return True
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        return False
    return address.is_loopback or (address.is_private and not address.is_unspecified and not address.is_link_local and not address.is_multicast)


def _write_ready_file(server: _Server):
    server.output.mkdir(parents=True, exist_ok=True)
    actual_bind = server.server_address[0]
    document = {
        "version": 1,
        "bindAddress": actual_bind,
        "port": server.server_address[1],
        "pid": server.server_pid,
    }
    target = server.output / "server-ready.json"
    temporary = server.output / f".server-ready.{server.server_pid}.tmp"
    temporary.write_text(json.dumps(document, sort_keys=True) + "\n")
    os.replace(temporary, target)
    server.ready_document = document


def _validate_version_one(value, expected):
    if not isinstance(value, dict) or set(value) != expected or type(value.get("version")) is not int or value["version"] != 1:
        raise WireError(400, "invalid_envelope", "request does not match the exact version-1 envelope")


def _valid_release(body):
    if type(body.get("version")) is not int or body["version"] != 1 or not isinstance(body.get("requestTag"), str):
        raise WireError(400, "invalid_release", "release requires version 1 and requestTag")
    kind = body.get("outcome")
    if kind == "success":
        _validate_version_one(body, {"version", "requestTag", "outcome", "credentialVersion"})
        version = body["credentialVersion"]
        if type(version) is not int or not 0 <= version <= (1 << 63) - 1:
            raise WireError(400, "invalid_release", "credentialVersion must be a nonnegative signed64 integer")
        return body["requestTag"], {"outcome": kind, "credentialVersion": version}
    if kind == "failure":
        _validate_version_one(body, {"version", "requestTag", "outcome", "failure"})
        if body["failure"] != "rejected":
            raise WireError(400, "invalid_release", "failure must use the canonical rejected code")
        return body["requestTag"], {"outcome": kind, "failure": "rejected"}
    if kind == "wrongCorrelation":
        _validate_version_one(body, {"version", "requestTag", "outcome", "credentialVersion"})
        version = body["credentialVersion"]
        if type(version) is not int or not 0 <= version <= (1 << 63) - 1:
            raise WireError(400, "invalid_release", "credentialVersion must be a nonnegative signed64 integer")
        return body["requestTag"], {"outcome": kind, "credentialVersion": version}
    if kind in {"http500", "malformed", "disconnect"}:
        _validate_version_one(body, {"version", "requestTag", "outcome"})
        return body["requestTag"], {"outcome": kind}
    raise WireError(400, "invalid_release", "release outcome is outside the frozen set")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def state(self):
        return self.server.server_state

    def log_message(self, fmt, *args):
        # Requests contain synthetic credentials and test capabilities. The
        # event API records only references and SHA-256 body digests.
        return

    def _send_bytes(self, status, body: bytes, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_json(self, status, document):
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._send_bytes(status, payload)

    def _error(self, status, code):
        try:
            self._send_json(status, {"version": 1, "error": code})
        except OSError:
            self.close_connection = True

    def _read_body(self):
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not re.fullmatch(r"[0-9]+", raw_length):
            raise WireError(400, "invalid_content_length", "Content-Length is required")
        if len(raw_length) > 8:
            self.close_connection = True
            raise WireError(413, "body_too_large", "request body exceeds 16 KiB")
        length = int(raw_length)
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise WireError(413, "body_too_large", "request body exceeds 16 KiB")
        body = self.rfile.read(length)
        if len(body) != length:
            raise WireError(400, "truncated_body", "request body ended before Content-Length")
        return body

    def _control_key(self):
        return self.headers.get("X-Demo-Control-Key", "")

    def _authorize(self, run_id):
        self.state.authenticate(run_id, self._control_key())

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/health" and not parsed.query:
            self._send_json(200, {"version": 1, "ready": bool(self.server.ready)})
            return
        if path == "/v1/checkpoints":
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                if set(query) != {"runId", "processInstanceId", "name"} or any(len(values) != 1 for values in query.values()):
                    raise ServerError(400, "invalid_query", "checkpoint query requires runId, processInstanceId and name exactly once")
                result = self.state.checkpoint_ready(query["runId"][0], query["processInstanceId"][0], query["name"][0])
                self._send_json(200, result)
            except ServerError as exc:
                self._error(exc.status, exc.code)
            except ValueError:
                self._error(400, "invalid_query")
            return

        match = re.fullmatch(r"/control/runs/([A-Za-z0-9_-]+)/(?P<action>pending|events)", path)
        if match:
            run_id, action = match.group(1), match.group("action")
            try:
                self._authorize(run_id)
                if action == "pending":
                    result = {"version": 1, "runId": run_id, "pending": self.state.pending(run_id)}
                else:
                    result = {
                        "version": 1,
                        "runId": run_id,
                        "events": self.state.events(run_id),
                        "bodyDigests": self.state.body_digests(run_id),
                    }
                self._send_json(200, result)
            except ServerError as exc:
                self._error(exc.status, exc.code)
            return
        self._error(404, "not_found")

    def do_POST(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        if parsed.query:
            self._error(400, "unexpected_query")
            return
        try:
            body_bytes = self._read_body()
            if path == "/control/runs":
                body = parse_json_object(body_bytes)
                _validate_version_one(body, {"version", "attemptId", "scenarioId", "platform"})
                result = self.state.create_run(body["scenarioId"], body["platform"], body["attemptId"])
                self._send_json(200, result)
                return
            if path == "/v1/refresh":
                request = parse_refresh(body_bytes)
                request["_bodyDigest"] = hashlib.sha256(body_bytes).hexdigest()
                pending = self.state.hold(request)
                outcome = pending.wait(self.server.hold_timeout_seconds)
                if outcome.get("kind") == "closed":
                    self._send_json(410, {"version": 1, "runId": request["runId"], "requestTag": request["requestTag"], "failure": "runClosed"})
                    return
                if outcome.get("kind") == "timeout":
                    outcome = self.state.expire(request["runId"], request["requestTag"])
                if outcome.get("kind") == "closed":
                    self._send_json(410, {"version": 1, "runId": request["runId"], "requestTag": request["requestTag"], "failure": "runClosed"})
                    return
                if outcome.get("kind") == "timeout":
                    try:
                        self._send_json(504, {"version": 1, "runId": request["runId"], "requestTag": request["requestTag"], "failure": "timeout"})
                        self.state.response_written(request["runId"], request["requestTag"], "failure")
                    except OSError:
                        self.state.disconnected(request["runId"], request["requestTag"], "writeFailed")
                        self.close_connection = True
                    return
                kind = outcome["outcome"]
                if kind == "disconnect":
                    self.state.disconnected(request["runId"], request["requestTag"], "disconnect")
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
                if kind == "success":
                    version = outcome["credentialVersion"]
                    token = f"demo-{request['account']}-v{version}"
                    response = {
                        "version": 1,
                        "runId": request["runId"],
                        "requestTag": request["requestTag"],
                        "outcome": "success",
                        "credential": {"account": request["account"], "version": version, "accessToken": token, "refreshToken": token},
                    }
                    status = 200
                    response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
                elif kind == "failure":
                    response = {"version": 1, "runId": request["runId"], "requestTag": request["requestTag"], "outcome": "failure", "failure": outcome["failure"]}
                    status = 401
                    response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
                elif kind == "wrongCorrelation":
                    version = outcome["credentialVersion"]
                    token = f"demo-{request['account']}-v{version}"
                    echoed_tag = request["requestTag"] + ":wrong-correlation"
                    response = {
                        "version": 1,
                        "runId": request["runId"],
                        "requestTag": echoed_tag,
                        "outcome": "success",
                        "credential": {"account": request["account"], "version": version, "accessToken": token, "refreshToken": token},
                    }
                    status = 200
                    response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
                    self.state.fault_response(
                        request["runId"], request["requestTag"], "wrongCorrelation", echoed_request_tag=echoed_tag
                    )
                elif kind == "http500":
                    response = {"version": 1, "runId": request["runId"], "requestTag": request["requestTag"], "outcome": "failure", "failure": "server"}
                    status = 500
                    response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
                    self.state.fault_response(request["runId"], request["requestTag"], "http500")
                elif kind == "malformed":
                    status = 200
                    response_body = b'{"version":1,"outcome":'
                    self.state.fault_response(request["runId"], request["requestTag"], "malformed")
                else:
                    self._error(400, "invalid_outcome")
                    return
                try:
                    self._send_bytes(status, response_body)
                    self.state.response_written(
                        request["runId"],
                        request["requestTag"],
                        "success" if kind == "success" else "failure",
                    )
                except OSError:
                    self.state.disconnected(request["runId"], request["requestTag"], "writeFailed")
                    self.close_connection = True
                return

            checkpoint_match = re.fullmatch(r"/control/runs/([A-Za-z0-9_-]+)/checkpoints", path)
            release_match = re.fullmatch(r"/control/runs/([A-Za-z0-9_-]+)/release", path)
            if checkpoint_match or release_match:
                run_id = (checkpoint_match or release_match).group(1)
                self._authorize(run_id)
                body = parse_json_object(body_bytes)
                if checkpoint_match:
                    _validate_version_one(body, {"version", "processInstanceId", "name"})
                    result = self.state.publish_checkpoint(run_id, body["processInstanceId"], body["name"])
                else:
                    request_tag, outcome = _valid_release(body)
                    result = self.state.release(run_id, request_tag, outcome)
                self._send_json(200, result)
                return
            self._error(404, "not_found")
        except WireError as exc:
            self._error(exc.status, exc.code)
        except ServerError as exc:
            self._error(exc.status, exc.code)
        except (KeyError, TypeError):
            self._error(400, "invalid_envelope")

    def do_DELETE(self):
        parsed = urlsplit(self.path)
        if parsed.query:
            self._error(400, "unexpected_query")
            return
        match = re.fullmatch(r"/control/runs/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            self._error(404, "not_found")
            return
        run_id = match.group(1)
        try:
            self._authorize(run_id)
            result = self.state.close_run(run_id)
            self._send_json(200, result)
        except ServerError as exc:
            self._error(exc.status, exc.code)


def start_server(bind="127.0.0.1", port=0, output=".", *, state=None, hold_timeout_seconds=HOLD_SECONDS):
    if not _bind_address_is_explicitly_safe(bind):
        raise ValueError("bind must be loopback or an explicitly supplied private LAN address")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an integer in 0..65535")
    if isinstance(hold_timeout_seconds, bool) or not isinstance(hold_timeout_seconds, (int, float)) or not math.isfinite(hold_timeout_seconds) or hold_timeout_seconds <= 0:
        raise ValueError("hold_timeout_seconds must be positive and finite")
    state = state or ServerState()
    server = _Server((bind, port), _Handler, state, output, float(hold_timeout_seconds))
    _write_ready_file(server)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        server = start_server(args.bind, args.port, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(server.ready_document, sort_keys=True), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
