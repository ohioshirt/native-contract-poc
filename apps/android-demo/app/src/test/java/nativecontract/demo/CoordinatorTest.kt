package nativecontract.demo

import java.io.File
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.CommandReceipt
import nativecontract.demo.coordinator.CommandStatus
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.coordinator.DemoViewState
import nativecontract.demo.coordinator.FailStop
import nativecontract.demo.coordinator.IngressClosedException
import nativecontract.demo.coordinator.Json
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.RefreshSlot
import nativecontract.demo.coordinator.ScenarioHooks
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.coordinator.SessionPhase
import nativecontract.demo.coordinator.TerminalAuditRecorder
import nativecontract.demo.coordinator.ViewPublisher
import nativecontract.demo.debug.ControlRevisionClock
import nativecontract.demo.debug.DebugControlErrorCode
import nativecontract.demo.debug.DebugControlException
import nativecontract.demo.debug.DebugScenarioHooks
import nativecontract.demo.debug.DefaultDebugScenarioControl
import nativecontract.demo.debug.DemoIngress
import nativecontract.demo.debug.HookPhase
import nativecontract.demo.debug.HookTarget
import nativecontract.demo.debug.JSONLAuditRecorder
import nativecontract.demo.debug.ProbeResult
import nativecontract.demo.debug.StoreFaultKind
import nativecontract.demo.storage.AuditedCredentialStore
import nativecontract.demo.storage.CredentialStore
import nativecontract.demo.storage.CredentialStoreErrorCode
import nativecontract.demo.storage.CredentialStoreException
import nativecontract.demo.storage.CredentialStoreFailure
import nativecontract.demo.storage.StoreFaultInjecting
import nativecontract.demo.storage.observation
import nativecontract.demo.transport.Completion
import nativecontract.demo.transport.FencedTransportHandle
import nativecontract.demo.transport.RefreshOutcome
import nativecontract.demo.transport.RefreshTransport
import nativecontract.demo.transport.TransportHandle

private const val WAIT_SECONDS = 10L

class CoordinatorTest {
    @BeforeTest
    fun failStopThrowsInsteadOfHaltingTheTestJvm() {
        FailStop.handler = { reason -> throw IllegalStateException("fail-stop: $reason") }
    }

    @Test
    fun lateSuccessAfterCompletedLogoutCannotWrite() {
        val harness = Harness("APP-02")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        val logout = harness.submit(AppCommand.Logout)
        assertEquals(CommandStatus.COMPLETED, logout.status)

        harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L)))
        val late = harness.audit.awaitReceipt(5L)

        assertEquals("IgnoredStale", late["status"])
        assertNull(harness.store.credential)
        assertEquals(listOf("clear", "replace:A:0", "clear"), harness.store.mutations)
        assertEquals(SessionPhase.SIGNED_OUT, harness.publisher.latest().phase)
    }

    @Test
    fun lateFailureAfterLoginBDoesNotClearB() {
        val harness = Harness("APP-05")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        assertEquals(CommandStatus.COMPLETED, harness.submit(AppCommand.Logout).status)
        assertEquals(CommandStatus.COMPLETED, harness.submit(AppCommand.Login(CredentialAccount.B)).status)

        harness.transport.deliver(pending, RefreshOutcome.Failure("rejected"))
        val late = harness.audit.awaitReceipt(6L)

        assertEquals("IgnoredStale", late["status"])
        assertEquals(Credential.demo(CredentialAccount.B, 0L), harness.store.credential)
        assertEquals(listOf("clear", "replace:A:0", "clear", "replace:B:0"), harness.store.mutations)
        val view = harness.publisher.latest()
        assertEquals(SessionPhase.SIGNED_IN, view.phase)
        assertEquals(CredentialAccount.B, view.account)
    }

    @Test
    fun duplicateCannotCommitTwice() {
        val harness = Harness("APP-06")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        val payload = RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L))

        harness.transport.deliver(pending, payload)
        assertEquals("Completed", harness.audit.awaitReceipt(4L)["status"])
        harness.transport.deliver(pending, payload)
        assertEquals("IgnoredStale", harness.audit.awaitReceipt(5L)["status"])

        assertEquals(listOf("clear", "replace:A:0", "replace:A:1"), harness.store.mutations)
        assertEquals(1, harness.audit.rows("storeMutation").count { it["cause"] == "RefreshSuccess" })
    }

    @Test
    fun mismatchedRefreshPayloadCannotReplaceIssuedAccountsCredential() {
        val harness = Harness("APP-01")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()

        harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.B, 1L)))
        val receipt = harness.audit.awaitReceipt(4L)

        assertEquals("FaultLocked", receipt["status"])
        assertEquals(Credential.demo(CredentialAccount.A, 0L), harness.store.credential)
        assertEquals(SessionPhase.FAULT_LOCKED, harness.publisher.latest().phase)
    }

    @Test
    fun nextCommandWaitsForMainPublicationAck() {
        val publisher = GatedPublisher()
        val harness = Harness("APP-11", publisher = publisher)
        publisher.open()
        harness.bootstrapAndLogin(CredentialAccount.A)
        publisher.close()

        val logout = harness.coordinator.submit(AppCommand.Logout)
        val login = harness.coordinator.submit(AppCommand.Login(CredentialAccount.B))
        publisher.awaitBlockedPublication()
        val blockedRevision = publisher.latest().revision
        // Deterministic: the coordinator worker itself must be parked on the
        // publication acknowledgement, not merely slower than this assertion.
        awaitThreadBlockedIn("SessionCoordinator.publish", "CompletableFuture")

        assertTrue(harness.audit.rows("uiPublishAck").none { it["revision"] == blockedRevision })
        assertFalse(logout.isDone)
        assertFalse(login.isDone)
        assertTrue(harness.audit.rows("commandStarted").none { commandId(it) == 4L })
        publisher.open()
        assertEquals(CommandStatus.COMPLETED, logout.get(WAIT_SECONDS, TimeUnit.SECONDS).status)
        assertEquals(CommandStatus.COMPLETED, login.get(WAIT_SECONDS, TimeUnit.SECONDS).status)
        val started = harness.audit.rows("commandStarted").map(::commandId)
        val receipts = harness.audit.rows("commandReceipt").map(::commandId)
        assertEquals(listOf(1L, 2L, 3L, 4L), started)
        assertEquals(listOf(1L, 2L, 3L, 4L), receipts)
    }

    @Test
    fun cancelledFutureStillCompletesAcceptedLogout() {
        val publisher = GatedPublisher()
        val harness = Harness("APP-03", publisher = publisher)
        publisher.open()
        harness.bootstrapAndLogin(CredentialAccount.A)
        publisher.close()

        val logout = harness.coordinator.submit(AppCommand.Logout)
        publisher.awaitBlockedPublication()
        logout.cancel(true)
        publisher.open()

        val receipt = harness.audit.awaitReceipt(3L)
        assertEquals("Completed", receipt["status"])
        assertNull(harness.store.credential)
    }

    @Test
    fun failedClearIsNotCompleted() {
        val harness = Harness("APP-10")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.store.failNextClear()

        val receipt = harness.submit(AppCommand.Logout)

        assertEquals(CommandStatus.FAULT_LOCKED, receipt.status)
        assertEquals(SessionPhase.FAULT_LOCKED, harness.publisher.latest().phase)
        assertEquals(Credential.demo(CredentialAccount.A, 0L), harness.store.credential)
    }

    @Test
    fun writeThenReadbackFailureLocksUI() {
        val harness = Harness("APP-09")
        harness.submit(AppCommand.Bootstrap)
        harness.store.failNextReplacementAfterWrite()

        val receipt = harness.submit(AppCommand.Login(CredentialAccount.A))

        assertEquals(CommandStatus.FAULT_LOCKED, receipt.status)
        assertTrue(harness.publisher.published.none { it.phase == SessionPhase.SIGNED_IN || it.phase == SessionPhase.REFRESHING })
        assertEquals(SessionPhase.FAULT_LOCKED, harness.publisher.latest().phase)
    }

    @Test
    fun ignoredStaleUpdatesReceiptMetadataOnly() {
        val harness = Harness("APP-04")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        harness.submit(AppCommand.Logout)
        val before = harness.publisher.latest()

        harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L)))
        harness.audit.awaitReceipt(5L)
        val after = harness.publisher.latest()

        assertEquals(before.phase, after.phase)
        assertEquals(before.account, after.account)
        assertEquals(before.credentialVersion, after.credentialVersion)
        assertEquals(before.pendingRequestId, after.pendingRequestId)
        assertTrue(after.revision > before.revision)
        assertEquals(5L, after.lastCompletedCommandId)
        assertEquals(CommandStatus.IGNORED_STALE, after.lastCommandStatus)
    }

    @Test
    fun cancelRefreshInFaultLockedIsRejectedLikeLogoutUntilRetryCleanup() {
        val harness = Harness("APP-10")
        harness.bootstrapAndLogin(CredentialAccount.A)
        harness.store.failNextRead()
        assertEquals(CommandStatus.FAULT_LOCKED, harness.submit(AppCommand.Expire).status)
        val mutationsBefore = harness.store.mutations

        val cancel = harness.submit(AppCommand.CancelRefresh)

        assertEquals(CommandStatus.FAULT_LOCKED, cancel.status)
        assertTrue(harness.audit.rows("managedReduced").none { commandId(it) == cancel.commandId })
        assertEquals(mutationsBefore, harness.store.mutations)
        assertEquals(SessionPhase.FAULT_LOCKED, harness.publisher.latest().phase)
        assertEquals(CommandStatus.REJECTED_BUSY, harness.submit(AppCommand.Login(CredentialAccount.A)).status)
        assertEquals(CommandStatus.COMPLETED, harness.submit(AppCommand.RetryCleanup).status)
        assertEquals(CommandStatus.COMPLETED, harness.submit(AppCommand.Login(CredentialAccount.B)).status)
        assertEquals(Credential.demo(CredentialAccount.B, 0L), harness.store.credential)
    }

    /** Expected rows follow integration/tests/_history_fixtures.py replace-fault inventory rows. */
    @Test
    fun refreshReplaceFaultRunsVerifiedFaultCleanupBeforeFaultLockedReceipt() {
        val cases = listOf(
            "replaceBefore" to listOf(
                "storeFault" to mapOf("operation" to "replace", "fault" to "replaceBefore", "mutationApplied" to false, "observation" to present("A", 0)),
                "storeMutation" to mapOf("operation" to "clear", "cause" to "FaultCleanup", "before" to present("A", 0), "after" to absent()),
                "storeReadback" to mapOf("operation" to "clear", "observation" to absent()),
            ),
            "replaceAfterBeforeVerify" to listOf(
                "storeMutation" to mapOf("operation" to "replace", "cause" to "RefreshSuccess", "before" to present("A", 0), "after" to present("A", 1)),
                "storeFault" to mapOf("operation" to "replace", "fault" to "replaceAfterBeforeVerify", "mutationApplied" to true, "observation" to unknown("readFailed")),
                "storeMutation" to mapOf("operation" to "clear", "cause" to "FaultCleanup", "before" to unknown("readFailed"), "after" to absent()),
                "storeReadback" to mapOf("operation" to "clear", "observation" to absent()),
            ),
        )
        for ((fault, expectedRows) in cases) {
            val store = FaultStore()
            val harness = Harness("APP-09", base = store)
            harness.bootstrapAndLogin(CredentialAccount.A)
            harness.submit(AppCommand.Expire)
            val pending = harness.transport.awaitPending()
            store.setStoreFault(fault)

            harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L)))
            val receipt = harness.audit.awaitReceipt(4L)

            assertEquals("FaultLocked", receipt["status"], fault)
            assertEquals(absent(), (receipt["observation"] as Map<*, *>)["store"], fault)
            val storeRows = harness.audit.rowsFor(4L).filter { it["kind"] in setOf("storeMutation", "storeReadback", "storeFault") }
            assertEquals(expectedRows.map { it.first }, storeRows.map { it["kind"] }, fault)
            storeRows.zip(expectedRows).forEach { (row, expected) ->
                expected.second.forEach { (key, value) -> assertEquals(value, row[key], "$fault ${expected.first}.$key") }
            }
            assertNull(store.physical, fault)
            assertTrue(harness.publisher.published.none { it.lastCompletedCommandId == 4L && it.phase == SessionPhase.SIGNED_IN }, fault)
        }
    }

    @Test
    fun loginReplaceFaultRunsVerifiedFaultCleanupAndStaysFaultLocked() {
        val store = FaultStore()
        val harness = Harness("APP-09", base = store)
        harness.submit(AppCommand.Bootstrap)
        store.setStoreFault("replaceAfterBeforeVerify")

        val login = harness.submit(AppCommand.Login(CredentialAccount.A))

        assertEquals(CommandStatus.FAULT_LOCKED, login.status)
        assertEquals(StoreObservation.Absent, login.observation.store)
        val cleanup = harness.audit.rowsFor(login.commandId).last { it["kind"] == "storeMutation" }
        assertEquals("FaultCleanup", cleanup["cause"])
        assertEquals(unknown("readFailed"), cleanup["before"])
        assertNull(store.physical)
        assertEquals(CommandStatus.REJECTED_BUSY, harness.submit(AppCommand.Login(CredentialAccount.A)).status)
    }

    /** APP-10 clear-after-before-verify reference history: RetryCleanup chains from the receipt observation. */
    @Test
    fun retryCleanupAfterUnverifiedClearRecordsChainedUnknownBefore() {
        val store = FaultStore()
        val harness = Harness("APP-10", base = store)
        harness.bootstrapAndLogin(CredentialAccount.A)
        store.setStoreFault("clearAfterBeforeVerify")
        val logout = harness.submit(AppCommand.Logout)
        assertEquals(CommandStatus.FAULT_LOCKED, logout.status)
        assertEquals(StoreObservation.Unknown("readFailed"), logout.observation.store)
        store.setStoreFault(null)

        val cleanup = harness.submit(AppCommand.RetryCleanup)

        assertEquals(CommandStatus.COMPLETED, cleanup.status)
        val mutation = harness.audit.rowsFor(cleanup.commandId).first { it["kind"] == "storeMutation" }
        assertEquals("RetryCleanup", mutation["cause"])
        assertEquals(unknown("readFailed"), mutation["before"])
        assertEquals(absent(), mutation["after"])
        val reset = harness.audit.rows("managedInstanceReset").single()
        assertEquals("Unauthenticated", (reset["before"] as Map<*, *>)["state"])
        assertEquals(1L, (reset["after"] as Map<*, *>)["nextRequestId"])
        assertTrue((reset["before"] as Map<*, *>)["ownerId"] != (reset["after"] as Map<*, *>)["ownerId"])
    }

    @Test
    fun releaseBypassesPausedCoordinatorAndQueuedCommandsKeepFifo() {
        val harness = DebugHarness("APP-11")
        harness.control.arm(HookPoint.BEFORE_STORE, HookTarget.NEXT_COMMAND)
        val bootstrap = harness.coordinator.submit(AppCommand.Bootstrap)
        harness.control.awaitArrival(HookPoint.BEFORE_STORE, 5_000)
        val login = harness.coordinator.submit(AppCommand.Login(CredentialAccount.A))
        harness.awaitEnqueued(2L)
        assertNull(harness.control.snapshot().lastProcessedCommandRef)
        assertFalse(login.isDone)

        val ack = harness.control.release(HookPoint.BEFORE_STORE)

        assertTrue(ack.actionId > 0L && ack.controlRevision > 0L)
        assertEquals(CommandStatus.COMPLETED, bootstrap.get(WAIT_SECONDS, TimeUnit.SECONDS).status)
        assertEquals(CommandStatus.COMPLETED, login.get(WAIT_SECONDS, TimeUnit.SECONDS).status)
        assertEquals(listOf(1L, 2L), harness.audit.rows("commandReceipt").map(::commandId))
        val hook = harness.control.snapshot().hooks.single()
        assertEquals(HookPhase.RELEASED, hook.phase)
        assertEquals(ack.actionId, hook.armSequence)
        val bootstrapClear = harness.audit.rowsFor(1L).first { it["kind"] == "storeMutation" }
        assertEquals("Bootstrap", bootstrapClear["cause"])
    }

    @Test
    fun bootstrapProbeBeforeClearCarriesReleasedActionId() {
        val harness = DebugHarness("APP-12-SAVED", ordinal = 2L)
        harness.control.arm(HookPoint.BEFORE_BOOTSTRAP_CLEAR, HookTarget.BOOTSTRAP)
        val bootstrap = harness.coordinator.submit(AppCommand.Bootstrap)
        val arrival = harness.control.awaitArrival(HookPoint.BEFORE_BOOTSTRAP_CLEAR, 5_000)
        assertEquals(1L, arrival.arrivalCommandRef?.id)

        val probe = harness.control.probeStore().get(WAIT_SECONDS, TimeUnit.SECONDS)
        assertEquals(harness.process.processInstanceId, probe.processInstanceId)
        assertTrue(harness.audit.rows("storeMutation").isEmpty())
        val release = harness.control.release(HookPoint.BEFORE_BOOTSTRAP_CLEAR)

        assertEquals(CommandStatus.COMPLETED, bootstrap.get(WAIT_SECONDS, TimeUnit.SECONDS).status)
        assertEquals(release.actionId, harness.audit.rows("storeMutation").single()["releaseActionId"])
    }

    @Test
    fun replayUsesNormalDeliverWithTheCapturedSlot() {
        val harness = DebugHarness("APP-06")
        harness.submit(AppCommand.Bootstrap)
        harness.submit(AppCommand.Login(CredentialAccount.A))
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L)))
        harness.audit.awaitReceipt(4L)

        val ack = harness.control.replayLastCompletion()
        val replay = harness.audit.awaitReceipt(5L)

        assertEquals("scheduled", ack.status.wireValue)
        assertEquals("IgnoredStale", replay["status"])
        val enqueued = harness.audit.rows("commandEnqueued").map { it["name"] }
        assertEquals("Deliver(slot-A1,success)", enqueued[3])
        assertEquals("Deliver(slot-A1,success)", enqueued[4])
    }

    @Test
    fun replayWithoutCapturedCompletionIsRejected() {
        val harness = DebugHarness("APP-06")
        val error = assertFailsWith<DebugControlException> { harness.control.replayLastCompletion() }
        assertEquals(DebugControlErrorCode.NO_CAPTURED_COMPLETION, error.code)
    }

    @Test
    fun finishRejectsPausedHookWithoutTerminalRowThenSucceedsAfterRelease() {
        val harness = DebugHarness("APP-11")
        harness.control.arm(HookPoint.BEFORE_STORE, HookTarget.NEXT_COMMAND)
        harness.coordinator.submit(AppCommand.Bootstrap)
        harness.control.awaitArrival(HookPoint.BEFORE_STORE, 5_000)

        val busy = assertFailsWith<DebugControlException> { harness.control.finishProcess(2_000) }

        assertEquals(DebugControlErrorCode.PROCESS_BUSY, busy.code)
        assertTrue(harness.audit.rows("processEnd").isEmpty())
        harness.control.release(HookPoint.BEFORE_STORE)
        harness.audit.awaitReceipt(1L)
        val ack = harness.control.finishProcess(5_000)
        assertEquals(ack, harness.control.finishProcess(5_000))
        assertEquals(1, harness.audit.rows("processEnd").size)
        assertEquals(ack.eventRef.localSequence, harness.audit.rows().last()["localSequence"])
    }

    @Test
    fun finishFencesHeldTransportAndDropsItsLateCompletion() {
        val harness = DebugHarness("APP-07")
        harness.submit(AppCommand.Bootstrap)
        harness.submit(AppCommand.Login(CredentialAccount.A))
        harness.submit(AppCommand.Expire)
        harness.transport.awaitPending()
        val rowsBefore = harness.audit.rows().size

        val ack = harness.control.finishProcess(5_000)

        assertEquals(1, harness.transport.fencedCancels)
        val rows = harness.audit.rows()
        assertEquals(rowsBefore + 1, rows.size)
        assertEquals("processEnd", rows.last()["kind"])
        assertEquals(ack.eventRef.localSequence, rows.last()["localSequence"])
        assertFailsWith<java.util.concurrent.ExecutionException> {
            harness.coordinator.submit(AppCommand.Observe).get(WAIT_SECONDS, TimeUnit.SECONDS)
        }.also { assertTrue(it.cause is IngressClosedException) }
        assertEquals(Credential.demo(CredentialAccount.A, 0L), harness.store.value)
    }

    /**
     * Writes real JSONL through the Debug recorder for host validation against the
     * frozen integration/check.py EVENT_FIELDS (file under build/schema-smoke).
     */
    @Test
    fun jsonlRowsCarryTheFrozenEventBaseAcrossAuthHookFaultAndResetKinds() {
        val directory = File("build/schema-smoke").apply { mkdirs() }
        val file = File(directory, "kotlin-flows.jsonl").apply { delete() }
        val harness = DebugHarness("APP-10", auditFile = file, base = FaultStore())
        harness.control.arm(HookPoint.AFTER_MANAGED, HookTarget.NEXT_DELIVERY)
        harness.submit(AppCommand.Bootstrap)
        harness.submit(AppCommand.Login(CredentialAccount.A))
        harness.submit(AppCommand.Expire)
        val pending = harness.transport.awaitPending()
        harness.transport.deliver(pending, RefreshOutcome.Success(Credential.demo(CredentialAccount.A, 1L)))
        harness.control.awaitArrival(HookPoint.AFTER_MANAGED, 5_000)
        harness.control.release(HookPoint.AFTER_MANAGED)
        harness.audit.awaitReceipt(4L)
        harness.control.injectStoreFault(StoreFaultKind.CLEAR_AFTER_BEFORE_VERIFY)
        assertEquals(CommandStatus.FAULT_LOCKED, harness.submit(AppCommand.Logout).status)
        harness.control.injectStoreFault(StoreFaultKind.NONE)
        assertEquals(CommandStatus.COMPLETED, harness.submit(AppCommand.RetryCleanup).status)
        harness.control.finishProcess(5_000)

        val rows = file.readLines().map { Json.parse(it) as Map<*, *> }
        assertTrue(rows.size > 20)
        rows.forEachIndexed { index, row ->
            assertEquals(harness.process.processInstanceId, row["processInstanceId"])
            assertEquals(1L, row["launchOrdinal"])
            assertEquals(index + 1L, row["localSequence"])
        }
        val kinds = rows.map { it["kind"] }.toSet()
        assertTrue(kinds.containsAll(setOf("hookEvent", "storeFault", "managedInstanceReset", "transportReceived", "completionProcessed", "processEnd")))
        println("schema-smoke-jsonl=${file.absolutePath}")
    }

    // ---- helpers -------------------------------------------------------------------------

    private class Harness(
        scenario: String,
        val publisher: RecordingPublisher = RecordingPublisher(),
        base: CredentialStore? = null,
    ) {
        val process = ProcessContext("t5-${System.nanoTime()}/$scenario/p1", 1L, "t5", scenario)
        val store = TestCredentialStore()
        val transport = TestTransport()
        val audit = MemoryAuditRecorder()
        val coordinator = SessionCoordinator(process, base ?: store, transport, publisher, NoopHooks, audit, false)

        init {
            coordinator.start()
        }

        fun submit(command: AppCommand): CommandReceipt = coordinator.submit(command).get(WAIT_SECONDS, TimeUnit.SECONDS)

        fun bootstrapAndLogin(account: CredentialAccount) {
            assertEquals(CommandStatus.COMPLETED, submit(AppCommand.Bootstrap).status)
            assertEquals(CommandStatus.COMPLETED, submit(AppCommand.Login(account)).status)
        }
    }

    private class DebugHarness(
        scenario: String,
        ordinal: Long = 1L,
        auditFile: File? = null,
        base: CredentialStore? = null,
    ) {
        val process = ProcessContext("t5-${System.nanoTime()}/$scenario/p$ordinal", ordinal, "t5", scenario)
        private val jsonl = auditFile?.let { JSONLAuditRecorder(it, process.processInstanceId, ordinal) }
        val audit = MemoryAuditRecorder(jsonl)
        val clock = ControlRevisionClock()
        val hooks = DebugScenarioHooks(process, audit, clock)
        val store = (base as? FaultStore) ?: FaultStore()
        val audited = AuditedCredentialStore(store, audit, hooks::storeIOChanged)
        val transport = TestTransport()
        val publisher = RecordingPublisher()
        val ingress = DemoIngress()
        val coordinator = SessionCoordinator(process, audited, transport.capturing(ingress), publisher, hooks, audit, false)
        val control = DefaultDebugScenarioControl(
            process, coordinator, audited, hooks, ingress,
            probe = { id -> ProbeResult(id, process.processInstanceId, store.physical?.observation() ?: StoreObservation.Absent) },
            revisionClock = clock,
        )

        init {
            ingress.attach(coordinator)
            coordinator.start()
        }

        fun submit(command: AppCommand): CommandReceipt = coordinator.submit(command).get(WAIT_SECONDS, TimeUnit.SECONDS)

        fun awaitEnqueued(id: Long) {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(WAIT_SECONDS)
            while (control.snapshot().lastEnqueuedCommandRef?.id != id) {
                check(System.nanoTime() < deadline) { "command $id was not enqueued" }
                Thread.sleep(5)
            }
        }
    }
}

/** Waits until some live thread's stack contains both frames (in either order). */
private fun awaitThreadBlockedIn(callerFrame: String, waitFrame: String) {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(WAIT_SECONDS)
    while (System.nanoTime() < deadline) {
        val found = Thread.getAllStackTraces().values.any { stack ->
            val frames = stack.map { "${it.className.substringAfterLast('.')}.${it.methodName}" }
            frames.any { it.contains(callerFrame) } && frames.any { it.contains(waitFrame) }
        }
        if (found) return
        Thread.sleep(5)
    }
    error("no thread was blocked in $callerFrame waiting on $waitFrame")
}

private fun commandId(row: Map<String, Any?>): Long? = ((row["commandRef"] as? Map<*, *>)?.get("id") as? Long)

private fun present(account: String, version: Long): Map<String, Any?> = mapOf("kind" to "Present", "account" to account, "version" to version)

private fun absent(): Map<String, Any?> = mapOf("kind" to "Absent")

private fun unknown(code: String): Map<String, Any?> = mapOf("kind" to "Unknown", "errorCode" to code)

private object NoopHooks : ScenarioHooks {
    override fun pauseIfArmed(point: HookPoint) = Unit
}

/** Stores rows as decoded JSON (via the production encoder) and optionally tees to a real JSONL file. */
private class MemoryAuditRecorder(private val tee: TerminalAuditRecorder? = null) : TerminalAuditRecorder {
    private val lock = Object()
    private val records = ArrayList<Map<String, Any?>>()

    override fun append(kind: String, fields: Map<String, Any?>): Long = add(kind, fields) { tee?.append(kind, fields) }

    override fun appendProcessEndAndSeal(fields: Map<String, Any?>): Long =
        add("processEnd", fields) { tee?.appendProcessEndAndSeal(fields) }

    override fun synchronize() {
        tee?.synchronize()
    }

    private fun add(kind: String, fields: Map<String, Any?>, forward: () -> Long?): Long = synchronized(lock) {
        forward()
        @Suppress("UNCHECKED_CAST")
        val decoded = Json.parse(Json.encode(fields)) as Map<String, Any?>
        records += decoded + mapOf("kind" to kind, "localSequence" to records.size + 1L)
        lock.notifyAll()
        records.size.toLong()
    }

    fun rows(kind: String? = null): List<Map<String, Any?>> = synchronized(lock) {
        records.filter { kind == null || it["kind"] == kind }
    }

    fun rowsFor(id: Long): List<Map<String, Any?>> = rows().filter { commandId(it) == id }

    fun awaitReceipt(id: Long): Map<String, Any?> = synchronized(lock) {
        val deadline = System.currentTimeMillis() + TimeUnit.SECONDS.toMillis(WAIT_SECONDS)
        var receipt = records.firstOrNull { it["kind"] == "commandReceipt" && commandId(it) == id }
        while (receipt == null) {
            val remaining = deadline - System.currentTimeMillis()
            check(remaining > 0) { "receipt for command $id was not recorded" }
            lock.wait(remaining)
            receipt = records.firstOrNull { it["kind"] == "commandReceipt" && commandId(it) == id }
        }
        receipt
    }
}

private open class RecordingPublisher : ViewPublisher {
    private val lock = Object()
    private val items = ArrayList<DemoViewState>()
    val published: List<DemoViewState> get() = synchronized(lock) { ArrayList(items) }

    override fun publish(view: DemoViewState): CompletableFuture<Unit> {
        synchronized(lock) { items.add(view) }
        return CompletableFuture.completedFuture(Unit)
    }

    fun latest(): DemoViewState = published.last()
}

/** Completes publication acknowledgements only while open, on a separate thread. */
private class GatedPublisher : RecordingPublisher() {
    private val waiting = LinkedBlockingQueue<CompletableFuture<Unit>>()
    @Volatile private var openGate = false
    private val blocked = CountDownLatch(1)

    fun open() {
        openGate = true
        while (true) waiting.poll()?.complete(Unit) ?: break
    }

    fun close() {
        openGate = false
    }

    fun awaitBlockedPublication() {
        check(blocked.await(WAIT_SECONDS, TimeUnit.SECONDS)) { "no publication reached the closed gate" }
    }

    override fun publish(view: DemoViewState): CompletableFuture<Unit> {
        super.publish(view)
        if (openGate) return CompletableFuture.completedFuture(Unit)
        val future = CompletableFuture<Unit>()
        waiting.add(future)
        blocked.countDown()
        if (openGate) future.complete(Unit)
        return future
    }
}

private class TestCredentialStore : CredentialStore {
    private var value: Credential? = null
    private val recorded = ArrayList<String>()
    private var failClear = false
    private var failRead = false
    private var failReplacementReadback = false

    val credential: Credential? @Synchronized get() = value
    val mutations: List<String> @Synchronized get() = ArrayList(recorded)

    @Synchronized fun failNextClear() { failClear = true }
    @Synchronized fun failNextRead() { failRead = true }
    @Synchronized fun failNextReplacementAfterWrite() { failReplacementReadback = true }

    @Synchronized
    override fun readVerified(): Credential? {
        if (failRead) {
            failRead = false
            throw CredentialStoreException(CredentialStoreErrorCode.READ_FAILED)
        }
        return value
    }

    @Synchronized
    override fun replaceVerified(credential: Credential) {
        value = credential
        recorded += "replace:${credential.account.raw}:${credential.version}"
        if (failReplacementReadback) {
            failReplacementReadback = false
            throw CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
        }
    }

    @Synchronized
    override fun clearVerified() {
        if (failClear) {
            failClear = false
            throw CredentialStoreException(CredentialStoreErrorCode.CLEAR_FAILED)
        }
        value = null
        recorded += "clear"
    }
}

/**
 * In-memory store with the same injected-fault semantics as the app's
 * AtomicFileCredentialStore (faults persist until cleared; reads are not faulted).
 */
private class FaultStore : CredentialStore, StoreFaultInjecting {
    @Volatile var physical: Credential? = null
    val value: Credential? get() = physical
    @Volatile private var fault: String? = null

    override fun setStoreFault(kind: String?) {
        fault = kind
    }

    @Synchronized
    override fun readVerified(): Credential? = physical

    @Synchronized
    override fun replaceVerified(credential: Credential) {
        val before = physical?.observation() ?: StoreObservation.Absent
        if (fault == "replaceBefore") throw CredentialStoreFailure("replace", "replaceBefore", false, "notAttempted", before, before, before)
        physical = credential
        if (fault == "replaceAfterBeforeVerify") {
            throw CredentialStoreFailure("replace", "replaceAfterBeforeVerify", true, "failed", before, StoreObservation.Unknown("readFailed"), credential.observation())
        }
    }

    @Synchronized
    override fun clearVerified() {
        val before = physical?.observation() ?: StoreObservation.Absent
        if (fault == "clearBefore") throw CredentialStoreFailure("clear", "clearBefore", false, "notAttempted", before, before, before)
        physical = null
        if (fault == "clearAfterBeforeVerify") {
            throw CredentialStoreFailure("clear", "clearAfterBeforeVerify", true, "failed", before, StoreObservation.Unknown("readFailed"), StoreObservation.Absent)
        }
    }
}

private class TestTransport : RefreshTransport {
    class Pending(val slot: RefreshSlot, val callback: (Completion) -> Unit)

    private val pending = LinkedBlockingQueue<Pending>()
    private var capture: DemoIngress? = null
    @Volatile var fencedCancels = 0

    fun capturing(ingress: DemoIngress): TestTransport = apply { capture = ingress }

    override fun start(slot: RefreshSlot, credential: Credential, completion: (Completion) -> Unit): TransportHandle {
        pending.add(Pending(slot, completion))
        return object : FencedTransportHandle {
            override fun cancel() = Unit
            override fun cancelAndWait(timeoutMillis: Long) {
                fencedCancels += 1
            }
        }
    }

    fun awaitPending(): Pending = pending.poll(WAIT_SECONDS, TimeUnit.SECONDS) ?: error("no refresh request was started")

    fun deliver(request: Pending, outcome: RefreshOutcome) {
        val completion = Completion(request.slot, outcome)
        thread {
            capture?.capture(completion)
            request.callback(completion)
        }.join()
    }
}
