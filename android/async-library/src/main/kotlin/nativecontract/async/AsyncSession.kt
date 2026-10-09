package nativecontract.async

enum class AsyncState { Unauthenticated, Authenticated, Refreshing }
enum class AsyncRejection { RequestIdExhausted }

sealed interface AsyncEvent {
    data object LoginSucceeded : AsyncEvent
    data object Logout : AsyncEvent
    data object TokenExpired : AsyncEvent
    /** requestId must be a positive signed 64-bit ID issued to this same logical session. */
    data class RefreshSucceeded(val requestId: Long) : AsyncEvent
    /** requestId must be a positive signed 64-bit ID issued to this same logical session. */
    data class RefreshFailed(val requestId: Long) : AsyncEvent
}

sealed interface AsyncEffect {
    data object ClearCredentials : AsyncEffect
    data class RequestTokenRefresh(val requestId: Long) : AsyncEffect
}

data class AsyncResult(
    val state: AsyncState,
    val pendingRequestId: Long?,
    val effects: List<AsyncEffect> = emptyList(),
    val rejection: AsyncRejection? = null,
)

data class AsyncSnapshot(val state: AsyncState, val pendingRequestId: Long?, val nextRequestId: Long?)

/**
 * Caller-owned state machine scoped to one logical session. Keep one authoritative instance for that
 * session and route each response back to the same instance; IDs alone do not identify an instance.
 * Calls require caller serialization. This mutable class is not thread-safe.
 */
class AsyncSession(nextRequestId: Long = 1L) {
    init { require(nextRequestId > 0) { "nextRequestId must be a positive signed 64-bit integer" } }

    var state: AsyncState = AsyncState.Unauthenticated
        private set
    var pendingRequestId: Long? = null
        private set
    var nextRequestId: Long? = nextRequestId
        private set

    fun snapshot() = AsyncSnapshot(state, pendingRequestId, nextRequestId)

    fun handle(event: AsyncEvent): AsyncResult {
        val isResponse = event is AsyncEvent.RefreshSucceeded || event is AsyncEvent.RefreshFailed
        val responseId = when (event) {
            is AsyncEvent.RefreshSucceeded -> event.requestId
            is AsyncEvent.RefreshFailed -> event.requestId
            else -> null
        }
        if (isResponse && (state != AsyncState.Refreshing || pendingRequestId != responseId)) {
            return result() // PATCH_SITE_STALE_RESPONSE_GUARD
        }

        if (event == AsyncEvent.TokenExpired && state == AsyncState.Authenticated && nextRequestId == null) {
            return result(rejection = AsyncRejection.RequestIdExhausted)
        }

        var effects: List<AsyncEffect> = emptyList()
        when (state) {
            AsyncState.Unauthenticated -> when (event) {
                AsyncEvent.LoginSucceeded -> state = AsyncState.Authenticated
                else -> Unit
            }
            AsyncState.Authenticated -> when (event) {
                AsyncEvent.LoginSucceeded -> effects = listOf(AsyncEffect.ClearCredentials)
                AsyncEvent.Logout -> {
                    state = AsyncState.Unauthenticated
                    pendingRequestId = null
                    effects = listOf(AsyncEffect.ClearCredentials)
                    // PATCH_SITE_ACCEPTED_LOGOUT_COUNTER_RESET
                }
                AsyncEvent.TokenExpired -> {
                    val allocated = checkNotNull(nextRequestId)
                    pendingRequestId = allocated
                    nextRequestId = if (allocated == Long.MAX_VALUE) null else allocated + 1
                    state = AsyncState.Refreshing
                    effects = listOf(AsyncEffect.RequestTokenRefresh(allocated))
                }
                else -> Unit
            }
            AsyncState.Refreshing -> when (event) {
                is AsyncEvent.RefreshSucceeded -> { state = AsyncState.Authenticated; pendingRequestId = null }
                is AsyncEvent.RefreshFailed -> { state = AsyncState.Unauthenticated; pendingRequestId = null; effects = listOf(AsyncEffect.ClearCredentials) }
                else -> Unit // Refreshing × Logout remains ignored.
            }
        }
        return result(effects)
    }

    private fun result(effects: List<AsyncEffect> = emptyList(), rejection: AsyncRejection? = null) =
        AsyncResult(state, pendingRequestId, effects, rejection)
}
