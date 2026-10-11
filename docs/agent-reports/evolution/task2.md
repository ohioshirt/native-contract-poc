# Task 2 — contract v4 and independent gates

Status: implementation ready for scoped review; native mutation runs deferred until native workers implement frozen anchors. No native source, protocol, checker/model, scripts/verify.sh, staging or commit changes were made by Task 2.

## Behavior and interfaces

The contract is v4 with `async.logoutWhileRefreshing=invalidate`. Only async Refreshing × Logout differs from the core action table: Unauthenticated, cleared pending, exactly ClearCredentials, always guard. All core fields/rows equal baseline 8458f66 apart from the version field; the historical v3 ignore profile validates with the current schema. `reports/evolution/task2/contract-compatibility.log` records the executed equality assertions and validator calls.

`verification.async_contract.step(spec,state,pending,next_id,event,*,request_id_max=None)` returns state,pendingRequestId,nextRequestId,effects,rejection. Event is a normalized object. The default bound remains production signed64; max=3 is an explicitly separate finite instantiation for the numeric model. The low-level wire format retains event,state,pendingRequestId,effects,rejection, omitting nextRequestId. The oracle delegates to step.

Independent `policy_errors` checks Logout invalidation, allocator preservation including exhaustion, repeated Logout, pending iff Refreshing, stale full-triple no-op, and atomic exhaustion without deriving expectations from row contents. TLA adds independent LogoutPolicy, positive fixed-point exploration, isolated exact ignored-Logout negative control and the existing isolated stale-response control. Parsed negative traces must match the exact injected fault.

Frozen low-level snippets live in `docs/experiments/native-anchors.md`: INSERT the complete Swift refreshing Logout case before the general event case; INSERT the Kotlin Logout branch inside Refreshing; PRESERVE existing response guards/reset anchor fragments without inserting them again. Every added mutation is defined for both languages: ignored Logout, omitted ClearCredentials, retained pending ID, allocator reset. Original stale/accepted-Logout controls remain. The existing native mutation driver is unchanged; builds remain infrastructure failures.

`AsyncMutationFixtureTests` applies every matrix patch once to concatenated frozen snippets. `AsyncNativeMutationAnchorTests.test_all_native_patch_sites_are_unique` remains an unskipped check against actual native sources; it must run after Luna implements anchors. Native mutation kills have not been run or claimed. Managed owner-guard anchors/mutations belong to the separate Task 5/6 guide and driver.

## Executed evidence

All evidence below is preparatory; the controller must repeat preserved-runner RED through the frozen evaluator manifest before native execution. Commands ran from `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`.

### Initial TDD RED

Command:

```sh
python3 -m unittest verification.test_async.AsyncContractTests.test_logout_invalidation_contract_and_historical_ignore verification.test_async.AsyncContractTests.test_step_logout_preserves_allocator_and_canceled_replies verification.test_async.AsyncContractTests.test_logout_policy_rejects_faults_independently_of_transition_rows -v
```

Raw tail (`reports/evolution/task2/tdd-red.log`):

```text
?                      ^^^^

   'rejection': None,
-  'state': 'Refreshing'}
+  'state': 'Unauthenticated'}

----------------------------------------------------------------------
Ran 3 tests in 0.001s

FAILED (failures=1, errors=2)
```

### Owned Python checks

Command:

```sh
python3 -m unittest verification.test_async.AsyncContractTests verification.test_async.AsyncFormalTraceTests verification.test_async.AsyncMutationFixtureTests verification.test_async.AsyncRunnerFailureTests verification.test_async.AsyncMutationSkipTests -v
```

Raw tail (`reports/evolution/task2/python-final.log`):

```text
test_tlc_timeout_evidence_is_normalized_and_persisted (verification.test_async.AsyncFormalTraceTests) ... ok
test_matrix_patches_apply_once_to_frozen_low_level_fixtures (verification.test_async.AsyncMutationFixtureTests) ... ok
test_crash_and_signal_remain_infrastructure_with_raw_status_and_stderr (verification.test_async.AsyncRunnerFailureTests) ... ok
test_malformed_successful_outputs_create_fail_report_and_direct_fail (verification.test_async.AsyncRunnerFailureTests) ... ok
test_skip_marks_every_case_not_run_and_clears_owned_stale_results (verification.test_async.AsyncMutationSkipTests) ... ok

----------------------------------------------------------------------
Ran 20 tests in 4.142s

OK
```

### Formal gate

Command:

```sh
python3 -m verification.async_formal --output reports/evolution/task2/async-formal
```

Raw tail (`reports/evolution/task2/formal-command.log`):

```text
PASS: async TLC; 19 distinct states; validated StaleResponseSafety and LogoutPolicy counterexamples
```

### Old native full semantic RED

Command:

```sh
python3 -m verification.async_verify --output reports/evolution/task2/old-native-full-red --swift reports/evolution/baseline-native/AsyncTraceRunner --kotlin reports/evolution/baseline-native/async-library/bin/async-library
```

Raw tail (`reports/evolution/task2/old-native-full-red-command.log`):

```text
kotlin: logout-after-final-allocation-preserves-exhaustion step 2: pendingRequestId mismatch
kotlin: logout-after-final-allocation-preserves-exhaustion step 2: effects mismatch
kotlin: logout-after-final-allocation-preserves-exhaustion step 3: state mismatch
kotlin: logout-after-final-allocation-preserves-exhaustion step 4: state mismatch
kotlin: logout-after-final-allocation-preserves-exhaustion step 5: effects mismatch
kotlin: refreshing-logout-invalidate step 2: state mismatch
kotlin: refreshing-logout-invalidate step 2: pendingRequestId mismatch
kotlin: refreshing-logout-invalidate step 2: effects mismatch
kotlin: refreshing-logout-invalidate step 3: state mismatch
FAIL: 19624 scenarios, 94864 steps; swift=FAIL, kotlin=FAIL, differential=PASS
```

The old runners both executed successfully (runner exit 0); comparator exit 1 is semantic native mismatch with valid schema. Their agreement yields differential PASS while each independently fails the v4 oracle. Concrete mismatches include Refreshing Logout and Logout after allocating signed64 MAX. The focused normalized-input RED is retained separately under `old-native-red`.

`old-native-provenance.json` records baseline commit, actual tool versions, exact commands, all distribution/binary SHA-256 values before/after, current valid spec/policy, comparator exits and verdicts. Values match the controller's `docs/agent-reports/evolution/baseline-native-hashes.json`, and all preserved artifacts remain unchanged. Native binaries were not rebuilt.

An earlier shorthand-string input attempt caused runner errors and is retained under `old-native-infra-unormalized`; it is INFRA_FAILURE, never counted as semantic RED. Input was normalized before the focused retry; the final full RED uses the default normalized exhaustive generator. A zsh read-only `status` variable prevented initial exit-code capture; it was replaced by `task2_exit` and the commands were rerun to capture real exits.

### Actual TLC raw stdout tails

Command (`positive-tlc`, subprocess exit 0):

```sh
java -cp /Users/shigeo/.codex/worktrees/b195/native-contract-poc/.formal-cache/tla2tools-1.7.4.jar tlc2.TLC -workers 1 -config /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/positive/AsyncSession.cfg /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/positive/AsyncSession.tla
```

```text
Computing initial states...
Finished computing initial states: 1 distinct state generated at 2026-10-12 01:08:57.
Model checking completed. No error has been found.
  Estimates of the probability that TLC did not check all reachable states
  because two distinct states had the same fingerprint:
  calculated (optimistic):  val = 9.6E-17
112 states generated, 19 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 4.
The average outdegree of the complete state graph is 1 (minimum is 0, the maximum 7 and the 95th percentile is 7).
Finished in 00s at (2026-10-12 01:08:57)
```

Command (`negative-tlc`, subprocess exit 12):

```sh
java -cp /Users/shigeo/.codex/worktrees/b195/native-contract-poc/.formal-cache/tla2tools-1.7.4.jar tlc2.TLC -workers 1 -config /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/negative/AsyncSession.cfg /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/negative/AsyncSession.tla
```

```text
/\ rejection = "__none__"
/\ effects = <<>>
/\ responseClass = "STALE"
/\ event = "RefreshSucceeded"
/\ previousPending = TRUE

48 states generated, 17 distinct states found, 7 states left on queue.
The depth of the complete state graph search is 4.
The average outdegree of the complete state graph is 1 (minimum is 0, the maximum 6 and the 95th percentile is 6).
Finished in 00s at (2026-10-12 01:08:58)
```

Command (`negative-logout-tlc`, subprocess exit 12):

```sh
java -cp /Users/shigeo/.codex/worktrees/b195/native-contract-poc/.formal-cache/tla2tools-1.7.4.jar tlc2.TLC -workers 1 -config /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/negative-logout/AsyncSession.cfg /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/task2/async-formal/negative-logout/AsyncSession.tla
```

```text
/\ rejection = "__none__"
/\ effects = <<>>
/\ responseClass = "NA"
/\ event = "Logout"
/\ previousPending = TRUE

45 states generated, 14 distinct states found, 4 states left on queue.
The depth of the complete state graph search is 4.
The average outdegree of the complete state graph is 1 (minimum is 0, the maximum 6 and the 95th percentile is 6).
Finished in 00s at (2026-10-12 01:08:59)
```

### In-progress full Python snapshot (non-authoritative)

A one-time discovery run occurred while other workers were editing. It is not final integration evidence and will not be repeated by Task 2:

```sh
python3 -m unittest discover -s verification -p 'test_*.py' -v
```

Raw tail (`reports/evolution/task2/python-discovery.log`):

```text


----------------------------------------------------------------------
Ran 93 tests in 6.957s

FAILED (failures=11)
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

Failures were the deferred new native anchor checks and unrelated in-progress numeric tests: `test_exhaustive_finite_correspondence`, `test_owner_mutant_has_concrete_foreign_counterexample`, `test_reset_mutant_has_concrete_allocator_counterexample` returned NOT_RUN while that worker had not implemented the model. Printed formal failure lines are expected diagnostics of successful mocked negative tests; those test cases reported `ok` earlier in the log. No complete-suite PASS is claimed.

## Frozen owned input paths

- contract/specification.json
- contract/schema.json
- verification/contract.py
- verification/async_contract.py
- verification/test_async.py
- verification/async_formal.py
- formal/AsyncSession.tla
- verification/async-mutation-matrix.json
- docs/experiments/native-anchors.md

Existing dependent evaluator paths include verification/async_verify.py and scripts/async_mutations.py (unchanged by this task), plus contract loader/formal toolchain dependencies. Controller determines complete protected membership.

Limits: Boolean TLA correlation abstraction does not prove numeric allocation or native refinement. The finite numeric explorer and ownership/concurrent native gate are handled by other tasks. These results do not prove unbounded concurrency, transport cancellation or response authenticity at the low-level caller-serialized API.
