import CoreFoundation
import Foundation
import Security

/// Read-only evaluator probe. It performs its own Security query and decoder;
/// it does not call the candidate CredentialStore or read cached view state.
enum StorageProbe {
    private static let credentialKeys: Set<String> = ["account", "version", "accessToken", "refreshToken"]

    static func testingService(attemptId: String, scenarioId: String) -> String? {
        guard isLabel(attemptId), isLabel(scenarioId) else { return nil }
        return "native-contract-demo.credentials.test.\(attemptId).\(scenarioId)"
    }

    static func read(service: String, probeId: String, processInstanceId: String) -> ProbeResult {
        guard !service.isEmpty, !probeId.isEmpty, !processInstanceId.isEmpty else {
            return ProbeResult(
                probeId: probeId,
                processInstanceId: processInstanceId,
                observation: .unknown(errorCode: "invalidProbeArgument")
            )
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        let observation: StoreObservation
        if status == errSecItemNotFound {
            observation = .absent
        } else if status != errSecSuccess {
            observation = .unknown(errorCode: "keychainStatus_\(status)")
        } else if let data = result as? Data {
            observation = redactCredentialBlob(data)
        } else {
            observation = .unknown(errorCode: "unexpectedKeychainResult")
        }
        return ProbeResult(probeId: probeId, processInstanceId: processInstanceId, observation: observation)
    }

    static func redactCredentialBlob(_ data: Data) -> StoreObservation {
        guard
            let object = try? JSONSerialization.jsonObject(with: data, options: []),
            let dictionary = object as? [String: Any],
            Set(dictionary.keys) == credentialKeys,
            let account = dictionary["account"] as? String,
            ["A", "B"].contains(account),
            let number = dictionary["version"] as? NSNumber,
            CFGetTypeID(number) != CFBooleanGetTypeID()
        else {
            return .unknown(errorCode: "invalidBlob")
        }

        let version = number.int64Value
        guard version >= 0, number.compare(NSNumber(value: version)) == .orderedSame else {
            return .unknown(errorCode: "invalidVersion")
        }
        let expectedToken = "demo-\(account)-v\(version)"
        guard dictionary["accessToken"] as? String == expectedToken,
              dictionary["refreshToken"] as? String == expectedToken else {
            return .unknown(errorCode: "tokenMismatch")
        }
        return .present(account: account, version: version)
    }

    private static func isLabel(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) || ($0 >= 97 && $0 <= 122) || $0 == 45 || $0 == 95
        }
    }
}
