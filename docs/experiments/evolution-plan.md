# Contract evolution Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development at controller level. Workers execute only their assigned task and MUST NOT spawn agents. Follow the user's authorized review-then-execute sequence without asking again.

**Goal:** Execute the four contract-evolution improvements using lower models and reproducible evidence.
**Architecture:** Keep core and low-level APIs; update async policy, freeze evaluation inputs, add owned serialized facades and a common history checker with explicit numeric model.
**Tech Stack:** Python stdlib, TLA+/TLC, Swift 6/SwiftPM, Kotlin/JVM 17/Gradle.
**Spec:** docs/experiments/evolution-design.md

## Global Constraints
- Baseline 8458f66; isolated managed worktree; no publish/merge.
- Native implementations remain independent; Swift worker must not read Kotlin and vice versa.
- All implementation and code review use gpt-6.1-sol or gpt-6-luna, explicit model/effort.
- No nested worker delegation. No git add -A or git add .; controller owns staging/commits.
- Evidence commands + raw tail required for every reported test count or pass/fail.
- Reports persist under docs/agent-reports/evolution; raw logs under reports/evolution.
- Semantic RED requires built runners and valid specification; compile/schema failures are not semantic RED.

## Review Focus
- Logout after allocating MAX must preserve exhaustion (Task 2/3/4).
- A foreign session with the same request number must not complete work (Task 3/4/5).
- Calling snapshot during transitions must expose one coherent state (Task 3/4/5).
- Missing history operations or exhausted checker budget must not pass (Task 5).
- Tampered evaluator or stale attempt artifacts must not be accepted (Task 1).

### Task 1: Frozen change protocol (Sol, high)
Files: create verification/change_protocol.py, verification/test_change_protocol.py, scripts/change-protocol.sh, docs/experiments/change-protocol.md.
Interface: CLI freeze/check/run; manifest freezes named argv/cwd/timeout/verdict/artifact stages. run selects a frozen stage with only candidate/output substitutions; arbitrary argv or verdict overrides are refused. Result binds manifest, candidate, stage and attempt digests; required fresh artifacts must substantiate PASS. Shared metadata includes exact model IDs/effort/seed/cache status/null costs. check protects file set as well as file contents.
- [ ] Tests for successful capture, protected-file edit/add/delete, out-of-scope source edit, timeout/signal/nonzero infrastructure classification, comparator semantic failure, output collision, unavailable metrics, substituted argv/protocol, missing/stale artifacts and digest mismatch.
- [ ] Implement freeze/check/run and bounded-attempt record convention; validate baseline/provenance and path containment, preserve raw logs.
- [ ] Run python3 -m unittest verification.test_change_protocol -v, capture commands/tails, self-review, report.
- [ ] Review before using protocol to freeze this experiment.

### Task 2: v4 contract and independent gates (Sol, high)
Files: contract/specification.json, contract/schema.json, verification/contract.py, verification/async_contract.py, verification/test_async.py, formal/AsyncSession.tla, verification/async_formal.py, verification/async-mutation-matrix.json.
Produces verification.async_contract.step(spec,state,pending,next_id,event,*,request_id_max=None) returning full state/pendingRequestId/nextRequestId/effects/rejection, fixed contract/oracle/native mutation gate for Task 3/4; ensure async rows apart from Refreshing Logout still equal core. v3 ignore profile validation remains internally coherent, v4 uses invalidate.
- [ ] Tests for each mode, illegal other divergence, exact Logout result, stale success/failure after new login/request, repeated Logout, final-ID exhaustion.
- [ ] Implement schema/validator policy exception and independent Logout invariants. Update fixture names and formal checks/negative controls; do not weaken old guards.
- [ ] Define exact stable native mutation anchor snippets in docs/experiments/native-anchors.md, add matrices/drivers and fixture-level patch checks BEFORE freeze. Cover all Logout faults and one managed owner-guard mutant per language; coordinate only through parent.
- [ ] Run Python tests and formal gates; run new async comparator on OLD native binaries from baseline. Save behavioral RED with meaningful failing steps, not build/schema failures.
- [ ] Report evidence and frozen input paths; review before native workers.

### Task 3: Swift native change (3A: Luna high) then owned actor/runner (3B: Sol high)
Files: ios/Sources/AsyncNativeContract/AsyncSession.swift; new ManagedAsyncSession.swift; ios/Tests/AsyncNativeContractTests/*; ios/Package.swift plus new ManagedHistoryRunner executable sources.
Exact public types: ManagedAsyncSession actor, RefreshRequest immutable opaque reference (requestId:Int64), ManagedEvent, ManagedEffect, ManagedRejection, ManagedSnapshot, ManagedResult. handle(_:) -> ManagedResult; snapshot() -> ManagedSnapshot (cross-actor await at caller only). ManagedSnapshot holds state, pendingRequestId, nextRequestId; ManagedResult holds snapshot,effects,rejection. No await within handle. Immutable values Sendable. Align wire history with Task 5 schema; use TaskGroup and serialized timestamp recorder, all tasks joined.
- [ ] New failing tests for invalidating Logout and nextId preservation, then minimal low-level implementation independent of Kotlin.
- [ ] Owned actor tests: foreign-owner same numeric ID, stale/duplicate token, aliases share history, coherent snapshot, MAX exhaustion, simultaneous TokenExpired, Logout/completion overlap.
- [ ] Add bounded history exporter using actual managed calls and shared wire schema. Keep results associated with invocation op IDs.
- [ ] swift test --package-path ios; emit JSON histories; capture commands/tails; report. Do not edit spec or verifier.

### Task 4: Kotlin native change (4A: Luna high) then owned monitor/runner (4B: Sol high)
Files: android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt; new ManagedAsyncSession.kt; managed tests; new ManagedHistoryRunner.kt and Gradle JavaExec/run entry as needed.
Exact public types parallel Task 3 (Kotlin naming style allowed), ManagedAsyncSession class with one private monitor and handle(event):ManagedResult / snapshot():ManagedSnapshot. RefreshRequest cannot publicly construct/copy/deserialize owner identity; no data-class token. Synchronize validation, low-level transition, token creation and snapshot. Immutable exposed snapshots/effects. No coroutine dependency.
- [ ] Same semantic/ownership/boundary tests as Task 3, independently of Swift.
- [ ] Concurrent history runner uses real threads/executor and atomic/synchronized timestamps outside operation interval; awaits all futures and captures failures.
- [ ] ./android/gradlew -p android :async-library:test :async-library:installDist; emit histories; commands/tails; report.

### Task 5A/5B: Shared evaluator before freeze / actual histories after native implementation (Sol, high)
Files: new verification/linearizability.py, verification/test_linearizability.py, verification/numeric_model.py, verification/test_numeric_model.py, scripts/managed-verify.sh, docs/experiments/managed-history-format.md.
Produce complete verifier-owned workload schema, scenario inventory, checker/model and gate script BEFORE freeze; post-native Task 5B only evaluates histories. Workload independently fixes all IDs, events, phases and token-producing-operation references. checker consumes common JSON spec and completed histories; separate per-language history verdicts. Numeric model uses exactly finite owner/ID bounds and stores counterexamples; no native proof claim.
- [ ] Publish precise JSON example/schema in guide; send path to controller for native briefs.
- [ ] Checker tests legal overlapping reorder; illegal real-time reorder; wrong state/pending/counter/effect/rejection; malformed/dropped/duplicate operations against independent workload; missing/future producer and owner/ID mismatch; equal/reversed timestamps; omitted snapshot; budget inconclusive; snapshots.
- [ ] Implement bounded backtracking over enabled operations preserving real-time edges, applying oracle and validating full observations; persist witness ordering or diagnostics. CLI exits nonzero for all non-PASS incl inconclusive, preserves distinction in JSON.
- [ ] Model exhaustive successors with IDs 1..3 and two owners, invariants and named reset/foreign-owner mutants; actual counterexample mandatory.
- [ ] Run targeted Python tests and numeric model, then actual Swift/Kotlin histories once runners exist. Report commands/tails.

### Task 6A/6B: Evaluator integration before freeze / final execution and review (Sol, high)
Files: scripts/verify.sh, README.md, formal/README.md, docs/experiments/evolution-evidence.md, scoped fixes from reviews.
- [ ] BEFORE FREEZE: wire managed-history, public-API compile probes, managed native owner mutants and numeric-model gates into normal full gate; no skipping accepted as PASS.
- [ ] AFTER NATIVE WORK: use protocol manifest and attempt logs for candidate evaluation; record repairs, model IDs and unavailable cost fields honestly. A verifier revision invalidates prior manifest, starts a newly frozen revision and requires re-evaluation.
- [ ] Run full scripts/verify.sh and independent review; verify original sync table equality and original sync tests kept, async changed tests replaced intentionally.
- [ ] Explain new facade versus old low-level assumptions and finite guarantee limits. Comparison protocol reusable, current run explicitly not a controlled Sol+Luna vs Luna benchmark.
- [ ] Final lower-model reviewer checks implementation, verifier integrity, real-time history semantics, bounds and evidence; resolve important findings with original workers.

## Scheduling / review checkpoints
Plan review first. Task 1 and Task 2 may run concurrently. Task 5A schema/checker/model uses the declared step interface; Task 6A evaluator wiring and native mutation/API-check drivers finish before freeze. Review evaluator, freeze named stages, run old-native semantic RED, then Tasks 3A/4A (Luna) and 3B/4B (Sol). Task 5B checks actual histories; Task 6B records final evidence/review. Any evaluator fix starts a revised manifest and reruns old-native RED and candidate evaluation. Reuse original worker for fixes, bounded at five rounds with controller ruling at cap. No unreviewed important finding silently deferred.

## Mandatory review resolutions inherited by every task
The design section Review resolutions R1–R5 is normative. Task 1 owns R1. Task 2 owns R5 pure step and low-level mutation anchors. Task 5A owns R3/R5 wire and model. Task 6A owns R2 freeze ordering plus R4 external API/native-owner mutation evaluator. Task 6A owns the positive and negative external compile probe source fixtures as protected evaluator inputs BEFORE freeze. Task 3B/4B implement R4 APIs to satisfy those fixed probes and do not edit probe fixtures. Native briefs MUST include exact anchor strings before freeze. Task 6A may be implemented by Task 5A worker to keep evaluator ownership coherent. Task 1/2 workers must not touch scripts/verify.sh.

Allowed native source boundaries after freeze: ios/Sources/AsyncNativeContract/, ios/Sources/ManagedHistoryRunner/, ios/Tests/AsyncNativeContractTests/, ios/Package.swift; android/async-library/. Existing sync trees and core source are protected. New managed facade exposes no seed mutation, restore, numeric response overload or token constructor. Positive external client and negative token-constructor/owner/session access probes compile without privileged test access. Snapshot remains mandatory in common scenarios. Stable history inventory comes from frozen evaluator, never synthesized solely from native output.

Evidence/log destinations and docs/agent-reports/evolution plus final evolution-evidence.md are declared non-source exclusions in protocol. README and formal boundary docs are prepared in 6A before freeze. Preserve authoritative manifest digest and all superseded records in controller evidence. Hash baseline Swift binary and all Kotlin preserved distribution files before behavioral RED.
