#!/usr/bin/env python3
"""Freeze reviewed evaluator inputs and run only named evidence-producing stages.

This is a reproducibility guard for cooperative workers, not an adversarial sandbox.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time


class ProtocolError(ValueError):
    pass


PROTECTED = ['contract/', 'verification/', 'formal/', 'scripts/']
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def write_json(path, value):
    path.write_bytes(encode(value))


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ProtocolError('paths must be nonempty relative POSIX paths')
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or '.' in p.parts or str(p) != value.rstrip('/'):
        raise ProtocolError('noncanonical or escaping path: '+value)
    return value


def matches(path, rules):
    return any(path == rule.rstrip('/') or (rule.endswith('/') and path.startswith(rule)) for rule in rules)


def overlap(a, b):
    return matches(a.rstrip('/'), [b]) or matches(b.rstrip('/'), [a])


def positive(value, label, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ProtocolError(label+' must be positive and finite')
    if integer and not isinstance(value, int):
        raise ProtocolError(label+' must be an integer')


def metadata(value):
    if not isinstance(value, dict):
        raise ProtocolError('metadata must be an object')
    required = {'modelId', 'reasoningEffort', 'arm', 'seed', 'caches', 'tokenUsage', 'costUsd'}
    if set(value) != required:
        raise ProtocolError('metadata requires exactly '+', '.join(sorted(required)))
    for key in ('modelId','reasoningEffort','arm'):
        if value[key] is not None and (not isinstance(value[key],str) or not value[key]):
            raise ProtocolError('invalid metadata '+key)
    if value['seed'] is not None and (type(value['seed']) is not int):
        raise ProtocolError('seed must be integer or null')
    caches=value['caches']
    if not isinstance(caches,dict) or set(caches) != {'build','provider'} or any(x is not None and not isinstance(x,str) for x in caches.values()):
        raise ProtocolError('caches must declare build and provider status (or null)')
    for key in ('tokenUsage','costUsd'):
        x=value[key]
        if x is not None and (isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0):
            raise ProtocolError('invalid metric '+key)
    return value


def validate_config(config):
    keys={'changeId','baselineCommit','allowedPaths','protectedPaths','ignoredPaths','outputRoot',
          'maxAttempts','maxTotalSeconds','metadata','provenance','stages'}
    if not isinstance(config,dict) or set(config)!=keys:
        raise ProtocolError('config requires exactly '+', '.join(sorted(keys)))
    if not NAME.fullmatch(config['changeId']): raise ProtocolError('invalid changeId')
    if not isinstance(config['baselineCommit'],str) or not re.fullmatch('[0-9a-f]{40}',config['baselineCommit']):
        raise ProtocolError('baselineCommit must be a full Git commit ID')
    for key in ('allowedPaths','protectedPaths','ignoredPaths'):
        if not isinstance(config[key],list): raise ProtocolError(key+' must be an array')
        for value in config[key]: relative(value)
    protected=PROTECTED+config['protectedPaths']
    if any(overlap(a,p) for a in config['allowedPaths'] for p in protected):
        raise ProtocolError('allowed paths overlap protected evaluator')
    # Narrow protected exceptions may live under an excluded report tree.
    if any(overlap(i,p) for i in config['ignoredPaths'] for p in PROTECTED):
        # __pycache__ is an explicit generated output, never an evaluator input.
        if any(overlap(i,p) and not i.endswith('/__pycache__/') for i in config['ignoredPaths'] for p in PROTECTED):
            raise ProtocolError('ignored paths overlap protected evaluator')
    if not matches('.git',config['ignoredPaths']): raise ProtocolError('explicit .git/ exclusion required')
    out=relative(config['outputRoot'])
    if not matches(out,config['ignoredPaths']) or any(overlap(out+'/',p) for p in protected):
        raise ProtocolError('outputRoot must be excluded evidence outside protected paths')
    positive(config['maxAttempts'],'maxAttempts',True)
    positive(config['maxTotalSeconds'],'maxTotalSeconds')
    metadata(config['metadata'])
    if not isinstance(config['provenance'],dict) or not config['provenance']:
        raise ProtocolError('explicit nonempty provenance required')
    if not isinstance(config['stages'],dict) or not config['stages']: raise ProtocolError('named stages required')
    for name,stage in config['stages'].items():
        if not NAME.fullmatch(name): raise ProtocolError('invalid stage ID')
        if not isinstance(stage,dict) or set(stage)!= {'argv','cwd','timeoutSeconds','verdictProtocol','requiredArtifacts'}:
            raise ProtocolError('invalid frozen stage shape')
        if stage['cwd']!='{candidate}': raise ProtocolError('cwd must be {candidate}')
        positive(stage['timeoutSeconds'],'timeoutSeconds')
        argv=stage['argv']
        if not isinstance(argv,list) or not argv or any(not isinstance(a,str) or not a for a in argv):
            raise ProtocolError('argv must be a nonempty string array')
        for arg in argv:
            if re.search(r'[{}]',arg.replace('{candidate}','').replace('{output}','')):
                raise ProtocolError('only candidate/output substitutions allowed')
        protocol=stage['verdictProtocol']
        if protocol=='async-comparator':
            if argv[:3]==['python3','-m','verification.async_verify']: rest=argv[3:]
            elif argv[:2] in (['bash','scripts/async-verify.sh'],['bash','{candidate}/scripts/async-verify.sh']):
                if len(argv)!=3 or not argv[2].startswith('{output}/'): raise ProtocolError('invalid async wrapper argv')
                rest=['--output',argv[2]]
            else: raise ProtocolError('async protocol requires the known comparator entry point')
            options={}
            if len(rest)%2: raise ProtocolError('invalid comparator argv')
            for flag,arg in zip(rest[::2],rest[1::2]):
                if flag not in ('--output','--swift','--kotlin','--input') or flag in options: raise ProtocolError('unknown/duplicate comparator option')
                prefix='{output}/' if flag=='--output' else '{candidate}/'
                if not arg.startswith(prefix): raise ProtocolError('comparator paths must use '+prefix)
                relative(arg[len(prefix):]); options[flag]=arg
            if '--output' not in options: raise ProtocolError('comparator output required')
            primary=options['--output'][len('{output}/'):].rstrip('/')+'/async-report.json'
            validator='async-report'
        elif protocol=='full-gate':
            if len(argv)!=3 or argv[:2] not in (['bash','scripts/verify.sh'],['bash','{candidate}/scripts/verify.sh']) or not argv[2].startswith('{output}/'):
                raise ProtocolError('full protocol requires bash scripts/verify.sh {output}/...')
            relative(argv[2][len('{output}/'):])
            primary=argv[2][len('{output}/'):].rstrip('/')+'/report.md'; validator='full-report'
        else: raise ProtocolError('unknown verdict protocol')
        artifacts=stage['requiredArtifacts']
        if not isinstance(artifacts,list) or not artifacts: raise ProtocolError('required artifacts missing')
        seen=set()
        for artifact in artifacts:
            if not isinstance(artifact,dict) or set(artifact)!= {'path','validator'}: raise ProtocolError('invalid artifact shape')
            relative(artifact['path'])
            if artifact['path'] in seen or artifact['validator'] not in ('async-report','full-report','json-object','file'):
                raise ProtocolError('invalid/duplicate artifact')
            if artifact['validator'] in ('async-report','full-report') and artifact != {'path':primary,'validator':validator}:
                raise ProtocolError('only the stage primary report may supply its verdict')
            seen.add(artifact['path'])
        if {'path':primary,'validator':validator} not in artifacts: raise ProtocolError('known primary report required')


def contained(root, rel):
    relative(rel)
    path=root/rel.rstrip('/')
    current=root
    for part in PurePosixPath(rel).parts:
        current=current/part
        if current.is_symlink(): raise ProtocolError('symlink path refused: '+str(current))
    if not path.resolve().is_relative_to(root.resolve()): raise ProtocolError('path escapes root')
    return path


def regular_file(root, rel, required=False):
    path=contained(root,rel)
    if (path.exists() and not path.is_file()) or (required and not path.is_file()):
        raise ProtocolError('missing or nonregular evidence file: '+str(path))
    return path


def snapshot(root, config):
    root=root.resolve()
    protected=PROTECTED+config['protectedPaths']
    hashes={}
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in list(dirs)+files:
            path=Path(base)/name; rel=path.relative_to(root).as_posix()
            excluded=matches(rel,config['ignoredPaths']) and not matches(rel,config['protectedPaths'])
            has_protected_descendant=any(p.startswith(rel+'/') for p in protected)
            if excluded and not has_protected_descendant:
                if name in dirs: dirs.remove(name)
                continue
            if path.is_symlink(): raise ProtocolError('source symlink refused: '+rel)
            if name in files and not excluded:
                if not path.is_file(): raise ProtocolError('nonregular source refused: '+rel)
                hashes[rel]=digest_bytes(path.read_bytes())
    for path in ('verification/change_protocol.py','scripts/change-protocol.sh')+tuple(config['protectedPaths']):
        if not any(matches(p,[path]) for p in hashes): raise ProtocolError('protected input missing: '+path)
    return hashes


def source_digest(hashes):
    return digest_bytes(encode(hashes))


def freeze(root, config, destination):
    validate_config(config)
    root=Path(root).resolve(); destination=Path(destination).absolute()
    try: rel=destination.relative_to(root).as_posix()
    except ValueError as error: raise ProtocolError('manifest must be under candidate evidence') from error
    if not matches(rel,config['ignoredPaths']) or matches(rel,PROTECTED+config['protectedPaths']):
        raise ProtocolError('manifest must be excluded evidence')
    contained(root,rel)
    if destination.exists(): raise ProtocolError('never overwrite a frozen manifest; use a new revision')
    base=config['baselineCommit']
    for command in (['git','cat-file','-e',base+'^{commit}'],['git','merge-base','--is-ancestor',base,'HEAD']):
        proc=subprocess.run(command,cwd=root,capture_output=True)
        if proc.returncode: raise ProtocolError('baseline commit unavailable or not ancestor of current HEAD')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    hashes=snapshot(root,config)
    manifest={'schemaVersion':1,**config,'frozenHead':head,'frozenUtc':utc(),'inputSnapshot':hashes,
              'frozenSourceDigest':source_digest(hashes)}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as target: target.write(encode(manifest))
    return digest_bytes(destination.read_bytes())


def read_manifest(path, expected):
    data=Path(path).read_bytes()
    if not isinstance(expected,str) or digest_bytes(data)!=expected: raise ProtocolError('authoritative manifest digest mismatch')
    value=json.loads(data)
    if value.get('schemaVersion')!=1: raise ProtocolError('unsupported manifest')
    validate_config({k:v for k,v in value.items() if k not in ('schemaVersion','frozenHead','frozenUtc','inputSnapshot','frozenSourceDigest')})
    if source_digest(value['inputSnapshot'])!=value['frozenSourceDigest']: raise ProtocolError('frozen snapshot digest mismatch')
    return value


def check_sources(manifest, candidate):
    now=snapshot(candidate,manifest); before=manifest['inputSnapshot']
    protected=PROTECTED+manifest['protectedPaths']
    changed=[p for p in sorted(set(now)|set(before)) if now.get(p)!=before.get(p)
             and (matches(p,protected) or not matches(p,manifest['allowedPaths']))]
    if changed: raise ProtocolError('protected/out-of-scope membership or content changed: '+', '.join(changed))
    return source_digest(now)


def check(manifest_path, expected, candidate, result_path=None):
    manifest=read_manifest(manifest_path,expected); candidate=Path(candidate).resolve()
    try:
        digest=check_sources(manifest,candidate)
        if result_path is not None:
            path=Path(result_path).absolute()
            path=regular_file(candidate,path.relative_to(candidate).as_posix(),required=True)
            result=json.loads(path.read_text())
            if result['manifestDigest']!=expected or result['candidateDigest']!=digest:
                raise ProtocolError('result manifest/candidate digest mismatch')
            stage=manifest['stages'][result['stageId']]
            output=contained(candidate,manifest['outputRoot']+'/'+result['attemptId'])
            if not NAME.fullmatch(result['attemptId']) or path!=output/'result.json' or result['outputDirectory']!=str(output):
                raise ProtocolError('result attempt/output binding mismatch')
            argv=[a.replace('{candidate}',str(candidate)).replace('{output}',str(output)) for a in stage['argv']]
            if result['argv']!=argv or result['cwd']!=str(candidate) or result['verdictProtocol']!=stage['verdictProtocol']:
                raise ProtocolError('result frozen stage mismatch')
            evidence=captured_evidence(output,argv,str(candidate))
            if evidence!=result['evidence']: raise ProtocolError('result raw evidence digest mismatch')
            artifacts=read_artifacts(output,stage,result['startedNs'])
            if artifacts!=result['artifacts']: raise ProtocolError('result artifact digest mismatch')
            classification=classify(stage,result['exitCode'],result['timedOut'],output)
            if classification!=result['classification']: raise ProtocolError('result verdict mismatch')
            return {'classification':classification,'resultClassification':classification,
                    'bindingClassification':'PASS','manifestDigest':expected,'candidateDigest':digest}
        return {'classification':'PASS','manifestDigest':expected,'candidateDigest':digest}
    except (ProtocolError,OSError,ValueError,KeyError,TypeError) as error:
        failure={'classification':'INFRA_FAILURE','detail':str(error),'manifestDigest':expected}
        if result_path is not None: failure['bindingClassification']='INFRA_FAILURE'
        return failure


def utc():
    return datetime.now(timezone.utc).isoformat()


def async_report(path):
    report=json.loads(path.read_text())
    if not isinstance(report,dict) or set(report)!= {'status','scenarioCount','stepCount','verdicts','errors'}:
        raise ProtocolError('malformed async report')
    if any(type(report[k]) is not int or report[k]<=0 for k in ('scenarioCount','stepCount')):
        raise ProtocolError('async report must include exercised scenarios and steps')
    keys={'swift','kotlin','differential'}
    verdicts=report['verdicts']; errors=report['errors']
    if not isinstance(verdicts,dict) or set(verdicts)!=keys or any(v not in ('PASS','FAIL','INFRA_FAILURE','NOT_RUN') for v in verdicts.values()):
        raise ProtocolError('malformed native verdicts')
    if not isinstance(errors,dict) or set(errors)!=keys or any(not isinstance(x,(list,str)) for x in errors.values()):
        raise ProtocolError('malformed native diagnostics')
    for k,v in verdicts.items():
        if isinstance(errors[k],list) and any(not isinstance(x,str) for x in errors[k]): raise ProtocolError('malformed diagnostic entries')
        if v=='PASS' and errors[k]: raise ProtocolError('PASS native verdict has errors')
        if v=='FAIL' and (not isinstance(errors[k],list) or not errors[k]): raise ProtocolError('semantic native failure lacks mismatch evidence')
    status='PASS' if all(v=='PASS' for v in verdicts.values()) else 'FAIL'
    if report['status']!=status: raise ProtocolError('inconsistent async status')
    return report


def read_artifacts(output, stage, started_ns):
    hashes={}
    for artifact in stage['requiredArtifacts']:
        p=contained(output,artifact['path'])
        if not p.is_file() or p.stat().st_mtime_ns<started_ns: raise ProtocolError('missing or stale artifact: '+artifact['path'])
        data=p.read_bytes()
        if not data: raise ProtocolError('empty artifact: '+artifact['path'])
        validator=artifact['validator']
        if validator=='async-report': async_report(p)
        if validator=='json-object' and not isinstance(json.loads(data),dict): raise ProtocolError('artifact must be a JSON object')
        if validator=='full-report' and p.read_text().splitlines()[0] not in ('Overall: PASS','Overall: FAIL') and not p.read_text().splitlines()[0].startswith('Overall: INCOMPLETE'):
            raise ProtocolError('malformed aggregate report')
        hashes[artifact['path']]=digest_bytes(data)
    return hashes


def captured_evidence(output, argv, cwd):
    files={name:regular_file(output,name,required=True) for name in ('command.json','stdout.log','stderr.log')}
    if json.loads(files['command.json'].read_text())!={'argv':argv,'cwd':cwd}:
        raise ProtocolError('captured command disagrees with frozen argv/cwd')
    return {name:digest_bytes(path.read_bytes()) for name,path in files.items()}


def classify(stage, exit_code, timed_out, output):
    if timed_out or exit_code is None or exit_code<0: return 'INFRA_FAILURE'
    primary=next(a for a in stage['requiredArtifacts'] if a['validator'] in ('async-report','full-report'))
    if stage['verdictProtocol']=='full-gate':
        line=(output/primary['path']).read_text().splitlines()[0]
        if exit_code!=0: return 'INFRA_FAILURE'
        return 'PASS' if line=='Overall: PASS' else ('NOT_RUN' if line.startswith('Overall: INCOMPLETE') else 'INFRA_FAILURE')
    report=async_report(output/primary['path']); values=report['verdicts'].values()
    if 'INFRA_FAILURE' in values: return 'INFRA_FAILURE'
    if 'NOT_RUN' in values: return 'NOT_RUN'
    if exit_code==0 and report['status']=='PASS': return 'PASS'
    if exit_code==1 and report['status']=='FAIL' and any(report['verdicts'][k]=='FAIL' for k in ('swift','kotlin')):
        return 'SEMANTIC_FAIL'
    return 'INFRA_FAILURE'


@contextmanager
def budget_lock(output_root):
    with regular_file(output_root,'.budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def run(manifest_path, expected, candidate, stage_id, attempt_id, attempt_metadata=None):
    manifest=read_manifest(manifest_path,expected); candidate=Path(candidate).resolve()
    if stage_id not in manifest['stages']: raise ProtocolError('unknown frozen stage')
    if not isinstance(attempt_id,str) or not NAME.fullmatch(attempt_id): raise ProtocolError('invalid attempt ID')
    md=metadata(attempt_metadata if attempt_metadata is not None else manifest['metadata'])
    stage=manifest['stages'][stage_id]
    output_root=contained(candidate,manifest['outputRoot']); output_root.mkdir(parents=True,exist_ok=True)
    output=contained(output_root,attempt_id)
    # One manifest revision owns this ledger; crashed reservations consume budget.
    with budget_lock(output_root):
        owner=regular_file(output_root,'.manifest-digest')
        if owner.exists() and owner.read_text().strip()!=expected: raise ProtocolError('outputRoot belongs to another manifest revision')
        if not owner.exists(): owner.write_text(expected+'\n')
        if output.exists(): raise ProtocolError('output collision; no existing directory is replaced')
        attempts=[]
        for entry in output_root.iterdir():
            if entry.name in ('.budget.lock','.manifest-digest'): continue
            p=contained(output_root,entry.name)
            if not NAME.fullmatch(p.name) or not p.is_dir():
                raise ProtocolError('incompatible prior attempt entry: '+str(p))
            attempts.append(p)
        elapsed=0.0
        active=False
        for p in attempts:
            record_path=regular_file(p,'result.json')
            if not record_path.exists(): active=True; continue
            prior=json.loads(record_path.read_text())
            if prior['manifestDigest']!=expected: raise ProtocolError('mixed manifest ledger')
            elapsed+=prior['durationSeconds']
        if active: raise ProtocolError('unfinished attempt must be resolved before another run')
        stopped=len(attempts)>=manifest['maxAttempts'] or elapsed>=manifest['maxTotalSeconds']
        output.mkdir(mode=0o700)
    start=time.monotonic(); start_ns=time.time_ns()
    result={'manifestDigest':expected,'candidateDigest':None,'stageId':stage_id,'attemptId':attempt_id,
            'outputDirectory':str(output),'argv':[a.replace('{candidate}',str(candidate)).replace('{output}',str(output)) for a in stage['argv']],
            'cwd':str(candidate),'verdictProtocol':stage['verdictProtocol'],'metadata':md,
            'startedUtc':utc(),'startedNs':start_ns,'exitCode':None,'timedOut':False,'artifacts':{},'evidence':{},'classification':'NOT_RUN'}
    regular_file(output,'command.json').write_bytes(encode({'argv':result['argv'],'cwd':result['cwd']}))
    try:
        result['candidateDigest']=check_sources(manifest,candidate)
        if stopped:
            result['detail']='stopped: repair/elapsed budget exhausted'
        else:
            timeout=min(stage['timeoutSeconds'],manifest['maxTotalSeconds']-elapsed)
            env=os.environ.copy(); env['PYTHONPATH']=str(candidate)
            with regular_file(output,'stdout.log').open('wb') as stdout, regular_file(output,'stderr.log').open('wb') as stderr:
                proc=subprocess.Popen(result['argv'],cwd=candidate,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
                try: result['exitCode']=proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    result['timedOut']=True
                    os.killpg(proc.pid,signal.SIGKILL)
                    result['exitCode']=proc.wait()
            after=check_sources(manifest,candidate)
            if after!=result['candidateDigest']: raise ProtocolError('candidate source changed during evaluation')
            result['artifacts']=read_artifacts(output,stage,start_ns)
            result['classification']=classify(stage,result['exitCode'],result['timedOut'],output)
    except (ProtocolError,OSError,ValueError,KeyError,TypeError) as error:
        result['classification']='INFRA_FAILURE'; result['detail']=str(error)
    finally:
        result['endedUtc']=utc(); result['durationSeconds']=time.monotonic()-start
        try:
            for log in ('stdout.log','stderr.log'):
                path=regular_file(output,log)
                if not path.exists(): path.touch()
            result['evidence']=captured_evidence(output,result['argv'],result['cwd'])
        except (ProtocolError,OSError,ValueError,TypeError) as error:
            result['classification']='INFRA_FAILURE'; result['detail']=str(error)
        write_json(regular_file(output,'result.json'),result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze'); f.add_argument('--candidate',required=True); f.add_argument('--config',required=True); f.add_argument('--manifest',required=True)
    for name in ('check','run'):
        p=sub.add_parser(name); p.add_argument('--candidate',required=True); p.add_argument('--manifest',required=True); p.add_argument('--manifest-digest',required=True)
        if name=='check': p.add_argument('--result')
        else:
            p.add_argument('--stage',required=True); p.add_argument('--attempt',required=True); p.add_argument('--metadata')
    args=parser.parse_args(argv)
    try:
        if args.command=='freeze':
            d=freeze(args.candidate,json.loads(Path(args.config).read_text()),args.manifest)
            result={'classification':'PASS','manifestDigest':d,'manifest':str(Path(args.manifest).absolute())}
        elif args.command=='check': result=check(args.manifest,args.manifest_digest,args.candidate,args.result)
        else: result=run(args.manifest,args.manifest_digest,args.candidate,args.stage,args.attempt,json.loads(Path(args.metadata).read_text()) if args.metadata else None)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0 if result['classification']=='PASS' else 1 if result['classification']=='SEMANTIC_FAIL' else 2
    except (ProtocolError,OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({'classification':'INFRA_FAILURE','detail':str(error)})); return 2


if __name__=='__main__': raise SystemExit(main())
