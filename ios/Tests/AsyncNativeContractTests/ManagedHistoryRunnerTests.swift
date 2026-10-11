import Foundation
import XCTest
@testable import ManagedHistoryRunner

@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
@MainActor
final class ManagedHistoryRunnerTests: XCTestCase {
    // Floating-point conversion, missing setup rows or forged tokens break these observations.
    func testRunnerRecordsActualMaxTokenAndEveryOperationWithPhaseEdges() async throws {
        let input = #"{"version":1,"scenarios":[{"id":"max","seed":0,"owners":[{"id":"A","nextRequestId":9223372036854775807}],"concurrentPhases":[],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"}},{"id":"issue","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"}},{"id":"complete","owner":"A","kind":"handle","phase":2,"after":["issue"],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"issue","effectIndex":0}}},{"id":"view","owner":"A","kind":"snapshot","phase":3,"after":[]}]}]}"#
        let output = try await ManagedHistoryProcessor.process(Data(input.utf8))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let histories = try XCTUnwrap(root["histories"] as? [[String: Any]])
        let rows = try XCTUnwrap(histories.first?["operations"] as? [[String: Any]])
        XCTAssertEqual(rows.count, 4)
        let byID = Dictionary(uniqueKeysWithValues: rows.map { ($0["id"] as! String, $0) })
        let issue = try XCTUnwrap(byID["issue"])
        let result = try XCTUnwrap(issue["result"] as? [String: Any])
        let effects = try XCTUnwrap(result["effects"] as? [[String: Any]])
        let token = try XCTUnwrap(effects[0]["token"] as? [String: Any])
        XCTAssertEqual((token["requestId"] as? NSNumber)?.int64Value, Int64.max)
        let response = try XCTUnwrap(byID["complete"]?["event"] as? [String: Any])
        XCTAssertEqual((response["token"] as? NSDictionary), token as NSDictionary)
        XCTAssertEqual((response["tokenRef"] as? NSDictionary), ["operationId": "issue", "effectIndex": 0] as NSDictionary)
        for (a,b) in [("login","issue"),("issue","complete"),("complete","view")] {
            XCTAssertLessThan(byID[a]!["return"] as! Int, byID[b]!["invoke"] as! Int)
        }
        let final = try XCTUnwrap(byID["view"]?["result"] as? [String: Any])
        let snapshot = try XCTUnwrap(final["snapshot"] as? [String: Any])
        XCTAssertEqual(snapshot["state"] as? String, "Authenticated")
        XCTAssertTrue(snapshot["nextRequestId"] is NSNull)
        XCTAssertTrue(snapshot["pendingRequestId"] is NSNull)
        XCTAssertTrue(final["rejection"] is NSNull)
    }

    // Serial synthesis or starting the clock after the barrier would miss required live overlap.
    func testConcurrentPhaseRetainsOneWholeTrialAndObservedOverlap() async throws {
        let input = #"{"version":1,"scenarios":[{"id":"parallel","seed":0,"owners":[{"id":"A","nextRequestId":1}],"concurrentPhases":[1],"operations":[{"id":"login","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"LoginSucceeded"}},{"id":"one","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"}},{"id":"two","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"TokenExpired"}},{"id":"view","owner":"A","kind":"snapshot","phase":1,"after":[]}]}]}"#
        let output = try await ManagedHistoryProcessor.process(Data(input.utf8))
        let root = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let histories = try XCTUnwrap(root["histories"] as? [[String: Any]])
        let history = try XCTUnwrap(histories.first)
        XCTAssertTrue((0..<20).contains(history["trial"] as! Int))
        let rows = try XCTUnwrap(history["operations"] as? [[String: Any]])
        XCTAssertEqual(Set(rows.map { $0["id"] as! String }), ["login", "one", "two", "view"])
        let parallel = rows.filter { ($0["phase"] as? Int) == 1 }
        XCTAssertTrue(parallel.enumerated().contains { i,a in parallel.dropFirst(i+1).contains { b in
            (a["invoke"] as! Int) < (b["return"] as! Int) && (b["invoke"] as! Int) < (a["return"] as! Int)
        } })
        let stamps = rows.flatMap { [$0["invoke"] as! Int, $0["return"] as! Int] }
        XCTAssertEqual(Set(stamps).count, stamps.count)
    }

    // Accepting missing producer effects would silently fabricate a token or partial history.
    func testMissingActualTokenRejectsWholeRun() async {
        let input = #"{"version":1,"scenarios":[{"id":"missing","seed":0,"owners":[{"id":"A","nextRequestId":1}],"concurrentPhases":[],"operations":[{"id":"no-token","owner":"A","kind":"handle","phase":0,"after":[],"event":{"event":"TokenExpired"}},{"id":"response","owner":"A","kind":"handle","phase":1,"after":[],"event":{"event":"RefreshSucceeded","tokenRef":{"operationId":"no-token","effectIndex":0}}}]}]}"#
        do {
            _ = try await ManagedHistoryProcessor.process(Data(input.utf8))
            XCTFail("missing emitted token must reject")
        } catch { }
    }
}
