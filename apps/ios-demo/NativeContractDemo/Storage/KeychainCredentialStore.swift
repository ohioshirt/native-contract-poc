import Foundation
import Security

/// One synthetic credential item in the app's or test's explicitly owned service.
final class KeychainCredentialStore: CredentialStore, StoreFaultInjecting, @unchecked Sendable {
    private let service: String
    private let lock = NSLock()
    private var configuredFault: String?

    init(service: String) throws {
        guard !service.isEmpty,
              service.range(of: "^[A-Za-z0-9._-]{1,200}$", options: .regularExpression) != nil else {
            throw CredentialStoreError.malformedCredential
        }
        self.service = service
    }

    func setStoreFault(_ kind: String?) {
        lock.withLock {
            if let kind,
               ["replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"].contains(kind) {
                configuredFault = kind
            } else {
                configuredFault = nil
            }
        }
    }

    func readVerified() throws -> Credential? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess,
              let data = result as? Data else {
            throw CredentialStoreError.readFailed
        }
        guard let credential = try? JSONDecoder().decode(Credential.self, from: data),
              Self.valid(credential) else {
            throw CredentialStoreError.malformedCredential
        }
        return credential
    }

    func replaceVerified(_ credential: Credential) throws {
        guard Self.valid(credential) else { throw CredentialStoreError.malformedCredential }
        let before = try readVerified().map(Self.observation) ?? .absent
        let fault = lock.withLock { configuredFault }
        if fault == "replaceBefore" {
            throw CredentialStoreFailure(
                operation: "replace",
                fault: fault!,
                mutationApplied: false,
                verification: "notAttempted",
                before: before,
                observation: before,
                physicalAfter: before
            )
        }

        let encoded: Data
        do { encoded = try JSONEncoder().encode(credential) }
        catch { throw CredentialStoreError.replaceFailed }

        let query = baseQuery
        let attributes: [String: Any] = [
            kSecValueData as String: encoded,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecAttrSynchronizable as String: false,
        ]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecItemNotFound {
            var add = query
            attributes.forEach { add[$0.key] = $0.value }
            let addStatus = SecItemAdd(add as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw CredentialStoreError.replaceFailed }
        } else if updateStatus != errSecSuccess {
            throw CredentialStoreError.replaceFailed
        }

        let after = StoreObservation.present(account: credential.account.rawValue, version: credential.version)
        if fault == "replaceAfterBeforeVerify" {
            throw CredentialStoreFailure(
                operation: "replace",
                fault: fault!,
                mutationApplied: true,
                verification: "failed",
                before: before,
                observation: .unknown(errorCode: "readFailed"),
                physicalAfter: after
            )
        }
        guard try readVerified() == credential else { throw CredentialStoreError.readbackFailed }
    }

    func clearVerified() throws {
        // Clearing an owned malformed item is a recovery operation. Preserve the
        // pre-clear uncertainty in diagnostics, but never let decoding it block
        // SecItemDelete for this exact service/account.
        let before = bestEffortObservation()
        let fault = lock.withLock { configuredFault }
        if fault == "clearBefore" {
            throw CredentialStoreFailure(
                operation: "clear",
                fault: fault!,
                mutationApplied: false,
                verification: "notAttempted",
                before: before,
                observation: before,
                physicalAfter: before
            )
        }

        let status = SecItemDelete(baseQuery as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialStoreError.clearFailed
        }
        if fault == "clearAfterBeforeVerify" {
            throw CredentialStoreFailure(
                operation: "clear",
                fault: fault!,
                mutationApplied: true,
                verification: "failed",
                before: before,
                observation: .unknown(errorCode: "readFailed"),
                physicalAfter: .absent
            )
        }
        guard try readVerified() == nil else { throw CredentialStoreError.readbackFailed }
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "current",
            kSecAttrSynchronizable as String: false,
        ]
    }

    private static func valid(_ credential: Credential) -> Bool {
        credential.version >= 0
            && !credential.accessToken.isEmpty
            && !credential.refreshToken.isEmpty
    }

    private static func observation(_ credential: Credential) -> StoreObservation {
        .present(account: credential.account.rawValue, version: credential.version)
    }

    private func bestEffortObservation() -> StoreObservation {
        do {
            guard let credential = try readVerified() else { return .absent }
            return Self.observation(credential)
        } catch let error as CredentialStoreError {
            return .unknown(errorCode: error.safeCode)
        } catch {
            return .unknown(errorCode: "storeFailure")
        }
    }
}
