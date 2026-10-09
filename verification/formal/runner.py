"""Pinned TLC runner and auditable formal verification report producer."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from verification.formal import bridge

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "formal/toolchain.json"
TIMEOUT_SECONDS = 180
MARKER = ".formal-verification-owned"


def prepare_output(output):
    output = Path(output).resolve()
    if output in (Path("/"), ROOT): raise RuntimeError(f"refusing unsafe output directory: {output}")
    if output.exists() and not output.is_dir(): raise RuntimeError("formal output must be a directory")
    output.mkdir(parents=True, exist_ok=True)
    marker = output / MARKER
    entries = list(output.iterdir())
    if entries and not marker.is_file():
        raise RuntimeError("formal output directory is nonempty and not owned by this runner")
    if marker.is_file():
        for child in entries:
            if child.name == MARKER: continue
            if child.is_dir(): shutil.rmtree(child)
            else: child.unlink()
    marker.write_text("Owned by verification.formal.run; generated formal verification evidence.\n")
    return output


def verify_jar(path, expected):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected: raise RuntimeError(f"TLC JAR SHA-256 mismatch: expected {expected}, got {digest}")
    return digest


def ensure_jar(path=None):
    lock = json.loads(LOCK.read_text())
    if path:
        jar = Path(path).resolve()
        digest = verify_jar(jar, lock["sha256"])
        return jar, digest, "provided"
    jar = ROOT / ".formal-cache" / "tla2tools-1.7.4.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    if jar.exists(): return jar, verify_jar(jar, lock["sha256"]), "cache"
    temp = jar.with_suffix(".jar.download")
    try:
        request = urllib.request.Request(lock["url"], headers={"User-Agent": "native-contract-formal-verifier"})
        with urllib.request.urlopen(request, timeout=30) as response, temp.open("wb") as out:
            shutil.copyfileobj(response, out)
        digest = verify_jar(temp, lock["sha256"])
        os.replace(temp, jar)
        return jar, digest, "download"
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _record_cmd(path, cmd, cwd, env=None):
    start = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=TIMEOUT_SECONDS, check=False)
        result = {"command": cmd, "cwd": str(cwd), "exit": proc.returncode,
                  "stdout": proc.stdout, "stderr": proc.stderr, "timedOut": False,
                  "durationSeconds": round(time.time() - start, 3)}
    except subprocess.TimeoutExpired as error:
        result = {"command": cmd, "cwd": str(cwd), "exit": None,
                  "stdout": error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or ""),
                  "stderr": error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or ""),
                  "timedOut": True, "durationSeconds": round(time.time() - start, 3)}
    path.write_text(json.dumps(result, indent=2) + "\n")
    path.with_suffix(".stdout.txt").write_text(result["stdout"])
    path.with_suffix(".stderr.txt").write_text(result["stderr"])
    return result


def _negative_trace_matches(states, spec):
    from verification.contract import validate
    schema = json.loads((ROOT / "contract/schema.json").read_text())
    machine = validate(spec, schema)
    initial = (spec["initialState"], "__initial__", spec["initialState"], ())
    if len(states) < 3 or states[0] != initial: return False
    fault_pair = ("Authenticated", "Logout")
    violated = []
    prior = spec["initialState"]
    for index, observation in enumerate(states[1:], start=1):
        state, event, previous, effects = observation
        if previous != prior: return False
        pair = (prior, event)
        if pair not in machine: return False
        expected_state, expected_effects = machine[pair]
        if state != expected_state: return False
        if pair == fault_pair:
            # The intentional model fault suppresses just this contract effect.
            if tuple(expected_effects) == () or tuple(effects) != (): return False
            violated.append(index)
        elif tuple(effects) != tuple(expected_effects):
            return False
        prior = state
    return len(violated) == 1 and violated[0] == len(states) - 1


def classify_negative(exit_code, output, trace_path, timed_out, spec=None):
    text = output.lower()
    ok = False
    try:
        if exit_code != 12 or timed_out or "error: invariant transitionsound is violated." not in text:
            raise ValueError("negative tool status or invariant diagnostic mismatch")
        if not trace_path or not Path(trace_path).is_file(): raise ValueError("counterexample artifact missing")
        output_states = bridge.parse_counterexample(output)
        file_states = bridge.parse_counterexample(Path(trace_path).read_text())
        if output_states != file_states: raise ValueError("counterexample artifact does not match TLC output")
        if spec is None:
            from verification.io import load_contract
            spec, _ = load_contract()
        ok = _negative_trace_matches(output_states, spec)
    except (OSError, ValueError, KeyError, TypeError):
        ok = False
    return ok, "named TransitionSound violation with validated Authenticated/Logout counterexample" if ok else "negative control was not a validated invariant counterexample"


def _write_cfg(path):
    path.write_text("SPECIFICATION Spec\nINVARIANT StateClosed\nINVARIANT PreviousStateClosed\nINVARIANT EventClosed\nINVARIANT EffectsClosed\nINVARIANT TransitionSound\n")


def _run_model(work, jar, name, session_text, dump_path, log_dir):
    (work / "Session.tla").write_text(session_text)
    cfg = work / "Session.cfg"
    _write_cfg(cfg)
    cmd = ["java", "-cp", str(jar), "tlc2.TLC", "-workers", "1", "-dump", str(dump_path), "-config", str(cfg), str(work / "Session.tla")]
    result = _record_cmd(log_dir / f"{name}.json", cmd, work)
    generated_dump = Path(str(dump_path) + ".dump")
    if generated_dump.is_file(): shutil.copy2(generated_dump, dump_path)
    return result


def run(output, spec_path=None, jar_path=None):
    output = prepare_output(output)
    started = time.time()
    lock = json.loads(LOCK.read_text())
    from verification.io import load_contract
    spec, machine = load_contract(spec_path)
    del machine
    source = Path(spec_path).resolve() if spec_path else ROOT / "contract/specification.json"
    schema = ROOT / "contract/schema.json"
    spec_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if "__initial__" in spec["events"]:
        raise RuntimeError("reserved __initial__ marker must not appear in the event alphabet")
    metadata = {"spec": str(source), "specSha256": spec_hash, "schema": str(schema),
        "schemaSha256": hashlib.sha256(schema.read_bytes()).hexdigest(),
        "model": str(ROOT / "formal/Session.tla"),
        "modelSha256": hashlib.sha256((ROOT / "formal/Session.tla").read_bytes()).hexdigest(),
        "lock": str(LOCK), "lockSha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        "release": lock["release"], "tlcVersion": lock["tlcVersion"], "jarSha256Expected": lock["sha256"],
        "hashOrigin": lock["hashOrigin"]}
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    jar, digest, jar_source = ensure_jar(jar_path)
    metadata.update({"jar": str(jar), "jarSha256": digest, "jarSource": jar_source})
    java = subprocess.run(["java", "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    java_text = java.stderr + java.stdout
    metadata["java"] = java_text.strip()
    if java.returncode != 0 or '"17' not in java_text and ' version "1.17' not in java_text:
        (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        raise RuntimeError("Java 17 is required by formal/toolchain.json")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    work = output / "positive"
    work.mkdir()
    (work / "ContractData.tla").write_text(bridge.render_data(spec))
    shutil.copy2(ROOT / "formal/Session.tla", work / "Session.tla")
    _write_cfg(work / "Session.cfg")
    logs = output / "logs"
    logs.mkdir()
    dump = output / "positive-state-dump.txt"
    pos = _run_model(work, jar, "positive-tlc", (work / "Session.tla").read_text(), dump, logs)
    pos_text = pos["stdout"] + "\n" + pos["stderr"]
    completion = "Model checking completed. No error has been found." in pos_text and "0 states left on queue" in pos_text
    if pos["timedOut"] or pos["exit"] != 0 or not completion or not dump.is_file(): raise RuntimeError("positive TLC run failed, lacked completion evidence, or produced no state dump")
    expected = bridge.expected_observations(spec)
    actual = bridge.compare_dump(dump.read_text(), expected)
    neg_work = output / "negative"
    neg_work.mkdir()
    (neg_work / "ContractData.tla").write_text(bridge.render_data(spec))
    original = (ROOT / "formal/Session.tla").read_text()
    fault = original.replace("/\\ effects' = row[4]", "/\\ effects' = IF row[1] = \"Authenticated\" /\\ row[2] = \"Logout\" THEN << >> ELSE row[4]")
    if fault == original: raise RuntimeError("could not inject isolated Logout fault")
    shutil.copy2(ROOT / "formal/Session.tla", output / "Session.tla")
    (neg_work / "Session.tla").write_text(fault)
    _write_cfg(neg_work / "Session.cfg")
    neg_dump = output / "negative-state-dump.txt"
    neg = _run_model(neg_work, jar, "negative-tlc", fault, neg_dump, logs)
    neg_text = neg["stdout"] + "\n" + neg["stderr"]
    cex_candidates = [p for p in neg_work.rglob("*") if p.is_file() and ("trace" in p.name.lower() or "counterexample" in p.name.lower())]
    # TLC may put the trace inline when -dump only writes states. Keep that diagnostic as evidence too.
    (output / "negative-counterexample.txt").write_text(neg_text)
    trace = next((p for p in cex_candidates if p.stat().st_size), None)
    named = "Invariant TransitionSound is violated" in neg_text or "Invariant TransitionSound is violated" in neg_text.replace("\n", " ")
    trace_evidence = str(trace) if trace else (str(output / "negative-counterexample.txt") if named and "State 1" in neg_text else "")
    neg_ok, neg_reason = classify_negative(neg["exit"], neg_text, trace_evidence, neg["timedOut"], spec)
    if not neg_ok: raise RuntimeError(f"negative TLC control failed: {neg_reason}")
    metadata["elapsedSeconds"] = round(time.time()-started, 3)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    report = {"status": "PASS", "positiveExit": pos["exit"], "negativeExit": neg["exit"],
              "expectedObservations": len(expected), "actualObservations": len(actual),
              "negativeControl": neg_reason, "sourceSha256": spec_hash, "jarSha256": digest}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "report.md").write_text(f"# Formal verification report\n\nStatus: **PASS**\n\n"
        f"- TLC: {lock['release']} / {lock['tlcVersion']}; Java 17\n- Contract SHA-256: `{spec_hash}`\n"
        f"- TLC JAR SHA-256: `{digest}` ({lock['hashOrigin']})\n- Reachable dump observations: {len(actual)}; JSON observations including initial: {len(expected)}\n"
        f"- Negative control: {neg_reason}\n- Raw command, stdout, stderr, exit and dump: `logs/`, `positive-state-dump.txt`, `negative-counterexample.txt`\n\n"
        "This checks the finite generated model's reachable safety properties; it makes no liveness or native-program refinement claim.\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--spec")
    parser.add_argument("--jar")
    args = parser.parse_args(argv)
    try:
        report = run(args.output, args.spec, args.jar)
        print(f"PASS: formal TLC model check; {report['actualObservations']} observations; negative control detected TransitionSound")
        return 0
    except Exception as error:
        try:
            output = Path(args.output).resolve()
            if (output / MARKER).is_file():
                failure = {"status": "FAIL", "error": f"{type(error).__name__}: {error}"}
                metadata_path = output / "metadata.json"
                if metadata_path.is_file(): failure["metadata"] = json.loads(metadata_path.read_text())
                (output / "report.json").write_text(json.dumps(failure, indent=2) + "\n")
                (output / "report.md").write_text(f"# Formal verification report\n\nStatus: **FAIL**\n\n{failure['error']}\n")
        except OSError:
            pass
        print(f"FAIL: formal verification: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
