import XCTest
import CoreFoundation
import Security
@testable import NativeContractDemo

final class ScenarioContractTests: XCTestCase {
    func testFrozenHookAndFaultInventories() {
        XCTAssertEqual(HookPoint.allCases.map(\.rawValue), [
            "beforeBootstrapClear",
            "afterManaged",
            "beforeStore",
            "beforePublish",
            "afterPublishAck",
            "afterLogoutReceipt",
            "ingressHeld",
            "beforeDeferredControlClear",
        ])
        XCTAssertEqual(StoreFaultKind.allCases.map(\.rawValue), [
            "none",
            "replaceBefore",
            "replaceAfterBeforeVerify",
            "clearBefore",
            "clearAfterBeforeVerify",
        ])
    }

    func testControlPanelIdentifiersUseTheFrozenLabels() {
        XCTAssertEqual(DebugScenarioControlPanelID.target(.bootstrap), "hook-target-bootstrap")
        XCTAssertEqual(DebugScenarioControlPanelID.target(.nextCommand), "hook-target-nextCommand")
        XCTAssertEqual(DebugScenarioControlPanelID.target(.nextDelivery), "hook-target-nextDelivery")
        XCTAssertEqual(DebugScenarioControlPanelID.arm(.beforeBootstrapClear), "hook-arm-beforeBootstrapClear")
        XCTAssertEqual(DebugScenarioControlPanelID.release(.beforeBootstrapClear), "hook-release-beforeBootstrapClear")
        XCTAssertEqual(DebugScenarioControlPanelID.state(.beforeBootstrapClear), "hook-state-beforeBootstrapClear")
        XCTAssertEqual(DebugScenarioControlPanelID.fault(.clearBefore), "fault-set-clearBefore")
        XCTAssertEqual(DebugScenarioControlPanelID.finishProcess, "finish-process")
        XCTAssertEqual(DebugScenarioControlPanelID.processEndAckJSON, "process-end-ack-json")
    }

    func testProcessEndAckCarriesItsActualProcessScopedEventReference() throws {
        let processId = "attempt-01/APP-07/p1"
        let ack = ProcessEndAck(
            processInstanceId: processId,
            eventRef: ProcessEndEventReference(processInstanceId: processId, localSequence: 19)
        )
        let data = try JSONEncoder().encode(ack)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let reference = try XCTUnwrap(object["eventRef"] as? [String: Any])

        XCTAssertEqual(Set(object.keys), ["processInstanceId", "eventRef"])
        XCTAssertEqual(object["processInstanceId"] as? String, processId)
        XCTAssertEqual(reference["processInstanceId"] as? String, processId)
        XCTAssertEqual((reference["localSequence"] as? NSNumber)?.int64Value, 19)
    }

    func testProbeRedactorReturnsOnlyCredentialLabels() {
        let blob = Data(#"{"account":"A","version":7,"accessToken":"demo-A-v7","refreshToken":"demo-A-v7"}"#.utf8)
        let observation = StorageProbe.redactCredentialBlob(blob)

        guard case let .present(account, version) = observation else {
            return XCTFail("valid demo credential should produce a redacted Present observation")
        }
        XCTAssertEqual(account, "A")
        XCTAssertEqual(version, 7)
        XCTAssertFalse(String(describing: observation).contains("demo-A-v7"))
    }

    func testUnknownProbeDoesNotExposeRawErrorOrCredentialData() {
        let observation = StoreObservation.unknown(errorCode: "readFailed")
        let result = ProbeResult(probeId: "probe-01", processInstanceId: "attempt-01/APP-01/p1", observation: observation)
        let rendered = String(describing: result)

        XCTAssertTrue(rendered.contains("readFailed"))
        XCTAssertFalse(rendered.contains("accessToken"))
        XCTAssertFalse(rendered.contains("refreshToken"))
    }

    func testStorageProbeReadsOnlyItsOwnedRealKeychainItem() throws {
        let attemptId = "probe-" + UUID().uuidString
        let scenarioId = "PROBE"
        let processInstanceId = "\(attemptId)/\(scenarioId)/p1"
        let service = try XCTUnwrap(StorageProbe.testingService(attemptId: attemptId, scenarioId: scenarioId))
        let itemQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
        ]
        let cleanup = SecItemDelete(itemQuery as CFDictionary)
        XCTAssertTrue(cleanup == errSecSuccess || cleanup == errSecItemNotFound)
        defer { _ = SecItemDelete(itemQuery as CFDictionary) }

        XCTAssertEqual(
            StorageProbe.read(service: service, probeId: "before", processInstanceId: processInstanceId).observation,
            .absent
        )

        let syntheticBlob = Data(#"{"account":"A","version":7,"accessToken":"demo-A-v7","refreshToken":"demo-A-v7"}"#.utf8)
        let addQuery = itemQuery.merging([
            kSecValueData as String: syntheticBlob,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecAttrSynchronizable as String: false,
        ]) { _, new in new }
        XCTAssertEqual(SecItemAdd(addQuery as CFDictionary, nil), errSecSuccess)
        guard case let .present(account, version) = StorageProbe.read(
            service: service,
            probeId: "during",
            processInstanceId: processInstanceId
        ).observation else {
            return XCTFail("direct Keychain probe did not return the synthetic redacted value")
        }
        XCTAssertEqual(account, "A")
        XCTAssertEqual(version, 7)

        XCTAssertEqual(SecItemDelete(itemQuery as CFDictionary), errSecSuccess)
        XCTAssertEqual(
            StorageProbe.read(service: service, probeId: "after", processInstanceId: processInstanceId).observation,
            .absent
        )
    }
}
