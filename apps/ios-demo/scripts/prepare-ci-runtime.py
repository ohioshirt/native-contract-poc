"""Gate CI on Xcode 16.2 and the exact available iOS 18.2 runtime.

Acquisition uses Apple's documented command. This helper creates no devices,
never substitutes another version, and bounds all subprocesses by one deadline.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time


def select_runtime(document):
    rows = document.get('runtimes', []) if isinstance(document, dict) else []
    if not isinstance(rows, list):
        return None
    matches = [r for r in rows if isinstance(r, dict)
               and r.get('version') == '18.2' and r.get('isAvailable') is True
               and r.get('identifier') == 'com.apple.CoreSimulator.SimRuntime.iOS-18-2']
    return matches[0] if len(matches) == 1 else None


def run_command(argv, remaining):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        # The newly created process group is owned solely by this invocation.
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(argv, remaining, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def prepare(output, runner=run_command, timeout_seconds=600):
    output = Path(output)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('timeout_seconds must be finite and positive')
    output.mkdir(parents=True, exist_ok=True)
    result = {'version': 1, 'classification': 'INFRA_FAILURE', 'commands': [],
              'expectedXcode': '16.2', 'expectedRuntime': '18.2'}
    deadline = time.monotonic() + timeout_seconds

    def invoke(argv):
        ordinal = len(result['commands']) + 1
        row = {'argv': argv, 'stdout': f'command-{ordinal}.stdout.log',
               'stderr': f'command-{ordinal}.stderr.log'}
        result['commands'].append(row)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('runtime gate deadline exhausted')
        try:
            completed = runner(argv, remaining)
        except subprocess.TimeoutExpired as exc:
            row['timedOut'] = True
            for key, value in [('stdout', exc.output), ('stderr', exc.stderr)]:
                (output / row[key]).write_text(value.decode() if isinstance(value, bytes) else value or '')
            raise TimeoutError('runtime gate command timed out') from exc
        (output / row['stdout']).write_text(completed.stdout)
        (output / row['stderr']).write_text(completed.stderr)
        row.update(exitCode=completed.returncode, timedOut=False)
        if completed.returncode != 0:
            raise RuntimeError('runtime gate command failed')
        return completed.stdout

    try:
        version = invoke(['xcodebuild', '-version'])
        if version.splitlines()[0:1] != ['Xcode 16.2']:
            raise RuntimeError('selected Xcode does not match 16.2')
        result['observedXcode'] = version.strip()
        def inspect_runtime():
            document = json.loads(invoke(['xcrun', 'simctl', 'list', 'runtimes', '-j']))
            if not isinstance(document, dict) or not isinstance(document.get('runtimes'), list):
                raise RuntimeError('simctl runtime inventory has an invalid envelope')
            return select_runtime(document)

        runtime = inspect_runtime()
        if runtime is None:
            invoke(['xcodebuild', '-downloadPlatform', 'iOS', '-buildVersion', '18.2'])
            runtime = inspect_runtime()
        if runtime is None:
            raise RuntimeError('exact available iOS 18.2 runtime is absent after acquisition')
        result.update(classification='PASS', runtime=runtime)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        result['diagnostic'] = str(exc)
    (output / 'runtime-gate.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('--output must name a fresh directory')
    result = prepare(args.output, timeout_seconds=args.timeout_seconds)
    print(json.dumps(result))
    return 0 if result['classification'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
