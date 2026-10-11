# Final contract evolution integration review

Verdict: **APPROVED** for the integrated implementation and evaluator. No important actionable blocker or genuinely missing implementation acceptance criterion was found. The r2 aggregate result was completed and inspected before finalizing this review: it records PASS, exit 0, Overall: PASS and the unchanged candidate digest. The controller retains final result-binding verification and evidence finalization. This review did not rerun the gate.

Date: 2026-10-12. Worktree: `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`. Baseline: `8458f66a0691532a7f48e7ca1fb14fc86238b67f`.

## Scope and method

Read the approved design/plan and requested scoped reviews: plan, Task 1, Task 2, Task 5A/6A including API fix1, Logout, Swift managed and Kotlin managed. Inspected current git status/diff, both managed facades and low-level/oracle boundary, history checker, numeric explorer, protocol implementation and actual r2 manifest, evaluator/API/mutation drivers, verification scripts, CI entry point, frozen workload/native/history briefs, test coverage inventory, controller ledger, baseline/core compatibility evidence and available candidate reports.

Read-only apart from this report. No native builds, test suites, model/mutation runs, source edits, nested agents, staging or commits were performed. Focused reviewer commands only read sources/evidence. Existing worker/gate results are distinguished from reviewer executions; no new test totals are claimed. Scoped reviews remain the detailed individual source reviews.

## Integration assessment

- **Logout and compatibility:** The sole intentional behavior difference is the v4 async Refreshing/Logout row. Both native branches clear pending and emit ClearCredentials without changing the allocator, including exhausted null. Managed calls delegate after ownership validation. The JSON full-step oracle agrees, and low-level trace wire remains intact. Reviewer comparison confirmed synchronous fields excluding version/async and baseline synchronous source/test/build files are identical. Existing low-level APIs remain with caller assumptions; the facade adds stronger semantics without reinterpreting Swift value copies.
- **Ownership and atomicity:** Both facades retain private reference identity and own one low-level session. Foreign tokens are rejected before numeric stale handling with unchanged full snapshot, no effects and ForeignRequest. Swift handle has no await; Kotlin validation/reduction/token creation/result construction and snapshot share one private monitor. Immutable tokens/results and detached effects match checker/API fixtures. Ordinary external Swift/Kotlin source clients are the stated boundary; Kotlin internal helpers are not JVM bytecode secrecy. Physical effects/transport guarantees are not inferred.
- **History/model correspondence:** The frozen verifier-owned workload fixes setup/handle/snapshot membership and metadata. Actual responses reference observed producer effects after producer return. The checker validates complete observations and every global return-before-invoke edge, allowing different schedules across platforms. Bounds and insufficient overlap are INCONCLUSIVE/non-PASS. Exporters use actual callers and whole-trial recording per scoped reviews. The independent finite reducer compares reachable full observations with the bounded oracle; issued-ID sets are ghost state. Numeric controls and actual native owner mutants are separate required evidence.
- **Freeze/verdict integrity:** The actual r2 manifest protects schema/spec/oracle/formal/evaluator/scripts and workload/probes/briefs; it records native allowances, named argv/artifact/timeout/verdict stages and generated/evidence exclusions. Saved baseline distributions are protected exceptions. Result checks bind source/manifest/stage/attempt, command/log hashes and report hashes. Missing/stale/malformed artifacts, source edits, timeout/signals/build failures and incomplete paths cannot yield PASS. API fix1 was reviewed/refrozen as r2; r1 stays archived/superseded with INFRA_FAILURE. No ranking/cost metrics are invented.
- **Gate and meaningful coverage:** verify.sh retains synchronous/async/formal/native/mutation gates and adds managed verification; existing CI invokes it. Skips and absent runners stay non-PASS. Tests address illegal/allowed orderings, dropped calls/snapshots, provenance, impossible observations, search/overlap bounds, exhaustion, aliases/detachment and foreign equal-number responses. Deterministic native foreign controls require successful mutant build and execution before semantic checker rejection; compiler errors do not count as detection.

## Reviewer evidence

Executed read-only record/source binding command:

```sh
bash scripts/change-protocol.sh check --candidate /Users/shigeo/.codex/worktrees/b195/native-contract-poc --manifest /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/manifest-r2.json --manifest-digest 2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481 --result /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/old-native-red-01/result.json
```

Entire raw output, exit 0:

```text
{"candidateDigest": "635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157", "classification": "PASS", "manifestDigest": "2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481"}
```

That PASS validates binding; the old-native attempt remains SEMANTIC_FAIL. Its frozen argv is `python3 -m verification.async_verify --output <attempt>/async --swift <candidate>/reports/evolution/baseline-native/AsyncTraceRunner --kotlin <candidate>/reports/evolution/baseline-native/async-library/bin/async-library`. Inspected `tail -n 10 reports/evolution/protocol-r2/old-native-red-01/stderr.log`:

```text
kotlin: logout-after-final-allocation-preserves-exhaustion step 2: state mismatch
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

Executed compatibility/source comparison:

```sh
python3 - <<'PY'
import json, subprocess
from pathlib import Path
base='8458f66a0691532a7f48e7ca1fb14fc86238b67f'
old=json.loads(subprocess.check_output(['git','show',base+':contract/specification.json']))
new=json.loads(Path('contract/specification.json').read_text())
for d in (old,new):
    d.pop('version'); d.pop('async')
assert old == new
print('CORE_SPEC_UNCHANGED_EXCLUDING_VERSION_ASYNC')
paths=subprocess.check_output(['git','ls-tree','-r','--name-only',base,'ios/Sources/NativeContract','ios/Sources/TraceRunner','ios/Tests/NativeContractTests','android/library'],text=True).splitlines()
for path in paths:
    assert Path(path).read_bytes() == subprocess.check_output(['git','show',base+':'+path]), path
print('BASELINE_CORE_SOURCE_TEST_BUILD_FILES_IDENTICAL')
p=Path('reports/evolution/protocol-r2/candidate-full-01/result.json')
if p.exists():
    r=json.loads(p.read_text()); print('R2_CANDIDATE_CLASSIFICATION',r['classification'])
else:
    print('R2_CANDIDATE_RESULT_PENDING')
PY
```

Entire raw output, exit 0:

```text
CORE_SPEC_UNCHANGED_EXCLUDING_VERSION_ASYNC
BASELINE_CORE_SOURCE_TEST_BUILD_FILES_IDENTICAL
R2_CANDIDATE_RESULT_PENDING
```

Already-completed managed subgate command inspected, not rerun:

```sh
bash scripts/managed-verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm
```

Recorded exit code: 0. Its managed-report.json records PASS for numeric, both actual histories, both external API gates and owner mutations. Each native owner mutant record contains build exit 0, runner exit 0 and checker FAIL. Inspected `tail -n 10 reports/evolution/protocol-r2/candidate-full-01/full/managed-verify.stdout.log`:

```text
          },
          "checkerVerdict": "FAIL",
          "verdict": "PASS",
          "semanticDetection": "real foreign-same-id history has no legal managed serialization"
        }
      ]
    }
  },
  "limits": "2 owners, IDs 1..3 finite model; completed histories <=16 operations; no unbounded refinement proof"
}
```

## Acceptance boundary

No additional feature or widened guarantee is required. Controller must validate the completed r2 result binding and finalize evolution-evidence.md/controller ledger from actual command/tails. The earlier draft pending status during active evaluation was not an implementation defect. No unbounded native refinement/concurrency, liveness, physical effect ordering, recovery, transport authentication, hostile runtime-client secrecy or controlled model-ranking experiment is established or claimed.

Report hygiene: the first write command failed with a shell heredoc-delimiter parse error before writing. This corrected command used a unique delimiter. No implementation source changed.

## Completed r2 aggregate evidence inspected

The earlier pending observation above was made during evaluation. Before this review was finalized, the completed result was read with:

```sh
python3 - <<'PY'
import json
from pathlib import Path
p=Path('reports/evolution/protocol-r2/candidate-full-01/result.json')
d=json.loads(p.read_text())
for key in ('argv','classification','exitCode','candidateDigest','manifestDigest','timedOut'):
    print(key, d[key])
report=p.parent/'full/report.md'
print('reportFirstLine',report.read_text().splitlines()[0])
PY
```

Entire raw inspection output, exit 0:

```text
argv ['bash', 'scripts/verify.sh', '/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full']
classification PASS
exitCode 0
candidateDigest 635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157
manifestDigest 2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481
timedOut False
reportFirstLine Overall: PASS
```

The exact completed child command is the printed argv above. Its captured command.json agrees. `tail -n 10 reports/evolution/protocol-r2/candidate-full-01/stdout.log` and the corresponding stderr.log tail both emitted no content; the full report retains each component's command and raw tails. This is inspection of the controller's execution, not a reviewer build/test run. Overall integration verdict remains **APPROVED**.
