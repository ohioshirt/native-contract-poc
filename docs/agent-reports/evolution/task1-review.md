# Task 1 independent review

Status: CHANGES REQUESTED before experiment freeze.

Reviewer: independent scoped Sol review. Reviewed evolution-design.md B/R1, evolution-plan.md Task 1, Task 1 handoff, and the four owned protocol files. No source edits, staging, commits, nested delegation, full suite, or unrelated-agent review. The implementation's existing targeted test evidence is recorded in task1.md; it was not rerun merely for confirmation. This review used only concrete isolated temporary-tree probes.

## Important findings

### R1. Output ledger symlinks escape owned output and still permit PASS

Priority: P1, acceptance blocker. Location: verification/change_protocol.py:324–325 and 340–343.

`run` checks the outputRoot using `contained`, but then opens `.budget.lock` and `.manifest-digest` directly. A preexisting dangling `.manifest-digest` symlink is considered nonexistent by `exists()` and `write_text()` follows it. An isolated fixture with that output symlink created a file outside the candidate tree containing the authoritative manifest digest, then returned PASS. `.budget.lock` has the same unchecked open pattern. This conflicts with the documented refusal of output symlinks and the R1 isolated output ownership requirement, and can occur with leftover/unowned output entries; it does not require a privileged adversary or rewriting the manifest/controller.

Bounded fix: apply the same containment/symlink/regular-file checks to ledger internal entries before opening them, including prior attempt/result entries read for budget accounting. Reject an existing incompatible entry rather than following or replacing it. Add focused regression cases for dangling and existing-target ledger symlinks, assert external sentinel contents remain unchanged, and reject the attempt before evaluator launch. Do not expand this into a general sandbox.

Exact reproduction, from the managed worktree:

```sh
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from verification.test_change_protocol import ChangeProtocolTests
case = ChangeProtocolTests('test_capture_binds_fresh_artifact_and_exact_candidate')
case.setUp()
try:
    case.freeze()
    with TemporaryDirectory() as external:
        target = Path(external).resolve() / 'unowned-manifest-digest'
        ledger = case.root / case.config['outputRoot']
        ledger.mkdir(parents=True)
        link = ledger / '.manifest-digest'
        link.symlink_to(target)
        result = case.run_stage()
        print('preexisting_output_symlink:', link.is_symlink())
        print('outside_target_created:', target.exists())
        print('outside_target_contains_manifest_digest:', target.read_text().strip() == case.digest)
        print('run_classification:', result['classification'])
finally:
    case.doCleanups()
PY
```

Raw output (entire output, exit 0):

```text
preexisting_output_symlink: True
outside_target_created: True
outside_target_contains_manifest_digest: True
run_classification: PASS
```

The first invocation of this probe omitted the Git configuration override and failed before freeze because the inherited global commit signing configuration could not access keyboxd in the sandbox. It did not establish any protocol verdict. Its raw tail was:

```text
fatal: failed to write commit object
Traceback (most recent call last):
  File "<stdin>", line 5, in <module>
  File "/Users/shigeo/.codex/worktrees/b195/native-contract-poc/verification/test_change_protocol.py", line 37, in setUp
    subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Protocol Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline'], check=True)
  File "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/subprocess.py", line 528, in run
    raise CalledProcessError(retcode, process.args,
subprocess.CalledProcessError: Command '['git', '-C', '/private/var/folders/hk/75z5bqzs7cx5sb9r5qn552xc0000gn/T/tmpnb58dyue', '-c', 'user.name=Protocol Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline']' returned non-zero exit status 128.
```

### R2. Completed result verification does not bind captured raw evidence

Priority: P2, acceptance blocker for R1 evidence binding. Location: verification/change_protocol.py:242–260, 358–362, 384–387.

The result hashes required evaluator artifacts but does not hash `command.json`, `stdout.log`, or `stderr.log`, and `check --result` never reads these files. After a legitimate PASS, accidentally replacing the stdout capture and command record leaves `check --result` returning PASS. Removing these evidence files would likewise go unnoticed. R1 requires a record bound to its raw logs, and the handoff claims bound result records/raw subprocess evidence; checking only the evaluator's primary report does not preserve that evidence. This finding concerns accidental replacement within an excluded writable evidence directory, not a malicious party rewriting result.json too.

Bounded fix: record hashes for the three captured command/log files after closing log handles, require regular contained files when checking, compare their hashes, and verify command.json agrees with the frozen argv/cwd. Add focused missing/replaced evidence tests. An empty stdout/stderr log is valid and should still have a digest. Keep the existing artifact validators and source checks.

Exact reproduction, from the managed worktree:

```sh
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false python3 - <<'PY'
from pathlib import Path
from verification.test_change_protocol import ChangeProtocolTests
from verification import change_protocol
case = ChangeProtocolTests('test_capture_binds_fresh_artifact_and_exact_candidate')
case.setUp()
try:
    case.freeze()
    result = case.run_stage()
    output = Path(result['outputDirectory'])
    (output / 'stdout.log').write_text('accidental replacement\n')
    (output / 'command.json').write_text('{}\n')
    checked = change_protocol.check(case.manifest, case.digest, case.root, output / 'result.json')
    print('original_run_classification:', result['classification'])
    print('stdout_log_replaced:', (output / 'stdout.log').read_text().strip())
    print('command_record_replaced:', (output / 'command.json').read_text().strip())
    print('check_result_classification:', checked['classification'])
finally:
    case.doCleanups()
PY
```

Raw output (entire output, exit 0):

```text
original_run_classification: PASS
stdout_log_replaced: accidental replacement
command_record_replaced: {}
check_result_classification: PASS
```

## Remaining scoped assessment

Static review found the named-stage argv whitelist, frozen primary report selection, manifest digest/source digest comparison, source membership checks with protected exceptions, artifact freshness, timeout/signal non-PASS behavior, full aggregate failure handling, native semantic-report requirement, and reserved-attempt budgets aligned with the scoped design. Those observations are code inspection, not new passing-test claims. No broader implementation correctness or final evaluator approval is claimed. Re-review the owned fixes and their focused regression evidence before using this protocol to freeze the experiment.

## Fix round 1 scoped re-review — APPROVED

This verdict supersedes the initial CHANGES REQUESTED status above for Task 1. Both original findings are resolved; no unresolved important issue was identified in the fixes. The protocol is approved for the controller's reviewed experiment freeze within the cooperative-worker scope.

R1: `regular_file` now applies containment, symlink rejection and regular-file checks before opening ledger control files. Prior attempt entries are checked as contained directories, and their result records are checked before reads. The fix refuses both dangling and existing-target symlinks before evaluator launch. The regression controls cover both ledger files, directory substitutions, prior attempt/result symlinks and incompatible prior entries, while asserting unchanged external sentinel contents.

R2: `result.evidence` now binds `command.json`, `stdout.log` and `stderr.log` by SHA-256 after log handles close. `check --result` requires contained regular captures, compares every digest and verifies command.json against frozen argv/cwd independently of its hash. Empty logs remain valid. The regressions cover missing/replaced/symlinked/directory evidence and command disagreement even when its recorded hash is updated. Capturing evidence is also part of run finalization; evidence failure becomes INFRA_FAILURE rather than retaining PASS.

Reviewed only the owned fix paths and Task 1 fix evidence. No new source edit, suite run, nested delegation, staging or commit. No further reproduction was needed because the focused regression controls directly cover the original probes. The inherited Git signing independence fix is confined to temporary fixture commits. Static inspection found no new important breakage from these changes.

Worker validation command, as retained in task1.md (not rerun by this reviewer):

```sh
python3 -m unittest verification.test_change_protocol -v > reports/evolution/task1/fix1/targeted-green.log 2>&1
```

Reviewer evidence inspection command:

```sh
tail -n 10 reports/evolution/task1/fix1/targeted-green.log
```

Raw inspected tail:

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

Approval is scoped to Task 1 after this fix round. It does not substitute for the controller's final combined evaluator review, baseline binary provenance, explicit exclusions/budgets or final branch gate.
