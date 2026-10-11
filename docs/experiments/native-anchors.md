# Frozen native mutation anchors

These low-level snippets are evaluator inputs for contract v4. Native workers must implement these exact snippets, including comments and whitespace. Core reducer behavior remains unchanged. The snippets contain no allocator reset in Logout: exhaustion (`nil`/`null`) stays exhausted. Response guards remain exact and continue to reject stale IDs.

## LOW LEVEL — Swift

### INSERT this complete case

Insert this switch case before the general `.loginSucceeded, .logout, .tokenExpired` branch. No core source change is needed.

<!-- fixture:ios/Sources/AsyncNativeContract/AsyncSession.swift -->
```swift
        case .logout where state == .refreshing:
            state = .unauthenticated // PATCH_SITE_REFRESHING_LOGOUT_STATE
            pendingRequestId = nil // PATCH_SITE_REFRESHING_LOGOUT_PENDING
            // PATCH_SITE_REFRESHING_LOGOUT_COUNTER_PRESERVED
            return result(effects: [.clearCredentials]) // PATCH_SITE_REFRESHING_LOGOUT_EFFECT
```

### PRESERVE existing anchor line (do not insert)

Keep this guard in its existing response branch.

<!-- fixture:ios/Sources/AsyncNativeContract/AsyncSession.swift -->
```swift
            guard state == .refreshing, pendingRequestId == requestId else {
```

## LOW LEVEL — Kotlin

### INSERT this complete branch

Insert the Logout branch in `AsyncState.Refreshing`; keep the existing accepted-Logout counter-reset comment.

<!-- fixture:android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt -->
```kotlin
                AsyncEvent.Logout -> {
                    state = AsyncState.Unauthenticated // PATCH_SITE_REFRESHING_LOGOUT_STATE
                    pendingRequestId = null // PATCH_SITE_REFRESHING_LOGOUT_PENDING
                    effects = listOf(AsyncEffect.ClearCredentials) // PATCH_SITE_REFRESHING_LOGOUT_EFFECT
                    // PATCH_SITE_REFRESHING_LOGOUT_COUNTER_PRESERVED
                }
```

### PRESERVE existing anchor lines (do not insert)

Keep the response guard and counter-reset marker at their existing locations. The two lines below are independent matching fragments, not a code block to insert.

<!-- fixture:android/async-library/src/main/kotlin/nativecontract/async/AsyncSession.kt -->
```kotlin
        if (isResponse && (state != AsyncState.Refreshing || pendingRequestId != responseId)) {
                    // PATCH_SITE_ACCEPTED_LOGOUT_COUNTER_RESET
```

## Matrix semantics

`verification/async-mutation-matrix.json` retains stale-response and accepted-Logout reset controls and adds each language's ignored Refreshing Logout, omitted ClearCredentials, retained pending ID and allocator-reset controls. Each mutant must build successfully, then fail the fixed semantic comparator. Build failure is INFRA_FAILURE. The existing driver applies exactly one textual match in isolated copies and cannot edit the evaluator.

`AsyncMutationFixtureTests` checks every low-level patch against the frozen snippets before native work. `AsyncNativeMutationAnchorTests` checks every patch against real sources and is deferred until the native workers have implemented the snippets; the latter test must then run without skips. Fixture matching demonstrates executable patch formation, not a native mutation kill.

Managed owner-guard anchors and their dedicated history mutation matrix are documented in the separate managed runner guide owned by Task 5/6.
