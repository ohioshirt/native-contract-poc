package nativecontract.demo

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import nativecontract.demo.debug.DebugScenarioControlPanelId
import nativecontract.demo.debug.HookObservation
import nativecontract.demo.debug.HookPhase
import nativecontract.demo.debug.HookTarget
import nativecontract.demo.debug.ProcessEndAck
import nativecontract.demo.debug.ProcessEndEventReference
import nativecontract.demo.debug.StoreFaultKind
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.contract.StoreObservation

class ScenarioContractTest {
    @Test
    fun frozenHookAndFaultInventoriesMatchTheProtocol() {
        assertEquals(
            listOf(
                "beforeBootstrapClear", "afterManaged", "beforeStore", "beforePublish",
                "afterPublishAck", "afterLogoutReceipt", "ingressHeld", "beforeDeferredControlClear",
            ),
            HookPoint.entries.map(HookPoint::wireValue),
        )
        assertEquals(
            listOf("none", "replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"),
            StoreFaultKind.entries.map(StoreFaultKind::wireValue),
        )
    }

    @Test
    fun controlPanelIdentifiersMatchTheFrozenAccessibilityNames() {
        assertEquals("hook-target-bootstrap", DebugScenarioControlPanelId.target(HookTarget.BOOTSTRAP))
        assertEquals("hook-target-nextCommand", DebugScenarioControlPanelId.target(HookTarget.NEXT_COMMAND))
        assertEquals("hook-arm-beforeBootstrapClear", DebugScenarioControlPanelId.arm(HookPoint.BEFORE_BOOTSTRAP_CLEAR))
        assertEquals("hook-release-beforeBootstrapClear", DebugScenarioControlPanelId.release(HookPoint.BEFORE_BOOTSTRAP_CLEAR))
        assertEquals("fault-set-clearBefore", DebugScenarioControlPanelId.fault(StoreFaultKind.CLEAR_BEFORE))
        assertEquals("finish-process", DebugScenarioControlPanelId.FINISH_PROCESS)
        assertEquals("process-end-ack-json", DebugScenarioControlPanelId.PROCESS_END_ACK_JSON)
    }

    @Test
    fun processEndAckCarriesItsActualProcessScopedEventReference() {
        val processId = "attempt-01/APP-07/p1"
        val ack = ProcessEndAck(processId, ProcessEndEventReference(processId, 19L))

        assertEquals(processId, ack.processInstanceId)
        assertEquals(processId, ack.eventRef.processInstanceId)
        assertEquals(19L, ack.eventRef.localSequence)
    }

    @Test
    fun hookSnapshotsKeepReleasedRowsInArmSequenceOrder() {
        val processId = "attempt-01/APP-11/p1"
        val snapshot = nativecontract.demo.debug.ControlSnapshot(
            processInstanceId = processId,
            launchOrdinal = 1L,
            controlRevision = 2L,
            storeIoActive = false,
            hooks = listOf(
                HookObservation(11L, HookPoint.BEFORE_STORE, HookPhase.RELEASED, HookTarget.NEXT_DELIVERY),
                HookObservation(17L, HookPoint.BEFORE_PUBLISH, HookPhase.RELEASED, HookTarget.NEXT_DELIVERY),
            ),
        )

        assertEquals(listOf(11L, 17L), snapshot.hooks.map(HookObservation::armSequence))
        assertEquals(listOf(HookPhase.RELEASED, HookPhase.RELEASED), snapshot.hooks.map(HookObservation::phase))
    }

    @Test
    fun unknownStoreStateDoesNotContainCredentialFields() {
        val observation = StoreObservation.Unknown("readFailed")
        val wire = observation.toRedactedFields()
        assertEquals(mapOf("kind" to "Unknown", "errorCode" to "readFailed"), wire)
        assertFalse(wire.contains("accessToken"))
        assertFalse(wire.contains("refreshToken"))
    }
}
