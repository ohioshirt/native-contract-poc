import Foundation

private actor N2CompileFixture: N2DuplicateClearMutationHost {
    private var events: [String] = []

    func n2PerformNormalVerifiedLogout(commandID: Int64) async throws {
        events.append("normal:\(commandID)")
    }

    func n2PauseBeforeDeferredControlClear(effectID: String, originCommandID: Int64) async {
        events.append("arrived:\(effectID):\(originCommandID)")
    }

    func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async {
        events.append("cleared:\(effectID):\(originCommandID)")
    }
}

private actor N4CompileFixture: N4FalseLogoutMutationHost {
    struct Receipt: Sendable { let commandID: Int64; let status: String }

    func n4PublishSignedOutWithoutStoreClear(commandID: Int64) async {}
    func n4MakeCompletedLogoutReceipt(commandID: Int64) async -> Receipt {
        Receipt(commandID: commandID, status: "Completed")
    }
}

@main
private struct MutationHelperCompileFixture {
    static func main() async {
        let n2 = N2CompileFixture()
        try? await n2.debugClearThenScheduleDuplicate(commandID: 7)
        let n4 = N4CompileFixture()
        _ = await n4.debugFalseLogoutReceipt(commandID: 8)
    }
}
