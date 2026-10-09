package nativecontract

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class SessionReducerTest {
    @Test fun startsUnauthenticated() {
        assertEquals(SessionState.Unauthenticated, SessionReducer().state)
    }

    @Test fun everyStateEventPairHasExpectedTransition() {
        val expected = mapOf(
            SessionState.Unauthenticated to listOf(
                Transition(SessionState.Authenticated), Transition(SessionState.Unauthenticated),
                Transition(SessionState.Unauthenticated), Transition(SessionState.Unauthenticated),
                Transition(SessionState.Unauthenticated)),
            SessionState.Authenticated to listOf(
                Transition(SessionState.Authenticated), Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials)),
                Transition(SessionState.Refreshing, listOf(Effect.RequestTokenRefresh)), Transition(SessionState.Authenticated),
                Transition(SessionState.Authenticated)),
            SessionState.Refreshing to listOf(
                Transition(SessionState.Refreshing), Transition(SessionState.Refreshing), Transition(SessionState.Refreshing),
                Transition(SessionState.Authenticated), Transition(SessionState.Unauthenticated, listOf(Effect.ClearCredentials)))
        )
        for ((state, transitions) in expected) {
            for ((index, event) in SessionEvent.entries.withIndex()) {
                val reducer = SessionReducer(state)
                assertEquals(transitions[index], reducer.handle(event), "$state × $event")
                assertEquals(transitions[index].state, reducer.state, "$state × $event state")
            }
        }
    }

    @Test fun runnerEmitsExactWireShapeAndResetsPerScenario() {
        val output = runDocument("""{"scenarios":[{"scenario":"a","events":["LoginSucceeded","TokenExpired","RefreshFailed"]},{"scenario":"empty","events":[]},{"scenario":"b","events":["Logout"]}]}""")
        assertEquals("""{"traces":[{"scenario":"a","steps":[{"event":"LoginSucceeded","state":"Authenticated","effects":[]},{"event":"TokenExpired","state":"Refreshing","effects":["RequestTokenRefresh"]},{"event":"RefreshFailed","state":"Unauthenticated","effects":["ClearCredentials"]}]},{"scenario":"empty","steps":[]},{"scenario":"b","steps":[{"event":"Logout","state":"Unauthenticated","effects":[]}]}]}""", output)
    }

    @Test fun runnerAcceptsAnEmptyScenarioId() {
        assertEquals("""{"traces":[{"scenario":"","steps":[]}]}""", runDocument("""{"scenarios":[{"scenario":"","events":[]}]}"""))
    }

    @Test fun runnerRejectsUnknownEventsDuplicateIdsAndMalformedDocuments() {
        assertFailsWith<IllegalArgumentException> { runDocument("""{"scenarios":[{"scenario":"x","events":["bogus"]}]}""") }
        assertFailsWith<IllegalArgumentException> { runDocument("""{"scenarios":[{"scenario":"x","events":[]},{"scenario":"x","events":[]}] }""") }
        assertFailsWith<IllegalArgumentException> { runDocument("""{"scenarios":[{"scenario":"x","events":[],"extra":true}]}""") }
    }
}
