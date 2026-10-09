# Native Contract PoC design

User brief is the binding design; Sol fixes the finite total Mealy machine before native delegation.
States S={Unauthenticated, Authenticated, Refreshing}; events E={LoginSucceeded, Logout, TokenExpired, RefreshSucceeded, RefreshFailed}; effects F={RequestTokenRefresh, ClearCredentials}.
δ:S×E→S×F* is fully enumerated in contract/specification.json. Domain completeness, determinism, codomain closure and effect bounds are checked before generating the oracle. All runs begin in Unauthenticated.

Swift and Kotlin implement independent reducers without reading each other or interpreting the specification. Python alone interprets the contract to generate oracle traces; a separate comparison checks native agreement. Exhaustively enumerate E^0 through E^4. This is bounded testing, not proof of arbitrary program equivalence.

Wire interface: stdin {"scenarios":[{"scenario":"id","events":["LoginSucceeded"]}]}; stdout {"traces":[{"scenario":"id","steps":[{"event":"LoginSucceeded","state":"Authenticated","effects":[]}]}]}. Initial state is observable through the library API and unit tests; an empty trace contains zero steps. Unknown events, duplicate scenario IDs or malformed input are rejected with nonzero exit and stderr diagnostics; no partial stdout. Output steps contain only event/state/effects; effects are ordered lists. Each scenario has a fresh session.

Library API typed enums, state accessor and handle(event) result/effects. Caller serializes access; OS concurrency is outside this PoC. Foundation JSON (Swift) and kotlinx.serialization JSON (Kotlin runner only) are acceptable; no shared implementation dependency.

Mutation scripts copy sources to isolated temporary directories, patch uniquely identified reducer branches, rebuild runners and evaluate each expected matrix. Build failures do not count as killed mutations. Baseline restored by discarding copies. Reports retain commands/logs and provenance including source dirty status.

Phase 6: Sol updates only Authenticated×LoginSucceeded to emit ClearCredentials and stay Authenticated. Observe pre-fix contract rejection, delegate independent fixes, keep existing tests and rerun all gates and mutations. Preserve v1 contract/reports as experiment history; sole current authority remains specification.json.

CI on macOS, explicit Swift selection/version logging, Gradle wrapper pinned distribution/checksum, Kotlin plugin version and Java/Python managed. PR/main run native builds, unit tests, oracle and differential checks; artifacts and job summary uploaded even on failures.

Acceptance is local successful gates and mutation matrix, documented change experiment, and CI definition. Actual hosted CI success needs a GitHub remote and run; never infer it from local success. No deployment/distribution. Additional Luna-only experiment uses isolated v1 copy, same v2 contract and evidence, reports measured quality/fix attempts; monetary cost unavailable unless provider exposes usage.
