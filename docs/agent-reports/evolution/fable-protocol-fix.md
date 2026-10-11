# Fable protocol verdict fix

Status: implemented; ready for Fable scoped re-review. Worktree: `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`. No full suites, subagents, staging or commits. No actual experiment manifest was frozen or reused; the controller will freeze revision r3 after review.

Fable identified that `check --result` successfully verified a record then unconditionally returned PASS, causing CLI exit 0 even for a bound non-PASS evaluation. The code path was verified and reproduced through actual subprocess CLI regressions before editing production code.

## Concise change

- `verification/change_protocol.py`: after validating bindings and recomputing the stored evaluation verdict, return that verdict as both `classification` and `resultClassification`, plus `bindingClassification: PASS`. Existing CLI status mapping now returns 0 only for evaluation PASS, 1 for SEMANTIC_FAIL, and 2 for INFRA_FAILURE/NOT_RUN. An invalid result binding returns infrastructure failure without trusted resultClassification or binding PASS. Source-only check remains source-integrity PASS.
- `verification/test_change_protocol.py`: actual-CLI controls for bound PASS/SEMANTIC_FAIL/INFRA_FAILURE/NOT_RUN, invalid raw evidence binding, and source-only integrity checks. Existing source, ledger, artifact and raw evidence protections remain covered by the owned targeted suite.
- `docs/experiments/change-protocol.md`: documents classification fields, CLI statuses and source-only check limits.
- This report and raw command/log evidence under `reports/evolution/fable-protocol-fix/`.

## Exact commands and raw tails

Commands ran in the authorized managed worktree using require_escalated execution. The RED log contains expected wrong-exit failures and absent-new-field errors; it is preserved without claiming success.

```sh
python3 -m unittest verification.test_change_protocol.ChangeProtocolTests.test_cli_result_check_preserves_bound_evaluation_verdict verification.test_change_protocol.ChangeProtocolTests.test_cli_result_check_rejects_invalid_evidence_binding verification.test_change_protocol.ChangeProtocolTests.test_cli_check_without_result_reports_source_integrity_only -v > reports/evolution/fable-protocol-fix/red.log 2>&1
tail -n 10 reports/evolution/fable-protocol-fix/red.log
```

```text
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 298, in test_cli_result_check_preserves_bound_evaluation_verdict
    self.assertEqual(code,exit_code)
AssertionError: 0 != 2

----------------------------------------------------------------------
Ran 3 tests in 1.110s

FAILED (failures=3, errors=2)
```

```sh
python3 -m unittest verification.test_change_protocol -v > reports/evolution/fable-protocol-fix/targeted-green.log 2>&1
tail -n 10 reports/evolution/fable-protocol-fix/targeted-green.log
```

```text
test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_protected_edit_add_delete_and_out_of_scope_new_source (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_semantic_requires_report_and_native_mismatch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass (verification.test_change_protocol.ChangeProtocolTests) ... ok

----------------------------------------------------------------------
Ran 19 tests in 4.243s

OK
```

No unresolved issue identified within this scoped fix. The inherited manifest/source/artifact/evidence checks were preserved. Bound infrastructure/NOT_RUN controls use complete validated reports so they exercise successful binding independently of the evaluation failure. Missing or malformed required evidence remains a binding failure.
