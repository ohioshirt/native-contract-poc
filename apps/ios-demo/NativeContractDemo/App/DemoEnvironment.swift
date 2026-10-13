import Foundation
import SwiftUI

struct DemoLaunchParameters {
    let process: ProcessContext
    let runId: String
    let baseURL: URL
    let cancelTransportOnCancelRefresh: Bool
    let armPoint: HookPoint?
#if DEBUG
    let armTarget: HookTarget?
    let storeFault: StoreFaultKind?
#endif
    let service: String

    static func load(arguments: [String]) throws -> DemoLaunchParameters {
        var values: [String: String] = [:]
        var index = 1
        while index < arguments.count {
            let key = arguments[index]
            guard key.hasPrefix("--"), index + 1 < arguments.count else {
                throw DemoLaunchError.invalidArguments
            }
            values[key] = arguments[index + 1]
            index += 2
        }

        let runId = values["--run-id"] ?? "manual-\(UUID().uuidString)"
        let scenarioId = values["--scenario-id"] ?? "manual"
        let launchOrdinal = Int64(values["--launch-ordinal"] ?? "1") ?? 0
        let attemptId: String
        let processInstanceId: String
        if let supplied = values["--process-instance-id"] {
            let components = supplied.split(separator: "/", omittingEmptySubsequences: false)
            guard components.count == 3,
                  components[1] == Substring(scenarioId),
                  components[2] == Substring("p\(launchOrdinal)") else {
                throw DemoLaunchError.invalidArguments
            }
            attemptId = String(components[0])
            processInstanceId = supplied
        } else {
            attemptId = "manual-\(UUID().uuidString)"
            processInstanceId = "\(attemptId)/\(scenarioId)/p1"
        }
        guard launchOrdinal > 0,
              isLabel(attemptId), isLabel(scenarioId), isLabel(runId),
              let baseURL = URL(string: values["--base-url"] ?? "http://127.0.0.1:8080"),
              let components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              components.scheme == "http", components.host != nil,
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              components.path.isEmpty || components.path == "/" else {
            throw DemoLaunchError.invalidArguments
        }
        let cancelMode = values["--cancel-mode"] ?? "enabled"
        guard cancelMode == "enabled" || cancelMode == "disabled" else {
            throw DemoLaunchError.invalidArguments
        }

        let armPoint: HookPoint?
#if DEBUG
        let armTarget: HookTarget?
        let storeFault: StoreFaultKind?
        if let rawPoint = values["--arm"], let rawTarget = values["--arm-target"] {
            guard let point = HookPoint(rawValue: rawPoint), let target = HookTarget(rawValue: rawTarget) else {
                throw DemoLaunchError.invalidArguments
            }
            armPoint = point
            armTarget = target
        } else if values["--arm"] == nil, values["--arm-target"] == nil {
            armPoint = nil
            armTarget = nil
        } else {
            throw DemoLaunchError.invalidArguments
        }
        if let rawFault = values["--store-fault"] {
            guard let parsedFault = StoreFaultKind(rawValue: rawFault) else {
                throw DemoLaunchError.invalidArguments
            }
            storeFault = parsedFault
        } else {
            storeFault = nil
        }
#else
        _ = values["--arm"]
        _ = values["--arm-target"]
#endif

#if DEBUG
        let service = StorageProbe.testingService(attemptId: attemptId, scenarioId: scenarioId)
            ?? "native-contract-demo.credentials"
#else
        let service = "native-contract-demo.credentials"
#endif
        let process = ProcessContext(
            processInstanceId: processInstanceId,
            launchOrdinal: launchOrdinal,
            attemptId: attemptId,
            scenarioId: scenarioId
        )
#if DEBUG
        return DemoLaunchParameters(
            process: process,
            runId: runId,
            baseURL: baseURL,
            cancelTransportOnCancelRefresh: cancelMode == "enabled",
            armPoint: armPoint,
            armTarget: armTarget,
            storeFault: storeFault,
            service: service
        )
#else
        return DemoLaunchParameters(
            process: process,
            runId: runId,
            baseURL: baseURL,
            cancelTransportOnCancelRefresh: cancelMode == "enabled",
            armPoint: nil,
            service: service
        )
#endif
    }

    private static func isLabel(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) || ($0 >= 97 && $0 <= 122) || $0 == 45 || $0 == 95
        }
    }
}

@MainActor
final class DemoEnvironment: ObservableObject {
    let viewModel: DemoViewModel
    private var coordinator: SessionCoordinator?
    private var startupTask: Task<Void, Never>?

    init() {
        let launch: DemoLaunchParameters
        do {
            launch = try DemoLaunchParameters.load(arguments: CommandLine.arguments)
        } catch {
            let process = ProcessContext(
                processInstanceId: "startup/failed/p1",
                launchOrdinal: 1,
                attemptId: "startup",
                scenarioId: "failed"
            )
            let model = DemoViewModel(process: process)
            viewModel = model
            model.setStartupError(error)
            return
        }
        let model = DemoViewModel(process: launch.process)
        viewModel = model
        do { try start(launch, viewModel: model) }
        catch { model.setStartupError(error) }
    }

    private func start(_ launch: DemoLaunchParameters, viewModel: DemoViewModel) throws {
        let store = try KeychainCredentialStore(service: launch.service)

#if DEBUG
        let documents = try FileManager.default.url(
            for: .documentDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let auditURL = documents
            .appendingPathComponent("native-harness", isDirectory: true)
            .appendingPathComponent(launch.process.attemptId, isDirectory: true)
            .appendingPathComponent(launch.process.scenarioId, isDirectory: true)
            .appendingPathComponent("p\(launch.process.launchOrdinal)", isDirectory: true)
            .appendingPathComponent("native-events.jsonl")
        let audit = try JSONLAuditRecorder(fileURL: auditURL, processInstanceId: launch.process.processInstanceId, launchOrdinal: launch.process.launchOrdinal)
        let revisionClock = ControlRevisionClock()
        let hooks = DebugScenarioHooks(process: launch.process, audit: audit, revisionClock: revisionClock)
        let auditedStore = AuditedCredentialStore(base: store, audit: audit, storeIOChanged: hooks.storeIOChanged)
        let ingress = DemoIngress()
        let transport = URLSessionRefreshTransport(
            baseURL: launch.baseURL,
            runId: launch.runId,
            onCompletionCaptured: { ingress.capture($0) }
        )
        let coordinator = SessionCoordinator(
            process: launch.process,
            store: auditedStore,
            transport: transport,
            publisher: viewModel,
            hooks: hooks,
            audit: audit,
            cancelTransportOnCancelRefresh: launch.cancelTransportOnCancelRefresh
        )
        self.coordinator = coordinator
        ingress.attach(coordinator)
        let control = DefaultDebugScenarioControl(
            process: launch.process,
            coordinator: coordinator,
            store: auditedStore,
            hooks: hooks,
            ingress: ingress,
            service: launch.service,
            revisionClock: revisionClock
        )
        viewModel.attach(coordinator)
        viewModel.attachDebugControl(control)
        startupTask = Task { [weak viewModel] in
            do {
                try await coordinator.start()
                try control.installLaunchControls(armPoint: launch.armPoint, armTarget: launch.armTarget, storeFault: launch.storeFault)
                let receipt = await coordinator.submit(.bootstrap)
                viewModel?.updateStoreObservation(receipt.observation.store)
            } catch {
                viewModel?.setStartupError(error)
            }
        }
#else
        let coordinator = SessionCoordinator(
            process: launch.process,
            store: store,
            transport: URLSessionRefreshTransport(baseURL: launch.baseURL, runId: launch.runId),
            publisher: viewModel,
            hooks: NoopScenarioHooks(),
            audit: NoopAuditRecorder(),
            cancelTransportOnCancelRefresh: launch.cancelTransportOnCancelRefresh
        )
        self.coordinator = coordinator
        viewModel.attach(coordinator)
        startupTask = Task { [weak viewModel] in
            do {
                try await coordinator.start()
                let receipt = await coordinator.submit(.bootstrap)
                viewModel?.updateStoreObservation(receipt.observation.store)
            } catch {
                viewModel?.setStartupError(error)
            }
        }
#endif
    }
}

private enum DemoLaunchError: Error {
    case invalidArguments
}
