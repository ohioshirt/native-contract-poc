from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/integration.yml"


class LedgerUploadPolicyTests(unittest.TestCase):
    def test_both_portable_uploads_exclude_only_generated_cache_trees(self):
        text = WORKFLOW.read_text()
        rules = (
            "derived-data",
            "preflight-derived-data",
            "gradle-home",
            ".gradle",
            ".swift-cache",
            "candidate-copy",
            "__pycache__",
            "*.pyc",
            ".DS_Store",
        )
        upload_blocks = []
        for marker, next_job in (
            ("Upload iOS portable ledger", "\n  android-native:"),
            ("Upload Android portable ledger", "\n  native-acceptance:"),
        ):
            start = text.index(marker)
            end = text.index(next_job, start)
            upload_blocks.append(text[start:end])

        self.assertEqual(len(upload_blocks), 2)
        for block in upload_blocks:
            self.assertIn("path: |", block)
            self.assertIn("${{ env.NATIVE_CONTRACT_OUTPUT_ROOT }}/", block)
            self.assertIn("include-hidden-files: true", block)
            for rule in rules:
                self.assertIn(f"!${{{{ env.NATIVE_CONTRACT_OUTPUT_ROOT }}}}/**/{rule}/**" if not rule.startswith("*") and rule != ".DS_Store" else f"!${{{{ env.NATIVE_CONTRACT_OUTPUT_ROOT }}}}/**/{rule}", block)
            for evidence in ("native-trace.jsonl", "ui-observations.json", "model/", "suite-report.json", "ledger-owner.json"):
                self.assertNotIn(f"!${{{{ env.NATIVE_CONTRACT_OUTPUT_ROOT }}}}/**/{evidence}", block)

    def test_android_build_and_stage_steps_share_the_explicit_prewarmed_cache(self):
        text = WORKFLOW.read_text()
        cache_env = "GRADLE_USER_HOME: ${{ runner.temp }}/native-contract-gradle-home"
        self.assertEqual(text.count(cache_env), 2)
        self.assertIn("Build included JVM jar, debug APK and instrumentation APK", text)
        self.assertIn("Run Android-bound frozen stages", text)


if __name__ == "__main__":
    unittest.main()
