import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import aggregate, progress


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


class ProgressLogTests(unittest.TestCase):
    def test_event_is_a_noop_without_the_progress_environment(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            progress.event("case-start", scenario="APP-01")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_event_appends_one_single_line_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(path)}):
                progress.event("case-end", scenario="APP-01", variant=None, ok=True, detail="line one\nline two")
                progress.event("case-start", scenario="APP-02")
            lines = path.read_text().splitlines()

        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z case-end scenario=APP-01 ok=true detail=\"line one line two\"$")
        self.assertTrue(lines[1].endswith(" case-start scenario=APP-02"))

    def test_event_never_raises_for_unencodable_values_or_unwritable_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(path)}):
                progress.event("command-start", step="APP\udcff01", detail=ValueError("bad \udcff byte"))
            self.assertIn("command-start step=APP\\udcff01", path.read_text())
            with patch.dict(os.environ, {progress.ENVIRONMENT: directory}):
                progress.event("case-start", scenario="APP-01")

    def test_summary_lists_every_stage_with_its_outcome(self):
        report = {
            "classification": "INFRA_FAILURE",
            "stageResults": [
                {"stageId": "candidate-ios", "classification": "INFRA_FAILURE", "acceptanceClassification": "INFRA_FAILURE",
                 "durationSeconds": 1802.4, "timedOut": True, "detail": "missing artifact"},
                {"stageId": "legacy-full", "classification": "NOT_RUN", "acceptanceClassification": "NOT_RUN",
                 "skippedAfter": {"stageId": "candidate-ios", "classification": "INFRA_FAILURE", "timedOut": True}},
            ],
        }
        text = progress.summary_markdown(report, title="iOS ledger")

        self.assertIn("### iOS ledger: INFRA_FAILURE", text)
        self.assertIn("| candidate-ios | INFRA_FAILURE | 30.0 min | timed out; missing artifact |", text)
        self.assertIn("| legacy-full | NOT_RUN | - | skipped after candidate-ios INFRA_FAILURE |", text)


class ControllerProgressTests(unittest.TestCase):
    def test_native_commands_report_their_step_and_elapsed_time(self):
        from integration import controller

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(log)}):
                result = controller.run_streaming_command(
                    [sys.executable, "-c", "print('ok')"],
                    cwd=root,
                    environment=dict(os.environ),
                    output_directory=root / "ios" / "APP-01" / "runner" / "p1",
                    timeout_seconds=30,
                )
            lines = log.read_text().splitlines()

        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r" command-start step=APP-01/runner/p1 program=python")
        self.assertRegex(lines[1], r" command-end step=APP-01/runner/p1 exitCode=0 timedOut=false seconds=\d+\.\d$")

    def test_xcodebuild_milestones_are_reported_once_each(self):
        from integration import controller

        script = (
            "print('Command line invocation:')\n"
            "print('2026-10-13 15:42:18.558280+0000 Runner[1:2] [Default] Running tests...')\n"
            "print(\"Test Suite 'Selected tests' started at 2026-10-13 15:42:44.138.\")\n"
            "print(\"Test Suite 'Selected tests' started at 2026-10-13 15:42:45.000.\")\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(log)}):
                controller.run_streaming_command(
                    [sys.executable, "-c", script],
                    cwd=root,
                    environment=dict(os.environ),
                    output_directory=root / "ios" / "APP-01" / "runner" / "p1",
                    timeout_seconds=30,
                )
            milestones = [line for line in log.read_text().splitlines() if " command-milestone " in line]

        self.assertEqual(
            [line.split(" milestone=")[1].split()[0] for line in milestones],
            ["test-runner-launched", "tests-started"],
        )
        for line in milestones:
            self.assertRegex(line, r" command-milestone step=APP-01/runner/p1 milestone=[a-z-]+ seconds=\d+\.\d$")

    def test_commands_without_xcodebuild_markers_report_no_milestones(self):
        from integration import controller

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(log)}):
                controller.run_streaming_command(
                    [sys.executable, "-c", "print('Running tests')"],
                    cwd=root,
                    environment=dict(os.environ),
                    output_directory=root / "android" / "APP-01" / "runner",
                    timeout_seconds=30,
                )
            kinds = [line.split()[1] for line in log.read_text().splitlines()]

        self.assertEqual(kinds, ["command-start", "command-end"])

    def test_refresh_server_reports_its_startup_and_shutdown_time(self):
        from integration import controller

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            log = Path(directory) / "progress.log"
            with patch.dict(os.environ, {progress.ENVIRONMENT: str(log)}):
                with controller.LoopbackRun(
                    candidate=ROOT,
                    output=Path(directory) / "case",
                    platform="ios",
                    scenario_id="APP-01",
                    attempt_id="attempt-01",
                ):
                    pass
            kinds = [line.split()[1] for line in log.read_text().splitlines()]
            lines = log.read_text().splitlines()

        self.assertEqual(kinds, ["server-ready", "server-stopped"])
        self.assertRegex(lines[0], r" server-ready scenario=APP-01 seconds=\d+\.\d$")
        self.assertRegex(lines[1], r" server-stopped scenario=APP-01 seconds=\d+\.\d$")


class SkippedLedgerTests(unittest.TestCase):
    def test_aggregate_names_the_stage_that_stopped_the_ledger(self):
        stages = list(aggregate.IOS_STAGES)
        rows = [{"stageId": stage} for stage in stages]
        rows[2] = {"stageId": stages[2], "classification": "NOT_RUN",
                   "skippedAfter": {"stageId": stages[1], "classification": "INFRA_FAILURE", "timedOut": True}}
        rows[3] = {"stageId": stages[3], "classification": "NOT_RUN",
                   "skippedAfter": {"stageId": stages[1], "classification": "INFRA_FAILURE", "timedOut": True}}
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            root = Path(directory)
            (root / "suite-report.json").write_text(json.dumps({
                "version": 1, "classification": "INFRA_FAILURE", "manifest": "m.json",
                "manifestDigest": "d" * 64, "selectedStages": stages, "stageResults": rows,
            }))
            with self.assertRaisesRegex(
                aggregate.AggregateError,
                "ios stage integration-controls was not run: skipped after candidate-ios INFRA_FAILURE",
            ):
                aggregate._suite_ledger(root, ROOT, {}, "d" * 64, "ios", stages, "c" * 64)


if __name__ == "__main__":
    unittest.main()
