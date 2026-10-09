# Swift async-correlation implementation

Implemented the independent typed Swift adapter and `AsyncTraceRunner` under `ios/Sources/AsyncNativeContract` and `ios/Sources/AsyncTraceRunner`. The adapter uses the existing Swift `AuthReducer`, allocates monotonically increasing positive `Int64` request IDs, never resets its counter, matches response IDs against the active pending ID, preserves the existing ignored `Refreshing × Logout` behavior, and returns atomic `RequestIdExhausted` rejections. Same-session calls require caller serialization.

The runner accepts the v3 async wire shape, emits full event/state/pending/effect/rejection steps, and rejects malformed shapes, duplicate object keys/scenario IDs, unknown events, invalid ID tokens, and IDs outside positive signed64. ID token validation operates on the original JSON bytes because Foundation's decoder accepts integral decimals/exponents for `Int64`. It assembles output only after the entire input validates, so failures do not write partial stdout. `ios/Package.swift` exposes both new library and executable targets; existing targets and their sources are unchanged.

The unique stale-response mutation site is [AsyncSession.swift](/Users/shigeo/work/mobile/native-contract-poc/ios/Sources/AsyncNativeContract/AsyncSession.swift:50), the guard `guard state == .refreshing, pendingRequestId == requestId else`. Removing this guard makes stale and duplicate response events reach the core reducer.

Canonical contract SHA-256 remained `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`.

Validation:

Command: `swift test --package-path ios --scratch-path ios/.swift-cache` (SwiftPM needed the authorized toolchain cache access). Summary command: `rg 'Test Suite .*passed|Executed [0-9]+ tests|Test Suite .*failed' ios/.swift-cache/swift-test.log | tail -10`.

Raw summary output:

```text
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 14:17:04.936.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 14:17:04.936.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
Test Suite 'AsyncNativeContractTests' passed at 2026-10-09 14:17:05.051.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'AsyncNativeContractTests.xctest' passed at 2026-10-09 14:17:05.051.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 14:17:05.051.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
```

Valid runner smoke command: `printf '%s' '<freshness JSON>' | ios/.swift-cache/debug/AsyncTraceRunner`. Raw final output:

```text
{"traces":[{"scenario":"freshness","steps":[{"effects":[],"event":{"event":"LoginSucceeded"},"pendingRequestId":null,"rejection":null,"state":"Authenticated"},{"effects":[{"effect":"RequestTokenRefresh","requestId":1}],"event":{"event":"TokenExpired"},"pendingRequestId":1,"rejection":null,"state":"Refreshing"},{"effects":[],"event":{"event":"RefreshSucceeded","requestId":1},"pendingRequestId":null,"rejection":null,"state":"Authenticated"},{"effects":[],"event":{"event":"RefreshSucceeded","requestId":1},"pendingRequestId":null,"rejection":null,"state":"Authenticated"}]}]}
```

Malformed runner smoke used `requestId:1e0`; raw result: exit code `1`, stdout `0` bytes, stderr `AsyncTraceRunner: invalid input shape: requestId must be a positive signed64 integer token`.

## Native review follow-up (Swift)

Expanded the public API documentation at `AsyncSession.swift` to define one authoritative mutable value per logical session, require serialized calls to that value, explain that copied/restored snapshots form independent histories, and state that IDs are only scoped to that history and cannot authenticate or route responses alone. `AsyncAuthEvent` now states that response IDs must be positive signed64 IDs issued by the same logical session; nonpositive native arguments are outside the valid event domain and are ignored by the current mismatch guard. No valid-input behavior changed.

The Unicode probe confirmed Swift `String` canonical equality collapsed composed U+00E9 and decomposed U+0065 U+0301 scenario IDs, while the wire strings are distinct scalar sequences. The async runner now uses each decoded scenario ID's exact UTF-8 bytes for duplicate detection. A regression test sends `\\u00e9` and `e\\u0301` in one document and expects two traces; no normalization or ASCII restriction is applied. Legacy runner code is untouched.

Focused TDD probe before the production change:

Command: `swift test --package-path ios --scratch-path ios/.swift-cache --filter AsyncNativeContractTests.testScenarioIdsUseExactUnicodeScalarIdentity`

Raw failure output:

```text
Test Case '-[AsyncNativeContractTests.AsyncNativeContractTests testScenarioIdsUseExactUnicodeScalarIdentity]' started.
... failed: caught error: "duplicate scenario ID: é"
Test Case '-[AsyncNativeContractTests.AsyncNativeContractTests testScenarioIdsUseExactUnicodeScalarIdentity]' failed (0.059 seconds).
	 Executed 1 test, with 1 failure (1 unexpected) in 0.059 (0.060) seconds
Test Suite 'AsyncNativeContractTests' failed at 2026-10-09 14:21:37.164.
Test Suite 'AsyncNativeContractTests.xctest' failed at 2026-10-09 14:21:37.164.
Test Suite 'Selected tests' failed at 2026-10-09 14:21:37.164.
```

After the fix, the focused command passed:

```text
Test Case '-[AsyncNativeContractTests.AsyncNativeContractTests testScenarioIdsUseExactUnicodeScalarIdentity]' passed (0.001 seconds)
Test Suite 'AsyncNativeContractTests' passed at 2026-10-09 14:21:52.117.
	 Executed 1 test, with 0 failures (0 unexpected) in 0.001 (0.001) seconds
Test Suite 'Selected tests' passed at 2026-10-09 14:21:52.117.
	 Executed 1 test, with 0 failures (0 unexpected) in 0.001 (0.003) seconds
```

Final full-suite command: `swift test --package-path ios --scratch-path ios/.swift-cache`. Summary command: `rg 'Test Suite .*passed|Executed [0-9]+ tests|Test Suite .*failed' ios/.swift-cache/swift-review-test.log | tail -12`.

Raw summary output:

```text
Test Suite 'TraceRunnerTests' passed at 2026-10-09 14:21:59.231.
	 Executed 4 tests, with 0 failures (0 unexpected) in 0.001 (0.002) seconds
Test Suite 'NativeContractTests.xctest' passed at 2026-10-09 14:21:59.231.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 14:21:59.231.
	 Executed 7 tests, with 0 failures (0 unexpected) in 0.002 (0.004) seconds
Test Suite 'AsyncNativeContractTests' passed at 2026-10-09 14:21:59.332.
	 Executed 8 tests, with 0 failures (0 unexpected) in 0.003 (0.003) seconds
Test Suite 'AsyncNativeContractTests.xctest' passed at 2026-10-09 14:21:59.332.
	 Executed 8 tests, with 0 failures (0 unexpected) in 0.003 (0.003) seconds
Test Suite 'All tests' passed at 2026-10-09 14:21:59.332.
	 Executed 8 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
```

Unicode CLI smoke command: `printf '%s' '<two-scenario JSON using \\u00e9 and e\\u0301>' | ios/.swift-cache/debug/AsyncTraceRunner`.

Raw output:

```text
{"traces":[{"scenario":"é","steps":[]},{"scenario":"é","steps":[]}]}
```

Canonical SHA-256 remains `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`.
