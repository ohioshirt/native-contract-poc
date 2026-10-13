import Foundation
import XCTest
@testable import NativeContractDemo

final class CoordinatorTests: XCTestCase {
    func testLateSuccessAfterCompletedLogoutCannotWrite() async throws {
        let harness = try await makeHarness("APP-02")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let old = try await harness.transport.waitForPending()

        let logout = await harness.coordinator.submit(.logout)
        XCTAssertEqual(logout.status, .completed)
        XCTAssertNil(harness.store.credential)

        harness.transport.deliver(old, outcome: .success(.demo(account: .a, version: 1)))
        let staleView = try await harness.publisher.waitForCommand(logout.commandId + 1)

        XCTAssertEqual(staleView.lastCommandStatus, .ignoredStale)
        XCTAssertEqual(staleView.phase, .signedOut)
        XCTAssertNil(harness.store.credential)
        XCTAssertEqual(harness.store.mutations, ["clear", "replace:A:0", "clear"])
    }

    func testLateFailureAfterLoginBCannotClearB() async throws {
        let harness = try await makeHarness("APP-04")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let old = try await harness.transport.waitForPending()
        _ = await harness.coordinator.submit(.logout)
        _ = await harness.coordinator.submit(.login(.b))
        XCTAssertEqual(harness.store.credential, .demo(account: .b, version: 0))

        harness.transport.deliver(old, outcome: .failure("disconnected"))
        let staleView = try await harness.publisher.waitForCommand(6)

        XCTAssertEqual(staleView.lastCommandStatus, .ignoredStale)
        XCTAssertEqual(staleView.phase, .signedIn)
        XCTAssertEqual(staleView.account, .b)
        XCTAssertEqual(staleView.credentialVersion, 0)
        XCTAssertEqual(harness.store.credential, .demo(account: .b, version: 0))
        XCTAssertEqual(harness.store.mutations, ["clear", "replace:A:0", "clear", "replace:B:0"])
    }

    func testDuplicateCompletionCannotCommitTwice() async throws {
        let harness = try await makeHarness("APP-06")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()

        harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        _ = try await harness.publisher.waitForCommand(4)
        let mutationsAfterFirst = harness.store.mutations
        let duplicate = Completion(slot: pending.slot, outcome: .success(.demo(account: .a, version: 1)))

        let receipt = await harness.coordinator.submit(.deliver(duplicate))
        let finalView = await harness.publisher.current

        XCTAssertEqual(receipt.status, .ignoredStale)
        XCTAssertEqual(harness.store.mutations, mutationsAfterFirst)
        XCTAssertEqual(finalView?.phase, .signedIn)
        XCTAssertEqual(finalView?.credentialVersion, 1)
    }

    func testMismatchedRefreshPayloadCannotReplaceIssuedAccountsCredential() async throws {
        let harness = try await makeHarness("APP-01")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()

        harness.transport.deliver(pending, outcome: .success(.demo(account: .b, version: 0)))
        let view = try await harness.publisher.waitForCommand(4)

        XCTAssertEqual(view.phase, .faultLocked)
        XCTAssertEqual(harness.store.credential, .demo(account: .a, version: 0))
        XCTAssertEqual(harness.store.mutations, ["clear", "replace:A:0"])
    }

    func testLogicalCancelWithPhysicalCancellationDisabledStillProcessesLateCompletionAsStale() async throws {
        let harness = try await makeHarness("APP-08", cancelTransportOnCancelRefresh: false)
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()

        let cancelReceipt = await harness.coordinator.submit(.cancelRefresh)
        XCTAssertEqual(cancelReceipt.status, .completed)
        XCTAssertEqual(harness.transport.cancelCount, 0)
        XCTAssertNil(harness.store.credential)

        harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        let staleView = try await harness.publisher.waitForCommand(5)
        XCTAssertEqual(staleView.lastCommandStatus, .ignoredStale)
        XCTAssertEqual(staleView.phase, .signedOut)
        XCTAssertNil(harness.store.credential)
    }

    func testVerifiedRefreshPublicationBarrierExposesIdleStoreForIndependentProbe() async throws {
        let hooks = TestScenarioHooks()
        let harness = try await makeHarness("CTRL-N3-EARLY-PUBLISH", hooks: hooks)
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()
        await hooks.arm(.afterPublishAck)

        harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        await hooks.waitForArrival(.afterPublishAck)
        let storeIoActive = await hooks.storeIoActive

        XCTAssertFalse(storeIoActive, "the physical replacement and readback must finish before the UI publication barrier")
        await hooks.release(.afterPublishAck)
        let view = try await harness.publisher.waitForCommand(4)
        XCTAssertEqual(view.phase, .signedIn)
        XCTAssertEqual(harness.store.credential, .demo(account: .a, version: 1))
    }

    func testReentrantSubmitDuringManagedAwaitDoesNotDrainTwice() async throws {
        let hooks = TestScenarioHooks()
        let harness = try await makeHarness("APP-11", hooks: hooks)
        try await bootstrapAndLogin(.a, in: harness)
        let mutationsBefore = harness.store.mutations
        let publicationsBefore = await MainActor.run { harness.publisher.published.count }
        await hooks.arm(.afterManaged)

        let expireTask = Task { await harness.coordinator.submit(.expire) }
        await hooks.waitForArrival(.afterManaged)
        let logoutTask = Task { await harness.coordinator.submit(.logout) }
        _ = try await harness.audit.waitForEnqueued("Logout")

        XCTAssertEqual(
            harness.store.mutations,
            mutationsBefore,
            "Logout must remain queued while Expire is paused after its managed actor await"
        )
        let publicationCount = await MainActor.run { harness.publisher.published.count }
        XCTAssertEqual(publicationCount, publicationsBefore)

        await hooks.release(.afterManaged)
        let expireReceipt = await expireTask.value
        let logoutReceipt = await logoutTask.value

        XCTAssertEqual(expireReceipt.status, .completed)
        XCTAssertEqual(logoutReceipt.status, .completed)
        XCTAssertEqual(harness.store.mutations, mutationsBefore + ["clear"])
        let finalPhase = await MainActor.run { harness.publisher.current?.phase }
        XCTAssertEqual(finalPhase, .signedOut)
    }

    func testQueuedLogoutWaitsForStoreAndPublicationAcknowledgement() async throws {
        let harness = try await makeHarness("APP-05")
        _ = await harness.coordinator.submit(.bootstrap)
        let mutationsBefore = harness.store.mutations
        let publicationsBefore = await MainActor.run { harness.publisher.published.count }
        let publicationGate = TestBarrier()
        await MainActor.run { harness.publisher.blockNextPublication(on: publicationGate) }

        let loginTask = Task { await harness.coordinator.submit(.login(.a)) }
        await publicationGate.waitForArrival()
        let logoutTask = Task { await harness.coordinator.submit(.logout) }
        _ = try await harness.audit.waitForEnqueued("Logout")

        XCTAssertEqual(harness.store.mutations, mutationsBefore + ["replace:A:0"])
        let publishedCount = await MainActor.run { harness.publisher.published.count }
        XCTAssertEqual(publishedCount, publicationsBefore)

        await publicationGate.release()
        _ = await loginTask.value
        let logout = await logoutTask.value

        XCTAssertEqual(logout.status, .completed)
        XCTAssertEqual(harness.store.mutations, mutationsBefore + ["replace:A:0", "clear"])
        let finalPhase = await MainActor.run { harness.publisher.current?.phase }
        XCTAssertEqual(finalPhase, .signedOut)
    }

    func testFailedClearReturnsFaultLockedNotCompletedLogout() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        harness.store.failNextClear()

        let receipt = await harness.coordinator.submit(.logout)
        let view = await MainActor.run { harness.publisher.current }

        XCTAssertEqual(receipt.status, .faultLocked)
        XCTAssertEqual(view?.phase, .faultLocked)
        XCTAssertNotEqual(receipt.status, .completed)
    }

    func testCancelRefreshInFaultLockedIsRejectedLikeLogoutUntilRetryCleanup() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        harness.store.failNextRead()
        let expire = await harness.coordinator.submit(.expire)
        XCTAssertEqual(expire.status, .faultLocked)
        let mutationsBefore = harness.store.mutations

        let cancel = await harness.coordinator.submit(.cancelRefresh)
        let view = await MainActor.run { harness.publisher.current }

        XCTAssertEqual(cancel.status, .faultLocked)
        XCTAssertFalse(harness.audit.hasManagedReduction(commandId: cancel.commandId))
        XCTAssertEqual(harness.store.mutations, mutationsBefore)
        XCTAssertEqual(view?.phase, .faultLocked)
        XCTAssertEqual(view?.lastCompletedCommandId, cancel.commandId)
        let blockedLogin = await harness.coordinator.submit(.login(.a))
        XCTAssertEqual(blockedLogin.status, .rejectedBusy)

        let cleanup = await harness.coordinator.submit(.retryCleanup)
        XCTAssertEqual(cleanup.status, .completed)
        let login = await harness.coordinator.submit(.login(.b))
        XCTAssertEqual(login.status, .completed)
        XCTAssertEqual(harness.store.credential, .demo(account: .b, version: 0))
    }

    /// Expected rows follow the frozen APP-09 reference history
    /// (integration/tests/_history_fixtures.py, replace-fault inventory rows).
    func testRefreshReplaceFaultRunsVerifiedFaultCleanupBeforeFaultLockedReceipt() async throws {
        let cases: [(fault: String, rows: [(kind: String, fields: NSDictionary)])] = [
            ("replaceBefore", [
                ("storeFault", ["operation": "replace", "fault": "replaceBefore", "mutationApplied": false, "observation": storeRow("Present", "A", 0)]),
                ("storeMutation", ["operation": "clear", "cause": "FaultCleanup", "before": storeRow("Present", "A", 0), "after": storeRow("Absent")]),
                ("storeReadback", ["operation": "clear", "observation": storeRow("Absent")]),
            ]),
            ("replaceAfterBeforeVerify", [
                ("storeMutation", ["operation": "replace", "cause": "RefreshSuccess", "before": storeRow("Present", "A", 0), "after": storeRow("Present", "A", 1)]),
                ("storeFault", ["operation": "replace", "fault": "replaceAfterBeforeVerify", "mutationApplied": true, "observation": unknownRow("readFailed")]),
                ("storeMutation", ["operation": "clear", "cause": "FaultCleanup", "before": unknownRow("readFailed"), "after": storeRow("Absent")]),
                ("storeReadback", ["operation": "clear", "observation": storeRow("Absent")]),
            ]),
        ]
        for testCase in cases {
            let harness = try await makeKeychainHarness("APP-09")
            defer { try? harness.base.clearVerified() }
            try await bootstrapAndLogin(.a, in: harness)
            _ = await harness.coordinator.submit(.expire)
            let pending = try await harness.transport.waitForPending()
            harness.store.setStoreFault(testCase.fault)

            harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
            let view = try await harness.publisher.waitForCommand(4)

            XCTAssertEqual(view.phase, .faultLocked, testCase.fault)
            let receipt = try XCTUnwrap(harness.audit.commandRows(kind: "commandReceipt", commandId: 4).first, testCase.fault)
            XCTAssertEqual(receipt["status"] as? String, "FaultLocked", testCase.fault)
            XCTAssertEqual((receipt["observation"] as? [String: Any])?["store"] as? NSDictionary, storeRow("Absent"), testCase.fault)
            let storeRows = harness.audit.commandRows(kind: nil, commandId: 4).filter {
                ["storeMutation", "storeReadback", "storeFault"].contains($0["kind"] as? String)
            }
            XCTAssertEqual(storeRows.map { $0["kind"] as? String }, testCase.rows.map(\.kind), testCase.fault)
            for (row, expected) in zip(storeRows, testCase.rows) {
                for (key, value) in expected.fields {
                    XCTAssertEqual(row[key as! String] as? NSObject, value as? NSObject, "\(testCase.fault) \(expected.kind).\(key)")
                }
            }
            XCTAssertNil(try harness.base.readVerified(), testCase.fault)
            let published = await MainActor.run { harness.publisher.published }
            XCTAssertFalse(published.contains { $0.lastCompletedCommandId == 4 && $0.phase == .signedIn }, testCase.fault)
        }
    }

    func testLoginReplaceFaultRunsVerifiedFaultCleanupAndStaysFaultLocked() async throws {
        let harness = try await makeKeychainHarness("APP-09")
        defer { try? harness.base.clearVerified() }
        _ = await harness.coordinator.submit(.bootstrap)
        harness.store.setStoreFault("replaceAfterBeforeVerify")

        let login = await harness.coordinator.submit(.login(.a))

        XCTAssertEqual(login.status, .faultLocked)
        XCTAssertEqual(login.observation.store, .absent)
        let cleanup = try XCTUnwrap(harness.audit.commandRows(kind: "storeMutation", commandId: login.commandId).last)
        XCTAssertEqual(cleanup["cause"] as? String, "FaultCleanup")
        XCTAssertEqual(cleanup["before"] as? NSDictionary, unknownRow("readFailed"))
        XCTAssertNil(try harness.base.readVerified())
        let retry = await harness.coordinator.submit(.login(.a))
        XCTAssertEqual(retry.status, .rejectedBusy)
    }

    /// APP-10 clear-after-before-verify reference history: RetryCleanup's clear
    /// chains from the FaultLocked receipt observation, not a fresh physical read.
    func testRetryCleanupAfterUnverifiedClearRecordsChainedUnknownBefore() async throws {
        let harness = try await makeKeychainHarness("APP-10")
        defer { try? harness.base.clearVerified() }
        try await bootstrapAndLogin(.a, in: harness)
        harness.store.setStoreFault("clearAfterBeforeVerify")
        let logout = await harness.coordinator.submit(.logout)
        XCTAssertEqual(logout.status, .faultLocked)
        XCTAssertEqual(logout.observation.store, .unknown(errorCode: "readFailed"))
        harness.store.setStoreFault(nil)

        let cleanup = await harness.coordinator.submit(.retryCleanup)

        XCTAssertEqual(cleanup.status, .completed)
        let mutation = try XCTUnwrap(harness.audit.commandRows(kind: "storeMutation", commandId: cleanup.commandId).first)
        XCTAssertEqual(mutation["cause"] as? String, "RetryCleanup")
        XCTAssertEqual(mutation["before"] as? NSDictionary, unknownRow("readFailed"))
        XCTAssertEqual(mutation["after"] as? NSDictionary, storeRow("Absent"))
    }

    /// An HTTP completion is an internal Deliver whose receipt never reaches the view
    /// model, so every publication must carry the store observation it was made with.
    func testInternalRefreshDeliveriesPublishTheirStoreObservation() async throws {
        let cases: [(RefreshOutcome, StoreObservation, SessionPhase)] = [
            (.success(.demo(account: .a, version: 1)), .present(account: "A", version: 1), .signedIn),
            (.failure("rejected"), .absent, .signedOut),
        ]
        for (outcome, expectedStore, expectedPhase) in cases {
            let harness = try await makeHarness("APP-06")
            try await bootstrapAndLogin(.a, in: harness)
            _ = await harness.coordinator.submit(.expire)
            let pending = try await harness.transport.waitForPending()
            let refreshingStore = await MainActor.run { harness.publisher.currentStore }
            XCTAssertEqual(refreshingStore, .present(account: "A", version: 0))

            harness.transport.deliver(pending, outcome: outcome)
            let view = try await harness.publisher.waitForCommand(4)
            let store = await MainActor.run { harness.publisher.currentStore }

            XCTAssertEqual(view.phase, expectedPhase)
            XCTAssertEqual(store, expectedStore)
        }
    }

    @MainActor
    func testCredentialLabelFollowsPublishedStoreAndIgnoresStaleRevisions() async {
        let model = DemoViewModel(process: ProcessContext(processInstanceId: "store/p1", launchOrdinal: 1, attemptId: "store", scenarioId: "store"))
        func view(_ revision: Int64, _ phase: SessionPhase, _ version: Int64?) -> DemoViewState {
            DemoViewState(
                processInstanceId: "store/p1",
                revision: revision,
                phase: phase,
                account: version == nil ? nil : .a,
                credentialVersion: version,
                pendingRequestId: nil,
                lastCompletedCommandId: nil,
                lastCommandStatus: nil
            )
        }
        XCTAssertEqual(model.credentialStatusLabel, "Credentials unknown")

        await model.publish(view(1, .signedIn, 0), store: .present(account: "A", version: 0))
        XCTAssertEqual(model.credentialStatusLabel, "Credentials version 0")
        await model.publish(view(2, .signedIn, 1), store: .present(account: "A", version: 1))
        XCTAssertEqual(model.credentialStatusLabel, "Credentials version 1")
        await model.publish(view(1, .signedOut, nil), store: .absent)
        XCTAssertEqual(model.credentialStatusLabel, "Credentials version 1")
        await model.publish(view(3, .signedOut, nil), store: .absent)
        XCTAssertEqual(model.credentialStatusLabel, "Credentials absent")
    }

    /// The real view model as the coordinator's publisher: the label must follow an
    /// HTTP completion that no `submit` receipt ever reports.
    @MainActor
    func testViewModelCredentialLabelFollowsHttpRefreshCompletion() async throws {
        let context = ProcessContext(processInstanceId: "label-e2e/APP-06/p1", launchOrdinal: 1, attemptId: "label-e2e", scenarioId: "APP-06")
        let model = DemoViewModel(process: context)
        let transport = TestRefreshTransport()
        let coordinator = SessionCoordinator(
            process: context,
            store: TestCredentialStore(),
            transport: transport,
            publisher: model,
            hooks: TestScenarioHooks(),
            audit: MemoryAuditRecorder(),
            cancelTransportOnCancelRefresh: false
        )
        try await coordinator.start()
        _ = await coordinator.submit(.bootstrap)
        _ = await coordinator.submit(.login(.a))
        _ = await coordinator.submit(.expire)
        let pending = try await transport.waitForPending()
        XCTAssertEqual(model.credentialStatusLabel, "Credentials version 0")

        transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        for _ in 0..<200 where model.current.lastCompletedCommandId != 4 {
            try await Task.sleep(nanoseconds: 5_000_000)
        }

        XCTAssertEqual(model.sessionLabel, "Signed in demo-A")
        XCTAssertEqual(model.credentialStatusLabel, "Credentials version 1")
    }

    /// Frozen session-state labels (integration/native-anchors.md): authenticated
    /// phases carry `…demo-A`/`…demo-B`; unauthenticated phases carry no account.
    @MainActor
    func testSessionStateLabelCarriesAccountOnlyForAuthenticatedPhases() async {
        let model = DemoViewModel(process: ProcessContext(processInstanceId: "labels/p1", launchOrdinal: 1, attemptId: "labels", scenarioId: "labels"))
        let cases: [(SessionPhase, CredentialAccount?, String)] = [
            (.booting, nil, "Booting"),
            (.signedOut, nil, "Signed out"),
            (.signingOut, nil, "Signing out"),
            (.faultLocked, nil, "Fault locked"),
            (.signedIn, .a, "Signed in demo-A"),
            (.signedIn, .b, "Signed in demo-B"),
            (.refreshing, .a, "Refreshing demo-A"),
            (.refreshing, .b, "Refreshing demo-B"),
        ]
        for (index, (phase, account, expected)) in cases.enumerated() {
            let view = DemoViewState(
                processInstanceId: "labels/p1",
                revision: Int64(index + 1),
                phase: phase,
                account: account,
                credentialVersion: account == nil ? nil : 0,
                pendingRequestId: phase == .refreshing ? 1 : nil,
                lastCompletedCommandId: nil,
                lastCommandStatus: nil
            )
            await model.publish(view, store: .absent)
            XCTAssertEqual(model.sessionLabel, expected)
        }
    }

    func testDeliveryAfterFaultLockDoesNotCallManagerAndCompletesReceipt() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let old = try await harness.transport.waitForPending()
        harness.store.failNextClear()
        let logout = await harness.coordinator.submit(.logout)
        XCTAssertEqual(logout.status, .faultLocked)

        let delivery = await harness.coordinator.submit(
            .deliver(Completion(slot: old.slot, outcome: .success(.demo(account: .a, version: 1))))
        )

        XCTAssertEqual(delivery.status, .faultLocked)
        XCTAssertEqual(delivery.observation.managed.state, "Unauthenticated")
        XCTAssertFalse(harness.audit.hasManagedReduction(commandId: delivery.commandId))
        XCTAssertEqual(harness.store.credential, .demo(account: .a, version: 0))
    }

    func testFaultLockedDeliveryPreservesRefreshingManagedTripleWithoutReduction() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let old = try await harness.transport.waitForPending()
        harness.store.failNextRead()
        let observe = await harness.coordinator.submit(.observe)
        let before = observe.observation.managed
        XCTAssertEqual(observe.status, .faultLocked)
        XCTAssertEqual(before.state, "Refreshing")

        let delivery = await harness.coordinator.submit(
            .deliver(Completion(slot: old.slot, outcome: .success(.demo(account: .a, version: 1))))
        )

        XCTAssertEqual(delivery.status, .faultLocked)
        XCTAssertEqual(delivery.observation.managed, before)
        XCTAssertFalse(harness.audit.hasManagedReduction(commandId: delivery.commandId))
        XCTAssertEqual(harness.store.credential, .demo(account: .a, version: 0))
        XCTAssertEqual(delivery.observation.view.phase, .faultLocked)
        XCTAssertEqual(delivery.observation.view.lastCompletedCommandId, delivery.commandId)
    }

    func testRetryCleanupLogsManagedLogoutBeforeResetAfterRefreshWriteFailure() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()
        harness.store.failNextReplacementAfterWrite()

        harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        let fault = try await harness.publisher.waitForCommand(4)
        XCTAssertEqual(fault.phase, .faultLocked)
        XCTAssertEqual(harness.audit.eventRows.last(where: { $0["kind"] as? String == "commandReceipt" })?["status"] as? String, "FaultLocked")
        let ownerBeforeCleanup = try XCTUnwrap(harness.audit.eventRows.last(where: {
            $0["kind"] as? String == "commandReceipt"
        })?["observation"] as? [String: Any])
        let managedBeforeCleanup = try XCTUnwrap(ownerBeforeCleanup["managed"] as? [String: Any])
        XCTAssertEqual(managedBeforeCleanup["state"] as? String, "Authenticated")

        let cleanup = await harness.coordinator.submit(.retryCleanup)
        let rows = harness.audit.eventRows
        let reset = try XCTUnwrap(rows.first { $0["kind"] as? String == "managedInstanceReset" })
        let cleanupReduction = try XCTUnwrap(rows.first { row in
            row["kind"] as? String == "managedReduced"
                && (row["commandRef"] as? [String: Any])?["id"] as? Int64 == cleanup.commandId
        })

        XCTAssertEqual(cleanup.status, .completed)
        XCTAssertEqual((reset["before"] as? [String: Any])?["state"] as? String, "Unauthenticated")
        XCTAssertEqual((reset["after"] as? [String: Any])?["state"] as? String, "Unauthenticated")
        XCTAssertEqual((cleanupReduction["event"] as? [String: Any])?["event"] as? String, "Logout")
        XCTAssertEqual((cleanupReduction["result"] as? [String: Any])?["state"] as? String, "Unauthenticated")
        XCTAssertNil(harness.store.credential)

        let login = await harness.coordinator.submit(.login(.b))
        XCTAssertEqual(login.status, .completed)
        XCTAssertEqual(harness.store.credential, .demo(account: .b, version: 0))
    }

    func testWriteThenReadbackFailureNeverPublishesSignedIn() async throws {
        let harness = try await makeHarness("APP-10")
        _ = await harness.coordinator.submit(.bootstrap)
        harness.store.failNextReplacementAfterWrite()

        let receipt = await harness.coordinator.submit(.login(.a))
        let states = await MainActor.run { harness.publisher.published }

        XCTAssertEqual(receipt.status, .faultLocked)
        XCTAssertTrue(states.allSatisfy { $0.phase != .signedIn && $0.phase != .refreshing })
        XCTAssertEqual(states.last?.phase, .faultLocked)
    }

    func testExpireReadFailureFaultLocksWithoutIssuingRefresh() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        harness.store.failNextRead()

        let receipt = await harness.coordinator.submit(.expire)
        let view = await MainActor.run { harness.publisher.current }

        XCTAssertEqual(receipt.status, .faultLocked)
        XCTAssertEqual(receipt.observation.store, .unknown(errorCode: "readFailed"))
        XCTAssertEqual(view?.phase, .faultLocked)
        XCTAssertTrue(harness.transport.startedSlots.isEmpty)
    }

    func testObserveReadFailureFaultLocksInsteadOfUsingCachedStoreObservation() async throws {
        let harness = try await makeHarness("APP-10")
        try await bootstrapAndLogin(.a, in: harness)
        harness.store.failNextRead()

        let receipt = await harness.coordinator.submit(.observe)
        let view = await MainActor.run { harness.publisher.current }

        XCTAssertEqual(receipt.status, .faultLocked)
        XCTAssertEqual(receipt.observation.store, .unknown(errorCode: "readFailed"))
        XCTAssertEqual(view?.phase, .faultLocked)
    }

#if DEBUG
    func testLaunchStoreFaultIsParsedForTheTargetedDebugStoreWrapper() throws {
        let launch = try DemoLaunchParameters.load(arguments: [
            "NativeContractDemo",
            "--scenario-id", "APP-09",
            "--run-id", "run-task4",
            "--process-instance-id", "attempt-09/APP-09/p1",
            "--launch-ordinal", "1",
            "--base-url", "http://127.0.0.1:8080",
            "--cancel-mode", "disabled",
            "--store-fault", "replaceBefore",
        ])

        XCTAssertEqual(launch.storeFault, .replaceBefore)
        XCTAssertFalse(launch.cancelTransportOnCancelRefresh)
        XCTAssertEqual(launch.process.scenarioId, "APP-09")
    }
#endif

    func testSuccessfulObserveReadsStoreWithoutPublishingANewView() async throws {
        let harness = try await makeHarness("APP-10")
        _ = await harness.coordinator.submit(.bootstrap)
        let login = await harness.coordinator.submit(.login(.a))
        let viewBefore = await MainActor.run { harness.publisher.current }
        let readsBefore = harness.store.readCount
        let acknowledgementsBefore = harness.audit.count(kind: "uiPublishAck")

        let receipt = await harness.coordinator.submit(.observe)
        let viewAfter = await MainActor.run { harness.publisher.current }

        XCTAssertEqual(receipt.status, .completed)
        XCTAssertEqual(receipt.observation.store, .present(account: "A", version: 0))
        XCTAssertEqual(receipt.observation.view, viewBefore)
        XCTAssertEqual(receipt.observation.revision, viewBefore?.revision)
        XCTAssertEqual(receipt.acknowledgedEventRef, login.acknowledgedEventRef)
        XCTAssertEqual(viewAfter, viewBefore)
        XCTAssertGreaterThan(harness.store.readCount, readsBefore)
        XCTAssertEqual(harness.audit.count(kind: "uiPublishAck"), acknowledgementsBefore)
    }

    func testCancelledSubmitStillCompletesAcceptedLogout() async throws {
        let hooks = TestScenarioHooks()
        let harness = try await makeHarness("APP-10", hooks: hooks)
        try await bootstrapAndLogin(.a, in: harness)
        await hooks.arm(.afterManaged)

        let logoutTask = Task { await harness.coordinator.submit(.logout) }
        await hooks.waitForArrival(.afterManaged)
        logoutTask.cancel()
        await hooks.release(.afterManaged)

        let receipt = await logoutTask.value
        let view = await MainActor.run { harness.publisher.current }
        XCTAssertEqual(receipt.status, .completed)
        XCTAssertNil(harness.store.credential)
        XCTAssertEqual(view?.phase, .signedOut)
    }

    func testDebugReleaseBypassesPausedCoordinatorAndKeepsHookIdentity() async throws {
        let harness = try await makeDebugHarness("APP-10")
        _ = await harness.coordinator.submit(.bootstrap)
        let armed = try harness.control.arm(.afterManaged, target: .nextCommand)
        let loginTask = Task { await harness.coordinator.submit(.login(.a)) }
        let arrival = try await harness.control.awaitArrival(.afterManaged, timeoutMillis: 1_000)

        XCTAssertEqual(arrival.phase, .arrived)
        XCTAssertEqual(arrival.armSequence, armed.actionId)
        let released = try harness.control.release(.afterManaged)
        XCTAssertEqual(released.actionId, armed.actionId)
        let loginReceipt = await loginTask.value
        XCTAssertEqual(loginReceipt.status, .completed)

        let phases = harness.audit.hookRows(point: .afterManaged).compactMap { $0["phase"] as? String }
        XCTAssertEqual(phases, ["armed", "arrived", "released"])
        XCTAssertTrue(harness.audit.hookRows(point: .afterManaged).allSatisfy {
            ($0["actionId"] as? NSNumber)?.int64Value == armed.actionId
        })
    }

    func testRestartBootstrapClearCarriesReleasedHookActionId() async throws {
        let process = ProcessContext(
            processInstanceId: "task4-restart/APP-12/p2",
            launchOrdinal: 2,
            attemptId: "task4-restart",
            scenarioId: "APP-12"
        )
        let audit = MemoryAuditRecorder()
        let clock = ControlRevisionClock()
        let hooks = DebugScenarioHooks(process: process, audit: audit, revisionClock: clock)
        let store = DebugTestCredentialStore()
        try store.replaceVerified(.demo(account: .a, version: 0))
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let coordinator = SessionCoordinator(
            process: process,
            store: store,
            transport: TestRefreshTransport(),
            publisher: publisher,
            hooks: hooks,
            audit: audit
        )
        let control = DefaultDebugScenarioControl(
            process: process,
            coordinator: coordinator,
            store: store,
            hooks: hooks,
            ingress: DemoIngress(),
            service: "native-contract-demo.credentials.test.task4-restart.APP-12",
            revisionClock: clock
        )
        try await coordinator.start()
        let armed = try control.arm(.beforeBootstrapClear, target: .bootstrap)
        let bootstrapTask = Task { await coordinator.submit(.bootstrap) }
        let arrival = try await control.awaitArrival(.beforeBootstrapClear, timeoutMillis: 1_000)
        XCTAssertEqual(arrival.phase, .arrived)
        XCTAssertEqual(arrival.armSequence, armed.actionId)

        let released = try control.release(.beforeBootstrapClear)
        let receipt = await bootstrapTask.value
        let rows = audit.eventRows
        let clear = try XCTUnwrap(rows.first { row in
            row["kind"] as? String == "storeMutation" && row["cause"] as? String == "Bootstrap"
        })

        XCTAssertEqual(receipt.status, .completed)
        XCTAssertEqual(process.launchOrdinal, 2)
        XCTAssertEqual(store.value, nil)
        XCTAssertEqual((clear["releaseActionId"] as? NSNumber)?.int64Value, released.actionId)
        XCTAssertTrue(rows.contains { row in
            row["kind"] as? String == "hookEvent"
                && row["point"] as? String == HookPoint.beforeBootstrapClear.rawValue
                && row["phase"] as? String == HookPhase.released.rawValue
                && (row["actionId"] as? NSNumber)?.int64Value == released.actionId
        })
    }

    func testIngressHeldPausesCapturedDeliveryBeforeManagerOrStoreEffects() async throws {
        let harness = try await makeDebugHarness("APP-01")
        _ = await harness.coordinator.submit(.bootstrap)
        _ = await harness.coordinator.submit(.login(.a))
        _ = await harness.coordinator.submit(.expire)
        let pending = try await harness.transport.waitForPending()
        let reductionsBefore = harness.audit.count(kind: "managedReduced")
        let mutationsBefore = harness.audit.count(kind: "storeMutation")
        let viewBefore = await MainActor.run { harness.publisher.current }
        let armed = try harness.control.arm(.ingressHeld, target: .nextDelivery)

        harness.transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        let arrival = try await harness.control.awaitArrival(.ingressHeld, timeoutMillis: 1_000)
        let deliveryReference = try XCTUnwrap(arrival.arrivalCommandRef)
        let rowsBeforeRelease = harness.audit.eventRows

        XCTAssertEqual(arrival.phase, .arrived)
        XCTAssertEqual(arrival.armSequence, armed.actionId)
        XCTAssertEqual(deliveryReference.processInstanceId, harness.process.processInstanceId)
        XCTAssertTrue(rowsBeforeRelease.contains { row in
            row["kind"] as? String == "transportReceived"
                && (row["commandRef"] as? [String: Any])?["id"] as? Int64 == deliveryReference.id
        })
        XCTAssertFalse(harness.audit.hasManagedReduction(commandId: deliveryReference.id))
        XCTAssertEqual(harness.audit.count(kind: "managedReduced"), reductionsBefore)
        XCTAssertEqual(harness.audit.count(kind: "storeMutation"), mutationsBefore)
        let heldView = await MainActor.run { harness.publisher.current }
        XCTAssertEqual(heldView, viewBefore)

        let release = try harness.control.release(.ingressHeld)
        let finalView = try await harness.publisher.waitForCommand(deliveryReference.id)

        XCTAssertEqual(release.actionId, armed.actionId)
        XCTAssertGreaterThan(harness.audit.count(kind: "managedReduced"), reductionsBefore)
        XCTAssertGreaterThan(harness.audit.count(kind: "storeMutation"), mutationsBefore)
        XCTAssertEqual(finalView.phase, .signedIn)
        XCTAssertEqual(finalView.account, .a)
        XCTAssertEqual(finalView.credentialVersion, 1)
    }

    func testProcessEndAckIsActualIdempotentTerminalEvent() async throws {
        let harness = try await makeDebugHarness("APP-07")
        _ = await harness.coordinator.submit(.bootstrap)

        let first = try await harness.control.finishProcess(timeoutMillis: 1_000)
        let repeated = try await harness.control.finishProcess(timeoutMillis: 1_000)
        let afterEnd = await harness.coordinator.submit(.login(.a))
        let rows = harness.audit.eventRows

        XCTAssertEqual(first, repeated)
        XCTAssertEqual(first.processInstanceId, harness.process.processInstanceId)
        XCTAssertEqual(first.eventRef.localSequence, rows.last?["localSequence"] as? Int64)
        XCTAssertEqual(rows.filter { $0["kind"] as? String == "processEnd" }.count, 1)
        XCTAssertEqual(rows.last?["kind"] as? String, "processEnd")
        XCTAssertEqual(afterEnd.status, .rejectedBusy)
        XCTAssertNil(harness.store.value)
    }

    func testProcessEndRejectsPausedHookWithoutWritingTerminalRow() async throws {
        let harness = try await makeDebugHarness("APP-11")
        _ = await harness.coordinator.submit(.bootstrap)
        let arm = try harness.control.arm(.afterManaged, target: .nextCommand)
        let loginTask = Task { await harness.coordinator.submit(.login(.a)) }
        _ = try await harness.control.awaitArrival(.afterManaged, timeoutMillis: 1_000)

        do {
            _ = try await harness.control.finishProcess(timeoutMillis: 1_000)
            XCTFail("finishProcess must reject an active paused consumer")
        } catch let error as DebugControlError {
            XCTAssertEqual(error, .processBusy)
        }
        XCTAssertFalse(harness.audit.eventRows.contains { $0["kind"] as? String == "processEnd" })

        XCTAssertEqual(try harness.control.release(.afterManaged).actionId, arm.actionId)
        let receipt = await loginTask.value
        XCTAssertEqual(receipt.status, .completed)
        _ = try await harness.control.finishProcess(timeoutMillis: 1_000)
        XCTAssertEqual(harness.audit.eventRows.filter { $0["kind"] as? String == "processEnd" }.count, 1)
    }

    func testProcessEndWaitsForAdmittedHookControlBeforeWritingTerminalRow() async throws {
        let armBarrier = TestControlBarrier()
        let finishWaitSignal = TestControlSignal()
        let harness = try await makeDebugHarness(
            "APP-11",
            onControlAdmitted: { operation in
                if operation == "arm" { armBarrier.pause() }
            },
            onFinishWaitingForControls: { finishWaitSignal.signal() }
        )
        _ = await harness.coordinator.submit(.bootstrap)

        let armTask = Task.detached {
            try harness.control.arm(.afterManaged, target: .nextCommand)
        }
        XCTAssertTrue(armBarrier.waitUntilEntered(timeoutMillis: 1_000))
        let finishTask = Task {
            try await harness.control.finishProcess(timeoutMillis: 2_000)
        }

        guard finishWaitSignal.wait(timeoutMillis: 1_000) else {
            let terminalAlreadyWritten = harness.audit.eventRows.contains { $0["kind"] as? String == "processEnd" }
            armBarrier.release()
            _ = try? await armTask.value
            _ = try? await finishTask.value
            XCTFail("finish must wait for admitted control work; processEndBeforeArmResumed=\(terminalAlreadyWritten)")
            return
        }

        XCTAssertFalse(harness.audit.eventRows.contains { $0["kind"] as? String == "processEnd" })
        armBarrier.release()
        let arm = try await armTask.value
        let acknowledgement = try await finishTask.value
        let rows = harness.audit.eventRows
        let armRow = try XCTUnwrap(rows.first { row in
            row["kind"] as? String == "hookEvent" && row["phase"] as? String == "armed"
        })
        let armSequence = try XCTUnwrap((armRow["localSequence"] as? NSNumber)?.int64Value)

        XCTAssertGreaterThan(arm.actionId, 0)
        XCTAssertEqual(rows.last?["kind"] as? String, "processEnd")
        XCTAssertEqual(rows.filter { $0["kind"] as? String == "processEnd" }.count, 1)
        XCTAssertGreaterThan(acknowledgement.eventRef.localSequence, armSequence)
        XCTAssertThrowsError(try harness.control.release(.afterManaged)) { error in
            XCTAssertEqual(error as? DebugControlError, .processBusy)
        }
        XCTAssertEqual(harness.audit.eventRows.last?["kind"] as? String, "processEnd")
    }

    /// integration/check.py EVENT_BASE requires processInstanceId, launchOrdinal,
    /// localSequence and kind on every native row. The JSONL is kept under the
    /// simulator temporary directory for host-side validation against EVENT_FIELDS.
    func testJSONLRecorderRowsCarryFrozenEventBaseThroughAuthFlow() async throws {
        let process = ProcessContext(
            processInstanceId: "schema-smoke/APP-01/p1",
            launchOrdinal: 1,
            attemptId: "schema-smoke",
            scenarioId: "APP-01"
        )
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("native-contract-schema-smoke", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fileURL = directory.appendingPathComponent("swift-auth-flow.jsonl")
        try? FileManager.default.removeItem(at: fileURL)
        let recorder = try JSONLAuditRecorder(fileURL: fileURL, processInstanceId: process.processInstanceId, launchOrdinal: process.launchOrdinal)
        let clock = ControlRevisionClock()
        let hooks = DebugScenarioHooks(process: process, audit: recorder, revisionClock: clock)
        let store = DebugTestCredentialStore()
        let transport = TestRefreshTransport()
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let coordinator = SessionCoordinator(
            process: process,
            store: store,
            transport: transport,
            publisher: publisher,
            hooks: hooks,
            audit: recorder,
            cancelTransportOnCancelRefresh: false
        )
        let control = DefaultDebugScenarioControl(
            process: process,
            coordinator: coordinator,
            store: store,
            hooks: hooks,
            ingress: DemoIngress(),
            service: "native-contract-demo.credentials.test.schema-smoke.APP-01",
            revisionClock: clock
        )
        try await coordinator.start()
        _ = await coordinator.submit(.bootstrap)
        _ = await coordinator.submit(.login(.a))
        _ = await coordinator.submit(.expire)
        let pending = try await transport.waitForPending()
        transport.deliver(pending, outcome: .success(.demo(account: .a, version: 1)))
        _ = try await publisher.waitForCommand(4)
        _ = await coordinator.submit(.logout)
        _ = try await control.finishProcess(timeoutMillis: 5_000)
        print("schema-smoke-jsonl=\(fileURL.path)")

        let rows = try String(contentsOf: fileURL, encoding: .utf8)
            .split(whereSeparator: \.isNewline)
            .map { try XCTUnwrap(JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any]) }
        XCTAssertGreaterThan(rows.count, 10)
        for row in rows {
            XCTAssertEqual(row["processInstanceId"] as? String, process.processInstanceId)
            XCTAssertEqual((row["launchOrdinal"] as? NSNumber)?.int64Value, 1, "\(row["kind"] ?? "?") lacks launchOrdinal")
            XCTAssertNotNil(row["localSequence"] as? NSNumber)
            XCTAssertNotNil(row["kind"] as? String)
        }
    }

    func testCoordinatorProcessEndSynchronizesAndSealsJSONRecorder() async throws {
        let process = ProcessContext(
            processInstanceId: "task4-json-end/APP-11/p1",
            launchOrdinal: 1,
            attemptId: "task4-json-end",
            scenarioId: "APP-11"
        )
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("native-contract-task4-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("history.jsonl")
        let recorder = try JSONLAuditRecorder(fileURL: fileURL, processInstanceId: process.processInstanceId, launchOrdinal: process.launchOrdinal)
        let clock = ControlRevisionClock()
        let hooks = DebugScenarioHooks(process: process, audit: recorder, revisionClock: clock)
        let store = DebugTestCredentialStore()
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let coordinator = SessionCoordinator(
            process: process,
            store: store,
            transport: TestRefreshTransport(),
            publisher: publisher,
            hooks: hooks,
            audit: recorder
        )
        let control = DefaultDebugScenarioControl(
            process: process,
            coordinator: coordinator,
            store: store,
            hooks: hooks,
            ingress: DemoIngress(),
            service: "native-contract-demo.credentials.test.task4-json-end",
            revisionClock: clock
        )
        try await coordinator.start()

        let acknowledgement = try await control.finishProcess(timeoutMillis: 1_000)

        let lines = try String(contentsOf: fileURL, encoding: .utf8)
            .split(whereSeparator: \.isNewline)
        let rows = try lines.map { line in
            try XCTUnwrap(JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any])
        }
        XCTAssertEqual(rows.map { $0["kind"] as? String }, ["processStart", "processEnd"])
        XCTAssertEqual((rows.last?["localSequence"] as? NSNumber)?.int64Value, acknowledgement.eventRef.localSequence)
        XCTAssertThrowsError(try recorder.append(kind: "hookEvent", fields: Data("{}".utf8)))
        XCTAssertThrowsError(try control.arm(.afterManaged, target: .nextCommand)) { error in
            XCTAssertEqual(error as? DebugControlError, .processBusy)
        }
    }

    private func bootstrapAndLogin(_ account: CredentialAccount, in harness: CoordinatorHarness) async throws {
        let bootstrap = await harness.coordinator.submit(.bootstrap)
        XCTAssertEqual(bootstrap.status, .completed)
        let login = await harness.coordinator.submit(.login(account))
        XCTAssertEqual(login.status, .completed)
    }

    private func makeHarness(
        _ scenario: String,
        hooks: TestScenarioHooks = TestScenarioHooks(),
        cancelTransportOnCancelRefresh: Bool = false
    ) async throws -> CoordinatorHarness {
        let processID = "task4-\(UUID().uuidString)/\(scenario)/p1"
        let context = ProcessContext(
            processInstanceId: processID,
            launchOrdinal: 1,
            attemptId: processID.split(separator: "/").first.map(String.init)!,
            scenarioId: scenario
        )
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let store = TestCredentialStore()
        let transport = TestRefreshTransport()
        let audit = MemoryAuditRecorder()
        let coordinator = SessionCoordinator(
            process: context,
            store: store,
            transport: transport,
            publisher: publisher,
            hooks: hooks,
            audit: audit,
            cancelTransportOnCancelRefresh: cancelTransportOnCancelRefresh
        )
        try await coordinator.start()
        return CoordinatorHarness(
            coordinator: coordinator,
            store: store,
            transport: transport,
            publisher: publisher,
            hooks: hooks,
            audit: audit
        )
    }

    private func bootstrapAndLogin(_ account: CredentialAccount, in harness: KeychainCoordinatorHarness) async throws {
        let bootstrap = await harness.coordinator.submit(.bootstrap)
        XCTAssertEqual(bootstrap.status, .completed)
        let login = await harness.coordinator.submit(.login(account))
        XCTAssertEqual(login.status, .completed)
    }

    /// Real simulator Keychain behind the audited wrapper, so injected faults
    /// produce the same CredentialStoreFailure rows as the app.
    private func makeKeychainHarness(_ scenario: String) async throws -> KeychainCoordinatorHarness {
        let attemptId = "t4-\(UUID().uuidString)"
        let process = ProcessContext(
            processInstanceId: "\(attemptId)/\(scenario)/p1",
            launchOrdinal: 1,
            attemptId: attemptId,
            scenarioId: scenario
        )
        let base = try KeychainCredentialStore(service: "native-contract-demo.credentials.test.\(attemptId).\(scenario)")
        try base.clearVerified()
        let hooks = TestScenarioHooks()
        let audit = MemoryAuditRecorder()
        let store = AuditedCredentialStore(base: base, audit: audit, storeIOChanged: hooks.storeIOChanged)
        let transport = TestRefreshTransport()
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let coordinator = SessionCoordinator(
            process: process,
            store: store,
            transport: transport,
            publisher: publisher,
            hooks: hooks,
            audit: audit,
            cancelTransportOnCancelRefresh: false
        )
        try await coordinator.start()
        return KeychainCoordinatorHarness(
            coordinator: coordinator,
            base: base,
            store: store,
            transport: transport,
            publisher: publisher,
            audit: audit
        )
    }

    private func makeDebugHarness(
        _ scenario: String,
        onControlAdmitted: @escaping @Sendable (String) -> Void = { _ in },
        onFinishWaitingForControls: @escaping @Sendable () -> Void = {}
    ) async throws -> DebugCoordinatorHarness {
        let process = ProcessContext(
            processInstanceId: "task4-debug/\(scenario)/p1",
            launchOrdinal: 1,
            attemptId: "task4-debug",
            scenarioId: scenario
        )
        let audit = MemoryAuditRecorder()
        let clock = ControlRevisionClock()
        let hooks = DebugScenarioHooks(process: process, audit: audit, revisionClock: clock)
        let store = DebugTestCredentialStore()
        let transport = TestRefreshTransport()
        let publisher = await MainActor.run { RecordingViewPublisher() }
        let coordinator = SessionCoordinator(
            process: process,
            store: store,
            transport: transport,
            publisher: publisher,
            hooks: hooks,
            audit: audit
        )
        let control = DefaultDebugScenarioControl(
            process: process,
            coordinator: coordinator,
            store: store,
            hooks: hooks,
            ingress: DemoIngress(),
            service: "native-contract-demo.credentials.test.task4-debug.\(scenario)",
            revisionClock: clock,
            onControlAdmitted: onControlAdmitted,
            onFinishWaitingForControls: onFinishWaitingForControls
        )
        try await coordinator.start()
        return DebugCoordinatorHarness(
            process: process,
            coordinator: coordinator,
            store: store,
            transport: transport,
            publisher: publisher,
            audit: audit,
            control: control
        )
    }
}

private struct CoordinatorHarness {
    let coordinator: SessionCoordinator
    let store: TestCredentialStore
    let transport: TestRefreshTransport
    let publisher: RecordingViewPublisher
    let hooks: TestScenarioHooks
    let audit: MemoryAuditRecorder
}

private struct KeychainCoordinatorHarness {
    let coordinator: SessionCoordinator
    let base: KeychainCredentialStore
    let store: AuditedCredentialStore
    let transport: TestRefreshTransport
    let publisher: RecordingViewPublisher
    let audit: MemoryAuditRecorder
}

private func storeRow(_ kind: String, _ account: String? = nil, _ version: Int64? = nil) -> NSDictionary {
    var row: [String: Any] = ["kind": kind]
    if let account { row["account"] = account }
    if let version { row["version"] = version }
    return row as NSDictionary
}

private func unknownRow(_ errorCode: String) -> NSDictionary {
    ["kind": "Unknown", "errorCode": errorCode]
}

private struct DebugCoordinatorHarness {
    let process: ProcessContext
    let coordinator: SessionCoordinator
    let store: DebugTestCredentialStore
    let transport: TestRefreshTransport
    let publisher: RecordingViewPublisher
    let audit: MemoryAuditRecorder
    let control: DefaultDebugScenarioControl
}

private final class TestControlBarrier: @unchecked Sendable {
    private let condition = NSCondition()
    private var entered = false
    private var released = false

    func pause() {
        condition.lock()
        entered = true
        condition.broadcast()
        while !released { condition.wait() }
        condition.unlock()
    }

    func waitUntilEntered(timeoutMillis: Int64) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        let deadline = Date(timeIntervalSinceNow: Double(timeoutMillis) / 1_000)
        while !entered {
            if !condition.wait(until: deadline) { return false }
        }
        return true
    }

    func release() {
        condition.lock()
        released = true
        condition.broadcast()
        condition.unlock()
    }
}

private final class TestControlSignal: @unchecked Sendable {
    private let semaphore = DispatchSemaphore(value: 0)

    func signal() { semaphore.signal() }

    func wait(timeoutMillis: Int64) -> Bool {
        semaphore.wait(timeout: .now() + .milliseconds(Int(timeoutMillis))) == .success
    }
}

private final class DebugTestCredentialStore: CredentialStore, StoreFaultInjecting, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Credential?
    var value: Credential? { lock.withLock { stored } }
    func setStoreFault(_ kind: String?) {}
    func readVerified() throws -> Credential? { lock.withLock { stored } }
    func replaceVerified(_ credential: Credential) throws { lock.withLock { stored = credential } }
    func clearVerified() throws { lock.withLock { stored = nil } }
}

private final class TestCredentialStore: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var value: Credential?
    private var recordedMutations: [String] = []
    private var failClear = false
    private var failRead = false
    private var failReplacementReadback = false
    private var recordedReadCount = 0

    var credential: Credential? { lock.withLock { value } }
    var mutations: [String] { lock.withLock { recordedMutations } }
    var readCount: Int { lock.withLock { recordedReadCount } }

    func failNextClear() { lock.withLock { failClear = true } }
    func failNextRead() { lock.withLock { failRead = true } }
    func failNextReplacementAfterWrite() { lock.withLock { failReplacementReadback = true } }

    func readVerified() throws -> Credential? {
        try lock.withLock {
            recordedReadCount += 1
            if failRead {
                failRead = false
                throw CredentialStoreError.readFailed
            }
            return value
        }
    }

    func replaceVerified(_ credential: Credential) throws {
        try lock.withLock {
            value = credential
            recordedMutations.append("replace:\(credential.account.rawValue):\(credential.version)")
            if failReplacementReadback {
                failReplacementReadback = false
                throw CredentialStoreError.readbackFailed
            }
        }
    }

    func clearVerified() throws {
        try lock.withLock {
            if failClear {
                failClear = false
                throw CredentialStoreError.clearFailed
            }
            value = nil
            recordedMutations.append("clear")
        }
    }
}

private final class TestRefreshTransport: RefreshTransport, @unchecked Sendable {
    struct Pending: Sendable {
        let slot: RefreshSlot
        let completion: @Sendable (Completion) -> Void
    }

    private let lock = NSLock()
    private var pending: Pending?
    private var recordedStartedSlots: [RefreshSlot] = []
    private var recordedCancelCount = 0

    var startedSlots: [RefreshSlot] { lock.withLock { recordedStartedSlots } }
    var cancelCount: Int { lock.withLock { recordedCancelCount } }

    func start(
        slot: RefreshSlot,
        credential: Credential,
        completion: @escaping @Sendable (Completion) -> Void
    ) -> any TransportHandle {
        lock.withLock {
            pending = Pending(slot: slot, completion: completion)
            recordedStartedSlots.append(slot)
        }
        return TestTransportHandle { [weak self] in
            self?.lock.withLock { self?.recordedCancelCount += 1 }
        }
    }

    func waitForPending() async throws -> Pending {
        for _ in 0..<200 {
            if let value = lock.withLock({ pending }) { return value }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        throw TestFailure.timeout("refresh transport was not started")
    }

    func deliver(_ pending: Pending, outcome: RefreshOutcome) {
        pending.completion(Completion(slot: pending.slot, outcome: outcome))
    }
}

private struct TestTransportHandle: TransportHandle {
    let onCancel: @Sendable () -> Void
    func cancel() { onCancel() }
}

private actor TestBarrier {
    private var arrived = false
    private var released = false
    private var arrivalWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func pause() async {
        arrived = true
        arrivalWaiters.forEach { $0.resume() }
        arrivalWaiters.removeAll()
        guard !released else { return }
        await withCheckedContinuation { releaseWaiters.append($0) }
    }

    func waitForArrival() async {
        guard !arrived else { return }
        await withCheckedContinuation { arrivalWaiters.append($0) }
    }

    func release() {
        released = true
        releaseWaiters.forEach { $0.resume() }
        releaseWaiters.removeAll()
    }
}

private final class TestScenarioHooks: ScenarioHooks, @unchecked Sendable {
    private let lock = NSLock()
    private var barriers: [HookPoint: TestBarrier] = [:]
    private var recordedStoreIoActive = false

    var storeIoActive: Bool { lock.withLock { recordedStoreIoActive } }

    func storeIOChanged(_ active: Bool) { lock.withLock { recordedStoreIoActive = active } }

    func arm(_ point: HookPoint) {
        lock.withLock { barriers[point] = TestBarrier() }
    }

    func pauseIfArmed(_ point: HookPoint) async {
        guard let barrier = lock.withLock({ barriers[point] }) else { return }
        await barrier.pause()
        lock.withLock { barriers[point] = nil }
    }

    func waitForArrival(_ point: HookPoint) async {
        guard let barrier = lock.withLock({ barriers[point] }) else { return }
        await barrier.waitForArrival()
    }

    func release(_ point: HookPoint) async {
        await lock.withLock({ barriers[point] })?.release()
    }
}

@MainActor
private final class RecordingViewPublisher: ViewPublisher {
    private(set) var current: DemoViewState?
    private(set) var currentStore: StoreObservation?
    private(set) var published: [DemoViewState] = []
    private var nextGate: TestBarrier?

    func blockNextPublication(on gate: TestBarrier) {
        nextGate = gate
    }

    func publish(_ view: DemoViewState, store: StoreObservation) async {
        if let gate = nextGate {
            nextGate = nil
            await gate.pause()
        }
        current = view
        currentStore = store
        published.append(view)
    }

    func waitForCommand(_ commandId: Int64) async throws -> DemoViewState {
        for _ in 0..<200 {
            if let current, current.lastCompletedCommandId == commandId { return current }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        throw TestFailure.timeout("view did not acknowledge command \(commandId)")
    }
}

private final class MemoryAuditRecorder: AuditRecorder, @unchecked Sendable {
    private let lock = NSLock()
    private var sequence: Int64 = 0
    private var records: [(kind: String, fields: Data)] = []

    func append(kind: String, fields: Data) throws -> Int64 {
        lock.withLock {
            sequence += 1
            records.append((kind, fields))
            return sequence
        }
    }

    func synchronize() throws {}

    func count(kind: String) -> Int {
        lock.withLock { records.filter { $0.kind == kind }.count }
    }

    var eventRows: [[String: Any]] {
        lock.withLock {
            records.enumerated().compactMap { index, record in
                guard var row = try? JSONSerialization.jsonObject(with: record.fields) as? [String: Any] else { return nil }
                row["kind"] = record.kind
                row["localSequence"] = Int64(index + 1)
                return row
            }
        }
    }

    /// Rows for one command in log order; `kind == nil` returns every kind.
    func commandRows(kind: String?, commandId: Int64) -> [[String: Any]] {
        eventRows.filter { row in
            guard kind == nil || row["kind"] as? String == kind,
                  let reference = row["commandRef"] as? [String: Any],
                  let number = reference["id"] as? NSNumber else { return false }
            return number.int64Value == commandId
        }
    }

    func hookRows(point: HookPoint) -> [[String: Any]] {
        eventRows.filter { $0["kind"] as? String == "hookEvent" && $0["point"] as? String == point.rawValue }
    }

    func hasManagedReduction(commandId: Int64) -> Bool {
        lock.withLock {
            records.contains { record in
                guard record.kind == "managedReduced",
                      let row = try? JSONSerialization.jsonObject(with: record.fields) as? [String: Any],
                      let reference = row["commandRef"] as? [String: Any],
                      let number = reference["id"] as? NSNumber else { return false }
                return number.int64Value == commandId
            }
        }
    }

    func waitForEnqueued(_ commandName: String) async throws -> Int64 {
        for _ in 0..<200 {
            if let commandId = lock.withLock({
                records.compactMap { record -> Int64? in
                    guard record.kind == "commandEnqueued",
                          let row = try? JSONSerialization.jsonObject(with: record.fields) as? [String: Any],
                          row["name"] as? String == commandName,
                          let reference = row["commandRef"] as? [String: Any],
                          let number = reference["id"] as? NSNumber else { return nil }
                    return number.int64Value
                }.first
            }) {
                return commandId
            }
            try await Task.sleep(nanoseconds: 5_000_000)
        }
        throw TestFailure.timeout("command \(commandName) was not synchronously recorded as enqueued")
    }
}

private enum TestFailure: Error {
    case timeout(String)
}
