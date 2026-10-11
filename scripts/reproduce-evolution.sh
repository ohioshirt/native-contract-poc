#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR"
export PYTHONPYCACHEPREFIX="$ROOT_DIR/.python-cache"
exec python3 -m verification.reproduce_evolution "$@"
