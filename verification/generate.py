#!/usr/bin/env python3
"""Generate exhaustive oracle traces from the immutable contract."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification.contract import scenarios
from verification.io import load_contract, write_document
from verification.traces import oracle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec")
    parser.add_argument("--schema")
    parser.add_argument("--output", "-o")
    parser.add_argument("--wire-input", action="store_true", help="emit runner input instead of oracle output")
    args = parser.parse_args()
    spec, machine = load_contract(args.spec, args.schema)
    sequences = list(scenarios(spec))
    if args.wire_input:
        rows = [{"scenario": f"s{i:04d}", "events": list(events)} for i, events in enumerate(sequences)]
        write_document({"scenarios": rows}, args.output)
    else:
        traces = [oracle(f"s{i:04d}", events, spec["initialState"], machine)
                  for i, events in enumerate(sequences)]
        write_document({"traces": traces}, args.output)


if __name__ == "__main__":
    main()
