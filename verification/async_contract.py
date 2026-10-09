"""Independent async JSON contract oracle, generators, and strict wire validators."""
from itertools import product

from verification.contract import validate_async

SIMPLE = ("LoginSucceeded", "Logout", "TokenExpired")
RESPONSES = ("RefreshSucceeded", "RefreshFailed")
MAX_ID = 9223372036854775807


def validate(spec, schema):
    from verification.contract import validate as validate_core
    validate_core(spec, schema)
    return validate_async(spec, spec["async"])


def _event_object(event, events):
    if isinstance(event, str):
        if event not in SIMPLE or event not in events:
            raise ValueError(f"unknown or malformed simple event {event!r}")
        return {"event": event}
    if not isinstance(event, dict) or set(event) not in ({"event"}, {"event", "requestId"}):
        raise ValueError("event object must contain event and optional requestId only")
    name = event["event"]
    if name in SIMPLE and set(event) == {"event"}:
        if name not in events: raise ValueError(f"unknown event {name!r}")
        return {"event": name}
    if set(event) != {"event", "requestId"}:
        raise ValueError("response event must contain exactly event and requestId")
    ident = event["requestId"]
    if name not in RESPONSES or name not in events:
        raise ValueError(f"unknown or malformed response event {name!r}")
    if type(ident) is not int or not 1 <= ident <= MAX_ID:
        raise ValueError("requestId must be a positive signed64 integer token")
    return {"event": name, "requestId": ident}


def validate_input(document, spec):
    profile = spec["async"]
    if not isinstance(document, dict) or set(document) != {"scenarios"} or not isinstance(document["scenarios"], list):
        raise ValueError("input document must contain only scenarios array")
    seen, cleaned = set(), []
    for scenario in document["scenarios"]:
        if not isinstance(scenario, dict) or set(scenario) - {"scenario", "events", "nextRequestId"} or not {"scenario", "events"} <= set(scenario):
            raise ValueError("scenario must contain scenario/events and optional nextRequestId only")
        name, events = scenario["scenario"], scenario["events"]
        if not isinstance(name, str): raise ValueError("scenario must be string")
        if name in seen: raise ValueError(f"duplicate scenario id {name!r}")
        seen.add(name)
        if not isinstance(events, list): raise ValueError("events must be array")
        seed = scenario.get("nextRequestId", profile["initialNextRequestId"])
        if type(seed) is not int or not profile["requestIdMin"] <= seed <= profile["requestIdMax"]:
            raise ValueError("nextRequestId must be a positive signed64 integer token")
        cleaned.append({"scenario": name, "events": [_event_object(event, spec["events"]) for event in events], "nextRequestId": seed})
    return cleaned


def exhaustive_scenarios(spec):
    profile = spec["async"]
    alphabet = []
    for event in spec["events"]:
        if event in RESPONSES:
            alphabet.extend({"event": event, "requestId": ident} for ident in profile["verification"]["responseIds"])
        else:
            alphabet.append({"event": event})
    for length in range(profile["verification"]["exhaustiveMaxLength"] + 1):
        for index, sequence in enumerate(product(alphabet, repeat=length)):
            yield {"scenario": f"a{length:02d}-{index:05d}", "events": list(sequence)}


def named_scenarios(spec):
    return [
        {"scenario": "old-success-after-new-request", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, {"event": "RefreshSucceeded", "requestId": 2}]},
        {"scenario": "old-failure-after-new-request", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "TokenExpired", {"event": "RefreshFailed", "requestId": 1}, {"event": "RefreshFailed", "requestId": 2}]},
        {"scenario": "old-reply-after-logout-login", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "Logout", "LoginSucceeded", {"event": "RefreshSucceeded", "requestId": 1}]},
        {"scenario": "old-success-after-accepted-logout-with-new-request", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "Logout", "LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, {"event": "RefreshSucceeded", "requestId": 2}]},
        {"scenario": "old-failure-after-accepted-logout-with-new-request", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "Logout", "LoginSucceeded", "TokenExpired", {"event": "RefreshFailed", "requestId": 1}, {"event": "RefreshFailed", "requestId": 2}]},
        {"scenario": "accepted-logout-counter-never-resets", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, "Logout", "LoginSucceeded", "TokenExpired"]},
        {"scenario": "duplicate-completion", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 1}, {"event": "RefreshSucceeded", "requestId": 1}]},
        {"scenario": "future-unissued-id", "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 2}]},
        {"scenario": "repeated-login", "events": ["LoginSucceeded", "LoginSucceeded", "LoginSucceeded"]},
        {"scenario": "refreshing-logout-ignored", "events": ["LoginSucceeded", "TokenExpired", "Logout", {"event": "RefreshSucceeded", "requestId": 1}]},
        {"scenario": "allocate-signed64-maximum", "nextRequestId": MAX_ID, "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": MAX_ID}, "TokenExpired"]},
        {"scenario": "allocate-final-two-signed64-ids", "nextRequestId": MAX_ID - 1, "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": MAX_ID - 1}, "TokenExpired", {"event": "RefreshSucceeded", "requestId": MAX_ID}, "TokenExpired"]},
        {"scenario": "cross-json-safe-integer-boundary", "nextRequestId": 9007199254740991, "events": ["LoginSucceeded", "TokenExpired", {"event": "RefreshSucceeded", "requestId": 9007199254740991}, "TokenExpired", {"event": "RefreshSucceeded", "requestId": 9007199254740992}]},
    ]


def oracle(scenario, raw_events, spec, next_request_id=None):
    profile = spec["async"]
    events = [_event_object(event, spec["events"]) for event in raw_events]
    state, pending = profile["initialState"], None
    next_id = profile["initialNextRequestId"] if next_request_id is None else next_request_id
    steps = []
    for event in events:
        name = event["event"]
        row = next(row for row in profile["transitions"] if row["state"] == state and row["event"] == name)
        response_id = event.get("requestId")
        active = row["guard"] == "always" or (state == "Refreshing" and pending is not None and response_id == pending)
        effects, rejection = [], None
        if active:
            if row["pendingAction"] == "allocate" and next_id is None:
                rejection = profile["exhaustionRejection"]
            else:
                state = row["nextState"]
                if row["pendingAction"] == "clear": pending = None
                elif row["pendingAction"] == "allocate":
                    allocated = next_id
                    pending = allocated
                    next_id = None if allocated == profile["requestIdMax"] else allocated + 1
                for effect in row["effects"]:
                    effects.append({"effect": effect, **({"requestId": allocated} if effect == "RequestTokenRefresh" else {})})
        steps.append({"event": event, "state": state, "pendingRequestId": pending, "effects": effects, "rejection": rejection})
    return {"scenario": scenario, "steps": steps}


def expected_traces(spec):
    inputs = list(exhaustive_scenarios(spec)) + named_scenarios(spec)
    inputs = [{"scenario": row["scenario"], "events": [_event_object(event, spec["events"]) for event in row["events"]], **({"nextRequestId": row["nextRequestId"]} if "nextRequestId" in row else {})} for row in inputs]
    expected = [oracle(row["scenario"], row["events"], spec, row.get("nextRequestId")) for row in inputs]
    return expected, inputs


def _wire_shape_errors(document, expected, spec=None):
    errors = []
    if not isinstance(document, dict) or set(document) != {"traces"} or not isinstance(document["traces"], list):
        return ["document must contain only traces array"]
    actual = document["traces"]
    if len(actual) != len(expected): errors.append(f"trace count expected {len(expected)} got {len(actual)}")
    states = set(spec["states"]) if spec else {step.get("state") for trace in expected for step in trace.get("steps", [])}
    effects_allowed = set(spec["effects"]) if spec else {effect.get("effect") for trace in expected for step in trace.get("steps", []) for effect in step.get("effects", []) if isinstance(effect, dict)}
    rejection_allowed = spec["async"]["exhaustionRejection"] if spec else "RequestIdExhausted"
    for i, trace in enumerate(actual):
        if not isinstance(trace, dict) or set(trace) != {"scenario", "steps"}:
            errors.append(f"trace[{i}] must contain exactly scenario and steps"); continue
        if not isinstance(trace["scenario"], str) or not isinstance(trace["steps"], list):
            errors.append(f"trace[{i}] has invalid scenario/steps type"); continue
        if i >= len(expected):
            errors.append(f"trace[{i}] is unexpected")
            continue
        exp = expected[i]
        if trace["scenario"] != exp["scenario"]: errors.append(f"trace[{i}] scenario mismatch")
        if len(trace["steps"]) != len(exp["steps"]): errors.append(f"{trace['scenario']}: step count mismatch")
        for j, step in enumerate(trace["steps"]):
            if not isinstance(step, dict) or set(step) != {"event", "state", "pendingRequestId", "effects", "rejection"}:
                errors.append(f"{trace['scenario']} step {j}: invalid or extra/missing fields"); continue
            if j >= len(exp["steps"]): continue
            want = exp["steps"][j]
            try:
                actual_event = _event_object(step["event"], ("LoginSucceeded", "Logout", "TokenExpired", "RefreshSucceeded", "RefreshFailed"))
            except (ValueError, TypeError, KeyError):
                actual_event = None
            if actual_event is None or actual_event != want["event"]:
                errors.append(f"{trace['scenario']} step {j}: event mismatch")
            if not isinstance(step["state"], str) or step["state"] not in states: errors.append(f"{trace['scenario']} step {j}: state outside declared domain")
            pending = step["pendingRequestId"]
            if pending is not None and (type(pending) is not int or not 1 <= pending <= MAX_ID): errors.append(f"{trace['scenario']} step {j}: invalid pendingRequestId")
            effects = step["effects"]
            if not isinstance(effects, list): errors.append(f"{trace['scenario']} step {j}: effects must be array")
            else:
                for effect in effects:
                    if not isinstance(effect, dict) or set(effect) not in ({"effect"}, {"effect", "requestId"}):
                        errors.append(f"{trace['scenario']} step {j}: malformed effect object"); break
                    if not isinstance(effect.get("effect"), str) or effect["effect"] not in effects_allowed:
                        errors.append(f"{trace['scenario']} step {j}: effect outside declared domain"); break
                    if (effect["effect"] == "RequestTokenRefresh") != (set(effect) == {"effect", "requestId"}):
                        errors.append(f"{trace['scenario']} step {j}: effect has invalid requestId shape"); break
                    if "requestId" in effect and (type(effect["requestId"]) is not int or not 1 <= effect["requestId"] <= MAX_ID):
                        errors.append(f"{trace['scenario']} step {j}: invalid effect requestId"); break
            rejection = step["rejection"]
            if rejection is not None and (not isinstance(rejection, str) or rejection != rejection_allowed): errors.append(f"{trace['scenario']} step {j}: invalid rejection")
    return errors


def validate_output(document, expected, spec=None):
    errors = _wire_shape_errors(document, expected, spec)
    if errors: return errors
    for i, (trace, want_trace) in enumerate(zip(document["traces"], expected)):
        if trace["scenario"] != want_trace["scenario"]: errors.append(f"trace[{i}] scenario mismatch")
        for j, (step, want) in enumerate(zip(trace["steps"], want_trace["steps"])):
            for field in ("event", "state", "pendingRequestId", "effects", "rejection"):
                if step[field] != want[field]: errors.append(f"{trace['scenario']} step {j}: {field} mismatch")
    return errors


def compare_documents(left, right, expected_shape, spec=None):
    errors = []
    for label, document in (("left", left), ("right", right)):
        shape_errors = _wire_shape_errors(document, expected_shape, spec)
        errors.extend(f"{label}: {error}" for error in shape_errors)
    if errors: return errors
    if left["traces"] != right["traces"]: errors.append("native traces differ")
    return errors


def compare(expected, actual):
    errors = validate_output({"traces": actual}, expected)
    return errors
