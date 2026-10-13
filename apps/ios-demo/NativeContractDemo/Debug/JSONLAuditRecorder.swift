import Foundation

final class JSONLAuditRecorder: TerminalAuditRecorder, @unchecked Sendable {
    let fileURL: URL
    private let processInstanceId: String
    private let launchOrdinal: Int64
    private let lock = NSLock()
    private var handle: FileHandle
    private var nextSequence: Int64 = 1
    private var sealed = false

    init(fileURL: URL, processInstanceId: String, launchOrdinal: Int64) throws {
        guard launchOrdinal > 0 else { throw AuditRecorderError.invalidEvent }
        self.fileURL = fileURL
        self.processInstanceId = processInstanceId
        self.launchOrdinal = launchOrdinal
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
        guard FileManager.default.createFile(atPath: fileURL.path, contents: nil, attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]),
              let opened = try? FileHandle(forWritingTo: fileURL) else {
            throw AuditRecorderError.unavailable
        }
        handle = opened
    }

    func append(kind: String, fields: Data) throws -> Int64 {
        try lock.withLock {
            guard !sealed else { throw AuditRecorderError.sealed }
            return try appendUnlocked(kind: kind, fields: fields)
        }
    }

    func appendProcessEndAndSeal(fields: Data) throws -> Int64 {
        try lock.withLock {
            guard !sealed else { throw AuditRecorderError.sealed }
            let sequence = try appendUnlocked(kind: "processEnd", fields: fields)
            // Once a terminal row has been written, forbid later rows even if
            // fsync reports an error. A retry cannot safely invent another end.
            sealed = true
            try handle.synchronize()
            return sequence
        }
    }

    private func appendUnlocked(kind: String, fields: Data) throws -> Int64 {
        guard nextSequence > 0, nextSequence < Int64.max,
              let decoded = try JSONSerialization.jsonObject(with: fields, options: [.fragmentsAllowed]) as? [String: Any] else {
                throw AuditRecorderError.invalidEvent
        }
        var event = decoded
        event["processInstanceId"] = processInstanceId
        event["launchOrdinal"] = launchOrdinal
        event["localSequence"] = nextSequence
        event["kind"] = kind
        let encoded = try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys])
        var row = encoded
        row.append(0x0A)
        try handle.write(contentsOf: row)
        let assigned = nextSequence
        nextSequence += 1
        return assigned
    }

    func synchronize() throws {
        try lock.withLock { try handle.synchronize() }
    }
}

private enum AuditRecorderError: Error {
    case unavailable
    case invalidEvent
    case sealed
}
