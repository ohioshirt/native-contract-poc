import AsyncNativeContract
import Foundation

struct Workload: Decodable, Sendable {
    let version: Int
    let scenarios: [Scenario]
}
struct Scenario: Decodable, Sendable {
    let id: String
    let seed: Int64
    let owners: [OwnerDeclaration]
    let concurrentPhases: [Int]
    let operations: [Operation]
}
struct OwnerDeclaration: Codable, Sendable {
    let id: String
    let nextRequestId: Int64
}
struct TokenReference: Codable, Sendable {
    let operationId: String
    let effectIndex: Int
}
struct EventInput: Codable, Sendable {
    let event: String
    let tokenRef: TokenReference?
}
struct Operation: Decodable, Sendable {
    let id: String
    let owner: String
    let kind: String
    let phase: Int
    let after: [String]
    let event: EventInput?

    var dependencies: [String] {
        after + (event?.tokenRef.map { [$0.operationId] } ?? [])
    }
}
struct RenderedToken: Encodable, Sendable {
    let owner: String
    let requestId: Int64
}
struct RecordedEvent: Encodable, Sendable {
    let event: String
    let tokenRef: TokenReference?
    let token: RenderedToken?
}
struct RecordedSnapshot: Encodable, Sendable {
    let state: String
    let pendingRequestId: Int64?
    let nextRequestId: Int64?
    init(_ snapshot: ManagedSnapshot) {
        state = snapshot.state.rawValue
        pendingRequestId = snapshot.pendingRequestId
        nextRequestId = snapshot.nextRequestId
    }
    enum CodingKeys: String, CodingKey { case state, pendingRequestId, nextRequestId }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(state, forKey: .state)
        try c.encode(pendingRequestId, forKey: .pendingRequestId)
        try c.encode(nextRequestId, forKey: .nextRequestId)
    }
}
struct RecordedEffect: Encodable, Sendable {
    let effect: String
    let token: RenderedToken?
}
struct RecordedResult: Encodable, Sendable {
    let snapshot: RecordedSnapshot
    let effects: [RecordedEffect]
    let rejection: String?
    enum CodingKeys: String, CodingKey { case snapshot, effects, rejection }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(snapshot, forKey: .snapshot)
        try c.encode(effects, forKey: .effects)
        try c.encode(rejection, forKey: .rejection)
    }
}
struct RecordedOperation: Encodable, Sendable {
    let id: String
    let owner: String
    let kind: String
    let phase: Int
    let after: [String]
    let event: RecordedEvent?
    let invoke: Int64
    let `return`: Int64
    let result: RecordedResult
}
struct History: Encodable, Sendable {
    let scenario: String
    let seed: Int64
    let trial: Int
    let owners: [OwnerDeclaration]
    let operations: [RecordedOperation]
}
struct HistoryDocument: Encodable, Sendable {
    let version = 1
    let histories: [History]
}
struct RunnerError: Error, CustomStringConvertible, Sendable {
    let description: String
    init(_ description: String) { self.description = description }
}

/// Only the logical clock is locked. No API execution or suspension holds this lock.
private final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var clock: Int64 = 0
    func stamp() -> Int64 {
        lock.lock()
        defer { lock.unlock() }
        clock += 1
        return clock
    }
}

/// Every phase caller must arrive before any caller is released to invoke the API.
@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
private actor StartBarrier {
    private var remaining: Int
    private var waiting: [CheckedContinuation<Void, Never>] = []
    init(count: Int) { remaining = count }
    func arrive() async {
        remaining -= 1
        if remaining == 0 {
            for continuation in waiting { continuation.resume() }
            waiting.removeAll()
        } else {
            await withCheckedContinuation { waiting.append($0) }
        }
    }
}
private struct StoredToken: Sendable {
    let request: RefreshRequest
    let rendered: RenderedToken
}

/// A token is published only after the producing API return has been stamped.
@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
private actor CompletionStore {
    private var completed: Set<String> = []
    private var tokens: [String: [Int: StoredToken]] = [:]
    private var waiting: [String: [CheckedContinuation<Void, Error>]] = [:]
    private var failure: RunnerError?

    func wait(for id: String) async throws {
        if let failure { throw failure }
        if completed.contains(id) { return }
        try await withCheckedThrowingContinuation { waiting[id, default: []].append($0) }
    }
    func token(_ reference: TokenReference) throws -> StoredToken {
        guard completed.contains(reference.operationId),
              let token = tokens[reference.operationId]?[reference.effectIndex] else {
            throw RunnerError("missing actual emitted token: \(reference.operationId)[\(reference.effectIndex)]")
        }
        return token
    }
    func complete(_ id: String, owner: String, effects: [ManagedEffect]) {
        var emitted: [Int: StoredToken] = [:]
        for (index, effect) in effects.enumerated() {
            if case let .requestTokenRefresh(request) = effect {
                emitted[index] = StoredToken(request: request, rendered: RenderedToken(owner: owner, requestId: request.requestId))
            }
        }
        tokens[id] = emitted
        completed.insert(id)
        for continuation in waiting.removeValue(forKey: id) ?? [] { continuation.resume() }
    }
    func fail(_ error: Error) {
        let failure = RunnerError(String(describing: error))
        self.failure = failure
        for continuations in waiting.values {
            for continuation in continuations { continuation.resume(throwing: failure) }
        }
        waiting.removeAll()
    }
}

@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
enum ManagedHistoryProcessor {
    static func process(_ data: Data) async throws -> Data {
        let workload = try JSONDecoder().decode(Workload.self, from: data)
        guard workload.version == 1, !workload.scenarios.isEmpty,
              Set(workload.scenarios.map(\.id)).count == workload.scenarios.count else {
            throw RunnerError("invalid workload version or scenarios")
        }
        for scenario in workload.scenarios { try validate(scenario) }
        var histories: [History] = []
        for scenario in workload.scenarios {
            var selected: History?
            for trial in 0..<20 {
                let history = try await run(scenario, trial: trial)
                selected = history
                if hasRequiredOverlap(history, phases: scenario.concurrentPhases) { break }
            }
            guard let selected else { throw RunnerError("no completed trial") }
            histories.append(selected)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(HistoryDocument(histories: histories))
    }

    private static func validate(_ scenario: Scenario) throws {
        guard !scenario.owners.isEmpty,
              Set(scenario.owners.map(\.id)).count == scenario.owners.count,
              scenario.owners.allSatisfy({ $0.nextRequestId > 0 }),
              !scenario.operations.isEmpty, scenario.operations.count <= 16,
              Set(scenario.operations.map(\.id)).count == scenario.operations.count else {
            throw RunnerError("invalid owner declarations or operation inventory")
        }
        let owners = Set(scenario.owners.map(\.id))
        let operations = Dictionary(uniqueKeysWithValues: scenario.operations.map { ($0.id, $0) })
        for operation in scenario.operations {
            guard owners.contains(operation.owner), operation.phase >= 0,
                  Set(operation.after).count == operation.after.count else {
                throw RunnerError("invalid owner, phase or dependencies")
            }
            switch operation.kind {
            case "snapshot":
                guard operation.event == nil else { throw RunnerError("snapshot must not have event") }
            case "handle":
                guard let event = operation.event else { throw RunnerError("handle event missing") }
                switch event.event {
                case "LoginSucceeded", "Logout", "TokenExpired":
                    guard event.tokenRef == nil else { throw RunnerError("simple event cannot consume a token") }
                case "RefreshSucceeded", "RefreshFailed":
                    guard let reference = event.tokenRef, reference.effectIndex >= 0,
                          operations[reference.operationId]?.kind == "handle" else {
                        throw RunnerError("invalid token producer reference")
                    }
                default: throw RunnerError("unknown event \(event.event)")
                }
            default: throw RunnerError("unknown operation kind")
            }
            for id in operation.dependencies {
                guard let predecessor = operations[id], id != operation.id,
                      predecessor.phase <= operation.phase else { throw RunnerError("invalid predecessor") }
            }
        }
        var visiting: Set<String> = [], visited: Set<String> = []
        func visit(_ id: String) throws {
            if visited.contains(id) { return }
            guard visiting.insert(id).inserted else { throw RunnerError("cyclic operation dependencies") }
            for dependency in operations[id]!.dependencies { try visit(dependency) }
            visiting.remove(id)
            visited.insert(id)
        }
        for operation in scenario.operations { try visit(operation.id) }
        guard Set(scenario.concurrentPhases).count == scenario.concurrentPhases.count,
              scenario.concurrentPhases.allSatisfy({ phase in scenario.operations.filter { $0.phase == phase }.count >= 2 }) else {
            throw RunnerError("invalid concurrent phases")
        }
    }

    private static func run(_ scenario: Scenario, trial: Int) async throws -> History {
        let sessions = Dictionary(uniqueKeysWithValues: scenario.owners.map { ($0.id, ManagedAsyncSession(nextRequestId: $0.nextRequestId)) })
        let recorder = Recorder()
        let store = CompletionStore()
        var rows: [RecordedOperation] = []
        for phase in Set(scenario.operations.map(\.phase)).sorted() {
            let operations = scenario.operations.filter { $0.phase == phase }
            let barrier = StartBarrier(count: operations.count)
            let phaseRows = try await withThrowingTaskGroup(of: RecordedOperation.self) { group in
                for operation in operations {
                    group.addTask {
                        await barrier.arrive()
                        do {
                            for dependency in operation.dependencies { try await store.wait(for: dependency) }
                            try Task.checkCancellation()
                            let session = sessions[operation.owner]!
                            let event: ManagedEvent?
                            let renderedEvent: RecordedEvent?
                            if let input = operation.event {
                                let token = try await input.tokenRef.asyncMap { try await store.token($0) }
                                renderedEvent = RecordedEvent(event: input.event, tokenRef: input.tokenRef, token: token?.rendered)
                                switch input.event {
                                case "LoginSucceeded": event = .loginSucceeded
                                case "Logout": event = .logout
                                case "TokenExpired": event = .tokenExpired
                                case "RefreshSucceeded": event = .refreshSucceeded(token!.request)
                                case "RefreshFailed": event = .refreshFailed(token!.request)
                                default: throw RunnerError("unknown event")
                                }
                            } else {
                                event = nil
                                renderedEvent = nil
                            }
                            let invoke: Int64
                            let returned: Int64
                            let snapshot: ManagedSnapshot
                            let effects: [ManagedEffect]
                            let rejection: ManagedRejection?
                            if let event {
                                invoke = recorder.stamp()
                                let result = await session.handle(event)
                                returned = recorder.stamp()
                                snapshot = result.snapshot
                                effects = result.effects
                                rejection = result.rejection
                            } else {
                                invoke = recorder.stamp()
                                snapshot = await session.snapshot()
                                returned = recorder.stamp()
                                effects = []
                                rejection = nil
                            }
                            await store.complete(operation.id, owner: operation.owner, effects: effects)
                            let renderedEffects = effects.map { effect in
                                switch effect {
                                case .clearCredentials: RecordedEffect(effect: "ClearCredentials", token: nil)
                                case .requestTokenRefresh(let request):
                                    RecordedEffect(effect: "RequestTokenRefresh", token: RenderedToken(owner: operation.owner, requestId: request.requestId))
                                }
                            }
                            let renderedRejection: String? = switch rejection {
                            case .foreignRequest: "ForeignRequest"
                            case .requestIdExhausted: "RequestIdExhausted"
                            case nil: nil
                            }
                            return RecordedOperation(id: operation.id, owner: operation.owner, kind: operation.kind,
                                phase: operation.phase, after: operation.after, event: renderedEvent,
                                invoke: invoke, return: returned,
                                result: RecordedResult(snapshot: RecordedSnapshot(snapshot), effects: renderedEffects, rejection: renderedRejection))
                        } catch {
                            await store.fail(error)
                            throw error
                        }
                    }
                }
                var completed: [RecordedOperation] = []
                for try await row in group { completed.append(row) }
                return completed
            }
            rows.append(contentsOf: phaseRows)
        }
        return History(scenario: scenario.id, seed: scenario.seed, trial: trial, owners: scenario.owners, operations: rows)
    }

    private static func hasRequiredOverlap(_ history: History, phases: [Int]) -> Bool {
        phases.allSatisfy { phase in
            let rows = history.operations.filter { $0.phase == phase }
            return rows.enumerated().contains { i, a in
                rows.dropFirst(i + 1).contains { b in a.invoke < b.return && b.invoke < a.return }
            }
        }
    }
}

@available(macOS 10.15, iOS 13, tvOS 13, watchOS 6, *)
private extension Optional {
    func asyncMap<T>(_ transform: (Wrapped) async throws -> T) async rethrows -> T? {
        switch self {
        case .some(let value): try await transform(value)
        case .none: nil
        }
    }
}
