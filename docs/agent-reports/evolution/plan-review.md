# Contract evolution plan review

Verdict: **CHANGES_REQUESTED**

Reviewed baseline: `8458f66a0691532a7f48e7ca1fb14fc86238b67f`.
All paths below are relative to `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`.
Reviewed the design and plan dated 2026-10-12 and the relevant existing contract validators, oracle, native sessions, TLA+ model, verifier entry points and mutation runner. This was a read-only source review apart from this report. I did not execute tests or builds and make no test-result claims. The parent's baseline gate evidence is separate.

The design covers all four requested improvements with appropriately bounded claims. The Logout rule is precise; the actor/monitor facade can enforce ownership for ordinary public API clients; completed histories can be checked for linearizability; a finite numeric explorer can add evidence without implying a native refinement proof. The remaining issues concern executable evaluator boundaries and evidence completeness. They can be addressed in these documents and task briefs before implementation, without adding new product features.

## Required revisions

### R1 — Freeze the evaluation command and verdict protocol, not only source hashes

Locations: design §B; plan Task 1 interface and Task 6.

`run` currently accepts arbitrary argv and a caller-selected verdict protocol. An unchanged evaluator file set plus a command such as `true` could therefore yield an apparent candidate PASS. Recording that command does not establish that the frozen evaluation was run. Comparator exit 1 also needs to be tied to a known entry point: `verification.async_verify` already distinguishes semantic exit 1 from infrastructure exit 2, while `scripts/verify.sh` aggregates both kinds into exit 1.

Smallest fix:

- Freeze named evaluation stages with argv templates, cwd rule, required result artifacts, timeout and verdict protocol in the manifest. Permit only explicit candidate/output-path substitutions. `run` either selects a frozen stage or rejects mismatching supplied argv/protocol.
- Bind each result to manifest digest, stage ID, candidate source digest, attempt ID and newly owned output directory. Validate required fresh artifacts before PASS; a missing/malformed report is infrastructure failure.
- Define stage-specific classification. The async comparator may classify exit 1 as semantic only with its expected report and semantic native verdicts; signals, exit 2, NOT_RUN or infrastructure native verdicts remain infrastructure/not-run. The full aggregate gate's exit 1 must not automatically mean semantic failure.
- Include the protocol implementation and entry-point scripts in the protected evaluator set. Enumerate protected directory/file membership, exact allowed native edits and explicitly ignored build/cache/report outputs; compare all other tracked and new source paths against the frozen input snapshot. Do not use baseline HEAD alone to reject the already reviewed v4 verifier changes.
- Add protocol tests for substituted argv/protocol, absent or stale result artifacts, and candidate/result digest mismatch in addition to the planned tests.

This is a local reproducibility guard, not protection against a malicious worker able to rewrite both manifest and controller. Keep an authoritative manifest digest in controller evidence and state this limit.

### R2 — Complete the evaluator before native work, with explicit dependency phases

Locations: plan Tasks 2, 5, 6 and scheduling line 76.

The plan freezes before native work but still leaves checker implementation/gate wiring to Tasks 5/6 and says to add mutations when future native patch sites exist. Those files are explicitly protected. The implementation would either violate its own frozen manifest or require an avoidable evaluator revision partway through the run.

Smallest fix:

1. Task 1 protocol implementation/review and Task 2 v4 oracle/formal gates can proceed independently.
2. Task 5A publishes the complete wire format, pure oracle/checker interface, numeric model and checker tests. Task 6A wires those gates into `scripts/verify.sh`; unavailable managed runners are NOT_RUN/non-PASS until they exist. It may use fixtures for its own checker tests.
3. Define exact native mutation anchors and their replacement strings in the native briefs. Add matrices/drivers and fixture-level patch validation before freeze, even though the candidate implementation supplies those anchors later.
4. Review Tasks 1/2/5A/6A together, freeze their complete file sets and named evaluation stages, and run the reviewed v4 comparator on the preserved old native binaries. Do not mutate or rebuild the old binaries for that RED. Hash the preserved runners and record toolchain/provenance.
5. Execute native work, then Task 5B actual history evaluation and Task 6B final full evaluation/evidence/review. These stages write evidence but do not introduce new evaluator code.

Any necessary later evaluator fix creates a new manifest revision, invalidates old candidate verdicts and reruns the relevant old-native RED and candidate stages. The expected model-comparison protocol can remain documentation; this run should retain its explicit non-benchmark status.

The parent's proposed 3A/4A (Luna, bounded Logout change) then 3B/4B (Sol, facade and runner integration) decomposition is suitable. Native stages must still start after evaluator freeze, and each language must retain the prohibition on reading the other implementation.

### R3 — Specify independently expected operations, token provenance and recorder intervals

Locations: design §D; plan Task 5 format/checker and Tasks 3/4 history exporters.

A checker cannot detect a dropped complete operation from the completed-operation list alone. Owner plus request number also permits a fabricated future token in a history, despite the proposed API disallowing that token. Snapshot rows and the recorder's exact interval must be part of the wire contract.

Smallest bounded wire contract:

- A frozen scenario plan contains the expected owner declarations, operation IDs, operation kinds, event templates, setup operations and dependency/phase edges. The verifier owns that plan and passes it to the runner. The checker compares records against this independent plan, with exact operation membership; expected IDs/count copied only from the runner's completed rows are insufficient.
- Include all setup calls that issue tokens as ordinary recorded operations. Responses reference a producing operation's refresh effect, for example `tokenRef: {operationId, effectIndex}`, in addition to rendered owner/ID. Store emitted token provenance in the checker state; reject nonexistent producers, unissued/future tokens and owner/ID disagreement. A foreign response must carry a legitimate token issued by the other owner. Avoid unverified initial token fixtures.
- Publish a token to later scenario calls only after the producing wrapper records its return. Enforce producer-return before response-invocation and the declared phase/dependency edges. Simple predeclared token-producing setup calls avoid dynamic operation inventories.
- Use one globally serialized strictly increasing logical event counter per history, covering both owners. Invocation is recorded immediately before calling/awaiting the managed API; return is recorded immediately after it returns. Require unique timestamps and `invoke < return`. Waiting between those observations is inside the recorded wrapper interval. Do not assign timestamps from result order or hold the recorder lock over the managed call.
- Explicitly distinguish `handle` and `snapshot` operations. A snapshot has no input event, observes the complete state/pending/next triple, produces no effects/rejection and leaves oracle state unchanged. Concurrent snapshots are mandatory scenarios, not optional omissions.
- Require all tasks/futures to be joined. Exceptions, cancellation, missing returns or incomplete expected operations cannot yield a completed PASS history; preserve them as diagnostics/non-PASS. Assert independent coverage of the planned overlap/non-overlap phases. The seed describes scenario generation and never claims scheduler determinism.
- Choose explicit operation/search bounds in the guide. An exhausted node/time budget returns INCONCLUSIVE with no PASS; use small separate histories rather than one large factorial search.

Add the already planned legal/illegal ordering controls, plus: deletion of an otherwise legal whole operation, future-token provenance, missing producer, equal/reversed timestamps and omitted snapshot operation. This addresses real-time constraints and recording completeness without claiming exhaustive OS schedule coverage.

### R4 — Make ownership enforcement an externally reviewable API property and add a native negative control

Locations: design §C; plan Tasks 3/4/5.

The proposed owner check and retained reference identity are sufficient for the intended public API scope, but ordinary runtime tests alone do not demonstrate the claim that requests cannot be fabricated through that API. The current native mutation matrix checks the low-level numeric guard; the finite model's owner mutant is not a mutant of either managed native facade.

Smallest fix:

- Make `RefreshRequest` final, with immutable request ID, inaccessible owner identity and no public construction/copy/serialization path. Keep the low-level session inaccessible inside the facade. Do not add a numeric response overload or a mutable seed/restore entry point.
- Define the claim for ordinary external Swift/Kotlin source API clients, excluding reflection/unsafe runtime manipulation and privileged same-module/test access. Avoid a whole-runtime security claim. Use same-file/private construction where practical rather than relying on Kotlin `internal` as if it were JVM runtime secrecy.
- Add a tiny separately compiled external-client positive/negative API check: obtaining and reusing an emitted token is allowed; constructing a token, setting its owner/ID or reaching the owned session is rejected. Do not use Swift `@testable` or Kotlin friend-module access for this check.
- Return detached immutable effect collections, including protection against Kotlin mutable-list casts affecting retained state/results. Both response kinds check foreign ownership before numeric stale handling and return the documented ForeignRequest rejection with unchanged snapshot and empty effects.
- Add a stable managed owner-check mutation per native platform. A deterministic same-number foreign-token scenario in the frozen managed gate must reject the resulting native history. Keep build failure separate from successful semantic mutant detection. Checker synthetic foreign-acceptance tests and numeric-model mutants remain useful but do not substitute for this control.

`AuthState` is already Sendable in the reviewed baseline. Remove the optional core source edit from the allowed native paths unless a concrete necessity appears later.

### R5 — Define the finite instantiation and its oracle correspondence explicitly

Locations: design §D; plan Task 2 oracle API and Task 5 numeric model.

The existing oracle consumes whole scenarios and does not expose `nextRequestId` in its result. The existing validator fixes requestIdMax to signed64 MAX. Saying the new model uses IDs 1..3 and derives transitions from the v4 profile leaves the allocator/exhaustion correspondence and issuing history underdefined for a lower-model worker.

Smallest fix:

- In Task 2 add a pure single-step oracle interface taking `(state, pending, next)` and returning the full new triple, ordered effects and rejection, without changing the old trace wire format. The managed checker wraps that behavior with the explicit ownership/provenance rules. All behavior rows remain sourced from JSON.
- Define the numeric model as a finite instantiation of those rules with `min=1`, `max=3`, initial next=1 and null exhausted sentinel, not as a valid production signed64 profile accepted by the normal schema/validator. State this parameter substitution explicitly.
- Each owner's model state includes its own immutable identity, triple and ghost issued-ID set. Same number across different owners is permitted; no-reuse is per owner. Generate simple events, both response kinds for every previously issued token from either owner, and snapshots exhaustively. Do not generate publicly unforgeable tokens as ordinary managed events.
- Keep issued-ID history as ghost state in a strengthened abstraction `(alpha(native), issuedHistory)`; do not pretend the native snapshot exposes that history. Check allocator monotonicity/no reuse, exact exhaustion no-op, foreign-owner unchanged snapshot, pending iff Refreshing and stale canceled-token no-op with empty effects/no rejection.
- Add explicit one-step correspondence checks across reachable bounded states using a test-only bound parameter, and native signed64 MAX boundary cases. Both named mutants must produce concrete trace artifacts and fail the intended invariant. Report the finite bound and preserve the existing limitation: neither this explorer nor finite histories prove all native executions.

Clarify design §A's “preserve ... effects” wording to say stale responses emit **no effects** and **no rejection** while preserving the entire state/pending/allocator triple. Logout itself emits exactly one ClearCredentials; a repeated Logout emits none.

## Acceptance after document changes

The revisions above are sufficient to proceed. No additional user approval is required by this review. The controller should update the design/plan and native briefs, then have the reviewer confirm that these concrete requirements are incorporated. Preserve the four-task scope: protocol, Logout invalidation, ownership facade and concurrent-history/model evidence. Avoid adding transport/cancellation/persistence work or claiming stronger guarantees.

Review evidence: source inspection only. No test counts, pass/fail totals or build results are reported here.

## Scoped re-review — 2026-10-12

Final plan verdict: **APPROVED**. This supersedes the initial CHANGES_REQUESTED verdict for implementation readiness.

Reviewed only incorporation of R1–R5 in the revised design/plan, including their normative Review resolutions sections. Frozen named stages now bind evaluation commands, artifacts and verdict protocols; evaluator/schema/model/gate preparation precedes freeze and native implementation; the workload independently fixes expected operations and token-producing references; snapshots and real-time recorder semantics are explicit; external API probes and deterministic native owner mutants are required; and the full-step oracle plus separately implemented finite max=3 model have a stated correspondence and limits. Core source edits are removed. The Luna 3A/4A then Sol 3B/4B decomposition is retained.

The final small ownership correction was also inspected: Task 6A owns positive and negative external compile probe source fixtures as protected inputs before freeze; Task 3B/4B implement APIs to satisfy those probes and cannot edit them. Thus native workers cannot weaken the public API evaluator while implementing the facade.

No unresolved blocker remains from this scoped review. Lower-model implementation may begin under the revised task dependencies; protocol/evaluator freeze review and subsequent implementation review remain required checkpoints. Approval is of the plan, not evidence that the future implementation or gates already pass. No tests or builds were executed during either review.
