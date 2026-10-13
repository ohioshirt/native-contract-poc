import Foundation
import AsyncNativeContract
import NativeContract

enum CredentialAccount: String, Codable, CaseIterable, Sendable {
    case a = "A"
    case b = "B"

    var label: String { "demo-\(rawValue)" }
}

/// Synthetic-only credential data. Values never enter UI or native audit records.
struct Credential: Codable, Equatable, Sendable {
    let account: CredentialAccount
    let version: Int64
    let accessToken: String
    let refreshToken: String

    static func demo(account: CredentialAccount, version: Int64) -> Credential {
        let token = "demo-\(account.rawValue)-v\(version)"
        return Credential(account: account, version: version, accessToken: token, refreshToken: token)
    }
}

struct ProcessContext: Equatable, Sendable {
    let processInstanceId: String
    let launchOrdinal: Int64
    let attemptId: String
    let scenarioId: String
}

struct NativeEventReference: Equatable, Codable, Sendable {
    let processInstanceId: String
    let localSequence: Int64
}

struct AppCommandReference: Equatable, Codable, Sendable {
    let processInstanceId: String
    let id: Int64
}

enum CredentialStoreError: Error, Equatable, Sendable {
    case readFailed
    case replaceFailed
    case clearFailed
    case readbackFailed
    case malformedCredential
    case auditContextMissing

    var safeCode: String {
        switch self {
        case .readFailed: "readFailed"
        case .replaceFailed: "replaceFailed"
        case .clearFailed: "clearFailed"
        case .readbackFailed: "readbackFailed"
        case .malformedCredential: "malformedCredential"
        case .auditContextMissing: "auditContextMissing"
        }
    }
}

/// A test-injected operation failure with an explicitly recorded physical attempt.
struct CredentialStoreFailure: Error, Sendable {
    let operation: String
    let fault: String
    let mutationApplied: Bool
    let verification: String
    let before: StoreObservation
    let observation: StoreObservation
    let physicalAfter: StoreObservation
}

enum SessionPhase: String, Codable, Sendable {
    case booting = "Booting"
    case signedOut = "SignedOut"
    case signingOut = "SigningOut"
    case signedIn = "SignedIn"
    case refreshing = "Refreshing"
    case faultLocked = "FaultLocked"

    var userLabel: String {
        switch self {
        case .booting: "Booting"
        case .signedOut: "Signed out"
        case .signingOut: "Signing out"
        case .signedIn: "Signed in"
        case .refreshing: "Refreshing"
        case .faultLocked: "Fault locked"
        }
    }
}

struct DemoViewState: Equatable, Sendable {
    let processInstanceId: String
    let revision: Int64
    let phase: SessionPhase
    let account: CredentialAccount?
    let credentialVersion: Int64?
    let pendingRequestId: Int64?
    let lastCompletedCommandId: Int64?
    let lastCommandStatus: CommandStatus?

    var authProjection: (SessionPhase, CredentialAccount?, Int64?, Int64?) {
        (phase, account, credentialVersion, pendingRequestId)
    }

    static func == (lhs: DemoViewState, rhs: DemoViewState) -> Bool {
        lhs.processInstanceId == rhs.processInstanceId
            && lhs.revision == rhs.revision
            && lhs.phase == rhs.phase
            && lhs.account == rhs.account
            && lhs.credentialVersion == rhs.credentialVersion
            && lhs.pendingRequestId == rhs.pendingRequestId
            && lhs.lastCompletedCommandId == rhs.lastCompletedCommandId
            && lhs.lastCommandStatus == rhs.lastCommandStatus
    }
}

enum CommandStatus: String, Codable, Sendable {
    case completed = "Completed"
    case rejectedBusy = "RejectedBusy"
    case ignoredStale = "IgnoredStale"
    case ignoredForeign = "IgnoredForeign"
    case rejectedExhausted = "RejectedExhausted"
    case faultLocked = "FaultLocked"
}

enum AppCommand: Sendable {
    case bootstrap
    case login(CredentialAccount)
    case expire
    case logout
    case cancelRefresh
    case retryCleanup
    case observe
    case deliver(Completion)

    var name: String {
        switch self {
        case .bootstrap: "Bootstrap"
        case .login(.a): "Login(A)"
        case .login(.b): "Login(B)"
        case .expire: "Expire"
        case .logout: "Logout"
        case .cancelRefresh: "CancelRefresh"
        case .retryCleanup: "RetryCleanup"
        case .observe: "Observe"
        case let .deliver(completion):
            "Deliver(\(completion.slot.slotId),\(completion.outcome.label))"
        }
    }
}

struct ManagedViewSnapshot: Equatable, Sendable {
    let ownerId: String
    let state: String
    let pendingRequestId: Int64?
    let nextRequestId: Int64?
}

struct CommandObservation: Equatable, Sendable {
    let managed: ManagedViewSnapshot
    let store: StoreObservation
    let view: DemoViewState
    let revision: Int64
}

struct CommandReceipt: Equatable, Sendable {
    let commandId: Int64
    let commandName: String
    let status: CommandStatus
    let observation: CommandObservation
    let acknowledgedEventRef: NativeEventReference?
}

protocol ViewPublisher: Sendable {
    @MainActor func publish(_ view: DemoViewState) async
}
