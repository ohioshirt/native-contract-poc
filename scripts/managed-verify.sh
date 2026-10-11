#!/bin/bash
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/reports/managed-latest}"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
args=(python3 -m verification.managed_verify --output "$OUT_DIR")
if [ "${SKIP_MUTATIONS:-0}" = "1" ]; then args+=(--skip-mutations); fi
exec "${args[@]}"
