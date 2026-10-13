import Foundation
import Security
import XCTest
@testable import NativeContractDemo

final class KeychainStoreTests: XCTestCase {
    func testOwnedKeychainItemIsReadBackWithDeviceOnlyAccessibilityAndDeletedIdempotently() throws {
        let attemptId = "t4-\(UUID().uuidString)"
        let scenarioId = "KeychainTests"
        let service = "native-contract-demo.credentials.test.\(attemptId).\(scenarioId)"
        let store = try KeychainCredentialStore(service: service)
        defer { try? store.clearVerified() }

        try store.clearVerified()
        XCTAssertNil(try store.readVerified())
        try store.replaceVerified(.demo(account: .a, version: 0))
        let stored = try XCTUnwrap(store.readVerified())
        XCTAssertEqual(stored.account, .a)
        XCTAssertEqual(stored.version, 0)

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
            kSecAttrSynchronizable as String: false,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        let attributes = try XCTUnwrap(result as? [String: Any])
        XCTAssertEqual(attributes[kSecAttrAccessible as String] as? String, kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        XCTAssertEqual((attributes[kSecAttrSynchronizable as String] as? NSNumber)?.boolValue, false)

        try store.replaceVerified(.demo(account: .a, version: 1))
        let replaced = try XCTUnwrap(store.readVerified())
        XCTAssertEqual(replaced.account, .a)
        XCTAssertEqual(replaced.version, 1)
        try store.clearVerified()
        try store.clearVerified()
        XCTAssertNil(try store.readVerified())
    }

    func testInjectedReplaceFaultPersistsAcrossMatchingOperationsUntilNone() throws {
        let attemptId = "t4-fault-\(UUID().uuidString)"
        let service = "native-contract-demo.credentials.test.\(attemptId).FaultTarget"
        let base = try KeychainCredentialStore(service: service)
        let audit = StoreOperationRecorder()
        let store = AuditedCredentialStore(base: base, audit: audit, storeIOChanged: { _ in })
        defer { try? base.clearVerified() }

        try base.clearVerified()
        store.setStoreFault("replaceBefore")
        try store.beginOperation(context("Bootstrap"))
        try store.clearVerified()
        store.endOperation()

        for version: Int64 in [0, 1] {
            try store.beginOperation(context("RefreshSuccess"))
            XCTAssertThrowsError(try store.replaceVerified(.demo(account: .a, version: version))) { error in
                guard let failure = error as? CredentialStoreFailure else {
                    return XCTFail("replace fault must retain its redacted physical failure details")
                }
                XCTAssertEqual(failure.operation, "replace")
                XCTAssertEqual(failure.fault, "replaceBefore")
                XCTAssertFalse(failure.mutationApplied)
            }
            store.endOperation()
        }

        store.setStoreFault(nil)
        try store.beginOperation(context("Login"))
        try store.replaceVerified(.demo(account: .a, version: 0))
        store.endOperation()
        XCTAssertEqual(try base.readVerified()?.version, 0)
    }

    func testClearDeletesMalformedOwnedItemAndRecordsUnknownBeforeAbsentAfter() throws {
        let attemptId = "t4-malformed-clear-\(UUID().uuidString)"
        let service = "native-contract-demo.credentials.test.\(attemptId).MalformedClear"
        let itemQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
            kSecAttrSynchronizable as String: false,
        ]
        var malformedItem = itemQuery
        malformedItem[kSecValueData as String] = Data([0xff, 0x00, 0x80])
        malformedItem[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        XCTAssertEqual(SecItemAdd(malformedItem as CFDictionary, nil), errSecSuccess)
        defer { _ = SecItemDelete(itemQuery as CFDictionary) }

        let base = try KeychainCredentialStore(service: service)
        let audit = StoreOperationRecorder()
        let store = AuditedCredentialStore(base: base, audit: audit, storeIOChanged: { _ in })
        try store.beginOperation(context("Bootstrap"))
        defer { store.endOperation() }

        try store.clearVerified()

        XCTAssertNil(try base.readVerified())
        let mutation = try XCTUnwrap(audit.rows.first { $0.kind == "storeMutation" })
        let before = try XCTUnwrap(try JSONSerialization.jsonObject(with: mutation.fields) as? [String: Any])
        XCTAssertEqual((before["before"] as? [String: Any])?["kind"] as? String, "Unknown")
        XCTAssertEqual((before["before"] as? [String: Any])?["errorCode"] as? String, "malformedCredential")
        XCTAssertEqual((before["after"] as? [String: Any])?["kind"] as? String, "Absent")

        let readback = try XCTUnwrap(audit.rows.first { $0.kind == "storeReadback" })
        let readbackFields = try XCTUnwrap(try JSONSerialization.jsonObject(with: readback.fields) as? [String: Any])
        XCTAssertEqual((readbackFields["observation"] as? [String: Any])?["kind"] as? String, "Absent")
    }

    private func context(_ cause: String) -> StoreAuditContext {
        StoreAuditContext(
            commandRef: AppCommandReference(processInstanceId: "attempt/APP-01/p1", id: 3),
            cause: cause,
            epochId: "epoch-test",
            slotId: "slot-A1",
            ownerId: "owner-test",
            effectId: nil,
            originCommandRef: nil,
            releaseActionId: nil
        )
    }
}

private final class StoreOperationRecorder: AuditRecorder, @unchecked Sendable {
    private let lock = NSLock()
    private var sequence: Int64 = 0
    private var records: [(kind: String, fields: Data)] = []

    func append(kind: String, fields: Data) throws -> Int64 {
        lock.withLock {
            sequence += 1
            records.append((kind, fields))
            return sequence
        }
    }

    func synchronize() throws {}

    var rows: [(kind: String, fields: Data)] {
        lock.withLock { records }
    }
}
