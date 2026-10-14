import Foundation
import AsyncNativeContract

/// Reference identity that is replaced when the logical managed owner changes.
final class SessionEpoch: Sendable {
    let id: String

    init(id: String = "epoch-\(UUID().uuidString)") {
        self.id = id
    }
}

/// An opaque request capability retained from the managed effect through delivery.
final class RefreshSlot: Sendable {
    let slotId: String
    let request: RefreshRequest
    let epoch: SessionEpoch
    let issuanceCommandId: Int64
    let wireTag: String
    let account: CredentialAccount
    let seedVersion: Int64
    let ownerId: String

    init(
        slotId: String,
        request: RefreshRequest,
        epoch: SessionEpoch,
        issuanceCommandId: Int64,
        wireTag: String,
        account: CredentialAccount,
        seedVersion: Int64,
        ownerId: String
    ) {
        self.slotId = slotId
        self.request = request
        self.epoch = epoch
        self.issuanceCommandId = issuanceCommandId
        self.wireTag = wireTag
        self.account = account
        self.seedVersion = seedVersion
        self.ownerId = ownerId
    }
}
