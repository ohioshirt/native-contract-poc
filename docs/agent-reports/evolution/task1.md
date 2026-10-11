# Task 1: frozen change protocol

Status: implemented; ready for independent protocol review before experiment freeze. No manifest for the actual experiment has been created, and no native candidate or old-native semantic RED was run by this task. No staging or commits.

## Owned changes

- `verification/change_protocol.py`: stdlib freeze/check/run CLI, authoritative manifest digest, reviewed working-copy inventory, exact candidate digest, protected membership/content, explicit native allowances and generated/evidence exclusions, narrow protected exceptions, known named-stage entry points, fresh artifact shape/hash verification, bound result records, raw subprocess logs, timeout/process-group handling, shared attempt/time budgets and collision-safe ledger ownership.
- `verification/test_change_protocol.py`: real temporary Git trees and real subprocess controls covering success, protected edits/additions/deletions, out-of-scope source, candidate/result/artifact mismatch, metadata nulls, semantic mismatch classification, native infrastructure/not-run, missing/malformed/stale artifacts, timeout/signal/nonzero, full-gate incomplete/aggregate failures, collisions, budgets, symlinks and CLI/freeze override rejection.
- `scripts/change-protocol.sh`: repository entry wrapper.
- `docs/experiments/change-protocol.md`: complete CLI/schema, old-native RED/full-stage examples, source validity/acceptance conditions and evidence/budget/revision conventions.
- This handoff report; raw evidence under `reports/evolution/task1/`.

The normative R1 implementation freezes only known async comparator and full gate entry points, rather than trusting arbitrary exit-zero commands. `requiredArtifacts` must contain the known primary report; unrelated verdict validators cannot replace it. Narrow `protectedPaths` exceptions can protect `reports/evolution/baseline-native/` and the controller's hash mapping inside normally ignored evidence trees. All source membership is compared to the reviewed freeze snapshot, not baseline HEAD alone.

## Exact commands and raw evidence

Commands were run from `/Users/shigeo/.codex/worktrees/b195/native-contract-poc`. Write/test invocations used authorized `require_escalated` execution for this managed worktree. Test output is retained verbatim; no aggregate counts have been computed.

Initial RED before production implementation:

```sh
python3 -m unittest verification.test_change_protocol -v > reports/evolution/task1/red.log 2>&1
tail -n 10 reports/evolution/task1/red.log
```

```text
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 18, in setUp
    self.assertIsNotNone(protocol, 'the frozen change protocol must exist')
AssertionError: unexpectedly None : the frozen change protocol must exist

----------------------------------------------------------------------
Ran 11 tests in 0.001s

FAILED (failures=11)
```

Self-review regression RED before rejecting ambiguous verdict artifact selection:

```sh
python3 -m unittest verification.test_change_protocol.ChangeProtocolTests.test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze -v > reports/evolution/task1/red-primary.log 2>&1
tail -n 10 reports/evolution/task1/red-primary.log
```

```text
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 185, in test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze
    with self.assertRaises(protocol.ProtocolError): protocol.freeze(self.root,config,self.manifest)
AssertionError: ProtocolError not raised

----------------------------------------------------------------------
Ran 1 test in 0.246s

FAILED (failures=1)
```

Final owned targeted test command:

```sh
python3 -m unittest verification.test_change_protocol -v > reports/evolution/task1/targeted-final.log 2>&1
tail -n 10 reports/evolution/task1/targeted-final.log
```

```text
test_manifest_result_and_artifact_digest_mismatch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_protected_edit_add_delete_and_out_of_scope_new_source (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_semantic_requires_report_and_native_mismatch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass (verification.test_change_protocol.ChangeProtocolTests) ... ok

----------------------------------------------------------------------
Ran 11 tests in 3.644s

OK
```

The initial implementation run (`green-initial.log`) exposed test temporary-root aliasing (`/var` versus canonical `/private/var`). The fixture root was resolved, its repeated manifest revisions received separate ledger roots, and cache exclusions were corrected to yield precedence only to explicit protected exceptions. The subsequent targeted run is retained in `green-second.log`; the final targeted result above supersedes it.

One broader Python suite was already started while other agents were editing. This is an **in-progress workspace snapshot**, not final branch validation. The controller instructed no further whole-suite runs until concurrent work settles.

```sh
python3 -m unittest discover -s verification -p 'test_*.py' -v > reports/evolution/task1/python-suite.log 2>&1
tail -n 10 reports/evolution/task1/python-suite.log
```

```text
AssertionError: 0 != 1

----------------------------------------------------------------------
Ran 93 tests in 7.343s

FAILED (failures=8)
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

The named unittest failures were all `test_all_native_patch_sites_are_unique` in `test_async.AsyncNativeMutationAnchorTests`, at these native cases (still deferred at this snapshot):

- `swift-ignores-refreshing-logout`
- `swift-omits-logout-clear-credentials`
- `swift-retains-logout-pending`
- `swift-resets-refreshing-logout-counter`
- `kotlin-ignores-refreshing-logout`
- `kotlin-omits-logout-clear-credentials`
- `kotlin-retains-logout-pending`
- `kotlin-resets-refreshing-logout-counter`

The formal-verification lines in the tail are diagnostics printed by existing negative-control tests; they are not additional unittest failure names. The full raw output is retained, and the final whole branch gate remains the controller's task.

Also inspected CLI help with `bash scripts/change-protocol.sh --help`; no actual freeze/run occurred outside the isolated test fixtures.

## Interface and rulings

Exact schema/usage is in `docs/experiments/change-protocol.md`, sent to the controller before handoff.

- `freeze --candidate ABS --config JSON --manifest ABS`
- `check --candidate ABS --manifest ABS --manifest-digest SHA [--result ABS]`
- `run --candidate ABS --manifest ABS --manifest-digest SHA --stage ID --attempt ID [--metadata JSON]`

Ruling: support only the two known evaluator protocols/entry points — R1 requires a meaningful stage report and prohibits arbitrary commands producing apparent PASS — future evaluator entry points require a reviewed protocol/manifest revision.

Ruling: positive timeout and total duration budgets are shared across named-stage executions, with global reserved-attempt count — keeps a minimal composable ledger and controller already accepted this convention — controller must budget RED/full runs separately from the plan's five native repair rounds.

Ruling: generated output exclusions use explicit relative file/subtree paths, without glob interpretation — source membership must remain auditable — controller must enumerate any additional generated trees before freeze.

Ruling: authoritative manifests and attempt directories are never overwritten; crashes preserve reserved directories and block the same ledger — prevents stale/reused evidence — controller investigates and creates a new reviewed revision if needed.

## Limits and remaining work

Independent Task 1 review and combined evaluator review are still required before actual freeze. The controller owns the authoritative digest, baseline provenance/toolchain evidence, final exclusions, stage budgets, five-repair cap, superseded-record invalidation and final branch gate.

`check --result` verifies a completed substantiated verdict against current sources and artifacts; infrastructure attempts with missing/malformed artifacts remain infrastructure failures. The guard is intended for cooperative local execution. It does not authenticate provider metrics or defend against rewriting controller and manifest together. Costs/tokens/cache status are supplied as observed metadata or null. Other inherited toolchain/build environment still needs controller provenance.

No unresolved Task 1 implementation issue identified in self-review. The full-suite native-anchor failures above remain outside Task 1 ownership and are explicitly reported as ongoing work.

## Fix round 1 — scoped independent review R1/R2

Read `docs/agent-reports/evolution/task1-review.md` and applied the receiving-code-review workflow. Both reported issues were verified against the existing open/read paths and reproduced by focused regression tests before fixes.

R1: added a shared contained regular-file check for ledger internals, checked every prior attempt entry as a contained real directory, and checked prior result files before budget reads. Dangling/existing-target `.manifest-digest` and `.budget.lock` symlinks, directories used as ledger files, prior attempt/result symlinks and incompatible entries are refused before evaluator launch. External sentinel contents remain unchanged in the regression controls.

R2: result records now contain `evidence` hashes for the captured command and raw stdout/stderr after log handles close. `check --result` requires those contained regular files, checks hashes, and independently compares `command.json` to frozen argv/cwd. Missing, replaced, symlinked and directory replacements cannot PASS. Empty raw logs remain valid and are hashed. Direct result-file reads are also contained/regular checks. The guide documents these checks.

Only the owned implementation/tests/guide and requested report/logs were edited. Test fixture commits now explicitly disable inherited Git commit signing so isolated protocol tests do not depend on keyboxd. No whole suite, staging, commit, actual experiment freeze, or subagent was used for this fix round.

The first RED runs retained failure/error output, including fixture-restoration cascades after failed assertions. The raw-evidence fixture was changed to restore captures before asserting, and its clean RED is preserved separately. No passing claim is made for any RED log. The final owned targeted run below is the completion evidence.

Exact command:

```sh
python3 -m unittest verification.test_change_protocol.ChangeProtocolTests.test_ledger_symlinks_and_nonregular_entries_refuse_launch verification.test_change_protocol.ChangeProtocolTests.test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch -v > reports/evolution/task1/fix1/r1-red.log 2>&1
tail -n 10 reports/evolution/task1/fix1/r1-red.log
```

Raw tail:

```text
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 239, in test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch
    with self.assertRaises(protocol.ProtocolError): self.run_stage()
AssertionError: ProtocolError not raised

----------------------------------------------------------------------
Ran 2 tests in 0.273s

FAILED (failures=2, errors=8)
```

Exact command:

```sh
python3 -m unittest verification.test_change_protocol.ChangeProtocolTests.test_ledger_symlinks_and_nonregular_entries_refuse_launch verification.test_change_protocol.ChangeProtocolTests.test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch -v > reports/evolution/task1/fix1/r1-green.log 2>&1
tail -n 10 reports/evolution/task1/fix1/r1-green.log
```

Raw tail:

```text
test_ledger_symlinks_and_nonregular_entries_refuse_launch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (verification.test_change_protocol.ChangeProtocolTests) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.420s

OK
```

Exact command:

```sh
python3 -m unittest verification.test_change_protocol.ChangeProtocolTests.test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check verification.test_change_protocol.ChangeProtocolTests.test_command_record_must_agree_with_frozen_argv_even_if_hash_is_updated verification.test_change_protocol.ChangeProtocolTests.test_empty_raw_logs_are_bound_and_valid -v > reports/evolution/task1/fix1/r2-red-clean.log 2>&1
tail -n 10 reports/evolution/task1/fix1/r2-red-clean.log
```

Raw tail:

```text
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 278, in test_empty_raw_logs_are_bound_and_valid
    self.assertIn('evidence',result)
AssertionError: 'evidence' not found in {'manifestDigest': '413ab6a0c882a3a95bef47ebc123eb35e8f5cb7fbd71de5fa90b1af1f775a004', 'candidateDigest': 'ef3e0d4beee014112d371a047ace50559372aad3b2844523a0d2c518fa3fa5e5', 'stageId': 'full', 'attemptId': 'a1', 'outputDirectory': '/private/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/tmp0b8lv0ib/reports/attempts/a1', 'argv': ['bash', 'scripts/verify.sh', '/private/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/tmp0b8lv0ib/reports/attempts/a1/full'], 'cwd': '/private/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/tmp0b8lv0ib', 'verdictProtocol': 'full-gate', 'metadata': {'arm': 'test', 'caches': {'build': 'cold', 'provider': None}, 'costUsd': None, 'modelId': 'test-model', 'reasoningEffort': 'high', 'seed': None, 'tokenUsage': None}, 'startedUtc': '2026-10-11T16:22:06.894943+00:00', 'startedNs': 1791735726894940000, 'exitCode': 0, 'timedOut': False, 'artifacts': {'full/report.md': 'b91a11419c869ad7697e3ff58e44679208174f154aea6cca8e47ac33235ab6cd'}, 'classification': 'PASS', 'endedUtc': '2026-10-11T16:22:06.903815+00:00', 'durationSeconds': 0.008883540999999995}

----------------------------------------------------------------------
Ran 3 tests in 0.430s

FAILED (failures=14)
```

Exact command:

```sh
python3 -m unittest verification.test_change_protocol -v > reports/evolution/task1/fix1/targeted-green.log 2>&1
tail -n 10 reports/evolution/task1/fix1/targeted-green.log
```

Raw tail:

```text
test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_protected_edit_add_delete_and_out_of_scope_new_source (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_semantic_requires_report_and_native_mismatch (verification.test_change_protocol.ChangeProtocolTests) ... ok
test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass (verification.test_change_protocol.ChangeProtocolTests) ... ok

----------------------------------------------------------------------
Ran 16 tests in 2.855s

OK
```

Ready for scoped re-review of R1/R2. No unresolved issue identified within these fixes. The reviewer should confirm them before actual protocol freeze; the prior in-progress broader-suite snapshot has not been rerun.
