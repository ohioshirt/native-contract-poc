public enum AuthState: String, CaseIterable, Sendable {
    case unauthenticated = "Unauthenticated"
    case authenticated = "Authenticated"
    case refreshing = "Refreshing"
}

public enum AuthEvent: String, CaseIterable, Sendable {
    case loginSucceeded = "LoginSucceeded"
    case logout = "Logout"
    case tokenExpired = "TokenExpired"
    case refreshSucceeded = "RefreshSucceeded"
    case refreshFailed = "RefreshFailed"
}

public enum AuthEffect: String, CaseIterable, Sendable {
    case requestTokenRefresh = "RequestTokenRefresh"
    case clearCredentials = "ClearCredentials"
}

public struct TransitionResult: Equatable, Sendable {
    public let state: AuthState
    public let effects: [AuthEffect]

    public init(state: AuthState, effects: [AuthEffect]) {
        self.state = state
        self.effects = effects
    }
}

/// A synchronous reducer. Callers serialize access to a session.
public struct AuthReducer: Sendable {
    public private(set) var state: AuthState

    public init(initialState: AuthState = .unauthenticated) {
        self.state = initialState
    }

    @discardableResult
    public mutating func handle(_ event: AuthEvent) -> TransitionResult {
        let result: TransitionResult
        switch (state, event) {
        case (.unauthenticated, .loginSucceeded):
            result = TransitionResult(state: .authenticated, effects: [])
        case (.unauthenticated, .logout),
             (.unauthenticated, .tokenExpired),
             (.unauthenticated, .refreshSucceeded),
             (.unauthenticated, .refreshFailed):
            result = TransitionResult(state: .unauthenticated, effects: [])
        case (.authenticated, .loginSucceeded):
            result = TransitionResult(state: .authenticated, effects: [.clearCredentials])
        case (.authenticated, .logout):
            result = TransitionResult(state: .unauthenticated, effects: [.clearCredentials])
        case (.authenticated, .tokenExpired):
            result = TransitionResult(state: .refreshing, effects: [.requestTokenRefresh])
        case (.authenticated, .refreshSucceeded),
             (.authenticated, .refreshFailed):
            result = TransitionResult(state: .authenticated, effects: [])
        case (.refreshing, .loginSucceeded),
             (.refreshing, .logout),
             (.refreshing, .tokenExpired):
            result = TransitionResult(state: .refreshing, effects: [])
        case (.refreshing, .refreshSucceeded):
            result = TransitionResult(state: .authenticated, effects: [])
        case (.refreshing, .refreshFailed):
            result = TransitionResult(state: .unauthenticated, effects: [.clearCredentials])
        }
        state = result.state
        return result
    }
}
