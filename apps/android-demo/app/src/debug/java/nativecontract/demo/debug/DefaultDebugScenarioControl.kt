package nativecontract.demo.debug

import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.coordinator.CoordinatorFailure
import nativecontract.demo.coordinator.CoordinatorFailureCode
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.storage.StoreFaultInjecting

/**
 * Independent Debug control plane. Every operation uses [ControlOperationGate]
 * and the hooks' own lock; none enters or waits on the coordinator mailbox.
 * `probe` performs the frozen read-only store probe for a fresh probe ID.
 */
class DefaultDebugScenarioControl(
    private val process: ProcessContext,
    private val coordinator: SessionCoordinator,
    private val store: StoreFaultInjecting,
    private val hooks: DebugScenarioHooks,
    private val ingress: DemoIngress,
    private val probe: (String) -> ProbeResult,
    private val revisionClock: ControlRevisionClock,
    private val onFinishWaitingForControls: () -> Unit = {},
) : DebugScenarioControl {
    private val lock = Any()
    private val admission = ControlOperationGate()
    private var nextActionId = 1L
    private var nextProbeOrdinal = 1L
    private var lastActionId: Long? = null
    private var lastActionStatus: ControlAckStatus? = null
    private var lastProbe: ProbeResult? = null
    private var endedAcknowledgement: ProcessEndAck? = null

    override fun arm(point: HookPoint, target: HookTarget): ControlAck = admitted {
        val actionId = allocateActionId()
        hooks.arm(point, target, actionId)
        recordAction(actionId, ControlAckStatus.APPLIED)
    }

    override fun awaitArrival(point: HookPoint, timeoutMillis: Long): HookObservation = admitted {
        hooks.awaitArrival(point, timeoutMillis)
    }

    override fun release(point: HookPoint): ControlAck = admitted {
        recordAction(hooks.release(point), ControlAckStatus.APPLIED)
    }

    override fun replayLastCompletion(): ControlAck = admitted {
        val actionId = allocateActionId()
        ingress.replayLastCompletion()
        recordAction(actionId, ControlAckStatus.SCHEDULED)
    }

    override fun injectStoreFault(kind: StoreFaultKind): ControlAck = admitted {
        val actionId = allocateActionId()
        store.setStoreFault(if (kind == StoreFaultKind.NONE) null else kind.wireValue)
        recordAction(actionId, ControlAckStatus.APPLIED)
    }

    override fun probeStore(): CompletableFuture<ProbeResult> = admitted {
        hooks.beginProbe()
        val result = try {
            probe(allocateProbeId())
        } finally {
            hooks.endProbe()
        }
        val actionId = allocateActionId()
        synchronized(lock) { lastProbe = result }
        recordAction(actionId, ControlAckStatus.APPLIED)
        CompletableFuture.completedFuture(result)
    }

    override fun snapshot(): ControlSnapshot {
        val values = synchronized(lock) { Triple(lastActionId, lastActionStatus, lastProbe) }
        val hookSnapshot = hooks.snapshot()
        return ControlSnapshot(
            processInstanceId = process.processInstanceId,
            launchOrdinal = process.launchOrdinal,
            controlRevision = revisionClock.current,
            lastActionId = values.first,
            lastActionStatus = values.second,
            lastEnqueuedCommandRef = hookSnapshot.lastEnqueuedCommandRef,
            lastProcessedCommandRef = hookSnapshot.lastProcessedCommandRef,
            storeIoActive = hookSnapshot.storeIoActive,
            hooks = hookSnapshot.hooks,
            lastProbe = values.third,
        )
    }

    override fun finishProcess(timeoutMillis: Long): ProcessEndAck {
        if (timeoutMillis !in 1L..21_600_000L) throw DebugControlException(DebugControlErrorCode.TIMEOUT)
        when (admission.beginFinish()) {
            ControlFinishStart.ENDED -> return synchronized(lock) { endedAcknowledgement }
                ?: throw DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
            ControlFinishStart.BUSY -> throw DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
            ControlFinishStart.BEGIN -> Unit
        }
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        try {
            if (hooks.hasPausedHook) throw DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
            admission.waitForQuiescence(remainingMillis(deadline), onFinishWaitingForControls)
            if (hooks.hasPausedHook) throw DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
            val native = coordinator.finishNativeProcess(remainingMillis(deadline))
            val acknowledgement = ProcessEndAck(
                process.processInstanceId,
                ProcessEndEventReference(native.processInstanceId, native.localSequence),
            )
            synchronized(lock) { endedAcknowledgement = acknowledgement }
            admission.markEnded()
            return acknowledgement
        } catch (error: Exception) {
            if (error is CoordinatorFailure && error.code == CoordinatorFailureCode.TERMINAL_JOURNAL) {
                admission.markFailed()
            } else {
                admission.reopen()
            }
            throw when {
                error is DebugControlException -> error
                error is CoordinatorFailure && error.code == CoordinatorFailureCode.TIMEOUT ->
                    DebugControlException(DebugControlErrorCode.TIMEOUT)
                else -> DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
            }
        }
    }

    /** Startup arms and faults are applied before Bootstrap is submitted. */
    fun installLaunchControls(armPoint: HookPoint?, armTarget: HookTarget?, storeFault: StoreFaultKind?) {
        if ((armPoint == null) != (armTarget == null)) throw DebugControlException(DebugControlErrorCode.INVALID_ARGUMENT)
        if (armPoint != null && armTarget != null) arm(armPoint, armTarget)
        if (storeFault != null) injectStoreFault(storeFault)
    }

    private inline fun <T> admitted(operation: () -> T): T {
        admission.admit()
        try {
            return operation()
        } finally {
            admission.complete()
        }
    }

    private fun allocateActionId(): Long = synchronized(lock) {
        if (nextActionId <= 0L || nextActionId == Long.MAX_VALUE) throw DebugControlException(DebugControlErrorCode.INVALID_ARGUMENT)
        nextActionId++
    }

    private fun allocateProbeId(): String = synchronized(lock) {
        if (nextProbeOrdinal <= 0L || nextProbeOrdinal == Long.MAX_VALUE) throw DebugControlException(DebugControlErrorCode.INVALID_ARGUMENT)
        "probe-${process.launchOrdinal}-${nextProbeOrdinal++}-${UUID.randomUUID()}"
    }

    private fun recordAction(actionId: Long, status: ControlAckStatus): ControlAck {
        synchronized(lock) {
            lastActionId = actionId
            lastActionStatus = status
        }
        return ControlAck(actionId, revisionClock.bump(), status)
    }

    private fun remainingMillis(deadline: Long): Long {
        val remaining = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime())
        if (remaining <= 0L) throw DebugControlException(DebugControlErrorCode.TIMEOUT)
        return remaining
    }
}

enum class ControlFinishStart { ENDED, BEGIN, BUSY }

/** Open → Closing → Ended(ack) admission for Debug control operations. */
class ControlOperationGate {
    private enum class State { OPEN, CLOSING, ENDED, FAILED }

    private val lock = ReentrantLock()
    private val quiescent = lock.newCondition()
    private var state = State.OPEN
    private var inFlight = 0

    fun admit() = lock.withLock {
        if (state != State.OPEN || inFlight == Int.MAX_VALUE) throw DebugControlException(DebugControlErrorCode.PROCESS_BUSY)
        inFlight += 1
    }

    fun complete() = lock.withLock {
        check(inFlight > 0) { "control admission underflow" }
        inFlight -= 1
        if (inFlight == 0) quiescent.signalAll()
    }

    fun beginFinish(): ControlFinishStart = lock.withLock {
        when (state) {
            State.OPEN -> {
                state = State.CLOSING
                ControlFinishStart.BEGIN
            }
            State.ENDED -> ControlFinishStart.ENDED
            State.CLOSING, State.FAILED -> ControlFinishStart.BUSY
        }
    }

    fun waitForQuiescence(timeoutMillis: Long, onWaitStarted: () -> Unit) {
        lock.withLock {
            if (inFlight > 0) onWaitStarted()
            var remaining = TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
            while (inFlight > 0) {
                if (remaining <= 0L) throw DebugControlException(DebugControlErrorCode.TIMEOUT)
                remaining = quiescent.awaitNanos(remaining)
            }
        }
    }

    fun reopen() = lock.withLock {
        if (state == State.CLOSING) state = State.OPEN
        quiescent.signalAll()
    }

    fun markEnded() = lock.withLock {
        check(state == State.CLOSING) { "process end requires closed control admission" }
        state = State.ENDED
        quiescent.signalAll()
    }

    fun markFailed() = lock.withLock {
        state = State.FAILED
        quiescent.signalAll()
    }
}
