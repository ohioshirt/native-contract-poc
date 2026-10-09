package nativecontract

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private val strictJson = Json { isLenient = false; allowTrailingComma = false }

fun runDocument(input: String): String {
    val document = try {
        strictJson.parseToJsonElement(input)
    } catch (error: SerializationException) {
        throw IllegalArgumentException("malformed JSON: ${error.message}", error)
    }
    val root = document as? JsonObject ?: reject("root must be an object")
    requireKeys(root, setOf("scenarios"), "root")
    val scenarios = root["scenarios"] as? JsonArray ?: reject("scenarios must be an array")
    val seenIds = mutableSetOf<String>()
    val traces = buildJsonArray {
        scenarios.forEachIndexed { scenarioIndex, value ->
            val scenario = value as? JsonObject ?: reject("scenario[$scenarioIndex] must be an object")
            requireKeys(scenario, setOf("scenario", "events"), "scenario[$scenarioIndex]")
            val id = scenario.string("scenario", "scenario[$scenarioIndex]")
            if (!seenIds.add(id)) reject("duplicate scenario id: $id")
            val events = scenario["events"] as? JsonArray ?: reject("events for $id must be an array")
            val reducer = SessionReducer()
            val steps = buildJsonArray {
                events.forEachIndexed { eventIndex, eventValue ->
                    val eventName = (eventValue as? JsonPrimitive)?.takeIf { it.isString }?.content
                        ?: reject("event[$eventIndex] for $id must be a string")
                    val event = SessionEvent.entries.firstOrNull { it.name == eventName }
                        ?: reject("unknown event: $eventName")
                    val result = reducer.handle(event)
                    add(buildJsonObject {
                        put("event", event.name)
                        put("state", result.state.name)
                        put("effects", buildJsonArray { result.effects.forEach { add(kotlinx.serialization.json.JsonPrimitive(it.name)) } })
                    })
                }
            }
            add(buildJsonObject {
                put("scenario", id)
                put("steps", steps)
            })
        }
    }
    return buildJsonObject { put("traces", traces) }.toString()
}

private fun requireKeys(value: JsonObject, expected: Set<String>, label: String) {
    if (value.keys != expected) reject("$label must have exactly keys ${expected.sorted()}")
}

private fun JsonObject.string(key: String, label: String): String =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: reject("$label.$key must be a string")

private fun reject(message: String): Nothing = throw IllegalArgumentException(message)

fun main() {
    val input = generateSequence(::readLine).joinToString("\n")
    try {
        println(runDocument(input))
    } catch (error: Exception) {
        System.err.println(error.message ?: "invalid input")
        kotlin.system.exitProcess(2)
    }
}
