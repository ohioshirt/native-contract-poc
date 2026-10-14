"""Strict independent checker for native command, storage, server and UI histories."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from verification.async_contract import step as managed_step


ROOT = Path(__file__).resolve().parents[1]
MAX_I64 = 9223372036854775807
COMMAND_INVENTORY_ALIASES = {"Logout(failed)": "Logout", "Login(A0)": "Login(A)"}
REPORT_KEYS = ("classification", "scenarioId", "violations", "missingObservations")
TOP_REQUIRED_KEYS = {
    "version", "runId", "scenarioId", "platform", "buildHash", "processInstances",
    "controllerEvents", "commandInventory", "events", "artifactPaths",
}
TOP_OPTIONAL_KEYS = {"variantId", "controlId"}
TOP_KEYS = TOP_REQUIRED_KEYS | TOP_OPTIONAL_KEYS


def _native_command_name(inventory_name):
    """Map a frozen test-only action label to its one real FIFO command name."""
    return COMMAND_INVENTORY_ALIASES.get(inventory_name, inventory_name)


def _native_command_matches(actual_name, inventory_name):
    return (
        actual_name == inventory_name
        or actual_name == _native_command_name(inventory_name)
        or inventory_name == _native_command_name(actual_name)
    )


def _delivery_declaration(scenario, occurrence):
    declared = scenario.get("expectedDeliveries")
    if isinstance(declared, list):
        return declared[occurrence] if occurrence < len(declared) else None
    if occurrence == 0:
        return scenario.get("requiredDelivery")
    return None


def _transport_pair_for_label(label):
    return {
        "success": ("success", None),
        "failure": ("failure", "rejected"),
        "serverError": ("failure", "server"),
        "malformed": ("failure", "malformed"),
        "disconnected": ("failure", "disconnected"),
        "correlationMismatch": ("failure", "wrongCorrelation"),
    }.get(label)


def _command_role_bindings(scenario, trace):
    """Bind frozen input aliases to native commands using captured slot lineage."""
    errors = []
    process_by_ordinal = {
        row.get("launchOrdinal"): row.get("processInstanceId")
        for row in trace.get("processInstances", []) if isinstance(row, dict)
    }
    rows_by_pid = defaultdict(list)
    for row in trace.get("commandInventory", []):
        if isinstance(row, dict) and isinstance(row.get("commandRef"), dict):
            ref = row["commandRef"]
            rows_by_pid.setdefault(ref.get("processInstanceId"), []).append(row)
    events = [event for event in trace.get("events", []) if isinstance(event, dict)] if isinstance(trace.get("events"), list) else []
    controller = [item for item in trace.get("controllerEvents", []) if isinstance(item, dict)] if isinstance(trace.get("controllerEvents"), list) else []
    bindings = {}
    for launch in scenario.get("launches", []):
        if not isinstance(launch, dict):
            continue
        pid = process_by_ordinal.get(launch.get("ordinal"))
        actual_rows = sorted(rows_by_pid.get(pid, []), key=lambda row: row.get("commandRef", {}).get("id", 0))
        expected_rows = launch.get("commands", [])
        if scenario.get("id") == "APP-11":
            expected_prefix = list(expected_rows[:len(actual_rows)])
            remaining = list(expected_prefix)
            for row in actual_rows:
                actual_name = row["name"]
                ref = row["commandRef"]
                key = (ref["processInstanceId"], ref["id"])
                selected = next((value for value in remaining if actual_name == _native_command_name(value)), None)
                if selected is None:
                    current = next((value for value in remaining if value.startswith("Deliver(current,")), None)
                    if current is not None:
                        label = current[len("Deliver(current,"):-1]
                        declaration = _delivery_declaration(scenario, 0)
                        transport_pair = _transport_pair_for_label(label)
                        if isinstance(declaration, dict) and transport_pair and actual_name == f"Deliver({declaration.get('slotId')},{transport_pair[0]})":
                            selected = current
                if selected is None:
                    errors.append(f"native command {actual_name} does not fulfill the APP-11 frozen queue")
                    continue
                remaining.remove(selected)
                bindings[key] = selected
            if remaining:
                errors.append("APP-11 native queue omits or repeats a frozen command")
            continue
        delivery_occurrence = 0
        for index, row in enumerate(actual_rows[:len(expected_rows)]):
            expected_name = expected_rows[index]
            actual_name = row["name"]
            ref = row["commandRef"]
            key = (ref["processInstanceId"], ref["id"])
            logical_name = _native_command_name(expected_name)
            input_alias = isinstance(expected_name, str) and re.fullmatch(
                r"Deliver\((?:current|replay|slot-[AB][1-9][0-9]*),[A-Za-z]+\)", expected_name
            ) is not None
            if not input_alias and actual_name == logical_name:
                bindings[key] = expected_name
                continue
            if input_alias:
                input_slot, expected_label = expected_name[len("Deliver("):-1].split(",", 1)
                transport_pair = _transport_pair_for_label(expected_label)
                if input_slot == "current":
                    declaration = _delivery_declaration(scenario, delivery_occurrence)
                    delivery_occurrence += 1
                elif input_slot == "replay":
                    prior_current = [
                        value for value in expected_rows[:index]
                        if isinstance(value, str) and value.startswith("Deliver(current,")
                    ]
                    declaration = _delivery_declaration(scenario, max(0, len(prior_current) - 1)) if prior_current else None
                else:
                    declaration = _delivery_declaration(scenario, 0)
                    if declaration is None:
                        declaration = {"slotId": input_slot, "outcome": transport_pair[0] if transport_pair else None}
                    elif declaration.get("slotId") != input_slot:
                        declaration = None
                if (
                    isinstance(declaration, dict)
                    and transport_pair is not None
                    and declaration.get("outcome") == transport_pair[0]
                    and isinstance(declaration.get("slotId"), str)
                    and actual_name == f"Deliver({declaration['slotId']},{transport_pair[0]})"
                ):
                    slot_id = declaration["slotId"]
                    if not any(
                        event.get("kind") == "slotIssued"
                        and event.get("processInstanceId") == pid
                        and event.get("slotId") == slot_id
                        for event in events if isinstance(event, dict)
                    ):
                        errors.append(f"{expected_name} alias has no native slot issuance for {slot_id}")
                    if input_slot != "replay":
                        received = [
                            event for event in events
                            if event.get("kind") == "transportReceived" and event.get("commandRef") == ref
                        ]
                        if len(received) > 1 or (received and (
                            received[0].get("slotId") != slot_id
                        )):
                            errors.append(f"{expected_name} alias disagrees with its native transport slot or outcome")
                        completions = [
                            event for event in events
                            if event.get("kind") == "completionProcessed" and event.get("commandRef") == ref
                        ]
                        if len(completions) > 1 or (completions and completions[0].get("slotId") != slot_id):
                            errors.append(f"{expected_name} alias disagrees with its native completion slot")
                        bindings[key] = expected_name
                    else:
                        replay_rows = [
                            item for item in controller
                            if item.get("kind") == "replayRequested" and item.get("commandRef") == ref
                        ]
                        if len(replay_rows) != 1:
                            errors.append(f"{expected_name} alias lacks one bound Debug replay action")
                        else:
                            replay = replay_rows[0]
                            source_ref = replay.get("sourceCommandRef")
                            prior_completions = [
                                event for event in events
                                if event.get("kind") == "completionProcessed"
                                and event.get("processInstanceId") == pid
                                and event.get("slotId") == slot_id
                                and isinstance(event.get("commandRef"), dict)
                                and event["commandRef"].get("id", MAX_I64) < ref["id"]
                            ]
                            latest = max(prior_completions, key=lambda event: event.get("localSequence", 0), default=None)
                            source_ref_key = (source_ref.get("processInstanceId"), source_ref.get("id")) if isinstance(source_ref, dict) else None
                            source_name = next((
                                item.get("name") for item in trace.get("commandInventory", [])
                                if isinstance(item, dict) and item.get("commandRef") == source_ref
                            ), None)
                            source_received = any(
                                event.get("kind") == "transportReceived"
                                and event.get("commandRef") == source_ref
                                and event.get("slotId") == slot_id
                                for event in events if isinstance(event, dict)
                            )
                            if (
                                replay.get("slotId") != slot_id
                                or type(replay.get("actionId")) is not int or not 1 <= replay["actionId"] <= MAX_I64
                                or source_ref_key is None or source_ref_key[0] != pid
                                or source_ref_key == key or latest is None
                                or latest.get("commandRef") != source_ref
                                or not source_received
                                or source_name != f"Deliver({slot_id},{transport_pair[0]})"
                            ):
                                errors.append(f"{expected_name} alias has invalid action or source completion lineage")
                            else:
                                bindings[key] = expected_name
                if key not in bindings:
                    errors.append(f"native command {actual_name} does not fulfill frozen input {expected_name}")
                continue
            errors.append(f"native command {actual_name} does not fulfill frozen input {expected_name}")
    return bindings, errors


def _normalize_command_roles(scenario, trace):
    """Use verified frozen roles internally while preserving raw native names."""
    bindings, _ = _command_role_bindings(scenario, trace)
    normalized = copy.deepcopy(trace)
    for row in normalized.get("commandInventory", []):
        ref = row.get("commandRef", {})
        role = bindings.get((ref.get("processInstanceId"), ref.get("id")))
        if role is not None:
            row["name"] = role
    for event in normalized.get("events", []):
        if event.get("kind") != "commandEnqueued":
            continue
        ref = event.get("commandRef", {})
        role = bindings.get((ref.get("processInstanceId"), ref.get("id")))
        if role is not None:
            event["name"] = role
    return normalized
SCENARIO_INVENTORY_FIELDS = {
    "id", "platforms", "launches", "commands", "variants", "cancelMode", "controls",
    "requiredServerEvents", "requiredControllerEvents", "requiredProbes",
    "probeExpectations", "probeExpectationInvariants", "requiredRenderedViews",
    "renderExpectations", "renderExpectationInvariants", "expectedFinal",
    "requiredDelivery", "expectedDeliveries", "expectedIssuance",
    "requiredServerRequestCount", "replayCount", "serverResponsesPerRequest",
    "receiptExpectations", "expectedTransport", "receiptStoreExpectation",
    "requiredStoreFault", "fault", "faultObservation", "probeBeforeRetry", "outcome", "receiptProbeOrder",
    "releaseAfterCommand", "releaseAfterProbes", "hookReleaseAfterCommand",
    "hookReleasePoint", "hookReleaseAfterProbes", "barrier", "queuedOrder",
    "forbiddenCommands", "effects", "selectedVariantId",
}
VARIANT_INVENTORY_FIELDS = {
    "id", "commands", "fault", "faultObservation", "barrier", "queuedOrder",
    "outcome", "probeBeforeRetry", "expectedFinal", "expectedTransport",
    "receiptStoreExpectation", "receiptExpectations", "probeExpectations",
    "renderExpectations", "probeExpectationInvariants", "renderExpectationInvariants",
    "receiptProbeOrder", "releaseAfterCommand", "releaseAfterProbes",
    "requiredControllerEvents", "requiredProbes", "requiredRenderedViews",
    "requiredServerEvents",
}
CONTROL_INVENTORY_FIELDS = {
    "id", "mutant", "commands", "required", "witnessInvariants", "requiredControllerEvents",
    "requiredServerEvents", "requiredDelivery", "requiredProbes", "probeExpectations",
    "requiredRenderedViews", "renderExpectations", "expectedFinal", "receiptExpectations",
    "receiptStoreExpectation", "probeExpectationInvariants", "renderExpectationInvariants",
    "launches", "platforms", "cancelMode", "releaseAfterCommand", "releaseAfterProbes",
    "receiptProbeOrder", "hookReleaseAfterCommand", "hookReleasePoint", "hookReleaseAfterProbes",
    "effects", "controlActions", "forbiddenCommands",
}
EVENT_BASE = {"processInstanceId", "launchOrdinal", "localSequence", "kind"}
EVENT_FIELDS = {
    "processStart": (EVENT_BASE | {"initialView"}, EVENT_BASE | {"initialView"}),
    "processEnd": (EVENT_BASE, EVENT_BASE),
    "commandEnqueued": (EVENT_BASE | {"commandRef", "name"}, EVENT_BASE | {"commandRef", "name"}),
    "commandStarted": (EVENT_BASE | {"commandRef"}, EVENT_BASE | {"commandRef"}),
    "managedReduced": (
        EVENT_BASE | {"commandRef", "event", "pre", "result", "epochId"},
        EVENT_BASE | {"commandRef", "event", "pre", "result", "epochId", "slotId", "requestOwnerId"},
    ),
    "managedInstanceReset": (EVENT_BASE | {"commandRef", "before", "after"}, EVENT_BASE | {"commandRef", "before", "after"}),
    "slotIssued": (
        EVENT_BASE | {"commandRef", "slotId", "ownerId", "epochId", "requestId", "wireRequestId", "account", "seedVersion", "wireTag"},
        EVENT_BASE | {"commandRef", "slotId", "ownerId", "epochId", "requestId", "wireRequestId", "account", "seedVersion", "wireTag"},
    ),
    "transportReceived": (EVENT_BASE | {"commandRef", "slotId", "outcome", "failureCode", "requestTag"}, EVENT_BASE | {"commandRef", "slotId", "outcome", "failureCode", "requestTag"}),
    "completionProcessed": (EVENT_BASE | {"commandRef", "slotId", "receiptEventRef"}, EVENT_BASE | {"commandRef", "slotId", "receiptEventRef"}),
    "storeMutation": (
        EVENT_BASE | {"commandRef", "operation", "cause", "before", "after"},
        EVENT_BASE | {"commandRef", "operation", "cause", "before", "after", "slotId", "epochId", "ownerId", "releaseActionId", "effectId", "originCommandRef"},
    ),
    "storeReadback": (EVENT_BASE | {"commandRef", "operation", "observation"}, EVENT_BASE | {"commandRef", "operation", "observation"}),
    "storeFault": (EVENT_BASE | {"commandRef", "operation", "fault", "mutationApplied", "verification", "before", "observation"}, EVENT_BASE | {"commandRef", "operation", "fault", "mutationApplied", "verification", "before", "observation"}),
    "detachedStoreMutation": (EVENT_BASE | {"effectId", "originCommandRef", "operation", "cause", "before", "after", "releaseActionId"}, EVENT_BASE | {"effectId", "originCommandRef", "operation", "cause", "before", "after", "releaseActionId"}),
    "detachedStoreReadback": (EVENT_BASE | {"effectId", "originCommandRef", "operation", "observation"}, EVENT_BASE | {"effectId", "originCommandRef", "operation", "observation"}),
    "hookEvent": (EVENT_BASE | {"actionId", "point", "phase"}, EVENT_BASE | {"actionId", "point", "phase", "target", "commandRef"}),
    "uiPublishAck": (EVENT_BASE | {"commandRef", "revision", "view"}, EVENT_BASE | {"commandRef", "revision", "view"}),
    "commandReceipt": (EVENT_BASE | {"commandRef", "status", "observation", "acknowledgedEventRef"}, EVENT_BASE | {"commandRef", "status", "observation", "acknowledgedEventRef"}),
}
CONTROLLER_BASE = {"sequence", "kind", "processInstanceId"}
CONTROLLER_FIELDS = {
    "launch": (CONTROLLER_BASE | {"launchOrdinal"}, CONTROLLER_BASE | {"launchOrdinal"}),
    "requestHeld": (CONTROLLER_BASE | {"requestTag"}, CONTROLLER_BASE | {"requestTag"}),
    "receiptObserved": (CONTROLLER_BASE | {"commandRef", "eventRef"}, CONTROLLER_BASE | {"commandRef", "eventRef"}),
    "probeCaptured": (CONTROLLER_BASE | {"stepId"}, CONTROLLER_BASE | {"stepId"}),
    "releaseRequested": (CONTROLLER_BASE | {"requestTag"}, CONTROLLER_BASE | {"requestTag"}),
    "releaseAccepted": (CONTROLLER_BASE | {"requestTag"}, CONTROLLER_BASE | {"requestTag", "serverSequence"}),
    "responseWritten": (CONTROLLER_BASE | {"requestTag"}, CONTROLLER_BASE | {"requestTag", "serverSequence"}),
    "wrongCorrelation": (CONTROLLER_BASE | {"requestTag", "serverSequence", "echoedRequestTag"}, CONTROLLER_BASE | {"requestTag", "serverSequence", "echoedRequestTag"}),
    "completionProcessedObserved": (CONTROLLER_BASE | {"commandRef", "eventRef"}, CONTROLLER_BASE | {"commandRef", "eventRef"}),
    "terminated": (CONTROLLER_BASE | {"launchOrdinal"}, CONTROLLER_BASE | {"launchOrdinal"}),
    "forceStopped": (CONTROLLER_BASE | {"pidAbsent"}, CONTROLLER_BASE | {"pidAbsent"}),
    "bootstrapHookArrived": (CONTROLLER_BASE | {"point", "authMailboxPaused"}, CONTROLLER_BASE | {"point", "authMailboxPaused"}),
    "hookArrived": (CONTROLLER_BASE | {"point"}, CONTROLLER_BASE | {"point", "authMailboxPaused", "eventRef"}),
    "hookReleased": (
        CONTROLLER_BASE | {"point", "releaseChannel", "eventRef"},
        CONTROLLER_BASE | {"point", "releaseChannel", "eventRef", "authMailboxPaused", "bootstrapReceiptObserved", "deliverReceiptObserved"},
    ),
    "detachedEffectAwaited": (
        CONTROLLER_BASE | {"effectId", "originCommandRef", "mutationEventRef", "readbackEventRef"},
        CONTROLLER_BASE | {"effectId", "originCommandRef", "mutationEventRef", "readbackEventRef"},
    ),
    "checkpointPublished": (CONTROLLER_BASE | {"name", "serverSequence"}, CONTROLLER_BASE | {"name", "serverSequence"}),
    "replayRequested": (
        CONTROLLER_BASE | {"slotId", "actionId", "commandRef", "sourceCommandRef"},
        CONTROLLER_BASE | {"slotId", "actionId", "commandRef", "sourceCommandRef"},
    ),
    "hookArmed": (CONTROLLER_BASE | {"point", "target"}, CONTROLLER_BASE | {"point", "target"}),
    "disconnected": (CONTROLLER_BASE | {"requestTag", "serverSequence"}, CONTROLLER_BASE | {"requestTag", "serverSequence"}),
    "processEndAcknowledged": (
        CONTROLLER_BASE | {"eventRef"},
        CONTROLLER_BASE | {"eventRef"},
    ),
}
CONTROLLER_KINDS = set(CONTROLLER_FIELDS)
SERVER_FIELDS = {
    "requestHeld": {"runId", "sequence", "kind", "requestTag", "requestId"},
    "releaseAccepted": {"runId", "sequence", "kind", "requestTag", "outcome"},
    "responseWritten": {"runId", "sequence", "kind", "requestTag", "outcome"},
    "wrongCorrelation": {"runId", "sequence", "kind", "requestTag", "echoedRequestTag"},
    "disconnected": {"runId", "sequence", "kind", "requestTag", "outcome"},
    "http500": {"runId", "sequence", "kind", "requestTag"},
    "malformed": {"runId", "sequence", "kind", "requestTag"},
    "checkpointPublished": {"runId", "sequence", "kind", "processInstanceId", "name"},
}
AUTH_PHASES = {"SignedIn", "Refreshing"}
NO_AUTH_PROJECTION = {"Booting", "SignedOut", "SigningOut", "FaultLocked"}


def _ref_ok(value, process_ids):
    return (
        isinstance(value, dict)
        and set(value) == {"processInstanceId", "id"}
        and isinstance(value.get("processInstanceId"), str)
        and value["processInstanceId"] in process_ids
        and type(value.get("id")) is int
        and 1 <= value["id"] <= MAX_I64
    )


def _event_ref_ok(value, process_ids):
    return (
        isinstance(value, dict)
        and set(value) == {"processInstanceId", "localSequence"}
        and isinstance(value.get("processInstanceId"), str)
        and value["processInstanceId"] in process_ids
        and type(value.get("localSequence")) is int
        and 1 <= value["localSequence"] <= MAX_I64
    )


def _native_released_hook_event(trace, controller_event):
    """Resolve a host release only through its real process-scoped native hookEvent ref."""
    ref = controller_event.get("eventRef") if isinstance(controller_event, dict) else None
    if not isinstance(ref, dict) or set(ref) != {"processInstanceId", "localSequence"}:
        return None
    return next((
        event for event in trace.get("events", [])
        if isinstance(event, dict)
        and event.get("processInstanceId") == ref.get("processInstanceId")
        and event.get("localSequence") == ref.get("localSequence")
        and event.get("kind") == "hookEvent"
        and event.get("phase") == "released"
        and event.get("processInstanceId") == controller_event.get("processInstanceId")
        and event.get("point") == controller_event.get("point")
    ), None)


def _controller_releases_for_action(trace, process_id, action_id, point=None):
    matches = []
    for controller_event in trace.get("controllerEvents", []):
        if (
            not isinstance(controller_event, dict)
            or controller_event.get("kind") != "hookReleased"
            or controller_event.get("processInstanceId") != process_id
            or (point is not None and controller_event.get("point") != point)
        ):
            continue
        native = _native_released_hook_event(trace, controller_event)
        if native is not None and native.get("actionId") == action_id:
            matches.append((controller_event, native))
    return matches


def _store_ok(value):
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return False
    if value["kind"] == "Absent":
        return set(value) == {"kind"}
    if value["kind"] == "Present":
        return set(value) == {"kind", "account", "version"} and value.get("account") in {"A", "B"} and type(value.get("version")) is int and 0 <= value["version"] <= MAX_I64
    if value["kind"] == "Unknown":
        return set(value) == {"kind", "errorCode"} and isinstance(value.get("errorCode"), str) and bool(value["errorCode"])
    return False


def _view_ok(value):
    expected = {"phase", "account", "credentialVersion", "pendingRequestId", "lastCompletedCommandId", "lastCommandStatus"}
    if not isinstance(value, dict) or set(value) != expected:
        return False
    if value["phase"] not in {"Booting", "SignedOut", "SigningOut", "SignedIn", "Refreshing", "FaultLocked"}:
        return False
    if value["account"] not in {None, "A", "B"}:
        return False
    if value["credentialVersion"] is not None and (type(value["credentialVersion"]) is not int or not 0 <= value["credentialVersion"] <= MAX_I64):
        return False
    if value["pendingRequestId"] is not None and (type(value["pendingRequestId"]) is not int or not 1 <= value["pendingRequestId"] <= MAX_I64):
        return False
    if value["lastCompletedCommandId"] is not None and (type(value["lastCompletedCommandId"]) is not int or not 1 <= value["lastCompletedCommandId"] <= MAX_I64):
        return False
    if value["lastCommandStatus"] is not None and value["lastCommandStatus"] not in {"Completed", "RejectedBusy", "IgnoredStale", "IgnoredForeign", "RejectedExhausted", "FaultLocked"}:
        return False
    if value["phase"] in AUTH_PHASES and value["account"] not in {"A", "B"}:
        return False
    if value["phase"] in NO_AUTH_PROJECTION and value["account"] is not None:
        return False
    return True


def _managed_ok(value, *, result=False):
    if not isinstance(value, dict):
        return False
    keys = {"ownerId", "state", "pendingRequestId", "nextRequestId"}
    if result:
        keys |= {"effects", "rejection"}
    if set(value) != keys or not isinstance(value.get("ownerId"), str) or not value["ownerId"]:
        return False
    if value.get("state") not in {"Unauthenticated", "Authenticated", "Refreshing"}:
        return False
    pending, next_id = value.get("pendingRequestId"), value.get("nextRequestId")
    if pending is not None and (type(pending) is not int or not 1 <= pending <= MAX_I64):
        return False
    if next_id is not None and (type(next_id) is not int or not 1 <= next_id <= MAX_I64):
        return False
    if (value["state"] == "Refreshing") != (pending is not None):
        return False
    if result:
        effects = value.get("effects")
        if not isinstance(effects, list) or value.get("rejection") not in {None, "RequestIdExhausted", "ForeignRequest"}:
            return False
        for effect in effects:
            if not isinstance(effect, dict) or set(effect) not in ({"effect"}, {"effect", "requestId"}):
                return False
            if effect.get("effect") not in {"ClearCredentials", "RequestTokenRefresh"}:
                return False
            if (effect["effect"] == "RequestTokenRefresh") != (set(effect) == {"effect", "requestId"}):
                return False
            if "requestId" in effect and (type(effect["requestId"]) is not int or not 1 <= effect["requestId"] <= MAX_I64):
                return False
    return True


def _issue(invariant, command_ref, event, expected, actual):
    process_id = "unknown"
    ident = 0
    if isinstance(command_ref, dict) and isinstance(command_ref.get("processInstanceId"), str) and type(command_ref.get("id")) is int:
        process_id, ident = command_ref["processInstanceId"], command_ref["id"]
    event_process, sequence = process_id, 0
    if isinstance(event, dict) and isinstance(event.get("processInstanceId"), str):
        event_process = event["processInstanceId"]
        sequence = event.get("localSequence", 0) if type(event.get("localSequence", 0)) is int else 0
    return {
        "invariant": invariant,
        "commandRef": {"processInstanceId": process_id, "id": ident},
        "eventRef": {"processInstanceId": event_process, "localSequence": sequence},
        "expected": expected,
        "actual": actual,
    }


def _history_error(message, event=None, command_ref=None):
    return _issue("HISTORY", command_ref, event, "well-formed frozen evidence", message)


def _shape_errors(contract, scenario, trace, server_events, ui_observations):
    errors = []
    if not isinstance(contract, dict) or contract.get("version") != 1 or not isinstance(contract.get("invariants"), list):
        return ["invalid integration contract"]
    if not isinstance(scenario, dict) or not isinstance(scenario.get("id"), str):
        return ["invalid scenario inventory entry"]
    errors.extend(_scenario_inventory_errors(scenario))
    if not isinstance(trace, dict) or not TOP_REQUIRED_KEYS <= set(trace) or set(trace) - TOP_KEYS or len(set(trace) & TOP_OPTIONAL_KEYS) > 1:
        return ["trace must have the exact frozen top-level fields"]
    if trace.get("version") != 1 or trace.get("scenarioId") != scenario["id"]:
        errors.append("trace version/scenario ID does not match the frozen inventory")
    if not isinstance(trace.get("runId"), str) or not trace["runId"]:
        errors.append("runId must be a nonempty string")
    for selector in TOP_OPTIONAL_KEYS:
        if selector in trace and (not isinstance(trace[selector], str) or not trace[selector]):
            errors.append(f"{selector} must be a nonempty string")
    if trace.get("platform") not in {"ios", "android"} or trace.get("platform") not in scenario.get("platforms", []):
        errors.append("platform is not declared for this scenario")
    if not isinstance(trace.get("buildHash"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", trace["buildHash"]):
        errors.append("buildHash must be sha256 plus 64 lowercase hexadecimal digits")

    expected_launches = scenario.get("launches", [])
    if not isinstance(expected_launches, list) or any(not isinstance(x, dict) or type(x.get("ordinal")) is not int or not isinstance(x.get("commands"), list) for x in expected_launches):
        errors.append("scenario launches inventory is malformed")
        expected_launches = []
    processes = trace.get("processInstances")
    if not isinstance(processes, list):
        return errors + ["processInstances must be an array"]
    process_ids, process_ordinals = set(), {}
    for row in processes:
        if not isinstance(row, dict) or set(row) != {"processInstanceId", "launchOrdinal"}:
            errors.append("process instance has invalid fields")
            continue
        pid, ordinal = row["processInstanceId"], row["launchOrdinal"]
        if not isinstance(pid, str) or not pid or type(ordinal) is not int or not 1 <= ordinal <= MAX_I64:
            errors.append("process identity/launch ordinal is invalid")
            continue
        if pid in process_ids:
            errors.append("processInstanceId is reused")
        if ordinal in process_ordinals:
            errors.append("launchOrdinal is duplicated")
        if not pid.endswith(f"/{scenario['id']}/p{ordinal}"):
            errors.append("processInstanceId does not encode scenario and launch ordinal")
        process_ids.add(pid)
        process_ordinals[ordinal] = pid
    want_ordinals = [row["ordinal"] for row in expected_launches]
    if len(set(want_ordinals)) != len(want_ordinals):
        errors.append("scenario inventory has duplicate launch ordinals")
    if any(ordinal not in want_ordinals for ordinal in process_ordinals):
        errors.append("trace contains an undeclared launch ordinal")
    if len(processes) > len(want_ordinals):
        errors.append("trace contains more processes than the scenario inventory")

    command_inventory = trace.get("commandInventory")
    if not isinstance(command_inventory, list):
        return errors + ["commandInventory must be an array"]
    command_names, command_refs = {}, {}
    for row in command_inventory:
        if not isinstance(row, dict) or set(row) != {"commandRef", "name"} or not isinstance(row.get("name"), str):
            errors.append("command inventory entry has invalid fields")
            continue
        ref = row["commandRef"]
        if not _ref_ok(ref, process_ids):
            errors.append("command inventory has an invalid commandRef")
            continue
        key = (ref["processInstanceId"], ref["id"])
        if key in command_refs:
            errors.append("duplicate command identity")
        command_refs[key] = row["name"]
        command_names.setdefault(ref["processInstanceId"], []).append((ref["id"], row["name"]))
    for pid, rows in command_names.items():
        rows.sort()
        ids = [ident for ident, _ in rows]
        if ids != list(range(1, len(ids) + 1)):
            errors.append(f"command IDs do not start at 1 and increase without gaps in {pid}")
    command_bindings, alias_errors = _command_role_bindings(scenario, trace)
    errors.extend(alias_errors)
    for launch in expected_launches:
        ordinal = launch["ordinal"]
        pid = process_ordinals.get(ordinal)
        if pid is None:
            continue
        actual = [name for _, name in sorted(command_names.get(pid, []))]
        expected = launch["commands"]
        if len(actual) > len(expected):
            errors.append(f"command inventory for launch {ordinal} exceeds the frozen sequence")
        elif scenario.get("id") == "APP-11":
            ordered_rows = sorted(
                (row for row in command_inventory if isinstance(row, dict) and row.get("commandRef", {}).get("processInstanceId") == pid),
                key=lambda row: row["commandRef"]["id"],
            )
            logical = [command_bindings.get((pid, row["commandRef"]["id"]), row["name"]) for row in ordered_rows]
            if sorted(logical) != sorted(expected[:len(actual)]):
                errors.append("APP-11 command inventory is not a permutation of the frozen queued prefix")

    events = trace.get("events")
    if not isinstance(events, list):
        return errors + ["events must be an array"]
    event_by_ref, per_process_sequences = {}, defaultdict(list)
    enqueued, started, receipts, managed_by_command = {}, {}, {}, {}
    open_commands = defaultdict(list)
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
            errors.append("native event must be an object with a kind")
            continue
        kind = event["kind"]
        if kind not in EVENT_FIELDS:
            errors.append(f"unknown native event kind {kind!r}")
            continue
        required, allowed = EVENT_FIELDS[kind]
        if not required <= set(event) or set(event) - allowed:
            errors.append(f"{kind} has missing or extra fields")
            continue
        pid, ordinal, sequence = event.get("processInstanceId"), event.get("launchOrdinal"), event.get("localSequence")
        if pid not in process_ids or type(ordinal) is not int or process_ordinals.get(ordinal) != pid or type(sequence) is not int or not 1 <= sequence <= MAX_I64:
            errors.append(f"{kind} has invalid process namespace or sequence")
            continue
        ref = (pid, sequence)
        if ref in event_by_ref:
            errors.append("duplicate process-local event sequence")
        event_by_ref[ref] = event
        per_process_sequences[pid].append(sequence)
        if kind in {"commandEnqueued", "commandStarted", "managedReduced", "slotIssued", "transportReceived", "completionProcessed", "storeMutation", "storeReadback", "storeFault", "uiPublishAck", "commandReceipt"}:
            cmd = event.get("commandRef")
            if not _ref_ok(cmd, process_ids) or (cmd["processInstanceId"], cmd["id"]) not in command_refs:
                errors.append(f"{kind} refers to an unknown command")
                continue
            key = (cmd["processInstanceId"], cmd["id"])
            if kind == "commandEnqueued":
                if key in enqueued or command_refs[key] != event["name"]:
                    errors.append("command enqueue does not match its unique inventory entry")
                enqueued[key] = event["localSequence"]
            elif kind == "commandStarted":
                if key not in enqueued or key in started or event["localSequence"] <= enqueued.get(key, 0):
                    errors.append("command start has no earlier unique enqueue")
                started[key] = event["localSequence"]
                open_commands[pid].append(key)
            elif kind == "managedReduced":
                if key in managed_by_command or key not in started:
                    errors.append("managed reduction is duplicated or outside a started command")
                managed_by_command[key] = event
                if not _managed_ok(event.get("pre")) or not _managed_ok(event.get("result"), result=True) or not isinstance(event.get("epochId"), str) or not event["epochId"]:
                    errors.append("managed reduction does not carry a complete owner/epoch snapshot")
                if not isinstance(event.get("event"), dict) or set(event["event"]) not in ({"event"}, {"event", "requestId"}) or not isinstance(event["event"].get("event"), str):
                    errors.append("managed reduction event has invalid shape")
                if event.get("slotId") is not None and not isinstance(event.get("slotId"), str):
                    errors.append("managed reduction slotId is invalid")
                if command_refs.get(key, "").startswith("Deliver("):
                    if not isinstance(event.get("slotId"), str) or not isinstance(event.get("requestOwnerId"), str) or not event.get("requestOwnerId"):
                        errors.append("Deliver reduction requires captured slotId and requestOwnerId")
            elif kind == "commandReceipt":
                if key in receipts or key not in started:
                    errors.append("command receipt is duplicated or has no command start")
                if key not in open_commands[pid]:
                    errors.append("command receipt does not close the currently executing command")
                else:
                    open_commands[pid].remove(key)
                receipts[key] = event
                observation = event.get("observation")
                if event.get("status") not in {"Completed", "RejectedBusy", "IgnoredStale", "IgnoredForeign", "RejectedExhausted", "FaultLocked"}:
                    errors.append("command receipt status is outside the frozen set")
                if not isinstance(observation, dict) or set(observation) != {"managed", "store", "view", "revision"}:
                    errors.append("command receipt observation is incomplete")
                elif not _managed_ok(observation["managed"]) or not _store_ok(observation["store"]) or not _view_ok(observation["view"]) or type(observation["revision"]) is not int or not 1 <= observation["revision"] <= MAX_I64:
                    errors.append("command receipt observation has invalid values")
            elif kind == "uiPublishAck" and (len(open_commands[pid]) != 1 or open_commands[pid][-1] != key):
                errors.append("UI acknowledgement is outside its active command or is not the currently executing command")
            elif kind == "transportReceived":
                outcome, failure = event.get("outcome"), event.get("failureCode")
                if outcome == "success" and failure is not None:
                    errors.append("successful transport event cannot carry a failure code")
                elif outcome == "failure" and (not isinstance(failure, str) or not failure):
                    errors.append("failed transport event requires a frozen failure code")
            elif kind == "storeFault":
                fault = event.get("fault")
                operation = "replace" if isinstance(fault, str) and fault.startswith("replace") else "clear" if isinstance(fault, str) and fault.startswith("clear") else None
                applied = fault in {"replaceAfterBeforeVerify", "clearAfterBeforeVerify"}
                if (
                    operation != event.get("operation") or event.get("mutationApplied") is not applied
                    or event.get("verification") != ("failed" if applied else "notAttempted")
                    or not _store_ok(event.get("before")) or not _store_ok(event.get("observation"))
                    or (not applied and event.get("before") != event.get("observation"))
                    or (applied and event.get("observation", {}).get("kind") != "Unknown")
                ):
                    errors.append("store fault event does not document the frozen failure and observed physical state")
            elif kind == "storeMutation":
                needs_bootstrap_release = event.get("cause") == "Bootstrap" and ordinal > 1
                action_id = event.get("releaseActionId")
                if needs_bootstrap_release and action_id is None:
                    errors.append("restart Bootstrap clear has no native release action ID")
                if action_id is not None:
                    if type(action_id) is not int or not 1 <= action_id <= MAX_I64:
                        errors.append("store mutation releaseActionId is invalid")
                    else:
                        expected_point = "beforeBootstrapClear" if needs_bootstrap_release else None
                        releases = _controller_releases_for_action(trace, pid, action_id, expected_point)
                        if len(releases) != 1:
                            errors.append("store mutation release action ID has no unique linked native released hook")
                        elif releases[0][1].get("localSequence", MAX_I64) >= sequence:
                            errors.append("store mutation precedes its native released hook action")
        elif kind in {"detachedStoreMutation", "detachedStoreReadback"}:
            origin = event.get("originCommandRef")
            if not _ref_ok(origin, process_ids) or origin.get("processInstanceId") != pid:
                errors.append(f"{kind} has invalid process-scoped originCommandRef")
            if not isinstance(event.get("effectId"), str) or not event["effectId"]:
                errors.append(f"{kind} requires a nonempty effectId")
            if event.get("operation") != "clear":
                errors.append(f"{kind} operation is outside the frozen detached-effect set")
            if kind == "detachedStoreMutation":
                action_id = event.get("releaseActionId")
                if event.get("cause") != "DeferredLogoutClear" or not _store_ok(event.get("before")) or not _store_ok(event.get("after")) or type(action_id) is not int or not 1 <= action_id <= MAX_I64:
                    errors.append("detached mutation has invalid cause, store snapshots or release link")
            elif not _store_ok(event.get("observation")):
                errors.append("detached readback has an invalid store observation")
        elif kind == "hookEvent":
            if type(event.get("actionId")) is not int or not 1 <= event["actionId"] <= MAX_I64 or event.get("phase") not in {"armed", "arrived", "released"} or event.get("point") not in {"beforeBootstrapClear", "afterManaged", "beforeStore", "beforePublish", "afterPublishAck", "afterLogoutReceipt", "ingressHeld", "beforeDeferredControlClear"}:
                errors.append("native hook event has invalid action, point or phase")
            if event.get("target") is not None and event.get("target") not in {"bootstrap", "nextCommand", "nextDelivery"}:
                errors.append("native hook event target is outside the frozen set")
            if event.get("commandRef") is not None and (not _ref_ok(event.get("commandRef"), process_ids) or event["commandRef"]["processInstanceId"] != pid):
                errors.append("native hook event commandRef has invalid process identity")
        elif kind == "managedInstanceReset":
            command_ref = event.get("commandRef")
            if not _ref_ok(command_ref, process_ids) or command_ref.get("processInstanceId") != pid or not _managed_ok(event.get("before")) or not _managed_ok(event.get("after")):
                errors.append("managed instance reset has invalid command provenance or snapshots")
            elif event["before"]["state"] != "Unauthenticated" or event["after"]["state"] != "Unauthenticated" or event["before"]["pendingRequestId"] is not None or event["after"]["pendingRequestId"] is not None or event["before"]["ownerId"] == event["after"]["ownerId"] or event["after"]["nextRequestId"] != 1:
                errors.append("managed instance reset must create a fresh unauthenticated owner and allocator")

    for pid, sequences in per_process_sequences.items():
        if sequences != sorted(sequences):
            errors.append(f"native events are not serialized in process-sequence order in {pid}")
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            errors.append(f"event sequence is not contiguous in {pid}")
        enqueue_order = [
            key for key, _ in sorted(
                ((key, sequence) for key, sequence in enqueued.items() if key[0] == pid),
                key=lambda row: row[1],
            )
        ]
        start_order = [
            key for key, _ in sorted(
                ((key, sequence) for key, sequence in started.items() if key[0] == pid),
                key=lambda row: row[1],
            )
        ]
        if start_order != enqueue_order[:len(start_order)]:
            errors.append(f"command start order violates FIFO enqueue order in {pid}")
    for pid in process_ids:
        process_events = [event for event in events if event.get("processInstanceId") == pid]
        kinds = [event["kind"] for event in process_events]
        if kinds.count("processStart") > 1 or kinds.count("processEnd") > 1:
            errors.append(f"process start/end marker is duplicated in {pid}")
        terminal_rows = [index for index, event in enumerate(process_events) if event.get("kind") == "processEnd"]
        if len(terminal_rows) == 1 and terminal_rows[0] != len(process_events) - 1:
            errors.append(f"native event appears after processEnd in {pid}")
    # Verify event links that must identify actual native records.
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        command_ref = event.get("commandRef") if isinstance(event.get("commandRef"), dict) else {}
        if kind == "managedReduced" and command_refs.get((command_ref.get("processInstanceId"), command_ref.get("id")), "").startswith("Deliver("):
            slot = next((row for row in events if row.get("kind") == "slotIssued" and row.get("slotId") == event.get("slotId")), None)
            if not slot or slot.get("commandRef", {}).get("processInstanceId") != event.get("processInstanceId") or slot.get("ownerId") != event.get("requestOwnerId"):
                errors.append("Deliver requestOwnerId/slotId does not match its original issuance")
        if kind == "commandReceipt":
            ref = event.get("acknowledgedEventRef")
            if not _event_ref_ok(ref, process_ids):
                errors.append("receipt has invalid UI acknowledgement reference")
                continue
            ack = event_by_ref.get((ref["processInstanceId"], ref["localSequence"]))
            if not ack or ack.get("kind") != "uiPublishAck" or ack.get("commandRef") != event.get("commandRef") or ack.get("localSequence", MAX_I64) >= event.get("localSequence", 0):
                errors.append("receipt acknowledgement does not point to its earlier UI publication")
            elif ack.get("revision") != event.get("observation", {}).get("revision") or ack.get("view") != event.get("observation", {}).get("view"):
                errors.append("receipt observation does not match acknowledged UI state")
        elif kind == "completionProcessed":
            ref = event.get("receiptEventRef")
            if not _event_ref_ok(ref, process_ids):
                errors.append("completion has invalid receipt reference")
                continue
            receipt = event_by_ref.get((ref["processInstanceId"], ref["localSequence"]))
            if not receipt or receipt.get("kind") != "commandReceipt" or receipt.get("commandRef") != event.get("commandRef") or receipt.get("localSequence", MAX_I64) >= event.get("localSequence", 0):
                errors.append("completion processed marker does not follow its receipt")
        elif kind == "detachedStoreMutation":
            origin = event.get("originCommandRef", {})
            origin_key = (origin.get("processInstanceId"), origin.get("id"))
            receipt = receipts.get(origin_key)
            origin_name = command_refs.get(origin_key)
            releases = _controller_releases_for_action(
                trace,
                event.get("processInstanceId"),
                event.get("releaseActionId"),
                "beforeDeferredControlClear",
            )
            if origin_name != "Logout" or not receipt or receipt.get("status") != "Completed" or receipt.get("localSequence", MAX_I64) >= event.get("localSequence", 0):
                errors.append("detached store mutation does not cite a prior completed Logout")
            if len(releases) != 1:
                errors.append("detached store mutation has no matching native DeferredLogoutClear release action")
        elif kind == "managedInstanceReset":
            ref = event["commandRef"]
            key = (ref["processInstanceId"], ref["id"])
            receipt = receipts.get(key)
            if command_refs.get(key) != "RetryCleanup" or not receipt or receipt.get("status") != "Completed" or receipt.get("localSequence", MAX_I64) >= event.get("localSequence", 0) or receipt.get("observation", {}).get("managed") != event.get("before"):
                errors.append("managed instance reset is not linked to a completed RetryCleanup receipt")
        elif kind == "detachedStoreReadback":
            mutation = next((row for row in events if row.get("kind") == "detachedStoreMutation" and row.get("effectId") == event.get("effectId")), None)
            if not mutation or mutation.get("localSequence", MAX_I64) >= event.get("localSequence", 0) or mutation.get("originCommandRef") != event.get("originCommandRef") or mutation.get("after") != event.get("observation"):
                errors.append("detached readback does not verify its unique earlier mutation")

    # Candidate-provided pre-snapshots must chain from the previous receipt.
    for pid in process_ids:
        current = None
        ordered = sorted((event for event in events if event.get("processInstanceId") == pid), key=lambda event: event.get("localSequence", 0))
        for event in ordered:
            if event.get("kind") == "processStart":
                current = None
            elif event.get("kind") == "managedReduced":
                if current is not None and event.get("pre") != current:
                    errors.append("managed pre-snapshot differs from the prior command receipt")
            elif event.get("kind") == "commandReceipt":
                observation = event.get("observation")
                if not isinstance(observation, dict) or not isinstance(observation.get("managed"), dict):
                    continue
                key = (pid, event["commandRef"]["id"])
                reduced = managed_by_command.get(key)
                if reduced:
                    result_snapshot = {field: reduced["result"].get(field) for field in ("ownerId", "state", "pendingRequestId", "nextRequestId")}
                    if observation["managed"] != result_snapshot:
                        errors.append("receipt managed snapshot differs from reducer result")
                elif current is not None and observation["managed"] != current:
                    errors.append("command without a managed reduction changed the managed snapshot")
                current = observation["managed"]
            elif event.get("kind") == "managedInstanceReset":
                if current is not None and event.get("before") != current:
                    errors.append("managed instance reset does not continue the prior receipt snapshot")
                current = event["after"]

    if not isinstance(trace.get("artifactPaths"), list) or any(not isinstance(path, str) or not path for path in trace["artifactPaths"]):
        errors.append("artifactPaths must contain nonempty relative paths")
    elif len(set(trace["artifactPaths"])) != len(trace["artifactPaths"]):
        errors.append("artifact paths overwrite one another")
    elif any(path.startswith("/") or ".." in Path(path).parts for path in trace["artifactPaths"]):
        errors.append("artifact paths must remain within the scenario output namespace")

    controller = trace.get("controllerEvents")
    if not isinstance(controller, list):
        return errors + ["controllerEvents must be an array"]
    controller_by_seq = {}
    for item in controller:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or item.get("kind") not in CONTROLLER_KINDS:
            errors.append("controller event has unknown kind")
            continue
        required_fields, allowed_fields = CONTROLLER_FIELDS[item["kind"]]
        if not required_fields <= set(item) or not set(item) <= allowed_fields:
            errors.append(f"controller event {item['kind']} has missing or extra fields")
            continue
        if type(item.get("sequence")) is not int or not 1 <= item["sequence"] <= MAX_I64 or item.get("processInstanceId") not in process_ids:
            errors.append("controller event has invalid sequence/process identity")
            continue
        if item["sequence"] in controller_by_seq:
            errors.append("controller event sequence is duplicated")
        controller_by_seq[item["sequence"]] = item
        kind = item["kind"]
        if kind in {"launch", "terminated"} and (type(item.get("launchOrdinal")) is not int or process_ordinals.get(item["launchOrdinal"]) != item["processInstanceId"]):
            errors.append(f"{kind} controller event has invalid launch ordinal")
        if kind in {"receiptObserved", "completionProcessedObserved"}:
            if not _ref_ok(item.get("commandRef"), process_ids) or not _event_ref_ok(item.get("eventRef"), process_ids):
                errors.append(f"{kind} controller event lacks command and native event provenance")
            else:
                native = event_by_ref.get((item["eventRef"]["processInstanceId"], item["eventRef"]["localSequence"]))
                expected_kind = "commandReceipt" if kind == "receiptObserved" else "completionProcessed"
                if not native or native.get("kind") != expected_kind or native.get("commandRef") != item.get("commandRef"):
                    errors.append(f"{kind} does not identify its native evidence")
        if kind == "processEndAcknowledged":
            if not _event_ref_ok(item.get("eventRef"), process_ids):
                errors.append("processEnd acknowledgement lacks a valid native event reference")
            else:
                native = event_by_ref.get((item["eventRef"]["processInstanceId"], item["eventRef"]["localSequence"]))
                if (
                    not native or native.get("kind") != "processEnd"
                    or native.get("processInstanceId") != item.get("processInstanceId")
                ):
                    errors.append("processEnd acknowledgement does not identify its native processEnd row")
        if kind == "replayRequested":
            target = item.get("commandRef")
            source = item.get("sourceCommandRef")
            target_key = (target.get("processInstanceId"), target.get("id")) if isinstance(target, dict) else None
            source_key = (source.get("processInstanceId"), source.get("id")) if isinstance(source, dict) else None
            source_completion = next((
                event for event in events
                if event.get("kind") == "completionProcessed" and event.get("commandRef") == source
                and event.get("slotId") == item.get("slotId")
            ), None)
            source_transport = next((
                event for event in events
                if event.get("kind") == "transportReceived" and event.get("commandRef") == source
                and event.get("slotId") == item.get("slotId")
            ), None)
            preceding = [
                event for event in events
                if event.get("kind") == "completionProcessed"
                and event.get("processInstanceId") == item.get("processInstanceId")
                and event.get("slotId") == item.get("slotId")
                and isinstance(event.get("commandRef"), dict)
                and target_key is not None and event["commandRef"].get("id", MAX_I64) < target_key[1]
            ]
            latest = max(preceding, key=lambda event: event.get("localSequence", 0), default=None)
            target_enqueue = next((
                event for event in events
                if event.get("kind") == "commandEnqueued" and event.get("commandRef") == target
            ), None)
            if (
                type(item.get("actionId")) is not int or not 1 <= item["actionId"] <= MAX_I64
                or not isinstance(item.get("slotId"), str) or not item["slotId"]
                or not _ref_ok(target, process_ids) or not _ref_ok(source, process_ids)
                or target.get("processInstanceId") != item.get("processInstanceId")
                or source.get("processInstanceId") != item.get("processInstanceId")
                or target_key == source_key
                or target_key not in command_refs or source_key not in command_refs
                or target_enqueue is None
                or source_completion is None or source_transport is None
                or latest is None or latest.get("commandRef") != source
            ):
                errors.append("replayRequested lacks fresh Debug action and actual source/target command lineage")
            observed_target_receipts = [
                event for event in events
                if event.get("kind") == "completionProcessed" and event.get("commandRef") == target
            ]
            if any(event.get("slotId") != item.get("slotId") for event in observed_target_receipts):
                errors.append("replayRequested target completion changes its captured source slot")
            if len([event for event in controller if event.get("kind") == "replayRequested" and event.get("actionId") == item.get("actionId")]) != 1:
                errors.append("replayRequested Debug actionId is reused")
        if kind == "detachedEffectAwaited":
            origin = item.get("originCommandRef")
            mutation_ref = item.get("mutationEventRef")
            readback_ref = item.get("readbackEventRef")
            mutation = event_by_ref.get((mutation_ref.get("processInstanceId"), mutation_ref.get("localSequence"))) if isinstance(mutation_ref, dict) else None
            readback = event_by_ref.get((readback_ref.get("processInstanceId"), readback_ref.get("localSequence"))) if isinstance(readback_ref, dict) else None
            if (
                not isinstance(item.get("effectId"), str) or not item["effectId"]
                or not _ref_ok(origin, process_ids)
                or origin.get("processInstanceId") != item.get("processInstanceId")
                or not _event_ref_ok(mutation_ref, process_ids)
                or not _event_ref_ok(readback_ref, process_ids)
                or mutation_ref.get("processInstanceId") != item.get("processInstanceId")
                or readback_ref.get("processInstanceId") != item.get("processInstanceId")
                or not mutation or mutation.get("kind") != "detachedStoreMutation"
                or mutation.get("effectId") != item.get("effectId")
                or mutation.get("originCommandRef") != origin
                or not readback or readback.get("kind") != "detachedStoreReadback"
                or readback.get("effectId") != item.get("effectId")
                or readback.get("originCommandRef") != origin
                or readback.get("operation") != mutation.get("operation")
                or readback.get("observation") != mutation.get("after")
                or readback_ref.get("localSequence", 0) <= mutation_ref.get("localSequence", 0)
            ):
                errors.append("detachedEffectAwaited does not identify its exact mutation and readback")
        if scenario.get("id") == "APP-11" and kind in {"hookArrived", "hookReleased"}:
            ref = item.get("eventRef")
            if not _event_ref_ok(ref, process_ids):
                errors.append(f"APP-11 {kind} lacks native hook event provenance")
            else:
                native = event_by_ref.get((ref["processInstanceId"], ref["localSequence"]))
                phase = "arrived" if kind == "hookArrived" else "released"
                if not native or native.get("kind") != "hookEvent" or native.get("phase") != phase:
                    errors.append(f"APP-11 {kind} does not identify the matching native hook event")
        if kind in {"requestHeld", "releaseRequested", "releaseAccepted", "responseWritten", "wrongCorrelation"} and not isinstance(item.get("requestTag"), str):
            errors.append(f"{kind} is missing requestTag")
        if kind == "probeCaptured" and not isinstance(item.get("stepId"), str):
            errors.append("probeCaptured is missing stepId")
    controller_sequences = [item.get("sequence") for item in controller if isinstance(item, dict)]
    if controller_sequences != sorted(controller_sequences):
        errors.append("controller events are not serialized in sequence order")
    if controller_by_seq and sorted(controller_by_seq) != list(range(1, len(controller_by_seq) + 1)):
        errors.append("controller sequence is not contiguous")
    for pid in process_ids:
        end_ack_count = sum(
            item.get("kind") == "processEndAcknowledged" and item.get("processInstanceId") == pid
            for item in controller
        )
        if end_ack_count > 1:
            errors.append(f"process end acknowledgement is duplicated in {pid}")

    if not isinstance(server_events, list):
        errors.append("server events must be an array")
    else:
        sequences = []
        for item in server_events:
            if not isinstance(item, dict) or item.get("kind") not in SERVER_FIELDS or set(item) != SERVER_FIELDS[item.get("kind")]:
                errors.append("server event has invalid fields")
                continue
            if item.get("runId") != trace.get("runId"):
                errors.append("server event belongs to another run")
            if type(item.get("sequence")) is not int or not 1 <= item["sequence"] <= MAX_I64:
                errors.append("server event sequence is invalid")
            else:
                sequences.append(item["sequence"])
            if item.get("kind") in {"requestHeld", "releaseAccepted", "responseWritten", "disconnected", "http500", "malformed", "wrongCorrelation"} and not isinstance(item.get("requestTag"), str):
                errors.append("server event requestTag is invalid")
            if item.get("kind") == "wrongCorrelation" and (
                not isinstance(item.get("echoedRequestTag"), str)
                or item.get("echoedRequestTag") == item.get("requestTag")
            ):
                errors.append("server wrongCorrelation event must record a distinct echoed requestTag")
        if sequences and sorted(sequences) != list(range(1, len(sequences) + 1)):
            errors.append("server event sequence is not contiguous")
        for item in controller:
            if item.get("kind") != "wrongCorrelation":
                continue
            linked = [
                event for event in server_events
                if event.get("kind") == "wrongCorrelation"
                and event.get("sequence") == item.get("serverSequence")
                and event.get("requestTag") == item.get("requestTag")
                and event.get("echoedRequestTag") == item.get("echoedRequestTag")
                and event.get("runId") == trace.get("runId")
            ]
            if len(linked) != 1 or item.get("echoedRequestTag") == item.get("requestTag"):
                errors.append("controller wrongCorrelation does not bind one distinct echoed-tag server event")
        for item in controller:
            if item.get("kind") != "checkpointPublished":
                continue
            matching = [
                server_event for server_event in server_events
                if server_event.get("kind") == "checkpointPublished"
                and server_event.get("sequence") == item.get("serverSequence")
                and server_event.get("processInstanceId") == item.get("processInstanceId")
                and server_event.get("name") == item.get("name")
                and server_event.get("runId") == trace.get("runId")
            ]
            if len(matching) != 1:
                errors.append("controller checkpoint does not identify one server checkpoint event")

        expected_issuance = scenario.get("expectedIssuance")
        if expected_issuance is not None:
            actual_issuance = [
                {"requestId": event["requestId"], "slotId": event["slotId"]}
                for event in sorted(trace.get("events", []), key=lambda row: row.get("localSequence", 0))
                if event.get("kind") == "slotIssued"
            ]
            if actual_issuance != expected_issuance:
                errors.append("slot issuance history differs from the frozen expectedIssuance list")
        required_request_count = scenario.get("requiredServerRequestCount")
        if required_request_count is not None:
            held_count = sum(event.get("kind") == "requestHeld" for event in server_events)
            if held_count != required_request_count:
                errors.append("server requestHeld count differs from requiredServerRequestCount")
        expected_deliveries = scenario.get("expectedDeliveries")
        if expected_deliveries is not None:
            actual_deliveries = [
                {"slotId": event.get("slotId"), "outcome": event.get("outcome")}
                for event in trace.get("events", [])
                if event.get("kind") == "transportReceived"
            ]
            if actual_deliveries != expected_deliveries:
                errors.append("transport delivery history differs from the frozen expectedDeliveries list")
        replay_count = scenario.get("replayCount")
        if replay_count is not None:
            actual_replays = sum(
                isinstance(item, dict) and item.get("kind") == "replayRequested"
                for item in trace.get("controllerEvents", [])
            )
            if actual_replays != replay_count:
                errors.append("replay command count differs from the frozen replayCount")
        responses_per_request = scenario.get("serverResponsesPerRequest")
        if responses_per_request is not None:
            for held in (event for event in server_events if event.get("kind") == "requestHeld"):
                response_count = sum(
                    event.get("kind") == "responseWritten" and event.get("requestTag") == held.get("requestTag")
                    for event in server_events
                )
                if response_count != responses_per_request:
                    errors.append("server response count differs from serverResponsesPerRequest")

    if not isinstance(ui_observations, list):
        errors.append("UI/storage observations must be an array")
    else:
        seen_steps = set()
        for item in ui_observations:
            if not isinstance(item, dict) or item.get("kind") not in {"storageProbe", "renderedView"}:
                errors.append("external observation has invalid kind")
                continue
            if item["kind"] == "storageProbe":
                expected = {"kind", "stepId", "processInstanceId", "controllerSequence", "observation"}
                if "commandRef" in item:
                    expected.add("commandRef")
                if "effectRef" in item or "effectId" in item:
                    expected |= {"effectRef", "effectId"}
            else:
                expected = {"kind", "stepId", "processInstanceId", "revision", "eventRef", "phase", "account"}
            if set(item) != expected or not isinstance(item.get("stepId"), str) or not item["stepId"] or item.get("processInstanceId") not in process_ids:
                errors.append("external observation has incomplete identity/provenance")
                continue
            step_id = item["stepId"]
            if step_id in seen_steps:
                errors.append("external observation stepId is duplicated")
            seen_steps.add(step_id)
            if item["kind"] == "storageProbe":
                if type(item.get("controllerSequence")) is not int or not 1 <= item["controllerSequence"] <= MAX_I64 or not _store_ok(item.get("observation")):
                    errors.append("storage probe has invalid result/sequence")
                if "commandRef" in item and not _ref_ok(item["commandRef"], process_ids):
                    errors.append("storage probe has invalid command reference")
                if "effectRef" in item:
                    if "commandRef" in item or not _event_ref_ok(item.get("effectRef"), process_ids) or not isinstance(item.get("effectId"), str) or not item["effectId"]:
                        errors.append("detached-effect probe has invalid effect provenance")
                    else:
                        effect = event_by_ref.get((item["effectRef"]["processInstanceId"], item["effectRef"]["localSequence"]))
                        if not effect or effect.get("kind") != "detachedStoreMutation" or effect.get("effectId") != item["effectId"]:
                            errors.append("detached-effect probe does not identify its native mutation")
                elif "effectId" in item:
                    errors.append("detached-effect probe is missing its effectRef")
            else:
                if type(item.get("revision")) is not int or not 1 <= item["revision"] <= MAX_I64 or item.get("phase") not in {"Booting", "SignedOut", "SigningOut", "SignedIn", "Refreshing", "FaultLocked"} or item.get("account") not in {None, "A", "B"} or not _event_ref_ok(item.get("eventRef"), process_ids):
                    errors.append("rendered view observation is malformed")
                else:
                    ack = event_by_ref.get((item["eventRef"]["processInstanceId"], item["eventRef"]["localSequence"]))
                    if not ack or ack.get("kind") != "uiPublishAck" or ack.get("revision") != item["revision"] or ack.get("view", {}).get("phase") != item["phase"] or ack.get("view", {}).get("account") != item["account"]:
                        errors.append("rendered view is not bound to the acknowledged UI revision")
    return errors


def _selected_commands(scenario):
    launches = scenario.get("launches", [])
    return {row["ordinal"]: row["commands"] for row in launches}


def _apply_store_fault_contract(resolved, commands, fault):
    if fault is None:
        return resolved, None
    if fault not in {"replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"}:
        return None, "selected store fault has an unsupported kind"
    operation = "replace" if fault.startswith("replace") else "clear"
    applied = fault in {"replaceAfterBeforeVerify", "clearAfterBeforeVerify"}
    receipt_store = resolved.get("receiptStoreExpectation")
    expected_transport = resolved.get("expectedTransport")
    if operation == "clear":
        fault_command = next((name for name in commands if name.startswith("Logout")), None)
        if fault_command is None:
            fault_command = receipt_store.get("command") if isinstance(receipt_store, dict) else None
    else:
        fault_command = expected_transport.get("command") if isinstance(expected_transport, dict) else None
        if fault_command is None:
            fault_command = receipt_store.get("command") if isinstance(receipt_store, dict) else None
    if not isinstance(fault_command, str) or fault_command not in commands:
        return None, "selected store fault has no uniquely declared command"
    resolved["requiredStoreFault"] = {
        "command": fault_command,
        "operation": operation,
        "fault": fault,
        "mutationApplied": applied,
        "verification": "failed" if applied else "notAttempted",
    }
    return resolved, None


def _resolve_scenario_variant(scenario, trace, variant_id=None):
    if not isinstance(scenario, dict):
        return None, None, "scenario inventory row is not an object"
    unknown_scenario_fields = set(scenario) - SCENARIO_INVENTORY_FIELDS
    if unknown_scenario_fields:
        return None, None, f"unknown scenario inventory field(s): {sorted(unknown_scenario_fields)}"
    variants = scenario.get("variants")
    recorded = trace.get("variantId") if isinstance(trace, dict) else None
    if not variants:
        if variant_id is not None or recorded is not None:
            return None, None, "trace selects a variant that is not declared for this scenario"
        commands = [command for launch in scenario.get("launches", []) for command in launch.get("commands", [])]
        resolved, error = _apply_store_fault_contract(dict(scenario), commands, scenario.get("fault"))
        return resolved, None, error
    if not isinstance(variants, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in variants):
        return None, None, "scenario variant inventory is malformed"
    for row in variants:
        unknown_variant_fields = set(row) - VARIANT_INVENTORY_FIELDS
        if unknown_variant_fields:
            return None, None, f"unknown scenario variant field(s): {sorted(unknown_variant_fields)}"
    if not isinstance(recorded, str) or not recorded:
        return None, None, "variant trace must record its frozen variantId"
    if variant_id is not None and variant_id != recorded:
        return None, None, "requested variantId does not match the trace"
    matches = [row for row in variants if row["id"] == recorded]
    if len(matches) != 1:
        return None, None, "trace variantId is missing or ambiguous in the frozen inventory"
    variant = matches[0]
    commands = variant.get("commands")
    if not isinstance(commands, list) or not commands or any(not isinstance(command, str) or not command for command in commands):
        return None, None, "selected variant has no complete command inventory"
    resolved = {**scenario, **variant, "id": scenario["id"], "selectedVariantId": recorded}
    resolved["launches"] = [{"ordinal": 1, "commands": commands}]
    resolved["probeExpectations"] = {**scenario.get("probeExpectations", {}), **variant.get("probeExpectations", {})}
    resolved["probeExpectationInvariants"] = {
        **scenario.get("probeExpectationInvariants", {}), **variant.get("probeExpectationInvariants", {})
    }
    if variant.get("probeBeforeRetry") is not None and resolved.get("requiredProbes"):
        resolved["probeExpectations"][resolved["requiredProbes"][0]] = variant["probeBeforeRetry"]
    resolved["renderExpectations"] = {**scenario.get("renderExpectations", {}), **variant.get("renderExpectations", {})}
    resolved["renderExpectationInvariants"] = {
        **scenario.get("renderExpectationInvariants", {}), **variant.get("renderExpectationInvariants", {})
    }
    expected_final = variant.get("expectedFinal")
    if expected_final is None and "expectedStore" in variant and "expectedView" in variant:
        expected_final = {"store": variant["expectedStore"], "view": variant["expectedView"]}
    if expected_final is not None:
        resolved["expectedFinal"] = expected_final
        if resolved.get("requiredProbes"):
            resolved["probeExpectations"][resolved["requiredProbes"][-1]] = expected_final["store"]
        if resolved.get("requiredRenderedViews"):
            resolved["renderExpectations"][resolved["requiredRenderedViews"][-1]] = expected_final["view"]
    resolved, error = _apply_store_fault_contract(resolved, commands, resolved.get("fault"))
    return resolved, variant, error


def _scenario_inventory_errors(scenario):
    errors = []
    unknown_fields = set(scenario) - SCENARIO_INVENTORY_FIELDS
    if unknown_fields:
        errors.append(f"unknown scenario inventory field(s): {sorted(unknown_fields)}")
    if scenario.get("cancelMode") != "disabled":
        errors.append("cancelMode must explicitly freeze physical transport cancellation as disabled")
    declared_commands = [
        command
        for launch in scenario.get("launches", [])
        if isinstance(launch, dict) and isinstance(launch.get("commands"), list)
        for command in launch["commands"]
    ]
    required_probes = scenario.get("requiredProbes", [])
    required_views = scenario.get("requiredRenderedViews", [])
    if not isinstance(required_probes, list) or any(not isinstance(step, str) or not step for step in required_probes) or len(set(required_probes)) != len(required_probes):
        errors.append("requiredProbes must be a unique list of nonempty step IDs")
        required_probes = []
    if not isinstance(required_views, list) or any(not isinstance(step, str) or not step for step in required_views) or len(set(required_views)) != len(required_views):
        errors.append("requiredRenderedViews must be a unique list of nonempty step IDs")
        required_views = []
    probe_expectations = scenario.get("probeExpectations", {})
    render_expectations = scenario.get("renderExpectations", {})
    if not isinstance(probe_expectations, dict) or set(probe_expectations) != set(required_probes):
        errors.append("every required storage probe must have exactly one frozen expected value")
    elif any(not _store_ok(value) for value in probe_expectations.values()):
        errors.append("a frozen storage probe expectation has an invalid store value")
    if not isinstance(render_expectations, dict) or set(render_expectations) != set(required_views):
        errors.append("every required rendered view must have exactly one frozen expected value")
    elif any(
        not isinstance(value, dict) or set(value) != {"phase", "account"}
        or value.get("phase") not in {"Booting", "SignedOut", "SigningOut", "SignedIn", "Refreshing", "FaultLocked"}
        or value.get("account") not in {None, "A", "B"}
        for value in render_expectations.values()
    ):
        errors.append("a frozen rendered view expectation has invalid fields")
    probe_invariants = scenario.get("probeExpectationInvariants", {})
    render_invariants = scenario.get("renderExpectationInvariants", {})
    valid_invariants = {"I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9"}
    if (not isinstance(probe_invariants, dict) or set(probe_invariants) != set(required_probes)
            or any(value not in valid_invariants for value in probe_invariants.values())):
        errors.append("every required storage probe must declare one frozen mismatch invariant")
    if (not isinstance(render_invariants, dict) or set(render_invariants) != set(required_views)
            or any(value not in valid_invariants for value in render_invariants.values())):
        errors.append("every required rendered view must declare one frozen mismatch invariant")
    final = scenario.get("expectedFinal")
    if not isinstance(final, dict) or set(final) != {"store", "view"} or not _store_ok(final.get("store")) or not isinstance(final.get("view"), dict) or set(final["view"]) != {"phase", "account"}:
        errors.append("scenario must declare a valid expectedFinal store and view")
    elif required_probes and probe_expectations.get(required_probes[-1]) != final["store"]:
        errors.append("final probe expectation differs from expectedFinal store")
    elif required_views and render_expectations.get(required_views[-1]) != final["view"]:
        errors.append("final rendered view expectation differs from expectedFinal view")
    receipt_expectations = scenario.get("receiptExpectations", [])
    if not isinstance(receipt_expectations, list) or any(
        not isinstance(item, dict) or set(item) != {"command", "status", "invariant"}
        or not isinstance(item.get("command"), str) or not item["command"]
        or item.get("status") not in {"Completed", "RejectedBusy", "IgnoredStale", "IgnoredForeign", "RejectedExhausted", "FaultLocked"}
        or item.get("invariant") not in {"I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9"}
        for item in receipt_expectations
    ):
        errors.append("receiptExpectations must identify a command, status and invariant")
    expected_transport = scenario.get("expectedTransport")
    if expected_transport is not None and (
        not isinstance(expected_transport, dict) or set(expected_transport) != {"command", "outcome", "failureCode", "invariant"}
        or not isinstance(expected_transport.get("command"), str) or not expected_transport["command"]
        or expected_transport.get("outcome") not in {"success", "failure"}
        or (expected_transport["outcome"] == "success" and expected_transport.get("failureCode") is not None)
        or (expected_transport["outcome"] == "failure" and expected_transport.get("failureCode") not in {"rejected", "server", "malformed", "disconnected", "wrongCorrelation", "timeout"})
        or expected_transport.get("invariant") not in {"I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9"}
    ):
        errors.append("expectedTransport must declare one frozen outcome, failure code and invariant")
    elif expected_transport is not None and expected_transport.get("command") not in declared_commands:
        errors.append("expectedTransport command must be present in the frozen command inventory")
    if "CancelRefresh" in declared_commands and scenario.get("cancelMode") == "disabled" and expected_transport is None:
        errors.append("CancelRefresh with physical cancellation disabled must declare its expected transport outcome")
    expected_issuance = scenario.get("expectedIssuance")
    if expected_issuance is not None and (
        not isinstance(expected_issuance, list)
        or any(
            not isinstance(item, dict) or set(item) != {"requestId", "slotId"}
            or type(item.get("requestId")) is not int or not 1 <= item["requestId"] <= MAX_I64
            or not isinstance(item.get("slotId"), str) or not item["slotId"]
            for item in expected_issuance
        )
        or len({item["requestId"] for item in expected_issuance if isinstance(item, dict) and type(item.get("requestId")) is int}) != len(expected_issuance)
        or len({item["slotId"] for item in expected_issuance if isinstance(item, dict) and isinstance(item.get("slotId"), str)}) != len(expected_issuance)
    ):
        errors.append("expectedIssuance must identify unique request IDs and slot IDs")
    required_request_count = scenario.get("requiredServerRequestCount")
    if required_request_count is not None and (
        type(required_request_count) is not int or not 0 <= required_request_count <= MAX_I64
    ):
        errors.append("requiredServerRequestCount must be a nonnegative signed64 integer")
    elif expected_issuance is not None and isinstance(expected_issuance, list) and required_request_count != len(expected_issuance):
        errors.append("requiredServerRequestCount must equal the exact expectedIssuance count")
    expected_deliveries = scenario.get("expectedDeliveries")
    if expected_deliveries is not None and (
        not isinstance(expected_deliveries, list)
        or any(
            not isinstance(item, dict) or set(item) != {"slotId", "outcome"}
            or not isinstance(item.get("slotId"), str) or not item["slotId"]
            or item.get("outcome") not in {"success", "failure"}
            for item in expected_deliveries
        )
    ):
        errors.append("expectedDeliveries must name a slot and transport outcome")
    elif expected_deliveries is not None and expected_issuance is not None:
        issued_slots = {item["slotId"] for item in expected_issuance}
        if any(item["slotId"] not in issued_slots for item in expected_deliveries):
            errors.append("expectedDeliveries must refer to an expected issued slot")
    for key, minimum in (("replayCount", 0), ("serverResponsesPerRequest", 1)):
        value = scenario.get(key)
        if value is not None and (type(value) is not int or not minimum <= value <= MAX_I64):
            errors.append(f"{key} must be a signed64 integer at least {minimum}")
    fault = scenario.get("fault")
    if fault is not None and fault not in {"replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"}:
        errors.append("scenario fault kind is outside the frozen store-fault set")
    fault_observation = scenario.get("faultObservation")
    if fault_observation is not None and not _store_ok(fault_observation):
        errors.append("faultObservation must be one redacted store observation")
    receipt_store = scenario.get("receiptStoreExpectation")
    if receipt_store is not None and (
        not isinstance(receipt_store, dict) or set(receipt_store) != {"command", "store"}
        or not isinstance(receipt_store.get("command"), str) or not receipt_store["command"]
        or not _store_ok(receipt_store.get("store"))
    ):
        errors.append("receiptStoreExpectation must distinguish one command snapshot from the physical probe")
    required_fault = scenario.get("requiredStoreFault")
    if required_fault is not None and (
        not isinstance(required_fault, dict)
        or set(required_fault) != {"command", "operation", "fault", "mutationApplied", "verification"}
        or not isinstance(required_fault.get("command"), str) or not required_fault["command"]
        or required_fault.get("operation") not in {"replace", "clear"}
        or required_fault.get("fault") not in {"replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"}
        or type(required_fault.get("mutationApplied")) is not bool
        or required_fault.get("verification") not in {"failed", "notAttempted"}
        or (required_fault["mutationApplied"] != (required_fault["verification"] == "failed"))
        or required_fault.get("operation") != ("replace" if str(required_fault.get("fault", "")).startswith("replace") else "clear")
        or required_fault.get("mutationApplied") != (required_fault.get("fault") in {"replaceAfterBeforeVerify", "clearAfterBeforeVerify"})
    ):
        errors.append("requiredStoreFault must identify one exact wrapper fault observation")
    return errors


def scenario_inventory_errors(scenario):
    """Validate a complete base scenario and every declared variant at freeze time."""
    if not isinstance(scenario, dict):
        return ["scenario inventory row must be an object"]
    variants = scenario.get("variants")
    if variants is None:
        return _scenario_inventory_errors(scenario)
    if not isinstance(variants, list) or not variants:
        return ["variants must be a nonempty array when present"]
    errors = []
    variant_ids = []
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(variant.get("id"), str):
            errors.append("variant rows must have a frozen string id")
            continue
        variant_ids.append(variant["id"])
        unknown = set(variant) - VARIANT_INVENTORY_FIELDS
        if unknown:
            errors.append(f"unknown scenario variant field(s): {sorted(unknown)}")
            continue
        resolved, _, selector_error = _resolve_scenario_variant(scenario, {"variantId": variant["id"]})
        if selector_error:
            errors.append(selector_error)
        else:
            errors.extend(_scenario_inventory_errors(resolved))
    if len(variant_ids) != len(set(variant_ids)):
        errors.append("variant IDs must be unique")
    return list(dict.fromkeys(errors))


def control_inventory_errors(control):
    if not isinstance(control, dict):
        return ["control inventory row must be an object"]
    errors = []
    unknown = set(control) - CONTROL_INVENTORY_FIELDS
    if unknown:
        errors.append(f"unknown control inventory field(s): {sorted(unknown)}")
    if control.get("cancelMode") != "disabled":
        errors.append("control cancelMode must freeze physical transport cancellation as disabled")
    if not isinstance(control.get("id"), str) or not control["id"]:
        errors.append("control ID must be nonempty")
    witnesses = control.get("witnessInvariants")
    if not isinstance(witnesses, list) or not witnesses or any(value not in {f"I{i}" for i in range(1, 10)} for value in witnesses) or len(witnesses) != len(set(witnesses)):
        errors.append("control witnessInvariants must be a unique nonempty invariant list")
    effects = control.get("effects", [])
    actions = control.get("controlActions", [])
    if not isinstance(effects, list) or not isinstance(actions, list):
        errors.append("control effects and actions must be arrays")
        return errors
    effect_ids = [row.get("effectId") for row in effects if isinstance(row, dict)]
    awaited_ids = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or not isinstance(action.get("action"), str):
            errors.append("control action must be an object with an action name")
            continue
        if action["action"] == "awaitDetachedEffect":
            if set(action) != {"action", "effectId"} or not isinstance(action.get("effectId"), str) or not action["effectId"]:
                errors.append("awaitDetachedEffect requires exactly one frozen effectId")
            else:
                awaited_ids.append(action["effectId"])
                if action["effectId"] not in effect_ids:
                    errors.append("awaitDetachedEffect names an undeclared detached effect")
                release_indexes = [
                    action_index for action_index, candidate in enumerate(actions[:index])
                    if isinstance(candidate, dict) and candidate.get("action") == "release"
                    and candidate.get("point") == control.get("hookReleasePoint")
                ]
                if not release_indexes:
                    errors.append("awaitDetachedEffect must follow the frozen effect hook release")
        elif action["action"] == "injectStoreFault":
            fault = action.get("fault")
            command = action.get("command")
            known_faults = {"replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify"}
            if set(action) != {"action", "fault", "command"} or fault not in known_faults or not isinstance(command, str):
                errors.append("injectStoreFault requires exactly one frozen fault and target command")
                continue
            if command not in control.get("commands", []):
                errors.append("injectStoreFault target command is not in the frozen control sequence")
            elif fault.startswith("replace") and not command.startswith("Deliver("):
                errors.append("fault target command must be a Deliver command for a replace fault")
            elif fault.startswith("clear") and _native_command_name(command) != "Logout":
                errors.append("fault target command must be Logout for a clear fault")
    if len(awaited_ids) != len(set(awaited_ids)) or set(awaited_ids) != set(effect_ids):
        errors.append("each frozen detached effect requires exactly one awaitDetachedEffect action")
    if awaited_ids and "detachedEffectAwaited" not in control.get("requiredControllerEvents", []):
        errors.append("detached-effect controls must require the host await acknowledgement")
    return errors


def _required_observations(scenario, trace, server_events, ui_observations):
    missing = []
    commands_by_ordinal = _selected_commands(scenario)
    process_by_ordinal = {row["launchOrdinal"]: row["processInstanceId"] for row in trace["processInstances"]}
    inventory_by_pid = defaultdict(list)
    for item in trace["commandInventory"]:
        inventory_by_pid[item["commandRef"]["processInstanceId"]].append(item["name"])
    receipts = {
        (event["commandRef"]["processInstanceId"], event["commandRef"]["id"])
        for event in trace["events"]
        if event["kind"] == "commandReceipt"
    }
    for item in trace["commandInventory"]:
        ref = item["commandRef"]
        if (ref["processInstanceId"], ref["id"]) not in receipts:
            missing.append(f"receipt for command {item['name']} is missing")
    required_fault = scenario.get("requiredStoreFault")
    if required_fault is not None:
        fault_commands = [row for row in trace["commandInventory"] if _native_command_matches(row.get("name"), required_fault["command"])]
        matching_faults = []
        if len(fault_commands) == 1:
            command_ref = fault_commands[0]["commandRef"]
            matching_faults = [
                event for event in trace["events"]
                if event.get("kind") == "storeFault"
                and event.get("commandRef") == command_ref
                and event.get("operation") == required_fault["operation"]
                and event.get("fault") == required_fault["fault"]
                and event.get("mutationApplied") is required_fault["mutationApplied"]
                and event.get("verification") == required_fault["verification"]
            ]
        if len(matching_faults) != 1:
            missing.append(
                f"required store fault {required_fault['fault']} on {required_fault['command']} is missing or inconsistent"
            )
    for mutation in (event for event in trace["events"] if event.get("kind") == "storeMutation"):
        readback = any(
            event.get("kind") == "storeReadback" and event.get("commandRef") == mutation.get("commandRef")
            and event.get("operation") == mutation.get("operation") and event.get("observation") == mutation.get("after")
            for event in trace["events"]
        )
        documented_failure = any(
            event.get("kind") == "storeFault" and event.get("commandRef") == mutation.get("commandRef")
            and event.get("operation") == mutation.get("operation") and event.get("mutationApplied") is True
            and event.get("verification") == "failed"
            for event in trace["events"]
        )
        if not readback and not documented_failure:
            missing.append(f"store mutation readback or explicit verification failure is missing for {mutation.get('commandRef')}")
    for process in trace["processInstances"]:
        pid = process["processInstanceId"]
        bootstrap_rows = [
            row for row in trace["commandInventory"]
            if row["commandRef"]["processInstanceId"] == pid and row["name"] == "Bootstrap"
        ]
        if len(bootstrap_rows) != 1:
            missing.append(f"one Bootstrap command is required in process {pid}")
            continue
        bootstrap_ref = bootstrap_rows[0]["commandRef"]
        mutations = [
            event for event in trace["events"]
            if event.get("kind") == "storeMutation" and event.get("commandRef") == bootstrap_ref and event.get("cause") == "Bootstrap" and event.get("operation") == "clear"
        ]
        readbacks = [
            event for event in trace["events"]
            if event.get("kind") == "storeReadback" and event.get("commandRef") == bootstrap_ref and event.get("operation") == "clear"
        ]
        if len(mutations) != 1 or len(readbacks) != 1 or readbacks[0]["localSequence"] <= mutations[0]["localSequence"]:
            missing.append(f"Bootstrap clear and verified readback are incomplete in process {pid}")
        if process["launchOrdinal"] > 1:
            before_clear = next((
                row["stepId"] for row in ui_observations
                if row.get("kind") == "storageProbe" and row.get("processInstanceId") == pid
                and "before-bootstrap-clear" in row.get("stepId", "")
            ), None)
            if before_clear is None:
                missing.append(f"pre-clear independent Bootstrap probe is missing in process {pid}")
    event_index = {(event["processInstanceId"], event["localSequence"]): event for event in trace["events"]}
    for ordinal, expected in commands_by_ordinal.items():
        pid = process_by_ordinal.get(ordinal)
        if pid is None:
            missing.append(f"launch {ordinal} is missing")
            continue
        actual = inventory_by_pid.get(pid, [])
        app11_permuted_queue = scenario.get("id") == "APP-11" and sorted(actual) == sorted(expected[: len(actual)])
        if actual != expected[: len(actual)] and not app11_permuted_queue:
            continue  # Structural validation reports a non-prefix inventory.
        for name in expected[len(actual):]:
            missing.append(f"command {name} is missing in launch {ordinal}")
        event_kinds = [event.get("kind") for event in trace["events"] if event.get("processInstanceId") == pid]
        if event_kinds.count("processStart") != 1:
            missing.append(f"process start marker is missing in launch {ordinal}")
        if event_kinds.count("processEnd") != 1:
            missing.append(f"process end marker is missing in launch {ordinal}")
        end_acks = [
            event for event in trace["controllerEvents"]
            if event.get("kind") == "processEndAcknowledged" and event.get("processInstanceId") == pid
        ]
        if not end_acks:
            missing.append(f"process end acknowledgement is missing in launch {ordinal}")
        elif len(end_acks) != 1:
            missing.append(f"process end acknowledgement is duplicated in launch {ordinal}")
    for kind in scenario.get("requiredServerEvents", []):
        if not any(event.get("kind") == kind for event in server_events):
            missing.append(f"server event {kind} is missing")
    controller_kinds = [event.get("kind") for event in trace["controllerEvents"]]
    for kind in scenario.get("requiredControllerEvents", []):
        if kind not in controller_kinds:
            missing.append(f"controller event {kind} is missing")
    for command_name, step_id in scenario.get("receiptProbeOrder", []):
        command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], command_name)), None)
        if command is None:
            missing.append(f"controller ordering command {command_name} is missing")
            continue
        if not any(event.get("kind") == "receiptObserved" and event.get("commandRef") == command["commandRef"] for event in trace["controllerEvents"]):
            missing.append(f"controller receipt for {command_name} is missing")
        if not any(event.get("kind") == "probeCaptured" and event.get("stepId") == step_id for event in trace["controllerEvents"]):
            missing.append(f"controller probe acknowledgement for {step_id} is missing")
    if scenario.get("id") == "APP-11":
        point = scenario.get("barrier")
        for phase in ("armed", "arrived", "released"):
            if not any(event.get("kind") == "hookEvent" and event.get("point") == point and event.get("phase") == phase for event in trace["events"]):
                missing.append(f"APP-11 hook {point}/{phase} event is missing")
        for name in scenario.get("queuedOrder", []):
            if not any(event.get("kind") == "commandEnqueued" and event.get("name") == name for event in trace["events"]):
                missing.append(f"APP-11 queued command {name} was not observed")
    hook_release_command = scenario.get("hookReleaseAfterCommand")
    if hook_release_command:
        command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], hook_release_command)), None)
        if command is None or not any(event.get("kind") == "receiptObserved" and event.get("commandRef") == command["commandRef"] for event in trace["controllerEvents"]):
            missing.append(f"controller receipt for hook-release command {hook_release_command} is missing")
        if not any(event.get("kind") == "hookReleased" and event.get("point") == scenario.get("hookReleasePoint") for event in trace["controllerEvents"]):
            missing.append(f"direct release of hook {scenario.get('hookReleasePoint')} is missing")
        for step_id in scenario.get("hookReleaseAfterProbes", []):
            if not any(event.get("kind") == "probeCaptured" and event.get("stepId") == step_id for event in trace["controllerEvents"]):
                missing.append(f"controller probe acknowledgement for {step_id} is missing")
    observations_by_step = {item["stepId"]: item for item in ui_observations}
    for step_id in scenario.get("requiredProbes", []):
        item = observations_by_step.get(step_id)
        if item is None or item.get("kind") != "storageProbe":
            missing.append(f"storage probe {step_id} is missing")
            continue
        expected_store = scenario.get("probeExpectations", {}).get(step_id)
        if item["observation"].get("kind") == "Unknown" and not (isinstance(expected_store, dict) and expected_store.get("kind") == "Unknown"):
            missing.append(f"storage probe {step_id} is Unknown, not a verified state")
    for step_id in scenario.get("requiredRenderedViews", []):
        item = observations_by_step.get(step_id)
        if item is None or item.get("kind") != "renderedView":
            missing.append(f"rendered view {step_id} is missing")
    required_delivery = scenario.get("requiredDelivery")
    if required_delivery:
        if not any(event.get("kind") == "transportReceived" and event.get("slotId") == required_delivery.get("slotId") and event.get("outcome") == required_delivery.get("outcome") for event in trace["events"]):
            missing.append("required transport response was not observed")
        if not any(event.get("kind") == "completionProcessed" and event.get("slotId") == required_delivery.get("slotId") for event in trace["events"]):
            missing.append("required completion was not processed")
    if scenario.get("id") == "APP-11":
        point = scenario.get("barrier")
        for phase, controller_kind in (("arrived", "hookArrived"), ("released", "hookReleased")):
            native = next((event for event in trace["events"] if event.get("kind") == "hookEvent" and event.get("point") == point and event.get("phase") == phase), None)
            linked = next((event for event in trace["controllerEvents"] if event.get("kind") == controller_kind and event.get("point") == point), None)
            if native is None or linked is None or linked.get("eventRef") != {"processInstanceId": native["processInstanceId"], "localSequence": native["localSequence"]}:
                missing.append(f"APP-11 {controller_kind} acknowledgement is missing or unbound")
        deliver = next((row for row in trace["commandInventory"] if row["name"] == "Deliver(current,success)"), None)
        delivery_receipt = next((event for event in trace["events"] if event.get("kind") == "commandReceipt" and deliver and event.get("commandRef") == deliver["commandRef"]), None)
        if delivery_receipt is None:
            missing.append("APP-11 paused delivery terminal receipt is missing")
    for path in trace.get("artifactPaths", []):
        if not any(path.startswith(scenario["id"] + f"/p{ordinal}/") for ordinal in commands_by_ordinal):
            missing.append(f"artifact path is outside a declared process namespace: {path}")
    for ref, event in event_index.items():
        if event.get("kind") == "commandEnqueued" and not any(row["commandRef"] == event.get("commandRef") for row in trace["commandInventory"]):
            missing.append(f"enqueued command has no inventory entry at {ref[0]}:{ref[1]}")
    return list(dict.fromkeys(missing))


def _controller_barrier_issues(scenario, trace, observations):
    issues = []
    controller = trace["controllerEvents"]
    by_kind = defaultdict(list)
    for event in controller:
        by_kind[event["kind"]].append(event)
    command_names = {(row["commandRef"]["processInstanceId"], row["commandRef"]["id"]): row["name"] for row in trace["commandInventory"]}
    receipts_by_ref = {(event["commandRef"]["processInstanceId"], event["commandRef"]["id"]): event for event in trace["events"] if event["kind"] == "commandReceipt"}
    for item in by_kind["receiptObserved"]:
        key = (item["commandRef"]["processInstanceId"], item["commandRef"]["id"])
        native = receipts_by_ref.get(key)
        if not native or native["localSequence"] != item["eventRef"]["localSequence"]:
            issues.append(_history_error("controller observed a receipt that is not in the native trace", item, item.get("commandRef")))
    for item in by_kind["probeCaptured"]:
        observation = next((row for row in observations if row["stepId"] == item["stepId"]), None)
        if observation is not None and observation.get("controllerSequence") != item["sequence"]:
            issues.append(_history_error("controller probe acknowledgement does not match the independent observation", item))

    for process in trace["processInstances"]:
        process_id = process["processInstanceId"]
        end_rows = [
            event for event in trace["events"]
            if event.get("processInstanceId") == process_id and event.get("kind") == "processEnd"
        ]
        acknowledgements = [
            item for item in by_kind["processEndAcknowledged"]
            if item.get("processInstanceId") == process_id
        ]
        if len(end_rows) != 1 or len(acknowledgements) != 1:
            continue  # Completeness reports missing/duplicate end evidence as INCONCLUSIVE.
        end_row, acknowledgement = end_rows[0], acknowledgements[0]
        expected_ref = {"processInstanceId": process_id, "localSequence": end_row["localSequence"]}
        if acknowledgement.get("eventRef") != expected_ref:
            issues.append(_history_error("processEnd acknowledgement does not bind the actual processEnd row", acknowledgement))
        required_before_end = {
            "receiptObserved", "probeCaptured", "hookReleased", "detachedEffectAwaited",
            "replayRequested",
        }
        preceding = [
            item for item in controller
            if item.get("processInstanceId") == process_id and item.get("kind") in required_before_end
        ]
        if any(item["sequence"] >= acknowledgement["sequence"] for item in preceding):
            issues.append(_history_error("processEnd acknowledgement precedes required controller observations", acknowledgement))
        teardown = [
            item for item in controller
            if item.get("processInstanceId") == process_id and item.get("kind") in {"forceStopped", "terminated"}
        ]
        if any(item["sequence"] <= acknowledgement["sequence"] for item in teardown):
            issues.append(_history_error("processEnd acknowledgement follows controller teardown", acknowledgement))

    target_name = scenario.get("releaseAfterCommand")
    if target_name:
        target_ref = next((row["commandRef"] for row in trace["commandInventory"] if _native_command_matches(row["name"], target_name)), None)
        receipt_observed = next((item for item in by_kind["receiptObserved"] if item.get("commandRef") == target_ref), None)
        release = next(iter(by_kind["releaseRequested"]), None)
        if target_ref and not receipt_observed:
            return issues
        if release and receipt_observed and release["sequence"] <= receipt_observed["sequence"]:
            issues.append(_history_error("response release was requested before its required app receipt", release, target_ref))
        expected_probe_steps = scenario.get("releaseAfterProbes", [])
        for step_id in expected_probe_steps:
            probe = next((item for item in by_kind["probeCaptured"] if item.get("stepId") == step_id), None)
            if release and probe and release["sequence"] <= probe["sequence"]:
                issues.append(_history_error("response release was requested before the required independent probe", release, target_ref))
    receipt_probe_order = scenario.get("receiptProbeOrder", [])
    for index, (command_name, step_id) in enumerate(receipt_probe_order):
        command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], command_name)), None)
        receipt = next((item for item in by_kind["receiptObserved"] if command and item.get("commandRef") == command["commandRef"]), None)
        probe = next((item for item in by_kind["probeCaptured"] if item.get("stepId") == step_id), None)
        next_name = receipt_probe_order[index + 1][0] if index + 1 < len(receipt_probe_order) else None
        next_command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], next_name)), None)
        next_receipt = next((item for item in by_kind["receiptObserved"] if next_command and item.get("commandRef") == next_command["commandRef"]), None)
        if receipt and probe and (receipt["sequence"] >= probe["sequence"] or (next_receipt and probe["sequence"] >= next_receipt["sequence"])):
            issues.append(_history_error("receipt and independent probe order is reversed", probe, command["commandRef"] if command else None))
    hook_target_name = scenario.get("hookReleaseAfterCommand")
    if hook_target_name:
        target = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], hook_target_name)), None)
        receipt = next((item for item in by_kind["receiptObserved"] if target and item.get("commandRef") == target["commandRef"]), None)
        point = scenario.get("hookReleasePoint")
        hook_release = next((item for item in by_kind["hookReleased"] if item.get("point") == point), None)
        probes = [next((item for item in by_kind["probeCaptured"] if item.get("stepId") == step_id), None) for step_id in scenario.get("hookReleaseAfterProbes", [])]
        if not receipt or not hook_release or any(item is None for item in probes):
            return issues
        if hook_release["sequence"] <= receipt["sequence"] or any(item["sequence"] >= hook_release["sequence"] for item in probes):
            issues.append(_history_error("direct hook release preceded its receipt or independent probes", hook_release, target.get("commandRef")))
        if hook_release.get("releaseChannel") != "DebugScenarioControl":
            issues.append(_history_error("hook release did not use the independent DebugScenarioControl plane", hook_release, target.get("commandRef")))
    # A response cannot be released before the controller has observed its acceptance.
    for kind_before, kind_after in (("releaseRequested", "releaseAccepted"), ("releaseAccepted", "responseWritten"), ("responseWritten", "completionProcessedObserved")):
        left, right = by_kind[kind_before], by_kind[kind_after]
        if left and right and min(x["sequence"] for x in right) <= min(x["sequence"] for x in left):
            issues.append(_history_error(f"controller barrier order {kind_before} -> {kind_after} is reversed", right[0]))
    launches = scenario.get("launches", [])
    if len(launches) == 2 and [row.get("ordinal") for row in launches] == [1, 2]:
        process_by_ordinal = {row["launchOrdinal"]: row["processInstanceId"] for row in trace["processInstances"]}
        p1, p2 = process_by_ordinal.get(1), process_by_ordinal.get(2)
        force_stop = next((item for item in by_kind["forceStopped"] if item.get("processInstanceId") == p1), None)
        terminated = next((item for item in by_kind["terminated"] if item.get("processInstanceId") == p1), None)
        p2_launch = next((item for item in by_kind["launch"] if item.get("processInstanceId") == p2), None)
        hook_arrival = next((item for item in by_kind["bootstrapHookArrived"] if item.get("processInstanceId") == p2 and item.get("point") == "beforeBootstrapClear"), None)
        before_step = next((step for step in scenario.get("requiredProbes", []) if "before-bootstrap-clear" in step), None)
        pre_probe = next((item for item in by_kind["probeCaptured"] if item.get("processInstanceId") == p2 and item.get("stepId") == before_step), None)
        checkpoint = next((item for item in by_kind["checkpointPublished"] if item.get("processInstanceId") == p2 and item.get("name") == "bootstrapStoreProbed"), None)
        release = next((item for item in by_kind["hookReleased"] if item.get("processInstanceId") == p2 and item.get("point") == "beforeBootstrapClear"), None)
        bootstrap = next((row for row in trace["commandInventory"] if row["commandRef"]["processInstanceId"] == p2 and row["name"] == "Bootstrap"), None)
        bootstrap_mutation = next((event for event in trace["events"] if event.get("kind") == "storeMutation" and bootstrap and event.get("commandRef") == bootstrap["commandRef"] and event.get("cause") == "Bootstrap"), None)
        bootstrap_receipt = next((item for item in by_kind["receiptObserved"] if bootstrap and item.get("commandRef") == bootstrap["commandRef"]), None)
        if not force_stop or not terminated or not p2_launch or not hook_arrival or not pre_probe or not checkpoint or not release:
            # _required_observations reports missing evidence as INCONCLUSIVE.
            return issues
        if force_stop.get("pidAbsent") is not True or not (force_stop["sequence"] < terminated["sequence"] < p2_launch["sequence"]):
            issues.append(_history_error("APP-12 requires force-stop, confirmed PID absence, then p2 launch", force_stop))
        if hook_arrival.get("authMailboxPaused") is not True or not (hook_arrival["sequence"] < pre_probe["sequence"] < checkpoint["sequence"] < release["sequence"]):
            issues.append(_history_error("APP-12 bootstrap hook/probe/checkpoint/release order is invalid", hook_arrival))
        if release.get("releaseChannel") != "DebugScenarioControl" or release.get("authMailboxPaused") is not True or release.get("bootstrapReceiptObserved") is not False:
            issues.append(_history_error("APP-12 bootstrap release must bypass the paused auth mailbox", release))
        native_release = _native_released_hook_event(trace, release)
        if bootstrap_mutation and (
            native_release is None
            or bootstrap_mutation.get("releaseActionId") != native_release.get("actionId")
        ):
            issues.append(_history_error("APP-12 Bootstrap clear is not tied to its native released hook action", bootstrap_mutation))
        if bootstrap_receipt and bootstrap_receipt["sequence"] <= release["sequence"]:
            native_receipt = receipts_by_ref.get((bootstrap["commandRef"]["processInstanceId"], bootstrap["commandRef"]["id"])) if bootstrap else None
            if native_receipt is not None:
                issues.append(_issue(
                    "I9",
                    bootstrap["commandRef"],
                    native_receipt,
                    "Bootstrap receipt follows the independent control release",
                    {
                        "receiptObservedControllerSequence": bootstrap_receipt["sequence"],
                        "hookReleasedControllerSequence": release["sequence"],
                    },
                ))
    return issues


def _managed_event_for_command(name):
    if name.startswith("Login("):
        return {"event": "LoginSucceeded"}
    if name == "Expire":
        return {"event": "TokenExpired"}
    if name.startswith("Logout"):
        return {"event": "Logout"}
    if name == "CancelRefresh":
        return {"event": "Logout"}
    if name.startswith("Deliver("):
        outcome = name.rsplit(",", 1)[-1].removesuffix(")")
        if outcome in {"success", "replay"}:
            return {"event": "RefreshSucceeded"}
        if outcome in {"failure", "serverError", "malformed", "disconnected", "correlationMismatch"}:
            return {"event": "RefreshFailed"}
    return None


def _projection(view):
    return tuple(view.get(key) for key in ("phase", "account", "credentialVersion", "pendingRequestId"))


def _evaluate(contract, scenario, trace, server_events, ui_observations):
    issues = []
    missing = []
    event_list = trace["events"]
    event_by_ref = {(event["processInstanceId"], event["localSequence"]): event for event in event_list}
    inventory = {(item["commandRef"]["processInstanceId"], item["commandRef"]["id"]): item["name"] for item in trace["commandInventory"]}
    managed_by_command = {(event["commandRef"]["processInstanceId"], event["commandRef"]["id"]): event for event in event_list if event["kind"] == "managedReduced"}
    slots = {}
    active_slot = {}
    last_store = {}
    last_verified = {}
    last_projection = {}
    last_revision = {}
    logout_active = defaultdict(bool)
    current_login = {}
    logout_origin_accounts = {}
    stale_commands = {}
    slot_delivery_count = defaultdict(int)
    slot_commit_count = defaultdict(int)
    store_mutations = defaultdict(list)
    last_managed = {}
    open_commands = defaultdict(list)
    server_tags = {item.get("requestTag") for item in server_events if item.get("kind") in {"requestHeld", "releaseAccepted", "responseWritten", "disconnected", "http500", "malformed", "wrongCorrelation"}}
    server_held_tags = {item.get("requestTag") for item in server_events if item.get("kind") == "requestHeld"}
    observation_by_step = {item["stepId"]: item for item in ui_observations}

    def _probe_receipt(probe):
        command_ref = probe.get("commandRef") if isinstance(probe, dict) else None
        if isinstance(command_ref, dict):
            return next((event for event in reversed(event_list)
                         if event.get("kind") == "commandReceipt" and event.get("commandRef") == command_ref), None)
        effect_ref = probe.get("effectRef") if isinstance(probe, dict) else None
        if isinstance(effect_ref, dict):
            event = event_by_ref.get((effect_ref.get("processInstanceId"), effect_ref.get("localSequence")))
            if event and event.get("kind") == "detachedStoreMutation" and event.get("effectId") == probe.get("effectId"):
                return event
        return None

    try:
        spec = json.loads((ROOT / "contract" / "specification.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], [], f"managed oracle cannot be loaded: {exc}"

    # Completeness is checked before semantics: a broken/missing mutant trace is never RED.
    missing.extend(_required_observations(scenario, trace, server_events, ui_observations))
    for expected in scenario.get("receiptExpectations", []):
        commands = [row for row in trace["commandInventory"] if _native_command_matches(row["name"], expected["command"])]
        if len(commands) != 1:
            missing.append(f"receipt expectation command {expected['command']} is missing or ambiguous")
            continue
        ref = commands[0]["commandRef"]
        if not any(event.get("kind") == "commandReceipt" and event.get("commandRef") == ref for event in event_list):
            missing.append(f"expected receipt for {expected['command']} is missing")
    receipt_store = scenario.get("receiptStoreExpectation")
    if receipt_store:
        command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], receipt_store["command"])), None)
        if command is None or not any(event.get("kind") == "commandReceipt" and event.get("commandRef") == command["commandRef"] for event in event_list):
            missing.append(f"receipt store snapshot for {receipt_store['command']} is missing")
    expected_transport = scenario.get("expectedTransport")
    if expected_transport:
        command = next((row for row in trace["commandInventory"] if _native_command_matches(row["name"], expected_transport["command"])), None)
        if command is None or not any(event.get("kind") == "transportReceived" and event.get("commandRef") == command["commandRef"] for event in event_list):
            missing.append(f"transport observation for {expected_transport['command']} is missing")
    if missing:
        return [], list(dict.fromkeys(missing)), None

    for expected in scenario.get("receiptExpectations", []):
        command = next(row for row in trace["commandInventory"] if _native_command_matches(row["name"], expected["command"]))
        receipt = next(event for event in event_list if event.get("kind") == "commandReceipt" and event.get("commandRef") == command["commandRef"])
        if receipt["status"] != expected["status"]:
            issues.append(_issue(expected["invariant"], receipt["commandRef"], receipt, expected["status"], receipt["status"]))
    receipt_store = scenario.get("receiptStoreExpectation")
    if receipt_store:
        command = next(row for row in trace["commandInventory"] if _native_command_matches(row["name"], receipt_store["command"]))
        receipt = next(event for event in event_list if event.get("kind") == "commandReceipt" and event.get("commandRef") == command["commandRef"])
        if receipt["observation"]["store"] != receipt_store["store"]:
            issues.append(_issue("I8", command["commandRef"], receipt, receipt_store["store"], receipt["observation"]["store"]))
    expected_transport = scenario.get("expectedTransport")
    if expected_transport:
        command = next(row for row in trace["commandInventory"] if _native_command_matches(row["name"], expected_transport["command"]))
        received = next(event for event in event_list if event.get("kind") == "transportReceived" and event.get("commandRef") == command["commandRef"])
        if received["outcome"] != expected_transport["outcome"] or received["failureCode"] != expected_transport["failureCode"]:
            issues.append(_issue(expected_transport["invariant"], command["commandRef"], received, {"outcome": expected_transport["outcome"], "failureCode": expected_transport["failureCode"]}, {"outcome": received["outcome"], "failureCode": received["failureCode"]}))
    if scenario.get("id") == "APP-11":
        expected_queue = scenario.get("queuedOrder", [])
        queued_set = set(expected_queue)
        enqueues = [event for event in event_list if event.get("kind") == "commandEnqueued" and event.get("name") in queued_set]
        actual_queue = [event["name"] for event in sorted(enqueues, key=lambda event: event["localSequence"])]
        if actual_queue != expected_queue:
            source = enqueues[0] if enqueues else next((event for event in event_list if event.get("kind") == "processStart"), None)
            issues.append(_issue("I1", source.get("commandRef") if source else None, source, expected_queue, actual_queue))
        point = scenario.get("barrier")
        arrived = next((event for event in event_list if event.get("kind") == "hookEvent" and event.get("point") == point and event.get("phase") == "arrived"), None)
        released = next((event for event in event_list if event.get("kind") == "hookEvent" and event.get("point") == point and event.get("phase") == "released"), None)
        deliver = next((row for row in trace["commandInventory"] if row["name"] == "Deliver(current,success)"), None)
        deliver_receipt = next((event for event in event_list if event.get("kind") == "commandReceipt" and deliver and event.get("commandRef") == deliver["commandRef"]), None)
        queued_refs = {name: row["commandRef"] for name in expected_queue for row in trace["commandInventory"] if row["name"] == name}
        started = [event for event in event_list if event.get("kind") == "commandStarted" and event.get("commandRef") in queued_refs.values()]
        started_names = [inventory[(event["commandRef"]["processInstanceId"], event["commandRef"]["id"])] for event in sorted(started, key=lambda event: event["localSequence"])]
        if started_names != actual_queue:
            source = started[0] if started else (released or arrived)
            issues.append(_issue("I1", source.get("commandRef") if source else None, source, actual_queue, started_names))
        if released and any(event["localSequence"] <= released["localSequence"] for event in started):
            source = next(event for event in started if event["localSequence"] <= released["localSequence"])
            issues.append(_issue("I1", source["commandRef"], source, "queued command start follows independent control release", source["localSequence"]))
        if arrived and released and (not arrived["localSequence"] < released["localSequence"] or any(not arrived["localSequence"] < event["localSequence"] < released["localSequence"] for event in enqueues)):
            issues.append(_issue("I1", deliver["commandRef"] if deliver else None, arrived, "hook arrival < both enqueue events < direct release", [arrived["localSequence"], [event["localSequence"] for event in enqueues], released["localSequence"]]))
        if released and deliver_receipt and released["localSequence"] >= deliver_receipt["localSequence"]:
            issues.append(_issue("I1", deliver["commandRef"], deliver_receipt, "direct release precedes the paused delivery receipt", "receipt preceded release"))
        queued_refs_set = {(ref["processInstanceId"], ref["id"]) for ref in queued_refs.values()}
        early_receipts = [
            event for event in event_list
            if event.get("kind") == "commandReceipt"
            and (event["commandRef"]["processInstanceId"], event["commandRef"]["id"]) in queued_refs_set
            and released and event["localSequence"] <= released["localSequence"]
        ]
        if early_receipts:
            issues.append(_issue("I1", early_receipts[0]["commandRef"], early_receipts[0], "queued receipts follow direct control release", early_receipts[0]["localSequence"]))
        controller_release = next((event for event in trace["controllerEvents"] if event.get("kind") == "hookReleased" and event.get("point") == point), None)
        if controller_release and (controller_release.get("releaseChannel") != "DebugScenarioControl" or controller_release.get("authMailboxPaused") is not True or controller_release.get("deliverReceiptObserved") is not False):
            issues.append(_issue("I1", deliver["commandRef"] if deliver else None, controller_release, "direct control release while auth consumer is paused", controller_release))

    # Oracle conformance and command order.
    for event in event_list:
        pid, kind = event["processInstanceId"], event["kind"]
        if kind == "commandStarted":
            key = (pid, event["commandRef"]["id"])
            if open_commands[pid]:
                issues.append(_issue("I1", event["commandRef"], event, "one command executes at a time", {"alreadyOpen": open_commands[pid], "newCommand": key}))
            open_commands[pid].append(key)
        elif kind == "commandReceipt":
            key = (pid, event["commandRef"]["id"])
            if key not in open_commands[pid]:
                issues.append(_history_error("receipt does not close the currently executing command", event, event["commandRef"]))
            else:
                open_commands[pid].remove(key)
            observation = event["observation"]
            reduced = managed_by_command.get(key)
            reducer_snapshot = {field: reduced["result"][field] for field in ("ownerId", "state", "pendingRequestId", "nextRequestId")} if reduced else None
            if reduced and observation["managed"] != reducer_snapshot:
                issues.append(_history_error("receipt managed snapshot differs from reducer result", event, event["commandRef"]))
            elif not reduced and pid in last_managed and observation["managed"] != last_managed[pid]:
                issues.append(_history_error("command without a managed reduction changed the managed snapshot", event, event["commandRef"]))
            if pid in last_store and observation["store"] != last_store[pid]:
                issues.append(_history_error("receipt store snapshot differs from last verified readback", event, event["commandRef"]))
            name = inventory[key]
            if name.startswith("Logout") or name == "CancelRefresh":
                current = current_login.get(pid, {})
                logout_origin_accounts[key] = current.get("account", last_store.get(pid, {}).get("account"))
            if (name.startswith("Logout") or name == "CancelRefresh") and event["status"] == "Completed":
                verified_absent = last_store.get(pid) == {"kind": "Absent"} and any(
                    probe["kind"] == "storeReadback"
                    and probe["commandRef"] == event["commandRef"]
                    and probe["observation"] == {"kind": "Absent"}
                    and probe["localSequence"] < event["localSequence"]
                    for probe in event_list
                )
                correct = observation["managed"]["state"] == "Unauthenticated" and observation["managed"]["pendingRequestId"] is None and observation["store"] == {"kind": "Absent"} and verified_absent and observation["view"]["phase"] == "SignedOut"
                if not correct:
                    issues.append(_issue("I5", event["commandRef"], event, "Unauthenticated + no pending + verified Absent + SignedOut acknowledgement", observation))
                if observation["store"]["kind"] == "Unknown" or observation["view"]["phase"] == "FaultLocked" or last_store.get(pid, {}).get("kind") == "Unknown":
                    issues.append(_issue("I8", event["commandRef"], event, "storage/cleanup failure cannot report successful Logout", observation))
                logout_active[pid] = True
                active_slot.pop(pid, None)
            elif name.startswith("Login(") and event["status"] == "Completed":
                current_login.setdefault(pid, {"account": observation["store"].get("account"), "version": observation["store"].get("version"), "commandRef": event["commandRef"]})
            if name.startswith("Deliver("):
                reduced = managed_by_command.get(key)
                if reduced and reduced["event"]["event"] in {"RefreshSucceeded", "RefreshFailed"}:
                    if key in stale_commands:
                        before_projection = stale_commands[key]["projection"]
                        if before_projection is not None and _projection(observation["view"]) != before_projection:
                            issues.append(_issue("I7", event["commandRef"], event, "stale/foreign completion changes only metadata, not auth projection", _projection(observation["view"])))
                        if event["status"] not in {"IgnoredStale", "IgnoredForeign", "FaultLocked"}:
                            issues.append(_issue("I7", event["commandRef"], event, "stale delivery receipt is ignored", event["status"]))
                    elif event["status"] not in {"Completed", "FaultLocked", "RejectedExhausted"}:
                        issues.append(_issue("I7", event["commandRef"], event, "eligible delivery reports its commit/fault status", event["status"]))
            last_managed[pid] = observation["managed"]
        elif kind == "managedReduced":
            key = (pid, event["commandRef"]["id"])
            name = inventory[key]
            expected_event = _managed_event_for_command(name)
            if expected_event is not None:
                observed_event = event["event"]
                event_name = expected_event["event"]
                if observed_event.get("event") != event_name:
                    issues.append(_history_error("managed event does not match its app command", event, event["commandRef"]))
                else:
                    pre, actual = event["pre"], event["result"]
                    request_owner = event.get("requestOwnerId")
                    foreign = event_name in {"RefreshSucceeded", "RefreshFailed"} and request_owner is not None and request_owner != pre["ownerId"]
                    if foreign:
                        expected = {"ownerId": pre["ownerId"], "state": pre["state"], "pendingRequestId": pre["pendingRequestId"], "nextRequestId": pre["nextRequestId"], "effects": [], "rejection": "ForeignRequest"}
                    else:
                        try:
                            expected = managed_step(spec, pre["state"], pre["pendingRequestId"], pre["nextRequestId"], observed_event)
                            expected["ownerId"] = pre["ownerId"]
                        except (ValueError, KeyError, StopIteration) as exc:
                            issues.append(_history_error(f"managed oracle rejected event: {exc}", event, event["commandRef"]))
                            expected = None
                    if expected is not None and actual != expected:
                        issues.append(_history_error("managed reducer result differs from the frozen oracle", event, event["commandRef"]))
                    if event_name in {"RefreshSucceeded", "RefreshFailed"}:
                        slot_delivery_count[event.get("slotId")] += 1
                        slot = slots.get(event.get("slotId"))
                        stale = foreign or pre["state"] != "Refreshing" or pre["pendingRequestId"] != observed_event.get("requestId") or active_slot.get(pid) != event.get("slotId")
                        if stale:
                            prior_view = last_projection.get(pid)
                            prior_store = last_store.get(pid)
                            stale_commands[key] = {"projection": prior_view, "store": prior_store, "slot": slot}
                if event_name == "Logout":
                    active_slot.pop(pid, None)

        elif kind == "slotIssued":
            slot_id = event["slotId"]
            if event["wireTag"] not in server_held_tags:
                issues.append(_history_error("slot wireTag has no matching server request-held evidence", event, event["commandRef"]))
            if slot_id in slots:
                issues.append(_history_error("slot identity was reused", event, event["commandRef"]))
            reducer = managed_by_command.get((pid, event["commandRef"]["id"]))
            if not reducer or not any(effect.get("effect") == "RequestTokenRefresh" and effect.get("requestId") == event["requestId"] for effect in reducer["result"]["effects"]):
                issues.append(_issue("I2", event["commandRef"], event, "slot is backed by the actual managed RequestTokenRefresh effect", "slot exists without matching reducer effect"))
            if event["wireRequestId"] != str(event["requestId"]) or event["wireTag"] != f"{pid}:refresh:{event['commandRef']['id']}" or event["account"] not in {"A", "B"}:
                issues.append(_history_error("slot correlation metadata is inconsistent", event, event["commandRef"]))
            slots[slot_id] = event
            active_slot[pid] = slot_id

        elif kind == "storeMutation":
            key = (pid, event["commandRef"]["id"])
            command_name = inventory[key]
            cause, slot_id = event["cause"], event.get("slotId")
            reducer = managed_by_command.get(key)
            slot = slots.get(slot_id)
            store_mutations[key].append(event)
            prior = last_store.get(pid)
            if prior is not None and event["before"] != prior:
                issues.append(_history_error("store mutation before-value differs from last verified readback", event, event["commandRef"]))
            eligible = False
            if cause == "Bootstrap":
                eligible = command_name == "Bootstrap" and event["operation"] == "clear"
            elif cause == "Login":
                eligible = command_name.startswith("Login(") and reducer is not None and reducer["event"]["event"] == "LoginSucceeded" and reducer["pre"]["state"] == "Unauthenticated" and reducer["result"]["state"] == "Authenticated" and event["before"]["kind"] == "Absent"
            elif cause == "Logout":
                eligible = command_name.startswith("Logout") and reducer is not None and "ClearCredentials" in {item["effect"] for item in reducer["result"]["effects"]}
            elif cause in {"RefreshSuccess", "RefreshFailure"}:
                wanted = "RefreshSucceeded" if cause == "RefreshSuccess" else "RefreshFailed"
                eligible = bool(
                    command_name.startswith("Deliver(") and reducer and reducer["event"]["event"] == wanted and slot
                    and active_slot.get(pid) == slot_id and event.get("ownerId") == reducer["pre"]["ownerId"] == slot["ownerId"]
                    and event.get("epochId") == slot["epochId"] == reducer["epochId"]
                    and reducer["pre"]["state"] == "Refreshing" and reducer["pre"]["pendingRequestId"] == slot["requestId"] == reducer["event"].get("requestId")
                    and reducer["result"]["rejection"] is None
                    and ((cause == "RefreshSuccess" and reducer["result"]["state"] == "Authenticated") or (cause == "RefreshFailure" and reducer["result"]["state"] == "Unauthenticated"))
                )
            elif cause == "RetryCleanup":
                eligible = command_name == "RetryCleanup" and event["operation"] == "clear"
            elif cause == "CancelRefresh":
                eligible = command_name == "CancelRefresh" and event["operation"] == "clear"
            elif cause == "FaultCleanup":
                cleanup_fault = next((item for item in event_list if item.get("kind") == "storeFault" and item.get("commandRef") == event["commandRef"] and item.get("localSequence", MAX_I64) < event.get("localSequence", 0)), None)
                eligible = bool(cleanup_fault) and command_name.startswith(("Login(", "Deliver(", "Logout")) and event["operation"] == "clear"
            elif cause == "DeferredLogoutClear":
                eligible = False
            if not eligible:
                issues.append(_issue("I2", event["commandRef"], event, "admitted command/slot authorizes this mutation", f"unadmitted {cause} mutation"))
            if slot and slot_commit_count[slot_id] > 0 and cause in {"RefreshSuccess", "RefreshFailure", "DeferredLogoutClear"}:
                issues.append(_issue("I7", event["commandRef"], event, "a slot authorizes at most one credential commit", f"slot {slot_id} was already committed"))
            if slot and slot_id not in {active_slot.get(pid)}:
                if current_login.get(pid) and current_login[pid]["account"] != slot["account"]:
                    issues.append(_issue("I4", event["commandRef"], event, "old completion leaves the newer account unchanged", f"old {slot['account']} slot mutated current {current_login[pid]['account']} credential"))
                elif logout_active[pid] and event["after"].get("kind") != "Absent":
                    issues.append(_issue("I3", event["commandRef"], event, "credential remains Absent after Logout until a later Login", event["after"]))
            if logout_active[pid] and cause != "Login" and event["after"].get("kind") != "Absent":
                issues.append(_issue("I3", event["commandRef"], event, "credential remains Absent after Logout", event["after"]))
            if cause == "Login" and eligible:
                logout_active[pid] = False
                current_login[pid] = {"account": event["after"].get("account"), "version": event["after"].get("version"), "commandRef": event["commandRef"]}
            if cause in {"Logout", "CancelRefresh"}:
                active_slot.pop(pid, None)
                if cause == "CancelRefresh":
                    logout_active[pid] = True
            if eligible and cause in {"RefreshSuccess", "RefreshFailure"}:
                slot_commit_count[slot_id] += 1
                if slot_commit_count[slot_id] > 1:
                    issues.append(_issue("I7", event["commandRef"], event, "a slot authorizes at most one credential commit", slot_commit_count[slot_id]))
                active_slot.pop(pid, None)

        elif kind == "managedInstanceReset":
            if pid in last_managed and event["before"] != last_managed[pid]:
                issues.append(_history_error("managed owner reset does not match the latest completed snapshot", event, event["commandRef"]))
            last_managed[pid] = event["after"]

        elif kind == "storeReadback":
            key = (pid, event["commandRef"]["id"])
            mutations = store_mutations.get(key, [])
            if not mutations or mutations[-1]["operation"] != event["operation"] or mutations[-1]["after"] != event["observation"]:
                issues.append(_history_error("store readback does not verify the preceding mutation", event, event["commandRef"]))
            last_store[pid] = event["observation"]
            last_verified[pid] = event["localSequence"]

        elif kind == "detachedStoreMutation":
            origin = event["originCommandRef"]
            origin_key = (origin["processInstanceId"], origin["id"])
            origin_account = logout_origin_accounts.get(origin_key)
            prior = last_store.get(pid)
            if prior is not None and event["before"] != prior:
                issues.append(_history_error("detached effect before-value differs from last verified readback", event, origin))
            issues.append(_issue("I2", origin, event, "credential mutations are owned by the active app command or eligible slot", "detached Logout effect changed storage after its receipt"))
            current_account = current_login.get(pid, {}).get("account")
            if current_account is not None and origin_account is not None and current_account != origin_account:
                issues.append(_issue("I4", origin, event, "a prior Logout effect cannot clear a later account", {"originAccount": origin_account, "currentAccount": current_account, "after": event["after"]}))
            elif logout_active[pid] and event["after"].get("kind") != "Absent":
                issues.append(_issue("I3", origin, event, "credential remains Absent after Logout", event["after"]))
            last_store[pid] = event["after"]

        elif kind == "detachedStoreReadback":
            last_store[pid] = event["observation"]
            last_verified[pid] = event["localSequence"]

        elif kind == "storeFault":
            prior = last_store.get(pid)
            if prior is not None and event["before"] != prior:
                issues.append(_history_error("failed store operation before-value differs from last verified readback", event, event["commandRef"]))
            expected_fault = scenario.get("requiredStoreFault")
            expected_observation = scenario.get("faultObservation")
            if (
                expected_fault is not None and expected_observation is not None
                and event.get("commandRef") == next((row["commandRef"] for row in trace["commandInventory"] if _native_command_matches(row.get("name"), expected_fault["command"])), None)
                and event.get("observation") != expected_observation
            ):
                issues.append(_issue("I8", event["commandRef"], event, expected_observation, event.get("observation")))
            last_store[pid] = event["observation"]

        elif kind == "transportReceived":
            if event["requestTag"] not in server_tags:
                issues.append(_history_error("native transport receipt has no matching server response evidence", event, event["commandRef"]))
            if event["outcome"] not in {"success", "failure"}:
                issues.append(_history_error("transport outcome is outside the frozen envelope", event, event["commandRef"]))

        elif kind == "uiPublishAck":
            key = (pid, event["commandRef"]["id"])
            view = event["view"]
            previous_revision = last_revision.get(pid, 0)
            if event["revision"] <= previous_revision or event["revision"] > MAX_I64:
                issues.append(_issue("I6", event["commandRef"], event, "strictly increasing process-local UI revision", event["revision"]))
            last_revision[pid] = event["revision"]
            if view["phase"] in AUTH_PHASES:
                stored = last_store.get(pid)
                verified_sequence = last_verified.get(pid, 0)
                if stored is None or stored.get("kind") != "Present" or stored.get("account") != view["account"] or stored.get("version") != view["credentialVersion"] or verified_sequence >= event["localSequence"]:
                    issues.append(_issue("I6", event["commandRef"], event, "verified matching credential precedes authenticated UI acknowledgement", {"view": view, "store": stored}))
            if key in stale_commands:
                baseline = stale_commands[key]
                if baseline["projection"] is not None and _projection(view) != baseline["projection"]:
                    issues.append(_issue("I7", event["commandRef"], event, "stale completion preserves auth projection", _projection(view)))
                if logout_active[pid] and view["phase"] in AUTH_PHASES:
                    issues.append(_issue("I3", event["commandRef"], event, "old completion preserves logged-out UI", view))
                if baseline["slot"] and current_login.get(pid) and current_login[pid]["account"] != baseline["slot"]["account"] and _projection(view) != baseline["projection"]:
                    issues.append(_issue("I4", event["commandRef"], event, "old completion preserves Login B UI", view))
            last_projection[pid] = _projection(view)

    # Independent observations must match the frozen step expectations.
    final_store = scenario.get("expectedFinal", {}).get("store", {})
    for step_id, expected in scenario.get("probeExpectations", {}).items():
        item = observation_by_step.get(step_id)
        if not item:
            continue
        if item["observation"].get("kind") != "Unknown" and item["observation"] != expected:
            invariant = scenario["probeExpectationInvariants"][step_id]
            receipt = _probe_receipt(item)
            if receipt is None:
                issues.append(_history_error("mismatching storage probe has no matching native command receipt", command_ref=item.get("commandRef")))
            else:
                provenance = item.get("commandRef") or receipt.get("originCommandRef")
                issues.append(_issue(invariant, provenance, receipt, expected, item["observation"]))
    for step_id, expected in scenario.get("renderExpectations", {}).items():
        item = observation_by_step.get(step_id)
        if item and {"phase": item["phase"], "account": item["account"]} != expected:
            invariant = scenario["renderExpectationInvariants"][step_id]
            acknowledgement = event_by_ref.get((item["eventRef"]["processInstanceId"], item["eventRef"]["localSequence"]))
            if acknowledgement is None:
                issues.append(_history_error("mismatching rendered view has no native acknowledgement", item.get("eventRef")))
            else:
                issues.append(_issue(invariant, acknowledgement.get("commandRef"), acknowledgement, expected, {"phase": item["phase"], "account": item["account"]}))

    final = scenario.get("expectedFinal")
    if final:
        probe_step = next((step for step in reversed(scenario.get("requiredProbes", [])) if step in observation_by_step), None)
        probe = observation_by_step.get(probe_step) if probe_step else None
        view_step = next((step for step in reversed(scenario.get("requiredRenderedViews", [])) if step in observation_by_step), None)
        view = observation_by_step.get(view_step) if view_step else None
        if probe and probe["observation"].get("kind") != "Unknown" and probe["observation"] != final.get("store"):
            inv = scenario["probeExpectationInvariants"][probe_step]
            receipt = _probe_receipt(probe)
            if receipt is None:
                issues.append(_history_error("final storage probe has no matching native command receipt", command_ref=probe.get("commandRef")))
            else:
                provenance = probe.get("commandRef") or receipt.get("originCommandRef")
                issues.append(_issue(inv, provenance, receipt, final["store"], probe["observation"]))
        if view and {"phase": view["phase"], "account": view["account"]} != final.get("view"):
            inv = scenario["renderExpectationInvariants"][view_step]
            acknowledgement = event_by_ref.get((view["eventRef"]["processInstanceId"], view["eventRef"]["localSequence"]))
            if acknowledgement is None:
                issues.append(_history_error("final rendered view has no native acknowledgement", view.get("eventRef")))
            else:
                issues.append(_issue(inv, acknowledgement.get("commandRef"), acknowledgement, final["view"], {"phase": view["phase"], "account": view["account"]}))

    # A fresh process starts unauthenticated and observes the persisted store before bootstrap writes.
    for process in trace["processInstances"]:
        pid = process["processInstanceId"]
        first = next((event for event in event_list if event["processInstanceId"] == pid and event["kind"] == "processStart"), None)
        if first and first["initialView"]["phase"] != "Booting":
            bootstrap_ref = next((row["commandRef"] for row in trace["commandInventory"]
                                  if row["commandRef"]["processInstanceId"] == pid and row["name"] == "Bootstrap"), None)
            if bootstrap_ref is None:
                issues.append(_history_error("non-Booting process start has no Bootstrap command in inventory", first))
            else:
                issues.append(_issue("I9", bootstrap_ref, first, "Booting before verified bootstrap cleanup", first["initialView"]))
        bootstrap_command = next((row for row in trace["commandInventory"] if row["commandRef"]["processInstanceId"] == pid and row["name"] == "Bootstrap"), None)
        if bootstrap_command:
            ref = bootstrap_command["commandRef"]
            bootstrap_mutation = next((event for event in event_list if event.get("kind") == "storeMutation" and event.get("commandRef") == ref and event.get("cause") == "Bootstrap"), None)
            bootstrap_readback = next((event for event in event_list if event.get("kind") == "storeReadback" and event.get("commandRef") == ref and event.get("operation") == "clear"), None)
            bootstrap_receipt = next((event for event in event_list if event.get("kind") == "commandReceipt" and event.get("commandRef") == ref), None)
            if bootstrap_mutation and bootstrap_readback and bootstrap_receipt:
                if bootstrap_mutation["after"] != {"kind": "Absent"} or bootstrap_readback["observation"] != {"kind": "Absent"} or bootstrap_readback["localSequence"] >= bootstrap_receipt["localSequence"] or bootstrap_receipt["observation"]["view"]["phase"] != "SignedOut":
                    issues.append(_issue("I9", ref, bootstrap_receipt, "verified Absent bootstrap clear precedes SignedOut receipt", bootstrap_receipt["observation"]))
        ordinal = process["launchOrdinal"]
        if ordinal > 1:
            boot_probe = next((item for item in ui_observations if item["processInstanceId"] == pid and "before-bootstrap-clear" in item["stepId"]), None)
            bootstrap_mutation = next((event for event in event_list if event["processInstanceId"] == pid and event["kind"] == "storeMutation" and event["cause"] == "Bootstrap"), None)
            if boot_probe and bootstrap_mutation:
                hook_release = next((item for item in trace["controllerEvents"] if item.get("kind") == "hookReleased" and item.get("processInstanceId") == pid), None)
                checkpoint = next((item for item in trace["controllerEvents"] if item.get("kind") == "checkpointPublished" and item.get("processInstanceId") == pid and item.get("name") == "bootstrapStoreProbed"), None)
                native_release = _native_released_hook_event(trace, hook_release) if hook_release else None
                action_linked = native_release is not None and bootstrap_mutation.get("releaseActionId") == native_release.get("actionId")
                if not hook_release or not checkpoint or not action_linked or not boot_probe["controllerSequence"] < checkpoint["sequence"] < hook_release["sequence"] or bootstrap_mutation["localSequence"] <= 1:
                    issues.append(_issue("I9", bootstrap_mutation.get("commandRef"), bootstrap_mutation, "persisted credential probe and native hook action precede bootstrap clear", {
                        "releaseActionId": bootstrap_mutation.get("releaseActionId"),
                        "nativeReleaseActionId": native_release.get("actionId") if native_release else None,
                        "ordering": "incomplete or reversed",
                    }))
                elif bootstrap_mutation["after"] != {"kind": "Absent"}:
                    issues.append(_issue("I9", bootstrap_mutation.get("commandRef"), bootstrap_mutation, "Bootstrap clear produces verified Absent storage", bootstrap_mutation["after"]))

    return issues, missing, None


def check_trace(contract, scenario, trace, server_events, ui_observations, *, variant_id=None):
    """Return one of PASS, SEMANTIC_FAIL, INVALID_HISTORY, INFRA_FAILURE, INCONCLUSIVE."""
    resolved, variant, selector_error = _resolve_scenario_variant(scenario, trace, variant_id)
    if selector_error:
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": scenario.get("id") if isinstance(scenario, dict) else "unknown",
            "violations": [_history_error(selector_error)],
            "missingObservations": [],
        }
    scenario = resolved
    structural = _shape_errors(contract, scenario, trace, server_events, ui_observations)
    if structural:
        report = {
            "classification": "INVALID_HISTORY",
            "scenarioId": scenario.get("id") if isinstance(scenario, dict) else "unknown",
            "violations": [_history_error(error) for error in structural],
            "missingObservations": [],
        }
        return report
    trace = _normalize_command_roles(scenario, trace)
    report_variant = {}
    barrier_issues = _controller_barrier_issues(scenario, trace, ui_observations)
    if any(issue.get("invariant") == "HISTORY" for issue in barrier_issues):
        return {"classification": "INVALID_HISTORY", "scenarioId": scenario["id"], **report_variant, "violations": barrier_issues, "missingObservations": []}
    issues, missing, infrastructure_error = _evaluate(contract, scenario, trace, server_events, ui_observations)
    issues.extend(barrier_issues)
    if infrastructure_error:
        return {
            "classification": "INFRA_FAILURE",
            "scenarioId": scenario["id"],
            "violations": [],
            "missingObservations": [infrastructure_error],
        }
    if issues and any(issue["invariant"] == "HISTORY" for issue in issues):
        return {"classification": "INVALID_HISTORY", "scenarioId": scenario["id"], **report_variant, "violations": issues, "missingObservations": []}
    if missing:
        return {"classification": "INCONCLUSIVE", "scenarioId": scenario["id"], **report_variant, "violations": [], "missingObservations": missing}
    if issues:
        return {"classification": "SEMANTIC_FAIL", "scenarioId": scenario["id"], **report_variant, "violations": issues, "missingObservations": []}
    return {"classification": "PASS", "scenarioId": scenario["id"], **report_variant, "violations": [], "missingObservations": []}


def check_control_trace(contract, control, trace, server_events, ui_observations):
    """Check one frozen native mutation control and require its targeted witness."""
    control_id = control.get("id") if isinstance(control, dict) else "unknown"
    inventory_errors = control_inventory_errors(control)
    if inventory_errors:
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": control_id,
            "violations": [_history_error(error) for error in inventory_errors],
            "missingObservations": [],
        }
    if (
        not isinstance(control, dict) or not isinstance(control_id, str)
        or not isinstance(trace, dict)
        or trace.get("controlId") != control_id or trace.get("scenarioId") != control_id
    ):
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": control_id,
            "violations": [_history_error("trace control identity differs from the frozen control inventory")],
            "missingObservations": [],
        }
    if trace.get("variantId") is not None:
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": control_id,
            "violations": [_history_error("control trace cannot select an application scenario variant")],
            "missingObservations": [],
        }
    forbidden = set(control.get("forbiddenCommands", []))
    observed_commands = {row.get("name") for row in trace.get("commandInventory", []) if isinstance(row, dict)}
    if forbidden & observed_commands:
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": control_id,
            "violations": [_history_error(f"forbidden control command was executed: {sorted(forbidden & observed_commands)}")],
            "missingObservations": [],
        }

    scenario = {
        key: control[key]
        for key in (
            "platforms", "launches", "cancelMode", "requiredControllerEvents", "requiredServerEvents",
            "requiredProbes", "probeExpectations", "requiredRenderedViews", "renderExpectations",
            "expectedFinal", "receiptExpectations", "requiredDelivery", "releaseAfterCommand",
            "releaseAfterProbes", "receiptProbeOrder", "receiptStoreExpectation",
            "probeExpectationInvariants", "renderExpectationInvariants", "hookReleaseAfterCommand",
            "hookReleasePoint", "hookReleaseAfterProbes",
        )
        if key in control
    }
    scenario["id"] = control_id
    if not scenario.get("launches") and isinstance(control.get("commands"), list):
        scenario["launches"] = [{"ordinal": 1, "commands": list(control["commands"])}]

    declared_effects = control.get("effects", [])
    if not isinstance(declared_effects, list):
        return {
            "classification": "INVALID_HISTORY",
            "scenarioId": control_id,
            "violations": [_history_error("frozen control effect inventory is malformed")],
            "missingObservations": [],
        }
    if declared_effects:
        mutations = [event for event in trace.get("events", []) if event.get("kind") == "detachedStoreMutation"]
        declared_ids = [row.get("effectId") for row in declared_effects if isinstance(row, dict)]
        actual_ids = [event.get("effectId") for event in mutations]
        if len(set(declared_ids)) != len(declared_ids) or any(not isinstance(effect_id, str) or not effect_id for effect_id in declared_ids):
            return {
                "classification": "INVALID_HISTORY",
                "scenarioId": control_id,
                "violations": [_history_error("frozen detached effect IDs are duplicated or invalid")],
                "missingObservations": [],
            }
        if any(effect_id not in actual_ids for effect_id in declared_ids):
            return {
                "classification": "INCONCLUSIVE",
                "scenarioId": control_id,
                "violations": [],
                "missingObservations": [f"declared detached effect {effect_id} was not observed" for effect_id in declared_ids if effect_id not in actual_ids],
            }
        if set(actual_ids) != set(declared_ids) or len(actual_ids) != len(declared_ids):
            return {
                "classification": "INVALID_HISTORY",
                "scenarioId": control_id,
                "violations": [_history_error("observed detached effects differ from the exact frozen control inventory")],
                "missingObservations": [],
            }
        inventory = {row["commandRef"]["id"]: row["name"] for row in trace.get("commandInventory", []) if isinstance(row, dict) and isinstance(row.get("commandRef"), dict)}
        for frozen in declared_effects:
            event = next(row for row in mutations if row.get("effectId") == frozen["effectId"])
            origin = event.get("originCommandRef")
            expected_origin = frozen.get("originCommandRef")
            process_ordinals = {row["processInstanceId"]: row["launchOrdinal"] for row in trace.get("processInstances", []) if isinstance(row, dict)}
            if (
                not isinstance(origin, dict) or not isinstance(expected_origin, dict)
                or inventory.get(origin.get("id")) != expected_origin.get("command")
                or process_ordinals.get(origin.get("processInstanceId")) != expected_origin.get("launchOrdinal")
            ):
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error("detached effect originCommandRef does not identify its frozen origin command", event, origin)],
                    "missingObservations": [],
                }
            if event.get("operation") != frozen.get("operation"):
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error("detached effect operation differs from the frozen control", event, origin)],
                    "missingObservations": [],
                }
            readbacks = [row for row in trace.get("events", []) if row.get("kind") == "detachedStoreReadback" and row.get("effectId") == frozen["effectId"]]
            if not readbacks:
                return {
                    "classification": "INCONCLUSIVE",
                    "scenarioId": control_id,
                    "violations": [],
                    "missingObservations": [f"detached effect readback {frozen['effectId']} is missing"],
                }
            if len(readbacks) != 1 or readbacks[0].get("observation") != event.get("after") or readbacks[0].get("originCommandRef") != origin:
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error("detached effect readback is inconsistent with its mutation", readbacks[0], origin)],
                    "missingObservations": [],
                }

    for action in control.get("controlActions", []):
        if not isinstance(action, dict) or not isinstance(action.get("action"), str):
            return {
                "classification": "INVALID_HISTORY",
                "scenarioId": control_id,
                "violations": [_history_error("frozen control action is malformed")],
                "missingObservations": [],
            }
        if action["action"] == "injectStoreFault":
            fault = action.get("fault")
            fault_events = [event for event in trace.get("events", []) if event.get("kind") == "storeFault" and event.get("fault") == fault]
            if not fault_events:
                return {
                    "classification": "INCONCLUSIVE",
                    "scenarioId": control_id,
                    "violations": [],
                    "missingObservations": [f"store fault injection {fault} was not observed"],
                }
            command_names = {
                (row["commandRef"]["processInstanceId"], row["commandRef"]["id"]): row["name"]
                for row in trace.get("commandInventory", [])
                if isinstance(row, dict) and isinstance(row.get("commandRef"), dict)
            }
            command_roles, _ = _command_role_bindings(scenario, trace)
            target = action["command"]
            fault_key = (
                fault_events[0].get("commandRef", {}).get("processInstanceId"),
                fault_events[0].get("commandRef", {}).get("id"),
            ) if fault_events else None
            if len(fault_events) != 1 or command_roles.get(fault_key, command_names.get(fault_key)) != target:
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error("store fault event is not bound to its frozen target command", fault_events[0])],
                    "missingObservations": [],
                }
        elif action["action"] in {"arm", "awaitArrival", "release"}:
            phases = {"arm": "armed", "awaitArrival": "arrived", "release": "released"}
            observed = any(
                event.get("kind") == "hookEvent" and event.get("phase") == phases[action["action"]]
                and event.get("point") == action.get("point")
                and (action.get("target") is None or event.get("target") == action.get("target"))
                for event in trace.get("events", [])
            )
            if not observed:
                return {
                    "classification": "INCONCLUSIVE",
                    "scenarioId": control_id,
                    "violations": [],
                    "missingObservations": [f"control action {action['action']} at {action.get('point')} was not observed"],
                }
        elif action["action"] == "awaitDetachedEffect":
            effect_id = action["effectId"]
            acknowledgements = [
                event for event in trace.get("controllerEvents", [])
                if event.get("kind") == "detachedEffectAwaited" and event.get("effectId") == effect_id
            ]
            if not acknowledgements:
                return {
                    "classification": "INCONCLUSIVE",
                    "scenarioId": control_id,
                    "violations": [],
                    "missingObservations": [f"host acknowledgement for detached effect {effect_id} is missing"],
                }
            if len(acknowledgements) != 1:
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error(f"detached effect {effect_id} has duplicate host acknowledgements")],
                    "missingObservations": [],
                }
            acknowledgement = acknowledgements[0]
            frozen = next((row for row in declared_effects if row.get("effectId") == effect_id), None)
            origin = acknowledgement.get("originCommandRef")
            process_by_ordinal = {
                row["launchOrdinal"]: row["processInstanceId"]
                for row in trace.get("processInstances", []) if isinstance(row, dict)
            }
            command_names = {
                (row["commandRef"]["processInstanceId"], row["commandRef"]["id"]): row["name"]
                for row in trace.get("commandInventory", [])
                if isinstance(row, dict) and isinstance(row.get("commandRef"), dict)
            }
            expected_origin = frozen.get("originCommandRef") if isinstance(frozen, dict) else None
            if (
                not isinstance(expected_origin, dict)
                or not isinstance(origin, dict)
                or origin.get("processInstanceId") != process_by_ordinal.get(expected_origin.get("launchOrdinal"))
                or command_names.get((origin.get("processInstanceId"), origin.get("id"))) != expected_origin.get("command")
            ):
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error(f"detached effect {effect_id} acknowledgement has the wrong origin", acknowledgement, origin)],
                    "missingObservations": [],
                }
            release_point = control.get("hookReleasePoint")
            release_event = next((
                event for event in trace.get("controllerEvents", [])
                if event.get("kind") == "hookReleased" and event.get("point") == release_point
            ), None)
            if release_event is None or acknowledgement.get("sequence", 0) <= release_event.get("sequence", 0):
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error(f"detached effect {effect_id} was acknowledged before its release", acknowledgement, origin)],
                    "missingObservations": [],
                }
            final_probe_id = next((
                step for step in reversed(control.get("requiredProbes", [])) if "final" in step
            ), None)
            final_probe_event = next((
                event for event in trace.get("controllerEvents", [])
                if event.get("kind") == "probeCaptured" and event.get("stepId") == final_probe_id
            ), None)
            if final_probe_event is None:
                return {
                    "classification": "INCONCLUSIVE",
                    "scenarioId": control_id,
                    "violations": [],
                    "missingObservations": [f"final probe after detached effect {effect_id} is missing"],
                }
            if acknowledgement.get("sequence", 0) >= final_probe_event.get("sequence", 0):
                return {
                    "classification": "INVALID_HISTORY",
                    "scenarioId": control_id,
                    "violations": [_history_error(f"final probe precedes detached effect {effect_id} acknowledgement", final_probe_event)],
                    "missingObservations": [],
                }
        else:
            return {
                "classification": "INVALID_HISTORY",
                "scenarioId": control_id,
                "violations": [_history_error(f"unknown frozen control action {action['action']}")],
                "missingObservations": [],
            }

    report = check_trace(contract, scenario, trace, server_events, ui_observations)
    if report["classification"] != "SEMANTIC_FAIL":
        if report["classification"] == "PASS":
            return {
                "classification": "NOT_DETECTED",
                "scenarioId": control_id,
                "violations": [],
                "missingObservations": [],
            }
        return report
    observed = {item["invariant"] for item in report["violations"]}
    required = set(control.get("witnessInvariants", []))
    if not required <= observed:
        return {
            "classification": "NOT_DETECTED",
            "scenarioId": control_id,
            "violations": report["violations"],
            "missingObservations": [],
        }
    return report


def _load_json(path):
    return json.loads(Path(path).read_text())


def _read_artifacts(directory):
    root = Path(directory)
    trace_path = root / "trace.json"
    if not trace_path.is_file():
        raise FileNotFoundError(f"missing trace.json in {root}")
    trace = _load_json(trace_path)
    server_path = root / "server-events.json"
    observations_path = root / "ui-observations.json"
    server = _load_json(server_path) if server_path.is_file() else []
    observations = _load_json(observations_path) if observations_path.is_file() else []
    return trace, server, observations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--variant-id")
    args = parser.parse_args(argv)
    report_path = Path(args.report)
    try:
        contract = _load_json(args.contract)
        scenarios = _load_json(args.scenarios)["scenarios"]
        trace, server, observations = _read_artifacts(args.artifacts)
        scenario = next(row for row in scenarios if row["id"] == trace["scenarioId"])
        result = check_trace(contract, scenario, trace, server, observations, variant_id=args.variant_id)
    except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
        result = {"classification": "INFRA_FAILURE", "scenarioId": "unknown", "violations": [], "missingObservations": [f"evaluator input unavailable: {exc}"]}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    if result["classification"] == "PASS":
        return 0
    if result["classification"] in {"SEMANTIC_FAIL", "INVALID_HISTORY"}:
        return 1
    if result["classification"] == "INFRA_FAILURE":
        return 2
    return 3


if __name__ == "__main__":
    sys.exit(main())
