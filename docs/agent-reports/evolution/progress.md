# SDD ledger — plan: docs/superpowers/plans/2026-10-12-contract-evolution.md

Baseline: 8458f66. Managed worktree: /Users/shigeo/.codex/worktrees/b195/native-contract-poc.

Ruling: User explicitly requested review then lower-model execution; follow that approval flow without repeating skill human approval gates. Cost if wrong: design rework.
Ruling: Add managed owner facade rather than break low-level Swift value API. Cost if wrong: callers must migrate to receive stronger guarantees.
Ruling: Use Kotlin monitor for synchronous atomic transitions; no coroutine dependency. Cost if wrong: API is blocking rather than suspending.
Ruling: Current run records actual lower-model team work; comparative benchmark protocol is delivered, but do not mislabel parent coordination as a Sol experiment. Cost if wrong: separate controlled experiment still needed for ranking.

| Shared boundary | Producer / consumer | Check |
|---|---|---|
| Task 1 -> 2/6 | immutable hashes and attempt record | freeze after evaluator review; version any subsequent evaluator change |
| Task 2 -> 3/4/5 | v4 policy, low-level oracle | sole async difference Refreshing Logout; old profile remains exact |
| Task 3/4 -> 5 | history wire | Task 5 publishes before runners |
| Task 3/4 -> 6 | native APIs/runners | no cross-language source reads; build separately |
| Task 5 -> 6 | bounded verdict gate | INCONCLUSIVE not PASS |
| Task 1 self | CLI tests vs protected manifest | no broad exit1 semantic convention |
| Task 2 self | policy vs validators | preserve all non-exception equivalences |
| Task 3 self | actor vs native low-level value | no internal await or restore |
| Task 4 self | monitor vs mutable state | all operations/snapshots one monitor |
| Task 5 self | numeric finite model vs native traces | no unbounded refinement claim |
| Task 6 self | final evidence vs prior gates | raw command/tail and frozen provenance |

Task plan review: pending.
Baseline gate: running, logs reports/evolution/baseline.

Baseline gate complete: exit 0; report docs/agent-reports/evolution/baseline.md. Old binaries preserved reports/evolution/baseline-native.

Plan review R1–R5: incorporated into spec/plan; scoped re-review pending.
Ruling: Split bounded native Logout work to Luna, multi-file managed API/runner work to Sol. Cost if wrong: more worker handoffs; lowers risk of underspecified large Luna task.

Plan review: APPROVED after R1–R5 revisions (docs/agent-reports/evolution/plan-review.md).
Task 1: dispatched protocol, gpt-6.1-sol high, implementing frozen CLI.
Task 2: dispatched contract, gpt-6.1-sol high, implementing v4/oracle/formal/mutation evaluator.
Task 5A/6A: dispatched managed_evaluator, gpt-6.1-sol high, implementing wire/checker/model/integration before freeze.
Baseline runner hashes: baseline-native-hashes.json.

Approved design/plan preserved in tracked docs/experiments/evolution-design.md and evolution-plan.md because machine global ignore excludes docs/superpowers. Same requirements; not a scope change.

Task 2: evaluator code review APPROVED (task2-review.md); native source anchor and actual mutation runs remain downstream gates.
Task 1: fix round 1/5 dispatched to original protocol worker for ledger symlinks (R1) and raw-evidence binding (R2); task1-review.md has exact reproduction. No manifest frozen yet.
Task 5A/6A: checker/model/API/mutation fixtures/drivers implemented, integration/docs in progress.

Task 1: fix round 1 scoped re-review APPROVED (task1-review.md). Protocol ready; no freeze yet.
Task 5A/6A: implementation ready (task5a.md); independent reviewer checking final driver/API/integration details.
Native Luna briefs prepared under docs/agent-reports/evolution; not dispatched until protected evaluator freeze + old-native RED.
Draft actual stage config reports/evolution/protocol-config-r1.json prepared (old-native-red, candidate-full).

Task 5A/6A: independent code review APPROVED (task5a-review.md).
Evaluator FROZEN r1: c801ad810217540101718dfd933d6d8d35333c180954666fd5905ad695770d60. Controller digest persisted controller-manifests.json.
Frozen old-native-red-01: exit1 / SEMANTIC_FAIL; preserved native runners execute successfully. Native implementation may start.

Task 3A/4A: Luna implementations complete, independent combined Sol review APPROVED (logout-review.md).
Deferred native anchor gate now executed: python3 -m unittest verification.test_async.AsyncNativeMutationAnchorTests -v, exit0; raw reports/evolution/native-anchor-check.log.
Protected evaluator check after Luna changes: PASS; candidateDigest 1327e11628116cd08f64aa583750ba28ed9808835c776524ed76bc495e1495c4.
Task 3B: dispatched swift_managed, gpt-6.1-sol high.
Task 4B: dispatched kotlin_managed, gpt-6.1-sol high.

Task 3B/4B: native source complete; actual histories checked by frozen checker (task3b.md/task4b.md). Independent Sol native reviews running.
Frozen candidate-full-01 launched using warm shared Gradle cache; raw output reports/evolution/protocol-r1/candidate-full-01. No source edits during run.

Task 3B: independent review APPROVED (task3b-review.md).
Task 4B: independent review APPROVED (task4b-review.md); Kotlin-source API scope as frozen R4, not JVM bytecode secrecy.
Candidate r1 full attempt completed INFRA_FAILURE (aggregate exit1); all non-managed gate exit codes0, managed public API probe failed due Swift Xcode artifact layout and Kotlin missing owner argument in negative probe. Native histories/model/owner mutations pass in report.
R1 candidate source archived before edits: reports/evolution/candidate-r1-source.tar.gz, sourceDigest 853f4c524f486e31c9b770a850a13e02ce327eb474159b7c61acaec10cdc716d matches attempt result.
Evaluator API fix1 authorized to original managed_evaluator; no native changes. Will review/refreeze r2/re-RED/full.
Core behavior/source/test compatibility check executed; raw reports/evolution/core-compatibility.log.

Evaluator API fix1 implemented and actual external probes succeed on both platforms; scoped re-review pending. Only managed_api.py, test_managed_evaluator.py, Kotlin constructor probe changed. Runtime diagnostic strictness unchanged. Draft protocol-config-r2.json ready.

Evaluator API fix1 independent scoped review APPROVED.
Evaluator FROZEN r2: 2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481.
R2 old-native-red-01 launched against saved baseline binaries.

R2 old-native-red-01: SEMANTIC_FAIL after successful preserved runner execution.
R2 candidate-full-01: PASS / child verify.sh exit0. All local gates included.
Result binding check: PASS, candidateDigest 635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157.
Final source/archive preserved; final-gate.md contains executed commands + raw report tails.
Task 1/2/3A/4A/3B/4B/5/6 implementation and validation complete; final integration review report finishing.

Final whole-workstream review: APPROVED (final-review.md).
Final result binding check and evidence finalization complete. All requested primary workstreams completed locally. Managed worktree and raw source/evidence archives retained; no publishing/merge performed.
