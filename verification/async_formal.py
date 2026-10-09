"""Finite abstract TLA+ check of async correlation guards and lifecycle actions."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from verification.contract import validate_async
from verification.formal.runner import LOCK, ensure_jar
from verification.io import load_contract
from verification.formal.bridge import tla_string

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".async-formal-owned"
TIMEOUT = 180


def _set(values):
    return "{ " + ", ".join(tla_string(value) for value in values) + " }"


def render_data(spec):
    profile = spec["async"]
    # Build records explicitly to keep emitted TLA auditable and avoid host-language codegen.
    rows = []
    for row in profile["transitions"]:
        fx = "<< " + ", ".join(tla_string(effect) for effect in row["effects"]) + " >>" if row["effects"] else "<< >>"
        rows.append("[state |-> %s, event |-> %s, nextState |-> %s, effects |-> %s, guard |-> %s, pendingAction |-> %s]" % (
            tla_string(row["state"]), tla_string(row["event"]), tla_string(row["nextState"]), fx,
            tla_string(row["guard"]), tla_string(row["pendingAction"])))
    effects = sorted(set(spec["effects"]))
    return ("---------------- MODULE AsyncContractData ----------------\n"
            "EXTENDS Sequences\n"
            f"States == {_set(spec['states'])}\nEvents == {_set(spec['events'])}\nEffects == {_set(effects)}\n"
            f"SimpleEvents == {_set([event for event in spec['events'] if event not in ('RefreshSucceeded', 'RefreshFailed')])}\n"
            f"ResponseEvents == {_set([event for event in spec['events'] if event in ('RefreshSucceeded', 'RefreshFailed')])}\n"
            f"InitialState == {tla_string(profile['initialState'])}\n"
            f"MaxEffects == {spec['invariants']['maxEffectsPerStep']}\n"
            f"ExhaustionRejection == {tla_string(profile['exhaustionRejection'])}\n"
            "AsyncRows == {\n  " + ",\n  ".join(rows) + "\n}\n"
            "==============================\n")


def prepare_output(path):
    out = Path(path).resolve()
    if out in (Path("/"), ROOT): raise RuntimeError(f"refusing unsafe async formal output: {out}")
    out.mkdir(parents=True, exist_ok=True)
    children = list(out.iterdir())
    marker = out / MARKER
    if children and not marker.is_file(): raise RuntimeError("refusing nonempty unowned async formal output")
    if marker.is_file():
        for child in children:
            if child.name == MARKER: continue
            if child.is_dir(): shutil.rmtree(child)
            else: child.unlink()
    marker.write_text("Owned by verification.async_formal.\n")
    return out


def _run_tlc(work, jar, label, out):
    cfg = work / "AsyncSession.cfg"
    cfg.write_text("SPECIFICATION Spec\nINVARIANT StateClosed\nINVARIANT PendingExactlyRefreshing\nINVARIANT EventClosed\nINVARIANT ResponseClassClosed\nINVARIANT EffectsClosed\nINVARIANT CurrentRequiresPending\nINVARIANT StaleResponseSafety\nINVARIANT RejectedAtomic\nINVARIANT RowTransitionSound\n")
    command = ["java", "-cp", str(jar), "tlc2.TLC", "-workers", "1", "-config", str(cfg), str(work / "AsyncSession.tla")]
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired as err:
        proc = None
        timed_out = True
        result = {"exit": None, "timedOut": True, "stdout": _timeout_text(err.stdout), "stderr": _timeout_text(err.stderr)}
    if proc is not None:
        result = {"exit": proc.returncode, "timedOut": False, "stdout": proc.stdout, "stderr": proc.stderr}
    result.update({"command": command, "durationSeconds": round(time.time() - started, 3)})
    (out / f"{label}.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def _timeout_text(value):
    if value is None: return ""
    if isinstance(value, bytes): return value.decode(errors="replace")
    return str(value)


_VAR_NAMES = {"state", "pending", "previousState", "previousPending", "event", "responseClass", "effects", "rejection"}
_HEADER = re.compile(r"^State (\d+):(?: <[^\n]*>)?$")
_VAR = re.compile(r"^/\\ ([A-Za-z][A-Za-z0-9]*) = (.*)$")
_STRING = re.compile(r'^"(?:[^"\\]|\\["\\nrt])*"$')


def _string(raw):
    if not _STRING.fullmatch(raw): raise ValueError(f"malformed TLA string: {raw!r}")
    body, out, i = raw[1:-1], [], 0
    escapes = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
    while i < len(body):
        if body[i] == "\\":
            i += 1
            if i >= len(body) or body[i] not in escapes: raise ValueError("unsupported TLA escape")
            out.append(escapes[body[i]])
        else: out.append(body[i])
        i += 1
    return "".join(out)


def _value(name, raw):
    if name in {"state", "previousState", "event", "responseClass", "rejection"}: return _string(raw)
    if name in {"pending", "previousPending"}:
        if raw == "TRUE": return True
        if raw == "FALSE": return False
        raise ValueError(f"invalid boolean TLC value for {name}")
    if name == "effects":
        if raw in ("<<>>", "<< >>"): return ()
        if not raw.startswith("<<") or not raw.endswith(">>"): raise ValueError("malformed effects sequence")
        inner = raw[2:-2].strip()
        if not inner: return ()
        parts = re.split(r',\s*(?=")', inner)
        return tuple(_string(part.strip()) for part in parts)
    raise ValueError(f"unknown TLC variable {name}")


def parse_counterexample(text):
    marker = "Error: The behavior up to this point is:\n"
    if marker not in text: raise ValueError("TLC counterexample behavior marker missing")
    lines, states, pos = text.split(marker, 1)[1].splitlines(), [], 0
    while pos < len(lines):
        while pos < len(lines) and not lines[pos]: pos += 1
        if pos >= len(lines): break
        header = _HEADER.fullmatch(lines[pos])
        if not header:
            if states and re.fullmatch(r"\d+ states generated, \d+ distinct states found, \d+ states left on queue\.", lines[pos]): break
            raise ValueError(f"malformed TLC counterexample line {lines[pos]!r}")
        if int(header.group(1)) != len(states) + 1: raise ValueError("nonsequential TLC trace state")
        pos += 1
        values = {}
        while pos < len(lines) and lines[pos].startswith("/\\ "):
            match = _VAR.fullmatch(lines[pos])
            if not match: raise ValueError(f"malformed TLC variable line: {lines[pos]!r}")
            name = match.group(1)
            if name not in _VAR_NAMES or name in values: raise ValueError(f"duplicate or unexpected TLC variable {name}")
            values[name] = _value(name, match.group(2))
            pos += 1
        if set(values) != _VAR_NAMES: raise ValueError(f"incomplete TLC state, fields={sorted(values)}")
        states.append(values)
    if not states: raise ValueError("empty TLC counterexample")
    return states


def validate_trace(states, spec, stale_fault=False):
    if not isinstance(states, list) or not states:
        raise ValueError("TLC trace must contain an initial state")
    profile = spec["async"]
    required = _VAR_NAMES
    allowed_responses = {"RefreshSucceeded", "RefreshFailed"}
    allowed_simple = set(spec["events"]) - allowed_responses
    rows = {(row["state"], row["event"]): row for row in profile["transitions"]}
    initial = states[0]
    if initial != {"state": profile["initialState"], "pending": False, "previousState": profile["initialState"], "previousPending": False,
                   "event": "__initial__", "responseClass": "NA", "effects": (), "rejection": "__none__"}:
        raise ValueError("TLC trace initial state mismatch")
    witnessed_final_fault = False
    for index, row_state in enumerate(states[1:], start=1):
        if not isinstance(row_state, dict) or set(row_state) != required:
            raise ValueError("TLC trace state has missing or extra variables")
        if not isinstance(row_state["state"], str) or not isinstance(row_state["previousState"], str) or row_state["state"] not in spec["states"] or row_state["previousState"] not in spec["states"]:
            raise ValueError("TLC trace state is outside declared state domain")
        if type(row_state["pending"]) is not bool or type(row_state["previousPending"]) is not bool:
            raise ValueError("TLC trace pending values must be booleans")
        if not isinstance(row_state["event"], str) or row_state["event"] not in spec["events"]:
            raise ValueError("TLC trace event is outside declared event domain")
        if not isinstance(row_state["responseClass"], str) or row_state["responseClass"] not in {"CURRENT", "STALE", "NA"}:
            raise ValueError("TLC trace response class is outside declared domain")
        if not isinstance(row_state["effects"], tuple) or len(row_state["effects"]) > spec["invariants"]["maxEffectsPerStep"] or any(not isinstance(effect, str) or effect not in spec["effects"] for effect in row_state["effects"]):
            raise ValueError("TLC trace effects are outside declared ordered effect domain")
        if not isinstance(row_state["rejection"], str) or row_state["rejection"] not in {"__none__", profile["exhaustionRejection"]}:
            raise ValueError("TLC trace rejection is outside declared domain")
        prev = states[index - 1]
        if row_state["previousState"] != prev["state"] or row_state["previousPending"] != prev["pending"]:
            raise ValueError("TLC trace predecessor observations do not match")
        if row_state["pending"] != (row_state["state"] == "Refreshing"):
            raise ValueError("pending iff Refreshing violated in trace")
        event = row_state["event"]
        row = rows.get((prev["state"], event))
        if row is None: raise ValueError("TLC trace event has no canonical async row")
        if row_state["rejection"] == profile["exhaustionRejection"]:
            if event != "TokenExpired" or prev["state"] != "Authenticated" or row["pendingAction"] != "allocate" or row_state["responseClass"] != "NA":
                raise ValueError("allocation rejection occurred outside Authenticated × TokenExpired")
            if row_state["state"] != prev["state"] or row_state["pending"] != prev["pending"] or row_state["effects"]:
                raise ValueError("allocation rejection was not atomic")
            continue
        if row_state["responseClass"] == "CURRENT":
            if event not in allowed_responses or prev["state"] != "Refreshing" or not prev["pending"] or row["guard"] != "activeResponse":
                raise ValueError("CURRENT response outside active pending response domain")
        elif row_state["responseClass"] == "STALE":
            if event not in allowed_responses or row["guard"] != "activeResponse":
                raise ValueError("STALE label used for a non-response event")
            if stale_fault and index == len(states) - 1:
                if prev["state"] != "Refreshing" or not prev["pending"]:
                    raise ValueError("negative stale response did not start in Refreshing with pending request")
                want_pending = True if row["pendingAction"] == "allocate" else False if row["pendingAction"] == "clear" else prev["pending"]
                if row_state["state"] != row["nextState"] or row_state["pending"] != want_pending or row_state["effects"] != tuple(row["effects"]) or row_state["rejection"] != "__none__":
                    raise ValueError("negative stale response differs from the exact injected canonical Apply row")
                if row_state["state"] == prev["state"] and row_state["pending"] == prev["pending"] and not row_state["effects"]:
                    raise ValueError("negative counterexample did not demonstrate stale response mutation")
                witnessed_final_fault = True
                continue
            if row_state["state"] != prev["state"] or row_state["pending"] != prev["pending"] or row_state["effects"] or row_state["rejection"] != "__none__":
                raise ValueError("stale response was not a no-op")
            continue
        if row_state["responseClass"] == "NA" and event not in allowed_simple:
            raise ValueError("NA response class used for a response event")
        if row_state["responseClass"] != "NA" and event not in allowed_responses:
            raise ValueError("response class used for a simple event")
        want_pending = True if row["pendingAction"] == "allocate" else False if row["pendingAction"] == "clear" else prev["pending"]
        if row_state["state"] != row["nextState"] or row_state["pending"] != want_pending or row_state["effects"] != tuple(row["effects"]):
            raise ValueError("TLC transition differs from canonical async row")
    if stale_fault and (len(states) < 2 or not witnessed_final_fault):
        raise ValueError("negative TLC trace must end with an observed stale-response Apply violation")
    return True


def run(output, jar_path=None):
    out = prepare_output(output)
    spec, _ = load_contract()
    validate_async(spec, spec["async"])
    lock = json.loads(LOCK.read_text())
    meta = {"specSha256": hashlib.sha256((ROOT / "contract/specification.json").read_bytes()).hexdigest(),
            "schemaSha256": hashlib.sha256((ROOT / "contract/schema.json").read_bytes()).hexdigest(),
            "modelSha256": hashlib.sha256((ROOT / "formal/AsyncSession.tla").read_bytes()).hexdigest(),
            "lock": lock}
    try:
        java = subprocess.run(["java", "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        java_text = java.stderr + java.stdout
        meta["javaVersion"] = java_text.strip()
        meta["javaExit"] = java.returncode
    except Exception as error:
        meta["javaVersionError"] = f"{type(error).__name__}: {error}"
        java_text = ""
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    if meta.get("javaExit") != 0 or '"17' not in java_text and ' version "1.17' not in java_text:
        raise RuntimeError("Java 17 is required by formal/toolchain.json")
    jar, jar_hash, jar_source = ensure_jar(jar_path)
    meta.update({"jarSha256": jar_hash, "jarSource": jar_source})
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    data = render_data(spec)
    base = (ROOT / "formal/AsyncSession.tla").read_text()
    work = out / "positive"
    work.mkdir()
    (work / "AsyncContractData.tla").write_text(data)
    (work / "AsyncSession.tla").write_text(base)
    pos = _run_tlc(work, jar, "positive-tlc", out)
    pos_text = pos["stdout"] + "\n" + pos["stderr"]
    counts = re.findall(r"(\d+) states generated, (\d+) distinct states found, 0 states left on queue\.", pos_text)
    if pos["timedOut"]: raise RuntimeError("positive TLC timed out")
    if pos["exit"] != 0 or "Model checking completed. No error has been found." not in pos_text or not counts:
        raise RuntimeError("positive TLC run failed or lacked fixed-point state-count evidence")
    negative = out / "negative"
    negative.mkdir()
    (negative / "AsyncContractData.tla").write_text(data)
    faulty = base.replace('StaleResponse(row) ==\n  Observe(state, pending, << >>, NoRejection, "STALE", row.event)', 'StaleResponse(row) ==\n  Apply(row, "STALE")')
    if faulty == base: raise RuntimeError("could not inject isolated stale-response guard fault")
    (negative / "AsyncSession.tla").write_text(faulty)
    neg = _run_tlc(negative, jar, "negative-tlc", out)
    neg_text = neg["stdout"] + "\n" + neg["stderr"]
    (out / "negative-counterexample.txt").write_text(neg_text)
    if neg["timedOut"]: raise RuntimeError("negative TLC timed out")
    if neg["exit"] != 12 or "Invariant StaleResponseSafety is violated." not in neg_text:
        raise RuntimeError("negative TLC control did not violate named StaleResponseSafety")
    trace = parse_counterexample(neg_text)
    validate_trace(trace, spec, stale_fault=True)
    meta.update({"generatedDataSha256": hashlib.sha256(data.encode()).hexdigest(),
            "positiveStateCountsFromTLC": {"generated": int(counts[0][0]), "distinct": int(counts[0][1])},
            "negativeCounterexampleStates": len(trace), "abstraction": "pending boolean; CURRENT means routed equality with active ID; IDs themselves and numeric refinement omitted; calls serialized"}
    )
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    report = {"status": "PASS", **meta, "negativeControl": "named StaleResponseSafety counterexample parsed and validated"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "report.md").write_text("# Async correlation formal verification\n\nStatus: **PASS**\n\n"
        f"- TLC `{lock['release']}` / `{lock['tlcVersion']}`; JAR SHA-256 `{jar_hash}`\n"
        f"- Positive exploration: {counts[0][0]} generated, {counts[0][1]} distinct states (captured from TLC output).\n"
        f"- Negative control: `StaleResponseSafety` counterexample validated across {len(trace)} states.\n"
        "- Abstraction: pending is Boolean. CURRENT represents a correctly routed response equal to the active request ID; STALE represents every nonmatching/duplicate/unissued response. IDs, numeric exhaustion refinement, native implementation refinement, concurrency and liveness are not claimed. Request allocation may nondeterministically reject atomically to represent exhaustion.\n"
        "- Raw TLC stdout/stderr and counterexample: `positive-tlc.json`, `negative-tlc.json`, `negative-counterexample.txt`.\n")
    return report


def _write_failure_report(path, error):
    out = Path(path).resolve()
    if not (out / MARKER).is_file(): return
    meta_path = out / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    report = {"status": "FAIL", "error": f"{type(error).__name__}: {error}", "metadata": meta}
    for label in ("positive-tlc", "negative-tlc"):
        result_path = out / f"{label}.json"
        if result_path.is_file(): report[label] = json.loads(result_path.read_text())
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "report.md").write_text("# Async correlation formal verification\n\nStatus: **FAIL**\n\n"
        f"Error: `{report['error']}`\n\nMetadata and any partial TLC command/stdout/stderr evidence are preserved in this output directory.\n")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--jar")
    args = parser.parse_args(argv)
    try:
        report = run(args.output, args.jar)
        print(f"PASS: async TLC; {report['positiveStateCountsFromTLC']['distinct']} distinct states; validated StaleResponseSafety counterexample")
        return 0
    except Exception as error:
        try: _write_failure_report(args.output, error)
        except Exception as report_error: print(f"could not persist async formal failure report: {report_error}", file=sys.stderr)
        print(f"async formal verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
