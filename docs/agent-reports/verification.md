# Verification implementation report

## Scope

This worker added an independent Python contract interpreter, schema and semantic checks, exhaustive vectors, strict native trace comparison, local/CI scripts, and an isolated mutation harness. No contract or native reducer source was changed. Native integration and the actual mutation builds are left for the coordinator's v1/v2 gates; the matrix below records expected verdicts, not measured mutation outcomes.

## Machine checks

`contract/schema.json` is consumed at runtime by `verification/contract.py`. The standard-library validator enforces the schema keywords used in this schema: `type`, `required`, `additionalProperties`, `$ref`, `const`, `minimum`, array `items`, `minItems`, and `uniqueItems`. It rejects unsupported validation keywords instead of silently skipping them. `$schema` and `title` are metadata. Both schema and specification JSON reject duplicate object keys.

Semantic checks prove that this finite table has exactly the 3 × 5 = 15 unique state/event pairs, every successor and effect is declared, the declared effect bound equals the observed maximum, each declared invariant is true, all states are reachable, and length 0–4 sequences exercise every pair. The product generator creates 1 + 5 + 25 + 125 + 625 = 781 independent scenarios from `Unauthenticated`; this is bounded exhaustive checking and does not prove arbitrary program equivalence.

The comparator rejects malformed roots and steps, duplicate/missing/extra scenarios, scenario reordering, duplicate JSON keys, missing/extra steps, changed intermediate states, changed events, changed effects or effect order. Runner output must contain exactly one `traces` property and each trace/step must have exactly the wire fields. `verify.py` emits oracle, Swift, Kotlin, and direct Swift/Kotlin differential verdicts, plus 1-based failed-step rows containing expected, Swift, Kotlin, and a divergence classification.

## Commands

Run the full local gate with `bash scripts/verify.sh [output-directory]`. The default evidence directory is `reports/latest`; passing a path supports independent v1/v2 reports. It records each command, stdout and stderr, final ten log lines, git SHA and dirty status, specification SHA-256, and actual Swift, Xcode, Java and Python versions plus the pinned Kotlin plugin version. The output directory contains generated input, native traces, JSON and Markdown summaries, and mutation evidence. Build caches live in `.swift-cache/` and `.gradle-home/` by default, outside uploaded evidence. `SKIP_MUTATIONS=1` skips only mutation runs for controlled experiments. `contract/test-vectors/README.md` documents generation of the full 781-case vector set.

Useful standalone commands:

```sh
python3 -m unittest discover -s verification -p 'test_*.py' -v
python3 verification/generate.py --output oracle.json
python3 verification/generate.py --wire-input --output scenarios.json
python3 verification/compare.py swift-traces.json
python3 verification/compare.py --left swift-traces.json --right kotlin-traces.json
python3 verification/verify.py --swift swift-traces.json --kotlin kotlin-traces.json --report summary.json
bash scripts/mutation-test.sh [output-directory]
```

Mutation A changes only Swift's authenticated/token-expired next state and expects `{Swift: FAIL, Kotlin: PASS, differential: FAIL}`. B removes only Kotlin's refresh-failed effect and expects `{Swift: PASS, Kotlin: FAIL, differential: FAIL}`. C removes logout's clear-credentials effect in both isolated copies and expects `{Swift: FAIL, Kotlin: FAIL, differential: PASS}`. Each patch must match one source location. Runners are rebuilt from disposable copies without unit tests, whose assertions intentionally reject the mutants. A compilation or runner failure is an infrastructure failure, never a killed mutation.

## Verification run by this worker

Python suite command:

```text
python3 -m unittest discover -s verification -p 'test_*.py' -v
...
---------------------------------------------------------------------
Ran 22 tests in 0.082s

OK
```

The test tail above is the raw output from the command run in this workspace. It covers malformed and duplicate inputs, schema type and completeness failures, domain completeness, effect closure/bounds, reachability/coverage, trace shape/order/length, duplicate/missing scenarios, and report verdict/failure rows.

Synthetic CLI check used oracle traces as both runner outputs and verified the direct Swift/Kotlin comparator. Raw output:

```text
PASS: 781 scenarios, ordered state/effect traces match
oracle: PASS
swift: PASS
kotlin: PASS
differential: PASS
```

The CLI test also altered one Kotlin intermediate state and verified the report retained `Swift: PASS`, `Kotlin: FAIL`, and a one-based expected/Swift/Kotlin row. `bash -n scripts/verify.sh` and Python byte compilation completed successfully in the same verification command. This synthetic check validates the reporting path only; it is not evidence that native code has passed the full integration gate.

## Review follow-up

The review probe with list/object scenario IDs now exits as a conformance failure while always writing JSON and Markdown with oracle, Swift, Kotlin and direct differential verdicts. Invalid IDs stay in comparator diagnostics; the per-step table omits them because they cannot be matched to an expected scenario. Missing runner outputs and oracle failures also preserve the same verdict-table shape.

Mutation output starts each run with a fresh manifest. Only case directories carrying this harness's marker or its legacy PASS/FAIL result signature are removed; unrelated files are preserved. Every matrix case begins as `NOT_RUN`, becomes `RUNNING`, then records `PASS`, `MATRIX_FAIL`, or `INFRA_FAILURE` with its case exit code. An early infrastructure failure leaves later cases `NOT_RUN`. Explicit skipping clears prior owned case results and records `NOT_RUN`; the local report says `Overall: INCOMPLETE (mutation matrix NOT_RUN)`. Individual command exit codes are retained beside command/stdout/stderr logs. `verify.sh` resolves relative output paths before changing directories and removes only its explicit top-level evidence filenames.

Regression command and raw final output after these changes:

```text
python3 -m unittest discover -s verification -p 'test_*.py' -v
...
Ran 26 tests in 0.154s

OK
```

The new regressions cover list and object scenario IDs producing FAIL JSON/Markdown, unavailable runner summary shape, skip clearing old owned PASS files while preserving unrelated output, and an infrastructure failure on the first mutation marking later cases `NOT_RUN` with no stale PASS evidence. Native integration was not rerun for this review follow-up; the coordinator will rerun the full gate after this report is complete.

The final report-format fix corrected the Markdown two-column delimiter. Focused test output:

```text
python3 -m unittest verification.test_verification.CliTests.test_missing_runners_keep_stable_summary_and_markdown_shape -v
Ran 1 test in 0.006s

OK
```

The final mutation exit-code hardening treats only comparator code 0 as PASS and code 1 as a semantic mismatch; negative signal exits and every other code are infrastructure failures. A regression injects `-15` into both native conformance and direct differential comparisons. The differential case reaches the eighth subcommand (`native-differential`); reverting that guard to the old `> 1` check produced the expected red test (`expected infrastructure exit 2, got matrix mismatch exit 1`). Final Python suite tail:

```text
python3 -m unittest discover -s verification -p 'test_*.py' -v
...
Ran 27 tests in 0.175s

OK
```

## CI

`.github/workflows/verify.yml` runs on macOS 15 for pull requests and pushes to `main`, selects Xcode 16.2, Python 3.12.8, and Temurin Java 17.0.13, then runs `verify.sh`. The report and evidence directory are uploaded in an `always()` step, including when a gate fails. A hosted CI pass must be reported only after an actual GitHub run.
