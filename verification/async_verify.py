#!/usr/bin/env python3
"""Run both installed async trace runners against the independent Python oracle."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from verification.async_contract import compare_documents, expected_traces, validate_input, validate_output
from verification.io import load_contract, read_document, write_document

ROOT = Path(__file__).resolve().parents[1]


class RunnerExecutionFailure(RuntimeError):
    pass


def _run(label, executable, input_path, output_path, out):
    command = [str(executable)]
    (out / f"{label}.command.log").write_text(" ".join(command) + f" < {input_path} > {output_path}\n")
    try:
        with input_path.open("rb") as source, output_path.open("wb") as target:
            proc = subprocess.run(command, cwd=ROOT, stdin=source, stdout=target,
                                  stderr=subprocess.PIPE, timeout=180, check=False)
        (out / f"{label}.stderr.log").write_bytes(proc.stderr)
        (out / f"{label}.exit-code").write_text(f"{proc.returncode}\n")
        result = {"classification": "PASS" if proc.returncode == 0 else "INFRA_FAILURE", "returnCode": proc.returncode,
                  "timedOut": False, "stdoutPath": str(output_path), "stderrPath": f"{label}.stderr.log"}
        (out / f"{label}.result.json").write_text(json.dumps(result, indent=2) + "\n")
        if proc.returncode != 0:
            raise RunnerExecutionFailure(f"runner exited {proc.returncode}; retained numeric code and stderr")
    except subprocess.TimeoutExpired as error:
        (out / f"{label}.stderr.log").write_bytes(error.stderr if isinstance(error.stderr, bytes) else (error.stderr or "").encode())
        (out / f"{label}.exit-code").write_text("TIMEOUT\n")
        result = {"classification": "INFRA_FAILURE", "returnCode": None, "timedOut": True,
                  "stdoutPath": str(output_path), "stderrPath": f"{label}.stderr.log"}
        (out / f"{label}.result.json").write_text(json.dumps(result, indent=2) + "\n")
        raise RunnerExecutionFailure("runner timed out; partial stdout and stderr were retained") from error
    except RunnerExecutionFailure:
        raise
    except Exception as error:
        # Preserve any process-produced stderr and numeric status; report launch/tool
        # failures separately so they cannot be confused with a conformance kill.
        result_path = out / f"{label}.result.json"
        if not result_path.exists():
            (out / f"{label}.stderr.log").write_text(f"{type(error).__name__}: {error}\n")
            (out / f"{label}.exit-code").write_text("NOT_STARTED\n")
            (out / f"{label}.result.json").write_text(json.dumps({"classification": "INFRA_FAILURE", "returnCode": None, "timedOut": False,
                                                                       "detail": f"{type(error).__name__}: {error}"}, indent=2) + "\n")
        raise RunnerExecutionFailure(f"runner launch/tool failure: {type(error).__name__}: {error}") from error


def run(output, swift=None, kotlin=None, input_path=None):
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if out in (Path("/"), ROOT): raise RuntimeError(f"refusing unsafe async output directory: {out}")
    marker = out / ".async-verification-owned"
    children = list(out.iterdir())
    if children and not marker.is_file(): raise RuntimeError("refusing to replace unowned async verification output")
    if marker.is_file():
        for child in children:
            if child.name == marker.name: continue
            if child.is_dir(): shutil.rmtree(child)
            else: child.unlink()
    marker.write_text("Owned by verification.async_verify; generated async conformance evidence.\n")
    spec, _ = load_contract()
    expected, inputs = expected_traces(spec)
    generated = {"scenarios": [{"scenario": row["scenario"], "events": row["events"], **({"nextRequestId": row["nextRequestId"]} if "nextRequestId" in row else {})} for row in inputs]}
    source = read_document(input_path) if input_path else generated
    normalized = validate_input(source, spec)
    if input_path:
        expected = [__import__("verification.async_contract", fromlist=["oracle"]).oracle(row["scenario"], row["events"], spec, row["nextRequestId"]) for row in normalized]
    input_file = out / "async-input.json"
    write_document(source, input_file)
    (out / "expected-async-traces.json").write_text(json.dumps({"traces": expected}, ensure_ascii=False, separators=(",", ":")) + "\n")
    verdicts = {}
    errors = {}
    documents = {}
    for language, executable in (("swift", swift or ROOT / "ios/.build/debug/AsyncTraceRunner"),
                                 ("kotlin", kotlin or ROOT / "android/async-library/build/install/async-library/bin/async-library")):
        path = Path(executable)
        if not path.is_file():
            verdicts[language] = "NOT_RUN"
            errors[language] = f"runner unavailable: {path}"
            documents[language] = None
            continue
        actual_path = out / f"{language}-async-traces.json"
        try:
            _run(f"{language}-async-runner", path, input_file, actual_path, out)
            try: actual = read_document(actual_path)
            except Exception as error:
                actual = None
                mismatches = [f"invalid runner JSON: {type(error).__name__}: {error}"]
            else: mismatches = validate_output(actual, expected, spec)
            documents[language] = actual
            verdicts[language] = "PASS" if not mismatches else "FAIL"
            errors[language] = mismatches
            (out / f"{language}-async-comparison.log").write_text(("PASS\n" if not mismatches else "\n".join(mismatches) + "\n"))
        except RunnerExecutionFailure as error:
            verdicts[language] = "INFRA_FAILURE"
            errors[language] = [str(error)]
            documents[language] = None
        except Exception as error:
            verdicts[language] = "INFRA_FAILURE"
            errors[language] = [str(error)]
            documents[language] = None
    if verdicts.get("swift") == "NOT_RUN" or verdicts.get("kotlin") == "NOT_RUN":
        verdicts["differential"] = "NOT_RUN"
    elif verdicts.get("swift") == "INFRA_FAILURE" or verdicts.get("kotlin") == "INFRA_FAILURE":
        verdicts["differential"] = "NOT_RUN"
    else:
        direct = compare_documents(documents["swift"], documents["kotlin"], expected, spec)
        verdicts["differential"] = "PASS" if not direct else "FAIL"
        (out / "async-direct-differential.log").write_text("PASS\n" if not direct else "\n".join(direct) + "\n")
        errors["differential"] = direct
    report = {"status": "PASS" if verdicts == {"swift": "PASS", "kotlin": "PASS", "differential": "PASS"} else "FAIL",
              "scenarioCount": len(expected), "stepCount": sum(len(trace["steps"]) for trace in expected),
              "verdicts": verdicts, "errors": errors}
    (out / "async-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['status']}: {report['scenarioCount']} scenarios, {report['stepCount']} steps; " +
          ", ".join(f"{k}={v}" for k, v in verdicts.items()))
    if report["status"] != "PASS":
        for language, lines in errors.items():
            for line in (lines if isinstance(lines, list) else [lines]): print(f"{language}: {line}", file=sys.stderr)
        return 2 if "INFRA_FAILURE" in verdicts.values() or "NOT_RUN" in verdicts.values() else 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--swift")
    parser.add_argument("--kotlin")
    parser.add_argument("--input")
    args = parser.parse_args(argv)
    return run(args.output, args.swift, args.kotlin, args.input)


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as error:
        print(f"async verification infrastructure failure: {error}", file=sys.stderr)
        raise SystemExit(2)
