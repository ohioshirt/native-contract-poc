package nativecontract.demo.debug

import java.util.concurrent.CompletableFuture
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.contract.StoreObservation

enum class HookTarget(val wireValue: String) {
    BOOTSTRAP("bootstrap"),
    NEXT_COMMAND("nextCommand"),
    NEXT_DELIVERY("nextDelivery"),
}

enum class StoreFaultKind(val wireValue: String) {
    NONE("none"),
    REPLACE_BEFORE("replaceBefore"),
    REPLACE_AFTER_BEFORE_VERIFY("replaceAfterBeforeVerify"),
    CLEAR_BEFORE("clearBefore"),
    CLEAR_AFTER_BEFORE_VERIFY("clearAfterBeforeVerify"),
}

enum class ControlAckStatus(val wireValue: String) {
    APPLIED("applied"),
    SCHEDULED("scheduled"),
}

enum class HookPhase(val wireValue: String) {
    ARMED("armed"),
    ARRIVED("arrived"),
    RELEASED("released"),
}

enum class DebugControlErrorCode(val wireValue: String) {
    ALREADY_ARMED("alreadyArmed"),
    NOT_ARRIVED("notArrived"),
    ALREADY_RELEASED("alreadyReleased"),
    NO_CAPTURED_COMPLETION("noCapturedCompletion"),
    PROBE_NOT_SAFE("probeNotSafe"),
    TIMEOUT("timeout"),
    PROCESS_BUSY("processBusy"),
    INVALID_ARGUMENT("invalidArgument"),
}

class DebugControlException(
    val code: DebugControlErrorCode,
) : IllegalStateException(code.wireValue)

data class CommandReference(
    val processInstanceId: String,
    val id: Long,
)

data class ControlAck(
    val actionId: Long,
    val controlRevision: Long,
    val status: ControlAckStatus,
)

data class ProcessEndEventReference(
    val processInstanceId: String,
    val localSequence: Long,
) {
    init {
        require(processInstanceId.isNotBlank())
        require(localSequence in 1..Long.MAX_VALUE)
    }
}

/** Cached acknowledgement for the one synchronized terminal native processEnd row. */
data class ProcessEndAck(
    val processInstanceId: String,
    val eventRef: ProcessEndEventReference,
) {
    init {
        require(processInstanceId.isNotBlank())
        require(eventRef.processInstanceId == processInstanceId)
    }
}

data class HookObservation(
    /** The checked ControlAck.actionId assigned when this hook was armed. */
    val armSequence: Long,
    val point: HookPoint,
    val phase: HookPhase,
    val target: HookTarget,
    val arrivalCommandRef: CommandReference? = null,
)

data class ProbeResult(
    val probeId: String,
    val processInstanceId: String,
    val observation: StoreObservation,
)

data class ControlSnapshot(
    val processInstanceId: String,
    val launchOrdinal: Long,
    val controlRevision: Long,
    val lastActionId: Long? = null,
    val lastActionStatus: ControlAckStatus? = null,
    val lastEnqueuedCommandRef: CommandReference? = null,
    val lastProcessedCommandRef: CommandReference? = null,
    val storeIoActive: Boolean,
    val hooks: List<HookObservation>,
    val lastProbe: ProbeResult? = null,
    val version: Int = 1,
)

/** Control work uses its own synchronization boundary, never the auth mailbox. */
interface DebugScenarioControl {
    fun arm(point: HookPoint, target: HookTarget): ControlAck
    fun awaitArrival(point: HookPoint, timeoutMillis: Long): HookObservation
    fun release(point: HookPoint): ControlAck
    fun replayLastCompletion(): ControlAck
    fun injectStoreFault(kind: StoreFaultKind): ControlAck
    fun probeStore(): CompletableFuture<ProbeResult>
    fun snapshot(): ControlSnapshot
    fun finishProcess(timeoutMillis: Long): ProcessEndAck
}

/** Implemented by the Debug Application; Release composition has no such reference. */
interface DebugScenarioControlProvider {
    val debugScenarioControl: DebugScenarioControl
}

object DebugScenarioControlPanelId {
    fun target(target: HookTarget): String = "hook-target-${target.wireValue}"
    fun arm(point: HookPoint): String = "hook-arm-${point.wireValue}"
    fun release(point: HookPoint): String = "hook-release-${point.wireValue}"
    fun state(point: HookPoint): String = "hook-state-${point.wireValue}"
    fun fault(kind: StoreFaultKind): String = "fault-set-${kind.wireValue}"

    const val REPLAY_LAST = "replay-last"
    const val PROBE_STORE = "probe-store"
    const val STORE_PROBE_RESULT = "store-probe-result"
    const val CONTROL_STATUS_JSON = "control-status-json"
    const val LAST_ENQUEUED_COMMAND_ID = "last-enqueued-command-id"
    const val FINISH_PROCESS = "finish-process"
    const val PROCESS_END_ACK_JSON = "process-end-ack-json"
}
