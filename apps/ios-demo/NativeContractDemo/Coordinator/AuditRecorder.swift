import Foundation

/// App-internal append/sync boundary for redacted native history rows.
protocol AuditRecorder: Sendable {
    func append(kind: String, fields: Data) throws -> Int64
    func synchronize() throws
}

/// A recorder that can atomically append, synchronize, and seal the terminal
/// processEnd row so no later native event can follow it.
protocol TerminalAuditRecorder: AuditRecorder {
    func appendProcessEndAndSeal(fields: Data) throws -> Int64
}

final class NoopAuditRecorder: AuditRecorder, @unchecked Sendable {
    private let lock = NSLock()
    private var sequence: Int64 = 0

    func append(kind: String, fields: Data) throws -> Int64 {
        lock.withLock {
            guard sequence < Int64.max else { preconditionFailure("native event sequence exhausted") }
            sequence += 1
            return sequence
        }
    }

    func synchronize() throws {}
}
