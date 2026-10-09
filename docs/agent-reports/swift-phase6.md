# Swift Phase 6 report

Updated `ios/Sources/NativeContract/AuthReducer.swift` so authenticated `LoginSucceeded` preserves `.authenticated` and emits exactly `[.clearCredentials]`. Updated the exhaustive all-state/event expectation and added a repeated-login regression that checks both consecutive events and the unchanged authenticated state. The contract digest observed before implementation was `fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11`.

Tests-first evidence: after changing only the tests, `swift test` failed against the v1 reducer at 2026-10-09 13:16:41 local. The all-pairs check and both repeated-login assertions observed `[]` where `[clearCredentials]` was expected. Raw failure lines from that run:

```text
ReducerTests.swift:32: error: ... testAllStateEventPairsHaveExpectedResults : XCTAssertEqual failed: ("[]") is not equal to ("[NativeContract.AuthEffect.clearCredentials]") - authenticated × loginSucceeded
ReducerTests.swift:42: error: ... testRepeatedLoginWhileAuthenticatedClearsCredentialsEachTime : XCTAssertEqual failed: ("[]") is not equal to ("[NativeContract.AuthEffect.clearCredentials]")
ReducerTests.swift:46: error: ... testRepeatedLoginWhileAuthenticatedClearsCredentialsEachTime : XCTAssertEqual failed: ("[]") is not equal to ("[NativeContract.AuthEffect.clearCredentials]")
```

Swift 6.4 commands used redirected compiler caches under `/tmp/native-contract-swift`; the last ten lines below are copied from the retained command logs.

```text
CLANG_MODULE_CACHE_PATH=/tmp/native-contract-swift/clang SWIFTPM_MODULECACHE_OVERRIDE=/tmp/native-contract-swift/modules swift build
Building for debugging...
[2 / 8] NativeContract
[3 / 9] NativeContract
[7 / 11] NativeContract
[11 / 12] TraceRunner-product
Build complete! (1.02秒)
```

```text
CLANG_MODULE_CACHE_PATH=/tmp/native-contract-swift/clang SWIFTPM_MODULECACHE_OVERRIDE=/tmp/native-contract-swift/modules swift test
Test Suite 'TraceRunnerTests' passed at 2026-10-09 13:16:59.857.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.001 (0.002) seconds
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 13:16:59.857.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 13:16:59.857.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
􀟈  Test run started.
􄵄  Testing Library Version: 2084
􄵄  Target Platform: arm64e-apple-macos14.0
􁁛  Test run with 0 tests in 0 suites passed after 0.001 seconds.
```

Repair attempts after the first implementation: one implementation edit, changing the authenticated-login branch effect list; no follow-up corrective edits were needed. The Swift Phase 6 build and test runs completed at 2026-10-09 13:16 local. No contract, schema, verification, or other native sources were changed.
