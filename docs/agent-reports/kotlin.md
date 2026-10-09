# Kotlin implementation report (v1)

Implemented the independent Kotlin/JVM reducer and strict stdin JSON runner under `android/`. The API exposes typed `SessionState`, `SessionEvent`, and `Effect` enums, a state accessor, and `handle(event)` returning the new state and ordered effects. The runner validates the document and scenario keys, rejects non-string or unknown events and duplicate IDs, accepts any string scenario ID including the empty string, and writes no trace until the entire document has parsed successfully. Each scenario starts a new reducer. `installDist` creates `android/library/build/install/library/bin/library`.

## Verification

Java runtime: `openjdk version "17.0.13" 2024-10-15 LTS` (Amazon Corretto).

RED command, run after adding tests and before production Kotlin sources:

```sh
GRADLE_USER_HOME="$PWD/.gradle-home" gradle -p android :library:test --no-daemon
```

It failed at `:library:compileTestKotlin` because the tests referenced the not-yet-defined `SessionReducer` and `runDocument` API. Full log: `android/verification-logs/kotlin-red.log`. Its final output was:

```text
Execution failed for task ':library:compileTestKotlin' (registered by plugin 'org.jetbrains.kotlin.jvm').
> A failure occurred while executing org.jetbrains.kotlin.compilerRunner.btapi.BuildToolsApiCompilationWork
   > Compilation error. See log for more details

* Try:
> Run with --stacktrace option to get the stack trace.
> Run with --info or --debug option to get more log output.
> Run with --scan to get full insights into a Build Scan (powered by Develocity).
> Get more help at https://help.gradle.org.

BUILD FAILED in 6s
2 actionable tasks: 1 executed, 1 up-to-date
```

GREEN command after implementation:

```sh
GRADLE_USER_HOME="$PWD/.gradle-home" gradle -p android :library:test --no-daemon
```

Its final output was:

```text
> Task :library:compileJava NO-SOURCE
> Task :library:classes UP-TO-DATE
> Task :library:jar
> Task :library:compileTestKotlin
> Task :library:compileTestJava NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test

BUILD SUCCESSFUL in 9s
4 actionable tasks: 4 executed
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Full log: `android/verification-logs/kotlin-green.log`.

Final build command using the committed wrapper:

```sh
GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android build --no-daemon
```

Its final output was:

```text
> Task :library:assemble
> Task :library:compileTestKotlin UP-TO-DATE
> Task :library:compileTestJava NO-SOURCE
> Task :library:processTestResources NO-SOURCE
> Task :library:testClasses UP-TO-DATE
> Task :library:test UP-TO-DATE
> Task :library:check UP-TO-DATE
> Task :library:build

BUILD SUCCESSFUL in 3s
7 actionable tasks: 2 executed, 5 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Full log: `android/verification-logs/kotlin-build.log`. The wrapper uses Gradle 9.8.0, binary distribution, pinned by SHA-256 in `android/gradle/wrapper/gradle-wrapper.properties`. The wrapper generation/installDist logs are also retained in `android/verification-logs/`.

The installed runner produced the expected ordered state/effect trace for `LoginSucceeded, TokenExpired, RefreshFailed`; stdout is retained in `android/verification-logs/runner-valid.stdout`. An unknown event exited with status 2, emitted `unknown event: Unknown` to stderr, and left stdout empty; captured streams are `android/verification-logs/invalid.stderr` and `android/verification-logs/invalid.stdout`.

## Mutation patch locations

Patch only the unique matching branch line in `android/library/src/main/kotlin/nativecontract/SessionReducer.kt`:

- Mutation B (Refreshing × RefreshFailed drops its effect): line 30, `SessionEvent.RefreshFailed -> Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials))`. Replace the transition with `Transition(SessionState.Unauthenticated)`.
- Mutation C (Authenticated × Logout drops its effect): line 23, `SessionEvent.Logout -> Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials))`. Replace the transition with `Transition(SessionState.Unauthenticated)`.

No mutation flags or behavior are present in the production runner.


## Empty scenario ID contract correction

The native review noted that any string ID is valid in the frozen wire contract. Added `runnerAcceptsAnEmptyScenarioId` before changing the implementation. The first regression run failed in `:library:test` as expected while the runner rejected `id.isEmpty()`; the failing run is retained in `android/verification-logs/kotlin-empty-id-red.log`. Removed that rejection and retained the regression test.

Final command, including `installDist`:

```sh
GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android build :library:installDist --no-daemon
```

Its final output was:

```text
> Task :library:compileTestKotlin UP-TO-DATE
> Task :library:compileTestJava NO-SOURCE
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

Full log: `android/verification-logs/kotlin-final-build.log`. The refreshed installed runner accepted an empty ID and returned `{"traces":[{"scenario":"","steps":[]}]}`; captured output is `android/verification-logs/runner-empty-id.stdout`.
