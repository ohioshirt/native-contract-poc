import Foundation

enum RefreshOutcome: Sendable, Equatable {
    case success(Credential)
    case failure(String)

    var label: String {
        switch self {
        case .success: "success"
        case .failure: "failure"
        }
    }

    var isSuccess: Bool {
        if case .success = self { return true }
        return false
    }

    var failureCode: String? {
        guard case let .failure(code) = self else { return nil }
        return code
    }
}

struct Completion: Sendable {
    let slot: RefreshSlot
    let outcome: RefreshOutcome
}

protocol TransportHandle: Sendable {
    func cancel()
}

protocol FencedTransportHandle: TransportHandle {
    func cancelAndWait(timeoutMillis: Int64) async throws
}

extension TransportHandle {
    func cancelAndWait(timeoutMillis: Int64) async throws { cancel() }
}

protocol RefreshTransport: Sendable {
    func start(
        slot: RefreshSlot,
        credential: Credential,
        completion: @escaping @Sendable (Completion) -> Void
    ) -> any TransportHandle
}
