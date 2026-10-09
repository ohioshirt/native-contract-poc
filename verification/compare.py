#!/usr/bin/env python3
"""Compare a native wire document with the independently generated oracle."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verification.contract import scenarios
from verification.io import load_contract, read_document
from verification.traces import compare, oracle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("actual", nargs="?", help="native runner JSON output; oracle mode")
    parser.add_argument("--left", help="left runner output for direct native-to-native mode")
    parser.add_argument("--right", help="right runner output for direct native-to-native mode")
    parser.add_argument("--spec")
    parser.add_argument("--schema")
    args = parser.parse_args()
    if bool(args.left) != bool(args.right): parser.error("--left and --right must be supplied together")
    try:
      if args.left:
        left, right = read_document(args.left), read_document(args.right)
        if not isinstance(left, dict) or set(left) != {"traces"} or not isinstance(left["traces"], list): raise ValueError("left document must contain only traces array")
        if not isinstance(right, dict) or set(right) != {"traces"} or not isinstance(right["traces"], list): raise ValueError("right document must contain only traces array")
        errors = compare(left["traces"], right["traces"])
        expected_count = len(left["traces"])
      else:
        if not args.actual: parser.error("actual is required in oracle mode")
        spec, machine = load_contract(args.spec, args.schema)
        expected = [oracle(f"s{i:04d}", seq, spec["initialState"], machine)
                    for i, seq in enumerate(scenarios(spec))]
        doc = read_document(args.actual)
        if not isinstance(doc, dict) or set(doc) != {"traces"} or not isinstance(doc["traces"], list):
            raise ValueError("document must contain only a traces array")
        errors = compare(expected, doc["traces"])
        expected_count = len(expected)
    except Exception as error:
        print(f"invalid input: {error}", file=sys.stderr)
        return 2
    if errors:
        for error in errors: print(error, file=sys.stderr)
        return 1
    print(f"PASS: {expected_count} scenarios, ordered state/effect traces match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
