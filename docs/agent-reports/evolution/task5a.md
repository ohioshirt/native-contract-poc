# Task 5A / 6A managed evaluator handoff

Display note: trailing spaces in compiler diagnostic excerpts are trimmed for Markdown; original command logs under reports/evolution are unchanged.

Status: evaluator implementation is ready for independent review before freeze. Native histories, external native API probes and native owner mutations have NOT_RUN evidence until native implementations/runners are added. No full native gate result is claimed. No staging, commits, contract/oracle changes or native source changes were made.

## Delivered protected inputs

- verification/linearizability.py and test_linearizability.py: independent expected-operation membership, exact metadata, globally unique positive timestamps, every real-time predecessor edge, phase/dependency edges, real emitted token provenance, coherent complete snapshots, full oracle results, and bounded memoized search. A well-formed impossible history is FAIL; malformed/incomplete history is INVALID_HISTORY; search/coverage bounds are INCONCLUSIVE. CLI exit 0 is reserved for PASS.
- verification/numeric_model.py and test_numeric_model.py: independently reduced JSON row rules, two owners and IDs 1..3, exhaustive issued-token successors, ghost issued-ID sets, full-step oracle correspondence and concrete reset-on-Logout/owner-check-removed counterexamples. Production signed64 schema remains unchanged.
- verification/managed-workload.json, docs/experiments/managed-history-format.md and managed-native-brief.md: fixed public source APIs, input/output schema, native caller recorder rules, bounded overlap trials and stable owner mutation anchors. Frozen scenarios cover same-number legitimate foreign tokens for both response kinds, Logout versus success/failure, stale responses after a new request, simultaneous expiration and snapshots, MAX exhaustion after Logout, and the final two IDs. Every setup and snapshot is recorded.
- verification/managed_tools.py, managed_api.py, managed_mutations.py, managed_verify.py and test_managed_evaluator.py; verification/managed-mutation-matrix.json; verification/managed-api/swift/{positive,constructor,owner,session,mutation}.swift and equivalent kotlin .kt fixtures. Positive probes are separate externally compiled source clients. Negative probe success requires expected access/mutation diagnostics after positive compile/runtime success. Kotlin positive probe also attempts a mutable-list cast and verifies immutable effects.
- scripts/managed-verify.sh; scripts/verify.sh integration; README.md and formal/README.md document facade versus low-level assumptions, finite bounds, tracked approved design/plan and the non-benchmark status of this run.

Native commands are frozen in the brief: Swift ManagedHistoryRunner; Kotlin java main nativecontract.async.ManagedHistoryRunnerKt through the existing async-library installDist classpath. Missing new runner detection checks the actual Kotlin main class in installed jars. The gate never substitutes old async traces for managed histories. No extra dependency is required.

## Evidence and limitations

All commands below ran in /Users/shigeo/.codex/worktrees/b195/native-contract-poc. Logs are under reports/evolution/task5a. Tests followed a stub RED, implementation, GREEN cycle. Initial RED was a real assertion failure against NOT_RUN stubs, rather than import errors. Fixture patch tests require exactly one mutation anchor and preserve the rejection body. Process timeout tests kill the owned subprocess group and retain infrastructure evidence.

The managed gate before native implementation returned exit 2 with overall NOT_RUN; numeric model ran, while both native history/API/mutation stages explicitly reported NOT_RUN. Actual native mutant builds and API compiler diagnostics remain required after freeze. The compile probe evaluator distinguishes unrelated compiler failure from access rejection; owner mutation build/runtime failure is infrastructure, and only successful execution plus a semantic FAIL in the deterministic foreign-same-id history qualifies.

A whole Python discovery was run while other workers were editing. It is a non-authoritative in-progress snapshot, not final acceptance. It reported future native-anchor failures from test_async and unfinished protocol ledger/raw-evidence checks from test_change_protocol. These were communicated to the controller; no other worker's source was changed. The full suite will be rerun by the controller after implementation is stable. Formal test failure diagnostic prints in its raw tail belong to negative-control tests; this worker did not run TLC or the full native gate.

Final test self-review isolated future-token provenance from timestamp-uniqueness failures: the test swaps distinct stamps and requires the exact future/unreturned-producer diagnostic.

Self-review checked the R3 inventory/provenance/real-time rules, R4 external probes/native mutation distinction, R5 independent finite transition implementation and explicit bounds, and scripts/verify.sh connection. Bounds and missed overlap are always non-PASS. The retained owner identity and atomic actor/monitor claims still depend on native implementation/review; these evaluator files do not prove those implementations before they exist.

## Commands and raw tails

Command: `python3 -m unittest verification.test_linearizability -v`

Exit: 1 (expected RED)

Raw tail (checker-red.log):
```
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_linearizability.py", line 72, in test_whole_operation_deletion_is_invalid
    self.assertEqual(self.check()['verdict'], 'INVALID_HISTORY')
AssertionError: 'NOT_RUN' != 'INVALID_HISTORY'
- NOT_RUN
+ INVALID_HISTORY


----------------------------------------------------------------------
Ran 20 tests in 0.016s

FAILED (failures=21)
```

Command: `python3 -m unittest verification.test_numeric_model -v`

Exit: 1 (expected RED)

Raw tail (model-red.log):
```
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_numeric_model.py", line 16, in test_reset_mutant_has_concrete_allocator_counterexample
    self.assertEqual(result['verdict'], 'COUNTEREXAMPLE')
AssertionError: 'NOT_RUN' != 'COUNTEREXAMPLE'
- NOT_RUN
+ COUNTEREXAMPLE


----------------------------------------------------------------------
Ran 5 tests in 0.001s

FAILED (failures=3)
```

Command: `python3 -m unittest verification.test_managed_evaluator -v`

Exit: 1 (expected RED)

Raw tail (drivers-red.log):
```
======================================================================
FAIL: test_process_timeout_is_infrastructure (verification.test_managed_evaluator.ManagedEvaluatorTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_managed_evaluator.py", line 41, in test_process_timeout_is_infrastructure
    self.assertTrue(result['timedOut'])
AssertionError: False is not true

----------------------------------------------------------------------
Ran 6 tests in 0.002s

FAILED (failures=5)
```

Command: `python3 -m unittest verification.test_linearizability verification.test_numeric_model verification.test_managed_evaluator -v`

Exit: 0

Raw tail (targeted-final.log):
```
test_unknown_mutant_refused (verification.test_numeric_model.NumericModelTests) ... ok
test_api_negative_diagnostic_is_specific (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_exit_one_mutant_build_failure_not_semantic_detection (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_frozen_anchors_patch_once_and_preserve_branch_body (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_gate_aggregation_never_passes_skips (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_native_missing_is_not_run (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_process_timeout_is_infrastructure (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok

----------------------------------------------------------------------
Ran 31 tests in 0.115s

OK
```

Command: `bash scripts/managed-verify.sh reports/evolution/task5a/managed-not-run`

Exit: 2 (expected NOT_RUN)

Raw tail (managed-not-run.log):
```
        },
        {
          "id": "kotlin-owner-guard",
          "platform": "kotlin",
          "verdict": "NOT_RUN",
          "reason": "managed native source missing"
        }
      ]
    }
  },
  "limits": "2 owners, IDs 1..3 finite model; completed histories <=16 operations; no unbounded refinement proof"
}
```

Command: `python3 -m unittest discover -s verification -p 'test_*.py' -v`

Exit: 1 (in-progress snapshot only)

Raw tail (python-tests.log):
```
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 239, in test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch
    with self.assertRaises(protocol.ProtocolError): self.run_stage()
AssertionError: ProtocolError not raised

----------------------------------------------------------------------
Ran 104 tests in 7.424s

FAILED (failures=15, errors=17)
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

Command: `bash -n scripts/verify.sh scripts/managed-verify.sh`

Exit: 0. Raw output is empty.

Full discovery failure names (as reported, no manual totaling):

```
ERROR: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.manifest-digest', kind='existing')
ERROR: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.manifest-digest', kind='directory')
ERROR: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.budget.lock', kind='dangling')
ERROR: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.budget.lock', kind='existing')
ERROR: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.budget.lock', kind='directory')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='command.json', kind='replaced')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='command.json', kind='symlink')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='command.json', kind='directory')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stdout.log', kind='replaced')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stdout.log', kind='symlink')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stdout.log', kind='directory')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stderr.log', kind='replaced')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stderr.log', kind='symlink')
ERROR: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stderr.log', kind='directory')
ERROR: test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (kind='result-symlink')
ERROR: test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (kind='result-directory')
ERROR: test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (kind='attempt-file')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='swift-ignores-refreshing-logout')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='swift-omits-logout-clear-credentials')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='swift-retains-logout-pending')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='swift-resets-refreshing-logout-counter')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='kotlin-ignores-refreshing-logout')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='kotlin-omits-logout-clear-credentials')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='kotlin-retains-logout-pending')
FAIL: test_all_native_patch_sites_are_unique (test_async.AsyncNativeMutationAnchorTests) (case='kotlin-resets-refreshing-logout-counter')
FAIL: test_command_record_must_agree_with_frozen_argv_even_if_hash_is_updated (test_change_protocol.ChangeProtocolTests)
FAIL: test_empty_raw_logs_are_bound_and_valid (test_change_protocol.ChangeProtocolTests)
FAIL: test_ledger_symlinks_and_nonregular_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (name='.manifest-digest', kind='dangling')
FAIL: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='command.json', kind='missing')
FAIL: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stdout.log', kind='missing')
FAIL: test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check (test_change_protocol.ChangeProtocolTests) (name='stderr.log', kind='missing')
FAIL: test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (test_change_protocol.ChangeProtocolTests) (kind='attempt-symlink')
```

## Evaluator revision: API portability fix 1

Controller authorized this protected evaluator revision only after candidate-full-01 ended INFRA_FAILURE and preserved reports/evolution/candidate-r1-source.tar.gz. Revision r1 verdicts require invalidation; controller owns scoped review, r2 freeze and re-evaluation. No native source, oracle, contract, workload, mutation driver or guide was changed by this fix. No whole suite or full gate was run here.

Root causes were confirmed read-only before editing. The actual Swift .build/debug symlink resolves .build/out/Products/Debug under the Xcode backend: public .swiftmodule directories and aggregate NativeContract.o/AsyncNativeContract.o objects exist directly under debug, while the conventional Modules and target.build directories do not. The API evaluator had assumed only conventional SwiftPM placement. The new swift_artifacts helper supports both layouts and requires modules and objects for both imported public targets. External client module separation remains unchanged; no testable imports are introduced.

Kotlin RefreshRequest has a private constructor(requestId: Long, owner: Any). The old probe omitted owner and produced only a missing-argument diagnostic. The corrected probe supplies Any(), so the actual compiler reports private-constructor access rejection. Diagnostic policy remains strict: missing-argument output alone is not access evidence. Swift's constructor log includes an explicit initializer-inaccessible diagnostic as well as an arity diagnostic; the former is the accepted evidence.

Exact changed files for this evaluator revision:

- verification/managed_api.py
- verification/managed-api/kotlin/constructor.kt
- verification/test_managed_evaluator.py
- docs/agent-reports/evolution/task5a.md (this append)

Focused regressions cover conventional SwiftPM artifacts, Xcode product artifacts through the debug symlink, a missing required object, and refusal of arity-only constructor diagnostics. The two new layout checks first failed against a NOT_RUN helper stub, then succeeded after the layout implementation. Actual positive compile/runtime probes and every negative access/mutation probe were then executed against existing artifacts for both languages. Individual compiler argv/cwd/time/exit records and complete stdout/stderr remain under reports/evolution/task5a/api-fix1/{swift,kotlin}/*.command.json and *.log.

Command: `python3 -m unittest verification.test_managed_evaluator -v`

Exit: 1 (expected layout RED)

Raw tail:
```
======================================================================
FAIL: test_swift_xcode_product_layout_is_detected (verification.test_managed_evaluator.ManagedEvaluatorTests)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_managed_evaluator.py", line 42, in test_swift_xcode_product_layout_is_detected
    self.assertEqual(managed_api.swift_artifacts(root),(debug,objects))
AssertionError: None != (PosixPath('/var/folders/hk/75z5bqzs7cx5s[271 chars]o')])

----------------------------------------------------------------------
Ran 9 tests in 0.069s

FAILED (failures=2)
```

Command: `python3 -m unittest verification.test_managed_evaluator -v`

Exit: 0

Raw tail:
```
test_exit_one_mutant_build_failure_not_semantic_detection (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_frozen_anchors_patch_once_and_preserve_branch_body (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_gate_aggregation_never_passes_skips (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_native_missing_is_not_run (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_process_timeout_is_infrastructure (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_swift_conventional_layout_is_detected (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok
test_swift_xcode_product_layout_is_detected (verification.test_managed_evaluator.ManagedEvaluatorTests) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.062s

OK
```

Command: `python3 -m verification.managed_api --platform swift --output reports/evolution/task5a/api-fix1/swift`

Exit: 0

Raw tail:
```
PASS
```

Command: `python3 -m verification.managed_api --platform kotlin --output reports/evolution/task5a/api-fix1/kotlin`

Exit: 0

Raw tail:
```
PASS
```

Raw swift positive-run stdout tail (`reports/evolution/task5a/api-fix1/swift/positive-run.stdout.log`):
```
External API emitted-token reuse: PASS
```

Raw swift constructor stderr tail (`reports/evolution/task5a/api-fix1/swift/constructor.stderr.log`):
```
1 | import AsyncNativeContract
2 | func forbidden() { _ = RefreshRequest(requestId: 1) }
  |                                                   `- error: missing argument for parameter 'owner' in call
3 |

AsyncNativeContract.RefreshRequest.init:2:13: note: 'init(requestId:owner:)' declared here
1 | class RefreshRequest {
2 | fileprivate init(requestId: Int64, owner: AsyncNativeContract.RequestOwner)}
  |             `- note: 'init(requestId:owner:)' declared here
3 |
```

Raw kotlin positive-run stdout tail (`reports/evolution/task5a/api-fix1/kotlin/positive-run.stdout.log`):
```
External API emitted-token reuse and immutable effects: PASS
```

Raw kotlin constructor stderr tail (`reports/evolution/task5a/api-fix1/kotlin/constructor.stderr.log`):
```
verification/managed-api/kotlin/constructor.kt:2:19: error: cannot access 'constructor(requestId: Long, owner: Any): RefreshRequest': it is private in 'nativecontract.async.RefreshRequest'.
fun forbidden() { RefreshRequest(1L, Any()) }
                  ^^^^^^^^^^^^^^
```

Swift constructor access diagnostic, raw first six lines of the same captured compiler stderr:
```
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/constructor.swift:2:24: error: 'RefreshRequest' initializer is inaccessible due to 'fileprivate' protection level
1 | import AsyncNativeContract
2 | func forbidden() { _ = RefreshRequest(requestId: 1) }
  |                        `- error: 'RefreshRequest' initializer is inaccessible due to 'fileprivate' protection level
3 |

```
