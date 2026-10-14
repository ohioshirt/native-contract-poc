"""Candidate implementation paths must be explicitly editable after freeze."""

from pathlib import Path
import unittest

from integration import controller, protocol_config
from verification import change_protocol


ROOT = Path(__file__).resolve().parents[2]


class CandidateRuntimePathPolicyTests(unittest.TestCase):
    def test_every_platform_runtime_required_file_is_in_frozen_allowed_paths(self):
        config = protocol_config.build_config(
            ROOT,
            ROOT / "reports/standalone/test-candidate-path-policy",
            protocol_config.acceptance_baseline(ROOT),
        )
        for platform in ("ios", "android"):
            for relative in controller._candidate_runtime_required_files(platform):
                with self.subTest(platform=platform, path=relative):
                    self.assertTrue(
                        change_protocol.matches(relative, config["allowedPaths"]),
                        f"{platform} candidate runtime path is not allowed after freeze: {relative}",
                    )


if __name__ == "__main__":
    unittest.main()
