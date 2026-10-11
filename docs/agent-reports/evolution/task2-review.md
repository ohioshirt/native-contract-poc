# Task 2 independent code review

Verdict: **APPROVED**

Scope: Task 2 requirements in `docs/experiments/evolution-design.md` / `evolution-plan.md`, author report `docs/agent-reports/evolution/task2.md`, and the baseline-relative diff of the declared contract/oracle/formal/mutation files plus `docs/experiments/native-anchors.md`. Other workers' implementation files were not reviewed. No product or evaluator source was edited. No tests, builds or formal runs were executed by this reviewer; existing author evidence was inspected, not rerun.

## Findings

No important issue found within this scope.

- The production specification changes version, explicit Logout policy and only the async Refreshing × Logout row. Core table content is unchanged. The semantic validator allows exactly that action exception for invalidate mode and still checks every other async/core action pair. Both permitted modes require their exact Logout state/effects/pending action; guard, pending iff Refreshing, totality and effect bounds remain enforced. Historical ignore mode remains valid.
- The pure `step` function retains no state and returns the full state/pending/next/effect/rejection observation. The default allocator limit remains production signed64. A separate finite bound only changes the chosen allocator maximum; successful final allocation preserves its issued ID and changes next to null. Exhaustion returns the unchanged triple with no effects and the specified rejection. Logout clears pending and preserves next, including null. Guard mismatches leave the triple unchanged with no effects/rejection. Its documented normalized-event/reachable-state precondition is consistent with its oracle callers and planned model use.
- `policy_errors` expresses Logout/stale/pending/rejection properties without reading action-row expectations. The poisoned-row test checks that separation. TLA+ also adds independent LogoutPolicy with explicit expected behavior, ordered ClearCredentials and rejection constraints; it is included in the generated TLC config.
- The new formal negative control changes only SimpleApply's Refreshing Logout behavior. It requires the named LogoutPolicy violation and validates an exact final ignored-Logout step after a legal prefix. The existing stale negative control remains isolated; requesting both fault modes is rejected. Missing or malformed control evidence cannot be treated as a valid counterexample.
- Native mutation descriptions retain the old guard/reset controls and define both languages' ignored Logout, missing ClearCredentials, retained pending and allocator-reset patches. The frozen fixture documents distinguish inserted complete branches from preserved matching fragments. Fixture tests establish one-match textual patch formation only and do not claim native semantic kills. Actual-source anchor tests remain enabled and correctly deferred until native code exists. Native kills, managed owner mutants and final full integration remain later checkpoints.
- The author report distinguishes preparatory evidence from the required future frozen-evaluator run. It explicitly retains the initial infrastructure failure and does not relabel that attempt as RED. It also reports the in-progress discovery failures without claiming a whole-suite result. The semantic old-native evidence is separate and consistent with the retained runner records.

## Inspected old-native RED evidence

These commands were executed by the Task 2 author and read from retained artifacts by this reviewer; they were **not rerun** during review.

Comparator command recorded in `reports/evolution/task2/old-native-provenance.json`:

```sh
python3 -m verification.async_verify --output reports/evolution/task2/old-native-full-red --swift reports/evolution/baseline-native/AsyncTraceRunner --kotlin reports/evolution/baseline-native/async-library/bin/async-library
```

The preserved native invocation commands are in `old-native-full-red/{swift,kotlin}-async-runner.command.log`. Their corresponding result JSON records both native returnCode values as 0 with timedOut=false; those are process execution results, not native conformance verdicts. `old-native-full-red-exit-code` and provenance record comparator exit 1. Concrete raw stderr-tail excerpts from `old-native-full-red-command.log`:

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
```

These are behavioral comparison mismatches after actual native execution, consistent with v3 ignoring Refreshing Logout. The provenance file records unchanged before/after hashes of the preserved Swift binary and Kotlin distribution and the current validated invalidate specification. This is preparatory semantic RED, not a frozen protocol attempt or a final native mutation result.

## Remaining required checkpoints

Before native work: complete the other evaluator tasks, independent evaluator review/freeze and repeat preserved-runner RED through named immutable stages. After native work: run enabled source-anchor checks, actual native mutation controls, managed ownership/history/API gates and final full verification. Task 2 approval does not replace those checkpoints or assert guarantees beyond the documented Boolean TLA and finite-model limits.
