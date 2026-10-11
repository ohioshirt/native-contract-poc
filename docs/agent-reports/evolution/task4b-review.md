# Task4B independent Kotlin review

Verdict: **APPROVED** within the frozen ordinary external Kotlin source-client scope. No important correctness issue was found. Parent retains the aggregate API/mutation gate and frozen-manifest checks; this approval does not claim those pending gates were executed by this reviewer.

## Scope

Reviewed only `ManagedAsyncSession.kt`, `ManagedHistoryRunner.kt`, and the managed tests under `android/async-library`, against frozen `managed-native-brief.md`, `managed-history-format.md`, and evolution design C/R3/R4. Read the Task4B implementation report and command evidence. The existing low-level session was treated as the approved dependency. No Swift source, evaluator implementation, or other native implementation was inspected. No source edits, test reruns, nested agents, staging, or commits were performed. No concrete behavioral doubt remained that required a targeted reproduction.

## Facade reasoning

- `ManagedAsyncSession.kt:43–78`: one final session owns one private low-level session, private retained owner identity, and private monitor. Both public operations acquire the same monitor. The whole owner validation/reduction/token creation/effects copying/snapshot operation remains inside that critical section. The private snapshot helper has only monitor-protected callers. Thus an operation observes a coherent `(state,pending,next)` triple, and monitor release/acquire supplies visibility to aliases and concurrent callers.
- `ManagedAsyncSession.kt:5–12,51–67`: the final token has read-only ID, a private retained identity reference, private constructor, and no copy or restoration API. Each new session creates a distinct identity. Retaining the identity prevents identity reuse even after the originating session is unreachable. The common identity guard precedes numeric response correlation for both response kinds. A foreign token therefore returns unchanged state, detached empty effects, and `ForeignRequest` even with a stale or coincident numeric ID.
- `ManagedAsyncSession.kt:46,68–75`: the facade seeds the approved signed64 allocator only once, obtains IDs only from actual low-level effects, and exposes no state/counter restoration or mutation. Fresh allocation, atomic exhaustion, Logout counter preservation, and matching-owner stale/duplicate handling remain delegated to the approved session. Tests cover both final IDs, exhausted null allocator, canceled local requests, foreign-before-stale rejection, and duplicate completion.
- `ManagedAsyncSession.kt:29–36,69–75`: snapshots contain immutable values. Each result copies effects into a fresh ArrayList and wraps it with `Collections.unmodifiableList`. Effect objects and request fields are immutable. Retained snapshots/effects cannot change with later transitions; populated and empty effects resist mutable-list casts. Public snapshot copies cannot restore session state.
- No callback, caller-supplied collection, I/O, await, or arbitrary caller implementation executes during facade transitions. Sealed final event/effect types and direct identity comparison provide no reentrant caller hook; monitor reentrancy introduces no independent mutation path.

Opacity is assessed for ordinary external Kotlin source clients, as explicitly clarified by the parent. Kotlin `internal` declarations are not JVM-wide secrecy; no Java-source or hostile bytecode/reflection claim is made. Parent owns the frozen external compile probes.

## Runner reasoning

- `ManagedHistoryRunner.kt:107–179`: each trial constructs new sessions, recorder, token store, completion futures, and rows. Every phase launches actual pool threads behind a common pre-invocation barrier; pool size equals phase size, so same-phase dependency waits do not starve producers. Futures are joined before advancing to the next phase. The first caller failure is retained while remaining futures are joined. Shutdown and termination waiting run on failure too. Worker failures propagate to nonzero process exit rather than a completed subset.
- `ManagedHistoryRunner.kt:24–26,139–148`: one short synchronized recorder supplies globally increasing stamps across all owners. Invocation and return stamps immediately surround actual `handle`/`snapshot` calls. No recorder lock spans the API call. Observations come from actual returned objects; no serial expected state is synthesized.
- `ManagedHistoryRunner.kt:82–100,125–126,149–163`: tokenRef adds the producer dependency. Cycles and later-phase predecessors are rejected before launching callers. Producer return is stamped before the actual emitted request is published. Publication and result-row creation precede completion-future signaling. Consumers wait, then retrieve that same request. CompletableFuture completion/wait and ConcurrentHashMap publication provide the required visibility. Failed/nonproducing references fail the whole document.
- Rendering preserves complete owner/seed declarations and operation input/phase/after metadata. Response metadata adds the actual token owner/ID while retaining tokenRef. Results contain actual snapshot/effects/rejection; snapshots add only required empty effects/null rejection. Signed64 parsing/rendering uses integer tokens and Long, with no floating conversion. Maximum-ID and metadata tests exercise those paths.
- `ManagedHistoryRunner.kt:36–43,212–219`: bounded retries recreate the complete scenario and emit exactly one complete trial. Observed intervals determine overlap; rows are not combined across trials. Exhausted retries leave missing overlap visible for the external checker to classify as non-PASS.

Managed tests cover alias coherence, effect detachment, foreign and stale requests, signed64 exhaustion, concurrent expiration/snapshots, actual returned-token provenance, metadata and stamps, same-phase ordering, malformed/nonproducing refs, and cycles. Supplied checker evidence independently covers frozen concurrent phases. This is bounded observation evidence, not unbounded native refinement or an effects-execution ordering guarantee.

## Evidence inspected, not rerun

Original worker execution commands and raw tails are in `reports/evolution/task4b/commands.md`. Reviewer executed this read-only inspection:

```sh
tail -n 12 reports/evolution/task4b/green-managed.log
tail -n 12 reports/evolution/task4b/green-module.log
```

Raw latter tail:

```text
> Task :async-library:jar UP-TO-DATE
> Task :async-library:compileTestKotlin UP-TO-DATE
> Task :async-library:compileTestJava NO-SOURCE
> Task :async-library:processTestResources NO-SOURCE
> Task :async-library:testClasses UP-TO-DATE
> Task :async-library:test
> Task :async-library:startScripts UP-TO-DATE
> Task :async-library:installDist UP-TO-DATE

BUILD SUCCESSFUL in 906ms
6 actionable tasks: 1 executed, 5 up-to-date
Consider enabling configuration cache to speed up this build: https://docs.gradle.org/9.8.0/userguide/configuration_cache_enabling.html
```

Reviewer read the already-produced checker report with:

```sh
python3 - <<'PY'
import json
from pathlib import Path
p=Path('reports/evolution/task4b/linearizability.json')
d=json.loads(p.read_text())
print('report:', p)
print('verdict:', d.get('verdict'))
print('bounds:', d.get('bounds'))
for entry in d.get('histories', d.get('results', [])):
    print(entry.get('scenario'), entry.get('verdict'), entry.get('concurrencyCoverage'))
PY
```

Raw inspection output:

```text
report: reports/evolution/task4b/linearizability.json
verdict: PASS
bounds: {'operations': 16, 'nodes': 1000000, 'seconds': 10}
foreign-same-id PASS {}
logout-vs-success PASS {'2': True}
logout-vs-failure PASS {'2': True}
stale-after-new-request PASS {}
simultaneous-expiration PASS {'1': True}
max-logout-exhaustion PASS {}
last-two-ids PASS {}
```

These are existing worker artifacts inspected during review, not newly executed build/test/checker results. No combined test total is reported.

Report write hygiene: the first report-write shell command failed with a heredoc-delimiter parse error before writing the report; the corrected command used a distinct delimiter. No implementation file was changed.
