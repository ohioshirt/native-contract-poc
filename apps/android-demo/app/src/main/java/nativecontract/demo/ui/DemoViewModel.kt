package nativecontract.demo.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.concurrent.CompletableFuture
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.DemoViewState
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.coordinator.SessionPhase
import nativecontract.demo.coordinator.ViewPublisher

/**
 * Application-owned view model. `publish` assigns one immutable state on the main
 * looper and only then completes the acknowledgement; it never calls the
 * coordinator. Activity recreation re-attaches to this same instance.
 */
class DemoViewModel(process: ProcessContext) : ViewPublisher {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var coordinator: SessionCoordinator? = null

    var current by mutableStateOf(
        DemoViewState(process.processInstanceId, 0L, SessionPhase.BOOTING, null, null, null, null, null),
    )
        private set
    var storeObservation by mutableStateOf<StoreObservation>(StoreObservation.Unknown("notRead"))
        private set
    var startupError by mutableStateOf<String?>(null)
        private set

    override fun publish(view: DemoViewState, store: StoreObservation): CompletableFuture<Unit> {
        val acknowledged = CompletableFuture<Unit>()
        mainHandler.post {
            if (view.processInstanceId == current.processInstanceId && view.revision > current.revision) {
                current = view
                storeObservation = store
            }
            acknowledged.complete(Unit)
        }
        return acknowledged
    }

    fun attach(coordinator: SessionCoordinator) {
        this.coordinator = coordinator
    }

    /**
     * Non-blocking: the main thread never waits on a command future. The store label
     * follows publications only: a receipt can arrive after a newer publication (for
     * example an HTTP completion) and would roll the label back.
     */
    fun submit(command: AppCommand) {
        coordinator?.submit(command)
    }

    fun setStartupError(error: Throwable) {
        mainHandler.post { startupError = error.javaClass.simpleName + ": " + (error.message ?: "") }
    }

    /** Frozen session-state labels: authenticated phases append the redacted account label. */
    val sessionLabel: String
        get() {
            val account = accountLabel
            return if (account.isEmpty()) current.phase.userLabel else "${current.phase.userLabel} $account"
        }

    val accountLabel: String
        get() {
            val view = current
            if (view.phase != SessionPhase.SIGNED_IN && view.phase != SessionPhase.REFRESHING) return ""
            return view.account?.label ?: ""
        }

    val credentialStatusLabel: String
        get() = when (val observation = storeObservation) {
            StoreObservation.Absent -> "Credentials absent"
            is StoreObservation.Present -> "Credentials version ${observation.version}"
            is StoreObservation.Unknown -> "Credentials unknown"
        }
}
