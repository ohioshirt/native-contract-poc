import Foundation
import XCTest
import NativeContract
import AsyncNativeContract

@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
@MainActor
final class ManagedAsyncSessionTests: XCTestCase {
    private func issued(_ result: ManagedResult) throws -> RefreshRequest {
        guard result.effects.count == 1, case let .requestTokenRefresh(request) = result.effects[0] else {
            XCTFail("expected one issued request")
            throw NSError(domain: "ManagedTests", code: 1)
        }
        return request
    }
    private func check(_ snapshot: ManagedSnapshot, _ state: AuthState, _ pending: Int64?, _ next: Int64?, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(snapshot.state, state, file: file, line: line)
        XCTAssertEqual(snapshot.pendingRequestId, pending, file: file, line: line)
        XCTAssertEqual(snapshot.nextRequestId, next, file: file, line: line)
    }
    // Removing the identity guard would accept B's token with A's numeric ID.
    func testForeignSameNumberRejectsBothResponseKindsBeforeStaleHandling() async throws {
        let a = ManagedAsyncSession(), b = ManagedAsyncSession()
        _ = await a.handle(.loginSucceeded)
        _ = await b.handle(.loginSucceeded)
        let own = try issued(await a.handle(.tokenExpired))
        let foreign = try issued(await b.handle(.tokenExpired))
        XCTAssertEqual(own.requestId, foreign.requestId)
        for event in [ManagedEvent.refreshSucceeded(foreign), .refreshFailed(foreign)] {
            let rejected = await a.handle(event)
            check(rejected.snapshot, .refreshing, 1, 2)
            XCTAssertTrue(rejected.effects.isEmpty)
            XCTAssertEqual(rejected.rejection, .foreignRequest)
        }
        _ = await a.handle(.logout)
        let staleForeign = await a.handle(.refreshSucceeded(foreign))
        XCTAssertEqual(staleForeign.rejection, .foreignRequest)
        check(staleForeign.snapshot, .unauthenticated, nil, 2)
        let ownStale = await a.handle(.refreshSucceeded(own))
        XCTAssertNil(ownStale.rejection)
        check(ownStale.snapshot, .unauthenticated, nil, 2)
    }
    // Resetting allocation or losing correlation would let canceled replies finish ID 2.
    func testCanceledAndDuplicateTokensCannotCompleteNewRequest() async throws {
        let session = ManagedAsyncSession()
        _ = await session.handle(.loginSucceeded)
        let old = try issued(await session.handle(.tokenExpired))
        let logout = await session.handle(.logout)
        check(logout.snapshot, .unauthenticated, nil, 2)
        guard case .clearCredentials = logout.effects.first else { return XCTFail("missing clear effect") }
        _ = await session.handle(.loginSucceeded)
        let fresh = try issued(await session.handle(.tokenExpired))
        XCTAssertEqual(fresh.requestId, 2)
        for event in [ManagedEvent.refreshSucceeded(old), .refreshFailed(old)] {
            let stale = await session.handle(event)
            check(stale.snapshot, .refreshing, 2, 3)
            XCTAssertTrue(stale.effects.isEmpty)
            XCTAssertNil(stale.rejection)
        }
        let completed = await session.handle(.refreshSucceeded(fresh))
        check(completed.snapshot, .authenticated, nil, 3)
        let duplicate = await session.handle(.refreshFailed(fresh))
        check(duplicate.snapshot, .authenticated, nil, 3)
        XCTAssertTrue(duplicate.effects.isEmpty)
    }
    // Copying owned state or exposing live result storage would break alias and retained snapshots.
    func testAliasesShareSessionAndResultsStayDetached() async throws {
        let session = ManagedAsyncSession()
        let alias = session
        _ = await session.handle(.loginSucceeded)
        let retained = await alias.handle(.tokenExpired)
        let token = try issued(retained)
        _ = await session.handle(.refreshFailed(token))
        check(await alias.snapshot(), .unauthenticated, nil, 2)
        check(retained.snapshot, .refreshing, 1, 2)
        XCTAssertEqual(try issued(retained).requestId, 1)
        var callerEffects = retained.effects
        callerEffects.removeAll()
        XCTAssertEqual(retained.effects.count, 1)
    }
    // Overflow or allocator reset would issue MAX twice or mutate state on exhaustion.
    func testLastTwoIdsAndLogoutExhaustionAreAtomic() async throws {
        let session = ManagedAsyncSession(nextRequestId: Int64.max - 1)
        _ = await session.handle(.loginSucceeded)
        let penultimate = try issued(await session.handle(.tokenExpired))
        XCTAssertEqual(penultimate.requestId, Int64.max - 1)
        _ = await session.handle(.refreshSucceeded(penultimate))
        let last = try issued(await session.handle(.tokenExpired))
        XCTAssertEqual(last.requestId, Int64.max)
        check(await session.snapshot(), .refreshing, Int64.max, nil)
        _ = await session.handle(.logout)
        _ = await session.handle(.loginSucceeded)
        let exhausted = await session.handle(.tokenExpired)
        check(exhausted.snapshot, .authenticated, nil, nil)
        XCTAssertEqual(exhausted.rejection, .requestIdExhausted)
        XCTAssertTrue(exhausted.effects.isEmpty)
        let stale = await session.handle(.refreshFailed(last))
        check(stale.snapshot, .authenticated, nil, nil)
        XCTAssertNil(stale.rejection)
        XCTAssertTrue(stale.effects.isEmpty)
    }
    // A split validation/reduction could allocate more than once or expose an incoherent triple.
    func testParallelExpirationsAllocateOnceWithCoherentSnapshots() async throws {
        let session = ManagedAsyncSession()
        _ = await session.handle(.loginSucceeded)
        let results = await withTaskGroup(of: ManagedResult.self, returning: [ManagedResult].self) { group in
            for _ in 0..<32 { group.addTask { await session.handle(.tokenExpired) } }
            var results: [ManagedResult] = []
            for await result in group { results.append(result) }
            return results
        }
        XCTAssertEqual(results.flatMap(\.effects).count, 1)
        for result in results {
            check(result.snapshot, .refreshing, 1, 2)
            XCTAssertNil(result.rejection)
        }
        await withTaskGroup(of: ManagedSnapshot.self) { group in
            for _ in 0..<32 { group.addTask { await session.snapshot() } }
            for await snapshot in group { check(snapshot, .refreshing, 1, 2) }
        }
    }
}
