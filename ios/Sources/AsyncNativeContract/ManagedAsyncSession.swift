import NativeContract

// Retained by every emitted token, so identity cannot be reused after a session dies.
fileprivate final class RequestOwner: Sendable {}

public final class RefreshRequest: Sendable {
    public let requestId: Int64
    private let owner: RequestOwner

    fileprivate init(requestId: Int64, owner: RequestOwner) {
        self.requestId = requestId
        self.owner = owner
    }

    fileprivate func belongs(to owner: RequestOwner) -> Bool {
        self.owner === owner
    }
}

public enum ManagedEvent: Sendable {
    case loginSucceeded, logout, tokenExpired
    case refreshSucceeded(RefreshRequest), refreshFailed(RefreshRequest)
}

public enum ManagedEffect: Sendable {
    case clearCredentials, requestTokenRefresh(RefreshRequest)
}

public enum ManagedRejection: Sendable, Equatable {
    case foreignRequest, requestIdExhausted
}

public struct ManagedSnapshot: Sendable {
    public let state: AuthState
    public let pendingRequestId: Int64?
    public let nextRequestId: Int64?
}

public struct ManagedResult: Sendable {
    public let snapshot: ManagedSnapshot
    public let effects: [ManagedEffect]
    public let rejection: ManagedRejection?
}

/// One authoritative session. Each complete reduction and snapshot is actor isolated.
public actor ManagedAsyncSession {
    private let owner = RequestOwner()
    private var session: AsyncSession

    public init(nextRequestId: Int64 = 1) {
        session = AsyncSession(nextRequestId: nextRequestId)
    }

    public func snapshot() -> ManagedSnapshot {
        ManagedSnapshot(state: session.state, pendingRequestId: session.pendingRequestId,
                        nextRequestId: session.nextRequestId)
    }

    public func handle(_ event: ManagedEvent) -> ManagedResult {
        let lowLevelEvent: AsyncAuthEvent
        switch event {
        case .loginSucceeded: lowLevelEvent = .loginSucceeded
        case .logout: lowLevelEvent = .logout
        case .tokenExpired: lowLevelEvent = .tokenExpired
        case .refreshSucceeded(let request), .refreshFailed(let request):
            if !request.belongs(to: owner) {
                return ManagedResult(snapshot: snapshot(), effects: [], rejection: .foreignRequest)
            }
            switch event {
            case .refreshSucceeded: lowLevelEvent = .refreshSucceeded(requestId: request.requestId)
            case .refreshFailed: lowLevelEvent = .refreshFailed(requestId: request.requestId)
            default: preconditionFailure("response switch invariant")
            }
        }
        let transition = session.handle(lowLevelEvent)
        let effects: [ManagedEffect] = transition.effects.map { effect in
            switch effect {
            case .clearCredentials: .clearCredentials
            case .requestTokenRefresh(let requestId):
                .requestTokenRefresh(RefreshRequest(requestId: requestId, owner: owner))
            }
        }
        return ManagedResult(snapshot: snapshot(), effects: effects,
                             rejection: transition.rejection == nil ? nil : .requestIdExhausted)
    }
}
