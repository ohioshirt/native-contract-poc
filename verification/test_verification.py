import copy
import contextlib
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verification import contract, traces
from verification.io import load_contract
from verification import verify

ROOT = Path(__file__).resolve().parents[1]
MUTATION_MODULE_SPEC = importlib.util.spec_from_file_location("mutations", ROOT / "scripts/mutations.py")
mutations = importlib.util.module_from_spec(MUTATION_MODULE_SPEC)
MUTATION_MODULE_SPEC.loader.exec_module(mutations)

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "contract/specification.json").read_text())
        self.schema = json.loads((ROOT / "contract/schema.json").read_text())

    def test_valid_contract_is_total_and_domain_is_15(self):
        machine = contract.validate(self.spec, self.schema)
        self.assertEqual(len(machine), 15)
        self.assertEqual(len(list(contract.scenarios(self.spec))), 781)

    def test_schema_rejects_wrong_top_level_type(self):
        bad = copy.deepcopy(self.spec)
        bad["version"] = "1"
        with self.assertRaisesRegex(ValueError, "schema"):
            contract.validate(bad, self.schema)

    def test_semantics_reject_incomplete_domain(self):
        bad = copy.deepcopy(self.spec)
        bad["transitions"].pop()
        with self.assertRaisesRegex(ValueError, "missing transition"):
            contract.validate(bad, self.schema)

    def test_semantics_reject_duplicate_pair(self):
        bad = copy.deepcopy(self.spec)
        bad["transitions"].append(copy.deepcopy(bad["transitions"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate transition"):
            contract.validate(bad, self.schema)

    def test_semantics_reject_effect_outside_declared_alphabet(self):
        bad = copy.deepcopy(self.spec)
        bad["transitions"][0]["effects"] = ["Unknown"]
        with self.assertRaisesRegex(ValueError, "effect"):
            contract.validate(bad, self.schema)

    def test_semantics_enforce_effect_bound_and_invariant_flags(self):
        bad = copy.deepcopy(self.spec)
        bad["transitions"][0]["effects"] = ["ClearCredentials", "RequestTokenRefresh"]
        with self.assertRaisesRegex(ValueError, "maxEffectsPerStep"):
            contract.validate(bad, self.schema)
        bad = copy.deepcopy(self.spec)
        bad["invariants"]["maxEffectsPerStep"] = 2
        with self.assertRaisesRegex(ValueError, "maxEffectsPerStep"):
            contract.validate(bad, self.schema)

    def test_schema_const_true_rejects_integer_one(self):
        bad = copy.deepcopy(self.spec)
        bad["invariants"]["totalTransitionFunction"] = 1
        with self.assertRaisesRegex(ValueError, "schema"):
            contract.validate(bad, self.schema)


class TraceTests(unittest.TestCase):
    def setUp(self):
        spec = json.loads((ROOT / "contract/specification.json").read_text())
        schema = json.loads((ROOT / "contract/schema.json").read_text())
        self.machine = contract.validate(spec, schema)
        self.events = ["LoginSucceeded", "Logout"]
        self.expected = traces.oracle("scenario-1", self.events, spec["initialState"], self.machine)

    def test_oracle_preserves_ordered_effects_and_step_states(self):
        self.assertEqual(self.expected["steps"], [
            {"event": "LoginSucceeded", "state": "Authenticated", "effects": []},
            {"event": "Logout", "state": "Unauthenticated", "effects": ["ClearCredentials"]},
        ])

    def test_comparison_accepts_exact_trace(self):
        self.assertEqual(traces.compare([self.expected], [self.expected]), [])

    def test_comparison_accepts_empty_scenario_id(self):
        row = {"scenario": "", "steps": []}
        self.assertEqual(traces.compare([row], [row]), [])

    def test_schema_rejects_transition_missing_effects(self):
        bad = copy.deepcopy(json.loads((ROOT / "contract/specification.json").read_text()))
        del bad["transitions"][0]["effects"]
        schema = json.loads((ROOT / "contract/schema.json").read_text())
        with self.assertRaisesRegex(ValueError, "schema"):
            contract.validate(bad, schema)

    def test_schema_rejects_unknown_keyword_instead_of_ignoring_it(self):
        schema = json.loads((ROOT / "contract/schema.json").read_text())
        spec = json.loads((ROOT / "contract/specification.json").read_text())
        schema["properties"]["version"]["pattern"] = "^1$"
        with self.assertRaisesRegex(ValueError, "unsupported schema keyword"):
            contract.validate(spec, schema)

    def test_duplicate_contract_json_keys_are_rejected(self):
        schema = ROOT / "contract/schema.json"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "spec.json"
            path.write_text('{"version":1,"version":1}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                load_contract(path, schema)

    def test_comparison_rejects_missing_step(self):
        actual = copy.deepcopy(self.expected)
        actual["steps"].pop()
        self.assertTrue(any("step count" in e for e in traces.compare([self.expected], [actual])))

    def test_comparison_rejects_extra_step_and_length_mismatch(self):
        actual = copy.deepcopy(self.expected)
        actual["steps"].append(copy.deepcopy(actual["steps"][-1]))
        self.assertTrue(any("step count" in e for e in traces.compare([self.expected], [actual])))

    def test_comparison_rejects_duplicate_or_missing_scenarios(self):
        self.assertTrue(any("duplicate" in e for e in traces.compare([self.expected], [self.expected, self.expected])))
        self.assertTrue(any("missing" in e for e in traces.compare([self.expected], [])))
        self.assertTrue(any("must be an array" in e for e in traces.compare([self.expected], None)))

    def test_comparison_detects_state_and_effect_order_changes(self):
        actual = copy.deepcopy(self.expected)
        actual["steps"][1]["state"] = "Authenticated"
        self.assertTrue(any("state" in e for e in traces.compare([self.expected], [actual])))
        actual = copy.deepcopy(self.expected)
        actual["steps"][1]["effects"] = ["RequestTokenRefresh"]
        self.assertTrue(any("effects" in e for e in traces.compare([self.expected], [actual])))

    def test_malformed_step_fields_are_rejected(self):
        actual = copy.deepcopy(self.expected)
        del actual["steps"][0]["event"]
        self.assertTrue(traces.compare([self.expected], [actual]))

    def test_identical_malformed_native_traces_are_rejected(self):
        malformed = {"scenario": "bad", "steps": [{"event": "x", "state": 5, "effects": "ClearCredentials"}]}
        self.assertTrue(traces.compare([malformed], [malformed]))

    def test_effect_order_is_compared_even_when_contract_bound_is_one(self):
        expected = {"scenario": "order", "steps": [{"event": "x", "state": "S", "effects": ["A", "B"]}]}
        actual = copy.deepcopy(expected)
        actual["steps"][0]["effects"].reverse()
        self.assertTrue(any("effects" in error for error in traces.compare([expected], [actual])))


class CliTests(unittest.TestCase):
    def test_malformed_scenario_ids_still_emit_failed_json_and_markdown(self):
        for scenario_id in ([], {}):
            with self.subTest(scenario_id=scenario_id), tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                invalid = temp / "invalid.json"
                invalid.write_text(json.dumps({"traces": [{"scenario": scenario_id, "steps": []}]}))
                report, markdown = temp / "summary.json", temp / "summary.md"
                with patch("sys.argv", ["verify.py", "--swift", str(invalid), "--kotlin", str(invalid),
                                         "--report", str(report), "--markdown", str(markdown)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(verify.main(), 1)
                parsed = json.loads(report.read_text())
                self.assertEqual([parsed[name]["verdict"] for name in ("oracle", "swift", "kotlin", "differential")],
                                 ["PASS", "FAIL", "FAIL", "FAIL"])
                self.assertIn("scenario must be string", markdown.read_text())

    def test_missing_runners_keep_stable_summary_and_markdown_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            report, markdown = temp / "summary.json", temp / "summary.md"
            with patch("sys.argv", ["verify.py", "--report", str(report), "--markdown", str(markdown)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(verify.main(), 1)
            parsed = json.loads(report.read_text())
            self.assertEqual([parsed[name]["verdict"] for name in ("oracle", "swift", "kotlin", "differential")],
                             ["PASS", "NOT_RUN", "NOT_RUN", "NOT_RUN"])
            self.assertIn("| differential | NOT_RUN |", markdown.read_text())

    def test_skip_mutations_clears_old_owned_pass_evidence_and_marks_not_run(self):
        matrix = json.loads((ROOT / "verification/mutation-matrix.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "mutations"
            output.mkdir()
            (output / "unrelated.txt").write_text("keep")
            for case in matrix["cases"]:
                case_dir = output / case["id"]
                case_dir.mkdir()
                (case_dir / ".native-contract-mutation-case").write_text("owned\n")
                (case_dir / "result.txt").write_text("PASS expected=old\n")
            with patch("sys.argv", ["mutations.py", str(ROOT / "verification/mutation-matrix.json"), "--skip", "--output", str(output)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mutations.main(), 0)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "NOT_RUN")
            self.assertTrue(all(case["status"] == "NOT_RUN" for case in manifest["cases"]))
            self.assertEqual((output / "unrelated.txt").read_text(), "keep")
            self.assertFalse(any((output / case["id"] / "result.txt").exists() for case in matrix["cases"]))

    def test_mutation_infrastructure_abort_marks_later_cases_not_run(self):
        config = {"cases": [{"id": name, "expected": {"swift": "PASS", "kotlin": "PASS", "differential": "PASS"}, "patches": []}
                             for name in ("A-first", "B-second", "C-third")]}
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            config_path, output = temp / "matrix.json", temp / "mutations"
            config_path.write_text(json.dumps(config))
            for name in ("A-first", "B-second", "C-third"):
                case_dir = output / name
                case_dir.mkdir(parents=True)
                (case_dir / ".native-contract-mutation-case").write_text("owned\n")
                (case_dir / "result.txt").write_text("PASS expected=previous\n")
            def fail_generation(label, command, cwd, log_dir, **kwargs):
                (log_dir / f"{label}.command.log").write_text(command + "\n")
                (log_dir / f"{label}.stdout.log").write_text("")
                (log_dir / f"{label}.stderr.log").write_text("synthetic failure\n")
                (log_dir / f"{label}.exit-code").write_text("1\n")
                return 1
            with patch("sys.argv", ["mutations.py", str(config_path), "--output", str(output)]), patch.object(mutations, "execute", side_effect=fail_generation), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(mutations.main(), 2)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "INFRA_FAILURE")
            self.assertEqual([case["status"] for case in manifest["cases"]], ["INFRA_FAILURE", "NOT_RUN", "NOT_RUN"])
            self.assertEqual([case.get("exitCode") for case in manifest["cases"]], [2, None, None])
            self.assertEqual((output / "A-first" / "generate.exit-code").read_text().strip(), "1")
            self.assertFalse(any((output / name / "result.txt").exists() and "previous" in (output / name / "result.txt").read_text()
                                 for name in ("A-first", "B-second", "C-third")))

    def test_mutation_matrix_patch_sites_are_unique(self):
        matrix = json.loads((ROOT / "verification/mutation-matrix.json").read_text())
        self.assertEqual([case["expected"] for case in matrix["cases"]], [
            {"swift": "FAIL", "kotlin": "PASS", "differential": "FAIL"},
            {"swift": "PASS", "kotlin": "FAIL", "differential": "FAIL"},
            {"swift": "FAIL", "kotlin": "FAIL", "differential": "PASS"},
        ])
        for case in matrix["cases"]:
            for patch in case["patches"]:
                source = (ROOT / patch["file"]).read_text()
                self.assertEqual(source.count(patch["before"]), 1, case["id"])

    def test_verify_reports_three_verdicts_and_step_comparison(self):
        spec = json.loads((ROOT / "contract/specification.json").read_text())
        schema = json.loads((ROOT / "contract/schema.json").read_text())
        machine = contract.validate(spec, schema)
        expected = [traces.oracle(f"s{i:04d}", sequence, spec["initialState"], machine)
                    for i, sequence in enumerate(contract.scenarios(spec))]
        changed = copy.deepcopy(expected)
        changed[1]["steps"][0]["state"] = "Unauthenticated"
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            swift, kotlin, json_report, md_report = (temp / name for name in ("swift.json", "kotlin.json", "report.json", "report.md"))
            swift.write_text(json.dumps({"traces": expected}))
            kotlin.write_text(json.dumps({"traces": changed}))
            with patch("sys.argv", ["verify.py", "--swift", str(swift), "--kotlin", str(kotlin),
                                     "--report", str(json_report), "--markdown", str(md_report)]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(verify.main(), 1)
            report = json.loads(json_report.read_text())
            self.assertEqual([report[k]["verdict"] for k in ("oracle", "swift", "kotlin", "differential")], ["PASS", "PASS", "FAIL", "FAIL"])
            self.assertEqual(report["failedSteps"][0]["step"], 1)
            self.assertIn("| s0001 | 1 |", md_report.read_text())


if __name__ == "__main__":
    unittest.main()
