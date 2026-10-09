import Foundation
import NativeContract

private struct DynamicCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?
    init?(stringValue: String) { self.stringValue = stringValue; self.intValue = nil }
    init?(intValue: Int) { self.stringValue = String(intValue); self.intValue = intValue }
}

private enum JSONContainerFrame {
    case object(Set<String>)
    case array
}

public enum AsyncTraceDocumentError: Error, CustomStringConvertible {
    case malformedJSON
    case invalidShape(String)
    case unknownEvent(String)
    case duplicateScenario(String)

    public var description: String {
        switch self {
        case .malformedJSON: "input is not valid JSON"
        case .invalidShape(let detail): "invalid input shape: \(detail)"
        case .unknownEvent(let event): "unknown event: \(event)"
        case .duplicateScenario(let id): "duplicate scenario ID: \(id)"
        }
    }
}

private struct WireDocument: Decodable {
    let scenarios: [WireScenario]

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        guard Set(container.allKeys.map(\.stringValue)) == ["scenarios"] else {
            throw AsyncTraceDocumentError.invalidShape("expected only a scenarios field")
        }
        scenarios = try container.decode([WireScenario].self, forKey: DynamicCodingKey(stringValue: "scenarios")!)
    }
}

private struct WireScenario: Decodable {
    let scenario: String
    let nextRequestId: Int64?
    let events: [WireEvent]
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        let keys = Set(container.allKeys.map(\.stringValue))
        guard keys == ["scenario", "events"] || keys == ["scenario", "nextRequestId", "events"] else {
            throw AsyncTraceDocumentError.invalidShape("scenario must contain scenario, events, and optional nextRequestId")
        }
        scenario = try container.decode(String.self, forKey: DynamicCodingKey(stringValue: "scenario")!)
        events = try container.decode([WireEvent].self, forKey: DynamicCodingKey(stringValue: "events")!)
        if keys.contains("nextRequestId") {
            let value = try container.decode(Int64.self, forKey: DynamicCodingKey(stringValue: "nextRequestId")!)
            guard value > 0 else { throw AsyncTraceDocumentError.invalidShape("nextRequestId must be positive signed64") }
            nextRequestId = value
        } else {
            nextRequestId = nil
        }
    }
}

private struct WireEvent: Decodable {
    let name: String
    let requestId: Int64?
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: DynamicCodingKey.self)
        let keys = Set(container.allKeys.map(\.stringValue))
        guard keys.contains("event"), keys.isSubset(of: ["event", "requestId"]) else {
            throw AsyncTraceDocumentError.invalidShape("event object has unexpected keys")
        }
        name = try container.decode(String.self, forKey: DynamicCodingKey(stringValue: "event")!)
        if keys.contains("requestId") {
            let value = try container.decode(Int64.self, forKey: DynamicCodingKey(stringValue: "requestId")!)
            guard value > 0 else { throw AsyncTraceDocumentError.invalidShape("requestId must be positive signed64") }
            requestId = value
        } else {
            requestId = nil
        }
        let isResponse = name == "RefreshSucceeded" || name == "RefreshFailed"
        guard isResponse == (requestId != nil) else {
            throw AsyncTraceDocumentError.invalidShape("only response events require requestId")
        }
    }
}

public enum AsyncTraceDocumentProcessor {
    public static func process(_ input: Data) throws -> Data {
        try validateIntegerTokens(input)
        let document: WireDocument
        do {
            document = try JSONDecoder().decode(WireDocument.self, from: input)
        } catch let error as AsyncTraceDocumentError {
            throw error
        } catch {
            throw AsyncTraceDocumentError.malformedJSON
        }

        // Swift String equality canonicalizes equivalent Unicode spellings. The wire
        // protocol uses exact decoded scalar sequences, so retain their UTF-8 identity.
        var seen = Set<[UInt8]>()
        var traces = [[String: Any]]()
        for scenario in document.scenarios {
            guard seen.insert(Array(scenario.scenario.utf8)).inserted else {
                throw AsyncTraceDocumentError.duplicateScenario(scenario.scenario)
            }
            var session = AsyncSession(nextRequestId: scenario.nextRequestId ?? 1)
            var steps = [[String: Any]]()
            for wireEvent in scenario.events {
                let event = try nativeEvent(wireEvent)
                let transition = session.handle(event)
                let inputEvent: [String: Any]
                if let requestId = wireEvent.requestId {
                    inputEvent = ["event": wireEvent.name, "requestId": requestId]
                } else {
                    inputEvent = ["event": wireEvent.name]
                }
                let effects: [[String: Any]] = transition.effects.map { effect in
                    switch effect {
                    case .requestTokenRefresh(let requestId): ["effect": "RequestTokenRefresh", "requestId": requestId]
                    case .clearCredentials: ["effect": "ClearCredentials"]
                    }
                }
                steps.append([
                    "event": inputEvent,
                    "state": transition.state.rawValue,
                    "pendingRequestId": transition.pendingRequestId as Any? ?? NSNull(),
                    "effects": effects,
                    "rejection": transition.rejection?.rawValue as Any? ?? NSNull()
                ])
            }
            traces.append(["scenario": scenario.scenario, "steps": steps])
        }
        do {
            return try JSONSerialization.data(withJSONObject: ["traces": traces], options: [.sortedKeys])
        } catch {
            throw AsyncTraceDocumentError.invalidShape("could not encode trace output")
        }
    }

    /// JSONDecoder accepts exponent and decimal spellings for integral numeric values.
    /// Validate the original token spelling before decoding so wire IDs are integer tokens.
    private static func validateIntegerTokens(_ data: Data) throws {
        let bytes = Array(data)
        var index = 0
        var stack = [JSONContainerFrame]()
        while index < bytes.count {
            switch bytes[index] {
            case 0x7b: stack.append(.object([])); index += 1; continue // {
            case 0x5b: stack.append(.array); index += 1; continue // [
            case 0x7d, 0x5d: if !stack.isEmpty { stack.removeLast() }; index += 1; continue // } ]
            case 0x22: break
            default: index += 1; continue
            }
            let start = index
            index += 1
            var escaped = false
            while index < bytes.count {
                let byte = bytes[index]
                index += 1
                if escaped { escaped = false; continue }
                if byte == 0x5c { escaped = true; continue }
                if byte == 0x22 { break }
            }
            let end = index
            var cursor = index
            skipWhitespace(bytes, &cursor)
            guard cursor < bytes.count, bytes[cursor] == 0x3a else { continue }
            let keyData = Data(bytes[start..<end])
            guard let key = try? JSONDecoder().decode(String.self, from: keyData) else { continue }
            if !stack.isEmpty, case .object(var keys) = stack[stack.count - 1] {
                guard keys.insert(key).inserted else {
                    throw AsyncTraceDocumentError.invalidShape("duplicate object key: \(key)")
                }
                stack[stack.count - 1] = .object(keys)
            }
            guard key == "requestId" || key == "nextRequestId" else { continue }
            cursor += 1
            skipWhitespace(bytes, &cursor)
            let valueStart = cursor
            while cursor < bytes.count, ![0x2c, 0x5d, 0x7d, 0x20, 0x09, 0x0a, 0x0d].contains(bytes[cursor]) { cursor += 1 }
            let token = String(decoding: bytes[valueStart..<cursor], as: UTF8.self)
            guard token.first.map({ $0 >= "1" && $0 <= "9" }) == true,
                  token.utf8.allSatisfy({ $0 >= 0x30 && $0 <= 0x39 }),
                  Int64(token) != nil else {
                throw AsyncTraceDocumentError.invalidShape("\(key) must be a positive signed64 integer token")
            }
        }
    }

    private static func skipWhitespace(_ bytes: [UInt8], _ index: inout Int) {
        while index < bytes.count, [0x20, 0x09, 0x0a, 0x0d].contains(bytes[index]) { index += 1 }
    }

    private static func nativeEvent(_ event: WireEvent) throws -> AsyncAuthEvent {
        switch event.name {
        case "LoginSucceeded": .loginSucceeded
        case "Logout": .logout
        case "TokenExpired": .tokenExpired
        case "RefreshSucceeded": .refreshSucceeded(requestId: event.requestId!)
        case "RefreshFailed": .refreshFailed(requestId: event.requestId!)
        default: throw AsyncTraceDocumentError.unknownEvent(event.name)
        }
    }
}
