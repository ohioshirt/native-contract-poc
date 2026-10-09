# Native Contract Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development; user mandates parallel independent Luna workers, overriding sequential execution and repeated human approval steps.

**Goal:** Demonstrate independent native implementations checked against a fixed machine-readable contract.
**Architecture:** Sol owns contract and quality gates; Luna A/B own distinct native trees; Luna C owns the independent Python oracle and CI.
**Tech Stack:** SwiftPM, Kotlin/JVM Gradle, Python 3, GitHub Actions macOS.
**Spec:** ../specs/2026-10-09-native-contract-design.md

## Global Constraints
- Never read the other language implementation; no native code generation or contract interpreter.
- Contract is immutable to workers. Only Sol changes it in Phase 6.
- 781 scenarios, length 0–4, each from initial state; compare every ordered effect and intermediate state.
- Stage only explicit paths. Record actual commands and raw log tails for test claims.
- No source review by human is an acceptance gate; no hosted CI claim without hosted evidence.

## Review Focus
- Empty scenario and scenario isolation: native runner tests.
- Invalid/unknown event and duplicate scenario ID: native runner rejects, verification rejects malformed traces.
- Oracle tampering/missing or duplicate steps/traces: verification tests.
- Incomplete/nondeterministic contract: validator tests.
- Mutation compile error: mutation harness treats as infrastructure failure.

### Task 1: Swift (Luna A)
Files: ios/Package.swift, ios/Sources, ios/Tests.
Consumes fixed contract and wire format from design; produces library + executable TraceRunner accepting one JSON document.
- [ ] Write unit tests for typed state/effects, all branches/defaults and runner edge cases; record failure before implementation.
- [ ] Implement independent typed state machine; add strict JSON runner.
- [ ] Run swift build and swift test, retain logs/report. Report reducer file and exact patch sites for mutations A/C. No commit by worker.

### Task 2: Kotlin (Luna B)
Files: android/settings.gradle.kts, build.gradle.kts, library, Gradle wrapper.
Consumes fixed contract/wire; produces JVM library and installDist runner at android/library/build/install/library/bin/library.
- [ ] Write unit tests for branches/defaults and runner edge cases; record failure before implementation.
- [ ] Implement native typed reducer and strict runner; pin dependencies and wrapper with checksum.
- [ ] Run ./gradlew build and unit tests, retain logs/report; report mutation B/C patch sites. No commit by worker.

### Task 3: Verification and CI (Luna C)
Files: contract/schema.json, verification, scripts, .github/workflows/verify.yml.
Consumes contract and runner interface; produces generate.py, verify.py, compare.py and local/CI commands.
- [ ] Write validator/comparator tests: duplicates, missing steps, extra effects, incomplete domain, bad schema; record red.
- [ ] Implement schema validation plus semantic total function checks, product generator and independent oracle.
- [ ] Implement strict traces, three verdicts and detailed failure report/provenance.
- [ ] Implement verify.sh with build/test logs and reports, CI artifacts/summary, isolated mutation harness.
- [ ] Run Python tests; run native integration when A/B available. No changing contract or native sources.

### Task 4: Sol integration and change experiment
- [ ] Evaluate worker artifacts and run full local verification.
- [ ] Run mutations A/B/C and verify exact expected matrix.
- [ ] Preserve v1 evidence and snapshot for Luna-only control.
- [ ] Update contract to v2; verify old native code fails without weakening tests.
- [ ] Delegate v2 changes to A/B, rerun same verification and mutations.
- [ ] Run Luna-only control in isolated snapshot; report quality/repair attempts and cost measurement limits.
- [ ] Document guarantee scope, prerequisites, limitations, reproducibility and acceptance evidence in README.
- [ ] Keep local git repository ready for GitHub private remote; hosted CI remains pending if no destination exists.
