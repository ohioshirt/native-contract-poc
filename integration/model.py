"""Finite FIFO integration model and bounded breadth-first exploration."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from verification.async_contract import step as managed_step


ROOT = Path(__file__).resolve().parents[1]
MAX_I64 = 9223372036854775807
MAX_STATES = 50000
BOUNDS = {
    "dequeuedCommands": 6,
    "uiRevisions": 12,
    "owners": 2,
    "epochs": 3,
    "requestIdsPerOwner": 2,
    "queuedCommands": 2,
    "currentSlots": 1,
    "retainedOldSlots": 1,
    "replaysPerSlot": 1,
}
GOAL_NAMES = {
    "app02": "APP-02-success-after-logout",
    "app03": "APP-03-failure-after-logout",
    "app04": "APP-04-old-success-after-login-b",
    "app05": "APP-05-old-failure-after-login-b",
    "duplicate": "duplicate-delivery",
    "queued": "queued-logout-during-pause",
    "retry": "fault-retry-cleanup",
    "restart": "restart-bootstrap-cleanup",
}
MUTANT_TARGETS = {
    "unconditional-success-commit": ("I2", "I3", "I4"),
    "reentrant-consumer": ("I1", "I3"),
    "duplicate-deferred-clear": ("I4",),
    "unverified-publish": ("I6",),
    "failed-clear-ack": ("I8",),
}


@dataclass(frozen=True)
class Slot:
    ident: str
    owner: int
    epoch: int
    request_id: int
    account: str
    seed_version: int
    outcome: str | None = None
    released: bool = False
    delivery_count: int = 0
    replayed: bool = False
    committed: bool = False
    commit_count: int = 0
    revoked: bool = False


@dataclass(frozen=True)
class StoreIntent:
    after: str
    cause: str
    slot_id: str | None
    authorized: bool


@dataclass(frozen=True)
class State:
    health: str = "Booting"
    managed: str = "Unauthenticated"
    pending: int | None = None
    next_ids: tuple[int, int] = (1, 1)
    owner: int = 0
    owner_count: int = 0
    epoch: int = 0
    epoch_count: int = 0
    active_slot: str | None = None
    slots: tuple[Slot, ...] = ()
    physical_store: str = "Absent"
    store_observation: str = "Unknown"
    verified_store: str | None = None
    view_phase: str = "Booting"
    view_account: str | None = None
    view_version: int | None = None
    view_pending: int | None = None
    revision: int = 0
    launch_ordinal: int = 1
    bootstrap_verified: bool = False
    mailbox: tuple[str, ...] = ()
    running: tuple[str, ...] = ()
    pc: str = "idle"
    pending_store: StoreIntent | None = None
    pending_view: tuple[str, str | None, int | None, int | None] | None = None
    pending_status: str = "Completed"
    pause_armed: str | None = None
    paused_at: str | None = None
    dequeued: int = 0
    current_login_account: str | None = None
    logout_completed: bool = False
    logout_active: bool = False
    login_after_logout: bool = False
    restart_had_credential: bool = False
    last_write_authorized: bool = True
    last_write_cause: str = "none"
    last_write_slot: str | None = None
    last_delivery_stale: bool = False
    last_delivery_slot: str | None = None
    last_delivery_outcome: str | None = None
    last_delivery_slot_account: str | None = None
    delivery_pre_projection: tuple | None = None
    last_receipt_invalid: bool = False
    last_receipt_command: str = ""
    last_receipt_status: str = ""
    deferred_clear_pending: bool = False
    fault_seen: bool = False
    coverage: frozenset[str] = frozenset()


@lru_cache(maxsize=1)
def _load_spec():
    return json.loads((ROOT / "contract" / "specification.json").read_text())


def _credential(account, version):
    return f"{account}{version}"


def _decode_credential(value):
    if value in {"A0", "A1", "B0", "B1"}:
        return value[0], int(value[1])
    return None, None


def _slot_index(slots, slot_id):
    for index, slot in enumerate(slots):
        if slot.ident == slot_id:
            return index
    return None


def _replace_slot(state, slot):
    slots = list(state.slots)
    index = _slot_index(slots, slot.ident)
    if index is None:
        slots.append(slot)
    else:
        slots[index] = slot
    return replace(state, slots=tuple(slots))


def _get_slot(state, slot_id):
    index = _slot_index(state.slots, slot_id)
    return state.slots[index] if index is not None else None


def _auth_projection(state):
    return (state.view_phase, state.view_account, state.view_version, state.view_pending)


def _set_coverage(state):
    coverage = set(state.coverage)
    if state.last_delivery_stale and state.logout_completed and not state.login_after_logout:
        if state.last_delivery_outcome == "success":
            coverage.add(GOAL_NAMES["app02"])
        if state.last_delivery_outcome == "failure":
            coverage.add(GOAL_NAMES["app03"])
    if state.last_delivery_stale and state.login_after_logout and state.current_login_account == "B":
        if state.last_delivery_outcome == "success":
            coverage.add(GOAL_NAMES["app04"])
        if state.last_delivery_outcome == "failure":
            coverage.add(GOAL_NAMES["app05"])
    if state.last_delivery_slot:
        slot = _get_slot(state, state.last_delivery_slot)
        if slot and slot.replayed and slot.delivery_count >= 2 and state.last_delivery_stale:
            coverage.add(GOAL_NAMES["duplicate"])
    if state.paused_at and "Logout" in state.mailbox and "Login(B)" in state.mailbox:
        coverage.add("queued-pause-seen")
    if "RetryCleanup" not in state.running and state.fault_seen and state.health == "Ready" and state.managed == "Unauthenticated":
        if any(slot.revoked for slot in state.slots) or state.store_observation == "Absent":
            coverage.add(GOAL_NAMES["retry"])
    if state.launch_ordinal == 2 and state.restart_had_credential and state.health == "Ready" and state.store_observation == "Absent" and state.verified_store == "Absent":
        coverage.add(GOAL_NAMES["restart"])
    return replace(state, coverage=frozenset(coverage))


def _snapshot(state):
    return {
        "ownerId": f"owner-{state.owner + 1}",
        "state": state.managed,
        "pendingRequestId": state.pending,
        "nextRequestId": state.next_ids[state.owner] if state.owner < len(state.next_ids) else None,
    }


def _view(state):
    return {
        "phase": state.view_phase,
        "account": state.view_account,
        "credentialVersion": state.view_version,
        "pendingRequestId": state.view_pending,
    }


def _public_state(state):
    return {
        "health": state.health,
        "managed": _snapshot(state),
        "physicalStore": state.physical_store,
        "storeObservation": state.store_observation,
        "verifiedStore": state.verified_store,
        "view": _view(state),
        "revision": state.revision,
        "launchOrdinal": state.launch_ordinal,
        "queuedCommands": list(state.mailbox),
        "runningCommands": list(state.running),
        "pausedAt": state.paused_at,
        "activeSlot": state.active_slot,
        "dequeuedCommands": state.dequeued,
    }


def _command_kind(command):
    if command.startswith("Deliver("):
        return "Deliver"
    return command


def _command_parts(command):
    if not command.startswith("Deliver(") or not command.endswith(")"):
        return None, None
    body = command[len("Deliver("):-1]
    slot_id, outcome = body.rsplit(",", 1)
    return slot_id, outcome


def _manager_result(spec, state, event):
    next_id = state.next_ids[state.owner]
    bounded_next = None if next_id > BOUNDS["requestIdsPerOwner"] else next_id
    result = managed_step(spec, state.managed, state.pending, bounded_next, event, request_id_max=BOUNDS["requestIdsPerOwner"])
    next_ids = list(state.next_ids)
    next_id = result["nextRequestId"]
    next_ids[state.owner] = 3 if next_id is None else next_id
    return replace(state, managed=result["state"], pending=result["pendingRequestId"], next_ids=tuple(next_ids)), result


def _allocate_epoch(state):
    if state.epoch_count >= BOUNDS["epochs"]:
        return None
    return replace(state, epoch=state.epoch_count, epoch_count=state.epoch_count + 1)


def _mark_fault(state):
    if state.active_slot is not None:
        bumped = _allocate_epoch(state)
        if bumped is not None:
            state = bumped
    slots = tuple(replace(slot, revoked=True) for slot in state.slots)
    return replace(state, health="FaultLocked", active_slot=None, slots=slots, managed="Unauthenticated", pending=None)


def _receipt_name(command, status):
    kind = _command_kind(command)
    return f"receipt({kind},{status})"


def _state_violations(state):
    violations = []
    if len(state.running) > 1:
        violations.append("I1")
    if state.last_write_cause == "DeferredLogoutClear" and state.login_after_logout and state.current_login_account == "B":
        violations.append("I4")
    if state.last_write_cause != "none" and not state.last_write_authorized:
        violations.append("I2")
    if state.logout_active and state.health != "FaultLocked" and (
        state.physical_store != "Absent" or state.view_phase in {"SignedIn", "Refreshing"}
    ):
        violations.append("I3")
    if state.last_receipt_invalid and state.last_receipt_command == "Logout" and state.last_receipt_status == "Completed":
        violations.extend(("I8", "I5"))
    if any(slot.commit_count > 1 for slot in state.slots):
        violations.append("I7")
    if state.last_delivery_stale and state.delivery_pre_projection is not None and _auth_projection(state) != state.delivery_pre_projection:
        violations.append("I7")
    if state.launch_ordinal > 1 and state.health == "Ready" and not state.bootstrap_verified:
        violations.append("I9")
    # Preserve deterministic ordering and remove duplicate labels.
    return list(dict.fromkeys(violations))


def _goal_flags(state):
    return state.coverage


def _transition_violations(before, action, after):
    violations = _state_violations(after)
    if action.startswith("publish(") or action.startswith("receipt("):
        account, version = _decode_credential(after.store_observation)
        if after.view_phase in {"SignedIn", "Refreshing"} and (
            after.store_observation == "Unknown"
            or after.verified_store != after.store_observation
            or (account, version) != (after.view_account, after.view_version)
        ):
            violations.append("I6")
        if after.health == "FaultLocked" and after.view_phase in {"SignedIn", "Refreshing"}:
            violations.append("I8")
    return list(dict.fromkeys(violations))


def _available_commands(state):
    used = set(state.mailbox) | set(state.running)
    if state.health == "Booting":
        return [] if "Bootstrap" in used else ["Bootstrap"]
    if state.health == "FaultLocked":
        return [] if "RetryCleanup" in used else ["RetryCleanup"]
    commands = []
    if state.managed == "Unauthenticated" and state.store_observation == "Absent":
        next_account = "B" if state.logout_completed else "A"
        candidate = f"Login({next_account})"
        if candidate not in used:
            commands.append(candidate)
    if state.managed == "Authenticated":
        if "Expire" not in used:
            commands.append("Expire")
        if "Logout" not in used:
            commands.append("Logout")
    if state.managed == "Refreshing":
        if "Expire" not in used:
            commands.append("Expire")
        if "Logout" not in used:
            commands.append("Logout")
        if "CancelRefresh" not in used:
            commands.append("CancelRefresh")
    if "Logout" in state.mailbox and "Login(B)" not in used:
        commands.append("Login(B)")
    if "CancelRefresh" in state.mailbox and "Login(B)" not in used:
        commands.append("Login(B)")
    return commands


def _environment_actions(state, mutant):
    actions = []
    outstanding = state.dequeued + len(state.mailbox)
    if outstanding < BOUNDS["dequeuedCommands"] and len(state.mailbox) < BOUNDS["queuedCommands"]:
        actions.extend(f"enqueue({command})" for command in _available_commands(state))
        for slot in state.slots:
            if not slot.released and slot.outcome is None:
                command_counted = outstanding + 1
                if command_counted <= BOUNDS["dequeuedCommands"]:
                    actions.append(f"release({slot.ident},success)")
                    actions.append(f"release({slot.ident},failure)")
            elif slot.delivery_count == 1 and slot.outcome is not None and not slot.replayed:
                actions.append(f"replay({slot.ident})")
    if state.paused_at:
        actions.append("releasePause")
    if state.running and len(state.running) == 1 and state.pc == "begin" and state.pause_armed is None:
        command = state.running[0]
        if command.startswith("Deliver("):
            actions.append("arm(store)")
            actions.append("arm(publish)")
    if state.launch_ordinal == 1 and state.health == "Ready" and not state.running and not state.mailbox and state.owner_count < 2 and state.epoch_count < BOUNDS["epochs"]:
        actions.append("restart")
    if state.launch_ordinal == 2 and state.health == "Booting" and state.pause_armed is None:
        actions.append("arm(bootstrap)")
    if mutant == "duplicate-deferred-clear" and state.deferred_clear_pending and state.login_after_logout and state.current_login_account == "B" and not state.running:
        actions.append("deferredClear(old-logout)")
    if state.paused_at == "bootstrapClear" and state.launch_ordinal == 2 and state.store_observation == "Unknown":
        actions.append("probeBeforeBootstrap")
    return actions


def initial_state():
    return State()


def _account_from_state(state):
    account, version = _decode_credential(state.physical_store)
    return account, version


def _bump_revision(state):
    if state.revision >= BOUNDS["uiRevisions"]:
        return None
    return replace(state, revision=state.revision + 1)


def _close_fault(state, *, after_value=None):
    physical = state.physical_store if after_value is None else after_value
    state = replace(state, physical_store=physical, store_observation="Unknown", verified_store=None, fault_seen=True)
    state = _mark_fault(state)
    return replace(
        state,
        pending_store=None,
        pending_view=("FaultLocked", None, None, None),
        pending_status="FaultLocked",
        pc="publishPending",
        last_write_cause="none",
        last_write_slot=None,
        last_write_authorized=True,
    )


def _begin_command(state, command, mutant):
    if command == "Bootstrap":
        if state.owner_count == 0:
            state = replace(state, owner=0, owner_count=1, epoch=0, epoch_count=1)
        state = replace(
            state,
            pending_store=StoreIntent("Absent", "Bootstrap", None, True),
            pending_view=("SignedOut", None, None, None),
            pending_status="Completed",
            pc="storePending",
            paused_at="bootstrapClear" if state.pause_armed == "bootstrap" else None,
        )
        return _set_coverage(state)

    if command.startswith("Login("):
        account = "B" if command == "Login(B)" else "A"
        allowed = state.health == "Ready" and state.managed == "Unauthenticated" and state.store_observation == "Absent"
        if not allowed:
            return replace(state, pending_view=_view_as_tuple(state), pending_status="RejectedBusy", pc="publishPending")
        seed = _credential(account, 0)
        return replace(
            state,
            pending_store=StoreIntent(seed, "Login", None, True),
            pending_view=("SignedIn", account, 0, None),
            pending_status="Completed",
            pc="storePending",
            paused_at="store" if state.pause_armed == "store" else None,
        )

    if command == "Expire":
        if state.health != "Ready" or state.managed not in {"Authenticated", "Refreshing"}:
            return replace(state, pending_view=_view_as_tuple(state), pending_status="RejectedBusy", pc="publishPending")
        spec = _load_spec()
        next_state, result = _manager_result(spec, state, {"event": "TokenExpired"})
        if result["rejection"] is not None:
            return replace(next_state, pending_view=_view_as_tuple(next_state), pending_status="RejectedExhausted", pc="publishPending")
        effect = next((item for item in result["effects"] if item["effect"] == "RequestTokenRefresh"), None)
        if effect:
            request_id = effect["requestId"]
            if request_id > BOUNDS["requestIdsPerOwner"]:
                return replace(state, pending_view=_view_as_tuple(state), pending_status="RejectedExhausted", pc="publishPending")
            account, version = _account_from_state(state)
            if account is None:
                return _close_fault(state)
            slot_id = f"slot-o{state.owner}-e{state.epoch}-r{request_id}"
            slot = Slot(slot_id, state.owner, state.epoch, request_id, account, version)
            slots = list(state.slots)
            slots.append(slot)
            slots = slots[-2:]
            next_state = replace(next_state, active_slot=slot_id, slots=tuple(slots))
            pending_view = ("Refreshing", account, version, request_id)
        else:
            account, version = _account_from_state(state)
            pending_view = ("Refreshing", account, version, state.pending)
        return replace(next_state, pending_view=pending_view, pending_status="Completed", pc="publishPending")

    if command in {"Logout", "CancelRefresh"}:
        if state.health != "Ready":
            return replace(state, pending_view=("FaultLocked", None, None, None), pending_status="FaultLocked", pc="publishPending")
        slots = tuple(replace(slot, revoked=True) if slot.ident == state.active_slot else slot for slot in state.slots)
        allocated = _allocate_epoch(state)
        if allocated is None:
            return replace(state, pending_view=_view_as_tuple(state), pending_status="RejectedExhausted", pc="publishPending")
        state = allocated
        state = replace(state, active_slot=None, slots=slots, pending_view=("SigningOut", None, None, None), pending_status="Completed", pc="publishInterim")
        if mutant == "duplicate-deferred-clear" and slots:
            state = replace(state, deferred_clear_pending=True)
        return state

    if command.startswith("Deliver("):
        slot_id, outcome = _command_parts(command)
        slot = _get_slot(state, slot_id)
        if slot is None or slot.outcome != outcome or not slot.released:
            return replace(state, pending_view=_view_as_tuple(state), pending_status="IgnoredStale", pc="publishPending")
        was_replayed = slot.delivery_count > 0
        slot = replace(slot, delivery_count=min(2, slot.delivery_count + 1))
        state = _replace_slot(state, slot)
        pre_projection = _auth_projection(state)
        foreign = slot.owner != state.owner
        eligible = (
            not foreign
            and state.health == "Ready"
            and state.active_slot == slot.ident
            and slot.epoch == state.epoch
            and state.managed == "Refreshing"
            and state.pending == slot.request_id
        )
        outcome_event = {"event": "RefreshSucceeded" if outcome == "success" else "RefreshFailed", "requestId": slot.request_id}
        if foreign:
            status = "IgnoredForeign"
            next_state = state
        else:
            next_state, _ = _manager_result(_load_spec(), state, outcome_event)
            status = "Completed" if eligible else "IgnoredStale"
        pending_store = None
        if eligible:
            if outcome == "success":
                pending_store = StoreIntent(_credential(slot.account, slot.seed_version + 1), "RefreshSuccess", slot.ident, True)
                pending_view = ("SignedIn", slot.account, slot.seed_version + 1, None)
            else:
                pending_store = StoreIntent("Absent", "RefreshFailure", slot.ident, True)
                pending_view = ("SignedOut", None, None, None)
            next_state = replace(next_state, active_slot=None)
        else:
            pending_view = _view_as_tuple(next_state)
            if mutant == "unconditional-success-commit" and outcome == "success":
                pending_store = StoreIntent(_credential(slot.account, slot.seed_version + 1), "RefreshSuccess", slot.ident, False)
                pending_view = ("SignedIn", slot.account, slot.seed_version + 1, None)
                status = "IgnoredStale"
        return replace(
            next_state,
            last_delivery_stale=not eligible,
            last_delivery_slot=slot.ident,
            last_delivery_outcome=outcome,
            last_delivery_slot_account=slot.account,
            delivery_pre_projection=pre_projection,
            pending_store=pending_store,
            pending_view=pending_view,
            pending_status=status,
            pc="storePending" if pending_store else "publishPending",
            paused_at="store" if pending_store and state.pause_armed == "store" else None,
        )

    if command == "RetryCleanup":
        if state.health != "FaultLocked":
            return replace(state, pending_view=_view_as_tuple(state), pending_status="RejectedBusy", pc="publishPending")
        return replace(
            state,
            pending_store=StoreIntent("Absent", "RetryCleanup", None, True),
            pending_view=("SignedOut", None, None, None),
            pending_status="Completed",
            pc="storePending",
            paused_at="store" if state.pause_armed == "store" else None,
        )
    raise ValueError(f"unknown app command {command}")


def _view_as_tuple(state):
    return (state.view_phase, state.view_account, state.view_version, state.view_pending)


def enabled_actions(state, mutant=None):
    # Revision exhaustion is a finite-model cut: do not fabricate a UI
    # publication or receipt after the bounded publisher has stopped.
    if state.revision >= BOUNDS["uiRevisions"]:
        return []
    actions = _environment_actions(state, mutant)
    if not state.running:
        if state.mailbox and state.dequeued < BOUNDS["dequeuedCommands"]:
            actions.append(f"dequeue({state.mailbox[0]})")
        return sorted(set(actions))
    if len(state.running) > 1:
        return sorted(set(actions))

    command = state.running[0]
    if mutant == "reentrant-consumer" and state.paused_at and state.mailbox and state.mailbox[0] == "Logout" and state.dequeued < BOUNDS["dequeuedCommands"]:
        actions.append(f"dequeue({state.mailbox[0]})")
    if state.pc == "begin":
        actions.append(f"begin({command})")
    elif state.pc == "publishInterim":
        actions.append("publish(SigningOut)")
    elif state.pc == "reduceLogout":
        actions.append("reduce(Logout)")
    elif state.pc == "storePending":
        if not state.paused_at:
            actions.extend(("store(success)", "store(failBefore)", "store(failAfter)"))
        if mutant == "unverified-publish" and state.pending_view and state.pending_view[0] in {"SignedIn", "Refreshing"}:
            actions.append(f"publish({state.pending_view[0]})")
    elif state.pc == "publishPending":
        if not state.paused_at and state.pending_view is not None:
            actions.append(f"publish({state.pending_view[0]})")
    elif state.pc == "receiptPending":
        actions.append(_receipt_name(command, state.pending_status))
    return sorted(set(actions))


def _publish_view(state, view, *, revision=None):
    phase, account, version, pending = view
    bumped = _bump_revision(state)
    if bumped is None:
        return state
    return replace(
        bumped,
        view_phase=phase,
        view_account=account,
        view_version=version,
        view_pending=pending,
    )


def _store_success(state):
    intent = state.pending_store
    if intent is None:
        raise ValueError("store success without a pending store intent")
    state = replace(
        state,
        physical_store=intent.after,
        store_observation=intent.after,
        verified_store=intent.after,
        last_write_authorized=intent.authorized,
        last_write_cause=intent.cause,
        last_write_slot=intent.slot_id,
    )
    if intent.cause == "Bootstrap":
        state = replace(state, health="Ready", bootstrap_verified=True, pending_view=("SignedOut", None, None, None))
    elif intent.cause == "Login":
        account, _ = _decode_credential(intent.after)
        spec = _load_spec()
        state, _ = _manager_result(spec, state, {"event": "LoginSucceeded"})
        state = replace(
            state,
            current_login_account=account,
            logout_active=False,
            login_after_logout=state.logout_completed,
            pending_view=("SignedIn", account, 0, None),
            health="Ready",
        )
    elif intent.cause == "RefreshSuccess":
        slot = _get_slot(state, intent.slot_id)
        if slot:
            state = _replace_slot(state, replace(slot, committed=True, commit_count=slot.commit_count + 1))
        state = replace(state, active_slot=None)
        state = replace(state, pending_view=("SignedIn", *_decode_credential(intent.after), None))
    elif intent.cause == "RefreshFailure":
        slot = _get_slot(state, intent.slot_id)
        if slot:
            state = _replace_slot(state, replace(slot, committed=True, commit_count=slot.commit_count + 1))
        state = replace(state, active_slot=None)
        state = replace(state, pending_view=("SignedOut", None, None, None))
    elif intent.cause in {"Logout", "CancelRefresh"}:
        state = replace(state, pending_view=("SignedOut", None, None, None))
    elif intent.cause == "RetryCleanup":
        if state.owner_count >= BOUNDS["owners"] or state.epoch_count >= BOUNDS["epochs"]:
            return replace(state, health="FaultLocked", pending_view=("FaultLocked", None, None, None), pending_status="FaultLocked")
        owner = state.owner_count
        epoch = state.epoch_count
        next_ids = list(state.next_ids)
        next_ids[owner] = 1
        state = replace(
            state,
            owner=owner,
            owner_count=owner + 1,
            epoch=epoch,
            epoch_count=epoch + 1,
            next_ids=tuple(next_ids),
            active_slot=None,
            slots=(),
            managed="Unauthenticated",
            pending=None,
            health="Ready",
            current_login_account=None,
            pending_view=("SignedOut", None, None, None),
        )
    state = replace(state, pc="publishPending", pending_store=None)
    if state.pause_armed == "publish":
        state = replace(state, paused_at="publish")
    return state


def _store_failure(state, outcome, mutant):
    intent = state.pending_store
    if intent is None:
        raise ValueError("store failure without a pending store intent")
    physical = state.physical_store if outcome == "failBefore" else intent.after
    if mutant == "failed-clear-ack" and intent.cause in {"Logout", "CancelRefresh"}:
        return replace(
            state,
            physical_store=physical,
            store_observation="Unknown",
            verified_store=None,
            health="Ready",
            pending_store=None,
            pending_view=("SignedOut", None, None, None),
            pending_status="Completed",
            pc="publishPending",
            last_receipt_invalid=True,
        )
    state = _close_fault(state, after_value=physical)
    state = replace(
        state,
        last_write_authorized=intent.authorized,
        last_write_cause=intent.cause,
        last_write_slot=intent.slot_id,
    )
    if mutant == "duplicate-deferred-clear" and intent.cause in {"Logout", "CancelRefresh"}:
        state = replace(state, deferred_clear_pending=bool(state.slots))
    return state


def apply_action(state, action, mutant=None):
    """Apply one explicit environment or coordinator microstep."""
    allowed = enabled_actions(state, mutant)
    if action not in allowed:
        raise ValueError(f"action {action!r} is not enabled in this state")

    if action.startswith("enqueue(") and action.endswith(")"):
        command = action[len("enqueue("):-1]
        state = replace(state, mailbox=state.mailbox + (command,))

    elif action.startswith("dequeue(") and action.endswith(")"):
        command = action[len("dequeue("):-1]
        if state.running:
            state = replace(state, running=state.running + (command,), dequeued=state.dequeued + 1)
        else:
            state = replace(state, mailbox=state.mailbox[1:], running=(command,), pc="begin", dequeued=state.dequeued + 1)

    elif action.startswith("begin(") and action.endswith(")"):
        command = action[len("begin("):-1]
        if not state.running or state.running[0] != command:
            raise ValueError("begin action does not match running command")
        state = replace(state, pc="begin")
        state = _begin_command(state, command, mutant)

    elif action.startswith("arm(") and action.endswith(")"):
        target = action[len("arm("):-1]
        if target not in {"store", "publish", "bootstrap"}:
            raise ValueError("unknown pause target")
        state = replace(state, pause_armed=target)

    elif action == "releasePause":
        state = replace(state, paused_at=None, pause_armed=None)

    elif action == "probeBeforeBootstrap":
        state = replace(state, store_observation=state.physical_store)

    elif action == "restart":
        if state.owner_count >= BOUNDS["owners"] or state.epoch_count >= BOUNDS["epochs"]:
            raise ValueError("owner/epoch bound exhausted")
        owner = state.owner_count
        epoch = state.epoch_count
        next_ids = list(state.next_ids)
        next_ids[owner] = 1
        state = replace(
            state,
            health="Booting",
            managed="Unauthenticated",
            pending=None,
            next_ids=tuple(next_ids),
            owner=owner,
            owner_count=owner + 1,
            epoch=epoch,
            epoch_count=epoch + 1,
            active_slot=None,
            slots=(),
            store_observation="Unknown",
            verified_store=None,
            view_phase="Booting",
            view_account=None,
            view_version=None,
            view_pending=None,
            revision=0,
            launch_ordinal=2,
            bootstrap_verified=False,
            restart_had_credential=state.physical_store != "Absent",
        )

    elif action.startswith("release(") and action.endswith(")"):
        body = action[len("release("):-1]
        slot_id, outcome = body.rsplit(",", 1)
        slot = _get_slot(state, slot_id)
        if not slot:
            raise ValueError("release refers to unknown slot")
        state = _replace_slot(state, replace(slot, released=True, outcome=outcome))
        command = f"Deliver({slot_id},{outcome})"
        state = replace(state, mailbox=state.mailbox + (command,))

    elif action.startswith("replay(") and action.endswith(")"):
        slot_id = action[len("replay("):-1]
        slot = _get_slot(state, slot_id)
        if not slot or slot.outcome is None or slot.replayed:
            raise ValueError("replay refers to unavailable completion")
        state = _replace_slot(state, replace(slot, replayed=True))
        state = replace(state, mailbox=state.mailbox + (f"Deliver({slot_id},{slot.outcome})",))

    elif action == "publish(SigningOut)":
        state = _publish_view(state, ("SigningOut", None, None, None))
        state = replace(state, pc="reduceLogout")

    elif action == "reduce(Logout)":
        state, result = _manager_result(_load_spec(), state, {"event": "Logout"})
        slots = tuple(replace(slot, revoked=True) if slot.ident == state.active_slot else slot for slot in state.slots)
        state = replace(
            state,
            active_slot=None,
            slots=slots,
            pending_store=StoreIntent("Absent", "Logout", None, True),
            pending_view=("SignedOut", None, None, None),
            pending_status="Completed",
            pc="storePending",
            paused_at="store" if state.pause_armed == "store" else None,
        )

    elif action.startswith("store(") and action.endswith(")"):
        outcome = action[len("store("):-1]
        if outcome == "success":
            state = _store_success(state)
        elif outcome in {"failBefore", "failAfter"}:
            state = _store_failure(state, outcome, mutant)
        else:
            raise ValueError("unknown store outcome")

    elif action.startswith("publish(") and action.endswith(")"):
        phase = action[len("publish("):-1]
        if state.pending_view is None or state.pending_view[0] != phase:
            raise ValueError("publication does not match pending view")
        state = _publish_view(state, state.pending_view)
        if state.pc != "storePending":
            state = replace(state, pc="receiptPending")

    elif action.startswith("receipt(") and action.endswith(")"):
        if not state.running:
            raise ValueError("receipt without running command")
        command = state.running[0]
        kind = _command_kind(command)
        status = action[len("receipt("):-1].rsplit(",", 1)[1]
        invalid_logout = kind == "Logout" and status == "Completed" and not (state.store_observation == "Absent" and state.verified_store == "Absent" and state.managed == "Unauthenticated" and state.view_phase == "SignedOut")
        logout_completed = state.logout_completed or (kind == "Logout" and status == "Completed")
        logout_active = state.logout_active or (kind == "Logout" and status == "Completed")
        state = replace(
            state,
            logout_completed=logout_completed,
            logout_active=logout_active,
            last_receipt_invalid=invalid_logout,
            last_receipt_command=kind,
            last_receipt_status=status,
            running=(),
            pc="idle",
            pending_store=None,
            pending_view=None,
            pending_status="Completed",
            pause_armed=None,
            paused_at=None,
        )
        if kind == "Deliver" and state.last_delivery_stale:
            if state.last_delivery_slot:
                slot = _get_slot(state, state.last_delivery_slot)
                if slot and slot.replayed and slot.delivery_count >= 2 and _auth_projection(state) == state.delivery_pre_projection:
                    state = replace(state, coverage=state.coverage | {GOAL_NAMES["duplicate"]})
        if kind == "RetryCleanup" and status == "Completed":
            state = replace(state, coverage=state.coverage | {GOAL_NAMES["retry"]})
        if kind == "Bootstrap" and state.launch_ordinal == 2 and state.restart_had_credential and status == "Completed":
            state = replace(state, coverage=state.coverage | {GOAL_NAMES["restart"]})
        if kind == "Login(B)" and status == "Completed" and "queued-pause-seen" in state.coverage and state.physical_store == "B0" and state.view_phase == "SignedIn":
            state = replace(state, coverage=state.coverage | {GOAL_NAMES["queued"]})
        if kind == "Deliver" and state.last_delivery_stale:
            if state.logout_completed and not state.login_after_logout and state.last_delivery_outcome == "success":
                state = replace(state, coverage=state.coverage | {GOAL_NAMES["app02"]})
            if state.logout_completed and not state.login_after_logout and state.last_delivery_outcome == "failure":
                state = replace(state, coverage=state.coverage | {GOAL_NAMES["app03"]})
            if state.login_after_logout and state.current_login_account == "B" and state.last_delivery_outcome == "success":
                state = replace(state, coverage=state.coverage | {GOAL_NAMES["app04"]})
            if state.login_after_logout and state.current_login_account == "B" and state.last_delivery_outcome == "failure":
                state = replace(state, coverage=state.coverage | {GOAL_NAMES["app05"]})
            state = replace(state, last_delivery_stale=False, delivery_pre_projection=None)

    elif action == "deferredClear(old-logout)":
        old = next((slot for slot in state.slots if slot.account == "A"), None)
        state = replace(
            state,
            physical_store="Absent",
            store_observation="Absent",
            verified_store="Absent",
            view_phase="SignedOut",
            view_account=None,
            view_version=None,
            view_pending=None,
            last_write_authorized=False,
            last_write_cause="DeferredLogoutClear",
            last_write_slot=old.ident if old else None,
            deferred_clear_pending=False,
        )
        state = _bump_revision(state) or state

    else:
        raise ValueError(f"unknown model action {action!r}")

    state = _set_coverage(state)
    return state


def _invariant_violations(state):
    return _state_violations(state)


def replay_trace(actions, mutant=None, *, stop_on_target=True):
    """Replay a reported witness through the same transition relation used by BFS."""
    state = initial_state()
    trace = []
    violations = []
    targets = set(MUTANT_TARGETS.get(mutant, ()))
    for action in actions:
        previous = state
        state = apply_action(state, action, mutant)
        trace.append(action)
        violations.extend(_transition_violations(previous, action, state))
        if violations and (mutant is None or (stop_on_target and targets.intersection(violations))):
            break
    return {"state": _public_state(state), "violations": list(dict.fromkeys(violations)), "trace": trace}


def foreign_owner_step(spec, target, request_owner, event):
    """Apply the managed owner guard before numeric request-ID reduction."""
    if request_owner != target["ownerId"]:
        return dict(target), "ForeignRequest"
    result = managed_step(spec, target["state"], target["pendingRequestId"], target["nextRequestId"], event)
    return {
        "ownerId": target["ownerId"],
        "state": result["state"],
        "pendingRequestId": result["pendingRequestId"],
        "nextRequestId": result["nextRequestId"],
    }, result["rejection"]


def replay_foreign_owner_trace(actions):
    """Replay the explicit same-number, different-owner control history."""
    spec = _load_spec()
    owners = {
        "A": {"ownerId": "A", "state": "Authenticated", "pendingRequestId": None, "nextRequestId": 1},
        "B": {"ownerId": "B", "state": "Authenticated", "pendingRequestId": None, "nextRequestId": 1},
    }
    request_ids = {}
    rejection = None
    for action in actions:
        if action.startswith("issue(") and action.endswith(")"):
            owner, raw_id = action[len("issue("):-1].split(",", 1)
            result = managed_step(spec, owners[owner]["state"], owners[owner]["pendingRequestId"], owners[owner]["nextRequestId"], {"event": "TokenExpired"})
            effect = result["effects"][0]
            request_ids[owner] = effect["requestId"]
            owners[owner] = {"ownerId": owner, "state": result["state"], "pendingRequestId": result["pendingRequestId"], "nextRequestId": result["nextRequestId"]}
            if request_ids[owner] != int(raw_id):
                raise ValueError("foreign-owner witness request ID does not match the oracle")
        elif action.startswith("foreignDeliver(") and action.endswith(")"):
            args = dict(item.split("=", 1) for item in action[len("foreignDeliver("):-1].split(","))
            target, slot_owner, request_id = args["target"], args["slotOwner"], int(args["requestId"])
            before = dict(owners[target])
            after, rejection = foreign_owner_step(spec, before, owners[slot_owner]["ownerId"], {"event": "RefreshSucceeded", "requestId": request_id})
            if after != before:
                raise AssertionError("foreign request changed the target owner snapshot")
            owners[target] = after
        else:
            raise ValueError(f"unknown foreign-owner action {action!r}")
    return {"owners": owners, "requestIds": request_ids, "rejection": rejection}


def replay_coverage_witness(name, witness):
    """Replay one reported coverage witness and verify its actual final state.

    This is used by the integration protocol validator. Labels and trace length
    alone are not evidence: the trace must be enabled in the transition system,
    reach the named coverage predicate, and produce the reported state.
    """
    if name == "foreign-same-id":
        if not isinstance(witness, dict) or set(witness) != {
            "trace", "owners", "requestIds", "invariantResult", "final", "rejection"
        }:
            raise ValueError("malformed foreign-owner model witness")
        replayed = replay_foreign_owner_trace(witness["trace"])
        final = {"managed": replayed["owners"]["A"]}
        if (
            witness["owners"] != [replayed["owners"]["A"]["ownerId"], replayed["owners"]["B"]["ownerId"]]
            or witness["requestIds"] != [replayed["requestIds"]["A"], replayed["requestIds"]["B"]]
            or witness["invariantResult"] != "preserved"
            or witness["final"] != final
            or witness["rejection"] != "ForeignRequest"
            or replayed["rejection"] != "ForeignRequest"
        ):
            raise ValueError("foreign-owner witness disagrees with the managed reducer replay")
        if replayed["requestIds"] != {"A": 1, "B": 1}:
            raise ValueError("foreign-owner witness does not use equal numeric request IDs")
        return {"coverage": name, "finalState": final, "violations": []}

    if not isinstance(witness, dict) or set(witness) != {"trace", "finalState", "violation"}:
        raise ValueError(f"malformed coverage witness {name!r}")
    replayed = replay_trace(witness["trace"])
    if (
        replayed["trace"] != witness["trace"]
        or replayed["violations"]
        or witness["violation"] is not None
        or replayed["state"] != witness["finalState"]
    ):
        raise ValueError(f"coverage witness {name!r} disagrees with transition replay")

    state = initial_state()
    for action in witness["trace"]:
        state = apply_action(state, action)
    if name not in state.coverage:
        raise ValueError(f"trace does not reach named coverage predicate {name!r}")
    return {"coverage": name, "finalState": replayed["state"], "violations": []}


def _foreign_owner_witness():
    trace = ["issue(A,1)", "issue(B,1)", "foreignDeliver(target=A,slotOwner=B,requestId=1)"]
    replay = replay_foreign_owner_trace(trace)
    return {
        "trace": trace,
        "owners": [replay["owners"]["A"]["ownerId"], replay["owners"]["B"]["ownerId"]],
        "requestIds": [replay["requestIds"]["A"], replay["requestIds"]["B"]],
        "invariantResult": "preserved" if replay["rejection"] == "ForeignRequest" else "invalid",
        "final": {"managed": replay["owners"]["A"]},
        "rejection": replay["rejection"],
    }


def _trace_to(state, predecessor):
    actions = []
    current = state
    while True:
        previous, action = predecessor[current]
        if previous is None:
            break
        actions.append(action)
        current = previous
    actions.reverse()
    return actions


def _coverage_witness(state, predecessor):
    return {"trace": _trace_to(state, predecessor), "finalState": _public_state(state), "violation": None}


def _base_report(classification, explored, checked, witnesses, *, mutant=None, counterexample=None, missing=None, boundary=False, search_complete=False, limit_reached=False, unexpected_violations=None, unexpected_witnesses=None):
    return {
        "version": 1,
        "classification": classification,
        "mutant": mutant,
        "bounds": dict(BOUNDS),
        "exploredStates": explored,
        "invariantChecks": {"statesExamined": checked, "violations": [] if classification == "PASS" else []},
        "coverageBoundary": boundary,
        "coverageExhaustiveWithinBound": search_complete and not limit_reached,
        "searchComplete": search_complete,
        "limitReached": limit_reached,
        "abstraction": {
            "environment": "bounded to scenario-relevant Login(A/B), Expire, Logout, CancelRefresh, held/replayed delivery, RetryCleanup, restart, and named phase pauses",
            "excludedNoOps": ["Observe projections", "busy Login attempts unrelated to stale-response authority", "arbitrary wall-clock/network scheduling"],
            "execution": "each app command advances through explicit begin, reducer, store, verification, UI publication, and receipt phases",
        },
        "claims": {"unboundedLiveness": False, "arbitraryNativeRefinement": False},
        "witnesses": witnesses,
        "counterexample": counterexample,
        "missingCoverage": missing or [],
        "unexpectedMutantViolations": unexpected_violations or [],
        "unexpectedMutantWitnesses": unexpected_witnesses or {},
    }


def _search(mutant=None):
    """Return a defensive copy of the memoized finite search result."""
    return deepcopy(_search_cached(mutant, MAX_STATES))


@lru_cache(maxsize=12)
def _search_cached(mutant=None, max_states=MAX_STATES):
    required = set(GOAL_NAMES.values()) | {"foreign-same-id"}
    initial = initial_state()
    frontier = deque([initial])
    predecessor = {initial: (None, None)}
    witnesses = {"foreign-same-id": _foreign_owner_witness()}
    checked = 0
    boundary = False
    limit_reached = False
    unexpected_mutant_violations = set()
    unexpected_mutant_witnesses = {}
    counterexample = None
    while frontier:
        current = frontier.popleft()
        checked += 1
        for action in enabled_actions(current, mutant):
            following = apply_action(current, action, mutant)
            violations = _transition_violations(current, action, following)
            if violations:
                if mutant:
                    trace = _trace_to(current, predecessor) + [action]
                    targets = set(MUTANT_TARGETS[mutant])
                    for invariant in violations:
                        if invariant in targets:
                            if counterexample is None:
                                primary = next(label for label in MUTANT_TARGETS[mutant] if label in violations)
                                counterexample = {
                                    "invariant": primary,
                                    "trace": trace,
                                    "finalState": _public_state(following),
                                }
                        else:
                            unexpected_mutant_violations.add(invariant)
                            unexpected_mutant_witnesses.setdefault(
                                invariant,
                                {"trace": trace, "finalState": _public_state(following)},
                            )
                else:
                    return {
                        "classification": "SEMANTIC_FAIL",
                        "exploredStates": len(predecessor),
                        "statesExamined": checked,
                        "counterexample": {"invariant": violations[0], "trace": _trace_to(current, predecessor) + [action], "finalState": _public_state(following)},
                        "witnesses": witnesses,
                        "boundary": boundary,
                        "missingCoverage": [],
                    }
            if following not in predecessor:
                predecessor[following] = (current, action)
                frontier.append(following)
                for name in following.coverage:
                    if name in required and name not in witnesses:
                        witnesses[name] = _coverage_witness(following, predecessor)
                if following.dequeued >= BOUNDS["dequeuedCommands"] or following.revision >= BOUNDS["uiRevisions"] or following.epoch_count >= BOUNDS["epochs"] or max(following.next_ids) > BOUNDS["requestIdsPerOwner"]:
                    boundary = True
                if len(predecessor) >= max_states:
                    limit_reached = True
                    if mutant and counterexample is not None:
                        return {
                            "classification": "SEMANTIC_FAIL",
                            "exploredStates": len(predecessor),
                            "statesExamined": checked,
                            "counterexample": counterexample,
                            "witnesses": witnesses,
                            "boundary": True,
                            "searchComplete": False,
                            "limitReached": True,
                            "missingCoverage": sorted(required - witnesses.keys()),
                            "unexpectedViolations": sorted(unexpected_mutant_violations),
                            "unexpectedWitnesses": unexpected_mutant_witnesses,
                        }
                    return {
                        "classification": "INCONCLUSIVE",
                        "exploredStates": len(predecessor),
                        "statesExamined": checked,
                        "counterexample": None,
                        "witnesses": witnesses,
                        "boundary": True,
                        "searchComplete": False,
                        "limitReached": True,
                        "missingCoverage": sorted(required - witnesses.keys()),
                        "unexpectedViolations": sorted(unexpected_mutant_violations),
                        "unexpectedWitnesses": unexpected_mutant_witnesses,
                    }
    if mutant:
        if counterexample is not None:
            return {
                "classification": "SEMANTIC_FAIL",
                "exploredStates": len(predecessor),
                "statesExamined": checked,
                "counterexample": counterexample,
                "witnesses": witnesses,
                "boundary": boundary,
                "searchComplete": True,
                "limitReached": False,
                "unexpectedViolations": sorted(unexpected_mutant_violations),
                "unexpectedWitnesses": unexpected_mutant_witnesses,
                "missingCoverage": [],
            }
        return {
            "classification": "INCONCLUSIVE",
            "exploredStates": len(predecessor),
            "statesExamined": checked,
            "counterexample": None,
            "witnesses": witnesses,
            "boundary": boundary,
            "searchComplete": True,
            "limitReached": limit_reached,
            "unexpectedViolations": sorted(unexpected_mutant_violations),
            "unexpectedWitnesses": unexpected_mutant_witnesses,
            "missingCoverage": [f"mutant witness not found: {mutant}"],
        }
    missing = sorted(required - witnesses.keys())
    return {
        "classification": "PASS" if not missing else "INCONCLUSIVE",
        "exploredStates": len(predecessor),
        "statesExamined": checked,
        "counterexample": None,
        "witnesses": witnesses,
        "boundary": boundary,
        "searchComplete": not limit_reached,
        "limitReached": limit_reached,
        "missingCoverage": missing,
        "unexpectedViolations": sorted(unexpected_mutant_violations),
        "unexpectedWitnesses": unexpected_mutant_witnesses,
    }


def explore(*, output: Path, mutant: str | None = None) -> dict:
    """Exhaust the explicit finite transition system and write its evidence report."""
    allowed = {"unconditional-success-commit", "reentrant-consumer", "duplicate-deferred-clear", "unverified-publish", "failed-clear-ack"}
    if mutant is not None and mutant not in allowed:
        raise ValueError(f"unknown model mutant {mutant!r}")
    search = _search(mutant)
    report = _base_report(
        search["classification"],
        search["exploredStates"],
        search["statesExamined"],
        search["witnesses"],
        mutant=mutant,
        counterexample=search["counterexample"],
        missing=search["missingCoverage"],
        boundary=search["boundary"],
        search_complete=search.get("searchComplete", False),
        limit_reached=search.get("limitReached", False),
        unexpected_violations=search.get("unexpectedViolations", []),
        unexpected_witnesses=search.get("unexpectedWitnesses", {}),
    )
    report["invariantChecks"]["violations"] = [] if search["classification"] == "PASS" else ([search["counterexample"]["invariant"]] if search["counterexample"] else [])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mutant", choices=("unconditional-success-commit", "reentrant-consumer", "duplicate-deferred-clear", "unverified-publish", "failed-clear-ack"))
    args = parser.parse_args(argv)
    try:
        report = explore(output=Path(args.output), mutant=args.mutant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"classification": "INFRA_FAILURE", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"classification": report["classification"], "exploredStates": report["exploredStates"], "counterexample": report["counterexample"], "missingCoverage": report["missingCoverage"]}, sort_keys=True))
    if report["classification"] == "PASS":
        return 0
    if report["classification"] == "SEMANTIC_FAIL":
        return 1
    if report["classification"] == "INFRA_FAILURE":
        return 2
    return 3


if __name__ == "__main__":
    sys.exit(main())
