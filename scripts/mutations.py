#!/usr/bin/env python3
"""Run exact mutation expectations against disposable native source copies.

Config format: {"cases":[{"id":"A","expected":{"swift":"FAIL","kotlin":"PASS"},
"patches":[{"file":"ios/Sources/...swift","before":"unique text","after":"replacement"}]}]}.
Each patch must match exactly once. Build errors are infrastructure failures, never kills.
"""
import argparse
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def execute(label, command, cwd, log_dir, input_path=None, output_path=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    command = command.format(root=shlex.quote(str(cwd)), input=shlex.quote(str(input_path or "")),
                             output=shlex.quote(str(output_path or "")))
    result = subprocess.run(command, cwd=cwd, env=env, shell=True, text=True, capture_output=True)
    (log_dir / f"{label}.command.log").write_text(command + "\n")
    (log_dir / f"{label}.stdout.log").write_text(result.stdout)
    (log_dir / f"{label}.stderr.log").write_text(result.stderr)
    (log_dir / f"{label}.exit-code").write_text(f"{result.returncode}\n")
    return result.returncode


def write_manifest(path, cases, skipped=False):
    if skipped: status = "NOT_RUN"
    elif any(case["status"] == "INFRA_FAILURE" for case in cases): status = "INFRA_FAILURE"
    elif any(case["status"] == "RUNNING" for case in cases): status = "RUNNING"
    elif any(case["status"] == "MATRIX_FAIL" for case in cases): status = "MATRIX_FAIL"
    elif all(case["status"] == "PASS" for case in cases): status = "PASS"
    else: status = "RUNNING"
    manifest = {"status": status, "cases": cases}
    if skipped: manifest["reason"] = "explicitly skipped by --skip"
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def prepare_case_dirs(output, cases):
    output.mkdir(parents=True, exist_ok=True)
    root_marker = output / ".native-contract-mutations"
    manifest_path = output / "manifest.json"
    if not root_marker.exists() and manifest_path.exists():
        raise RuntimeError(f"refusing to replace unowned mutation manifest: {manifest_path}")
    case_dirs = []
    seen = set()
    for case in cases:
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in (".", "..") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in case_id):
            raise ValueError(f"unsafe mutation case ID: {case_id!r}")
        if case_id in seen: raise ValueError(f"duplicate mutation case ID: {case_id}")
        seen.add(case_id)
        case_dir = output / case_id
        case_dirs.append(case_dir)
        if not case_dir.exists(): continue
        if not case_dir.is_dir(): raise RuntimeError(f"refusing to replace non-directory mutation result: {case_dir}")
        marker = case_dir / ".native-contract-mutation-case"
        result = case_dir / "result.txt"
        legacy_owned = result.is_file() and result.read_text().startswith(("PASS expected=", "FAIL expected=", "INFRA_FAILURE"))
        if not marker.is_file() and not legacy_owned:
            raise RuntimeError(f"refusing to remove unowned mutation result directory: {case_dir}")
    for case_dir in case_dirs:
        if case_dir.exists(): shutil.rmtree(case_dir)
    root_marker.write_text("owned\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="mutation matrix JSON")
    parser.add_argument("--output", default="reports/mutations")
    parser.add_argument("--skip", action="store_true", help="clear stale case evidence and record every case as NOT_RUN")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    output = (ROOT / args.output).resolve()
    cases = config["cases"]
    prepare_case_dirs(output, cases)
    entries = [{"id": case["id"], "expected": case["expected"], "status": "NOT_RUN"} for case in cases]
    manifest_path = output / "manifest.json"
    write_manifest(manifest_path, entries, skipped=args.skip)
    if args.skip:
        for case in cases: print(f"{case['id']}: NOT_RUN (explicitly skipped)")
        return 0
    overall = 0
    for case_index, case in enumerate(cases):
        case_dir = output / case["id"]
        case_dir.mkdir(parents=True)
        (case_dir / ".native-contract-mutation-case").write_text("owned\n")
        entries[case_index]["status"] = "RUNNING"
        write_manifest(manifest_path, entries)
        try:
            with tempfile.TemporaryDirectory(prefix=f"native-contract-{case['id']}-") as temp:
                work = Path(temp) / "src"
                work.mkdir()
                for tree in ("contract", "verification", "ios", "android"):
                    src = ROOT / tree
                    if not src.exists(): raise RuntimeError(f"missing source tree {src}")
                    shutil.copytree(src, work / tree, ignore=shutil.ignore_patterns(".build", "build", ".gradle", ".gradle-home", "verification-logs", "__pycache__"))
                shutil.copy2(ROOT / "android/gradlew", work / "android/gradlew")
                for patch in case.get("patches", []):
                    path = work / patch["file"]
                    source = path.read_text()
                    matches = source.count(patch["before"])
                    if matches != 1: raise RuntimeError(f"{case['id']}: patch {patch['file']} matched {matches}, expected 1")
                    path.write_text(source.replace(patch["before"], patch["after"], 1))
                gen = execute("generate", "python3 verification/generate.py --wire-input --output {output}", work, case_dir,
                              output_path=case_dir / "scenarios.json")
                if gen: raise RuntimeError(f"{case['id']}: oracle input generation failed")
                actual = {}
                for language, build, runner in (
                        ("swift", "swift build --package-path ios", "ios/.build/debug/TraceRunner < {input} > {output}"),
                        ("kotlin", "./android/gradlew -p android :library:assemble :library:installDist", "android/library/build/install/library/bin/library < {input} > {output}")):
                    build_status = execute(f"{language}-build", build, work, case_dir)
                    if build_status: raise RuntimeError(f"{case['id']}: {language} build failed (infrastructure failure)")
                    output_path = case_dir / f"{language}-traces.json"
                    runner_status = execute(f"{language}-runner", runner, work, case_dir,
                                            input_path=case_dir / "scenarios.json", output_path=output_path)
                    if runner_status: raise RuntimeError(f"{case['id']}: {language} runner failed (infrastructure failure)")
                    compare_status = execute(f"{language}-compare", "python3 verification/compare.py {output}", work, case_dir,
                                             output_path=output_path)
                    if compare_status > 1: raise RuntimeError(f"{case['id']}: {language} comparison failed as infrastructure")
                    actual[language] = "PASS" if compare_status == 0 else "FAIL"
                differential_status = execute("native-differential", "python3 verification/compare.py --left {input} --right {output}", work, case_dir,
                                              input_path=case_dir / "swift-traces.json", output_path=case_dir / "kotlin-traces.json")
                if differential_status > 1: raise RuntimeError(f"{case['id']}: differential comparison failed as infrastructure")
                actual["differential"] = "PASS" if differential_status == 0 else "FAIL"
                wanted = case["expected"]
                (case_dir / "actual.json").write_text(json.dumps(actual, indent=2) + "\n")
                if actual != wanted:
                    overall = 1
                    entries[case_index]["status"] = "MATRIX_FAIL"
                    entries[case_index]["exitCode"] = 1
                    entries[case_index]["actual"] = actual
                    (case_dir / "result.txt").write_text(f"FAIL expected={wanted} actual={actual}\n")
                    print(f"{case['id']}: FAIL expected={wanted} actual={actual}")
                else:
                    entries[case_index]["status"] = "PASS"
                    entries[case_index]["exitCode"] = 0
                    entries[case_index]["actual"] = actual
                    (case_dir / "result.txt").write_text(f"PASS expected={wanted} actual={actual}\n")
                    print(f"{case['id']}: PASS {actual}")
                write_manifest(manifest_path, entries)
        except Exception as error:
            entries[case_index]["status"] = "INFRA_FAILURE"
            entries[case_index]["exitCode"] = 2
            entries[case_index]["detail"] = str(error)
            (case_dir / "result.txt").write_text(f"INFRA_FAILURE {error}\n")
            write_manifest(manifest_path, entries)
            print(f"{case['id']}: INFRA_FAILURE {error}", file=sys.stderr)
            return 2
    return overall


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as error:
        print(f"mutation harness infrastructure failure: {error}", file=sys.stderr)
        raise SystemExit(2)
