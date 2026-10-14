package nativecontract.demo.transport

import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.RefreshSlot

sealed interface RefreshOutcome {
    val label: String
    val isSuccess: Boolean
    val failureCode: String?

    class Success(val credential: Credential) : RefreshOutcome {
        override val label = "success"
        override val isSuccess = true
        override val failureCode: String? = null
    }

    data class Failure(val code: String) : RefreshOutcome {
        override val label = "failure"
        override val isSuccess = false
        override val failureCode: String? get() = code
    }
}

/** A decoded response bound to the original issued slot reference. */
class Completion(val slot: RefreshSlot, val outcome: RefreshOutcome)

interface TransportHandle {
    fun cancel()
}

/** A handle whose producer can be cancelled and awaited so late callbacks are fenced. */
interface FencedTransportHandle : TransportHandle {
    /** Throws [java.util.concurrent.TimeoutException] when the producer did not settle in time. */
    fun cancelAndWait(timeoutMillis: Long)
}

interface RefreshTransport {
    fun start(slot: RefreshSlot, credential: Credential, completion: (Completion) -> Unit): TransportHandle
}
