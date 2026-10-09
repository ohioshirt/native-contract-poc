import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verification.formal import bridge, runner


NEGATIVE_TRACE = '''TLC2 Version 2.19
Error: Invariant TransitionSound is violated.
Error: The behavior up to this point is:
State 1: <Initial predicate>
/\\ previousState = "Unauthenticated"
/\\ state = "Unauthenticated"
/\\ effects = <<>>
/\\ event = "__initial__"

State 2: <Next line 14, col 3 to line 18, col 87 of module Session>
/\\ previousState = "Unauthenticated"
/\\ state = "Authenticated"
/\\ effects = <<>>
/\\ event = "LoginSucceeded"

State 3: <Next line 14, col 3 to line 18, col 87 of module Session>
/\\ previousState = "Authenticated"
/\\ state = "Unauthenticated"
/\\ effects = <<>>
/\\ event = "Logout"

8 states generated, 8 distinct states found, 5 states left on queue.
'''


class FormalBridgeTests(unittest.TestCase):
    def test_generated_data_quotes_values_and_keeps_transition_rows(self):
        spec = {"states": ['A"B'], "events": ["e\\x"], "effects": ["fx"],
                "initialState": 'A"B', "transitions": [{"state": 'A"B', "event": "e\\x", "nextState": 'A"B', "effects": ["fx"]}],
                "invariants": {"maxEffectsPerStep": 1}}
        text = bridge.render_data(spec)
        self.assertIn('"A\\"B"', text)
        self.assertIn('"e\\\\x"', text)
        self.assertEqual(bridge.expected_observations(spec), {('A"B', 'e\\x', 'A"B', ("fx",)), ("A\"B", "__initial__", "A\"B", ())})

    def test_dump_parser_and_comparison_are_exact(self):
        valid = ('State 1:\n/\\ state = "Unauthenticated"\n/\\ previousState = "Unauthenticated"\n/\\ event = "__initial__"\n/\\ effects = <<>>\n\n'
                 'State 2:\n/\\ state = "Authenticated"\n/\\ previousState = "Unauthenticated"\n/\\ event = "LoginSucceeded"\n/\\ effects = <<>>\n\n'
                 'State 3:\n/\\ state = "Unauthenticated"\n/\\ previousState = "Authenticated"\n/\\ event = "Logout"\n/\\ effects = <<"ClearCredentials">>\n')
        parsed = bridge.parse_dump(valid)
        self.assertEqual(len(parsed), 3)
        expected = {("Unauthenticated", "__initial__", "Unauthenticated", ()),
                    ("Authenticated", "LoginSucceeded", "Unauthenticated", ()),
                    ("Unauthenticated", "Logout", "Authenticated", ("ClearCredentials",))}
        self.assertEqual(bridge.compare_dump(valid, expected), parsed)
        with self.assertRaises(ValueError): bridge.parse_dump(valid + "garbage\n")
        with self.assertRaises(ValueError): bridge.compare_dump(valid, set())
        with self.assertRaises(ValueError): bridge.parse_dump(valid.replace('/\\ event = "LoginSucceeded"\n', ''))
        malformed = valid.replace('/\\ effects = <<"ClearCredentials">>', '/\\ effects = <<"ClearCredentials",>>')
        with self.assertRaisesRegex(ValueError, "trailing"):
            bridge.compare_dump(malformed, expected)

    def test_duplicate_observation_rejected(self):
        block = 'State 1:\n/\\ state = "A"\n/\\ previousState = "A"\n/\\ event = "__initial__"\n/\\ effects = <<>>\n\n'
        with self.assertRaisesRegex(ValueError, "duplicate"):
            bridge.parse_dump(block + block.replace("State 1:", "State 2:"))

    def test_effect_parser_rejects_trailing_or_malformed_tokens(self):
        for malformed in ['<<"fx",>>', '<<"fx", "other",>>', '<<"fx" garbage>>', '<<"bad\\q">>']:
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                bridge._parse_effects(malformed)


class FormalRunnerTests(unittest.TestCase):
    def test_hash_verification(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jar"
            path.write_bytes(b"jar")
            self.assertEqual(runner.verify_jar(path, hashlib.sha256(b"jar").hexdigest()), hashlib.sha256(b"jar").hexdigest())
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                runner.verify_jar(path, "0" * 64)

    def test_output_safety_rejects_unowned_nonempty_and_root(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "out"
            output.mkdir()
            keep = output / "important.txt"
            keep.write_text("keep")
            with self.assertRaisesRegex(RuntimeError, "nonempty"):
                runner.prepare_output(output)
            self.assertEqual(keep.read_text(), "keep")
            with self.assertRaises(RuntimeError):
                runner.prepare_output("/")

    def test_negative_control_requires_named_invariant_and_counterexample(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "trace"
            trace.write_text(NEGATIVE_TRACE)
            good = runner.classify_negative(12, NEGATIVE_TRACE, str(trace), False)
            self.assertTrue(good[0], good[1])
            negatives = [
                (1, NEGATIVE_TRACE, NEGATIVE_TRACE),
                (12, "Syntax error: TransitionSound", NEGATIVE_TRACE),
                (-9, NEGATIVE_TRACE, NEGATIVE_TRACE),
                (12, NEGATIVE_TRACE, "State 1\\n"),
                (12, NEGATIVE_TRACE, NEGATIVE_TRACE.rsplit("/\\ event =", 1)[0]),
                (12, NEGATIVE_TRACE.replace("8 states generated", "garbage\n8 states generated"),
                 NEGATIVE_TRACE.replace("8 states generated", "garbage\n8 states generated")),
                (12, NEGATIVE_TRACE.replace('/\\ effects = <<>>\n/\\ event = "Logout"', '/\\ effects = <<>>\n/\\ event = "TokenExpired"'), NEGATIVE_TRACE),
                (12, NEGATIVE_TRACE.replace('/\\ previousState = "Authenticated"\n/\\ state = "Unauthenticated"', '/\\ previousState = "Unauthenticated"\n/\\ state = "Unauthenticated"'), NEGATIVE_TRACE),
            ]
            for i, (code, output, contents) in enumerate(negatives):
                trace.write_text(contents)
                with self.subTest(case=i):
                    self.assertFalse(runner.classify_negative(code, output, str(trace), False)[0])

    def test_fullrunner_writes_fail_report_for_tool_failures(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "formal"
            cases = [
                ("download", patch.object(runner, "ensure_jar", side_effect=RuntimeError("download failed")), None),
                ("hash", patch.object(runner, "ensure_jar", side_effect=RuntimeError("TLC JAR SHA-256 mismatch")), None),
                ("timeout", patch.object(runner, "ensure_jar", return_value=(Path("fake.jar"), "a" * 64, "provided")),
                 {"exit": None, "timedOut": True, "stdout": "", "stderr": "killed"}),
                ("missing completion", patch.object(runner, "ensure_jar", return_value=(Path("fake.jar"), "a" * 64, "provided")),
                 {"exit": 0, "timedOut": False, "stdout": "TLC started", "stderr": ""}),
            ]
            for name, jar_patch, model_result in cases:
                with self.subTest(name=name):
                    output.mkdir(exist_ok=True)
                    if runner.MARKER in {item.name for item in output.iterdir()}:
                        (output / "report.json").write_text(json.dumps({"status": "PASS", "stale": True}))
                    if model_result is None:
                        model_patch = patch.object(runner, "_run_model")
                    else:
                        model_patch = patch.object(runner, "_run_model", return_value=model_result)
                    java_result = subprocess.CompletedProcess(["java", "-version"], 0, 'openjdk version "17.0.1"', "")
                    with jar_patch, model_patch, patch.object(runner.subprocess, "run", return_value=java_result):
                        status = runner.main(["--output", str(output)])
                    self.assertEqual(status, 1)
                    self.assertEqual(json.loads((output / "report.json").read_text())["status"], "FAIL")
                    self.assertTrue((output / "metadata.json").is_file())
                    # Marker-owned reuse clears any stale PASS before starting.
                    self.assertNotEqual(json.loads((output / "report.json").read_text()).get("status"), "PASS")

    def test_legitimate_spec_format_change_is_not_locked_to_old_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = Path("contract/specification.json").read_text()
            changed = root / "spec.json"
            changed.write_text("\n" + json.dumps(json.loads(source), indent=4, ensure_ascii=False) + "\n")
            output = root / "out"
            observations = sorted(bridge.expected_observations(json.loads(changed.read_text())))

            def fake_model(work, jar, name, session_text, dump_path, log_dir):
                if name == "positive-tlc":
                    lines = []
                    for index, (state, event, previous, effects) in enumerate(observations, start=1):
                        lines.extend([f"State {index}:", f"/\\ previousState = {bridge.tla_string(previous)}",
                                      f"/\\ state = {bridge.tla_string(state)}",
                                      f"/\\ effects = <<{','.join(bridge.tla_string(item) for item in effects)}>>",
                                      f"/\\ event = {bridge.tla_string(event)}", ""])
                    dump_path.write_text("\n".join(lines))
                    return {"exit": 0, "timedOut": False,
                            "stdout": "Model checking completed. No error has been found.\n0 states left on queue.\n", "stderr": ""}
                return {"exit": 12, "timedOut": False, "stdout": NEGATIVE_TRACE, "stderr": ""}

            java_result = subprocess.CompletedProcess(["java", "-version"], 0, 'openjdk version "17.0.1"', "")
            with patch.object(runner, "ensure_jar", return_value=(root / "fake.jar", "a" * 64, "provided")), \
                 patch.object(runner.subprocess, "run", return_value=java_result), \
                 patch.object(runner, "_run_model", side_effect=fake_model):
                result = runner.run(output, spec_path=changed)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["sourceSha256"], hashlib.sha256(changed.read_bytes()).hexdigest())
            self.assertNotEqual(result["sourceSha256"], hashlib.sha256(source.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
