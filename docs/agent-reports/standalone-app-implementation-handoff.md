# Standalone native integration implementation handoff

**Checkpoint:** 2026-10-12, based on baseline `d2ce1847cb2644252f7c4d069ef9e36142bb327b`. Work was done in place because the sandbox denied creation of a Git worktree. No source was committed or pushed. The three pre-existing untracked design/review documents were preserved.

## Completed work

- **Task 0:** Recorded the environment and baseline. The restricted baseline attempt failed on sandbox networking/build permissions. The escalated `bash scripts/verify.sh "$PWD/reports/standalone/baseline-full-escalated"` completed with `Overall: PASS`; original source was unchanged. Device inventory could not access CoreSimulator/adb daemons in the restricted sandbox; API 35 ARM64 image was unavailable. Evidence is under `reports/standalone/task0/` and `reports/standalone/baseline-full-escalated/`.
- **Task 1 implementation:** Added the integration contract, full APP/control inventories, history schema, independent checker, finite bounded model, hand-authored traces, and evaluator-only unsafe adapter. The model CLI reached 13,495 states, returned `PASS`, and reported all required non-vacuity witnesses. Counterexample reports exist for the five named mutants. The unsafe fixture runs the actual managed reducer and then deliberately writes/publishes a stale payload: APP-02 reports I2/I3, and APP-04 reports I2/I4. These are evaluator fixtures, never native-app observations.
- **Task 2:** Added strict wire parsing, bounded synchronized server state, loopback HTTP server, atomic readiness metadata, release/fault injection, redacted event/digest output, and process-scoped checkpoints. Follow-up fixes make hold timeout terminal and record `responseWritten` after an actual flush. Request tags now require an owned process namespace and canonical positive signed64 issuance suffix, but the server does not restrict manual refreshes to the scripted Expire positions. The 8-request capacity test uses a test-only inventory that declares nine issuance commands.
- **Task 3 partial:** Extended `verification.change_protocol` additively with the fixed `integration-comparator` entry point and strict `integration-report` validation. The protocol freezes platform/scenario/variant trace bindings and per-control witness sets, checks their build hashes, and validates replayable baseline/mutant model reports. It rejects exit-1 PASS reports and malformed semantic reports, yields INCONCLUSIVE for missing platforms/scenarios/artifacts, and requires APP-02 I2+I3 plus APP-04 I4 for integration-red. Legacy async/full protocols retain their existing tests. The real unsafe `reproduce.stage` wrapper is exercised; a manifest-frozen `change_protocol.run` integration-red stage and manifest freeze have not been performed.

## Verification evidence

### Task 1 checker and model

Command: `python3.12 -m unittest integration.tests.test_check integration.tests.test_model -v` (exit 0). Raw final log tail:

```text
test_model_reports_finite_boundary_without_liveness_claim (integration.tests.test_model.BoundedIntegrationModelTests.test_model_reports_finite_boundary_without_liveness_claim) ... ok
test_reentrant_consumer_mutant_has_I1_or_I3_witness (integration.tests.test_model.BoundedIntegrationModelTests.test_reentrant_consumer_mutant_has_I1_or_I3_witness) ... ok
test_search_limit_never_claims_exhaustive_coverage (integration.tests.test_model.BoundedIntegrationModelTests.test_search_limit_never_claims_exhaustive_coverage) ... ok
test_unconditional_success_commit_mutant_has_I2_or_I3_witness (integration.tests.test_model.BoundedIntegrationModelTests.test_unconditional_success_commit_mutant_has_I2_or_I3_witness) ... ok
test_unverified_publish_mutant_has_I6_witness (integration.tests.test_model.BoundedIntegrationModelTests.test_unverified_publish_mutant_has_I6_witness) ... ok
test_equal_numeric_request_id_from_foreign_owner_is_ignored (integration.tests.test_model.StaticManagedOracleRegressions.test_equal_numeric_request_id_from_foreign_owner_is_ignored) ... ok
test_stale_responses_preserve_full_managed_triple_and_effects (integration.tests.test_model.StaticManagedOracleRegressions.test_stale_responses_preserve_full_managed_triple_and_effects) ... ok

----------------------------------------------------------------------
Ran 32 tests in 3.740s

OK
```

Command: `python3.12 -m integration.model --output reports/standalone/model-final` (exit 0). Raw output:

```text
{"classification": "PASS", "counterexample": null, "exploredStates": 13495, "missingCoverage": []}
```

Command: `python3.12 -m integration.fixtures.unsafe_adapter --output reports/standalone/unsafe-adapter` (exit 0). Raw output:

```text
{"evidenceKind": "evaluator-fixture", "scenarios": [{"actualClassification": "SEMANTIC_FAIL", "expectedClassification": "SEMANTIC_FAIL", "fixtureVerdict": "PASS", "observedInvariants": ["I2", "I3", "I7"], "requiredInvariants": ["I2", "I3"], "scenarioId": "APP-02"}, {"actualClassification": "SEMANTIC_FAIL", "expectedClassification": "SEMANTIC_FAIL", "fixtureVerdict": "PASS", "observedInvariants": ["I2", "I4", "I7"], "requiredInvariants": ["I2", "I4"], "scenarioId": "APP-04"}]}
```

### Task 2 server and wire

Command: `python3.12 -m unittest integration.tests.test_wire integration.tests.test_server -v` (escalated loopback-only run, exit 0). Raw final log tail:

```text
test_failure_and_disconnect_outcomes (integration.tests.test_server.ControllableHttpServerTests.test_failure_and_disconnect_outcomes) ... ok
test_hold_timeout_is_terminal_and_rejects_late_release (integration.tests.test_server.ControllableHttpServerTests.test_hold_timeout_is_terminal_and_rejects_late_release) ... ok
test_limits_413_and_capacity_429 (integration.tests.test_server.ControllableHttpServerTests.test_limits_413_and_capacity_429) ... ok
test_release_is_single_use_409 (integration.tests.test_server.ControllableHttpServerTests.test_release_is_single_use_409) ... ok
test_request_is_held_until_explicit_release (integration.tests.test_server.ControllableHttpServerTests.test_request_is_held_until_explicit_release) ... ok
test_request_tag_must_match_declared_process_and_issuance (integration.tests.test_server.ControllableHttpServerTests.test_request_tag_must_match_declared_process_and_issuance) ... ok
test_unknown_checkpoint_rejected (integration.tests.test_server.ControllableHttpServerTests.test_unknown_checkpoint_rejected) ... ok
test_wrong_control_key_403 (integration.tests.test_server.ControllableHttpServerTests.test_wrong_control_key_403) ... ok

----------------------------------------------------------------------
Ran 17 tests in 1.719s

OK
```

Command: `python3.12 reports/standalone/task2/server-cli-smoke.py` (escalated loopback-only smoke, exit 0). Raw output:

```text
{"cliPid": 85187, "health": {"ready": true, "version": 1}, "ready": {"bindAddress": "127.0.0.1", "pid": 85187, "port": 60657, "version": 1}}
```

Capacity diagnosis is captured in `reports/standalone/task2/capacity-root-cause.log`: Python `TCPServer.request_queue_size` was 5; the integration server now uses 64 and tests wait for explicit pending barriers.

### Task 3 protocol and regression suites

Command: `python3.12 -m unittest verification.test_change_protocol -v` (exit 0). Raw final log tail:

```text
test_missing_scenario_or_artifact_membership_is_inconclusive (verification.test_change_protocol.ChangeProtocolTests.test_missing_scenario_or_artifact_membership_is_inconclusive) ... ok
test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (verification.test_change_protocol.ChangeProtocolTests.test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch) ... ok
test_protected_edit_add_delete_and_out_of_scope_new_source (verification.test_change_protocol.ChangeProtocolTests.test_protected_edit_add_delete_and_out_of_scope_new_source) ... ok
test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze (verification.test_change_protocol.ChangeProtocolTests.test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze) ... ok
test_semantic_requires_report_and_native_mismatch (verification.test_change_protocol.ChangeProtocolTests.test_semantic_requires_report_and_native_mismatch) ... ok
test_stale_artifact_rejected (verification.test_change_protocol.ChangeProtocolTests.test_stale_artifact_rejected) ... ok
test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass (verification.test_change_protocol.ChangeProtocolTests.test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass) ... ok

----------------------------------------------------------------------
Ran 27 tests in 5.358s

OK
```

Command: `~/.local/bin/python3.12 -m unittest discover -s verification -p 'test_*.py' -v` (parent fresh run, exit 0). Raw final log tail:

```text
test_effect_order_is_compared_even_when_contract_bound_is_one (test_verification.TraceTests.test_effect_order_is_compared_even_when_contract_bound_is_one) ... ok
test_identical_malformed_native_traces_are_rejected (test_verification.TraceTests.test_identical_malformed_native_traces_are_rejected) ... ok
test_malformed_step_fields_are_rejected (test_verification.TraceTests.test_malformed_step_fields_are_rejected) ... ok
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests.test_oracle_preserves_ordered_effects_and_step_states) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests.test_schema_rejects_transition_missing_effects) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests.test_schema_rejects_unknown_keyword_instead_of_ignoring_it) ... ok
test_failed_builds_record_not_run_without_missing_log_warnings (test_verify_reporting.VerifyReportingTests.test_failed_builds_record_not_run_without_missing_log_warnings) ... ok

----------------------------------------------------------------------
Ran 123 tests in 13.528s

OK
```

Command: `~/.local/bin/python3.12 -m unittest discover -s integration/tests -p 'test_*.py' -v` (parent fresh run, exit 0). Raw final log tail:

```text
test_unknown_checkpoint_rejected (test_server.ControllableHttpServerTests.test_unknown_checkpoint_rejected) ... ok
test_wrong_control_key_403 (test_server.ControllableHttpServerTests.test_wrong_control_key_403) ... ok
test_duplicate_json_keys_rejected (test_wire.RefreshWireTests.test_duplicate_json_keys_rejected) ... ok
test_oversized_refresh_envelope_is_413 (test_wire.RefreshWireTests.test_oversized_refresh_envelope_is_413) ... ok
test_refresh_envelope_rejects_unknown_fields_and_token_mismatch (test_wire.RefreshWireTests.test_refresh_envelope_rejects_unknown_fields_and_token_mismatch) ... ok
test_signed64_decimal_id_exact (test_wire.RefreshWireTests.test_signed64_decimal_id_exact) ... ok
test_valid_envelope_preserves_decimal_request_id (test_wire.RefreshWireTests.test_valid_envelope_preserves_decimal_request_id) ... ok

----------------------------------------------------------------------
Ran 49 tests in 5.360s

OK
```

## Independent review and acceptance gate

At the original checkpoint, Task 1 had no usable independent review: the restricted CLI was unauthenticated and MCP Fable timed out. After the user completed `/login`, the fresh tools-disabled escalated CLI review completed and returned **FAIL / NOT READY**. Its full raw response, parsed JSON, bundle and actual model usage are preserved under `reports/standalone/task1/claude-review-refresh-*`. Do not treat the earlier authentication failure or timeout as a review disposition.

**Do not freeze the protocol or begin candidate Tasks 4/5 until the current findings are resolved and focused independent review approves the evaluator.** Task 3 now has protocol configuration, reproduce wrapper, controller primitives and an Android package/harness shell; a real iOS project, full runner, native app behavior, CI workflow, freeze manifest, candidate run and native acceptance remain incomplete or NOT_RUN. Tasks 4–7 candidate behavior remains unstarted.

Next action: fix the current variant/control checker gap and other Important findings in the implementation ledger, add the specified hand-authored regressions, then request a focused diff-and-fixture re-review. Do not run freeze or bind integration-red before that gate passes. Continue Tasks 3 and packaging preflight where they do not cross that boundary.

## Source snapshot

Current HEAD is unchanged from the baseline. The exact SHA-256 values for the implemented files and final test logs are in `reports/standalone/task3/implementation-source-hashes.json` (19 implementation files, 9 evidence logs). Source hashes:

| Path | SHA-256 |
|---|---|
| `integration/__init__.py` | `02662b3dbadc1aabae553dd8ea22704aedab9092d89b640df994ea156e8340d1` |
| `integration/check.py` | `85ba96651d5152db6238b36bf239f23a1d7f0e720ba13fc9ae16632df04c9292` |
| `integration/contract.json` | `31b232b3d100d86cf908acbc9c213a44426436a2d65e39d81818077653db6275` |
| `integration/control-scenarios.json` | `53fab3712d269fac2cd62583c395b85e45bf5d42fe9ee4e694b13b171105ff50` |
| `integration/fixtures/__init__.py` | `094b666ef6b8cbf269a5014b5c3e42e94b648e29133dfd0ff6839c6cc5c8033f` |
| `integration/fixtures/unsafe_adapter.py` | `5cdf5cbf80610a70a75528d957c4ec2d3b735db7c80cfdf2c76c81ec43250da7` |
| `integration/history.schema.json` | `e05a2b3a685b7c81c810448322a7f6700da4b5aba828308a084b24bc4fb2c06a` |
| `integration/model.py` | `9cf879ece2aada6eac44ef12fbd9d41875ad0cc43c0072f7e9fecee7b3e59aaa` |
| `integration/scenarios.json` | `ceca14bc1d4f6de12a74466081ea4f1315fad2c8325499fabe9d84b2d7f4f3fd` |
| `integration/server.py` | `6b43a31e44efc05580d667616544dcf45c651aacb9f7c5194baa5295e0b33b37` |
| `integration/server_state.py` | `a7eb0b88429084615fd7fbea99f168930a22a784a1f08737cacbc4489d6bf495` |
| `integration/tests/_history_fixtures.py` | `b4af87265c1314c311e9b230f74d05313775ec2594a0b8c910f9a30887c3bb4c` |
| `integration/tests/test_check.py` | `d9aa374cdddf614279fa03a675a8efb9979a6d9084399ea9dd978233b4022dd0` |
| `integration/tests/test_model.py` | `abce7b53aff7f9aa36447cc2c57bae4b0d2631993f33123d911d04d656d4aafb` |
| `integration/tests/test_server.py` | `2442c4dc8e261353b1d40b7e9c667ad2477145574b602aa26210babc5b5686c5` |
| `integration/tests/test_wire.py` | `be3f29f69eeb07ce012ad70f73fa8e6f5867adfb3462a5bcd044f0baaa811a84` |
| `integration/wire.py` | `25e614e4e3e35c0d14b904a5244fae3f0bd5b82cbc60ec297214f2c93079aaf5` |
| `verification/change_protocol.py` | `340604affabcfa19154133a91a7e272fd4ae3ec5f8bcc06ada96271058feaeb0` |
| `verification/test_change_protocol.py` | `62be4a53aaa5caf3e0b9b0aa31e24907b24bc9c26068ebd794abd5d75be60fca` |

The three design/review documents remain untracked and unchanged. Only explicit report paths under `reports/standalone/` were used for test logs and generated evidence. No Git staging, commit, or push was performed.

### Authenticated Fable result snapshot — 2026-10-12 (superseded source bytes)

The review used a tools-disabled CLI invocation with elevated sandbox access because the login session required Keychain/network access. It completed in 988.899 API seconds with exit 0, `is_error=false`, and actual model `claude-fable-5-1`. The model usage/cost is in `reports/standalone/task1/claude-review-refresh-metadata.json`. The disposition is **FAIL / NOT READY**, with 15 findings: two Critical, seven Important and six Minor. The review artifact is `reports/standalone/task1/claude-review-refresh-escalated.result.json`; `docs/agent-reports/standalone-app-fable-review-refresh.md` summarizes the finding set.

One Critical finding about checker-generated zero provenance was already stale at review time: the packet predates a positive-reference correction. The other Critical and the remaining findings applied to that reviewed source snapshot. The current remediation status is recorded in the continuation checkpoint below; none of those fixes is considered independently approved until a focused fresh review is available.

APP12 Android controller regressions and the Android Gradle 8.13 wrapper scaffold were added after the review snapshot. The adjacent `implementation-source-hashes.json` still describes older source bytes and is superseded. See `reports/standalone/execution-ledger.md` for current test commands and evidence. No source freeze or candidate implementation occurred.

## Authoritative continuation checkpoint — exact Python pin and review fixes (2026-10-12)

This section supersedes stale Task 1/2/3 status and source hashes above. The authenticated Fable review has **not** been rerun against these bytes, so freeze and candidate implementation remain blocked on focused independent review.

The checker now evaluates all scenario variants and five control inventories, enforces closed history/controller event schemas, requires a frozen mismatch invariant for every observation, validates APP-03/04/05 release/probe/receipt ordering, requires Bootstrap clear/readback in each process, and checks foreign owner, detached effect, failure code, UI acknowledgement, and command sequence evidence. The model now reports all observed mutant invariant families with replayable traces. Its reporter distinguishes finite-bound cutoffs and terminal revision/epoch behavior. `verification.change_protocol` binds per-platform scenario/variant trace selector rows, per-control expected witness sets, the bounded baseline model, and each named mutant report. Complete native reports must bind trace build hashes to the owning platform build hash. The real unsafe adapter is exercised through `integration.reproduce stage`; APP-02 reports I2/I3 and APP-04 reports I2/I4.

The server requestTag whitelist was removed after a scope check against design §7: the server accepts additional manual refresh issuances inside an owned process, with a unique canonical positive signed64 suffix, while enforcing process membership and duplicate rejection. This retains the request tag as diagnostic routing metadata and does not derive authority from it.

The exact Python3.12.8 runtime was installed under the owned reports tree with an owned `python3` PATH shim. The system `/usr/bin/python3` remains 3.9.6 and the previous explicit `~/.local/bin/python3.12` remains 3.12.9; neither is described as satisfying the acceptance pin. The exact interpreter SHA and local/CI separation are recorded in `integration/toolchain.json` and `reports/standalone/task3/parent-python-pin.json`.

Exact-pin verification command: `PATH="$PWD/reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest discover -s verification -p 'test_*.py' -v`; exit 0. Raw tail from `reports/standalone/task3/verification-full-python3128-attempt2.stdout.log`:

```text
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests.test_schema_rejects_unknown_keyword_instead_of_ignoring_it) ... ok
test_failed_builds_record_not_run_without_missing_log_warnings (test_verify_reporting.VerifyReportingTests.test_failed_builds_record_not_run_without_missing_log_warnings) ... ok

----------------------------------------------------------------------
Ran 124 tests in 12.860s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

Exact-pin full integration command required elevated permission only for the tests' ephemeral 127.0.0.1 binds: `PATH="reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest discover -s integration/tests -p 'test_*.py' -v`; exit 0. The latest full run is `reports/standalone/task3/integration-full-python3128-attempt6.stderr.log`:

```text
test_unknown_checkpoint_rejected (test_server.ControllableHttpServerTests.test_unknown_checkpoint_rejected) ... ok
test_wrong_control_key_403 (test_server.ControllableHttpServerTests.test_wrong_control_key_403) ... ok
test_duplicate_json_keys_rejected (test_wire.RefreshWireTests.test_duplicate_json_keys_rejected) ... ok
test_oversized_refresh_envelope_is_413 (test_wire.RefreshWireTests.test_oversized_refresh_envelope_is_413) ... ok
test_refresh_envelope_rejects_unknown_fields_and_token_mismatch (test_wire.RefreshWireTests.test_refresh_envelope_rejects_unknown_fields_and_token_mismatch) ... ok
test_signed64_decimal_id_exact (test_wire.RefreshWireTests.test_signed64_decimal_id_exact) ... ok
test_valid_envelope_preserves_decimal_request_id (test_wire.RefreshWireTests.test_valid_envelope_preserves_decimal_request_id) ... ok

----------------------------------------------------------------------
Ran 117 tests in 61.582s

OK
```

The separate stdout tail from `reports/standalone/task3/integration-full-python3128-attempt6.stdout.log` records the required real unsafe-fixture witnesses:

```text
{"evidenceKind": "evaluator-fixture", "scenarios": [{"actualClassification": "SEMANTIC_FAIL", "expectedClassification": "SEMANTIC_FAIL", "fixtureVerdict": "PASS", "observedInvariants": ["I2", "I3", "I7"], "requiredInvariants": ["I2", "I3"], "scenarioId": "APP-02"}, {"actualClassification": "SEMANTIC_FAIL", "expectedClassification": "SEMANTIC_FAIL", "fixtureVerdict": "PASS", "observedInvariants": ["I2", "I4", "I7"], "requiredInvariants": ["I2", "I4"], "scenarioId": "APP-04"}]}
```

Task 3 is still partial. The mutation matrix and copied-source patcher are present, but candidate source files and isolated N2/N4 helpers do not exist, so anchors have only been exercised against synthetic test sources. Variant test launches now receive unique platform/base-scenario/variant attempt IDs and variant-scoped artifact folders; APP-12 p1/p2 retain distinct process IDs but the same storage namespace. Native `Observe` is documented as a FIFO command with receipt and no UI publication; the bounded model alone treats its projection as stuttering, and current automated inventories remain unchanged. The CI preflight workflow exists but has not run in GitHub Actions. Parent local Xcode `-list`, package resolution and generic-simulator build succeeded; Android JAR/debug APK packaging succeeded. No app was installed or run on the owned devices. Native coordinator behavior, controller-driven scenario runners, evaluator review/freeze, candidate Tasks 4/5 and Tasks 6/7 acceptance remain pending. No commit or push was made.

The iOS package build command appears in the raw invocation header of `reports/standalone/task3/parent-ios-build.stdout.log`: `/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo -configuration Debug -sdk iphonesimulator -destination "generic/platform=iOS Simulator" -derivedDataPath reports/standalone/task3/parent-ios-deriveddata build CODE_SIGNING_ALLOWED=NO`. Its raw final line is `** BUILD SUCCEEDED **`. The separate list and resolve logs are `reports/standalone/task3/parent-ios-list.stdout.log` and `reports/standalone/task3/parent-ios-resolve.stdout.log`; these are local Xcode 27.1 results, not the pinned Xcode 16.2 CI run.

Android package command: `GRADLE_USER_HOME="$PWD/.gradle-home" ./apps/android-demo/gradlew -p apps/android-demo :contract-async:jar :app:assembleDebug`; parent evidence `reports/standalone/task3/parent-android-packaging-evidence.json` records exit 0. Raw final tail from `reports/standalone/task3/parent-packaging-final.stdout.log`:

```text
> Task :app:assembleDebug UP-TO-DATE

BUILD SUCCESSFUL in 889ms
39 actionable tasks: 39 up-to-date
```

The focused mutation patcher command on exact Python 3.12.8 was `PATH="$PWD/reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_mutations -v`; exit 0. Raw tail from `reports/standalone/task3/mutation-function-scope-final.stderr.log`:

```text
test_anchor_must_be_inside_the_declared_function (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_anchor_must_be_inside_the_declared_function) ... ok
test_each_mutation_writes_only_hash_bound_copied_sources (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_each_mutation_writes_only_hash_bound_copied_sources) ... ok
test_malformed_matrix_witness_values_are_rejected_as_protocol_data (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_malformed_matrix_witness_values_are_rejected_as_protocol_data) ... ok
test_mutation_witnesses_match_the_frozen_control_inventory (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_mutation_witnesses_match_the_frozen_control_inventory) ... ok
test_patch_refuses_existing_output_and_source_path_escape (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_patch_refuses_existing_output_and_source_path_escape) ... ok
test_patch_requires_exactly_one_anchor_match_before_writing (integration.tests.test_mutations.IsolatedMutationPatcherTests.test_patch_requires_exactly_one_anchor_match_before_writing) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.036s

OK
```

The Observe/variant namespace regressions ran on exact Python 3.12.8: `PATH="$PWD/reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_controller.VariantCaseNamespaceTests integration.tests.test_protocol.ProtocolConfigurationTests.test_native_observe_is_fifo_command_but_not_in_current_automated_inventories -v`; exit 0. Raw final tail from `reports/standalone/task3/observe-variant-namespaces-green.stderr.log`:

```text
test_frozen_variant_cases_have_unique_attempt_process_and_artifact_namespaces (integration.tests.test_controller.VariantCaseNamespaceTests.test_frozen_variant_cases_have_unique_attempt_process_and_artifact_namespaces) ... ok
test_nonvariant_app12_restarts_keep_one_case_storage_namespace (integration.tests.test_controller.VariantCaseNamespaceTests.test_nonvariant_app12_restarts_keep_one_case_storage_namespace) ... ok
test_native_observe_is_fifo_command_but_not_in_current_automated_inventories (integration.tests.test_protocol.ProtocolConfigurationTests.test_native_observe_is_fifo_command_but_not_in_current_automated_inventories) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.003s

OK
```

The CI workflow and toolchain contract test used exact Python 3.12.8: `PATH="$PWD/reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_protocol.ProtocolConfigurationTests.test_ci_workflow_pins_actions_and_checks_xcode_project_before_build integration.tests.test_protocol.ProtocolConfigurationTests.test_toolchain_record_separates_acceptance_pins_from_local_mismatches -v`; exit 0. Raw tail from `reports/standalone/task3/ci-workflow-contract.stderr.log`:

```text
test_ci_workflow_pins_actions_and_checks_xcode_project_before_build (integration.tests.test_protocol.ProtocolConfigurationTests.test_ci_workflow_pins_actions_and_checks_xcode_project_before_build) ... ok
test_toolchain_record_separates_acceptance_pins_from_local_mismatches (integration.tests.test_protocol.ProtocolConfigurationTests.test_toolchain_record_separates_acceptance_pins_from_local_mismatches) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.001s

OK
```

After the full integration run, `integration/toolchain.json` was updated to record its PASS status. This exact-pin consistency check then passed: `PATH="$PWD/reports/standalone/task3/parent-toolchain-bin:$PATH" reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_protocol.ProtocolConfigurationTests.test_toolchain_record_separates_acceptance_pins_from_local_mismatches -v`; raw tail at `reports/standalone/task3/toolchain-final-consistency.stderr.log`:

```text
test_toolchain_record_separates_acceptance_pins_from_local_mismatches (integration.tests.test_protocol.ProtocolConfigurationTests.test_toolchain_record_separates_acceptance_pins_from_local_mismatches) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

The workflow YAML parse command was `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/integration.yml"); puts "YAML parse OK"'`; its raw output was `YAML parse OK`. The workflow itself and pinned CI runtimes remain unexecuted.

## Continuation — N2 completion barrier and APP-10 command label (2026-10-12)

The N2 control now has an explicit `awaitDetachedEffect(late-clear-1)` action after the deferred-clear hook release. Both native harnesses submit a typed host wait request, and the controller publishes its checkpoint only after the live process audit stream contains the matching detached mutation and readback. The controller event `detachedEffectAwaited` binds the effect ID, Logout origin, and exact mutation/readback event references. The checker rejects missing acknowledgements as INCONCLUSIVE, rejects bad references/origins as INVALID_HISTORY, and requires release → acknowledgement → final physical probe order. The checkpoint is added to the HTTP server’s frozen allowed set from `controlActions`; arbitrary effect names remain rejected.

APP-10-RECOVER-OLD retains `Logout(failed)` as a frozen test-action label for an ordinary Logout with a declared clear fault. The harness uses the real Logout control and applies the actual wrapper fault. Native command records retain canonical `Logout`; the checker applies one explicit inventory label mapping for sequence, receipt, probe, and fault matching. This preserves native event provenance and does not add a second command kind.

Exact Python 3.12.8 focused N2 checker/controller/config command, exit 0: `PYTHONDONTWRITEBYTECODE=1 reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_check.IndependentCheckerTests.test_control_n2_detached_effect_has_independent_origin_provenance integration.tests.test_check.IndependentCheckerTests.test_control_n2_missing_declared_effect_is_inconclusive integration.tests.test_check.IndependentCheckerTests.test_control_n2_requires_a_host_ack_after_matching_effect_readback integration.tests.test_check.IndependentCheckerTests.test_control_n2_effect_ack_must_reference_its_actual_readback integration.tests.test_controller.NativeStatusStreamTests.test_effect_wait_status_requires_references_and_host_ack_binds_live_readback integration.tests.test_protocol.ProtocolConfigurationTests.test_inventory_freeze_validation_rejects_unknown_scenario_and_control_fields -v`. Raw tail from `reports/standalone/task3/detached-effect-ack-targeted-attempt1.stderr.log`:

```text
test_control_n2_detached_effect_has_independent_origin_provenance (integration.tests.test_check.IndependentCheckerTests.test_control_n2_detached_effect_has_independent_origin_provenance) ... ok
test_control_n2_missing_declared_effect_is_inconclusive (integration.tests.test_check.IndependentCheckerTests.test_control_n2_missing_declared_effect_is_inconclusive) ... ok
test_control_n2_requires_a_host_ack_after_matching_effect_readback (integration.tests.test_check.IndependentCheckerTests.test_control_n2_requires_a_host_ack_after_matching_effect_readback) ... ok
test_control_n2_effect_ack_must_reference_its_actual_readback (integration.tests.test_check.IndependentCheckerTests.test_control_n2_effect_ack_must_reference_its_actual_readback) ... ok
test_effect_wait_status_requires_references_and_host_ack_binds_live_readback (integration.tests.test_controller.NativeStatusStreamTests.test_effect_wait_status_requires_references_and_host_ack_binds_live_readback) ... ok
test_inventory_freeze_validation_rejects_unknown_scenario_and_control_fields (integration.tests.test_protocol.ProtocolConfigurationTests.test_inventory_freeze_validation_rejects_unknown_scenario_and_control_fields) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.006s

OK
```

Exact loopback checkpoint regression (elevated only because the sandbox denies local socket binds), exit 0: `PYTHONDONTWRITEBYTECODE=1 reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest integration.tests.test_server.ControllableHttpServerTests.test_detached_effect_checkpoint_is_declared_only_for_its_frozen_control -v`; raw tail from `reports/standalone/task3/detached-effect-checkpoint-targeted.stderr.log`:

```text
test_detached_effect_checkpoint_is_declared_only_for_its_frozen_control (integration.tests.test_server.ControllableHttpServerTests.test_detached_effect_checkpoint_is_declared_only_for_its_frozen_control) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.519s

OK
```

The exact-pin full integration suite, including the N2 and APP-10 regressions, completed with exit 0 under an unsandboxed test run because these tests bind loopback sockets. Command: `PYTHONDONTWRITEBYTECODE=1 reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest discover -s integration/tests -p 'test_*.py' -v`. Raw tail from `reports/standalone/task3/integration-n2-alias-final-attempt1.stderr.log`:

```text
test_wrong_control_key_403 (test_server.ControllableHttpServerTests.test_wrong_control_key_403) ... ok
test_wrong_correlation_writes_valid_success_payload_with_wrong_echo (test_server.ControllableHttpServerTests.test_wrong_correlation_writes_valid_success_payload_with_wrong_echo) ... ok
test_duplicate_json_keys_rejected (test_wire.RefreshWireTests.test_duplicate_json_keys_rejected) ... ok
test_oversized_refresh_envelope_is_413 (test_wire.RefreshWireTests.test_oversized_refresh_envelope_is_413) ... ok
test_refresh_envelope_rejects_unknown_fields_and_token_mismatch (test_wire.RefreshWireTests.test_refresh_envelope_rejects_unknown_fields_and_token_mismatch) ... ok
test_signed64_decimal_id_exact (test_wire.RefreshWireTests.test_signed64_decimal_id_exact) ... ok
test_valid_envelope_preserves_decimal_request_id (test_wire.RefreshWireTests.test_valid_envelope_preserves_decimal_request_id) ... ok

----------------------------------------------------------------------
Ran 194 tests in 16.668s

OK
```

Updated Android instrumentation and iOS UI harness sources compile. Android command: `GRADLE_USER_HOME="$PWD/.gradle-home" ./apps/android-demo/gradlew -p apps/android-demo :contract-async:jar :app:assembleDebug :app:assembleDebugAndroidTest`; exit 0, raw tail in `reports/standalone/task3/n2-effect-handshake-android-build.stdout.log` ends `BUILD SUCCESSFUL in 1s` and `69 actionable tasks: 7 executed, 62 up-to-date`. iOS command: `xcodebuild -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath "$PWD/reports/standalone/task3/n2-effect-handshake-ios-deriveddata" -parallel-testing-enabled NO build-for-testing CODE_SIGNING_ALLOWED=NO`; exit 0, raw tail in `reports/standalone/task3/n2-effect-handshake-ios-build.stdout.log` ends `** TEST BUILD SUCCEEDED **`. These are compile checks only; no N2 copied-mutant app was built or executed.

The prior authentic Fable review remains NOT_READY, and these source/input hashes postdate that packet. No new manifest freeze or fresh Fable review has been completed. Candidate Task 4/5 behavior, copied-mutation app linkage/runtime witnesses, and hosted CI acceptance remain NOT_RUN. Parent must review the fresh protected-input manifest before any candidate behavior or acceptance claim.

The full exact-pin verification suite was rerun after these changes: `PYTHONDONTWRITEBYTECODE=1 reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest discover -s verification -p 'test_*.py' -v`; exit 0. Raw tail from `reports/standalone/task3/verification-n2-alias-final-attempt1.stderr.log`:

```text
test_effect_order_is_compared_even_when_contract_bound_is_one (test_verification.TraceTests.test_effect_order_is_compared_even_when_contract_bound_is_one) ... ok
test_identical_malformed_native_traces_are_rejected (test_verification.TraceTests.test_identical_malformed_native_traces_are_rejected) ... ok
test_malformed_step_fields_are_rejected (test_verification.TraceTests.test_malformed_step_fields_are_rejected) ... ok
test_oracle_preserves_ordered_effects_and_step_states (test_verification.TraceTests.test_oracle_preserves_ordered_effects_and_step_states) ... ok
test_schema_rejects_transition_missing_effects (test_verification.TraceTests.test_schema_rejects_transition_missing_effects) ... ok
test_schema_rejects_unknown_keyword_instead_of_ignoring_it (test_verification.TraceTests.test_schema_rejects_unknown_keyword_instead_of_ignoring_it) ... ok
test_failed_builds_record_not_run_without_missing_log_warnings (test_verify_reporting.VerifyReportingTests.test_failed_builds_record_not_run_without_missing_log_warnings) ... ok

----------------------------------------------------------------------
Ran 127 tests in 14.809s

OK
```

The separately installed iOS runtime-gate tests still pass under the same interpreter: `PYTHONDONTWRITEBYTECODE=1 reports/standalone/task3/parent-python/cpython-3.12.8-macos-aarch64-none/bin/python3.12 -m unittest discover -s apps/ios-demo/scripts -p 'test_*.py' -v`; exit 0. Raw tail from `reports/standalone/task3/runtime-gate-n2-alias-final.stderr.log`:

```text
test_valid_json_with_wrong_inventory_shape_does_not_trigger_acquisition (test_prepare_ci_runtime.MalformedInventoryEnvelopeTests.test_valid_json_with_wrong_inventory_shape_does_not_trigger_acquisition) ... ok
test_download_without_exact_available_runtime_is_infra (test_prepare_ci_runtime.RuntimeAcquisitionTests.test_download_without_exact_available_runtime_is_infra) ... ok
test_exact_runtime_is_acquired_then_verified (test_prepare_ci_runtime.RuntimeAcquisitionTests.test_exact_runtime_is_acquired_then_verified) ... ok
test_wrong_xcode_fails_without_download (test_prepare_ci_runtime.RuntimeAcquisitionTests.test_wrong_xcode_fails_without_download) ... ok
test_malformed_inventory_is_infra_and_never_selects_default (test_prepare_ci_runtime.RuntimeFailureTests.test_malformed_inventory_is_infra_and_never_selects_default) ... ok
test_nonzero_xcode_is_infra_and_never_downloads (test_prepare_ci_runtime.RuntimeFailureTests.test_nonzero_xcode_is_infra_and_never_downloads) ... ok
test_timeout_is_infra_and_preserves_partial_command_output (test_prepare_ci_runtime.RuntimeFailureTests.test_timeout_is_infra_and_preserves_partial_command_output) ... ok

----------------------------------------------------------------------
Ran 10 tests in 0.275s

OK
```
