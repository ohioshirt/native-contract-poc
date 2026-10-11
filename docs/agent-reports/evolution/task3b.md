# Task3B Swift managed actor and completed history runner

Worktree: `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`.
Evaluator: frozen r1 `c801ad810217540101718dfd933d6d8d35333c180954666fd5905ad695770d60`.
Worker: delegated Sol; no agents spawned, no staging or commits.

## Implementation and contract correspondence

Added `ios/Sources/AsyncNativeContract/ManagedAsyncSession.swift`, `ios/Sources/ManagedHistoryRunner/HistoryProcessor.swift`, `RunnerMain.swift`, managed actor and runner tests in `ios/Tests/AsyncNativeContractTests/`, and SwiftPM target/product additions in `ios/Package.swift`.

The facade owns one private low-level `AsyncSession` and one immutable retained reference owner. Every opaque final `RefreshRequest` retains that owner and exposes only its immutable request ID to an external client. The exact required owner guard occurs once, and both response kinds pass through it before numeric correlation. No public session, owner, constructor, restore or numeric-response API is exposed. The actor's complete validation, reduction, token creation and result snapshot has no internal suspension. Snapshots and result effects are immutable value observations; caller array mutation is detached. The abstraction is `(session.state, session.pendingRequestId, session.nextRequestId, owner)`: actor serialization supplies the critical section and private retained identity supplies owner discrimination.

Existing low-level Swift sources and the independently approved Luna Logout tests were retained without edits by this worker. No Android sources were read or edited. No protected evaluator, spec, scripts or frozen guides were edited.

The runner decodes and encodes signed 64-bit IDs as `Int64`, creates real managed owners, and launches actual TaskGroup callers behind a per-phase common start barrier. One short NSLock recorder supplies global invocation/return timestamps across owners and never locks over an API await. Calls and snapshots are stamped immediately around the actual actor operation. Tokens are published to the completion store only after producer return is stamped; response events carry the same actual returned object with its producing owner/ID and original tokenRef metadata. Every task is joined, dependency/phase edges are retained, failures reject the complete run, and each scenario chooses one entire observed trial from at most 20 trials. There is no expected-state synthesis or row mixing. Missing required overlap remains an observed complete history for the external checker to classify as INCONCLUSIVE.

Native tests cover equal-number foreign responses of both kinds including foreign-before-stale ordering; canceled and duplicate tokens; aliases; retained snapshots and detached effects; the final two signed64 IDs, Logout and exhaustion; concurrent expiration allocation and coherent snapshots. Runner tests cover exact MAX token JSON/provenance, full operation inventory and phase ordering, real overlap with unique timestamps, and a missing actual token rejecting the whole run.

## Evidence and limits

The managed actor and runner APIs first failed compilation while absent; raw RED logs are retained. The runner RED test expression was corrected before recording the final expected missing-API RED. Focused tests, the brief's Swift platform suite, product build and actual frozen workload run exited 0. The external checker report is `PASS`, with required concurrency coverage true. This is bounded completed-history evidence, not a native refinement proof or an unbounded concurrency guarantee. Parent owns aggregate/common API probes and native owner-guard mutation gates; those were not run by this worker.

The command list is `reports/evolution/task3b/commands.txt`; all raw stdout/stderr and histories remain in that directory. Test counts below are quoted only from the corresponding raw output, without combining suites.

### RED: managed API absent

```sh
swift test --package-path ios --filter ManagedAsyncSessionTests > reports/evolution/task3b/red.log 2>&1
```

Exit: `1`. Raw output tail:

```text
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedAsyncSessionTests.swift:8:60: error: cannot find type 'RefreshRequest' in scope
    |                                                            `- error: cannot find type 'RefreshRequest' in scope
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedAsyncSessionTests.swift:8:35: error: cannot find type 'ManagedResult' in scope
    |                                   `- error: cannot find type 'ManagedResult' in scope
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedAsyncSessionTests.swift:15:36: error: cannot find type 'ManagedSnapshot' in scope
    |                                    `- error: cannot find type 'ManagedSnapshot' in scope
[Complete raw last 10 lines: reports/evolution/task3b/red.log.tail.txt]
```

### Managed actor tests

```sh
swift test --package-path ios --filter ManagedAsyncSessionTests > reports/evolution/task3b/managed-tests.log 2>&1
```

Exit: `0`. Raw output tail:

```text
Test Case '-[AsyncNativeContractTests.ManagedAsyncSessionTests testLastTwoIdsAndLogoutExhaustionAreAtomic]' started.
Test Case '-[AsyncNativeContractTests.ManagedAsyncSessionTests testLastTwoIdsAndLogoutExhaustionAreAtomic]' passed (0.000 seconds).
Test Case '-[AsyncNativeContractTests.ManagedAsyncSessionTests testParallelExpirationsAllocateOnceWithCoherentSnapshots]' started.
Test Case '-[AsyncNativeContractTests.ManagedAsyncSessionTests testParallelExpirationsAllocateOnceWithCoherentSnapshots]' passed (0.002 seconds).
Test Suite 'ManagedAsyncSessionTests' passed at 2026-10-12 01:36:09.487.
	 Executed 5 tests, with 0 failures (0 unexpected) in 0.004 (0.005) seconds
Test Suite 'AsyncNativeContractTests.xctest' passed at 2026-10-12 01:36:09.488.
	 Executed 5 tests, with 0 failures (0 unexpected) in 0.004 (0.005) seconds
Test Suite 'Selected tests' passed at 2026-10-12 01:36:09.488.
	 Executed 5 tests, with 0 failures (0 unexpected) in 0.004 (0.006) seconds
```

### RED: runner API absent

```sh
swift test --package-path ios --filter ManagedHistoryRunnerTests > reports/evolution/task3b/runner-red.log 2>&1
```

Exit: `1`. Raw output tail:

```text
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedHistoryRunnerTests.swift:10:32: error: cannot find 'ManagedHistoryProcessor' in scope
   |                                `- error: cannot find 'ManagedHistoryProcessor' in scope
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedHistoryRunnerTests.swift:38:32: error: cannot find 'ManagedHistoryProcessor' in scope
   |                                `- error: cannot find 'ManagedHistoryProcessor' in scope
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/Tests/AsyncNativeContractTests/ManagedHistoryRunnerTests.swift:57:27: error: cannot find 'ManagedHistoryProcessor' in scope
   |                           `- error: cannot find 'ManagedHistoryProcessor' in scope
[Complete raw last 10 lines: reports/evolution/task3b/runner-red.log.tail.txt]
```

### Runner tests

```sh
swift test --package-path ios --filter ManagedHistoryRunnerTests > reports/evolution/task3b/runner-tests.log 2>&1
```

Exit: `0`. Raw output tail:

```text
Test Case '-[AsyncNativeContractTests.ManagedHistoryRunnerTests testMissingActualTokenRejectsWholeRun]' started.
Test Case '-[AsyncNativeContractTests.ManagedHistoryRunnerTests testMissingActualTokenRejectsWholeRun]' passed (0.001 seconds).
Test Case '-[AsyncNativeContractTests.ManagedHistoryRunnerTests testRunnerRecordsActualMaxTokenAndEveryOperationWithPhaseEdges]' started.
Test Case '-[AsyncNativeContractTests.ManagedHistoryRunnerTests testRunnerRecordsActualMaxTokenAndEveryOperationWithPhaseEdges]' passed (0.001 seconds).
Test Suite 'ManagedHistoryRunnerTests' passed at 2026-10-12 01:39:08.007.
	 Executed 3 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'AsyncNativeContractTests.xctest' passed at 2026-10-12 01:39:08.007.
	 Executed 3 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'Selected tests' passed at 2026-10-12 01:39:08.007.
	 Executed 3 tests, with 0 failures (0 unexpected) in 0.003 (0.005) seconds
```

### Swift platform suite

```sh
swift test --package-path ios > reports/evolution/task3b/swift-tests.log 2>&1
```

Exit: `0`. Raw output tail:

```text
Test Suite 'All tests' passed at 2026-10-12 01:39:39.036.
	 Executed 18 tests, with 0 failures (0 unexpected) in 0.009 (0.011) seconds
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```

### Runner product build

```sh
swift build --package-path ios --product ManagedHistoryRunner > reports/evolution/task3b/build.log 2>&1
```

Exit: `0`. Raw output tail:

```text
Building for debugging...
[Planning deferred tasks]
Build complete! (0.42秒)
```

### Frozen workload actual history

```sh
ios/.build/debug/ManagedHistoryRunner < verification/managed-workload.json > reports/evolution/task3b/history.json 2> reports/evolution/task3b/runner.stderr
```

Exit: `0`. Raw output tail:

```text
(empty output)
```

### External completed-history check

```sh
python3 -m verification.linearizability --workload verification/managed-workload.json --history reports/evolution/task3b/history.json --report reports/evolution/task3b/linearizability.json > reports/evolution/task3b/checker.log 2>&1
```

Exit: `0`. Raw output tail:

```text
      "scenario": "last-two-ids",
      "concurrencyCoverage": {}
    }
  ],
  "bounds": {
    "operations": 16,
    "nodes": 1000000,
    "seconds": 10
  }
}
```

### Whitespace review

```sh
git diff --check -- ios > reports/evolution/task3b/diff-check.log 2>&1
```

Exit: `0`. Raw output tail:

```text
(empty output)
```

### External checker observed verdicts

```json
{
  "verdict": "PASS",
  "histories": [
    {
      "scenario": "foreign-same-id",
      "verdict": "PASS",
      "concurrencyCoverage": {}
    },
    {
      "scenario": "logout-vs-success",
      "verdict": "PASS",
      "concurrencyCoverage": {
        "2": true
      }
    },
    {
      "scenario": "logout-vs-failure",
      "verdict": "PASS",
      "concurrencyCoverage": {
        "2": true
      }
    },
    {
      "scenario": "stale-after-new-request",
      "verdict": "PASS",
      "concurrencyCoverage": {}
    },
    {
      "scenario": "simultaneous-expiration",
      "verdict": "PASS",
      "concurrencyCoverage": {
        "1": true
      }
    },
    {
      "scenario": "max-logout-exhaustion",
      "verdict": "PASS",
      "concurrencyCoverage": {}
    },
    {
      "scenario": "last-two-ids",
      "verdict": "PASS",
      "concurrencyCoverage": {}
    }
  ]
}
```

Observed whole-trial selection (read from recorded history):

```json
[
  {
    "scenario": "foreign-same-id",
    "trial": 0
  },
  {
    "scenario": "logout-vs-success",
    "trial": 2
  },
  {
    "scenario": "logout-vs-failure",
    "trial": 0
  },
  {
    "scenario": "stale-after-new-request",
    "trial": 0
  },
  {
    "scenario": "simultaneous-expiration",
    "trial": 1
  },
  {
    "scenario": "max-logout-exhaustion",
    "trial": 0
  },
  {
    "scenario": "last-two-ids",
    "trial": 0
  }
]
```
