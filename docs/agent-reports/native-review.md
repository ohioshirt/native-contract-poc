# Independent native quality review (v1)

Scope: the fixed v1 contract, design/plan, Swift `ios/`, Kotlin `android/`, native unit tests, native worker reports and Gradle wrapper configuration. Python verification, scripts and CI are outside this review. No native sources were modified, and no expensive builds were repeated.

## Verdict

Approved for v1 native task specification and quality after one correction round. The Important wire-interface mismatch below is resolved. No outstanding Critical or Important native issue found.

### Resolved Important finding: Kotlin rejected a valid empty string scenario ID

The initial `android/library/src/main/kotlin/nativecontract/TraceRunner.kt:29` imposed an undocumented nonempty-ID constraint. The design requires a string ID and rejects duplicate IDs; it does not prohibit the empty string. Swift accepts it. The writer removed the restriction and added `runnerAcceptsAnEmptyScenarioId`. Duplicate-ID validation is retained, including two empty IDs, confirmed by the targeted executable check below.

Targeted command executed from `/Users/shigeo/work/mobile`:

```sh
python3 - <<'PY'
import subprocess
from pathlib import Path
root=Path('native-contract-poc')
payload=b'{"scenarios":[{"scenario":"","events":[]}]}'
for name,path in [('Swift',root/'ios/.build/debug/TraceRunner'),('Kotlin',root/'android/library/build/install/library/bin/library')]:
    result=subprocess.run([str(path.resolve())],input=payload,capture_output=True)
    print(name, 'exit=',result.returncode,'stdout=',result.stdout.decode().strip(),'stderr=',result.stderr.decode().strip())
PY
```

Raw output:

```text
Swift exit= 0 stdout= {"traces":[{"scenario":"","steps":[]}]} stderr=
Kotlin exit= 2 stdout=  stderr= scenario id must not be empty
```

## Reviewed properties

Both handwritten reducers use typed enums, expose readable state with restricted mutation, return state and ordered effects, and match each declared v1 transition by source inspection. Their exhaustive Swift tuple switch / Kotlin enum `when` branches avoid fallback behavior outside the declared domain. Neither reducer reads or interprets the JSON contract or depends on the other implementation.

Both runners create a fresh reducer per scenario, represent empty event sequences with zero steps, preserve input event/effect order, validate exact document/scenario key sets and string event names, reject unknown events and duplicate IDs, and write stdout only after successful document processing. Typed reducer APIs remain independent of JSON processing in their implementation; Foundation / kotlinx.serialization are used by the trace adapters.

Native unit tests cover initial state, declared state/event transitions, state update, scenario isolation, empty event sequence, unknown event, duplicate scenario ID and invalid object shape. Swift additionally directly tests malformed JSON syntax. Kotlin's malformed-syntax branch is apparent in the parser catch but its existing rejection test exercises an extra field rather than malformed syntax; adding a syntax case would improve coverage, but is not an additional blocking issue.

SwiftPM declares library, executable and test targets. Kotlin declares a JVM library/application with Java 17 toolchain, a pinned Kotlin plugin and serialization dependency. Gradle wrapper scripts and JAR exist, `gradlew` is executable, and the wrapper properties and wrapper task agree on Gradle distribution and SHA-256. Native worker reports contain explicit build/test commands and raw final output. I read those evidence records; I do not claim fresh build/test execution here. The Kotlin recorded wrapper build completed with `BUILD SUCCESSFUL`, and its test task in that build was `UP-TO-DATE`; the separate green log shows `:library:test` executed. Swift's report records successful `swift build` and `swift test` output. No hosted CI result is inferred.

The review remains v1-specific. Phase 6 requires an updated review after the contract change and independent native fixes.


## Correction verification

Read the updated Kotlin report and `kotlin-empty-id-green.log` / `kotlin-final-build.log`. The report records `GRADLE_USER_HOME="$PWD/.gradle-home" ./android/gradlew -p android build :library:installDist --no-daemon`; its raw final log ends:

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

I reran only a lightweight binary probe, using the earlier Python command with both a single empty-ID scenario and two empty-ID scenarios. Exact output:

```text
Swift exit= 0 stdout= {"traces":[{"scenario":"","steps":[]}]} stderr=
Kotlin exit= 0 stdout= {"traces":[{"scenario":"","steps":[]}]} stderr=
Swift exit= 1 stdout=  stderr= TraceRunner: duplicate scenario ID:
Kotlin exit= 2 stdout=  stderr= duplicate scenario id:
```

Both executables now agree on acceptance of an empty string ID and rejection of duplicate empty string IDs without partial stdout.
