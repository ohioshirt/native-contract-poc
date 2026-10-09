# Formal Model Verification Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development; preserved user execution method is parallel independent Luna work, Sol-role owns fixed design and quality.

**Goal:** Add actual TLC full finite-model verification and counterexample controls without changing native behavior.
**Architecture:** JSON→generated finite TLA data→handwritten generic model→TLC→strict dump bridge. Native conformance stays independent and bounded.
**Tech Stack:** TLC v1.7.4/2.19 pinned SHA, Java17, Python3.9+, existing macOS CI.
**Spec:** ../specs/2026-10-09-formal-model-design.md

## Global Constraints
- Preserve specification v2 SHA fe82d03428bcd33b7101aaf24ff717d3bc59035f10ec22c2719147ca9602ec11 and all native files.
- Never generate native implementation from contract/model; no fairness/liveness or arbitrary program refinement claims.
- Only exit0 is success; negative control requires actual named invariant violation and counterexample, not parser/build error.
- Explicit git paths only; actual commands/raw tails for counts and pass claims.
- Root integrates only when workers signal stable DONE, avoiding edits during active gate runs.

## Review Focus
- Generated table drops or changes a valid row: dump bridge must reject.
- Malformed/truncated dump and missing/extra observations: fail closed.
- Corrupt cached JAR and download failure: nonzero infrastructure failure.
- Negative control parser failure or process signal: never credited as invariant detection.
- Output reuse and missing completion: no stale PASS or fabricated exploration counts.

### Task 1: Luna formal model/tool runner
Files: formal/Session.tla, verification/formal/*, verification/test_formal.py, docs/agent-reports/formal-model.md.
Consumes fixed toolchain lock and design; produces python3 -m verification.formal.run --output ABS_DIR (optional --spec/--jar) and all formal artifacts.
- [ ] Write failing tests for generator/bridge/tool classification/hash/counterexample evidence.
- [ ] Implement JSON data projection, generic TLA model/config and strict state dump bridge.
- [ ] Implement verified atomic tool cache, bounded subprocess execution, full TLC run and isolated named-invariant negative control.
- [ ] Run Python tests and actual TLC positive/negative controls; retain raw logs/tails and report. Do not edit scripts/README/native/spec/lock or commit.

### Task 2: Luna CI/local integration
Files: scripts/verify.sh, scripts/formal-verify.sh, .github/workflows/verify.yml, README.md, docs/agent-reports/formal-integration.md.
Consumes Task1 CLI contract; produces mandatory formal gate in existing full script and artifact/summary evidence.
- [ ] Add thin formal wrapper, recorded formal gate, formal report append and gate logging without deleting old gates.
- [ ] Keep fixed native toolchain settings, artifacts always uploaded; include formal version/hash through its report. Cache excluded from artifact.
- [ ] README explains commands, all-reachable model scope versus bounded native traces, negative control, no liveness/native refinement proof, tool hash trust origin.
- [ ] Run bash syntax and targeted integration smoke when Task1 is ready; root performs all native gates/hosted CI. No native/spec/lock changes or commit.

### Task 3: Sol-role acceptance and publishing
- [ ] Independently inspect model/bridge invariants and negative control evidence, delegate fixes as needed.
- [ ] Run full local script with existing native/Muation and new formal gate; inspect SHA and source diffs.
- [ ] Preserve actual commands/raw tails and remaining assumptions in experiment evidence.
- [ ] Commit explicit paths, push authorized public repository and verify actual hosted CI/artifacts before final completion claim.
