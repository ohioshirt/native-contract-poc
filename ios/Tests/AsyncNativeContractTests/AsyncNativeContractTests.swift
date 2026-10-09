import Foundation
import XCTest
@testable import AsyncNativeContract

final class AsyncNativeContractTests: XCTestCase {
    func testInitialStateAndRequestAllocation() {
        var session = AsyncSession()
        XCTAssertEqual(session.state, .unauthenticated)
        XCTAssertNil(session.pendingRequestId)
        XCTAssertEqual(session.nextRequestId, 1)
        _ = session.handle(.loginSucceeded)
        let request = session.handle(.tokenExpired)
        XCTAssertEqual(session.state, .refreshing)
        XCTAssertEqual(session.pendingRequestId, 1)
        XCTAssertEqual(session.nextRequestId, 2)
        XCTAssertEqual(request.effects, [.requestTokenRefresh(requestId: 1)])
    }

    func testOldReplyCannotCompleteSecondRequestAndDuplicatesAreIgnored() {
        var session = AsyncSession()
        _ = session.handle(.loginSucceeded)
        _ = session.handle(.tokenExpired)
        _ = session.handle(.refreshFailed(requestId: 1))
        _ = session.handle(.loginSucceeded)
        _ = session.handle(.tokenExpired)
        let stale = session.handle(.refreshSucceeded(requestId: 1))
        XCTAssertEqual(stale.state, .refreshing)
        XCTAssertEqual(session.pendingRequestId, 2)
        XCTAssertTrue(stale.effects.isEmpty)
        let current = session.handle(.refreshSucceeded(requestId: 2))
        XCTAssertEqual(current.state, .authenticated)
        XCTAssertNil(session.pendingRequestId)
        let duplicate = session.handle(.refreshSucceeded(requestId: 2))
        XCTAssertEqual(duplicate.state, .authenticated)
        XCTAssertTrue(duplicate.effects.isEmpty)
        XCTAssertEqual(session.nextRequestId, 3)
    }

    func testRefreshingLogoutIsIgnoredAndLogoutLoginDoesNotResetCounter() {
        var session = AsyncSession()
        _ = session.handle(.loginSucceeded)
        _ = session.handle(.tokenExpired)
        let logout = session.handle(.logout)
        XCTAssertEqual(logout.state, .refreshing)
        XCTAssertEqual(session.pendingRequestId, 1)
        _ = session.handle(.refreshSucceeded(requestId: 1))
        _ = session.handle(.logout)
        _ = session.handle(.loginSucceeded)
        XCTAssertEqual(session.nextRequestId, 2)
    }

    func testMaximumIdIsAllocatedOnceThenExhaustionIsAtomic() {
        var session = AsyncSession(nextRequestId: Int64.max)
        _ = session.handle(.loginSucceeded)
        let allocated = session.handle(.tokenExpired)
        XCTAssertEqual(session.pendingRequestId, Int64.max)
        XCTAssertNil(session.nextRequestId)
        XCTAssertEqual(allocated.effects, [.requestTokenRefresh(requestId: Int64.max)])
        _ = session.handle(.refreshSucceeded(requestId: Int64.max))
        let beforeState = session.state
        let exhausted = session.handle(.tokenExpired)
        XCTAssertEqual(exhausted.rejection, .requestIdExhausted)
        XCTAssertEqual(session.state, beforeState)
        XCTAssertNil(session.pendingRequestId)
        XCTAssertNil(session.nextRequestId)
        XCTAssertTrue(exhausted.effects.isEmpty)
    }

    func testRunnerPreservesRequestIdsAndProducesCompleteSteps() throws {
        let output = try AsyncTraceDocumentProcessor.process(Data(#"{"scenarios":[{"scenario":"one","events":[{"event":"LoginSucceeded"},{"event":"TokenExpired"},{"event":"RefreshSucceeded","requestId":1}]}]}"#.utf8))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let traces = try XCTUnwrap(root["traces"] as? [[String: Any]])
        let steps = try XCTUnwrap(traces[0]["steps"] as? [[String: Any]])
        XCTAssertEqual(steps.count, 3)
        XCTAssertEqual(Set(steps[0].keys), ["event", "state", "pendingRequestId", "effects", "rejection"])
        let effects = try XCTUnwrap(steps[1]["effects"] as? [[String: Any]])
        XCTAssertEqual(effects[0]["requestId"] as? Int64, 1)
        XCTAssertEqual(steps[1]["pendingRequestId"] as? Int64, 1)
        XCTAssertNil(steps[1]["rejection"] as? String)
    }

    func testScenarioIdsUseExactUnicodeScalarIdentity() throws {
        let input = #"{"scenarios":[{"scenario":"\u00e9","events":[]},{"scenario":"e\u0301","events":[]}]}"#
        let output = try AsyncTraceDocumentProcessor.process(Data(input.utf8))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let traces = try XCTUnwrap(root["traces"] as? [[String: Any]])
        XCTAssertEqual(traces.count, 2)
    }

    func testExhaustionIsAValidRunnerStep() throws {
        let source = #"{"scenarios":[{"scenario":"max","nextRequestId":9223372036854775807,"events":[{"event":"LoginSucceeded"},{"event":"TokenExpired"},{"event":"RefreshSucceeded","requestId":9223372036854775807},{"event":"TokenExpired"}]}]}"#
        let output = try AsyncTraceDocumentProcessor.process(Data(source.utf8))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let traces = try XCTUnwrap(root["traces"] as? [[String: Any]])
        let steps = try XCTUnwrap(traces[0]["steps"] as? [[String: Any]])
        XCTAssertEqual(steps[3]["rejection"] as? String, "RequestIdExhausted")
        XCTAssertEqual((steps[3]["effects"] as? [Any])?.count, 0)
    }

    func testMalformedIdsShapesAndDuplicateScenariosRejectWholeDocument() {
        let invalid = [
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":true}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":1.0}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":1e0}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":0}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":9223372036854775808}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"TokenExpired","requestId":1}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"LoginSucceeded","extra":1}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[{"event":"RefreshSucceeded","requestId":1,"requestId":1}]}]}"#,
            #"{"scenarios":[{"scenario":"x","events":[]},{"scenario":"x","events":[]}] }"#,
            #"{"scenarios":[{"scenario":"x","nextRequestId":false,"events":[]}] }"#
        ]
        for source in invalid {
            XCTAssertThrowsError(try AsyncTraceDocumentProcessor.process(Data(source.utf8)), source)
        }
    }
}
