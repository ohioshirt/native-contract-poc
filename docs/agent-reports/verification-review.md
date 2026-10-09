# Verification quality review (baseline v1)

Final verdict after the scoped fix wave: APPROVE with minor risks. Prior evidence robustness blockers are resolved. The initial review below is preserved as history; its request-changes verdict is superseded. Contract conformance and differential gates are fail-closed on the inspected normal paths. No native integration or hosted CI was run by this reviewer, and no hosted PASS is inferred. Phase 6 is outside this review.

Reviewed the fixed specification/schema, design and plan, verification worker report, Python oracle/comparator/reporting code, shell orchestration, mutation matrix/harness, workflow, Gradle pins and exact native mutation sites. Native libraries were otherwise excluded.

## Blocking findings

1. **Malformed output can prevent the promised report from being emitted.** `verification/verify.py:38` indexes unvalidated scenario values. A syntactically valid output with `scenario: []` makes `failure_rows` raise `TypeError` after the conformance checker has already identified invalid output. `summary.json` and Markdown are never written. This fails closed but loses the separate verdicts and diagnostics required for failure evidence. Guard index construction using the same structural validation as the comparator, and retain malformed-row errors in the report. Regression should assert nonzero exit AND generated JSON/Markdown with FAIL verdicts for list/object IDs.

Targeted probe command used `python3 -` to create temporary `bad.json` with `{"traces":[{"scenario":[],"steps":[]}]}`, then invoked:

```text
python3 verification/verify.py --swift bad.json --kotlin bad.json --report summary.json
exit: 1 summary exists: False
Traceback (most recent call last):
  File "/Users/shigeo/work/mobile/native-contract-poc/verification/verify.py", line 115, in <module>
    raise SystemExit(main())
  File "/Users/shigeo/work/mobile/native-contract-poc/verification/verify.py", line 87, in main
    "failedSteps": failure_rows(expected, swift_rows, swift_error, kotlin_rows, kotlin_error)}
  File "/Users/shigeo/work/mobile/native-contract-poc/verification/verify.py", line 38, in failure_rows
    indexed.append({row.get("scenario"): row for row in (rows or []) if isinstance(row, dict)})
  File "/Users/shigeo/work/mobile/native-contract-poc/verification/verify.py", line 38, in <dictcomp>
    indexed.append({row.get("scenario"): row for row in (rows or []) if isinstance(row, dict)})
TypeError: unhashable type: 'list'
```

2. **Reused evidence directories retain prior mutation PASS artifacts.** `scripts/verify.sh:8-9` removes top-level logs but retains `mutations/`. `scripts/mutations.py:42-45` clears a case only when reached. An infrastructure failure in the first case leaves later cases' previous `actual.json`/`result.txt` intact; `SKIP_MUTATIONS=1` also leaves all prior mutation results intact, records exit zero, and allows Overall PASS. The stderr skip notice is useful, but an artifact bundle can still mix current baseline evidence with old mutation outcomes. Clear the entire current-run mutation evidence before execution/skip or use fresh run directories and a manifest explicitly identifying completed/failed/skipped cases. A skipped gate should have a visible NOT_RUN status rather than look like an executed success.

A targeted `python3 -` probe imported `scripts.mutations`, created `out/B-old/result.txt` containing `PASS previous run`, invoked `mutations.main()` with an A-new case, and patched `execute` to return an infrastructure exit without running native builds. Raw output:

```text
injected generate infrastructure error: A-new: oracle input generation failed
command: synthetic mutations.main() probe, execute mocked to return 1 (no native builds)
prior B PASS artifact survives: PASS previous run
```

Neither finding makes the full default gate return success after an actual conformance failure; they compromise failure reporting and evidence provenance.

## Compliance and strengths

The interpreter is independent of native implementations. Cartesian event enumeration includes the empty sequence and every sequence through the fixed bound; semantic validation checks exact pair completeness, uniqueness, declared successor/effect closure, bound equality, reachability and exercised transition pairs. These checks establish properties of the finite table and bounded traces, not arbitrary native-program equivalence.

Oracle comparison checks every intermediate event/state/ordered effect list. Structural validation rejects malformed roots/steps, duplicate IDs, missing/extra/reordered scenarios and step-count changes. Duplicate JSON keys are rejected on input. Direct differential equality may legitimately PASS for identically wrong or empty traces; separate oracle checks remain necessary and the orchestration requires them. Mutation C deliberately exposes this distinction.

All matrix patch strings match unique intended native reducer sites, as inspected and covered by the existing worker test. Disposable source copies exclude native build directories and Python caches, patches affect copies, runners are rebuilt, and build/runner failures abort as infrastructure rather than count as mutation kills. Compare exit 2 is infrastructure; semantic mismatch exit 1 is a verdict.

Runner JSON is redirected separately from stdout/stderr command logs. The local gate records command lines, exit codes, raw tails, contract hash, source revision/dirty marker and tool versions. CI uses explicit macOS/Xcode/Python/Java choices, a pinned Kotlin plugin and Gradle distribution checksum, runs the same local gate, uploads evidence on failure and appends a job summary when the verification script reaches its end. Actual hosted execution remains unverified here.

## Minor risks and follow-up

- `verify.sh` creates a relative output path before changing directory, then accesses it relative to the project root. Invoking the script from outside the project with a relative output argument can write/create different paths. Resolve the output path before `cd`.
- Missing-runner fallback `summary.json` omits the differential verdict and supplies no per-check errors; early oracle failure emits JSON but no Markdown. Keep the summary shape stable across failure paths.
- Git SHA plus `dirty` does not reconstruct a dirty source tree. Preserve a source manifest/hash or diff for reproducibility of uncommitted baseline runs.
- Mutation subcommands retain command/stdout/stderr but not individual exit-code files, and infrastructure failures do not write a structured case result. Add explicit case outcome and exit evidence.
- CI action tags and the macOS image are mutable; versions are logged, but reproduction is less exact than commit-pinned actions. Add a job timeout if runtime should be bounded. Artifact upload before the verification script starts may have no evidence; the workflow currently warns rather than fails for missing files.
- The validator intentionally implements the schema subset used today. Unsupported keywords on schema branches never visited by the data are not globally checked; keep this limitation explicit if schema evolution is introduced.

No edits were made outside this report. Existing worker test counts were not independently rerun or claimed as passing. The reviewer ran only the targeted synthetic probes above; coordinator-owned native integration and mutation execution remain required.

## Scoped re-review after fix wave

Inspected the revised `verify.py`, `verify.sh`, `mutations.py`, regression tests and worker report. No remaining blocking issue was found in this scoped re-review. Native integration and hosted CI remain coordinator-owned; this approval is for the reviewed verification implementation, not a claim that either gate passed.

Malformed list/object scenario IDs now produce nonzero conformance verdicts and both JSON/Markdown reports. Comparator diagnostics remain present; unassignable malformed rows intentionally do not generate per-step rows. Missing runner outputs preserve all verdict keys, and oracle-failure handling writes Markdown as well as JSON.

The mutation harness clears all current-matrix owned case directories before beginning any case, initializes a current-run manifest with NOT_RUN entries, records infrastructure failure explicitly and leaves subsequent cases NOT_RUN. Skip also clears those case results and publishes a NOT_RUN manifest. Each executed subcommand now retains its exit code. Relative output paths are resolved before changing directory.

`SKIP_MUTATIONS=1` is coherently a subset-gate mode: it can exit zero when all requested checks succeed, but reports Overall INCOMPLETE and mutations NOT_RUN rather than full acceptance. The default hosted workflow does not set this flag. Consumers must use the documented full-gate command for acceptance and must not interpret subset exit zero as proof that mutations ran.

Targeted regression command actually run by the reviewer (no native builds):

```sh
python3 -m unittest verification.test_verification.CliTests.test_malformed_scenario_ids_still_emit_failed_json_and_markdown verification.test_verification.CliTests.test_missing_runners_keep_stable_summary_and_markdown_shape verification.test_verification.CliTests.test_skip_mutations_clears_old_owned_pass_evidence_and_marks_not_run verification.test_verification.CliTests.test_mutation_infrastructure_abort_marks_later_cases_not_run -v
```

Raw output:

```text
test_malformed_scenario_ids_still_emit_failed_json_and_markdown (verification.test_verification.CliTests) ... ok
test_missing_runners_keep_stable_summary_and_markdown_shape (verification.test_verification.CliTests) ... ok
test_skip_mutations_clears_old_owned_pass_evidence_and_marks_not_run (verification.test_verification.CliTests) ... ok
test_mutation_infrastructure_abort_marks_later_cases_not_run (verification.test_verification.CliTests) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.052s

OK
```

Remaining minor risks are dirty-source reproducibility, mutable action/image pins and schema-subset scope noted above. Additionally, `markdown_report` currently has a three-column delimiter row (`|---|---|---|`) under a two-column header; some Markdown renderers may not render the verdict table. Change it to `|---|---|`. The JSON verdicts are unaffected. Case cleanup covers IDs in the current matrix; if matrix IDs are removed/renamed later, older orphan directories may remain, so the current manifest must remain authoritative or a future migration should clean explicitly owned obsolete cases.
