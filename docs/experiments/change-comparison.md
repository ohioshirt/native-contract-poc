# Autonomous change experiment comparison

Both configurations implemented the same behavioral delta: Authenticated×LoginSucceeded preserves state and emits exactly [ClearCredentials]. No credentials/session identity claim is made. The Sol-role team delegates Swift/Kotlin to separate Luna contexts; the standalone Luna handles both trees in an isolated copy. Existing tests were retained and the changed expectation strengthened; repeat-login regression tests were added.

## Worker change gates

| Observation | Sol-role + Luna team | Standalone Luna |
|---|---|---|
| Changed-contract rejection before implementation | Swift FAIL / Kotlin FAIL / differential PASS | Swift FAIL / Kotlin FAIL / differential PASS |
| First implemented candidate | Contract + differential match | Contract + differential match |
| Additional implementation bug-repair requests | Empty ledger | Empty ledger |
| Version metadata | Incremented to 2 | Retained 1; not explicitly required in standalone brief |
| Verifier snapshot during worker gate | Reviewed/fixed shared framework | Earlier shared framework snapshot |
| Final external full gate | All local gates incl. exact Mutation matrix | Unchanged native sources also pass the same fixed external full gate incl. exact Mutation matrix |
| Billable tokens/currency | Not exposed | Not exposed |

Sol-role UTC start: `2026-10-09T04:16:10.458972+00:00`; subset report written: `2026-10-09T04:18:16.893957+00:00`. Change-to-report interval computed by Python: `126.43` seconds. Subset gate start `2026-10-09T04:18:10.867295+00:00` to report mtime: `6.03` seconds. Standalone reported clock start `2026-10-09 04:10:42 UTC` and final completion `2026-10-09 04:11:49 UTC`; its final gate was `04:11:36`–`04:11:49` (13 seconds, as recorded in its raw report). Sol interval includes orchestration and concurrent GitHub/status/document work; timing endpoints differ. Neither interval measures billable usage or provides a controlled speed comparison.

Commands/raw output:
- [Swift phase6](../agent-reports/swift-phase6.md), [Kotlin phase6](../agent-reports/kotlin-phase6.md)
- [Standalone Luna](../agent-reports/luna-control.md)
- [Team full v2 evidence](v2-evidence.md)
- [Standalone external oracle evaluation](luna-control-evidence.md)

## Repair counts

Counts refer only to explicit recorded review correction rounds or extra implementation candidate repairs, excluding draft feedback, expected RED tests, and tool/sandbox retries. Command executed:

```sh
wc -l docs/experiments/team-review-repairs.tsv docs/experiments/phase6-team-repairs.tsv docs/experiments/phase6-control-repairs.tsv
```

Raw output:

```text
       4 docs/experiments/team-review-repairs.tsv
       0 docs/experiments/phase6-team-repairs.tsv
       0 docs/experiments/phase6-control-repairs.tsv
       4 total
```

## Interpretation

The experiment establishes that both configurations can make this small specified effect change and that an independent oracle detects missing changes. It does not establish that either model organization is best for general Human No-Code Development. There is only one trial per configuration, caches are warm, contexts and access boundaries differ, the orchestrator runs unrelated tasks concurrently, and actual cost metadata is unavailable. Cost comparison remains unmeasured.


## Final infrastructure hardening

After both full native change evaluations, an additional shared-harness status guard was strengthened: only comparator exits 0/1 are verdicts; all other statuses, including negative POSIX signal statuses, are infrastructure failures. This did not change native sources, contract or normal mutation expectations. The final team gate was rerun; standalone full external evidence describes the earlier reviewed harness run, not a new model repair. See [final-hardened-evidence.md](final-hardened-evidence.md).
