"""Independent interpreter and finite-machine validator for specification.json."""
from itertools import product


def _schema_errors(value, schema, root, path="$", defs=None):
    """Validate the JSON Schema subset used by contract/schema.json."""
    defs = defs if defs is not None else root.get("$defs", {})
    errors = []
    if not isinstance(schema, dict): return [f"{path}: schema node must be an object"]
    supported = {"$ref", "type", "const", "enum", "minimum", "minItems", "uniqueItems", "items", "required",
                 "additionalProperties", "properties", "$defs", "$schema", "title"}
    unknown = set(schema) - supported
    if unknown: return [f"{path}: unsupported schema keyword(s): {', '.join(sorted(unknown))}"]
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in defs:
            return [f"{path}: unsupported or unresolved schema reference {ref!r}"]
        target = defs[ref[8:]]
        return _schema_errors(value, target, root, path, defs)
    typ = schema.get("type")
    is_int = isinstance(value, int) and not isinstance(value, bool)
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "integer": is_int, "boolean": isinstance(value, bool)}
    if typ and not matches.get(typ, False):
        return [f"{path}: expected {typ}"]
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum {schema['enum']!r}")
    if "minimum" in schema and is_int and value < schema["minimum"]:
        errors.append(f"{path}: below minimum {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): errors.append(f"{path}: too few items")
        if schema.get("uniqueItems") and len(value) != len(set(map(repr, value))): errors.append(f"{path}: duplicate items")
        if "items" in schema:
            for i, item in enumerate(value): errors.extend(_schema_errors(item, schema["items"], root, f"{path}[{i}]", defs))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: errors.append(f"{path}: missing required property {key}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key not in props and schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key}")
            elif key in props: errors.extend(_schema_errors(item, props[key], root, f"{path}.{key}", defs))
    return errors


def validate(spec, schema):
    errors = _schema_errors(spec, schema, schema)
    if errors: raise ValueError("schema validation failed: " + "; ".join(errors))
    states, events, effects = spec["states"], spec["events"], spec["effects"]
    if spec["initialState"] not in states: raise ValueError("initialState is outside declared states")
    expected = set(product(states, events))
    table = {}
    actual_max_effects = 0
    for row in spec["transitions"]:
        pair = (row["state"], row["event"])
        if pair not in expected: raise ValueError(f"transition domain contains undeclared pair {pair}")
        if pair in table: raise ValueError(f"duplicate transition for {pair}")
        if row["nextState"] not in states: raise ValueError(f"nextState outside declared states for {pair}")
        if any(effect not in effects for effect in row["effects"]): raise ValueError(f"effect outside declared set for {pair}")
        if len(row["effects"]) > spec["invariants"]["maxEffectsPerStep"]: raise ValueError("maxEffectsPerStep exceeded")
        actual_max_effects = max(actual_max_effects, len(row["effects"]))
        table[pair] = (row["nextState"], row["effects"])
    missing = expected - table.keys()
    if missing: raise ValueError(f"missing transition for {sorted(missing)[0]}")
    if actual_max_effects != spec["invariants"]["maxEffectsPerStep"]:
        raise ValueError(f"maxEffectsPerStep declares {spec['invariants']['maxEffectsPerStep']} but actual maximum is {actual_max_effects}")
    invariants = spec["invariants"]
    if not all((invariants["totalTransitionFunction"], invariants["stateInDeclaredSet"], invariants["effectsInDeclaredSet"])):
        raise ValueError("declared invariants must be true")
    if spec["exhaustiveMaxLength"] != 4: raise ValueError("exhaustiveMaxLength must be 4")
    reachable = {spec["initialState"]}
    changed = True
    while changed:
        expanded = reachable | {nxt for (state, _), (nxt, _) in table.items() if state in reachable}
        changed = expanded != reachable
        reachable = expanded
    if reachable != set(states): raise ValueError(f"unreachable states: {sorted(set(states) - reachable)}")
    exercised = {(s, e) for scenario in scenarios(spec) for s, e in _walk(scenario, spec["initialState"], table)}
    if exercised != expected: raise ValueError("length-0..4 scenarios do not cover all transition pairs")
    if "async" in spec:
        validate_async(spec, spec["async"])
    return table


def validate_async(spec, profile):
    """Check correlation-specific meanings that JSON Schema cannot express."""
    states, events, effects = spec["states"], spec["events"], spec["effects"]
    if profile["initialState"] != spec["initialState"]:
        raise ValueError("async initialState must match core initialState")
    if profile["initialPendingRequestId"] is not None:
        raise ValueError("async initialPendingRequestId must be null")
    lo, hi = profile["requestIdMin"], profile["requestIdMax"]
    if hi != 9223372036854775807 or lo != 1:
        raise ValueError("async request ID range must be positive signed64")
    if not lo <= profile["initialNextRequestId"] <= hi:
        raise ValueError("async initialNextRequestId outside request ID range")
    if profile["exhaustionRejection"] != "RequestIdExhausted":
        raise ValueError("async exhaustion rejection must be RequestIdExhausted")
    rows = profile["transitions"]
    domain = set(product(states, events))
    table = {}
    response_events = {"RefreshSucceeded", "RefreshFailed"}
    for row in rows:
        pair = (row["state"], row["event"])
        if pair not in domain:
            raise ValueError(f"async transition domain contains undeclared pair {pair}")
        if pair in table:
            raise ValueError(f"duplicate async transition for {pair}")
        if row["nextState"] not in states or any(effect not in effects for effect in row["effects"]):
            raise ValueError(f"async transition contains undeclared state/effect for {pair}")
        response = row["event"] in response_events
        if row["guard"] != ("activeResponse" if response else "always"):
            raise ValueError(f"async guard incoherent for {pair}")
        expected_action = ("allocate" if pair == ("Authenticated", "TokenExpired") else
                           "clear" if pair in {("Authenticated", "Logout"), ("Refreshing", "RefreshSucceeded"), ("Refreshing", "RefreshFailed")} else
                           "preserve")
        if row["pendingAction"] != expected_action:
            raise ValueError(f"async pending action incoherent for {pair}")
        resulting_pending = row["pendingAction"] == "allocate" or (row["pendingAction"] == "preserve" and row["state"] == "Refreshing")
        if (row["nextState"] == "Refreshing") != resulting_pending:
            raise ValueError(f"async pending iff Refreshing violated for {pair}")
        if pair == ("Refreshing", "Logout") and (row["nextState"] != "Refreshing" or row["pendingAction"] != "preserve" or row["effects"]):
            raise ValueError("async Refreshing Logout must preserve pending request and have no effects")
        table[pair] = row
    core_rows = {(row["state"], row["event"]): (row["nextState"], row["effects"]) for row in spec["transitions"]}
    for pair, row in table.items():
        if (row["nextState"], row["effects"]) != core_rows[pair]:
            raise ValueError(f"async action disagrees with core row for {pair}")
    missing = domain - table.keys()
    if missing:
        raise ValueError(f"missing async transition for {sorted(missing)[0]}")
    if set(events) - response_events != {"LoginSucceeded", "Logout", "TokenExpired"} or not response_events <= set(events):
        raise ValueError("async event alphabet must contain three simple and two response events")
    if profile["verification"]["exhaustiveMaxLength"] != 5:
        raise ValueError("async exhaustiveMaxLength must be 5")
    ids = profile["verification"]["responseIds"]
    if ids != [1, 2]:
        raise ValueError("async responseIds must be [1, 2]")
    if not any(row["pendingAction"] == "allocate" and "RequestTokenRefresh" in row["effects"] for row in rows):
        raise ValueError("async allocation must emit RequestTokenRefresh")
    return table


def _walk(events, initial, table):
    state = initial
    pairs = []
    for event in events:
        pairs.append((state, event))
        state = table[(state, event)][0]
    return pairs


def scenarios(spec):
    events = spec["events"]
    for length in range(spec["exhaustiveMaxLength"] + 1):
        for seq in product(events, repeat=length):
            yield seq
