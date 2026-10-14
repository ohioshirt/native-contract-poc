import http.client
import hashlib
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from integration.server import start_server
from integration.server_state import ServerState


class ServerStartupTests(unittest.TestCase):
    def test_startup_never_resolves_the_bind_address(self):
        refuse = AssertionError("startup must not reverse-resolve the bind address")
        with tempfile.TemporaryDirectory() as output, patch(
            "socket.getfqdn", side_effect=refuse
        ) as getfqdn, patch("socket.gethostbyaddr", side_effect=refuse) as gethostbyaddr:
            server = start_server("127.0.0.1", 0, Path(output))
            try:
                ready = json.loads((Path(output) / "server-ready.json").read_text())
            finally:
                server.server_close()

        getfqdn.assert_not_called()
        gethostbyaddr.assert_not_called()
        self.assertEqual(ready["bindAddress"], "127.0.0.1")
        self.assertEqual(ready["port"], server.server_address[1])
        self.assertEqual((server.server_name, server.server_port), ("127.0.0.1", server.server_address[1]))


class ControllableHttpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tempfile.TemporaryDirectory()
        cls.server = start_server("127.0.0.1", 0, Path(cls.output.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.server.server_address[:2]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.output.cleanup()

    def setUp(self):
        self.run_id = None
        self.control_key = None
        self.create_run()

    def tearDown(self):
        if self.run_id:
            self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())

    def call(self, method, path, value=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        request_headers = dict(headers or {})
        body = raw
        if value is not None:
            body = json.dumps(value, separators=(",", ":")).encode()
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            data = response.read()
            try:
                document = json.loads(data) if data else None
            except json.JSONDecodeError:
                document = None
            return response.status, document, data
        finally:
            connection.close()

    def create_run(self, *, scenario="APP-02", attempt="attempt-01"):
        status, response, _ = self.call(
            "POST",
            "/control/runs",
            {"version": 1, "attemptId": attempt, "scenarioId": scenario, "platform": "ios"},
        )
        self.assertEqual(status, 200)
        self.run_id = response["runId"]
        self.control_key = response["controlKey"]
        return response

    def key_headers(self, value=None):
        return {"X-Demo-Control-Key": self.control_key if value is None else value}

    def refresh(self, tag="attempt-01/APP-02/p1:refresh:3", request_id="1", **overrides):
        body = {
            "version": 1,
            "runId": self.run_id,
            "requestTag": tag,
            "requestId": request_id,
            "account": "A",
            "refreshToken": "demo-A-v0",
        }
        body.update(overrides)
        return body

    def pending(self, *, count=1, run_id=None):
        deadline = time.monotonic() + 4
        path = f"/control/runs/{run_id or self.run_id}/pending"
        observed = []
        while time.monotonic() < deadline:
            status, document, _ = self.call("GET", path, headers=self.key_headers())
            self.assertEqual(status, 200)
            observed = document["pending"]
            if len(observed) >= count:
                return observed
            # The pending endpoint is the ordering barrier; this short wait only
            # yields between bounded polls and is not used as proof of arrival.
            threading.Event().wait(0.01)
        _, event_document, _ = self.call("GET", f"/control/runs/{run_id or self.run_id}/events", headers=self.key_headers())
        self.fail(f"server did not report {count} held requests before the deadline; pending={observed}; events={event_document['events']}")

    def start_refresh(self, value):
        result = queue.Queue()

        def send():
            try:
                result.put(self.call("POST", "/v1/refresh", value))
            except BaseException as exc:
                result.put(exc)

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        return thread, result

    def wait_result(self, result):
        return result.get(timeout=5)

    def release(self, request_tag, outcome="success", **fields):
        body = {"version": 1, "requestTag": request_tag, "outcome": outcome, **fields}
        return self.call("POST", f"/control/runs/{self.run_id}/release", body, headers=self.key_headers())

    def replace_run(self, attempt):
        if self.run_id:
            self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
            self.run_id = None
        return self.create_run(attempt=attempt)

    def checkpoint(self, process_id, name="bootstrapStoreProbed", *, key=None):
        body = {"version": 1, "processInstanceId": process_id, "name": name}
        return self.call(
            "POST",
            f"/control/runs/{self.run_id}/checkpoints",
            body,
            headers=self.key_headers(key),
        )

    def checkpoint_get(self, process_id, name="bootstrapStoreProbed", *, run_id=None):
        query = urlencode({"runId": run_id or self.run_id, "processInstanceId": process_id, "name": name})
        return self.call("GET", f"/v1/checkpoints?{query}")

    def test_request_is_held_until_explicit_release(self):
        request_tag = "attempt-01/APP-02/p1:refresh:3"
        thread, result = self.start_refresh(self.refresh(request_tag))

        held = self.pending()[0]
        self.assertEqual(held["requestTag"], request_tag)
        self.assertEqual(held["status"], "held")
        self.assertTrue(thread.is_alive())
        self.assertTrue(result.empty(), "held request returned bytes before an explicit release")

        status, response, _ = self.release(request_tag, credentialVersion=1)
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "releaseAccepted")
        client_status, body, _ = self.wait_result(result)
        thread.join(timeout=1)
        self.assertEqual(client_status, 200)
        self.assertEqual(body["requestTag"], request_tag)
        self.assertEqual(body["credential"], {"account": "A", "version": 1, "accessToken": "demo-A-v1", "refreshToken": "demo-A-v1"})

        status, event_document, raw = self.call("GET", f"/control/runs/{self.run_id}/events", headers=self.key_headers())
        self.assertEqual(status, 200)
        held_event = next(event for event in event_document["events"] if event["kind"] == "requestHeld")
        self.assertEqual(set(held_event), {"runId", "sequence", "kind", "requestTag", "requestId"})
        self.assertEqual([event["sequence"] for event in event_document["events"]], [1, 2, 3])
        self.assertEqual(len(event_document["bodyDigests"]), 1)
        digest = event_document["bodyDigests"][0]
        self.assertEqual(digest["sequence"], held_event["sequence"])
        body = json.dumps(self.refresh(request_tag), separators=(",", ":")).encode()
        self.assertEqual(digest["sha256"], hashlib.sha256(body).hexdigest())
        self.assertNotIn(b"demo-A-v0", raw)
        self.assertNotIn(self.control_key.encode(), raw)

    def test_release_is_single_use_409(self):
        request_tag = "attempt-01/APP-02/p1:refresh:3"
        thread, result = self.start_refresh(self.refresh(request_tag))
        self.pending()

        self.assertEqual(self.release(request_tag, credentialVersion=1)[0], 200)
        self.assertEqual(self.release(request_tag, credentialVersion=1)[0], 409)
        client_status, _, _ = self.wait_result(result)
        thread.join(timeout=1)
        self.assertEqual(client_status, 200)

    def test_failure_and_disconnect_outcomes(self):
        for index, (attempt, outcome, expected_status) in enumerate((
            ("attempt-01", "failure", 401),
            ("attempt-http500", "http500", 500),
            ("attempt-malformed", "malformed", 200),
            ("attempt-disconnect", "disconnect", None),
        )):
            if index:
                self.replace_run(attempt)
            request_tag = f"{attempt}/APP-02/p1:refresh:3"
            thread, result = self.start_refresh(self.refresh(request_tag))
            self.pending()
            release_fields = {"failure": "rejected"} if outcome == "failure" else {}
            self.assertEqual(self.release(request_tag, outcome, **release_fields)[0], 200)
            response = self.wait_result(result)
            thread.join(timeout=1)

            if outcome == "disconnect":
                self.assertIsInstance(response, BaseException)
            else:
                status, body, raw = response
                self.assertEqual(status, expected_status)
                if outcome == "failure":
                    self.assertEqual(body["failure"], "rejected")
                elif outcome == "http500":
                    self.assertEqual(body["failure"], "server")
                else:
                    self.assertIsNone(body)
                    self.assertEqual(raw, b'{"version":1,"outcome":')

            status, event_document, _ = self.call("GET", f"/control/runs/{self.run_id}/events", headers=self.key_headers())
            self.assertEqual(status, 200)
            events = event_document["events"]
            if outcome in {"http500", "malformed"}:
                fault_index = next(i for i, event in enumerate(events) if event["kind"] == outcome)
                self.assertEqual(events[fault_index + 1], {
                    "runId": self.run_id,
                    "sequence": events[fault_index]["sequence"] + 1,
                    "kind": "responseWritten",
                    "requestTag": request_tag,
                    "outcome": "failure",
                })
            if outcome == "failure":
                self.assertEqual(events[-1]["kind"], "responseWritten")
                self.assertEqual(events[-1]["outcome"], "failure")
            if outcome == "disconnect":
                self.assertEqual(events[-1]["kind"], "disconnected")

    def test_wrong_correlation_writes_valid_success_payload_with_wrong_echo(self):
        request_tag = "attempt-01/APP-02/p1:refresh:3"
        thread, result = self.start_refresh(self.refresh(request_tag))
        self.pending()

        status, _, _ = self.release(request_tag, "wrongCorrelation", credentialVersion=1)
        self.assertEqual(status, 200)
        client_status, body, _ = self.wait_result(result)
        thread.join(timeout=1)
        self.assertEqual(client_status, 200)
        self.assertEqual(body["outcome"], "success")
        self.assertEqual(body["runId"], self.run_id)
        self.assertNotEqual(body["requestTag"], request_tag)
        self.assertEqual(body["credential"], {
            "account": "A", "version": 1, "accessToken": "demo-A-v1", "refreshToken": "demo-A-v1",
        })

        events = self.call("GET", f"/control/runs/{self.run_id}/events", headers=self.key_headers())[1]["events"]
        self.assertEqual([event["kind"] for event in events], [
            "requestHeld", "releaseAccepted", "wrongCorrelation", "responseWritten",
        ])
        self.assertEqual(events[2]["requestTag"], request_tag)
        self.assertEqual(events[2]["echoedRequestTag"], body["requestTag"])
        self.assertNotEqual(events[2]["echoedRequestTag"], events[2]["requestTag"])
        self.assertEqual(events[3]["outcome"], "failure")

    def test_hold_timeout_is_terminal_and_rejects_late_release(self):
        old_server, old_host, old_port = self.server, self.host, self.port
        old_run_id, old_key = self.run_id, self.control_key
        self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
        self.run_id = None
        short_output = tempfile.TemporaryDirectory()
        short_server = start_server("127.0.0.1", 0, Path(short_output.name), hold_timeout_seconds=0.05)
        short_thread = threading.Thread(target=short_server.serve_forever, daemon=True)
        short_thread.start()
        self.server = short_server
        self.host, self.port = short_server.server_address[:2]
        try:
            self.create_run()
            request_tag = "attempt-01/APP-02/p1:refresh:3"
            request_thread, result = self.start_refresh(self.refresh(request_tag))
            self.pending()

            status, body, _ = self.wait_result(result)
            request_thread.join(timeout=1)
            self.assertEqual(status, 504)
            self.assertEqual(body["failure"], "timeout")
            self.assertEqual(self.pending(count=0), [])
            self.assertEqual(self.release(request_tag, credentialVersion=1)[0], 409)

            events = self.call("GET", f"/control/runs/{self.run_id}/events", headers=self.key_headers())[1]["events"]
            timeout_index = next(index for index, event in enumerate(events) if event["kind"] == "disconnected")
            self.assertEqual(events[timeout_index]["outcome"], "timeout")
            self.assertEqual(events[timeout_index + 1]["kind"], "responseWritten")
            self.assertEqual(events[timeout_index + 1]["outcome"], "failure")
        finally:
            if self.run_id:
                self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
                self.run_id = None
            short_server.shutdown()
            short_server.server_close()
            short_thread.join(timeout=2)
            short_output.cleanup()
            self.server, self.host, self.port = old_server, old_host, old_port
            self.run_id, self.control_key = None, old_key

    def test_manual_canonical_issuance_id_is_allowed_for_owned_process(self):
        tag = "attempt-01/APP-02/p1:refresh:999"
        thread, result = self.start_refresh(self.refresh(tag, "1"))
        try:
            held = self.pending(count=1)[0]
            self.assertEqual(held["requestTag"], tag)
            self.assertEqual(self.release(tag, credentialVersion=1)[0], 200)
            status, body, _ = self.wait_result(result)
            thread.join(timeout=1)
            self.assertEqual(status, 200)
            self.assertEqual(body["requestTag"], tag)
        finally:
            if thread.is_alive():
                self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
                thread.join(timeout=1)

    def test_request_tag_requires_owned_process_and_canonical_positive_signed64_id(self):
        tags = (
            "other-attempt/APP-02/p1:refresh:3",
            "attempt-01/OTHER-SCENARIO/p1:refresh:3",
            "attempt-01/APP-02/p2:refresh:3",
            "attempt-01/APP-02/p1:refresh:0",
            "attempt-01/APP-02/p1:refresh:04",
            "attempt-01/APP-02/p1:refresh:9223372036854775808",
        )
        for index, tag in enumerate(tags):
            with self.subTest(tag=tag):
                thread, result = self.start_refresh(self.refresh(tag))
                try:
                    response = result.get(timeout=1)
                    self.assertEqual(response[0], 400)
                    self.assertEqual(response[1]["error"], "undeclared_request_tag")
                except queue.Empty:
                    status, pending, _ = self.call("GET", f"/control/runs/{self.run_id}/pending", headers=self.key_headers())
                    self.assertEqual(status, 200)
                    self.fail(f"invalid request tag was held as a valid request: {pending['pending']}")
                finally:
                    self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
                    self.run_id = None
                    thread.join(timeout=1)
                    if index + 1 < len(tags):
                        self.create_run()

    def test_limits_413_and_capacity_429(self):
        oversized = json.dumps(self.refresh(padding="x" * (16 * 1024))).encode()
        self.assertEqual(self.call("POST", "/v1/refresh", raw=oversized)[0], 413)

        old_server, old_host, old_port = self.server, self.host, self.port
        old_key = self.control_key
        self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
        self.run_id = None
        capacity_output = tempfile.TemporaryDirectory()
        scenarios_path = Path(capacity_output.name) / "scenarios.json"
        scenarios_path.write_text(json.dumps({"version": 1, "scenarios": [{
            "id": "CAPACITY",
            "platforms": ["ios"],
            "launches": [{"ordinal": 1, "commands": ["Expire"] * 9}],
            "requiredProbes": [],
        }]}))
        controls_path = Path(__file__).resolve().parents[1] / "control-scenarios.json"
        capacity_state = ServerState(scenarios_path=scenarios_path, controls_path=controls_path)
        capacity_server = start_server("127.0.0.1", 0, Path(capacity_output.name), state=capacity_state)
        capacity_thread = threading.Thread(target=capacity_server.serve_forever, daemon=True)
        capacity_thread.start()
        self.server = capacity_server
        self.host, self.port = capacity_server.server_address[:2]
        requests = []
        try:
            self.create_run(scenario="CAPACITY", attempt="attempt-cap")
            for index in range(1, 9):
                tag = f"attempt-cap/CAPACITY/p1:refresh:{index}"
                body = self.refresh(tag, str(index))
                requests.append(self.start_refresh(body))
                self.pending(count=index)
            ninth_tag = "attempt-cap/CAPACITY/p1:refresh:9"
            status, _, _ = self.call("POST", "/v1/refresh", self.refresh(ninth_tag, "9"))
            self.assertEqual(status, 429)

            self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
            self.run_id = None
            for thread, result in requests:
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertIsNotNone(self.wait_result(result))
        finally:
            if self.run_id:
                self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
                self.run_id = None
            capacity_server.shutdown()
            capacity_server.server_close()
            capacity_thread.join(timeout=2)
            capacity_output.cleanup()
            self.server, self.host, self.port = old_server, old_host, old_port
            self.control_key = old_key

    def test_wrong_control_key_403(self):
        status, _, _ = self.call("GET", f"/control/runs/{self.run_id}/pending", headers=self.key_headers("wrong-key"))
        self.assertEqual(status, 403)

    def test_close_run_unblocks_held_clients(self):
        request_tag = "attempt-01/APP-02/p1:refresh:3"
        thread, result = self.start_refresh(self.refresh(request_tag))
        self.pending()

        status, _, _ = self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
        self.assertEqual(status, 200)
        self.run_id = None
        client_status, body, _ = self.wait_result(result)
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(client_status, 410)
        self.assertEqual(body["failure"], "runClosed")

    def test_ephemeral_port_ready_metadata_matches_listener(self):
        ready_path = Path(self.output.name) / "server-ready.json"
        ready = json.loads(ready_path.read_text())

        self.assertEqual(set(ready), {"version", "bindAddress", "port", "pid"})
        self.assertEqual(ready["version"], 1)
        self.assertEqual(ready["bindAddress"], self.host)
        self.assertEqual(ready["port"], self.port)
        self.assertEqual(ready["pid"], self.server.server_pid)
        status, health, _ = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(set(health), {"version", "ready"})

    def test_checkpoint_is_process_scoped_and_cleared_with_run(self):
        self.call("DELETE", f"/control/runs/{self.run_id}", headers=self.key_headers())
        run = self.create_run(scenario="APP-12-SAVED", attempt="attempt-checkpoint")
        first = "attempt-checkpoint/APP-12-SAVED/p1"
        second = "attempt-checkpoint/APP-12-SAVED/p2"

        status, response, _ = self.checkpoint(first)
        self.assertEqual(status, 200)
        self.assertTrue(response["ready"])
        self.assertEqual(self.checkpoint(first)[0], 200)
        self.assertEqual(self.checkpoint_get(first)[1]["ready"], True)
        self.assertEqual(self.checkpoint_get(second)[1]["ready"], False)

        events = self.call("GET", f"/control/runs/{run['runId']}/events", headers=self.key_headers())
        checkpoints = [event for event in events[1]["events"] if event["kind"] == "checkpointPublished"]
        self.assertEqual(len(checkpoints), 1, "same checkpoint POST is idempotent")
        self.assertEqual(self.call("DELETE", f"/control/runs/{run['runId']}", headers=self.key_headers())[0], 200)
        self.run_id = None
        self.assertEqual(self.checkpoint_get(first, run_id=run["runId"])[0], 404)

    def test_checkpoint_publish_requires_control_key(self):
        process_id = "attempt-01/APP-02/p1"
        self.assertEqual(self.checkpoint(process_id, key="invalid")[0], 403)
        body = {"version": 1, "processInstanceId": process_id, "name": "bootstrapStoreProbed"}
        status, _, _ = self.call("POST", f"/control/runs/{self.run_id}/checkpoints", body)
        self.assertEqual(status, 403)

    def test_unknown_checkpoint_rejected(self):
        process_id = "attempt-01/APP-02/p1"
        self.assertEqual(self.checkpoint(process_id, "unknownStep")[0], 400)
        self.assertEqual(self.checkpoint("other-attempt/APP-02/p1")[0], 400)

    def test_detached_effect_checkpoint_is_declared_only_for_its_frozen_control(self):
        self.create_run(scenario="CTRL-N2-LATE-CLEAR", attempt="attempt-effect-checkpoint")
        process_id = "attempt-effect-checkpoint/CTRL-N2-LATE-CLEAR/p1"
        accepted = self.checkpoint(process_id, "detachedEffectAwaited.late-clear-1")
        undeclared = self.checkpoint(process_id, "detachedEffectAwaited.other-effect")
        probe = self.checkpoint(process_id, "storeProbe.CTRL-N2-LATE-CLEAR-probe-b")

        self.assertEqual(accepted[0], 200)
        self.assertEqual(undeclared[0], 400)
        self.assertEqual(probe[0], 200)


if __name__ == "__main__":
    unittest.main()
