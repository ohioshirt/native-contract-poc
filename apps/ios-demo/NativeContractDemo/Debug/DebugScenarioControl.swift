import Foundation

enum HookTarget: String, CaseIterable, Codable, Sendable {
    case bootstrap
    case nextCommand
    case nextDelivery
}

enum StoreFaultKind: String, CaseIterable, Codable, Sendable {
    case none
    case replaceBefore
    case replaceAfterBeforeVerify
    case clearBefore
    case clearAfterBeforeVerify
}

enum ControlAckStatus: String, Codable, Sendable {
    case applied
    case scheduled
}

enum HookPhase: String, Codable, Sendable {
    case armed
    case arrived
    case released
}

enum DebugControlError: String, Error, Codable, Sendable {
    case alreadyArmed
    case notArrived
    case alreadyReleased
    case noCapturedCompletion
    case probeNotSafe
    case timeout
    case processBusy
    case invalidArgument
}

struct CommandReference: Equatable, Codable, Sendable {
    let processInstanceId: String
    let id: Int64
}

struct ControlAck: Equatable, Codable, Sendable {
    let actionId: Int64
    let controlRevision: Int64
    let status: ControlAckStatus
}

struct ProcessEndEventReference: Equatable, Codable, Sendable {
    let processInstanceId: String
    let localSequence: Int64
}

/// Cached acknowledgement for the one synchronized terminal native processEnd row.
struct ProcessEndAck: Equatable, Codable, Sendable {
    let processInstanceId: String
    let eventRef: ProcessEndEventReference
}

struct HookObservation: Equatable, Codable, Sendable {
    /// The checked ControlAck.actionId assigned when this hook was armed.
    let armSequence: Int64
    let point: HookPoint
    let phase: HookPhase
    let target: HookTarget
    let arrivalCommandRef: CommandReference?
}

struct ProbeResult: Equatable, Codable, Sendable {
    /// Unique for this process; never reuse an earlier OS-read result ID.
    let probeId: String
    let processInstanceId: String
    let observation: StoreObservation
}

struct ControlSnapshot: Equatable, Codable, Sendable {
    let version: Int
    let processInstanceId: String
    let launchOrdinal: Int64
    let controlRevision: Int64
    let lastActionId: Int64?
    let lastActionStatus: ControlAckStatus?
    let lastEnqueuedCommandRef: CommandReference?
    let lastProcessedCommandRef: CommandReference?
    let storeIoActive: Bool
    let hooks: [HookObservation]
    let lastProbe: ProbeResult?

    init(
        processInstanceId: String,
        launchOrdinal: Int64,
        controlRevision: Int64,
        lastActionId: Int64? = nil,
        lastActionStatus: ControlAckStatus? = nil,
        lastEnqueuedCommandRef: CommandReference? = nil,
        lastProcessedCommandRef: CommandReference? = nil,
        storeIoActive: Bool,
        hooks: [HookObservation],
        lastProbe: ProbeResult? = nil
    ) {
        self.version = 1
        self.processInstanceId = processInstanceId
        self.launchOrdinal = launchOrdinal
        self.controlRevision = controlRevision
        self.lastActionId = lastActionId
        self.lastActionStatus = lastActionStatus
        self.lastEnqueuedCommandRef = lastEnqueuedCommandRef
        self.lastProcessedCommandRef = lastProcessedCommandRef
        self.storeIoActive = storeIoActive
        self.hooks = hooks
        self.lastProbe = lastProbe
    }
}

/// Control operations use a synchronization boundary separate from the auth mailbox.
protocol DebugScenarioControl: Sendable {
    func arm(_ point: HookPoint, target: HookTarget) throws -> ControlAck
    func awaitArrival(_ point: HookPoint, timeoutMillis: Int64) async throws -> HookObservation
    func release(_ point: HookPoint) throws -> ControlAck
    func replayLastCompletion() throws -> ControlAck
    func injectStoreFault(_ kind: StoreFaultKind) throws -> ControlAck
    func probeStore() async throws -> ProbeResult
    func snapshot() -> ControlSnapshot
    func finishProcess(timeoutMillis: Int64) async throws -> ProcessEndAck
}

enum DebugScenarioControlPanelID {
    static func target(_ target: HookTarget) -> String { "hook-target-\(target.rawValue)" }
    static func arm(_ point: HookPoint) -> String { "hook-arm-\(point.rawValue)" }
    static func release(_ point: HookPoint) -> String { "hook-release-\(point.rawValue)" }
    static func state(_ point: HookPoint) -> String { "hook-state-\(point.rawValue)" }
    static func fault(_ kind: StoreFaultKind) -> String { "fault-set-\(kind.rawValue)" }

    static let replayLast = "replay-last"
    static let probeStore = "probe-store"
    static let storeProbeResult = "store-probe-result"
    static let controlStatusJSON = "control-status-json"
    static let lastEnqueuedCommandID = "last-enqueued-command-id"
    static let finishProcess = "finish-process"
    static let processEndAckJSON = "process-end-ack-json"
}
