#!/usr/bin/env python3
"""Run isolated async source mutants; native build/tool errors are infrastructure failures."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MARKER = ".async-mutations-owned"


def record(label, command, cwd, case_dir):
    (case_dir / f"{label}.command.log").write_text(" ".join(map(str, command)) + "\n")
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(ROOT / ".swift-cache/clang")
    env["SWIFTPM_MODULECACHE_OVERRIDE"] = str(ROOT / ".swift-cache/modules")
    env["GRADLE_USER_HOME"] = str(ROOT / ".gradle-home")
    env["PYTHONPATH"] = str(cwd) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=240, check=False)
    except Exception as error:
        (case_dir / f"{label}.stdout.log").write_text("")
        (case_dir / f"{label}.stderr.log").write_text(str(error) + "\n")
        (case_dir / f"{label}.exit-code").write_text("INFRA\n")
        raise
    (case_dir / f"{label}.stdout.log").write_text(proc.stdout)
    (case_dir / f"{label}.stderr.log").write_text(proc.stderr)
    (case_dir / f"{label}.exit-code").write_text(f"{proc.returncode}\n")
    if proc.returncode < 0:
        raise RuntimeError(f"{label} terminated by signal {-proc.returncode}")
    return proc.returncode


def run_case(case, case_dir):
    from verification.async_contract import expected_traces
    spec = json.loads((ROOT / "contract/specification.json").read_text())
    _, vectors = expected_traces(spec)
    input_path = case_dir / "async-input.json"
    input_path.write_text(json.dumps({"scenarios": [{"scenario": row["scenario"], "events": row["events"], **({"nextRequestId": row["nextRequestId"]} if "nextRequestId" in row else {})} for row in vectors]}, separators=(",", ":")) + "\n")
    with tempfile.TemporaryDirectory(prefix=f"native-contract-{case['id']}-") as temp:
        work = Path(temp) / "src"
        work.mkdir()
        for tree in ("contract", "verification", "ios", "android"):
            shutil.copytree(ROOT / tree, work / tree,
                            ignore=shutil.ignore_patterns(".build", "build", ".gradle", ".gradle-home", "verification-logs", "__pycache__", ".swift-cache"))
        shutil.copy2(ROOT / "android/gradlew", work / "android/gradlew")
        for patch in case["patches"]:
            path = work / patch["file"]
            source = path.read_text()
            count = source.count(patch["before"])
            if count != 1: raise RuntimeError(f"{case['id']}: patch site in {patch['file']} matched {count}, expected 1")
            path.write_text(source.replace(patch["before"], patch["after"], 1))
        swift_status = record("swift-build", ["swift", "build", "--package-path", "ios"], work, case_dir)
        if swift_status: raise RuntimeError("Swift async mutation build failed (infrastructure failure)")
        kotlin_status = record("kotlin-build", ["./android/gradlew", "-p", "android", ":async-library:installDist"], work, case_dir)
        if kotlin_status: raise RuntimeError("Kotlin async mutation build failed (infrastructure failure)")
        output_path = case_dir / "conformance-output"
        cmd = ["python3", "-m", "verification.async_verify", "--output", str(output_path), "--input", str(input_path)]
        status = record("async-conformance", cmd, work, case_dir)
        if status not in (0, 1): raise RuntimeError(f"async conformance harness infrastructure exit {status}")
        report = json.loads((output_path / "async-report.json").read_text())
        actual = report["verdicts"]
        (case_dir / "actual.json").write_text(json.dumps(actual, indent=2) + "\n")
        return actual


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip", action="store_true", help="clear stale evidence and mark every async mutation NOT_RUN")
    args = parser.parse_args(argv)
    matrix = json.loads(Path(args.config).read_text())
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / MARKER
    children = list(output.iterdir())
    if children and not marker.is_file(): raise RuntimeError("refusing to replace unowned async mutation output")
    case_dirs = []
    seen = set()
    for case in matrix["cases"]:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", case_id) or case_id in (".", "..") or case_id in seen:
            raise ValueError(f"unsafe or duplicate async mutation case ID: {case_id!r}")
        seen.add(case_id)
        case_dir = output / case_id
        case_dirs.append(case_dir)
        if not case_dir.exists(): continue
        if not case_dir.is_dir(): raise RuntimeError(f"refusing non-directory async mutation result: {case_dir}")
        if not (case_dir / ".async-mutation-case").is_file():
            raise RuntimeError(f"refusing to replace unowned async mutation case: {case_dir}")
    for case_dir in case_dirs:
        if case_dir.exists(): shutil.rmtree(case_dir)
    marker.write_text("Owned by scripts/async_mutations.py.\n")
    entries, overall = [], 0
    if args.skip:
        for case in matrix["cases"]:
            case_dir = output / case["id"]
            case_dir.mkdir()
            (case_dir / ".async-mutation-case").write_text("owned\n")
            (case_dir / "result.txt").write_text("NOT_RUN (explicitly skipped)\n")
            entries.append({"id": case["id"], "status": "NOT_RUN", "expected": case["expected"]})
            print(f"{case['id']}: NOT_RUN (explicitly skipped)")
        (output / "manifest.json").write_text(json.dumps({"status": "NOT_RUN", "reason": "explicitly skipped by --skip", "cases": entries}, indent=2) + "\n")
        return 0
    for case in matrix["cases"]:
        case_dir = output / case["id"]
        case_dir.mkdir()
        (case_dir / ".async-mutation-case").write_text("owned\n")
        try:
            actual = run_case(case, case_dir)
            ok = actual == case["expected"]
            status = "PASS" if ok else "MATRIX_FAIL"
            if not ok: overall = 1
            (case_dir / "result.txt").write_text(f"{status} expected={case['expected']} actual={actual}\n")
            entries.append({"id": case["id"], "status": status, "expected": case["expected"], "actual": actual})
            print(f"{case['id']}: {status} expected={case['expected']} actual={actual}")
        except Exception as error:
            (case_dir / "result.txt").write_text(f"INFRA_FAILURE {error}\n")
            entries.append({"id": case["id"], "status": "INFRA_FAILURE", "detail": str(error)})
            (output / "manifest.json").write_text(json.dumps({"status": "INFRA_FAILURE", "cases": entries}, indent=2) + "\n")
            print(f"{case['id']}: INFRA_FAILURE {error}", file=sys.stderr)
            return 2
    status = "PASS" if overall == 0 else "MATRIX_FAIL"
    (output / "manifest.json").write_text(json.dumps({"status": status, "cases": entries}, indent=2) + "\n")
    return overall


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as error:
        print(f"async mutation harness infrastructure failure: {error}", file=sys.stderr)
        raise SystemExit(2)
