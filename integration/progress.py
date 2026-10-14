"""Human-readable progress for long native ledgers.

Stages run with their stdout/stderr captured as hashed evidence, so live progress
goes to a separate file named by NATIVE_CONTRACT_PROGRESS_LOG (CI tails it into
the Actions log). Progress is diagnostic only: it is never read back as evidence
and writing it can never fail a stage.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ENVIRONMENT = "NATIVE_CONTRACT_PROGRESS_LOG"


def _format(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.1f}"
    text = " ".join(str(value).split())
    if not text or any(character in text for character in ' "='):
        return json.dumps(text)
    return text


def event(kind, **fields):
    """Append one `<utc> <kind> key=value ...` line; a no-op without the environment."""
    path = os.environ.get(ENVIRONMENT)
    if not path:
        return
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        parts = [stamp, kind] + [f"{key}={_format(value)}" for key, value in fields.items() if value is not None]
    except Exception:  # noqa: BLE001 - an unprintable value must not fail a stage
        parts = [stamp, kind, "unformattable=true"]
    try:
        with open(path, "a", encoding="utf-8", errors="backslashreplace") as stream:
            stream.write(" ".join(parts) + "\n")
    except Exception:  # noqa: BLE001 - progress must never fail a stage
        pass


def _duration(row):
    seconds = row.get("durationSeconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "-"
    return f"{seconds / 60:.1f} min"


def _note(row):
    skipped = row.get("skippedAfter")
    if isinstance(skipped, dict):
        return f"skipped after {skipped.get('stageId')} {skipped.get('classification')}"
    notes = []
    if row.get("timedOut") is True:
        notes.append("timed out")
    detail = row.get("detail")
    if isinstance(detail, str) and detail:
        notes.append(" ".join(detail.split())[:200])
    return "; ".join(notes)


def summary_markdown(report, *, title):
    """Markdown table of a suite report for $GITHUB_STEP_SUMMARY."""
    lines = [
        f"### {title}: {report.get('classification')}",
        "",
        "| stage | acceptance | duration | note |",
        "|---|---|---|---|",
    ]
    for row in report.get("stageResults", []):
        acceptance = row.get("acceptanceClassification", row.get("classification"))
        note = _note(row).replace("|", "/")
        lines.append(f"| {row.get('stageId')} | {acceptance} | {_duration(row)} | {note} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="print a suite report as a Markdown table")
    summary.add_argument("report")
    summary.add_argument("--title", required=True)
    args = parser.parse_args(argv)
    report = json.loads(Path(args.report).read_text())
    sys.stdout.write(summary_markdown(report, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
