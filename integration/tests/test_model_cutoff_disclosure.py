import copy
import json
from pathlib import Path
import tempfile
import unittest

from integration import model, protocol_config
from verification import change_protocol as protocol


class MutantCutoffDisclosureTests(unittest.TestCase):
    def test_valid_detection_discloses_unreached_coverage_and_rejects_hidden_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            report = model.explore(output=destination, mutant="unverified-publish")
            required = set(model.GOAL_NAMES.values()) | {"foreign-same-id"}
            missing = sorted(required - set(report["witnesses"]))
            self.assertTrue(report["limitReached"])
            self.assertFalse(report["searchComplete"])
            self.assertTrue(missing)
            self.assertEqual(report["missingCoverage"], missing)
            self.assertEqual(report["classification"], "SEMANTIC_FAIL")
            protocol.model_mutant_report(
                destination / "report.json", "unverified-publish",
                protocol_config.MODEL_MUTANT_WITNESSES["unverified-publish"],
            )
            forged = copy.deepcopy(report)
            forged["missingCoverage"] = []
            (destination / "report.json").write_text(json.dumps(forged))
            with self.assertRaises(protocol.ProtocolError):
                protocol.model_mutant_report(
                    destination / "report.json", "unverified-publish",
                    protocol_config.MODEL_MUTANT_WITNESSES["unverified-publish"],
                )
