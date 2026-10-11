import nativecontract.async.*
fun main() {
    val session = ManagedAsyncSession()
    session.handle(ManagedEvent.LoginSucceeded)
    val result = session.handle(ManagedEvent.TokenExpired)
    val request = (result.effects.single() as ManagedEffect.RequestTokenRefresh).request
    check(request.requestId == 1L)
    try {
        (result.effects as MutableList<ManagedEffect>).clear()
        error("Public effects collection is mutable")
    } catch (_: UnsupportedOperationException) {
    } catch (_: ClassCastException) {
    }
    check(result.effects.size == 1)
    session.handle(ManagedEvent.RefreshSucceeded(request))
    session.handle(ManagedEvent.RefreshFailed(request))
    val snapshot = session.snapshot()
    check(snapshot.state == AsyncState.Authenticated)
    check(snapshot.pendingRequestId == null && snapshot.nextRequestId == 2L)
    println("External API emitted-token reuse and immutable effects: PASS")
}
