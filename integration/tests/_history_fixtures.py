"""Hand-authored histories for the evaluator; no values come from an app."""

import copy


def _ref(process_id, ident):
    return {"processInstanceId": process_id, "id": ident}


def _store(kind, account=None, version=None):
    value = {"kind": kind}
    if account is not None:
        value.update(account=account, version=version)
    return value


def _managed(owner, state, pending, next_id):
    return {
        "ownerId": owner,
        "state": state,
        "pendingRequestId": pending,
        "nextRequestId": next_id,
    }


def _effect(name, request_id=None):
    effect = {"effect": name}
    if request_id is not None:
        effect["requestId"] = request_id
    return effect


def _view(phase, account=None, version=None, pending=None, command_id=None, status=None):
    return {
        "phase": phase,
        "account": account,
        "credentialVersion": version,
        "pendingRequestId": pending,
        "lastCompletedCommandId": command_id,
        "lastCommandStatus": status,
    }


class _ProcessHistory:
    def __init__(self, process_id, launch_ordinal, owner_id):
        self.process_id = process_id
        self.launch_ordinal = launch_ordinal
        self.owner_id = owner_id
        self.sequence = 0
        self.revision = 0
        self.events = []
        self.command_inventory = []
        self.add("processStart", initialView=_view("Booting"))

    def add(self, kind, **fields):
        self.sequence += 1
        event = {
            "processInstanceId": self.process_id,
            "launchOrdinal": self.launch_ordinal,
            "localSequence": self.sequence,
            "kind": kind,
            **fields,
        }
        self.events.append(event)
        return event

    def _ack(self, command_ref, view):
        self.revision += 1
        return self.add(
            "uiPublishAck",
            commandRef=command_ref,
            revision=self.revision,
            view=view,
        )

    def command(
        self,
        ident,
        name,
        *,
        managed_event=None,
        managed_pre=None,
        managed_result=None,
        managed_epoch_id=None,
        store_mutation=None,
        store_fault=None,
        fault_cleanup_mutation=None,
        verify_store=True,
        slot_issued=None,
        delivery=None,
        completion=None,
        final_store=None,
        phase,
        account=None,
        version=None,
        pending=None,
        status="Completed",
        signing_out=False,
        release_action_id=None,
        already_enqueued=False,
    ):
        command_ref = _ref(self.process_id, ident)
        completion = completion or delivery
        native_name = name
        if isinstance(name, str) and name.startswith("Deliver(") and isinstance(completion, dict):
            outcome_label = "success" if completion.get("outcome") == "success" else "failure"
            native_name = f"Deliver({completion['slotId']},{outcome_label})"
        if name == "Bootstrap" and store_mutation is None:
            store_mutation = {
                "operation": "clear",
                "cause": "Bootstrap",
                "before": _store("Absent"),
                "after": _store("Absent"),
            }
        if not already_enqueued:
            self.command_inventory.append({"commandRef": command_ref, "name": native_name})
            self.add("commandEnqueued", commandRef=command_ref, name=native_name)
        self.add("commandStarted", commandRef=command_ref)

        if signing_out:
            interim = _view(
                "SigningOut",
                command_id=ident - 1,
                status="Completed",
            )
            self._ack(command_ref, interim)

        if delivery is not None:
            self.add(
                "transportReceived",
                commandRef=command_ref,
                slotId=delivery["slotId"],
                outcome=delivery["outcome"],
                failureCode=delivery.get("failureCode"),
                requestTag=delivery["requestTag"],
            )
        if managed_event is not None:
            self.add(
                "managedReduced",
                commandRef=command_ref,
                event=managed_event,
                pre=managed_pre,
                result=managed_result,
                epochId=managed_epoch_id or (delivery["epochId"] if delivery else "epoch-1"),
                **({"slotId": completion["slotId"], "requestOwnerId": completion["ownerId"]} if completion else {}),
                **({} if completion is not None else {}),
            )
        if slot_issued is not None:
            self.add("slotIssued", commandRef=command_ref, **slot_issued)
        if store_mutation is not None:
            mutation = {
                "commandRef": command_ref,
                **store_mutation,
            }
            if release_action_id is not None:
                mutation["releaseActionId"] = release_action_id
            self.add("storeMutation", **mutation)
            if verify_store:
                self.add(
                    "storeReadback",
                    commandRef=command_ref,
                    operation=store_mutation["operation"],
                    observation=store_mutation["after"],
                )
        if store_fault is not None:
            self.add("storeFault", commandRef=command_ref, **store_fault)
        if fault_cleanup_mutation is not None:
            cleanup = {"commandRef": command_ref, **fault_cleanup_mutation}
            self.add("storeMutation", **cleanup)
            self.add("storeReadback", commandRef=command_ref, operation="clear", observation=fault_cleanup_mutation["after"])

        view = _view(
            phase,
            account=account,
            version=version,
            pending=pending,
            command_id=ident,
            status=status,
        )
        acknowledgement = self._ack(command_ref, view)
        post = managed_result or managed_pre or _managed(self.owner_id, "Unauthenticated", None, 1)
        observation = {
            "managed": {key: post[key] for key in ("ownerId", "state", "pendingRequestId", "nextRequestId")},
            "store": final_store or _store("Absent"),
            "view": view,
            "revision": self.revision,
        }
        receipt = self.add(
            "commandReceipt",
            commandRef=command_ref,
            status=status,
            observation=observation,
            acknowledgedEventRef={
                "processInstanceId": self.process_id,
                "localSequence": acknowledgement["localSequence"],
            },
        )
        if completion is not None:
            self.add(
                "completionProcessed",
                commandRef=command_ref,
                slotId=completion["slotId"],
                receiptEventRef={
                    "processInstanceId": self.process_id,
                    "localSequence": receipt["localSequence"],
                },
            )
        return {"commandRef": command_ref, "ack": acknowledgement, "receipt": receipt}

    def end(self):
        return self.add("processEnd")


def _with_process_end_acks(trace, observations=None):
    """Complete a hand-authored trace with an ack bound to its real fixture end row."""
    controller = trace["controllerEvents"]
    for process in trace["processInstances"]:
        process_id = process["processInstanceId"]
        if any(row.get("kind") == "processEndAcknowledged" and row.get("processInstanceId") == process_id for row in controller):
            continue
        end_rows = [
            event for event in trace["events"]
            if event.get("kind") == "processEnd" and event.get("processInstanceId") == process_id
        ]
        if len(end_rows) != 1:
            continue
        end_row = end_rows[0]
        insert_at = next((
            index for index, row in enumerate(controller)
            if row.get("processInstanceId") == process_id and row.get("kind") in {"forceStopped", "terminated"}
        ), None)
        if insert_at is None:
            same_process = [index for index, row in enumerate(controller) if row.get("processInstanceId") == process_id]
            insert_at = (max(same_process) + 1) if same_process else len(controller)
        controller.insert(insert_at, {
            "sequence": 0,
            "kind": "processEndAcknowledged",
            "processInstanceId": process_id,
            "eventRef": {"processInstanceId": process_id, "localSequence": end_row["localSequence"]},
        })
    for sequence, row in enumerate(controller, start=1):
        row["sequence"] = sequence
    if observations is not None:
        rows = [observations] if isinstance(observations, dict) else observations
        for observation in rows:
            if not isinstance(observation, dict) or observation.get("kind") != "storageProbe":
                continue
            matches = [
                row for row in controller
                if row.get("kind") == "probeCaptured"
                and row.get("processInstanceId") == observation.get("processInstanceId")
                and row.get("stepId") == observation.get("stepId")
            ]
            if len(matches) == 1:
                observation["controllerSequence"] = matches[0]["sequence"]
    return trace


def _successful_managed(owner, state, pending, next_id, event, result_state, result_pending, result_next, effects=()):
    return {
        "managed_event": event,
        "managed_pre": _managed(owner, state, pending, next_id),
        "managed_result": {
            **_managed(owner, result_state, result_pending, result_next),
            "effects": list(effects),
            "rejection": None,
        },
    }


def _app02_prefix(history):
    bootstrap = history.command(1, "Bootstrap", final_store=_store("Absent"), phase="SignedOut")
    login_reducer = _successful_managed(history.owner_id, "Unauthenticated", None, 1, {"event": "LoginSucceeded"}, "Authenticated", None, 1)
    login = history.command(
        2,
        "Login(A)",
        **login_reducer,
        managed_epoch_id="epoch-1",
        store_mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-1", "before": _store("Absent"), "after": _store("Present", "A", 0)},
        final_store=_store("Present", "A", 0),
        phase="SignedIn",
        account="A",
        version=0,
    )
    expire_reducer = _successful_managed(history.owner_id, "Authenticated", None, 1, {"event": "TokenExpired"}, "Refreshing", 1, 2, [_effect("RequestTokenRefresh", 1)])
    expire = history.command(
        3,
        "Expire",
        **expire_reducer,
        managed_epoch_id="epoch-1",
        slot_issued={"slotId": "slot-A1", "ownerId": history.owner_id, "epochId": "epoch-1", "requestId": 1, "wireRequestId": "1", "account": "A", "seedVersion": 0, "wireTag": history.process_id + ":refresh:3"},
        final_store=_store("Present", "A", 0),
        phase="Refreshing",
        account="A",
        version=0,
        pending=1,
    )
    return bootstrap, login, expire


def make_app02_trace(*, unsafe_success=False, missing_delivery=False):
    process_id = "attempt-01/APP-02/p1"
    history = _ProcessHistory(process_id, 1, "owner-1")
    _, _, _ = _app02_prefix(history)
    logout_reducer = _successful_managed(history.owner_id, "Refreshing", 1, 2, {"event": "Logout"}, "Unauthenticated", None, 2, [_effect("ClearCredentials")])
    logout = history.command(
        4,
        "Logout",
        **logout_reducer,
        managed_epoch_id="epoch-1",
        store_mutation={"operation": "clear", "cause": "Logout", "epochId": "epoch-1", "before": _store("Present", "A", 0), "after": _store("Absent")},
        final_store=_store("Absent"),
        phase="SignedOut",
        signing_out=True,
    )
    histories = [history]
    controller = [
        {"sequence": 1, "kind": "launch", "processInstanceId": process_id, "launchOrdinal": 1},
        {"sequence": 2, "kind": "requestHeld", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3"},
        {"sequence": 3, "kind": "receiptObserved", "processInstanceId": process_id, "commandRef": logout["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": logout["receipt"]["localSequence"]}},
        {"sequence": 4, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-02-after-logout-store"},
    ]
    server = [{"runId": "run-app-02", "sequence": 1, "kind": "requestHeld", "requestTag": process_id + ":refresh:3", "requestId": "1"}]
    observations = [
        {"kind": "storageProbe", "stepId": "APP-02-after-logout-store", "processInstanceId": process_id, "commandRef": logout["commandRef"], "controllerSequence": 4, "observation": _store("Absent")},
        {"kind": "renderedView", "stepId": "APP-02-after-logout-view", "processInstanceId": process_id, "revision": 5, "eventRef": {"processInstanceId": process_id, "localSequence": logout["ack"]["localSequence"]}, "phase": "SignedOut", "account": None},
    ]

    if not missing_delivery:
        controller.extend([
            {"sequence": 5, "kind": "releaseRequested", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3"},
            {"sequence": 6, "kind": "releaseAccepted", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3", "serverSequence": 2},
            {"sequence": 7, "kind": "responseWritten", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3", "serverSequence": 3},
        ])
        server.extend([
            {"runId": "run-app-02", "sequence": 2, "kind": "releaseAccepted", "requestTag": process_id + ":refresh:3", "outcome": "success"},
            {"runId": "run-app-02", "sequence": 3, "kind": "responseWritten", "requestTag": process_id + ":refresh:3", "outcome": "success"},
        ])
        stale_event = {"event": "RefreshSucceeded", "requestId": 1}
        stale_result = _managed(history.owner_id, "Unauthenticated", None, 2)
        stale_reducer = {
            "managed_event": stale_event,
            "managed_pre": _managed(history.owner_id, "Unauthenticated", None, 2),
            "managed_result": {**stale_result, "effects": [], "rejection": None},
        }
        delivery = {"slotId": "slot-A1", "outcome": "success", "requestTag": process_id + ":refresh:3", "ownerId": "owner-1", "epochId": "epoch-1"}
        write = None
        phase, account, version, final_store, status = "SignedOut", None, None, _store("Absent"), "IgnoredStale"
        if unsafe_success:
            write = {"operation": "replace", "cause": "RefreshSuccess", "slotId": "slot-A1", "epochId": "epoch-1", "ownerId": "owner-1", "before": _store("Absent"), "after": _store("Present", "A", 1)}
            phase, account, version, final_store = "SignedIn", "A", 1, _store("Present", "A", 1)
        deliver = history.command(
            5,
            "Deliver(slot-A1,success)",
            **stale_reducer,
            managed_epoch_id="epoch-1",
            delivery=delivery,
            store_mutation=write,
            final_store=final_store,
            phase=phase,
            account=account,
            version=version,
            status=status,
        )
        controller.extend([
            {"sequence": 8, "kind": "completionProcessedObserved", "processInstanceId": process_id, "commandRef": deliver["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": history.events[-1]["localSequence"]}},
            {"sequence": 9, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-02-final-probe"},
            {"sequence": 10, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1},
        ])
        observations.extend([
            {"kind": "storageProbe", "stepId": "APP-02-final-probe", "processInstanceId": process_id, "commandRef": deliver["commandRef"], "controllerSequence": 9, "observation": final_store},
            {"kind": "renderedView", "stepId": "APP-02-final-view", "processInstanceId": process_id, "revision": 6, "eventRef": {"processInstanceId": process_id, "localSequence": deliver["ack"]["localSequence"]}, "phase": phase, "account": account},
        ])
        history.end()
    else:
        controller.append({"sequence": 5, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1})
        history.end()

    trace = {
        "version": 1,
        "runId": "run-app-02",
        "scenarioId": "APP-02",
        "platform": "ios",
        "buildHash": "sha256:" + "a" * 64,
        "processInstances": [{"processInstanceId": process_id, "launchOrdinal": 1}],
        "controllerEvents": controller,
        "commandInventory": list(history.command_inventory),
        "events": list(history.events),
        "artifactPaths": ["APP-02/p1/native.jsonl", "APP-02/p1/ui.jsonl"],
    }
    return _with_process_end_acks(trace, observations), server, observations


def make_app05_trace(*, unsafe_clear_b=False):
    scenario_id = "APP-05"
    run_id = "run-app-05"
    process_id = "attempt-01/APP-05/p1"
    history = _ProcessHistory(process_id, 1, "owner-1")
    _, _, _ = _app02_prefix(history)
    logout_reducer = _successful_managed(history.owner_id, "Refreshing", 1, 2, {"event": "Logout"}, "Unauthenticated", None, 2, [_effect("ClearCredentials")])
    logout = history.command(4, "Logout", **logout_reducer, managed_epoch_id="epoch-1", store_mutation={"operation": "clear", "cause": "Logout", "epochId": "epoch-1", "before": _store("Present", "A", 0), "after": _store("Absent")}, final_store=_store("Absent"), phase="SignedOut", signing_out=True)
    login_b_reducer = _successful_managed(history.owner_id, "Unauthenticated", None, 2, {"event": "LoginSucceeded"}, "Authenticated", None, 2)
    login_b = history.command(5, "Login(B)", **login_b_reducer, managed_epoch_id="epoch-2", store_mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-2", "before": _store("Absent"), "after": _store("Present", "B", 0)}, final_store=_store("Present", "B", 0), phase="SignedIn", account="B", version=0)
    stale_reducer = {
        "managed_event": {"event": "RefreshFailed", "requestId": 1},
        "managed_pre": _managed(history.owner_id, "Authenticated", None, 2),
        "managed_result": {**_managed(history.owner_id, "Authenticated", None, 2), "effects": [], "rejection": None},
    }
    delivery = {"slotId": "slot-A1", "outcome": "failure", "failureCode": "rejected", "requestTag": process_id + ":refresh:3", "ownerId": "owner-1", "epochId": "epoch-1"}
    write = None
    final_store, phase, account, version = _store("Present", "B", 0), "SignedIn", "B", 0
    if unsafe_clear_b:
        write = {"operation": "clear", "cause": "RefreshFailure", "slotId": "slot-A1", "epochId": "epoch-1", "ownerId": "owner-1", "before": _store("Present", "B", 0), "after": _store("Absent")}
        final_store, phase, account, version = _store("Absent"), "SignedOut", None, None
    deliver = history.command(6, "Deliver(slot-A1,failure)", **stale_reducer, managed_epoch_id="epoch-1", delivery=delivery, store_mutation=write, final_store=final_store, phase=phase, account=account, version=version, status="IgnoredStale")
    history.end()

    controller = [
        {"sequence": 1, "kind": "launch", "processInstanceId": process_id, "launchOrdinal": 1},
        {"sequence": 2, "kind": "requestHeld", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3"},
        {"sequence": 3, "kind": "receiptObserved", "processInstanceId": process_id, "commandRef": logout["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": logout["receipt"]["localSequence"]}},
        {"sequence": 4, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-05-after-logout-store"},
        {"sequence": 5, "kind": "receiptObserved", "processInstanceId": process_id, "commandRef": login_b["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": login_b["receipt"]["localSequence"]}},
        {"sequence": 6, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-05-after-login-b-store"},
        {"sequence": 7, "kind": "releaseRequested", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3"},
        {"sequence": 8, "kind": "releaseAccepted", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3", "serverSequence": 2},
        {"sequence": 9, "kind": "responseWritten", "processInstanceId": process_id, "requestTag": process_id + ":refresh:3", "serverSequence": 3},
        {"sequence": 10, "kind": "completionProcessedObserved", "processInstanceId": process_id, "commandRef": deliver["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": history.events[-2]["localSequence"]}},
        {"sequence": 11, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-05-final-probe"},
        {"sequence": 12, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1},
    ]
    server = [
        {"runId": run_id, "sequence": 1, "kind": "requestHeld", "requestTag": process_id + ":refresh:3", "requestId": "1"},
        {"runId": run_id, "sequence": 2, "kind": "releaseAccepted", "requestTag": process_id + ":refresh:3", "outcome": "failure"},
        {"runId": run_id, "sequence": 3, "kind": "responseWritten", "requestTag": process_id + ":refresh:3", "outcome": "failure"},
    ]
    observations = [
        {"kind": "storageProbe", "stepId": "APP-05-after-logout-store", "processInstanceId": process_id, "commandRef": logout["commandRef"], "controllerSequence": 4, "observation": _store("Absent")},
        {"kind": "renderedView", "stepId": "APP-05-after-logout-view", "processInstanceId": process_id, "revision": 5, "eventRef": {"processInstanceId": process_id, "localSequence": logout["ack"]["localSequence"]}, "phase": "SignedOut", "account": None},
        {"kind": "storageProbe", "stepId": "APP-05-after-login-b-store", "processInstanceId": process_id, "commandRef": login_b["commandRef"], "controllerSequence": 6, "observation": _store("Present", "B", 0)},
        {"kind": "renderedView", "stepId": "APP-05-after-login-b-view", "processInstanceId": process_id, "revision": 6, "eventRef": {"processInstanceId": process_id, "localSequence": login_b["ack"]["localSequence"]}, "phase": "SignedIn", "account": "B"},
        {"kind": "storageProbe", "stepId": "APP-05-final-probe", "processInstanceId": process_id, "commandRef": deliver["commandRef"], "controllerSequence": 11, "observation": final_store},
        {"kind": "renderedView", "stepId": "APP-05-final-view", "processInstanceId": process_id, "revision": 7, "eventRef": {"processInstanceId": process_id, "localSequence": deliver["ack"]["localSequence"]}, "phase": phase, "account": account},
    ]
    trace = {
        "version": 1,
        "runId": run_id,
        "scenarioId": scenario_id,
        "platform": "ios",
        "buildHash": "sha256:" + "b" * 64,
        "processInstances": [{"processInstanceId": process_id, "launchOrdinal": 1}],
        "controllerEvents": controller,
        "commandInventory": list(history.command_inventory),
        "events": list(history.events),
        "artifactPaths": ["APP-05/p1/native.jsonl", "APP-05/p1/ui.jsonl"],
    }
    return _with_process_end_acks(trace, observations), server, observations


def make_app13_trace(variant_id):
    """Hand-authored complete current-fault or stale-fault APP-13 history."""
    codes = {
        "http500-current": ("Deliver(current,serverError)", "server", "http500"),
        "malformed-current": ("Deliver(current,malformed)", "malformed", "malformed"),
        "disconnect-current": ("Deliver(current,disconnected)", "disconnected", "disconnect"),
        "wrong-correlation-current": ("Deliver(current,correlationMismatch)", "wrongCorrelation", "wrongCorrelation"),
    }
    if variant_id == "wrong-correlation-after-login-b":
        trace, server, observations = make_app05_trace()
        def rename(value):
            if isinstance(value, str):
                return value.replace("APP-05", "APP-13").replace("run-app-05", "run-app-13")
            if isinstance(value, list):
                return [rename(item) for item in value]
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            return value
        trace, server, observations = rename(trace), rename(server), rename(observations)
        trace["scenarioId"] = "APP-13"
        trace["variantId"] = variant_id
        trace["runId"] = "run-app-13"
        for event in trace["events"]:
            if event.get("kind") == "transportReceived":
                event["failureCode"] = "wrongCorrelation"
        server = [
            {**event, "runId": "run-app-13", **({"outcome": "wrongCorrelation"} if event.get("kind") == "releaseAccepted" else {})}
            for event in server
        ]
        request_tag = next(event["requestTag"] for event in server if event["kind"] == "requestHeld")
        written = next(event for event in server if event["kind"] == "responseWritten")
        written["sequence"] = 4
        wrong_tag = request_tag + ":wrong-correlation"
        server.append({"runId": "run-app-13", "sequence": 3, "kind": "wrongCorrelation", "requestTag": request_tag, "echoedRequestTag": wrong_tag})
        server.sort(key=lambda event: event["sequence"])
        controller = trace["controllerEvents"]
        controller_written = next(event for event in controller if event["kind"] == "responseWritten")
        controller_written["serverSequence"] = 4
        insert_sequence = controller_written["sequence"]
        for event in controller:
            if event["sequence"] >= insert_sequence:
                event["sequence"] += 1
        controller.append({
            "sequence": insert_sequence,
            "kind": "wrongCorrelation",
            "processInstanceId": trace["processInstances"][0]["processInstanceId"],
            "requestTag": request_tag,
            "serverSequence": 3,
            "echoedRequestTag": wrong_tag,
        })
        controller.sort(key=lambda event: event["sequence"])
        for observation in observations:
            if observation.get("controllerSequence", 0) >= insert_sequence:
                observation["controllerSequence"] += 1
        return _with_process_end_acks(trace, observations), server, observations

    command_name, failure_code, release_outcome = codes[variant_id]
    process_id = f"attempt-01/APP-13/p1"
    run_id = "run-app-13"
    history = _ProcessHistory(process_id, 1, "owner-1")
    history.command(1, "Bootstrap", phase="SignedOut", final_store=_store("Absent"))
    login = _successful_managed(history.owner_id, "Unauthenticated", None, 1, {"event": "LoginSucceeded"}, "Authenticated", None, 1)
    history.command(2, "Login(A)", **login, managed_epoch_id="epoch-1", store_mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-1", "before": _store("Absent"), "after": _store("Present", "A", 0)}, final_store=_store("Present", "A", 0), phase="SignedIn", account="A", version=0)
    expire = _successful_managed(history.owner_id, "Authenticated", None, 1, {"event": "TokenExpired"}, "Refreshing", 1, 2, [_effect("RequestTokenRefresh", 1)])
    request_tag = process_id + ":refresh:3"
    history.command(3, "Expire", **expire, managed_epoch_id="epoch-1", slot_issued={"slotId":"slot-A1","ownerId":history.owner_id,"epochId":"epoch-1","requestId":1,"wireRequestId":"1","account":"A","seedVersion":0,"wireTag":request_tag}, final_store=_store("Present","A",0), phase="Refreshing", account="A", version=0, pending=1)
    delivery={"slotId":"slot-A1","outcome":"failure","failureCode":failure_code,"requestTag":request_tag,"ownerId":history.owner_id,"epochId":"epoch-1"}
    failure={"managed_event":{"event":"RefreshFailed","requestId":1},"managed_pre":_managed(history.owner_id,"Refreshing",1,2),"managed_result":{**_managed(history.owner_id,"Unauthenticated",None,2),"effects":[_effect("ClearCredentials")],"rejection":None}}
    delivered=history.command(4,command_name,**failure,managed_epoch_id="epoch-1",delivery=delivery,store_mutation={"operation":"clear","cause":"RefreshFailure","slotId":"slot-A1","epochId":"epoch-1","ownerId":history.owner_id,"before":_store("Present","A",0),"after":_store("Absent")},final_store=_store("Absent"),phase="SignedOut",status="Completed")
    history.end()
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"requestHeld","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":3,"kind":"releaseRequested","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":4,"kind":"releaseAccepted","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":2},
    ]
    server=[
      {"runId":run_id,"sequence":1,"kind":"requestHeld","requestTag":request_tag,"requestId":"1"},
      {"runId":run_id,"sequence":2,"kind":"releaseAccepted","requestTag":request_tag,"outcome":release_outcome},
    ]
    if variant_id == "http500-current":
      server.extend([{ "runId":run_id,"sequence":3,"kind":"http500","requestTag":request_tag },{ "runId":run_id,"sequence":4,"kind":"responseWritten","requestTag":request_tag,"outcome":"http500" }])
      controller.append({"sequence":5,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":4})
    elif variant_id == "malformed-current":
      server.extend([{ "runId":run_id,"sequence":3,"kind":"malformed","requestTag":request_tag },{ "runId":run_id,"sequence":4,"kind":"responseWritten","requestTag":request_tag,"outcome":"malformed" }])
      controller.append({"sequence":5,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":4})
    elif variant_id == "disconnect-current":
      server.append({"runId":run_id,"sequence":3,"kind":"disconnected","requestTag":request_tag,"outcome":"disconnect"})
      controller.append({"sequence":5,"kind":"disconnected","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3})
    elif variant_id == "wrong-correlation-current":
      echoed_tag=request_tag+":wrong-correlation"
      server.extend([
        {"runId":run_id,"sequence":3,"kind":"wrongCorrelation","requestTag":request_tag,"echoedRequestTag":echoed_tag},
        {"runId":run_id,"sequence":4,"kind":"responseWritten","requestTag":request_tag,"outcome":"failure"},
      ])
      controller.extend([
        {"sequence":5,"kind":"wrongCorrelation","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3,"echoedRequestTag":echoed_tag},
        {"sequence":6,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":4},
      ])
    else:
      server.append({"runId":run_id,"sequence":3,"kind":"responseWritten","requestTag":request_tag,"outcome":"success"})
      controller.append({"sequence":5,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3})
    completion=next(event for event in history.events if event.get("kind")=="completionProcessed")
    next_controller_sequence=len(controller)+1
    receipt={"sequence":next_controller_sequence,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["receipt"]["localSequence"]}}
    controller.extend([
      receipt,
      {"sequence":next_controller_sequence+1,"kind":"completionProcessedObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":completion["localSequence"]}},
      {"sequence":next_controller_sequence+2,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-13-final-probe"},
      {"sequence":next_controller_sequence+3,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ])
    observations=[
      {"kind":"storageProbe","stepId":"APP-13-final-probe","processInstanceId":process_id,"commandRef":delivered["commandRef"],"controllerSequence":next_controller_sequence+2,"observation":_store("Absent")},
      {"kind":"renderedView","stepId":"APP-13-final-view","processInstanceId":process_id,"revision":delivered["ack"]["revision"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["ack"]["localSequence"]},"phase":"SignedOut","account":None},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":"APP-13","variantId":variant_id,"platform":"ios","buildHash":"sha256:"+"f"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":["APP-13/p1/native.jsonl","APP-13/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observations),server,observations


def make_app09_trace(variant_id):
    """A complete current-refresh history for each replace-fault inventory row."""
    faults={
      "replace-before":("replaceBefore",False,_store("Present","A",0),None),
      "replace-after-before-verify":("replaceAfterBeforeVerify",True,{"kind":"Unknown","errorCode":"readFailed"},{"operation":"replace","cause":"RefreshSuccess","slotId":"slot-A1","epochId":"epoch-1","ownerId":"owner-1","before":_store("Present","A",0),"after":_store("Present","A",1)}),
    }
    fault_name,applied,observed,mutation=faults[variant_id]
    process_id="attempt-01/APP-09/p1"
    run_id="run-app-09"
    request_tag=process_id+":refresh:3"
    history=_ProcessHistory(process_id,1,"owner-1")
    history.command(1,"Bootstrap",phase="SignedOut",final_store=_store("Absent"))
    login=_successful_managed("owner-1","Unauthenticated",None,1,{"event":"LoginSucceeded"},"Authenticated",None,1)
    history.command(2,"Login(A)",**login,managed_epoch_id="epoch-1",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-1","before":_store("Absent"),"after":_store("Present","A",0)},final_store=_store("Present","A",0),phase="SignedIn",account="A",version=0)
    expire=_successful_managed("owner-1","Authenticated",None,1,{"event":"TokenExpired"},"Refreshing",1,2,[_effect("RequestTokenRefresh",1)])
    history.command(3,"Expire",**expire,managed_epoch_id="epoch-1",slot_issued={"slotId":"slot-A1","ownerId":"owner-1","epochId":"epoch-1","requestId":1,"wireRequestId":"1","account":"A","seedVersion":0,"wireTag":request_tag},final_store=_store("Present","A",0),phase="Refreshing",account="A",version=0,pending=1)
    delivery={"slotId":"slot-A1","outcome":"success","failureCode":None,"requestTag":request_tag,"ownerId":"owner-1","epochId":"epoch-1"}
    success={"managed_event":{"event":"RefreshSucceeded","requestId":1},"managed_pre":_managed("owner-1","Refreshing",1,2),"managed_result":{**_managed("owner-1","Authenticated",None,2),"effects":[],"rejection":None}}
    store_fault={"operation":"replace","fault":fault_name,"mutationApplied":applied,"verification":"failed" if applied else "notAttempted","before":_store("Present","A",0),"observation":observed}
    final_store=_store("Absent")
    cleanup={"operation":"clear","cause":"FaultCleanup","before":observed,"after":final_store}
    delivered=history.command(4,"Deliver(current,success)",**success,managed_epoch_id="epoch-1",delivery=delivery,store_mutation=mutation,store_fault=store_fault,fault_cleanup_mutation=cleanup,verify_store=not applied,final_store=final_store,phase="FaultLocked",status="FaultLocked")
    history.end()
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"requestHeld","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":3,"kind":"releaseRequested","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":4,"kind":"releaseAccepted","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":2},
      {"sequence":5,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3},
      {"sequence":6,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["receipt"]["localSequence"]}},
      {"sequence":7,"kind":"completionProcessedObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":next(event["localSequence"] for event in history.events if event.get("kind")=="completionProcessed")}},
      {"sequence":8,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-09-final-probe"},
      {"sequence":9,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ]
    server=[
      {"runId":run_id,"sequence":1,"kind":"requestHeld","requestTag":request_tag,"requestId":"1"},
      {"runId":run_id,"sequence":2,"kind":"releaseAccepted","requestTag":request_tag,"outcome":"success"},
      {"runId":run_id,"sequence":3,"kind":"responseWritten","requestTag":request_tag,"outcome":"success"},
    ]
    observations=[
      {"kind":"storageProbe","stepId":"APP-09-final-probe","processInstanceId":process_id,"commandRef":delivered["commandRef"],"controllerSequence":8,"observation":final_store},
      {"kind":"renderedView","stepId":"APP-09-final-view","processInstanceId":process_id,"revision":delivered["ack"]["revision"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["ack"]["localSequence"]},"phase":"FaultLocked","account":None},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":"APP-09","variantId":variant_id,"platform":"ios","buildHash":"sha256:"+"9"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":["APP-09/p1/native.jsonl","APP-09/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observations),server,observations


def make_app08_trace(*, unsafe_success=False):
    """Cancellation control with an explicit late, cancellation-disabled response."""
    trace, server, observations = make_app02_trace(unsafe_success=unsafe_success)
    def rename(value):
        if isinstance(value,str): return value.replace("APP-02","APP-08")
        if isinstance(value,list): return [rename(item) for item in value]
        if isinstance(value,dict): return {key:rename(item) for key,item in value.items()}
        return value
    trace,server,observations=rename(trace),rename(server),rename(observations)
    trace["scenarioId"]="APP-08"
    for event in trace["controllerEvents"]:
        if event.get("kind")=="probeCaptured": event["stepId"]=event["stepId"].replace("after-logout","after-cancel")
    for item in observations:
        item["stepId"]=item["stepId"].replace("after-logout","after-cancel")
    for item in trace["commandInventory"]:
        if item["commandRef"]["id"]==4: item["name"]="CancelRefresh"
    for event in trace["events"]:
        if event.get("kind")=="commandEnqueued" and event.get("commandRef",{}).get("id")==4: event["name"]="CancelRefresh"
        if event.get("kind")=="storeMutation" and event.get("commandRef",{}).get("id")==4: event["cause"]="CancelRefresh"
    return _with_process_end_acks(trace, observations),server,observations


def make_app10_trace(variant_id):
    """A complete clear-fault, verified retry and new-login history."""
    faults={
      "clear-before":("clearBefore",False,_store("Present","A",0),_store("Present","A",0)),
      "clear-after-before-verify":("clearAfterBeforeVerify",True,{"kind":"Unknown","errorCode":"readFailed"},_store("Absent")),
    }
    fault_name,applied,receipt_readback,physical_after_logout=faults[variant_id]
    process_id="attempt-01/APP-10/p1"
    run_id="run-app-10"
    history=_ProcessHistory(process_id,1,"owner-1")
    history.command(1,"Bootstrap",phase="SignedOut",final_store=_store("Absent"))
    login=_successful_managed("owner-1","Unauthenticated",None,1,{"event":"LoginSucceeded"},"Authenticated",None,1)
    history.command(2,"Login(A)",**login,managed_epoch_id="epoch-1",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-1","before":_store("Absent"),"after":_store("Present","A",0)},final_store=_store("Present","A",0),phase="SignedIn",account="A",version=0)
    logout=_successful_managed("owner-1","Authenticated",None,1,{"event":"Logout"},"Unauthenticated",None,1,[_effect("ClearCredentials")])
    mutation={"operation":"clear","cause":"Logout","epochId":"epoch-1","before":_store("Present","A",0),"after":_store("Absent")} if applied else None
    fault={"operation":"clear","fault":fault_name,"mutationApplied":applied,"verification":"failed" if applied else "notAttempted","before":_store("Present","A",0),"observation":receipt_readback}
    logout_result=history.command(3,"Logout",**logout,managed_epoch_id="epoch-1",store_mutation=mutation,store_fault=fault,verify_store=not applied,final_store=receipt_readback,phase="FaultLocked",status="FaultLocked",signing_out=True)
    retry=history.command(4,"RetryCleanup",store_mutation={"operation":"clear","cause":"RetryCleanup","before":receipt_readback,"after":_store("Absent")},final_store=_store("Absent"),phase="SignedOut",status="Completed")
    login_b=_successful_managed("owner-1","Unauthenticated",None,1,{"event":"LoginSucceeded"},"Authenticated",None,1)
    login_b_result=history.command(5,"Login(B)",**login_b,managed_epoch_id="epoch-2",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-2","before":_store("Absent"),"after":_store("Present","B",0)},final_store=_store("Present","B",0),phase="SignedIn",account="B",version=0)
    history.end()
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":logout_result["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":logout_result["receipt"]["localSequence"]}},
      {"sequence":3,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-10-after-failed-logout"},
      {"sequence":4,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-after-failed-logout","serverSequence":1},
      {"sequence":5,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":retry["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":retry["receipt"]["localSequence"]}},
      {"sequence":6,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-10-after-retry"},
      {"sequence":7,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-after-retry","serverSequence":2},
      {"sequence":8,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":login_b_result["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":login_b_result["receipt"]["localSequence"]}},
      {"sequence":9,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-10-final-probe"},
      {"sequence":10,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-final-probe","serverSequence":3},
      {"sequence":11,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ]
    server=[
      {"runId":run_id,"sequence":1,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-after-failed-logout"},
      {"runId":run_id,"sequence":2,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-after-retry"},
      {"runId":run_id,"sequence":3,"kind":"checkpointPublished","processInstanceId":process_id,"name":"storeProbe.APP-10-final-probe"},
    ]
    observations=[
      {"kind":"storageProbe","stepId":"APP-10-after-failed-logout","processInstanceId":process_id,"commandRef":logout_result["commandRef"],"controllerSequence":3,"observation":physical_after_logout},
      {"kind":"storageProbe","stepId":"APP-10-after-retry","processInstanceId":process_id,"commandRef":retry["commandRef"],"controllerSequence":6,"observation":_store("Absent")},
      {"kind":"storageProbe","stepId":"APP-10-final-probe","processInstanceId":process_id,"commandRef":login_b_result["commandRef"],"controllerSequence":9,"observation":_store("Present","B",0)},
      {"kind":"renderedView","stepId":"APP-10-final-view","processInstanceId":process_id,"revision":login_b_result["ack"]["revision"],"eventRef":{"processInstanceId":process_id,"localSequence":login_b_result["ack"]["localSequence"]},"phase":"SignedIn","account":"B"},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":"APP-10","variantId":variant_id,"platform":"ios","buildHash":"sha256:"+"a"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":["APP-10/p1/native.jsonl","APP-10/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observations),server,observations


def make_app11_trace(variant_id, *, reverse_queued_order=False):
    """APP-11 pause at beforeStore/beforePublish with separate queued commands."""
    barrier={"store-pause":"beforeStore","publish-pause":"beforePublish"}[variant_id]
    scenario_id="APP-11"
    run_id="run-app-11"
    process_id=f"attempt-01/{scenario_id}/p1"
    history=_ProcessHistory(process_id,1,"owner-1")
    _app02_prefix(history)
    request_tag=process_id+":refresh:3"
    delivery_ref=_ref(process_id,4)
    history.command_inventory.append({"commandRef":delivery_ref,"name":"Deliver(slot-A1,success)"})
    history.add("commandEnqueued",commandRef=delivery_ref,name="Deliver(slot-A1,success)")
    history.add("commandStarted",commandRef=delivery_ref)
    history.add("transportReceived",commandRef=delivery_ref,slotId="slot-A1",outcome="success",failureCode=None,requestTag=request_tag)
    managed_event={"event":"RefreshSucceeded","requestId":1}
    managed_pre=_managed("owner-1","Refreshing",1,2)
    managed_result={**_managed("owner-1","Authenticated",None,2),"effects":[],"rejection":None}
    history.add("managedReduced",commandRef=delivery_ref,event=managed_event,pre=managed_pre,result=managed_result,epochId="epoch-1",slotId="slot-A1",requestOwnerId="owner-1")
    refresh_mutation={"operation":"replace","cause":"RefreshSuccess","slotId":"slot-A1","epochId":"epoch-1","ownerId":"owner-1","before":_store("Present","A",0),"after":_store("Present","A",1)}
    if variant_id=="publish-pause":
        history.add("storeMutation",commandRef=delivery_ref,**refresh_mutation)
        history.add("storeReadback",commandRef=delivery_ref,operation="replace",observation=_store("Present","A",1))
    action=1
    history.add("hookEvent",actionId=action,point=barrier,phase="armed",target="nextDelivery")
    history.add("hookEvent",actionId=action,point=barrier,phase="arrived",target="nextDelivery",commandRef=delivery_ref)
    queue_order=["Login(B)","Logout"] if reverse_queued_order else ["Logout","Login(B)"]
    command_ids={name:ident for ident,name in enumerate(queue_order,start=5)}
    for name in ("Logout","Login(B)"):
        history.command_inventory.append({"commandRef":_ref(process_id,command_ids[name]),"name":name})
    for name in queue_order:
        history.add("commandEnqueued",commandRef=_ref(process_id,command_ids[name]),name=name)
    released=history.add("hookEvent",actionId=action,point=barrier,phase="released",target="nextDelivery",commandRef=delivery_ref)
    if variant_id=="store-pause":
        history.add("storeMutation",commandRef=delivery_ref,**refresh_mutation)
        history.add("storeReadback",commandRef=delivery_ref,operation="replace",observation=_store("Present","A",1))
    delivered_view=_view("SignedIn","A",1,command_id=4,status="Completed")
    delivered_ack=history._ack(delivery_ref,delivered_view)
    delivered_receipt=history.add("commandReceipt",commandRef=delivery_ref,status="Completed",observation={"managed":_managed("owner-1","Authenticated",None,2),"store":_store("Present","A",1),"view":delivered_view,"revision":history.revision},acknowledgedEventRef={"processInstanceId":process_id,"localSequence":delivered_ack["localSequence"]})
    completion=history.add("completionProcessed",commandRef=delivery_ref,slotId="slot-A1",receiptEventRef={"processInstanceId":process_id,"localSequence":delivered_receipt["localSequence"]})
    logout_result=None
    login_b_result=None
    store=_store("Present","A",1)
    managed_state="Authenticated"
    pending=None
    next_id=2
    for name in queue_order:
        ident=command_ids[name]
        if name=="Logout":
            reducer=_successful_managed("owner-1",managed_state,pending,next_id,{"event":"Logout"},"Unauthenticated",None,next_id,[_effect("ClearCredentials")])
            logout_result=history.command(ident,name,**reducer,managed_epoch_id="epoch-1",store_mutation={"operation":"clear","cause":"Logout","epochId":"epoch-1","before":store,"after":_store("Absent")},final_store=_store("Absent"),phase="SignedOut",status="Completed",signing_out=True,already_enqueued=True)
            store=_store("Absent"); managed_state="Unauthenticated"; pending=None
        else:
            effects=[_effect("ClearCredentials")] if managed_state=="Authenticated" else []
            reducer=_successful_managed("owner-1",managed_state,pending,next_id,{"event":"LoginSucceeded"},"Authenticated",pending,next_id,effects)
            login_b_result=history.command(ident,name,**reducer,managed_epoch_id="epoch-2",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-2","before":store,"after":_store("Present","B",0)},final_store=_store("Present","B",0),phase="SignedIn",account="B",version=0,status="Completed",already_enqueued=True)
            store=_store("Present","B",0); managed_state="Authenticated"
    history.end()
    server=[
      {"runId":run_id,"sequence":1,"kind":"requestHeld","requestTag":request_tag,"requestId":"1"},
      {"runId":run_id,"sequence":2,"kind":"releaseAccepted","requestTag":request_tag,"outcome":"success"},
      {"runId":run_id,"sequence":3,"kind":"responseWritten","requestTag":request_tag,"outcome":"success"},
    ]
    native_arrival=next(event for event in history.events if event.get("kind")=="hookEvent" and event.get("phase")=="arrived")
    native_release=next(event for event in history.events if event.get("kind")=="hookEvent" and event.get("phase")=="released")
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"requestHeld","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":3,"kind":"releaseRequested","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":4,"kind":"releaseAccepted","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":2},
      {"sequence":5,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3},
      {"sequence":6,"kind":"hookArrived","processInstanceId":process_id,"point":barrier,"eventRef":{"processInstanceId":process_id,"localSequence":native_arrival["localSequence"]}},
      {"sequence":7,"kind":"hookReleased","processInstanceId":process_id,"point":barrier,"eventRef":{"processInstanceId":process_id,"localSequence":native_release["localSequence"]},"releaseChannel":"DebugScenarioControl","authMailboxPaused":True,"deliverReceiptObserved":False},
      {"sequence":8,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":delivery_ref,"eventRef":{"processInstanceId":process_id,"localSequence":delivered_receipt["localSequence"]}},
      {"sequence":9,"kind":"completionProcessedObserved","processInstanceId":process_id,"commandRef":delivery_ref,"eventRef":{"processInstanceId":process_id,"localSequence":completion["localSequence"]}},
      {"sequence":10,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":logout_result["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":logout_result["receipt"]["localSequence"]}},
      {"sequence":11,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":login_b_result["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":login_b_result["receipt"]["localSequence"]}},
      {"sequence":12,"kind":"probeCaptured","processInstanceId":process_id,"stepId":"APP-11-final-probe"},
      {"sequence":13,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ]
    final_store=store
    final_view=login_b_result["ack"]["view"] if "view" in login_b_result["ack"] else login_b_result["receipt"]["observation"]["view"]
    observations=[
      {"kind":"storageProbe","stepId":"APP-11-final-probe","processInstanceId":process_id,"commandRef":login_b_result["commandRef"],"controllerSequence":12,"observation":final_store},
      {"kind":"renderedView","stepId":"APP-11-final-view","processInstanceId":process_id,"revision":login_b_result["ack"]["revision"],"eventRef":{"processInstanceId":process_id,"localSequence":login_b_result["ack"]["localSequence"]},"phase":final_view["phase"],"account":final_view["account"]},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":scenario_id,"variantId":variant_id,"platform":"ios","buildHash":"sha256:"+"b"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":[f"{scenario_id}/p1/native.jsonl",f"{scenario_id}/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observations),server,observations


def make_app10_recover_old_trace(*, unsafe_owner_ignored=False):
    """Retry creates a fresh opaque owner before the old held request arrives."""
    scenario_id="APP-10-RECOVER-OLD"
    run_id="run-app-10-recover-old"
    process_id=f"attempt-01/{scenario_id}/p1"
    history=_ProcessHistory(process_id,1,"owner-1")
    _app02_prefix(history)
    request_tag=process_id+":refresh:3"
    logout_reducer=_successful_managed("owner-1","Refreshing",1,2,{"event":"Logout"},"Unauthenticated",None,2,[_effect("ClearCredentials")])
    logout_fault={"operation":"clear","fault":"clearBefore","mutationApplied":False,"verification":"notAttempted","before":_store("Present","A",0),"observation":_store("Present","A",0)}
    # The frozen inventory uses a test-only failure label; the native FIFO command is still Logout.
    logout=history.command(4,"Logout",**logout_reducer,managed_epoch_id="epoch-1",store_fault=logout_fault,final_store=_store("Present","A",0),phase="FaultLocked",status="FaultLocked",signing_out=True)
    retry=history.command(5,"RetryCleanup",managed_pre=_managed("owner-1","Unauthenticated",None,2),store_mutation={"operation":"clear","cause":"RetryCleanup","before":_store("Present","A",0),"after":_store("Absent")},final_store=_store("Absent"),phase="SignedOut",status="Completed")
    reset_before=_managed("owner-1","Unauthenticated",None,2)
    reset_after=_managed("owner-2","Unauthenticated",None,1)
    history.add("managedInstanceReset",commandRef=retry["commandRef"],before=reset_before,after=reset_after)
    login_b_reducer=_successful_managed("owner-2","Unauthenticated",None,1,{"event":"LoginSucceeded"},"Authenticated",None,1)
    login_b=history.command(6,"Login(B)",**login_b_reducer,managed_epoch_id="epoch-2",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-2","before":_store("Absent"),"after":_store("Present","B",0)},final_store=_store("Present","B",0),phase="SignedIn",account="B",version=0,status="Completed")
    foreign={"managed_event":{"event":"RefreshSucceeded","requestId":1},"managed_pre":_managed("owner-2","Authenticated",None,1),"managed_result":{**_managed("owner-2","Authenticated",None,1),"effects":[],"rejection":"ForeignRequest"}}
    delivery={"slotId":"slot-A1","outcome":"success","failureCode":None,"requestTag":request_tag,"ownerId":"owner-1","epochId":"epoch-1"}
    mutation={"operation":"replace","cause":"RefreshSuccess","slotId":"slot-A1","epochId":"epoch-1","ownerId":"owner-1","before":_store("Present","B",0),"after":_store("Present","A",1)} if unsafe_owner_ignored else None
    final_store=_store("Present","A",1) if unsafe_owner_ignored else _store("Present","B",0)
    final_phase,final_account,final_version=("SignedIn","A",1) if unsafe_owner_ignored else ("SignedIn","B",0)
    delivered=history.command(7,"Deliver(slot-A1,success)",**foreign,managed_epoch_id="epoch-2",delivery=delivery,store_mutation=mutation,final_store=final_store,phase=final_phase,account=final_account,version=final_version,status="IgnoredForeign")
    history.end()
    completion=next(event for event in history.events if event.get("kind")=="completionProcessed" and event.get("commandRef")==delivered["commandRef"])
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"requestHeld","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":3,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":logout["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":logout["receipt"]["localSequence"]}},
      {"sequence":4,"kind":"probeCaptured","processInstanceId":process_id,"stepId":f"{scenario_id}-after-failed-logout"},
      {"sequence":5,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":retry["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":retry["receipt"]["localSequence"]}},
      {"sequence":6,"kind":"probeCaptured","processInstanceId":process_id,"stepId":f"{scenario_id}-after-retry"},
      {"sequence":7,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":login_b["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":login_b["receipt"]["localSequence"]}},
      {"sequence":8,"kind":"probeCaptured","processInstanceId":process_id,"stepId":f"{scenario_id}-after-login-b"},
      {"sequence":9,"kind":"releaseRequested","processInstanceId":process_id,"requestTag":request_tag},
      {"sequence":10,"kind":"releaseAccepted","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":2},
      {"sequence":11,"kind":"responseWritten","processInstanceId":process_id,"requestTag":request_tag,"serverSequence":3},
      {"sequence":12,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["receipt"]["localSequence"]}},
      {"sequence":13,"kind":"completionProcessedObserved","processInstanceId":process_id,"commandRef":delivered["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":completion["localSequence"]}},
      {"sequence":14,"kind":"probeCaptured","processInstanceId":process_id,"stepId":f"{scenario_id}-final-probe"},
      {"sequence":15,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ]
    server=[
      {"runId":run_id,"sequence":1,"kind":"requestHeld","requestTag":request_tag,"requestId":"1"},
      {"runId":run_id,"sequence":2,"kind":"releaseAccepted","requestTag":request_tag,"outcome":"success"},
      {"runId":run_id,"sequence":3,"kind":"responseWritten","requestTag":request_tag,"outcome":"success"},
    ]
    observations=[
      {"kind":"storageProbe","stepId":f"{scenario_id}-after-failed-logout","processInstanceId":process_id,"commandRef":logout["commandRef"],"controllerSequence":4,"observation":_store("Present","A",0)},
      {"kind":"storageProbe","stepId":f"{scenario_id}-after-retry","processInstanceId":process_id,"commandRef":retry["commandRef"],"controllerSequence":6,"observation":_store("Absent")},
      {"kind":"storageProbe","stepId":f"{scenario_id}-after-login-b","processInstanceId":process_id,"commandRef":login_b["commandRef"],"controllerSequence":8,"observation":_store("Present","B",0)},
      {"kind":"storageProbe","stepId":f"{scenario_id}-final-probe","processInstanceId":process_id,"commandRef":delivered["commandRef"],"controllerSequence":14,"observation":final_store},
      {"kind":"renderedView","stepId":f"{scenario_id}-final-view","processInstanceId":process_id,"revision":delivered["ack"]["revision"],"eventRef":{"processInstanceId":process_id,"localSequence":delivered["ack"]["localSequence"]},"phase":final_phase,"account":final_account},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":scenario_id,"platform":"ios","buildHash":"sha256:"+"c"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":[f"{scenario_id}/p1/native.jsonl",f"{scenario_id}/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observations),server,observations


def make_ctrl_n2_trace(*, detached_clear=True, effect_ack=True, bad_effect_ack=False):
    """APP-05 history prefix plus a detached Logout clear after Login B."""
    trace, server, observations = make_app05_trace()
    control_id = "CTRL-N2-LATE-CLEAR"

    def rename(value):
        if isinstance(value, str):
            return value.replace("APP-05", control_id)
        if isinstance(value, list):
            return [rename(item) for item in value]
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        return value

    trace, server, observations = rename(trace), rename(server), rename(observations)
    trace["scenarioId"] = control_id
    trace["controlId"] = control_id
    process_id = trace["processInstances"][0]["processInstanceId"]
    trace["commandInventory"] = [row for row in trace["commandInventory"] if row["commandRef"]["id"] <= 5]
    login_b_receipt = next(
        event for event in trace["events"]
        if event.get("kind") == "commandReceipt" and event.get("commandRef", {}).get("id") == 5
    )
    trace["events"] = [event for event in trace["events"] if event["localSequence"] <= login_b_receipt["localSequence"]]
    trace["events"] = [event for event in trace["events"] if event["kind"] != "processEnd"]
    trace["controllerEvents"] = [event for event in trace["controllerEvents"] if event["kind"] != "processEndAcknowledged"]
    for event in trace["events"]:
        if event.get("kind") == "processStart":
            continue
    observations = [
        row for row in observations
        if row["stepId"] in {
            f"{control_id}-after-logout-store", f"{control_id}-after-logout-view",
            f"{control_id}-after-login-b-store", f"{control_id}-after-login-b-view",
        }
    ]
    step_rename = {
        f"{control_id}-after-logout-store": f"{control_id}-probe-absent",
        f"{control_id}-after-logout-view": f"{control_id}-after-logout-view",
        f"{control_id}-after-login-b-store": f"{control_id}-probe-b",
        f"{control_id}-after-login-b-view": f"{control_id}-after-login-b-view",
    }
    for row in observations:
        row["stepId"] = step_rename[row["stepId"]]

    controller = [
        item for item in trace["controllerEvents"]
        if item.get("kind") in {"launch", "requestHeld"}
        or (item.get("kind") == "receiptObserved" and item.get("commandRef", {}).get("id") in {4, 5})
        or (item.get("kind") == "probeCaptured" and item.get("stepId") in step_rename)
    ]
    controller = rename(controller)
    for sequence, item in enumerate(controller, start=1):
        item["sequence"] = sequence
        if item.get("kind") == "probeCaptured":
            item["stepId"] = step_rename[item["stepId"]]
    armed, arrived, released, effect_awaited = 7, 8, 9, 10
    final_probe = effect_awaited + (1 if effect_ack else 0)
    controller.extend([
        {"sequence": armed, "kind": "hookArmed", "processInstanceId": process_id, "point": "beforeDeferredControlClear", "target": "nextCommand"},
        {"sequence": arrived, "kind": "hookArrived", "processInstanceId": process_id, "point": "beforeDeferredControlClear", "authMailboxPaused": False},
    ])

    origin = {"processInstanceId": process_id, "id": 4}
    mutation_sequence = trace["events"][-1]["localSequence"] + 1
    trace["events"].extend([
        {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": mutation_sequence, "kind": "hookEvent", "actionId": 1, "point": "beforeDeferredControlClear", "phase": "armed", "target": "nextCommand"},
        {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": mutation_sequence + 1, "kind": "hookEvent", "actionId": 1, "point": "beforeDeferredControlClear", "phase": "arrived", "target": "nextCommand"},
        {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": mutation_sequence + 2, "kind": "hookEvent", "actionId": 1, "point": "beforeDeferredControlClear", "phase": "released", "target": "nextCommand"},
    ])
    controller.append({
        "sequence": released,
        "kind": "hookReleased",
        "processInstanceId": process_id,
        "point": "beforeDeferredControlClear",
        "eventRef": {"processInstanceId": process_id, "localSequence": mutation_sequence + 2},
        "releaseChannel": "DebugScenarioControl",
    })
    if detached_clear:
        native_mutation_sequence = mutation_sequence + 3
        before = {"kind": "Present", "account": "B", "version": 0}
        after = {"kind": "Absent"}
        trace["events"].extend([
            {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": native_mutation_sequence, "kind": "detachedStoreMutation", "effectId": "late-clear-1", "originCommandRef": origin, "operation": "clear", "cause": "DeferredLogoutClear", "before": before, "after": after, "releaseActionId": 1},
            {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": native_mutation_sequence + 1, "kind": "detachedStoreReadback", "effectId": "late-clear-1", "originCommandRef": origin, "operation": "clear", "observation": after},
            {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": native_mutation_sequence + 2, "kind": "processEnd"},
        ])
        if effect_ack:
            controller.append({
                "sequence": effect_awaited,
                "kind": "detachedEffectAwaited",
                "processInstanceId": process_id,
                "effectId": "late-clear-1",
                "originCommandRef": origin,
                "mutationEventRef": {"processInstanceId": process_id, "localSequence": native_mutation_sequence},
                "readbackEventRef": {
                    "processInstanceId": process_id,
                    "localSequence": native_mutation_sequence + (99 if bad_effect_ack else 1),
                },
            })
        controller.append({"sequence": final_probe, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": f"{control_id}-final-probe"})
        observations.extend([
            {"kind": "storageProbe", "stepId": f"{control_id}-final-probe", "processInstanceId": process_id, "controllerSequence": final_probe, "effectRef": {"processInstanceId": process_id, "localSequence": native_mutation_sequence}, "effectId": "late-clear-1", "observation": after},
            {"kind": "renderedView", "stepId": f"{control_id}-final-view", "processInstanceId": process_id, "revision": next(row["revision"] for row in observations if row["kind"] == "renderedView" and row["stepId"] == f"{control_id}-after-login-b-view"), "eventRef": next(row["eventRef"] for row in observations if row["kind"] == "renderedView" and row["stepId"] == f"{control_id}-after-login-b-view"), "phase": "SignedIn", "account": "B"},
        ])
    else:
        trace["events"].append({"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": trace["events"][-1]["localSequence"] + 1, "kind": "processEnd"})
    trace["controllerEvents"] = controller
    trace["artifactPaths"] = [f"{control_id}/p1/native.jsonl", f"{control_id}/p1/ui.jsonl"]
    server = [item for item in server if item.get("kind") == "requestHeld"]
    return _with_process_end_acks(trace, observations), server, observations


def make_ctrl_n4_trace():
    """False successful Logout: failed readback, Unknown receipt, physical probe Absent."""
    control_id="CTRL-N4-FALSE-LOGOUT"
    process_id=f"attempt-01/{control_id}/p1"
    run_id="run-ctrl-n4"
    history=_ProcessHistory(process_id,1,"owner-1")
    history.command(1,"Bootstrap",phase="SignedOut",final_store=_store("Absent"))
    login=_successful_managed("owner-1","Unauthenticated",None,1,{"event":"LoginSucceeded"},"Authenticated",None,1)
    history.command(2,"Login(A)",**login,managed_epoch_id="epoch-1",store_mutation={"operation":"replace","cause":"Login","epochId":"epoch-1","before":_store("Absent"),"after":_store("Present","A",0)},final_store=_store("Present","A",0),phase="SignedIn",account="A",version=0)
    logout=_successful_managed("owner-1","Authenticated",None,1,{"event":"Logout"},"Unauthenticated",None,1,[_effect("ClearCredentials")])
    fault={"operation":"clear","fault":"clearAfterBeforeVerify","mutationApplied":True,"verification":"failed","before":_store("Present","A",0),"observation":{"kind":"Unknown","errorCode":"readFailed"}}
    result=history.command(3,"Logout",**logout,managed_epoch_id="epoch-1",store_mutation={"operation":"clear","cause":"Logout","epochId":"epoch-1","before":_store("Present","A",0),"after":_store("Absent")},store_fault=fault,verify_store=False,final_store={"kind":"Unknown","errorCode":"readFailed"},phase="SignedOut",status="Completed",signing_out=True)
    history.end()
    controller=[
      {"sequence":1,"kind":"launch","processInstanceId":process_id,"launchOrdinal":1},
      {"sequence":2,"kind":"receiptObserved","processInstanceId":process_id,"commandRef":result["commandRef"],"eventRef":{"processInstanceId":process_id,"localSequence":result["receipt"]["localSequence"]}},
      {"sequence":3,"kind":"probeCaptured","processInstanceId":process_id,"stepId":f"{control_id}-independent-probe"},
      {"sequence":4,"kind":"terminated","processInstanceId":process_id,"launchOrdinal":1},
    ]
    observation=[
      {"kind":"storageProbe","stepId":f"{control_id}-independent-probe","processInstanceId":process_id,"commandRef":result["commandRef"],"controllerSequence":3,"observation":_store("Absent")},
    ]
    trace={"version":1,"runId":run_id,"scenarioId":control_id,"controlId":control_id,"platform":"ios","buildHash":"sha256:"+"4"*64,"processInstances":[{"processInstanceId":process_id,"launchOrdinal":1}],"controllerEvents":controller,"commandInventory":list(history.command_inventory),"events":list(history.events),"artifactPaths":[f"{control_id}/p1/native.jsonl",f"{control_id}/p1/ui.jsonl"]}
    return _with_process_end_acks(trace, observation),[],observation


def make_ctrl_n3_trace():
    """Capture the swapped UI acknowledgement before a failed first store write."""
    control_id = "CTRL-N3-EARLY-PUBLISH"
    trace, server, observations = make_app01_trace()
    process_id = trace["processInstances"][0]["processInstanceId"].replace("APP-01", control_id)
    old_process_id = trace["processInstances"][0]["processInstanceId"]
    run_id = "run-ctrl-n3"
    trace["scenarioId"] = control_id
    trace["controlId"] = control_id
    trace["runId"] = run_id
    trace["processInstances"][0]["processInstanceId"] = process_id
    trace["artifactPaths"] = [f"{control_id}/p1/native.jsonl", f"{control_id}/p1/ui.jsonl"]

    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            return value.replace(old_process_id, process_id).replace("APP-01", control_id).replace("run-app-01", run_id)
        return value

    trace = rewrite(trace)
    server = rewrite(server)
    observations = rewrite(observations)
    delivery_ref = _ref(process_id, 4)
    events = trace["events"]
    early_ack = next(event for event in events if event.get("kind") == "uiPublishAck" and event.get("commandRef") == delivery_ref)
    receipt = next(event for event in events if event.get("kind") == "commandReceipt" and event.get("commandRef") == delivery_ref)
    completion = next(event for event in events if event.get("kind") == "completionProcessed" and event.get("commandRef") == delivery_ref)
    request_tag = process_id + ":refresh:3"
    armed = {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": 0, "kind": "hookEvent", "actionId": 1, "point": "afterPublishAck", "phase": "armed", "target": "nextDelivery"}
    arrived = {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": 0, "kind": "hookEvent", "actionId": 1, "point": "afterPublishAck", "phase": "arrived", "target": "nextDelivery", "commandRef": delivery_ref}
    released = {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": 0, "kind": "hookEvent", "actionId": 1, "point": "afterPublishAck", "phase": "released", "target": "nextDelivery", "commandRef": delivery_ref}
    fault = {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": 0, "kind": "storeFault", "commandRef": delivery_ref, "operation": "replace", "fault": "replaceBefore", "mutationApplied": False, "verification": "notAttempted", "before": _store("Present", "A", 0), "observation": _store("Present", "A", 0)}
    fault_view = _view("FaultLocked", command_id=4, status="FaultLocked")
    terminal_ack = {"processInstanceId": process_id, "launchOrdinal": 1, "localSequence": 0, "kind": "uiPublishAck", "commandRef": delivery_ref, "revision": 5, "view": fault_view}
    rebuilt = []
    for event in events:
        kind = event.get("kind")
        if kind == "commandEnqueued" and event.get("commandRef") == delivery_ref:
            rebuilt.append(armed)
        if kind in {"storeMutation", "storeReadback"} and event.get("commandRef") == delivery_ref:
            continue
        if event is early_ack:
            rebuilt.append(event)
            rebuilt.extend([arrived, released, fault, terminal_ack])
            continue
        if event is receipt:
            event["status"] = "FaultLocked"
            event["acknowledgedEventRef"] = {"processInstanceId": process_id, "localSequence": 0}
            event["observation"]["store"] = _store("Present", "A", 0)
            event["observation"]["view"] = fault_view
            event["observation"]["revision"] = 5
        if event is completion:
            event["receiptEventRef"] = {"processInstanceId": process_id, "localSequence": 0}
        rebuilt.append(event)
    for sequence, event in enumerate(rebuilt, start=1):
        event["localSequence"] = sequence
    terminal_ack["localSequence"] = rebuilt.index(terminal_ack) + 1
    receipt["localSequence"] = rebuilt.index(receipt) + 1
    completion["receiptEventRef"] = {"processInstanceId": process_id, "localSequence": receipt["localSequence"]}
    receipt["acknowledgedEventRef"] = {"processInstanceId": process_id, "localSequence": terminal_ack["localSequence"]}
    trace["events"] = rebuilt

    server = [{**event, "runId": run_id} for event in server]
    base_observation = next(item for item in observations if item.get("stepId") == "CTRL-N3-EARLY-PUBLISH-final-probe")
    final_view = next(item for item in observations if item.get("stepId") == "CTRL-N3-EARLY-PUBLISH-final-view")
    base_observation.update(stepId="CTRL-N3-final-probe", observation=_store("Present", "A", 0), commandRef=delivery_ref, controllerSequence=12)
    final_view.update(stepId="CTRL-N3-final-view", revision=5, eventRef={"processInstanceId": process_id, "localSequence": terminal_ack["localSequence"]}, phase="FaultLocked", account=None)
    expire_ref = _ref(process_id, 3)
    observations.extend([
        {"kind": "storageProbe", "stepId": "CTRL-N3-store-probe-a0", "processInstanceId": process_id, "commandRef": expire_ref, "controllerSequence": 8, "observation": _store("Present", "A", 0)},
        {"kind": "renderedView", "stepId": "CTRL-N3-rendered-a1", "processInstanceId": process_id, "revision": early_ack["revision"], "eventRef": {"processInstanceId": process_id, "localSequence": early_ack["localSequence"]}, "phase": "SignedIn", "account": "A"},
    ])
    armed_event = next(event for event in rebuilt if event is armed)
    arrived_event = next(event for event in rebuilt if event is arrived)
    released_event = next(event for event in rebuilt if event is released)
    completion_event = next(event for event in rebuilt if event is completion)
    trace["controllerEvents"] = [
        {"sequence": 1, "kind": "launch", "processInstanceId": process_id, "launchOrdinal": 1},
        {"sequence": 2, "kind": "requestHeld", "processInstanceId": process_id, "requestTag": request_tag},
        {"sequence": 3, "kind": "releaseRequested", "processInstanceId": process_id, "requestTag": request_tag},
        {"sequence": 4, "kind": "releaseAccepted", "processInstanceId": process_id, "requestTag": request_tag, "serverSequence": 2},
        {"sequence": 5, "kind": "responseWritten", "processInstanceId": process_id, "requestTag": request_tag, "serverSequence": 3},
        {"sequence": 6, "kind": "hookArmed", "processInstanceId": process_id, "point": "afterPublishAck", "target": "nextDelivery"},
        {"sequence": 7, "kind": "hookArrived", "processInstanceId": process_id, "point": "afterPublishAck", "eventRef": {"processInstanceId": process_id, "localSequence": arrived_event["localSequence"]}},
        {"sequence": 8, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "CTRL-N3-store-probe-a0"},
        {"sequence": 9, "kind": "hookReleased", "processInstanceId": process_id, "point": "afterPublishAck", "eventRef": {"processInstanceId": process_id, "localSequence": released_event["localSequence"]}, "releaseChannel": "DebugScenarioControl", "authMailboxPaused": True, "deliverReceiptObserved": False},
        {"sequence": 10, "kind": "receiptObserved", "processInstanceId": process_id, "commandRef": delivery_ref, "eventRef": {"processInstanceId": process_id, "localSequence": receipt["localSequence"]}},
        {"sequence": 11, "kind": "completionProcessedObserved", "processInstanceId": process_id, "commandRef": delivery_ref, "eventRef": {"processInstanceId": process_id, "localSequence": completion_event["localSequence"]}},
        {"sequence": 12, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "CTRL-N3-final-probe"},
        {"sequence": 13, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1},
    ]
    return _with_process_end_acks(trace, observations), server, observations


def make_app12_trace(*, reuse_process_id=False):
    scenario_id = "APP-12-SAVED"
    run_id = "run-app-12"
    first = "attempt-01/APP-12-SAVED/p1"
    second = first if reuse_process_id else "attempt-01/APP-12-SAVED/p2"
    p1 = _ProcessHistory(first, 1, "owner-1")
    p2 = _ProcessHistory(second, 2, "owner-2")
    p1.command(1, "Bootstrap", final_store=_store("Absent"), phase="SignedOut")
    p1_login = _successful_managed(p1.owner_id, "Unauthenticated", None, 1, {"event": "LoginSucceeded"}, "Authenticated", None, 1)
    p1.command(2, "Login(A)", **p1_login, managed_epoch_id="epoch-1", store_mutation={"operation": "replace", "cause": "Login", "epochId": "epoch-1", "before": _store("Absent"), "after": _store("Present", "A", 0)}, final_store=_store("Present", "A", 0), phase="SignedIn", account="A", version=0)
    p1.end()
    p2.add("hookEvent", actionId=37, point="beforeBootstrapClear", phase="released", target="bootstrap")
    native_release = p2.events[-1]
    p2_bootstrap = p2.command(1, "Bootstrap", final_store=_store("Absent"), phase="SignedOut", release_action_id=37, store_mutation={"operation": "clear", "cause": "Bootstrap", "before": _store("Present", "A", 0), "after": _store("Absent")})
    p2.end()

    controller = [
        {"sequence": 1, "kind": "launch", "processInstanceId": first, "launchOrdinal": 1},
        {"sequence": 2, "kind": "receiptObserved", "processInstanceId": first, "commandRef": _ref(first, 2), "eventRef": {"processInstanceId": first, "localSequence": next(event["localSequence"] for event in p1.events if event["kind"] == "commandReceipt" and event["commandRef"]["id"] == 2)}},
        {"sequence": 3, "kind": "forceStopped", "processInstanceId": first, "pidAbsent": True},
        {"sequence": 4, "kind": "terminated", "processInstanceId": first, "launchOrdinal": 1},
        {"sequence": 5, "kind": "launch", "processInstanceId": second, "launchOrdinal": 2},
        {"sequence": 6, "kind": "bootstrapHookArrived", "processInstanceId": second, "point": "beforeBootstrapClear", "authMailboxPaused": True},
        {"sequence": 7, "kind": "probeCaptured", "processInstanceId": second, "stepId": "APP-12-p2-before-bootstrap-clear"},
        {"sequence": 8, "kind": "checkpointPublished", "processInstanceId": second, "name": "bootstrapStoreProbed", "serverSequence": 1},
        {"sequence": 9, "kind": "hookReleased", "processInstanceId": second, "point": "beforeBootstrapClear", "eventRef": {"processInstanceId": second, "localSequence": native_release["localSequence"]}, "releaseChannel": "DebugScenarioControl", "authMailboxPaused": True, "bootstrapReceiptObserved": False},
        {"sequence": 10, "kind": "receiptObserved", "processInstanceId": second, "commandRef": p2_bootstrap["commandRef"], "eventRef": {"processInstanceId": second, "localSequence": p2_bootstrap["receipt"]["localSequence"]}},
        {"sequence": 11, "kind": "probeCaptured", "processInstanceId": second, "stepId": "APP-12-final-probe"},
        {"sequence": 12, "kind": "terminated", "processInstanceId": second, "launchOrdinal": 2},
    ]
    trace = {
        "version": 1,
        "runId": run_id,
        "scenarioId": scenario_id,
        "platform": "ios",
        "buildHash": "sha256:" + "c" * 64,
        "processInstances": [
            {"processInstanceId": first, "launchOrdinal": 1},
            {"processInstanceId": second, "launchOrdinal": 2},
        ],
        "controllerEvents": controller,
        "commandInventory": [*p1.command_inventory, *p2.command_inventory],
        "events": [*p1.events, *p2.events],
        "artifactPaths": ["APP-12-SAVED/p1/native.jsonl", "APP-12-SAVED/p2/native.jsonl"],
    }
    server = [{"runId": run_id, "sequence": 1, "kind": "checkpointPublished", "processInstanceId": second, "name": "bootstrapStoreProbed"}]
    observations = [
        {"kind": "storageProbe", "stepId": "APP-12-p2-before-bootstrap-clear", "processInstanceId": second, "controllerSequence": 7, "observation": _store("Present", "A", 0)},
        {"kind": "storageProbe", "stepId": "APP-12-final-probe", "processInstanceId": second, "commandRef": p2_bootstrap["commandRef"], "controllerSequence": 11, "observation": _store("Absent")},
        {"kind": "renderedView", "stepId": "APP-12-final-view", "processInstanceId": second, "revision": 1, "eventRef": {"processInstanceId": second, "localSequence": p2_bootstrap["ack"]["localSequence"]}, "phase": "SignedOut", "account": None},
    ]
    return _with_process_end_acks(trace, observations), server, observations


def make_app01_trace():
    scenario_id = "APP-01"
    run_id = "run-app-01"
    process_id = "attempt-01/APP-01/p1"
    history = _ProcessHistory(process_id, 1, "owner-1")
    _, _, _ = _app02_prefix(history)
    reducer = {
        "managed_event": {"event": "RefreshSucceeded", "requestId": 1},
        "managed_pre": _managed(history.owner_id, "Refreshing", 1, 2),
        "managed_result": {**_managed(history.owner_id, "Authenticated", None, 2), "effects": [], "rejection": None},
    }
    completion = {"slotId": "slot-A1", "outcome": "success", "requestTag": process_id + ":refresh:3", "ownerId": history.owner_id, "epochId": "epoch-1"}
    delivered = history.command(
        4,
        "Deliver(current,success)",
        **reducer,
        managed_epoch_id="epoch-1",
        delivery=completion,
        store_mutation={"operation": "replace", "cause": "RefreshSuccess", "slotId": "slot-A1", "epochId": "epoch-1", "ownerId": history.owner_id, "before": _store("Present", "A", 0), "after": _store("Present", "A", 1)},
        final_store=_store("Present", "A", 1),
        phase="SignedIn",
        account="A",
        version=1,
        status="Completed",
    )
    history.end()
    controller = [
        {"sequence": 1, "kind": "launch", "processInstanceId": process_id, "launchOrdinal": 1},
        {"sequence": 2, "kind": "requestHeld", "processInstanceId": process_id, "requestTag": completion["requestTag"]},
        {"sequence": 3, "kind": "releaseRequested", "processInstanceId": process_id, "requestTag": completion["requestTag"]},
        {"sequence": 4, "kind": "releaseAccepted", "processInstanceId": process_id, "requestTag": completion["requestTag"], "serverSequence": 2},
        {"sequence": 5, "kind": "responseWritten", "processInstanceId": process_id, "requestTag": completion["requestTag"], "serverSequence": 3},
        {"sequence": 6, "kind": "receiptObserved", "processInstanceId": process_id, "commandRef": delivered["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": delivered["receipt"]["localSequence"]}},
        {"sequence": 7, "kind": "completionProcessedObserved", "processInstanceId": process_id, "commandRef": delivered["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": next(event["localSequence"] for event in history.events if event["kind"] == "completionProcessed")}},
        {"sequence": 8, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-01-final-probe"},
        {"sequence": 9, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1},
    ]
    server = [
        {"runId": run_id, "sequence": 1, "kind": "requestHeld", "requestTag": completion["requestTag"], "requestId": "1"},
        {"runId": run_id, "sequence": 2, "kind": "releaseAccepted", "requestTag": completion["requestTag"], "outcome": "success"},
        {"runId": run_id, "sequence": 3, "kind": "responseWritten", "requestTag": completion["requestTag"], "outcome": "success"},
    ]
    observations = [
        {"kind": "storageProbe", "stepId": "APP-01-final-probe", "processInstanceId": process_id, "commandRef": delivered["commandRef"], "controllerSequence": 8, "observation": _store("Present", "A", 1)},
        {"kind": "renderedView", "stepId": "APP-01-final-view", "processInstanceId": process_id, "revision": 4, "eventRef": {"processInstanceId": process_id, "localSequence": delivered["ack"]["localSequence"]}, "phase": "SignedIn", "account": "A"},
    ]
    trace = {
        "version": 1,
        "runId": run_id,
        "scenarioId": scenario_id,
        "platform": "ios",
        "buildHash": "sha256:" + "d" * 64,
        "processInstances": [{"processInstanceId": process_id, "launchOrdinal": 1}],
        "controllerEvents": controller,
        "commandInventory": list(history.command_inventory),
        "events": list(history.events),
        "artifactPaths": ["APP-01/p1/native.jsonl", "APP-01/p1/ui.jsonl"],
    }
    return _with_process_end_acks(trace, observations), server, observations


def make_app06_trace():
    scenario_id = "APP-06"
    run_id = "run-app-06"
    process_id = "attempt-01/APP-06/p1"
    history = _ProcessHistory(process_id, 1, "owner-1")
    _app02_prefix(history)
    first_reducer = {
        "managed_event": {"event": "RefreshSucceeded", "requestId": 1},
        "managed_pre": _managed(history.owner_id, "Refreshing", 1, 2),
        "managed_result": {**_managed(history.owner_id, "Authenticated", None, 2), "effects": [], "rejection": None},
    }
    completion = {"slotId": "slot-A1", "outcome": "success", "requestTag": process_id + ":refresh:3", "ownerId": history.owner_id, "epochId": "epoch-1"}
    first = history.command(
        4,
        "Deliver(current,success)",
        **first_reducer,
        managed_epoch_id="epoch-1",
        delivery=completion,
        store_mutation={"operation": "replace", "cause": "RefreshSuccess", "slotId": "slot-A1", "epochId": "epoch-1", "ownerId": history.owner_id, "before": _store("Present", "A", 0), "after": _store("Present", "A", 1)},
        final_store=_store("Present", "A", 1),
        phase="SignedIn",
        account="A",
        version=1,
        status="Completed",
    )
    duplicate_reducer = {
        "managed_event": {"event": "RefreshSucceeded", "requestId": 1},
        "managed_pre": _managed(history.owner_id, "Authenticated", None, 2),
        "managed_result": {**_managed(history.owner_id, "Authenticated", None, 2), "effects": [], "rejection": None},
    }
    replay = history.command(
        5,
        "Deliver(replay,success)",
        **duplicate_reducer,
        managed_epoch_id="epoch-1",
        completion=completion,
        final_store=_store("Present", "A", 1),
        phase="SignedIn",
        account="A",
        version=1,
        status="IgnoredStale",
    )
    history.end()
    controller = [
        {"sequence": 1, "kind": "launch", "processInstanceId": process_id, "launchOrdinal": 1},
        {"sequence": 2, "kind": "requestHeld", "processInstanceId": process_id, "requestTag": completion["requestTag"]},
        {"sequence": 3, "kind": "releaseRequested", "processInstanceId": process_id, "requestTag": completion["requestTag"]},
        {"sequence": 4, "kind": "releaseAccepted", "processInstanceId": process_id, "requestTag": completion["requestTag"], "serverSequence": 2},
        {"sequence": 5, "kind": "responseWritten", "processInstanceId": process_id, "requestTag": completion["requestTag"], "serverSequence": 3},
        {
            "sequence": 6,
            "kind": "replayRequested",
            "processInstanceId": process_id,
            "slotId": "slot-A1",
            "actionId": 19,
            "commandRef": replay["commandRef"],
            "sourceCommandRef": first["commandRef"],
        },
        {"sequence": 7, "kind": "completionProcessedObserved", "processInstanceId": process_id, "commandRef": replay["commandRef"], "eventRef": {"processInstanceId": process_id, "localSequence": history.events[-2]["localSequence"]}},
        {"sequence": 8, "kind": "probeCaptured", "processInstanceId": process_id, "stepId": "APP-06-final-probe"},
        {"sequence": 9, "kind": "terminated", "processInstanceId": process_id, "launchOrdinal": 1},
    ]
    server = [
        {"runId": run_id, "sequence": 1, "kind": "requestHeld", "requestTag": completion["requestTag"], "requestId": "1"},
        {"runId": run_id, "sequence": 2, "kind": "releaseAccepted", "requestTag": completion["requestTag"], "outcome": "success"},
        {"runId": run_id, "sequence": 3, "kind": "responseWritten", "requestTag": completion["requestTag"], "outcome": "success"},
    ]
    observations = [
        {"kind": "storageProbe", "stepId": "APP-06-final-probe", "processInstanceId": process_id, "commandRef": replay["commandRef"], "controllerSequence": 8, "observation": _store("Present", "A", 1)},
        {"kind": "renderedView", "stepId": "APP-06-final-view", "processInstanceId": process_id, "revision": 5, "eventRef": {"processInstanceId": process_id, "localSequence": replay["ack"]["localSequence"]}, "phase": "SignedIn", "account": "A"},
    ]
    trace = {
        "version": 1,
        "runId": run_id,
        "scenarioId": scenario_id,
        "platform": "ios",
        "buildHash": "sha256:" + "e" * 64,
        "processInstances": [{"processInstanceId": process_id, "launchOrdinal": 1}],
        "controllerEvents": controller,
        "commandInventory": list(history.command_inventory),
        "events": list(history.events),
        "artifactPaths": ["APP-06/p1/native.jsonl", "APP-06/p1/ui.jsonl"],
    }
    return _with_process_end_acks(trace, observations), server, observations
