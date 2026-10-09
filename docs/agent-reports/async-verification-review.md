# Async verification quality review

Current verdict after final scoped re-review: approved within the documented abstraction and serialized same-logical-session scope, subject to root's final gate/provenance confirmation. All reported Important findings are resolved. Original findings below are retained as history. Reviewed canonical v3, design/plan, oracle/comparator, async formal bridge/model, scripts/matrix, tests and worker/native reports. No native builds or full gates repeated. Only this review file was edited.

## Important: negative trace does not establish the injected transition

`verification/async_formal.py:163–166` accepts any final stale mutation from Refreshing, skipping canonical-row comparison and closure/rejection checks. A forged final `state="Unknown", pending=False, effects=("BogusFX",)` is accepted. Thus the named invariant/exit check is insufficient to substantiate the report's validated counterexample claim. Require the exact canonical response row's next state, pending action, ordered effects and no rejection under the deliberately bypassed guard. Validate event/class/state/effect domains and legal rejection allocation preconditions throughout the trace.

Targeted command executed:

```python
import copy,json
from pathlib import Path
from verification import async_formal as f
spec=json.loads(Path('contract/specification.json').read_text())
trace=f.parse_counterexample(Path('reports/async-formal-worker/negative-counterexample.txt').read_text())
bad=copy.deepcopy(trace);bad[-1]['state']='Unknown';bad[-1]['pending']=False;bad[-1]['effects']=('BogusFX',)
print('forged negative accepted:',f.validate_trace(bad,spec,stale_fault=True))
```

Raw output: `forged negative accepted: True`.

## Important: malformed runner output crashes the differential stage

`verification/async_verify.py:85–88` rereads successful runner outputs even after their JSON/shape has been rejected. Invalid JSON throws again; missing traces raises KeyError; malformed left-side traces can crash expected-side indexing. The normal conformance FAIL becomes infrastructure exit 2 and no final report is written. Preserve each runner's FAIL and always emit the report; guard direct comparison against structurally invalid documents. Exact source mutation status 0/1 discrimination must remain intact.

Executed cheap fake-runner probe (no native binaries): a temporary executable containing `#!/bin/sh` and `printf '{"oops":[]}'`, empty scenario input, passed as both `swift` and `kotlin` to `async_verify.run`. Raw output:

```text
malformed output diagnostic: KeyError 'traces'
final report exists: False
```

## Important: timeout loses formal evidence

`verification/async_formal.py:72–79` stores TimeoutExpired stdout/stderr directly. Python supplies bytes despite text=True; json.dumps then throws, so the intended timeout evidence artifact is absent. Main still exits nonzero, which prevents false PASS, but diagnostics and captured tool evidence are lost. Decode captured bytes explicitly, preserve timeout command/stdout/stderr, then fail with the correct timeout reason.

Executed mocked TimeoutExpired probe with `output=b'partial TLC evidence', stderr=b'timeout detail'` around `_run_tlc`:

```text
timeout diagnostic: TypeError Object of type bytes is not JSON serializable
timeout artifact exists: False
```

## Other corrections

- `scripts/verify.sh:61–66` turns explicit SKIP_MUTATIONS into overall FAIL, leaving its previous INCOMPLETE branch unreachable. Preserve the existing explicit-skip INCOMPLETE/exit-0 behavior for both mutation gates, while full non-skipped acceptance still requires both matrices. Its async skip diagnostic should say async gate, not core gate. This is a compatibility correction, not a false-PASS blocker.
- `async_verify._run:27–29` overwrites captured stderr and numeric exit with generic infrastructure text after a nonzero native exit. Keep raw numeric/signal status and native stderr; put classification/detail in separate metadata. It correctly avoids classifying crashes as mutation kills.
- `docs/agent-reports/async-verification.md` truncates canonical SHA by one trailing `f`; correct it. Remove duplicate shadowed `prepare_output` definition in async_formal for clarity.

## Scope and evidence assessment

The oracle derives behavior from the machine rows and does not read native implementations. The seven-symbol lengths 0..5 generator, named old/duplicate/unissued replies, accepted-Logout counter continuity and signed64 allocation/exhaustion case are present. Strict comparison checks IDs against bool/float aliases, exact fields and effect ordering. Core parser behavior is preserved with enum/schema extension and optional async validation; existing core tests/model remain in the full script. Mutation copies include contract/verification/ios/android, which suffice: load_contract imports contract validation, not formal source. Patch sites require exactly one match and only statuses 0/1 enter exact expected-matrix comparison. Nonzero builds, signals and tool failures remain infrastructure failures. New output ownership checks reject nonempty unowned directories.

Existing formal artifacts were inspected, not rerun. Executed Python JSON extraction of their raw stdout tails showed:

```text
positive exit 0 timedOut False
Model checking completed. No error has been found.
114 states generated, 19 distinct states found, 0 states left on queue.
negative exit 12 timedOut False
48 states generated, 17 distinct states found, 7 states left on queue.
```

Metadata source hashes match current specification/schema/model, observed via hashlib SHA-256. Current canonical hash: `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`. Existing native mutation manifest contains the exact requested A/B/C verdict matrices. Final source/tool provenance and current full gate remain root's responsibility; this review claims no fresh native/test/full-gate pass.

The TLA abstraction legitimately checks pending Boolean and correctly routed CURRENT/STALE responses with assumed freshness and serialized calls. It does not prove numeric-ID or native refinement, concurrency, liveness or cancellation. Refreshing Logout remains explicitly ignored. Worker report qualifications agree with these limits.

## Fix-wave scoped re-review

Malformed successful output now yields structured runner FAIL and direct FAIL with semantic exit 1. Numeric native crash/signal codes and raw stderr survive, with separate infrastructure classification and exit 2. Timeout bytes are normalized into saved TLC result files; failure metadata/report writing is present. Trace checking now enforces closed domains, predecessor observations, legal CURRENT/STALE/NA labels, allocation rejection preconditions and exact canonical injected Apply output. Duplicate prepare_output is removed; report SHA is corrected. Both skipped mutation gates emit NOT_RUN/exit 0, and full script reports INCOMPLETE instead of PASS. Canonical SHA remains unchanged; scoped legacy source/model git diff was empty. No expensive gates repeated.

Executed command:

```sh
python3 -m unittest verification.test_async -v > /tmp/async-review-fix-tests.log 2>&1
tail -n 10 /tmp/async-review-fix-tests.log
```

Raw tail:

```text
test_stale_negative_requires_exact_injected_canonical_response_row (verification.test_async.AsyncFormalTraceTests) ... ok
test_tlc_timeout_evidence_is_normalized_and_persisted (verification.test_async.AsyncFormalTraceTests) ... ok
test_skip_marks_every_case_not_run_and_clears_owned_stale_results (verification.test_async.AsyncMutationSkipTests) ... ok
test_crash_and_signal_remain_infrastructure_with_raw_status_and_stderr (verification.test_async.AsyncRunnerFailureTests) ... ok
test_malformed_successful_outputs_create_fail_report_and_direct_fail (verification.test_async.AsyncRunnerFailureTests) ... ok

----------------------------------------------------------------------
Ran 15 tests in 2.636s

OK
```

Remaining Important: `validate_trace(..., stale_fault=True)` validates exact injected Apply when a final STALE step is encountered, but never requires that step to exist. A wholly legal CURRENT completion or an initial-only trace still returns True. Therefore a named invariant/exit fixture with an unrelated valid trace could qualify as a validated negative control. Require at least one transition and a witnessed final canonical STALE Apply violation when stale_fault=True; keep legal traces acceptable only under normal mode. Add regression cases for CURRENT ending, initial-only ending and final stale no-op.

Executed command:

```python
import json
from pathlib import Path
from verification.async_formal import parse_counterexample,validate_trace
s=json.loads(Path('contract/specification.json').read_text())
t=parse_counterexample(Path('reports/async-formal-worker/negative-counterexample.txt').read_text())
t[-1]['responseClass']='CURRENT'
print('legal CURRENT ending accepted as stale fault:',validate_trace(t,s,stale_fault=True))
print('initial-only accepted as stale fault:',validate_trace(t[:1],s,stale_fault=True))
```

Raw output:

```text
legal CURRENT ending accepted as stale fault: True
initial-only accepted as stale fault: True
```

## Final witness correction re-review

The final negative mode requires a transition and records a witnessed final canonical STALE Apply violation before returning success. The remaining finding is resolved. Focused source inspection confirms the witness is set only after exact row validation and demonstrated stale safety mutation. CURRENT, initial-only and stale no-op traces retain normal-mode acceptance and are rejected in negative mode. No further blocker remains in the scoped review.

Executed the prior trace probe with CURRENT and initial-only variants, plus a final stale no-op variant constructed by setting state Refreshing, pending True and effects empty. Raw output:

```text
actual stale witness accepted: True
CURRENT normal accepted: True
CURRENT negative rejected: negative TLC trace must end with an observed stale-response Apply violation
initial-only normal accepted: True
initial-only negative rejected: negative TLC trace must end with an observed stale-response Apply violation
stale-no-op normal accepted: True
stale-no-op negative rejected: negative stale response differs from the exact injected canonical Apply row
```

Executed command and complete raw output:

```sh
python3 -m unittest verification.test_async.AsyncFormalTraceTests.test_stale_negative_requires_exact_injected_canonical_response_row -v
```

```text
test_stale_negative_requires_exact_injected_canonical_response_row (verification.test_async.AsyncFormalTraceTests) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.001s

OK
```

Root retains responsibility for final affected gates, provenance and unchanged native/core evidence. The canonical v3 and Refreshing Logout ignore policy remain the acceptance basis; no numeric/native refinement or cancellation proof is claimed.
