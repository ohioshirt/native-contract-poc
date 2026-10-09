# Swift implementation report

Implemented the SwiftPM package in `ios/` with an independent, exhaustive typed reducer, JSON trace processor, and `TraceRunner` executable. The library exposes `AuthState`, `AuthEvent`, `AuthEffect`, `TransitionResult`, and `AuthReducer`; each scenario receives a fresh reducer. The runner validates the complete input document before encoding one output object, rejects extra keys, malformed input, unknown events and duplicate scenario IDs, and emits diagnostics to stderr with a nonzero exit and no partial stdout.

Tests were written before the implementation. The first compiler-blocked attempt failed because the sandbox denied the Swift module-cache write. After redirecting cache paths and obtaining the required compiler execution, the valid-package red run failed as expected because `AuthReducer`, `AuthState`, `AuthEvent`, and `AuthEffect` were missing from the test target. The test-first failure included `ReducerTests.swift:6:24: error: cannot find 'AuthReducer' in scope` and ended with `error: Build failed`.

Commands and raw final output (Swift 6.4, arm64 macOS; module caches redirected to `/tmp/native-contract-swift`):

```text
CLANG_MODULE_CACHE_PATH=/tmp/native-contract-swift/clang SWIFTPM_MODULECACHE_OVERRIDE=/tmp/native-contract-swift/modules swift build
Building for debugging...
Build complete! (0.27秒)
```

```text
CLANG_MODULE_CACHE_PATH=/tmp/native-contract-swift/clang SWIFTPM_MODULECACHE_OVERRIDE=/tmp/native-contract-swift/modules swift test
Test Suite 'TraceRunnerTests' passed at 2026-10-09 13:01:25.567.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.001 (0.002) seconds
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 13:01:25.568.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 13:01:25.568.
	 Executed 6 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
􀟈  Test run started.
􄵄  Testing Library Version: 2084
􀟈  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```

Executable smoke check:

```text
printf '%s' '{"scenarios":[{"scenario":"empty","events":[]},{"scenario":"one","events":["LoginSucceeded","TokenExpired"]}]}' | .build/debug/TraceRunner
{"traces":[{"scenario":"empty","steps":[]},{"scenario":"one","steps":[{"effects":[],"event":"LoginSucceeded","state":"Authenticated"},{"effects":["RequestTokenRefresh"],"event":"TokenExpired","state":"Refreshing"}]}]}
```

Invalid-event check used a valid first scenario followed by `Bogus`:

```text
exit=1 stdout-bytes=       0
TraceRunner: unknown event: Bogus
```

Mutation patch sites in `ios/Sources/NativeContract/AuthReducer.swift`:

- A, TokenExpired next state: in the `.authenticated, .tokenExpired` branch (lines 53–54), replace `result = TransitionResult(state: .refreshing, effects: [.requestTokenRefresh])` with `result = TransitionResult(state: .unauthenticated, effects: [.requestTokenRefresh])`.
- C, Logout removes ClearCredentials: in the `.authenticated, .logout` branch (lines 51–52), replace `result = TransitionResult(state: .unauthenticated, effects: [.clearCredentials])` with `result = TransitionResult(state: .unauthenticated, effects: [])`.

Implementation files: `ios/Package.swift`, `ios/Sources/NativeContract/AuthReducer.swift`, `ios/Sources/NativeContract/TraceDocumentProcessor.swift`, `ios/Sources/TraceRunner/main.swift`, and `ios/Tests/NativeContractTests/{ReducerTests,TraceRunnerTests}.swift`. No contract changes were made.
