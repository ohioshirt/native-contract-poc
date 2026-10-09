import XCTest
@testable import NativeContract

final class TraceRunnerTests: XCTestCase {
    func testEmptyScenarioHasNoStepsAndEveryScenarioStartsFresh() throws {
        let output = try TraceDocumentProcessor.process(Data(#"{"scenarios":[{"scenario":"empty","events":[]},{"scenario":"login","events":["LoginSucceeded"]},{"scenario":"fresh","events":["Logout"]}]}"#.utf8))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: Any])
        let traces = try XCTUnwrap(object["traces"] as? [[String: Any]])
        XCTAssertEqual(traces.count, 3)
        XCTAssertEqual((traces[0]["steps"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual((traces[1]["steps"] as? [[String: Any]])?.first?["state"] as? String, "Authenticated")
        XCTAssertEqual((traces[2]["steps"] as? [[String: Any]])?.first?["state"] as? String, "Unauthenticated")
    }

    func testUnknownEventIsRejected() {
        XCTAssertThrowsError(try TraceDocumentProcessor.process(Data(#"{"scenarios":[{"scenario":"bad","events":["NoSuchEvent"]}]}"#.utf8)))
    }

    func testDuplicateScenarioIDsAreRejected() {
        XCTAssertThrowsError(try TraceDocumentProcessor.process(Data(#"{"scenarios":[{"scenario":"same","events":[]},{"scenario":"same","events":[]}]}"#.utf8)))
    }

    func testMalformedAndUnexpectedInputShapesAreRejected() {
        for data in [Data("{".utf8), Data(#"{"scenarios":[],"extra":true}"#.utf8), Data(#"{"scenarios":[{"scenario":"x","events":[],"extra":1}]}"#.utf8)] {
            XCTAssertThrowsError(try TraceDocumentProcessor.process(data))
        }
    }
}
