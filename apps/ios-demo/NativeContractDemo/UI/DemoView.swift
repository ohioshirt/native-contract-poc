import SwiftUI

struct DemoView: View {
    @ObservedObject var model: DemoViewModel
    /// Changing this identity tears down and rebuilds the content subtree while
    /// the same view model, coordinator and slots stay alive (APP-14).
    @State private var contentGeneration = 0

    var body: some View {
        VStack(spacing: 0) {
#if DEBUG
            Button("Recreate view") { contentGeneration += 1 }
                .accessibilityIdentifier("recreate-view")
#endif
            DemoContentView(model: model)
                .id(contentGeneration)
        }
    }
}

private struct DemoContentView: View {
    @ObservedObject var model: DemoViewModel

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Text(model.sessionLabel)
                    .font(.title2.weight(.semibold))
                    .accessibilityIdentifier("session-state")
                Text(model.credentialStatusLabel)
                    .accessibilityIdentifier("credential-status")
                Text(model.accountLabel)
                    .accessibilityIdentifier("account-label")
                Text(model.current.processInstanceId)
                    .accessibilityIdentifier("view-process-id")
                Text(String(model.current.revision))
                    .accessibilityIdentifier("view-revision")
                Text(model.current.lastCompletedCommandId.map(String.init) ?? "")
                    .accessibilityIdentifier("last-command-id")
                Text(model.current.lastCommandStatus?.rawValue ?? "")
                    .accessibilityIdentifier("last-command-status")

                if model.current.phase == .faultLocked {
                    Text("Cleanup failed")
                        .accessibilityIdentifier("cleanup-error")
                }
                if let startupError = model.startupError {
                    Text(startupError)
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("startup-error")
                }

                HStack {
                    Button("Login A") { model.submit(.login(.a)) }
                        .accessibilityIdentifier("login-A")
                    Button("Login B") { model.submit(.login(.b)) }
                        .accessibilityIdentifier("login-B")
                }
                HStack {
                    Button("Expire token") { model.submit(.expire) }
                        .accessibilityIdentifier("expire")
                    Button("Logout") { model.submit(.logout) }
                        .accessibilityIdentifier("logout")
                }
                HStack {
                    Button("Cancel refresh") { model.submit(.cancelRefresh) }
                        .accessibilityIdentifier("cancel-refresh")
                    Button("Retry cleanup") { model.submit(.retryCleanup) }
                        .accessibilityIdentifier("retry-cleanup")
                    Button("Observe") { model.submit(.observe) }
                        .accessibilityIdentifier("observe")
                }

#if DEBUG
                if let control = model.debugControl {
                    DebugControlPanel(model: model, control: control)
                }
#endif
            }
            .padding()
        }
    }
}

#if DEBUG
private struct DebugControlPanel: View {
    @ObservedObject var model: DemoViewModel
    let control: DefaultDebugScenarioControl
    @State private var selectedTarget: HookTarget = .nextCommand

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Scenario controls").font(.headline)
            HStack {
                ForEach(HookTarget.allCases, id: \.self) { target in
                    Button(target.rawValue) { selectedTarget = target }
                        .accessibilityIdentifier(DebugScenarioControlPanelID.target(target))
                }
            }
            ForEach(HookPoint.allCases, id: \.self) { point in
                HStack {
                    Button("Arm \(point.rawValue)") {
                        model.performControl { try $0.arm(point, target: selectedTarget) }
                    }
                    .accessibilityIdentifier(DebugScenarioControlPanelID.arm(point))
                    Text(hookPhase(point))
                        .accessibilityIdentifier(DebugScenarioControlPanelID.state(point))
                    Button("Release") {
                        model.performControl { try $0.release(point) }
                    }
                    .accessibilityIdentifier(DebugScenarioControlPanelID.release(point))
                }
            }
            HStack {
                Button("Replay last completion") {
                    model.performControl { _ = try $0.replayLastCompletion() }
                }
                .accessibilityIdentifier(DebugScenarioControlPanelID.replayLast)
                Button("Probe store") { model.probeStore() }
                    .accessibilityIdentifier(DebugScenarioControlPanelID.probeStore)
                Button("Finish process") { model.finishProcess() }
                    .accessibilityIdentifier(DebugScenarioControlPanelID.finishProcess)
            }
            HStack {
                ForEach(StoreFaultKind.allCases, id: \.self) { fault in
                    Button(fault.rawValue) {
                        model.performControl { try $0.injectStoreFault(fault) }
                    }
                    .accessibilityIdentifier(DebugScenarioControlPanelID.fault(fault))
                }
            }
            if let error = model.controlError {
                Text(error).foregroundStyle(.red)
            }
            Text(model.lastEnqueuedCommandID)
                .accessibilityIdentifier("last-enqueued-command-id")
            Text(model.controlSnapshotJSON)
                .font(.system(size: 1))
                .accessibilityIdentifier(DebugScenarioControlPanelID.controlStatusJSON)
                .accessibilityLabel(Text(model.controlSnapshotJSON))
            Text(model.probeResultJSON)
                .font(.system(size: 1))
                .accessibilityIdentifier(DebugScenarioControlPanelID.storeProbeResult)
                .accessibilityLabel(Text(model.probeResultJSON))
            Text(model.processEndAckJSON)
                .font(.system(size: 1))
                .accessibilityIdentifier(DebugScenarioControlPanelID.processEndAckJSON)
                .accessibilityLabel(Text(model.processEndAckJSON))
        }
        .task {
            while !Task.isCancelled {
                model.refreshControlSnapshot()
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
    }

    private func hookPhase(_ point: HookPoint) -> String {
        control.snapshot().hooks.first(where: { $0.point == point })?.phase.rawValue ?? "unarmed"
    }
}
#endif
