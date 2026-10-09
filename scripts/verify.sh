#!/bin/bash
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT_DIR/reports/latest}"
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
owned=(scenarios.json swift-traces.json kotlin-traces.json summary.json summary.md report.md git-sha.txt git-dirty.txt contract-sha256.txt swift-version.txt xcode-version.txt java-version.txt kotlin-version.txt python-version.txt)
for gate in python-tests formal-verify async-formal-verify swift-build swift-test kotlin-build contract-generate swift-runner kotlin-runner differential native-differential mutations async-runner async-mutations; do
  owned+=("$gate.exit-code" "$gate.stdout.log" "$gate.stderr.log" "$gate.command.log")
done
for file in "${owned[@]}"; do rm -f "$OUT_DIR/$file"; done
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$ROOT_DIR/.swift-cache/clang}"
export SWIFTPM_MODULECACHE_OVERRIDE="${SWIFTPM_MODULECACHE_OVERRIDE:-$ROOT_DIR/.swift-cache/modules}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$ROOT_DIR/.gradle-home}"
overall=0
mutation_skipped=0
FORMAL_OUT_DIR="$(mktemp -d "$OUT_DIR/formal-run.XXXXXX")"
ASYNC_FORMAL_OUT_DIR="$(mktemp -d "$OUT_DIR/async-formal-run.XXXXXX")"
run() {
  name="$1"; shift
  printf '$' > "$OUT_DIR/$name.command.log"
  printf ' %q' "$@" >> "$OUT_DIR/$name.command.log"
  printf '\n' >> "$OUT_DIR/$name.command.log"
  "$@" >"$OUT_DIR/$name.stdout.log" 2>"$OUT_DIR/$name.stderr.log"
  code=$?
  printf '%s\n' "$code" > "$OUT_DIR/$name.exit-code"
  if [ "$code" -ne 0 ]; then overall=1; fi
  return 0
}
run python-tests python3 -m unittest discover -s verification -p 'test_*.py' -v
run formal-verify bash scripts/formal-verify.sh "$FORMAL_OUT_DIR"
run async-formal-verify bash scripts/async-formal-verify.sh "$ASYNC_FORMAL_OUT_DIR"
run swift-build swift build --package-path ios
run swift-test swift test --package-path ios
run kotlin-build ./android/gradlew -p android build :library:installDist :async-library:installDist
run contract-generate python3 verification/generate.py --wire-input --output "$OUT_DIR/scenarios.json"
if [ "$(cat "$OUT_DIR/swift-build.exit-code")" = 0 ]; then
  run swift-runner bash -c 'ios/.build/debug/TraceRunner < "$1" > "$2"' _ "$OUT_DIR/scenarios.json" "$OUT_DIR/swift-traces.json"
else echo 'Swift runner not attempted: build failed' > "$OUT_DIR/swift-runner.stderr.log"; echo 125 > "$OUT_DIR/swift-runner.exit-code"; overall=1; fi
if [ "$(cat "$OUT_DIR/kotlin-build.exit-code")" = 0 ]; then
  run kotlin-runner bash -c 'android/library/build/install/library/bin/library < "$1" > "$2"' _ "$OUT_DIR/scenarios.json" "$OUT_DIR/kotlin-traces.json"
else echo 'Kotlin runner not attempted: build failed' > "$OUT_DIR/kotlin-runner.stderr.log"; echo 125 > "$OUT_DIR/kotlin-runner.exit-code"; overall=1; fi
if [ "$(cat "$OUT_DIR/swift-build.exit-code")" = 0 ] && [ "$(cat "$OUT_DIR/kotlin-build.exit-code")" = 0 ]; then
  run async-runner bash scripts/async-verify.sh "$OUT_DIR/async"
else echo 'Async runners not attempted: one or both builds failed' > "$OUT_DIR/async-runner.stderr.log"; echo 125 > "$OUT_DIR/async-runner.exit-code"; overall=1; fi
verify_args=(python3 verification/verify.py --report "$OUT_DIR/summary.json" --markdown "$OUT_DIR/summary.md")
if [ -f "$OUT_DIR/swift-traces.json" ]; then verify_args+=(--swift "$OUT_DIR/swift-traces.json"); fi
if [ -f "$OUT_DIR/kotlin-traces.json" ]; then verify_args+=(--kotlin "$OUT_DIR/kotlin-traces.json"); fi
run differential "${verify_args[@]}"
if [ -f "$OUT_DIR/swift-traces.json" ] && [ -f "$OUT_DIR/kotlin-traces.json" ]; then
  run native-differential python3 verification/compare.py --left "$OUT_DIR/swift-traces.json" --right "$OUT_DIR/kotlin-traces.json"
else
  echo 'not run: one or both runner traces are unavailable' > "$OUT_DIR/native-differential.command.log"
  echo 'NOT_RUN: one or both runner traces are unavailable' > "$OUT_DIR/native-differential.stdout.log"
  : > "$OUT_DIR/native-differential.stderr.log"
  echo 125 > "$OUT_DIR/native-differential.exit-code"
  overall=1
fi
if [ "${SKIP_MUTATIONS:-0}" = "1" ]; then
  mutation_skipped=1
  run async-mutations bash scripts/async-mutation-test.sh "$OUT_DIR/async-mutations" --skip
  run mutations python3 scripts/mutations.py verification/mutation-matrix.json --skip --output "$OUT_DIR/mutations"
else
  run async-mutations bash scripts/async-mutation-test.sh "$OUT_DIR/async-mutations"
  run mutations python3 scripts/mutations.py verification/mutation-matrix.json --output "$OUT_DIR/mutations"
fi

git rev-parse HEAD > "$OUT_DIR/git-sha.txt" 2>&1 || echo unavailable > "$OUT_DIR/git-sha.txt"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo dirty > "$OUT_DIR/git-dirty.txt"; else echo clean > "$OUT_DIR/git-dirty.txt"; fi
shasum -a 256 contract/specification.json > "$OUT_DIR/contract-sha256.txt"
swift --version > "$OUT_DIR/swift-version.txt" 2>&1 || true
xcodebuild -version > "$OUT_DIR/xcode-version.txt" 2>&1 || true
java -version > "$OUT_DIR/java-version.txt" 2>&1 || true
python3 --version > "$OUT_DIR/python-version.txt" 2>&1 || true
grep -E 'kotlin\("jvm"\) version' android/build.gradle.kts > "$OUT_DIR/kotlin-version.txt" 2>&1 || echo 'Kotlin plugin version unavailable' > "$OUT_DIR/kotlin-version.txt"
if [ "$overall" -ne 0 ]; then echo 'Overall: FAIL' > "$OUT_DIR/report.md"
elif [ "$mutation_skipped" -eq 1 ]; then echo 'Overall: INCOMPLETE (mutation matrix NOT_RUN)' > "$OUT_DIR/report.md"
else echo 'Overall: PASS' > "$OUT_DIR/report.md"; fi
for name in python-tests formal-verify async-formal-verify swift-build swift-test kotlin-build contract-generate swift-runner kotlin-runner async-runner differential native-differential mutations async-mutations; do
  printf '\n## %s (exit %s)\n' "$name" "$(cat "$OUT_DIR/$name.exit-code" 2>/dev/null || echo unknown)" >> "$OUT_DIR/report.md"
  printf '\nCommand: ' >> "$OUT_DIR/report.md"; cat "$OUT_DIR/$name.command.log" >> "$OUT_DIR/report.md"
  printf '\nstdout tail:\n```\n' >> "$OUT_DIR/report.md"; tail -n 10 "$OUT_DIR/$name.stdout.log" >> "$OUT_DIR/report.md" 2>/dev/null || true
  printf '```\nstderr tail:\n```\n' >> "$OUT_DIR/report.md"; tail -n 10 "$OUT_DIR/$name.stderr.log" >> "$OUT_DIR/report.md" 2>/dev/null || true
  printf '```\n' >> "$OUT_DIR/report.md"
done
for name in git-sha git-dirty contract-sha256 swift-version xcode-version java-version kotlin-version python-version; do
  printf '\n## %s\n```\n' "$name" >> "$OUT_DIR/report.md"; cat "$OUT_DIR/$name.txt" >> "$OUT_DIR/report.md"; printf '```\n' >> "$OUT_DIR/report.md"
done
if [ -f "$OUT_DIR/summary.md" ]; then printf '\n' >> "$OUT_DIR/report.md"; cat "$OUT_DIR/summary.md" >> "$OUT_DIR/report.md"; fi
if [ -f "$FORMAL_OUT_DIR/.formal-verification-owned" ] && [ -f "$FORMAL_OUT_DIR/report.md" ]; then
  printf '\n## Formal model report\n\n' >> "$OUT_DIR/report.md"
  cat "$FORMAL_OUT_DIR/report.md" >> "$OUT_DIR/report.md"
fi
if [ -f "$ASYNC_FORMAL_OUT_DIR/.async-formal-owned" ] && [ -f "$ASYNC_FORMAL_OUT_DIR/report.md" ]; then
  printf '\n## Async formal model report\n\n' >> "$OUT_DIR/report.md"
  cat "$ASYNC_FORMAL_OUT_DIR/report.md" >> "$OUT_DIR/report.md"
fi
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then cat "$OUT_DIR/report.md" >> "$GITHUB_STEP_SUMMARY"; fi
exit "$overall"
