package nativecontract.demo.coordinator

import java.util.concurrent.CompletableFuture
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.transport.Completion

enum class CredentialAccount(val raw: String) {
    A("A"),
    B("B");

    val label: String get() = "demo-$raw"

    companion object {
        fun fromRaw(raw: String): CredentialAccount? = entries.firstOrNull { it.raw == raw }
    }
}

/** Synthetic-only credential data. Values never enter UI, audit rows or `toString`. */
class Credential(
    val account: CredentialAccount,
    val version: Long,
    val accessToken: String,
    val refreshToken: String,
) {
    override fun equals(other: Any?): Boolean =
        other is Credential && account == other.account && version == other.version &&
            accessToken == other.accessToken && refreshToken == other.refreshToken

    override fun hashCode(): Int = 31 * account.hashCode() + version.hashCode()

    override fun toString(): String = "Credential(<redacted>)"

    companion object {
        fun token(account: CredentialAccount, version: Long): String = "demo-${account.raw}-v$version"

        fun demo(account: CredentialAccount, version: Long): Credential {
            val token = token(account, version)
            return Credential(account, version, token, token)
        }
    }
}

data class ProcessContext(
    val processInstanceId: String,
    val launchOrdinal: Long,
    val attemptId: String,
    val scenarioId: String,
)

data class NativeEventReference(val processInstanceId: String, val localSequence: Long)

data class AppCommandReference(val processInstanceId: String, val id: Long)

enum class SessionPhase(val wire: String, val userLabel: String) {
    BOOTING("Booting", "Booting"),
    SIGNED_OUT("SignedOut", "Signed out"),
    SIGNING_OUT("SigningOut", "Signing out"),
    SIGNED_IN("SignedIn", "Signed in"),
    REFRESHING("Refreshing", "Refreshing"),
    FAULT_LOCKED("FaultLocked", "Fault locked"),
}

enum class CommandStatus(val wire: String) {
    COMPLETED("Completed"),
    REJECTED_BUSY("RejectedBusy"),
    IGNORED_STALE("IgnoredStale"),
    IGNORED_FOREIGN("IgnoredForeign"),
    REJECTED_EXHAUSTED("RejectedExhausted"),
    FAULT_LOCKED("FaultLocked"),
}

data class DemoViewState(
    val processInstanceId: String,
    val revision: Long,
    val phase: SessionPhase,
    val account: CredentialAccount?,
    val credentialVersion: Long?,
    val pendingRequestId: Long?,
    val lastCompletedCommandId: Long?,
    val lastCommandStatus: CommandStatus?,
)

sealed interface AppCommand {
    val name: String

    data object Bootstrap : AppCommand { override val name = "Bootstrap" }
    data class Login(val account: CredentialAccount) : AppCommand { override val name = "Login(${account.raw})" }
    data object Expire : AppCommand { override val name = "Expire" }
    data object Logout : AppCommand { override val name = "Logout" }
    data object CancelRefresh : AppCommand { override val name = "CancelRefresh" }
    data object RetryCleanup : AppCommand { override val name = "RetryCleanup" }
    data object Observe : AppCommand { override val name = "Observe" }

    /** Carries the opaque issued slot by reference; never reconstructed from wire values. */
    class Deliver(val completion: Completion) : AppCommand {
        override val name: String get() = "Deliver(${completion.slot.slotId},${completion.outcome.label})"
    }
}

data class ManagedViewSnapshot(
    val ownerId: String,
    val state: String,
    val pendingRequestId: Long?,
    val nextRequestId: Long?,
)

data class CommandObservation(
    val managed: ManagedViewSnapshot,
    val store: StoreObservation,
    val view: DemoViewState,
    val revision: Long,
)

data class CommandReceipt(
    val commandId: Long,
    val commandName: String,
    val status: CommandStatus,
    val observation: CommandObservation,
    val acknowledgedEventRef: NativeEventReference?,
)

/**
 * Main-thread publication boundary. The returned future completes only after the
 * immutable view state has been assigned on the main thread; the implementation
 * must never call back into the coordinator.
 */
interface ViewPublisher {
    fun publish(view: DemoViewState): CompletableFuture<Unit>
}

/** Submissions after process end or during a finish attempt are not admitted. */
class IngressClosedException : IllegalStateException("command ingress is closed")

/**
 * Terminal fail-stop for counter exhaustion and unsynchronizable audit/publication
 * paths. It terminates only this demo process; tests may replace the handler.
 */
object FailStop {
    @Volatile
    var handler: (String) -> Unit = { reason ->
        System.err.println("native-contract fail-stop: $reason")
        Runtime.getRuntime().halt(70)
    }

    fun stop(reason: String): Nothing {
        handler(reason)
        throw IllegalStateException("fail-stop: $reason")
    }
}
