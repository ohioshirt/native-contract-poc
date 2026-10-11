# Frozen managed native implementation brief

This evaluator-owned brief and all `verification/managed-*` fixtures are protected inputs. Native workers implement these interfaces without editing evaluator inputs. Behavior is the design R1–R5, especially retained reference owner identity and immutable detached effects.

## Public source API

Swift module `AsyncNativeContract` (also import `NativeContract` for `AuthState`):

```swift
public actor ManagedAsyncSession {
    public init(nextRequestId: Int64 = 1)
    public func handle(_ event: ManagedEvent) -> ManagedResult
    public func snapshot() -> ManagedSnapshot
}
public final class RefreshRequest: Sendable {
    public var requestId: Int64 { get }
    // No public constructor, copy, owner, or serialization access.
}
public enum ManagedEvent: Sendable {
    case loginSucceeded, logout, tokenExpired
    case refreshSucceeded(RefreshRequest), refreshFailed(RefreshRequest)
}
public enum ManagedEffect: Sendable {
    case clearCredentials, requestTokenRefresh(RefreshRequest)
}
public enum ManagedRejection: Sendable {
    case foreignRequest, requestIdExhausted
}
public struct ManagedSnapshot: Sendable {
    public var state: AuthState { get }
    public var pendingRequestId: Int64? { get }
    public var nextRequestId: Int64? { get }
}
public struct ManagedResult: Sendable {
    public var snapshot: ManagedSnapshot { get }
    public var effects: [ManagedEffect] { get }
    public var rejection: ManagedRejection? { get }
}
```

Kotlin package `nativecontract.async`: `class ManagedAsyncSession(nextRequestId: Long = 1)` with `fun handle(event: ManagedEvent): ManagedResult` and `fun snapshot(): ManagedSnapshot`. `RefreshRequest` is final with read-only `val requestId: Long`, no externally callable constructor/copy/owner or serialization. `ManagedEvent` is a sealed interface with objects `LoginSucceeded`, `Logout`, `TokenExpired`, and classes `RefreshSucceeded(val request: RefreshRequest)`, `RefreshFailed(val request: RefreshRequest)`. `ManagedEffect` is a sealed interface with object `ClearCredentials` and class `RequestTokenRefresh(val request: RefreshRequest)`. `ManagedRejection` is an enum `ForeignRequest, RequestIdExhausted`. `ManagedSnapshot` exposes read-only `state` (existing AsyncState), `pendingRequestId: Long?`, `nextRequestId: Long?`. `ManagedResult` exposes read-only `snapshot`, `effects: List<ManagedEffect>`, `rejection: ManagedRejection?`. Every result's effects collection is detached and unmodifiable, including mutable-list casts. Owned low-level session and reference owner are private.

## Stable owner mutation anchors

Each implementation handles both response kinds through one common owner guard, with exactly one occurrence of the following line in `ManagedAsyncSession.swift` / `ManagedAsyncSession.kt`. Private/internal helper names are otherwise unrestricted; the request method must compare retained reference identity.

Swift original: `if !request.belongs(to: owner) {`
Swift replacement: `if false { // MUTANT: owner guard removed`

Kotlin original: `if (!request.belongsTo(owner)) {`
Kotlin replacement: `if (false) { // MUTANT: owner guard removed`

The evaluator requires exactly one patch match, a successful mutant build, and semantic rejection of the `foreign-same-id` recorded history. A build/runtime failure does not establish mutation detection.

## Runner commands

Swift: `ios/.build/debug/ManagedHistoryRunner`, a SwiftPM executable target using actual `TaskGroup` callers.
Kotlin: `java -cp android/async-library/build/install/async-library/lib/* nativecontract.async.ManagedHistoryRunnerKt` (classpath wildcard is one argument), using threads/executor and existing JSON dependency. Keep existing `AsyncTraceRunnerKt` application main and installDist; no additional dependency needed.

Each reads the independently frozen `verification/managed-workload.json` document on stdin and emits the complete history document on stdout. Read [managed-history-format.md](managed-history-format.md) for exact shape. No expected observations are provided in the workload. Runner must record every declared setup/handle/snapshot operation, preserve response token producer references, join every caller, and fail nonzero on errors. Use one shared strictly increasing recorder across both owners. At each phase create all live callers, release a shared start barrier, then join the phase. Repeat each scenario up to 20 trials if needed to obtain observed overlap; emit one complete observed trial, recording `trial` as 0..19. Retrying changes no inventory; do not combine rows from trials. The gate reports missing overlap as INCONCLUSIVE/non-PASS. API-call invocation/return stamps immediately surround the actual call/await; barrier is before invocation. No recorder lock across API calls.
