package nativecontract.async

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.*

@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
private val strictJson = Json { isLenient = false; allowTrailingComma = false }

fun runAsyncDocument(input: String): String {
    val parsed = try { strictJson.parseToJsonElement(input) }
    catch (error: SerializationException) { reject("malformed JSON: ${error.message}") }
    validateNoDuplicateObjectKeys(input)
    val root = parsed as? JsonObject ?: reject("root must be an object")
    keys(root, setOf("scenarios"), "root")
    val scenarios = root["scenarios"] as? JsonArray ?: reject("scenarios must be an array")
    val ids = mutableSetOf<String>()
    val traces = buildJsonArray {
        scenarios.forEachIndexed { si, item ->
            val scenario = item as? JsonObject ?: reject("scenario[$si] must be an object")
            if (scenario.keys != setOf("scenario", "events") && scenario.keys != setOf("scenario", "events", "nextRequestId")) reject("scenario[$si] has invalid keys")
            val id = scenario.string("scenario", "scenario[$si]")
            if (!ids.add(id)) reject("duplicate scenario id: $id")
            val seed = if ("nextRequestId" in scenario) scenario.longId("nextRequestId", "scenario[$si]") else 1L
            val events = scenario["events"] as? JsonArray ?: reject("events for $id must be an array")
            val machine = AsyncSession(seed)
            val steps = buildJsonArray {
                events.forEachIndexed { ei, value ->
                    val eventObject = value as? JsonObject ?: reject("event[$ei] for $id must be an object")
                    val name = eventObject.string("event", "event[$ei]")
                    val event: AsyncEvent = when (name) {
                        "LoginSucceeded" -> { keys(eventObject, setOf("event"), "event[$ei]"); AsyncEvent.LoginSucceeded }
                        "Logout" -> { keys(eventObject, setOf("event"), "event[$ei]"); AsyncEvent.Logout }
                        "TokenExpired" -> { keys(eventObject, setOf("event"), "event[$ei]"); AsyncEvent.TokenExpired }
                        "RefreshSucceeded" -> { keys(eventObject, setOf("event", "requestId"), "event[$ei]"); AsyncEvent.RefreshSucceeded(eventObject.longId("requestId", "event[$ei]")) }
                        "RefreshFailed" -> { keys(eventObject, setOf("event", "requestId"), "event[$ei]"); AsyncEvent.RefreshFailed(eventObject.longId("requestId", "event[$ei]")) }
                        else -> reject("unknown event: $name")
                    }
                    val result = machine.handle(event)
                    add(buildJsonObject {
                        put("event", eventObject)
                        put("state", result.state.name)
                        put("pendingRequestId", result.pendingRequestId?.let(::JsonPrimitive) ?: JsonNull)
                        put("effects", buildJsonArray {
                            result.effects.forEach { effect -> add(buildJsonObject {
                                when (effect) {
                                    AsyncEffect.ClearCredentials -> put("effect", "ClearCredentials")
                                    is AsyncEffect.RequestTokenRefresh -> { put("effect", "RequestTokenRefresh"); put("requestId", effect.requestId) }
                                }
                            }) }
                        })
                        put("rejection", result.rejection?.name?.let(::JsonPrimitive) ?: JsonNull)
                    })
                }
            }
            add(buildJsonObject { put("scenario", id); put("steps", steps) })
        }
    }
    return buildJsonObject { put("traces", traces) }.toString()
}

private fun keys(value: JsonObject, expected: Set<String>, label: String) {
    if (value.keys != expected) reject("$label must have exactly keys ${expected.sorted()}")
}
private fun JsonObject.string(key: String, label: String): String =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: reject("$label.$key must be a string")
private fun JsonObject.longId(key: String, label: String): Long {
    val primitive = this[key] as? JsonPrimitive ?: reject("$label.$key must be a positive integer")
    if (primitive.isString || !primitive.content.matches(Regex("[1-9][0-9]*"))) reject("$label.$key must be a positive integer token")
    val value = primitive.content.toLongOrNull() ?: reject("$label.$key is outside signed 64-bit range")
    if (value <= 0) reject("$label.$key must be positive")
    return value
}
private fun reject(message: String): Nothing = throw IllegalArgumentException(message)

/** Walks the already parser-validated JSON tokens before JsonObject can collapse duplicate keys. */
private fun validateNoDuplicateObjectKeys(source: String) = DuplicateKeyScanner(source).scan()

private class DuplicateKeyScanner(private val source: String) {
    private var offset = 0

    fun scan() {
        value()
        whitespace()
        check(offset == source.length) { "invalid JSON after root value" }
    }

    private fun value() {
        whitespace()
        when (source[offset]) {
            '{' -> objectValue()
            '[' -> arrayValue()
            '"' -> stringToken()
            else -> while (offset < source.length && source[offset] !in " \t\r\n,]}") offset++
        }
    }

    private fun objectValue() {
        offset++ // {
        whitespace()
        if (source[offset] == '}') { offset++; return }
        val names = mutableSetOf<String>()
        while (true) {
            whitespace()
            val key = stringToken()
            if (!names.add(key)) reject("duplicate object key: $key")
            whitespace()
            offset++ // :
            value()
            whitespace()
            if (source[offset] == '}') { offset++; return }
            offset++ // ,
        }
    }

    private fun arrayValue() {
        offset++ // [
        whitespace()
        if (source[offset] == ']') { offset++; return }
        while (true) {
            value()
            whitespace()
            if (source[offset] == ']') { offset++; return }
            offset++ // ,
        }
    }

    private fun stringToken(): String {
        val start = offset++ // opening quote
        while (offset < source.length) {
            when (source[offset++]) {
                '"' -> {
                    val primitive = strictJson.parseToJsonElement(source.substring(start, offset)) as JsonPrimitive
                    return primitive.content
                }
                '\\' -> offset++ // escaped quote/backslash or the 'u' of a validated unicode escape
            }
        }
        reject("unterminated JSON string")
    }

    private fun whitespace() {
        while (offset < source.length && source[offset] in " \t\r\n") offset++
    }
}

fun main() {
    val input = generateSequence(::readLine).joinToString("\n")
    try { println(runAsyncDocument(input)) }
    catch (error: Exception) { System.err.println(error.message ?: "invalid input"); kotlin.system.exitProcess(2) }
}
