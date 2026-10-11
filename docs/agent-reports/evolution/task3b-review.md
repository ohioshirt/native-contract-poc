# Task3B independent Swift review

Verdict: APPROVED for the scoped Swift native implementation. No important defects found.

Review worktree: /Users/shigeo/.codex/worktrees/b195/native-contract-poc.
Date: 2026-10-12.

## Scope and method

Read docs/agent-reports/evolution/task3b.md, the frozen managed-native-brief.md and managed-history-format.md, and evolution-design.md sections C, D, R3 and R4. Reviewed ManagedAsyncSession.swift, ManagedHistoryRunner/HistoryProcessor.swift and RunnerMain.swift, both managed test files, and the ios/Package.swift diff. Read the Swift low-level session/reducer to trace delegation. Read the frozen workload and supplied Task3B raw evidence. No Kotlin source was read.

No source edits, builds, test runs, nested agents, staging or commits were performed during this review. The parent owns the aggregate frozen gate, external public API probes and native owner-guard mutation checks. This approval is source-review evidence, not a claim that those pending gates passed.

## Ownership and actor semantics

- ManagedAsyncSession.swift:3-18: each final immutable RefreshRequest retains one private RequestOwner reference. The empty final owner class and immutable request fields satisfy checked Sendable conformance. The token initializer and belongs helper are fileprivate. Ordinary external source clients have no token constructor/copy/deserializer or owner/low-level-session access; the actor exposes only the declared fresh-session initializer, handle and snapshot, with no restore/copy API.
- ManagedAsyncSession.swift:46-85: the actor owns one private AsyncSession and a distinct retained owner. handle contains no await or callback; validation, numeric reduction, effect/token creation and the complete triple snapshot occur in one actor-isolated operation. snapshot uses the same isolation. Actor aliases therefore share one history.
- ManagedAsyncSession.swift:65-73: both response kinds pass through the single exact frozen owner guard before numeric correlation. A foreign token returns the unchanged complete snapshot, empty effects and ForeignRequest even when the addressed session has no pending request. Matching-owner stale/duplicate tokens delegate to the existing numeric correlation.
- ManagedSnapshot and ManagedResult use immutable value fields, with Swift Array value semantics detaching caller mutations. Tokens inside effects are themselves immutable. Exhaustion is mapped from the low-level rejection without allocator changes; the low-level MAX handling avoids overflow.

## Completed-history runner

- HistoryProcessor.swift:4-106 and 180-254: signed64 identifiers are decoded, retained and encoded as Int64. Snapshot null fields and result rejection are explicitly encoded; absent optional token/event fields are omitted as required. Declared IDs, owners, phases, dependencies, seed and tokenRef metadata are carried into the recorded history. Inventory validation rejects duplicates, invalid references and dependency cycles before launch.
- HistoryProcessor.swift:108-133 and 256-334: each phase creates actual TaskGroup child callers behind one shared actor barrier. All children arrive before release; the last arrival resumes and removes the waiting continuations. The short NSLock recorder is shared across all owners in a trial and is never held over an API call or await. Invocation and return stamps directly surround the actual handle/snapshot await.
- HistoryProcessor.swift:140-178 and 269-308: dependencies wait on actual completion. A producer return is stamped before its actual emitted RefreshRequest objects are published in CompletionStore. A consuming response retrieves that same object and retains producer owner/ID metadata rather than manufacturing a numeric token. Missing effects throw. Completion resumes/removes dependency waiters, and failure wakes all pending waiters with an error; later waits see the stored failure.
- The validated dependency graph is acyclic, and all phase callers have passed the barrier before dependency waiting or cancellation checks. An operation error calls store.fail before propagation, so dependent children are released and the throwing group joins its children rather than yielding a completed subset. RunnerMain writes stdout only after the entire process succeeds, and errors exit nonzero.
- HistoryProcessor.swift:188-201 and 340-346: retries create fresh sessions, clock, store and complete histories. Selection retains exactly one complete observed trial. The overlap predicate uses actual invocation intervals and neither synthesizes expected results nor mixes rows. Insufficient overlap is emitted for the external checker to classify, as required by the brief.

## Tests and supplied evidence

The managed tests directly exercise foreign equal-number responses of both kinds, foreign-before-stale ordering, cancellation by Logout, duplicate and stale responses, aliases, retained snapshots/effects, signed64 boundary allocation/exhaustion, and concurrent handle/snapshot observations. Runner tests inspect exact MAX provenance and metadata, phase edges and shared timestamp uniqueness/overlap, plus missing actual producer effects.

Inspected the worker's commands.txt and raw managed-tests.log, runner-tests.log, and linearizability.json tails. They are prior worker evidence; no test totals or fresh pass claims are made here. The independent parent gate remains authoritative for final acceptance.

## Limits

This review supports the stated in-process ordinary-source ownership boundary and completed-history implementation. It does not establish unbounded native refinement, liveness, physical effect execution order, transport authenticity, or a guarantee that OS scheduling produces overlap in every trial. Those limits match the approved design.
