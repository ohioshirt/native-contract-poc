# Formal model worker report

The runner converts validated `contract/specification.json` v2 rows into finite TLA+ sets and transition tuples, then checks them with the handwritten generic model in `formal/Session.tla`. The observation bridge parses only TLC 2.19's observed `State n:` and four `/\ variable = value` line grammar. It rejects missing, duplicated, malformed, or extra observations and compares the reachable observations against every contract row plus the unique initial observation.

The pinned artifact was read from `.formal-cache/tla2tools-1.7.4.jar`; its SHA-256 is `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`. The runner checks this hash on both cached and explicitly provided JARs. The hash origin is the official HTTPS release download; it is not publisher-signature verification. Java was Amazon Corretto 17.0.13.

The output directory is protected by an ownership marker. An existing nonempty unowned directory and filesystem root are rejected. The runner records tool/source metadata, exact commands, stdout, stderr, exit status, dump, and the negative run's counterexample text. The negative model is an isolated copy with only the `Authenticated × Logout` emitted effects changed to empty; the generated contract table and positive model remain intact.

Validation command:

```text
python3 -m unittest verification.test_formal -v
```

Observed output tail:

```text
Ran 6 tests in 0.004s

OK
```

Actual pinned TLC command (working directory is the output's `positive/` directory):

```text
java -cp /Users/shigeo/work/mobile/native-contract-poc/.formal-cache/tla2tools-1.7.4.jar tlc2.TLC -workers 1 -dump /private/tmp/formal-run-luna2/positive-state-dump.txt -config /private/tmp/formal-run-luna2/positive/Session.cfg /private/tmp/formal-run-luna2/positive/Session.tla
```

Positive exit was `0`. Raw stdout tail:

```text
Model checking completed. No error has been found.
  Estimates of the probability that TLC did not check all reachable states
  because two distinct states had the same fingerprint:
  calculated (optimistic):  val = 5.6E-17
81 states generated, 16 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 4.
The average outdegree of the complete state graph is 1 (minimum is 0, the maximum 5 and the 95th percentile is 5).
Finished in 00s at (2026-10-09 13:50:35)
```

The parser accepted all 16 unique dump observations and matched all 15 contract pairs plus the initial observation. No depth bound or fairness assumption was added; TLC completed breadth-first exploration and checked deadlocks by default.

Actual isolated negative control command:

```text
java -cp /Users/shigeo/work/mobile/native-contract-poc/.formal-cache/tla2tools-1.7.4.jar tlc2.TLC -workers 1 -dump /private/tmp/formal-run-luna2/negative-state-dump.txt -config /private/tmp/formal-run-luna2/negative/Session.cfg /private/tmp/formal-run-luna2/negative/Session.tla
```

Negative exit was `12`, TLC 2.19's invariant-violation status. Raw stdout evidence:

```text
Error: Invariant TransitionSound is violated.
Error: The behavior up to this point is:
State 1: <Initial predicate>
/\ previousState = "Unauthenticated"
/\ state = "Unauthenticated"
/\ effects = <<>>
/\ event = "__initial__"

State 2: <Next line 14, col 3 to line 18, col 87 of module Session>
/\ previousState = "Unauthenticated"
/\ state = "Authenticated"
/\ effects = <<>>
/\ event = "LoginSucceeded"

State 3: <Next line 14, col 3 to line 18, col 87 of module Session>
/\ previousState = "Authenticated"
/\ state = "Unauthenticated"
/\ effects = <<>>
/\ event = "Logout"
```

`python3 -m verification.formal.run --output /private/tmp/formal-run-luna2` returned exit `0` and wrote `report.json` with positive exit 0, negative exit 12, 16 expected and actual observations, and the locked source/JAR hashes. This model establishes properties of the generated finite machine; it does not claim liveness or refinement of arbitrary native programs.

## Review remediation

The effects-sequence parser now rejects trailing separators and malformed tokens. The counterexample classifier parses TLC's annotated four-variable trace, requires the unique initial observation, verifies every edge against the validated JSON transition table, and accepts only a final `Authenticated × Logout` row with its JSON effect suppressed. The trace artifact must parse to the same full state sequence as TLC's output, including the pinned tool's counterexample summary. Truncated traces, unrelated transitions, malformed suffixes, parser diagnostics, and process failures are rejected. Mocked runner tests cover download/hash failure reports, timeout, missing completion, stale report cleanup, and a whitespace-only spec reformat. The obsolete fixed specification digest was removed from production code. Unproved `THEOREM` declarations were removed; TLC's configured invariants remain the checked properties.

Review unit command:

```text
python3 -m unittest verification.test_formal -v
```

Observed output tail:

```text
test_output_safety_rejects_unowned_nonempty_and_root (verification.test_formal.FormalRunnerTests) ... ok
----------------------------------------------------------------------
Ran 9 tests in 0.034s

OK
FAIL: formal verification: RuntimeError: download failed
FAIL: formal verification: RuntimeError: TLC JAR SHA-256 mismatch
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
FAIL: formal verification: RuntimeError: positive TLC run failed, lacked completion evidence, or produced no state dump
```

The four `FAIL:` lines are expected output from mocked failure-path cases.

The final real TLC command was `python3 -m verification.formal.run --output /private/tmp/formal-run-review-final` (exit `0`). Its `report.json` records positive TLC exit `0`, negative exit `12`, and 16 expected/actual observations. Positive stdout ended with:

```text
81 states generated, 16 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 4.
The average outdegree of the complete state graph is 1 (minimum is 0, the maximum 5 and the 95th percentile is 5).
Finished in 00s at (2026-10-09 13:58:29)
```

Negative stdout ended with the complete three-state behavior trace, the exact `Authenticated × Logout` empty-effects observation, and:

```text
8 states generated, 8 distinct states found, 5 states left on queue.
The depth of the complete state graph search is 3.
The average outdegree of the complete state graph is 5 (minimum is 5, the maximum 5 and the 95th percentile is 5).
Finished in 00s at (2026-10-09 13:58:29)
```
