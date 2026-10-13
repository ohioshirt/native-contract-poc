import Foundation
import AsyncNativeContract
import NativeContract

private enum CoordinatorHealth {
    case booting
    case ready
    case faultLocked
}

private struct ManagedResetPlan {
    let before: ManagedViewSnapshot
    let after: ManagedViewSnapshot
    let session: ManagedAsyncSession
    let ownerId: String
    let epoch: SessionEpoch
}

private struct CommandExecution {
    let receipt: CommandReceipt
    let completion: Completion?
    let resetAfterReceipt: ManagedResetPlan?
}

private struct PendingCommand {
    let reference: AppCommandReference
    let command: AppCommand
    let continuation: CheckedContinuation<CommandReceipt, Never>
}

/// One actor-owned transaction drain. Every accepted command retains the drain
/// through managed actor awaits, verified storage and MainActor publication.
actor SessionCoordinator {
    private let process: ProcessContext
    private let store: AuditedCredentialStore
    private let transport: any RefreshTransport
    private let publisher: any ViewPublisher
    private let hooks: any ScenarioHooks
    private let audit: any AuditRecorder
    private let cancelTransportOnCancelRefresh: Bool

    private var managed = ManagedAsyncSession()
    private var ownerId = "owner-\(UUID().uuidString)"
    private var epoch = SessionEpoch()
    private var activeSlot: RefreshSlot?
    private var transportHandles: [String: any TransportHandle] = [:]
    private var nextSlotOrdinal: [CredentialAccount: Int64] = [.a: 0, .b: 0]
    private var pendingStoreCause: String?
    private var pendingStoreEpochId: String?
    private var detachedReleaseActions: [String: Int64] = [:]

    private var health: CoordinatorHealth = .booting
    private var currentStoreObservation: StoreObservation = .unknown(errorCode: "notRead")
    private var currentPhase: SessionPhase = .booting
    private var currentAccount: CredentialAccount?
    private var currentCredentialVersion: Int64?
    private var currentPendingRequestId: Int64?
    private var lastCompletedCommandId: Int64?
    private var lastCommandStatus: CommandStatus?
    private var currentView: DemoViewState
    private var currentRevision: Int64 = 0
    private var lastUIAcknowledgement: NativeEventReference?

    private var nextCommandId: Int64? = 1
    private var queue: [PendingCommand] = []
    private var draining = false
    private var drainIdleWaiters: [CheckedContinuation<Void, Never>] = []
    private var activeCommand: AppCommandReference?
    private var started = false
    private var ingressClosed = false
    private var endedReference: NativeEventReference?
    private var finishInProgress = false

    init(
        process: ProcessContext,
        store: any CredentialStore,
        transport: any RefreshTransport,
        publisher: any ViewPublisher,
        hooks: any ScenarioHooks,
        audit: any AuditRecorder,
        cancelTransportOnCancelRefresh: Bool = true
    ) {
        self.process = process
        if let auditedStore = store as? AuditedCredentialStore {
            self.store = auditedStore
        } else {
            self.store = AuditedCredentialStore(base: store, audit: audit, storeIOChanged: hooks.storeIOChanged)
        }
        self.transport = transport
        self.publisher = publisher
        self.hooks = hooks
        self.audit = audit
        self.cancelTransportOnCancelRefresh = cancelTransportOnCancelRefresh
        self.currentView = DemoViewState(
            processInstanceId: process.processInstanceId,
            revision: 0,
            phase: .booting,
            account: nil,
            credentialVersion: nil,
            pendingRequestId: nil,
            lastCompletedCommandId: nil,
            lastCommandStatus: nil
        )
    }

    /// Opens the process journal before the Debug control plane or Bootstrap.
    func start() throws {
        guard !started else { return }
        let reference = try appendEvent("processStart", fields: ["initialView": Self.viewJSON(currentView)])
        guard reference.localSequence == 1 else {
            throw CoordinatorFailure.journalSequence("processStart must be the first native row")
        }
        started = true
    }

    /// Synchronously records admission and resolves only after the serial drain
    /// has committed the terminal receipt. Caller cancellation does not cancel it.
    func submit(_ command: AppCommand) async -> CommandReceipt {
        if !started {
            do { try start() }
            catch { fatalError("native process start could not be recorded: \(error)") }
        }
        if ingressClosed || endedReference != nil {
            return await closedIngressReceipt(for: command)
        }
        return await withCheckedContinuation { continuation in
            guard !ingressClosed, endedReference == nil else {
                Task { continuation.resume(returning: await self.closedIngressReceipt(for: command)) }
                return
            }
            let id = allocateCommandId()
            let reference = AppCommandReference(processInstanceId: process.processInstanceId, id: id)
            do {
                _ = try appendEvent("commandEnqueued", fields: [
                    "commandRef": Self.commandJSON(reference),
                    "name": command.name,
                ])
            } catch {
                fatalError("command enqueue could not be synchronized: \(error)")
            }
            hooks.commandEnqueued(reference, name: command.name)
            queue.append(PendingCommand(reference: reference, command: command, continuation: continuation))
            beginDrainIfNeeded()
        }
    }

    /// Used only by the Debug finishProcess adapter after it has closed control
    /// ingress and rejected a still-paused hook. It creates the actual terminal row.
    func finishNativeProcess(timeoutMillis: Int64) async throws -> NativeEventReference {
        if let endedReference { return endedReference }
        guard (1...21_600_000).contains(timeoutMillis) else { throw CoordinatorFailure.timeout }
        guard !hooks.hasPausedHook else { throw CoordinatorFailure.processBusy }
        guard !finishInProgress else { throw CoordinatorFailure.processBusy }
        finishInProgress = true
        let previousIngressClosed = ingressClosed
        ingressClosed = true
        var terminalWriteStarted = false
        defer {
            finishInProgress = false
            if endedReference == nil && !terminalWriteStarted {
                ingressClosed = previousIngressClosed
            }
        }
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .milliseconds(timeoutMillis))
        try await waitForDrain(deadline: deadline)
        guard !hooks.hasPausedHook else { throw CoordinatorFailure.processBusy }

        let handles = Array(transportHandles.values)
        for handle in handles {
            if let fenced = handle as? any FencedTransportHandle {
                let remaining = clock.now.duration(to: deadline)
                let milliseconds = max(1, Int64(remaining.components.seconds * 1_000
                    + remaining.components.attoseconds / 1_000_000_000_000_000))
                try await fenced.cancelAndWait(timeoutMillis: milliseconds)
            } else {
                handle.cancel()
            }
        }
        activeSlot = nil
        epoch = SessionEpoch()
        terminalWriteStarted = true
        let reference: NativeEventReference
        do {
            reference = try appendEvent("processEnd", fields: [:])
        } catch {
            throw CoordinatorFailure.terminalJournal
        }
        endedReference = reference
        return reference
    }

    private func beginDrainIfNeeded() {
        guard !draining else { return }
        draining = true
        Task { await self.drain() }
    }

    private func drain() async {
        while !queue.isEmpty {
            let entry = queue.removeFirst()
            activeCommand = entry.reference
            currentCommandName = entry.command.name
            hooks.commandStarted(entry.reference, name: entry.command.name)
            _ = appendRequired("commandStarted", fields: ["commandRef": Self.commandJSON(entry.reference)])
            let execution = await execute(entry.command, reference: entry.reference)
            let receipt = execution.receipt
            let receiptReference = appendRequired("commandReceipt", fields: [
                "commandRef": Self.commandJSON(entry.reference),
                "acknowledgedEventRef": Self.eventJSON(receipt.acknowledgedEventRef),
                "status": receipt.status.rawValue,
                "observation": Self.observationJSON(receipt.observation),
            ])
            if let completion = execution.completion {
                _ = appendRequired("completionProcessed", fields: [
                    "commandRef": Self.commandJSON(entry.reference),
                    "slotId": completion.slot.slotId,
                    "receiptEventRef": Self.eventJSON(receiptReference),
                ])
            }
            if let reset = execution.resetAfterReceipt {
                _ = appendRequired("managedInstanceReset", fields: [
                    "commandRef": Self.commandJSON(entry.reference),
                    "before": Self.managedJSON(reset.before),
                    "after": Self.managedJSON(reset.after),
                ])
                managed = reset.session
                ownerId = reset.ownerId
                epoch = reset.epoch
            }
            hooks.commandProcessed(entry.reference)
            activeCommand = nil
            currentCommandName = nil
            entry.continuation.resume(returning: receipt)
            if entry.command.name == "Logout" || entry.command.name == "Logout(failed)" {
                await hooks.pauseIfArmed(.afterLogoutReceipt)
            }
        }
        draining = false
        let waiters = drainIdleWaiters
        drainIdleWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    private func execute(_ command: AppCommand, reference: AppCommandReference) async -> CommandExecution {
        switch command {
        case .bootstrap:
            return await handleBootstrap(reference)
        case let .login(account):
            return await handleLogin(account, reference: reference)
        case .expire:
            return await handleExpire(reference)
        case .logout:
            return await handleLogout(reference, cause: "Logout", cancelTransport: false)
        case .cancelRefresh:
            return await handleLogout(reference, cause: "CancelRefresh", cancelTransport: cancelTransportOnCancelRefresh)
        case .retryCleanup:
            return await handleRetryCleanup(reference)
        case .observe:
            return await handleObserve(reference)
        case let .deliver(completion):
            return await handleRefreshCompletion(completion, reference: reference)
        }
    }

    private func handleBootstrap(_ reference: AppCommandReference) async -> CommandExecution {
        guard health == .booting else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        await hooks.pauseIfArmed(.beforeBootstrapClear)
        let releaseActionId = hooks.releasedActionId(for: .beforeBootstrapClear)
        await hooks.pauseIfArmed(.beforeStore)
        do {
            try performVerifiedClear(
                reference: reference,
                cause: "Bootstrap",
                releaseActionId: releaseActionId
            )
            health = .ready
            currentAccount = nil
            currentCredentialVersion = nil
            currentPendingRequestId = nil
            currentPhase = .signedOut
            let receipt = await finalize(reference, status: .completed)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        } catch {
            let receipt = await lockAfterStoreFailure(error, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
    }

    private func handleObserve(_ reference: AppCommandReference) async -> CommandExecution {
        guard health != .booting else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let actual: StoreObservation
        do {
            guard let credential = try store.readVerified() else {
                actual = .absent
                guard currentStoreObservation == actual else {
                    let receipt = await lockAfterStoreFailure(
                        CredentialStoreError.readbackFailed,
                        commandID: reference.id,
                        storeObservation: actual
                    )
                    return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
                }
                currentStoreObservation = actual
                let receipt = await makeReceipt(reference: reference, status: .completed)
                return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
            }
            actual = .present(account: credential.account.rawValue, version: credential.version)
        } catch {
            currentStoreObservation = failureObservation(error)
            let receipt = await lockAfterStoreFailure(error, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        guard currentStoreObservation == actual else {
            let receipt = await lockAfterStoreFailure(
                CredentialStoreError.readbackFailed,
                commandID: reference.id,
                storeObservation: actual
            )
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        currentStoreObservation = actual
        let receipt = await makeReceipt(reference: reference, status: .completed)
        return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
    }

    private func handleLogin(_ account: CredentialAccount, reference: AppCommandReference) async -> CommandExecution {
        guard health == .ready else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let pre = await managed.snapshot()
        guard pre.state == .unauthenticated,
              pre.pendingRequestId == nil,
              currentStoreObservation == .absent else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let credential = Credential.demo(account: account, version: 0)
        await hooks.pauseIfArmed(.beforeStore)
        beginStoreAuditContext(reference: reference, cause: "Login", epochId: epoch.id)
        do {
            try store.replaceVerified(credential)
            currentStoreObservation = .present(account: account.rawValue, version: credential.version)
            endStoreAuditContext()
        } catch {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            attemptFaultCleanup(reference: reference)
            let receipt = await lockAfterStoreFailure(error, commandID: reference.id, storeObservation: currentStoreObservation)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        let managedResult = await managed.handle(.loginSucceeded)
        recordManagedReduction(
            reference: reference,
            event: "LoginSucceeded",
            pre: pre,
            result: managedResult,
            epochId: epoch.id
        )
        await hooks.pauseIfArmed(.afterManaged)
        guard managedResult.rejection == nil,
              managedResult.snapshot.state == .authenticated,
              managedResult.snapshot.pendingRequestId == nil,
              managedResult.effects.isEmpty else {
            let receipt = await lockAfterStoreFailure(CredentialStoreError.readbackFailed, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        currentAccount = account
        currentCredentialVersion = credential.version
        currentPendingRequestId = nil
        currentPhase = .signedIn
        let receipt = await finalize(reference, status: .completed)
        return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
    }

    private func handleExpire(_ reference: AppCommandReference) async -> CommandExecution {
        guard health == .ready else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let pre = await managed.snapshot()
        guard pre.state == .authenticated, pre.pendingRequestId == nil else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let credential: Credential
        do {
            guard let stored = try store.readVerified() else {
                currentStoreObservation = .absent
                let receipt = await lockAfterStoreFailure(
                    CredentialStoreError.readbackFailed,
                    commandID: reference.id,
                    storeObservation: .absent
                )
                return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
            }
            let persisted = StoreObservation.present(account: stored.account.rawValue, version: stored.version)
            guard currentStoreObservation == persisted else {
                currentStoreObservation = persisted
                let receipt = await lockAfterStoreFailure(
                    CredentialStoreError.readbackFailed,
                    commandID: reference.id,
                    storeObservation: persisted
                )
                return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
            }
            credential = stored
        } catch {
            currentStoreObservation = failureObservation(error)
            let receipt = await lockAfterStoreFailure(error, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        let managedResult = await managed.handle(.tokenExpired)
        recordManagedReduction(reference: reference, event: "TokenExpired", pre: pre, result: managedResult, epochId: epoch.id)
        await hooks.pauseIfArmed(.afterManaged)
        guard managedResult.rejection == nil,
              managedResult.snapshot.state == .refreshing,
              let request = managedResult.effects.compactMap({ effect -> RefreshRequest? in
                  if case let .requestTokenRefresh(value) = effect { return value }
                  return nil
              }).only else {
            let receipt = await completed(reference, status: .rejectedBusy, completion: nil).receipt
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        let slotId = allocateSlotId(for: credential.account)
        let wireTag = "\(process.processInstanceId):refresh:\(reference.id)"
        let slot = RefreshSlot(
            slotId: slotId,
            request: request,
            epoch: epoch,
            issuanceCommandId: reference.id,
            wireTag: wireTag,
            account: credential.account,
            seedVersion: credential.version,
            ownerId: ownerId
        )
        activeSlot = slot
        currentPendingRequestId = request.requestId
        currentPhase = .refreshing
        _ = appendRequired("slotIssued", fields: [
            "commandRef": Self.commandJSON(reference),
            "slotId": slot.slotId,
            "ownerId": slot.ownerId,
            "epochId": slot.epoch.id,
            "requestId": request.requestId,
            "wireRequestId": String(request.requestId),
            "account": slot.account.rawValue,
            "seedVersion": slot.seedVersion,
            "wireTag": slot.wireTag,
        ])
        let callback: @Sendable (Completion) -> Void = { [weak self] completion in
            guard let self else { return }
            Task { await self.acceptTransportCompletion(completion) }
        }
        transportHandles[wireTag] = transport.start(slot: slot, credential: credential, completion: callback)
        currentAccount = credential.account
        currentCredentialVersion = credential.version
        let receipt = await finalize(reference, status: .completed)
        return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
    }

    private func handleLogout(
        _ reference: AppCommandReference,
        cause: String,
        cancelTransport: Bool
    ) async -> CommandExecution {
        let commandID = reference.id
        guard health != .booting else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        if health == .faultLocked {
            return await completed(reference, status: .faultLocked, completion: nil)
        }
        let oldSlot = activeSlot
        let logoutEpochId = epoch.id
        activeSlot = nil
        epoch = SessionEpoch()
        currentPendingRequestId = nil
        currentPhase = .signingOut
        _ = await publishTransient(.signingOut, account: nil, credentialVersion: nil, pendingRequestId: nil)
        let pre = await managed.snapshot()
        let managedResult = await managed.handle(.logout)
        recordManagedReduction(reference: reference, event: "Logout", pre: pre, result: managedResult, epochId: logoutEpochId)
        await hooks.pauseIfArmed(.afterManaged)
        pendingStoreCause = cause
        pendingStoreEpochId = logoutEpochId
        do {
            try await clearThenPublishSignedOut(commandID: commandID)
            if cancelTransport, let oldSlot, let handle = transportHandles[oldSlot.wireTag] {
                handle.cancel()
            }
            let receipt = await makeReceipt(reference: reference, status: .completed)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        } catch {
            let receipt = await handleLogoutClearFailure(error, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
    }

    /// Kept as the mutation-matrix N2 caller anchor. A copied helper substitutes
    /// only this normal verified clear/publish call.
    private func clearThenPublishSignedOut(commandID: Int64) async throws {
        try await clearThenPublishSignedOut(commandID: commandID, causeOverride: nil)
    }

    private func clearThenPublishSignedOut(commandID: Int64, causeOverride: String?) async throws {
        guard let reference = activeCommand, reference.id == commandID else {
            throw CoordinatorFailure.journalSequence("Logout lost its active command reference")
        }
        let cause = causeOverride ?? pendingStoreCause ?? "Logout"
        let storeEpochId = pendingStoreEpochId ?? epoch.id
        await hooks.pauseIfArmed(.beforeStore)
        beginStoreAuditContext(reference: reference, cause: cause, epochId: storeEpochId)
        do {
            try store.clearVerified()
            currentStoreObservation = .absent
            endStoreAuditContext()
        } catch {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            throw error
        }
        currentAccount = nil
        currentCredentialVersion = nil
        currentPendingRequestId = nil
        currentPhase = .signedOut
        _ = await publishFinal(reference, status: .completed)
    }

    /// Kept as the N4 mutation anchor; a failed clear must stay FaultLocked.
    private func handleLogoutClearFailure(_ error: Error, commandID: Int64) async -> CommandReceipt {
        return await lockAfterStoreFailure(error, commandID: commandID)
    }

    private func lockAfterStoreFailure(
        _ error: Error,
        commandID: Int64,
        storeObservation: StoreObservation? = nil
    ) async -> CommandReceipt {
        health = .faultLocked
        activeSlot = nil
        epoch = SessionEpoch()
        currentStoreObservation = storeObservation ?? failureObservation(error)
        currentAccount = nil
        currentCredentialVersion = nil
        currentPendingRequestId = nil
        currentPhase = .faultLocked
        return await finalize(AppCommandReference(processInstanceId: process.processInstanceId, id: commandID), status: .faultLocked)
    }

    private func handleRetryCleanup(_ reference: AppCommandReference) async -> CommandExecution {
        guard health == .faultLocked else {
            return await completed(reference, status: .rejectedBusy, completion: nil)
        }
        let beforeSnapshot = await managed.snapshot()
        let logoutResult = await managed.handle(.logout)
        recordManagedReduction(
            reference: reference,
            event: "Logout",
            pre: beforeSnapshot,
            result: logoutResult,
            epochId: epoch.id
        )
        await hooks.pauseIfArmed(.afterManaged)
        guard logoutResult.rejection == nil,
              logoutResult.snapshot.state == .unauthenticated,
              logoutResult.snapshot.pendingRequestId == nil else {
            let receipt = await lockAfterStoreFailure(CredentialStoreError.readbackFailed, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        let before = Self.managedViewSnapshot(ownerId: ownerId, snapshot: logoutResult.snapshot)
        await hooks.pauseIfArmed(.beforeStore)
        beginStoreAuditContext(reference: reference, cause: "RetryCleanup", epochId: epoch.id)
        do {
            try store.clearVerified()
            currentStoreObservation = .absent
            endStoreAuditContext()
        } catch {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            let receipt = await lockAfterStoreFailure(error, commandID: reference.id)
            return CommandExecution(receipt: receipt, completion: nil, resetAfterReceipt: nil)
        }
        activeSlot = nil
        currentAccount = nil
        currentCredentialVersion = nil
        currentPendingRequestId = nil
        currentPhase = .signedOut
        health = .ready
        let receipt = await finalize(reference, status: .completed)
        let replacement = ManagedAsyncSession()
        let replacementOwner = "owner-\(UUID().uuidString)"
        let replacementSnapshot = await replacement.snapshot()
        let after = Self.managedViewSnapshot(ownerId: replacementOwner, snapshot: replacementSnapshot)
        return CommandExecution(
            receipt: receipt,
            completion: nil,
            resetAfterReceipt: ManagedResetPlan(
                before: before,
                after: after,
                session: replacement,
                ownerId: replacementOwner,
                epoch: SessionEpoch()
            )
        )
    }

    private func handleRefreshCompletion(
        _ completion: Completion,
        reference: AppCommandReference
    ) async -> CommandExecution {
        let slot = completion.slot
        let outcome = completion.outcome
        let outcomeName = outcome.label
        let failureCode = outcome.failureCode
        _ = appendRequired("transportReceived", fields: [
            "commandRef": Self.commandJSON(reference),
            "slotId": slot.slotId,
            "outcome": outcomeName,
            "failureCode": failureCode as Any? ?? NSNull(),
            "requestTag": slot.wireTag,
        ])
        await hooks.pauseIfArmed(.ingressHeld)
        if health == .faultLocked {
            let receipt = await finalize(reference, status: .faultLocked)
            return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
        }
        let preSnapshot = await managed.snapshot()
        let managedPre = Self.managedViewSnapshot(ownerId: ownerId, snapshot: preSnapshot)
        let eligible = health == .ready
            && activeSlot === slot
            && slot.epoch === epoch
            && preSnapshot.state == .refreshing
            && preSnapshot.pendingRequestId == slot.request.requestId
        let event: ManagedEvent
        switch outcome {
        case .success: event = .refreshSucceeded(slot.request)
        case .failure: event = .refreshFailed(slot.request)
        }
        let result = await managed.handle(event)
        let eventName = outcome.isSuccess ? "RefreshSucceeded" : "RefreshFailed"
        recordManagedReduction(
            reference: reference,
            event: eventName,
            requestId: slot.request.requestId,
            pre: preSnapshot,
            result: result,
            epochId: slot.epoch.id,
            slot: slot
        )
        await hooks.pauseIfArmed(.afterManaged)
        let validSuccessPayload: Bool
        if case let .success(payload) = outcome,
           slot.seedVersion < Int64.max {
            let expectedVersion = slot.seedVersion + 1
            let expectedToken = "demo-\(slot.account.rawValue)-v\(expectedVersion)"
            validSuccessPayload = payload.account == slot.account
                && payload.version == expectedVersion
                && payload.accessToken == expectedToken
                && payload.refreshToken == expectedToken
        } else {
            validSuccessPayload = false
        }
        let acceptedSuccess = outcome.isSuccess
            && validSuccessPayload
            && result.rejection == nil
            && result.snapshot.state == .authenticated
            && result.snapshot.pendingRequestId == nil
            && result.effects.isEmpty
        let admittedSuccess = eligible && acceptedSuccess

        if admittedSuccess, case let .success(credential) = outcome {
            activeSlot = nil
            currentPendingRequestId = nil
            do {
                await hooks.pauseIfArmed(.beforeStore)
                beginStoreAuditContext(
                    reference: reference,
                    cause: "RefreshSuccess",
                    epochId: slot.epoch.id,
                    slotId: slot.slotId,
                    ownerId: slot.ownerId
                )
                do {
                    try await commitRefreshSuccess(credential, commandID: reference.id)
                    endStoreAuditContext()
                } catch {
                    endStoreAuditContext()
                    throw error
                }
                currentPhase = .signedIn
                let receipt = await makeReceipt(reference: reference, status: .completed)
                return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
            } catch {
                currentStoreObservation = failureObservation(error)
                attemptFaultCleanup(reference: reference)
                let receipt = await lockAfterStoreFailure(error, commandID: reference.id, storeObservation: currentStoreObservation)
                return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
            }
        }

        let acceptedFailure = !outcome.isSuccess
            && result.rejection == nil
            && result.snapshot.state == .unauthenticated
            && result.snapshot.pendingRequestId == nil
            && result.effects.contains(where: { if case .clearCredentials = $0 { return true }; return false })
        if eligible && acceptedFailure {
            activeSlot = nil
            currentPendingRequestId = nil
            do {
                await hooks.pauseIfArmed(.beforeStore)
                beginStoreAuditContext(
                    reference: reference,
                    cause: "RefreshFailure",
                    epochId: slot.epoch.id,
                    slotId: slot.slotId,
                    ownerId: slot.ownerId
                )
                do {
                    try store.clearVerified()
                    currentStoreObservation = .absent
                    endStoreAuditContext()
                } catch {
                    endStoreAuditContext()
                    throw error
                }
                currentAccount = nil
                currentCredentialVersion = nil
                currentPhase = .signedOut
                let receipt = await finalize(reference, status: .completed)
                return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
            } catch {
                currentStoreObservation = failureObservation(error)
                let receipt = await lockAfterStoreFailure(error, commandID: reference.id)
                return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
            }
        }

        if eligible {
            let receipt = await lockAfterStoreFailure(
                CredentialStoreError.malformedCredential,
                commandID: reference.id,
                storeObservation: currentStoreObservation
            )
            return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
        }

        let managedPost = Self.managedViewSnapshot(ownerId: ownerId, snapshot: result.snapshot)
        if result.rejection != nil || !eligible {
            guard managedPre.state == managedPost.state,
                  managedPre.ownerId == managedPost.ownerId,
                  managedPre.pendingRequestId == managedPost.pendingRequestId,
                  managedPre.nextRequestId == managedPost.nextRequestId,
                  result.effects.isEmpty else {
                let receipt = await lockAfterStoreFailure(CredentialStoreError.readbackFailed, commandID: reference.id)
                return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
            }
        }
        if activeSlot === slot { activeSlot = nil }
        currentPhase = currentView.phase
        let ignoredStatus: CommandStatus = result.rejection == .foreignRequest ? .ignoredForeign : .ignoredStale
        let receipt = await finalize(reference, status: ignoredStatus)
        return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
    }

    /// Mutation-matrix N3 anchor. The verified store write precedes the main
    /// assignment acknowledgement; the swapped version is confined to the copy.
    private func commitRefreshSuccess(_ credential: Credential, commandID: Int64) async throws {
        try store.replaceVerified(credential)
        await publishSignedIn(credential, commandID: commandID)
    }

    private func publishSignedIn(_ credential: Credential, commandID: Int64) async {
        currentStoreObservation = .present(account: credential.account.rawValue, version: credential.version)
        currentAccount = credential.account
        currentCredentialVersion = credential.version
        currentPendingRequestId = nil
        currentPhase = .signedIn
        let reference = activeCommand ?? AppCommandReference(processInstanceId: process.processInstanceId, id: commandID)
        _ = await publishFinal(reference, status: .completed)
    }

    // Isolated N2 helper adapter. Normal Logout does not call these methods.
    func n2PerformNormalVerifiedLogout(commandID: Int64) async throws {
        pendingStoreCause = "Logout"
        pendingStoreEpochId = epoch.id
        try await clearThenPublishSignedOut(commandID: commandID, causeOverride: "Logout")
    }

    func n2PauseBeforeDeferredControlClear(effectID: String, originCommandID: Int64) async {
        let actionId = await hooks.pauseDetachedEffect(effectId: effectID, originCommandId: originCommandID)
        detachedReleaseActions[effectID] = actionId
    }

    func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async {
        let traceEffectId = traceEffectLabel(for: effectID)
        let origin = AppCommandReference(processInstanceId: process.processInstanceId, id: originCommandID)
        let actionId = detachedReleaseActions[effectID] ?? 0
        let context = StoreAuditContext(
            commandRef: nil,
            cause: "DeferredLogoutClear",
            epochId: nil,
            slotId: nil,
            ownerId: nil,
            effectId: traceEffectId,
            originCommandRef: origin,
            releaseActionId: actionId > 0 ? actionId : nil
        )
        do {
            try store.beginOperation(context)
            try store.clearVerified()
            currentStoreObservation = .absent
            store.endOperation()
        } catch {
            store.endOperation()
            currentStoreObservation = failureObservation(error)
        }
    }

    // Isolated N4 helper adapters. The ordinary failed-clear path returns
    // lockAfterStoreFailure and never calls this unsafe copied-build path.
    func n4PublishSignedOutWithoutStoreClear(commandID: Int64) async {
        currentStoreObservation = .unknown(errorCode: "readFailed")
        currentAccount = nil
        currentCredentialVersion = nil
        currentPendingRequestId = nil
        currentPhase = .signedOut
        let reference = AppCommandReference(processInstanceId: process.processInstanceId, id: commandID)
        _ = await publishFinal(reference, status: .completed)
    }

    func n4MakeCompletedLogoutReceipt(commandID: Int64) async -> CommandReceipt {
        let reference = AppCommandReference(processInstanceId: process.processInstanceId, id: commandID)
        return await makeReceipt(reference: reference, status: .completed)
    }

    private func completed(
        _ reference: AppCommandReference,
        status: CommandStatus,
        completion: Completion?
    ) async -> CommandExecution {
        let receipt = await finalize(reference, status: status)
        return CommandExecution(receipt: receipt, completion: completion, resetAfterReceipt: nil)
    }

    private func finalize(_ reference: AppCommandReference, status: CommandStatus) async -> CommandReceipt {
        _ = await publishFinal(reference, status: status)
        return await makeReceipt(reference: reference, status: status)
    }

    private func publishFinal(_ reference: AppCommandReference, status: CommandStatus) async -> NativeEventReference {
        lastCompletedCommandId = reference.id
        lastCommandStatus = status
        let view = nextView(
            revision: allocateRevision(),
            phase: currentPhase,
            account: currentAccount,
            credentialVersion: currentCredentialVersion,
            pendingRequestId: currentPendingRequestId,
            lastCompletedCommandId: reference.id,
            lastCommandStatus: status
        )
        await hooks.pauseIfArmed(.beforePublish)
        await publisher.publish(view)
        currentView = view
        let acknowledgement = appendRequired("uiPublishAck", fields: [
            "commandRef": Self.commandJSON(reference),
            "revision": view.revision,
            "view": Self.viewJSON(view),
        ])
        lastUIAcknowledgement = acknowledgement
        await hooks.pauseIfArmed(.afterPublishAck)
        return acknowledgement
    }

    private func publishTransient(
        _ phase: SessionPhase,
        account: CredentialAccount?,
        credentialVersion: Int64?,
        pendingRequestId: Int64?
    ) async -> NativeEventReference? {
        guard let activeCommand else { return nil }
        let view = nextView(
            revision: allocateRevision(),
            phase: phase,
            account: account,
            credentialVersion: credentialVersion,
            pendingRequestId: pendingRequestId,
            lastCompletedCommandId: lastCompletedCommandId,
            lastCommandStatus: lastCommandStatus
        )
        await hooks.pauseIfArmed(.beforePublish)
        await publisher.publish(view)
        currentView = view
        let reference = appendRequired("uiPublishAck", fields: [
            "commandRef": Self.commandJSON(activeCommand),
            "revision": view.revision,
            "view": Self.viewJSON(view),
        ])
        lastUIAcknowledgement = reference
        await hooks.pauseIfArmed(.afterPublishAck)
        return reference
    }

    private func makeReceipt(reference: AppCommandReference, status: CommandStatus) async -> CommandReceipt {
        let snapshot = await managed.snapshot()
        let managedView = Self.managedViewSnapshot(ownerId: ownerId, snapshot: snapshot)
        let observation = CommandObservation(
            managed: managedView,
            store: currentStoreObservation,
            view: currentView,
            revision: currentView.revision
        )
        return CommandReceipt(
            commandId: reference.id,
            commandName: currentCommandName ?? "Observe",
            status: status,
            observation: observation,
            acknowledgedEventRef: lastUIAcknowledgement
        )
    }

    private func performVerifiedClear(
        reference: AppCommandReference,
        cause: String,
        releaseActionId: Int64? = nil
    ) throws {
        beginStoreAuditContext(
            reference: reference,
            cause: cause,
            epochId: epoch.id,
            releaseActionId: releaseActionId
        )
        do {
            try store.clearVerified()
            currentStoreObservation = .absent
            endStoreAuditContext()
        } catch {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            throw error
        }
    }

    /// Same-transaction best-effort cleanup after a failed credential write
    /// (design §4.2). A failed cleanup keeps its failure observation; the
    /// command still ends FaultLocked either way.
    private func attemptFaultCleanup(reference: AppCommandReference) {
        do {
            try performVerifiedClear(reference: reference, cause: "FaultCleanup")
        } catch {
            // performVerifiedClear already recorded the failure observation.
        }
    }

    private func managedViewSnapshot() async -> ManagedViewSnapshot {
        let snapshot = await managed.snapshot()
        return Self.managedViewSnapshot(ownerId: ownerId, snapshot: snapshot)
    }

    private func allocateCommandId() -> Int64 {
        guard let nextCommandId, nextCommandId > 0 else { fatalError("CounterExhausted: app command ID") }
        self.nextCommandId = nextCommandId == Int64.max ? nil : nextCommandId + 1
        return nextCommandId
    }

    private func allocateRevision() -> Int64 {
        guard currentRevision < Int64.max else { fatalError("CounterExhausted: UI revision") }
        currentRevision += 1
        return currentRevision
    }

    private func allocateSlotId(for account: CredentialAccount) -> String {
        let current = nextSlotOrdinal[account] ?? 0
        guard current < Int64.max else { fatalError("CounterExhausted: refresh slot label") }
        let next = current + 1
        nextSlotOrdinal[account] = next
        return "slot-\(account.rawValue)\(next)"
    }

    private func beginStoreAuditContext(
        reference: AppCommandReference,
        cause: String,
        epochId: String? = nil,
        slotId: String? = nil,
        ownerId: String? = nil,
        releaseActionId: Int64? = nil
    ) {
        let context = StoreAuditContext(
            commandRef: reference,
            cause: cause,
            epochId: epochId,
            slotId: slotId,
            ownerId: ownerId,
            effectId: nil,
            originCommandRef: nil,
            releaseActionId: releaseActionId
        )
        do { try store.beginOperation(context) }
        catch { fatalError("store audit context collision: \(error)") }
    }

    private func endStoreAuditContext() { store.endOperation() }

    private func failureObservation(_ error: Error) -> StoreObservation {
        if let failure = error as? CredentialStoreFailure { return failure.observation }
        if let storeError = error as? CredentialStoreError { return .unknown(errorCode: storeError.safeCode) }
        return .unknown(errorCode: "storeFailure")
    }

    private func recordManagedReduction(
        reference: AppCommandReference,
        event: String,
        requestId: Int64? = nil,
        pre: ManagedSnapshot,
        result: ManagedResult,
        epochId: String,
        slot: RefreshSlot? = nil
    ) {
        var reducerEvent: [String: Any] = ["event": event]
        if let requestId { reducerEvent["requestId"] = requestId }
        var fields: [String: Any] = [
            "commandRef": Self.commandJSON(reference),
            "event": reducerEvent,
            "pre": Self.managedJSON(Self.managedViewSnapshot(ownerId: ownerId, snapshot: pre)),
            "result": Self.managedResultJSON(ownerId: ownerId, result: result),
            "epochId": epochId,
        ]
        if let slot {
            fields["slotId"] = slot.slotId
            fields["requestOwnerId"] = slot.ownerId
        }
        _ = appendRequired("managedReduced", fields: fields)
    }

    private func appendEvent(_ kind: String, fields: [String: Any]) throws -> NativeEventReference {
        guard endedReference == nil || kind == "processEnd" else {
            throw CoordinatorFailure.ended
        }
        let data = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        let localSequence: Int64
        if kind == "processEnd", let terminalAudit = audit as? any TerminalAuditRecorder {
            localSequence = try terminalAudit.appendProcessEndAndSeal(fields: data)
        } else {
            localSequence = try audit.append(kind: kind, fields: data)
            try audit.synchronize()
        }
        guard localSequence > 0, localSequence <= Int64.max else {
            throw CoordinatorFailure.journalSequence("invalid local sequence from recorder")
        }
        return NativeEventReference(processInstanceId: process.processInstanceId, localSequence: localSequence)
    }

    private func appendRequired(_ kind: String, fields: [String: Any]) -> NativeEventReference {
        do { return try appendEvent(kind, fields: fields) }
        catch { fatalError("native event \(kind) could not be synchronized: \(error)") }
    }

    private func waitForDrain(deadline: ContinuousClock.Instant) async throws {
        while draining || !queue.isEmpty {
            if hooks.hasPausedHook { throw CoordinatorFailure.processBusy }
            if ContinuousClock().now >= deadline { throw CoordinatorFailure.timeout }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
    }

    private func acceptTransportCompletion(_ completion: Completion) async {
        guard !ingressClosed, endedReference == nil else { return }
        _ = await submit(.deliver(completion))
    }

    private func closedIngressReceipt(for command: AppCommand) async -> CommandReceipt {
        await makeReceipt(
            reference: AppCommandReference(
                processInstanceId: process.processInstanceId,
                id: lastCompletedCommandId ?? 1
            ),
            status: .rejectedBusy
        )
    }

    private var currentCommandName: String?

    private func nextView(
        revision: Int64,
        phase: SessionPhase,
        account: CredentialAccount?,
        credentialVersion: Int64?,
        pendingRequestId: Int64?,
        lastCompletedCommandId: Int64?,
        lastCommandStatus: CommandStatus?
    ) -> DemoViewState {
        DemoViewState(
            processInstanceId: process.processInstanceId,
            revision: revision,
            phase: phase,
            account: account,
            credentialVersion: credentialVersion,
            pendingRequestId: pendingRequestId,
            lastCompletedCommandId: lastCompletedCommandId,
            lastCommandStatus: lastCommandStatus
        )
    }

    private static func commandJSON(_ reference: AppCommandReference) -> [String: Any] {
        ["processInstanceId": reference.processInstanceId, "id": reference.id]
    }

    private static func eventJSON(_ reference: NativeEventReference?) -> [String: Any]? {
        guard let reference else { return nil }
        return ["processInstanceId": reference.processInstanceId, "localSequence": reference.localSequence]
    }

    private static func viewJSON(_ view: DemoViewState) -> [String: Any] {
        [
            "phase": view.phase.rawValue,
            "account": view.account?.rawValue as Any? ?? NSNull(),
            "credentialVersion": view.credentialVersion as Any? ?? NSNull(),
            "pendingRequestId": view.pendingRequestId as Any? ?? NSNull(),
            "lastCompletedCommandId": view.lastCompletedCommandId as Any? ?? NSNull(),
            "lastCommandStatus": view.lastCommandStatus?.rawValue as Any? ?? NSNull(),
        ]
    }

    private static func observationJSON(_ observation: CommandObservation) -> [String: Any] {
        [
            "managed": managedJSON(observation.managed),
            "store": storeJSON(observation.store),
            "view": viewJSON(observation.view),
            "revision": observation.revision,
        ]
    }

    private static func storeJSON(_ observation: StoreObservation) -> [String: Any] {
        switch observation {
        case .absent:
            ["kind": "Absent"]
        case let .present(account, version):
            ["kind": "Present", "account": account, "version": version]
        case let .unknown(errorCode):
            ["kind": "Unknown", "errorCode": errorCode]
        }
    }

    private static func managedViewSnapshot(ownerId: String, snapshot: ManagedSnapshot) -> ManagedViewSnapshot {
        ManagedViewSnapshot(
            ownerId: ownerId,
            state: snapshot.state.rawValue,
            pendingRequestId: snapshot.pendingRequestId,
            nextRequestId: snapshot.nextRequestId
        )
    }

    private static func managedJSON(_ snapshot: ManagedViewSnapshot) -> [String: Any] {
        [
            "ownerId": snapshot.ownerId,
            "state": snapshot.state,
            "pendingRequestId": snapshot.pendingRequestId as Any? ?? NSNull(),
            "nextRequestId": snapshot.nextRequestId as Any? ?? NSNull(),
        ]
    }

    private static func managedResultJSON(ownerId: String, result: ManagedResult) -> [String: Any] {
        let effects: [[String: Any]] = result.effects.map { effect in
            switch effect {
            case .clearCredentials:
                ["effect": "ClearCredentials"]
            case let .requestTokenRefresh(request):
                ["effect": "RequestTokenRefresh", "requestId": request.requestId]
            }
        }
        let rejection: String?
        switch result.rejection {
        case .foreignRequest: rejection = "ForeignRequest"
        case .requestIdExhausted: rejection = "RequestIdExhausted"
        case nil: rejection = nil
        }
        return [
            "ownerId": ownerId,
            "state": result.snapshot.state.rawValue,
            "pendingRequestId": result.snapshot.pendingRequestId as Any? ?? NSNull(),
            "nextRequestId": result.snapshot.nextRequestId as Any? ?? NSNull(),
            "effects": effects,
            "rejection": rejection as Any? ?? NSNull(),
        ]
    }

    private func traceEffectLabel(for helperEffectId: String) -> String {
        if process.scenarioId == "CTRL-N2-LATE-CLEAR", helperEffectId.hasPrefix("duplicate-logout-") {
            return "late-clear-1"
        }
        return helperEffectId
    }
}

private extension Array {
    var only: Element? { count == 1 ? first : nil }
}

enum CoordinatorFailure: Error, Equatable {
    case processBusy
    case timeout
    case ended
    case terminalJournal
    case journalSequence(String)
}
