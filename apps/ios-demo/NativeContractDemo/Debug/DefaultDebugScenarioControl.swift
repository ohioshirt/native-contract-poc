import Foundation

final class DefaultDebugScenarioControl: DebugScenarioControl, @unchecked Sendable {
    private let lock = NSLock()
    private let admission = ControlOperationGate()
    private let process: ProcessContext
    private let coordinator: SessionCoordinator
    private let store: any StoreFaultInjecting
    private let hooks: DebugScenarioHooks
    private let ingress: DemoIngress
    private let service: String
    private let revisionClock: ControlRevisionClock
    private let onControlAdmitted: @Sendable (String) -> Void
    private let onFinishWaitingForControls: @Sendable () -> Void
    private var nextActionId: Int64 = 1
    private var nextProbeOrdinal: Int64 = 1
    private var lastActionId: Int64?
    private var lastActionStatus: ControlAckStatus?
    private var lastProbe: ProbeResult?
    private var endedAcknowledgement: ProcessEndAck?

    init(
        process: ProcessContext,
        coordinator: SessionCoordinator,
        store: any StoreFaultInjecting,
        hooks: DebugScenarioHooks,
        ingress: DemoIngress,
        service: String,
        revisionClock: ControlRevisionClock,
        onControlAdmitted: @escaping @Sendable (String) -> Void = { _ in },
        onFinishWaitingForControls: @escaping @Sendable () -> Void = {}
    ) {
        self.process = process
        self.coordinator = coordinator
        self.store = store
        self.hooks = hooks
        self.ingress = ingress
        self.service = service
        self.revisionClock = revisionClock
        self.onControlAdmitted = onControlAdmitted
        self.onFinishWaitingForControls = onFinishWaitingForControls
    }

    func arm(_ point: HookPoint, target: HookTarget) throws -> ControlAck {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("arm")
        let actionId = try allocateActionId()
        _ = try hooks.arm(point, target: target, actionId: actionId)
        return recordAction(actionId, status: .applied)
    }

    func awaitArrival(_ point: HookPoint, timeoutMillis: Int64) async throws -> HookObservation {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("awaitArrival")
        return try await hooks.awaitArrival(point, timeoutMillis: timeoutMillis)
    }

    func release(_ point: HookPoint) throws -> ControlAck {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("release")
        let actionId = try hooks.release(point)
        return recordAction(actionId, status: .applied)
    }

    func replayLastCompletion() throws -> ControlAck {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("replayLastCompletion")
        let actionId = try allocateActionId()
        try ingress.replayLastCompletion()
        return recordAction(actionId, status: .scheduled)
    }

    func injectStoreFault(_ kind: StoreFaultKind) throws -> ControlAck {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("injectStoreFault")
        let actionId = try allocateActionId()
        store.setStoreFault(kind == .none ? nil : kind.rawValue)
        return recordAction(actionId, status: .applied)
    }

    func probeStore() async throws -> ProbeResult {
        try admission.admit()
        defer { admission.complete() }
        onControlAdmitted("probeStore")
        try hooks.beginProbe()
        defer { hooks.endProbe() }
        let probeId = try allocateProbeId()
        let result = StorageProbe.read(
            service: service,
            probeId: probeId,
            processInstanceId: process.processInstanceId
        )
        let actionId = try allocateActionId()
        lock.withLock { lastProbe = result }
        _ = recordAction(actionId, status: .applied)
        return result
    }

    func snapshot() -> ControlSnapshot {
        let values = lock.withLock {
            (lastActionId, lastActionStatus, lastProbe, endedAcknowledgement)
        }
        let hookSnapshot = hooks.snapshot()
        return ControlSnapshot(
            processInstanceId: process.processInstanceId,
            launchOrdinal: process.launchOrdinal,
            controlRevision: revisionClock.current,
            lastActionId: values.0,
            lastActionStatus: values.1,
            lastEnqueuedCommandRef: hookSnapshot.lastEnqueuedCommandRef,
            lastProcessedCommandRef: hookSnapshot.lastProcessedCommandRef,
            storeIoActive: hookSnapshot.storeIoActive,
            hooks: hookSnapshot.hooks,
            lastProbe: values.2
        )
    }

    func finishProcess(timeoutMillis: Int64) async throws -> ProcessEndAck {
        guard (1...21_600_000).contains(timeoutMillis) else { throw DebugControlError.timeout }
        let start = admission.beginFinish()
        switch start {
        case .ended:
            guard let acknowledgement = lock.withLock({ endedAcknowledgement }) else {
                throw DebugControlError.processBusy
            }
            return acknowledgement
        case .busy: throw DebugControlError.processBusy
        case .begin: break
        }

        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .milliseconds(timeoutMillis))
        do {
            guard !hooks.hasPausedHook else { throw DebugControlError.processBusy }
            guard let gateWaitMillis = remainingMilliseconds(until: deadline) else {
                throw DebugControlError.timeout
            }
            try await admission.waitForQuiescence(
                timeoutMillis: gateWaitMillis,
                onWaitStarted: onFinishWaitingForControls
            )
            guard !hooks.hasPausedHook else { throw DebugControlError.processBusy }
            guard let drainMillis = remainingMilliseconds(until: deadline) else {
                throw DebugControlError.timeout
            }
            let nativeReference = try await coordinator.finishNativeProcess(timeoutMillis: drainMillis)
            let eventReference = ProcessEndEventReference(
                processInstanceId: nativeReference.processInstanceId,
                localSequence: nativeReference.localSequence
            )
            let acknowledgement = ProcessEndAck(processInstanceId: process.processInstanceId, eventRef: eventReference)
            lock.withLock { endedAcknowledgement = acknowledgement }
            admission.markEnded()
            return acknowledgement
        } catch {
            if (error as? CoordinatorFailure) == .terminalJournal {
                admission.markFailed()
            } else {
                admission.reopen()
            }
            if let controlError = error as? DebugControlError { throw controlError }
            if let failure = error as? CoordinatorFailure, failure == .timeout {
                throw DebugControlError.timeout
            }
            throw DebugControlError.processBusy
        }
    }

    func installLaunchControls(armPoint: HookPoint?, armTarget: HookTarget?, storeFault: StoreFaultKind?) throws {
        if let armPoint {
            guard let armTarget else { throw DebugControlError.invalidArgument }
            _ = try arm(armPoint, target: armTarget)
        }
        if let storeFault { _ = try injectStoreFault(storeFault) }
    }

    private func allocateActionId() throws -> Int64 {
        try lock.withLock {
            guard nextActionId > 0, nextActionId < Int64.max else { throw DebugControlError.invalidArgument }
            let result = nextActionId
            nextActionId += 1
            return result
        }
    }

    private func allocateProbeId() throws -> String {
        try lock.withLock {
            guard nextProbeOrdinal > 0, nextProbeOrdinal < Int64.max else { throw DebugControlError.invalidArgument }
            let ordinal = nextProbeOrdinal
            nextProbeOrdinal += 1
            return "probe-\(process.launchOrdinal)-\(ordinal)-\(UUID().uuidString)"
        }
    }

    private func recordAction(_ actionId: Int64, status: ControlAckStatus) -> ControlAck {
        lock.withLock {
            lastActionId = actionId
            lastActionStatus = status
        }
        let revision = revisionClock.bump()
        return ControlAck(actionId: actionId, controlRevision: revision, status: status)
    }
}

enum ControlFinishStart {
    case ended
    case begin
    case busy
}

final class ControlOperationGate: @unchecked Sendable {
    private enum State {
        case open
        case closing
        case ended
        case failed
    }

    private let condition = NSCondition()
    private var state = State.open
    private var inFlight = 0

    func admit() throws {
        condition.lock()
        defer { condition.unlock() }
        guard case .open = state, inFlight < Int.max else { throw DebugControlError.processBusy }
        inFlight += 1
    }

    func complete() {
        condition.lock()
        defer { condition.unlock() }
        precondition(inFlight > 0, "control admission underflow")
        inFlight -= 1
        if inFlight == 0 { condition.broadcast() }
    }

    func beginFinish() -> ControlFinishStart {
        condition.lock()
        defer { condition.unlock() }
        switch state {
        case .open:
            state = .closing
            return .begin
        case .ended:
            return .ended
        case .closing, .failed:
            return .busy
        }
    }

    func waitForQuiescence(
        timeoutMillis: Int64,
        onWaitStarted: @escaping @Sendable () -> Void = {}
    ) async throws {
        guard (1...21_600_000).contains(timeoutMillis) else { throw DebugControlError.timeout }
        let deadline = Date(timeIntervalSinceNow: Double(timeoutMillis) / 1_000)
        let quiescent = await Task.detached { [self] in
            waitSynchronously(until: deadline, onWaitStarted: onWaitStarted)
        }.value
        guard quiescent else { throw DebugControlError.timeout }
    }

    private func waitSynchronously(
        until deadline: Date,
        onWaitStarted: @Sendable () -> Void
    ) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        if inFlight > 0 { onWaitStarted() }
        while inFlight > 0 {
            if !condition.wait(until: deadline) { return false }
        }
        return true
    }

    func reopen() {
        condition.lock()
        if case .closing = state { state = .open }
        condition.broadcast()
        condition.unlock()
    }

    func markEnded() {
        condition.lock()
        guard case .closing = state else {
            condition.unlock()
            preconditionFailure("process end requires closed control admission")
        }
        state = .ended
        condition.broadcast()
        condition.unlock()
    }

    func markFailed() {
        condition.lock()
        state = .failed
        condition.broadcast()
        condition.unlock()
    }
}

private func remainingMilliseconds(until deadline: ContinuousClock.Instant) -> Int64? {
    let duration = ContinuousClock().now.duration(to: deadline)
    let components = duration.components
    let milliseconds = components.seconds * 1_000 + components.attoseconds / 1_000_000_000_000_000
    return milliseconds > 0 ? milliseconds : nil
}
