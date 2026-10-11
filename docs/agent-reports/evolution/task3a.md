# Task 3A — Swift Logout

Implemented the contract v4 Refreshing Logout behavior in `ios/Sources/AsyncNativeContract/AsyncSession.swift`, using the exact INSERT case from `docs/experiments/native-anchors.md`. The existing response guard remains in its original location. No spec, verifier, script, guide, Android, managed facade, staging, or commit changes were made.

Updated `ios/Tests/AsyncNativeContractTests/AsyncNativeContractTests.swift` to cover direct cancellation output, repeated Logout, stale success and failure after cancellation followed by a new request, acceptance of the fresh reply, and cancellation/exhaustion at `Int64.max`. Existing unrelated assertions remain.

## TDD evidence

Focused command in both runs: `swift test --package-path ios --filter AsyncNativeContractTests`.

The raw logs are in `reports/evolution/task3a/red.log` and `reports/evolution/task3a/green.log` (this repository ignores `reports/`).

RED tail, captured from `tail -n 10 reports/evolution/task3a/red.log`:

```text
Test Suite 'AsyncNativeContractTests' failed at 2026-10-12 01:30:35.382.
	 Executed 10 tests, with 24 failures (0 unexpected) in 0.042 (0.043) seconds
Test Suite 'AsyncNativeContractTests.xctest' failed at 2026-10-12 01:30:35.382.
	 Executed 10 tests, with 24 failures (0 unexpected) in 0.042 (0.043) seconds
Test Suite 'Selected tests' failed at 2026-10-12 01:30:35.382.
	 Executed 10 tests, with 24 failures (0 unexpected) in 0.042 (0.043) seconds
Note: Some test targets reported failures:
  - AsyncNativeContractTests (XCTest)
```

The first regression failed because Logout left state `refreshing` and request ID `1` pending; stale-response and re-login cases also failed as expected.

GREEN tail, captured from `tail -n 10 reports/evolution/task3a/green.log`:

```text
Test Case '-[AsyncNativeContractTests.AsyncNativeContractTests testStaleRepliesAfterRefreshingLogoutCannotAffectNewRequest]' passed (0.000 seconds).
Test Suite 'AsyncNativeContractTests' passed at 2026-10-12 01:30:56.263.
	 Executed 10 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'AsyncNativeContractTests.xctest' passed at 2026-10-12 01:30:56.263.
	 Executed 10 tests, with 0 failures (0 unexpected) in 0.003 (0.004) seconds
Test Suite 'Selected tests' passed at 2026-10-12 01:30:56.263.
	 Executed 10 tests, with 0 failures (0 unexpected) in 0.003 (0.005) seconds
COMMAND_EXIT=0
```

No broad Python or full verifier run was performed, per brief.
