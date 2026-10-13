import Foundation
import NativeContract

/// App-internal await points; control release is independent of the auth mailbox.
protocol ScenarioHooks: Sendable {
    var hasPausedHook: Bool { get }
    func pauseIfArmed(_ point: HookPoint) async
    func releasedActionId(for point: HookPoint) -> Int64?
    func commandEnqueued(_ reference: AppCommandReference, name: String)
    func commandStarted(_ reference: AppCommandReference, name: String)
    func commandProcessed(_ reference: AppCommandReference)
    func storeIOChanged(_ active: Bool)
    func pauseDetachedEffect(effectId: String, originCommandId: Int64) async -> Int64
}

extension ScenarioHooks {
    var hasPausedHook: Bool { false }
    func commandEnqueued(_ reference: AppCommandReference, name: String) {}
    func commandStarted(_ reference: AppCommandReference, name: String) {}
    func commandProcessed(_ reference: AppCommandReference) {}
    func storeIOChanged(_ active: Bool) {}
    func pauseDetachedEffect(effectId: String, originCommandId: Int64) async -> Int64 { 0 }
    func releasedActionId(for point: HookPoint) -> Int64? { nil }
}

struct NoopScenarioHooks: ScenarioHooks {
    func pauseIfArmed(_ point: HookPoint) async {}
}
