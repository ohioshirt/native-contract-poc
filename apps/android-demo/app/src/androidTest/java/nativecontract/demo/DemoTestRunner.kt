package nativecontract.demo

import android.app.Application
import android.os.Bundle
import androidx.test.runner.AndroidJUnitRunner
import java.net.URI

data class TestLaunchConfig(
    val scenarioId: String,
    val runId: String,
    val processInstanceId: String,
    val launchOrdinal: Int,
    val baseUrl: String,
    val scenarioPhase: String,
    val cancelMode: String,
    val scenarioInventorySha256: String,
    val controlInventorySha256: String,
    val variantId: String?,
    val armPoint: String?,
    val armTarget: String?,
    val storeFault: String?,
) {
    fun asMap(): Map<String, String> = buildMap {
        put("scenarioId", scenarioId)
        put("runId", runId)
        put("processInstanceId", processInstanceId)
        put("launchOrdinal", launchOrdinal.toString())
        put("baseUrl", baseUrl)
        put("scenarioPhase", scenarioPhase)
        put("cancelMode", cancelMode)
        put("scenarioInventorySha256", scenarioInventorySha256)
        put("controlInventorySha256", controlInventorySha256)
        variantId?.let { put("variantId", it) }
        armPoint?.let { put("armPoint", it) }
        armTarget?.let { put("armTarget", it) }
        storeFault?.let { put("storeFault", it) }
    }

    companion object {
        private val required = setOf(
            "scenarioId", "runId", "processInstanceId", "launchOrdinal", "baseUrl", "scenarioPhase", "cancelMode",
            "scenarioInventorySha256", "controlInventorySha256",
        )
        private val optional = setOf("variantId", "armPoint", "armTarget", "storeFault")
        private val labelPattern = Regex("[A-Za-z0-9_-]{1,64}")
        private val sha256Pattern = Regex("[0-9a-f]{64}")

        fun from(arguments: Bundle): TestLaunchConfig {
            val values = (required + optional).associateWith { key -> arguments.getString(key) }
            require(required.all { !values[it].isNullOrBlank() }) { "missing frozen scenario launch argument" }
            val unexpected = arguments.keySet() - required - optional - setOf("class")
            require(unexpected.isEmpty()) { "unknown scenario launch arguments: ${unexpected.sorted()}" }
            val ordinal = values.getValue("launchOrdinal")!!.toIntOrNull()
            require(ordinal != null && ordinal > 0) { "launchOrdinal must be a positive integer" }
            require(labelPattern.matches(values.getValue("scenarioId")!!)) { "scenarioId must be a frozen ASCII label" }
            require(values.getValue("scenarioInventorySha256")!!.let(sha256Pattern::matches)) {
                "scenarioInventorySha256 must be lowercase SHA-256"
            }
            require(values.getValue("controlInventorySha256")!!.let(sha256Pattern::matches)) {
                "controlInventorySha256 must be lowercase SHA-256"
            }
            require(values["variantId"] == null || labelPattern.matches(values.getValue("variantId")!!)) {
                "variantId must be a frozen ASCII label"
            }
            val attemptId = values.getValue("processInstanceId")!!.substringBefore('/')
            require(labelPattern.matches(attemptId)) { "processInstanceId must begin with a frozen attempt label" }
            require(values.getValue("processInstanceId") == "$attemptId/${values.getValue("scenarioId")}/p$ordinal") {
                "processInstanceId must match scenarioId and launchOrdinal"
            }
            require(values.getValue("scenarioPhase") in setOf("seed", "resume", "single")) {
                "scenarioPhase is outside the frozen set"
            }
            require(values.getValue("cancelMode") == "disabled") {
                "cancelMode is outside the frozen set"
            }
            val uri = URI(values.getValue("baseUrl"))
            require(uri.scheme == "http" && uri.host != null && uri.userInfo == null && uri.query == null && uri.fragment == null && uri.path in listOf("", "/")) {
                "baseUrl must be a plain HTTP origin"
            }
            require(values["armPoint"] == null || values["armPoint"] in hookPoints) { "armPoint is outside the frozen set" }
            require(values["armTarget"] == null || values["armTarget"] in setOf("bootstrap", "nextCommand", "nextDelivery")) {
                "armTarget is outside the frozen set"
            }
            require((values["armPoint"] == null) == (values["armTarget"] == null)) { "armPoint and armTarget must be supplied together" }
            require(values["storeFault"] == null || values["storeFault"] in storeFaultKinds) { "storeFault is outside the frozen set" }
            return TestLaunchConfig(
                scenarioId = values.getValue("scenarioId")!!,
                runId = values.getValue("runId")!!,
                processInstanceId = values.getValue("processInstanceId")!!,
                launchOrdinal = ordinal,
                baseUrl = values.getValue("baseUrl")!!,
                scenarioPhase = values.getValue("scenarioPhase")!!,
                cancelMode = values.getValue("cancelMode")!!,
                scenarioInventorySha256 = values.getValue("scenarioInventorySha256")!!,
                controlInventorySha256 = values.getValue("controlInventorySha256")!!,
                variantId = values["variantId"],
                armPoint = values["armPoint"],
                armTarget = values["armTarget"],
                storeFault = values["storeFault"],
            )
        }

        private val hookPoints = setOf(
            "beforeBootstrapClear", "afterManaged", "beforeStore", "beforePublish",
            "afterPublishAck", "afterLogoutReceipt", "ingressHeld", "beforeDeferredControlClear",
        )
        private val storeFaultKinds = setOf("none", "replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify")
    }
}

class DemoTestRunner : AndroidJUnitRunner() {
    private lateinit var launchConfig: TestLaunchConfig

    override fun onCreate(arguments: Bundle) {
        launchConfig = TestLaunchConfig.from(arguments)
        super.onCreate(arguments)
    }

    override fun callApplicationOnCreate(app: Application) {
        val debugApplication = app as? nativecontract.demo.debug.DebugDemoApplication
            ?: error("DebugDemoApplication is required by the frozen instrumentation runner")
        debugApplication.configureTestLaunch(launchConfig.asMap())
        super.callApplicationOnCreate(app)
    }
}
