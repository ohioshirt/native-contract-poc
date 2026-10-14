import Foundation

final class ControlRevisionClock: @unchecked Sendable {
    private let lock = NSLock()
    private var revision: Int64 = 0

    var current: Int64 { lock.withLock { revision } }

    @discardableResult
    func bump() -> Int64 {
        lock.withLock {
            guard revision < Int64.max else { fatalError("CounterExhausted: control revision") }
            revision += 1
            return revision
        }
    }
}

final class DebugScenarioHooks: ScenarioHooks, @unchecked Sendable {
    private final class HookRecord {
        let point: HookPoint
        let target: HookTarget
        let actionId: Int64
        var phase: HookPhase = .armed
        var selectedCommandRef: CommandReference?
        var arrivalCommandRef: CommandReference?
        var releaseContinuation: CheckedContinuation<Void, Never>?
        var detachedReleaseContinuation: CheckedContinuation<Int64, Never>?

        init(point: HookPoint, target: HookTarget, actionId: Int64) {
            self.point = point
            self.target = target
            self.actionId = actionId
        }

        var observation: HookObservation {
            HookObservation(
                armSequence: actionId,
                point: point,
                phase: phase,
                target: target,
                arrivalCommandRef: arrivalCommandRef
            )
        }
    }

    struct Snapshot {
        let hooks: [HookObservation]
        let storeIoActive: Bool
        let lastEnqueuedCommandRef: CommandReference?
        let lastProcessedCommandRef: CommandReference?
    }

    private let condition = NSCondition()
    private let process: ProcessContext
    private let audit: any AuditRecorder
    private let revisionClock: ControlRevisionClock
    private var records: [HookPoint: HookRecord] = [:]
    private var commandNames: [Int64: String] = [:]
    private var activeCommandRef: CommandReference?
    private var lastEnqueued: CommandReference?
    private var lastProcessed: CommandReference?
    private var storeIoActive = false
    private var probeActive = false

    init(process: ProcessContext, audit: any AuditRecorder, revisionClock: ControlRevisionClock) {
        self.process = process
        self.audit = audit
        self.revisionClock = revisionClock
    }

    var hasPausedHook: Bool {
        condition.lock()
        defer { condition.unlock() }
        return records.values.contains {
            $0.phase == .arrived && ($0.releaseContinuation != nil || $0.detachedReleaseContinuation != nil)
        }
    }

    func releasedActionId(for point: HookPoint) -> Int64? {
        condition.lock()
        defer { condition.unlock() }
        guard let record = records[point], record.phase == .released else { return nil }
        return record.actionId
    }

    func arm(_ point: HookPoint, target: HookTarget, actionId: Int64) throws -> HookObservation {
        condition.lock()
        defer { condition.unlock() }
        guard records[point] == nil, actionId > 0 else { throw DebugControlError.alreadyArmed }
        let record = HookRecord(point: point, target: target, actionId: actionId)
        records[point] = record
        do { try appendHookEvent(record, phase: .armed, commandRef: nil) }
        catch {
            records.removeValue(forKey: point)
            throw error
        }
        revisionClock.bump()
        return record.observation
    }

    func awaitArrival(_ point: HookPoint, timeoutMillis: Int64) async throws -> HookObservation {
        guard (1...21_600_000).contains(timeoutMillis) else { throw DebugControlError.invalidArgument }
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .milliseconds(timeoutMillis))
        while clock.now < deadline {
            let observation = hookObservation(point)
            if let observation, observation.phase == .arrived || observation.phase == .released {
                return observation
            }
            try await Task.sleep(for: .milliseconds(5))
        }
        throw DebugControlError.timeout
    }

    func release(_ point: HookPoint) throws -> Int64 {
        condition.lock()
        guard let record = records[point] else {
            condition.unlock()
            throw DebugControlError.notArrived
        }
        guard record.phase == .arrived,
              record.releaseContinuation != nil || record.detachedReleaseContinuation != nil else {
            condition.unlock()
            throw record.phase == .released ? DebugControlError.alreadyReleased : DebugControlError.notArrived
        }
        do { try appendHookEvent(record, phase: .released, commandRef: record.arrivalCommandRef) }
        catch {
            condition.unlock()
            throw error
        }
        record.phase = .released
        let continuation = record.releaseContinuation
        let detachedContinuation = record.detachedReleaseContinuation
        record.releaseContinuation = nil
        record.detachedReleaseContinuation = nil
        revisionClock.bump()
        let actionId = record.actionId
        condition.broadcast()
        condition.unlock()
        continuation?.resume()
        detachedContinuation?.resume(returning: actionId)
        return actionId
    }

    func pauseIfArmed(_ point: HookPoint) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            condition.lock()
            let commandRef = point == .afterLogoutReceipt ? lastProcessed : activeCommandRef
            guard let record = records[point], record.phase == .armed,
                  point != .beforeDeferredControlClear,
                  let reference = commandRef,
                  record.selectedCommandRef == reference else {
                condition.unlock()
                continuation.resume()
                return
            }
            arrive(record, commandRef: reference, continuation: continuation)
            condition.unlock()
        }
    }

    func pauseDetachedEffect(effectId: String, originCommandId: Int64) async -> Int64 {
        await withCheckedContinuation { (continuation: CheckedContinuation<Int64, Never>) in
            condition.lock()
            guard let record = records[.beforeDeferredControlClear],
                  record.phase == .armed,
                  record.target == .nextCommand,
                  commandNames[originCommandId] == "Logout" else {
                condition.unlock()
                continuation.resume(returning: 0)
                return
            }
            let origin = CommandReference(processInstanceId: process.processInstanceId, id: originCommandId)
            arriveDetached(record, commandRef: origin, continuation: continuation)
            condition.unlock()
        }
    }

    func commandEnqueued(_ reference: AppCommandReference, name: String) {
        condition.lock()
        let controlReference = Self.controlReference(reference)
        lastEnqueued = controlReference
        commandNames[reference.id] = name
        for record in records.values where record.phase == .armed && record.point != .beforeDeferredControlClear && record.selectedCommandRef == nil {
            if targetMatches(record.target, commandName: name) {
                record.selectedCommandRef = controlReference
            }
        }
        revisionClock.bump()
        condition.broadcast()
        condition.unlock()
    }

    func commandStarted(_ reference: AppCommandReference, name: String) {
        condition.lock()
        activeCommandRef = Self.controlReference(reference)
        condition.unlock()
    }

    func commandProcessed(_ reference: AppCommandReference) {
        condition.lock()
        let controlReference = Self.controlReference(reference)
        lastProcessed = controlReference
        if activeCommandRef == controlReference {
            activeCommandRef = nil
        }
        revisionClock.bump()
        condition.broadcast()
        condition.unlock()
    }

    func storeIOChanged(_ active: Bool) {
        condition.lock()
        if active {
            while probeActive { condition.wait() }
            storeIoActive = true
        } else {
            storeIoActive = false
            condition.broadcast()
        }
        revisionClock.bump()
        condition.unlock()
    }

    func snapshot() -> Snapshot {
        condition.lock()
        defer { condition.unlock() }
        return Snapshot(
            hooks: records.values.map(\.observation).sorted { $0.armSequence < $1.armSequence },
            storeIoActive: storeIoActive,
            lastEnqueuedCommandRef: lastEnqueued,
            lastProcessedCommandRef: lastProcessed
        )
    }

    func beginProbe() throws {
        condition.lock()
        defer { condition.unlock() }
        guard !storeIoActive, !probeActive else { throw DebugControlError.probeNotSafe }
        probeActive = true
    }

    func endProbe() {
        condition.lock()
        probeActive = false
        condition.broadcast()
        condition.unlock()
    }

    private func targetMatches(_ target: HookTarget, commandName: String) -> Bool {
        switch target {
        case .bootstrap: commandName == "Bootstrap"
        case .nextCommand: true
        case .nextDelivery: commandName.hasPrefix("Deliver(")
        }
    }

    private func hookObservation(_ point: HookPoint) -> HookObservation? {
        condition.lock()
        defer { condition.unlock() }
        return records[point]?.observation
    }

    private func arrive(
        _ record: HookRecord,
        commandRef: CommandReference,
        continuation: CheckedContinuation<Void, Never>
    ) {
        do { try appendHookEvent(record, phase: .arrived, commandRef: commandRef) }
        catch { fatalError("hook arrival could not be synchronized: \(error)") }
        record.phase = .arrived
        record.arrivalCommandRef = commandRef
        record.releaseContinuation = continuation
        revisionClock.bump()
        condition.broadcast()
    }

    private func arriveDetached(
        _ record: HookRecord,
        commandRef: CommandReference,
        continuation: CheckedContinuation<Int64, Never>
    ) {
        do { try appendHookEvent(record, phase: .arrived, commandRef: commandRef) }
        catch { fatalError("detached hook arrival could not be synchronized: \(error)") }
        record.phase = .arrived
        record.arrivalCommandRef = commandRef
        record.detachedReleaseContinuation = continuation
        revisionClock.bump()
        condition.broadcast()
    }

    private func appendHookEvent(_ record: HookRecord, phase: HookPhase, commandRef: CommandReference?) throws {
        var fields: [String: Any] = [
            "actionId": record.actionId,
            "point": record.point.rawValue,
            "phase": phase.rawValue,
            "target": record.target.rawValue,
        ]
        if let commandRef {
            fields["commandRef"] = ["processInstanceId": commandRef.processInstanceId, "id": commandRef.id]
        }
        let data = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        _ = try audit.append(kind: "hookEvent", fields: data)
        try audit.synchronize()
    }

    private static func controlReference(_ reference: AppCommandReference) -> CommandReference {
        CommandReference(processInstanceId: reference.processInstanceId, id: reference.id)
    }
}
