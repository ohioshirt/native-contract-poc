#!/bin/bash
# Exercise Intel's pre-concurrency deployment floor even on an Apple Silicon host.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:?usage: swift-availability-check.sh OUTPUT_DIR}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd "$ROOT_DIR"
PLATFORM_DIR="$(xcrun --show-sdk-platform-path)"
args=(-I "$PLATFORM_DIR/Developer/usr/lib" -F "$PLATFORM_DIR/Developer/Library/Frameworks" -parse-as-library -swift-version 6 -target x86_64-apple-macosx10.13 -module-cache-path "$OUT_DIR/cache" -I "$OUT_DIR")
swiftc "${args[@]}" -emit-module -module-name NativeContract ios/Sources/NativeContract/*.swift -emit-module-path "$OUT_DIR/NativeContract.swiftmodule"
swiftc "${args[@]}" -emit-module -enable-testing -module-name AsyncNativeContract ios/Sources/AsyncNativeContract/*.swift -emit-module-path "$OUT_DIR/AsyncNativeContract.swiftmodule"
swiftc "${args[@]}" -emit-module -enable-testing -module-name ManagedHistoryRunner ios/Sources/ManagedHistoryRunner/*.swift -emit-module-path "$OUT_DIR/ManagedHistoryRunner.swiftmodule"
swiftc "${args[@]}" -typecheck verification/managed-api/swift/positive.swift
swiftc "${args[@]}" -typecheck ios/Tests/AsyncNativeContractTests/*.swift
for probe in constructor owner session mutation; do
  if swiftc "${args[@]}" -typecheck -module-name ExternalManagedProbe "verification/managed-api/swift/$probe.swift" > "$OUT_DIR/$probe.stdout.log" 2> "$OUT_DIR/$probe.stderr.log"; then
    echo "negative probe unexpectedly compiled: $probe" >&2
    exit 1
  fi
  python3 - "$probe" "$OUT_DIR/$probe.stderr.log" <<'PYCODE'
from pathlib import Path
import sys
from verification.managed_api import expected_diagnostic
output = Path(sys.argv[2]).read_text()
if 'is only available in' in output or not expected_diagnostic('swift', sys.argv[1], output):
    raise SystemExit('negative probe did not isolate its access restriction: '+output)
PYCODE
done
printf 'Explicit macOS 10.13 compilation with scoped concurrency availability: PASS\n'
