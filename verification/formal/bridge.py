"""Strict JSON projection and fail-closed parser for TLC's text state dump."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tla_string(value):
    # TLA+ quoted strings accept these escapes; reject control characters with no
    # unambiguous encoding rather than emitting a potentially altered atom.
    out = []
    for char in value:
        code = ord(char)
        if char == '"': out.append('\\"')
        elif char == "\\": out.append("\\\\")
        elif char == "\n": out.append("\\n")
        elif char == "\r": out.append("\\r")
        elif char == "\t": out.append("\\t")
        elif code < 0x20 or 0x7f <= code < 0xa0:
            raise ValueError(f"unsupported control character U+{code:04X} in TLA string")
        else: out.append(char)
    return '"' + "".join(out) + '"'


def _seq(items):
    return "<< " + ", ".join(tla_string(x) for x in items) + " >>"


def _set(items):
    return "{ " + ", ".join(tla_string(x) for x in items) + " }"


def render_data(spec):
    states = _set(spec["states"])
    events = _set(spec["events"])
    effects = _set(spec["effects"])
    rows = ",\n  ".join("<< %s, %s, %s, %s >>" % (
        tla_string(row["state"]), tla_string(row["event"]), tla_string(row["nextState"]), _seq(row["effects"]))
        for row in spec["transitions"])
    return ("---------------- MODULE ContractData ----------------\n"
            "EXTENDS Sequences\n"
            f"States == {states}\nEvents == {events}\nEffects == {effects}\n"
            f"InitialState == {tla_string(spec['initialState'])}\n"
            f"MaxEffects == {spec['invariants']['maxEffectsPerStep']}\n"
            f"Transitions == {{\n  {rows}\n}}\n"
            "==============================\n")


def expected_observations(spec):
    rows = {(r["nextState"], r["event"], r["state"], tuple(r["effects"])) for r in spec["transitions"]}
    rows.add((spec["initialState"], "__initial__", spec["initialState"], ()))
    return rows


_VAR = {"state", "previousState", "event", "effects"}
_STRING = r'"(?:[^"\\]|\\["\\nrt])*"'
_HEADER = __import__("re").compile(r'^State (\d+):$')
_LINE = __import__("re").compile(r'^/\\ (state|previousState|event|effects) = (.*)$')
_STR = __import__("re").compile(r'^' + _STRING + r'$')
_TRACE_HEADER = re.compile(r'^State (\d+):(?: <[^\n]*>)?$')
_TRACE_SUMMARY = re.compile(r'^\d+ states generated, \d+ distinct states found, \d+ states left on queue\.$')


def _decode_string(token):
    if not _STR.fullmatch(token): raise ValueError("malformed string in TLC dump")
    body = token[1:-1]
    result = []
    i = 0
    while i < len(body):
        if body[i] == "\\":
            i += 1
            escapes = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
            if i == len(body) or body[i] not in escapes: raise ValueError("unsupported string escape in TLC dump")
            result.append(escapes[body[i]])
        else: result.append(body[i])
        i += 1
    return "".join(result)


def _parse_effects(value):
    if value == "<<>>": return ()
    if not value.startswith("<<") or not value.endswith(">>"): raise ValueError("malformed effects sequence")
    inner = value[2:-2]
    tokens = []
    pos = 0
    while pos < len(inner):
        match = __import__("re").match(_STRING, inner[pos:])
        if not match: raise ValueError("malformed effects item")
        tokens.append(_decode_string(match.group(0)))
        pos += match.end()
        if pos < len(inner):
            if inner[pos] != ",": raise ValueError("malformed effects separator")
            pos += 1
            if pos == len(inner): raise ValueError("trailing effects separator")
    return tuple(tokens)


def parse_dump(text):
    states = {}
    for line in text.splitlines():
        if not line:
            continue
        head = _HEADER.fullmatch(line)
        if head:
            index = int(head.group(1))
            if index in states: raise ValueError("duplicate state index in TLC dump")
            states[index] = {}
            continue
        match = _LINE.fullmatch(line)
        if not match: raise ValueError(f"unexpected TLC dump line: {line!r}")
        if not states: raise ValueError("variable before state header")
        index = next(reversed(states))
        var, raw = match.group(1), match.group(2)
        if var not in _VAR: raise ValueError("unknown state variable")
        if var in states.setdefault(index, {}): raise ValueError("duplicate variable in TLC dump")
        states[index][var] = _parse_effects(raw) if var == "effects" else _decode_string(raw)
    observations = set()
    if not states: raise ValueError("empty TLC state dump")
    for index, values in states.items():
        if set(values) != _VAR: raise ValueError(f"state {index} has missing variables")
        obs = (values["state"], values["event"], values["previousState"], values["effects"])
        if obs in observations: raise ValueError("duplicate transition observation in TLC dump")
        observations.add(obs)
    return observations


def compare_dump(text, expected):
    actual = parse_dump(text)
    missing, extra = expected - actual, actual - expected
    if missing or extra: raise ValueError(f"TLC dump mismatch; missing={sorted(missing)!r}, extra={sorted(extra)!r}")
    return actual


def parse_counterexample(text):
    """Parse TLC's annotated behavior trace, failing closed on incomplete states."""
    marker = "Error: The behavior up to this point is:\n"
    if marker not in text: raise ValueError("TLC counterexample behavior marker is missing")
    lines = text.split(marker, 1)[1].splitlines()
    states = []
    pos = 0
    while pos < len(lines):
        while pos < len(lines) and not lines[pos]: pos += 1
        if pos == len(lines): break
        header = _TRACE_HEADER.fullmatch(lines[pos])
        if not header:
            if states and _TRACE_SUMMARY.fullmatch(lines[pos]): break
            raise ValueError(f"malformed TLC counterexample line: {lines[pos]!r}")
        if int(header.group(1)) != len(states) + 1:
            raise ValueError("nonsequential TLC counterexample state index")
        pos += 1
        values = {}
        while pos < len(lines) and lines[pos].startswith("/\\ "):
            match = _LINE.fullmatch(lines[pos])
            if not match: raise ValueError(f"malformed TLC counterexample variable: {lines[pos]!r}")
            var, raw = match.group(1), match.group(2)
            if var in values: raise ValueError(f"duplicate counterexample variable {var}")
            values[var] = _parse_effects(raw) if var == "effects" else _decode_string(raw)
            pos += 1
        if set(values) != _VAR: raise ValueError(f"counterexample state {header.group(1)} is incomplete")
        states.append((values["state"], values["event"], values["previousState"], values["effects"]))
    if not states: raise ValueError("TLC counterexample contains no states")
    return states
