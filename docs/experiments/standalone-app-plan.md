# Standalone native integration implementation plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task in the next session. The requested executor is **Luna, Max reasoning**. Astra owns design decisions; Claude/Fable reviews. Do not spawn additional agents without user instruction. This session creates design/plan/handoff only. Do not implement, commit or push in this session.

**Goal:** Demonstrate with real iOS/Android apps that delayed refresh responses cannot restore or overwrite credentials/UI after completed Logout.

**Architecture:** One FIFO consumer sequences managed reduction, verified persistence and acknowledged main-thread publication. HTTP tasks return completions retaining the original opaque request object. An independent frozen evaluator checks explicit barriers, observable real storage/UI and negative controls.

**Tech Stack:** Swift 6/SwiftUI/URLSession/Keychain; Kotlin 2.3.20/Compose/HttpURLConnection/AtomicFile; app-local AGP 8.13.2 and Gradle 8.13; Python 3.12.8 standard library; existing JSON/TLC verification unchanged.

**Spec:** [standalone-app-design.md](standalone-app-design.md). Read both documents and the final review/handoff before executing.

## Global constraints

- Baseline is `d2ce1847cb2644252f7c4d069ef9e36142bb327b`; preserve existing `contract/`, `formal/`, `ios/` public library API/platform floors, `android/` root build and every old fixture/control.
- App iOS target 16.0, Swift 6; app Android minSdk 26, compile/target 35, Build Tools 35.0.0, JDK/bytecode 17, AGP 8.13.2, Gradle 8.13, Kotlin/Compose compiler 2.3.20, Compose BOM 2025.01.01, activity-compose 1.10.0, test runner 1.6.2/ext junit 1.2.1/JUnit 4.13.2.
- Source reuse through local Swift package and Gradle `:contract-async` project, with app-local build outputs. Do not duplicate/reimplement managed reducers or construct opaque requests from JSON.
- Scope is synthetic tokens, foreground requests, bootstrap credential deletion; persisted login restoration and production authentication are deferred.
- App command/audit/epoch-label/revision counter overflow is a terminal `CounterExhausted` process abort with no success receipt or new UI publication, never wrap/reuse or an impossible extra FaultLocked revision. Swift uses a `Never` fail-stop function and Kotlin a `Nothing` fail-stop function; it terminates only this demo app process. This is distinct from the existing managed allocator's recoverable `RequestIdExhausted` rejection.
- Every accepted command completes persistence/readback and UI acknowledgement before another starts. Transport never mutates credential storage or auth UI. Primary stale-response scenarios disable physical cancellation.
- Read/store/publication errors remain visible; failed cleanup cannot be called successful Logout. Test-only faults/replay/barriers are Debug seams recorded in evidence.
- Complete/review evaluator before freeze; run semantic integration RED before app candidate evaluation. Missing old app is NOT_RUN, not semantic RED. Evaluator changes require new manifest and repeated RED/candidate evaluations.
- Existing full gate and old change-protocol reproduction remain independent requirements. `SKIP_MUTATIONS=1` is incomplete.
- All commands below are **planned, not executed in this design session**. Capture exact argv, raw stdout/stderr, exit code, artifact hashes and final log tails for reported tests; do not invent counts or infer PASS from a build.
- Use dedicated test simulator/AVD; inventory-selected IDs via environment. Never reset/erase a user-owned booted simulator/AVD. Physical-device installation is a separately identified manual smoke run.
- Do not commit/push unless the next session's authorization explicitly includes it. Stage only named paths when authorized.

Execution variables are explicit: set `OUT` to a fresh owned directory under `reports/standalone/`, `IOS_SIMULATOR_UDID` to a dedicated simulator, and `ANDROID_SERIAL` to a dedicated emulator. The controller starts its own server with `--port 0`, reads the bound port from `server-ready.json`, then injects a platform-specific BaseURL (iOS loopback or Android `10.0.2.2`). Each platform run has its own server/output namespace, so local parallel runs cannot collide on 8765. Manual server runs may explicitly request 8765.

## Review focus

- A late failure after Login B must not delete B: APP-05, Tasks 1/4/5/6.
- Actor reentry while awaiting managed/UI work must not start a second consumer: APP-11, Tasks 4/6.
- Store mutates then readback fails: locked UI, unknown physical state, no success receipt: APP-09/10, Tasks 4/5/6.
- Real network cancellation hides late-response exposure: APP-02/03 require cancel-disabled delivery; APP-08 is distinct, Tasks 2/6.
- App/process/view lifecycle reuses or restores obsolete state: APP-12/14, Tasks 4/5/6.

## File ownership and interfaces

Evaluator-owned, protected after freeze:

```text
integration/__init__.py
integration/{contract.json,scenarios.json,control-scenarios.json,history.schema.json,native-anchors.md}
integration/{wire.py,server_state.py,server.py,model.py,check.py,controller.py}
integration/{mutation_matrix.json,mutations.py,protocol_config.py,reproduce.py,toolchain.json}
integration/fixtures/unsafe_adapter.py
integration/tests/test_{wire,server,model,check,protocol,mutations,controller}.py
verification/change_protocol.py
verification/test_change_protocol.py
scripts/integration-verify.sh
apps/ios-demo/NativeContractDemoUITests/ScenarioUITests.swift
apps/ios-demo/NativeContractDemoTests/ScenarioContractTests.swift
apps/ios-demo/NativeContractDemo/Debug/StorageProbe.swift
apps/ios-demo/NativeContractDemo/Debug/DebugScenarioControl.swift
apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt
apps/android-demo/app/src/androidTest/java/nativecontract/demo/DemoTestRunner.kt
apps/android-demo/app/src/test/java/nativecontract/demo/ScenarioContractTest.kt
apps/android-demo/app/src/debug/java/nativecontract/demo/debug/StorageProbe.kt
apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioControl.kt
.github/workflows/integration.yml
```

Candidate-owned after freeze: app runtime sources, candidate unit tests, and only the exact packaging files listed by the manifest. Frozen harness sources above are excluded from candidate ownership even though under `apps/`. Dependency pins/locks and CI scripts are protected. Packaging changes after freeze require a revised manifest. Existing code changes are limited to an additive change-protocol report validator with regression tests; old evaluator behavior cannot change.

Common type semantics (Swift structs/enums are immutable `Sendable`; Kotlin fields are `val`, no credential `toString`):

```text
Account = A | B
ProcessContext(processInstanceId: String, launchOrdinal: Int)
Credential(account: Account, version: Int, accessToken: String, refreshToken: String)
StoreObservation = Absent | Present(account, version) | Unknown(errorCode)
AppCommand = Bootstrap | Login(Account) | Expire | Logout | CancelRefresh
           | Deliver(Completion) | Observe | RetryCleanup
ReceiptStatus = Completed | RejectedBusy | IgnoredStale | IgnoredForeign
              | RejectedExhausted | FaultLocked(errorCode)
CommandReceipt(id: Int64, status: ReceiptStatus, observation: AppObservation)
AppObservation(managedState, pendingRequestId, nextRequestId,
               store: StoreObservation, view: DemoViewState)
DemoViewState(processInstanceId: String, revision: Int64, phase, account?,
              credentialVersion?, pendingRequestId?, lastCompletedCommandId?,
              lastCommandStatus?, errorCode?)
Outcome = Success(Credential) | Failure(TransportFailure)
TransportFailure = unauthorized | server | malformed | correlationMismatch
                 | disconnected | timeout | cancelled
RefreshSlot(identity, request: RefreshRequest, epoch: Epoch,
            issuanceCommandId: Int64, wireTag: String, account: Account)
Completion(slot: RefreshSlot, outcome: Outcome)
```

`StoreObservation` is redacted; the store's private read result retains raw values only for equality checks. `RefreshSlot` and `Epoch` are reference identities, not data classes with value equality. Native runtime command IDs, local trace sequence and UI revision are checked positive signed64 within each process. Trace event fields include `processInstanceId`, `launchOrdinal`, `localSequence`; command references are `{processInstanceId,id}`. Controller assigns `processInstanceId=<attemptId>/<scenarioId>/p<launchOrdinal>`, and native artifacts export to `<scenarioId>/p<launchOrdinal>/`. Relaunch resets local counters under a new namespace; controller launch/termination acknowledgements establish cross-process order. Scenario storage namespace remains unchanged. `wireTag=<processInstanceId>:refresh:<issuanceCommandId>` is unique diagnostic routing; wire request ID is a canonical decimal string and may repeat for a new managed owner. Do not carry allocator values across owners or serialize opaque slot authority.

## Task 0: Record baseline and prepare isolated working environment

**Files:** no product changes; fresh outputs under `reports/standalone/<attempt>/`.

**Interfaces:** consumes baseline commit and existing gates; produces captured toolchain/device inventory and baseline evidence with exact command records.

- [ ] Read repository instructions, design, this plan and final Claude/Fable review. Confirm intended executor/model/effort in run metadata; never infer unavailable provider cost/token statistics.
- [ ] Record `git status --short`, `git rev-parse HEAD`, `xcodebuild -version`, `swift --version`, `java -version`, `python3 --version`, `xcrun simctl list -j`, `adb devices -l`, `emulator -list-avds`. Handle sandbox/CoreSimulator permission errors as infrastructure issues, not proof that devices do not exist.
- [ ] Run baseline existing gate: `bash scripts/verify.sh "$PWD/reports/standalone/baseline-full"`. Expected future outcome: every required old gate succeeds and `report.md` begins `Overall: PASS`. Save command and raw log tail; if baseline fails, retain evidence and repair only within separately reviewed scope.
- [ ] Create an isolated worktree if needed using native workspace tooling/`using-git-worktrees`; preserve user changes. Do not copy prebuilt app artifacts into acceptance output.

**Gate:** baseline has recorded status; any existing failure is visible and cannot be hidden by new integration results. No new source is written before design approval/review is resolved.

## Task 1: Freezeable integration contract, model and independent checker

**Create:** `integration/__init__.py`, `contract.json`, `scenarios.json`, `control-scenarios.json`, `history.schema.json`, `model.py`, `check.py`, `fixtures/unsafe_adapter.py`, `tests/test_model.py`, `tests/test_check.py`.

**Interfaces:**

```python
def model.explore(*, output: Path, mutant: str | None = None) -> dict: ...
def check.check_trace(contract: dict, scenario: dict, trace: dict,
                     server_events: list[dict], ui_observations: list[dict]) -> dict: ...
# CLI: python3 -m integration.model --output DIR [--mutant NAME]
# CLI: python3 -m integration.check --contract FILE --scenarios FILE
#      --artifacts DIR --report FILE
# CLI: python3 -m integration.fixtures.unsafe_adapter --output DIR
```

`check_trace` produces exact keys `classification`, `scenarioId`, `violations`, `missingObservations`; each violation includes `invariant`, `commandRef` (`{processInstanceId,id}`), `eventRef` (`{processInstanceId,localSequence}`), `expected`, `actual`. CLI exits 0 PASS, 1 SEMANTIC_FAIL/INVALID_HISTORY, 2 INFRA_FAILURE, 3 INCONCLUSIVE. Report schema distinguishes INVALID_HISTORY from well-formed semantic mismatch. It never classifies every exit 1 as a valid RED.

- [ ] Write `test_stale_success_is_semantic_red`, `test_late_failure_preserves_new_login`, `test_missing_delivery_not_pass`, `test_wrong_run_or_duplicate_command_invalid`, `test_ui_ack_is_not_render_observation`, `test_unknown_storage_is_not_absent`, `test_out_of_order_publication_rejected`. Use hand-authored traces and exact scenario inventory, not candidate observations as expected values.
- [ ] Add `test_ignored_delivery_metadata_changes_without_auth_projection_change`, `test_process_restart_allows_local_id_reset_with_new_namespace`, `test_reused_process_instance_invalid`, `test_restart_exports_do_not_overwrite`, `test_incomplete_mutant_never_semantic_fail`. Compare UI revisions only inside one process; complete cross-launch histories must include controller launch/termination acknowledgements and each process's start/end-or-termination evidence.
- [ ] Run `python3 -m unittest integration.tests.test_check -v`; record expected initial failures due to missing checker/behavior. Implement strict shape, sequence/membership/provenance checks and independent invariant evaluation.
- [ ] Encode design §6 phase transitions and finite bounds, with symbolic reference identities and restart preserving physical store. Write `test_each_good_reachable_state_satisfies_invariants`, `test_unconditional_success_commit_mutant_has_I2_or_I4_witness`, `test_reentrant_consumer_mutant_has_I1_or_I3_witness`, `test_duplicate_deferred_clear_mutant_has_I4_witness`, `test_unverified_publish_mutant_has_I6_witness`, `test_failed_clear_ack_mutant_has_I8_witness`. The success mutant assigns `admittedSuccess = outcome.isSuccess`, bypassing both eligibility and managed acceptance; slot-guard-only removal is a nonrequired redundancy experiment. The clear mutant performs normal Logout clear first, then a duplicate deferred clear after Login B. Check actual counterexamples, not nonzero process status.
- [ ] Make every state component finite: at most six dequeued commands and twelve UI revisions per model execution, two managed-owner identities, three epoch identities and two request IDs per owner; do not wrap/reuse exhausted values. Three epochs permit Bootstrap → fault revocation → RetryCleanup. Reaching a generation bound disables further generation and permits terminal stuttering, reported as a coverage boundary rather than a liveness result; it does not simulate the separate native counter fail-stop policy. Store receipt history as bounded ghost summaries (`lastLogoutCompleted`, `postLogoutLoginCommitted`, slot commit bits), and store BFS predecessor/witness trace outside hashed model states. Observe is external projection/stutter, not a counted command. Require actual reachable witness paths for APP-02/03/04/05, duplicate delivery, paused-consumer queued Logout, fault/cleanup and restart with persisted credential followed by bootstrap cleanup; absence is INCONCLUSIVE. APP-04 has Bootstrap/Login A/Expire/Logout/Login B/Deliver old within the six-command bound. The combined fault/RetryCleanup/Login B/old-delivery sequence is native-test scope, not a claim under this model bound. Report all bounds and witnesses.
- [ ] Add static-contract regression tests to `integration/tests/test_model.py`: for both RefreshSucceeded/RefreshFailed, oracle states Unauthenticated/pending nil, Authenticated/pending nil and Refreshing/pending 2 with stale ID 1 must preserve the full triple/effects/rejection. Add same-number foreign-owner case in the native contract harness. This preserves the chosen policy of forwarding stale deliveries to managed `handle`; freeze the current JSON/source digests after this future test run. Do not change that policy silently.
- [ ] Implement a deterministic unsafe fixture that performs real managed-equivalent oracle steps, receives a valid stale no-op, then unconditionally records a credential write and auth publication from the old payload. Its trace must be structurally valid and violate APP-02/04. Label it an evaluator fixture, never a native app result.
- [ ] Run the checker/model tests and `python3 -m integration.model --output reports/standalone/model-draft`. Expected future outcomes: good finite exploration PASS; each named mutant has the intended concrete invariant counterexample. Preserve model limits and explored counts directly from generated output.

**Gate:** Astra/Claude review checks that invariants cover intermediate phases, no arbitrary native refinement is claimed, and RED is semantic rather than missing-app infrastructure.

## Task 2: Controllable real HTTP server and wire validation

**Create:** `integration/wire.py`, `server_state.py`, `server.py`, `tests/test_wire.py`, `tests/test_server.py`.

**Interfaces:**

```python
def wire.parse_refresh(body: bytes) -> dict: ...  # strict 16 KiB envelope
class ServerState:
    def create_run(self, scenario_id: str, platform: str, attempt_id: str) -> dict: ...
    def hold(self, request: dict) -> "PendingRequest": ...
    def release(self, run_id: str, request_tag: str, outcome: dict) -> dict: ...
    def pending(self, run_id: str) -> list[dict]: ...
    def events(self, run_id: str) -> list[dict]: ...
    def close_run(self, run_id: str) -> None: ...
# python3 -m integration.server --bind 127.0.0.1 --port 0 --output DIR
```

- [ ] Write tests using loopback `http.client` connections: `test_request_is_held_until_explicit_release`, `test_release_is_single_use_409`, `test_failure_and_disconnect_outcomes`, `test_duplicate_json_keys_rejected`, `test_signed64_decimal_id_exact`, `test_limits_413_and_capacity_429`, `test_wrong_control_key_403`, `test_close_run_unblocks_held_clients`.
- [ ] Run `python3 -m unittest integration.tests.test_wire integration.tests.test_server -v` for initial RED. Implement the exact routes and payloads in design §7, bounded queues and condition waits. No asyncio/web framework dependency.
- [ ] Implement server-owned body digests and event sequence. Redact `refreshToken`/access token/control keys from logs. Health endpoint contains no control capability. LAN binding requires explicit address and control header; localhost-only mode remains default.
- [ ] Atomically write `server-ready.json` after bind with `{version:1, bindAddress, port, pid}`; port is the actual bound ephemeral port. Extend server tests with `test_ephemeral_port_ready_metadata_matches_listener`. The controller waits for this fresh file and health check, never guesses a free port before bind.
- [ ] Implement the frozen metadata checkpoint bridge from design §7: control-key-protected POST `/control/runs/{runId}/checkpoints` body `{version:1,processInstanceId,name:"bootstrapStoreProbed"}` and read-only GET `/v1/checkpoints` with encoded run/process/name query returning `{version:1,ready:boolean}`. Other independent-probe checkpoints have names `storeProbe.<frozenStepId>` declared in scenario/control inventory; at most 32 entries/run. `POST /control/runs` includes `attemptId`; combine it with scenario inventory's allowed launchOrdinals (1, or 1/2 for APP-12) to validate exact process IDs. attemptId/scenarioId labels are ASCII alphanumeric/hyphen/underscore, length 1..64. Permit only declared names, idempotent same-checkpoint POST and bounded membership; never treat this as a refresh response. Add `test_checkpoint_is_process_scoped_and_cleared_with_run`, `test_checkpoint_publish_requires_control_key`, and `test_unknown_checkpoint_rejected`.
- [ ] Run the same tests; expected future PASS includes observation that no refresh bytes are returned before release and one response arrives after release. Use events with bounded waits; no arbitrary sleeps as ordering proof.

**Gate:** server never claims duplicate HTTP completion; native replay seam owns duplicate logical delivery. Controller release acknowledgement remains distinct from native receipt.

## Task 3: Package scaffolds, frozen harness/protocol and acceptance freeze

**Create:**

- `apps/ios-demo/NativeContractDemo.xcodeproj/project.pbxproj`, shared scheme `xcshareddata/xcschemes/NativeContractDemo.xcscheme`, `Config/Debug.xcconfig`, `Config/Release.xcconfig`, app `Info.plist` and empty composition root.
- `apps/android-demo/{settings.gradle.kts,build.gradle.kts,gradle.properties,gradlew,gradlew.bat}`, `gradle/wrapper/{gradle-wrapper.jar,gradle-wrapper.properties}`, `app/build.gradle.kts`, manifests/config resources, resolved lockfiles and `gradle/verification-metadata.xml`.
- Frozen scenario test paths from file ownership section, `integration/{controller.py,protocol_config.py,reproduce.py,toolchain.json,native-anchors.md,mutation_matrix.json,mutations.py}`, tests `test_{controller,protocol,mutations}.py`, `scripts/integration-verify.sh`, `.github/workflows/integration.yml`.
- Modify only additive protocol validation in `verification/change_protocol.py` and `verification/test_change_protocol.py`.

**Interfaces:**

```python
def controller.run_platform(platform: str, *, candidate: Path, output: Path,
                            device: str, scenarios: Path) -> dict: ...
def protocol_config.build_config(root: Path, output: Path, baseline: str) -> dict: ...
def reproduce.run(*, candidate: Path, output: Path, stages: list[str]) -> dict: ...
# integration.reproduce freeze --candidate PATH --output FRESH_DIR
# integration.reproduce run --candidate PATH --manifest FILE
#   --manifest-digest HEX --stage STAGE --attempt ID
# integration.reproduce check --candidate PATH --manifest FILE
#   --manifest-digest HEX --result FILE
# integration.reproduce stage --candidate PATH --stage STAGE --output FRESH_DIR
# integration.reproduce run-suite --candidate PATH --output FROZEN_DIR
```

The new wrapper delegates manifest/run/check binding to `verification.change_protocol`; it does not create a second weaker implementation. Supported stage IDs are fixed `integration-red`, `candidate-ios`, `candidate-android`, `integration-controls`, `legacy-full`. Add protocol `integration-comparator`, validator `integration-report`, exact command templates and semantic report shape validation. Report includes `classification`, `platformResults`, required scenario IDs, `violations`, device/build hashes, required artifact membership. Comparator exit 1 is SEMANTIC_FAIL only for complete valid observations with concrete violations. NOT_RUN, malformed evidence and infrastructure precedence are explicit; legacy `full-gate`/`async-comparator` unchanged.

`integration.reproduce stage` is the exact frozen integration-stage entry point used by the protocol template. It writes evaluator RED or an explicit platform NOT_RUN report into a fresh output directory; it never treats absent native runners as a semantic result.

`integration.reproduce run-suite` executes all five frozen stages serially and checks each saved result immediately. It accepts integration-red only when the bound unsafe fixture returns the named semantic witness; every native and legacy stage must PASS for the suite to PASS. `scripts/integration-verify.sh` requires a fresh explicit `RUN_ID` and the selected Python 3.12.8 interpreter.

- [ ] Write protocol tests first: `test_integration_exit_one_requires_semantic_report`, `test_missing_platform_not_pass`, `test_stale_artifact_rejected`, `test_changed_evaluator_invalidates_binding`, `test_changed_scenario_inventory_rejected`, `test_full_gate_legacy_verdict_unchanged`.
- [ ] Build minimal packaging shells solely to establish dependency resolution and local package/JVM-jar consumption. Missing coordinator behavior is explicitly NOT_RUN. Keep existing android root repositories/wrapper untouched; set included JVM project's build output under app build. Run exact preflight `./apps/android-demo/gradlew -p apps/android-demo :contract-async:jar` and record produced jar digest. Before freeze, statically check PBX `objectVersion=56`, `compatibilityVersion="Xcode 14.0"`, conventional groups, shared scheme and absence of `PBXFileSystemSynchronizedRootGroup`/synchronized-group exceptions; run local Xcode 27.1 `xcodebuild -list`, `-resolvePackageDependencies` and packaging build. A local Xcode 16.2 installation is not required to freeze. In `.github/workflows/integration.yml`, require explicit Xcode 16.2 `xcodebuild -list -project apps/ios-demo/NativeContractDemo.xcodeproj` and `xcodebuild -resolvePackageDependencies -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo` before app build/test; until that CI run, its compatibility result is NOT_RUN. Existing core CI success never substitutes for this new app-project preflight. Download/pin official wrapper checksum; write lock/verification metadata and `toolchain.json` with source URLs. Resolve exact CI actions SHAs and dedicated device creation/cleanup policy. Failed wiring is infrastructure failure requiring reviewed resolution; no automatic source copy/includeBuild/unbound-jar fallback or silent Xcode substitution.
- [ ] Fix app identities `dev.nativecontract.demo.ios` and `dev.nativecontract.demo.android`, with Debug tests installing only on owned devices. iOS Simulator build uses automatic/local simulator signing and no development team, no shared Keychain group/entitlement. Physical iOS signing supplies `DEVELOPMENT_TEAM` at execution; never commit a personal team ID or certificate. Android debug signing uses the normal local debug keystore, with no release signing key in the repository. Keychain production demo service remains `native-contract-demo.credentials`; Debug test service is `native-contract-demo.credentials.test.<attemptId>.<scenarioId>` and is held constant across that scenario's process restarts. Android test files likewise live under `noBackupFilesDir/demo-session/test-<attemptId>/<scenarioId>/`. App startup cannot switch namespaces mid-run; unit tests clean only their own suffix.
- [ ] Configure Gradle lockfiles at `apps/android-demo/gradle.lockfile`, `app/gradle.lockfile` and `gradle/contract-async.lockfile` (set the included project's lockfile location explicitly); never write a new lock/build artifact into existing `android/async-library/`. Wrapper and dependency verification metadata stay app-local and are frozen.
- [ ] Local Apple Silicon Android testing selects an API 35 `google_apis;arm64-v8a` image; Linux CI selects API 35 `google_apis;x86_64`. Create a unique AVD under controller-owned `ANDROID_AVD_HOME` in the attempt directory and record its image revision/ABI/serial/PID. Only this AVD may be stopped/deleted. iOS similarly records created device UUID and may delete only that owned device. Existing user AVDs and booted simulators are never reused by implicit default selection.
- [ ] Freeze runner interfaces/tests before candidate source: iOS uses XCUITest visible controls and accessible labels; Android uses Compose instrumentation tests. Both consume copied, hashed `integration/scenarios.json` or the separate frozen `control-scenarios.json`; expected outcomes originate there. Runner emits every declared command/observation and fails on missing methods/absent scenario. Native launch arguments configure endpoint, run ID, scenario path, processInstanceId/launchOrdinal and cancel mode; opaque slots never cross the launch boundary. Freeze iOS StorageProbe's independent SecItemCopyMatching implementation and Android host probe implementation in controller, including raw-byte-in-memory/redacted-output policy. The supplementary Android app probe is protected too. Enumerate exact candidate source directories/files without overlapping protected harness/probe files: list individual candidate Debug files, never whole `Debug/` directory or parent `apps/`.
- [ ] Implement controller using subprocess argv arrays and timeouts, not shell string interpolation. It starts/stops only its own server PID and dedicated device; records actual installed app hash, scenario digest, server events, native audit, UI observations/screenshots and test results. It never turns stale screenshots or prior-run trace files into current evidence. Record even failed attempts.
- [ ] Write controller tests with fake subprocess results: `test_missing_ui_evidence_not_pass`, `test_foreign_device_not_erased`, `test_server_exit_infra_failure`, `test_no_late_delivery_inconclusive_or_invalid`, `test_only_owned_processes_stopped`. Implement bounded polling on named barriers with explicit failure diagnostics.
- [ ] Add `test_app12_installs_once_and_never_pm_clears`, `test_instrumentation_exit_not_process_death_evidence`, `test_app12_new_process_namespace_keeps_store_namespace`, `test_bootstrap_probe_precedes_clear_release`, and `test_control_release_bypasses_paused_mailbox`. Freeze the exact Android per-launch argv protocol and DebugScenarioControl API below. p1 teardown exports checkpoint/end evidence without clearing credentials; controller force-stop/PID confirmation precedes p2 launch.
- [ ] Freeze an explicit per-process end handshake. Both harnesses call the Debug `finishProcess(timeoutMillis)` API after all declared receipts, probes, rendered views, screenshots, and control actions, then report its `ProcessEndAck` before final `phase=end`, test teardown, or artifact export. The call closes ingress, drains admitted auth work under the remaining runner deadline, refuses while any hook is paused or store/auth work is active, cancels only remaining physical transports after final observations, and ignores late callbacks. It neither submits an auth command nor changes command IDs, auth UI, or stored credentials. The recorder writes/syncs one terminal `processEnd`, seals its native stream, and caches the actual event reference; retries return the same ack. Android calls the application-owned control directly from instrumentation. iOS uses the panel action `finish-process` and reads `process-end-ack-json`; no lifecycle callback is a substitute. APP-07 may end with the second request held while preserving Refreshing/A; APP-12 p1 keeps its installed app and storage namespace. Add fake-collector/harness/controller/checker coverage and a schema-required controller acknowledgement bound to the terminal native row. Missing end evidence stays INCONCLUSIVE; mismatched/duplicate references or native records after processEnd are invalid.
- [ ] Freeze native mutation anchors described below, and validate substitutions against evaluator-owned exact snippets before runtime implementation. The candidate must implement those snippets; do not invent patch locations after seeing mutant results.
- [ ] Run protocol/controller/server/model tests and packaging preflight. Review all protected files. Write freeze manifest with baseline/source membership, app-only candidate paths excluding frozen harness, stage templates, old spec SHA and toolchain pins/locks. Existing protocol budgets count all stages in one ledger: set `maxAttempts=10`, `maxTotalSeconds=21600`, permitting at most two attempts for each of five stages; enforce the per-stage limit in the integration wrapper. Stage timeouts: integration-red 600s, candidate-ios 1800s, candidate-android 1200s, integration-controls 7200s, legacy-full 6600s. The platform budgets (iOS 1800s / Android 1200s) cover build + launch + all scenarios + export + checker; they are not per-scenario. Pre-freeze revision on 2026-10-13: measured local iOS scaffold plumbing extrapolates to approximately 894s across 25 launches, so iOS receives additional headroom for actual candidate scenario work. Android retains 1200s: its measured local scaffold launch overhead is much smaller and the CI preflight warms the same Gradle home. These measurements do not prove hosted or candidate timing; actual stages must meet their budgets. The global 21600s shared elapsed-time cap and attempt limits remain unchanged. Every subprocess/barrier deadline is capped by remaining stage budget. Retries consume the global budget and may be stopped as NOT_RUN. A timeout cannot be a semantic FAIL/PASS. The existing protocol runs ledger stages serially; separate CI platform checkouts may execute concurrently with independent manifests/output ledgers whose aggregate checks identical protected/source digests. Do not bypass its unfinished-attempt lock.
- [ ] Execute `integration-red` through the frozen protocol and bind result. Expected: SEMANTIC_FAIL for unsafe fixture with I2/I3 (APP-02) and I4 (APP-04). A report without these mismatches fails the gate. The original baseline has no app, so do not claim old-native integration RED.

**Gate:** review/freeze + semantic RED/binding complete before Tasks 4/5 candidate behavior. If a harness fix is needed later, refreeze/review/rerun RED first.

### Frozen DebugScenarioControl interface

Create the frozen Debug protocol/type files from the ownership list in Task 3; implement them in candidate `DefaultDebugScenarioControl` files in Tasks 4/5. `HookTarget` is `bootstrap | nextCommand | nextDelivery`. `StoreFaultKind` is `none | replaceBefore | replaceAfterBeforeVerify | clearBefore | clearAfterBeforeVerify`; an injected kind stays active for matching operations until `none`, without direct store mutation. HookPoint values are the complete list in Task 6, including `beforeBootstrapClear`.

```swift
protocol DebugScenarioControl: Sendable {
    func arm(_ point: HookPoint, target: HookTarget) throws -> ControlAck
    func awaitArrival(_ point: HookPoint, timeoutMillis: Int64) async throws -> HookObservation
    func release(_ point: HookPoint) throws -> ControlAck
    func replayLastCompletion() throws -> ControlAck
    func injectStoreFault(_ kind: StoreFaultKind) throws -> ControlAck
    func probeStore() async throws -> ProbeResult
    func snapshot() -> ControlSnapshot
    func finishProcess(timeoutMillis: Int64) async throws -> ProcessEndAck
}

struct ProcessEndEventReference: Codable, Sendable { let processInstanceId: String; let localSequence: Int64 }
struct ProcessEndAck: Codable, Sendable { let processInstanceId: String; let eventRef: ProcessEndEventReference }
```

```kotlin
interface DebugScenarioControl {
    fun arm(point: HookPoint, target: HookTarget): ControlAck
    fun awaitArrival(point: HookPoint, timeoutMillis: Long): HookObservation
    fun release(point: HookPoint): ControlAck
    fun replayLastCompletion(): ControlAck
    fun injectStoreFault(kind: StoreFaultKind): ControlAck
    fun probeStore(): CompletableFuture<ProbeResult>
    fun snapshot(): ControlSnapshot
    fun finishProcess(timeoutMillis: Long): ProcessEndAck
}

data class ProcessEndEventReference(val processInstanceId: String, val localSequence: Long)
data class ProcessEndAck(val processInstanceId: String, val eventRef: ProcessEndEventReference)
```

`ControlAck(actionId: Int64, controlRevision: Int64, status: applied|scheduled)` acknowledges control work only. `HookObservation(armSequence, point, phase: armed|arrived|released, target, arrivalCommandRef?)`; `armSequence` is the positive signed-64 `ControlAck.actionId` assigned at arm and remains unchanged at release. `ProbeResult(probeId, processInstanceId, observation: StoreObservation)`; `ControlSnapshot(version=1, processInstanceId, launchOrdinal, controlRevision, lastActionId?, lastActionStatus?, lastEnqueuedCommandRef?, lastProcessedCommandRef?, storeIoActive, hooks:[HookObservation], lastProbe:ProbeResult?)`. Snapshot retains each hook through `released`, once per point, in strictly increasing armSequence order; action sequence exhaustion never wraps. Explicit errors are `alreadyArmed`, `notArrived`, `alreadyReleased`, `noCapturedCompletion`, `probeNotSafe`, `processBusy`, `timeout`, `invalidArgument`.

Implementation uses a separate short lock/condition or async continuations. **Arm/release/awaitArrival/fault configuration/probe dispatch must not enter or wait on the auth mailbox.** They cannot hold their lock across await, MainActor/main-looper dispatch or Keychain/file I/O. `awaitArrival` is an independent signal wait; Kotlin callers use the instrumentation worker thread, never the main thread. The coordinator reports enqueue/arrival/store-I/O-idle/processed metadata to this control plane without awaiting a control consumer. Replay schedules the captured immutable completion through ordinary Deliver and returns `scheduled`; its actual command reference appears later in snapshot/normal receipt. The control plane never calls managed handle, writes/deletes credentials, or changes auth UI. Frozen probe access is allowed only when store I/O is idle and the consumer is quiescent or stopped at a declared safe barrier.

iOS panel IDs are `hook-target-bootstrap`, `hook-target-nextCommand`, `hook-target-nextDelivery`, `hook-arm-<point>`, `hook-release-<point>`, `hook-state-<point>`, `replay-last`, `fault-set-<kind>`, `probe-store`, `store-probe-result`, `control-status-json`, `last-enqueued-command-id`, `finish-process`, and `process-end-ack-json`. Target buttons select the next arm's target. `hook-state` encodes phase/arrival command reference; JSON labels expose the exact redacted structs above. Panel snapshot rendering is independent of auth revisions and remains live while coordinator is paused. XCUITest implements awaitArrival by polling the process-matched hook/control snapshot with the remaining stage timeout; it releases via the button, never an auth command. Android instrumentation obtains the Application's DebugScenarioControl and invokes these same methods directly; auth actions still use normal controls/submit paths.

### Process-end handshake

The protected harness calls `finishProcess` only after its final evidence capture. The API seals command/control ingress, waits for already-admitted auth work and store I/O to quiesce within its timeout, and returns `processBusy`/`timeout` without writing processEnd if a hook is paused or work remains unsettled. After observations are complete, it cancels any still-running physical transport and fences its callbacks before writing the terminal record; late callbacks cannot enqueue Deliver or emit native events. The recorder appends/synchronizes processEnd as the last native event, closes its write gate, and caches the event reference in `ProcessEndAck`. Repeating finish is idempotent and returns that identical cached reference.

Android `runScenario()` invokes `application.debugScenarioControl.finishProcess(remainingTimeoutMillis)` directly on the instrumentation worker, writes the ack to instrumentation evidence, and emits status `processEndAcknowledged` before `scenarioHarnessFinished`/`phase=end`. iOS captures all required probes, rendered views and screenshots, taps `finish-process`, waits for a process-bound `process-end-ack-json`, emits the same status/ack envelope, then emits final `phase=end`. The controller reads the native audit while the app is still alive, requires one final processEnd row matching the ack eventRef, records `processEndAcknowledged`, then exports and force-stops. The controller never creates the row. The checker requires one native row and one bound controller acknowledgement per launch, terminal event order, and acknowledgement after required receipts/probes and before controller teardown. Missing row/ack is INCONCLUSIVE; malformed/mismatched references and post-end rows are INVALID_HISTORY.

iOS startup argv pairs: `--scenario-id`, `--run-id`, `--process-instance-id`, `--launch-ordinal`, `--base-url`, optional `--arm <point>`, `--arm-target <target>`, `--store-fault <kind>`. Android uses corresponding instrumentation `-e` keys `scenarioId`, `runId`, `processInstanceId`, `launchOrdinal`, `baseUrl`, `armPoint`, `armTarget`, `storeFault`. Apply startup arms before `submit(Bootstrap)`. The frozen Android `DemoTestRunner : AndroidJUnitRunner` stores its arguments in `onCreate`, then overrides `callApplicationOnCreate(app)` to call `DebugDemoApplication.configureTestLaunch(config)` before `super.callApplicationOnCreate(app)`. The Debug application subclass creates its environment/control/coordinator from that immutable config in onCreate, exposes `debugControl`, and submits Bootstrap without blocking on its receipt. Configure-after-onCreate is rejected. Release DemoApplication never references a Debug-only type. `beforeBootstrapClear` has Booting UI and idle storage, pauses before first deletion, and can be released directly even though Bootstrap has no receipt yet. No credential/control key appears in argv or panel JSON.

### Frozen Android per-launch protocol

APP-12 is the family name; frozen concrete scenario IDs are `APP-12-SAVED` and `APP-12-LOGGED-OUT`. Each has exactly launchOrdinals 1/2 and its own scenario-scoped storage namespace. Other sections' APP-12 requirements apply to both; the seed action comes from that concrete inventory rather than an unspecified runtime choice.

Build once per platform candidate stage with `./apps/android-demo/gradlew -p apps/android-demo :app:assembleDebug :app:assembleDebugAndroidTest`; install `app/build/outputs/apk/debug/app-debug.apk` and `app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk` once on the owned emulator using `adb -s <serial> install -r <apk>`. Do not use a single `connectedDebugAndroidTest` task as evidence of all process-restart scenarios.

For each scenario launch, `controller.py` constructs this argv **array**, substituting strings without a shell:

```text
["adb","-s",serial,"shell","am","instrument","-w",
 "-e","class","nativecontract.demo.ScenarioInstrumentedTest#runScenario",
 "-e","scenarioId",scenarioId,"-e","runId",runId,
 "-e","processInstanceId",processInstanceId,"-e","launchOrdinal",ordinalString,
 "-e","baseUrl",baseUrl,"-e","scenarioPhase",phase,
 "dev.nativecontract.demo.android.test/nativecontract.demo.DemoTestRunner"]
```

APP-12 variants use `scenarioPhase=seed` in p1 (save A, or complete Logout), then `scenarioPhase=resume` in p2. p1 ends normally after writing a `restartCheckpoint` plus end marker and exporting artifacts, with **no credential cleanup in test teardown**. The controller then runs `["adb","-s",serial,"shell","am","force-stop","dev.nativecontract.demo.android"]` and polls `["adb","-s",serial,"shell","pidof","dev.nativecontract.demo.android"]` until no PID remains, recording command/exit/output. Instrumentation exit alone is insufficient. It invokes p2 with incremented namespace and adds `-e armPoint beforeBootstrapClear -e armTarget bootstrap` before the runner component. APKs and scenario storage remain installed/intact: no `pm clear`, reinstall or namespace deletion. Instrumentation calls `awaitArrival`, emits a process-scoped `INSTRUMENTATION_STATUS` checkpoint, and polls server `/v1/checkpoints` for `bootstrapStoreProbed`. The controller asynchronously reads that status while `am instrument` runs, obtains the authoritative physical store probe, persists only redacted output, and publishes the server checkpoint through the control-key-protected POST. On ready, instrumentation directly calls `release(beforeBootstrapClear)`, waits for Bootstrap receipt and final Absent/SignedOut, and exports p2 separately. This concrete bridge never requires an auth command behind Bootstrap or a raw credential/control-key file on the device. Configure `testInstrumentationRunner="nativecontract.demo.DemoTestRunner"`; Debug manifest selects `nativecontract.demo.debug.DebugDemoApplication`. This protocol also applies to any future declared multi-launch scenario.

For each APP-12 launch, final scenario observations precede `finishProcess`; the acknowledgement precedes the final `phase=end`. p1 finish does not stop the application or remove the shared scenario credential namespace, so the controller can confirm process death and launch p2 without `pm clear` or reinstall.

Use the same status → host probe → server checkpoint → native proceed handshake for every authoritative Android store probe, using `storeProbe.<frozenStepId>`. Instrumentation must not submit a later Login/RetryCleanup or release a paused store operation until its probe checkpoint is ready. Redacted status Bundle fields are `scenarioId`, `processInstanceId`, `checkpointName`, `phase="probeRequested"`; server ready is sent only after the host saved a redacted probe artifact. Missing status/probe/ready/release is incomplete evidence. This closes the timing gap between native receipts and host file reads for ordinary scenarios and mutation controls too.

## Task 4: Swift coordinator, Keychain and URLSession

**Create candidate files:**

```text
apps/ios-demo/NativeContractDemo/App/DemoEnvironment.swift
apps/ios-demo/NativeContractDemo/Coordinator/{DemoTypes,SessionCoordinator,RefreshSlot,ScenarioHooks,AuditRecorder}.swift
apps/ios-demo/NativeContractDemo/Storage/{CredentialStore,KeychainCredentialStore}.swift
apps/ios-demo/NativeContractDemo/Transport/{RefreshTransport,URLSessionRefreshTransport,RefreshWire}.swift
apps/ios-demo/NativeContractDemo/UI/{DemoViewModel,DemoView}.swift
apps/ios-demo/NativeContractDemo/Debug/{DemoIngress,DebugScenarioHooks,DefaultDebugScenarioControl,JSONLAuditRecorder}.swift
apps/ios-demo/NativeContractDemoTests/{CoordinatorTests,KeychainStoreTests,TransportTests}.swift
```

**Interfaces:**

```swift
actor SessionCoordinator {
    init(process: ProcessContext, store: any CredentialStore, transport: any RefreshTransport,
         publisher: any ViewPublisher, hooks: ScenarioHooks, audit: AuditRecorder)
    func submit(_ command: AppCommand) async -> CommandReceipt
}
protocol CredentialStore: Sendable {
    func readVerified() throws -> Credential?
    func replaceVerified(_ credential: Credential) throws
    func clearVerified() throws
}
protocol ViewPublisher: Sendable {
    @MainActor func publish(_ view: DemoViewState) async
}
protocol RefreshTransport: Sendable {
    func start(slot: RefreshSlot, credential: Credential,
               completion: @escaping @Sendable (Completion) -> Void) -> any TransportHandle
}
protocol TransportHandle: Sendable { func cancel() }
```

Use final immutable reference types for epoch/slot. The coordinator owns the only session and store instance. Store class is safe by sole-consumer ownership; any `@unchecked Sendable` justification is narrow and reviewed, never used to suppress mutable shared-state errors. URLSession callback closure only parses and enqueues. `ViewPublisher.publish` assigns state synchronously on MainActor before returning; it must not await any coordinator operation or launch a deferred auth update.

`ScenarioHooks` and `AuditRecorder` are app-internal protocols in the Coordinator directory, with no-op implementations available in every build. Debug implementations add barrier controls and JSONL output; Release composition injects no-op implementations and excludes `Debug/` sources. No production runtime source refers directly to a Debug-only concrete type. Swift protocol method `func pauseIfArmed(_ point: HookPoint) async` and Kotlin `fun pauseIfArmed(point: HookPoint)` name the same logical barrier. Read-only `StorageProbe` is frozen evaluator code from Task 3, not candidate code; use it only after a quiescent receipt/Observe or an explicitly paused transaction at a declared observation barrier, never concurrently with a store operation.

- [ ] Write `testLateSuccessAfterCompletedLogoutCannotWrite`, `testLateFailureAfterLoginBDoesNotClearB`, `testDuplicateCannotCommitTwice`, `testReentrantSubmitDuringManagedAwaitDoesNotDrainTwice`, `testQueuedLogoutWaitsForStoreAndPublication`, `testFailedClearReturnsFaultNotCompleted`, `testWriteThenReadbackFailureHidesAuth`, `testCancelledSubmitStillCompletesLogout`.
- [ ] Run app unit target with `xcodebuild test -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo -destination "platform=iOS Simulator,id=$IOS_SIMULATOR_UDID" -only-testing:NativeContractDemoTests -resultBundlePath "$OUT/swift-unit.xcresult"`. Initial RED must be recorded; do not count compiler failure as semantic negative-control evidence.
- [ ] Implement mailbox/drain algorithm from design §4: append continuation, set draining once, loop dequeue/execute/ack/resolve, and clear draining only when queue empty. Introduce deterministic Debug hook `await hooks.pauseIfArmed(.beforeStore/.beforePublish/.afterManaged)` within the existing consumer; while paused, actor reentry may only enqueue. No async child task applies effects. UI task cancellation does not cancel the coordinator's drain.
- [ ] Emit `commandEnqueued` and assign the command ID atomically with mailbox insertion. FIFO is the actual enqueue order, not an assumed order between independently scheduled Swift Tasks. APP-11 starts a submitted task, waits for its enqueued event, then starts the next submitted task without waiting for the paused command's receipt.
- [ ] Implement frozen DebugScenarioControl and panel IDs from Task 3 with a separate synchronization boundary; add `testReleaseUnblocksConsumerWhileAuthMailboxPaused`, `testControlSnapshotShowsEnqueueAndArrival`, `testProbeBeforeBootstrapDoesNotClear`, `testReplayOnlyEnqueuesCapturedDeliver`. Startup `beforeBootstrapClear` arm must precede Bootstrap submission; control snapshot publication must not await the auth publisher/receipt.
- [ ] Implement response eligibility from pre-state + exact slot/epoch identity, then call managed handle with original request. Set `admittedSuccess` once from complete eligibility/result predicate. Only its branch calls `store.replaceVerified(payload)` and publishes SignedIn. Stale branch checks unchanged triple/effects and records IgnoredStale. Fault path revokes slots/epoch and ensures locked publication.
- [ ] For IgnoredStale/IgnoredForeign and other terminal mutation/delivery outcomes, publish the same auth projection with a new local revision and final command ID/status, then return receipt. Observe alone remains read-only. Add `testIgnoredStalePublishesReceiptMetadataWithoutAuthChange`; lifecycle tests restart local IDs/revisions only under a new controller-supplied processInstanceId.
- [ ] Implement Keychain service/account/accessibility exactly as design §5, sync readback and idempotent delete; tests use dedicated test service suffixes and clean only owned items. Inject fail-before/fail-after wrappers; real Keychain smoke proves actual storage. Link frozen evaluator StorageProbe without editing it or sharing candidate decoding/query helpers.
- [ ] Implement ephemeral URLSession with redirect rejection, bounded response body, strict field validation, wire IDs as decimal strings, held-response timeout 75s and best-effort cancel. `DemoIngress` captures one decoded completion per issued slot and supports one replay via debug hook; all deliveries enqueue the original slot. Primary mode keeps HTTP alive after Logout.
- [ ] Wire SwiftUI UI and accessibility IDs: `login-A`, `login-B`, `expire`, `logout`, `retry-cleanup`, `session-state`, `credential-status`, `view-process-id`, `view-revision`, `last-command-id`, `last-command-status`. Use signed-out labels `Signed out`, `Credentials absent`; fault labels include `Cleanup failed`. No raw token text. Recreated view observes existing view model.
- [ ] Rerun unit tests, then frozen iOS scenario harness against real server. Expected future outcomes follow APP-01–14; any evaluator change returns to Task 3 freeze/RED, never adjust expectations inside this task.

**Gate:** Swift-specific review inspects await reentry, continuation cancellation, pending-result checks and OS storage error paths. Keep runtime build/test evidence separate from prior SwiftPM core results.

## Task 5: Kotlin coordinator, app-private store and platform HTTP

**Create candidate files:**

```text
apps/android-demo/app/src/main/java/nativecontract/demo/DemoApplication.kt
apps/android-demo/app/src/main/java/nativecontract/demo/MainActivity.kt
apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/{DemoTypes,SessionCoordinator,RefreshSlot,ScenarioHooks,AuditRecorder}.kt
apps/android-demo/app/src/main/java/nativecontract/demo/storage/{CredentialStore,AtomicFileCredentialStore}.kt
apps/android-demo/app/src/main/java/nativecontract/demo/transport/{RefreshTransport,UrlConnectionRefreshTransport,RefreshWire}.kt
apps/android-demo/app/src/main/java/nativecontract/demo/ui/{DemoViewModel,DemoScreen}.kt
apps/android-demo/app/src/debug/java/nativecontract/demo/debug/{DemoIngress,DebugScenarioHooks,DefaultDebugScenarioControl,JSONLAuditRecorder}.kt
apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugDemoApplication.kt
apps/android-demo/app/src/test/java/nativecontract/demo/{CoordinatorTest,TransportTest}.kt
apps/android-demo/app/src/androidTest/java/nativecontract/demo/AtomicFileStoreTest.kt
```

**Interfaces:**

```kotlin
class SessionCoordinator(process: ProcessContext, store: CredentialStore, transport: RefreshTransport,
    publisher: ViewPublisher, hooks: ScenarioHooks, audit: AuditRecorder) {
    fun submit(command: AppCommand): CompletableFuture<CommandReceipt>
}
interface CredentialStore {
    fun readVerified(): Credential?
    fun replaceVerified(credential: Credential)
    fun clearVerified()
}
interface ViewPublisher {
    fun publish(view: DemoViewState): CompletableFuture<Unit>
}
interface RefreshTransport {
    fun start(slot: RefreshSlot, credential: Credential,
              completion: (Completion) -> Unit): TransportHandle
}
interface TransportHandle { fun cancel() }
```

- [ ] Add matching behavior tests using latches/futures: `lateSuccessAfterCompletedLogoutCannotWrite`, `lateFailureAfterLoginBDoesNotClearB`, `duplicateCannotCommitTwice`, `nextCommandWaitsForMainPublicationAck`, `failedClearIsNotCompleted`, `writeThenReadbackFailureLocksUI`, `activityRecreationRetainsCoordinator`.
- [ ] Run `./apps/android-demo/gradlew -p apps/android-demo :app:testDebugUnitTest`; record initial RED. Add real AtomicFile read/replace/delete/readback tests to instrumentation target rather than using JVM Android stubs as evidence of storage.
- [ ] Implement sole single-thread executor transaction loop and dedicated HTTP executor. Future cancellation from a UI subscriber does not interrupt submitted cleanup. The main thread never calls `.get()`/`.join()` on command futures; the worker may wait for publication acknowledgement. Callback completion only submits a new command.
- [ ] Serialize the short command-ID assignment plus executor submission under one enqueue lock, emit `commandEnqueued` there, and release before any execution/I/O. APP-11 uses recorded enqueued events for command ordering; it does not infer order from racing future construction.
- [ ] Implement frozen DebugScenarioControl as an independent thread-safe control plane accessible through DemoApplication in Debug. Add `releaseBypassesPausedCoordinatorExecutor`, `snapshotExposesEnqueueAndArrival`, `bootstrapProbeBeforeClear`, `replayUsesNormalDeliver`. Main thread/control locks never wait for the coordinator worker; the instrumentation worker may wait for control arrival signals.
- [ ] Implement current-slot identity with `===`, full managed pre/post checks, same success branch and fault policy as Task 4. Copy the contract, not Swift implementation text. Reuse `nativecontract.async.ManagedAsyncSession` from project dependency; no Kotlin friend path or reflection.
- [ ] Publish ignored/foreign/rejected terminal command metadata with a fresh process-local revision while preserving auth projection. Add `ignoredStaleUpdatesReceiptMetadataOnly`. Observe is read-only; processInstanceId scopes revision/command IDs after process restart. Keep the frozen supplementary app StorageProbe untouched; authoritative Android storage evidence comes from the host controller.
- [ ] Implement `AtomicFile` with private no-backup namespace, `finishWrite`/`failWrite`, strict readback and sidecar-aware absence checking after delete; wrap errors into FaultLocked. Main manifest disables backup. Deletion never recursively touches unrelated files.
- [ ] Implement HttpURLConnection with redirects/cache disabled, 10s connect/75s read timeout, close streams/disconnect in finally, response-size validation and completion bound to original slot. Cancellation sets a best-effort stop signal/disconnect but does not change logical acceptance policy.
- [ ] Wire Application-owned view model/coordinator and Compose UI using same testTags/labels as Task 4. Main looper publication updates one immutable state then completes acknowledgement without calling coordinator. Activity recreation only reattaches. Debug instrumentation uses `ScenarioHooks`; release source excludes replay/fault controls.
- [ ] Run unit tests, build/install APKs once and execute frozen per-scenario/per-launch instrumentation through Task 3's controller protocol with dedicated `ANDROID_SERIAL`. Expected future outcome: real storage and complete frozen scenario inventory, including APP-12 separate p1/p2 launches, satisfy the checker. `connectedDebugAndroidTest` may be a separate single-process smoke check but cannot replace this acceptance protocol. Record device model/API, app hash and full native artifacts.

**Gate:** Kotlin review checks main/worker deadlock, no asynchronous `apply`, app-lifetime ownership, physical cancellation independence and distinct Gradle root/output paths.

## Task 6: Real app scenarios, independent observations and native negative controls

**Files:** candidate Debug hooks/audit/probe implementations from Tasks 4/5; frozen harness/anchors/scripts from Task 3 must not change without refreeze.

**Interfaces:** `ScenarioHooks` names are `beforeBootstrapClear`, `afterManaged`, `beforeStore`, `beforePublish`, `afterPublishAck`, `afterLogoutReceipt`, `ingressHeld`, `beforeDeferredControlClear`; each permits one arm/release and emits arm/arrive/release events. Use Task 3's exact DebugScenarioControl API/control snapshot; never expose hooks in the public library API or queue release behind a paused auth consumer. `StorageProbe.read()` is frozen iOS evaluator code using direct Keychain APIs; Android host-controller probe reads actual owned base/sidecar files. Both emit redacted `StoreObservation`, never cached UI values. `AuditRecorder` emits process-namespaced monotonically local-sequenced JSONL; flush completion marker before export to a per-launch path. APP-12 requires p1 checkpoint/end plus controller force-stop/PID-disappearance evidence; instrumentation exit is insufficient. Only a different future inventory explicitly declaring abrupt death may substitute controller-confirmed termination for native end marker; ordinary incomplete traces remain invalid.

- [ ] Implement APP-02/03 UI flow: tap Login A, tap Expire, wait server held request and native Refreshing, tap Logout, capture receipt plus immediate independent store probe before proceeding, release real HTTP, wait `transportReceived` plus matching `last-command-id/status` terminal metadata, then probe actual storage and capture rendered state at its new revision. Compare expected values after observation, so a wrong status is captured rather than waited for indefinitely. Primary acceptance requires successful Logout, SignedOut/Absent and IgnoredStale; assert cancellation-disabled mode in report.
- [ ] Implement APP-04/05 with Login B after Logout receipt and before release. Assert B0 remains in actual storage/UI and stale failure produces no clear. APP-06 explicitly labels one replay from recorded real completion rather than a second server response.
- [ ] APP-11 arm a transaction phase barrier, enqueue Logout then Login B, prove both pending and no later receipt/write/publication before releasing barrier; then require FIFO completion and final B. Swift barrier suspends via await without stopping enqueue; Android barrier blocks only coordinator worker while submissions remain accepted. Exercise pre-store and pre-publication variants.
- [ ] APP-09/10 fail-before/fail-after cases inspect real store separately from error receipt; accept Unknown when unreadable, never fake absence. APP-10 includes a separately named native variant `APP-10-RECOVER-OLD`: hold A refresh, failed Logout, probe, RetryCleanup, Login B, release old response, require foreign/stale ignored metadata and B preservation. This longer path is explicitly outside the six-command model coverage claim. RetryCleanup uses successful actual deletion/readback before enabling Login. APP-12 terminates/relaunches a dedicated app after storing A and after Logout; controller increments launchOrdinal/processInstanceId, preserves storage namespace, captures prelaunch artifacts before relaunch and never reconstructs old slots. Initial UI must be unauthenticated until bootstrap deletion. APP-14 recreates views/Activity without process death.
- [ ] Export audit JSONL and redacted storage probes into fresh process-namespaced artifacts. Both app audit recorders use `native-harness/<attemptId>/<scenarioId>/p<launchOrdinal>/native-events.jsonl`; Android instrumentation evidence is a separate `instrumentation-evidence.jsonl` with PNGs under that process directory's `screenshots/<frozenStepId>.png`. iOS XCUITest attaches screenshot/accessibility observation and uses the same audit path under app Documents (host resolves the app data container with `simctl get_app_container`); its frozen probe independently queries Keychain. Android audit files may be captured normally; credential-file `adb -s "$ANDROID_SERIAL" shell run-as <package> cat <relative-path>` output must stay in controller memory, be decoded/redacted and then discarded, never saved as generic subprocess stdout. Record only redacted account/version/absence/error and optional blob digest plus command/exit metadata; distinguish missing files from read errors and inspect owned AtomicFile sidecars. Never pull unrelated app data or log control keys. UI observations include processInstanceId/revision/requested/observed text; model publication alone cannot fill this file.
- [ ] Build/run each isolated native mutant using the frozen anchors below. Require a successfully launched app and named checker mismatch in its target scenario. Keep normal candidate source untouched. Run both platforms separately; negative result in one is not evidence for the other.

### Frozen native mutation contract

These anchors are design-required code shapes, protected in `integration/native-anchors.md` before candidates. The patcher checks exactly one match per language per mutant and records before/after hashes. Helper names are identical semantically across languages; expressions below are exact target lines. Mutants may need deliberate debug seam helpers, which live only in isolated copied test source, never normal runtime.

| Control | Swift anchor / Kotlin anchor | Replacement and semantic target |
|---|---|---|
| N1 stale payload commit | `let admittedSuccess = eligible && acceptedSuccess` / `val admittedSuccess = eligible && acceptedSuccess` | Replace with `let admittedSuccess = completion.outcome.isSuccess` / Kotlin equivalent. `acceptedSuccess` includes managed post-state/rejection. All actual success store+SignedIn publication lives inside this single branch. No second guard may silently mask this mutant. Complete CTRL-N1-LOGOUT must show post-Logout write/auth publication; CTRL-N1-NEW-LOGIN must show A replacing B. Library stale guard still works, demonstrating adapter escape. |
| N2 duplicate deferred clear | `try await clearThenPublishSignedOut(commandID: commandID)` / `clearThenPublishSignedOut(commandId)` | Replace with evaluator-owned `try await debugClearThenScheduleDuplicate(commandID: commandID)` / Kotlin equivalent in isolated copy. Helper performs the normal verified clear and SignedOut publication first, then schedules a detached duplicate old clear waiting at `beforeDeferredControlClear`, and returns. Controller waits for Logout receipt/probe Absent and successful Login B receipt/probe B, releases that hook, waits for actual duplicate-clear completion, then probes Absent. Initial deletion permits Login B; no forged absence or missing receipt is needed. Complete CTRL-N2-LATE-CLEAR must violate I4. |
| N3 unverified auth publication | `try store.replaceVerified(credential)` followed by exact `await publishSignedIn(credential, commandID: commandID)` / corresponding Kotlin pair inside refresh-success helper | Swap these two statements. `publishSignedIn` includes the normal evaluator `afterPublishAck` barrier. CTRL-N3-EARLY-PUBLISH arms this barrier for the current refresh completion and a fail-before-replacement wrapper; while paused, capture actual SignedIn version A1 and independent store A0, then release, receive terminal fault, probe and finish. I6 has a concrete credential-version/UI mismatch even if later fault hides authentication. Freeze full two-line snippets and whitespace after evaluator fixture validation. |
| N4 failed clear ACK | `return await lockAfterStoreFailure(error, commandID: commandID)` / `return lockAfterStoreFailure(error, commandId)` in unique Logout-clear catch helper | Replace with evaluator helper returning Completed after publishing SignedOut without successful clear. Complete CTRL-N4-FALSE-LOGOUT ends after that receipt and actual-store probe Present/Unknown, exposing I5/I8. Its inventory has no RetryCleanup, so forged Completed cannot prevent a required later step. This bypasses fault handling, not merely an ancillary error log. |

Do not weaken normal guards to make a mutant detectable. If compiler syntax or helper layout requires changing the frozen snippets, review/refreeze/rerun integration RED before using the revision. A native N1 failure must not be obtained solely by fabrication of audit events: actual store/UI actions are required and checked. N2/N4 helper sources are evaluator-owned isolated mutations and are compiled only for their negative-control builds.

Freeze these exact complete control inventories in Task 1/3, including Bootstrap and the initial store probe in each, with terminal end markers and all hook release/completion events:

| Inventory | Ordered actions after Bootstrap | Required forbidden observation |
|---|---|---|
| CTRL-N1-LOGOUT | Login A; Expire held; Logout; immediate store probe; release success; observe terminal delivery metadata; final store/UI probes; end | A credential/auth projection after completed Logout (I2/I3) |
| CTRL-N1-NEW-LOGIN | Login A; Expire held; Logout; immediate probe; Login B; probe B; release A success; terminal delivery metadata; final store/UI probes; end | A replaces B (I4) |
| CTRL-N2-LATE-CLEAR | Login A; Logout; immediate probe Absent; Login B; probe B; release duplicate-clear hook; observe duplicate-effect completion; final store/UI probes; end | prior Logout effect deletes B (I4) |
| CTRL-N3-EARLY-PUBLISH | Login A0; Expire held; arm persistent fail-before-replacement + afterPublishAck barrier for that delivery; release success A1; wait barrier; actual UI/independent-store probes; release barrier; terminal delivery fault receipt; final probes; end | SignedIn version A1 published while storage remains A0 (I6) |
| CTRL-N4-FALSE-LOGOUT | Login A; arm persistent fail-before-clear; Logout; capture any terminal receipt; immediate independent store/UI probes; end | Completed receipt while credential remains or absence unverified (I5/I8) |

Normal APP-10 still exercises RetryCleanup; its full inventory is not used for N4. All controls are independently named and protected before any candidate/mutant result exists. Add checker tests `test_complete_ctrl_n2_is_I4_semantic_fail`, `test_complete_ctrl_n4_is_I5_I8_semantic_fail`, `test_missing_control_end_or_probe_is_invalid`, and model-witness coverage for the duplicate-clear mutant. The checker validates full control inventory before semantic classification. It must never promote an arbitrary incomplete normal scenario to SEMANTIC_FAIL. The per-control mutation fixture establishes an illegal execution, not a claim that every possible duplicate/deferred-clear implementation is detected.

CTRL-N2's frozen inventory declares a detached `effectId` with `originCommandRef` naming its completed Logout. Trace shape/provenance accepts that reference even after return; effect execution order is checked semantically against I4. Missing/extra effects are invalid inventory, while the declared duplicate clear is a complete observable ordering violation. This separation prevents structural validation from swallowing the intended semantic witness. For CTRL-N3, the evaluator pauses the consumer after auth publication and before any store I/O, captures rendered credential version plus independent store version, then resumes to obtain the terminal receipt/end marker.

**Gate:** each target semantic mismatch is demonstrated, with actual source/binary hashes and app observations. No count or PASS claim without the current command and raw tail.

## Task 7: Frozen candidate runs, binding and full regression

**Files:** fresh evidence only; allowed candidate repairs follow frozen ownership. Final documentation updates are separate reviewed changes.

- [ ] Run each exact frozen stage via `integration.reproduce run`, including candidate iOS/Android, integration-controls and legacy-full, with a fresh attempt directory. Use `integration.reproduce check` to bind each recorded result immediately afterward. Expected future candidate result: PASS for required complete scenario inventory, not just process exit 0.
- [ ] Run original clean reproduction entry point in a clean candidate clone at its actual commit (if/when committing is separately authorized): `bash scripts/reproduce-evolution.sh --commit "$CANDIDATE_COMMIT" --output "$PWD/reports/standalone/legacy-reproduction"`. This retains original old-native v4 semantic RED and candidate full gate, independent of the new integration fixture. Before such commit authorization, working-copy mode is labeled precommit evidence, never clean-clone acceptance.
- [ ] Aggregate only bound valid stage results; require full old gates with mutations, integration finite model/control witnesses, actual iOS/Android scenarios, actual-store probes, rendered UI observations and per-language native controls. A missing simulator/emulator or unsuccessful server startup is infrastructure failure. Physical device smoke is labeled separately and may remain NOT_RUN without falsifying simulator/emulator results.
- [ ] Capture CI through separate integration workflow while retaining original verification workflow. Record resolved action SHAs, actual Xcode/SDK/runtime/Gradle/JDK versions and dependency manifest. An unavailable requested CI runtime requires a reviewed pin revision and fresh evidence.
- [ ] Request final Claude/Fable review of implemented candidate/evaluator boundary and any changed assumptions; resolve blocking findings, rerun affected frozen stages and binding. Never accept a reviewer opinion as test evidence.
- [ ] Produce implementation handoff/evidence listing exact commands and final raw log tails, scope of completed scenarios, limitations, current git status and artifacts. If any stage is NOT_RUN/INCONCLUSIVE, say so; do not label overall integration accepted.

**Completion criterion:** design §1 primary acceptance is observed on both native apps with real HTTP after successful Logout, real store absence and rendered logged-out UI; later-login isolation, ordering/fault/lifecycle scenarios and named controls meet frozen expectations; old full gates remain intact; every acceptance result is bound to its actual source and manifest. This plan itself establishes no such result.
