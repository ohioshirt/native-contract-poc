# Clean reproduction

Use a full candidate commit whose hosted workflow has succeeded, and start from a new remote clone. No prior `reports/`, worktree, build products or dependency caches are required. Xcode, Java 17, Python 3 and network access to GitHub/dependency hosts must be available. The workflow retains Xcode 16.2; a local run records its own toolchain and does not claim equivalence to that hosted environment.

```sh
repro_commit='<full SHA with accepted hosted evidence>'
repro_base=$(mktemp -d /private/tmp/native-contract-repro.XXXXXX)
git clone https://github.com/ohioshirt/native-contract-poc.git "$repro_base/current"
git -C "$repro_base/current" checkout --detach "$repro_commit"
cd "$repro_base/current"
bash scripts/reproduce-evolution.sh --commit "$repro_commit" --output "$PWD/reports/reproduction-01"
```

Repeat in another empty clone with another output directory. Output must be a new directory below the candidate's `reports/`; existing output is refused. Default mode requires a clean candidate with no existing build/cache directories. It assigns separate clone-local Gradle and Swift caches to candidate and baseline; dependencies are downloaded again. Swift build commands use a clone-local SwiftPM cache and local manifest caching with shared dependency caching disabled. Python bytecode uses `.python-cache/` inside the candidate. Do not set `SKIP_MUTATIONS=1`.

The entry point fetches baseline `8458f66a0691532a7f48e7ca1fb14fc86238b67f` into a separate checkout, builds only its `AsyncTraceRunner` and Kotlin `:async-library:installDist`, and preserves those executables/distribution files. It writes new SHA-256 values to `baseline-hashes.json`. Historical hash values are not acceptance inputs.

`toolchains.json` and controller command/stdout/stderr logs retain toolchain, OS, network policy, cache paths and build evidence. Generated config uses runtime paths, protects both baseline files and their hash mapping, and excludes only Git metadata, generated reports and known build/cache/bytecode directories. Evaluator sources remain protected. Freeze produces a new manifest and independently retained `manifest-digest.txt`; old evidence is never overwritten.

Acceptance requires old-native `SEMANTIC_FAIL`, candidate full `PASS` including mutations and managed API probes, and `check --result` binding for both. A bound RED retains its failed evaluation and exits 1. Infrastructure failures, skipped gates, incomplete histories or insufficient concurrency overlap cannot satisfy acceptance. The protocol checks unchanged candidate digests around each stage and binds command, stdout/stderr and artifact hashes to each attempt. Inspect `reproduction.json`, `attempts/*/result.json` and `attempts/candidate-full-01/full/report.md`; a missing summary means the controller did not complete acceptance.

For a reviewed precommit evaluator revision only, `--allow-working-copy` permits source changes and warm candidate caches. Its summary is explicitly marked `workingCopyMode: true` and is not clean-clone acceptance. Refreeze into a new output directory after every evaluator change.

Swift concurrency declarations have scoped macOS 10.15 / iOS 13 / tvOS 13 / watchOS 6 availability. The synchronous library and numeric async reducer retain their existing package floor. `swift-availability` explicitly compiles against Intel macOS 10.13, including the managed external positive client and tests, so an updated host/default SwiftPM target cannot conceal missing availability. The ordinary external API probes still compile independently and verify emitted-token reuse and access restrictions.

Guarantees remain bounded: finite formal models and observed native histories, with recorded token provenance and real-time ordering. This does not prove arbitrary-length native refinement or cancellation of actual network operations. Binary byte equality and identical thread schedules across runs are not required.

## Regression evidence during implementation

The explicit legacy-target check first rejected the unannotated `ManagedAsyncSession` actor. After scoped availability was added, this command completed:

```sh
bash scripts/swift-availability-check.sh reports/ci-repair/availability-green-6
```

```text
Explicit macOS 10.13 compilation with scoped concurrency availability: PASS
```

The reporting regression first observed missing `swift-runner.command.log`, `kotlin-runner.command.log` and `async-runner.command.log` on build failure. After the fix:

```sh
python3 -m unittest verification.test_verify_reporting -v
```

```text
test_failed_builds_record_not_run_without_missing_log_warnings (verification.test_verify_reporting.VerifyReportingTests) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.797s

OK
```

These are local regression records, not hosted workflow or clean-clone acceptance. Full execution evidence is generated independently per run by the entry point.

## Observed concurrency and scheduler variability

A start barrier creates live callers but cannot guarantee overlapping API invocation intervals on every scheduler. Unit tests therefore accept either a complete observed overlap trial or the final complete trial after the specified 20-trial budget. A deterministic same-phase dependency-chain test checks that the runner retains trial 19 and strict real-time order without fabricating overlap. The external gate continues to classify insufficient observed overlap as INCONCLUSIVE, never PASS.

The independently frozen simultaneous-expiration workload retains both expiration calls and its original snapshots, adding independent TokenExpired callers within the 16-operation bound, while retaining exactly one snapshot in that phase. Any overlapping pair therefore contains an expiration call. More actual callers improve the chance of observing real concurrency without moving invocation stamps, inserting waits inside measured call intervals, changing API behavior or weakening the checker. Scheduler determinism is still not claimed. All attempts, including insufficient-coverage attempts, remain evidence.
