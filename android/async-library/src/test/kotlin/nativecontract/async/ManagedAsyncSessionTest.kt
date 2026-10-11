package nativecontract.async

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.test.*

class ManagedAsyncSessionTest {
    private fun issue(session: ManagedAsyncSession): RefreshRequest {
        session.handle(ManagedEvent.LoginSucceeded)
        return assertIs<ManagedEffect.RequestTokenRefresh>(session.handle(ManagedEvent.TokenExpired).effects.single()).request
    }

    @Test fun foreignSameIdIsRejectedBeforeNumericCorrelationForBothResponses() {
        val a = ManagedAsyncSession()
        val b = ManagedAsyncSession()
        val foreign = issue(a)
        val local = issue(b)
        assertEquals(local.requestId, foreign.requestId)
        val before = ManagedSnapshot(AsyncState.Refreshing, 1L, 2L)
        for (event in listOf(ManagedEvent.RefreshSucceeded(foreign), ManagedEvent.RefreshFailed(foreign))) {
            val result = b.handle(event)
            assertEquals(before, result.snapshot)
            assertEquals(emptyList(), result.effects)
            assertEquals(ManagedRejection.ForeignRequest, result.rejection)
            assertEquals(before, b.snapshot())
        }
        assertEquals(AsyncState.Authenticated, b.handle(ManagedEvent.RefreshSucceeded(local)).snapshot.state)
    }

    @Test fun foreignTokenIsRejectedEvenWhenItWouldBeStale() {
        val a = ManagedAsyncSession()
        val b = ManagedAsyncSession()
        val foreign = issue(a)
        val result = b.handle(ManagedEvent.RefreshFailed(foreign))
        assertEquals(ManagedSnapshot(AsyncState.Unauthenticated, null, 1L), result.snapshot)
        assertEquals(ManagedRejection.ForeignRequest, result.rejection)
        assertEquals(emptyList(), result.effects)
    }

    @Test fun cancelledTokensCannotAffectNewRefreshAndDuplicateCompletionIsNoOp() {
        val session = ManagedAsyncSession()
        val old = issue(session)
        val logout = session.handle(ManagedEvent.Logout)
        assertEquals(ManagedSnapshot(AsyncState.Unauthenticated, null, 2L), logout.snapshot)
        assertEquals(listOf(ManagedEffect.ClearCredentials), logout.effects)
        assertEquals(emptyList(), session.handle(ManagedEvent.Logout).effects)
        val fresh = issue(session)
        assertEquals(2L, fresh.requestId)
        for (event in listOf(ManagedEvent.RefreshSucceeded(old), ManagedEvent.RefreshFailed(old))) {
            val ignored = session.handle(event)
            assertEquals(ManagedSnapshot(AsyncState.Refreshing, 2L, 3L), ignored.snapshot)
            assertEquals(emptyList(), ignored.effects)
            assertNull(ignored.rejection)
        }
        val complete = session.handle(ManagedEvent.RefreshSucceeded(fresh))
        assertEquals(ManagedSnapshot(AsyncState.Authenticated, null, 3L), complete.snapshot)
        val duplicate = session.handle(ManagedEvent.RefreshFailed(fresh))
        assertEquals(complete.snapshot, duplicate.snapshot)
        assertEquals(emptyList(), duplicate.effects)
        assertNull(duplicate.rejection)
    }

    @Test fun aliasedReferencesShareOneHistoryAndResultsStayDetached() {
        val session = ManagedAsyncSession()
        val alias = session
        val token = issue(alias)
        val before = session.snapshot()
        assertEquals(ManagedSnapshot(AsyncState.Refreshing, 1L, 2L), before)
        alias.handle(ManagedEvent.RefreshFailed(token))
        assertEquals(ManagedSnapshot(AsyncState.Unauthenticated, null, 2L), session.snapshot())
        assertEquals(ManagedSnapshot(AsyncState.Refreshing, 1L, 2L), before)
    }

    @Test fun retainedEffectsCannotBeMutatedThroughMutableListCast() {
        val session = ManagedAsyncSession()
        session.handle(ManagedEvent.LoginSucceeded)
        val result = session.handle(ManagedEvent.TokenExpired)
        val token = assertIs<ManagedEffect.RequestTokenRefresh>(result.effects.single()).request
        assertFailsWith<UnsupportedOperationException> { (result.effects as MutableList<ManagedEffect>).clear() }
        session.handle(ManagedEvent.Logout)
        assertSame(token, assertIs<ManagedEffect.RequestTokenRefresh>(result.effects.single()).request)
        val empty = session.handle(ManagedEvent.Logout)
        assertFailsWith<UnsupportedOperationException> { (empty.effects as MutableList<ManagedEffect>).add(ManagedEffect.ClearCredentials) }
    }

    @Test fun finalTwoIdsAreExactAndLogoutPreservesAtomicExhaustion() {
        val session = ManagedAsyncSession(Long.MAX_VALUE - 1)
        val penultimate = issue(session)
        assertEquals(Long.MAX_VALUE - 1, penultimate.requestId)
        session.handle(ManagedEvent.RefreshSucceeded(penultimate))
        val last = assertIs<ManagedEffect.RequestTokenRefresh>(session.handle(ManagedEvent.TokenExpired).effects.single()).request
        assertEquals(Long.MAX_VALUE, last.requestId)
        assertEquals(ManagedSnapshot(AsyncState.Refreshing, Long.MAX_VALUE, null), session.snapshot())
        session.handle(ManagedEvent.Logout)
        session.handle(ManagedEvent.LoginSucceeded)
        val exhausted = session.handle(ManagedEvent.TokenExpired)
        assertEquals(ManagedSnapshot(AsyncState.Authenticated, null, null), exhausted.snapshot)
        assertEquals(exhausted.snapshot, session.snapshot())
        assertEquals(ManagedRejection.RequestIdExhausted, exhausted.rejection)
        assertEquals(emptyList(), exhausted.effects)
        assertEquals(exhausted.snapshot, session.handle(ManagedEvent.RefreshSucceeded(last)).snapshot)
        assertEquals(exhausted.snapshot, session.handle(ManagedEvent.RefreshFailed(last)).snapshot)
    }

    @Test fun parallelExpirationIssuesOneTokenAndSnapshotsAreCoherent() {
        val session = ManagedAsyncSession()
        session.handle(ManagedEvent.LoginSucceeded)
        val pool = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val start = CountDownLatch(1)
        try {
            val callers = (0 until 8).map { index -> pool.submit<ManagedResult> {
                ready.countDown()
                check(start.await(5, TimeUnit.SECONDS))
                if (index < 4) session.handle(ManagedEvent.TokenExpired)
                else ManagedResult(session.snapshot(), emptyList(), null)
            } }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            start.countDown()
            val results = callers.map { it.get(5, TimeUnit.SECONDS) }
            assertEquals(1, results.flatMap { it.effects }.size)
            val token = assertIs<ManagedEffect.RequestTokenRefresh>(results.flatMap { it.effects }.single()).request
            assertEquals(1L, token.requestId)
            for (result in results) {
                assertTrue(result.snapshot in setOf(ManagedSnapshot(AsyncState.Authenticated, null, 1L), ManagedSnapshot(AsyncState.Refreshing, 1L, 2L)))
            }
            assertEquals(ManagedSnapshot(AsyncState.Refreshing, 1L, 2L), session.snapshot())
        } finally { start.countDown(); pool.shutdownNow() }
    }

    @Test fun nonpositiveInitialIdIsRejected() {
        assertFailsWith<IllegalArgumentException> { ManagedAsyncSession(0) }
        assertFailsWith<IllegalArgumentException> { ManagedAsyncSession(-1) }
    }
}
