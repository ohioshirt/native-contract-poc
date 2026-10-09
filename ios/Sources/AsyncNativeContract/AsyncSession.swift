import NativeContract

/// Response IDs must be positive signed 64-bit IDs issued by the same logical session.
/// Nonpositive response IDs are outside the valid native event domain.
public enum AsyncAuthEvent: Equatable {
    case loginSucceeded
    case logout
    case tokenExpired
    case refreshSucceeded(requestId: Int64)
    case refreshFailed(requestId: Int64)
}

public enum AsyncAuthEffect: Equatable {
    case requestTokenRefresh(requestId: Int64)
    case clearCredentials
}

public enum AsyncAuthRejection: String, Equatable {
    case requestIdExhausted = "RequestIdExhausted"
}

public struct AsyncTransitionResult: Equatable {
    public let state: AuthState
    public let pendingRequestId: Int64?
    public let effects: [AsyncAuthEffect]
    public let rejection: AsyncAuthRejection?

    public init(state: AuthState, pendingRequestId: Int64?, effects: [AsyncAuthEffect], rejection: AsyncAuthRejection?) {
        self.state = state
        self.pendingRequestId = pendingRequestId
        self.effects = effects
        self.rejection = rejection
    }
}

/// A mutable value representing one logical async session.
///
/// Callers must serialize calls and retain one authoritative value per logical session.
/// Copying or restoring an `AsyncSession` snapshot creates an independent logical session
/// with its own history; route each response to the authoritative value that issued it.
/// Request IDs are unique only within that value's history. They are not globally unique
/// and do not prove authenticity or identify which session should receive a response.
public struct AsyncSession {
    public private(set) var state: AuthState = .unauthenticated
    public private(set) var pendingRequestId: Int64?
    public private(set) var nextRequestId: Int64?

    public init(nextRequestId: Int64 = 1) {
        precondition(nextRequestId > 0, "nextRequestId must be a positive signed 64-bit integer")
        self.nextRequestId = nextRequestId
    }

    @discardableResult
    public mutating func handle(_ event: AsyncAuthEvent) -> AsyncTransitionResult {
        switch event {
        case .refreshSucceeded(let requestId), .refreshFailed(let requestId):
            // Mutation-test anchor: removing this guard accepts stale/duplicate replies.
            guard state == .refreshing, pendingRequestId == requestId else {
                return result(effects: [])
            }
            var reducer = AuthReducer(initialState: state)
            let coreEvent: AuthEvent = switch event {
            case .refreshSucceeded: .refreshSucceeded
            case .refreshFailed: .refreshFailed
            default: preconditionFailure("response switch invariant")
            }
            let transition = reducer.handle(coreEvent)
            state = transition.state
            pendingRequestId = nil
            return result(effects: transition.effects.map(mapEffect))
        case .tokenExpired where state == .authenticated:
            guard let requestId = nextRequestId else {
                return result(effects: [], rejection: .requestIdExhausted)
            }
            var reducer = AuthReducer(initialState: state)
            let transition = reducer.handle(.tokenExpired)
            state = transition.state
            pendingRequestId = requestId
            nextRequestId = requestId == Int64.max ? nil : requestId + 1
            return result(effects: [.requestTokenRefresh(requestId: requestId)])
        case .loginSucceeded, .logout, .tokenExpired:
            var reducer = AuthReducer(initialState: state)
            let coreEvent: AuthEvent = switch event {
            case .loginSucceeded: .loginSucceeded
            case .logout: .logout
            case .tokenExpired: .tokenExpired
            default: preconditionFailure("non-response switch invariant")
            }
            let transition = reducer.handle(coreEvent)
            state = transition.state
            if state == .unauthenticated, event == .logout { pendingRequestId = nil }
            return result(effects: transition.effects.map(mapEffect))
        }
    }

    private func result(effects: [AsyncAuthEffect], rejection: AsyncAuthRejection? = nil) -> AsyncTransitionResult {
        AsyncTransitionResult(state: state, pendingRequestId: pendingRequestId, effects: effects, rejection: rejection)
    }

    private func mapEffect(_ effect: AuthEffect) -> AsyncAuthEffect {
        switch effect {
        case .requestTokenRefresh: preconditionFailure("async allocation maps refresh request explicitly")
        case .clearCredentials: .clearCredentials
        }
    }
}
