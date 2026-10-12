"""Frozen concurrency coverage uses live independent callers within checker bounds."""
import json
from pathlib import Path
import unittest
from verification.linearizability import validate_workload

ROOT = Path(__file__).resolve().parents[1]


class ManagedWorkloadTests(unittest.TestCase):
    def test_expiration_phase_retains_core_operations_and_uses_bounded_live_callers(self):
        workload = json.loads((ROOT/'verification/managed-workload.json').read_text())
        validate_workload(workload)
        scenario = next(s for s in workload['scenarios'] if s['id'] == 'simultaneous-expiration')
        self.assertEqual(len(scenario['operations']), 16)
        rows = {o['id']: o for o in scenario['operations']}
        self.assertTrue({'login', 'expire-one', 'expire-two', 'during', 'final'} <= rows.keys())
        callers = [o for o in scenario['operations'] if o['phase'] == 1]
        self.assertEqual(len(callers), 14)
        self.assertTrue(all(not o['after'] for o in callers))
        self.assertEqual(sum(o['kind'] == 'snapshot' for o in callers), 1)
        self.assertTrue(all(o['event']['event'] == 'TokenExpired' for o in callers if o['kind'] == 'handle'))
