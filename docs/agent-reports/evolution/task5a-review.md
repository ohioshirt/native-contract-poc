# Task 5A / 6A independent evaluator code review

Verdict: **APPROVED**

Reviewed the stable evaluator code and fixtures listed in `task5a.md`, the managed workload/history/native briefs, the integration diff in `scripts/verify.sh`, and README/formal documentation against design C/D/R2–R5 and plan 5A/6A. Task 2 and other workers' source changes were outside this review. No source edits, nested agents, test runs, native builds or full-suite runs were performed. Existing author logs and reports were inspected rather than rerun.

## Findings

No important defect found within the reviewed scope. The evaluator is ready for the controller's complete freeze review; actual native implementation, compiler probes and native mutation runs remain required afterward.

### History checking

- The verifier-owned workload independently declares scenario membership, owners, every setup/handle/snapshot operation, exact input metadata and dependencies. History validation requires exact membership and rejects whole-operation deletion, missing snapshots, duplicates and unexpected input metadata. The runner does not supply the expected inventory.
- Each history uses globally unique positive integer timestamps with invoke < return. The checker computes a predecessor set from **every** return(A) < invoke(B) pair, not only phase order. Additional declared phase/dependency edges must also be satisfied by observed intervals. The sequential search only enables operations whose predecessors have already been selected.
- Responses retain a producer operation/effect reference. The producer must have returned before invocation, the producing effect must be RequestTokenRefresh, and the rendered owner/ID must match that observed effect. The producer itself must match the oracle during the witness search. Thus a fabricated producer result cannot authorize a token in a passing witness.
- Snapshot operations observe the exact state/pending/next triple, have empty effects/no rejection and preserve state. Handle observations compare the complete snapshot, ordered effects, token owner/ID and rejection against the full-step oracle plus managed ownership semantics. Foreign ownership is checked before low-level numeric correlation.
- Search memoization includes the completed operation set and all owners' current triples; token provenance is fixed by validated records and predecessor constraints. Overlap permits legal alternative orders while real-time precedence remains mandatory. No cross-language scheduling equality is assumed.
- Operation/node/time bounds and missing observed overlap return INCONCLUSIVE, never PASS. Malformed/incomplete histories are INVALID_HISTORY; well-formed impossible observations are FAIL. All non-PASS checker verdicts have nonzero CLI exits. Native phases use live callers and bounded whole-scenario trials according to the frozen brief; timestamps never claim deterministic scheduling.

### Finite model

The numeric reducer implements row/guard/pending/allocator rules separately from the oracle; the oracle is called only for correspondence checking. The reachable product exploration generates both owners' simple/snapshot operations and both response kinds for each actually issued token, maintains ghost issued-ID sets and compares the complete observation at every base-model successor. Bounds, initial state and per-owner no-reuse semantics match the approved finite instantiation. Production schema/bounds are not rewritten.

The reset and owner-check-removed modes inject isolated faults and check independent invariants. The retained report contains concrete counterexamples: Logout reduces allocator 2 to 1 after issuance, and a legitimate token from owner A delivered to B loses the required ForeignRequest rejection. These are finite-model evidence, not native mutation evidence or a source refinement proof.

### Native drivers and public API fixtures

- Missing Swift runner or missing Kotlin ManagedHistoryRunner main class yields NOT_RUN. The gate cannot substitute existing low-level trace executables. Missing facade sources/modules/compiler inputs similarly prevent public API PASS.
- Owner mutation patches require exactly one stable guard match. Each candidate is built in an isolated temporary copy, must run successfully, and must produce a complete deterministic foreign-same-id history for the external checker. Build/runtime failure, malformed history or inconclusive search remains infrastructure failure; only semantic checker FAIL establishes detection. An undetected mutant is non-PASS.
- Public API probes compile as external clients without privileged Swift imports or Kotlin friend paths. Positive compilation/runtime occurs first. Negative probes require nonzero compilation plus the expected access/mutation diagnostic; unrelated module/tool failures do not qualify. Token issuance/reuse, full snapshot and Kotlin effects immutability are exercised by the positive fixtures.
- The source API and commands in the frozen brief match the fixture calls, executable target/main names, existing public state enums and signed64 types. Native workers must implement those fixed interfaces and anchors without changing probe sources. The fixtures and drivers remain protected evaluator inputs.
- The process recorder preserves argv/cwd/time/status/stdout/stderr, kills its owned process group on timeout and does not count timeout/signals as semantic mutation detection.

### Normal gate and documentation

`verify.sh` invokes the managed gate, allocates a fresh managed evidence directory, records its command/status/tails and includes its report. Non-PASS managed stages cannot produce overall PASS. Explicit mutation skipping propagates NOT_RUN/non-PASS. The integration retains existing synchronous/core gates. README/formal documentation separates managed ownership from low-level caller assumptions, documents finite bounds and ghost state, and avoids unbounded/native-refinement/model-ranking claims.

## Evidence inspected

No new test-result claim is made by this review. The author report provides executed commands and raw tails; the refreshed `reports/evolution/task5a/targeted-final.log` was read. The retained pre-native managed report explicitly marks native histories, public API probes and owner mutations NOT_RUN.

For the concrete model controls, the recorded numeric command was:

```sh
python3 -m verification.numeric_model --output reports/evolution/task5a/managed-not-run/numeric
```

Its retained command JSON is `reports/evolution/task5a/managed-not-run/numeric.command.json`; concrete trace artifacts are in `numeric/numeric-report.json`. The two final faulty observations read from that artifact are:

```json
{"before":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"after":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":1},"owner":"A","event":{"event":"Logout"},"invariant":"AllocatorMonotonicity"}
{"before":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":1},"after":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":1},"owner":"B","event":{"event":"RefreshSucceeded","tokenOwner":"A","requestId":1},"rejection":null,"invariant":"OwnerIsolation"}
```

The snippets above select fields from recorded model traces; they are not new executions, native histories or raw test totals.

## Required continuation

Freeze all evaluator code, workload/briefs, mutation matrices and positive/negative probe sources together with the reviewed protocol. Then repeat preserved-old-native RED under that manifest, implement the fixed native APIs/runners and anchors, run actual history/API/mutation stages, and complete final independent native/integration review. This approval is for the evaluator preparation; it does not imply that absent native implementations already satisfy the contract.

## Scoped API fix1 review — 2026-10-12

Verdict: **APPROVED** for evaluator revision/refreeze.

Reviewed only the changes to `verification/managed_api.py`, `verification/managed-api/kotlin/constructor.kt` and `verification/test_managed_evaluator.py`, comparing them with the preserved r1 source archive. No native source, checker/model, workload or mutation behavior was changed by this fix. No tests, builds or API commands were executed by this reviewer.

The Swift artifact helper supports the conventional SwiftPM Modules/target.build layout and the Xcode product layout through `.build/debug`. It requires both public modules and both targets' objects before invoking the external client compiler. The fallback changes artifact discovery only; it preserves external module separation and positive compile/runtime validation. Regression coverage includes both layouts and missing required objects.

The Kotlin constructor fixture now supplies both actual arguments, so private-constructor rejection is distinguished from missing-argument failure. The diagnostic classifier is unchanged. The new regression explicitly refuses arity-only output; nonzero compilation must still have access evidence. A publicly callable constructor with these arguments would compile and be classified SEMANTIC_FAIL. Swift's retained constructor output contains explicit initializer-inaccessible diagnostics even though it also reports missing owner; approval relies on the former.

Inspected existing author commands, not rerun:

```sh
python3 -m verification.managed_api --platform swift --output reports/evolution/task5a/api-fix1/swift
python3 -m verification.managed_api --platform kotlin --output reports/evolution/task5a/api-fix1/kotlin
```

The author report retains each command's raw `PASS` tail and individual compile/runtime command records. Actual constructor stderr excerpts inspected from the respective captured files:

```text
error: 'RefreshRequest' initializer is inaccessible due to 'fileprivate' protection level
```

```text
verification/managed-api/kotlin/constructor.kt:2:19: error: cannot access 'constructor(requestId: Long, owner: Any): RefreshRequest': it is private in 'nativecontract.async.RefreshRequest'.
fun forbidden() { RefreshRequest(1L, Any()) }
                  ^^^^^^^^^^^^^^
```

No concrete blocker found. The controller must invalidate r1 candidate verdicts, freeze the changed evaluator/probe/test inputs under r2, repeat preserved-native semantic RED and rerun the full candidate evaluation. Prior review limitations and final native/integration review requirements remain in force.
