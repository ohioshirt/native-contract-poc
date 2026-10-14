#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
run_id="${RUN_ID:-}"
if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$ ]]; then
  printf '%s\n' 'RUN_ID must be an explicit unique ASCII label of length 1..80.' >&2
  exit 2
fi

output_dir="$repo_root/reports/standalone/$run_id"
attempts_dir="$repo_root/reports/standalone/attempts/$run_id"
if [[ -e "$output_dir" || -e "$attempts_dir" ]]; then
  printf '%s\n' 'Refusing to overwrite prior integration evidence.' >&2
  exit 2
fi

python_version="$(python3 --version 2>&1)"
if [[ "$python_version" != 'Python 3.12.8' ]]; then
  printf 'Required Python is 3.12.8; selected interpreter reported %s.\n' "$python_version" >&2
  exit 2
fi

python3 -m integration.reproduce freeze --candidate "$repo_root" --output "$output_dir"
python3 -m integration.reproduce run-suite --candidate "$repo_root" --output "$output_dir"
