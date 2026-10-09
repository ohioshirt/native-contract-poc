# Async Response Correlation Implementation Plan

> **For agentic workers:** Use parallel independent Luna implementation as explicitly requested; Sol-role fixes spec, evaluates gates and controls fixes.

**Goal:** Ignore stale refresh completions using non-reused per-instance request IDs, preserving existing core behavior.
**Architecture:** Independent typed native adapters, canonical JSON async rows, independent oracle/abstract formal model and isolated mutation matrices.
**Tech Stack:** Existing SwiftPM/Kotlin/JVM/Python/TLC/macOS CI versions.
**Spec:** ../specs/2026-10-09-async-correlation-design.md

## Global Constraints
- Canonical v3 spec is immutable to workers; core flat table/legacy native sources stay behavior-identical.
- No cross-language source reads, code generation/interpreter in native body, distribution or OS/network APIs.
- Current Refreshing Logout policy is explicit existing ignore; no inferred cancellation approval.
- Exact signed64 ID comparison; no wrapping/reuse; boundary rejection atomic.
- Preserve all existing tests/gates; stdout JSON separate diagnostics; malformed input no partial output.
- Only explicit staging paths; command/raw tail evidence for counts; no worker commit/agents.

## Review Focus
- Stale ID after a second request or logout/login must not change session/effects.
- Bool/fraction/exponent/overflow ID input must reject consistently.
- ID maximum can be allocated once; next allocation rejects without mutation.
- Kotlin counter reset or same bug on both sides detected by independent oracle.
- Abstract TLC CURRENT/STALE model is not numeric or native refinement proof.

### Task 1: Luna Swift
Files: ios/Package.swift, ios/Sources/AsyncNativeContract, ios/Sources/AsyncTraceRunner, ios/Tests/AsyncNativeContractTests, docs/agent-reports/async-swift.md.
Consumes fixed v3 async profile/wire. Produces AsyncTraceRunner and typed library adapter; may use own NativeContract reducer.
- [ ] Tests first for correlation, stale/duplicate, logout/login, current ignored R logout, ID range/exhaustion and runner validation.
- [ ] Implement idiomatic adapter/strict runner; preserve legacy sources/tests.
- [ ] Run Swift build/tests and CLI fixtures; report exact unique stale-guard mutation patch site and raw evidence. No Android reads.

### Task 2: Luna Kotlin
Files: android/settings.gradle.kts, android/async-library/*, docs/agent-reports/async-kotlin.md.
Consumes same fixed profile/wire. Produces async-library installDist runner plus typed API; own core dependency allowed.
- [ ] Tests first for same specified behavior/boundaries/invalid input.
- [ ] Implement Kotlin/JVM adapter, strict JSON runner and Gradle target; preserve library core sources/tests.
- [ ] Build/tests/installDist, raw evidence, unique stale guard + acceptedLogout counter-reset patch sites. No Swift reads.

### Task 3: Luna Verification
Files: contract/schema.json, verification/contract.py (schema enum support only/asynchronous validation integration), verification/async_*.py, verification/test_async.py, formal/AsyncSession.tla, scripts/async-verify.sh, scripts/async-mutation-test.sh, scripts/verify.sh, verification/async-mutation-matrix.json, README.md, workflow optional label, docs/agent-reports/async-verification.md.
Consumes immutable canonical async spec and runner paths. Produces independent oracle, vectors, strict async comparator/reports, exact async mutation matrix and finite abstract TLC gate.
- [ ] Extend schema/semantic validation without weakening prior tests; test guard/action/range/type failures.
- [ ] Implement length0–5 input generator plus named long/boundary cases, independent oracle and direct ID-inclusive comparator.
- [ ] Add new native installs/runners and async gates to full verify; preserve core/formal/native mutations and no unsafe output deletion.
- [ ] Add isolated async mutation source patches after worker patch sites available; compilation/crash never kill.
- [ ] Implement actual abstract TLC positive/negative control with pinned tool/output safety; document freshness/routing/no numeric refinement assumptions.
- [ ] Run own meaningful tests/TLC, report raw tails, signal stable DONE. Root runs all native/CI after workers stop edits.

### Task 4: Sol-role quality and acceptance
- [ ] Check core/native preservation and canonical spec hash before/after delegation.
- [ ] AI review, delegate any fixes, run all old/new local gates and exact matrices.
- [ ] Preserve evidence, counts from output and explicit correction ledger.
- [ ] Commit explicit paths, push authorized public main and verify hosted artifacts.
- [ ] If user chooses cancellation, separately update async R×Logout row/profile, delegate focused changes and reverify; do not silently change frozen spec mid-run.
