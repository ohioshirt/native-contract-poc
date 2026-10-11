"""Owner guard native mutants; build success and real-history semantic RED required."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
from verification.linearizability import check_document
from verification.managed_tools import capture, runner, write_report


def patch(source, mutation):
    if source.count(mutation['original']) != 1: raise ValueError('mutation requires exactly one stable owner guard')
    return source.replace(mutation['original'],mutation['replacement'],1)


def classify(build_code, run_code, checker_verdict):
    if build_code != 0 or run_code != 0 or checker_verdict not in ('PASS','FAIL'): return 'INFRA_FAILURE'
    return 'PASS' if checker_verdict == 'FAIL' else 'SEMANTIC_FAIL'


def run(root, out):
    root,out = Path(root),Path(out);out.mkdir(parents=True,exist_ok=True)
    matrix = json.loads((root/'verification/managed-mutation-matrix.json').read_text())
    workload = json.loads((root/'verification/managed-workload.json').read_text())
    spec = json.loads((root/'contract/specification.json').read_text()); results = []
    for mutation in matrix['mutations']:
        dest = out/mutation['id']; dest.mkdir(parents=True,exist_ok=True)
        original = root/mutation['file']; record = {'id':mutation['id'],'platform':mutation['platform']}
        if not original.is_file():
            record.update(verdict='NOT_RUN',reason='managed native source missing');results.append(record);continue
        try: changed = patch(original.read_text(),mutation)
        except ValueError as error:
            record.update(verdict='INFRA_FAILURE',reason=str(error));results.append(record);continue
        frozen = {'version':1,'scenarios':[s for s in workload['scenarios'] if s['id']==mutation['scenario']]}
        if len(frozen['scenarios']) != 1: raise ValueError('mutation scenario missing/duplicate')
        with tempfile.TemporaryDirectory(prefix='managed-mutant-') as temp:
            candidate = Path(temp); platform = mutation['platform']; tree = 'ios' if platform == 'swift' else 'android'
            shutil.copytree(root/tree,candidate/tree,ignore=shutil.ignore_patterns('.build','build','.gradle','.DS_Store'))
            (candidate/mutation['file']).write_text(changed)
            env = os.environ.copy();env.setdefault('GRADLE_USER_HOME',str(root/'.gradle-home'))
            env.setdefault('CLANG_MODULE_CACHE_PATH',str(root/'.swift-cache/clang'));env.setdefault('SWIFTPM_MODULECACHE_OVERRIDE',str(root/'.swift-cache/modules'))
            build_argv = ['swift','build','--package-path',str(candidate/'ios'),'--product','ManagedHistoryRunner','--cache-path',str(root/'.swift-cache/swiftpm'),'--manifest-cache','local','--disable-dependency-cache'] if platform == 'swift' else [str(candidate/'android/gradlew'),'-p',str(candidate/'android'),'--no-daemon',':async-library:installDist']
            build = capture(build_argv,dest,'build',cwd=candidate,env=env,timeout=240);record['build'] = build
            command = runner(candidate,platform) if build['exitCode']==0 else None
            if command is None:
                record.update(verdict='INFRA_FAILURE',reason='mutant build/runner unavailable');results.append(record);continue
            execution = capture(command,dest,'runner',cwd=candidate,env=env,stdin=json.dumps(frozen).encode());record['runner']=execution
            verdict = 'INFRA_FAILURE'
            if execution['exitCode']==0:
                try:
                    history = json.loads((dest/'runner.stdout.log').read_text());write_report(dest,'history.json',history)
                    comparison = check_document(frozen,history,spec);write_report(dest,'checker-report.json',comparison)
                    verdict = comparison['verdict']
                except (OSError,ValueError) as error: record['reason']=str(error)
            record['checkerVerdict']=verdict
            record['verdict']=classify(build['exitCode'],execution['exitCode'],verdict)
            if verdict=='FAIL':
                # Require the deterministic foreign workload itself, not another incidental failure.
                record['semanticDetection']='real foreign-same-id history has no legal managed serialization'
            results.append(record)
    verdict = next((v for v in ('INFRA_FAILURE','NOT_RUN','SEMANTIC_FAIL') if any(r['verdict']==v for r in results)),'PASS')
    return write_report(out,'mutation-report.json',{'verdict':verdict,'mutations':results})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));parser.add_argument('--output',required=True)
    args=parser.parse_args();result=run(args.root,args.output);print(result['verdict']);return 0 if result['verdict']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
