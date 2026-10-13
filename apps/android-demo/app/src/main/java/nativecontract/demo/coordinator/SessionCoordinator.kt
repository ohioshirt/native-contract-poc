package nativecontract.demo.coordinator

import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutionException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.thread
import kotlin.concurrent.withLock
import nativecontract.async.AsyncState
import nativecontract.async.ManagedAsyncSession
import nativecontract.async.ManagedEffect
import nativecontract.async.ManagedEvent
import nativecontract.async.ManagedRejection
import nativecontract.async.ManagedResult
import nativecontract.async.ManagedSnapshot
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.storage.AuditedCredentialStore
import nativecontract.demo.storage.CredentialStore
import nativecontract.demo.storage.CredentialStoreErrorCode
import nativecontract.demo.storage.CredentialStoreException
import nativecontract.demo.storage.CredentialStoreFailure
import nativecontract.demo.storage.StoreAuditContext
import nativecontract.demo.storage.observation
import nativecontract.demo.transport.Completion
import nativecontract.demo.transport.FencedTransportHandle
import nativecontract.demo.transport.RefreshOutcome
import nativecontract.demo.transport.RefreshTransport
import nativecontract.demo.transport.TransportHandle

enum class CoordinatorFailureCode { PROCESS_BUSY, TIMEOUT, ENDED, TERMINAL_JOURNAL, JOURNAL_SEQUENCE }

class CoordinatorFailure(val code: CoordinatorFailureCode, message: String = code.name) : Exception(message)

private enum class CoordinatorHealth { BOOTING, READY, FAULT_LOCKED }

private class ManagedResetPlan(
    val before: ManagedViewSnapshot,
    val after: ManagedViewSnapshot,
    val session: ManagedAsyncSession,
    val ownerId: String,
    val epoch: SessionEpoch,
)

private class CommandExecution(
    val receipt: CommandReceipt,
    val completion: Completion?,
    val resetAfterReceipt: ManagedResetPlan? = null,
)

/**
 * One single-thread transaction drain. Every accepted command holds the worker
 * through managed reduction, verified storage, main-thread publication and its
 * synchronized receipt before the next command starts. Command IDs, the
 * `commandEnqueued` row and executor submission happen under one enqueue lock,
 * so FIFO is the actual enqueue order. Future cancellation by a caller never
 * interrupts submitted work.
 */
class SessionCoordinator(
    private val process: ProcessContext,
    store: CredentialStore,
    private val transport: RefreshTransport,
    private val publisher: ViewPublisher,
    private val hooks: ScenarioHooks,
    private val audit: AuditRecorder,
    private val cancelTransportOnCancelRefresh: Boolean = true,
) {
    private val store: AuditedCredentialStore =
        store as? AuditedCredentialStore ?: AuditedCredentialStore(store, audit, hooks::storeIOChanged)
    private val worker: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "native-contract-coordinator").apply { isDaemon = true }
    }

    // Enqueue/admission state, guarded by `lock`.
    private val lock = ReentrantLock()
    private val idle = lock.newCondition()
    private var started = false
    private var nextCommandId: Long? = 1L
    private var inFlight = 0
    private var ingressClosed = false
    private var finishInProgress = false
    @Volatile private var endedReference: NativeEventReference? = null
    @Volatile private var terminalWriteStarted = false

    // Worker-confined transaction state.
    private var managed = ManagedAsyncSession()
    private var ownerId = "owner-${UUID.randomUUID()}"
    private var epoch = SessionEpoch()
    private var activeSlot: RefreshSlot? = null
    private val transportHandles = LinkedHashMap<String, TransportHandle>()
    private val nextSlotOrdinal = mutableMapOf(CredentialAccount.A to 0L, CredentialAccount.B to 0L)
    private var pendingStoreCause: String? = null
    private var pendingStoreEpochId: String? = null
    private val detachedReleaseActions = ConcurrentHashMap<String, Long>()

    private var health = CoordinatorHealth.BOOTING
    @Volatile private var currentStoreObservation: StoreObservation = StoreObservation.Unknown("notRead")
    private var currentPhase = SessionPhase.BOOTING
    private var currentAccount: CredentialAccount? = null
    private var currentCredentialVersion: Long? = null
    private var currentPendingRequestId: Long? = null
    private var lastCompletedCommandId: Long? = null
    private var lastCommandStatus: CommandStatus? = null
    private var currentView = DemoViewState(
        processInstanceId = process.processInstanceId,
        revision = 0L,
        phase = SessionPhase.BOOTING,
        account = null,
        credentialVersion = null,
        pendingRequestId = null,
        lastCompletedCommandId = null,
        lastCommandStatus = null,
    )
    private var currentRevision = 0L
    private var lastUIAcknowledgement: NativeEventReference? = null
    private var activeCommand: AppCommandReference? = null
    private var currentCommandName: String? = null

    /** Opens the process journal before the Debug control plane or Bootstrap. */
    fun start() {
        lock.withLock { startLocked() }
    }

    private fun startLocked() {
        if (started) return
        val reference = appendEvent("processStart", mapOf("initialView" to viewJson(currentView)))
        if (reference.localSequence != 1L) {
            throw CoordinatorFailure(CoordinatorFailureCode.JOURNAL_SEQUENCE, "processStart must be the first native row")
        }
        started = true
    }

    /**
     * Records admission synchronously and resolves only after the serial drain has
     * committed the terminal receipt. Rejects with [IngressClosedException] after
     * process end or while a finish attempt has sealed ingress.
     */
    fun submit(command: AppCommand): CompletableFuture<CommandReceipt> {
        val future = CompletableFuture<CommandReceipt>()
        lock.withLock {
            if (!started) startLocked()
            if (ingressClosed || endedReference != null) {
                future.completeExceptionally(IngressClosedException())
                return future
            }
            val reference = AppCommandReference(process.processInstanceId, allocateCommandId())
            appendRequired("commandEnqueued", mapOf("commandRef" to commandJson(reference), "name" to command.name))
            hooks.commandEnqueued(reference, command.name)
            inFlight += 1
            worker.execute { runCommand(reference, command, future) }
        }
        return future
    }

    /**
     * Used only by the Debug finishProcess adapter. Seals ingress, waits for admitted
     * work within the deadline, fences physical transports on the worker and writes
     * the one terminal row. Rejects without a row while a hook is paused.
     */
    fun finishNativeProcess(timeoutMillis: Long): NativeEventReference {
        endedReference?.let { return it }
        if (timeoutMillis !in 1L..21_600_000L) throw CoordinatorFailure(CoordinatorFailureCode.TIMEOUT)
        val deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        val previousIngressClosed: Boolean
        lock.withLock {
            endedReference?.let { return it }
            if (hooks.hasPausedHook || finishInProgress) throw CoordinatorFailure(CoordinatorFailureCode.PROCESS_BUSY)
            finishInProgress = true
            previousIngressClosed = ingressClosed
            ingressClosed = true
        }
        try {
            lock.withLock {
                while (inFlight > 0) {
                    if (hooks.hasPausedHook) throw CoordinatorFailure(CoordinatorFailureCode.PROCESS_BUSY)
                    val remaining = deadline - System.nanoTime()
                    if (remaining <= 0L) throw CoordinatorFailure(CoordinatorFailureCode.TIMEOUT)
                    idle.awaitNanos(minOf(remaining, TimeUnit.MILLISECONDS.toNanos(5)))
                }
            }
            if (hooks.hasPausedHook) throw CoordinatorFailure(CoordinatorFailureCode.PROCESS_BUSY)
            val terminal = CompletableFuture.supplyAsync({ finishOnWorker(deadline) }, worker)
            val remaining = deadline - System.nanoTime()
            if (remaining <= 0L) throw CoordinatorFailure(CoordinatorFailureCode.TIMEOUT)
            return try {
                terminal.get(remaining, TimeUnit.NANOSECONDS)
            } catch (_: TimeoutException) {
                throw CoordinatorFailure(CoordinatorFailureCode.TIMEOUT)
            } catch (error: ExecutionException) {
                throw (error.cause as? CoordinatorFailure) ?: CoordinatorFailure(CoordinatorFailureCode.TERMINAL_JOURNAL)
            }
        } finally {
            lock.withLock {
                finishInProgress = false
                if (endedReference == null && !terminalWriteStarted) ingressClosed = previousIngressClosed
            }
        }
    }

    private fun finishOnWorker(deadline: Long): NativeEventReference {
        // A retry queued behind an earlier, timed-out attempt must not write a second end row.
        endedReference?.let { return it }
        for (handle in transportHandles.values.toList()) {
            if (handle is FencedTransportHandle) {
                val remainingMillis = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime())
                try {
                    handle.cancelAndWait(maxOf(1L, remainingMillis))
                } catch (_: TimeoutException) {
                    throw CoordinatorFailure(CoordinatorFailureCode.TIMEOUT)
                }
            } else {
                handle.cancel()
            }
        }
        activeSlot = null
        epoch = SessionEpoch()
        terminalWriteStarted = true
        val reference = try {
            appendEvent("processEnd", emptyMap())
        } catch (_: Exception) {
            throw CoordinatorFailure(CoordinatorFailureCode.TERMINAL_JOURNAL)
        }
        lock.withLock { endedReference = reference }
        return reference
    }

    private fun runCommand(reference: AppCommandReference, command: AppCommand, future: CompletableFuture<CommandReceipt>) {
        try {
            activeCommand = reference
            currentCommandName = command.name
            hooks.commandStarted(reference, command.name)
            appendRequired("commandStarted", mapOf("commandRef" to commandJson(reference)))
            val execution = execute(command, reference)
            val receipt = execution.receipt
            val receiptReference = appendRequired(
                "commandReceipt",
                mapOf(
                    "commandRef" to commandJson(reference),
                    "acknowledgedEventRef" to eventJson(receipt.acknowledgedEventRef),
                    "status" to receipt.status.wire,
                    "observation" to observationJson(receipt.observation),
                ),
            )
            execution.completion?.let { completion ->
                appendRequired(
                    "completionProcessed",
                    mapOf(
                        "commandRef" to commandJson(reference),
                        "slotId" to completion.slot.slotId,
                        "receiptEventRef" to eventJson(receiptReference),
                    ),
                )
            }
            execution.resetAfterReceipt?.let { reset ->
                appendRequired(
                    "managedInstanceReset",
                    mapOf(
                        "commandRef" to commandJson(reference),
                        "before" to managedJson(reset.before),
                        "after" to managedJson(reset.after),
                    ),
                )
                managed = reset.session
                ownerId = reset.ownerId
                epoch = reset.epoch
            }
            hooks.commandProcessed(reference)
            activeCommand = null
            currentCommandName = null
            future.complete(receipt)
            if (command is AppCommand.Logout) hooks.pauseIfArmed(HookPoint.AFTER_LOGOUT_RECEIPT)
        } catch (error: Throwable) {
            FailStop.stop("command ${command.name} could not reach a synchronized receipt: ${error.javaClass.simpleName}")
        } finally {
            lock.withLock {
                inFlight -= 1
                idle.signalAll()
            }
        }
    }

    private fun execute(command: AppCommand, reference: AppCommandReference): CommandExecution = when (command) {
        AppCommand.Bootstrap -> handleBootstrap(reference)
        is AppCommand.Login -> handleLogin(command.account, reference)
        AppCommand.Expire -> handleExpire(reference)
        AppCommand.Logout -> handleLogout(reference, "Logout", false)
        AppCommand.CancelRefresh -> handleLogout(reference, "CancelRefresh", cancelTransportOnCancelRefresh)
        AppCommand.RetryCleanup -> handleRetryCleanup(reference)
        AppCommand.Observe -> handleObserve(reference)
        is AppCommand.Deliver -> handleRefreshCompletion(command.completion, reference)
    }

    private fun handleBootstrap(reference: AppCommandReference): CommandExecution {
        if (health != CoordinatorHealth.BOOTING) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        hooks.pauseIfArmed(HookPoint.BEFORE_BOOTSTRAP_CLEAR)
        val releaseActionId = hooks.releasedActionId(HookPoint.BEFORE_BOOTSTRAP_CLEAR)
        hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
        return try {
            performVerifiedClear(reference, "Bootstrap", releaseActionId)
            health = CoordinatorHealth.READY
            currentAccount = null
            currentCredentialVersion = null
            currentPendingRequestId = null
            currentPhase = SessionPhase.SIGNED_OUT
            CommandExecution(finalize(reference, CommandStatus.COMPLETED), null)
        } catch (error: Exception) {
            CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), null)
        }
    }

    private fun handleObserve(reference: AppCommandReference): CommandExecution {
        if (health == CoordinatorHealth.BOOTING) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        val actual = try {
            store.readVerified()?.observation() ?: StoreObservation.Absent
        } catch (error: Exception) {
            currentStoreObservation = failureObservation(error)
            return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), null)
        }
        if (currentStoreObservation != actual) {
            val mismatch = CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
            return CommandExecution(lockAfterStoreFailure(mismatch, reference.id, actual), null)
        }
        currentStoreObservation = actual
        return CommandExecution(makeReceipt(reference, CommandStatus.COMPLETED), null)
    }

    private fun handleLogin(account: CredentialAccount, reference: AppCommandReference): CommandExecution {
        if (health != CoordinatorHealth.READY) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        val pre = managed.snapshot()
        if (pre.state != AsyncState.Unauthenticated || pre.pendingRequestId != null ||
            currentStoreObservation != StoreObservation.Absent
        ) {
            return completed(reference, CommandStatus.REJECTED_BUSY, null)
        }
        val credential = Credential.demo(account, 0L)
        hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
        beginStoreAuditContext(reference, "Login", epochId = epoch.id)
        try {
            store.replaceVerified(credential)
            currentStoreObservation = credential.observation()
            endStoreAuditContext()
        } catch (error: Exception) {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            attemptFaultCleanup(reference)
            return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), null)
        }
        val result = managed.handle(ManagedEvent.LoginSucceeded)
        recordManagedReduction(reference, "LoginSucceeded", null, pre, result, epoch.id)
        hooks.pauseIfArmed(HookPoint.AFTER_MANAGED)
        if (result.rejection != null || result.snapshot.state != AsyncState.Authenticated ||
            result.snapshot.pendingRequestId != null || result.effects.isNotEmpty()
        ) {
            val unexpected = CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
            return CommandExecution(lockAfterStoreFailure(unexpected, reference.id, currentStoreObservation), null)
        }
        currentAccount = account
        currentCredentialVersion = credential.version
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNED_IN
        return CommandExecution(finalize(reference, CommandStatus.COMPLETED), null)
    }

    private fun handleExpire(reference: AppCommandReference): CommandExecution {
        if (health != CoordinatorHealth.READY) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        val pre = managed.snapshot()
        if (pre.state != AsyncState.Authenticated || pre.pendingRequestId != null) {
            return completed(reference, CommandStatus.REJECTED_BUSY, null)
        }
        val credential = try {
            store.readVerified()
        } catch (error: Exception) {
            currentStoreObservation = failureObservation(error)
            return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), null)
        }
        val persisted = credential?.observation() ?: StoreObservation.Absent
        if (credential == null || currentStoreObservation != persisted) {
            currentStoreObservation = persisted
            val mismatch = CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
            return CommandExecution(lockAfterStoreFailure(mismatch, reference.id, persisted), null)
        }
        val result = managed.handle(ManagedEvent.TokenExpired)
        recordManagedReduction(reference, "TokenExpired", null, pre, result, epoch.id)
        hooks.pauseIfArmed(HookPoint.AFTER_MANAGED)
        val requests = result.effects.filterIsInstance<ManagedEffect.RequestTokenRefresh>()
        if (result.rejection != null || result.snapshot.state != AsyncState.Refreshing || requests.size != 1) {
            return completed(reference, CommandStatus.REJECTED_BUSY, null)
        }
        val request = requests.single().request
        val slot = RefreshSlot(
            slotId = allocateSlotId(credential.account),
            request = request,
            epoch = epoch,
            issuanceCommandId = reference.id,
            wireTag = "${process.processInstanceId}:refresh:${reference.id}",
            account = credential.account,
            seedVersion = credential.version,
            ownerId = ownerId,
        )
        activeSlot = slot
        currentPendingRequestId = request.requestId
        currentPhase = SessionPhase.REFRESHING
        appendRequired(
            "slotIssued",
            mapOf(
                "commandRef" to commandJson(reference),
                "slotId" to slot.slotId,
                "ownerId" to slot.ownerId,
                "epochId" to slot.epoch.id,
                "requestId" to request.requestId,
                "wireRequestId" to request.requestId.toString(),
                "account" to slot.account.raw,
                "seedVersion" to slot.seedVersion,
                "wireTag" to slot.wireTag,
            ),
        )
        transportHandles[slot.wireTag] = transport.start(slot, credential) { completion -> acceptTransportCompletion(completion) }
        currentAccount = credential.account
        currentCredentialVersion = credential.version
        return CommandExecution(finalize(reference, CommandStatus.COMPLETED), null)
    }

    private fun handleLogout(reference: AppCommandReference, cause: String, cancelTransport: Boolean): CommandExecution {
        val commandId = reference.id
        if (health == CoordinatorHealth.BOOTING) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        if (health == CoordinatorHealth.FAULT_LOCKED) return completed(reference, CommandStatus.FAULT_LOCKED, null)
        val oldSlot = activeSlot
        val logoutEpochId = epoch.id
        activeSlot = null
        epoch = SessionEpoch()
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNING_OUT
        publishTransient(SessionPhase.SIGNING_OUT)
        val pre = managed.snapshot()
        val result = managed.handle(ManagedEvent.Logout)
        recordManagedReduction(reference, "Logout", null, pre, result, logoutEpochId)
        hooks.pauseIfArmed(HookPoint.AFTER_MANAGED)
        pendingStoreCause = cause
        pendingStoreEpochId = logoutEpochId
        return try {
            clearThenPublishSignedOut(commandId)
            if (cancelTransport && oldSlot != null) transportHandles[oldSlot.wireTag]?.cancel()
            CommandExecution(makeReceipt(reference, CommandStatus.COMPLETED), null)
        } catch (error: Exception) {
            CommandExecution(handleLogoutClearFailure(error, commandId), null)
        }
    }

    /** Kept as the mutation-matrix N2 caller anchor; a copied helper substitutes only this call. */
    private fun clearThenPublishSignedOut(commandId: Long) {
        clearThenPublishSignedOut(commandId, null)
    }

    private fun clearThenPublishSignedOut(commandId: Long, causeOverride: String?) {
        val reference = activeCommand
        if (reference == null || reference.id != commandId) {
            throw CoordinatorFailure(CoordinatorFailureCode.JOURNAL_SEQUENCE, "Logout lost its active command reference")
        }
        val cause = causeOverride ?: pendingStoreCause ?: "Logout"
        val storeEpochId = pendingStoreEpochId ?: epoch.id
        hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
        beginStoreAuditContext(reference, cause, epochId = storeEpochId)
        try {
            store.clearVerified()
            currentStoreObservation = StoreObservation.Absent
            endStoreAuditContext()
        } catch (error: Exception) {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            throw error
        }
        currentAccount = null
        currentCredentialVersion = null
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNED_OUT
        publishFinal(reference, CommandStatus.COMPLETED)
    }

    /** Kept as the N4 mutation anchor; a failed clear must stay FaultLocked. */
    private fun handleLogoutClearFailure(error: Exception, commandId: Long): CommandReceipt {
        return lockAfterStoreFailure(error, commandId)
    }

    private fun lockAfterStoreFailure(
        error: Throwable,
        commandId: Long,
        storeObservation: StoreObservation? = null,
    ): CommandReceipt {
        health = CoordinatorHealth.FAULT_LOCKED
        activeSlot = null
        epoch = SessionEpoch()
        currentStoreObservation = storeObservation ?: failureObservation(error)
        currentAccount = null
        currentCredentialVersion = null
        currentPendingRequestId = null
        currentPhase = SessionPhase.FAULT_LOCKED
        return finalize(AppCommandReference(process.processInstanceId, commandId), CommandStatus.FAULT_LOCKED)
    }

    private fun handleRetryCleanup(reference: AppCommandReference): CommandExecution {
        if (health != CoordinatorHealth.FAULT_LOCKED) return completed(reference, CommandStatus.REJECTED_BUSY, null)
        val pre = managed.snapshot()
        val result = managed.handle(ManagedEvent.Logout)
        recordManagedReduction(reference, "Logout", null, pre, result, epoch.id)
        hooks.pauseIfArmed(HookPoint.AFTER_MANAGED)
        if (result.rejection != null || result.snapshot.state != AsyncState.Unauthenticated ||
            result.snapshot.pendingRequestId != null
        ) {
            val unexpected = CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
            return CommandExecution(lockAfterStoreFailure(unexpected, reference.id, currentStoreObservation), null)
        }
        val before = managedViewSnapshot(ownerId, result.snapshot)
        hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
        beginStoreAuditContext(reference, "RetryCleanup", epochId = epoch.id)
        try {
            store.clearVerified()
            currentStoreObservation = StoreObservation.Absent
            endStoreAuditContext()
        } catch (error: Exception) {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), null)
        }
        activeSlot = null
        currentAccount = null
        currentCredentialVersion = null
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNED_OUT
        health = CoordinatorHealth.READY
        val receipt = finalize(reference, CommandStatus.COMPLETED)
        val replacement = ManagedAsyncSession()
        val replacementOwner = "owner-${UUID.randomUUID()}"
        val after = managedViewSnapshot(replacementOwner, replacement.snapshot())
        return CommandExecution(
            receipt,
            null,
            ManagedResetPlan(before, after, replacement, replacementOwner, SessionEpoch()),
        )
    }

    private fun handleRefreshCompletion(completion: Completion, reference: AppCommandReference): CommandExecution {
        val slot = completion.slot
        val outcome = completion.outcome
        appendRequired(
            "transportReceived",
            mapOf(
                "commandRef" to commandJson(reference),
                "slotId" to slot.slotId,
                "outcome" to outcome.label,
                "failureCode" to outcome.failureCode,
                "requestTag" to slot.wireTag,
            ),
        )
        hooks.pauseIfArmed(HookPoint.INGRESS_HELD)
        if (health == CoordinatorHealth.FAULT_LOCKED) {
            return CommandExecution(finalize(reference, CommandStatus.FAULT_LOCKED), completion)
        }
        val preSnapshot = managed.snapshot()
        val managedPre = managedViewSnapshot(ownerId, preSnapshot)
        val eligible = health == CoordinatorHealth.READY &&
            activeSlot === slot &&
            slot.epoch === epoch &&
            preSnapshot.state == AsyncState.Refreshing &&
            preSnapshot.pendingRequestId == slot.request.requestId
        val event = if (outcome.isSuccess) ManagedEvent.RefreshSucceeded(slot.request) else ManagedEvent.RefreshFailed(slot.request)
        val result = managed.handle(event)
        recordManagedReduction(
            reference,
            if (outcome.isSuccess) "RefreshSucceeded" else "RefreshFailed",
            slot.request.requestId,
            preSnapshot,
            result,
            slot.epoch.id,
            slot,
        )
        hooks.pauseIfArmed(HookPoint.AFTER_MANAGED)
        val validSuccessPayload = outcome is RefreshOutcome.Success && slot.seedVersion < Long.MAX_VALUE && run {
            val expectedVersion = slot.seedVersion + 1L
            val expectedToken = Credential.token(slot.account, expectedVersion)
            val payload = outcome.credential
            payload.account == slot.account && payload.version == expectedVersion &&
                payload.accessToken == expectedToken && payload.refreshToken == expectedToken
        }
        val acceptedSuccess = outcome.isSuccess &&
            validSuccessPayload &&
            result.rejection == null &&
            result.snapshot.state == AsyncState.Authenticated &&
            result.snapshot.pendingRequestId == null &&
            result.effects.isEmpty()
        val admittedSuccess = eligible && acceptedSuccess
        val successPayload = (outcome as? RefreshOutcome.Success)?.credential

        if (admittedSuccess && successPayload != null) {
            activeSlot = null
            currentPendingRequestId = null
            try {
                hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
                beginStoreAuditContext(reference, "RefreshSuccess", slot.epoch.id, slot.slotId, slot.ownerId)
                try {
                    commitRefreshSuccess(successPayload, reference.id)
                    endStoreAuditContext()
                } catch (error: Exception) {
                    endStoreAuditContext()
                    throw error
                }
                currentPhase = SessionPhase.SIGNED_IN
                return CommandExecution(makeReceipt(reference, CommandStatus.COMPLETED), completion)
            } catch (error: Exception) {
                currentStoreObservation = failureObservation(error)
                attemptFaultCleanup(reference)
                return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), completion)
            }
        }

        val acceptedFailure = !outcome.isSuccess &&
            result.rejection == null &&
            result.snapshot.state == AsyncState.Unauthenticated &&
            result.snapshot.pendingRequestId == null &&
            result.effects.any { it is ManagedEffect.ClearCredentials }
        if (eligible && acceptedFailure) {
            activeSlot = null
            currentPendingRequestId = null
            try {
                hooks.pauseIfArmed(HookPoint.BEFORE_STORE)
                beginStoreAuditContext(reference, "RefreshFailure", slot.epoch.id, slot.slotId, slot.ownerId)
                try {
                    store.clearVerified()
                    currentStoreObservation = StoreObservation.Absent
                    endStoreAuditContext()
                } catch (error: Exception) {
                    endStoreAuditContext()
                    throw error
                }
                currentAccount = null
                currentCredentialVersion = null
                currentPhase = SessionPhase.SIGNED_OUT
                return CommandExecution(finalize(reference, CommandStatus.COMPLETED), completion)
            } catch (error: Exception) {
                currentStoreObservation = failureObservation(error)
                return CommandExecution(lockAfterStoreFailure(error, reference.id, currentStoreObservation), completion)
            }
        }

        if (eligible) {
            val unexpected = CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
            return CommandExecution(lockAfterStoreFailure(unexpected, reference.id, currentStoreObservation), completion)
        }

        val managedPost = managedViewSnapshot(ownerId, result.snapshot)
        if (managedPre != managedPost || result.effects.isNotEmpty()) {
            val unexpected = CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
            return CommandExecution(lockAfterStoreFailure(unexpected, reference.id, currentStoreObservation), completion)
        }
        if (activeSlot === slot) activeSlot = null
        currentPhase = currentView.phase
        val ignored = if (result.rejection == ManagedRejection.ForeignRequest) CommandStatus.IGNORED_FOREIGN else CommandStatus.IGNORED_STALE
        return CommandExecution(finalize(reference, ignored), completion)
    }

    /**
     * Mutation-matrix N3 anchor. The verified store write precedes the main-thread
     * assignment acknowledgement; the swapped order is confined to the copied mutant.
     */
    private fun commitRefreshSuccess(credential: Credential, commandId: Long) {
        store.replaceVerified(credential)
        publishSignedIn(credential, commandId)
    }

    private fun publishSignedIn(credential: Credential, commandId: Long) {
        currentStoreObservation = credential.observation()
        currentAccount = credential.account
        currentCredentialVersion = credential.version
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNED_IN
        publishFinal(activeCommand ?: AppCommandReference(process.processInstanceId, commandId), CommandStatus.COMPLETED)
    }

    /**
     * Same-transaction best-effort cleanup after a failed credential write (design
     * §4.2). A failed cleanup keeps its failure observation; the command still ends
     * FaultLocked either way.
     */
    private fun attemptFaultCleanup(reference: AppCommandReference) {
        try {
            performVerifiedClear(reference, "FaultCleanup", null)
        } catch (_: Exception) {
            // performVerifiedClear already recorded the failure observation.
        }
    }

    // Isolated N2 helper adapters. The ordinary Logout path never calls these methods.
    fun n2PerformNormalVerifiedLogout(commandId: Long) {
        pendingStoreCause = "Logout"
        pendingStoreEpochId = epoch.id
        clearThenPublishSignedOut(commandId, "Logout")
    }

    fun n2ScheduleDetachedEffect(effectId: String, originCommandId: Long, action: () -> Unit) {
        thread(name = "native-contract-detached-effect", isDaemon = true) { action() }
    }

    fun n2PauseBeforeDeferredControlClear(effectId: String, originCommandId: Long) {
        detachedReleaseActions[effectId] = hooks.pauseDetachedEffect(effectId, originCommandId)
    }

    fun n2PerformDuplicateClearAndRecord(effectId: String, originCommandId: Long) {
        val actionId = detachedReleaseActions[effectId] ?: 0L
        val context = StoreAuditContext(
            commandRef = null,
            cause = "DeferredLogoutClear",
            effectId = traceEffectLabel(effectId),
            originCommandRef = AppCommandReference(process.processInstanceId, originCommandId),
            releaseActionId = actionId.takeIf { it > 0L },
        )
        val observed = try {
            store.beginOperation(context)
            try {
                store.clearVerified()
                StoreObservation.Absent
            } finally {
                store.endOperation()
            }
        } catch (error: Exception) {
            failureObservation(error)
        }
        worker.execute { currentStoreObservation = observed }
    }

    // Isolated N4 helper adapters. The ordinary failed-clear path never calls these.
    fun n4PublishSignedOutWithoutStoreClear(commandId: Long) {
        currentStoreObservation = StoreObservation.Unknown("readFailed")
        currentAccount = null
        currentCredentialVersion = null
        currentPendingRequestId = null
        currentPhase = SessionPhase.SIGNED_OUT
        publishFinal(AppCommandReference(process.processInstanceId, commandId), CommandStatus.COMPLETED)
    }

    fun n4MakeCompletedLogoutReceipt(commandId: Long): CommandReceipt =
        makeReceipt(AppCommandReference(process.processInstanceId, commandId), CommandStatus.COMPLETED)

    private fun completed(reference: AppCommandReference, status: CommandStatus, completion: Completion?): CommandExecution =
        CommandExecution(finalize(reference, status), completion)

    private fun finalize(reference: AppCommandReference, status: CommandStatus): CommandReceipt {
        publishFinal(reference, status)
        return makeReceipt(reference, status)
    }

    private fun publishFinal(reference: AppCommandReference, status: CommandStatus): NativeEventReference {
        lastCompletedCommandId = reference.id
        lastCommandStatus = status
        val view = nextView(currentPhase, currentAccount, currentCredentialVersion, currentPendingRequestId, reference.id, status)
        return publish(reference, view)
    }

    private fun publishTransient(phase: SessionPhase): NativeEventReference? {
        val reference = activeCommand ?: return null
        val view = nextView(phase, null, null, null, lastCompletedCommandId, lastCommandStatus)
        return publish(reference, view)
    }

    private fun publish(reference: AppCommandReference, view: DemoViewState): NativeEventReference {
        hooks.pauseIfArmed(HookPoint.BEFORE_PUBLISH)
        try {
            publisher.publish(view, currentStoreObservation).get()
        } catch (error: Exception) {
            FailStop.stop("UI publication failed: ${error.javaClass.simpleName}")
        }
        currentView = view
        val acknowledgement = appendRequired(
            "uiPublishAck",
            mapOf("commandRef" to commandJson(reference), "revision" to view.revision, "view" to viewJson(view)),
        )
        lastUIAcknowledgement = acknowledgement
        hooks.pauseIfArmed(HookPoint.AFTER_PUBLISH_ACK)
        return acknowledgement
    }

    private fun makeReceipt(reference: AppCommandReference, status: CommandStatus): CommandReceipt {
        val observation = CommandObservation(
            managed = managedViewSnapshot(ownerId, managed.snapshot()),
            store = currentStoreObservation,
            view = currentView,
            revision = currentView.revision,
        )
        return CommandReceipt(reference.id, currentCommandName ?: "Observe", status, observation, lastUIAcknowledgement)
    }

    private fun performVerifiedClear(reference: AppCommandReference, cause: String, releaseActionId: Long?) {
        beginStoreAuditContext(reference, cause, epochId = epoch.id, releaseActionId = releaseActionId)
        try {
            store.clearVerified()
            currentStoreObservation = StoreObservation.Absent
            endStoreAuditContext()
        } catch (error: Exception) {
            endStoreAuditContext()
            currentStoreObservation = failureObservation(error)
            throw error
        }
    }

    private fun beginStoreAuditContext(
        reference: AppCommandReference,
        cause: String,
        epochId: String? = null,
        slotId: String? = null,
        ownerId: String? = null,
        releaseActionId: Long? = null,
    ) {
        try {
            store.beginOperation(StoreAuditContext(reference, cause, epochId, slotId, ownerId, releaseActionId = releaseActionId))
        } catch (error: Exception) {
            FailStop.stop("store audit context collision")
        }
    }

    private fun endStoreAuditContext() = store.endOperation()

    private fun failureObservation(error: Throwable): StoreObservation = when (error) {
        is CredentialStoreFailure -> error.observation
        is CredentialStoreException -> StoreObservation.Unknown(error.code.safeCode)
        else -> StoreObservation.Unknown("storeFailure")
    }

    private fun recordManagedReduction(
        reference: AppCommandReference,
        event: String,
        requestId: Long?,
        pre: ManagedSnapshot,
        result: ManagedResult,
        epochId: String,
        slot: RefreshSlot? = null,
    ) {
        val reducerEvent = linkedMapOf<String, Any?>("event" to event)
        requestId?.let { reducerEvent["requestId"] = it }
        val fields = linkedMapOf<String, Any?>(
            "commandRef" to commandJson(reference),
            "event" to reducerEvent,
            "pre" to managedJson(managedViewSnapshot(ownerId, pre)),
            "result" to managedResultJson(ownerId, result),
            "epochId" to epochId,
        )
        if (slot != null) {
            fields["slotId"] = slot.slotId
            fields["requestOwnerId"] = slot.ownerId
        }
        appendRequired("managedReduced", fields)
    }

    private fun appendEvent(kind: String, fields: Map<String, Any?>): NativeEventReference {
        if (endedReference != null && kind != "processEnd") throw CoordinatorFailure(CoordinatorFailureCode.ENDED)
        val terminal = audit as? TerminalAuditRecorder
        val localSequence = if (kind == "processEnd" && terminal != null) {
            terminal.appendProcessEndAndSeal(fields)
        } else {
            audit.append(kind, fields).also { audit.synchronize() }
        }
        if (localSequence <= 0L) {
            throw CoordinatorFailure(CoordinatorFailureCode.JOURNAL_SEQUENCE, "invalid local sequence from recorder")
        }
        return NativeEventReference(process.processInstanceId, localSequence)
    }

    private fun appendRequired(kind: String, fields: Map<String, Any?>): NativeEventReference = try {
        appendEvent(kind, fields)
    } catch (error: Exception) {
        FailStop.stop("native event $kind could not be synchronized: ${error.javaClass.simpleName}")
    }

    private fun acceptTransportCompletion(completion: Completion) {
        // A completion after process end or during a finish attempt is dropped before
        // reducer dispatch, receipt, store access, publication or audit append.
        submit(AppCommand.Deliver(completion))
    }

    private fun allocateCommandId(): Long {
        val id = nextCommandId ?: FailStop.stop("CounterExhausted: app command ID")
        nextCommandId = if (id == Long.MAX_VALUE) null else id + 1L
        return id
    }

    private fun allocateRevision(): Long {
        if (currentRevision == Long.MAX_VALUE) FailStop.stop("CounterExhausted: UI revision")
        currentRevision += 1L
        return currentRevision
    }

    private fun allocateSlotId(account: CredentialAccount): String {
        val current = nextSlotOrdinal.getValue(account)
        if (current == Long.MAX_VALUE) FailStop.stop("CounterExhausted: refresh slot label")
        nextSlotOrdinal[account] = current + 1L
        return "slot-${account.raw}${current + 1L}"
    }

    private fun nextView(
        phase: SessionPhase,
        account: CredentialAccount?,
        credentialVersion: Long?,
        pendingRequestId: Long?,
        lastCompletedCommandId: Long?,
        lastCommandStatus: CommandStatus?,
    ) = DemoViewState(
        processInstanceId = process.processInstanceId,
        revision = allocateRevision(),
        phase = phase,
        account = account,
        credentialVersion = credentialVersion,
        pendingRequestId = pendingRequestId,
        lastCompletedCommandId = lastCompletedCommandId,
        lastCommandStatus = lastCommandStatus,
    )

    private fun traceEffectLabel(helperEffectId: String): String =
        if (process.scenarioId == "CTRL-N2-LATE-CLEAR" && helperEffectId.startsWith("duplicate-logout-")) "late-clear-1" else helperEffectId

    private companion object {
        fun commandJson(reference: AppCommandReference): Map<String, Any?> =
            mapOf("processInstanceId" to reference.processInstanceId, "id" to reference.id)

        fun eventJson(reference: NativeEventReference?): Map<String, Any?>? = reference?.let {
            mapOf("processInstanceId" to it.processInstanceId, "localSequence" to it.localSequence)
        }

        fun viewJson(view: DemoViewState): Map<String, Any?> = mapOf(
            "phase" to view.phase.wire,
            "account" to view.account?.raw,
            "credentialVersion" to view.credentialVersion,
            "pendingRequestId" to view.pendingRequestId,
            "lastCompletedCommandId" to view.lastCompletedCommandId,
            "lastCommandStatus" to view.lastCommandStatus?.wire,
        )

        fun observationJson(observation: CommandObservation): Map<String, Any?> = mapOf(
            "managed" to managedJson(observation.managed),
            "store" to observation.store.toRedactedFields(),
            "view" to viewJson(observation.view),
            "revision" to observation.revision,
        )

        fun managedViewSnapshot(ownerId: String, snapshot: ManagedSnapshot) =
            ManagedViewSnapshot(ownerId, snapshot.state.name, snapshot.pendingRequestId, snapshot.nextRequestId)

        fun managedJson(snapshot: ManagedViewSnapshot): Map<String, Any?> = mapOf(
            "ownerId" to snapshot.ownerId,
            "state" to snapshot.state,
            "pendingRequestId" to snapshot.pendingRequestId,
            "nextRequestId" to snapshot.nextRequestId,
        )

        fun managedResultJson(ownerId: String, result: ManagedResult): Map<String, Any?> = mapOf(
            "ownerId" to ownerId,
            "state" to result.snapshot.state.name,
            "pendingRequestId" to result.snapshot.pendingRequestId,
            "nextRequestId" to result.snapshot.nextRequestId,
            "effects" to result.effects.map { effect ->
                when (effect) {
                    ManagedEffect.ClearCredentials -> mapOf("effect" to "ClearCredentials")
                    is ManagedEffect.RequestTokenRefresh -> mapOf("effect" to "RequestTokenRefresh", "requestId" to effect.request.requestId)
                }
            },
            "rejection" to when (result.rejection) {
                ManagedRejection.ForeignRequest -> "ForeignRequest"
                ManagedRejection.RequestIdExhausted -> "RequestIdExhausted"
                null -> null
            },
        )
    }
}
