import json
import unittest
from pathlib import Path
from verification import numeric_model
SPEC = json.loads((Path(__file__).resolve().parents[1]/'contract/specification.json').read_text())

class NumericModelTests(unittest.TestCase):
    def test_exhaustive_finite_correspondence(self):
        result = numeric_model.explore(SPEC)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['bound'], {'owners':2,'min':1,'max':3})
        self.assertGreater(result['states'],1)
        self.assertGreater(result['edges'],result['states'])
    def test_reset_mutant_has_concrete_allocator_counterexample(self):
        result = numeric_model.explore(SPEC, mutant='reset-on-logout')
        self.assertEqual(result['verdict'], 'COUNTEREXAMPLE')
        self.assertEqual(result['invariant'], 'AllocatorMonotonicity')
        self.assertTrue(result['trace'])
        self.assertEqual(result['trace'][-1]['event']['event'], 'Logout')
    def test_owner_mutant_has_concrete_foreign_counterexample(self):
        result = numeric_model.explore(SPEC, mutant='owner-check-removed')
        self.assertEqual(result['verdict'], 'COUNTEREXAMPLE')
        self.assertEqual(result['invariant'], 'OwnerIsolation')
        self.assertNotEqual(result['trace'][-1]['owner'],result['trace'][-1]['event']['tokenOwner'])
    def test_bound_does_not_modify_production_profile(self):
        copy = json.loads(json.dumps(SPEC)); numeric_model.explore(SPEC)
        self.assertEqual(SPEC,copy)
        self.assertEqual(SPEC['async']['requestIdMax'],9223372036854775807)
    def test_unknown_mutant_refused(self):
        with self.assertRaises(ValueError): numeric_model.explore(SPEC,mutant='unknown')

if __name__ == '__main__': unittest.main()
