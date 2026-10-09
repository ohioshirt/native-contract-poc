# Async native quality review

Current verdict after first fix-wave re-review: acceptable within the stated serialized, same-logical-session, valid-input scope; no remaining native review blocker found. Full acceptance still requires root's pending gates. Reviewed the fixed canonical v3 specification, design/plan, Swift/Kotlin worker reports, new adapter/runner/test sources and target additions. Did not review unfinished Python/TLC work and did not rebuild either adapter. Canonical SHA-256 observed: `2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f`. Original findings/evidence below are retained as history and are resolved by the addendum.

## Blocker: Kotlin drops duplicate JSON object keys

`android/async-library/src/main/kotlin/nativecontract/async/AsyncTraceRunner.kt:9` parses directly to `JsonObject`; duplicate names have already been collapsed before `keys` can inspect them. The runner accepts both literal duplicates and escaped-equivalent names. This violates the design's whole-document rejection requirement and diverges from Swift. Add duplicate-aware validation before this lossy parse, including decoded key equality, and focused tests at root/scenario/event depths. Reject with nonzero exit and zero stdout even when an earlier scenario is valid.

Probe command executed from `/Users/shigeo/work/mobile` (existing installed binaries only):

```python
python3 - <<'PY'
import subprocess
from pathlib import Path
root=Path('native-contract-poc')
runners={'swift':root/'ios/.swift-cache/debug/AsyncTraceRunner','kotlin':root/'android/async-library/build/install/async-library/bin/async-library'}
samples={'duplicate-key':'{"scenarios":[{"scenario":"ok","events":[]},{"scenario":"dup","events":[{"event":"RefreshSucceeded","requestId":1,"requestId":2}]}]}','duplicate-escaped':'{"scenarios":[],"scenari\\u006fs":[]}','empty':'{"scenarios":[]}'}
for name,body in samples.items():
 for lang,exe in runners.items():
  p=subprocess.run([str(exe)],input=body,text=True,capture_output=True)
  print(name,lang,'exit=',p.returncode,'stdout-bytes=',len(p.stdout.encode()),'stdout=',p.stdout.strip(),'stderr=',p.stderr.strip())
PY
```

Raw output:

```text
duplicate-key swift exit= 1 stdout-bytes= 0 stdout=  stderr= AsyncTraceRunner: invalid input shape: duplicate object key: requestId
duplicate-key kotlin exit= 0 stdout-bytes= 204 stdout= {"traces":[{"scenario":"ok","steps":[]},{"scenario":"dup","steps":[{"event":{"event":"RefreshSucceeded","requestId":2},"state":"Unauthenticated","pendingRequestId":null,"effects":[],"rejection":null}]}]} stderr=
duplicate-escaped swift exit= 1 stdout-bytes= 0 stdout=  stderr= AsyncTraceRunner: invalid input shape: duplicate object key: scenarios
duplicate-escaped kotlin exit= 0 stdout-bytes= 14 stdout= {"traces":[]} stderr=
empty swift exit= 0 stdout-bytes= 14 stdout= {"traces":[]} stderr=
empty kotlin exit= 0 stdout-bytes= 14 stdout= {"traces":[]} stderr=
```

## API documentation gap: Swift copies and response routing

`ios/Sources/AsyncNativeContract/AsyncSession.swift:34` documents serialization only. A struct copy duplicates pending/counter state; two independently advanced copies can issue equal IDs, and a copy made while refreshing accepts the original pending completion. This is ordinary value semantics, not a numeric-counter bug. The design already requires routing to the same logical session and disclaims cross-instance identity. Before claiming the library's per-instance freshness guarantee, document beside the public type that copies are independent snapshots, callers must maintain one authoritative value per logical session, and IDs are not sufficient to route between copies/instances. Mirror same-instance routing documentation on Kotlin's public type. No class conversion or thread-safety expansion is needed.

## Native invalid IDs: no functional blocker under valid-input scope

Both public response events can carry zero/negative signed IDs, unlike the wire. Their guards ignore these values without mutation because pending IDs are always positive. Thus invalid native IDs cannot clear pending state or allocate IDs. The wire strictness explicitly concerns JSON tokens; the design does not prescribe a native malformed-input rejection type, and `RequestIdExhausted` must remain a domain rejection. A documented positive-ID precondition on native response events/handle is sufficient for contract conformance over valid inputs. Currently that precondition is not explicit in the public API comments; add it or explicitly document ignored out-of-domain native IDs. Do not silently repurpose exhaustion for malformed native input.

## Other source findings

By source inspection, both adapters compare full signed64 IDs; stale/duplicate/unissued responses preserve state/pending/counter/effects; counters survive logout/login and refresh completion; maximum allocation advances to unavailable without overflow; exhaustion occurs before mutation; effect/rejection shapes and ordering match canonical rows. Matching failure clears pending and credentials; success clears pending. Reachable states preserve `pending != null iff state == Refreshing`. Refreshing Logout remains ignored. No shared-caller thread-safety claim is made.

Swift token spelling validation rejects bool/string/fraction/exponent/nonpositive/out-of-range IDs before Foundation decoding and tracks decoded duplicate keys. Kotlin ID regex/range checks correctly reject those spellings but require the duplicate-key fix above. Both runners construct output before writing stdout, support absent/default or positive boundary seeds, empty scenarios/events, and duplicate scenario-ID rejection.

Command `git -C native-contract-poc diff -- ios/Sources/NativeContract ios/Sources/TraceRunner ios/Tests/NativeContractTests android/library` produced no output. Package/settings diffs add async targets/modules only. No claim is made that tests or full gates passed in this review: no tests/builds were run. Acceptance still depends on root's stable all-gate run and verification-worker results.

## First fix-wave re-review

Kotlin now scans original tokens with object-local decoded-name sets before producing any trace. Parsing occurs first to establish JSON validity; the scanner then checks the original source, so duplicate information is not lost despite the prior parsed tree being lossy. Nested object/array handling and quoted-string/escape skipping are correct by scoped source inspection. Swift's scenario duplicate set now uses UTF8 bytes rather than Swift String canonical-equivalence equality, aligning exact decoded codepoint identity with Kotlin/Python. Public Swift comments explain the authoritative value, copy history, response routing and non-global/non-authentic IDs. Both languages document positive native response IDs and caller serialization; Kotlin explicitly disclaims thread safety. These resolve the original findings.

Re-review command (existing binaries, no builds):

```python
python3 - <<'PY'
import subprocess,json
from pathlib import Path
root=Path('native-contract-poc')
runners={'swift':root/'ios/.swift-cache/debug/AsyncTraceRunner','kotlin':root/'android/async-library/build/install/async-library/bin/async-library'}
samples={'duplicate-key':'{"scenarios":[{"scenario":"ok","events":[]},{"scenario":"dup","events":[{"event":"RefreshSucceeded","requestId":1,"requestId":2}]}]}','duplicate-escaped':'{"scenarios":[],"scenari\\u006fs":[]}','distinct-unicode':json.dumps({'scenarios':[{'scenario':'é','events':[]},{'scenario':'e\u0301','events':[]}]}),'braces-in-string':json.dumps({'scenarios':[{'scenario':'x{"a":"b"}[]\\"','events':[]}]}),'duplicate-scenario-key':'{"scenarios":[{"scenario":"a","scenario":"b","events":[]}]}' }
for name,body in samples.items():
 for lang,exe in runners.items():
  p=subprocess.run([str(exe)],input=body,text=True,capture_output=True)
  print(name,lang,'exit=',p.returncode,'stdout-bytes=',len(p.stdout.encode()),'stdout=',p.stdout.strip(),'stderr=',p.stderr.strip())
PY
```

Raw output (complete):

```text
duplicate-key swift exit= 1 stdout-bytes= 0 stdout=  stderr= AsyncTraceRunner: invalid input shape: duplicate object key: requestId
duplicate-key kotlin exit= 2 stdout-bytes= 0 stdout=  stderr= duplicate object key: requestId
duplicate-escaped swift exit= 1 stdout-bytes= 0 stdout=  stderr= AsyncTraceRunner: invalid input shape: duplicate object key: scenarios
duplicate-escaped kotlin exit= 2 stdout-bytes= 0 stdout=  stderr= duplicate object key: scenarios
distinct-unicode swift exit= 0 stdout-bytes= 72 stdout= {"traces":[{"scenario":"é","steps":[]},{"scenario":"é","steps":[]}]} stderr=
distinct-unicode kotlin exit= 0 stdout-bytes= 72 stdout= {"traces":[{"scenario":"é","steps":[]},{"scenario":"é","steps":[]}]} stderr=
braces-in-string swift exit= 0 stdout-bytes= 60 stdout= {"traces":[{"scenario":"x{\"a\":\"b\"}[]\\\"","steps":[]}]} stderr=
braces-in-string kotlin exit= 0 stdout-bytes= 60 stdout= {"traces":[{"scenario":"x{\"a\":\"b\"}[]\\\"","steps":[]}]} stderr=
duplicate-scenario-key swift exit= 1 stdout-bytes= 0 stdout=  stderr= AsyncTraceRunner: invalid input shape: duplicate object key: scenario
duplicate-scenario-key kotlin exit= 2 stdout-bytes= 0 stdout=  stderr= duplicate object key: scenario
```

Command `shasum -a 256 native-contract-poc/contract/specification.json` again returned:

```text
2accb45bb81eb931c2debebb990719e05d49109eec7afec2718c34afdc3aa08f  native-contract-poc/contract/specification.json
```

No native tests/builds were repeated in this re-review. No verification-worker code was reviewed. Review report is stable.
