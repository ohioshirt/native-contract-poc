package nativecontract.demo

import android.os.Bundle
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import nativecontract.demo.debug.DebugScenarioControlProvider
import nativecontract.demo.debug.ProcessEndAck
import nativecontract.demo.contract.HookPoint
import nativecontract.demo.contract.StoreObservation

private const val PROCESS_END_TIMEOUT_MILLIS = 15_000L

private fun isLogoutCommand(command: String): Boolean = command == "Logout" || command == "Logout(failed)"

private fun logoutButtonTag(command: String): String? = if (isLogoutCommand(command)) "logout" else null

private fun storeFaultAppliesToCommand(
    fault: String,
    command: String,
    isDelivery: Boolean,
    replayDelivery: Boolean,
): Boolean =
    (fault.startsWith("replace") && isDelivery && !replayDelivery) ||
        (fault.startsWith("clear") && isLogoutCommand(command))

private data class App11FinalQueuedReceipt(val command: String, val commandId: Long)

/** Test-only collector used to exercise the explicit harness end boundary. */
private class FakeProcessEndCollector(
    val processInstanceId: String,
) {
    val nativeEvents = mutableListOf<Map<String, Any>>()
    var ingressOpen = true
        private set
    var activeAuthCommands = 0
    var storeIoActive = false
    var hookPaused = false
    var physicalTransportPending = false
    var cancelCount = 0
        private set
    var authProjection = "Refreshing/A"
        private set
    var physicalStore = "Present(A,1)"
        private set
    private var cachedAck: ProcessEndAck? = null
    private var sealed = false

    init {
        nativeEvents += mapOf(
            "processInstanceId" to processInstanceId,
            "launchOrdinal" to 1L,
            "localSequence" to 1L,
            "kind" to "processStart",
            "initialView" to mapOf("phase" to "Refreshing", "account" to "A"),
        )
    }

    fun finish(timeoutMillis: Long): ProcessEndAck {
        cachedAck?.let { return it }
        require(timeoutMillis > 0L)
        ingressOpen = false
        if (hookPaused || activeAuthCommands != 0 || storeIoActive) {
            ingressOpen = true
            throw nativecontract.demo.debug.DebugControlException(
                nativecontract.demo.debug.DebugControlErrorCode.PROCESS_BUSY,
            )
        }
        if (physicalTransportPending) {
            cancelCount += 1
            physicalTransportPending = false
        }
        val sequence = nativeEvents.size.toLong() + 1L
        nativeEvents += mapOf(
            "processInstanceId" to processInstanceId,
            "launchOrdinal" to 1L,
            "localSequence" to sequence,
            "kind" to "processEnd",
        )
        sealed = true
        return ProcessEndAck(
            processInstanceId,
            nativecontract.demo.debug.ProcessEndEventReference(processInstanceId, sequence),
        ).also { cachedAck = it }
    }

    fun appendAfterEnd() {
        check(!sealed) { "native event stream is sealed by processEnd" }
        error("this fixture has no additional native operation")
    }
}

private class FakeProcessEndControl(
    private val collector: FakeProcessEndCollector,
    private val config: TestLaunchConfig,
) : nativecontract.demo.debug.DebugScenarioControl {
    override fun arm(
        point: HookPoint,
        target: nativecontract.demo.debug.HookTarget,
    ): nativecontract.demo.debug.ControlAck = error("not used by process-end fixture")

    override fun awaitArrival(
        point: HookPoint,
        timeoutMillis: Long,
    ): nativecontract.demo.debug.HookObservation = error("not used by process-end fixture")

    override fun release(point: HookPoint): nativecontract.demo.debug.ControlAck = error("not used by process-end fixture")
    override fun replayLastCompletion(): nativecontract.demo.debug.ControlAck = error("not used by process-end fixture")
    override fun injectStoreFault(kind: nativecontract.demo.debug.StoreFaultKind): nativecontract.demo.debug.ControlAck =
        error("not used by process-end fixture")

    override fun probeStore(): java.util.concurrent.CompletableFuture<nativecontract.demo.debug.ProbeResult> =
        java.util.concurrent.CompletableFuture.failedFuture(UnsupportedOperationException("not used by process-end fixture"))

    override fun snapshot() = nativecontract.demo.debug.ControlSnapshot(
        processInstanceId = config.processInstanceId,
        launchOrdinal = config.launchOrdinal.toLong(),
        controlRevision = 0L,
        storeIoActive = false,
        hooks = emptyList(),
    )

    override fun finishProcess(timeoutMillis: Long): ProcessEndAck = collector.finish(timeoutMillis)
}

private fun app11FinalQueuedReceipt(
    deliveryCommandId: Long,
    queuedOrder: List<String>,
): App11FinalQueuedReceipt {
    require(deliveryCommandId > 0L && queuedOrder.isNotEmpty()) { "APP-11 requires a delivery and queued commands" }
    require(queuedOrder.size.toLong() <= Long.MAX_VALUE - deliveryCommandId) { "APP-11 command ID exhausted" }
    return App11FinalQueuedReceipt(queuedOrder.last(), deliveryCommandId + queuedOrder.size.toLong())
}

private data class SelectedScenario(
    val commands: List<String>,
    val cancelMode: String,
    val receiptProbeOrder: List<Pair<String, String>>,
    val controlActions: List<JSONObject>,
    val requiredProbes: List<String>,
    val requiredRenderedViews: List<String>,
    val releaseAfterCommand: String?,
    val releaseAfterProbes: List<String>,
    val queuedOrder: List<String>,
    val barrierPoint: String?,
    val assertNoLaterReceiptBeforeRelease: Boolean,
    val declaredControls: List<String>,
    val storeFault: String?,
    val replayCount: Int,
    val effects: List<JSONObject>,
)

/** Namespaced, redacted evidence file retrieved by the host controller. */
private class InstrumentationEvidenceWriter(
    context: android.content.Context,
    private val config: TestLaunchConfig,
) {
    private val directory: File
    private var sequence = 0L

    init {
        val parts = config.processInstanceId.split('/')
        require(parts.size == 3 && parts[0].matches(Regex("[A-Za-z0-9_-]{1,64}")) &&
            parts[1].matches(Regex("[A-Za-z0-9_-]{1,64}")) && parts[2].matches(Regex("p[1-9][0-9]*"))) {
            "processInstanceId is not a safe artifact path"
        }
        directory = File(context.noBackupFilesDir, "native-harness/${parts[0]}/${parts[1]}/${parts[2]}")
        check(directory.mkdirs() || directory.isDirectory) { "cannot create instrumentation evidence directory" }
        check(!File(directory, "instrumentation-evidence.jsonl").exists()) {
            "stale instrumentation evidence already exists for this process namespace"
        }
    }

    @Synchronized
    fun record(event: String, values: Map<String, String> = emptyMap()) {
        require(event.matches(Regex("[A-Za-z][A-Za-z0-9_.-]{0,79}"))) { "invalid instrumentation event name" }
        values.forEach { (_, value) ->
            require(!Regex("(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)").containsMatchIn(value)) {
                "instrumentation evidence contains credential data"
            }
        }
        val row = JSONObject()
            .put("version", 1)
            .put("scenarioId", config.scenarioId)
            .put("processInstanceId", config.processInstanceId)
            .put("launchOrdinal", config.launchOrdinal)
            .put("sequence", ++sequence)
            .put("event", event)
            .put("values", JSONObject(values))
        FileOutputStream(File(directory, "instrumentation-evidence.jsonl"), true).use { stream ->
            stream.write((row.toString() + "\n").toByteArray(Charsets.UTF_8))
            stream.fd.sync()
        }
    }

    fun captureScreenshot(stepId: String) {
        require(stepId.matches(Regex("[A-Za-z0-9_.-]{1,160}"))) { "invalid screenshot step ID" }
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
            ?: error("Android instrumentation screenshot was unavailable")
        val directoryForScreenshots = File(directory, "screenshots")
        check(directoryForScreenshots.mkdirs() || directoryForScreenshots.isDirectory) {
            "cannot create instrumentation screenshot directory"
        }
        val file = File(directoryForScreenshots, "$stepId.png")
        check(!file.exists()) { "stale screenshot already exists for this process step" }
        FileOutputStream(file).use { stream ->
            check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, stream)) {
                "Android screenshot encoding failed"
            }
            stream.fd.sync()
        }
        bitmap.recycle()
        record("screenshot", mapOf("stepId" to stepId))
    }
}

private object FrozenScenarioInventory {
    fun load(config: TestLaunchConfig): SelectedScenario {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val scenarios = readVerifiedAsset(
            instrumentation.context.assets.open("scenarios.json").use { it.readBytes() },
            config.scenarioInventorySha256,
        )
        val controls = readVerifiedAsset(
            instrumentation.context.assets.open("control-scenarios.json").use { it.readBytes() },
            config.controlInventorySha256,
        )
        val isControl = config.scenarioId.startsWith("CTRL-")
        val rows = if (isControl) controls.optJSONArray("controls") else scenarios.optJSONArray("scenarios")
            ?: error("frozen inventory rows are missing")
        val row = findById(rows, config.scenarioId) ?: error("scenario is not present in its hashed inventory")
        val selected = selectVariant(row, config.variantId)
        val commands = selectCommands(selected, config.launchOrdinal)
        require(commands.isNotEmpty()) { "selected frozen command inventory is empty" }
        val cancelMode = selected.optString("cancelMode", row.optString("cancelMode", ""))
        require(cancelMode == config.cancelMode) { "launch cancelMode disagrees with its hashed inventory" }
        val receiptProbeOrder = parseReceiptProbeOrder(selected, row)
        val controlActions = parseControlActions(selected, row)
        require(commands.first() == "Bootstrap") { "every frozen launch must begin with Bootstrap" }
        val requiredProbes = selectStringArray(selected, row, "requiredProbes")
        val requiredViews = selectStringArray(selected, row, "requiredRenderedViews")
        val releaseAfterCommand = selected.optString("releaseAfterCommand", row.optString("releaseAfterCommand", ""))
            .takeIf(String::isNotBlank)
        val releaseAfterProbes = selectStringArray(selected, row, "releaseAfterProbes")
        val queuedOrder = selectStringArray(selected, row, "queuedOrder")
        val barrierPoint = selected.optString("barrier", row.optString("barrier", "")).takeIf(String::isNotBlank)
        val assertNoLaterReceipt = selected.optBoolean(
            "assertNoLaterReceiptBeforeRelease",
            row.optBoolean("assertNoLaterReceiptBeforeRelease", false),
        )
        val declaredControls = selectStringArray(selected, row, "controls")
        val storeFault = selected.optString("fault", "").takeIf(String::isNotBlank)
        val effects = selectObjectArray(selected, row, "effects")
        val replayCount = selected.optInt("replayCount", row.optInt("replayCount", 0))
        require(replayCount >= 0) { "replayCount must not be negative" }
        require(declaredControls.all {
            it in setOf("arm", "awaitArrival", "release", "snapshot", "replayLastCompletion", "injectStoreFault", "probeStore", "recreateView")
        }) { "frozen controls contains an unsupported operation" }
        require((replayCount > 0) == ("replayLastCompletion" in declaredControls)) {
            "replayCount and declared replay control disagree"
        }
        return SelectedScenario(
            commands,
            cancelMode,
            receiptProbeOrder,
            controlActions,
            requiredProbes,
            requiredViews,
            releaseAfterCommand,
            releaseAfterProbes,
            queuedOrder,
            barrierPoint,
            assertNoLaterReceipt,
            declaredControls,
            storeFault,
            replayCount,
            effects,
        )
    }

    private fun readVerifiedAsset(bytes: ByteArray, expectedSha256: String): JSONObject {
        val actual = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {
            "%02x".format(it.toInt() and 0xff)
        }
        require(actual == expectedSha256) { "packaged scenario inventory digest differs from controller digest" }
        return JSONObject(String(bytes, Charsets.UTF_8))
    }

    private fun findById(rows: JSONArray, id: String): JSONObject? {
        for (index in 0 until rows.length()) {
            val row = rows.optJSONObject(index) ?: continue
            if (row.optString("id") == id) return row
        }
        return null
    }

    private fun selectVariant(row: JSONObject, variantId: String?): JSONObject {
        val variants = row.optJSONArray("variants")
        if (variants == null) {
            require(variantId == null) { "variantId was supplied for a non-variant scenario" }
            return row
        }
        require(!variantId.isNullOrBlank()) { "variantId is required by the frozen scenario inventory" }
        return findById(variants, variantId) ?: error("variantId is not present in the hashed inventory")
    }

    private fun selectCommands(row: JSONObject, launchOrdinal: Int): List<String> {
        val launches = row.optJSONArray("launches")
        val source = if (launches == null) row else {
            var selected: JSONObject? = null
            for (index in 0 until launches.length()) {
                val launch = launches.optJSONObject(index) ?: continue
                if (launch.optInt("ordinal", -1) == launchOrdinal) selected = launch
            }
            selected ?: error("launchOrdinal is not present in the selected frozen inventory")
        }
        val values = source.optJSONArray("commands") ?: error("selected inventory has no commands")
        return (0 until values.length()).map { index ->
            values.optString(index).takeIf(String::isNotBlank) ?: error("frozen command is not a nonempty string")
        }
    }

    private fun parseReceiptProbeOrder(selected: JSONObject, base: JSONObject): List<Pair<String, String>> {
        val order = selected.optJSONArray("receiptProbeOrder") ?: base.optJSONArray("receiptProbeOrder") ?: return emptyList()
        return (0 until order.length()).map { index ->
            val pair = order.optJSONArray(index) ?: error("receiptProbeOrder entry is malformed")
            require(pair.length() == 2) { "receiptProbeOrder entry must contain command and probe step" }
            pair.getString(0) to pair.getString(1)
        }
    }

    private fun parseControlActions(selected: JSONObject, base: JSONObject): List<JSONObject> {
        val actions = selected.optJSONArray("controlActions") ?: base.optJSONArray("controlActions") ?: return emptyList()
        return (0 until actions.length()).map { index ->
            actions.optJSONObject(index) ?: error("controlActions entry is malformed")
        }
    }

    private fun selectStringArray(selected: JSONObject, base: JSONObject, key: String): List<String> {
        val values = selected.optJSONArray(key) ?: base.optJSONArray(key) ?: return emptyList()
        return (0 until values.length()).map { index ->
            values.optString(index).takeIf(String::isNotBlank) ?: error("$key contains an invalid value")
        }
    }

    private fun selectObjectArray(selected: JSONObject, base: JSONObject, key: String): List<JSONObject> {
        val values = selected.optJSONArray(key) ?: base.optJSONArray(key) ?: return emptyList()
        return (0 until values.length()).map { index ->
            values.optJSONObject(index) ?: error("$key contains a malformed object")
        }
    }
}

@RunWith(AndroidJUnit4::class)
class ScenarioInstrumentedTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()
    private lateinit var evidence: InstrumentationEvidenceWriter

    @Test
    fun app11ReceiptWaitMustAcceptLatestRefAfterFifoCommandsCompleteBetweenPolls() {
        val processId = "attempt-11/APP-11/p1"
        val previous = nativecontract.demo.debug.CommandReference(processId, 3L)
        val finalReceipt = app11FinalQueuedReceipt(4L, listOf("Logout", "Login(B)"))
        val snapshots = listOf(
            controlSnapshot(processId, previous),
            controlSnapshot(processId, nativecontract.demo.debug.CommandReference(processId, 6L)),
        )
        val control = SnapshotSequenceControl(snapshots)

        assertEquals(App11FinalQueuedReceipt("Login(B)", 6L), finalReceipt)
        val completed = awaitProcessedHighWater(
            finalReceipt.commandId,
            previous,
            processId,
            control,
        )
        assertEquals(6L, completed.id)
        assertEquals(2, control.snapshotsRead)
    }

    @Test
    fun app11HighWaterRejectsUnexpectedCommandBeyondFrozenQueue() {
        val processId = "attempt-11/APP-11/p1"
        val previous = nativecontract.demo.debug.CommandReference(processId, 3L)
        val finalReceipt = app11FinalQueuedReceipt(4L, listOf("Logout", "Login(B)"))
        val control = SnapshotSequenceControl(
            listOf(
                controlSnapshot(processId, previous),
                controlSnapshot(processId, nativecontract.demo.debug.CommandReference(processId, 7L)),
            ),
        )

        val result = runCatching {
            awaitProcessedHighWater(finalReceipt.commandId, previous, processId, control)
        }

        assertTrue(result.exceptionOrNull()?.message?.contains("unexpected intervening processed command 7") == true)
    }

    @Test
    fun processEndHarnessAcknowledgesOneTerminalCollectorRowAfterFinalObservations() {
        val attempt = "end-test-${System.nanoTime()}"
        val processId = "$attempt/APP-07/p1"
        val config = TestLaunchConfig(
            scenarioId = "APP-07",
            runId = "run-end-test",
            processInstanceId = processId,
            launchOrdinal = 1,
            baseUrl = "http://127.0.0.1",
            scenarioPhase = "single",
            cancelMode = "disabled",
            scenarioInventorySha256 = "a".repeat(64),
            controlInventorySha256 = "b".repeat(64),
            variantId = null,
            armPoint = null,
            armTarget = null,
            storeFault = null,
        )
        val collector = FakeProcessEndCollector(processId).apply { physicalTransportPending = true }
        val control = FakeProcessEndControl(collector, config)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val evidence = InstrumentationEvidenceWriter(instrumentation.targetContext, config)
        evidence.record("finalProbeCaptured")
        evidence.record("finalRenderedViewCaptured")

        val ack = finishProcessAndReport(config, control, evidence)
        val retry = control.finishProcess(PROCESS_END_TIMEOUT_MILLIS)
        val ends = collector.nativeEvents.filter { it["kind"] == "processEnd" }
        val evidencePath = File(
            instrumentation.targetContext.noBackupFilesDir,
            "native-harness/$attempt/APP-07/p1/instrumentation-evidence.jsonl",
        )
        val rows = evidencePath.readLines().map(::JSONObject)
        val names = rows.map { it.optString("event") }

        assertEquals(ack, retry)
        assertEquals(1, ends.size)
        assertEquals(ack.eventRef.localSequence, ends.single()["localSequence"])
        assertFalse(collector.ingressOpen)
        assertEquals(1, collector.cancelCount)
        assertEquals(listOf("processStart", "processEnd"), collector.nativeEvents.map { it["kind"] })
        assertEquals("Refreshing/A", collector.authProjection)
        assertEquals("Present(A,1)", collector.physicalStore)
        assertTrue(names.indexOf("finalProbeCaptured") < names.indexOf("processEndAcknowledged"))
        assertTrue(names.indexOf("finalRenderedViewCaptured") < names.indexOf("processEndAcknowledged"))
        assertTrue(names.lastIndexOf("controllerStatus") > names.indexOf("processEndAcknowledged"))
        assertTrue(rows.last().getJSONObject("values").optString("phase") == "end")
        assertTrue(runCatching { collector.appendAfterEnd() }.exceptionOrNull()?.message?.contains("sealed") == true)
    }

    @Test
    fun processEndRejectsPausedHookWithoutWritingTerminalRow() {
        val processId = "end-test-paused/APP-11/p1"
        val collector = FakeProcessEndCollector(processId).apply { hookPaused = true }
        val result = runCatching { collector.finish(PROCESS_END_TIMEOUT_MILLIS) }

        assertTrue(result.exceptionOrNull() is nativecontract.demo.debug.DebugControlException)
        assertEquals(nativecontract.demo.debug.DebugControlErrorCode.PROCESS_BUSY,
            (result.exceptionOrNull() as nativecontract.demo.debug.DebugControlException).code)
        assertEquals(0, collector.nativeEvents.count { it["kind"] == "processEnd" })
        assertTrue(collector.ingressOpen)
        assertEquals(0, collector.cancelCount)
    }

    private fun controlSnapshot(
        processId: String,
        processed: nativecontract.demo.debug.CommandReference,
    ) = nativecontract.demo.debug.ControlSnapshot(
        processInstanceId = processId,
        launchOrdinal = 1L,
        controlRevision = processed.id,
        lastProcessedCommandRef = processed,
        storeIoActive = false,
        hooks = emptyList(),
    )

    private class SnapshotSequenceControl(
        snapshots: List<nativecontract.demo.debug.ControlSnapshot>,
    ) : nativecontract.demo.debug.DebugScenarioControl {
        private val remaining = ArrayDeque(snapshots)
        private var last: nativecontract.demo.debug.ControlSnapshot? = null
        var snapshotsRead: Int = 0
            private set

        override fun arm(
            point: HookPoint,
            target: nativecontract.demo.debug.HookTarget,
        ): nativecontract.demo.debug.ControlAck = error("not used by receipt wait regression")

        override fun awaitArrival(
            point: HookPoint,
            timeoutMillis: Long,
        ): nativecontract.demo.debug.HookObservation = error("not used by receipt wait regression")

        override fun release(
            point: HookPoint,
        ): nativecontract.demo.debug.ControlAck = error("not used by receipt wait regression")

        override fun replayLastCompletion(): nativecontract.demo.debug.ControlAck =
            error("not used by receipt wait regression")

        override fun injectStoreFault(
            kind: nativecontract.demo.debug.StoreFaultKind,
        ): nativecontract.demo.debug.ControlAck = error("not used by receipt wait regression")

        override fun probeStore(): java.util.concurrent.CompletableFuture<nativecontract.demo.debug.ProbeResult> =
            error("not used by receipt wait regression")

        override fun snapshot(): nativecontract.demo.debug.ControlSnapshot {
            snapshotsRead += 1
            if (remaining.isNotEmpty()) last = remaining.removeFirst()
            return last ?: error("no process snapshot was supplied")
        }

        override fun finishProcess(timeoutMillis: Long): ProcessEndAck = error("not used by receipt wait regression")
    }

    @Test
    fun failedLogoutAliasRunsLogoutButtonWithItsDeclaredClearFault() {
        assertTrue(isLogoutCommand("Logout(failed)"))
        assertEquals("logout", logoutButtonTag("Logout(failed)"))
        assertTrue(storeFaultAppliesToCommand("clearBefore", "Logout(failed)", false, false))
        assertTrue(storeFaultAppliesToCommand("clearAfterBeforeVerify", "Logout(failed)", false, false))
    }

    @Test
    fun launchConfigRequiresExplicitCancellationMode() {
        val arguments = Bundle().apply {
            putString("scenarioId", "APP-01")
            putString("runId", "attempt-01")
            putString("processInstanceId", "attempt-01/APP-01/p1")
            putString("launchOrdinal", "1")
            putString("baseUrl", "http://10.0.2.2:43217")
            putString("scenarioPhase", "single")
            putString("scenarioInventorySha256", "a".repeat(64))
            putString("controlInventorySha256", "b".repeat(64))
        }

        assertTrue(runCatching { TestLaunchConfig.from(arguments) }.isFailure)
    }

    @Test
    fun launchConfigRejectsUnsupportedCancellationMode() {
        val arguments = Bundle().apply {
            putString("scenarioId", "APP-01")
            putString("runId", "attempt-01")
            putString("processInstanceId", "attempt-01/APP-01/p1")
            putString("launchOrdinal", "1")
            putString("baseUrl", "http://10.0.2.2:43217")
            putString("scenarioPhase", "single")
            putString("scenarioInventorySha256", "a".repeat(64))
            putString("controlInventorySha256", "b".repeat(64))
            putString("cancelMode", "platformDefault")
        }

        assertTrue(runCatching { TestLaunchConfig.from(arguments) }.isFailure)
    }

    @Test
    fun androidScaffoldStatusRelaySmoke() {
        // Plumbing-only: the test launches the scaffold, records a screenshot, and
        // emits an instrumentation status. It does not exercise auth or storage.
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val config = TestLaunchConfig.from(InstrumentationRegistry.getArguments())
        FrozenScenarioInventory.load(config)
        composeRule.onNodeWithTag("session-state").assertExists()

        val smokeEvidence = InstrumentationEvidenceWriter(instrumentation.targetContext, config)
        smokeEvidence.captureScreenshot("scaffold-plumbing-smoke")
        smokeEvidence.record("scaffoldStatusRelaySmoke", mapOf("activityVisible" to "true"))
        instrumentation.sendStatus(
            2,
            Bundle().apply {
                putString("scenarioId", config.scenarioId)
                putString("processInstanceId", config.processInstanceId)
                putString("checkpointName", "androidRelaySmoke")
                putString("phase", "plumbingSmoke")
                putString("activityVisible", "true")
                putString("screenshotStepId", "scaffold-plumbing-smoke")
            },
        )
    }

    @Test
    fun runScenario() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val config = TestLaunchConfig.from(InstrumentationRegistry.getArguments())
        val selection = FrozenScenarioInventory.load(config)
        evidence = InstrumentationEvidenceWriter(instrumentation.targetContext, config)
        val application = instrumentation.targetContext.applicationContext as? DebugScenarioControlProvider
            ?: error("DebugDemoApplication must expose the frozen DebugScenarioControl")
        val control = application.debugScenarioControl
        val initial = control.snapshot()
        assertEquals(config.processInstanceId, initial.processInstanceId)
        assertEquals(config.launchOrdinal.toLong(), initial.launchOrdinal)
        validateControlActions(selection)
        assertEquals(config.cancelMode, selection.cancelMode)

        composeRule.onNodeWithTag("session-state").assertExists()
        var lastProcessed: nativecontract.demo.debug.CommandReference
        val releasedHooks = mutableSetOf<String>()
        val processedCommandReferences = mutableMapOf<String, nativecontract.demo.debug.CommandReference>()
        val capturedProbes = mutableSetOf<String>()
        if (isApp12Resume(config)) {
            awaitEnqueued(1L, config.processInstanceId, control)
            val arrival = control.awaitArrival(HookPoint.BEFORE_BOOTSTRAP_CLEAR, 60_000)
            check(arrival.phase.wireValue == "arrived") { "Bootstrap hook did not arrive" }
            sendControllerStatus(config, "hookArrived.beforeBootstrapClear", "hookArrived", control, evidence)
            requestHostProbe(config, "bootstrapStoreProbed", control, evidence)
            // The controller maps bootstrapStoreProbed to the one frozen pre-clear step;
            // record it so the final sweep does not capture that step ID a second time.
            capturedProbes += selection.requiredProbes.single { it.contains("before-bootstrap-clear") }
            val ack = control.release(HookPoint.BEFORE_BOOTSTRAP_CLEAR)
            releasedHooks += HookPoint.BEFORE_BOOTSTRAP_CLEAR.wireValue
            evidence.record("hookReleased", mapOf("point" to HookPoint.BEFORE_BOOTSTRAP_CLEAR.wireValue, "actionId" to ack.actionId.toString()))
            sendControllerStatus(config, "hookReleased.beforeBootstrapClear", "hookReleased", control, evidence)
            lastProcessed = awaitProcessed(1L, null, config.processInstanceId, control)
        } else {
            // Bootstrap is submitted by the Debug Application before the Activity
            // appears; accept its existing receipt instead of waiting for a second one.
            awaitEnqueued(1L, config.processInstanceId, control)
            lastProcessed = awaitProcessed(1L, null, config.processInstanceId, control)
        }
        processedCommandReferences["Bootstrap"] = lastProcessed

        selection.controlActions.filter { it.optString("action") == "arm" }
            .forEach { applyControlAction(it, control, evidence) }
        if (selection.barrierPoint != null) {
            val point = HookPoint.entries.single { it.wireValue == selection.barrierPoint }
            val ack = control.arm(point, nativecontract.demo.debug.HookTarget.NEXT_DELIVERY)
            evidence.record("hookArmed", mapOf("point" to point.wireValue, "target" to "nextDelivery", "actionId" to ack.actionId.toString()))
        }

        val awaitingAction = selection.controlActions.firstOrNull { it.optString("action") == "awaitArrival" }
        val skippedCommandIndexes = mutableSetOf<Int>()
        var faultInjected = false
        var replayInvocations = 0
        for ((commandIndex, command) in selection.commands.withIndex()) {
            if (commandIndex in skippedCommandIndexes) continue
            if (command == "Bootstrap") {
                check(lastProcessed.id == 1L) { "Bootstrap receipt was not process-local command 1" }
                continue
            }
            val previous = lastProcessed
            require(previous.id < Long.MAX_VALUE) { "command id exhausted before frozen sequence completed" }
            val nextCommandId = previous.id + 1L
            val isDelivery = command.startsWith("Deliver(")
            val replayDelivery = command.startsWith("Deliver(replay,")
            var replayActionId: Long? = null
            val targetedFaultAction = selection.controlActions.firstOrNull {
                it.optString("action") == "injectStoreFault" && it.optString("command") == command
            }
            val selectedFault = targetedFaultAction?.optString("fault")?.takeIf { it.isNotBlank() }
                ?: selection.storeFault ?: config.storeFault
            val faultAppliesNow = selectedFault != null && !faultInjected &&
                (targetedFaultAction != null || storeFaultAppliesToCommand(selectedFault, command, isDelivery, replayDelivery))
            if (faultAppliesNow) {
                require(selectedFault in setOf("replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"))
                require(storeFaultAppliesToCommand(selectedFault, command, isDelivery, replayDelivery)) {
                    "store fault target command does not perform the matching operation"
                }
                injectFault(selectedFault, control, evidence)
                faultInjected = true
            }
            if (command == "RetryCleanup" && faultInjected) {
                val failedLogoutProbe = selection.requiredProbes.filter { it.contains("after-failed-logout") }
                require(failedLogoutProbe.isNotEmpty() && failedLogoutProbe.all { it in capturedProbes }) {
                    "RetryCleanup cannot start before the frozen failed-Logout probe"
                }
                injectFault("none", control, evidence)
                faultInjected = false
            }
            if (replayDelivery) {
                require("replayLastCompletion" in selection.declaredControls)
                val ack = control.replayLastCompletion()
                require(ack.actionId > 0 && ack.controlRevision > 0)
                require(ack.status == nativecontract.demo.debug.ControlAckStatus.SCHEDULED)
                replayInvocations += 1
                replayActionId = ack.actionId
                evidence.record("replayScheduled", mapOf("actionId" to ack.actionId.toString(), "deliveryCommandId" to nextCommandId.toString()))
            }
            if (isDelivery && selection.barrierPoint != null && selection.queuedOrder.isNotEmpty()) {
                sendControllerStatus(config, "delivery.$nextCommandId", "releaseRequested", control, evidence, command)
                awaitEnqueued(nextCommandId, config.processInstanceId, control)
                val point = HookPoint.entries.single { it.wireValue == selection.barrierPoint }
                val arrival = control.awaitArrival(point, 60_000)
                check(arrival.phase.wireValue == "arrived") { "queue barrier ${point.wireValue} did not arrive" }
                sendControllerStatus(config, "hookArrived.${point.wireValue}", "hookArrived", control, evidence)
                evidence.record(
                    "hookArrived",
                    mapOf("point" to point.wireValue, "commandId" to (arrival.arrivalCommandRef?.id?.toString() ?: "")),
                )
                val queuedReferences = mutableListOf<Pair<String, nativecontract.demo.debug.CommandReference>>()
                selection.queuedOrder.forEachIndexed { offset, queuedCommand ->
                    val queuedIndex = commandIndex + offset + 1
                    require(selection.commands.getOrNull(queuedIndex) == queuedCommand) {
                        "queuedOrder disagrees with the next frozen command positions"
                    }
                    val queuedId = nextCommandId + offset + 1L
                    tapCommand(queuedCommand)
                    awaitEnqueued(queuedId, config.processInstanceId, control)
                    val enqueued = control.snapshot().lastEnqueuedCommandRef
                        ?: error("queued command has no process reference")
                    queuedReferences += queuedCommand to enqueued
                    skippedCommandIndexes += queuedIndex
                    val currentProcessed = control.snapshot().lastProcessedCommandRef
                    if (selection.assertNoLaterReceiptBeforeRelease) {
                        check(currentProcessed?.id == previous.id) {
                            "paused consumer processed a later receipt before control release"
                        }
                    }
                }
                if (selection.assertNoLaterReceiptBeforeRelease) {
                    check(control.snapshot().lastProcessedCommandRef?.id == previous.id) {
                        "paused consumer advanced before hook release"
                    }
                }
                val releaseAck = control.release(point)
                releasedHooks += point.wireValue
                evidence.record("hookReleased", mapOf("point" to point.wireValue, "actionId" to releaseAck.actionId.toString()))
                sendControllerStatus(config, "hookReleased.${point.wireValue}", "hookReleased", control, evidence)
                val finalReceipt = app11FinalQueuedReceipt(nextCommandId, selection.queuedOrder)
                lastProcessed = awaitProcessedHighWater(
                    finalReceipt.commandId,
                    previous,
                    config.processInstanceId,
                    control,
                )
                processedCommandReferences[finalReceipt.command] = lastProcessed
                sendControllerStatus(
                    config,
                    "receipt.${finalReceipt.commandId}",
                    "receiptObserved",
                    control,
                    evidence,
                    finalReceipt.command,
                )
                continue
            }
            when (command) {
                "Login(A)" -> tap("login-A")
                "Login(A0)" -> tap("login-A")
                "Login(B)" -> tap("login-B")
                "Expire" -> tap("expire")
                "Logout", "Logout(failed)" -> tap(logoutButtonTag(command)!!)
                "RetryCleanup" -> tap("retry-cleanup")
                "CancelRefresh" -> tap("cancel-refresh")
                "Observe" -> error("Observe is a FIFO app command; no current frozen inventory declares it")
                else -> {
                    if (!isDelivery) error("unsupported frozen command: $command")
                    if (!replayDelivery) {
                        sendControllerStatus(config, "delivery.$nextCommandId", "releaseRequested", control, evidence, command)
                    }
                }
            }
            awaitEnqueued(expectedId = nextCommandId, processInstanceId = config.processInstanceId, control = control)
            if (replayDelivery) {
                val snapshot = control.snapshot()
                require(snapshot.lastActionId == replayActionId && snapshot.lastActionStatus == nativecontract.demo.debug.ControlAckStatus.SCHEDULED) {
                    "replay acknowledgement is not the current observed Debug action"
                }
                sendControllerStatus(
                    config,
                    "replay.$nextCommandId",
                    "replayScheduled",
                    control,
                    evidence,
                    command,
                    replayActionId = replayActionId,
                )
            }

            val barrierAction = awaitingAction?.takeIf { it.optString("point").isNotEmpty() }
            val deliveryBarrierAction = barrierAction.takeIf { isDelivery }
            val deliveryAtHook = deliveryBarrierAction != null
            if (deliveryBarrierAction != null) {
                awaitHook(config, deliveryBarrierAction, control, evidence)
                val barrierProbe = selection.requiredProbes.firstOrNull { it !in capturedProbes && !it.contains("final") }
                if (barrierProbe != null) {
                    requestHostProbe(config, "storeProbe.$barrierProbe", control, evidence)
                    capturedProbes += barrierProbe
                }
                val barrierViews = selection.requiredRenderedViews.filter { it.contains("rendered-a1") }
                if (barrierViews.isNotEmpty()) captureRenderedView(config, barrierViews, control, evidence)
                releaseHookFor(config, deliveryBarrierAction, selection.controlActions, control, evidence)
                releasedHooks += deliveryBarrierAction.getString("point")
            }

            lastProcessed = awaitProcessed(nextCommandId, previous, config.processInstanceId, control)
            processedCommandReferences[command] = lastProcessed
            sendControllerStatus(config, "receipt.$nextCommandId", "receiptObserved", control, evidence, command)

            selection.receiptProbeOrder.filter { it.first == command }.forEach { (_, stepId) ->
                requestHostProbe(config, "storeProbe.$stepId", control, evidence)
                capturedProbes += stepId
            }
            if (isLogoutCommand(command)) {
                selection.requiredProbes.filter { it.contains("after-failed-logout") && it !in capturedProbes }.forEach { probeId ->
                    requestHostProbe(config, "storeProbe.$probeId", control, evidence)
                    capturedProbes += probeId
                }
            }
            if (command == "RetryCleanup") {
                selection.requiredProbes.filter { it.contains("after-retry") && it !in capturedProbes }.forEach { probeId ->
                    requestHostProbe(config, "storeProbe.$probeId", control, evidence)
                    capturedProbes += probeId
                }
            }
            if (selection.requiredRenderedViews.any { renderStepMatches(it, command) }) {
                captureRenderedView(config, selection.requiredRenderedViews.filter { renderStepMatches(it, command) }, control, evidence)
            }
            val releaseAfter = selection.releaseAfterCommand
            if (releaseAfter == command) {
                check(selection.releaseAfterProbes.all { it in capturedProbes }) {
                    "server release reached before its frozen immediate probes"
                }
                sendControllerStatus(config, "serverRelease.$nextCommandId", "releaseReady", control, evidence, command)
            }

            if (!deliveryAtHook) {
                if (barrierAction != null && hookArrivalCommand(barrierAction) == command) {
                    awaitHook(config, barrierAction, control, evidence)
                }
            }
        }

        require(replayInvocations == selection.replayCount) {
            "observed replay invocation count $replayInvocations disagrees with frozen count ${selection.replayCount}"
        }
        if ("recreateView" in selection.declaredControls) {
            val providerBefore = application.debugScenarioControl
            val snapshotBefore = control.snapshot()
            composeRule.activityRule.scenario.recreate()
            composeRule.waitForIdle()
            val providerAfter = (instrumentation.targetContext.applicationContext as DebugScenarioControlProvider).debugScenarioControl
            val snapshotAfter = providerAfter.snapshot()
            check(providerBefore === providerAfter) { "Activity recreation replaced the application-owned coordinator" }
            check(snapshotAfter.processInstanceId == snapshotBefore.processInstanceId &&
                snapshotAfter.lastProcessedCommandRef == snapshotBefore.lastProcessedCommandRef) {
                "Activity recreation reset process identity or command progress"
            }
            evidence.record("activityRecreated", mapOf("lastProcessedCommandId" to (snapshotAfter.lastProcessedCommandRef?.id?.toString() ?: "")))
        }

        selection.controlActions.forEach { action ->
            when (action.optString("action")) {
                "release" -> if (action.optString("point") !in releasedHooks) {
                    releaseHookFor(config, action, selection.controlActions, control, evidence)
                    releasedHooks += action.optString("point")
                }
                "awaitDetachedEffect" -> {
                    val effectId = action.getString("effectId")
                    val effect = selection.effects.single { it.optString("effectId") == effectId }
                    val origin = effect.getJSONObject("originCommandRef")
                    require(origin.optInt("launchOrdinal", -1) == config.launchOrdinal)
                    val originCommand = origin.getString("command")
                    val originRef = processedCommandReferences[originCommand]
                        ?: error("detached effect origin command has no observed receipt")
                    require(originRef.processInstanceId == config.processInstanceId)
                    val checkpoint = "detachedEffectAwaited.$effectId"
                    sendControllerStatus(
                        config,
                        checkpoint,
                        "effectAwaitRequested",
                        control,
                        evidence,
                        effectId = effectId,
                        effectOriginCommandRef = JSONObject()
                            .put("processInstanceId", originRef.processInstanceId)
                            .put("id", originRef.id)
                            .toString(),
                    )
                    waitForHostCheckpoint(config, checkpoint)
                    evidence.record("detachedEffectAwaited", mapOf(
                        "effectId" to effectId,
                        "originCommandId" to originRef.id.toString(),
                    ))
                }
            }
        }
        selection.controlActions.filter { it.optString("action") == "replayLastCompletion" }.forEach {
            val ack = control.replayLastCompletion()
            require(ack.actionId > 0 && ack.controlRevision > 0)
            evidence.record("replayScheduled", mapOf("actionId" to ack.actionId.toString()))
        }
        // A multi-launch seed process (APP-12 p1) records no scenario-level probe or
        // final view; those step IDs belong to the resumed launch and must be unique.
        if (config.scenarioPhase != "seed") {
            selection.requiredProbes.filter { it !in capturedProbes }.forEach { probeId ->
                requestHostProbe(config, "storeProbe.$probeId", control, evidence)
                capturedProbes += probeId
            }
            if (selection.requiredRenderedViews.any { it.contains("final") }) {
                captureRenderedView(config, selection.requiredRenderedViews.filter { it.contains("final") }, control, evidence)
            }
        }

        if (config.scenarioId.startsWith("APP-12-") && config.launchOrdinal == 1) {
            sendControllerStatus(config, "restartCheckpoint", "restartCheckpoint", control, evidence)
        }
        finishProcessAndReport(config, control, evidence)
    }

    @Test
    fun storageProbeDecoderNeverReturnsSyntheticTokenText() {
        val blob = """{"account":"A","version":7,"accessToken":"demo-A-v7","refreshToken":"demo-A-v7"}""".encodeToByteArray()
        val observation = nativecontract.demo.debug.StorageProbe.redactCredentialBlob(blob)
        assertTrue(observation is StoreObservation.Present)
        val rendered = observation.toString()
        assertTrue("demo-A-v7" !in rendered)
        assertTrue("accessToken" !in rendered)
    }

    private fun tap(tag: String) {
        composeRule.onNodeWithTag(tag).assertExists().performClick()
    }

    private fun tapCommand(command: String) {
        val tag = when (command) {
            "Login(A)", "Login(A0)" -> "login-A"
            "Login(B)" -> "login-B"
            "Expire" -> "expire"
            "Logout", "Logout(failed)" -> "logout"
            "RetryCleanup" -> "retry-cleanup"
            "CancelRefresh" -> "cancel-refresh"
            else -> error("queued order contains unsupported app command: $command")
        }
        tap(tag)
    }

    private fun awaitProcessed(
        expectedId: Long,
        previous: nativecontract.demo.debug.CommandReference?,
        processInstanceId: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
    ): nativecontract.demo.debug.CommandReference {
        var found: nativecontract.demo.debug.CommandReference? = null
        composeRule.waitUntil(60_000) {
            val current = control.snapshot().lastProcessedCommandRef
            if (current != null) {
                if (current.processInstanceId != processInstanceId) error("processed reference belongs to another process namespace")
                if (current.id > expectedId) error("unexpected intervening processed command ${current.id}; expected $expectedId")
                if (current.id == expectedId && current != previous) found = current
            }
            found != null
        }
        val receipt = found ?: error("native receipt for process-local command $expectedId was not observed")
        if (previous != null) require(receipt.processInstanceId == previous.processInstanceId)
        return receipt
    }

    private fun awaitProcessedHighWater(
        expectedFinalId: Long,
        previous: nativecontract.demo.debug.CommandReference?,
        processInstanceId: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
    ): nativecontract.demo.debug.CommandReference {
        var found: nativecontract.demo.debug.CommandReference? = null
        composeRule.waitUntil(60_000) {
            val current = control.snapshot().lastProcessedCommandRef
            if (current != null) {
                if (current.processInstanceId != processInstanceId) error("processed reference belongs to another process namespace")
                if (current.id > expectedFinalId) {
                    error("unexpected intervening processed command ${current.id}; expected final FIFO command $expectedFinalId")
                }
                if (current.id == expectedFinalId && current != previous) found = current
            }
            found != null
        }
        return found ?: error("final FIFO command $expectedFinalId was not processed")
    }

    private fun awaitEnqueued(
        expectedId: Long,
        processInstanceId: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
    ) {
        composeRule.waitUntil(60_000) {
            val current = control.snapshot().lastEnqueuedCommandRef ?: return@waitUntil false
            if (current.processInstanceId != processInstanceId) error("enqueued reference belongs to another process namespace")
            if (current.id > expectedId) error("unexpected intervening enqueued command ${current.id}; expected $expectedId")
            current.id == expectedId
        }
    }

    private fun requestHostProbe(
        config: TestLaunchConfig,
        checkpointName: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        val snapshot = control.snapshot()
        check(!snapshot.storeIoActive) { "host probe requested while native store I/O was active" }
        val localProbe = control.probeStore().get(10, java.util.concurrent.TimeUnit.SECONDS)
        check(localProbe.processInstanceId == config.processInstanceId) { "supplemental app probe crossed process identity" }
        sendControllerStatus(
            config,
            checkpointName,
            "probeRequested",
            control,
            evidence,
            redactedProbe = JSONObject(localProbe.observation.toRedactedFields()).toString()
        )
        waitForHostCheckpoint(config, checkpointName)
    }

    private fun waitForHostCheckpoint(config: TestLaunchConfig, checkpointName: String) {
        val query = listOf(
            "runId" to config.runId,
            "processInstanceId" to config.processInstanceId,
            "name" to checkpointName,
        ).joinToString("&") { (key, value) ->
            "${encode(key)}=${encode(value)}"
        }
        val deadlineNanos = System.nanoTime() + 60_000_000_000L
        while (System.nanoTime() < deadlineNanos) {
            val connection = URL("${config.baseUrl.trimEnd('/')}/v1/checkpoints?$query").openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 5_000
                connection.readTimeout = 5_000
                connection.requestMethod = "GET"
                if (connection.responseCode == 200 && JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).optBoolean("ready")) {
                    return
                }
            } finally {
                connection.disconnect()
            }
            Thread.sleep(250)
        }
        error("host did not publish independent probe checkpoint $checkpointName")
    }

    private fun sendControllerStatus(
        config: TestLaunchConfig,
        checkpointName: String,
        phase: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
        command: String? = null,
        redactedProbe: String? = null,
        renderedState: String? = null,
        effectId: String? = null,
        effectOriginCommandRef: String? = null,
        replayActionId: Long? = null,
        processEndAck: ProcessEndAck? = null,
        snapshotOverride: nativecontract.demo.debug.ControlSnapshot? = null,
    ) {
        val snapshot = snapshotOverride ?: control.snapshot()
        val fields = buildMap {
            command?.let { put("command", it) }
            redactedProbe?.let { put("redactedProbe", it) }
            renderedState?.let { put("renderedState", it) }
            effectId?.let { put("effectId", it) }
            effectOriginCommandRef?.let { put("effectOriginCommandRef", it) }
            replayActionId?.let { put("replayActionId", it.toString()) }
            processEndAck?.let { ack ->
                require(ack.processInstanceId == config.processInstanceId)
                require(ack.eventRef.processInstanceId == config.processInstanceId)
                put("processEndAckJSON", JSONObject()
                    .put("processInstanceId", ack.processInstanceId)
                    .put("eventRef", JSONObject()
                        .put("processInstanceId", ack.eventRef.processInstanceId)
                        .put("localSequence", ack.eventRef.localSequence))
                    .toString())
            }
            snapshot.lastEnqueuedCommandRef?.let { put("lastEnqueuedCommandId", it.id.toString()) }
            snapshot.lastProcessedCommandRef?.let { put("lastProcessedCommandId", it.id.toString()) }
            snapshot.lastProcessedCommandRef?.let { put("lastProcessedProcessInstanceId", it.processInstanceId) }
            snapshot.hooks.lastOrNull()?.let { hook ->
                put("hookPoint", hook.point.wireValue)
                put("hookPhase", hook.phase.wireValue)
                put("hookTarget", hook.target.wireValue)
                put("hookArmSequence", hook.armSequence.toString())
                hook.arrivalCommandRef?.let { put("hookCommandId", it.id.toString()) }
                put("authMailboxPaused", (hook.phase != nativecontract.demo.debug.HookPhase.ARMED).toString())
                if (hook.point == HookPoint.BEFORE_BOOTSTRAP_CLEAR) {
                    put("bootstrapReceiptObserved", "false")
                }
            }
        }
        evidence.record("controllerStatus", mapOf("checkpointName" to checkpointName, "phase" to phase) + fields)
        val status = Bundle().apply {
            putString("scenarioId", config.scenarioId)
            putString("processInstanceId", config.processInstanceId)
            putString("checkpointName", checkpointName)
            putString("phase", phase)
            fields.forEach { (key, value) -> putString(key, value) }
        }
        InstrumentationRegistry.getInstrumentation().sendStatus(2, status)
    }

    private fun finishProcessAndReport(
        config: TestLaunchConfig,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ): ProcessEndAck {
        // Read the final control snapshot before closing the Debug ingress. No
        // snapshot/control operation is issued after the terminal acknowledgement.
        val finalControlSnapshot = control.snapshot()
        val ack = control.finishProcess(timeoutMillis = PROCESS_END_TIMEOUT_MILLIS)
        require(ack.processInstanceId == config.processInstanceId)
        require(ack.eventRef.processInstanceId == config.processInstanceId && ack.eventRef.localSequence > 0L)
        evidence.record("processEndAcknowledged", mapOf(
            "localSequence" to ack.eventRef.localSequence.toString(),
        ))
        sendControllerStatus(
            config,
            checkpointName = "processEndAcknowledged",
            phase = "processEndAcknowledged",
            control = control,
            evidence = evidence,
            processEndAck = ack,
            snapshotOverride = finalControlSnapshot,
        )
        sendControllerStatus(
            config,
            checkpointName = "scenarioHarnessFinished",
            phase = "end",
            control = control,
            evidence = evidence,
            snapshotOverride = finalControlSnapshot,
        )
        return ack
    }

    private fun validateControlActions(selection: SelectedScenario) {
        val actions = selection.controlActions
        val supported = setOf("arm", "awaitArrival", "release", "injectStoreFault", "replayLastCompletion", "awaitDetachedEffect")
        val declaredEffectIds = selection.effects.map { it.optString("effectId") }
        val awaitedEffectIds = actions.filter { it.optString("action") == "awaitDetachedEffect" }
            .map { it.optString("effectId") }
        require(declaredEffectIds.size == declaredEffectIds.toSet().size &&
            awaitedEffectIds.size == awaitedEffectIds.toSet().size &&
            awaitedEffectIds.toSet() == declaredEffectIds.toSet()) {
            "every frozen detached effect requires exactly one host wait action"
        }
        actions.forEach { action ->
            require(action.optString("action") in supported) { "control inventory contains an unsupported action" }
            when (action.optString("action")) {
                "arm" -> {
                    require(action.optString("point") in HookPoint.entries.map(HookPoint::wireValue)) { "hook point is not frozen" }
                    require(action.optString("target") in setOf("bootstrap", "nextCommand", "nextDelivery")) { "hook target is not frozen" }
                }
                "awaitArrival", "release" -> require(action.optString("point") in HookPoint.entries.map(HookPoint::wireValue)) {
                    "hook point is not frozen"
                }
                "injectStoreFault" -> {
                    require(action.length() == 3 && action.optString("fault") in setOf("replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify")) {
                        "store fault action must name one frozen fault and command"
                    }
                    val targetCommand = action.optString("command")
                    val targetIsDelivery = targetCommand.startsWith("Deliver(")
                    require(targetCommand in selection.commands && storeFaultAppliesToCommand(
                        action.optString("fault"), targetCommand, targetIsDelivery, targetCommand.startsWith("Deliver(replay,"),
                    )) { "store fault target command does not perform the matching operation" }
                }
                "awaitDetachedEffect" -> {
                    require(action.length() == 2 && selection.effects.any { it.optString("effectId") == action.optString("effectId") }) {
                        "detached effect is not declared by the hashed control inventory"
                    }
                }
            }
        }
    }

    private fun applyControlAction(
        action: JSONObject,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        when (action.optString("action")) {
            "arm" -> {
                val point = HookPoint.entries.single { it.wireValue == action.getString("point") }
                val target = nativecontract.demo.debug.HookTarget.entries.single { it.wireValue == action.getString("target") }
                val ack = control.arm(point, target)
                require(ack.actionId > 0 && ack.controlRevision > 0)
                evidence.record("hookArmed", mapOf("point" to point.wireValue, "target" to target.wireValue, "actionId" to ack.actionId.toString()))
            }
            "injectStoreFault" -> {
                val kind = nativecontract.demo.debug.StoreFaultKind.entries.single { it.wireValue == action.getString("fault") }
                val ack = control.injectStoreFault(kind)
                require(ack.actionId > 0 && ack.controlRevision > 0)
                evidence.record("storeFaultConfigured", mapOf("fault" to kind.wireValue, "actionId" to ack.actionId.toString()))
            }
        }
    }

    private fun injectFault(
        wireValue: String,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        val kind = nativecontract.demo.debug.StoreFaultKind.entries.single { it.wireValue == wireValue }
        val ack = control.injectStoreFault(kind)
        check(ack.actionId > 0 && ack.controlRevision > 0)
        evidence.record("storeFaultConfigured", mapOf("fault" to kind.wireValue, "actionId" to ack.actionId.toString()))
    }

    private fun awaitHook(
        config: TestLaunchConfig,
        action: JSONObject,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        val point = HookPoint.entries.single { it.wireValue == action.getString("point") }
        val arrived = control.awaitArrival(point, 60_000)
        check(arrived.phase.wireValue == "arrived") { "hook ${point.wireValue} did not arrive" }
        evidence.record(
            "hookArrived",
            mapOf("point" to point.wireValue, "arrivalCommandId" to (arrived.arrivalCommandRef?.id?.toString() ?: "")),
        )
        sendControllerStatus(config, "hookArrived.${point.wireValue}", "hookArrived", control, evidence)
    }

    private fun hookArrivalCommand(action: JSONObject): String? = when (action.optString("point")) {
        "beforeDeferredControlClear" -> "Logout"
        else -> null
    }

    private fun releaseHookFor(
        config: TestLaunchConfig,
        action: JSONObject,
        actions: List<JSONObject>,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        val pointName = action.optString("point").takeIf(String::isNotBlank)
            ?: actions.firstOrNull { it.optString("action") == "awaitArrival" }?.optString("point")
            ?: error("release hook has no matching awaited point")
        val point = HookPoint.entries.single { it.wireValue == pointName }
        val ack = control.release(point)
        check(ack.actionId > 0 && ack.controlRevision > 0)
        evidence.record("hookReleased", mapOf("point" to pointName, "actionId" to ack.actionId.toString()))
        sendControllerStatus(config, "hookReleased.$pointName", "hookReleased", control, evidence)
    }

    private fun renderStepMatches(step: String, command: String): Boolean {
        if (step.contains("final")) return false
        val commandKey = when (command) {
            "Login(A)", "Login(A0)" -> "login-a"
            "Login(B)" -> "login-b"
            "CancelRefresh" -> "cancel"
            else -> command.lowercase().replace(" ", "-")
        }
        return step.lowercase().contains("after-$commandKey")
    }

    private fun captureRenderedView(
        config: TestLaunchConfig,
        stepIds: List<String>,
        control: nativecontract.demo.debug.DebugScenarioControl,
        evidence: InstrumentationEvidenceWriter,
    ) {
        val stateText = visibleText("session-state")
        val credentialText = visibleText("credential-status")
        val processText = visibleText("view-process-id")
        val revisionText = visibleText("view-revision")
        require(processText == config.processInstanceId) { "rendered view process identity does not match this launch" }
        val safeText = listOf(stateText, credentialText, processText, revisionText).joinToString("\n")
        require(!Regex("(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)").containsMatchIn(safeText)) {
            "rendered session state exposes credential data"
        }
        val rendered = JSONObject()
            .put("session-state", stateText)
            .put("credential-status", credentialText)
            .put("view-process-id", config.processInstanceId)
            .put("view-revision", revisionText)
            .toString()
        evidence.record("renderedView", mapOf("state" to rendered, "revision" to revisionText))
        stepIds.forEach { stepId ->
            evidence.captureScreenshot(stepId)
            sendControllerStatus(config, "renderedView.$stepId", "rendered", control, evidence, renderedState = rendered)
        }
    }

    private fun visibleText(tag: String): String = composeRule.onNodeWithTag(tag).fetchSemanticsNode().config
        .get(SemanticsProperties.Text).joinToString("\n") { it.text }

    private fun encode(value: String): String = java.net.URLEncoder.encode(value, Charsets.UTF_8.name())

    private fun isApp12Resume(config: TestLaunchConfig): Boolean =
        config.scenarioId.startsWith("APP-12-") && config.launchOrdinal == 2 &&
            config.armPoint == "beforeBootstrapClear" && config.armTarget == "bootstrap"
}
