package nativecontract.demo

import android.app.Application
import java.io.File
import java.util.UUID
import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.NoopAuditRecorder
import nativecontract.demo.coordinator.NoopScenarioHooks
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.storage.AtomicFileCredentialStore
import nativecontract.demo.transport.UrlConnectionRefreshTransport
import nativecontract.demo.ui.DemoViewModel

/**
 * Owns the one coordinator and view model for the process lifetime; Activities
 * only attach. The Release composition references no Debug-only type.
 */
open class DemoApplication : Application() {
    lateinit var viewModel: DemoViewModel
        protected set
    protected var coordinator: SessionCoordinator? = null

    override fun onCreate() {
        super.onCreate()
        startEnvironment()
    }

    protected open fun startEnvironment() {
        val attemptId = "production-${UUID.randomUUID()}"
        val process = ProcessContext("$attemptId/production/p1", 1L, attemptId, "production")
        val model = DemoViewModel(process)
        viewModel = model
        try {
            val coordinator = SessionCoordinator(
                process = process,
                store = AtomicFileCredentialStore(File(noBackupFilesDir, "demo-session/production")),
                transport = UrlConnectionRefreshTransport(PRODUCTION_BASE_URL, attemptId),
                publisher = model,
                hooks = NoopScenarioHooks,
                audit = NoopAuditRecorder(),
            )
            this.coordinator = coordinator
            model.attach(coordinator)
            coordinator.start()
            coordinator.submit(AppCommand.Bootstrap)
        } catch (error: Exception) {
            model.setStartupError(error)
        }
    }

    private companion object {
        const val PRODUCTION_BASE_URL = "http://10.0.2.2:8080"
    }
}
