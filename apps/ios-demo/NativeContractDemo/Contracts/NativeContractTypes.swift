import Foundation

/// Evaluator-owned bounded hook inventory shared by Debug and Release code.
enum HookPoint: String, CaseIterable, Codable, Sendable {
    case beforeBootstrapClear
    case afterManaged
    case beforeStore
    case beforePublish
    case afterPublishAck
    case afterLogoutReceipt
    case ingressHeld
    case beforeDeferredControlClear
}

/// Frozen redacted physical-store value. Credential bytes never cross this type.
enum StoreObservation: Equatable, Sendable, Codable {
    case absent
    case present(account: String, version: Int64)
    case unknown(errorCode: String)

    private enum CodingKeys: String, CodingKey {
        case kind
        case account
        case version
        case errorCode
    }

    private enum Kind: String, Codable {
        case absent = "Absent"
        case present = "Present"
        case unknown = "Unknown"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        switch try container.decode(Kind.self, forKey: .kind) {
        case .absent:
            self = .absent
        case .present:
            let account = try container.decode(String.self, forKey: .account)
            let version = try container.decode(Int64.self, forKey: .version)
            guard ["A", "B"].contains(account), version >= 0 else {
                throw DecodingError.dataCorruptedError(forKey: .account, in: container, debugDescription: "invalid redacted credential labels")
            }
            self = .present(account: account, version: version)
        case .unknown:
            let errorCode = try container.decode(String.self, forKey: .errorCode)
            guard !errorCode.isEmpty else {
                throw DecodingError.dataCorruptedError(forKey: .errorCode, in: container, debugDescription: "error code must not be empty")
            }
            self = .unknown(errorCode: errorCode)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .absent:
            try container.encode(Kind.absent, forKey: .kind)
        case let .present(account, version):
            try container.encode(Kind.present, forKey: .kind)
            try container.encode(account, forKey: .account)
            try container.encode(version, forKey: .version)
        case let .unknown(errorCode):
            try container.encode(Kind.unknown, forKey: .kind)
            try container.encode(errorCode, forKey: .errorCode)
        }
    }

    func encodedRedactedJSON() throws -> Data {
        try JSONEncoder().encode(self)
    }
}
