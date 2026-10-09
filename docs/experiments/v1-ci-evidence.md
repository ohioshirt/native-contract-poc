# Baseline v1 hosted CI evidence

Run: https://github.com/ohioshirt/native-contract-poc/actions/runs/37883044062

`gh run view 37883044062 --repo ohioshirt/native-contract-poc --json status,conclusion,url` returned:

```json
{"conclusion":"success","status":"completed","url":"https://github.com/ohioshirt/native-contract-poc/actions/runs/37883044062"}
```

Artifact downloaded using `gh run download 37883044062 --repo ohioshirt/native-contract-poc --dir reports/ci-v1`. The actual clean-source report follows.

Overall: PASS

## python-tests (exit 0)

Command: $ python3 -m unittest discover -s verification -p test_\*.py -v

stdout tail:
```
```
stderr tail:
```
test_identical_malformed_native_traces_are_rejected (test_verification.TraceTests.test_identical_malformed_native_traces_are_rejected) ... ok
test_malformed_step_fields_are_rejected (test_verification.TraceTests.test_malformed_step_fields_are_rejected) ... ok
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests.test_oracle_preserves_ordered_effects_and_step_states) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests.test_schema_rejects_transition_missing_effects) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests.test_schema_rejects_unknown_keyword_instead_of_ignoring_it) ... ok

----------------------------------------------------------------------
Ran 26 tests in 0.136s

OK
```

## swift-build (exit 0)

Command: $ swift build --package-path ios

stdout tail:
```
[3/7] Write swift-version-4657CCE4B953477C.txt
[5/10] Emitting module NativeContract
[6/10] Compiling NativeContract TraceDocumentProcessor.swift
[7/10] Compiling NativeContract AuthReducer.swift
[8/12] Emitting module TraceRunner
[9/12] Compiling TraceRunner main.swift
[9/12] Write Objects.LinkFileList
[10/12] Linking TraceRunner
[11/12] Applying TraceRunner
Build complete! (8.34s)
```
stderr tail:
```
```

## swift-test (exit 0)

Command: $ swift test --package-path ios

stdout tail:
```
Test Case '-[NativeContractTests.TraceRunnerTests testUnknownEventIsRejected]' passed (0.000 seconds).
Test Suite 'TraceRunnerTests' passed at 2026-10-09 04:17:25.796.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.003 (0.003) seconds
Test Suite 'NativeContractPackageTests.xctest' passed at 2026-10-09 04:17:25.796.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.004 (0.005) seconds
Test Suite 'All tests' passed at 2026-10-09 04:17:25.796.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.004 (0.007) seconds
◇ Test run started.
↳ Testing Library Version: 102 (arm64e-apple-macos13.0)
✔ Test run with 0 tests passed after 0.001 seconds.
```
stderr tail:
```
[0/8] Write sources
[3/8] Write swift-version-4657CCE4B953477C.txt
[5/9] Compiling NativeContractTests TraceRunnerTests.swift
[6/9] Compiling NativeContractTests ReducerTests.swift
[7/9] Emitting module NativeContractTests
[8/11] Compiling NativeContractPackageTests runner.swift
[9/11] Emitting module NativeContractPackageTests
[9/11] Write Objects.LinkFileList
[10/11] Linking NativeContractPackageTests
Build complete! (17.02s)
```

## kotlin-build (exit 0)

Command: $ ./android/gradlew -p android build :library:installDist

stdout tail:
```
> Task :library:compileTestKotlin
> Task :library:compileTestJava NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test
> Task :library:check
> Task :library:build

BUILD SUCCESSFUL in 53s
8 actionable tasks: 8 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr tail:
```
```

## contract-generate (exit 0)

Command: $ python3 verification/generate.py --wire-input --output /Users/runner/work/_temp/native-contract-artifacts/scenarios.json

stdout tail:
```
```
stderr tail:
```
```

## swift-runner (exit 0)

Command: $ bash -c ios/.build/debug/TraceRunner\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/runner/work/_temp/native-contract-artifacts/scenarios.json /Users/runner/work/_temp/native-contract-artifacts/swift-traces.json

stdout tail:
```
```
stderr tail:
```
```

## kotlin-runner (exit 0)

Command: $ bash -c android/library/build/install/library/bin/library\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/runner/work/_temp/native-contract-artifacts/scenarios.json /Users/runner/work/_temp/native-contract-artifacts/kotlin-traces.json

stdout tail:
```
```
stderr tail:
```
```

## differential (exit 0)

Command: $ python3 verification/verify.py --report /Users/runner/work/_temp/native-contract-artifacts/summary.json --markdown /Users/runner/work/_temp/native-contract-artifacts/summary.md --swift /Users/runner/work/_temp/native-contract-artifacts/swift-traces.json --kotlin /Users/runner/work/_temp/native-contract-artifacts/kotlin-traces.json

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

Command: $ python3 verification/compare.py --left /Users/runner/work/_temp/native-contract-artifacts/swift-traces.json --right /Users/runner/work/_temp/native-contract-artifacts/kotlin-traces.json

stdout tail:
```
PASS: 781 scenarios, ordered state/effect traces match
```
stderr tail:
```
```

## mutations (exit 0)

Command: $ python3 scripts/mutations.py verification/mutation-matrix.json --output /Users/runner/work/_temp/native-contract-artifacts/mutations

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
aaee28285f2f28ecf713d299efdf1edfc9b659ce
```

## git-dirty
```
clean
```

## contract-sha256
```
9fec360d43f7f730867a6d5819e9065d629f55c107a6172a81f7016e2bdfee34  contract/specification.json
```

## swift-version
```
swift-driver version: 1.115.1 Apple Swift version 6.0.3 (swiftlang-6.0.3.1.10 clang-1600.0.30.1)
Target: arm64-apple-macosx15.0
```

## xcode-version
```
Xcode 16.2
Build version 16C5032a
```

## java-version
```
openjdk version "17.0.13" 2024-10-15
OpenJDK Runtime Environment Temurin-17.0.13+11 (build 17.0.13+11)
OpenJDK 64-Bit Server VM Temurin-17.0.13+11 (build 17.0.13+11, mixed mode, sharing)
```

## kotlin-version
```
    kotlin("jvm") version "2.3.20" apply false
```

## python-version
```
Python 3.12.8
```

# Native contract verification

| Check | Verdict |
|---|---|
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
