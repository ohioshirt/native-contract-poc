package nativecontract.demo.storage

import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.coordinator.AppCommandReference
import nativecontract.demo.coordinator.AuditRecorder
import nativecontract.demo.coordinator.Credential

/** Synchronous verified persistence. The coordinator worker is the sole production caller. */
interface CredentialStore {
    fun readVerified(): Credential?
    fun replaceVerified(credential: Credential)
    fun clearVerified()
}

interface StoreFaultInjecting {
    fun setStoreFault(kind: String?)
}

enum class CredentialStoreErrorCode(val safeCode: String) {
    READ_FAILED("readFailed"),
    REPLACE_FAILED("replaceFailed"),
    CLEAR_FAILED("clearFailed"),
    READBACK_FAILED("readbackFailed"),
    MALFORMED_CREDENTIAL("malformedCredential"),
    AUDIT_CONTEXT_MISSING("auditContextMissing"),
}

class CredentialStoreException(val code: CredentialStoreErrorCode, cause: Throwable? = null) :
    Exception(code.safeCode, cause)

/** A test-injected operation failure with an explicitly recorded physical attempt. */
class CredentialStoreFailure(
    val operation: String,
    val fault: String,
    val mutationApplied: Boolean,
    val verification: String,
    val before: StoreObservation,
    val observation: StoreObservation,
    val physicalAfter: StoreObservation,
) : Exception("store fault $fault")

data class StoreAuditContext(
    val commandRef: AppCommandReference?,
    val cause: String,
    val epochId: String? = null,
    val slotId: String? = null,
    val ownerId: String? = null,
    val effectId: String? = null,
    val originCommandRef: AppCommandReference? = null,
    val releaseActionId: Long? = null,
)

fun Credential.observation(): StoreObservation = StoreObservation.Present(account.raw, version)

/**
 * Decorates a physical store so its actual write/readback rows are synchronized
 * before the coordinator can publish the resulting view. Physical operations are
 * serialized; the audit context is set by the caller around each operation.
 */
class AuditedCredentialStore(
    private val base: CredentialStore,
    private val audit: AuditRecorder,
    private val storeIOChanged: (Boolean) -> Unit,
) : CredentialStore, StoreFaultInjecting {
    private val contextLock = Any()
    private var context: StoreAuditContext? = null

    /**
     * Last observation this wrapper audited (readback or fault), mirroring the
     * evaluator's verified-store chain for later mutation `before` values.
     */
    private var lastAuditedObservation: StoreObservation? = null

    fun beginOperation(value: StoreAuditContext) {
        synchronized(contextLock) {
            if (context != null) throw CredentialStoreException(CredentialStoreErrorCode.AUDIT_CONTEXT_MISSING)
            context = value
        }
    }

    fun endOperation() {
        synchronized(contextLock) { context = null }
    }

    override fun setStoreFault(kind: String?) {
        (base as? StoreFaultInjecting)?.setStoreFault(kind)
    }

    @Synchronized
    override fun readVerified(): Credential? {
        storeIOChanged(true)
        try {
            return base.readVerified()
        } finally {
            storeIOChanged(false)
        }
    }

    @Synchronized
    override fun replaceVerified(credential: Credential) {
        val operation = currentContext()
        storeIOChanged(true)
        try {
            val before = observedStore()
            try {
                base.replaceVerified(credential)
                val readback = observedStore()
                if (readback != credential.observation()) {
                    throw CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
                }
                recordMutation(operation, "replace", before, readback)
                recordReadback(operation, "replace", readback)
            } catch (failure: CredentialStoreFailure) {
                recordFailure(operation, failure)
                throw failure
            }
        } finally {
            storeIOChanged(false)
        }
    }

    @Synchronized
    override fun clearVerified() {
        val operation = currentContext()
        storeIOChanged(true)
        try {
            // A malformed/unreadable record must not block deleting this store's one
            // owned item. Once this process has audited an observation, `before`
            // chains from it so an earlier Unknown is not replaced by a fresh read.
            val before = synchronized(contextLock) { lastAuditedObservation } ?: bestEffortObservation()
            try {
                base.clearVerified()
                val readback = observedStore()
                if (readback != StoreObservation.Absent) {
                    throw CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
                }
                recordMutation(operation, "clear", before, readback)
                recordReadback(operation, "clear", readback)
            } catch (failure: CredentialStoreFailure) {
                recordFailure(operation, failure)
                throw failure
            }
        } finally {
            storeIOChanged(false)
        }
    }

    private fun currentContext(): StoreAuditContext = synchronized(contextLock) {
        context ?: throw CredentialStoreException(CredentialStoreErrorCode.AUDIT_CONTEXT_MISSING)
    }

    private fun observedStore(): StoreObservation = base.readVerified()?.observation() ?: StoreObservation.Absent

    private fun bestEffortObservation(): StoreObservation = try {
        observedStore()
    } catch (error: CredentialStoreException) {
        StoreObservation.Unknown(error.code.safeCode)
    } catch (_: Exception) {
        StoreObservation.Unknown("storeFailure")
    }

    private fun recordMutation(
        context: StoreAuditContext,
        operation: String,
        before: StoreObservation,
        after: StoreObservation,
    ) {
        val fields = linkedMapOf<String, Any?>(
            "operation" to operation,
            "before" to before.toRedactedFields(),
            "after" to after.toRedactedFields(),
            "cause" to context.cause,
        )
        context.commandRef?.let { fields["commandRef"] = commandJson(it) }
        context.epochId?.let { fields["epochId"] = it }
        context.slotId?.let { fields["slotId"] = it }
        context.ownerId?.let { fields["ownerId"] = it }
        context.effectId?.let { fields["effectId"] = it }
        context.originCommandRef?.let { fields["originCommandRef"] = commandJson(it) }
        context.releaseActionId?.let { fields["releaseActionId"] = it }
        append(if (context.effectId != null) "detachedStoreMutation" else "storeMutation", fields)
    }

    private fun recordReadback(context: StoreAuditContext, operation: String, observation: StoreObservation) {
        val fields = linkedMapOf<String, Any?>(
            "operation" to operation,
            "observation" to observation.toRedactedFields(),
        )
        context.commandRef?.let { fields["commandRef"] = commandJson(it) }
        context.effectId?.let { fields["effectId"] = it }
        context.originCommandRef?.let { fields["originCommandRef"] = commandJson(it) }
        append(if (context.effectId != null) "detachedStoreReadback" else "storeReadback", fields)
        synchronized(contextLock) { lastAuditedObservation = observation }
    }

    private fun recordFailure(context: StoreAuditContext, failure: CredentialStoreFailure) {
        if (failure.mutationApplied) {
            recordMutation(context, failure.operation, failure.before, failure.physicalAfter)
        }
        val commandRef = context.commandRef
        if (context.effectId != null || commandRef == null) return
        append(
            "storeFault",
            mapOf(
                "commandRef" to commandJson(commandRef),
                "operation" to failure.operation,
                "fault" to failure.fault,
                "mutationApplied" to failure.mutationApplied,
                "verification" to failure.verification,
                "before" to failure.before.toRedactedFields(),
                "observation" to failure.observation.toRedactedFields(),
            ),
        )
        synchronized(contextLock) { lastAuditedObservation = failure.observation }
    }

    private fun append(kind: String, fields: Map<String, Any?>) {
        audit.append(kind, fields)
        audit.synchronize()
    }

    private fun commandJson(reference: AppCommandReference): Map<String, Any?> =
        mapOf("processInstanceId" to reference.processInstanceId, "id" to reference.id)
}
