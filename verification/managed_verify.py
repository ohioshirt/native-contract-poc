"""Managed evaluator entry point; absent native evidence is never PASS."""
import argparse
import json
from pathlib import Path
from verification.contract import validate
from verification.linearizability import check_document, read_json, validate_workload
from verification import managed_api, managed_mutations
from verification.managed_tools import capture, runner, write_report


def aggregate(verdicts):
    return next((v for v in ('INFRA_FAILURE','NOT_RUN','SEMANTIC_FAIL','INCONCLUSIVE') if v in verdicts), 'PASS')


def evaluate(root, out, *, skip_mutations=False):
    root,out = Path(root),Path(out);out.mkdir(parents=True,exist_ok=True)
    marker = out/'.managed-evaluator-owned'
    if any(out.iterdir()) and not marker.exists(): raise ValueError('output directory is nonempty and not evaluator-owned')
    marker.write_text('managed evaluator v1\n')
    stages = {}
    spec = read_json(root/'contract/specification.json');validate(spec,read_json(root/'contract/schema.json'))
    workload = read_json(root/'verification/managed-workload.json');validate_workload(workload)
    numeric_out = out/'numeric';numeric_out.mkdir(exist_ok=True)
    numeric = capture(['python3','-m','verification.numeric_model','--output',str(numeric_out)],out,'numeric',cwd=root)
    numeric_report = read_json(numeric_out/'numeric-report.json') if numeric['exitCode']==0 and (numeric_out/'numeric-report.json').is_file() else None
    stages['numeric'] = {'verdict':'PASS' if numeric_report and numeric_report.get('verdict')=='PASS' else 'INFRA_FAILURE','command':numeric}
    for platform in ('swift','kotlin'):
        directory = out/platform;directory.mkdir(exist_ok=True)
        command = runner(root,platform)
        if command is None:
            stages[f'{platform}-history']={'verdict':'NOT_RUN','reason':'managed history executable unavailable'}
        else:
            execution = capture(command,directory,'runner',cwd=root,stdin=json.dumps(workload).encode())
            if execution['exitCode'] != 0:
                stages[f'{platform}-history']={'verdict':'INFRA_FAILURE','reason':'history runner did not complete successfully','command':execution}
            else:
                try:
                    history = read_json(directory/'runner.stdout.log');write_report(directory,'history.json',history)
                    result = check_document(workload,history,spec);write_report(directory,'checker-report.json',result)
                    verdict = {'PASS':'PASS','FAIL':'SEMANTIC_FAIL','INVALID_HISTORY':'SEMANTIC_FAIL','INCONCLUSIVE':'INCONCLUSIVE'}[result['verdict']]
                    stages[f'{platform}-history']={'verdict':verdict,'checkerVerdict':result['verdict'],'command':execution}
                except (OSError,ValueError) as error:
                    stages[f'{platform}-history']={'verdict':'INFRA_FAILURE','reason':str(error),'command':execution}
        stages[f'{platform}-public-api']=managed_api.run(root,directory/'public-api',platform)
    if skip_mutations:
        stages['owner-mutations']={'verdict':'NOT_RUN','reason':'SKIP_MUTATIONS explicitly requested'}
    else: stages['owner-mutations']=managed_mutations.run(root,out/'owner-mutations')
    report = {'verdict':aggregate([s['verdict'] for s in stages.values()]),'stages':stages,'limits':'2 owners, IDs 1..3 finite model; completed histories <=16 operations; no unbounded refinement proof'}
    write_report(out,'managed-report.json',report)
    lines = [f"Overall: {report['verdict']}",'']+[f"- {name}: {stage['verdict']}" for name,stage in stages.items()]
    for log in sorted(out.glob('**/*.command.json')):
        lines += ['',f'Command record: {log.relative_to(out)}','```json',log.read_text().rstrip(),'```']
        for suffix in ('stdout.log','stderr.log'):
            raw = log.with_name(log.name.replace('command.json',suffix))
            if raw.exists(): lines += [f'{suffix} tail:','```', '\n'.join(raw.read_text(errors='replace').splitlines()[-10:]),'```']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));parser.add_argument('--output',required=True);parser.add_argument('--skip-mutations',action='store_true')
    args=parser.parse_args()
    try: result=evaluate(args.root,args.output,skip_mutations=args.skip_mutations)
    except (OSError,ValueError) as error:
        result={'verdict':'INFRA_FAILURE','reason':str(error)}
        if (Path(args.output)/'.managed-evaluator-owned').is_file(): write_report(args.output,'managed-report.json',result)
    print(json.dumps(result,indent=2));return 0 if result['verdict']=='PASS' else 2

if __name__=='__main__':raise SystemExit(main())
