# Task 4A: Kotlin Logout

Implemented the v4 Refreshing Logout behavior in `AsyncSession`. Logout now transitions to `Unauthenticated`, clears the pending request, and returns exactly `ClearCredentials`, while preserving the next request ID (including `null` exhaustion). The response guard and accepted-Logout counter-reset marker remain at their existing locations. Added tests for direct cancellation results, repeated Logout, stale success and failure after a later refresh, fresh response acceptance, and cancellation of the final allocated ID.

## TDD evidence

Focused command:

```sh
GRADLE_USER_HOME=/Users/shigeo/work/mobile/native-contract-poc/.gradle-home ./android/gradlew -p android :async-library:test
```

The command was first run before the production change. Raw output is in `reports/evolution/task4a/red.log`; the test summary and tail were:

```text
AsyncSessionTest > cancelledSuccessAndFailureCannotChangeANewerRefresh() FAILED
    org.opentest4j.AssertionFailedError at AsyncSessionTest.kt:71

AsyncSessionTest > cancellingFinalAllocatedIdPreservesExhaustion() FAILED
    org.opentest4j.AssertionFailedError at AsyncSessionTest.kt:97

AsyncSessionTest > logoutCancelsRefreshAndRepeatedLogoutHasNoEffects() FAILED
    org.opentest4j.AssertionFailedError at AsyncSessionTest.kt:49

8 tests completed, 3 failed

FAILURE: Build failed with an exception.
> Task :async-library:test FAILED
BUILD FAILED in 850ms
4 actionable tasks: 1 executed, 3 up-to-date
```

After the production change, the same command passed. Raw output is in `reports/evolution/task4a/green.log`; its raw tail is:

```text
> Task :async-library:classes UP-TO-DATE
> Task :async-library:jar
> Task :async-library:compileTestKotlin UP-TO-DATE
> Task :async-library:compileTestJava NO-SOURCE
> Task :async-library:testClasses UP-TO-DATE
> Task :async-library:test

BUILD SUCCESSFUL in 1s
4 actionable tasks: 3 executed, 1 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

The green Gradle output did not print a test-case count. No other test command was run.
