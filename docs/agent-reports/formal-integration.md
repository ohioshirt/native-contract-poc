# Formal verification integration

## Changes

- Added `scripts/formal-verify.sh`, a working-directory-independent wrapper for `python3 -m verification.formal.run --output ABS_DIR`.
- Made the wrapper a mandatory `formal-verify` gate in `scripts/verify.sh`, alongside the existing Python, Swift, Kotlin, contract, differential, native differential, and mutation gates. Each full run gets a fresh `formal-run.*` directory; preexisting paths are preserved. Its command, stdout/stderr tails, and exit code are included in the regular gate report. The formal CLI's detailed report is appended only from that run's output after the runner ownership marker exists, so a stale or unowned report cannot be presented as current evidence.
- Updated the existing workflow's gate label. The workflow retains its macOS 15, Xcode 16.2, Python 3.12.8, and Java 17 setup and always uploads the complete report directory, including formal outputs.
- Updated README to distinguish TLC all-reachable-state safety checking from bounded native traces, describe the strict dump projection bridge and intentional negative control, and state the limits around liveness, fairness, graph-edge proof, and native refinement. It documents the fixed official release URL/hash and hash trust origin.

## Verification status

The wrapper passed a smoke run from `/private/tmp`, confirming that it resolves the project root independently of the caller's working directory and writes the report/artifacts to the requested output directory. The first sandboxed JVM attempt could not bind TLC's local ephemeral RMI socket; rerunning with local socket access completed normally.

Commands and observed output:

```text
$ bash -n /Users/shigeo/work/mobile/native-contract-poc/scripts/verify.sh /Users/shigeo/work/mobile/native-contract-poc/scripts/formal-verify.sh
exit: 0

$ cd /private/tmp && bash /Users/shigeo/work/mobile/native-contract-poc/scripts/formal-verify.sh /private/tmp/formal-integration-smoke-escalated
PASS: formal TLC model check; 16 observations; negative control detected TransitionSound

Formal report: Status PASS; TLC v1.7.4 / 2.19; Java 17; contract SHA-256 fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11; JAR SHA-256 936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88; reachable dump observations 16; JSON observations including initial 16; named TransitionSound invariant violation and nonempty counterexample present.
```

The detailed raw command/stdout/stderr/exit logs, generated models, dumps, and counterexample were produced under `/private/tmp/formal-integration-smoke-escalated`. No hosted CI result is claimed; that requires an actual workflow run.

After review, a mock integration run exercised the full shell gate script without native builds. Its fixture began with an unowned `OUT/formal/` containing both `unrelated.txt` and a stale PASS report. The mocked formal command failed without creating an ownership marker. The script preserved the sentinel, kept the formal exit nonzero, and omitted the stale report from its aggregate report.

Commands and raw output tail:

````text
$ bash -n scripts/verify.sh scripts/formal-verify.sh
exit: 0

$ python3 /private/tmp/formal-integration-mock.py
mock integration assertions: preserved unowned sentinel; omitted stale PASS; formal gate remained nonzero
verify exit: 1; fresh formal dirs: 1
report tail:
## kotlin-version
```
kotlin("jvm") version "2.3.20"
```
## python-version
```
```
# Summary
```
```
````
