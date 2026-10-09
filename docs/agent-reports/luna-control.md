# Luna control experiment report

Workspace: `/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/native-contract-luna-control-jski6y9o`

The contract now specifies that `Authenticated × LoginSucceeded` leaves the state `Authenticated` and returns exactly `[ClearCredentials]`. Swift and Kotlin implement this effect directly. The native tests retain the full state/event tables with the changed expected value, and each adds a focused regression asserting the state and the one-element effect list. No credential or session identifier is represented or generated.

## Contract-only rejection check

First candidate: contract transition only; native source remained unchanged. The initial direct `./scripts/verify.sh` launch did not start because the script lacks executable permission (`zsh:1: permission denied`). The same supplied gate was then run through `bash`. Its first sandboxed attempt could not build Swift (compiler sandbox denied) or start Gradle (socket operation denied). The gate was rerun with escalation and produced native traces. No verifier, script, schema, or runner was changed.

Command:

```sh
SKIP_MUTATIONS=1 GRADLE_USER_HOME=/Users/shigeo/work/mobile/native-contract-poc/.gradle-home CLANG_MODULE_CACHE_PATH="$PWD/.swift-cache/clang" SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.swift-cache/modules" bash scripts/verify.sh reports/luna-control-contract-only
```

Clock start: `2026-10-09 04:10:42 UTC`. The exec session returned over three polling calls totaling 15 seconds of reported `wall_time_seconds`, following the initial 4-second call; the completion call reported 0 seconds.

Raw output tails from `reports/luna-control-contract-only/report.md`:

```text
oracle: PASS
swift: FAIL
kotlin: FAIL
differential: PASS
```

```text
s0532 step 3: Expected={'event': 'LoginSucceeded', 'state': 'Authenticated', 'effects': ['ClearCredentials']}; Swift={'effects': [], 'event': 'LoginSucceeded', 'state': 'Authenticated'}; Kotlin={'event': 'LoginSucceeded', 'state': 'Authenticated', 'effects': []} (both diverged)
```

This establishes that the revised contract rejects the unchanged native traces.

## Native candidate and repair history

One implementation candidate followed: Swift and Kotlin reducers were changed for the one transition, and their two reducer test suites were strengthened with the same focused regression. There were no implementation repair attempts after this candidate. The full measured gate passed on the first candidate.

Exact measured command:

```sh
SKIP_MUTATIONS=1 GRADLE_USER_HOME=/Users/shigeo/work/mobile/native-contract-poc/.gradle-home CLANG_MODULE_CACHE_PATH="$PWD/.swift-cache/clang" SWIFTPM_MODULECACHE_OVERRIDE="$PWD/.swift-cache/modules" bash scripts/verify.sh reports/luna-control-final
```

Clock start: `2026-10-09 04:11:36 UTC`; finish: `2026-10-09 04:11:49 UTC`; elapsed wall clock: 13 seconds.

The raw tails below are from `reports/luna-control-final/report.md`:

```text
Ran 22 tests in 0.082s

OK
```

```text
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 13:11:43.043.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 13:11:43.043.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
```

```text
BUILD SUCCESSFUL in 1s
8 actionable tasks: 8 executed
```

```text
oracle: PASS
swift: PASS
kotlin: PASS
differential: PASS
```

```text
PASS: 781 scenarios, ordered state/effect traces match
```

The gate completed with exit code 0 and `Overall: PASS`. Mutation analysis was intentionally skipped by the requested `SKIP_MUTATIONS=1`; it was not run separately. No billable token or cost data is exposed by the available tools. No human intervention occurred; a sandbox escalation was used after the sandboxed gate could not launch the compilers/build system.

## Paths changed

- `contract/specification.json`
- `ios/Sources/NativeContract/AuthReducer.swift`
- `ios/Tests/NativeContractTests/ReducerTests.swift`
- `android/library/src/main/kotlin/nativecontract/SessionReducer.kt`
- `android/library/src/test/kotlin/nativecontract/SessionReducerTest.kt`
- `docs/agent-reports/luna-control.md`
