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
INTEGRATION_PLATFORMS = {
    'integration-red': ['evaluator'],
    'candidate-ios': ['ios'],
    'candidate-android': ['android'],
    'integration-controls': ['ios', 'android'],
}
INTEGRATION_TRACE_VARIANTS = {
    'APP-01': [None], 'APP-02': [None], 'APP-03': [None], 'APP-04': [None], 'APP-05': [None],
    'APP-06': [None], 'APP-07': [None], 'APP-08': [None],
    'APP-09': ['replace-before', 'replace-after-before-verify'],
    'APP-10': ['clear-before', 'clear-after-before-verify'],
    'APP-10-RECOVER-OLD': [None],
    'APP-11': ['store-pause', 'publish-pause'],
    'APP-12-SAVED': [None], 'APP-12-LOGGED-OUT': [None],
    'APP-13': ['http500-current', 'malformed-current', 'disconnect-current', 'wrong-correlation-current', 'wrong-correlation-after-login-b'],
    'APP-14': [None],
}
INTEGRATION_CONTROL_TRACE_VARIANTS = {
    'CTRL-N1-LOGOUT': [None], 'CTRL-N1-NEW-LOGIN': [None], 'CTRL-N2-LATE-CLEAR': [None],
    'CTRL-N3-EARLY-PUBLISH': [None], 'CTRL-N4-FALSE-LOGOUT': [None],
}
INTEGRATION_RED_WITNESSES = {'APP-02': {'I2','I3'}, 'APP-04': {'I4'}}
INTEGRATION_CONTROL_WITNESSES = {
    'CTRL-N1-LOGOUT': ['I2', 'I3'],
    'CTRL-N1-NEW-LOGIN': ['I2', 'I4'],
    'CTRL-N2-LATE-CLEAR': ['I4'],
    'CTRL-N3-EARLY-PUBLISH': ['I6'],
    'CTRL-N4-FALSE-LOGOUT': ['I5', 'I8'],
}
MODEL_REQUIRED_WITNESSES = [
    'APP-02-success-after-logout',
    'APP-03-failure-after-logout',
    'APP-04-old-success-after-login-b',
    'APP-05-old-failure-after-login-b',
    'duplicate-delivery',
    'queued-logout-during-pause',
    'fault-retry-cleanup',
    'restart-bootstrap-cleanup',
    'foreign-same-id',
]
MODEL_MUTANT_WITNESSES = {
    'unconditional-success-commit': ['I2', 'I3', 'I4'],
    'reentrant-consumer': ['I1', 'I3'],
    'duplicate-deferred-clear': ['I4'],
    'unverified-publish': ['I6'],
    'failed-clear-ack': ['I8'],
}
MODEL_BOUNDS = {
    'dequeuedCommands': 6,
    'uiRevisions': 12,
    'owners': 2,
    'epochs': 3,
    'requestIdsPerOwner': 2,
    'queuedCommands': 2,
    'currentSlots': 1,
    'retainedOldSlots': 1,
    'replaysPerSlot': 1,
}
VERDICT_VALUES = {'PASS', 'SEMANTIC_FAIL', 'INVALID_HISTORY', 'INFRA_FAILURE', 'NOT_RUN', 'INCONCLUSIVE'}
SHA256 = re.compile(r'^sha256:[0-9a-f]{64}$')


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
    return any(
        (rule == '**/.DS_Store' and PurePosixPath(path).name == '.DS_Store')
        or path == rule.rstrip('/') or (rule.endswith('/') and path.startswith(rule))
        for rule in rules
    )


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
    if (config['changeId']=='standalone-native-app-integration'
            and (type(config['provenance'].get('maxAttemptsPerStage')) is not int
                 or config['provenance']['maxAttemptsPerStage']!=2)):
        raise ProtocolError('standalone integration requires its frozen two-attempt per-stage budget')
    if not isinstance(config['stages'],dict) or not config['stages']: raise ProtocolError('named stages required')
    for name,stage in config['stages'].items():
        if not NAME.fullmatch(name): raise ProtocolError('invalid stage ID')
        base_stage_keys={'argv','cwd','timeoutSeconds','verdictProtocol','requiredArtifacts'}
        if not isinstance(stage,dict): raise ProtocolError('invalid frozen stage shape')
        protocol=stage.get('verdictProtocol')
        integration_stage=protocol=='integration-comparator'
        expected_stage_keys=base_stage_keys|({'expectedPlatforms','requiredScenarioIds'} if integration_stage else set())
        if integration_stage and name in {'candidate-ios','candidate-android','integration-controls'}:
            expected_stage_keys |= {'expectedTraceBindings'}
        if integration_stage and name == 'integration-controls':
            expected_stage_keys |= {'expectedControlWitnesses', 'modelReportPath', 'requiredModelWitnesses', 'requiredMutantWitnesses'}
        if set(stage)!=expected_stage_keys:
            raise ProtocolError('invalid frozen stage shape')
        if stage['cwd']!='{candidate}': raise ProtocolError('cwd must be {candidate}')
        positive(stage['timeoutSeconds'],'timeoutSeconds')
        argv=stage['argv']
        if not isinstance(argv,list) or not argv or any(not isinstance(a,str) or not a for a in argv):
            raise ProtocolError('argv must be a nonempty string array')
        for arg in argv:
            if re.search(r'[{}]',arg.replace('{candidate}','').replace('{output}','')):
                raise ProtocolError('only candidate/output substitutions allowed')
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
        elif protocol=='integration-comparator':
            if name not in INTEGRATION_PLATFORMS or stage['expectedPlatforms']!=INTEGRATION_PLATFORMS[name]:
                raise ProtocolError('integration stage/platform membership is not frozen')
            required_ids=stage['requiredScenarioIds']
            if (not isinstance(required_ids,list) or not required_ids
                    or any(not isinstance(value,str) or not value for value in required_ids)
                    or len(set(required_ids))!=len(required_ids)):
                raise ProtocolError('integration requiredScenarioIds must be unique nonempty strings')
            if name=='integration-red' and required_ids!=['APP-02','APP-04']:
                raise ProtocolError('integration-red requires the frozen APP-02 and APP-04 unsafe witnesses')
            if name == 'integration-controls':
                witnesses = stage['expectedControlWitnesses']
                if not isinstance(witnesses, dict) or witnesses != INTEGRATION_CONTROL_WITNESSES:
                    raise ProtocolError('integration-controls must freeze the exact per-control witness inventory')
                if required_ids != list(INTEGRATION_CONTROL_WITNESSES):
                    raise ProtocolError('integration-controls scenario inventory differs from frozen controls')
                if stage['modelReportPath'] != 'model/baseline/report.json':
                    raise ProtocolError('integration-controls model report path is fixed')
                if stage['requiredModelWitnesses'] != MODEL_REQUIRED_WITNESSES:
                    raise ProtocolError('integration-controls model witness inventory is fixed')
                if stage['requiredMutantWitnesses'] != MODEL_MUTANT_WITNESSES:
                    raise ProtocolError('integration-controls mutant witness inventory is fixed')
            if name in {'candidate-ios','candidate-android','integration-controls'}:
                trace_contract = (INTEGRATION_CONTROL_TRACE_VARIANTS if name=='integration-controls'
                                  else INTEGRATION_TRACE_VARIANTS)
                if required_ids != list(trace_contract):
                    raise ProtocolError('native stage scenario inventory differs from the frozen variant inventory')
                expected_bindings = [
                    {'platform':platform,'scenarioId':scenario_id,'variantId':variant_id}
                    for platform in stage['expectedPlatforms']
                    for scenario_id in required_ids
                    for variant_id in trace_contract[scenario_id]
                ]
                if stage['expectedTraceBindings'] != expected_bindings:
                    raise ProtocolError('native stage trace-binding inventory differs from the frozen scenarios and variants')
            elif {'expectedControlWitnesses', 'modelReportPath', 'requiredModelWitnesses', 'requiredMutantWitnesses'} & set(stage):
                raise ProtocolError('control/model fields are only valid for integration-controls')
            expected_argv=['python3','-m','integration.reproduce','stage','--candidate','{candidate}',
                           '--stage',name,'--output','{output}/'+name]
            if argv!=expected_argv:
                raise ProtocolError('integration comparator requires the known frozen reproduce entry point')
            primary=name+'/report.json'; validator='integration-report'
        else: raise ProtocolError('unknown verdict protocol')
        artifacts=stage['requiredArtifacts']
        if not isinstance(artifacts,list) or not artifacts: raise ProtocolError('required artifacts missing')
        seen=set()
        for artifact in artifacts:
            if not isinstance(artifact,dict) or set(artifact)!= {'path','validator'}: raise ProtocolError('invalid artifact shape')
            relative(artifact['path'])
            if artifact['path'] in seen or artifact['validator'] not in ('async-report','full-report','integration-report','model-report','model-mutant-report','json-object','file'):
                raise ProtocolError('invalid/duplicate artifact')
            if artifact['validator'] in ('async-report','full-report','integration-report') and artifact != {'path':primary,'validator':validator}:
                raise ProtocolError('only the stage primary report may supply its verdict')
            if artifact['validator'] == 'model-report' and (
                name != 'integration-controls'
                or artifact['path'] != name + '/' + stage['modelReportPath']
            ):
                raise ProtocolError('only the frozen integration-controls model report is allowed')
            if artifact['validator'] == 'model-mutant-report' and (
                name != 'integration-controls'
                or artifact['path'] not in {
                    name + '/model/mutants/' + mutant + '/report.json'
                    for mutant in stage['requiredMutantWitnesses']
                }
            ):
                raise ProtocolError('only the frozen integration-controls mutant reports are allowed')
            seen.add(artifact['path'])
        if integration_stage and name == 'integration-controls' and {'path':name+'/'+stage['modelReportPath'],'validator':'model-report'} not in artifacts:
            raise ProtocolError('integration-controls requires its checked finite-model report')
        if integration_stage and name == 'integration-controls' and any(
            {'path':name+'/model/mutants/'+mutant+'/report.json','validator':'model-mutant-report'} not in artifacts
            for mutant in stage['requiredMutantWitnesses']
        ):
            raise ProtocolError('integration-controls requires each named mutant counterexample report')
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
            generated_caches=[item for item in config['ignoredPaths']
                              if item.endswith('/__pycache__/') or item=='**/.DS_Store']
            excluded=(matches(rel,generated_caches)
                      or (matches(rel,config['ignoredPaths']) and not matches(rel,config['protectedPaths'])))
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


def string_array(value, label):
    if (not isinstance(value,list) or any(not isinstance(item,str) or not item for item in value)
            or len(value)!=len(set(value))):
        raise ProtocolError(label+' must be an array of unique nonempty strings')
    return value


def model_report(path, required_witnesses):
    report=json.loads(path.read_text())
    keys={'version','classification','mutant','bounds','exploredStates','invariantChecks',
          'coverageBoundary','coverageExhaustiveWithinBound','searchComplete','limitReached',
          'abstraction','claims','witnesses','counterexample','missingCoverage','unexpectedMutantViolations','unexpectedMutantWitnesses'}
    if not isinstance(report,dict) or set(report)!=keys:
        raise ProtocolError('malformed finite-model report')
    if type(report['version']) is not int or report['version']!=1 or report['classification']!='PASS' or report['mutant'] is not None:
        raise ProtocolError('model report must be the successful non-mutant exploration')
    if report['bounds']!=MODEL_BOUNDS:
        raise ProtocolError('model finite bounds differ from the frozen integration contract')
    for field in ('exploredStates',):
        if type(report[field]) is not int or report[field]<=0:
            raise ProtocolError('model report state counts must be positive integers')
    if any(type(report[field]) is not bool for field in ('coverageBoundary','coverageExhaustiveWithinBound','searchComplete','limitReached')):
        raise ProtocolError('model coverage flags must be booleans')
    if (not report['searchComplete'] or report['limitReached'] or not report['coverageExhaustiveWithinBound']
            or report['coverageExhaustiveWithinBound'] != (report['searchComplete'] and not report['limitReached'])):
        raise ProtocolError('model report does not establish exhaustive search within the declared bound')
    checks=report['invariantChecks']
    if (not isinstance(checks,dict) or set(checks)!={'statesExamined','violations'}
            or type(checks['statesExamined']) is not int or checks['statesExamined']<report['exploredStates']
            or checks['violations']!=[]):
        raise ProtocolError('model invariant-check summary is incomplete or failed')
    claims=report['claims']
    if not isinstance(claims,dict) or claims!={'unboundedLiveness':False,'arbitraryNativeRefinement':False}:
        raise ProtocolError('model report overstates its guarantee boundary')
    abstraction=report['abstraction']
    if (not isinstance(abstraction,dict) or set(abstraction)!={'environment','excludedNoOps','execution'}
            or any(not isinstance(abstraction[key],str) or not abstraction[key] for key in ('environment','execution'))
            or not isinstance(abstraction['excludedNoOps'],list)
            or any(not isinstance(item,str) or not item for item in abstraction['excludedNoOps'])):
        raise ProtocolError('model abstraction disclosure is malformed')
    if (report['counterexample'] is not None or report['missingCoverage']!=[]
            or report['unexpectedMutantViolations']!=[] or report['unexpectedMutantWitnesses']!={}):
        raise ProtocolError('passing model report cannot omit witnesses or contain a counterexample')
    if not isinstance(required_witnesses,list) or not required_witnesses or len(required_witnesses)!=len(set(required_witnesses)):
        raise ProtocolError('frozen model witness inventory is malformed')
    witnesses=report['witnesses']
    if not isinstance(witnesses,dict) or set(witnesses)!=set(required_witnesses):
        raise ProtocolError('model witness membership differs from the frozen inventory')
    from integration import model as finite_model
    search=finite_model._search()
    expected=finite_model._base_report(
        search['classification'],search['exploredStates'],search['statesExamined'],search['witnesses'],
        mutant=None,counterexample=search['counterexample'],missing=search['missingCoverage'],
        boundary=search['boundary'],search_complete=search.get('searchComplete',False),
        limit_reached=search.get('limitReached',False),unexpected_violations=search.get('unexpectedViolations',[]),
        unexpected_witnesses=search.get('unexpectedWitnesses',{}),
    )
    expected['invariantChecks']['violations']=[] if search['classification']=='PASS' else ([search['counterexample']['invariant']] if search['counterexample'] else [])
    if report!=expected:
        raise ProtocolError('model report differs from a fresh bounded exploration')
    for name in required_witnesses:
        try:
            finite_model.replay_coverage_witness(name,witnesses[name])
        except (AssertionError,KeyError,TypeError,ValueError) as error:
            raise ProtocolError(f'model witness {name!r} failed transition replay: {error}') from error
    return report


def model_mutant_report(path, mutant, expected_invariants):
    report=json.loads(path.read_text())
    keys={'version','classification','mutant','bounds','exploredStates','invariantChecks',
          'coverageBoundary','coverageExhaustiveWithinBound','searchComplete','limitReached',
          'abstraction','claims','witnesses','counterexample','missingCoverage','unexpectedMutantViolations','unexpectedMutantWitnesses'}
    if not isinstance(report,dict) or set(report)!=keys:
        raise ProtocolError('malformed model mutant report')
    if (type(report['version']) is not int or report['version']!=1
            or report['classification']!='SEMANTIC_FAIL' or report['mutant']!=mutant):
        raise ProtocolError('model mutant report identity/classification mismatch')
    if report['bounds']!=MODEL_BOUNDS:
        raise ProtocolError('model mutant finite bounds differ from the frozen contract')
    if type(report['exploredStates']) is not int or report['exploredStates']<=0:
        raise ProtocolError('model mutant state count must be positive')
    if (not isinstance(report['searchComplete'],bool) or not isinstance(report['limitReached'],bool)
            or not isinstance(report['coverageExhaustiveWithinBound'],bool)
            or not isinstance(report['coverageBoundary'],bool)
            or (report['searchComplete'] and report['limitReached'])
            or report['coverageExhaustiveWithinBound'] != (report['searchComplete'] and not report['limitReached'])):
        raise ProtocolError('model mutant finite-search flags are inconsistent')
    missing_coverage=string_array(report['missingCoverage'],'model mutant missingCoverage')
    if missing_coverage and not report['limitReached']:
        raise ProtocolError('model mutant coverage gaps require a disclosed search cutoff')
    unexpected=string_array(report['unexpectedMutantViolations'],'unexpectedMutantViolations') if report['unexpectedMutantViolations'] else []
    if any(invariant not in {f'I{i}' for i in range(1,10)} or invariant in expected_invariants for invariant in unexpected):
        raise ProtocolError('model mutant unexpected invariant summary is malformed')
    if not isinstance(report['unexpectedMutantWitnesses'],dict) or set(report['unexpectedMutantWitnesses'])!=set(unexpected):
        raise ProtocolError('model mutant unexpected witnesses do not match the disclosed violation families')
    if report['claims']!={'unboundedLiveness':False,'arbitraryNativeRefinement':False}:
        raise ProtocolError('model mutant report overstates its guarantee boundary')
    counterexample=report['counterexample']
    if not isinstance(counterexample,dict) or set(counterexample)!={'invariant','trace','finalState'}:
        raise ProtocolError('model mutant report lacks a concrete counterexample')
    if counterexample['invariant'] not in expected_invariants:
        raise ProtocolError('model mutant counterexample is outside its frozen target invariant set')
    checks=report['invariantChecks']
    if (not isinstance(checks,dict) or set(checks)!={'statesExamined','violations'}
            or type(checks['statesExamined']) is not int or checks['statesExamined']<=0
            or checks['violations']!=[counterexample['invariant']]):
        raise ProtocolError('model mutant invariant summary disagrees with its counterexample')
    from integration import model as finite_model
    search=finite_model._search(mutant)
    expected=finite_model._base_report(
        search['classification'],search['exploredStates'],search['statesExamined'],search['witnesses'],
        mutant=mutant,counterexample=search['counterexample'],missing=search['missingCoverage'],
        boundary=search['boundary'],search_complete=search.get('searchComplete',False),
        limit_reached=search.get('limitReached',False),unexpected_violations=search.get('unexpectedViolations',[]),
        unexpected_witnesses=search.get('unexpectedWitnesses',{}),
    )
    expected['invariantChecks']['violations']=[] if search['classification']=='PASS' else ([search['counterexample']['invariant']] if search['counterexample'] else [])
    if report!=expected:
        raise ProtocolError('model mutant report differs from a fresh bounded exploration')
    try:
        replayed=finite_model.replay_trace(counterexample['trace'],mutant=mutant)
    except (AssertionError,KeyError,TypeError,ValueError) as error:
        raise ProtocolError(f'model mutant counterexample failed transition replay: {error}') from error
    if (replayed['trace']!=counterexample['trace'] or counterexample['invariant'] not in replayed['violations']
            or replayed['state']!=counterexample['finalState']):
        raise ProtocolError('model mutant counterexample disagrees with transition replay')
    for invariant,witness in report['unexpectedMutantWitnesses'].items():
        if not isinstance(witness,dict) or set(witness)!={'trace','finalState'}:
            raise ProtocolError('model mutant unexpected invariant witness is malformed')
        try:
            replayed_extra=finite_model.replay_trace(witness['trace'],mutant=mutant,stop_on_target=False)
        except (AssertionError,KeyError,TypeError,ValueError) as error:
            raise ProtocolError(f'unexpected model invariant {invariant!r} failed replay: {error}') from error
        if (replayed_extra['trace']!=witness['trace'] or invariant not in replayed_extra['violations']
                or replayed_extra['state']!=witness['finalState']):
            raise ProtocolError(f'unexpected model invariant {invariant!r} witness disagrees with replay')
    return report


def reference(value, command, *, allow_zero=False):
    fields={'processInstanceId','id'} if command else {'processInstanceId','localSequence'}
    number='id' if command else 'localSequence'
    minimum=0 if allow_zero else 1
    return (isinstance(value,dict) and set(value)==fields
            and isinstance(value.get('processInstanceId'),str) and bool(value['processInstanceId'])
            and type(value.get(number)) is int and minimum<=value[number]<=9223372036854775807)


def integration_report(path, stage):
    report=json.loads(path.read_text())
    keys={'version','stageId','classification','requiredScenarioIds','platformResults','violations',
          'deviceHashes','buildHashes','requiredArtifacts'}
    has_control_contract='expectedControlWitnesses' in stage
    has_trace_contract='expectedTraceBindings' in stage
    if has_control_contract: keys.add('controlResults')
    if has_trace_contract: keys.add('traceBindings')
    if not isinstance(report,dict) or set(report)!=keys:
        raise ProtocolError('malformed integration report')
    primary=next(item['path'] for item in stage['requiredArtifacts'] if item['validator']=='integration-report')
    frozen_stage_id=primary.split('/',1)[0]
    if type(report['version']) is not int or report['version']!=1 or report['stageId']!=frozen_stage_id:
        raise ProtocolError('invalid integration report version/stage')
    if not isinstance(report['classification'],str) or report['classification'] not in VERDICT_VALUES:
        raise ProtocolError('invalid integration report classification')
    required=string_array(report['requiredScenarioIds'],'requiredScenarioIds')
    if required!=stage['requiredScenarioIds']:
        raise ProtocolError('integration report scenario inventory differs from frozen stage')
    expected_artifacts=[item['path'] for item in stage['requiredArtifacts'] if item['validator']!='integration-report']
    platform_artifacts=[item['path'] for item in stage['requiredArtifacts']
                        if item['validator'] not in ('integration-report','model-report','model-mutant-report')]
    artifacts=string_array(report['requiredArtifacts'],'requiredArtifacts')
    for artifact in artifacts: relative(artifact)
    if artifacts!=expected_artifacts:
        raise ProtocolError('integration report artifact membership differs from frozen stage')

    rows=report['platformResults']
    if not isinstance(rows,list): raise ProtocolError('platformResults must be an array')
    row_keys={'platform','classification','requiredScenarioIds','completedScenarioIds','missingScenarioIds',
              'deviceHash','buildHash','requiredArtifacts'}
    if has_control_contract: row_keys.add('scenarioBuildHashes')
    if has_trace_contract: row_keys.add('validationScope')
    platforms=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!=row_keys:
            raise ProtocolError('integration platform result has invalid fields')
        platform=row['platform']
        if (not isinstance(platform,str) or platform not in {'evaluator','ios','android'}
                or platform not in stage['expectedPlatforms'] or platform in platforms):
            raise ProtocolError('integration report has duplicate or undeclared platform')
        platforms.append(platform)
        if not isinstance(row['classification'],str) or row['classification'] not in VERDICT_VALUES:
            raise ProtocolError('integration platform classification is invalid')
        if string_array(row['requiredScenarioIds'],'platform requiredScenarioIds')!=required:
            raise ProtocolError('platform scenario inventory differs from report inventory')
        completed=string_array(row['completedScenarioIds'],'completedScenarioIds')
        missing=string_array(row['missingScenarioIds'],'missingScenarioIds')
        if not set(completed)<=set(required) or set(completed)&set(missing) or set(completed)|set(missing)!=set(required):
            raise ProtocolError('platform scenario completion set is inconsistent')
        if has_trace_contract:
            scope=row.get('validationScope')
            if scope not in {'ci','local-observed','not-run'}:
                raise ProtocolError('native platform validation scope is invalid')
            if completed and scope not in {'ci','local-observed'}:
                raise ProtocolError('completed native history lacks an explicit validation scope')
        row_artifacts=string_array(row['requiredArtifacts'],'platform requiredArtifacts')
        for artifact in row_artifacts: relative(artifact)
        if not set(row_artifacts)<=set(platform_artifacts):
            raise ProtocolError('platform reports an undeclared artifact')
        if has_control_contract:
            build_index=row.get('scenarioBuildHashes')
            if not isinstance(build_index,dict) or not set(build_index)<=set(required):
                raise ProtocolError('control platform scenarioBuildHashes is malformed')
            if any(not isinstance(value,str) or not SHA256.fullmatch(value) for value in build_index.values()):
                raise ProtocolError('control case build hash must be sha256 hex')
            if not set(build_index)<=set(completed):
                raise ProtocolError('control build hash exists for an incomplete scenario')
            if (row['classification'] in {'PASS','SEMANTIC_FAIL'}
                    and set(completed)==set(required) and set(build_index)!=set(required)):
                raise ProtocolError('complete control platform result omits per-control build hashes')
        for field in ('deviceHash','buildHash'):
            value=row[field]
            if value is not None and (not isinstance(value,str) or not SHA256.fullmatch(value)):
                raise ProtocolError('device/build hash must be sha256 hex or null')
            if platform=='evaluator' and value is not None:
                raise ProtocolError('evaluator fixture cannot claim a native device/build hash')
            if (platform in {'ios','android'} and row['classification'] in {'PASS','SEMANTIC_FAIL'}
                    and set(row['completedScenarioIds'])==set(required) and value is None
                    and not (has_control_contract and field=='buildHash'
                             and set(row['scenarioBuildHashes'])==set(required))):
                raise ProtocolError('complete native result must bind device and build hashes')

    if not isinstance(report['deviceHashes'],dict) or not isinstance(report['buildHashes'],dict):
        raise ProtocolError('deviceHashes and buildHashes must be objects')
    if set(report['deviceHashes'])!=set(platforms) or set(report['buildHashes'])!=set(platforms):
        raise ProtocolError('device/build hash membership differs from platform results')
    for row in rows:
        if report['deviceHashes'][row['platform']]!=row['deviceHash'] or report['buildHashes'][row['platform']]!=row['buildHash']:
            raise ProtocolError('device/build hash summary differs from platform result')

    if has_trace_contract:
        expected_bindings={(row['platform'],row['scenarioId'],row['variantId']) for row in stage['expectedTraceBindings']}
        trace_bindings=report['traceBindings']
        if not isinstance(trace_bindings,list):
            raise ProtocolError('traceBindings must be an array')
        seen_bindings=set()
        platform_rows={row['platform']:row for row in rows}
        for binding in trace_bindings:
            if not isinstance(binding,dict) or set(binding)!={'platform','scenarioId','variantId','buildHash'}:
                raise ProtocolError('trace binding has invalid fields')
            platform,scenario_id,variant_id=binding['platform'],binding['scenarioId'],binding['variantId']
            key=(platform,scenario_id,variant_id)
            if key not in expected_bindings or key in seen_bindings:
                raise ProtocolError('trace binding is undeclared or duplicated')
            seen_bindings.add(key)
            build_hash=binding['buildHash']
            if not isinstance(build_hash,str) or not SHA256.fullmatch(build_hash):
                raise ProtocolError('trace binding build hash must be sha256 hex')
            expected_build = (
                platform_rows[platform]['scenarioBuildHashes'].get(scenario_id)
                if has_control_contract and platform in platform_rows
                else platform_rows[platform]['buildHash'] if platform in platform_rows else None
            )
            if platform not in platform_rows or expected_build!=build_hash:
                raise ProtocolError('trace build hash differs from its owning platform result')
        if report['classification'] in {'PASS','SEMANTIC_FAIL'} and seen_bindings!=expected_bindings:
            raise ProtocolError('complete native report omits a scenario/variant trace binding')

    violations=report['violations']
    if not isinstance(violations,list): raise ProtocolError('violations must be an array')
    violation_keys={'scenarioId','invariant','commandRef','eventRef','expected','actual'}
    for violation in violations:
        if not isinstance(violation,dict) or set(violation)!=violation_keys:
            raise ProtocolError('integration violation has invalid fields')
        if not isinstance(violation['scenarioId'],str) or not violation['scenarioId']:
            raise ProtocolError('integration violation scenarioId is invalid')
        semantic=report['classification']=='SEMANTIC_FAIL'
        if semantic:
            if (violation['scenarioId'] not in required or not isinstance(violation['invariant'],str)
                    or violation['invariant'] not in {f'I{i}' for i in range(1,10)}):
                raise ProtocolError('semantic violation lacks a frozen scenario/invariant')
            if not reference(violation['commandRef'],True) or not reference(violation['eventRef'],False):
                raise ProtocolError('semantic violation lacks positive command/event provenance')
            if violation['expected']==violation['actual']:
                raise ProtocolError('semantic violation does not contain a concrete mismatch')
        else:
            if not isinstance(violation['invariant'],str) or not violation['invariant']:
                raise ProtocolError('nonsemantic violation invariant is invalid')
            if not reference(violation['commandRef'],True,allow_zero=True) or not reference(violation['eventRef'],False,allow_zero=True):
                raise ProtocolError('nonsemantic violation references are malformed')
    if has_control_contract:
        control_rows=report['controlResults']
        if not isinstance(control_rows,list):
            raise ProtocolError('integration control results must be an array')
        control_ids=stage['requiredScenarioIds']
        expected_witnesses=stage['expectedControlWitnesses']
        control_pairs=set()
        for control in control_rows:
            if not isinstance(control,dict) or set(control)!={'platform','controlId','classification','observedWitnesses'}:
                raise ProtocolError('integration control result has invalid fields')
            platform,control_id=control['platform'],control['controlId']
            if platform not in stage['expectedPlatforms'] or control_id not in control_ids:
                raise ProtocolError('integration control result names an undeclared platform/control')
            pair=(platform,control_id)
            if pair in control_pairs:
                raise ProtocolError('duplicate platform/control result')
            control_pairs.add(pair)
            if control['classification'] not in {'DETECTED','NOT_DETECTED'}:
                raise ProtocolError('integration control result classification is invalid')
            observed=string_array(control['observedWitnesses'],'control observedWitnesses')
            if any(invariant not in {f'I{i}' for i in range(1,10)} for invariant in observed):
                raise ProtocolError('integration control result has an unknown invariant witness')
            required=expected_witnesses[control_id]
            if control['classification']=='DETECTED' and not set(required)<=set(observed):
                raise ProtocolError('control is marked detected without its frozen invariant witness')
            if control['classification']=='NOT_DETECTED' and set(required)<=set(observed):
                raise ProtocolError('control is marked not detected despite containing every required witness')
        complete_control_pairs={(platform,control_id) for platform in stage['expectedPlatforms'] for control_id in control_ids}
        if report['classification'] in {'PASS','SEMANTIC_FAIL'} and control_pairs!=complete_control_pairs:
            raise ProtocolError('completed integration-control report omits a platform/control result')
        if report['classification']=='PASS' and any(row['classification']!='DETECTED' for row in control_rows):
            raise ProtocolError('integration-controls cannot pass unless every mutation witness was detected')
        model_path=Path(path).parent/stage['modelReportPath']
        if not model_path.is_file():
            raise ProtocolError('integration-controls model report is missing')
        model_report(model_path,stage['requiredModelWitnesses'])
        for mutant, invariants in stage['requiredMutantWitnesses'].items():
            mutant_path=Path(path).parent/'model'/'mutants'/mutant/'report.json'
            if not mutant_path.is_file():
                raise ProtocolError('integration-controls mutant model report is missing: '+mutant)
            model_mutant_report(mutant_path,mutant,invariants)

    if report['classification']=='SEMANTIC_FAIL':
        if not violations or not any(row['classification']=='SEMANTIC_FAIL' for row in rows):
            raise ProtocolError('semantic integration report requires a platform failure and concrete mismatches')
        if report['stageId']=='integration-red':
            observed={scenario:set() for scenario in required}
            for violation in violations:
                observed[violation['scenarioId']].add(violation['invariant'])
            for scenario, invariants in INTEGRATION_RED_WITNESSES.items():
                if not invariants<=observed.get(scenario,set()):
                    raise ProtocolError('integration-red lacks its scenario-specific unsafe witness invariants')
    elif report['classification']=='PASS':
        if violations or any(row['classification']!='PASS' for row in rows):
            raise ProtocolError('PASS integration report cannot contain violations or failed platform results')
    elif report['classification']=='INVALID_HISTORY':
        if not violations or not any(row['classification']=='INVALID_HISTORY' for row in rows):
            raise ProtocolError('INVALID_HISTORY report requires a concrete invalid platform history')
    return report


def read_artifacts(output, stage, started_ns, *, verify_mtime=True):
    hashes={}
    for artifact in stage['requiredArtifacts']:
        p=contained(output,artifact['path'])
        if not p.is_file(): raise ProtocolError('missing artifact: '+artifact['path'])
        # Artifact downloads can rewrite extraction mtimes. Portable ledger
        # verification binds the original record and byte hashes instead.
        if verify_mtime and p.stat().st_mtime_ns<started_ns:
            raise ProtocolError('missing or stale artifact: '+artifact['path'])
        data=p.read_bytes()
        if not data: raise ProtocolError('empty artifact: '+artifact['path'])
        validator=artifact['validator']
        if validator=='async-report': async_report(p)
        if validator=='integration-report': integration_report(p,stage)
        if validator=='model-report':
            if 'requiredModelWitnesses' not in stage: raise ProtocolError('model report is outside a model-bound stage')
            model_report(p,stage['requiredModelWitnesses'])
        if validator=='model-mutant-report':
            relative_path=artifact['path'].split('/')
            if len(relative_path)!=5: raise ProtocolError('model mutant artifact path is malformed')
            mutant=relative_path[3]
            if mutant not in stage.get('requiredMutantWitnesses',{}):
                raise ProtocolError('model mutant artifact is undeclared by the stage')
            model_mutant_report(p,mutant,stage['requiredMutantWitnesses'][mutant])
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
    primary=next(a for a in stage['requiredArtifacts'] if a['validator'] in ('async-report','full-report','integration-report'))
    if stage['verdictProtocol']=='full-gate':
        line=(output/primary['path']).read_text().splitlines()[0]
        if exit_code!=0: return 'INFRA_FAILURE'
        return 'PASS' if line=='Overall: PASS' else ('NOT_RUN' if line.startswith('Overall: INCOMPLETE') else 'INFRA_FAILURE')
    if stage['verdictProtocol']=='integration-comparator':
        report=integration_report(output/primary['path'],stage)
        if any(row.get('validationScope')=='local-observed' for row in report['platformResults']):
            return 'INCONCLUSIVE'
        statuses=[report['classification']]+[row['classification'] for row in report['platformResults']]
        if 'INFRA_FAILURE' in statuses: return 'INFRA_FAILURE'
        if 'INVALID_HISTORY' in statuses:
            return 'INVALID_HISTORY' if exit_code==1 else 'INFRA_FAILURE'
        if 'NOT_RUN' in statuses: return 'NOT_RUN'
        if 'INCONCLUSIVE' in statuses: return 'INCONCLUSIVE'
        rows={row['platform']:row for row in report['platformResults']}
        if set(rows)!=set(stage['expectedPlatforms']): return 'INCONCLUSIVE'
        required=set(stage['requiredScenarioIds'])
        for row in rows.values():
            if set(row['completedScenarioIds'])!=required or row['missingScenarioIds']:
                return 'INCONCLUSIVE'
        membership=set().union(*(set(row['requiredArtifacts']) for row in rows.values()))
        required_artifacts={item['path'] for item in stage['requiredArtifacts']
                            if item['validator'] not in ('integration-report','model-report','model-mutant-report')}
        if membership!=required_artifacts: return 'INCONCLUSIVE'
        if report['classification']=='PASS':
            if exit_code==0 and all(row['classification']=='PASS' for row in rows.values()): return 'PASS'
            return 'INFRA_FAILURE'
        if report['classification']=='SEMANTIC_FAIL':
            if exit_code==1 and report['violations'] and any(row['classification']=='SEMANTIC_FAIL' for row in rows.values()):
                return 'SEMANTIC_FAIL'
            return 'INFRA_FAILURE'
        if report['classification']=='INCONCLUSIVE': return 'INCONCLUSIVE'
        if report['classification']=='NOT_RUN': return 'NOT_RUN'
        return 'INFRA_FAILURE'
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
        stage_attempts=0
        for p in attempts:
            record_path=regular_file(p,'result.json')
            if not record_path.exists(): active=True; continue
            prior=json.loads(record_path.read_text())
            if prior['manifestDigest']!=expected: raise ProtocolError('mixed manifest ledger')
            elapsed+=prior['durationSeconds']
            if prior.get('stageId')==stage_id: stage_attempts+=1
        if active: raise ProtocolError('unfinished attempt must be resolved before another run')
        per_stage_limit=manifest['provenance'].get('maxAttemptsPerStage')
        if manifest['changeId']=='standalone-native-app-integration':
            if type(per_stage_limit) is not int or per_stage_limit<=0:
                raise ProtocolError('frozen per-stage attempt limit is invalid')
        else:
            per_stage_limit=None
        stopped=(len(attempts)>=manifest['maxAttempts'] or elapsed>=manifest['maxTotalSeconds']
                 or (per_stage_limit is not None and stage_attempts>=per_stage_limit))
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
            result['detail']='stopped: global or per-stage repair/elapsed budget exhausted'
        else:
            timeout=min(stage['timeoutSeconds'],manifest['maxTotalSeconds']-elapsed)
            env=os.environ.copy(); env['PYTHONPATH']=str(candidate); env['PYTHONDONTWRITEBYTECODE']='1'
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
