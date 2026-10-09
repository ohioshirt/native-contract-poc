#!/bin/bash
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/reports/async-mutations}"
cd "$ROOT_DIR"
args=(verification/async-mutation-matrix.json --output "$OUT_DIR")
if [ "${2:-}" = "--skip" ]; then args+=(--skip); fi
exec python3 scripts/async_mutations.py "${args[@]}"
