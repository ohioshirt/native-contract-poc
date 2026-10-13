package nativecontract.demo.debug

import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.transport.Completion

/**
 * Debug-only replay retains the exact decoded response and opaque issued slot from
 * the transport. Replay re-enters the ordinary coordinator mailbox as a Deliver.
 */
class DemoIngress {
    private var lastCompletion: Completion? = null
    private var coordinator: SessionCoordinator? = null

    @Synchronized
    fun attach(coordinator: SessionCoordinator) {
        this.coordinator = coordinator
    }

    @Synchronized
    fun capture(completion: Completion) {
        lastCompletion = completion
    }

    fun replayLastCompletion() {
        val (completion, coordinator) = synchronized(this) { lastCompletion to coordinator }
        if (completion == null || coordinator == null) {
            throw DebugControlException(DebugControlErrorCode.NO_CAPTURED_COMPLETION)
        }
        coordinator.submit(AppCommand.Deliver(completion))
    }
}
