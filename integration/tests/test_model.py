import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import integration.model as integration_model
from integration.model import explore, replay_coverage_witness, replay_foreign_owner_trace, replay_trace
from verification.async_contract import policy_errors, step


ROOT = Path(__file__).resolve().parents[1]
MAX_ID = 9223372036854775807


def _load_spec():
    return json.loads((ROOT.parent / "contract" / "specification.json").read_text())


class StaticManagedOracleRegressions(unittest.TestCase):
    def test_stale_responses_preserve_full_managed_triple_and_effects(self):
        spec = _load_spec()
        cases = [
            ("Unauthenticated", None, 2),
            ("Authenticated", None, 2),
            ("Refreshing", 2, 3),
        ]
        for state, pending, next_id in cases:
            for event_name in ("RefreshSucceeded", "RefreshFailed"):
                with self.subTest(state=state, event=event_name):
                    stale = {"event": event_name, "requestId": 1}
                    result = step(spec, state, pending, next_id, stale)
                    expected = {
                        "state": state,
                        "pendingRequestId": pending,
                        "nextRequestId": next_id,
                        "effects": [],
                        "rejection": None,
                    }
                    self.assertEqual(result, expected)
                    self.assertEqual(policy_errors(spec, state, pending, next_id, stale, result), [])

    def test_equal_numeric_request_id_from_foreign_owner_is_ignored(self):
        report = self._explore()
        witness = report["witnesses"]["foreign-same-id"]

        self.assertEqual(witness["invariantResult"], "preserved")
        self.assertEqual(witness["requestIds"], [1, 1])
        self.assertNotEqual(witness["owners"][0], witness["owners"][1])
        self.assertEqual(witness["final"]["managed"]["state"], "Refreshing")
        self.assertEqual(witness["final"]["managed"]["pendingRequestId"], 1)
        replayed = replay_foreign_owner_trace(witness["trace"])
        self.assertEqual(replayed["rejection"], "ForeignRequest")
        self.assertEqual(replayed["owners"]["A"], witness["final"]["managed"])

    def _explore(self):
        with tempfile.TemporaryDirectory(prefix="native-contract-model-") as directory:
            return explore(output=Path(directory))


class BoundedIntegrationModelTests(unittest.TestCase):
    def test_identical_bounded_searches_reuse_the_completed_result(self):
        integration_model._search_cached.cache_clear()
        first = integration_model._search("unconditional-success-commit")
        after_first = integration_model._search_cached.cache_info()
        second = integration_model._search("unconditional-success-commit")
        after_second = integration_model._search_cached.cache_info()
        try:
            self.assertEqual(first, second)
            self.assertEqual(after_second.misses, after_first.misses)
            self.assertEqual(after_second.hits, after_first.hits + 1)
        finally:
            integration_model._search_cached.cache_clear()

    def _explore(self, mutant=None):
        with tempfile.TemporaryDirectory(prefix="native-contract-model-") as directory:
            output = Path(directory)
            report = explore(output=output, mutant=mutant)
            saved = json.loads((output / "report.json").read_text())
            self.assertEqual(report, saved)
            return report

    def assert_unexpected_witnesses(self, report, expected):
        self.assertEqual(report["unexpectedMutantViolations"], expected)
        self.assertEqual(set(report["unexpectedMutantWitnesses"]), set(expected))
        for invariant, witness in report["unexpectedMutantWitnesses"].items():
            replayed = replay_trace(witness["trace"], mutant=report["mutant"], stop_on_target=False)
            self.assertIn(invariant, replayed["violations"])
            self.assertEqual(replayed["state"], witness["finalState"])

    def test_each_good_reachable_state_satisfies_invariants(self):
        report = self._explore()

        self.assertEqual(report["classification"], "PASS")
        self.assertGreater(report["invariantChecks"]["statesExamined"], 0)
        self.assertEqual(report["invariantChecks"]["violations"], [])

    def test_good_model_has_required_nonvacuity_witnesses(self):
        report = self._explore()
        required = {
            "APP-02-success-after-logout",
            "APP-03-failure-after-logout",
            "APP-04-old-success-after-login-b",
            "APP-05-old-failure-after-login-b",
            "duplicate-delivery",
            "queued-logout-during-pause",
            "fault-retry-cleanup",
            "restart-bootstrap-cleanup",
        }

        self.assertTrue(required <= set(report["witnesses"]))
        for name in required:
            witness = report["witnesses"][name]
            self.assertTrue(witness["trace"], name)
            self.assertIsNone(witness.get("violation"), name)
            replayed = replay_trace(witness["trace"])
            self.assertEqual(replayed["violations"], [], name)
            self.assertEqual(replayed["state"], witness["finalState"], name)
            self.assertEqual(replay_coverage_witness(name, witness)["coverage"], name)

    def test_coverage_replay_rejects_forged_state_and_nonwitness_trace(self):
        report = self._explore()
        witness = json.loads(json.dumps(report["witnesses"]["APP-02-success-after-logout"]))
        witness["finalState"]["physicalStore"] = "A1"

        with self.assertRaises(ValueError):
            replay_coverage_witness("APP-02-success-after-logout", witness)

        witness = json.loads(json.dumps(report["witnesses"]["APP-02-success-after-logout"]))
        witness["trace"] = witness["trace"][:-1]
        with self.assertRaises(ValueError):
            replay_coverage_witness("APP-02-success-after-logout", witness)

    def test_model_reports_finite_boundary_without_liveness_claim(self):
        report = self._explore()

        self.assertEqual(
            report["bounds"],
            {
                "dequeuedCommands": 6,
                "uiRevisions": 12,
                "owners": 2,
                "epochs": 3,
                "requestIdsPerOwner": 2,
                "queuedCommands": 2,
                "currentSlots": 1,
                "retainedOldSlots": 1,
                "replaysPerSlot": 1,
            },
        )
        self.assertFalse(report["claims"]["unboundedLiveness"])
        self.assertFalse(report["claims"]["arbitraryNativeRefinement"])
        self.assertTrue(report["coverageBoundary"])
        self.assertTrue(report["searchComplete"])
        self.assertFalse(report["limitReached"])

    def test_search_limit_never_claims_exhaustive_coverage(self):
        with tempfile.TemporaryDirectory(prefix="native-contract-model-limit-") as directory:
            # Populate the normal-bound cache first; a later tighter bound must be a distinct search.
            explore(output=Path(directory) / "normal-bound")
            with patch.object(integration_model, "MAX_STATES", 1):
                report = explore(output=Path(directory) / "limited")

        self.assertEqual(report["classification"], "INCONCLUSIVE")
        self.assertFalse(report["searchComplete"])
        self.assertTrue(report["limitReached"])
        self.assertFalse(report["coverageExhaustiveWithinBound"])

    def test_unconditional_success_commit_mutant_has_I2_or_I3_witness(self):
        report = self._explore(mutant="unconditional-success-commit")

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assert_unexpected_witnesses(report, ["I7", "I8"])
        self.assertIn(report["counterexample"]["invariant"], {"I2", "I3", "I4"})
        self.assertTrue(any("Deliver(" in action for action in report["counterexample"]["trace"]))
        trace = report["counterexample"]["trace"]
        deliver_start = next(i for i, action in enumerate(trace) if action.startswith("begin(Deliver("))
        self.assertGreater(deliver_start, 0)
        replayed = replay_trace(report["counterexample"]["trace"], mutant="unconditional-success-commit")
        self.assertIn(report["counterexample"]["invariant"], replayed["violations"])
        self.assertEqual(replayed["state"], report["counterexample"]["finalState"])

    def test_revision_bound_is_terminal_and_epoch_bound_rejects_logout_without_mutation(self):
        from dataclasses import replace

        terminal = replace(integration_model.initial_state(), revision=integration_model.BOUNDS["uiRevisions"])
        self.assertEqual(integration_model.enabled_actions(terminal), [])

        exhausted = replace(
            integration_model.initial_state(),
            health="Ready",
            managed="Authenticated",
            epoch=integration_model.BOUNDS["epochs"] - 1,
            epoch_count=integration_model.BOUNDS["epochs"],
            physical_store="A0",
            store_observation="A0",
            verified_store="A0",
            view_phase="SignedIn",
            view_account="A",
            view_version=0,
        )
        following = integration_model._begin_command(exhausted, "Logout", None)

        self.assertEqual(following.epoch, exhausted.epoch)
        self.assertEqual(following.pending_status, "RejectedExhausted")
        self.assertIsNone(following.pending_store)
        self.assertEqual(following.managed, exhausted.managed)

    def test_reentrant_consumer_mutant_has_I1_or_I3_witness(self):
        report = self._explore(mutant="reentrant-consumer")

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assert_unexpected_witnesses(report, [])
        self.assertIn(report["counterexample"]["invariant"], {"I1", "I3"})
        self.assertTrue(any(action.startswith("dequeue(") for action in report["counterexample"]["trace"]))
        self.assertIn("arm(store)", report["counterexample"]["trace"])
        self.assertEqual(len(report["counterexample"]["finalState"]["runningCommands"]), 2)
        self.assertEqual(report["counterexample"]["finalState"]["pausedAt"], "store")
        replayed = replay_trace(report["counterexample"]["trace"], mutant="reentrant-consumer")
        self.assertIn(report["counterexample"]["invariant"], replayed["violations"])
        self.assertEqual(replayed["state"], report["counterexample"]["finalState"])

    def test_duplicate_deferred_clear_mutant_has_I4_witness(self):
        report = self._explore(mutant="duplicate-deferred-clear")

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assert_unexpected_witnesses(report, ["I2"])
        self.assertEqual(report["counterexample"]["invariant"], "I4")
        self.assertIn("deferredClear(old-logout)", report["counterexample"]["trace"])
        replayed = replay_trace(report["counterexample"]["trace"], mutant="duplicate-deferred-clear")
        self.assertIn("I4", replayed["violations"])
        self.assertEqual(replayed["state"], report["counterexample"]["finalState"])

    def test_unverified_publish_mutant_has_I6_witness(self):
        report = self._explore(mutant="unverified-publish")

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assert_unexpected_witnesses(report, ["I3"])
        self.assertEqual(report["counterexample"]["invariant"], "I6")
        self.assertIn("publish(SignedIn)", report["counterexample"]["trace"])
        replayed = replay_trace(report["counterexample"]["trace"], mutant="unverified-publish")
        self.assertIn("I6", replayed["violations"])
        self.assertEqual(replayed["state"], report["counterexample"]["finalState"])

    def test_failed_clear_ack_mutant_has_I8_witness(self):
        report = self._explore(mutant="failed-clear-ack")

        self.assertEqual(report["classification"], "SEMANTIC_FAIL")
        self.assertEqual(report["counterexample"]["invariant"], "I8")
        self.assert_unexpected_witnesses(report, ["I3", "I5"])
        self.assertIn("receipt(Logout,Completed)", report["counterexample"]["trace"])
        replayed = replay_trace(report["counterexample"]["trace"], mutant="failed-clear-ack")
        self.assertIn("I8", replayed["violations"])
        self.assertEqual(replayed["state"], report["counterexample"]["finalState"])

    def test_logout_followed_by_failed_or_successful_login_uses_current_authority(self):
        prefix = [
            "enqueue(Bootstrap)", "dequeue(Bootstrap)", "begin(Bootstrap)", "store(success)",
            "publish(SignedOut)", "receipt(Bootstrap,Completed)",
            "enqueue(Login(A))", "dequeue(Login(A))", "begin(Login(A))", "store(success)",
            "publish(SignedIn)", "receipt(Login(A),Completed)",
            "enqueue(Logout)", "dequeue(Logout)", "begin(Logout)", "publish(SigningOut)",
            "reduce(Logout)", "store(success)", "publish(SignedOut)", "receipt(Logout,Completed)",
        ]
        failed_login = replay_trace(prefix + [
            "enqueue(Login(B))", "dequeue(Login(B))", "begin(Login(B))", "store(failBefore)",
            "publish(FaultLocked)", "receipt(Login(B),FaultLocked)",
        ])
        successful_login = replay_trace(prefix + [
            "enqueue(Login(B))", "dequeue(Login(B))", "begin(Login(B))", "store(success)",
            "publish(SignedIn)", "receipt(Login(B),Completed)",
        ])

        self.assertEqual(failed_login["violations"], [])
        self.assertEqual(failed_login["state"]["physicalStore"], "Absent")
        self.assertEqual(failed_login["state"]["health"], "FaultLocked")
        self.assertEqual(successful_login["violations"], [])
        self.assertEqual(successful_login["state"]["physicalStore"], "B0")
        self.assertEqual(successful_login["state"]["view"]["account"], "B")


if __name__ == "__main__":
    unittest.main()
