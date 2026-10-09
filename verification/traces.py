"""Trace oracle and strict structural comparator."""


def oracle(scenario_id, events, initial_state, machine):
    state, steps = initial_state, []
    for event in events:
        if not isinstance(event, str): raise ValueError("event names must be strings")
        try: state, effects = machine[(state, event)]
        except KeyError: raise ValueError(f"unknown event: {event}") from None
        steps.append({"event": event, "state": state, "effects": list(effects)})
    return {"scenario": scenario_id, "steps": steps}


def compare(expected, actual):
    errors = []
    if not isinstance(expected, list):
        errors.append("expected traces must be an array")
        expected = []
    if not isinstance(actual, list):
        errors.append("actual traces must be an array")
        actual = []
    def index(rows, label):
        indexed = {}
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != {"scenario", "steps"}:
                errors.append(f"{label} trace[{i}] malformed fields"); continue
            sid = row["scenario"]
            if not isinstance(sid, str): errors.append(f"{label} trace[{i}] scenario must be string"); continue
            if not isinstance(row["steps"], list): errors.append(f"{label} scenario {sid}: steps must be an array")
            elif any(not isinstance(step, dict) or set(step) != {"event", "state", "effects"} or
                     not isinstance(step.get("event"), str) or not isinstance(step.get("state"), str) or
                     not isinstance(step.get("effects"), list) or
                     any(not isinstance(effect, str) for effect in step.get("effects", []))
                     for step in row["steps"]):
                errors.append(f"{label} scenario {sid}: malformed step fields or types")
            if sid in indexed: errors.append(f"{label} duplicate scenario {sid}")
            indexed[sid] = row
        return indexed
    exp, got = index(expected, "expected"), index(actual, "actual")
    expected_order = [row.get("scenario") for row in expected if isinstance(row, dict)]
    actual_order = [row.get("scenario") for row in actual if isinstance(row, dict)]
    if expected_order != actual_order:
        errors.append("trace scenario order differs from expected order")
    for sid in sorted(exp.keys() - got.keys()): errors.append(f"missing scenario {sid}")
    for sid in sorted(got.keys() - exp.keys()): errors.append(f"extra scenario {sid}")
    for sid in sorted(exp.keys() & got.keys()):
        e_steps, a_steps = exp[sid]["steps"], got[sid]["steps"]
        if not isinstance(e_steps, list) or not isinstance(a_steps, list):
            errors.append(f"scenario {sid}: steps must be arrays"); continue
        if len(e_steps) != len(a_steps): errors.append(f"scenario {sid}: step count {len(a_steps)} != {len(e_steps)}")
        for i, (e, a) in enumerate(zip(e_steps, a_steps)):
            if not isinstance(a, dict) or set(a) != {"event", "state", "effects"}:
                errors.append(f"scenario {sid} step {i}: malformed fields"); continue
            for key in ("event", "state", "effects"):
                if a[key] != e[key]: errors.append(f"scenario {sid} step {i}: {key}; expected={e[key]!r}; actual={a[key]!r}")
    return errors
