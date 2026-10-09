# Kotlin Phase 6 report

Implemented contract v2 in the Kotlin reducer only. The contract file SHA-256 was verified as `fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11`. The only production behavior change is `Authenticated × LoginSucceeded`: state remains `Authenticated`, and the result now contains exactly `[ClearCredentials]`. The all-pairs expectation was strengthened, and `repeatedLoginWhileAuthenticatedClearsCredentialsAndKeepsSessionAuthenticated` covers the transition after an initial login. Existing tests were preserved.

## RED evidence

At `2026-10-09 04:16:43 UTC`, before changing production code, I ran:

```sh
date -u '+%Y-%m-%d %H:%M:%S UTC'; GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android :library:test --no-daemon
```

Both the repeated-login regression and the all-pairs test failed because the unchanged v1 reducer returned no effects where the v2 contract requires `[ClearCredentials]`. Full Gradle output is retained in `android/verification-logs/kotlin-phase6-red.log` (Gradle’s local report URL is omitted from this report).

The final 10 lines of the RED run were:

```text
* What went wrong:
Execution failed for task ':library:test'.
> There were failing tests. See the Gradle test report.

* Try:
> Run with --scan to get full insights into a Build Scan (powered by Develocity).

BUILD FAILED in 6s
4 actionable tasks: 2 executed, 2 up-to-date
```

## Repair and GREEN evidence

One candidate repair was applied after RED: split `SessionEvent.LoginSucceeded` out of the Authenticated branch's no-effect event group and return `Transition(SessionState.Authenticated, listOf(Effect.ClearCredentials))`. No follow-up repair was needed.

At `2026-10-09 04:16:59 UTC`, I reran the tests:

```sh
date -u '+%Y-%m-%d %H:%M:%S UTC'; GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android :library:test --no-daemon
```

The final 10 lines of the GREEN run were:

```text
> Task :library:classes UP-TO-DATE
> Task :library:jar
> Task :library:compileTestKotlin UP-TO-DATE
> Task :library:compileTestJava NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test

BUILD SUCCESSFUL in 5s
4 actionable tasks: 3 executed, 1 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Full logs: `android/verification-logs/kotlin-phase6-red.log` and `android/verification-logs/kotlin-phase6-green.log`.

At `2026-10-09 04:17:10 UTC`, the final wrapper build and distribution command was:

```sh
date -u '+%Y-%m-%d %H:%M:%S UTC'; GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android build :library:installDist --no-daemon
```

The final 10 lines were:

```text
> Task :library:processTestResources NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test UP-TO-DATE
> Task :library:check UP-TO-DATE
> Task :library:build
> Task :library:installDist

BUILD SUCCESSFUL in 4s
8 actionable tasks: 4 executed, 4 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Full log: `android/verification-logs/kotlin-phase6-build.log`.

The built runner processed `LoginSucceeded, LoginSucceeded, Logout` as expected: first login entered Authenticated with no effects; repeated login stayed Authenticated and emitted `ClearCredentials`; logout returned to Unauthenticated and emitted `ClearCredentials`. Captured stdout is in `android/verification-logs/runner-phase6.stdout`.
