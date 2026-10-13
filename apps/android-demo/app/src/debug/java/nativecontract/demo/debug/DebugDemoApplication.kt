package nativecontract.demo.debug

import java.io.File
import java.net.URI
import java.util.UUID
import nativecontract.demo.DemoApplication
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.ProcessContext
import nativecontract.demo.coordinator.SessionCoordinator
import nativecontract.demo.storage.AtomicFileCredentialStore
import nativecontract.demo.storage.AuditedCredentialStore
import nativecontract.demo.transport.UrlConnectionRefreshTransport
import nativecontract.demo.ui.DemoViewModel

/**
 * Debug composition. The frozen runner supplies an immutable launch configuration
 * before `onCreate`; the environment, control plane and coordinator are created
 * from it once, startup arms precede Bootstrap, and Bootstrap is submitted
 * without blocking on its receipt.
 */
class DebugDemoApplication : DemoApplication(), DebugScenarioControlProvider {
    private var launchConfig: Map<String, String>? = null
    private var created = false
    private var control: DefaultDebugScenarioControl? = null

    override val debugScenarioControl: DebugScenarioControl
        get() = control ?: error("Debug scenario control is unavailable: ${viewModel.startupError ?: "not started"}")

    fun configureTestLaunch(config: Map<String, String>) {
        check(!created) { "test launch configuration must precede Application.onCreate" }
        check(launchConfig == null) { "test launch configuration is immutable" }
        launchConfig = config.toMap()
    }

    override fun startEnvironment() {
        created = true
        val launch = try {
            DebugLaunch.from(launchConfig)
        } catch (error: Exception) {
            viewModel = DemoViewModel(ProcessContext("startup/failed/p1", 1L, "startup", "failed"))
            viewModel.setStartupError(error)
            return
        }
        val model = DemoViewModel(launch.process)
        viewModel = model
        try {
            val namespace = StorageProbe.testNamespaceRelativePath(launch.process.attemptId, launch.process.scenarioId)
                ?: error("storage namespace label is invalid")
            val storeDirectory = File(noBackupFilesDir, namespace)
            val auditFile = File(
                noBackupFilesDir,
                "native-harness/${launch.process.attemptId}/${launch.process.scenarioId}/p${launch.process.launchOrdinal}/native-events.jsonl",
            )
            val audit = JSONLAuditRecorder(auditFile, launch.process.processInstanceId, launch.process.launchOrdinal)
            val clock = ControlRevisionClock()
            val hooks = DebugScenarioHooks(launch.process, audit, clock)
            val store = AuditedCredentialStore(AtomicFileCredentialStore(storeDirectory), audit, hooks::storeIOChanged)
            val ingress = DemoIngress()
            val transport = UrlConnectionRefreshTransport(launch.baseUrl, launch.runId, onCompletionCaptured = ingress::capture)
            val coordinator = SessionCoordinator(
                process = launch.process,
                store = store,
                transport = transport,
                publisher = model,
                hooks = hooks,
                audit = audit,
                cancelTransportOnCancelRefresh = launch.cancelTransportOnCancelRefresh,
            )
            this.coordinator = coordinator
            ingress.attach(coordinator)
            val control = DefaultDebugScenarioControl(
                process = launch.process,
                coordinator = coordinator,
                store = store,
                hooks = hooks,
                ingress = ingress,
                probe = { probeId ->
                    StorageProbe.read(this, launch.process.attemptId, launch.process.scenarioId, probeId, launch.process.processInstanceId)
                },
                revisionClock = clock,
            )
            this.control = control
            model.attach(coordinator)
            coordinator.start()
            control.installLaunchControls(launch.armPoint, launch.armTarget, launch.storeFault)
            coordinator.submit(AppCommand.Bootstrap)
        } catch (error: Exception) {
            model.setStartupError(error)
        }
    }

    private class DebugLaunch(
        val process: ProcessContext,
        val runId: String,
        val baseUrl: String,
        val cancelTransportOnCancelRefresh: Boolean,
        val armPoint: HookPoint?,
        val armTarget: HookTarget?,
        val storeFault: StoreFaultKind?,
    ) {
        companion object {
            private val label = Regex("[A-Za-z0-9_-]{1,64}")

            /** Manual Debug launches (no runner config) use a fresh manual namespace. */
            fun from(config: Map<String, String>?): DebugLaunch {
                if (config == null) {
                    val attemptId = "manual-${UUID.randomUUID()}"
                    return DebugLaunch(
                        ProcessContext("$attemptId/manual/p1", 1L, attemptId, "manual"),
                        attemptId, "http://10.0.2.2:8080", true, null, null, null,
                    )
                }
                val scenarioId = config.getValue("scenarioId")
                val processInstanceId = config.getValue("processInstanceId")
                val ordinal = config.getValue("launchOrdinal").toLong()
                val attemptId = processInstanceId.substringBefore('/')
                require(ordinal > 0L && label.matches(scenarioId) && label.matches(attemptId)) { "invalid launch identity" }
                require(processInstanceId == "$attemptId/$scenarioId/p$ordinal") { "processInstanceId disagrees with launch identity" }
                val baseUrl = config.getValue("baseUrl")
                val uri = URI(baseUrl)
                require(uri.scheme == "http" && uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null) {
                    "baseUrl must be a plain HTTP origin"
                }
                val cancelMode = config.getValue("cancelMode")
                require(cancelMode == "disabled" || cancelMode == "enabled") { "cancelMode is outside the frozen set" }
                val armPoint = config["armPoint"]?.let { raw -> HookPoint.entries.single { it.wireValue == raw } }
                val armTarget = config["armTarget"]?.let { raw -> HookTarget.entries.single { it.wireValue == raw } }
                val storeFault = config["storeFault"]?.let { raw -> StoreFaultKind.entries.single { it.wireValue == raw } }
                return DebugLaunch(
                    ProcessContext(processInstanceId, ordinal, attemptId, scenarioId),
                    config.getValue("runId"), baseUrl, cancelMode == "enabled", armPoint, armTarget, storeFault,
                )
            }
        }
    }
}
