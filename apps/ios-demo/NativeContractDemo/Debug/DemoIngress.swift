import Foundation

/// Debug-only replay retains the exact response and opaque issued slot that
/// arrived from URLSession. Replay re-enters the ordinary coordinator mailbox.
final class DemoIngress: @unchecked Sendable {
    private let lock = NSLock()
    private var lastCompletion: Completion?
    private weak var coordinator: SessionCoordinator?

    func attach(_ coordinator: SessionCoordinator) {
        lock.withLock { self.coordinator = coordinator }
    }

    func capture(_ completion: Completion) {
        lock.withLock { lastCompletion = completion }
    }

    func replayLastCompletion() throws {
        let (completion, coordinator) = lock.withLock { (lastCompletion, self.coordinator) }
        guard let completion, let coordinator else { throw DebugControlError.noCapturedCompletion }
        Task { await coordinator.submit(.deliver(completion)) }
    }
}
