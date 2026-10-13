import Foundation

/// Contract implemented by the copied candidate coordinator only for the N2
/// mutation build. Normal app targets never compile this file.
protocol N2DuplicateClearMutationHost: AnyObject, Sendable {
    func n2PerformNormalVerifiedLogout(commandID: Int64) async throws
    func n2PauseBeforeDeferredControlClear(effectID: String, originCommandID: Int64) async
    func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async
}

extension N2DuplicateClearMutationHost {
    func debugClearThenScheduleDuplicate(commandID: Int64) async throws {
        try await n2PerformNormalVerifiedLogout(commandID: commandID)

        let effectID = "duplicate-logout-\(commandID)"
        let host = self
        Task.detached {
            await host.n2PauseBeforeDeferredControlClear(
                effectID: effectID,
                originCommandID: commandID
            )
            await host.n2PerformDuplicateClearAndRecord(
                effectID: effectID,
                originCommandID: commandID
            )
        }
    }
}
