"""Declared xcresult screen attachments, not filename suffixes, own evidence."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integration import controller


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL9sAAAAASUVORK5CYII=")


class XcresultScreenshotTests(unittest.TestCase):
    def fixture(self, directory, *, name="screen-final_0_fixture.png", filename="nested/payload"):
        root = Path(directory)
        payload = root / "nested/payload"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(PNG)
        rows = [{"testIdentifier": "ScenarioUITests/testFrozenScenarioHarness()", "attachments": [{"exportedFileName": filename, "suggestedHumanReadableName": name}]}]
        (root / "manifest.json").write_text(json.dumps(rows))
        return root, rows

    def test_nested_png_without_suffix_is_preserved_from_declared_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory)
            rows = controller.ios_screenshot_rows(root, scenario_id="APP-01", ordinal=1)
            self.assertEqual(rows, [{"path": "APP-01/p1/screenshots/nested/payload", "sha256": hashlib.sha256(PNG).hexdigest()}])

    def test_missing_manifest_or_selected_case_never_means_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((OSError, ValueError)):
                controller.ios_screenshot_rows(root, scenario_id="APP-01", ordinal=1)
            for value in ([], [{"testIdentifier": "ScenarioUITests/testOther()", "attachments": []}]):
                (root / "manifest.json").write_text(json.dumps(value))
                with self.assertRaises((OSError, ValueError)):
                    controller.ios_screenshot_rows(root, scenario_id="APP-01", ordinal=1)

    def test_missing_required_final_screen_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory, name="screen-command-1_0_fixture.png")
            with self.assertRaises((OSError, ValueError)):
                controller.ios_screenshot_rows(root, scenario_id="APP-01", ordinal=1)

    def test_declared_screen_cannot_be_text_or_duplicate_or_escape(self):
        for problem in ("text", "duplicate", "escape"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                root, rows = self.fixture(directory)
                if problem == "text":
                    (root / "nested/payload").write_bytes(b"not a PNG")
                elif problem == "duplicate":
                    rows[0]["attachments"].append(dict(rows[0]["attachments"][0]))
                else:
                    rows[0]["attachments"][0]["exportedFileName"] = "../escaped"
                (root / "manifest.json").write_text(json.dumps(rows))
                with self.assertRaises((OSError, ValueError)):
                    controller.ios_screenshot_rows(root, scenario_id="APP-01", ordinal=1)

    def test_n3_barrier_screen_is_required_in_addition_to_final(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.fixture(directory)
            with self.assertRaises((OSError, ValueError)):
                controller.ios_screenshot_rows(root, scenario_id="CTRL-N3-EARLY-PUBLISH", ordinal=1, required_names=("screen-final", "screen-render-at-barrier"))
