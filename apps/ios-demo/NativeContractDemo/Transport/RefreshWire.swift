import CoreFoundation
import Foundation

enum RefreshWire {
    static let maximumBodyBytes = 16 * 1024

    static func makeRequest(
        baseURL: URL,
        runId: String,
        slot: RefreshSlot,
        credential: Credential
    ) throws -> URLRequest {
        guard isLabel(runId, maximum: 128),
              isLabel(slot.wireTag, maximum: 256),
              slot.request.requestId > 0,
              credential.account == slot.account,
              credential.version == slot.seedVersion,
              credential.accessToken == token(account: credential.account, version: credential.version),
              credential.refreshToken == token(account: credential.account, version: credential.version),
              var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              ["http", "https"].contains(components.scheme?.lowercased() ?? ""),
              components.host != nil,
              components.query == nil,
              components.fragment == nil else {
            throw RefreshWireError.invalidRequest
        }
        let basePath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = basePath.isEmpty ? "/v1/refresh" : "/\(basePath)/v1/refresh"
        guard let url = components.url else { throw RefreshWireError.invalidRequest }

        let fields: [String: Any] = [
            "version": 1,
            "runId": runId,
            "requestTag": slot.wireTag,
            "requestId": String(slot.request.requestId),
            "account": credential.account.rawValue,
            "refreshToken": credential.refreshToken,
        ]
        let body = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        guard body.count <= maximumBodyBytes else { throw RefreshWireError.invalidRequest }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.timeoutInterval = 75
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    static func parseResponse(
        _ data: Data,
        statusCode: Int,
        expectedRunId: String,
        slot: RefreshSlot
    ) -> RefreshOutcome {
        guard data.count <= maximumBodyBytes,
              !JSONDuplicateKeyScanner.hasDuplicateKeys(data),
              let object = try? JSONSerialization.jsonObject(with: data, options: []),
              let fields = object as? [String: Any],
              let version = exactInt64(fields["version"]), version == 1,
              let runId = fields["runId"] as? String,
              let requestTag = fields["requestTag"] as? String,
              let outcome = fields["outcome"] as? String else {
            return .failure("malformed")
        }
        guard runId == expectedRunId, requestTag == slot.wireTag else {
            return .failure("wrongCorrelation")
        }

        if statusCode == 401 || statusCode == 500 {
            guard Set(fields.keys) == ["version", "runId", "requestTag", "outcome", "failure"],
                  outcome == "failure",
                  let code = fields["failure"] as? String,
                  (statusCode == 401 && code == "rejected") || (statusCode == 500 && code == "server") else {
                return .failure("malformed")
            }
            return .failure(code)
        }
        guard statusCode == 200,
              outcome == "success",
              Set(fields.keys) == ["version", "runId", "requestTag", "outcome", "credential"],
              let credentialFields = fields["credential"] as? [String: Any],
              Set(credentialFields.keys) == ["account", "version", "accessToken", "refreshToken"],
              let accountRaw = credentialFields["account"] as? String,
              let account = CredentialAccount(rawValue: accountRaw),
              let credentialVersion = exactInt64(credentialFields["version"]),
              let accessToken = credentialFields["accessToken"] as? String,
              let refreshToken = credentialFields["refreshToken"] as? String,
              slot.seedVersion < Int64.max else {
            return .failure("malformed")
        }
        let expectedVersion = slot.seedVersion + 1
        let expectedToken = token(account: slot.account, version: expectedVersion)
        guard account == slot.account,
              credentialVersion == expectedVersion,
              accessToken == expectedToken,
              refreshToken == expectedToken else {
            return .failure("malformed")
        }
        return .success(Credential(
            account: account,
            version: credentialVersion,
            accessToken: accessToken,
            refreshToken: refreshToken
        ))
    }

    private static func exactInt64(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let result = number.int64Value
        return number.compare(NSNumber(value: result)) == .orderedSame ? result : nil
    }

    private static func token(account: CredentialAccount, version: Int64) -> String {
        "demo-\(account.rawValue)-v\(version)"
    }

    private static func isLabel(_ value: String, maximum: Int) -> Bool {
        !value.isEmpty && value.utf8.count <= maximum && value.utf8.allSatisfy {
            ($0 >= 33 && $0 <= 126)
        }
    }
}

private enum RefreshWireError: Error {
    case invalidRequest
}

/// Foundation's JSON object APIs discard duplicate keys. This small scanner only
/// identifies duplicate object members; JSONSerialization remains the syntax and
/// type decoder for the actual versioned envelope.
private struct JSONDuplicateKeyScanner {
    private let bytes: [UInt8]
    private var index = 0

    private init(_ data: Data) { bytes = Array(data) }

    static func hasDuplicateKeys(_ data: Data) -> Bool {
        var scanner = JSONDuplicateKeyScanner(data)
        do {
            try scanner.scanValue()
            return false
        } catch {
            return true
        }
    }

    private mutating func scanValue() throws {
        skipWhitespace()
        guard index < bytes.count else { throw RefreshWireError.invalidRequest }
        switch bytes[index] {
        case 0x7B: try scanObject()
        case 0x5B: try scanArray()
        case 0x22: _ = try scanStringToken()
        default: try scanPrimitive()
        }
    }

    private mutating func scanObject() throws {
        index += 1
        skipWhitespace()
        if consume(0x7D) { return }
        var keys = Set<String>()
        while true {
            skipWhitespace()
            let token = try scanStringToken()
            let key = try JSONDecoder().decode(String.self, from: token)
            guard keys.insert(key).inserted else { throw RefreshWireError.invalidRequest }
            skipWhitespace()
            guard consume(0x3A) else { throw RefreshWireError.invalidRequest }
            try scanValue()
            skipWhitespace()
            if consume(0x7D) { return }
            guard consume(0x2C) else { throw RefreshWireError.invalidRequest }
        }
    }

    private mutating func scanArray() throws {
        index += 1
        skipWhitespace()
        if consume(0x5D) { return }
        while true {
            try scanValue()
            skipWhitespace()
            if consume(0x5D) { return }
            guard consume(0x2C) else { throw RefreshWireError.invalidRequest }
        }
    }

    private mutating func scanStringToken() throws -> Data {
        guard index < bytes.count, bytes[index] == 0x22 else { throw RefreshWireError.invalidRequest }
        let start = index
        index += 1
        while index < bytes.count {
            switch bytes[index] {
            case 0x5C:
                index += 2
            case 0x22:
                index += 1
                return Data(bytes[start..<index])
            default:
                index += 1
            }
        }
        throw RefreshWireError.invalidRequest
    }

    private mutating func scanPrimitive() throws {
        let start = index
        while index < bytes.count,
              ![0x2C, 0x5D, 0x7D, 0x20, 0x09, 0x0A, 0x0D].contains(bytes[index]) {
            index += 1
        }
        guard index > start else { throw RefreshWireError.invalidRequest }
    }

    private mutating func skipWhitespace() {
        while index < bytes.count, [0x20, 0x09, 0x0A, 0x0D].contains(bytes[index]) { index += 1 }
    }

    private mutating func consume(_ byte: UInt8) -> Bool {
        guard index < bytes.count, bytes[index] == byte else { return false }
        index += 1
        return true
    }
}
