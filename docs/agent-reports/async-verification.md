# Async verification report

The verifier keeps the synchronous contract parser and 781-case gate intact. The v3 async profile is schema checked, then semantically checked for complete 15-row coverage, deterministic state/event pairs, guard/action coherence, pending iff Refreshing, signed64 ID bounds, monotonic non-reuse, agreement with each core row, and the explicit Refreshing × Logout ignore policy. `verification/async_contract.py` independently interprets those rows and compares complete wire objects, including input/output request IDs and ordered effect objects.

Input generation expands three simple events and two response event kinds across IDs 1 and 2, giving seven event variants at lengths 0 through 5, then appends named lifecycle and maximum-ID cases. The same vectors drive both installed runners. Named cases cover delayed old success/failure after a second request, an old response after accepted Logout and relogin, accepted Logout counter continuity, duplicate completion, unissued IDs, repeated login, ignored Refreshing Logout and signed64 maximum exhaustion.

Command: `bash scripts/async-verify.sh reports/async-worker`

Raw output:

```text
PASS: 19621 scenarios, 94842 steps; swift=PASS, kotlin=PASS, differential=PASS
```

Counterexample validation now checks variable closure, state/event/effect domains, predecessor continuity, legal CURRENT/STALE event classes, and the exact canonical row output for the injected stale `Apply`. Allocation rejection is accepted only for Authenticated × TokenExpired and must preserve state/pending with no effects. TLC timeout output bytes are decoded, with command, captured stdout/stderr and timeout status persisted before the formal failure report.

Successful runner output is separated into wire-shape validation and semantic comparison. Malformed JSON, wrong roots, missing/extra trace or step fields produce structured conformance FAIL for that language and direct FAIL; the report is still written. Nonzero exits and signals remain infrastructure failures with their numeric exit code, raw stdout file and stderr retained. Explicit `SKIP_MUTATIONS=1` marks both matrices `NOT_RUN`, clears stale owned case evidence, returns zero when other gates pass, and reports `INCOMPLETE`.

Command: `python3 -m unittest discover -s verification -p 'test_*.py' -v`

Raw final output (the four `FAIL: formal verification` diagnostics are intentional mocked failure-path fixtures in `test_formal.py`; the unittest process itself passed):

```text
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests) ... ok

----------------------------------------------------------------------
Ran 52 tests in 8.326s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

Command: `bash scripts/async-formal-verify.sh reports/async-formal-worker`

Raw output:

```text
PASS: async TLC; 19 distinct states; validated StaleResponseSafety counterexample
```

The pinned TLC 2.19 positive run generated 114 states, found 19 distinct states, and finished with 0 queued states at depth 4. The isolated stale-guard mutant exited with invariant status 12; its four-state counterexample was parsed and validated as a stale RefreshSucceeded transition changing the state while a request was pending. TLC output and the raw trace are in the owned `reports/async-formal-worker` evidence directory. The model tracks a pending Boolean and an abstract CURRENT/STALE relation. CURRENT assumes same-session routing and equality to the pending ID. Numeric ID allocation, exhaustion refinement, native refinement, concurrency, and liveness are outside this abstraction. The nondeterministic allocation rejection branch is atomic.

Command: `bash scripts/async-mutation-test.sh reports/async-mutations-worker`

Raw output:

```text
A-swift-accepts-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
B-kotlin-resets-counter-on-accepted-logout: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-accept-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'} actual={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
```

Each mutant used a disposable source copy. The unique source edits are specified in [async-mutation-matrix.json](../../verification/async-mutation-matrix.json); Swift's response-ID guard and Kotlin's response-ID guard are independently patched, while the counter-reset mutant inserts a reset only at the accepted Authenticated Logout site. Build/tool failures and signal exits are recorded as infrastructure failures, never as kills.

The canonical specification SHA-256 remains `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`.

## Final stale fault witness review

Negative mode now requires a nonempty execution and an actual final STALE response whose state, pending value, effects and rejection equal the exact injected canonical Apply row and violate stale no-op safety. Legal CURRENT, initial-only and stale no-op traces remain valid in ordinary mode but cannot qualify as the negative control.

Command: `python3 -m unittest verification.test_async.AsyncFormalTraceTests -v`

Raw output:

```text
test_formal_tool_failure_persists_metadata_and_failure_report (verification.test_async.AsyncFormalTraceTests) ... ok
test_formal_trace_restricts_response_class_and_rejection_to_legal_rows (verification.test_async.AsyncFormalTraceTests) ... ok
test_stale_negative_requires_exact_injected_canonical_response_row (verification.test_async.AsyncFormalTraceTests) ... ok
test_tlc_timeout_evidence_is_normalized_and_persisted (verification.test_async.AsyncFormalTraceTests) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.038s

OK
```

Command: `bash scripts/async-formal-verify.sh reports/async-formal-worker`

Raw output:

```text
PASS: async TLC; 19 distinct states; validated StaleResponseSafety counterexample
```

Command: `python3 -m unittest discover -s verification -p 'test_*.py' -v`

Raw final output:

```text
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests) ... ok

----------------------------------------------------------------------
Ran 51 tests in 8.763s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

The four trailing formal diagnostics are the existing mock failure-path fixtures in `test_formal.py`; the unittest command exited zero.

## Additional logout and numeric-boundary vectors

Added paired old-success/old-failure callbacks after an accepted Logout, relogin and a new request with pending ID 2. Added a seed at signed64 MAX-1 that allocates MAX-1 and MAX before atomic exhaustion, plus a seed at `2^53-1` that completes requests at both `2^53-1` and `2^53`. Focused assertions derive each expected trace from the canonical async rows and check exact effect IDs, stale preservation and final outcomes.

Command: `bash scripts/async-verify.sh reports/async-worker`

Raw output:

```text
PASS: 19621 scenarios, 94842 steps; swift=PASS, kotlin=PASS, differential=PASS
```

Command: `bash scripts/async-mutation-test.sh reports/async-mutations-worker`

Raw output:

```text
A-swift-accepts-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
B-kotlin-resets-counter-on-accepted-logout: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-accept-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'} actual={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
```

Command: `python3 -m unittest discover -s verification -p 'test_*.py' -v`

Raw final output:

```text
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests) ... ok

----------------------------------------------------------------------
Ran 52 tests in 8.326s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

The trailing formal messages are expected mock failure-path output; the test command exited zero. The canonical contract and native library APIs were not modified.
