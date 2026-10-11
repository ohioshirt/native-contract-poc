# Frozen change protocol

`verification.change_protocol` is a Python stdlib reproducibility guard. The controller reviews the complete evaluator, freezes its current working copy, and saves the printed manifest SHA-256 in controller evidence. Every `check` and `run` requires that independently retained digest. Baseline HEAD is provenance, not the source of evaluator hashes: reviewed uncommitted changes are included in `inputSnapshot`.

This protects cooperative workers against accidental or unauthorized edits. A worker able to rewrite both the manifest and authoritative controller evidence can bypass it. It is not an adversarial execution sandbox or a native refinement proof.

## CLI

Run from the repository root; supply canonical absolute candidate/manifest paths.

```sh
bash scripts/change-protocol.sh freeze \
  --candidate "$PWD" --config reports/evolution/protocol-config-r1.json \
  --manifest "$PWD/reports/evolution/manifest-r1.json"

bash scripts/change-protocol.sh check \
  --candidate "$PWD" --manifest "$PWD/reports/evolution/manifest-r1.json" \
  --manifest-digest '<controller-retained SHA-256>'

bash scripts/change-protocol.sh run \
  --candidate "$PWD" --manifest "$PWD/reports/evolution/manifest-r1.json" \
  --manifest-digest '<controller-retained SHA-256>' \
  --stage old-native-red --attempt old-native-red-01

bash scripts/change-protocol.sh run \
  --candidate "$PWD" --manifest "$PWD/reports/evolution/manifest-r1.json" \
  --manifest-digest '<controller-retained SHA-256>' \
  --stage candidate-full --attempt candidate-full-01 \
  --metadata reports/evolution/candidate-metadata-01.json

bash scripts/change-protocol.sh check \
  --candidate "$PWD" --manifest "$PWD/reports/evolution/manifest-r1.json" \
  --manifest-digest '<controller-retained SHA-256>' \
  --result "$PWD/reports/evolution/protocol-r1/candidate-full-01/result.json"
```

Exit status is `0` for PASS, `1` for SEMANTIC_FAIL, and `2` for INFRA_FAILURE or NOT_RUN. Output is one JSON object. `check` without `--result` checks source integrity only: its PASS does not establish an evaluation PASS. `check --result` retains the verified evaluation verdict in both `classification` and `resultClassification`, and separately reports `bindingClassification: "PASS"` after successful binding checks. Its CLI exit status follows the evaluation verdict, so a bound semantic failure exits 1 and a bound infrastructure failure or NOT_RUN exits 2. Binding failures return `classification: "INFRA_FAILURE"`, never claim binding PASS, and do not publish a trusted `resultClassification`. Unknown arguments, including `--argv` and `--verdict-protocol`, are refused. `run` selects a frozen stage and substitutes only `{candidate}` and its newly reserved `{output}` directory. Stage timeout, cwd, command, artifact inventory and verdict protocol cannot be overridden.

## Configuration schema

The JSON object below shows every required top-level key and both supported verdict protocols. The controller must replace the example metadata/provenance with observed facts, review exclusions, and choose budgets before freezing. These values are illustrative, not evidence of an actual run.

```json
{
  "changeId": "contract-evolution-r1",
  "baselineCommit": "8458f66a0691532a7f48e7ca1fb14fc86238b67f",
  "allowedPaths": [
    "ios/Sources/AsyncNativeContract/",
    "ios/Sources/ManagedHistoryRunner/",
    "ios/Tests/AsyncNativeContractTests/",
    "ios/Package.swift",
    "android/async-library/"
  ],
  "protectedPaths": [
    "reports/evolution/baseline-native/",
    "docs/agent-reports/evolution/baseline-native-hashes.json"
  ],
  "ignoredPaths": [
    ".git/", "ios/.build/", "android/.gradle/",
    "android/library/build/", "android/async-library/build/",
    ".gradle-home/", ".swift-cache/", ".formal-cache/",
    "verification/__pycache__/", "verification/formal/__pycache__/",
    "reports/", "docs/agent-reports/evolution/",
    "docs/experiments/evolution-evidence.md"
  ],
  "outputRoot": "reports/evolution/protocol-r1",
  "maxAttempts": 12,
  "maxTotalSeconds": 7200,
  "metadata": {
    "modelId": null,
    "reasoningEffort": null,
    "arm": "coordinated-lower-model-run",
    "seed": null,
    "caches": {"build": null, "provider": null},
    "tokenUsage": null,
    "costUsd": null
  },
  "provenance": {
    "baselineRunnerHashes": "docs/agent-reports/evolution/baseline-native-hashes.json",
    "toolchains": "controller-retained baseline toolchain evidence"
  },
  "stages": {
    "old-native-red": {
      "argv": [
        "python3", "-m", "verification.async_verify",
        "--output", "{output}/async",
        "--swift", "{candidate}/reports/evolution/baseline-native/AsyncTraceRunner",
        "--kotlin", "{candidate}/reports/evolution/baseline-native/async-library/bin/async-library"
      ],
      "cwd": "{candidate}",
      "timeoutSeconds": 600,
      "verdictProtocol": "async-comparator",
      "requiredArtifacts": [
        {"path": "async/async-report.json", "validator": "async-report"}
      ]
    },
    "candidate-full": {
      "argv": ["bash", "scripts/verify.sh", "{output}/full"],
      "cwd": "{candidate}",
      "timeoutSeconds": 3600,
      "verdictProtocol": "full-gate",
      "requiredArtifacts": [
        {"path": "full/report.md", "validator": "full-report"}
      ]
    }
  }
}
```

Rules:

- `baselineCommit` is a full available Git commit ID and must be an ancestor of the freezing tree's HEAD. `changeId`, stage IDs and attempt IDs match `[A-Za-z0-9][A-Za-z0-9_.-]{0,79}`.
- Paths are canonical relative POSIX paths. A trailing slash matches a directory and all descendants; a path without it matches only that file. Globs, traversal and source/output symlinks are refused. There are no implicit generated-output exclusions: declare each build/cache/evidence subtree needed by the evaluator. `.git/` must be explicitly excluded.
- `contract/`, `verification/`, `formal/` and `scripts/` are always protected, including the protocol implementation and entry scripts. Native allowances cannot overlap them. Explicit `__pycache__/` exclusions under evaluator trees are permitted. An explicit `protectedPaths` exception takes precedence over an evidence exclusion; therefore preserved baseline distributions and controller hashes remain protected inside reports/evidence directories.
- The complete current nonexcluded file inventory is frozen, including untracked reviewed inputs. Modified, added or deleted files are permitted only within `allowedPaths`; protected exceptions take precedence. Files elsewhere must match the frozen inventory and contents. Generated files outside declared exclusions are treated as source additions.
- `outputRoot` and the manifest path must be within excluded evidence, outside protected exceptions. Never overwrite a manifest: each evaluator revision uses a new manifest path and outputRoot. Stage output paths must be descendants of `{output}`. Input/native runner options must be descendants of `{candidate}`.
- Every stage has exactly `argv`, `cwd`, `timeoutSeconds`, `verdictProtocol`, `requiredArtifacts`. `cwd` is exactly `{candidate}`. Positive finite seconds and positive integer `maxAttempts` are required.
- `async-comparator` accepts only `python3 -m verification.async_verify --output ...` with optional `--swift`, `--kotlin`, `--input` pairs, or `bash scripts/async-verify.sh {output}/...`. `full-gate` accepts only `bash scripts/verify.sh {output}/...`. Script paths may alternatively start with `{candidate}/`. Freezing `true`, arbitrary programs, shell snippets, unknown comparator options or an exit-zero-only protocol is refused.
- A stage must require the correct known primary report under its frozen output path. Only that primary report can use a verdict validator. Additional required artifacts can use `file` (nonempty regular file) or `json-object` (JSON object). Required artifact paths are unique relative paths within the owned attempt directory.
- Metadata has exactly the seven keys shown. `modelId`, `reasoningEffort`, `arm` are nonempty strings or null; `seed` is integer or null; caches declare build/provider strings or null. Token usage and USD cost are finite nonnegative numbers or null. `--metadata` changes attempt metadata only. Record actual provider figures when available; use null when unavailable. The protocol makes no provider calls or estimates. Duration is measured independently using a monotonic clock.
- Nonempty `provenance` is explicit controller-supplied evidence, not automatic toolchain validation. Preserved binary/distribution files and the recorded hash mapping should be protected exceptions; content/membership is rechecked before and after every stage.

## Acceptance conditions

Let `S(C)` be the path-to-SHA256 map of candidate files after exclusions, `P` the protected paths, and `A` allowed native paths. Source validity is:

```text
for every changed/added/deleted path p in S(C) versus frozen S:
    p is in A and p is not in P
candidateDigest = SHA256(canonical JSON of S(C))
```

An attempt can PASS only after the before/after protected membership check succeeds, the exact candidate digest stays equal, the fixed command finishes, and every required artifact is a newly produced regular file with modification time at or after the attempt start. A newly reserved directory prevents preexisting artifacts; copied old timestamps, missing, empty, malformed or symlinked reports fail. The record binds manifest digest, candidate digest, stage ID, attempt ID, argv, cwd, protocol, artifact hashes and an `evidence` SHA-256 map for `command.json`, `stdout.log`, `stderr.log`. `check --result` requires all captured evidence as contained regular files, verifies those hashes and checks that the captured command agrees with the frozen argv/cwd, then rechecks current candidate digest, report shape, freshness, artifact hashes and classification. Empty stdout/stderr captures are valid and still have hashes; missing or replaced captures cannot PASS. Successful binding verification does not promote a non-PASS evaluation to PASS. For example, a bound semantic failure returns `{"classification":"SEMANTIC_FAIL","resultClassification":"SEMANTIC_FAIL","bindingClassification":"PASS",...}` and exits 1. A previous verdict does not apply after even an allowed native source edit.

For async comparison, a report must contain positive scenario/step counts, exactly swift/kotlin/differential verdicts, consistent status, and diagnostics for every FAIL. Exit 1 is semantic only when the known comparator's report includes an actual native FAIL with mismatch diagnostics. Native INFRA_FAILURE outranks semantic results; native NOT_RUN prevents PASS. Exit 2, signals, timeouts, launch errors and inconsistent exit/report combinations are infrastructure failures. The aggregate full gate requires exit 0 and `report.md` beginning exactly `Overall: PASS`; `Overall: INCOMPLETE` is NOT_RUN. Aggregate exit 1 is INFRA_FAILURE, never assumed semantic RED.

The protocol writes `command.json`, `stdout.log`, `stderr.log` and `result.json` into a fresh `<outputRoot>/<attemptId>/`. The result includes UTC start/end, start nanoseconds, monotonic duration, numeric exit code, timeout flag, hashes, metadata and classification. Timeout kills the launched process group and preserves logs. `PYTHONPATH` is set to the candidate root. Ordinary inherited build/toolchain environment still matters; retain its provenance and cache status.

## Attempt budget and revisions

The ledger belongs to one authoritative manifest digest. `maxAttempts` counts all reserved stage attempts, including old-native RED and the full gate, and is not automatically a count of native repair rounds. The controller also enforces the plan's five-repair limit and records interventions. `maxTotalSeconds` sums measured durations across stages; each process is limited by the smaller of its stage timeout and remaining duration budget. A stopped attempt records NOT_RUN and an explicit budget-exhausted detail. No budget stop is PASS.

Directory reservation is protected by a local POSIX file lock. The `.budget.lock`, `.manifest-digest`, prior attempt directories and their result files are checked for containment, symlinks and incompatible file types before opening them. Existing incompatible ledger entries are rejected before evaluator launch. Concurrent/unfinished attempts are refused. A crashed reservation is retained; the controller must investigate and begin a reviewed revision/new ledger if recovery is needed. Existing attempt directories and unowned files are never deleted or replaced. Changed evaluator code invalidates prior results: retain superseded records in controller evidence, review/refreeze a new revision, and rerun the applicable old-native RED and candidate stages.

This run is a coordinated lower-model workflow, not a controlled model comparison. For a later comparison, use identical reviewed inputs/evaluator/baseline in clean per-arm trees, balance execution order, record build/provider caches and all attempts, and distinguish workflow comparison from model-only comparison.
