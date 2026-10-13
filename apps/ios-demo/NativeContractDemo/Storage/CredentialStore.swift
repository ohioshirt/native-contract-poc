import Foundation

/// Synchronous verified persistence. The coordinator is the sole production caller.
protocol CredentialStore: Sendable {
    func readVerified() throws -> Credential?
    func replaceVerified(_ credential: Credential) throws
    func clearVerified() throws
}

protocol StoreFaultInjecting: Sendable {
    func setStoreFault(_ kind: String?)
}

struct StoreAuditContext: Sendable {
    let commandRef: AppCommandReference?
    let cause: String
    let epochId: String?
    let slotId: String?
    let ownerId: String?
    let effectId: String?
    let originCommandRef: AppCommandReference?
    let releaseActionId: Int64?
}

/// Decorates a physical store so its actual write/readback rows are synchronized
/// before the coordinator can publish the resulting authenticated view.
final class AuditedCredentialStore: CredentialStore, StoreFaultInjecting, @unchecked Sendable {
    private let base: any CredentialStore
    private let audit: any AuditRecorder
    private let storeIOChanged: @Sendable (Bool) -> Void
    private let contextLock = NSLock()
    private var context: StoreAuditContext?
    /// Last observation this wrapper audited (readback or fault), mirroring the
    /// evaluator's verified-store chain for later mutation `before` values.
    private var lastAuditedObservation: StoreObservation?

    init(
        base: any CredentialStore,
        audit: any AuditRecorder,
        storeIOChanged: @escaping @Sendable (Bool) -> Void
    ) {
        self.base = base
        self.audit = audit
        self.storeIOChanged = storeIOChanged
    }

    func beginOperation(_ value: StoreAuditContext) throws {
        try contextLock.withLock {
            guard context == nil else { throw CredentialStoreError.auditContextMissing }
            context = value
        }
    }

    func endOperation() {
        contextLock.withLock { context = nil }
    }

    func setStoreFault(_ kind: String?) {
        contextLock.withLock {
            (base as? any StoreFaultInjecting)?.setStoreFault(kind)
        }
    }

    func readVerified() throws -> Credential? {
        storeIOChanged(true)
        defer { storeIOChanged(false) }
        return try base.readVerified()
    }

    func replaceVerified(_ credential: Credential) throws {
        let operation = try currentContext()
        storeIOChanged(true)
        defer { storeIOChanged(false) }
        let before = try observedStore()
        do {
            try base.replaceVerified(credential)
            let readback = try observedStore()
            guard readback == .present(account: credential.account.rawValue, version: credential.version) else {
                throw CredentialStoreError.readbackFailed
            }
            try recordMutation(operation, name: "replace", before: before, after: readback)
            try recordReadback(operation, name: "replace", observation: readback)
        } catch let failure as CredentialStoreFailure {
            try recordFailure(operation, failure: failure)
            throw failure
        } catch {
            throw error
        }
    }

    func clearVerified() throws {
        let operation = try currentContext()
        storeIOChanged(true)
        defer { storeIOChanged(false) }
        // A malformed/temporarily unreadable record must not prevent recovery
        // from deleting this store's one owned item. Keep the uncertainty as
        // Unknown in the audit, then require a verified Absent readback. Once
        // this process has audited an observation, `before` chains from it so
        // an earlier Unknown is not silently replaced by a fresh read.
        let before = contextLock.withLock { lastAuditedObservation } ?? bestEffortObservation()
        do {
            try base.clearVerified()
            let readback = try observedStore()
            guard readback == .absent else { throw CredentialStoreError.readbackFailed }
            try recordMutation(operation, name: "clear", before: before, after: readback)
            try recordReadback(operation, name: "clear", observation: readback)
        } catch let failure as CredentialStoreFailure {
            try recordFailure(operation, failure: failure)
            throw failure
        } catch {
            throw error
        }
    }

    private func currentContext() throws -> StoreAuditContext {
        try contextLock.withLock {
            guard let context else { throw CredentialStoreError.auditContextMissing }
            return context
        }
    }

    private func observedStore() throws -> StoreObservation {
        guard let credential = try base.readVerified() else { return .absent }
        return .present(account: credential.account.rawValue, version: credential.version)
    }

    private func bestEffortObservation() -> StoreObservation {
        do {
            return try observedStore()
        } catch let error as CredentialStoreError {
            return .unknown(errorCode: error.safeCode)
        } catch {
            return .unknown(errorCode: "storeFailure")
        }
    }

    private func recordMutation(
        _ context: StoreAuditContext,
        name operation: String,
        before: StoreObservation,
        after: StoreObservation
    ) throws {
        var fields: [String: Any] = [
            "operation": operation,
            "before": storeJSON(before),
            "after": storeJSON(after),
            "cause": context.cause,
        ]
        if let commandRef = context.commandRef { fields["commandRef"] = commandJSON(commandRef) }
        if let epochId = context.epochId { fields["epochId"] = epochId }
        if let slotId = context.slotId { fields["slotId"] = slotId }
        if let ownerId = context.ownerId { fields["ownerId"] = ownerId }
        if let effectId = context.effectId { fields["effectId"] = effectId }
        if let origin = context.originCommandRef { fields["originCommandRef"] = commandJSON(origin) }
        if let releaseActionId = context.releaseActionId { fields["releaseActionId"] = releaseActionId }
        if context.effectId != nil {
            try append("detachedStoreMutation", fields: fields)
        } else {
            try append("storeMutation", fields: fields)
        }
    }

    private func recordReadback(
        _ context: StoreAuditContext,
        name operation: String,
        observation: StoreObservation
    ) throws {
        var fields: [String: Any] = ["operation": operation, "observation": storeJSON(observation)]
        if let commandRef = context.commandRef { fields["commandRef"] = commandJSON(commandRef) }
        if let effectId = context.effectId { fields["effectId"] = effectId }
        if let origin = context.originCommandRef { fields["originCommandRef"] = commandJSON(origin) }
        if context.effectId != nil {
            try append("detachedStoreReadback", fields: fields)
        } else {
            try append("storeReadback", fields: fields)
        }
        contextLock.withLock { lastAuditedObservation = observation }
    }

    private func recordFailure(_ context: StoreAuditContext, failure: CredentialStoreFailure) throws {
        if failure.mutationApplied {
            try recordMutation(
                context,
                name: failure.operation,
                before: failure.before,
                after: failure.physicalAfter
            )
        }
        guard context.effectId == nil, let commandRef = context.commandRef else { return }
        try append("storeFault", fields: [
            "commandRef": commandJSON(commandRef),
            "operation": failure.operation,
            "fault": failure.fault,
            "mutationApplied": failure.mutationApplied,
            "verification": failure.verification,
            "before": storeJSON(failure.before),
            "observation": storeJSON(failure.observation),
        ])
        contextLock.withLock { lastAuditedObservation = failure.observation }
    }

    private func append(_ kind: String, fields: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        _ = try audit.append(kind: kind, fields: data)
        try audit.synchronize()
    }

    private func commandJSON(_ reference: AppCommandReference) -> [String: Any] {
        ["processInstanceId": reference.processInstanceId, "id": reference.id]
    }

    private func storeJSON(_ observation: StoreObservation) -> [String: Any] {
        switch observation {
        case .absent:
            ["kind": "Absent"]
        case let .present(account, version):
            ["kind": "Present", "account": account, "version": version]
        case let .unknown(errorCode):
            ["kind": "Unknown", "errorCode": errorCode]
        }
    }

}
