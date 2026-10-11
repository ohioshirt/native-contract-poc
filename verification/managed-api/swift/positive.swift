import AsyncNativeContract
import NativeContract

@main struct ExternalManagedClient {
    static func main() async {
        let session = ManagedAsyncSession()
        _ = await session.handle(.loginSucceeded)
        let result = await session.handle(.tokenExpired)
        guard let first = result.effects.first, case let .requestTokenRefresh(request) = first else { fatalError("no emitted request") }
        precondition(request.requestId == 1)
        _ = await session.handle(.refreshSucceeded(request))
        _ = await session.handle(.refreshFailed(request))
        let snapshot = await session.snapshot()
        precondition(snapshot.state == .authenticated)
        precondition(snapshot.pendingRequestId == nil && snapshot.nextRequestId == 2)
        print("External API emitted-token reuse: PASS")
    }
}
