# Independent formal quality review

Final review verdict after one remediation wave: ACCEPT for the reviewed finite-model implementation, subject to root's full local and hosted acceptance gates. All three original blocking defects below are resolved. The original findings are retained as review history. No native build or TLC exploration was repeated by this reviewer.

## Blocking findings

1. `verification/formal/bridge.py:78-92`: the strict effects parser accepts a trailing comma (`<<"fx",>>`) as the valid tuple `("fx",)`. A malformed dump can therefore pass the exact JSON observation comparison. Require an item after every separator and add a regression exercising the complete dump comparison with a malformed otherwise matching effects field.
2. `verification/formal/runner.py:classify_negative` and `run` trace selection: an exact invariant message, exit 12, and any nonempty file count as an actual counterexample. The inline fallback checks only `State 1`; it does not require complete states or the injected failing Logout observation. The existing positive classifier test uses only `State 1\n`, so it enshrines this weakness. Validate a real TLC behavior trace (complete four-field states, initial observation, causal transitions, and the expected Authenticated/Logout empty-effects violation). Reject truncated or unrelated trace content even alongside the right exit/message. Preserve raw evidence.
3. `scripts/verify.sh:14`: unconditional `rm -rf "$OUT_DIR/formal"` removes any preexisting unowned directory before the runner can enforce its ownership marker. Remove that recursive deletion and let the formal runner clean only its owned directory; add an integration regression proving an unowned sentinel survives. Avoid appending a stale prior PASS when an unowned directory causes failure.

## Model and scope assessment

`Init` uses a reserved event sentinel; `Next` selects a generated row whose source equals the current state and assigns previous state, event, next state and ordered effects together. `[][Next]_vars` permits stuttering while preserving last-transition observations. No fairness assumptions or liveness assertions were introduced. Closure, maximum sequence length and table membership are appropriate safety invariants. The configuration explicitly checks all five invariants and leaves default deadlock checking enabled; the runner selects one worker, no simulation/depth bound, requires exit 0 plus completion evidence, and compares the full dumped observation set with the direct JSON projection.

The projection is complete for the current reachable contract states; omitted or changed generated rows are detected by missing/extra observations. It is an observation correspondence check, not a proof of every causal graph edge. That limitation is correctly stated in the design and README. The handwritten causal `Next` assignment remains essential. Existing JSON validation supplies totality/determinism and declared-alphabet checks before conversion.

The `THEOREM Spec => []...` declarations are unproved mathematical statements. This change invokes TLC model checking, not TLAPS or a deductive proof checker. Acceptance and documentation must continue saying that the configured finite instance was model checked; the declarations do not establish generic theorems for all future contracts. No native refinement or arbitrary-length native equivalence is established.

## Tooling, provenance and maintenance

The immutable official release URL and SHA lock are checked for cached, downloaded and explicit JAR paths; installation uses a verified temporary download and atomic replacement. Trust origin is accurately described as a locally measured official HTTPS artifact hash, not a publisher signature. Timeout/signal/nonzero positive exit, missing completion and missing dump fail closed. Python subprocess timeout kills/reaps the direct Java child used here. No unchecked shell interpolation is used by the runner.

The runner's default-spec hash pin matches the explicitly frozen stage, and `--spec` is deliberately allowed by the design. It is not a current-stage blocking defect or a soundness bypass: the override is schema/semantically validated and receives the same model checks. It is a maintenance concern that permanent verifier code inhibits a future same-authority JSON update. Prefer keeping the freeze in stage acceptance evidence rather than a permanent behavior verifier constant, or clearly documenting removal/update when a future contract change is authorized. The fixed Logout negative control similarly depends on the current contract vocabulary.

Mandatory gate wiring, report append, Job Summary, and always-upload artifact settings are consistent with the intended integration. Outer verification captures commit/dirty state and contract hash; formal metadata captures exact contract and JAR hashes, Java text, source path and commands. For stronger standalone reproducibility, also record schema/model/lock hashes. Download/hash/Java failures currently happen before metadata creation; their FAIL report has an error but less provenance than a successful run.

The current unit suite covers useful parser/hash/classifier cases, but does not yet satisfy the design's explicit mocked tool-failure coverage. Add targeted regressions for timeout, positive nonzero/missing completion or dump, download failure/corrupt cache, malformed negative trace, and stale output reuse. Avoid claiming those failure paths were tested from the existing suite alone.

## Commands and observed output

Targeted probes and the lightweight existing suite were run in `/Users/shigeo/work/mobile/native-contract-poc`:

```sh
python3 - <<'PY'
from verification.formal import bridge, runner
from pathlib import Path
import tempfile
print('trailing-comma probe:', bridge._parse_effects('<<"fx",>>'))
with tempfile.TemporaryDirectory() as td:
 p=Path(td)/'trace'; p.write_text('arbitrary non-counterexample content')
 print('non-counterexample probe:',runner.classify_negative(12,'Error: Invariant TransitionSound is violated.',str(p),False))
print('no-effect interior probe:', bridge._parse_effects('<<>>'))
PY
python3 -m unittest verification.test_formal -v
```

Raw probe output:

```text
trailing-comma probe: ('fx',)
non-counterexample probe: (True, 'named TransitionSound invariant violation and nonempty counterexample present')
no-effect interior probe: ()
```

Raw suite output tail:

```text
test_duplicate_observation_rejected (verification.test_formal.FormalBridgeTests) ... ok
test_generated_data_quotes_values_and_keeps_transition_rows (verification.test_formal.FormalBridgeTests) ... ok
test_hash_verification (verification.test_formal.FormalRunnerTests) ... ok
test_negative_control_requires_named_invariant_and_counterexample (verification.test_formal.FormalRunnerTests) ... ok
test_output_safety_rejects_unowned_nonempty_and_root (verification.test_formal.FormalRunnerTests) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.004s

OK
```

Command exit: 0. Passing existing tests does not resolve the demonstrated malformed-input acceptance defects. Root owns the full native/formal gate and hosted CI verification; this review makes no claim about those runs.

## Remediation re-review and final verdict

The strict effects parser now rejects the trailing separator and its regression covers the complete dump comparison. Negative classification now requires exit 12, the exact named invariant diagnostic, a complete annotated TLC behavior trace in both command output and artifact, equal parsed state sequences, the JSON initial observation, causal edges matching the validated table, and a single final injected Authenticated/Logout suppressed-effect violation. The arbitrary nonempty-file acceptance is eliminated. The full shell verifier creates a fresh `formal-run.*` directory, preserves unrelated paths, and appends only that run's marker-owned report. The integration worker recorded a lightweight mocked shell regression preserving an unowned sentinel and excluding stale PASS output.

The unproved THEOREM declarations and obsolete production specification digest pin were removed. Safety invariants and the causal model assignments remain unchanged. Metadata now includes schema/model/lock hashes and is emitted before JAR acquisition, improving failure provenance. Mocked runner tests exercise download/hash failure handling, positive timeout/missing completion, and marker-owned stale report replacement. The finite safety, no-fairness, no-native-refinement scope remains appropriate.

Minor documentation correction requested from root: README currently refers to removed THEOREM declarations and a verifier stage pin. Describe TLC checking the configured finite instance and the stage SHA as acceptance evidence instead. Minor test limitation: the reformatted-spec test supplies `--spec`, which bypassed the former default pin already; it does not itself regress the default-source pin removal, although direct code inspection confirms that removal.

Re-review commands:

```sh
python3 - <<'PY'
from verification.formal import bridge, runner
from pathlib import Path
import tempfile
try: bridge._parse_effects('<<"fx",>>')
except ValueError as e: print('trailing-comma rejected:', e)
with tempfile.TemporaryDirectory() as td:
 p=Path(td)/'trace'; p.write_text('arbitrary non-counterexample content')
 print('non-counterexample rejected:',not runner.classify_negative(12,'Error: Invariant TransitionSound is violated.',str(p),False)[0])
PY
python3 -m unittest verification.test_formal -v
```

Raw probes:

```text
trailing-comma rejected: trailing effects separator
non-counterexample rejected: True
```

Raw suite output tail:

```text
test_output_safety_rejects_unowned_nonempty_and_root (verification.test_formal.FormalRunnerTests) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.042s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

Command exit: 0. The FAIL lines are expected mocked failure-path diagnostics. No new blocking defect found in the scoped re-review. This verdict does not substitute for root's actual full local gate, contract/native freeze checks, or hosted CI evidence.
