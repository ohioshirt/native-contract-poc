package nativecontract.demo.debug

import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.coordinator.AppCommandReference
import nativecontract.demo.coordinator.AuditRecorder
import nativecontract.demo.coordinator.FailStop
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.ScenarioHooks

class ControlRevisionClock {
    private val revision = AtomicLong(0L)

    val current: Long get() = revision.get()

    fun bump(): Long = revision.updateAndGet { value ->
        if (value == Long.MAX_VALUE) FailStop.stop("CounterExhausted: control revision")
        value + 1L
    }
}

/**
 * Debug barriers with their own lock/condition. A paused coordinator worker waits
 * on this condition; release comes from the control plane and never enters or
 * waits on the auth mailbox.
 */
class DebugScenarioHooks(
    private val process: ProcessContext,
    private val audit: AuditRecorder,
    private val revisionClock: ControlRevisionClock,
) : ScenarioHooks {
    private class HookRecord(val point: HookPoint, val target: HookTarget, val actionId: Long) {
        var phase = HookPhase.ARMED
        var selectedCommandRef: CommandReference? = null
        var arrivalCommandRef: CommandReference? = null
        var waiting = false

        val observation: HookObservation
            get() = HookObservation(actionId, point, phase, target, arrivalCommandRef)
    }

    data class Snapshot(
        val hooks: List<HookObservation>,
        val storeIoActive: Boolean,
        val lastEnqueuedCommandRef: CommandReference?,
        val lastProcessedCommandRef: CommandReference?,
    )

    private val lock = ReentrantLock()
    private val changed = lock.newCondition()
    private val records = LinkedHashMap<HookPoint, HookRecord>()
    private val commandNames = HashMap<Long, String>()
    private var activeCommandRef: CommandReference? = null
    private var lastEnqueued: CommandReference? = null
    private var lastProcessed: CommandReference? = null
    private var storeIoActive = false
    private var probeActive = false

    override val hasPausedHook: Boolean
        get() = lock.withLock { records.values.any { it.phase == HookPhase.ARRIVED && it.waiting } }

    override fun releasedActionId(point: HookPoint): Long? = lock.withLock {
        records[point]?.takeIf { it.phase == HookPhase.RELEASED }?.actionId
    }

    fun arm(point: HookPoint, target: HookTarget, actionId: Long): HookObservation = lock.withLock {
        if (actionId <= 0L) throw DebugControlException(DebugControlErrorCode.INVALID_ARGUMENT)
        if (records.containsKey(point)) throw DebugControlException(DebugControlErrorCode.ALREADY_ARMED)
        val record = HookRecord(point, target, actionId)
        appendHookEvent(record, HookPhase.ARMED, null)
        records[point] = record
        revisionClock.bump()
        changed.signalAll()
        record.observation
    }

    fun awaitArrival(point: HookPoint, timeoutMillis: Long): HookObservation {
        if (timeoutMillis !in 1L..21_600_000L) throw DebugControlException(DebugControlErrorCode.INVALID_ARGUMENT)
        var remaining = TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        lock.withLock {
            while (true) {
                val record = records[point]
                if (record != null && record.phase != HookPhase.ARMED) return record.observation
                if (remaining <= 0L) throw DebugControlException(DebugControlErrorCode.TIMEOUT)
                remaining = changed.awaitNanos(remaining)
            }
        }
    }

    fun release(point: HookPoint): Long = lock.withLock {
        val record = records[point] ?: throw DebugControlException(DebugControlErrorCode.NOT_ARRIVED)
        if (record.phase == HookPhase.RELEASED) throw DebugControlException(DebugControlErrorCode.ALREADY_RELEASED)
        if (record.phase != HookPhase.ARRIVED || !record.waiting) throw DebugControlException(DebugControlErrorCode.NOT_ARRIVED)
        appendHookEvent(record, HookPhase.RELEASED, record.arrivalCommandRef)
        record.phase = HookPhase.RELEASED
        revisionClock.bump()
        changed.signalAll()
        record.actionId
    }

    override fun pauseIfArmed(point: HookPoint) {
        lock.withLock {
            val commandRef = if (point == HookPoint.AFTER_LOGOUT_RECEIPT) lastProcessed else activeCommandRef
            val record = records[point] ?: return
            if (record.phase != HookPhase.ARMED || point == HookPoint.BEFORE_DEFERRED_CONTROL_CLEAR ||
                commandRef == null || record.selectedCommandRef != commandRef
            ) {
                return
            }
            arriveAndWait(record, commandRef)
        }
    }

    override fun pauseDetachedEffect(effectId: String, originCommandId: Long): Long = lock.withLock {
        val record = records[HookPoint.BEFORE_DEFERRED_CONTROL_CLEAR]
        if (record == null || record.phase != HookPhase.ARMED || record.target != HookTarget.NEXT_COMMAND ||
            commandNames[originCommandId] != "Logout"
        ) {
            return@withLock 0L
        }
        arriveAndWait(record, CommandReference(process.processInstanceId, originCommandId))
        record.actionId
    }

    override fun commandEnqueued(reference: AppCommandReference, name: String) {
        lock.withLock {
            val controlReference = controlReference(reference)
            lastEnqueued = controlReference
            commandNames[reference.id] = name
            for (record in records.values) {
                if (record.phase == HookPhase.ARMED && record.point != HookPoint.BEFORE_DEFERRED_CONTROL_CLEAR &&
                    record.selectedCommandRef == null && targetMatches(record.target, name)
                ) {
                    record.selectedCommandRef = controlReference
                }
            }
            revisionClock.bump()
            changed.signalAll()
        }
    }

    override fun commandStarted(reference: AppCommandReference, name: String) {
        lock.withLock { activeCommandRef = controlReference(reference) }
    }

    override fun commandProcessed(reference: AppCommandReference) {
        lock.withLock {
            val controlReference = controlReference(reference)
            lastProcessed = controlReference
            if (activeCommandRef == controlReference) activeCommandRef = null
            revisionClock.bump()
            changed.signalAll()
        }
    }

    override fun storeIOChanged(active: Boolean) {
        lock.withLock {
            if (active) {
                while (probeActive) changed.await()
                storeIoActive = true
            } else {
                storeIoActive = false
                changed.signalAll()
            }
            revisionClock.bump()
        }
    }

    fun snapshot(): Snapshot = lock.withLock {
        Snapshot(
            hooks = records.values.map { it.observation }.sortedBy { it.armSequence },
            storeIoActive = storeIoActive,
            lastEnqueuedCommandRef = lastEnqueued,
            lastProcessedCommandRef = lastProcessed,
        )
    }

    fun beginProbe() {
        lock.withLock {
            if (storeIoActive || probeActive) throw DebugControlException(DebugControlErrorCode.PROBE_NOT_SAFE)
            probeActive = true
        }
    }

    fun endProbe() {
        lock.withLock {
            probeActive = false
            changed.signalAll()
        }
    }

    /** Called with [lock] held; returns after an independent release. */
    private fun arriveAndWait(record: HookRecord, commandRef: CommandReference) {
        appendHookEvent(record, HookPhase.ARRIVED, commandRef)
        record.phase = HookPhase.ARRIVED
        record.arrivalCommandRef = commandRef
        record.waiting = true
        revisionClock.bump()
        changed.signalAll()
        while (record.phase != HookPhase.RELEASED) changed.awaitUninterruptibly()
        record.waiting = false
    }

    private fun targetMatches(target: HookTarget, commandName: String): Boolean = when (target) {
        HookTarget.BOOTSTRAP -> commandName == "Bootstrap"
        HookTarget.NEXT_COMMAND -> true
        HookTarget.NEXT_DELIVERY -> commandName.startsWith("Deliver(")
    }

    private fun appendHookEvent(record: HookRecord, phase: HookPhase, commandRef: CommandReference?) {
        val fields = linkedMapOf<String, Any?>(
            "actionId" to record.actionId,
            "point" to record.point.wireValue,
            "phase" to phase.wireValue,
            "target" to record.target.wireValue,
        )
        commandRef?.let { fields["commandRef"] = mapOf("processInstanceId" to it.processInstanceId, "id" to it.id) }
        try {
            audit.append("hookEvent", fields)
            audit.synchronize()
        } catch (error: Exception) {
            if (phase == HookPhase.ARMED || phase == HookPhase.RELEASED) throw error
            FailStop.stop("hook arrival could not be synchronized")
        }
    }

    private fun controlReference(reference: AppCommandReference) = CommandReference(reference.processInstanceId, reference.id)
}
