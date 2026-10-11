package nativecontract.async

import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.*

private data class TokenKey(val operationId: String, val effectIndex: Int)
private data class ObservedToken(val request: RefreshRequest, val owner: String) {
    fun json() = buildJsonObject { put("owner", owner); put("requestId", request.requestId) }
}
private data class Operation(
    val source: JsonObject,
    val id: String,
    val owner: String,
    val phase: Int,
    val eventName: String?,
    val tokenRef: TokenKey?,
    val dependencies: Set<String>,
)
private data class Scenario(val source: JsonObject, val id: String, val operations: List<Operation>, val concurrentPhases: Set<Int>)
private class LogicalClock {
    private var value = 0L
    @Synchronized fun tick(): Long = ++value
}

/** Runs complete observed trials. Input chooses operations; the OS chooses actual scheduling. */
fun runManagedDocument(input: String): String {
    val root = Json.parseToJsonElement(input).jsonObject
    root.exactKeys("version", "scenarios")
    require(root.integer("version") == 1L) { "unsupported workload version" }
    val scenarios = root["scenarios"]!!.jsonArray.map { parseScenario(it.jsonObject) }
    require(scenarios.map { it.id }.toSet().size == scenarios.size) { "duplicate scenario ID" }
    val histories = scenarios.map { scenario ->
        var observed: JsonObject? = null
        for (trial in 0 until 20) {
            observed = runTrial(scenario, trial)
            if (hasRequiredOverlap(observed, scenario.concurrentPhases)) break
        }
        checkNotNull(observed)
    }
    return buildJsonObject { put("version", 1); put("histories", JsonArray(histories)) }.toString()
}

private fun parseScenario(source: JsonObject): Scenario {
    source.exactKeys("id", "seed", "owners", "concurrentPhases", "operations")
    val id = source.string("id")
    source.integer("seed")
    val owners = source["owners"]!!.jsonArray.map { value ->
        val owner = value.jsonObject
        owner.exactKeys("id", "nextRequestId")
        require(owner.integer("nextRequestId") > 0) { "nextRequestId must be positive" }
        owner.string("id")
    }
    require(owners.isNotEmpty() && owners.toSet().size == owners.size) { "owners must be unique and nonempty" }
    val operations = source["operations"]!!.jsonArray.map { value ->
        val op = value.jsonObject
        val kind = op.string("kind")
        require(kind in setOf("handle", "snapshot")) { "unknown operation kind" }
        op.exactKeys(*(if (kind == "handle") arrayOf("id", "owner", "kind", "phase", "after", "event") else arrayOf("id", "owner", "kind", "phase", "after")))
        val opId = op.string("id")
        val owner = op.string("owner")
        require(owner in owners) { "unknown owner" }
        val phase = op.index("phase")
        val after = op["after"]!!.jsonArray.map { it.stringValue() }
        require(after.toSet().size == after.size) { "duplicate dependency" }
        val event = op["event"]?.jsonObject
        val name = event?.string("event")
        val tokenRef = when (name) {
            null -> null
            "LoginSucceeded", "Logout", "TokenExpired" -> { event.exactKeys("event"); null }
            "RefreshSucceeded", "RefreshFailed" -> {
                event.exactKeys("event", "tokenRef")
                val ref = event["tokenRef"]!!.jsonObject
                ref.exactKeys("operationId", "effectIndex")
                TokenKey(ref.string("operationId"), ref.index("effectIndex"))
            }
            else -> throw IllegalArgumentException("unknown managed event: $name")
        }
        Operation(op, opId, owner, phase, name, tokenRef, after.toSet() + listOfNotNull(tokenRef?.operationId))
    }
    require(operations.isNotEmpty() && operations.size <= 16) { "scenario must contain 1..16 operations" }
    val byId = operations.associateBy { it.id }
    require(byId.size == operations.size) { "duplicate operation ID" }
    for (op in operations) for (dependency in op.dependencies) {
        val predecessor = byId[dependency] ?: throw IllegalArgumentException("unknown dependency: $dependency")
        require(predecessor.phase <= op.phase) { "dependency is in a later phase" }
    }
    val visiting = mutableSetOf<String>()
    val visited = mutableSetOf<String>()
    fun visit(op: Operation) {
        if (op.id in visited) return
        require(visiting.add(op.id)) { "cyclic dependencies" }
        op.dependencies.forEach { visit(byId.getValue(it)) }
        visiting.remove(op.id)
        visited.add(op.id)
    }
    operations.forEach(::visit)
    val concurrent = source["concurrentPhases"]!!.jsonArray.map { it.nonnegativeIndex() }
    require(concurrent.toSet().size == concurrent.size) { "duplicate concurrent phase" }
    require(concurrent.all { phase -> operations.count { it.phase == phase } >= 2 }) { "concurrent phase needs multiple callers" }
    return Scenario(source, id, operations, concurrent.toSet())
}

private fun runTrial(scenario: Scenario, trial: Int): JsonObject {
    val sessions = scenario.source["owners"]!!.jsonArray.associate { value ->
        val owner = value.jsonObject
        owner.string("id") to ManagedAsyncSession(owner.integer("nextRequestId"))
    }
    val clock = LogicalClock()
    val tokens = ConcurrentHashMap<TokenKey, ObservedToken>()
    val completed = scenario.operations.associate { it.id to CompletableFuture<Unit>() }
    val rows = ConcurrentHashMap<String, JsonObject>()
    for ((_, phase) in scenario.operations.groupBy { it.phase }.toSortedMap()) {
        val executor = Executors.newFixedThreadPool(phase.size)
        val ready = CountDownLatch(phase.size)
        val start = CountDownLatch(1)
        try {
            val futures = phase.map { op -> executor.submit {
                try {
                    ready.countDown()
                    check(start.await(10, TimeUnit.SECONDS)) { "phase start timeout" }
                    op.dependencies.forEach { completed.getValue(it).get(10, TimeUnit.SECONDS) }
                    val token = op.tokenRef?.let { tokens[it] ?: throw IllegalArgumentException("referenced effect did not issue a token: $it") }
                    val event = when (op.eventName) {
                        "LoginSucceeded" -> ManagedEvent.LoginSucceeded
                        "Logout" -> ManagedEvent.Logout
                        "TokenExpired" -> ManagedEvent.TokenExpired
                        "RefreshSucceeded" -> ManagedEvent.RefreshSucceeded(checkNotNull(token).request)
                        "RefreshFailed" -> ManagedEvent.RefreshFailed(checkNotNull(token).request)
                        else -> null
                    }
                    val session = sessions.getValue(op.owner)
                    val result: ManagedResult
                    val invoke: Long
                    val returned: Long
                    if (event == null) {
                        invoke = clock.tick()
                        val snapshot = session.snapshot()
                        returned = clock.tick()
                        result = ManagedResult(snapshot, emptyList())
                    } else {
                        invoke = clock.tick()
                        result = session.handle(event)
                        returned = clock.tick()
                    }
                    // Publication occurs only after the producer's return stamp.
                    result.effects.forEachIndexed { index, effect ->
                        if (effect is ManagedEffect.RequestTokenRefresh) tokens[TokenKey(op.id, index)] = ObservedToken(effect.request, op.owner)
                    }
                    rows[op.id] = buildJsonObject {
                        op.source.forEach { (key, value) -> put(key, value) }
                        if (token != null) put("event", buildJsonObject {
                            op.source["event"]!!.jsonObject.forEach { (key, value) -> put(key, value) }
                            put("token", token.json())
                        })
                        put("invoke", invoke)
                        put("return", returned)
                        put("result", renderResult(result, op.owner))
                    }
                    completed.getValue(op.id).complete(Unit)
                } catch (error: Throwable) {
                    completed.getValue(op.id).completeExceptionally(error)
                    throw error
                }
            } }
            check(ready.await(10, TimeUnit.SECONDS)) { "callers did not reach the start barrier" }
            start.countDown()
            var failure: Throwable? = null
            // Every submitted caller is joined, including when another caller failed.
            for (future in futures) try { future.get(10, TimeUnit.SECONDS) }
            catch (error: Exception) { if (failure == null) failure = error.cause ?: error }
            failure?.let { throw IllegalArgumentException("scenario ${scenario.id} failed", it) }
        } finally {
            start.countDown()
            executor.shutdownNow()
            check(executor.awaitTermination(10, TimeUnit.SECONDS)) { "caller termination timeout" }
        }
    }
    check(rows.size == scenario.operations.size) { "incomplete history" }
    return buildJsonObject {
        put("scenario", scenario.id)
        put("seed", scenario.source["seed"]!!)
        put("trial", trial)
        put("owners", scenario.source["owners"]!!)
        put("operations", JsonArray(scenario.operations.map { rows.getValue(it.id) }))
    }
}

private fun renderResult(result: ManagedResult, owner: String) = buildJsonObject {
    put("snapshot", buildJsonObject {
        put("state", result.snapshot.state.name)
        put("pendingRequestId", result.snapshot.pendingRequestId?.let(::JsonPrimitive) ?: JsonNull)
        put("nextRequestId", result.snapshot.nextRequestId?.let(::JsonPrimitive) ?: JsonNull)
    })
    put("effects", buildJsonArray {
        for (effect in result.effects) add(buildJsonObject {
            when (effect) {
                ManagedEffect.ClearCredentials -> put("effect", "ClearCredentials")
                is ManagedEffect.RequestTokenRefresh -> {
                    put("effect", "RequestTokenRefresh")
                    put("token", ObservedToken(effect.request, owner).json())
                }
            }
        })
    })
    put("rejection", result.rejection?.name?.let(::JsonPrimitive) ?: JsonNull)
}

private fun hasRequiredOverlap(history: JsonObject, phases: Set<Int>): Boolean {
    val rows = history["operations"]!!.jsonArray.map { it.jsonObject }
    return phases.all { phase ->
        val calls = rows.filter { it.index("phase") == phase }
        calls.any { a -> calls.any { b ->
            a !== b && a.integer("invoke") < b.integer("return") && b.integer("invoke") < a.integer("return")
        } }
    }
}

private fun JsonObject.exactKeys(vararg expected: String) {
    require(keys == expected.toSet()) { "expected exactly keys ${expected.toList()}" }
}
private fun JsonElement.stringValue(): String {
    val primitive = this as? JsonPrimitive ?: throw IllegalArgumentException("expected string")
    require(primitive.isString) { "expected string" }
    return primitive.content
}
private fun JsonObject.string(key: String) = getValue(key).stringValue()
private fun JsonElement.exactInteger(): Long {
    val primitive = this as? JsonPrimitive ?: throw IllegalArgumentException("expected integer")
    require(!primitive.isString && primitive.content.matches(Regex("-?(0|[1-9][0-9]*)"))) { "expected integer token" }
    return primitive.content.toLongOrNull() ?: throw IllegalArgumentException("integer outside signed64")
}
private fun JsonObject.integer(key: String) = getValue(key).exactInteger()
private fun JsonElement.nonnegativeIndex(): Int {
    val value = exactInteger()
    require(value in 0..Int.MAX_VALUE.toLong()) { "expected nonnegative bounded index" }
    return value.toInt()
}
private fun JsonObject.index(key: String) = getValue(key).nonnegativeIndex()

fun main() {
    try {
        val input = System.`in`.bufferedReader().readText()
        println(runManagedDocument(input))
    } catch (error: Exception) {
        System.err.println(error.message ?: "managed history failed")
        error.cause?.let { System.err.println(it.message) }
        kotlin.system.exitProcess(2)
    }
}
