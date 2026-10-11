package nativecontract.async

import java.util.Collections

/** A request issued by one retained owner; ordinary callers cannot construct or reassign it. */
class RefreshRequest private constructor(val requestId: Long, private val owner: Any) {
    internal fun belongsTo(candidate: Any): Boolean = owner === candidate

    internal companion object {
        fun issue(requestId: Long, owner: Any): RefreshRequest = RefreshRequest(requestId, owner)
    }
}

sealed interface ManagedEvent {
    data object LoginSucceeded : ManagedEvent
    data object Logout : ManagedEvent
    data object TokenExpired : ManagedEvent
    class RefreshSucceeded(val request: RefreshRequest) : ManagedEvent
    class RefreshFailed(val request: RefreshRequest) : ManagedEvent
}

sealed interface ManagedEffect {
    data object ClearCredentials : ManagedEffect
    class RequestTokenRefresh(val request: RefreshRequest) : ManagedEffect
}

enum class ManagedRejection { ForeignRequest, RequestIdExhausted }

data class ManagedSnapshot(val state: AsyncState, val pendingRequestId: Long?, val nextRequestId: Long?)

class ManagedResult(
    val snapshot: ManagedSnapshot,
    effects: List<ManagedEffect>,
    val rejection: ManagedRejection? = null,
) {
    val effects: List<ManagedEffect> = Collections.unmodifiableList(ArrayList(effects))
}

/**
 * One authoritative session. Reduction, request creation and observation share one private monitor;
 * effects describe work for the caller and never execute callbacks while the monitor is held.
 */
class ManagedAsyncSession(nextRequestId: Long = 1L) {
    private val monitor = Any()
    private val owner = Any()
    private val session = AsyncSession(nextRequestId)

    fun snapshot(): ManagedSnapshot = synchronized(monitor) { currentSnapshot() }

    fun handle(event: ManagedEvent): ManagedResult = synchronized(monitor) {
        val request = when (event) {
            is ManagedEvent.RefreshSucceeded -> event.request
            is ManagedEvent.RefreshFailed -> event.request
            else -> null
        }
        if (request != null) {
            if (!request.belongsTo(owner)) {
                return@synchronized ManagedResult(currentSnapshot(), emptyList(), ManagedRejection.ForeignRequest)
            }
        }
        val lowLevelEvent = when (event) {
            ManagedEvent.LoginSucceeded -> AsyncEvent.LoginSucceeded
            ManagedEvent.Logout -> AsyncEvent.Logout
            ManagedEvent.TokenExpired -> AsyncEvent.TokenExpired
            is ManagedEvent.RefreshSucceeded -> AsyncEvent.RefreshSucceeded(event.request.requestId)
            is ManagedEvent.RefreshFailed -> AsyncEvent.RefreshFailed(event.request.requestId)
        }
        val result = session.handle(lowLevelEvent)
        val effects = result.effects.map { effect ->
            when (effect) {
                AsyncEffect.ClearCredentials -> ManagedEffect.ClearCredentials
                is AsyncEffect.RequestTokenRefresh -> ManagedEffect.RequestTokenRefresh(RefreshRequest.issue(effect.requestId, owner))
            }
        }
        ManagedResult(currentSnapshot(), effects, result.rejection?.let { ManagedRejection.RequestIdExhausted })
    }

    private fun currentSnapshot() = ManagedSnapshot(session.state, session.pendingRequestId, session.nextRequestId)
}
