import CryptoKit
import Foundation
import Dispatch
import XCTest

private enum ScenarioHarnessError: Error, CustomStringConvertible {
    case missing(String)
    case invalid(String)

    var description: String {
        switch self {
        case let .missing(value): "missing frozen runner input: \(value)"
        case let .invalid(value): "invalid frozen runner input: \(value)"
        }
    }
}

private func isLogoutCommand(_ command: String) -> Bool {
    command == "Logout" || command == "Logout(failed)"
}

private func logoutButtonIdentifier(_ command: String) -> String? {
    isLogoutCommand(command) ? "logout" : nil
}

private func storeFaultAppliesToCommand(
    _ fault: String,
    command: String,
    isDelivery: Bool,
    replayDelivery: Bool
) -> Bool {
    (fault.hasPrefix("replace") && isDelivery && !replayDelivery) ||
        (fault.hasPrefix("clear") && isLogoutCommand(command))
}

private struct CommandLabels {
    let lastCompletedCommandID: Int64
    let lastCommandStatus: String
    let lastEnqueuedCommandID: Int64

    init(lastCompletedID: String, lastCommandStatus: String, lastEnqueuedID: String) throws {
        guard let completed = Int64(lastCompletedID), completed >= 0,
              let enqueued = Int64(lastEnqueuedID), enqueued >= completed,
              !lastCommandStatus.isEmpty else {
            throw ScenarioHarnessError.missing("valid completed/enqueued command labels")
        }
        self.lastCompletedCommandID = completed
        self.lastCommandStatus = lastCommandStatus
        self.lastEnqueuedCommandID = enqueued
    }

    func hasEnqueued(_ expectedID: Int64) -> Bool {
        lastEnqueuedCommandID == expectedID
    }

    func consumerHasNotCompleted(since previousID: Int64) -> Bool {
        lastCompletedCommandID == previousID
    }
}

private struct App11FinalQueuedReceipt: Equatable {
    let command: String
    let commandID: Int64
}

/// UI tests exchange JSON over the app-process boundary, so decode the frozen
/// wire shape locally instead of reaching into the app target's Swift types.
private struct HarnessProcessEndAck: Decodable {
    struct EventReference: Decodable {
        let processInstanceId: String
        let localSequence: Int64
    }

    let processInstanceId: String
    let eventRef: EventReference
}

private enum ProcessedHighWaterDecision: Equatable {
    case waiting
    case reached(Int64)
}

private func app11FinalQueuedReceipt(
    deliveryCommandID: Int64,
    queuedOrder: [String]
) throws -> App11FinalQueuedReceipt {
    guard deliveryCommandID > 0, !queuedOrder.isEmpty else {
        throw ScenarioHarnessError.invalid("APP-11 requires a delivery and queued commands")
    }
    let queuedCount = Int64(queuedOrder.count)
    guard queuedCount <= Int64.max - deliveryCommandID else {
        throw ScenarioHarnessError.invalid("APP-11 command ID exhausted")
    }
    return App11FinalQueuedReceipt(command: queuedOrder[queuedOrder.count - 1], commandID: deliveryCommandID + queuedCount)
}

private func processedHighWaterDecision(
    snapshot: [String: Any],
    expectedFinalID: Int64,
    previousID: Int64?,
    processInstanceID: String
) throws -> ProcessedHighWaterDecision {
    guard let ref = snapshot["lastProcessedCommandRef"] as? [String: Any],
          let processID = ref["processInstanceId"] as? String,
          let number = ref["id"] as? NSNumber else {
        return .waiting
    }
    guard processID == processInstanceID else {
        throw ScenarioHarnessError.invalid("processed high-water reference belongs to another process")
    }
    let current = number.int64Value
    guard current > 0 else {
        throw ScenarioHarnessError.invalid("processed high-water command ID must be positive")
    }
    if current > expectedFinalID {
        throw ScenarioHarnessError.invalid("unexpected processed command high-water \(current); expected \(expectedFinalID)")
    }
    if current == expectedFinalID, current > (previousID ?? 0) {
        return .reached(current)
    }
    return .waiting
}

private struct ScenarioLaunchConfiguration {
    let scenarioID: String
    let runID: String
    let processInstanceID: String
    let launchOrdinal: Int
    let baseURL: String
    let cancelMode: String
    let variantID: String?
    let scenarioPhase: String
    let armPoint: String?
    let armTarget: String?
    let storeFault: String?
    let scenarioInventoryPath: String
    let scenarioInventorySHA256: String
    let controlInventoryPath: String
    let controlInventorySHA256: String

    static let environmentKeys = [
        "NATIVE_CONTRACT_SCENARIO_ID",
        "NATIVE_CONTRACT_RUN_ID",
        "NATIVE_CONTRACT_PROCESS_INSTANCE_ID",
        "NATIVE_CONTRACT_LAUNCH_ORDINAL",
        "NATIVE_CONTRACT_BASE_URL",
        "NATIVE_CONTRACT_CANCEL_MODE",
        "NATIVE_CONTRACT_SCENARIO_PHASE",
        "NATIVE_CONTRACT_SCENARIO_INVENTORY_PATH",
        "NATIVE_CONTRACT_SCENARIO_INVENTORY_SHA256",
        "NATIVE_CONTRACT_CONTROL_INVENTORY_PATH",
        "NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256",
    ]

    init(environment: [String: String]) throws {
        func required(_ key: String) throws -> String {
            guard let value = environment[key], !value.isEmpty else {
                throw ScenarioHarnessError.missing(key)
            }
            return value
        }
        func optional(_ key: String) -> String? {
            guard let value = environment[key], !value.isEmpty else { return nil }
            return value
        }

        scenarioID = try required("NATIVE_CONTRACT_SCENARIO_ID")
        runID = try required("NATIVE_CONTRACT_RUN_ID")
        processInstanceID = try required("NATIVE_CONTRACT_PROCESS_INSTANCE_ID")
        guard let ordinal = Int(try required("NATIVE_CONTRACT_LAUNCH_ORDINAL")), ordinal > 0 else {
            throw ScenarioHarnessError.invalid("launch ordinal must be positive")
        }
        launchOrdinal = ordinal
        baseURL = try required("NATIVE_CONTRACT_BASE_URL")
        cancelMode = try required("NATIVE_CONTRACT_CANCEL_MODE")
        guard cancelMode == "disabled" else {
            throw ScenarioHarnessError.invalid("cancel mode is outside the frozen set")
        }
        scenarioPhase = try required("NATIVE_CONTRACT_SCENARIO_PHASE")
        scenarioInventoryPath = try required("NATIVE_CONTRACT_SCENARIO_INVENTORY_PATH")
        scenarioInventorySHA256 = try required("NATIVE_CONTRACT_SCENARIO_INVENTORY_SHA256")
        controlInventoryPath = try required("NATIVE_CONTRACT_CONTROL_INVENTORY_PATH")
        controlInventorySHA256 = try required("NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256")
        variantID = optional("NATIVE_CONTRACT_VARIANT_ID")
        armPoint = optional("NATIVE_CONTRACT_ARM_POINT")
        armTarget = optional("NATIVE_CONTRACT_ARM_TARGET")
        storeFault = optional("NATIVE_CONTRACT_STORE_FAULT")

        let label = "[A-Za-z0-9_-]{1,64}"
        guard scenarioID.range(of: "^\(label)$", options: .regularExpression) != nil,
              runID.range(of: "^\(label)$", options: .regularExpression) != nil else {
            throw ScenarioHarnessError.invalid("scenarioId and runId must be frozen ASCII labels")
        }
        let processParts = processInstanceID.split(separator: "/", omittingEmptySubsequences: false)
        guard processParts.count == 3,
              processParts[1] == Substring(scenarioID),
              processParts[2] == Substring("p\(launchOrdinal)"),
              String(processParts[0]).range(of: "^\(label)$", options: .regularExpression) != nil else {
            throw ScenarioHarnessError.invalid("processInstanceId must encode attempt, scenario and launch ordinal")
        }
        guard scenarioInventorySHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              controlInventorySHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
            throw ScenarioHarnessError.invalid("inventory digests must be lowercase SHA-256")
        }
        guard ["single", "seed", "resume"].contains(scenarioPhase) else {
            throw ScenarioHarnessError.invalid("scenarioPhase is outside the frozen set")
        }
        guard let components = URLComponents(string: baseURL), components.scheme == "http",
              components.host != nil, components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              components.path.isEmpty || components.path == "/" else {
            throw ScenarioHarnessError.invalid("baseURL must be a plain HTTP origin")
        }
        guard (armPoint == nil) == (armTarget == nil) else {
            throw ScenarioHarnessError.invalid("armPoint and armTarget must be supplied together")
        }
    }

    var appLaunchArguments: [String] {
        var arguments = [
            "--scenario-id", scenarioID,
            "--run-id", runID,
            "--process-instance-id", processInstanceID,
            "--launch-ordinal", String(launchOrdinal),
            "--base-url", baseURL,
            "--cancel-mode", cancelMode,
        ]
        if let armPoint { arguments += ["--arm", armPoint] }
        if let armTarget { arguments += ["--arm-target", armTarget] }
        if let storeFault { arguments += ["--store-fault", storeFault] }
        return arguments
    }

    var appLaunchEnvironment: [String: String] {
        [
            "scenarioId": scenarioID,
            "runId": runID,
            "processInstanceId": processInstanceID,
            "launchOrdinal": String(launchOrdinal),
            "scenarioPhase": scenarioPhase,
            "cancelMode": cancelMode,
        ]
    }
}

private struct SelectedScenario {
    let commands: [String]
    let cancelMode: String
    let controlActions: [[String: Any]]
    let receiptProbeOrder: [(command: String, probeID: String)]
    let requiredProbes: [String]
    let requiredRenderedViews: [String]
    let releaseAfterCommand: String?
    let releaseAfterProbes: [String]
    let queuedOrder: [String]
    let barrierPoint: String?
    let assertNoLaterReceiptBeforeRelease: Bool
    let declaredControls: [String]
    let storeFault: String?
    let replayCount: Int
    let effects: [[String: Any]]

    static func load(configuration: ScenarioLaunchConfiguration) throws -> SelectedScenario {
        let isControl = configuration.scenarioID.hasPrefix("CTRL-")
        let path = isControl ? configuration.controlInventoryPath : configuration.scenarioInventoryPath
        let digest = isControl ? configuration.controlInventorySHA256 : configuration.scenarioInventorySHA256
        let data: Data
        do {
            data = try Data(contentsOf: URL(fileURLWithPath: path), options: [.mappedIfSafe])
        } catch {
            throw ScenarioHarnessError.missing("inventory bytes at \(path)")
        }
        let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard actual == digest else { throw ScenarioHarnessError.invalid("copied inventory digest mismatch") }
        let decoded = try JSONSerialization.jsonObject(with: data)
        guard let document = decoded as? [String: Any], document["version"] as? Int == 1 else {
            throw ScenarioHarnessError.invalid("inventory top-level version/shape")
        }
        let rowsKey = isControl ? "controls" : "scenarios"
        guard let rows = document[rowsKey] as? [[String: Any]],
              let base = rows.first(where: { $0["id"] as? String == configuration.scenarioID }) else {
            throw ScenarioHarnessError.missing("scenario row \(configuration.scenarioID)")
        }
        let selected: [String: Any]
        if let variants = base["variants"] as? [[String: Any]] {
            guard let variantID = configuration.variantID,
                  let variant = variants.first(where: { $0["id"] as? String == variantID }) else {
                throw ScenarioHarnessError.missing("selected frozen variant")
            }
            selected = variant
        } else {
            guard configuration.variantID == nil else {
                throw ScenarioHarnessError.invalid("variantId was supplied for a non-variant scenario")
            }
            selected = base
        }

        let commandSource: [String: Any]
        if let launches = selected["launches"] as? [[String: Any]] {
            guard let launch = launches.first(where: { $0["ordinal"] as? Int == configuration.launchOrdinal }) else {
                throw ScenarioHarnessError.missing("launch ordinal \(configuration.launchOrdinal)")
            }
            commandSource = launch
        } else if let launches = base["launches"] as? [[String: Any]] {
            guard let launch = launches.first(where: { $0["ordinal"] as? Int == configuration.launchOrdinal }) else {
                throw ScenarioHarnessError.missing("launch ordinal \(configuration.launchOrdinal)")
            }
            commandSource = launch
        } else {
            commandSource = selected
        }
        guard let commands = commandSource["commands"] as? [String], !commands.isEmpty else {
            throw ScenarioHarnessError.missing("frozen command inventory")
        }
        guard let cancelMode = (selected["cancelMode"] as? String) ?? (base["cancelMode"] as? String) else {
            throw ScenarioHarnessError.missing("frozen cancellation mode")
        }
        guard cancelMode == configuration.cancelMode else {
            throw ScenarioHarnessError.invalid("launch cancelMode disagrees with the hashed inventory")
        }
        let actions = (selected["controlActions"] as? [[String: Any]])
            ?? (base["controlActions"] as? [[String: Any]]) ?? []
        let orderRows = (selected["receiptProbeOrder"] as? [[Any]])
            ?? (base["receiptProbeOrder"] as? [[Any]]) ?? []
        var order: [(command: String, probeID: String)] = []
        for pair in orderRows {
            guard pair.count == 2, let command = pair[0] as? String, let probeID = pair[1] as? String else {
                throw ScenarioHarnessError.invalid("receiptProbeOrder entry")
            }
            order.append((command, probeID))
        }
        let requiredProbes = (selected["requiredProbes"] as? [String])
            ?? (base["requiredProbes"] as? [String]) ?? []
        let requiredViews = (selected["requiredRenderedViews"] as? [String])
            ?? (base["requiredRenderedViews"] as? [String]) ?? []
        let releaseAfterCommand = (selected["releaseAfterCommand"] as? String)
            ?? (base["releaseAfterCommand"] as? String)
        let releaseAfterProbes = (selected["releaseAfterProbes"] as? [String])
            ?? (base["releaseAfterProbes"] as? [String]) ?? []
        let queuedOrder = (selected["queuedOrder"] as? [String])
            ?? (base["queuedOrder"] as? [String]) ?? []
        let barrierPoint = (selected["barrier"] as? String)
            ?? (base["barrier"] as? String)
        let assertNoLaterReceipt = (selected["assertNoLaterReceiptBeforeRelease"] as? Bool)
            ?? (base["assertNoLaterReceiptBeforeRelease"] as? Bool) ?? false
        let controls = (selected["controls"] as? [String])
            ?? (base["controls"] as? [String]) ?? []
        let storeFault = (selected["fault"] as? String)
            ?? (base["fault"] as? String)
        let replayCount = (selected["replayCount"] as? Int)
            ?? (base["replayCount"] as? Int) ?? 0
        let effects = (selected["effects"] as? [[String: Any]])
            ?? (base["effects"] as? [[String: Any]]) ?? []
        guard replayCount >= 0,
              (replayCount > 0) == controls.contains("replayLastCompletion") else {
            throw ScenarioHarnessError.invalid("replayCount and frozen control list disagree")
        }
        let declaredEffectIDs = effects.compactMap { $0["effectId"] as? String }
        let awaitedEffectIDs = actions.compactMap { action -> String? in
            guard action["action"] as? String == "awaitDetachedEffect" else { return nil }
            return action["effectId"] as? String
        }
        guard declaredEffectIDs.count == effects.count,
              Set(declaredEffectIDs).count == declaredEffectIDs.count,
              Set(awaitedEffectIDs) == Set(declaredEffectIDs),
              awaitedEffectIDs.count == declaredEffectIDs.count,
              actions.allSatisfy({
                  guard let name = $0["action"] as? String else { return false }
                  if name == "awaitDetachedEffect" { return Set($0.keys) == Set(["action", "effectId"]) }
                  return true
              }) else {
            throw ScenarioHarnessError.invalid("every detached effect requires exactly one frozen await action")
        }
        for action in actions where action["action"] as? String == "injectStoreFault" {
            guard Set(action.keys) == Set(["action", "fault", "command"]),
                  let fault = action["fault"] as? String,
                  ["replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"].contains(fault),
                  let command = action["command"] as? String,
                  commands.contains(command),
                  storeFaultAppliesToCommand(fault, command: command, isDelivery: command.hasPrefix("Deliver("), replayDelivery: command.hasPrefix("Deliver(replay,")) else {
                throw ScenarioHarnessError.invalid("store fault action must name its frozen target command")
            }
        }
        return SelectedScenario(
            commands: commands,
            cancelMode: cancelMode,
            controlActions: actions,
            receiptProbeOrder: order,
            requiredProbes: requiredProbes,
            requiredRenderedViews: requiredViews,
            releaseAfterCommand: releaseAfterCommand,
            releaseAfterProbes: releaseAfterProbes,
            queuedOrder: queuedOrder,
            barrierPoint: barrierPoint,
            assertNoLaterReceiptBeforeRelease: assertNoLaterReceipt,
            declaredControls: controls,
            storeFault: storeFault,
            replayCount: replayCount,
            effects: effects
        )
    }
}

private final class CheckpointResponseBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: (Data?, URLResponse?, Error?)?

    func set(data: Data?, response: URLResponse?, error: Error?) {
        lock.lock()
        stored = (data, response, error)
        lock.unlock()
    }

    func get() -> (Data?, URLResponse?, Error?)? {
        lock.lock()
        defer { lock.unlock() }
        return stored
    }
}

final class ScenarioUITests: XCTestCase {
    private let actionTimeout: TimeInterval = 45
    private var probeIDsByProcess: [String: Set<String>] = [:]

    func testCommandLabelsSupportReplayAndPausedQueueSameSemantics() {
        assertCommandLabelContract()
    }

    func testApp11FastFifoDrainUsesOneFinalReceiptHighWater() throws {
        let processID = "attempt-11/APP-11/p1"
        let previousID: Int64 = 3
        let target = try app11FinalQueuedReceipt(
            deliveryCommandID: 4,
            queuedOrder: ["Logout", "Login(B)"]
        )
        XCTAssertEqual(target, App11FinalQueuedReceipt(command: "Login(B)", commandID: 6))

        let atBarrier: [String: Any] = [
            "version": 1,
            "processInstanceId": processID,
            "launchOrdinal": 1,
            "controlRevision": 3,
            "storeIoActive": false,
            "lastProcessedCommandRef": ["processInstanceId": processID, "id": 3],
        ]
        let fastDrain: [String: Any] = [
            "version": 1,
            "processInstanceId": processID,
            "launchOrdinal": 1,
            "controlRevision": 6,
            "storeIoActive": false,
            "lastProcessedCommandRef": ["processInstanceId": processID, "id": 6],
        ]
        XCTAssertEqual(
            try processedHighWaterDecision(
                snapshot: atBarrier,
                expectedFinalID: target.commandID,
                previousID: previousID,
                processInstanceID: processID
            ),
            .waiting
        )
        XCTAssertEqual(
            try processedHighWaterDecision(
                snapshot: fastDrain,
                expectedFinalID: target.commandID,
                previousID: previousID,
                processInstanceID: processID
            ),
            .reached(6)
        )
        XCTAssertThrowsError(
            try processedHighWaterDecision(
                snapshot: ["lastProcessedCommandRef": ["processInstanceId": processID, "id": 7]],
                expectedFinalID: target.commandID,
                previousID: previousID,
                processInstanceID: processID
            )
        )
        XCTAssertThrowsError(
            try processedHighWaterDecision(
                snapshot: ["lastProcessedCommandRef": ["processInstanceId": "other/APP-11/p1", "id": 6]],
                expectedFinalID: target.commandID,
                previousID: previousID,
                processInstanceID: processID
            )
        )
    }

    func testLiveControllerStatusCheckpointRelay() throws {
        // Plumbing-only: this checks XCUITest stdout relay and the host checkpoint bridge.
        // It does not exercise candidate authentication, storage, HTTP, or APP acceptance.
        let configuration = try ScenarioLaunchConfiguration(environment: ProcessInfo.processInfo.environment)
        let app = XCUIApplication()
        app.launchArguments = configuration.appLaunchArguments
        app.launchEnvironment = configuration.appLaunchEnvironment
        app.launch()
        guard app.descendants(matching: .any)["session-state"].firstMatch.waitForExistence(timeout: actionTimeout) else {
            throw ScenarioHarnessError.missing("scaffold session-state for status relay smoke")
        }

        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "screen-relay-smoke"
        screenshot.lifetime = .keepAlways
        add(screenshot)

        // Use an already-declared checkpoint; this plumbing fixture does not
        // perform or claim the storage observation named by that checkpoint.
        let scenario = try SelectedScenario.load(configuration: configuration)
        guard let probeID = scenario.requiredProbes.first else {
            throw ScenarioHarnessError.missing("declared checkpoint for relay smoke")
        }
        let checkpoint = "storeProbe.\(probeID)"
        postControllerStatus(configuration, checkpoint: checkpoint, phase: "end", command: nil)
        try waitForHostProbeCheckpoint(configuration, name: checkpoint)
    }

    func testFailedLogoutAliasUsesLogoutButtonAndDeclaredClearFault() {
        XCTAssertTrue(isLogoutCommand("Logout(failed)"))
        XCTAssertEqual(logoutButtonIdentifier("Logout(failed)"), "logout")
        XCTAssertTrue(storeFaultAppliesToCommand("clearBefore", command: "Logout(failed)", isDelivery: false, replayDelivery: false))
        XCTAssertTrue(storeFaultAppliesToCommand("clearAfterBeforeVerify", command: "Logout(failed)", isDelivery: false, replayDelivery: false))
    }

    func testFrozenScenarioHarness() throws {
        let configuration = try ScenarioLaunchConfiguration(environment: ProcessInfo.processInfo.environment)
        let scenario = try SelectedScenario.load(configuration: configuration)
        let app = XCUIApplication()
        app.launchArguments = configuration.appLaunchArguments
        app.launchEnvironment = configuration.appLaunchEnvironment
        app.launch()
        guard app.descendants(matching: .any)["session-state"].firstMatch.waitForExistence(timeout: actionTimeout) else {
            throw ScenarioHarnessError.missing("visible session-state")
        }
        guard visibleText("view-process-id", in: app) == configuration.processInstanceID else {
            throw ScenarioHarnessError.invalid("rendered process identity disagrees with launch arguments")
        }

        var lastCommandID: Int64
        var releasedHooks = Set<String>()
        var processedCommandIDs: [String: Int64] = [:]
        var capturedProbes = Set<String>()
        if configuration.armPoint == "beforeBootstrapClear" {
            try waitForHookArrival("beforeBootstrapClear", in: app)
            postControllerStatus(
                configuration,
                checkpoint: "hookArrived.beforeBootstrapClear",
                phase: "hookArrived",
                command: nil,
                hookPoint: "beforeBootstrapClear",
                hookPhase: "arrived",
                hookTarget: "bootstrap",
                authMailboxPaused: true,
                bootstrapReceiptObserved: false,
                application: app
            )
            try captureStoreProbe("bootstrapStoreProbed", in: app, configuration: configuration)
            // The controller maps bootstrapStoreProbed to the one frozen pre-clear step;
            // record it so the final sweep does not capture that step ID a second time.
            if let preClear = scenario.requiredProbes.first(where: { $0.contains("before-bootstrap-clear") }) {
                capturedProbes.insert(preClear)
            }
            try tapRequired("hook-release-beforeBootstrapClear", in: app)
            releasedHooks.insert("beforeBootstrapClear")
            postControllerStatus(
                configuration,
                checkpoint: "hookReleased.beforeBootstrapClear",
                phase: "hookReleased",
                command: nil,
                hookPoint: "beforeBootstrapClear",
                hookPhase: "released",
                hookTarget: "bootstrap",
                authMailboxPaused: true,
                bootstrapReceiptObserved: false,
                application: app
            )
            lastCommandID = try waitForReceipt(expectedID: 1, previousID: nil, in: app)
        } else {
            // Bootstrap is submitted before the first screen appears; consume its
            // existing receipt rather than waiting for a second command.
            lastCommandID = try waitForReceipt(expectedID: 1, previousID: nil, in: app)
        }
        processedCommandIDs["Bootstrap"] = lastCommandID

        for action in scenario.controlActions where action["action"] as? String == "arm" {
            try applyControlAction(action, in: app)
        }
        if let barrier = scenario.barrierPoint { try armHook(barrier, target: "nextDelivery", in: app) }

        var completedCommands = Set<String>()
        var skippedCommandIndexes = Set<Int>()
        var faultIsActive = false
        var replayInvocations = 0
        for (index, command) in scenario.commands.enumerated() {
            if skippedCommandIndexes.contains(index) { continue }
            if command == "Bootstrap" {
                guard lastCommandID == 1 else { throw ScenarioHarnessError.invalid("Bootstrap was not command 1") }
                continue
            }
            let previousID = lastCommandID
            let expectedID = previousID + 1
            let isDelivery = command.hasPrefix("Deliver(")
            let replayDelivery = command.hasPrefix("Deliver(replay,")
            var replayActionID: Int64?
            let targetedFault = scenario.controlActions.first {
                $0["action"] as? String == "injectStoreFault" && $0["command"] as? String == command
            }
            let fault = targetedFault?["fault"] as? String ?? scenario.storeFault
            if let fault, !faultIsActive,
               (targetedFault != nil || storeFaultAppliesToCommand(fault, command: command, isDelivery: isDelivery, replayDelivery: replayDelivery)) {
                guard storeFaultAppliesToCommand(fault, command: command, isDelivery: isDelivery, replayDelivery: replayDelivery) else {
                    throw ScenarioHarnessError.invalid("store fault target command does not perform the matching operation")
                }
                try tapRequired("fault-set-\(fault)", in: app)
                faultIsActive = true
            }
            if command == "RetryCleanup", faultIsActive {
                let failedLogoutProbes = scenario.requiredProbes.filter { $0.contains("after-failed-logout") }
                guard !failedLogoutProbes.isEmpty, failedLogoutProbes.allSatisfy(capturedProbes.contains) else {
                    throw ScenarioHarnessError.invalid("RetryCleanup precedes its required failed-Logout probe")
                }
                try tapRequired("fault-set-none", in: app)
                faultIsActive = false
            }
            if replayDelivery {
                guard scenario.declaredControls.contains("replayLastCompletion") else {
                    throw ScenarioHarnessError.invalid("replay delivery is not declared by the frozen controls")
                }
                let (_, beforeReplay) = try readControlSnapshot(in: app, configuration: configuration)
                guard let previousRevision = (beforeReplay["controlRevision"] as? NSNumber)?.int64Value else {
                    throw ScenarioHarnessError.invalid("replay preflight snapshot has no control revision")
                }
                try tapRequired("replay-last", in: app)
                let (_, replayAck) = try waitForControlAction(app, configuration: configuration, after: previousRevision)
                replayActionID = (replayAck["lastActionId"] as? NSNumber)?.int64Value
                replayInvocations += 1
            }

            if isDelivery, let barrier = scenario.barrierPoint, !scenario.queuedOrder.isEmpty {
                postControllerStatus(configuration, checkpoint: "deliveryReleaseRequested", phase: "releaseRequested", command: command)
                try waitForEnqueued(expectedID: expectedID, in: app)
                try waitForHookArrival(barrier, in: app)
                postControllerStatus(
                    configuration,
                    checkpoint: "hookArrived.\(barrier)",
                    phase: "hookArrived",
                    command: command,
                    hookPoint: barrier,
                    hookPhase: "arrived",
                    hookTarget: "nextDelivery",
                    authMailboxPaused: true,
                    application: app
                )
                for (offset, queued) in scenario.queuedOrder.enumerated() {
                    let queuedIndex = index + offset + 1
                    guard scenario.commands.indices.contains(queuedIndex), scenario.commands[queuedIndex] == queued else {
                        throw ScenarioHarnessError.invalid("queuedOrder disagrees with frozen command positions")
                    }
                    let queuedID = expectedID + Int64(offset) + 1
                    try tapCommand(queued, in: app)
                    try waitForEnqueued(expectedID: queuedID, in: app)
                    skippedCommandIndexes.insert(queuedIndex)
                    if scenario.assertNoLaterReceiptBeforeRelease,
                       !(try currentCommandLabels(in: app).consumerHasNotCompleted(since: previousID)) {
                        throw ScenarioHarnessError.invalid("paused consumer processed a later command before hook release")
                    }
                }
                try tapRequired("hook-release-\(barrier)", in: app)
                releasedHooks.insert(barrier)
                postControllerStatus(
                    configuration,
                    checkpoint: "hookReleased.\(barrier)",
                    phase: "hookReleased",
                    command: command,
                    hookPoint: barrier,
                    hookPhase: "released",
                    hookTarget: "nextDelivery",
                    authMailboxPaused: true,
                    application: app
                )
                let finalReceipt = try app11FinalQueuedReceipt(
                    deliveryCommandID: expectedID,
                    queuedOrder: scenario.queuedOrder
                )
                lastCommandID = try waitForProcessedHighWater(
                    expectedID: finalReceipt.commandID,
                    previousID: previousID,
                    in: app,
                    configuration: configuration
                )
                completedCommands.insert(command)
                for queued in scenario.queuedOrder { completedCommands.insert(queued) }
                processedCommandIDs[finalReceipt.command] = lastCommandID
                postControllerStatus(
                    configuration,
                    checkpoint: "receipt.\(finalReceipt.commandID)",
                    phase: "receiptObserved",
                    command: finalReceipt.command
                )
                continue
            }

            if !replayDelivery && isDelivery {
                postControllerStatus(configuration, checkpoint: "deliveryReleaseRequested.\(expectedID)", phase: "releaseRequested", command: command)
            } else if !replayDelivery {
                try tapCommand(command, in: app)
            }
            try waitForEnqueued(expectedID: expectedID, in: app)
            if replayDelivery {
                guard let replayActionID, try currentCommandLabels(in: app).hasEnqueued(expectedID) else {
                    throw ScenarioHarnessError.invalid("replay action lacks its actual enqueued command identity")
                }
                postControllerStatus(
                    configuration,
                    checkpoint: "replayScheduled.\(expectedID)",
                    phase: "replayScheduled",
                    command: command,
                    replayActionId: String(replayActionID),
                    lastEnqueuedCommandId: String(expectedID)
                )
            }

            if isDelivery,
               let waitAction = scenario.controlActions.first(where: { $0["action"] as? String == "awaitArrival" }),
               let point = waitAction["point"] as? String {
                try waitForHookArrival(point, in: app)
                postControllerStatus(
                    configuration,
                    checkpoint: "hookArrived.\(point)",
                    phase: "hookArrived",
                    command: command,
                    hookPoint: point,
                    hookPhase: "arrived",
                    hookTarget: "nextDelivery",
                    authMailboxPaused: true,
                    application: app
                )
                if let probe = scenario.requiredProbes.first(where: { !capturedProbes.contains($0) && !$0.contains("final") }) {
                    try captureStoreProbe(probe, in: app, configuration: configuration)
                    capturedProbes.insert(probe)
                }
                if scenario.requiredRenderedViews.contains(where: { $0.contains("rendered-a1") }) {
                    if let rendered = attachRedactedUIEvidence(app, name: "render-at-barrier") {
                        for step in scenario.requiredRenderedViews where step.contains("rendered-a1") {
                            postControllerStatus(configuration, checkpoint: "renderedView.\(step)", phase: "rendered", command: command, renderedState: rendered)
                        }
                    }
                }
                try tapRequired("hook-release-\(point)", in: app)
                releasedHooks.insert(point)
                postControllerStatus(
                    configuration,
                    checkpoint: "hookReleased.\(point)",
                    phase: "hookReleased",
                    command: command,
                    hookPoint: point,
                    hookPhase: "released",
                    hookTarget: "nextDelivery",
                    authMailboxPaused: true,
                    application: app
                )
            }

            lastCommandID = try waitForReceipt(expectedID: expectedID, previousID: previousID, in: app)
            processedCommandIDs[command] = lastCommandID
            completedCommands.insert(command)
            _ = attachRedactedUIEvidence(app, name: "command-\(index + 1)-\(safeName(command))")
            postControllerStatus(configuration, checkpoint: "receipt.\(expectedID)", phase: "receiptObserved", command: command)
            for probe in scenario.receiptProbeOrder.filter({ $0.command == command }) {
                try captureStoreProbe(probe.probeID, in: app, configuration: configuration)
                capturedProbes.insert(probe.probeID)
            }
            if isLogoutCommand(command) {
                for probe in scenario.requiredProbes.filter({ $0.contains("after-failed-logout") && !capturedProbes.contains($0) }) {
                    try captureStoreProbe(probe, in: app, configuration: configuration)
                    capturedProbes.insert(probe)
                }
            }
            if command == "RetryCleanup" {
                for probe in scenario.requiredProbes.filter({ $0.contains("after-retry") && !capturedProbes.contains($0) }) {
                    try captureStoreProbe(probe, in: app, configuration: configuration)
                    capturedProbes.insert(probe)
                }
            }
            for action in scenario.controlActions where action["action"] as? String == "awaitArrival" {
                guard let point = action["point"] as? String else { throw ScenarioHarnessError.invalid("awaitArrival point") }
                if hookArrivalCommand(point) == command {
                    try waitForHookArrival(point, in: app)
                    let target = scenario.controlActions.first(where: { $0["action"] as? String == "arm" && $0["point"] as? String == point })?["target"] as? String ?? "nextCommand"
                    postControllerStatus(
                        configuration,
                        checkpoint: "hookArrived.\(point)",
                        phase: "hookArrived",
                        command: command,
                        hookPoint: point,
                        hookPhase: "arrived",
                        hookTarget: target,
                        authMailboxPaused: true,
                        application: app
                    )
                }
            }
            if scenario.requiredRenderedViews.contains(where: { renderStep($0, matches: command) }) {
                if let rendered = attachRedactedUIEvidence(app, name: "render-\(index + 1)-\(safeName(command))") {
                    for step in scenario.requiredRenderedViews where renderStep(step, matches: command) {
                        postControllerStatus(configuration, checkpoint: "renderedView.\(step)", phase: "rendered", command: command, renderedState: rendered)
                    }
                }
            }
            if scenario.releaseAfterCommand == command {
                guard scenario.releaseAfterProbes.allSatisfy(capturedProbes.contains) else {
                    throw ScenarioHarnessError.invalid("server release precedes a frozen immediate probe")
                }
                postControllerStatus(configuration, checkpoint: "serverReleaseReady.\(expectedID)", phase: "releaseReady", command: command)
            }
        }

        guard replayInvocations == scenario.replayCount else {
            throw ScenarioHarnessError.invalid("observed replay count disagrees with frozen replayCount")
        }
        for action in scenario.controlActions {
            switch action["action"] as? String {
            case "release":
                guard let point = action["point"] as? String else { throw ScenarioHarnessError.invalid("release point") }
                if !releasedHooks.contains(point) {
                    try tapRequired("hook-release-\(point)", in: app)
                    releasedHooks.insert(point)
                    let target = scenario.controlActions.first(where: { $0["action"] as? String == "arm" && $0["point"] as? String == point })?["target"] as? String ?? "nextCommand"
                    postControllerStatus(
                        configuration,
                        checkpoint: "hookReleased.\(point)",
                        phase: "hookReleased",
                        command: nil,
                        hookPoint: point,
                        hookPhase: "released",
                        hookTarget: target,
                        authMailboxPaused: true,
                        application: app
                    )
                }
            case "awaitDetachedEffect":
                guard let effectID = action["effectId"] as? String,
                      let effect = scenario.effects.first(where: { $0["effectId"] as? String == effectID }),
                      let origin = effect["originCommandRef"] as? [String: Any],
                      let launchOrdinal = origin["launchOrdinal"] as? Int,
                      launchOrdinal == configuration.launchOrdinal,
                      let originCommand = origin["command"] as? String,
                      let originID = processedCommandIDs[originCommand] else {
                    throw ScenarioHarnessError.invalid("detached effect origin command has no observed receipt")
                }
                let originReference: [String: Any] = [
                    "processInstanceId": configuration.processInstanceID,
                    "id": originID,
                ]
                guard let originData = try? JSONSerialization.data(withJSONObject: originReference, options: [.sortedKeys]),
                      let originJSON = String(data: originData, encoding: .utf8) else {
                    throw ScenarioHarnessError.invalid("detached effect origin reference could not be encoded")
                }
                let checkpoint = "detachedEffectAwaited.\(effectID)"
                postControllerStatus(
                    configuration,
                    checkpoint: checkpoint,
                    phase: "effectAwaitRequested",
                    command: nil,
                    effectId: effectID,
                    effectOriginCommandRef: originJSON
                )
                try waitForHostProbeCheckpoint(configuration, name: checkpoint)
                attach(String: "detachedEffectAwaited effectId=\(effectID) originCommandId=\(originID)", name: "detached-effect-\(safeName(effectID))")
            default:
                break
            }
        }
        if scenario.declaredControls.contains("recreateView") {
            let processBefore = visibleText("view-process-id", in: app)
            let commandBefore = try currentCommandID(in: app)
            try tapRequired("recreate-view", in: app)
            guard visibleText("view-process-id", in: app) == processBefore,
                  try currentCommandID(in: app) == commandBefore else {
                throw ScenarioHarnessError.invalid("view recreation changed process identity or command progress")
            }
        }
        // A multi-launch seed process (APP-12 p1) records no scenario-level probe or
        // final rendered-view step; those step IDs belong to the resumed launch and
        // must be unique. Its per-process final screenshot is still attached.
        let isSeed = configuration.scenarioPhase == "seed"
        if !isSeed {
            for probeID in scenario.requiredProbes where !capturedProbes.contains(probeID) {
                try captureStoreProbe(probeID, in: app, configuration: configuration)
                capturedProbes.insert(probeID)
            }
        }
        if let rendered = attachRedactedUIEvidence(app, name: "final"), !isSeed {
            for step in scenario.requiredRenderedViews where step.contains("final") {
                postControllerStatus(configuration, checkpoint: "renderedView.\(step)", phase: "rendered", command: nil, renderedState: rendered)
            }
        }
        if configuration.scenarioID.hasPrefix("APP-12-"), configuration.launchOrdinal == 1 {
            postControllerStatus(configuration, checkpoint: "restartCheckpoint", phase: "restartCheckpoint", command: nil)
        }
        try finishProcessAndReport(app, configuration: configuration)
    }

    func testRunnerRejectsMissingFrozenInputs() {
        XCTAssertThrowsError(try ScenarioLaunchConfiguration(environment: [:]))
    }

    func testXcodeForwardsFrozenRunnerEnvironment() throws {
        let environment = ProcessInfo.processInfo.environment
        let configuration = try ScenarioLaunchConfiguration(environment: environment)
        XCTAssertEqual(environment["NATIVE_CONTRACT_SCENARIO_ID"], configuration.scenarioID)
        XCTAssertEqual(environment["NATIVE_CONTRACT_PROCESS_INSTANCE_ID"], configuration.processInstanceID)
        XCTAssertEqual(environment["NATIVE_CONTRACT_SCENARIO_INVENTORY_SHA256"], configuration.scenarioInventorySHA256)
        XCTAssertEqual(environment["NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256"], configuration.controlInventorySHA256)
    }

    func testRunnerRequiresSupportedCancellationMode() {
        var environment = [
            "NATIVE_CONTRACT_SCENARIO_ID": "APP-01",
            "NATIVE_CONTRACT_RUN_ID": "attempt-01",
            "NATIVE_CONTRACT_PROCESS_INSTANCE_ID": "attempt-01/APP-01/p1",
            "NATIVE_CONTRACT_LAUNCH_ORDINAL": "1",
            "NATIVE_CONTRACT_BASE_URL": "http://127.0.0.1:43217",
            "NATIVE_CONTRACT_SCENARIO_PHASE": "single",
            "NATIVE_CONTRACT_SCENARIO_INVENTORY_PATH": "/tmp/scenarios.json",
            "NATIVE_CONTRACT_SCENARIO_INVENTORY_SHA256": String(repeating: "a", count: 64),
            "NATIVE_CONTRACT_CONTROL_INVENTORY_PATH": "/tmp/control-scenarios.json",
            "NATIVE_CONTRACT_CONTROL_INVENTORY_SHA256": String(repeating: "b", count: 64),
        ]
        XCTAssertThrowsError(try ScenarioLaunchConfiguration(environment: environment))

        environment["NATIVE_CONTRACT_CANCEL_MODE"] = "platformDefault"
        XCTAssertThrowsError(try ScenarioLaunchConfiguration(environment: environment))

        environment["NATIVE_CONTRACT_CANCEL_MODE"] = "disabled"
        XCTAssertNoThrow(try ScenarioLaunchConfiguration(environment: environment))
    }

    private func tapCommand(_ command: String, in app: XCUIApplication) throws {
        let identifier: String
        switch command {
        case "Login(A)": identifier = "login-A"
        case "Login(A0)": identifier = "login-A"
        case "Login(B)": identifier = "login-B"
        case "Expire": identifier = "expire"
        case "Logout", "Logout(failed)": identifier = logoutButtonIdentifier(command)!
        case "RetryCleanup": identifier = "retry-cleanup"
        case "CancelRefresh": identifier = "cancel-refresh"
        case "Observe": identifier = "observe"
        default:
            if command.hasPrefix("Deliver(") { return }
            throw ScenarioHarnessError.invalid("unsupported frozen UI command \(command)")
        }
        try tapRequired(identifier, in: app)
    }

    private func tapRequired(_ identifier: String, in app: XCUIApplication) throws {
        let button = app.buttons[identifier]
        guard button.waitForExistence(timeout: actionTimeout) else {
            throw ScenarioHarnessError.missing("visible control \(identifier)")
        }
        button.tap()
    }

    private func waitForReceipt(expectedID: Int64, previousID: Int64?, in app: XCUIApplication) throws -> Int64 {
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            let labels = try? currentCommandLabels(in: app)
            if let labels {
                let current = labels.lastCompletedCommandID
                if current > expectedID {
                    throw ScenarioHarnessError.invalid("unexpected intervening receipt \(current); expected \(expectedID)")
                }
                let terminal = labels.lastCommandStatus
                if current == expectedID, current != previousID,
                   !["Pending", "Running", "Queued"].contains(terminal) {
                    return current
                }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("terminal receipt for command \(expectedID)")
    }

    private func waitForEnqueued(expectedID: Int64, in app: XCUIApplication) throws {
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            if let labels = try? currentCommandLabels(in: app) {
                let current = labels.lastEnqueuedCommandID
                if current > expectedID {
                    throw ScenarioHarnessError.invalid("unexpected intervening enqueue \(current); expected \(expectedID)")
                }
                if labels.hasEnqueued(expectedID) { return }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("enqueue for command \(expectedID)")
    }

    private func waitForProcessedHighWater(
        expectedID: Int64,
        previousID: Int64?,
        in app: XCUIApplication,
        configuration: ScenarioLaunchConfiguration
    ) throws -> Int64 {
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            if let (_, snapshot) = try? readControlSnapshot(in: app, configuration: configuration) {
                if case let .reached(current) = try processedHighWaterDecision(
                    snapshot: snapshot,
                    expectedFinalID: expectedID,
                    previousID: previousID,
                    processInstanceID: configuration.processInstanceID
                ) {
                    return current
                }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("processed high-water receipt \(expectedID)")
    }

    private func currentCommandID(in app: XCUIApplication) throws -> Int64 {
        try currentCommandLabels(in: app).lastCompletedCommandID
    }

    private func currentCommandLabels(in app: XCUIApplication) throws -> CommandLabels {
        try CommandLabels(
            lastCompletedID: visibleText("last-command-id", in: app),
            lastCommandStatus: visibleText("last-command-status", in: app),
            lastEnqueuedID: visibleText("last-enqueued-command-id", in: app)
        )
    }

    private func assertCommandLabelContract() {
        do {
            let replay = try CommandLabels(
                lastCompletedID: "3",
                lastCommandStatus: "Completed",
                lastEnqueuedID: "4"
            )
            XCTAssertTrue(replay.hasEnqueued(4))
            XCTAssertEqual(replay.lastCompletedCommandID, 3)

            let pausedWithQueuedCommands = try CommandLabels(
                lastCompletedID: "3",
                lastCommandStatus: "Completed",
                lastEnqueuedID: "5"
            )
            XCTAssertTrue(pausedWithQueuedCommands.consumerHasNotCompleted(since: 3))
            XCTAssertEqual(pausedWithQueuedCommands.lastEnqueuedCommandID, 5)
        } catch {
            XCTFail("frozen command label contract sample is invalid: \(error)")
        }
    }

    private func visibleText(_ identifier: String, in app: XCUIApplication) -> String {
        let element = app.descendants(matching: .any)[identifier].firstMatch
        guard element.exists else { return "" }
        // SwiftUI static text reports an empty-string value (not nil) on iOS 18;
        // only a nonempty string value overrides the accessibility label.
        if let value = element.value as? String, !value.isEmpty { return value }
        return element.label
    }

    private func finishProcessAndReport(_ app: XCUIApplication, configuration: ScenarioLaunchConfiguration) throws {
        try tapRequired("finish-process", in: app)
        var acknowledgementJSON: String?
        let deadline = Date().addingTimeInterval(min(actionTimeout, 15))
        while Date() < deadline {
            let raw = visibleText("process-end-ack-json", in: app)
            if let data = raw.data(using: .utf8),
               let ack = try? JSONDecoder().decode(HarnessProcessEndAck.self, from: data),
               ack.processInstanceId == configuration.processInstanceID,
               ack.eventRef.processInstanceId == configuration.processInstanceID,
               ack.eventRef.localSequence > 0 {
                acknowledgementJSON = raw
                break
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        guard let acknowledgementJSON else {
            throw ScenarioHarnessError.missing("Debug finishProcess did not return its process-bound terminal event reference")
        }
        postControllerStatus(
            configuration,
            checkpoint: "processEndAcknowledged",
            phase: "processEndAcknowledged",
            command: nil,
            processEndAckJSON: acknowledgementJSON
        )
        postControllerStatus(configuration, checkpoint: "scenarioHarnessFinished", phase: "end", command: nil)
    }

    private func waitForHookArrival(_ point: String, in app: XCUIApplication) throws {
        let state = app.staticTexts["hook-state-\(point)"]
        guard state.waitForExistence(timeout: actionTimeout) else {
            throw ScenarioHarnessError.missing("hook state \(point)")
        }
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            let stateText = (state.value as? String).flatMap { $0.isEmpty ? nil : $0 } ?? state.label
            if stateText.contains("arrived") { return }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("hook arrival \(point)")
    }

    private func readControlSnapshot(in app: XCUIApplication, configuration: ScenarioLaunchConfiguration) throws -> (String, [String: Any]) {
        let status = app.staticTexts["control-status-json"]
        // An empty-string value (iOS 18 SwiftUI static text) must not shadow the label.
        let candidates = [status.value as? String, status.label].compactMap { $0 }.filter { !$0.isEmpty }
        guard let raw = candidates.first(where: {
            $0.range(of: "(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)", options: .regularExpression) == nil
        }),
              let data = raw.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              value["version"] as? Int == 1,
              value["processInstanceId"] as? String == configuration.processInstanceID,
              value["launchOrdinal"] as? Int == configuration.launchOrdinal,
              value["controlRevision"] is NSNumber,
              value["storeIoActive"] is Bool else {
            throw ScenarioHarnessError.invalid("protected control snapshot is missing or malformed")
        }
        return (raw, value)
    }

    private func waitForControlAction(
        _ app: XCUIApplication,
        configuration: ScenarioLaunchConfiguration,
        after revision: Int64
    ) throws -> (String, [String: Any]) {
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            if let (raw, snapshot) = try? readControlSnapshot(in: app, configuration: configuration),
               let currentRevision = (snapshot["controlRevision"] as? NSNumber)?.int64Value,
               let actionID = (snapshot["lastActionId"] as? NSNumber)?.int64Value,
               snapshot["lastActionStatus"] as? String == "scheduled",
               currentRevision > revision, actionID > 0 {
                return (raw, snapshot)
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("fresh scheduled Debug control acknowledgement")
    }

    private func captureStoreProbe(
        _ probeID: String,
        in app: XCUIApplication,
        configuration: ScenarioLaunchConfiguration
    ) throws {
        let checkpointName = probeID == "bootstrapStoreProbed" ? probeID : "storeProbe.\(probeID)"
        let result = app.staticTexts["store-probe-result"]
        let processID = configuration.processInstanceID
        let (snapshotJSON, snapshot) = try readControlSnapshot(in: app, configuration: configuration)
        guard snapshot["storeIoActive"] as? Bool == false else {
            throw ScenarioHarnessError.invalid("independent probe requires a same-process idle control snapshot")
        }
        let previousProbeID = (snapshot["lastProbe"] as? [String: Any])?["probeId"] as? String
        postControllerStatus(
            configuration,
            checkpoint: checkpointName,
            phase: "probeRequested",
            command: nil,
            controlSnapshotJSON: snapshotJSON
        )
        var seenProbeIDs = probeIDsByProcess[processID] ?? []
        try tapRequired("probe-store", in: app)
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            let candidates = [result.value as? String, result.label].compactMap { $0 }.filter { !$0.isEmpty }
            if let resultRow = candidates.compactMap({ value -> (String, String)? in
                guard let nativeProbeID = validRedactedProbeEnvelope(value, expectedProcessInstanceID: processID) else {
                    return nil
                }
                return (value, nativeProbeID)
            }).first(where: { $0.1 != previousProbeID && !seenProbeIDs.contains($0.1) }) {
                let (value, nativeProbeID) = resultRow
                seenProbeIDs.insert(nativeProbeID)
                probeIDsByProcess[processID] = seenProbeIDs
                attach(String: "probeId=\(probeID) processInstanceId=\(configuration.processInstanceID) redactedResult=\(value)", name: "store-\(safeName(probeID))")
                postControllerStatus(configuration, checkpoint: checkpointName, phase: "probeCaptured", command: nil, redactedObservation: value)
                try waitForHostProbeCheckpoint(configuration, name: checkpointName)
                return
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        throw ScenarioHarnessError.missing("redacted store probe \(probeID)")
    }

    private func validRedactedProbeEnvelope(_ raw: String, expectedProcessInstanceID: String) -> String? {
        guard raw.range(of: "(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)", options: .regularExpression) == nil,
              let data = raw.data(using: .utf8),
              let envelope = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(envelope.keys) == Set(["probeId", "processInstanceId", "observation"]),
              let probeID = envelope["probeId"] as? String, !probeID.isEmpty,
              envelope["processInstanceId"] as? String == expectedProcessInstanceID,
              let observation = envelope["observation"] as? [String: Any],
              isRedactedStoreObservation(observation) else {
            return nil
        }
        return probeID
    }

    private func isRedactedStoreObservation(_ observation: [String: Any]) -> Bool {
        switch observation["kind"] as? String {
        case "Absent":
            return Set(observation.keys) == Set(["kind"])
        case "Present":
            guard Set(observation.keys) == Set(["kind", "account", "version"]),
                  let account = observation["account"] as? String,
                  ["A", "B"].contains(account),
                  let version = observation["version"] as? Int64 else {
                return false
            }
            return version >= 0
        case "Unknown":
            guard Set(observation.keys) == Set(["kind", "errorCode"]),
                  let errorCode = observation["errorCode"] as? String else {
                return false
            }
            return !errorCode.isEmpty
        default:
            return false
        }
    }

    @discardableResult
    private func attachRedactedUIEvidence(_ app: XCUIApplication, name: String) -> String? {
        let safeIdentifiers = [
            "session-state", "credential-status", "view-process-id", "view-revision",
            "last-command-id", "last-command-status", "control-status-json", "store-probe-result",
        ]
        let values = safeIdentifiers.reduce(into: [String: String]()) { result, identifier in
            let value = visibleText(identifier, in: app)
            if !value.isEmpty { result[identifier] = value }
        }
        let fieldText = safeIdentifiers.compactMap { identifier in
            values[identifier].map { "\(identifier)=\($0)" }
        }.joined(separator: "\n")
        if fieldText.range(of: "(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)", options: .regularExpression) != nil {
            XCTFail("visible UI contains a raw credential field; evidence attachment was suppressed")
            return nil
        }
        attach(String: fieldText, name: "ui-\(safeName(name))")
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "screen-\(safeName(name))"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        guard let data = try? JSONSerialization.data(withJSONObject: values, options: [.sortedKeys]),
              let serialized = String(data: data, encoding: .utf8) else {
            XCTFail("visible UI evidence could not be encoded as JSON")
            return nil
        }
        return serialized
    }

    private func postControllerStatus(
        _ configuration: ScenarioLaunchConfiguration,
        checkpoint: String,
        phase: String,
        command: String?,
        redactedObservation: String? = nil,
        controlSnapshotJSON: String? = nil,
        renderedState: String? = nil,
        hookPoint: String? = nil,
        hookPhase: String? = nil,
        hookTarget: String? = nil,
        authMailboxPaused: Bool? = nil,
        bootstrapReceiptObserved: Bool? = nil,
        deliverReceiptObserved: Bool? = nil,
        effectId: String? = nil,
        effectOriginCommandRef: String? = nil,
        replayActionId: String? = nil,
        lastEnqueuedCommandId: String? = nil,
        application: XCUIApplication? = nil,
        processEndAckJSON: String? = nil
    ) {
        let sensitive = "(?i)(accessToken|refreshToken|demo-[AB]-v[0-9]+)"
        if [redactedObservation, controlSnapshotJSON, renderedState, command, processEndAckJSON].compactMap({ $0 }).contains(where: {
            $0.range(of: sensitive, options: .regularExpression) != nil
        }) {
            XCTFail("controller progress record would contain raw credential data; record suppressed")
            return
        }
        var payload = [
            "scenarioId": configuration.scenarioID,
            "processInstanceId": configuration.processInstanceID,
            "checkpointName": checkpoint,
            "phase": phase,
            "command": command ?? "",
        ]
        if let redactedObservation {
            payload["redactedObservation"] = redactedObservation
        }
        if let controlSnapshotJSON {
            payload["controlSnapshotJSON"] = controlSnapshotJSON
        }
        if let renderedState {
            payload["renderedState"] = renderedState
        }
        if let hookPoint { payload["hookPoint"] = hookPoint }
        if let hookPhase { payload["hookPhase"] = hookPhase }
        if let hookTarget { payload["hookTarget"] = hookTarget }
        if let authMailboxPaused { payload["authMailboxPaused"] = String(authMailboxPaused) }
        if let bootstrapReceiptObserved { payload["bootstrapReceiptObserved"] = String(bootstrapReceiptObserved) }
        if let deliverReceiptObserved { payload["deliverReceiptObserved"] = String(deliverReceiptObserved) }
        if let effectId { payload["effectId"] = effectId }
        if let effectOriginCommandRef { payload["effectOriginCommandRef"] = effectOriginCommandRef }
        if let replayActionId { payload["replayActionId"] = replayActionId }
        if let lastEnqueuedCommandId { payload["lastEnqueuedCommandId"] = lastEnqueuedCommandId }
        if let processEndAckJSON { payload["processEndAckJSON"] = processEndAckJSON }
        if let hookPoint {
            guard let application else {
                XCTFail("hook status lacks its process-matched armSequence snapshot")
                return
            }
            let snapshotJSON = visibleText("control-status-json", in: application)
            guard !snapshotJSON.isEmpty,
                  let snapshotData = snapshotJSON.data(using: .utf8),
                  let snapshot = (try? JSONSerialization.jsonObject(with: snapshotData)) as? [String: Any],
                  let hooks = snapshot["hooks"] as? [[String: Any]],
                  let hook = hooks.first(where: { $0["point"] as? String == hookPoint }),
                  let phase = hook["phase"] as? String, phase == hookPhase,
                  let armSequence = hook["armSequence"] as? NSNumber,
                  armSequence.int64Value > 0 else {
                XCTFail("hook status lacks its process-matched armSequence snapshot")
                return
            }
            payload["hookArmSequence"] = armSequence.stringValue
        }
        let attachment = XCTAttachment(string: payload.keys.sorted().map { "\($0)=\(payload[$0]!)" }.joined(separator: "\n"))
        attachment.name = "controller-status-\(safeName(checkpoint))"
        attachment.lifetime = .keepAlways
        add(attachment)
        if let bytes = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
           let line = String(data: bytes, encoding: .utf8) {
            FileHandle.standardOutput.write(Data(("NATIVE_CONTRACT_STATUS_V1 \(line)\n").utf8))
        }
    }

    private func waitForHostProbeCheckpoint(
        _ configuration: ScenarioLaunchConfiguration,
        name: String
    ) throws {
        guard var components = URLComponents(string: configuration.baseURL) else {
            throw ScenarioHarnessError.invalid("baseURL cannot form a checkpoint URL")
        }
        components.path = "/v1/checkpoints"
        components.queryItems = [
            URLQueryItem(name: "runId", value: configuration.runID),
            URLQueryItem(name: "processInstanceId", value: configuration.processInstanceID),
            URLQueryItem(name: "name", value: name),
        ]
        guard let url = components.url else { throw ScenarioHarnessError.invalid("checkpoint URL is invalid") }
        let deadline = Date().addingTimeInterval(actionTimeout)
        while Date() < deadline {
            let semaphore = DispatchSemaphore(value: 0)
            let responseBox = CheckpointResponseBox()
            URLSession.shared.dataTask(with: url) { data, response, error in
                responseBox.set(data: data, response: response, error: error)
                semaphore.signal()
            }.resume()
            guard semaphore.wait(timeout: .now() + 5) == .success,
                  let (data, response, error) = responseBox.get(), error == nil,
                  let http = response as? HTTPURLResponse else {
                throw ScenarioHarnessError.missing("host probe checkpoint response for \(name)")
            }
            guard http.statusCode == 200, let data,
                  let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  body["version"] as? Int == 1 else {
                throw ScenarioHarnessError.invalid("host rejected the frozen probe checkpoint \(name)")
            }
            if body["ready"] as? Bool == true { return }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        throw ScenarioHarnessError.missing("host did not complete independent probe \(name)")
    }

    private func renderStep(_ step: String, matches command: String) -> Bool {
        if step.contains("final") { return false }
        let needle: String
        switch command {
        case "Login(A)": needle = "login-a"
        case "Login(A0)": needle = "login-a"
        case "Login(B)": needle = "login-b"
        case "CancelRefresh": needle = "cancel"
        default: needle = command.lowercased().replacingOccurrences(of: " ", with: "-")
        }
        return step.lowercased().contains("after-\(needle)")
    }

    private func armHook(_ point: String, target: String, in app: XCUIApplication) throws {
        try tapRequired("hook-target-\(target)", in: app)
        try tapRequired("hook-arm-\(point)", in: app)
    }

    private func applyControlAction(_ action: [String: Any], in app: XCUIApplication) throws {
        switch action["action"] as? String {
        case "arm":
            guard let point = action["point"] as? String, let target = action["target"] as? String else {
                throw ScenarioHarnessError.invalid("arm action is incomplete")
            }
            try armHook(point, target: target, in: app)
        case "injectStoreFault":
            guard let fault = action["fault"] as? String else { throw ScenarioHarnessError.invalid("fault action is incomplete") }
            try tapRequired("fault-set-\(fault)", in: app)
        default:
            break
        }
    }

    private func hookArrivalCommand(_ point: String) -> String? {
        switch point {
        case "beforeDeferredControlClear": "Logout"
        default: nil
        }
    }

    private func safeName(_ value: String) -> String {
        value.unicodeScalars.map { CharacterSet.alphanumerics.contains($0) ? String($0) : "-" }.joined()
    }

    private func attach(String value: String, name: String) {
        let attachment = XCTAttachment(string: value)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
