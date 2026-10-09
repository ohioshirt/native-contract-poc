# Standalone Luna external evaluation

The standalone worker used an isolated baseline source copy and changed contract/native tests/native reducers without modifying the supplied verifier. Root independently constructed the target contract from the baseline and the user request, then compared the worker traces using the fixed root verification code. All behavioral contract fields equal the target. The standalone worker retained version=1 while Sol incremented version=2; incrementing this metadata was not explicit in the standalone brief. Versioning differs, but oracle expectations remain rooted in the Sol-defined target, never native output.

External command:

```sh
python3 verification/verify.py --spec reports/luna-control/target-specification.json --swift reports/luna-control/final/swift-traces.json --kotlin reports/luna-control/final/kotlin-traces.json --report reports/luna-control/external-summary.json --markdown reports/luna-control/external-summary.md
```

Raw stdout:

```text
oracle: PASS
swift: PASS
kotlin: PASS
differential: PASS
```

Worker build/test commands and raw tails: [luna-control.md](../agent-reports/luna-control.md). Full local copied evidence: reports/luna-control/. The worker trial skipped Mutation. After it ended, root externally evaluated unchanged standalone native sources in a fresh directory with the same fixed Sol target and reviewed harness, including the full Mutation matrix. The full external gate completed with exit 0; original and evaluated native source bytes were asserted equal. Full external evidence is appended below. This external evaluation is not a worker repair or model-cost measurement.

This is one exploratory trial using a pre-review-fix harness snapshot for the standalone worker and the fixed shared oracle for external evaluation. Both trials reuse toolchain caches; native edits are tiny, and timing excludes baseline environment construction. The standalone worker can see both native trees, whereas the team isolates each native implementer's context. These are confounders, not a controlled statistical comparison. Billable usage is not exposed, so no token or monetary cost is reported. A JSON-version metadata check initially failed; behavior equality was then checked separately, preserving rather than concealing the metadata difference.


## Full external gate

Command executed in a fresh evaluation directory containing byte-identical standalone native source plus the reviewed root contract/tools:

```sh
GRADLE_USER_HOME=/Users/shigeo/work/mobile/native-contract-poc/.gradle-home CLANG_MODULE_CACHE_PATH=/Users/shigeo/work/mobile/native-contract-poc/.swift-cache/clang SWIFTPM_MODULECACHE_OVERRIDE=/Users/shigeo/work/mobile/native-contract-poc/.swift-cache/modules bash scripts/verify.sh /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external
```

The evaluation copy is outside Git; its revision is unavailable. The recorded source manifest and asserted original/evaluated byte identity identify native code; the official main CI below uses a clean immutable Git revision.

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
Ran 26 tests in 0.135s

OK
```

## swift-build (exit 0)

Command: $ swift build --package-path ios

stdout tail:
```
[50 / 78]
[53 / 78]
[56 / 78]
[58 / 78]
[59 / 78]
[62 / 78] NativeContract
[71 / 79] TraceRunner-product
[74 / 81] TraceRunner-product
[79 / 81] TraceRunner-product
Build complete! (7.29秒)
```
stderr tail:
```
```

## swift-test (exit 0)

Command: $ swift test --package-path ios

stdout tail:
```
Test Suite 'TraceRunnerTests' passed at 2026-10-09 13:22:50.859.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.001 (0.002) seconds
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 13:22:50.859.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'All tests' passed at 2026-10-09 13:22:50.859.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.003 (0.005) seconds
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```
stderr tail:
```
[44 / 65]
[45 / 65]
[47 / 65]
[48 / 65]
[49 / 65]
[50 / 65]
[54 / 65] NativeContractTests-product
[59 / 65] NativeContractTests-product
[61 / 65] NativeContractTests-product
Build complete! (7.34秒)
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

BUILD SUCCESSFUL in 1s
8 actionable tasks: 8 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr tail:
```
```

## contract-generate (exit 0)

Command: $ python3 verification/generate.py --wire-input --output /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/scenarios.json

stdout tail:
```
```
stderr tail:
```
```

## swift-runner (exit 0)

Command: $ bash -c ios/.build/debug/TraceRunner\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/swift-traces.json

stdout tail:
```
```
stderr tail:
```
```

## kotlin-runner (exit 0)

Command: $ bash -c android/library/build/install/library/bin/library\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/kotlin-traces.json

stdout tail:
```
```
stderr tail:
```
```

## differential (exit 0)

Command: $ python3 verification/verify.py --report /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/summary.json --markdown /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/summary.md --swift /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/swift-traces.json --kotlin /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/kotlin-traces.json

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

Command: $ python3 verification/compare.py --left /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/swift-traces.json --right /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/kotlin-traces.json

stdout tail:
```
PASS: 781 scenarios, ordered state/effect traces match
```
stderr tail:
```
```

## mutations (exit 0)

Command: $ python3 scripts/mutations.py verification/mutation-matrix.json --output /Users/shigeo/work/mobile/native-contract-poc/reports/luna-control/full-external/mutations

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
unavailable
```

## git-dirty
```
clean
```

## contract-sha256
```
fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11  contract/specification.json
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
