#!/bin/bash
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${MUTATION_MATRIX:-$ROOT_DIR/verification/mutation-matrix.json}"
OUT_DIR="${1:-$ROOT_DIR/reports/mutations}"
exec python3 "$ROOT_DIR/scripts/mutations.py" "$CONFIG" --output "$OUT_DIR"
