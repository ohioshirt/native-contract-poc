package nativecontract

enum class SessionState { Unauthenticated, Authenticated, Refreshing }
enum class SessionEvent { LoginSucceeded, Logout, TokenExpired, RefreshSucceeded, RefreshFailed }
enum class Effect { RequestTokenRefresh, ClearCredentials }

data class Transition(val state: SessionState, val effects: List<Effect> = emptyList())

class SessionReducer(initialState: SessionState = SessionState.Unauthenticated) {
    var state: SessionState = initialState
        private set

    fun handle(event: SessionEvent): Transition {
        val transition = when (state) {
            SessionState.Unauthenticated -> when (event) {
                SessionEvent.LoginSucceeded -> Transition(SessionState.Authenticated)
                SessionEvent.Logout, SessionEvent.TokenExpired, SessionEvent.RefreshSucceeded,
                SessionEvent.RefreshFailed -> Transition(SessionState.Unauthenticated)
            }
            SessionState.Authenticated -> when (event) {
                SessionEvent.LoginSucceeded -> Transition(SessionState.Authenticated, listOf(Effect.ClearCredentials))
                SessionEvent.RefreshSucceeded, SessionEvent.RefreshFailed -> Transition(SessionState.Authenticated)
                SessionEvent.Logout -> Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials))
                SessionEvent.TokenExpired -> Transition(SessionState.Refreshing, listOf(Effect.RequestTokenRefresh))
            }
            SessionState.Refreshing -> when (event) {
                SessionEvent.LoginSucceeded, SessionEvent.Logout, SessionEvent.TokenExpired ->
                    Transition(SessionState.Refreshing)
                SessionEvent.RefreshSucceeded -> Transition(SessionState.Authenticated)
                SessionEvent.RefreshFailed -> Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials))
            }
        }
        state = transition.state
        return transition
    }
}
