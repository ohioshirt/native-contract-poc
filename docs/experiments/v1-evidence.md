# Baseline v1 local evidence

Command: `bash scripts/verify.sh "$PWD/reports/v1-accepted"`; exit 0. These are recorded command logs/tails from this run, not forecasts. Raw logs/traces remain locally under reports/v1-accepted. The source manifest records the then-dirty tree; hosted CI will identify a clean commit.

Overall: PASS

## python-tests (exit 0)

Command: $ python3 -m unittest discover -s verification -p test_\*.py -v

stdout tail:
```
```
stderr tail:
```
test_identical_malformed_native_traces_are_rejected (test_verification.TraceTests) ... ok
test_malformed_step_fields_are_rejected (test_verification.TraceTests) ... ok
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests) ... ok

----------------------------------------------------------------------
Ran 26 tests in 0.137s

OK
```

## swift-build (exit 0)

Command: $ swift build --package-path ios

stdout tail:
```
Building for debugging...
[1 / 7]
Build complete! (0.34秒)
```
stderr tail:
```
```

## swift-test (exit 0)

Command: $ swift test --package-path ios

stdout tail:
```
Test Suite 'TraceRunnerTests' passed at 2026-10-09 13:13:36.673.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.001 (0.001) seconds
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 13:13:36.673.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'All tests' passed at 2026-10-09 13:13:36.673.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.003 (0.005) seconds
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```
stderr tail:
```
Building for debugging...
[1 / 12]
Build complete! (0.32秒)
```

## kotlin-build (exit 0)

Command: $ ./android/gradlew -p android build :library:installDist

stdout tail:
```
> Task :library:processTestResources NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test UP-TO-DATE
> Task :library:check UP-TO-DATE
> Task :library:build UP-TO-DATE
> Task :library:installDist UP-TO-DATE

BUILD SUCCESSFUL in 550ms
8 actionable tasks: 8 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr tail:
```
```

## contract-generate (exit 0)

Command: $ python3 verification/generate.py --wire-input --output /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/scenarios.json

stdout tail:
```
```
stderr tail:
```
```

## swift-runner (exit 0)

Command: $ bash -c ios/.build/debug/TraceRunner\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/swift-traces.json

stdout tail:
```
```
stderr tail:
```
```

## kotlin-runner (exit 0)

Command: $ bash -c android/library/build/install/library/bin/library\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/kotlin-traces.json

stdout tail:
```
```
stderr tail:
```
```

## differential (exit 0)

Command: $ python3 verification/verify.py --report /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/summary.json --markdown /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/summary.md --swift /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/swift-traces.json --kotlin /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/kotlin-traces.json

stdout tail:
```
oracle: PASS
swift: PASS
kotlin: PASS
differential: PASS
```
stderr tail:
```
```

## native-differential (exit 0)

Command: $ python3 verification/compare.py --left /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/swift-traces.json --right /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/kotlin-traces.json

stdout tail:
```
PASS: 781 scenarios, ordered state/effect traces match
```
stderr tail:
```
```

## mutations (exit 0)

Command: $ python3 scripts/mutations.py verification/mutation-matrix.json --output /Users/shigeo/work/mobile/native-contract-poc/reports/v1-accepted/mutations

stdout tail:
```
A-swift-authenticated-token-expiry-next-state: PASS {'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
B-kotlin-refresh-failure-effect: PASS {'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-logout-effect: PASS {'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
```
stderr tail:
```
```

## git-sha
```
ef5b98ff66ba64ae3a3f251ddec503f5ec208d71
```

## git-dirty
```
dirty
```

## contract-sha256
```
9fec360d43f7f730867a6d5819e9065d629f55c107a6172a81f7016e2bdfee34  contract/specification.json
```

## swift-version
```
swift-driver version: 1.168.6 Apple Swift version 6.4 (swiftlang-6.4.0.34.1 clang-2100.3.34.1)
Target: arm64-apple-macosx27.0.0
```

## xcode-version
```
Xcode 27.1
Build version 27A9269
```

## java-version
```
openjdk version "17.0.13" 2024-10-15 LTS
OpenJDK Runtime Environment Corretto-17.0.13.11.1 (build 17.0.13+11-LTS)
OpenJDK 64-Bit Server VM Corretto-17.0.13.11.1 (build 17.0.13+11-LTS, mixed mode, sharing)
```

## kotlin-version
```
    kotlin("jvm") version "2.3.20" apply false
```

## python-version
```
Python 3.9.6
```

# Native contract verification

| Check | Verdict |
|---|---|---|
| oracle | PASS |
| swift | PASS |
| kotlin | PASS |
| differential | PASS |

Scenarios: 781

## Comparator diagnostics

### swift

- No mismatches

### kotlin

- No mismatches

### differential

- No mismatches
