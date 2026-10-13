"""Real-process controls for the frozen change protocol."""
import json
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from verification import change_protocol as protocol
except ImportError:
    protocol = None


class ChangeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(protocol, 'the frozen change protocol must exist')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        for path, content in {
            'verification/change_protocol.py': '# protected protocol\n',
            'verification/__init__.py': '',
            'scripts/change-protocol.sh': '# protected wrapper\n',
            'scripts/verify.sh': 'mkdir -p "$1"; echo "Overall: PASS" > "$1/report.md"\n',
            'integration/__init__.py': '',
            'integration/reproduce.py': '# fake integration stage entry point\n',
            'integration/scenarios.json': '{"version":1,"scenarios":[]}\n',
            'contract/specification.json': '{}',
            'formal/model.tla': 'model',
            'ios/Sources/AsyncNativeContract/session.swift': 'native',
            'core.txt': 'core',
            'reports/baseline/runner': 'preserved',
        }.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.writer('pass')
        self.integration_writer('pass')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Protocol Test', '-c', 'user.email=test@example.invalid', 'add', 'core.txt'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Protocol Test', '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'baseline'], check=True)
        baseline = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        self.config = {
            'changeId': 'test-change', 'baselineCommit': baseline,
            'allowedPaths': ['ios/Sources/AsyncNativeContract/'],
            'protectedPaths': ['reports/baseline/'],
            'ignoredPaths': ['.git/', 'reports/', 'verification/__pycache__/', 'integration/__pycache__/'],
            'outputRoot': 'reports/attempts',
            'maxAttempts': 3, 'maxTotalSeconds': 30,
            'metadata': {'modelId': 'test-model', 'reasoningEffort': 'high', 'arm': 'test', 'seed': None,
                         'caches': {'build': 'cold', 'provider': None}, 'tokenUsage': None, 'costUsd': None},
            'provenance': {'toolchain': 'test Python'},
            'stages': {
                'async': {'argv': ['python3', '-m', 'verification.async_verify', '--output', '{output}/async'],
                          'cwd': '{candidate}', 'timeoutSeconds': 3, 'verdictProtocol': 'async-comparator',
                          'requiredArtifacts': [{'path': 'async/async-report.json', 'validator': 'async-report'}]},
                'full': {'argv': ['bash', 'scripts/verify.sh', '{output}/full'], 'cwd': '{candidate}',
                         'timeoutSeconds': 3, 'verdictProtocol': 'full-gate',
                         'requiredArtifacts': [{'path': 'full/report.md', 'validator': 'full-report'}]},
                'integration-red': {
                    'argv': ['python3', '-m', 'integration.reproduce', 'stage', '--candidate', '{candidate}',
                             '--stage', 'integration-red', '--output', '{output}/integration-red'],
                    'cwd': '{candidate}', 'timeoutSeconds': 3, 'verdictProtocol': 'integration-comparator',
                    'expectedPlatforms': ['evaluator'],
                    'requiredScenarioIds': ['APP-02', 'APP-04'],
                    'requiredArtifacts': [
                        {'path': 'integration-red/report.json', 'validator': 'integration-report'},
                        {'path': 'integration-red/APP-02/trace.json', 'validator': 'json-object'},
                        {'path': 'integration-red/APP-04/trace.json', 'validator': 'json-object'},
                    ],
                },
            },
        }
        self.manifest = self.root / 'reports/manifest.json'

    def writer(self, mode):
        body = """import argparse, json, os, signal, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--output', required=True); a=p.parse_args()
o=Path(a.output); o.mkdir(parents=True, exist_ok=True)
mode=MODE
if mode=='timeout': time.sleep(10)
if mode=='signal': os.kill(os.getpid(), signal.SIGTERM)
if mode=='missing': raise SystemExit(0)
report={'status':'PASS', 'scenarioCount':1, 'stepCount':1,
        'verdicts':{'swift':'PASS','kotlin':'PASS','differential':'PASS'},
        'errors':{'swift':[],'kotlin':[],'differential':[]}}
if mode=='semantic':
 report['status']='FAIL'; report['verdicts']['swift']='FAIL'; report['verdicts']['differential']='FAIL'
 report['errors']['swift']=['s1 step 2 expected Unauthenticated, got Refreshing']
 report['errors']['differential']=['different states']
if mode=='infra': report['status']='FAIL'; report['verdicts']['swift']='INFRA_FAILURE'
if mode=='notrun': report['status']='FAIL'; report['verdicts']['swift']='NOT_RUN'
if mode=='malformed': report={'status':'PASS'}
(o/'async-report.json').write_text(json.dumps(report))
if mode=='stale': os.utime(o/'async-report.json',(1,1))
print('fixture stdout'); print('fixture stderr', file=__import__('sys').stderr)
raise SystemExit(1 if mode in ('semantic','infra','notrun','nonzero') else 0)
""".replace('MODE', repr(mode))
        (self.root / 'verification/async_verify.py').write_text(body)

    def integration_writer(self, mode):
        body = '''import argparse, json, os, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("command"); p.add_argument("--candidate",required=True); p.add_argument("--stage",required=True); p.add_argument("--output",required=True); a=p.parse_args()
out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
required=["APP-02","APP-04"]
paths=["integration-red/APP-02/trace.json","integration-red/APP-04/trace.json"]
for scenario in required:
 d=out/scenario; d.mkdir(parents=True,exist_ok=True); (d/"trace.json").write_text(json.dumps({"scenarioId":scenario}))
mode=MODE
classification="SEMANTIC_FAIL" if mode=="semantic" else ("INVALID_HISTORY" if mode=="invalid-history" else "PASS")
row_status=classification
platforms=[{"platform":"evaluator","classification":row_status,"requiredScenarioIds":required,"completedScenarioIds":required,"missingScenarioIds":[],"deviceHash":None,"buildHash":None,"requiredArtifacts":paths}]
if mode=="missing-platform": platforms=[]
if mode=="missing-scenario": platforms[0]["completedScenarioIds"]=["APP-02"]; platforms[0]["missingScenarioIds"]=["APP-04"]
if mode=="missing-artifact": platforms[0]["requiredArtifacts"]=[paths[0]]
violations=[]
if mode=="semantic":
 violations=[
  {"scenarioId":"APP-02","invariant":"I2","commandRef":{"processInstanceId":"attempt-01/APP-02/p1","id":5},"eventRef":{"processInstanceId":"attempt-01/APP-02/p1","localSequence":25},"expected":"no credential mutation","actual":"unconditional stale commit"},
  {"scenarioId":"APP-02","invariant":"I3","commandRef":{"processInstanceId":"attempt-01/APP-02/p1","id":5},"eventRef":{"processInstanceId":"attempt-01/APP-02/p1","localSequence":25},"expected":"Absent after Logout","actual":"old A credential present"},
  {"scenarioId":"APP-04","invariant":"I4","commandRef":{"processInstanceId":"attempt-01/APP-04/p1","id":6},"eventRef":{"processInstanceId":"attempt-01/APP-04/p1","localSequence":31},"expected":"B remains present","actual":"old A credential replaces B"},
 ]
if mode=="invalid-history":
 violations=[{"scenarioId":"APP-02","invariant":"HISTORY","commandRef":{"processInstanceId":"attempt-01/APP-02/p1","id":0},"eventRef":{"processInstanceId":"attempt-01/APP-02/p1","localSequence":0},"expected":"well-formed frozen evidence","actual":"invalid command event reference"}]
if mode=="wrong-invariants": violations[0]["invariant"]="I6"
if mode=="bad-semantic": violations=[]
device_hashes={row["platform"]:row["deviceHash"] for row in platforms}
build_hashes={row["platform"]:row["buildHash"] for row in platforms}
report={"version":1,"stageId":a.stage,"classification":classification,"requiredScenarioIds":required,"platformResults":platforms,"violations":violations,"deviceHashes":device_hashes,"buildHashes":build_hashes,"requiredArtifacts":paths}
(out/"report.json").write_text(json.dumps(report))
if mode=="stale": os.utime(out/"APP-02"/"trace.json",(1,1))
print("integration fixture output")
raise SystemExit(1 if mode in ("semantic","invalid-history","exit-one-pass","bad-semantic","wrong-invariants") else 0)
'''.replace('MODE', repr(mode))
        (self.root / 'integration/reproduce.py').write_text(body)

    def freeze(self):
        self.revision = getattr(self, 'revision', -1) + 1
        self.config['outputRoot'] = 'reports/attempts' + (('-revision'+str(self.revision)) if self.revision else '')
        self.digest = protocol.freeze(self.root, self.config, self.manifest)
        return json.loads(self.manifest.read_text())

    def run_stage(self, attempt='a1', stage='async'):
        return protocol.run(self.manifest, self.digest, self.root, stage, attempt)

    def test_capture_binds_fresh_artifact_and_exact_candidate(self):
        manifest = self.freeze()
        self.assertEqual(manifest['baselineCommit'], self.config['baselineCommit'])
        result = self.run_stage()
        self.assertEqual(result['classification'], 'PASS')
        self.assertEqual(result['manifestDigest'], self.digest)
        self.assertEqual(result['stageId'], 'async')
        self.assertEqual(result['metadata']['costUsd'], None)
        self.assertEqual(result['metadata']['tokenUsage'], None)
        self.assertEqual((Path(result['outputDirectory']) / 'stderr.log').read_text(), 'fixture stderr\n')
        self.assertGreaterEqual(result['durationSeconds'], 0)
        self.assertEqual(protocol.check(self.manifest, self.digest, self.root, Path(result['outputDirectory']) / 'result.json')['classification'], 'PASS')
        (self.root/'ios/Sources/AsyncNativeContract/session.swift').write_text('native revision')
        self.assertEqual(protocol.check(self.manifest, self.digest, self.root)['classification'], 'PASS')
        self.assertEqual(protocol.check(self.manifest, self.digest, self.root, Path(result['outputDirectory']) / 'result.json')['classification'], 'INFRA_FAILURE')

    def test_legacy_protocol_stages_keep_integration_reserved_names(self):
        reserved_names = ('candidate-ios', 'candidate-android', 'integration-controls')
        for name in reserved_names:
            for protocol_name in ('async-comparator', 'full-gate'):
                with self.subTest(stage=name, verdictProtocol=protocol_name):
                    config = copy.deepcopy(self.config)
                    if protocol_name == 'async-comparator':
                        stage = {
                            'argv': ['python3', '-m', 'verification.async_verify', '--output', f'{{output}}/{name}'],
                            'cwd': '{candidate}',
                            'timeoutSeconds': 3,
                            'verdictProtocol': protocol_name,
                            'requiredArtifacts': [{'path': f'{name}/async-report.json', 'validator': 'async-report'}],
                        }
                    else:
                        stage = {
                            'argv': ['bash', 'scripts/verify.sh', f'{{output}}/{name}'],
                            'cwd': '{candidate}',
                            'timeoutSeconds': 3,
                            'verdictProtocol': protocol_name,
                            'requiredArtifacts': [{'path': f'{name}/report.md', 'validator': 'full-report'}],
                        }
                    config['stages'] = {name: stage}
                    protocol.validate_config(config)

    def test_protected_edit_add_delete_and_out_of_scope_new_source(self):
        for mode in ('edit', 'add', 'delete', 'outside', 'baseline'):
            with self.subTest(mode=mode):
                self.freeze()
                p = self.root/'contract/specification.json'
                if mode == 'edit': p.write_text('changed')
                if mode == 'add': p = self.root/'verification/new.py'; p.write_text('new')
                if mode == 'delete': p.unlink()
                if mode == 'outside': p = self.root/'new-source.swift'; p.write_text('new')
                if mode == 'baseline': p = self.root/'reports/baseline/runner'; p.write_text('changed')
                self.assertEqual(protocol.check(self.manifest, self.digest, self.root)['classification'], 'INFRA_FAILURE')
                if mode in ('add', 'outside'): p.unlink()
                elif mode == 'baseline': p.write_text('preserved')
                else: p.write_text('{}')
                self.manifest.unlink()

    def test_semantic_requires_report_and_native_mismatch(self):
        self.writer('semantic'); self.freeze()
        self.assertEqual(self.run_stage()['classification'], 'SEMANTIC_FAIL')

    def run_integration(self, attempt='integration-a1'):
        return protocol.run(self.manifest, self.digest, self.root, 'integration-red', attempt)

    def test_integration_exit_one_requires_semantic_report(self):
        for mode, expected in (('semantic', 'SEMANTIC_FAIL'), ('exit-one-pass', 'INFRA_FAILURE'),
                               ('bad-semantic', 'INFRA_FAILURE'), ('wrong-invariants', 'INFRA_FAILURE')):
            with self.subTest(mode=mode):
                self.integration_writer(mode)
                self.freeze()
                self.assertEqual(self.run_integration(mode)['classification'], expected)
                self.manifest.unlink()

    def test_integration_stage_disables_python_bytecode_writes(self):
        self.integration_writer('pass')
        self.freeze()

        result = self.run_integration('bytecode-disabled')

        self.assertEqual(result['classification'], 'PASS')
        self.assertFalse((self.root / 'integration' / '__pycache__').exists())

    def test_invalid_history_classification_is_preserved(self):
        self.integration_writer('invalid-history')
        self.freeze()

        result = self.run_integration('invalid-history')

        self.assertEqual(result['classification'], 'INVALID_HISTORY')

    def test_missing_platform_not_pass(self):
        self.integration_writer('missing-platform')
        self.freeze()

        result = self.run_integration('missing-platform')

        self.assertNotEqual(result['classification'], 'PASS')
        self.assertEqual(result['classification'], 'INCONCLUSIVE')

    def test_missing_scenario_or_artifact_membership_is_inconclusive(self):
        for mode in ('missing-scenario','missing-artifact'):
            with self.subTest(mode=mode):
                self.integration_writer(mode)
                self.freeze()
                self.assertEqual(self.run_integration(mode)['classification'], 'INCONCLUSIVE')
                self.manifest.unlink()

    def test_integration_red_requires_scenario_specific_witnesses(self):
        self.integration_writer('wrong-invariants')
        self.freeze()

        result = self.run_integration('wrong-invariants')

        self.assertEqual(result['classification'], 'INFRA_FAILURE')

    def test_stale_artifact_rejected(self):
        self.integration_writer('stale')
        self.freeze()

        result = self.run_integration('stale')

        self.assertEqual(result['classification'], 'INFRA_FAILURE')
        self.assertIn('stale', result['detail'])

    def test_changed_evaluator_invalidates_binding(self):
        self.freeze()
        (self.root / 'integration/reproduce.py').write_text('changed evaluator source\n')

        result = self.run_integration('changed-evaluator')

        self.assertEqual(result['classification'], 'INFRA_FAILURE')
        self.assertIn('protected/out-of-scope', result['detail'])

    def test_changed_scenario_inventory_rejected(self):
        self.freeze()
        (self.root / 'integration/scenarios.json').write_text('{"version":1,"scenarios":[{"id":"changed"}]}\n')

        result = self.run_integration('changed-inventory')

        self.assertEqual(result['classification'], 'INFRA_FAILURE')
        self.assertIn('protected/out-of-scope', result['detail'])

    def test_full_gate_legacy_verdict_unchanged(self):
        self.freeze()

        result = self.run_stage('legacy-full-pass', 'full')

        self.assertEqual(result['classification'], 'PASS')
        self.assertEqual((Path(result['outputDirectory']) / 'full/report.md').read_text().splitlines()[0], 'Overall: PASS')

    def test_timeout_signal_nonzero_missing_stale_malformed_and_native_infra_never_pass(self):
        for i, mode in enumerate(('timeout','signal','nonzero','missing','stale','malformed','infra','notrun')):
            with self.subTest(mode=mode):
                self.writer(mode)
                self.config['stages']['async']['timeoutSeconds'] = .1 if mode == 'timeout' else 3
                self.freeze()
                result = self.run_stage('failure-'+str(i))
                self.assertEqual(result['classification'], 'NOT_RUN' if mode=='notrun' else 'INFRA_FAILURE')
                self.manifest.unlink()

    def test_full_gate_exit_one_is_infrastructure_and_incomplete_cannot_pass(self):
        for i, (line, code) in enumerate((('FAIL',1),('INCOMPLETE (mutation matrix NOT_RUN)',0))):
            (self.root/'scripts/verify.sh').write_text('mkdir -p "$1"; echo "Overall: '+line+'" > "$1/report.md"; exit '+str(code)+'\n')
            self.freeze()
            self.assertIn(self.run_stage('full-'+str(i),'full')['classification'], ('NOT_RUN','INFRA_FAILURE'))
            self.manifest.unlink()

    def test_collision_never_replaces_unowned_output(self):
        self.freeze()
        p = self.root/'reports/attempts/a1'; p.mkdir(parents=True); (p/'mine').write_text('mine')
        with self.assertRaises(protocol.ProtocolError): self.run_stage()
        self.assertEqual((p/'mine').read_text(), 'mine')

    def test_attempt_and_wall_budget_stop_without_pass(self):
        self.config['maxAttempts']=1; self.freeze(); self.run_stage()
        self.assertEqual(self.run_stage('a2')['classification'], 'NOT_RUN')
        self.manifest.unlink(); self.config['maxAttempts']=3; self.config['maxTotalSeconds']=.001
        self.freeze()
        self.assertEqual(self.run_stage('time')['classification'], 'INFRA_FAILURE')
        self.assertEqual(self.run_stage('after-time')['classification'], 'NOT_RUN')

    def test_legacy_protocol_stages_do_not_require_standalone_per_stage_budget(self):
        self.assertNotIn('maxAttemptsPerStage', self.config['provenance'])
        self.freeze()

        first = self.run_stage('legacy-first')
        second = self.run_stage('legacy-second')

        self.assertEqual(first['classification'], 'PASS')
        self.assertEqual(second['classification'], 'PASS')

    def test_manifest_result_and_artifact_digest_mismatch(self):
        self.freeze()
        with self.assertRaises(protocol.ProtocolError): protocol.check(self.manifest, '0'*64, self.root)
        result = self.run_stage(); path=Path(result['outputDirectory'])/'result.json'
        record=json.loads(path.read_text()); record['candidateDigest']='0'*64; path.write_text(json.dumps(record))
        self.assertEqual(protocol.check(self.manifest,self.digest,self.root,path)['classification'],'INFRA_FAILURE')
        record['candidateDigest']=result['candidateDigest']; path.write_text(json.dumps(record))
        (Path(result['outputDirectory'])/'async/async-report.json').write_text('{}')
        self.assertEqual(protocol.check(self.manifest,self.digest,self.root,path)['classification'],'INFRA_FAILURE')

    def test_reject_arbitrary_argv_protocol_and_unsafe_paths_at_freeze(self):
        for mode in ('argv','protocol','cwd','output','artifact','substitution','ignored-protected','allowed-protected','ambiguous-verdict'):
            with self.subTest(mode=mode):
                config=json.loads(json.dumps(self.config)); stage=config['stages']['async']
                if mode=='argv': stage['argv']=['true']
                if mode=='protocol': stage['verdictProtocol']='exit-zero'
                if mode=='cwd': stage['cwd']='/'
                if mode=='output': config['outputRoot']='../outside'
                if mode=='artifact': stage['requiredArtifacts'][0]['path']='../old-report.json'
                if mode=='substitution': stage['argv'].append('{command}')
                if mode=='ignored-protected': config['ignoredPaths'].append('verification/')
                if mode=='allowed-protected': config['allowedPaths'].append('contract/')
                if mode=='ambiguous-verdict': stage['requiredArtifacts'].insert(0,{'path':'wrong/report.md','validator':'full-report'})
                with self.assertRaises(protocol.ProtocolError): protocol.freeze(self.root,config,self.manifest)

    def test_cli_refuses_run_argv_and_verdict_overrides(self):
        self.freeze()
        cli=Path(protocol.__file__)
        for option in ('--argv','--verdict-protocol'):
            proc=subprocess.run(['python3',str(cli),'run','--manifest',str(self.manifest),'--manifest-digest',self.digest,
                                 '--candidate',str(self.root),'--stage','async','--attempt','cli',option,'true'],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0)
            self.assertFalse((self.root/'reports/attempts/cli').exists())

    def test_candidate_symlink_cannot_escape_snapshot(self):
        self.freeze()
        p=self.root/'ios/Sources/AsyncNativeContract/link'; p.symlink_to('/etc/passwd')
        self.assertEqual(protocol.check(self.manifest,self.digest,self.root)['classification'],'INFRA_FAILURE')


    def test_ledger_symlinks_and_nonregular_entries_refuse_launch(self):
        with tempfile.TemporaryDirectory() as external:
            outside=Path(external).resolve()
            for name in ('.manifest-digest','.budget.lock'):
                for kind in ('dangling','existing','directory'):
                    with self.subTest(name=name,kind=kind):
                        self.freeze()
                        ledger=self.root/self.config['outputRoot']; ledger.mkdir(parents=True)
                        entry=ledger/name; target=outside/(name+'-'+kind)
                        if kind=='directory': entry.mkdir()
                        else:
                            if kind=='existing': target.write_text(self.digest+'\n' if name=='.manifest-digest' else 'sentinel')
                            entry.symlink_to(target)
                        before=target.read_bytes() if target.exists() else None
                        with self.assertRaises(protocol.ProtocolError): self.run_stage()
                        self.assertFalse((ledger/'a1').exists(), 'evaluator must not launch')
                        self.assertEqual(target.read_bytes() if target.exists() else None,before)
                        self.manifest.unlink()

    def test_prior_attempt_symlink_and_nonregular_ledger_entries_refuse_launch(self):
        with tempfile.TemporaryDirectory() as external:
            outside=Path(external).resolve()
            for kind in ('attempt-symlink','result-symlink','result-directory','attempt-file'):
                with self.subTest(kind=kind):
                    self.freeze()
                    ledger=self.root/self.config['outputRoot']; ledger.mkdir(parents=True)
                    prior=ledger/'prior'
                    target=outside/('prior-'+kind); target.mkdir()
                    record={'manifestDigest':self.digest,'durationSeconds':0}
                    (target/'result.json').write_text(json.dumps(record))
                    if kind=='attempt-symlink': prior.symlink_to(target,target_is_directory=True)
                    elif kind=='attempt-file': prior.write_text('unowned')
                    else:
                        prior.mkdir()
                        if kind=='result-symlink': (prior/'result.json').symlink_to(target/'result.json')
                        else: (prior/'result.json').mkdir()
                    sentinel=(target/'result.json').read_bytes()
                    with self.assertRaises(protocol.ProtocolError): self.run_stage()
                    self.assertFalse((ledger/'a1').exists())
                    self.assertEqual((target/'result.json').read_bytes(),sentinel)
                    self.manifest.unlink()

    def test_missing_replaced_or_symlinked_raw_evidence_cannot_pass_result_check(self):
        self.freeze()
        result=self.run_stage(); output=Path(result['outputDirectory']); result_path=output/'result.json'
        for name in ('command.json','stdout.log','stderr.log'):
            original=(output/name).read_bytes()
            for kind in ('missing','replaced','symlink','directory'):
                with self.subTest(name=name,kind=kind):
                    p=output/name; p.unlink()
                    if kind=='replaced': p.write_text('{}' if name=='command.json' else 'replacement')
                    if kind=='symlink': p.symlink_to(output/'async/async-report.json')
                    if kind=='directory': p.mkdir()
                    checked=protocol.check(self.manifest,self.digest,self.root,result_path)
                    if p.is_symlink() or p.is_file(): p.unlink()
                    elif p.is_dir(): p.rmdir()
                    p.write_bytes(original)
                    self.assertEqual(checked['classification'],'INFRA_FAILURE')

    def test_command_record_must_agree_with_frozen_argv_even_if_hash_is_updated(self):
        self.freeze()
        result=self.run_stage(); output=Path(result['outputDirectory']); path=output/'result.json'
        record=json.loads(path.read_text())
        if 'evidence' not in record: self.fail('captured evidence digests must be recorded')
        (output/'command.json').write_text(json.dumps({'argv':['true'],'cwd':str(self.root)}))
        import hashlib
        record['evidence']['command.json']=hashlib.sha256((output/'command.json').read_bytes()).hexdigest()
        path.write_text(json.dumps(record))
        self.assertEqual(protocol.check(self.manifest,self.digest,self.root,path)['classification'],'INFRA_FAILURE')

    def test_empty_raw_logs_are_bound_and_valid(self):
        self.freeze()
        result=self.run_stage(stage='full'); output=Path(result['outputDirectory'])
        self.assertEqual(result['classification'],'PASS')
        self.assertEqual((output/'stdout.log').read_bytes(),b'')
        self.assertEqual((output/'stderr.log').read_bytes(),b'')
        self.assertIn('evidence',result)
        self.assertEqual(protocol.check(self.manifest,self.digest,self.root,output/'result.json')['classification'],'PASS')


    def check_cli(self, result_path=None):
        argv=['python3',str(Path(protocol.__file__)),'check','--manifest',str(self.manifest),
              '--manifest-digest',self.digest,'--candidate',str(self.root)]
        if result_path is not None: argv.extend(['--result',str(result_path)])
        proc=subprocess.run(argv,capture_output=True,text=True)
        return proc.returncode,json.loads(proc.stdout)

    def test_cli_result_check_preserves_bound_evaluation_verdict(self):
        for mode,expected,exit_code in (('pass','PASS',0),('semantic','SEMANTIC_FAIL',1),
                                       ('infra','INFRA_FAILURE',2),('notrun','NOT_RUN',2)):
            with self.subTest(mode=mode):
                self.writer(mode); self.freeze()
                result=self.run_stage(); output=Path(result['outputDirectory'])
                code,checked=self.check_cli(output/'result.json')
                self.manifest.unlink()
                self.assertEqual(result['classification'],expected)
                self.assertEqual(code,exit_code)
                self.assertEqual(checked['classification'],expected)
                self.assertEqual(checked['resultClassification'],expected)
                self.assertEqual(checked['bindingClassification'],'PASS')

    def test_cli_result_check_rejects_invalid_evidence_binding(self):
        self.freeze(); result=self.run_stage(); output=Path(result['outputDirectory'])
        (output/'stdout.log').write_text('accidental replacement')
        code,checked=self.check_cli(output/'result.json')
        self.assertEqual(code,2)
        self.assertEqual(checked['classification'],'INFRA_FAILURE')
        self.assertEqual(checked['bindingClassification'],'INFRA_FAILURE')
        self.assertNotIn('resultClassification',checked)

    def test_cli_check_without_result_reports_source_integrity_only(self):
        self.writer('semantic'); self.freeze(); self.run_stage()
        code,checked=self.check_cli()
        self.assertEqual(code,0)
        self.assertEqual(checked['classification'],'PASS')
        self.assertNotIn('bindingClassification',checked)
        self.assertNotIn('resultClassification',checked)


if __name__ == '__main__': unittest.main()
