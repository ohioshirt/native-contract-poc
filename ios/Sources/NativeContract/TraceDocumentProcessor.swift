import Foundation

public enum TraceDocumentError: Error, CustomStringConvertible {
    case malformedJSON
    case invalidShape(String)
    case unknownEvent(String)
    case duplicateScenario(String)

    public var description: String {
        switch self {
        case .malformedJSON: return "input is not valid JSON"
        case .invalidShape(let detail): return "invalid input shape: \(detail)"
        case .unknownEvent(let event): return "unknown event: \(event)"
        case .duplicateScenario(let id): return "duplicate scenario ID: \(id)"
        }
    }
}

public enum TraceDocumentProcessor {
    private struct Step {
        let event: String
        let state: String
        let effects: [String]

        var json: [String: Any] {
            ["event": event, "state": state, "effects": effects]
        }
    }

    public static func process(_ input: Data) throws -> Data {
        let root: Any
        do {
            root = try JSONSerialization.jsonObject(with: input, options: [.fragmentsAllowed])
        } catch {
            throw TraceDocumentError.malformedJSON
        }
        guard let document = root as? [String: Any], Set(document.keys) == ["scenarios"] else {
            throw TraceDocumentError.invalidShape("expected only a scenarios field")
        }
        guard let scenarios = document["scenarios"] as? [Any] else {
            throw TraceDocumentError.invalidShape("scenarios must be an array")
        }

        var seen = Set<String>()
        var traces = [[String: Any]]()
        for (index, rawScenario) in scenarios.enumerated() {
            guard let scenario = rawScenario as? [String: Any],
                  Set(scenario.keys) == ["scenario", "events"] else {
                throw TraceDocumentError.invalidShape("scenario at index \(index) must contain only scenario and events")
            }
            guard let id = scenario["scenario"] as? String,
                  let rawEvents = scenario["events"] as? [Any] else {
                throw TraceDocumentError.invalidShape("scenario at index \(index) needs a string ID and events array")
            }
            guard seen.insert(id).inserted else {
                throw TraceDocumentError.duplicateScenario(id)
            }

            var reducer = AuthReducer()
            var steps = [Step]()
            for rawEvent in rawEvents {
                guard let eventName = rawEvent as? String,
                      let event = AuthEvent(rawValue: eventName) else {
                    throw TraceDocumentError.unknownEvent(rawEvent as? String ?? String(describing: rawEvent))
                }
                let result = reducer.handle(event)
                steps.append(Step(
                    event: event.rawValue,
                    state: result.state.rawValue,
                    effects: result.effects.map(\.rawValue)
                ))
            }
            traces.append(["scenario": id, "steps": steps.map(\.json)])
        }

        do {
            return try JSONSerialization.data(withJSONObject: ["traces": traces], options: [.sortedKeys])
        } catch {
            throw TraceDocumentError.invalidShape("could not encode trace output")
        }
    }
}
