# Async Kotlin adapter report

Implemented the separate `:async-library` module and installed `AsyncTraceRunner` at `android/async-library/build/install/async-library/bin/async-library`. The adapter owns an independent typed reducer and state per `AsyncSession`; the legacy `:library` reducer and runner were not edited. It tracks the pending request ID separately from the monotonic next ID, never resets or wraps the counter, and returns typed `RequestIdExhausted` with no state or effect change after exhaustion. Refreshing × Logout remains ignored. The JSON runner requires exact input keys, unique scenario IDs, response IDs as positive integer tokens within signed `Long`, and builds the entire output before printing.

The canonical specification SHA-256 remained `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f` when checked after implementation.

## Verification evidence

The first successful test invocation compiled and exercised three focused tests for lifecycle correlation/staleness, maximum-ID exhaustion atomicity, and strict wire validation. The test source initially had a type/syntax error and one incorrect expected lifecycle step; those were corrected before the successful run.

Command: `GRADLE_USER_HOME="$PWD/../.gradle-home" ./gradlew :async-library:test` (run from `android/`; the sandbox required allowing Gradle's local file-lock socket).

Raw final output:

```text
> Task :async-library:test

BUILD SUCCESSFUL in 1s
4 actionable tasks: 2 executed, 2 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Command: `GRADLE_USER_HOME="$PWD/../.gradle-home" ./gradlew :async-library:installDist` (run from `android/`).

Raw final output:

```text
> Task :async-library:startScripts
> Task :async-library:installDist

BUILD SUCCESSFUL in 509ms
4 actionable tasks: 2 executed, 2 up-to-date
Consider enabling configuration cache to speed up your build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

The installed runner was also invoked with a normal lifecycle scenario and a `Long.MAX_VALUE` seed. It emitted request ID `9223372036854775807` once, then returned a step with unchanged `Authenticated` state, null pending ID, empty effects, and `RequestIdExhausted`.

Malformed exponent ID fixture command exited 2; its captured stdout size was 0 bytes, so a valid earlier scenario in the same document was not partially printed. Raw tail:

```text
exit=2 stdout-bytes=       0
stderr-tail:
event[0].requestId must be a positive integer token
```

`git diff --check` produced no output. No core Kotlin files were changed.

## Kotlin async mutation sites

- Stale-success guard: [AsyncSession.kt](/Users/shigeo/work/mobile/native-contract-poc/android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt:48), unique marker `PATCH_SITE_STALE_RESPONSE_GUARD`. Remove/disable the `if` guard at this location to accept stale responses.
- Accepted Authenticated Logout counter reset: [AsyncSession.kt](/Users/shigeo/work/mobile/native-contract-poc/android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt:68), unique marker `PATCH_SITE_ACCEPTED_LOGOUT_COUNTER_RESET`. Insert `nextRequestId = 1L` at this point for the isolated reset mutant.

These markers are comments only; production code has no mutation flags or alternate behavior.

## Duplicate-key review fixwave

Added a recursive tokenizer pass over parser-validated JSON before constructing the lossy `JsonObject` representation. It decodes each key string through the standard JSON parser and compares decoded keys within each object, so literal and escaped-equivalent duplicates reject at root, scenario, and event depth. String tokens are scanned with escape handling; object-like text inside a string is left untouched. The runner still constructs the complete result before stdout. Public API comments now state that native response IDs must be positive signed64 IDs issued to the same logical session, responses must return to the same authoritative `AsyncSession`, callers must serialize calls, and the mutable type is not thread-safe. Nonpositive native IDs continue to fail the active-ID match without changing state.

The duplicate-key regressions were added first. Red command: `GRADLE_USER_HOME="$PWD/../.gradle-home" ./gradlew :async-library:test` (from `android/`). Its raw tail before the fix:

```text
> Task :async-library:test FAILED

AsyncSessionTest > runnerRejectsDuplicateDecodedKeysAtEveryDepth() FAILED

5 tests completed, 1 failed

FAILURE: Build failed with an exception.
    org.opentest4j.AssertionFailedError at AsyncSessionTest.kt:60
```

Final focused command: `GRADLE_USER_HOME="$PWD/../.gradle-home" ./gradlew :async-library:test :async-library:installDist` (from `android/`). Raw tail:

```text
> Task :async-library:test

BUILD SUCCESSFUL in 1s
6 actionable tasks: 6 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Installed-runner probe command: Python `subprocess.run` over duplicate literal requestId, escaped duplicate root/scenario/event keys, a scenario name containing quote/braces/brackets, and two canonically equivalent Unicode spellings. Raw output:

```text
duplicate-requestId: exit=2 stdout-bytes=0 stdout='' stderr='duplicate object key: requestId'
duplicate-escaped-root: exit=2 stdout-bytes=0 stdout='' stderr='duplicate object key: scenarios'
duplicate-escaped-scenario: exit=2 stdout-bytes=0 stdout='' stderr='duplicate object key: scenario'
duplicate-escaped-event: exit=2 stdout-bytes=0 stdout='' stderr='duplicate object key: event'
syntax-like-string: exit=0 stdout-bytes=67 stdout='{"traces":[{"scenario":"quote \\" and braces { } [ ]","steps":[]}]}' stderr=''
unicode-id-spellings: exit=0 stdout-bytes=72 stdout='{"traces":[{"scenario":"é","steps":[]},{"scenario":"é","steps":[]}]}' stderr=''
```

The Kotlin runner treats the two Unicode scenario IDs as distinct exact strings and accepts both. This input behavior is reported for cross-runner comparison; the accepted ID alphabet was not narrowed. Canonical specification hash stayed unchanged, and the legacy Kotlin module remains untouched.
