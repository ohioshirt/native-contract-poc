# iOS ledger shards implementation plan

> **For agentic workers:** Use superpowers:executing-plans; implementation is inline, design and final code review use a subagent as requested by the user. Follow tasks in order and retain RED/GREEN evidence.

**Goal:** Run every frozen iOS APP case in four parallel native ledgers and retain the existing five-stage acceptance verdict.

**Architecture:** Freeze four fixed shard stages in addition to the existing stages. Every shard has disjoint complete scenario/variant membership and independently verified build identity. Aggregate their checked ledgers into a derived candidate-ios row; the auxiliary ledger holds RED, iOS controls and legacy-full.

**Tech Stack:** Python 3.12.8, unittest, GitHub Actions YAML, existing Swift/Kotlin native harnesses.

**Spec:** [ios-ledger-shards-design.md](ios-ledger-shards-design.md).

## Global Constraints

- Four shards named candidate-ios-shard-1 through candidate-ios-shard-4; each timeoutSeconds=1800.
- Original SUITE_STAGES and full local candidate-ios execution remain available.
- Keep checker semantics and APP/CTRL inventories unchanged.
- Each shard keeps all variants of its assigned scenarios, in original inventory order.
- Existing maxAttempts=10, maxTotalSeconds=21600, maxAttemptsPerStage=2 remain enforced across physical ledgers.
- Staging always uses explicit paths; exclude session handoff and reports.
- No main-branch implementation; use a task branch in the existing checkout (previous sandbox worktree fallback).
- Publish only a concrete reviewed/tested change. Record hosted execution separately from local verification.

## Review Focus

- A partially declared shard set or overlapping scenario/variant must never become full PASS.
- A non-PASS shard, missing native case, or source/build mismatch must remain visible after aggregation.
- Extra attempts across independently produced ledgers must remain subject to global budgets.
- Filtering must not accept unknown IDs, controls inventories, or changes in original full-inventory behavior.
- Matrix artifacts and owned devices must remain isolated; fail-fast must not cancel sibling evidence.

### Task 1: Frozen shard protocol

**Files:** integration/protocol_config.py, verification/change_protocol.py, integration/tests/test_ios_shards.py.

**Interfaces:** Produce IOS_SHARD_STAGES (fixed tuple), ios_shard_scenarios(rows) -> list[list[dict]], and stage declarations in build_config. Each declaration has complete expectedTraceBindings.

- [ ] Add tests asserting the design's exact partition, 1800s timeouts and complete variant coverage; reject partial declarations, overlap, missing IDs and unknown shard names.
- [ ] Run `python -m unittest integration.tests.test_ios_shards.FrozenShardTests -v`; expect failures because shard stages are absent.
- [ ] Implement deterministic weighted partition and narrowly extend config validation for the fixed shard names. Validate nonempty canonical subsets, pairwise disjointness and full union.
- [ ] Run focused tests and existing protocol/config regressions; expect OK.

### Task 2: Bound subset execution

**Files:** integration/controller.py, integration/reproduce.py, integration/tests/test_ios_shards.py.

**Interfaces:** Consume IOS_SHARD_STAGES. Add run_platform(..., scenario_subset=False); shard callers alone pass True. run_stages accepts original stages plus the fixed shard tuple.

- [ ] Test filtered inventory copies retain all variants and original order; unknown/missing IDs, control subsets and unordered IDs are rejected before running devices. Existing full inventory mismatch remains INVALID_HISTORY.
- [ ] Test shard stage dispatch and a bound run_stages ledger using controlled runner dependencies.
- [ ] Run focused tests; expect absent subset API / rejected shard dispatch failures.
- [ ] Implement explicit subset selection and canonical copied-inventory digest before device work; preserve full-mode equality validation.
- [ ] Extend reproduce only for fixed shards; run focused and existing controller/protocol regressions; expect OK.

### Task 3: Portable shard aggregation

**Files:** integration/aggregate.py, integration/tests/test_ios_shards.py, integration/tests/test_aggregate.py.

**Interfaces:** Extend aggregate_ledgers with ios_shard_ledgers=None (four roots in fixed order). Existing ios_ledger remains supported; in shard mode it holds integration-red/integration-controls/legacy-full. Add repeatable --ios-shard-ledger CLI option. Produce derivedCandidateIos with each shard's checked classification, build/device identity and case coverage.

- [ ] Add tests for all PASS, each non-PASS category, missing/duplicate ledgers, mixed old-full-ledger+shards, native inventory mismatch and total/per-stage budget overflow; retain old mode regression.
- [ ] Run focused aggregation tests; expect absent shard API / full-inventory replay failures.
- [ ] Verify every imported ledger through existing ownership/command/artifact checks. Replay each native shard against its frozen subset of the original protected inventory.
- [ ] Derive candidate-ios by conjunction, propagate worst non-PASS, count only actual physical attempts/durations; controls retain both-candidate dependency.
- [ ] Run focused and existing aggregation tests; expect OK.

### Task 4: Workflow and complete verification

**Files:** .github/workflows/integration.yml, integration/tests/test_protocol.py, integration/tests/test_ios_shards.py, design/plan docs.

**Interfaces:** Matrix ledger names ios-auxiliary and ios-shard-1..4; individually named artifacts. Acceptance job supplies auxiliary root and four ordered shard roots.

- [ ] Add workflow contract tests for exact matrix stage membership, fail-fast=false, unique artifact names, isolated import roots and complete aggregate arguments.
- [ ] Run workflow tests; expect current serial workflow to fail the new contract.
- [ ] Implement matrix, explicit stage array construction, role-specific progress summaries and artifact imports. Preserve SHA pins, labels, progress streaming and owned-device cleanup.
- [ ] Run full integration and verification unittest suites on exact Python, YAML parsing, shell syntax, fresh freeze and bound RED/check. Store commands and raw tails under reports/standalone/ios-shards-20261014/.
- [ ] Request whole-diff subagent review; repair blocking findings with failing regression first, then rerun affected/full gates.
- [ ] Present concrete diff and logs before publication; after authorization, commit explicit paths and run hosted CI against that commit. Report actual five-stage aggregate and limitations.

## Execution record

Progress/evidence are kept in reports/standalone/ios-shards-20261014/. The user's request to have a subagent review and then proceed replaces another human design/plan confirmation. Implementation stays inline; reviewer delegation is limited to review. No test, native execution or CI success is inferred from review approval.

The user selected local merge into main after implementation review. Publication and hosted shard CI remain pending; local merge does not establish native acceptance. Tasks 1–3 and Task 4's local checks are implemented and verified. The deferred minor is a TypeError while reporting non-list scalar required_scenario_ids, outside the typed/frozen caller contract; it cannot produce false PASS.
