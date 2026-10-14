/// Contract implemented by the copied candidate coordinator only for the N4
/// mutation build. It creates a terminal receipt without retrying or clearing
/// the credential store; normal app targets never compile this file.
protocol N4FalseLogoutMutationHost: Sendable {
    associatedtype LogoutReceipt: Sendable

    func n4PublishSignedOutWithoutStoreClear(commandID: Int64) async
    func n4MakeCompletedLogoutReceipt(commandID: Int64) async -> LogoutReceipt
}

extension N4FalseLogoutMutationHost {
    func debugFalseLogoutReceipt(commandID: Int64) async -> LogoutReceipt {
        await n4PublishSignedOutWithoutStoreClear(commandID: commandID)
        return await n4MakeCompletedLogoutReceipt(commandID: commandID)
    }
}
