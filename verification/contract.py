"""Independent interpreter and finite-machine validator for specification.json."""
from itertools import product


def _schema_errors(value, schema, root, path="$", defs=None):
    """Validate the JSON Schema subset used by contract/schema.json."""
    defs = defs if defs is not None else root.get("$defs", {})
    errors = []
    if not isinstance(schema, dict): return [f"{path}: schema node must be an object"]
    supported = {"$ref", "type", "const", "minimum", "minItems", "uniqueItems", "items", "required",
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
