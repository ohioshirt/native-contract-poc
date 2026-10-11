import tempfile
import unittest
from pathlib import Path
from verification import change_protocol
from verification.reproduce_evolution import build_config, require_verdict


class ReproductionTests(unittest.TestCase):
    def test_generated_config_is_valid_and_protects_fresh_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root/'reports/reproduction-02'
            config = build_config(root, out, 'a'*40)
            change_protocol.validate_config(config)
            self.assertEqual(config['protectedPaths'], ['reports/reproduction-02/baseline-native/', 'reports/reproduction-02/baseline-hashes.json'])
            self.assertEqual(config['outputRoot'], 'reports/reproduction-02/attempts')
            self.assertIn('scripts/__pycache__/', config['ignoredPaths'])
            self.assertIn('ios/.swift-cache/', config['ignoredPaths'])
            self.assertFalse(any(p.startswith('verification/') and '__pycache__' not in p for p in config['ignoredPaths']))
            self.assertIn('{candidate}/reports/reproduction-02/baseline-native/AsyncTraceRunner', config['stages']['old-native-red']['argv'])

    def test_bound_semantic_red_cannot_be_infrastructure_or_pass(self):
        require_verdict({'classification':'SEMANTIC_FAIL', 'resultClassification':'SEMANTIC_FAIL', 'bindingClassification':'PASS'}, 'SEMANTIC_FAIL', binding=True)
        for verdict in ('PASS', 'INFRA_FAILURE', 'NOT_RUN', 'INCONCLUSIVE'):
            with self.assertRaises(RuntimeError):
                require_verdict({'classification':verdict, 'bindingClassification':'PASS'}, 'SEMANTIC_FAIL', binding=True)
        with self.assertRaises(RuntimeError):
            require_verdict({'classification':'PASS', 'resultClassification':'PASS', 'bindingClassification':'INFRA_FAILURE'}, 'PASS', binding=True)
