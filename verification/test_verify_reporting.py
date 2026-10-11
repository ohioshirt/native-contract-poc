"""Build failures must leave explicit unexecuted gate evidence."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VerifyReportingTests(unittest.TestCase):
    def test_failed_builds_record_not_run_without_missing_log_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/verify.sh', root/'scripts/verify.sh')
            (root/'contract').mkdir()
            (root/'contract/specification.json').write_text('{}')
            (root/'android').mkdir()
            (root/'android/build.gradle.kts').write_text('kotlin("jvm") version "2.3.20"')
            (root/'android/gradlew').write_text('#!/bin/bash\nexit 1\n')
            (root/'android/gradlew').chmod(0o755)
            bin_dir = root/'bin'
            bin_dir.mkdir()
            for name in ('swift', 'python3', 'bash', 'java', 'xcodebuild'):
                command = bin_dir/name
                command.write_text('#!/bin/bash\nexit '+('1' if name == 'swift' else '0')+'\n')
                command.chmod(0o755)
            env = {**os.environ, 'PATH': str(bin_dir)+os.pathsep+os.environ['PATH']}
            out = root/'reports'
            result = subprocess.run(['/bin/bash', str(root/'scripts/verify.sh'), str(out)], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('No such file', result.stderr)
            self.assertTrue((out/'report.md').read_text().startswith('Overall: FAIL'))
            for gate in ('swift-runner', 'kotlin-runner', 'async-runner'):
                self.assertEqual((out/f'{gate}.exit-code').read_text().strip(), '125')
                self.assertTrue((out/f'{gate}.command.log').read_text().startswith('not run:'))
                self.assertTrue((out/f'{gate}.stdout.log').read_text().startswith('NOT_RUN:'))
                self.assertTrue((out/f'{gate}.stderr.log').is_file())


if __name__ == '__main__':
    unittest.main()
