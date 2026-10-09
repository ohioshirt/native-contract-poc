#!/usr/bin/env python3
"""Produce separate oracle, Swift, and Kotlin conformance verdicts."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification.contract import scenarios
from verification.io import load_contract, read_document, write_document
from verification.traces import compare, oracle


def check_runner(path, expected):
    if path is None: return {"verdict": "NOT_RUN", "errors": ["runner output not supplied"]}
    try:
        document = read_document(path)
        if not isinstance(document, dict) or set(document) != {"traces"} or not isinstance(document["traces"], list):
            raise ValueError("document must contain only a traces array")
        errors = compare(expected, document["traces"])
        return {"verdict": "PASS" if not errors else "FAIL", "errors": errors}
    except Exception as error:
        return {"verdict": "FAIL", "errors": [f"invalid JSON/output: {error}"]}


def load_runner(path):
    if path is None: return None, "runner output not supplied"
    try:
        document = read_document(path)
        if not isinstance(document, dict) or set(document) != {"traces"} or not isinstance(document["traces"], list):
            raise ValueError("document must contain only a traces array")
        return document["traces"], None
    except Exception as error: return None, f"invalid JSON/output: {error}"


def failure_rows(expected, swift_rows, swift_error, kotlin_rows, kotlin_error):
    if swift_rows is None or kotlin_rows is None: return []
    indexed = []
    for rows in (swift_rows, kotlin_rows):
        by_id = {}
        for row in rows or []:
            if not isinstance(row, dict) or not isinstance(row.get("scenario"), str):
                # The comparator records the malformed row. It cannot be
                # attributed to an expected scenario, so omit a misleading
                # thousands-of-steps "missing" cascade from this table.
                return []
            by_id[row["scenario"]] = row
        indexed.append(by_id)
    failures = []
    for exp in expected:
        sid = exp["scenario"]
        for i in range(len(exp["steps"])):
            observed = []
            bad = False
            for rows, parse_error in ((indexed[0], swift_error), (indexed[1], kotlin_error)):
                if parse_error: observed.append({"error": parse_error}); bad = True; continue
                got = rows.get(sid)
                step = got.get("steps", []) if got else []
                value = step[i] if isinstance(step, list) and i < len(step) else None
                observed.append(value)
                if value != exp["steps"][i]: bad = True
            if bad: failures.append({"scenario": sid, "step": i + 1, "expected": exp["steps"][i], "swift": observed[0], "kotlin": observed[1],
                                    "classification": "both diverged" if observed[0] != exp["steps"][i] and observed[1] != exp["steps"][i] else ("Swift diverged" if observed[0] != exp["steps"][i] else "Kotlin diverged")})
    return failures


def markdown_report(report):
    markdown = ["# Native contract verification", "", "| Check | Verdict |", "|---|---|"]
    for name in ("oracle", "swift", "kotlin", "differential"):
        markdown.append(f"| {name} | {report[name]['verdict']} |")
    markdown += ["", f"Scenarios: {report.get('oracle', {}).get('scenarioCount', 'NOT_RUN')}", ""]
    if report.get("failedSteps"):
        markdown += ["## Failed steps", "", "| Scenario | Step | Expected | Swift | Kotlin | Classification |", "|---|---:|---|---|---|---|"]
        for failure in report["failedSteps"]:
            cells = [failure[k] for k in ("scenario", "step", "expected", "swift", "kotlin", "classification")]
            markdown.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in cells) + " |")
        markdown.append("")
    markdown.extend(["## Comparator diagnostics", ""])
    for name in ("swift", "kotlin", "differential"):
        markdown += [f"### {name}", ""]
        markdown.extend(f"- {error}" for error in report[name].get("errors", [])[:100])
        if not report[name].get("errors"): markdown.append("- No mismatches")
        markdown.append("")
    return "\n".join(markdown)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec")
    parser.add_argument("--schema")
    parser.add_argument("--swift")
    parser.add_argument("--kotlin")
    parser.add_argument("--report", default="verification-report.json")
    parser.add_argument("--markdown")
    args = parser.parse_args()
    try:
        spec, machine = load_contract(args.spec, args.schema)
        expected = [oracle(f"s{i:04d}", seq, spec["initialState"], machine)
                    for i, seq in enumerate(scenarios(spec))]
        oracle_result = {"verdict": "PASS", "scenarioCount": len(expected), "errors": []}
    except Exception as error:
        report = {"oracle": {"verdict": "FAIL", "errors": [str(error)]},
                  "swift": {"verdict": "NOT_RUN", "errors": []},
                  "kotlin": {"verdict": "NOT_RUN", "errors": []},
                  "differential": {"verdict": "NOT_RUN", "errors": ["oracle generation failed"]},
                  "failedSteps": []}
        write_document(report, args.report)
        md_path = args.markdown or str(Path(args.report).with_suffix(".md"))
        Path(md_path).write_text(markdown_report(report))
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 1
    swift_rows, swift_error = load_runner(args.swift)
    kotlin_rows, kotlin_error = load_runner(args.kotlin)
    report = {"oracle": oracle_result,
              "swift": check_runner(args.swift, expected),
              "kotlin": check_runner(args.kotlin, expected),
              "differential": {"verdict": "PASS" if not compare(swift_rows, kotlin_rows) else "FAIL",
                               "errors": compare(swift_rows, kotlin_rows)} if swift_rows is not None and kotlin_rows is not None else
                              {"verdict": "NOT_RUN", "errors": ["both runner outputs are required"]},
              "failedSteps": failure_rows(expected, swift_rows, swift_error, kotlin_rows, kotlin_error)}
    write_document(report, args.report)
    for name in ("oracle", "swift", "kotlin", "differential"): print(f"{name}: {report[name]['verdict']}")
    for name in ("swift", "kotlin"):
        for error in report[name]["errors"][:100]: print(f"{name}: {error}", file=sys.stderr)
    md_path = args.markdown or str(Path(args.report).with_suffix(".md"))
    Path(md_path).write_text(markdown_report(report))
    for failure in report["failedSteps"][:100]:
        print(f"{failure['scenario']} step {failure['step']}: Expected={failure['expected']!r}; Swift={failure['swift']!r}; Kotlin={failure['kotlin']!r} ({failure['classification']})", file=sys.stderr)
    return 0 if all(report[n]["verdict"] == "PASS" for n in ("oracle", "swift", "kotlin", "differential")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
