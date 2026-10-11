"""Rebuild baseline and freeze/evaluate from Git inputs; no saved reports required."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from verification.managed_tools import capture

BASELINE = '8458f66a0691532a7f48e7ca1fb14fc86238b67f'
REMOTE = 'https://github.com/ohioshirt/native-contract-poc.git'


def build_config(root, out, commit):
    relative = out.relative_to(root).as_posix()
    return {
        'changeId': 'clean-reproduction-'+out.name,
        'baselineCommit': BASELINE,
        'allowedPaths': ['ios/Sources/AsyncNativeContract/', 'ios/Sources/ManagedHistoryRunner/', 'ios/Tests/AsyncNativeContractTests/', 'ios/Package.swift', 'android/async-library/'],
        'protectedPaths': [relative+'/baseline-native/', relative+'/baseline-hashes.json'],
        'ignoredPaths': ['.git/', 'ios/.build/', 'ios/.swift-cache/', 'android/.gradle/', 'android/library/build/', 'android/async-library/build/', '.gradle-home/', '.swift-cache/', '.formal-cache/', '.python-cache/', 'verification/__pycache__/', 'verification/formal/__pycache__/', 'scripts/__pycache__/', 'reports/'],
        'outputRoot': relative+'/attempts',
        'maxAttempts': 2,
        'maxTotalSeconds': 7200,
        'metadata': {'modelId': None, 'reasoningEffort': None, 'arm': 'clean-reproduction', 'seed': 0, 'caches': {'build': 'clone-local; baseline and candidate have separate caches', 'provider': None}, 'tokenUsage': None, 'costUsd': None},
        'provenance': {'candidateCommit': commit, 'baselineCommit': BASELINE, 'baselineRunnerHashes': relative+'/baseline-hashes.json', 'toolchains': relative+'/toolchains.json', 'network': 'dependency downloads permitted; no prior build artifacts copied'},
        'stages': {
            'old-native-red': {'argv': ['python3', '-m', 'verification.async_verify', '--output', '{output}/async', '--swift', '{candidate}/'+relative+'/baseline-native/AsyncTraceRunner', '--kotlin', '{candidate}/'+relative+'/baseline-native/async-library/bin/async-library'], 'cwd': '{candidate}', 'timeoutSeconds': 600, 'verdictProtocol': 'async-comparator', 'requiredArtifacts': [{'path': 'async/async-report.json', 'validator': 'async-report'}]},
            'candidate-full': {'argv': ['bash', 'scripts/verify.sh', '{output}/full'], 'cwd': '{candidate}', 'timeoutSeconds': 6600, 'verdictProtocol': 'full-gate', 'requiredArtifacts': [{'path': 'full/report.md', 'validator': 'full-report'}]},
        },
    }


def require_verdict(result, expected, *, binding=False):
    if result.get('classification') != expected:
        raise RuntimeError('expected '+expected+': '+json.dumps(result))
    if binding and (result.get('bindingClassification') != 'PASS' or result.get('resultClassification') != expected):
        raise RuntimeError('result binding did not retain evaluation: '+json.dumps(result))


def reproduce(root, out, commit, allow_working_copy=False):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('--commit must be a full Git SHA')
    if not out.is_relative_to(root/'reports') or out == root/'reports':
        raise ValueError('--output must be a fresh directory within candidate reports/')
    if os.environ.get('SKIP_MUTATIONS', '0') != '0':
        raise ValueError('SKIP_MUTATIONS is forbidden for acceptance')
    out.mkdir(parents=True, exist_ok=False)
    logs = out/'controller'

    def command(name, argv, *, cwd=root, env=None, expected=0, timeout=600):
        print('Running '+name, flush=True)
        record = capture(argv, logs, name, cwd=cwd, env=env, timeout=timeout)
        if record['exitCode'] != expected or record['timedOut'] or record['error']:
            raise RuntimeError(name+' failed; inspect '+str(logs/(name+'.stdout.log'))+' and '+str(logs/(name+'.stderr.log')))
        return (logs/(name+'.stdout.log')).read_text()

    if command('candidate-head', ['git', 'rev-parse', 'HEAD']).strip() != commit:
        raise ValueError('candidate HEAD differs from --commit')
    status = command('candidate-status', ['git', 'status', '--porcelain'])
    if status.strip() and not allow_working_copy:
        raise ValueError('candidate must be clean; working-copy mode is for precommit evaluator revisions only')
    cache_paths = (root/'.gradle-home', root/'.swift-cache', root/'.formal-cache', root/'ios/.build', root/'android/.gradle', root/'ios/.swift-cache', root/'android/library/build', root/'android/async-library/build')
    if not allow_working_copy and any(p.exists() for p in cache_paths):
        raise ValueError('fresh clone required: build/cache directories already exist')
    env = dict(os.environ)
    env.update(GRADLE_USER_HOME=str(root/'.gradle-home'), CLANG_MODULE_CACHE_PATH=str(root/'.swift-cache/clang'), SWIFTPM_MODULECACHE_OVERRIDE=str(root/'.swift-cache/modules'))
    versions = {}
    for name, argv in [('swift', ['swift', '--version']), ('xcode', ['xcodebuild', '-version']), ('sdk', ['xcrun', '--show-sdk-path']), ('java', ['java', '-version']), ('python', ['python3', '--version']), ('os', ['sw_vers'])]:
        command('toolchain-'+name, argv, env=env)
        versions[name] = {'stdout': (logs/('toolchain-'+name+'.stdout.log')).read_text(), 'stderr': (logs/('toolchain-'+name+'.stderr.log')).read_text()}
    versions['environment'] = {key: env.get(key) for key in ('GRADLE_USER_HOME', 'CLANG_MODULE_CACHE_PATH', 'SWIFTPM_MODULECACHE_OVERRIDE', 'PYTHONPYCACHEPREFIX', 'DEVELOPER_DIR', 'SWIFT_EXEC')}
    versions['workingCopyMode'] = allow_working_copy
    (out/'toolchains.json').write_text(json.dumps(versions, indent=2)+'\n')
    old = out/'old-source'
    command('baseline-clone', ['git', 'clone', REMOTE, str(old)], env=env)
    command('baseline-checkout', ['git', 'checkout', '--detach', BASELINE], cwd=old, env=env)
    old_env = dict(env)
    old_env.update(GRADLE_USER_HOME=str(old/'.gradle-home'), CLANG_MODULE_CACHE_PATH=str(old/'.swift-cache/clang'), SWIFTPM_MODULECACHE_OVERRIDE=str(old/'.swift-cache/modules'))
    command('baseline-swift-build', ['swift', 'build', '--package-path', 'ios', '--product', 'AsyncTraceRunner', '--cache-path', str(old/'.swift-cache/swiftpm'), '--manifest-cache', 'local', '--disable-dependency-cache'], cwd=old, env=old_env, timeout=1200)
    command('baseline-kotlin-build', ['./android/gradlew', '-p', 'android', ':async-library:installDist'], cwd=old, env=old_env, timeout=1200)
    baseline = out/'baseline-native'
    baseline.mkdir()
    shutil.copy2(old/'ios/.build/debug/AsyncTraceRunner', baseline/'AsyncTraceRunner')
    shutil.copytree(old/'android/async-library/build/install/async-library', baseline/'async-library')
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(baseline.rglob('*')) if p.is_file()}
    (out/'baseline-hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    config = build_config(root, out, commit)
    if allow_working_copy:
        config['metadata']['arm'] = 'precommit-working-copy'
        config['metadata']['caches']['build'] = 'candidate caches may be warm; baseline caches fresh'
    config_file = out/'config.json'
    config_file.write_text(json.dumps(config, indent=2)+'\n')
    manifest = out/'manifest.json'
    prefix = ['bash', 'scripts/change-protocol.sh']
    frozen = json.loads(command('freeze', prefix+['freeze', '--candidate', str(root), '--config', str(config_file), '--manifest', str(manifest)], env=env))
    require_verdict(frozen, 'PASS')
    digest = frozen['manifestDigest']
    (out/'manifest-digest.txt').write_text(digest+'\n')
    common = ['--candidate', str(root), '--manifest', str(manifest), '--manifest-digest', digest]
    results = {}
    for stage, expected, exit_code in [('old-native-red', 'SEMANTIC_FAIL', 1), ('candidate-full', 'PASS', 0)]:
        attempt = stage+'-01'
        result = json.loads(command(stage, prefix+['run']+common+['--stage', stage, '--attempt', attempt], env=env, expected=exit_code, timeout=7000))
        require_verdict(result, expected)
        bound = json.loads(command(stage+'-binding', prefix+['check']+common+['--result', str(out/'attempts'/attempt/'result.json')], env=env, expected=exit_code))
        require_verdict(bound, expected, binding=True)
        results[stage] = bound
    summary = {'classification': 'PASS', 'candidateCommit': commit, 'manifestDigest': digest, 'workingCopyMode': allow_working_copy, 'results': results}
    (out/'reproduction.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, sort_keys=True), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-working-copy', action='store_true', help='precommit refreeze only; not clean-clone acceptance')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        reproduce(root, Path(args.output).absolute().resolve(), args.commit, args.allow_working_copy)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({'classification': 'INFRA_FAILURE', 'detail': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
