# Final frozen full gate — r2

Display note: trailing spaces in compiler diagnostic excerpts are trimmed for Markdown; original command logs under reports/evolution are unchanged.

Executed child command:

```sh
bash scripts/verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full
```

Environment: `GRADLE_USER_HOME=/Users/shigeo/work/mobile/native-contract-poc/.gradle-home`.

Protocol classification: PASS. Child exit: 0.

Manifest SHA256: 2719f833120802c3335139c1fd254e04db3814bec116e53e915a5c18ef726481

Candidate SHA256: 635754a4683503f28d4c83112056ae8eb9a2bd85fb78fede5c30cdccd314c157

Raw full-gate report follows, including each executed command and stdout/stderr tails.

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
Ran 107 tests in 7.792s

OK
```

## formal-verify (exit 0)

Command: $ bash scripts/formal-verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/formal-run.RQhNX4

stdout tail:
```
PASS: formal TLC model check; 16 observations; negative control detected TransitionSound
```
stderr tail:
```
```

## async-formal-verify (exit 0)

Command: $ bash scripts/async-formal-verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/async-formal-run.ktZpsd

stdout tail:
```
PASS: async TLC; 19 distinct states; validated StaleResponseSafety and LogoutPolicy counterexamples
```
stderr tail:
```
```

## swift-build (exit 0)

Command: $ swift build --package-path ios

stdout tail:
```
Building for debugging...
[1 / 11]
Build complete! (0.46秒)
```
stderr tail:
```
```

## swift-test (exit 0)

Command: $ swift test --package-path ios

stdout tail:
```
Test Suite 'All tests' passed at 2026-10-12 01:51:52.467.
	 Executed 18 tests, with 0 failures (0 unexpected) in 0.008 (0.011) seconds
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
[Provisioning 1 / 11]
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

BUILD SUCCESSFUL in 508ms
16 actionable tasks: 16 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr tail:
```
```

## contract-generate (exit 0)

Command: $ python3 verification/generate.py --wire-input --output /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/scenarios.json

stdout tail:
```
```
stderr tail:
```
```

## swift-runner (exit 0)

Command: $ bash -c ios/.build/debug/TraceRunner\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/scenarios.json /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/swift-traces.json

stdout tail:
```
```
stderr tail:
```
```

## kotlin-runner (exit 0)

Command: $ bash -c android/library/build/install/library/bin/library\ \<\ \"\$1\"\ \>\ \"\$2\" _ /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/scenarios.json /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/kotlin-traces.json

stdout tail:
```
```
stderr tail:
```
```

## async-runner (exit 0)

Command: $ bash scripts/async-verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/async

stdout tail:
```
PASS: 19624 scenarios, 94864 steps; swift=PASS, kotlin=PASS, differential=PASS
```
stderr tail:
```
```

## differential (exit 0)

Command: $ python3 verification/verify.py --report /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/summary.json --markdown /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/summary.md --swift /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/swift-traces.json --kotlin /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/kotlin-traces.json

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

Command: $ python3 verification/compare.py --left /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/swift-traces.json --right /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/kotlin-traces.json

stdout tail:
```
PASS: 781 scenarios, ordered state/effect traces match
```
stderr tail:
```
```

## mutations (exit 0)

Command: $ python3 scripts/mutations.py verification/mutation-matrix.json --output /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/mutations

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

Command: $ bash scripts/async-mutation-test.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/async-mutations

stdout tail:
```
B-kotlin-resets-counter-on-accepted-logout: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
C-both-accept-stale-response: PASS expected={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'} actual={'swift': 'FAIL', 'kotlin': 'FAIL', 'differential': 'PASS'}
swift-ignores-refreshing-logout: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
swift-omits-logout-clear-credentials: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
swift-retains-logout-pending: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
swift-resets-refreshing-logout-counter: PASS expected={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'} actual={'swift': 'FAIL', 'kotlin': 'PASS', 'differential': 'FAIL'}
kotlin-ignores-refreshing-logout: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
kotlin-omits-logout-clear-credentials: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
kotlin-retains-logout-pending: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
kotlin-resets-refreshing-logout-counter: PASS expected={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'} actual={'swift': 'PASS', 'kotlin': 'FAIL', 'differential': 'FAIL'}
```
stderr tail:
```
```

## managed-verify (exit 0)

Command: $ bash scripts/managed-verify.sh /Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm

stdout tail:
```
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
stderr tail:
```
```

## git-sha
```
8458f66a0691532a7f48e7ca1fb14fc86238b67f
```

## git-dirty
```
dirty
```

## contract-sha256
```
af3d4d840a0f3d37381a8a8fbb2d5d74ed3dfb3ca37d901ef4a9e8920a3bea27  contract/specification.json
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
- Contract SHA-256: `af3d4d840a0f3d37381a8a8fbb2d5d74ed3dfb3ca37d901ef4a9e8920a3bea27`
- TLC JAR SHA-256: `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` (SHA-256 measured from official HTTPS release download; upstream API digest absent; not publisher-signature verification)
- Reachable dump observations: 16; JSON observations including initial: 16
- Negative control: named TransitionSound violation with validated Authenticated/Logout counterexample
- Raw command, stdout, stderr, exit and dump: `logs/`, `positive-state-dump.txt`, `negative-counterexample.txt`

This checks the finite generated model's reachable safety properties; it makes no liveness or native-program refinement claim.

## Async formal model report

# Async correlation formal verification

Status: **PASS**

- TLC `v1.7.4` / `2.19`; JAR SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- Positive exploration: 112 generated, 19 distinct states (captured from TLC output).
- Negative control: `StaleResponseSafety` counterexample validated across 4 states.
- Negative Logout control: `LogoutPolicy` counterexample validated across 4 states.
- Abstraction: pending is Boolean. CURRENT represents a correctly routed response equal to the active request ID; STALE represents every nonmatching/duplicate/unissued response. IDs, numeric exhaustion refinement, native implementation refinement, concurrency and liveness are not claimed. Request allocation may nondeterministically reject atomically to represent exhaustion.
- Raw TLC stdout/stderr and counterexample: `positive-tlc.json`, `negative-tlc.json`, `negative-counterexample.txt`.

## Managed evaluator report

Overall: PASS

- numeric: PASS
- swift-history: PASS
- swift-public-api: PASS
- kotlin-history: PASS
- kotlin-public-api: PASS
- owner-mutations: PASS

Command record: kotlin/public-api/constructor.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.code.gson/gson/2.11.0/527175ca6d81050b53bdd4c457a6d6e017626b0e/gson-2.11.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.errorprone/error_prone_annotations/2.27.0/91b2c29d8a6148b5e2e4930f070d4840e2e48e34/error_prone_annotations-2.27.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.apiguardian/apiguardian-api/1.1.2/a231e0d844d2721b0fa1b238006d15c6ded6842a/apiguardian-api-1.1.2.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains/annotations/13.0/919f0dfe192fb4e063e7dacadee7f8bb9a2672a9/annotations-13.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/abi-tools-api/2.3.20/f4547769617b1d30e516de6a05163696e6091f5b/abi-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/fus-statistics-gradle-plugin/2.3.20/57a6fa102dda18abb93fc87557dc9a3cb1e979a8/fus-statistics-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-statistics/2.3.20/e54080a07c295b9d0edc2f2db311ee9f79ab2f33/kotlin-build-statistics-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-api/2.3.20/9d10b958f69ea67132d24ce9c759cf60465f29a5/kotlin-build-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-compat/2.3.20/649d59d16f0dc2427cc900a8b003496ad39aaa33/kotlin-build-tools-compat-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-cri-impl/2.3.20/52abdf3a26f3f71b94b90b45ad54f6a64610dcba/kotlin-build-tools-cri-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-impl/2.3.20/90a14213a621db275bf64e605e6c849d482656be/kotlin-build-tools-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20/2fac4210c52c27b244305d60b0906e831f49be/kotlin-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-runner/2.3.20/11f74384a212c68bb6eb18ab6cd2cdf6354901b8/kotlin-compiler-runner-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-client/2.3.20/d1f3f5c2efb2ed264dd3dfaf3ae8a581cbf47138/kotlin-daemon-client-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.3.20/92a638246f2a388e2ccf43784623b1c685c93ab8/kotlin-daemon-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.3.20/c486b4eff1485465b13e3ad5b4af747b87357af/kotlin-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-annotations/2.3.20/6608eb0cf5b268bab09eb8880ef15150918cc2d1/kotlin-gradle-plugin-annotations-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-api/2.3.20/ba83906f2886230214d53bc6845a6d8f35c04266/kotlin-gradle-plugin-api-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea/2.3.20/6f1d7150625bece534f9a1cef43a683bcb7b0f68/kotlin-gradle-plugin-idea-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea-proto/2.3.20/41f7b480c617afe84f4183af291f194d161facfb/kotlin-gradle-plugin-idea-proto-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-klib-commonizer-api/2.3.20/aab74e554a68cc9a619126d25bad9697881120ee/kotlin-klib-commonizer-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-native-utils/2.3.20/f554031b932a2b69f35d76608827eed90f1d1e3a/kotlin-native-utils-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-reflect/1.6.10/1cbe9c92c12a94eea200d23c2bbaedaf3daf5132/kotlin-reflect-1.6.10.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-script-runtime/2.3.20/4831ca1fea87f25bf39891ff56327b23b18c9bfa/kotlin-script-runtime-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-common/2.3.20/667e8523d43bdc90ee8d4c0cfda6807171d1fad7/kotlin-scripting-common-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-embeddable/2.3.20/6a701182edec0c66d3c972c4e720c26dbd9f9706/kotlin-scripting-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-impl-embeddable/2.3.20/8052eaa1bf891604b7ca8a3ec804836a8791e1e4/kotlin-scripting-compiler-impl-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-jvm/2.3.20/faacc4f2e7f12f9c18d4946a33428f40cc68db94/kotlin-scripting-jvm-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib/2.3.20/ed866de74ad3d49086a27bbd75952cd186479436/kotlin-stdlib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test/2.3.20/f01df9a21f429ec9f9f7f8cda8eefa92f741ea4a/kotlin-test-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test-junit5/2.3.20/2f6927047ede12c95c3525296b58cb66a88b004b/kotlin-test-junit5-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-tooling-core/2.3.20/7a050c09910ee587944bc2a7413e2d97d751f647/kotlin-tooling-core-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-io/2.3.20/b054b0939d1ecf6288c2e8015b159872f82769f6/kotlin-util-io-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib/2.3.20/8f8fa8f7354ee2e884edbeeccade5196dfe7c1e3/kotlin-util-klib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib-metadata/2.3.20/2494a2d725f31d0a7acdfa30a56f82c1a585c683/kotlin-util-klib-metadata-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0/ac1dc37a30a93150b704022f8d895ee1bd3a36b3/kotlinx-coroutines-core-jvm-1.8.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.8.1/510cb839cce9a3e708052d480a6fbf4a7274dfcd/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.8.1/4de3bace4b175753df5484d2acd74c14bfeb5be9/kotlinx-serialization-json-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-api/5.10.1/eb90c7d8bfaae8fdc97b225733fcb595ddd72843/junit-jupiter-api-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-engine/5.10.1/6c9ff773f9aa842b91d1f2fe4658973252ce2428/junit-jupiter-engine-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-commons/1.10.1/2bfcd4a4e38b10c671b6916d7e543c20afe25579/junit-platform-commons-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-engine/1.10.1/f32ae4af74fde68414b8a3d2b7cf1fb43824a83a/junit-platform-engine-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-launcher/1.10.1/ce85bf5e38bee0989ded9bd468dd4ff78dc0cfa8/junit-platform-launcher-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.opentest4j/opentest4j/1.3.0/152ea56b3a72f655d4fd677fc0ef2596c3dd5e6e/opentest4j-1.3.0.jar",
    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
    "-no-stdlib",
    "-no-reflect",
    "-jvm-target",
    "17",
    "-module-name",
    "managed_external_probe",
    "-classpath",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/kotlin/constructor.kt",
    "-d",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/constructor.jar"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:02.798819+00:00",
  "endUtc": "2026-10-11T16:52:04.251526+00:00",
  "seconds": 1.4527344580000001,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
verification/managed-api/kotlin/constructor.kt:2:19: error: cannot access 'constructor(requestId: Long, owner: Any): RefreshRequest': it is private in 'nativecontract.async.RefreshRequest'.
fun forbidden() { RefreshRequest(1L, Any()) }
                  ^^^^^^^^^^^^^^
```

Command record: kotlin/public-api/mutation.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.code.gson/gson/2.11.0/527175ca6d81050b53bdd4c457a6d6e017626b0e/gson-2.11.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.errorprone/error_prone_annotations/2.27.0/91b2c29d8a6148b5e2e4930f070d4840e2e48e34/error_prone_annotations-2.27.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.apiguardian/apiguardian-api/1.1.2/a231e0d844d2721b0fa1b238006d15c6ded6842a/apiguardian-api-1.1.2.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains/annotations/13.0/919f0dfe192fb4e063e7dacadee7f8bb9a2672a9/annotations-13.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/abi-tools-api/2.3.20/f4547769617b1d30e516de6a05163696e6091f5b/abi-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/fus-statistics-gradle-plugin/2.3.20/57a6fa102dda18abb93fc87557dc9a3cb1e979a8/fus-statistics-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-statistics/2.3.20/e54080a07c295b9d0edc2f2db311ee9f79ab2f33/kotlin-build-statistics-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-api/2.3.20/9d10b958f69ea67132d24ce9c759cf60465f29a5/kotlin-build-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-compat/2.3.20/649d59d16f0dc2427cc900a8b003496ad39aaa33/kotlin-build-tools-compat-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-cri-impl/2.3.20/52abdf3a26f3f71b94b90b45ad54f6a64610dcba/kotlin-build-tools-cri-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-impl/2.3.20/90a14213a621db275bf64e605e6c849d482656be/kotlin-build-tools-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20/2fac4210c52c27b244305d60b0906e831f49be/kotlin-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-runner/2.3.20/11f74384a212c68bb6eb18ab6cd2cdf6354901b8/kotlin-compiler-runner-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-client/2.3.20/d1f3f5c2efb2ed264dd3dfaf3ae8a581cbf47138/kotlin-daemon-client-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.3.20/92a638246f2a388e2ccf43784623b1c685c93ab8/kotlin-daemon-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.3.20/c486b4eff1485465b13e3ad5b4af747b87357af/kotlin-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-annotations/2.3.20/6608eb0cf5b268bab09eb8880ef15150918cc2d1/kotlin-gradle-plugin-annotations-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-api/2.3.20/ba83906f2886230214d53bc6845a6d8f35c04266/kotlin-gradle-plugin-api-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea/2.3.20/6f1d7150625bece534f9a1cef43a683bcb7b0f68/kotlin-gradle-plugin-idea-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea-proto/2.3.20/41f7b480c617afe84f4183af291f194d161facfb/kotlin-gradle-plugin-idea-proto-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-klib-commonizer-api/2.3.20/aab74e554a68cc9a619126d25bad9697881120ee/kotlin-klib-commonizer-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-native-utils/2.3.20/f554031b932a2b69f35d76608827eed90f1d1e3a/kotlin-native-utils-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-reflect/1.6.10/1cbe9c92c12a94eea200d23c2bbaedaf3daf5132/kotlin-reflect-1.6.10.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-script-runtime/2.3.20/4831ca1fea87f25bf39891ff56327b23b18c9bfa/kotlin-script-runtime-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-common/2.3.20/667e8523d43bdc90ee8d4c0cfda6807171d1fad7/kotlin-scripting-common-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-embeddable/2.3.20/6a701182edec0c66d3c972c4e720c26dbd9f9706/kotlin-scripting-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-impl-embeddable/2.3.20/8052eaa1bf891604b7ca8a3ec804836a8791e1e4/kotlin-scripting-compiler-impl-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-jvm/2.3.20/faacc4f2e7f12f9c18d4946a33428f40cc68db94/kotlin-scripting-jvm-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib/2.3.20/ed866de74ad3d49086a27bbd75952cd186479436/kotlin-stdlib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test/2.3.20/f01df9a21f429ec9f9f7f8cda8eefa92f741ea4a/kotlin-test-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test-junit5/2.3.20/2f6927047ede12c95c3525296b58cb66a88b004b/kotlin-test-junit5-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-tooling-core/2.3.20/7a050c09910ee587944bc2a7413e2d97d751f647/kotlin-tooling-core-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-io/2.3.20/b054b0939d1ecf6288c2e8015b159872f82769f6/kotlin-util-io-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib/2.3.20/8f8fa8f7354ee2e884edbeeccade5196dfe7c1e3/kotlin-util-klib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib-metadata/2.3.20/2494a2d725f31d0a7acdfa30a56f82c1a585c683/kotlin-util-klib-metadata-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0/ac1dc37a30a93150b704022f8d895ee1bd3a36b3/kotlinx-coroutines-core-jvm-1.8.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.8.1/510cb839cce9a3e708052d480a6fbf4a7274dfcd/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.8.1/4de3bace4b175753df5484d2acd74c14bfeb5be9/kotlinx-serialization-json-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-api/5.10.1/eb90c7d8bfaae8fdc97b225733fcb595ddd72843/junit-jupiter-api-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-engine/5.10.1/6c9ff773f9aa842b91d1f2fe4658973252ce2428/junit-jupiter-engine-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-commons/1.10.1/2bfcd4a4e38b10c671b6916d7e543c20afe25579/junit-platform-commons-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-engine/1.10.1/f32ae4af74fde68414b8a3d2b7cf1fb43824a83a/junit-platform-engine-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-launcher/1.10.1/ce85bf5e38bee0989ded9bd468dd4ff78dc0cfa8/junit-platform-launcher-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.opentest4j/opentest4j/1.3.0/152ea56b3a72f655d4fd677fc0ef2596c3dd5e6e/opentest4j-1.3.0.jar",
    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
    "-no-stdlib",
    "-no-reflect",
    "-jvm-target",
    "17",
    "-module-name",
    "managed_external_probe",
    "-classpath",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/kotlin/mutation.kt",
    "-d",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/mutation.jar"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:07.198907+00:00",
  "endUtc": "2026-10-11T16:52:08.584814+00:00",
  "seconds": 1.3859304999999988,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
verification/managed-api/kotlin/mutation.kt:2:50: error: 'val' cannot be reassigned.
fun forbidden(request: RefreshRequest) { request.requestId = 2L }
                                                 ^^^^^^^^^
```

Command record: kotlin/public-api/owner.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.code.gson/gson/2.11.0/527175ca6d81050b53bdd4c457a6d6e017626b0e/gson-2.11.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.errorprone/error_prone_annotations/2.27.0/91b2c29d8a6148b5e2e4930f070d4840e2e48e34/error_prone_annotations-2.27.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.apiguardian/apiguardian-api/1.1.2/a231e0d844d2721b0fa1b238006d15c6ded6842a/apiguardian-api-1.1.2.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains/annotations/13.0/919f0dfe192fb4e063e7dacadee7f8bb9a2672a9/annotations-13.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/abi-tools-api/2.3.20/f4547769617b1d30e516de6a05163696e6091f5b/abi-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/fus-statistics-gradle-plugin/2.3.20/57a6fa102dda18abb93fc87557dc9a3cb1e979a8/fus-statistics-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-statistics/2.3.20/e54080a07c295b9d0edc2f2db311ee9f79ab2f33/kotlin-build-statistics-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-api/2.3.20/9d10b958f69ea67132d24ce9c759cf60465f29a5/kotlin-build-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-compat/2.3.20/649d59d16f0dc2427cc900a8b003496ad39aaa33/kotlin-build-tools-compat-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-cri-impl/2.3.20/52abdf3a26f3f71b94b90b45ad54f6a64610dcba/kotlin-build-tools-cri-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-impl/2.3.20/90a14213a621db275bf64e605e6c849d482656be/kotlin-build-tools-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20/2fac4210c52c27b244305d60b0906e831f49be/kotlin-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-runner/2.3.20/11f74384a212c68bb6eb18ab6cd2cdf6354901b8/kotlin-compiler-runner-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-client/2.3.20/d1f3f5c2efb2ed264dd3dfaf3ae8a581cbf47138/kotlin-daemon-client-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.3.20/92a638246f2a388e2ccf43784623b1c685c93ab8/kotlin-daemon-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.3.20/c486b4eff1485465b13e3ad5b4af747b87357af/kotlin-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-annotations/2.3.20/6608eb0cf5b268bab09eb8880ef15150918cc2d1/kotlin-gradle-plugin-annotations-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-api/2.3.20/ba83906f2886230214d53bc6845a6d8f35c04266/kotlin-gradle-plugin-api-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea/2.3.20/6f1d7150625bece534f9a1cef43a683bcb7b0f68/kotlin-gradle-plugin-idea-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea-proto/2.3.20/41f7b480c617afe84f4183af291f194d161facfb/kotlin-gradle-plugin-idea-proto-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-klib-commonizer-api/2.3.20/aab74e554a68cc9a619126d25bad9697881120ee/kotlin-klib-commonizer-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-native-utils/2.3.20/f554031b932a2b69f35d76608827eed90f1d1e3a/kotlin-native-utils-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-reflect/1.6.10/1cbe9c92c12a94eea200d23c2bbaedaf3daf5132/kotlin-reflect-1.6.10.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-script-runtime/2.3.20/4831ca1fea87f25bf39891ff56327b23b18c9bfa/kotlin-script-runtime-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-common/2.3.20/667e8523d43bdc90ee8d4c0cfda6807171d1fad7/kotlin-scripting-common-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-embeddable/2.3.20/6a701182edec0c66d3c972c4e720c26dbd9f9706/kotlin-scripting-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-impl-embeddable/2.3.20/8052eaa1bf891604b7ca8a3ec804836a8791e1e4/kotlin-scripting-compiler-impl-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-jvm/2.3.20/faacc4f2e7f12f9c18d4946a33428f40cc68db94/kotlin-scripting-jvm-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib/2.3.20/ed866de74ad3d49086a27bbd75952cd186479436/kotlin-stdlib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test/2.3.20/f01df9a21f429ec9f9f7f8cda8eefa92f741ea4a/kotlin-test-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test-junit5/2.3.20/2f6927047ede12c95c3525296b58cb66a88b004b/kotlin-test-junit5-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-tooling-core/2.3.20/7a050c09910ee587944bc2a7413e2d97d751f647/kotlin-tooling-core-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-io/2.3.20/b054b0939d1ecf6288c2e8015b159872f82769f6/kotlin-util-io-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib/2.3.20/8f8fa8f7354ee2e884edbeeccade5196dfe7c1e3/kotlin-util-klib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib-metadata/2.3.20/2494a2d725f31d0a7acdfa30a56f82c1a585c683/kotlin-util-klib-metadata-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0/ac1dc37a30a93150b704022f8d895ee1bd3a36b3/kotlinx-coroutines-core-jvm-1.8.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.8.1/510cb839cce9a3e708052d480a6fbf4a7274dfcd/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.8.1/4de3bace4b175753df5484d2acd74c14bfeb5be9/kotlinx-serialization-json-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-api/5.10.1/eb90c7d8bfaae8fdc97b225733fcb595ddd72843/junit-jupiter-api-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-engine/5.10.1/6c9ff773f9aa842b91d1f2fe4658973252ce2428/junit-jupiter-engine-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-commons/1.10.1/2bfcd4a4e38b10c671b6916d7e543c20afe25579/junit-platform-commons-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-engine/1.10.1/f32ae4af74fde68414b8a3d2b7cf1fb43824a83a/junit-platform-engine-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-launcher/1.10.1/ce85bf5e38bee0989ded9bd468dd4ff78dc0cfa8/junit-platform-launcher-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.opentest4j/opentest4j/1.3.0/152ea56b3a72f655d4fd677fc0ef2596c3dd5e6e/opentest4j-1.3.0.jar",
    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
    "-no-stdlib",
    "-no-reflect",
    "-jvm-target",
    "17",
    "-module-name",
    "managed_external_probe",
    "-classpath",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/kotlin/owner.kt",
    "-d",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/owner.jar"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:04.257243+00:00",
  "endUtc": "2026-10-11T16:52:05.713947+00:00",
  "seconds": 1.456718875,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
verification/managed-api/kotlin/owner.kt:2:58: error: cannot access 'val owner: Any': it is private in 'nativecontract.async.RefreshRequest'.
fun forbidden(request: RefreshRequest) { println(request.owner) }
                                                         ^^^^^
```

Command record: kotlin/public-api/positive-compile.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.code.gson/gson/2.11.0/527175ca6d81050b53bdd4c457a6d6e017626b0e/gson-2.11.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.errorprone/error_prone_annotations/2.27.0/91b2c29d8a6148b5e2e4930f070d4840e2e48e34/error_prone_annotations-2.27.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.apiguardian/apiguardian-api/1.1.2/a231e0d844d2721b0fa1b238006d15c6ded6842a/apiguardian-api-1.1.2.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains/annotations/13.0/919f0dfe192fb4e063e7dacadee7f8bb9a2672a9/annotations-13.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/abi-tools-api/2.3.20/f4547769617b1d30e516de6a05163696e6091f5b/abi-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/fus-statistics-gradle-plugin/2.3.20/57a6fa102dda18abb93fc87557dc9a3cb1e979a8/fus-statistics-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-statistics/2.3.20/e54080a07c295b9d0edc2f2db311ee9f79ab2f33/kotlin-build-statistics-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-api/2.3.20/9d10b958f69ea67132d24ce9c759cf60465f29a5/kotlin-build-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-compat/2.3.20/649d59d16f0dc2427cc900a8b003496ad39aaa33/kotlin-build-tools-compat-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-cri-impl/2.3.20/52abdf3a26f3f71b94b90b45ad54f6a64610dcba/kotlin-build-tools-cri-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-impl/2.3.20/90a14213a621db275bf64e605e6c849d482656be/kotlin-build-tools-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20/2fac4210c52c27b244305d60b0906e831f49be/kotlin-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-runner/2.3.20/11f74384a212c68bb6eb18ab6cd2cdf6354901b8/kotlin-compiler-runner-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-client/2.3.20/d1f3f5c2efb2ed264dd3dfaf3ae8a581cbf47138/kotlin-daemon-client-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.3.20/92a638246f2a388e2ccf43784623b1c685c93ab8/kotlin-daemon-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.3.20/c486b4eff1485465b13e3ad5b4af747b87357af/kotlin-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-annotations/2.3.20/6608eb0cf5b268bab09eb8880ef15150918cc2d1/kotlin-gradle-plugin-annotations-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-api/2.3.20/ba83906f2886230214d53bc6845a6d8f35c04266/kotlin-gradle-plugin-api-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea/2.3.20/6f1d7150625bece534f9a1cef43a683bcb7b0f68/kotlin-gradle-plugin-idea-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea-proto/2.3.20/41f7b480c617afe84f4183af291f194d161facfb/kotlin-gradle-plugin-idea-proto-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-klib-commonizer-api/2.3.20/aab74e554a68cc9a619126d25bad9697881120ee/kotlin-klib-commonizer-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-native-utils/2.3.20/f554031b932a2b69f35d76608827eed90f1d1e3a/kotlin-native-utils-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-reflect/1.6.10/1cbe9c92c12a94eea200d23c2bbaedaf3daf5132/kotlin-reflect-1.6.10.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-script-runtime/2.3.20/4831ca1fea87f25bf39891ff56327b23b18c9bfa/kotlin-script-runtime-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-common/2.3.20/667e8523d43bdc90ee8d4c0cfda6807171d1fad7/kotlin-scripting-common-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-embeddable/2.3.20/6a701182edec0c66d3c972c4e720c26dbd9f9706/kotlin-scripting-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-impl-embeddable/2.3.20/8052eaa1bf891604b7ca8a3ec804836a8791e1e4/kotlin-scripting-compiler-impl-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-jvm/2.3.20/faacc4f2e7f12f9c18d4946a33428f40cc68db94/kotlin-scripting-jvm-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib/2.3.20/ed866de74ad3d49086a27bbd75952cd186479436/kotlin-stdlib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test/2.3.20/f01df9a21f429ec9f9f7f8cda8eefa92f741ea4a/kotlin-test-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test-junit5/2.3.20/2f6927047ede12c95c3525296b58cb66a88b004b/kotlin-test-junit5-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-tooling-core/2.3.20/7a050c09910ee587944bc2a7413e2d97d751f647/kotlin-tooling-core-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-io/2.3.20/b054b0939d1ecf6288c2e8015b159872f82769f6/kotlin-util-io-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib/2.3.20/8f8fa8f7354ee2e884edbeeccade5196dfe7c1e3/kotlin-util-klib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib-metadata/2.3.20/2494a2d725f31d0a7acdfa30a56f82c1a585c683/kotlin-util-klib-metadata-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0/ac1dc37a30a93150b704022f8d895ee1bd3a36b3/kotlinx-coroutines-core-jvm-1.8.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.8.1/510cb839cce9a3e708052d480a6fbf4a7274dfcd/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.8.1/4de3bace4b175753df5484d2acd74c14bfeb5be9/kotlinx-serialization-json-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-api/5.10.1/eb90c7d8bfaae8fdc97b225733fcb595ddd72843/junit-jupiter-api-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-engine/5.10.1/6c9ff773f9aa842b91d1f2fe4658973252ce2428/junit-jupiter-engine-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-commons/1.10.1/2bfcd4a4e38b10c671b6916d7e543c20afe25579/junit-platform-commons-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-engine/1.10.1/f32ae4af74fde68414b8a3d2b7cf1fb43824a83a/junit-platform-engine-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-launcher/1.10.1/ce85bf5e38bee0989ded9bd468dd4ff78dc0cfa8/junit-platform-launcher-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.opentest4j/opentest4j/1.3.0/152ea56b3a72f655d4fd677fc0ef2596c3dd5e6e/opentest4j-1.3.0.jar",
    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
    "-no-stdlib",
    "-no-reflect",
    "-jvm-target",
    "17",
    "-module-name",
    "managed_external_probe",
    "-classpath",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/kotlin/positive.kt",
    "-d",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/positive.jar"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:00.545368+00:00",
  "endUtc": "2026-10-11T16:52:02.733952+00:00",
  "seconds": 2.188601208,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```

```

Command record: kotlin/public-api/positive-run.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/positive.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "PositiveKt"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:02.734674+00:00",
  "endUtc": "2026-10-11T16:52:02.798100+00:00",
  "seconds": 0.06345650000000003,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
External API emitted-token reuse and immutable effects: PASS
```
stderr.log tail:
```

```

Command record: kotlin/public-api/session.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.code.gson/gson/2.11.0/527175ca6d81050b53bdd4c457a6d6e017626b0e/gson-2.11.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/com.google.errorprone/error_prone_annotations/2.27.0/91b2c29d8a6148b5e2e4930f070d4840e2e48e34/error_prone_annotations-2.27.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.apiguardian/apiguardian-api/1.1.2/a231e0d844d2721b0fa1b238006d15c6ded6842a/apiguardian-api-1.1.2.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains/annotations/13.0/919f0dfe192fb4e063e7dacadee7f8bb9a2672a9/annotations-13.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/abi-tools-api/2.3.20/f4547769617b1d30e516de6a05163696e6091f5b/abi-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/fus-statistics-gradle-plugin/2.3.20/57a6fa102dda18abb93fc87557dc9a3cb1e979a8/fus-statistics-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-statistics/2.3.20/e54080a07c295b9d0edc2f2db311ee9f79ab2f33/kotlin-build-statistics-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-api/2.3.20/9d10b958f69ea67132d24ce9c759cf60465f29a5/kotlin-build-tools-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-compat/2.3.20/649d59d16f0dc2427cc900a8b003496ad39aaa33/kotlin-build-tools-compat-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-cri-impl/2.3.20/52abdf3a26f3f71b94b90b45ad54f6a64610dcba/kotlin-build-tools-cri-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-build-tools-impl/2.3.20/90a14213a621db275bf64e605e6c849d482656be/kotlin-build-tools-impl-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-embeddable/2.3.20/2fac4210c52c27b244305d60b0906e831f49be/kotlin-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-compiler-runner/2.3.20/11f74384a212c68bb6eb18ab6cd2cdf6354901b8/kotlin-compiler-runner-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-client/2.3.20/d1f3f5c2efb2ed264dd3dfaf3ae8a581cbf47138/kotlin-daemon-client-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-daemon-embeddable/2.3.20/92a638246f2a388e2ccf43784623b1c685c93ab8/kotlin-daemon-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.3.20/c486b4eff1485465b13e3ad5b4af747b87357af/kotlin-gradle-plugin-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-annotations/2.3.20/6608eb0cf5b268bab09eb8880ef15150918cc2d1/kotlin-gradle-plugin-annotations-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-api/2.3.20/ba83906f2886230214d53bc6845a6d8f35c04266/kotlin-gradle-plugin-api-2.3.20-gradle813.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea/2.3.20/6f1d7150625bece534f9a1cef43a683bcb7b0f68/kotlin-gradle-plugin-idea-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin-idea-proto/2.3.20/41f7b480c617afe84f4183af291f194d161facfb/kotlin-gradle-plugin-idea-proto-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-klib-commonizer-api/2.3.20/aab74e554a68cc9a619126d25bad9697881120ee/kotlin-klib-commonizer-api-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-native-utils/2.3.20/f554031b932a2b69f35d76608827eed90f1d1e3a/kotlin-native-utils-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-reflect/1.6.10/1cbe9c92c12a94eea200d23c2bbaedaf3daf5132/kotlin-reflect-1.6.10.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-script-runtime/2.3.20/4831ca1fea87f25bf39891ff56327b23b18c9bfa/kotlin-script-runtime-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-common/2.3.20/667e8523d43bdc90ee8d4c0cfda6807171d1fad7/kotlin-scripting-common-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-embeddable/2.3.20/6a701182edec0c66d3c972c4e720c26dbd9f9706/kotlin-scripting-compiler-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-compiler-impl-embeddable/2.3.20/8052eaa1bf891604b7ca8a3ec804836a8791e1e4/kotlin-scripting-compiler-impl-embeddable-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-scripting-jvm/2.3.20/faacc4f2e7f12f9c18d4946a33428f40cc68db94/kotlin-scripting-jvm-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib/2.3.20/ed866de74ad3d49086a27bbd75952cd186479436/kotlin-stdlib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test/2.3.20/f01df9a21f429ec9f9f7f8cda8eefa92f741ea4a/kotlin-test-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-test-junit5/2.3.20/2f6927047ede12c95c3525296b58cb66a88b004b/kotlin-test-junit5-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-tooling-core/2.3.20/7a050c09910ee587944bc2a7413e2d97d751f647/kotlin-tooling-core-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-io/2.3.20/b054b0939d1ecf6288c2e8015b159872f82769f6/kotlin-util-io-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib/2.3.20/8f8fa8f7354ee2e884edbeeccade5196dfe7c1e3/kotlin-util-klib-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-util-klib-metadata/2.3.20/2494a2d725f31d0a7acdfa30a56f82c1a585c683/kotlin-util-klib-metadata-2.3.20.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm/1.8.0/ac1dc37a30a93150b704022f8d895ee1bd3a36b3/kotlinx-coroutines-core-jvm-1.8.0.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-core-jvm/1.8.1/510cb839cce9a3e708052d480a6fbf4a7274dfcd/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.jetbrains.kotlinx/kotlinx-serialization-json-jvm/1.8.1/4de3bace4b175753df5484d2acd74c14bfeb5be9/kotlinx-serialization-json-jvm-1.8.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-api/5.10.1/eb90c7d8bfaae8fdc97b225733fcb595ddd72843/junit-jupiter-api-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.jupiter/junit-jupiter-engine/5.10.1/6c9ff773f9aa842b91d1f2fe4658973252ce2428/junit-jupiter-engine-5.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-commons/1.10.1/2bfcd4a4e38b10c671b6916d7e543c20afe25579/junit-platform-commons-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-engine/1.10.1/f32ae4af74fde68414b8a3d2b7cf1fb43824a83a/junit-platform-engine-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.junit.platform/junit-platform-launcher/1.10.1/ce85bf5e38bee0989ded9bd468dd4ff78dc0cfa8/junit-platform-launcher-1.10.1.jar:/Users/shigeo/work/mobile/native-contract-poc/.gradle-home/caches/modules-2/files-2.1/org.opentest4j/opentest4j/1.3.0/152ea56b3a72f655d4fd677fc0ef2596c3dd5e6e/opentest4j-1.3.0.jar",
    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
    "-no-stdlib",
    "-no-reflect",
    "-jvm-target",
    "17",
    "-module-name",
    "managed_external_probe",
    "-classpath",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/annotations-13.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/async-library-1.0.0.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlin-stdlib-2.3.20.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-core-jvm-1.8.1.jar:/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/kotlinx-serialization-json-jvm-1.8.1.jar",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/kotlin/session.kt",
    "-d",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/kotlin/public-api/session.jar"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:05.714818+00:00",
  "endUtc": "2026-10-11T16:52:07.197967+00:00",
  "seconds": 1.4831709170000007,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
verification/managed-api/kotlin/session.kt:2:63: error: cannot access 'val session: AsyncSession': it is private in 'nativecontract.async.ManagedAsyncSession'.
fun forbidden(managed: ManagedAsyncSession) { println(managed.session) }
                                                              ^^^^^^^
```

Command record: kotlin/runner.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/android/async-library/build/install/async-library/lib/*",
    "nativecontract.async.ManagedHistoryRunnerKt"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:00.397695+00:00",
  "endUtc": "2026-10-11T16:52:00.526657+00:00",
  "seconds": 0.12898304199999977,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
{"version":1,"histories":[{"scenario":"foreign-same-id","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":1},{"id":"B","nextRequestId":1}],"operations":[{"id":"a-login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":3,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"b-login","owner":"B","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":2,"return":4,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"a-issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":5,"return":7,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"b-issue","owner":"B","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":6,"return":8,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"B","requestId":1}}],"rejection":null}},{"id":"foreign-success","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"b-issue","effectIndex":0},"token":{"owner":"B","requestId":1}},"invoke":9,"return":10,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":"ForeignRequest"}},{"id":"foreign-failure","owner":"A","kind":"handle","phase":3,"after":[],"event":{"event":"RefreshFailed","tokenRef":{"operationId":"b-issue","effectIndex":0},"token":{"owner":"B","requestId":1}},"invoke":11,"return":12,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":"ForeignRequest"}},{"id":"a-snapshot","owner":"A","kind":"snapshot","phase":4,"after":[],"invoke":13,"return":14,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"b-snapshot","owner":"B","kind":"snapshot","phase":4,"after":[],"invoke":15,"return":16,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"own-success","owner":"A","kind":"handle","phase":5,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"a-issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":17,"return":18,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}}]},{"scenario":"logout-vs-success","seed":0,"trial":4,"owners":[{"id":"A","nextRequestId":1}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":4,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"logout","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"Logout"},"invoke":6,"return":10,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[{"effect":"ClearCredentials"}],"rejection":null}},{"id":"response","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":5,"return":8,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"during","owner":"A","kind":"snapshot","phase":2,"after":[],"invoke":7,"return":9,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"final","owner":"A","kind":"snapshot","phase":3,"after":[],"invoke":11,"return":12,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}}]},{"scenario":"logout-vs-failure","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":1}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":4,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"logout","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"Logout"},"invoke":5,"return":7,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[{"effect":"ClearCredentials"}],"rejection":null}},{"id":"response","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshFailed","tokenRef":{"operationId":"issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":6,"return":9,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"during","owner":"A","kind":"snapshot","phase":2,"after":[],"invoke":8,"return":10,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"final","owner":"A","kind":"snapshot","phase":3,"after":[],"invoke":11,"return":12,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}}]},{"scenario":"stale-after-new-request","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":1}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"old-issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":4,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"logout","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"Logout"},"invoke":5,"return":6,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":2},"effects":[{"effect":"ClearCredentials"}],"rejection":null}},{"id":"new-login","owner":"A","kind":"handle","phase":3,"after":[],"event":{"event":"LoginSucceeded"},"invoke":7,"return":8,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"new-issue","owner":"A","kind":"handle","phase":4,"after":[],"event":{"event":"TokenExpired"},"invoke":9,"return":10,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":2,"nextRequestId":3},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":2}}],"rejection":null}},{"id":"old-success","owner":"A","kind":"handle","phase":5,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"old-issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":11,"return":12,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":2,"nextRequestId":3},"effects":[],"rejection":null}},{"id":"old-failure","owner":"A","kind":"handle","phase":6,"after":[],"event":{"event":"RefreshFailed","tokenRef":{"operationId":"old-issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":13,"return":14,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":2,"nextRequestId":3},"effects":[],"rejection":null}},{"id":"before-fresh","owner":"A","kind":"snapshot","phase":7,"after":[],"invoke":15,"return":16,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":2,"nextRequestId":3},"effects":[],"rejection":null}},{"id":"fresh","owner":"A","kind":"handle","phase":8,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"new-issue","effectIndex":0},"token":{"owner":"A","requestId":2}},"invoke":17,"return":18,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":3},"effects":[],"rejection":null}},{"id":"after-fresh","owner":"A","kind":"snapshot","phase":9,"after":[],"invoke":19,"return":20,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":3},"effects":[],"rejection":null}}]},{"scenario":"simultaneous-expiration","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":1}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"expire-one","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":5,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"expire-two","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":4,"return":8,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"during","owner":"A","kind":"snapshot","phase":1,"after":[],"invoke":6,"return":7,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"final","owner":"A","kind":"snapshot","phase":2,"after":[],"invoke":9,"return":10,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}}]},{"scenario":"max-logout-exhaustion","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":9223372036854775807}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":9223372036854775807},"effects":[],"rejection":null}},{"id":"last-issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":4,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":9223372036854775807,"nextRequestId":null},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775807}}],"rejection":null}},{"id":"logout","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"Logout"},"invoke":5,"return":6,"result":{"snapshot":{"state":"Unauthenticated","pendingRequestId":null,"nextRequestId":null},"effects":[{"effect":"ClearCredentials"}],"rejection":null}},{"id":"new-login","owner":"A","kind":"handle","phase":3,"after":[],"event":{"event":"LoginSucceeded"},"invoke":7,"return":8,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}},{"id":"exhausted","owner":"A","kind":"handle","phase":4,"after":[],"event":{"event":"TokenExpired"},"invoke":9,"return":10,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":"RequestIdExhausted"}},{"id":"old-success","owner":"A","kind":"handle","phase":5,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"last-issue","effectIndex":0},"token":{"owner":"A","requestId":9223372036854775807}},"invoke":11,"return":12,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}},{"id":"old-failure","owner":"A","kind":"handle","phase":6,"after":[],"event":{"event":"RefreshFailed","tokenRef":{"operationId":"last-issue","effectIndex":0},"token":{"owner":"A","requestId":9223372036854775807}},"invoke":13,"return":14,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}},{"id":"final","owner":"A","kind":"snapshot","phase":7,"after":[],"invoke":15,"return":16,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}}]},{"scenario":"last-two-ids","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":9223372036854775806}],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":2,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":9223372036854775806},"effects":[],"rejection":null}},{"id":"penultimate","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":3,"return":4,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":9223372036854775806,"nextRequestId":9223372036854775807},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775806}}],"rejection":null}},{"id":"complete-one","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"penultimate","effectIndex":0},"token":{"owner":"A","requestId":9223372036854775806}},"invoke":5,"return":6,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":9223372036854775807},"effects":[],"rejection":null}},{"id":"last","owner":"A","kind":"handle","phase":3,"after":[],"event":{"event":"TokenExpired"},"invoke":7,"return":8,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":9223372036854775807,"nextRequestId":null},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775807}}],"rejection":null}},{"id":"complete-two","owner":"A","kind":"handle","phase":4,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"last","effectIndex":0},"token":{"owner":"A","requestId":9223372036854775807}},"invoke":9,"return":10,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}},{"id":"exhausted","owner":"A","kind":"handle","phase":5,"after":[],"event":{"event":"TokenExpired"},"invoke":11,"return":12,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":"RequestIdExhausted"}},{"id":"final","owner":"A","kind":"snapshot","phase":6,"after":[],"invoke":13,"return":14,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":null},"effects":[],"rejection":null}}]}]}
```
stderr.log tail:
```

```

Command record: numeric.command.json
```json
{
  "argv": [
    "python3",
    "-m",
    "verification.numeric_model",
    "--output",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/numeric"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:57.801438+00:00",
  "endUtc": "2026-10-11T16:51:57.856642+00:00",
  "seconds": 0.05501374999999999,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
          "issuedAfter": [],
          "effects": [],
          "rejection": null
        }
      ],
      "states": 9,
      "edges": 35
    }
  }
}
```
stderr.log tail:
```

```

Command record: owner-mutations/kotlin-owner-guard/build.command.json
```json
{
  "argv": [
    "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-6dgklr_z/android/gradlew",
    "-p",
    "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-6dgklr_z/android",
    "--no-daemon",
    ":async-library:installDist"
  ],
  "cwd": "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-6dgklr_z",
  "startUtc": "2026-10-11T16:52:15.768840+00:00",
  "endUtc": "2026-10-11T16:52:21.950120+00:00",
  "seconds": 6.181275708000001,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
> Task :async-library:compileKotlin
> Task :async-library:compileJava NO-SOURCE
> Task :async-library:classes UP-TO-DATE
> Task :async-library:jar
> Task :async-library:startScripts
> Task :async-library:installDist

BUILD SUCCESSFUL in 5s
4 actionable tasks: 4 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```
stderr.log tail:
```

```

Command record: owner-mutations/kotlin-owner-guard/runner.command.json
```json
{
  "argv": [
    "java",
    "-cp",
    "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-6dgklr_z/android/async-library/build/install/async-library/lib/*",
    "nativecontract.async.ManagedHistoryRunnerKt"
  ],
  "cwd": "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-6dgklr_z",
  "startUtc": "2026-10-11T16:52:21.956063+00:00",
  "endUtc": "2026-10-11T16:52:22.079530+00:00",
  "seconds": 0.12348737499999984,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
{"version":1,"histories":[{"scenario":"foreign-same-id","seed":0,"trial":0,"owners":[{"id":"A","nextRequestId":1},{"id":"B","nextRequestId":1}],"operations":[{"id":"a-login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":2,"return":3,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"b-login","owner":"B","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"},"invoke":1,"return":4,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":1},"effects":[],"rejection":null}},{"id":"a-issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":5,"return":7,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null}},{"id":"b-issue","owner":"B","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"},"invoke":6,"return":8,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"B","requestId":1}}],"rejection":null}},{"id":"foreign-success","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"b-issue","effectIndex":0},"token":{"owner":"B","requestId":1}},"invoke":9,"return":10,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"foreign-failure","owner":"A","kind":"handle","phase":3,"after":[],"event":{"event":"RefreshFailed","tokenRef":{"operationId":"b-issue","effectIndex":0},"token":{"owner":"B","requestId":1}},"invoke":11,"return":12,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"a-snapshot","owner":"A","kind":"snapshot","phase":4,"after":[],"invoke":13,"return":14,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"b-snapshot","owner":"B","kind":"snapshot","phase":4,"after":[],"invoke":15,"return":16,"result":{"snapshot":{"state":"Refreshing","pendingRequestId":1,"nextRequestId":2},"effects":[],"rejection":null}},{"id":"own-success","owner":"A","kind":"handle","phase":5,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"a-issue","effectIndex":0},"token":{"owner":"A","requestId":1}},"invoke":17,"return":18,"result":{"snapshot":{"state":"Authenticated","pendingRequestId":null,"nextRequestId":2},"effects":[],"rejection":null}}]}]}
```
stderr.log tail:
```

```

Command record: owner-mutations/swift-owner-guard/build.command.json
```json
{
  "argv": [
    "swift",
    "build",
    "--package-path",
    "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-hw88bq5c/ios",
    "--product",
    "ManagedHistoryRunner"
  ],
  "cwd": "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-hw88bq5c",
  "startUtc": "2026-10-11T16:52:08.593117+00:00",
  "endUtc": "2026-10-11T16:52:15.349108+00:00",
  "seconds": 6.755989000000001,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
[63 / 90]
[64 / 90]
[74 / 91] AsyncNativeContract
[78 / 95] AsyncNativeContract
[87 / 96] ManagedHistoryRunner-product
[90 / 99] ManagedHistoryRunner-product
[91 / 99] ManagedHistoryRunner-product
[95 / 99] ManagedHistoryRunner-product
[97 / 99] ManagedHistoryRunner-product
Build complete! (5.63秒)
```
stderr.log tail:
```

```

Command record: owner-mutations/swift-owner-guard/runner.command.json
```json
{
  "argv": [
    "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-hw88bq5c/ios/.build/debug/ManagedHistoryRunner"
  ],
  "cwd": "/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/managed-mutant-hw88bq5c",
  "startUtc": "2026-10-11T16:52:15.349852+00:00",
  "endUtc": "2026-10-11T16:52:15.562473+00:00",
  "seconds": 0.21265049999999874,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
{"histories":[{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"b-login","invoke":1,"kind":"handle","owner":"B","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":3},{"after":[],"event":{"event":"LoginSucceeded"},"id":"a-login","invoke":2,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":4},{"after":[],"event":{"event":"TokenExpired"},"id":"b-issue","invoke":5,"kind":"handle","owner":"B","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"B","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":7},{"after":[],"event":{"event":"TokenExpired"},"id":"a-issue","invoke":6,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":8},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"B","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"b-issue"}},"id":"foreign-success","invoke":9,"kind":"handle","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":10},{"after":[],"event":{"event":"RefreshFailed","token":{"owner":"B","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"b-issue"}},"id":"foreign-failure","invoke":11,"kind":"handle","owner":"A","phase":3,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":12},{"after":[],"id":"b-snapshot","invoke":13,"kind":"snapshot","owner":"B","phase":4,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":14},{"after":[],"id":"a-snapshot","invoke":15,"kind":"snapshot","owner":"A","phase":4,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":16},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"a-issue"}},"id":"own-success","invoke":17,"kind":"handle","owner":"A","phase":5,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":18}],"owners":[{"id":"A","nextRequestId":1},{"id":"B","nextRequestId":1}],"scenario":"foreign-same-id","seed":0,"trial":0}],"version":1}
```
stderr.log tail:
```

```

Command record: swift/public-api/constructor.command.json
```json
{
  "argv": [
    "swiftc",
    "-swift-version",
    "6",
    "-typecheck",
    "-module-name",
    "ExternalManagedProbe",
    "-I",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/constructor.swift"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:59.727388+00:00",
  "endUtc": "2026-10-11T16:51:59.893556+00:00",
  "seconds": 0.16619033299999986,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
1 | import AsyncNativeContract
2 | func forbidden() { _ = RefreshRequest(requestId: 1) }
  |                                                   `- error: missing argument for parameter 'owner' in call
3 |

AsyncNativeContract.RefreshRequest.init:2:13: note: 'init(requestId:owner:)' declared here
1 | class RefreshRequest {
2 | fileprivate init(requestId: Int64, owner: AsyncNativeContract.RequestOwner)}
  |             `- note: 'init(requestId:owner:)' declared here
3 |
```

Command record: swift/public-api/mutation.command.json
```json
{
  "argv": [
    "swiftc",
    "-swift-version",
    "6",
    "-typecheck",
    "-module-name",
    "ExternalManagedProbe",
    "-I",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/mutation.swift"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:00.226035+00:00",
  "endUtc": "2026-10-11T16:52:00.391124+00:00",
  "seconds": 0.16510941700000004,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/mutation.swift:2:53: error: cannot assign to property: 'requestId' is a 'let' constant
1 | import AsyncNativeContract
2 | func forbidden(_ request: RefreshRequest) { request.requestId = 2 }
  |                                                     `- error: cannot assign to property: 'requestId' is a 'let' constant
3 |
```

Command record: swift/public-api/owner.command.json
```json
{
  "argv": [
    "swiftc",
    "-swift-version",
    "6",
    "-typecheck",
    "-module-name",
    "ExternalManagedProbe",
    "-I",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/owner.swift"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:59.894329+00:00",
  "endUtc": "2026-10-11T16:52:00.061095+00:00",
  "seconds": 0.16678608399999995,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
1 | import AsyncNativeContract
2 | func forbidden(_ request: RefreshRequest) { _ = request.owner }
  |                                                         `- error: 'owner' is inaccessible due to 'private' protection level
3 |

AsyncNativeContract.RefreshRequest.owner:2:13: note: 'owner' declared here
1 | class RefreshRequest {
2 | private let owner: AsyncNativeContract.RequestOwner}
  |             `- note: 'owner' declared here
3 |
```

Command record: swift/public-api/positive-compile.command.json
```json
{
  "argv": [
    "swiftc",
    "-swift-version",
    "6",
    "-parse-as-library",
    "-module-name",
    "ExternalManagedProbe",
    "-I",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/positive.swift",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug/NativeContract.o",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug/AsyncNativeContract.o",
    "-o",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/swift/public-api/positive"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:57.873198+00:00",
  "endUtc": "2026-10-11T16:51:59.687510+00:00",
  "seconds": 1.814324834,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```

```

Command record: swift/public-api/positive-run.command.json
```json
{
  "argv": [
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/reports/evolution/protocol-r2/candidate-full-01/full/managed-run.eMEytm/swift/public-api/positive"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:59.688079+00:00",
  "endUtc": "2026-10-11T16:51:59.726778+00:00",
  "seconds": 0.038719167,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
External API emitted-token reuse: PASS
```
stderr.log tail:
```

```

Command record: swift/public-api/session.command.json
```json
{
  "argv": [
    "swiftc",
    "-swift-version",
    "6",
    "-typecheck",
    "-module-name",
    "ExternalManagedProbe",
    "-I",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug",
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/managed-api/swift/session.swift"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:52:00.062038+00:00",
  "endUtc": "2026-10-11T16:52:00.225037+00:00",
  "seconds": 0.16301979099999997,
  "exitCode": 1,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```

```
stderr.log tail:
```
1 | import AsyncNativeContract
2 | func forbidden(_ managed: ManagedAsyncSession) { _ = managed.session }
  |                                                              `- error: 'session' is inaccessible due to 'private' protection level
3 |

AsyncNativeContract.ManagedAsyncSession.session:2:13: note: 'session' declared here
1 | actor ManagedAsyncSession {
2 | private var session: AsyncNativeContract.AsyncSession}
  |             `- note: 'session' declared here
3 |
```

Command record: swift/runner.command.json
```json
{
  "argv": [
    "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/ios/.build/debug/ManagedHistoryRunner"
  ],
  "cwd": "/Users/shigeo/.codex/worktrees/b195/native-contract-poc",
  "startUtc": "2026-10-11T16:51:57.857715+00:00",
  "endUtc": "2026-10-11T16:51:57.869288+00:00",
  "seconds": 0.011584332999999988,
  "exitCode": 0,
  "timedOut": false,
  "error": null
}
```
stdout.log tail:
```
{"histories":[{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"b-login","invoke":1,"kind":"handle","owner":"B","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":3},{"after":[],"event":{"event":"LoginSucceeded"},"id":"a-login","invoke":2,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":4},{"after":[],"event":{"event":"TokenExpired"},"id":"b-issue","invoke":5,"kind":"handle","owner":"B","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"B","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":7},{"after":[],"event":{"event":"TokenExpired"},"id":"a-issue","invoke":6,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":8},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"B","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"b-issue"}},"id":"foreign-success","invoke":9,"kind":"handle","owner":"A","phase":2,"result":{"effects":[],"rejection":"ForeignRequest","snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":10},{"after":[],"event":{"event":"RefreshFailed","token":{"owner":"B","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"b-issue"}},"id":"foreign-failure","invoke":11,"kind":"handle","owner":"A","phase":3,"result":{"effects":[],"rejection":"ForeignRequest","snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":12},{"after":[],"id":"b-snapshot","invoke":13,"kind":"snapshot","owner":"B","phase":4,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":14},{"after":[],"id":"a-snapshot","invoke":15,"kind":"snapshot","owner":"A","phase":4,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":16},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"a-issue"}},"id":"own-success","invoke":17,"kind":"handle","owner":"A","phase":5,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":18}],"owners":[{"id":"A","nextRequestId":1},{"id":"B","nextRequestId":1}],"scenario":"foreign-same-id","seed":0,"trial":0},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"event":{"event":"TokenExpired"},"id":"issue","invoke":3,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":4},{"after":[],"id":"during","invoke":5,"kind":"snapshot","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":6},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"issue"}},"id":"response","invoke":8,"kind":"handle","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":9},{"after":[],"event":{"event":"Logout"},"id":"logout","invoke":7,"kind":"handle","owner":"A","phase":2,"result":{"effects":[{"effect":"ClearCredentials"}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":10},{"after":[],"id":"final","invoke":11,"kind":"snapshot","owner":"A","phase":3,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":12}],"owners":[{"id":"A","nextRequestId":1}],"scenario":"logout-vs-success","seed":0,"trial":5},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"event":{"event":"TokenExpired"},"id":"issue","invoke":3,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":4},{"after":[],"event":{"event":"Logout"},"id":"logout","invoke":5,"kind":"handle","owner":"A","phase":2,"result":{"effects":[{"effect":"ClearCredentials"}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":8},{"after":[],"event":{"event":"RefreshFailed","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"issue"}},"id":"response","invoke":6,"kind":"handle","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":9},{"after":[],"id":"during","invoke":7,"kind":"snapshot","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":10},{"after":[],"id":"final","invoke":11,"kind":"snapshot","owner":"A","phase":3,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":12}],"owners":[{"id":"A","nextRequestId":1}],"scenario":"logout-vs-failure","seed":0,"trial":0},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"event":{"event":"TokenExpired"},"id":"old-issue","invoke":3,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":4},{"after":[],"event":{"event":"Logout"},"id":"logout","invoke":5,"kind":"handle","owner":"A","phase":2,"result":{"effects":[{"effect":"ClearCredentials"}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Unauthenticated"}},"return":6},{"after":[],"event":{"event":"LoginSucceeded"},"id":"new-login","invoke":7,"kind":"handle","owner":"A","phase":3,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":null,"state":"Authenticated"}},"return":8},{"after":[],"event":{"event":"TokenExpired"},"id":"new-issue","invoke":9,"kind":"handle","owner":"A","phase":4,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":2}}],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":2,"state":"Refreshing"}},"return":10},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"old-issue"}},"id":"old-success","invoke":11,"kind":"handle","owner":"A","phase":5,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":2,"state":"Refreshing"}},"return":12},{"after":[],"event":{"event":"RefreshFailed","token":{"owner":"A","requestId":1},"tokenRef":{"effectIndex":0,"operationId":"old-issue"}},"id":"old-failure","invoke":13,"kind":"handle","owner":"A","phase":6,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":2,"state":"Refreshing"}},"return":14},{"after":[],"id":"before-fresh","invoke":15,"kind":"snapshot","owner":"A","phase":7,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":2,"state":"Refreshing"}},"return":16},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":2},"tokenRef":{"effectIndex":0,"operationId":"new-issue"}},"id":"fresh","invoke":17,"kind":"handle","owner":"A","phase":8,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":null,"state":"Authenticated"}},"return":18},{"after":[],"id":"after-fresh","invoke":19,"kind":"snapshot","owner":"A","phase":9,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":3,"pendingRequestId":null,"state":"Authenticated"}},"return":20}],"owners":[{"id":"A","nextRequestId":1}],"scenario":"stale-after-new-request","seed":0,"trial":0},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"id":"during","invoke":3,"kind":"snapshot","owner":"A","phase":1,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":1,"pendingRequestId":null,"state":"Authenticated"}},"return":4},{"after":[],"event":{"event":"TokenExpired"},"id":"expire-two","invoke":5,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":1}}],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":7},{"after":[],"event":{"event":"TokenExpired"},"id":"expire-one","invoke":6,"kind":"handle","owner":"A","phase":1,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":8},{"after":[],"id":"final","invoke":9,"kind":"snapshot","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":2,"pendingRequestId":1,"state":"Refreshing"}},"return":10}],"owners":[{"id":"A","nextRequestId":1}],"scenario":"simultaneous-expiration","seed":0,"trial":2},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":9223372036854775807,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"event":{"event":"TokenExpired"},"id":"last-issue","invoke":3,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775807}}],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":9223372036854775807,"state":"Refreshing"}},"return":4},{"after":[],"event":{"event":"Logout"},"id":"logout","invoke":5,"kind":"handle","owner":"A","phase":2,"result":{"effects":[{"effect":"ClearCredentials"}],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Unauthenticated"}},"return":6},{"after":[],"event":{"event":"LoginSucceeded"},"id":"new-login","invoke":7,"kind":"handle","owner":"A","phase":3,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":8},{"after":[],"event":{"event":"TokenExpired"},"id":"exhausted","invoke":9,"kind":"handle","owner":"A","phase":4,"result":{"effects":[],"rejection":"RequestIdExhausted","snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":10},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":9223372036854775807},"tokenRef":{"effectIndex":0,"operationId":"last-issue"}},"id":"old-success","invoke":11,"kind":"handle","owner":"A","phase":5,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":12},{"after":[],"event":{"event":"RefreshFailed","token":{"owner":"A","requestId":9223372036854775807},"tokenRef":{"effectIndex":0,"operationId":"last-issue"}},"id":"old-failure","invoke":13,"kind":"handle","owner":"A","phase":6,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":14},{"after":[],"id":"final","invoke":15,"kind":"snapshot","owner":"A","phase":7,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":16}],"owners":[{"id":"A","nextRequestId":9223372036854775807}],"scenario":"max-logout-exhaustion","seed":0,"trial":0},{"operations":[{"after":[],"event":{"event":"LoginSucceeded"},"id":"login","invoke":1,"kind":"handle","owner":"A","phase":0,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":9223372036854775806,"pendingRequestId":null,"state":"Authenticated"}},"return":2},{"after":[],"event":{"event":"TokenExpired"},"id":"penultimate","invoke":3,"kind":"handle","owner":"A","phase":1,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775806}}],"rejection":null,"snapshot":{"nextRequestId":9223372036854775807,"pendingRequestId":9223372036854775806,"state":"Refreshing"}},"return":4},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":9223372036854775806},"tokenRef":{"effectIndex":0,"operationId":"penultimate"}},"id":"complete-one","invoke":5,"kind":"handle","owner":"A","phase":2,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":9223372036854775807,"pendingRequestId":null,"state":"Authenticated"}},"return":6},{"after":[],"event":{"event":"TokenExpired"},"id":"last","invoke":7,"kind":"handle","owner":"A","phase":3,"result":{"effects":[{"effect":"RequestTokenRefresh","token":{"owner":"A","requestId":9223372036854775807}}],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":9223372036854775807,"state":"Refreshing"}},"return":8},{"after":[],"event":{"event":"RefreshSucceeded","token":{"owner":"A","requestId":9223372036854775807},"tokenRef":{"effectIndex":0,"operationId":"last"}},"id":"complete-two","invoke":9,"kind":"handle","owner":"A","phase":4,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":10},{"after":[],"event":{"event":"TokenExpired"},"id":"exhausted","invoke":11,"kind":"handle","owner":"A","phase":5,"result":{"effects":[],"rejection":"RequestIdExhausted","snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":12},{"after":[],"id":"final","invoke":13,"kind":"snapshot","owner":"A","phase":6,"result":{"effects":[],"rejection":null,"snapshot":{"nextRequestId":null,"pendingRequestId":null,"state":"Authenticated"}},"return":14}],"owners":[{"id":"A","nextRequestId":9223372036854775806}],"scenario":"last-two-ids","seed":0,"trial":0}],"version":1}
```
stderr.log tail:
```

```
