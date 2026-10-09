# Async correlation local acceptance

Command: `bash scripts/verify.sh "$PWD/reports/async-final"`; exit 0. This is the final local run after native/parser, verification/failure, witnessed-counterexample and boundary-vector changes. Legacy native sources/tests were compared against f6605a4 with an empty diff. Canonical specification remains v3 SHA-256 2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f. No user source comparison/code edits were required.

Overall: PASS

## python-tests (exit 0)

Command: $ python3 -m unittest discover -s verification -p test_\*.py -v

stdout tail:
```
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```
stderr tail:
```
test_identical_malformed_native_traces_are_rejected (test_verification.TraceTests) ... ok
test_malformed_step_fields_are_rejected (test_verification.TraceTests) ... ok
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests) ... ok

----------------------------------------------------------------------
Ran 52 tests in 7.023s

OK
```

## formal-verify (exit 0)

Command: $ bash scripts/formal-verify.sh /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/formal-run.diohdm

stdout tail:
```
PASS: formal TLC model check; 16 observations; negative control detected TransitionSound
```
stderr tail:
```
```

## async-formal-verify (exit 0)

Command: $ bash scripts/async-formal-verify.sh /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/async-formal-run.nE1qc5

stdout tail:
```
PASS: async TLC; 19 distinct states; validated StaleResponseSafety counterexample
```
stderr tail:
```
```

## swift-build (exit 0)

Command: $ swift build --package-path ios

stdout tail:
```
Building for debugging...
[1 / 13]
Build complete! (0.81秒)
```
stderr tail:
```
```

## swift-test (exit 0)

Command: $ swift test --package-path ios

stdout tail:
```
Test Suite 'All tests' passed at 2026-10-09 14:52:57.333.
	 Executed 8 tests, with 0 failures (0 unexpected) in 0.004 (0.006) seconds
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
􀟈  Test run started.
􀄵  Testing Library Version: 2084
􀄵  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```
stderr tail:
```
Building for debugging...
[Using on-disk description]
Build complete! (0.37秒)
```

## kotlin-build (exit 0)

Command: $ ./android/gradlew -p android build :library:installDist :async-library:installDist

stdout tail:
```
> Task :library:testClasses UP-TO-DATE
> Task :library:test UP-TO-DATE
> Task :library:check UP-TO-DATE
> Task :library:build UP-TO-DATE
> Task :library:installDist UP-TO-DATE
> Task :async-library:installDist UP-TO-DATE

BUILD SUCCESSFUL in 519ms
16 actionable tasks: 16 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr tail:
```
```

## contract-generate (exit 0)

Command: $ python3 verification/generate.py --wire-input --output /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/scenarios.json

stdout tail:
```
```
stderr tail:
```
```

## swift-runner (exit 0)

Command: $ bash -c ios/.build/debug/TraceRunner\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/swift-traces.json

stdout tail:
```
```
stderr tail:
```
```

## kotlin-runner (exit 0)

Command: $ bash -c android/library/build/install/library/bin/library\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/scenarios.json /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/kotlin-traces.json

stdout tail:
```
```
stderr tail:
```
```

## async-runner (exit 0)

Command: $ bash scripts/async-verify.sh /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/async

stdout tail:
```
PASS: 19621 scenarios, 94842 steps; swift=PASS, kotlin=PASS, differential=PASS
```
stderr tail:
```
```

## differential (exit 0)

Command: $ python3 verification/verify.py --report /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/summary.json --markdown /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/summary.md --swift /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/swift-traces.json --kotlin /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/kotlin-traces.json

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

Command: $ python3 verification/compare.py --left /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/swift-traces.json --right /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/kotlin-traces.json

stdout tail:
```
PASS: 781 scenarios, ordered state/effect traces match
```
stderr tail:
```
```

## mutations (exit 0)

Command: $ python3 scripts/mutations.py verification/mutation-matrix.json --output /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/mutations

stdout tail:
```
A-swift-authenticated-token-expiry-next-state: PASS {'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
B-kotlin-refresh-failure-effect: PASS {'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-logout-effect: PASS {'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
```
stderr tail:
```
```

## async-mutations (exit 0)

Command: $ bash scripts/async-mutation-test.sh /Users/shigeo/work/mobile/native-contract-poc/reports/async-final/async-mutations

stdout tail:
```
A-swift-accepts-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
B-kotlin-resets-counter-on-accepted-logout: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-accept-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'} actual={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
```
stderr tail:
```
```

## git-sha
```
f6605a47d6da44d21f8cfb30d15a531ec2c9c457
```

## git-dirty
```
dirty
```

## contract-sha256
```
2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f  contract/specification.json
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

## Formal model report

# Formal verification report

Status: **PASS**

- TLC: v1.7.4 / 2.19; Java 17
- Contract SHA-256: `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`
- TLC JAR SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` (SHA-256 measured from official HTTPS release download; upstream API digest absent; not publisher-signature verification)
- Reachable dump observations: 16; JSON observations including initial: 16
- Negative control: named TransitionSound violation with validated Authenticated/Logout counterexample
- Raw command, stdout, stderr, exit and dump: `logs/`, `positive-state-dump.txt`, `negative-counterexample.txt`

This checks the finite generated model's reachable safety properties; it makes no liveness or native-program refinement claim.

## Async formal model report

# Async correlation formal verification

Status: **PASS**

- TLC `v1.7.4` / `2.19`; JAR SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Positive exploration: 114 generated, 19 distinct states (captured from TLC output).
- Negative control: `StaleResponseSafety` counterexample validated across 4 states.
- Abstraction: pending is Boolean. CURRENT represents a correctly routed response equal to the active request ID; STALE represents every nonmatching/duplicate/unissued response. IDs, numeric exhaustion refinement, native implementation refinement, concurrency and liveness are not claimed. Request allocation may nondeterministically reject atomically to represent exhaustion.
- Raw TLC stdout/stderr and counterexample: `positive-tlc.json`, `negative-tlc.json`, `negative-counterexample.txt`.
