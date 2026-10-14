import Foundation
import SwiftUI

@MainActor
final class DemoViewModel: ObservableObject, ViewPublisher {
    @Published private(set) var current: DemoViewState
    @Published private(set) var storeObservation: StoreObservation = .unknown(errorCode: "notRead")
    @Published private(set) var startupError: String?

    private weak var coordinator: SessionCoordinator?

#if DEBUG
    private(set) var debugControl: DefaultDebugScenarioControl?
    @Published private(set) var controlSnapshotJSON = "{}"
    @Published private(set) var probeResultJSON = "{}"
    @Published private(set) var processEndAckJSON = ""
    @Published private(set) var controlError: String?
    @Published private(set) var lastEnqueuedCommandID = ""
#endif

    init(process: ProcessContext) {
        current = DemoViewState(
            processInstanceId: process.processInstanceId,
            revision: 0,
            phase: .booting,
            account: nil,
            credentialVersion: nil,
            pendingRequestId: nil,
            lastCompletedCommandId: nil,
            lastCommandStatus: nil
        )
    }

    @MainActor
    func publish(_ view: DemoViewState, store: StoreObservation) async {
        guard view.processInstanceId == current.processInstanceId,
              view.revision > current.revision else { return }
        current = view
        storeObservation = store
    }

    func attach(_ coordinator: SessionCoordinator) {
        self.coordinator = coordinator
    }

    /// The store label follows publications only: a receipt can arrive after a newer
    /// publication (for example an HTTP completion) and would roll the label back.
    func submit(_ command: AppCommand) {
        guard let coordinator else { return }
        Task { [coordinator] in
            _ = await coordinator.submit(command)
        }
    }

    func setStartupError(_ error: Error) {
        startupError = String(describing: error)
    }

    /// Frozen session-state labels: authenticated phases append the redacted
    /// account label (`Signed in demo-A`); others never name an account.
    var sessionLabel: String {
        guard !accountLabel.isEmpty else { return current.phase.userLabel }
        return "\(current.phase.userLabel) \(accountLabel)"
    }

    var accountLabel: String {
        guard current.phase == .signedIn || current.phase == .refreshing,
              let account = current.account else { return "" }
        return account.label
    }

    var credentialStatusLabel: String {
        switch storeObservation {
        case .absent:
            "Credentials absent"
        case let .present(_, version):
            "Credentials version \(version)"
        case .unknown:
            "Credentials unknown"
        }
    }

#if DEBUG
    func attachDebugControl(_ control: DefaultDebugScenarioControl) {
        debugControl = control
        refreshControlSnapshot()
    }

    func refreshControlSnapshot() {
        guard let snapshot = debugControl?.snapshot(),
              let data = try? JSONEncoder().encode(snapshot),
              let json = String(data: data, encoding: .utf8) else { return }
        controlSnapshotJSON = json
        lastEnqueuedCommandID = snapshot.lastEnqueuedCommandRef.map { String($0.id) } ?? ""
        if let probe = snapshot.lastProbe,
           let probeData = try? JSONEncoder().encode(probe),
           let probeJSON = String(data: probeData, encoding: .utf8) {
            probeResultJSON = probeJSON
        }
    }

    func performControl(_ operation: @escaping @Sendable (DefaultDebugScenarioControl) throws -> Void) {
        guard let debugControl else { return }
        do {
            try operation(debugControl)
            refreshControlSnapshot()
            controlError = nil
        } catch {
            controlError = String(describing: error)
        }
    }

    func probeStore() {
        guard let debugControl else { return }
        Task { [weak self, debugControl] in
            do {
                let probe = try await debugControl.probeStore()
                guard let self,
                      let data = try? JSONEncoder().encode(probe),
                      let json = String(data: data, encoding: .utf8) else { return }
                probeResultJSON = json
                refreshControlSnapshot()
                controlError = nil
            } catch {
                self?.controlError = String(describing: error)
            }
        }
    }

    func finishProcess() {
        guard let debugControl else { return }
        Task { [weak self, debugControl] in
            do {
                let acknowledgement = try await debugControl.finishProcess(timeoutMillis: 30_000)
                guard let self,
                      let data = try? JSONEncoder().encode(acknowledgement),
                      let json = String(data: data, encoding: .utf8) else { return }
                processEndAckJSON = json
                refreshControlSnapshot()
                controlError = nil
            } catch {
                self?.controlError = String(describing: error)
                self?.refreshControlSnapshot()
            }
        }
    }
#endif
}
