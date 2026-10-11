# Contract evolution evidence — 2026-10-12

Status: r3 full local evaluation PASS after Claude Fable review and correction. Result/source/log/artifact bindings rechecked. Historical r1/r2 evidence is retained below.

## Work delivered

| Original task | Implementation | Actual model assignments |
|---|---|---|
| Refreshing Logout | v4 invalidates pending, emits ClearCredentials, preserves allocator/exhaustion; stale replies cannot revive or damage newer request | Luna high independently for Swift/Kotlin; Sol review |
| Reproducible change loop | freeze/check/run with source/command/artifact/log bindings, budgets and explicit failure classification | Sol high; independent Sol review and recorded repair |
| Concurrent calls | Swift actor / Kotlin private monitor with immutable snapshots; actual native histories checked with real-time constraints against common JSON oracle | independent Sol high native workers; Sol evaluator and reviewers |
| Model/implementation assumptions | owned opaque tokens, external source API probes, native owner mutants, finite two-owner numeric explorer with ghost issued IDs and one-step correspondence | Sol high, independently reviewed |

The parent decomposed requirements and coordinated work. Actual worker model IDs/efforts are in ../agent-reports/evolution/execution-metadata.json. This is not a controlled Sol+Luna versus Luna benchmark; comparison protocol is documented, cost/token metrics are unavailable and null.

## Frozen stages and repairs

The approved design and work orders are immutable inputs in evolution-design.md and evolution-plan.md. Completion is recorded in ../agent-reports/evolution/progress.md, not by editing a frozen checklist.

r1 manifest digest: c801ad810217540101718dfd933d6d8d35333c180954666fd5905ad695770d60.
Old native binaries were saved before native changes; hashes are in ../agent-reports/evolution/baseline-native-hashes.json. The frozen old-native stage returned SEMANTIC_FAIL after both runners executed. The first full candidate returned INFRA_FAILURE: Swift public-module discovery assumed conventional SwiftPM layout, and Kotlin's negative constructor probe omitted its owner argument. Histories/model/native mutations did not substitute for the missing API evidence.

The r1 source snapshot is retained at reports/evolution/candidate-r1-source.tar.gz (SHA256 b63cb388a1f748a896f6d0431d78f8f41708ad80fd5d7aa841694c702aef6c69), matching candidate digest 853f4c524f486e31c9b770a850a13e02ce327eb474159b7c61acaec10cdc716d. Source hashes and all raw outputs are retained locally under reports/evolution. They are generated artifacts and are not committed.

The evaluator revision supports both observed Swift layouts and supplies the complete Kotlin constructor call to test its private access restriction. It does not accept missing-argument errors as access evidence. Native source is unchanged by this repair. Independent scoped review approved the correction. The r2 old-native stage again returned SEMANTIC_FAIL; the r2 full candidate stage returned PASS with child exit 0.

## Scope

Existing synchronous contract fields (except the contract version) and synchronous Swift/Kotlin sources/tests are unchanged. The low-level async API still requires caller serialization and correct response routing. Stronger ownership and concurrency guarantees apply to ManagedAsyncSession. Ordinary external Swift/Kotlin source clients are the API boundary; JVM bytecode/reflection/unsafe manipulation are not a security boundary claim. Effects are descriptions; real network cancellation, credential deletion, persistence/restart recovery, liveness, arbitrary native executions and unbounded concurrency are not proved.

The numeric explorer is a finite instantiation (two owners, IDs 1..3), supplemented by native signed64 boundary tests. History checking covers the recorded completed workloads and reports insufficient overlap/search bounds as non-PASS. It is not a native refinement proof.

## Evidence links

- Baseline commands/raw tails: ../agent-reports/evolution/baseline.md
- Plan review: ../agent-reports/evolution/plan-review.md
- Protocol implementation/review: ../agent-reports/evolution/task1.md and task1-review.md
- Contract implementation/review: ../agent-reports/evolution/task2.md and task2-review.md
- Luna implementations/review: ../agent-reports/evolution/task3a.md, task4a.md and logout-review.md
- Managed evaluator/review/repair: ../agent-reports/evolution/task5a.md and task5a-review.md
- Managed native implementations/reviews: ../agent-reports/evolution/task3b.md, task4b.md, task3b-review.md and task4b-review.md

## Final r2 evidence

Manifest SHA256: `2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481`.
Candidate SHA256: `635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157`.

Full child command actually executed:

```sh
bash scripts/verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full
```

Raw first verdict from the generated report:

```text
Overall: PASS
```

All per-gate commands and raw stdout/stderr tails are in [final-gate.md](../agent-reports/evolution/final-gate.md). The report includes Python tests, core/async TLC, native builds/tests, sync/async contract comparisons, recorded managed histories, public API probes, numeric model and both mutation families. No counts are manually combined.

Result binding command actually executed:

```sh
bash scripts/change-protocol.sh check --candidate /Users/shigeo/.codex/worktrees/b195/native-contract-poc --manifest /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/manifest-r2.json --manifest-digest 2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481 --result /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/result.json
```

Raw output:

```json
{"candidateDigest": "635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157", "classification": "PASS", "manifestDigest": "2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481"}
```

Final source archive: `reports/evolution/candidate-r2-source.tar.gz`, SHA256 `8ee1e8346346828e5580c55f9fa4cd266b8c20dab5805c5b3f0218ca3a3af0a7`. This archive's source map matches the successful candidate digest and includes the protected old-native artifacts needed by the RED stage. Raw stage records and source maps remain under reports/evolution. Hosted CI and publishing were not performed in this task.

## Claude Fable follow-up and r3

Fable (claude-fable-5-1) independently reviewed native, semantic and protocol scopes. Its P2 finding was corrected: check --result now preserves the actual evaluation verdict/exit and separates bindingClassification. Source-only checks explicitly do not accept an evaluation. Regression tests and Fable re-review approved the fix.

- [Fable reviews and dispositions](../agent-reports/evolution/fable-review.md)
- [Fix commands and raw tails](../agent-reports/evolution/fable-protocol-fix.md)
- [r3 complete commands and raw tails](../agent-reports/evolution/final-gate-r3.md)

Manifest SHA256: 80b798a2106022efca62fb5a138a2dc19fb66b32eaaa772137f082d974e4e4e1. Candidate digest: 2594ede9a47604c32aaf4013826844cae942abb30de45d04c62a7778ae9a68ae. Old native RED remained SEMANTIC_FAIL; candidate-full returned PASS/exit0. Actual check of the old RED returned bindingClassification PASS, resultClassification SEMANTIC_FAIL and exit1; actual accepted-result check returned both PASS/exit0.

Fable judged a PR/hosted run not mandatory for this isolated PoC. Local main integration will use fast-forward and a fresh full gate on main; its local report is linked from reports/index.html. Existing hosted workflow remains, but this work does not claim a new hosted CI run.
