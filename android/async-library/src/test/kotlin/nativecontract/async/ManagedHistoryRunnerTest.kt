package nativecontract.async

import kotlinx.serialization.json.*
import kotlin.test.*

class ManagedHistoryRunnerTest {
    private val workload = """{"version":1,"scenarios":[{"id":"max","seed":0,"owners":[{"id":"A","nextRequestId":9223372036854775807}],"concurrentPhases":[],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"}},{"id":"issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"}},{"id":"reply","owner":"A","kind":"handle","phase":2,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"issue","effectIndex":0}}},{"id":"view","owner":"A","kind":"snapshot","phase":2,"after":["reply"]}]}]}"""

    @Test fun recordsActualReturnedTokenExactLongAndAllMetadata() {
        val history = Json.parseToJsonElement(runManagedDocument(workload)).jsonObject["histories"]!!.jsonArray.single().jsonObject
        assertEquals("max", history["scenario"]!!.jsonPrimitive.content)
        assertEquals(0, history["trial"]!!.jsonPrimitive.int)
        val operations = history["operations"]!!.jsonArray.map { it.jsonObject }.associateBy { it["id"]!!.jsonPrimitive.content }
        assertEquals(setOf("login", "issue", "reply", "view"), operations.keys)
        val issue = operations.getValue("issue")
        val reply = operations.getValue("reply")
        val view = operations.getValue("view")
        val token = issue["result"]!!.jsonObject["effects"]!!.jsonArray.single().jsonObject["token"]!!.jsonObject
        assertEquals("A", token["owner"]!!.jsonPrimitive.content)
        assertEquals(Long.MAX_VALUE, token["requestId"]!!.jsonPrimitive.long)
        assertEquals(token, reply["event"]!!.jsonObject["token"])
        assertEquals(buildJsonObject { put("operationId", "issue"); put("effectIndex", 0) }, reply["event"]!!.jsonObject["tokenRef"])
        assertEquals(buildJsonArray { add("reply") }, view["after"])
        assertFalse("event" in view)
        assertTrue(issue["return"]!!.jsonPrimitive.long < reply["invoke"]!!.jsonPrimitive.long)
        assertTrue(reply["return"]!!.jsonPrimitive.long < view["invoke"]!!.jsonPrimitive.long)
        val stamps = operations.values.flatMap { listOf(it["invoke"]!!.jsonPrimitive.long, it["return"]!!.jsonPrimitive.long) }
        assertEquals((1L..8L).toSet(), stamps.toSet())
        val snapshot = view["result"]!!.jsonObject["snapshot"]!!.jsonObject
        assertEquals("Authenticated", snapshot["state"]!!.jsonPrimitive.content)
        assertEquals(JsonNull, snapshot["pendingRequestId"])
        assertEquals(JsonNull, snapshot["nextRequestId"])
        assertEquals(JsonArray(emptyList()), view["result"]!!.jsonObject["effects"])
        assertEquals(JsonNull, view["result"]!!.jsonObject["rejection"])
    }

    @Test fun malformedOrUnproducedTokensFailTheWholeDocument() {
        for (bad in listOf(
            workload.replace("9223372036854775807", "9223372036854775808"),
            workload.replace("9223372036854775807", "9223372036854775807.0"),
            workload.replace("\"effectIndex\":0", "\"effectIndex\":1"),
            workload.replace("\"operationId\":\"issue\"", "\"operationId\":\"login\""),
            workload.replace("\"after\":[\"reply\"]", "\"after\":[\"missing\"]"),
            workload.replace("\"version\":1", "\"version\":2")
        )) { assertFailsWith<IllegalArgumentException> { runManagedDocument(bad) } }
    }

    @Test fun cyclicSamePhaseDependenciesAreRejectedBeforeLaunchingCallers() {
        val cyclic = """{"version":1,"scenarios":[{"id":"cycle","seed":0,"owners":[{"id":"A","nextRequestId":1}],"concurrentPhases":[],"operations":[{"id":"one","owner":"A","kind":"snapshot","phase":0,"after":["two"]},{"id":"two","owner":"A","kind":"snapshot","phase":0,"after":["one"]}]}]}"""
        assertFailsWith<IllegalArgumentException> { runManagedDocument(cyclic) }
    }
}
