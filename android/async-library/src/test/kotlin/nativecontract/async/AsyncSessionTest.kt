package nativecontract.async

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class AsyncSessionTest {
    @Test fun correlatesAndIgnoresStaleResponsesWithoutReusingIds() {
        val session = AsyncSession()
        assertEquals(AsyncState.Authenticated, session.handle(AsyncEvent.LoginSucceeded).state)
        val first = session.handle(AsyncEvent.TokenExpired)
        assertEquals(1L, (first.effects.single() as AsyncEffect.RequestTokenRefresh).requestId)
        assertEquals(AsyncState.Authenticated, session.handle(AsyncEvent.RefreshSucceeded(1)).state)
        session.handle(AsyncEvent.TokenExpired)
        val ignored = session.handle(AsyncEvent.RefreshSucceeded(1))
        assertEquals(AsyncState.Refreshing, ignored.state)
        assertEquals(2L, ignored.pendingRequestId)
        session.handle(AsyncEvent.Logout)
        session.handle(AsyncEvent.LoginSucceeded)
        assertEquals(AsyncState.Authenticated, session.handle(AsyncEvent.RefreshSucceeded(2)).state)
        session.handle(AsyncEvent.TokenExpired)
        assertEquals(AsyncState.Unauthenticated, session.handle(AsyncEvent.RefreshFailed(3)).state)
        session.handle(AsyncEvent.LoginSucceeded)
        session.handle(AsyncEvent.Logout)
        assertEquals(4L, session.nextRequestId)
    }

    @Test fun maximumCanBeAllocatedOnceThenRejectsAtomically() {
        val session = AsyncSession(Long.MAX_VALUE)
        session.handle(AsyncEvent.LoginSucceeded)
        val allocated = session.handle(AsyncEvent.TokenExpired)
        assertEquals(Long.MAX_VALUE, allocated.pendingRequestId)
        assertEquals(null, session.nextRequestId)
        session.handle(AsyncEvent.RefreshSucceeded(Long.MAX_VALUE))
        val before = session.snapshot()
        val exhausted = session.handle(AsyncEvent.TokenExpired)
        assertEquals(before, session.snapshot())
        assertEquals(AsyncRejection.RequestIdExhausted, exhausted.rejection)
        assertEquals(emptyList(), exhausted.effects)
        assertIs<AsyncRejection>(exhausted.rejection)
    }

    @Test fun runnerEmitsTypedEventsAndRejectsWholeDocument() {
        val out = runAsyncDocument("""{"scenarios":[{"scenario":"x","events":[{"event":"LoginSucceeded"},{"event":"TokenExpired"},{"event":"RefreshSucceeded","requestId":1}]}]}""")
        assertEquals(true, out.contains("\"pendingRequestId\":1"))
        for (id in listOf("true", "1.0", "1e0", "\"1\"", "9223372036854775808")) {
            val input = """{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":$id}]}]}"""
            kotlin.test.assertFailsWith<IllegalArgumentException> { runAsyncDocument(input) }
        }
        kotlin.test.assertFailsWith<IllegalArgumentException> {
            runAsyncDocument("""{"scenarios":[{"scenario":"x","events":[]},{"scenario":"x","events":[]}]}""")
        }
    }

    @Test fun runnerRejectsDuplicateDecodedKeysAtEveryDepth() {
        val duplicateRequest = """{"scenarios":[{"scenario":"ok","events":[]},{"scenario":"dup","events":[{"event":"RefreshSucceeded","requestId":1,"requestId":2}]}]}"""
        val duplicateRootEscaped = """{"scenarios":[],"scenari\u006fs":[]}"""
        val duplicateScenarioEscaped = """{"scenarios":[{"scenario":"a","scen\u0061rio":"b","events":[]}] }"""
        val duplicateEventEscaped = """{"scenarios":[{"scenario":"a","events":[{"event":"LoginSucceeded","ev\u0065nt":"Logout"}]}]}"""
        for (input in listOf(duplicateRequest, duplicateRootEscaped, duplicateScenarioEscaped, duplicateEventEscaped)) {
            kotlin.test.assertFailsWith<IllegalArgumentException> { runAsyncDocument(input) }
        }
    }

    @Test fun duplicateScannerIgnoresJsonLikeTextAndKeepsUnicodeIdsDistinct() {
        val json = """{"scenarios":[{"scenario":"quote \" and braces { } [ ]","events":[]},{"scenario":"é","events":[]},{"scenario":"e\u0301","events":[]}]}"""
        val output = runAsyncDocument(json)
        assertEquals(3, Regex("\\\"scenario\\\"").findAll(output).count())
    }
}
