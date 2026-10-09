import copy
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from verification import async_contract, async_formal, async_verify
from verification.contract import validate

ROOT = Path(__file__).resolve().parents[1]
ASYNC_MUTATION_SPEC = importlib.util.spec_from_file_location("async_mutations", ROOT / "scripts/async_mutations.py")
async_mutations = importlib.util.module_from_spec(ASYNC_MUTATION_SPEC)
ASYNC_MUTATION_SPEC.loader.exec_module(async_mutations)


class AsyncContractTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "contract/specification.json").read_text())
        self.schema = json.loads((ROOT / "contract/schema.json").read_text())

    def test_async_profile_is_total_and_enumeration_has_expected_length(self):
        self.assertEqual(len(async_contract.validate(self.spec, self.schema)), 15)
        vectors = list(async_contract.exhaustive_scenarios(self.spec))
        self.assertEqual(len(vectors), 19608)
        self.assertEqual(len({len(row["events"]) for row in vectors}), 6)

    def test_async_semantics_reject_guard_and_action_mismatch(self):
        for key, value, expected in (("guard", "always", "guard"), ("pendingAction", "preserve", "pending action")):
            bad = copy.deepcopy(self.spec)
            row = next(r for r in bad["async"]["transitions"] if r["state"] == "Refreshing" and r["event"] == "RefreshSucceeded")
            row[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, expected):
                validate(bad, self.schema)

    def test_async_schema_rejects_bad_enums_and_bool_ids(self):
        bad = copy.deepcopy(self.spec)
        bad["async"]["logoutWhileRefreshing"] = "cancel"
        with self.assertRaisesRegex(ValueError, "schema"):
            validate(bad, self.schema)
        with self.assertRaisesRegex(ValueError, "positive signed64"):
            async_contract.validate_input({"scenarios": [{"scenario": "x", "nextRequestId": True, "events": []}]}, self.spec)
        with self.assertRaisesRegex(ValueError, "positive signed64"):
            async_contract.validate_input({"scenarios": [{"scenario": "x", "events": [{"event": "RefreshSucceeded", "requestId": 1.0}]}]}, self.spec)

    def test_oracle_ignores_stale_and_allocates_without_reuse(self):
        events = ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1},
                  "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1},
                  {"event": "RefreshSucceeded", "requestId": 2}]
        trace = async_contract.oracle("x", events, self.spec)
        self.assertEqual(trace["steps"][1]["pendingRequestId"], 1)
        self.assertEqual(trace["steps"][2]["state"], "Authenticated")
        self.assertEqual(trace["steps"][3]["pendingRequestId"], 2)
        self.assertEqual(trace["steps"][4]["state"], "Refreshing")
        self.assertEqual(trace["steps"][5]["state"], "Authenticated")

    def test_strict_comparator_includes_ids_and_shape(self):
        trace = async_contract.oracle("x", ["LoginSucceeded", "TokenExpired"], self.spec)
        self.assertEqual(async_contract.compare([trace], [copy.deepcopy(trace)]), [])
        altered = copy.deepcopy(trace)
        altered["steps"][1]["pendingRequestId"] = 2
        self.assertTrue(async_contract.compare([trace], [altered]))
        del altered["steps"][1]["rejection"]
        self.assertTrue(async_contract.validate_output({"traces": [altered]}, [trace]))

    def test_wire_event_ids_reject_bool_alias_of_integer(self):
        trace = async_contract.oracle("x", ["LoginSucceeded", "TokenExpired"], self.spec)
        expected = async_contract.oracle("x", ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}], self.spec)
        expected["steps"][2]["event"]["requestId"] = True
        self.assertTrue(async_contract.validate_output({"traces": [expected]}, [async_contract.oracle("x", ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}], self.spec)]))

    def test_named_vectors_cover_counter_reset_and_domain_exhaustion(self):
        rows = {row["scenario"]: row for row in async_contract.named_scenarios(self.spec)}
        self.assertIn("accepted-logout-counter-never-resets", rows)
        maximum = rows["allocate-signed64-maximum"]
        trace = async_contract.oracle(maximum["scenario"], maximum["events"], self.spec, maximum["nextRequestId"])
        self.assertEqual(trace["steps"][-1]["rejection"], "RequestIdExhausted")
        self.assertEqual(trace["steps"][-1]["state"], "Authenticated")

    def test_new_named_vectors_cover_logout_new_request_and_numeric_boundaries(self):
        named = {row["scenario"]: row for row in async_contract.named_scenarios(self.spec)}
        cases = (
            ("old-success-after-accepted-logout-with-new-request", "RefreshSucceeded", "Authenticated", []),
            ("old-failure-after-accepted-logout-with-new-request", "RefreshFailed", "Unauthenticated", [{"effect": "ClearCredentials"}]),
        )
        for scenario, final_event, final_state, final_effects in cases:
            row = named[scenario]
            trace = async_contract.oracle(row["scenario"], row["events"], self.spec, row.get("nextRequestId"))
            self.assertEqual(trace["steps"][5]["pendingRequestId"], 2)
            self.assertEqual(trace["steps"][6]["event"], {"event": final_event, "requestId": 1})
            self.assertEqual((trace["steps"][6]["state"], trace["steps"][6]["pendingRequestId"], trace["steps"][6]["effects"]),
                             ("Refreshing", 2, []))
            self.assertEqual((trace["steps"][7]["state"], trace["steps"][7]["effects"]), (final_state, final_effects))

        near_max = named["allocate-final-two-signed64-ids"]
        max_trace = async_contract.oracle(near_max["scenario"], near_max["events"], self.spec, near_max["nextRequestId"])
        allocated_ids = [step["effects"][0]["requestId"] for step in max_trace["steps"] if step["effects"]]
        self.assertEqual(allocated_ids, [async_contract.MAX_ID - 1, async_contract.MAX_ID])
        self.assertEqual(max_trace["steps"][-1]["rejection"], "RequestIdExhausted")

        precise = named["cross-json-safe-integer-boundary"]
        precise_trace = async_contract.oracle(precise["scenario"], precise["events"], self.spec, precise["nextRequestId"])
        exact_boundary = 2**53
        request_steps = [step for step in precise_trace["steps"] if step["effects"]]
        self.assertEqual([step["effects"][0]["requestId"] for step in request_steps], [exact_boundary - 1, exact_boundary])
        self.assertEqual(precise_trace["steps"][4]["event"], {"event": "RefreshSucceeded", "requestId": exact_boundary})

    def test_async_mutation_patch_sites_are_unique(self):
        matrix = json.loads((ROOT / "verification/async-mutation-matrix.json").read_text())
        self.assertEqual([row["expected"] for row in matrix["cases"]], [
            {"swift": "FAIL", "kotlin": "PASS", "differential": "FAIL"},
            {"swift": "PASS", "kotlin": "FAIL", "differential": "FAIL"},
            {"swift": "FAIL", "kotlin": "FAIL", "differential": "PASS"},
        ])
        for case in matrix["cases"]:
            for patch in case["patches"]:
                self.assertEqual((ROOT / patch["file"]).read_text().count(patch["before"]), 1, case["id"])


class AsyncFormalTraceTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "contract/specification.json").read_text())
        self.initial = {"state": "Unauthenticated", "pending": False, "previousState": "Unauthenticated",
                        "previousPending": False, "event": "__initial__", "responseClass": "NA",
                        "effects": (), "rejection": "__none__"}

    def test_stale_negative_requires_exact_injected_canonical_response_row(self):
        trace = [self.initial,
                 {"state": "Authenticated", "pending": False, "previousState": "Unauthenticated", "previousPending": False,
                  "event": "LoginSucceeded", "responseClass": "NA", "effects": (), "rejection": "__none__"},
                 {"state": "Refreshing", "pending": True, "previousState": "Authenticated", "previousPending": False,
                  "event": "TokenExpired", "responseClass": "NA", "effects": ("RequestTokenRefresh",), "rejection": "__none__"},
                 {"state": "Authenticated", "pending": False, "previousState": "Refreshing", "previousPending": True,
                  "event": "RefreshSucceeded", "responseClass": "STALE", "effects": (), "rejection": "__none__"}]
        self.assertTrue(async_formal.validate_trace(trace, self.spec, stale_fault=True))
        for field, value in (("state", "Unknown"), ("effects", ("BogusFX",)), ("rejection", "RequestIdExhausted")):
            forged = copy.deepcopy(trace)
            forged[-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                async_formal.validate_trace(forged, self.spec, stale_fault=True)
        legal_current = copy.deepcopy(trace)
        legal_current[-1]["responseClass"] = "CURRENT"
        self.assertTrue(async_formal.validate_trace(legal_current, self.spec))
        with self.assertRaises(ValueError): async_formal.validate_trace(legal_current, self.spec, stale_fault=True)
        self.assertTrue(async_formal.validate_trace([self.initial], self.spec))
        with self.assertRaises(ValueError): async_formal.validate_trace([self.initial], self.spec, stale_fault=True)
        stale_no_op = copy.deepcopy(trace)
        stale_no_op[-1].update({"state": "Refreshing", "pending": True, "effects": ()})
        self.assertTrue(async_formal.validate_trace(stale_no_op, self.spec))
        with self.assertRaises(ValueError): async_formal.validate_trace(stale_no_op, self.spec, stale_fault=True)

    def test_formal_trace_restricts_response_class_and_rejection_to_legal_rows(self):
        bogus = [self.initial, {"state": "Unauthenticated", "pending": False, "previousState": "Unauthenticated", "previousPending": False,
                               "event": "LoginSucceeded", "responseClass": "CURRENT", "effects": (), "rejection": "__none__"}]
        with self.assertRaises(ValueError): async_formal.validate_trace(bogus, self.spec)
        current_without_pending = [self.initial,
            {"state": "Authenticated", "pending": False, "previousState": "Unauthenticated", "previousPending": False,
             "event": "LoginSucceeded", "responseClass": "NA", "effects": (), "rejection": "__none__"},
            {"state": "Authenticated", "pending": False, "previousState": "Authenticated", "previousPending": False,
             "event": "RefreshSucceeded", "responseClass": "CURRENT", "effects": (), "rejection": "__none__"}]
        with self.assertRaises(ValueError): async_formal.validate_trace(current_without_pending, self.spec)
        stale_simple = copy.deepcopy(bogus)
        stale_simple[1]["responseClass"] = "STALE"
        with self.assertRaises(ValueError): async_formal.validate_trace(stale_simple, self.spec)
        rejected_logout = [self.initial, {"state": "Unauthenticated", "pending": False, "previousState": "Unauthenticated", "previousPending": False,
                                         "event": "Logout", "responseClass": "NA", "effects": (), "rejection": "RequestIdExhausted"}]
        with self.assertRaises(ValueError): async_formal.validate_trace(rejected_logout, self.spec)
        valid_rejection = [self.initial,
            {"state": "Authenticated", "pending": False, "previousState": "Unauthenticated", "previousPending": False,
             "event": "LoginSucceeded", "responseClass": "NA", "effects": (), "rejection": "__none__"},
            {"state": "Authenticated", "pending": False, "previousState": "Authenticated", "previousPending": False,
             "event": "TokenExpired", "responseClass": "NA", "effects": (), "rejection": "RequestIdExhausted"}]
        self.assertTrue(async_formal.validate_trace(valid_rejection, self.spec))
        mutated_rejection = copy.deepcopy(valid_rejection)
        mutated_rejection[-1]["effects"] = ("ClearCredentials",)
        with self.assertRaises(ValueError): async_formal.validate_trace(mutated_rejection, self.spec)
        extra_var = copy.deepcopy(valid_rejection)
        extra_var[-1]["untrusted"] = True
        with self.assertRaises(ValueError): async_formal.validate_trace(extra_var, self.spec)

    def test_tlc_timeout_evidence_is_normalized_and_persisted(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            work, out = Path(temp) / "work", Path(temp) / "out"
            work.mkdir(); out.mkdir()
            with patch("verification.async_formal.subprocess.run", side_effect=__import__("subprocess").TimeoutExpired(["java", "tlc"], 1, output=b"partial TLC", stderr=b"timeout detail")):
                result = async_formal._run_tlc(work, Path("fake.jar"), "positive-tlc", out)
            self.assertTrue(result["timedOut"])
            saved = json.loads((out / "positive-tlc.json").read_text())
            self.assertEqual(saved["stdout"], "partial TLC")
            self.assertEqual(saved["stderr"], "timeout detail")
            self.assertTrue(saved["timedOut"])
            self.assertEqual(saved["command"][:3], ["java", "-cp", "fake.jar"])

    def test_formal_tool_failure_persists_metadata_and_failure_report(self):
        from unittest.mock import patch
        class JavaVersion:
            returncode = 0
            stdout = ""
            stderr = 'openjdk version "17.0.13"\n'
        with tempfile.TemporaryDirectory() as temp, patch("verification.async_formal.subprocess.run", return_value=JavaVersion()), patch("verification.async_formal.ensure_jar", side_effect=RuntimeError("tool unavailable")):
            output = Path(temp) / "formal"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(async_formal.main(["--output", str(output)]), 1)
            self.assertEqual(json.loads((output / "report.json").read_text())["status"], "FAIL")
            meta = json.loads((output / "metadata.json").read_text())
            self.assertIn("javaVersion", meta)
            self.assertIn("lock", meta)


class AsyncRunnerFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input.json"
        self.input.write_text('{"scenarios":[]}\n')

    def tearDown(self):
        self.temp.cleanup()

    def fake_runner(self, name, body):
        path = self.root / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return path

    def test_malformed_successful_outputs_create_fail_report_and_direct_fail(self):
        fixtures = ('{"oops":[]}', '{"traces":[]} extra', '{"traces":[{"scenario":"x"}]}',
                    '{"traces":[{"scenario":"x","steps":[{}]}]}')
        for index, fixture in enumerate(fixtures):
            with self.subTest(fixture=fixture):
                runner = self.fake_runner(f"bad-{index}", "printf '%s' '" + fixture.replace("'", "'\\''") + "'")
                output = self.root / f"bad-output-{index}"
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = async_verify.run(output, runner, runner, self.input)
                report = json.loads((output / "async-report.json").read_text())
                self.assertEqual(result, 1)
                self.assertEqual(report["verdicts"], {"swift": "FAIL", "kotlin": "FAIL", "differential": "FAIL"})

    def test_crash_and_signal_remain_infrastructure_with_raw_status_and_stderr(self):
        empty = self.fake_runner("valid", "printf '%s' '{\"traces\":[]}'")
        for name, body, raw_exit in (("crash", "printf 'crash detail' >&2; exit 7", 7),
                                     ("signal", "kill -TERM $$", -15)):
            with self.subTest(name=name):
                bad = self.fake_runner(name, body)
                output = self.root / f"{name}-output"
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = async_verify.run(output, bad, empty, self.input)
                report = json.loads((output / "async-report.json").read_text())
                self.assertEqual(result, 2)
                self.assertEqual(report["verdicts"]["swift"], "INFRA_FAILURE")
                self.assertEqual(int((output / "swift-async-runner.exit-code").read_text()), raw_exit)
                runner_result = json.loads((output / "swift-async-runner.result.json").read_text())
                self.assertEqual(runner_result["classification"], "INFRA_FAILURE")
                self.assertEqual(runner_result["returnCode"], raw_exit)
                self.assertIn("crash detail", (output / "swift-async-runner.stderr.log").read_text()) if name == "crash" else None


class AsyncMutationSkipTests(unittest.TestCase):
    def test_skip_marks_every_case_not_run_and_clears_owned_stale_results(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "mutations"
            output.mkdir()
            (output / ".async-mutations-owned").write_text("owned\n")
            matrix = json.loads((ROOT / "verification/async-mutation-matrix.json").read_text())
            first = output / matrix["cases"][0]["id"]
            first.mkdir(); (first / ".async-mutation-case").write_text("owned\n"); (first / "result.txt").write_text("PASS stale\n")
            (output / "unrelated.txt").write_text("preserve\n")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(async_mutations.main([str(ROOT / "verification/async-mutation-matrix.json"), "--output", str(output), "--skip"]), 0)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "NOT_RUN")
            self.assertTrue(all(row["status"] == "NOT_RUN" for row in manifest["cases"]))
            self.assertEqual((output / "unrelated.txt").read_text(), "preserve\n")
            self.assertNotIn("PASS stale", (first / "result.txt").read_text())


if __name__ == "__main__":
    unittest.main()
