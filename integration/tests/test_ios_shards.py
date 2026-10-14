"""Frozen iOS shard coverage and source-bound aggregation regressions."""

import copy
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import aggregate, controller, protocol_config, reproduce
from verification import change_protocol as protocol
from integration.tests._history_fixtures import make_app02_trace
from integration.check import check_trace


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "d2ce1847cb2644252f7c4d069ef9e36142bb327b"
SHARDS = tuple(f"candidate-ios-shard-{i}" for i in range(1, 5))
PARTITIONS = [
    ["APP-06", "APP-13", "APP-14"],
    ["APP-03", "APP-07", "APP-09", "APP-12-SAVED"],
    ["APP-04", "APP-08", "APP-10", "APP-12-LOGGED-OUT"],
    ["APP-01", "APP-02", "APP-05", "APP-10-RECOVER-OLD", "APP-11"],
]


def config():
    return protocol_config.build_config(ROOT, "reports/standalone/attempts/ios-shard-tests", BASELINE)


def declared_shards():
    """Independently spell the shard contract using the original full stage."""
    value = config()
    full = value["stages"]["candidate-ios"]
    for name, ids in zip(SHARDS, PARTITIONS):
        shard = copy.deepcopy(full)
        shard["requiredScenarioIds"] = ids[:]
        shard["expectedTraceBindings"] = [row for row in full["expectedTraceBindings"] if row["scenarioId"] in ids]
        shard["argv"] = [part.replace("candidate-ios", name) for part in full["argv"]]
        for artifact in shard["requiredArtifacts"]:
            artifact["path"] = artifact["path"].replace("candidate-ios/", name + "/", 1)
        value["stages"][name] = shard
    return value


class FrozenShardTests(unittest.TestCase):
    def test_generated_shards_cover_every_scenario_and_variant_with_bounded_stages(self):
        value = config()
        self.assertTrue(set(SHARDS) <= set(value["stages"]))
        bindings = []
        for name, ids in zip(SHARDS, PARTITIONS):
            stage = value["stages"][name]
            self.assertEqual(stage["requiredScenarioIds"], ids)
            self.assertEqual(stage["timeoutSeconds"], 1800)
            self.assertEqual(stage["expectedPlatforms"], ["ios"])
            bindings.extend(stage["expectedTraceBindings"])
        self.assertEqual(len(bindings), 23)
        self.assertEqual(
            sorted((r["scenarioId"], r["variantId"] or "") for r in bindings),
            sorted((r["scenarioId"], r["variantId"] or "") for r in value["stages"]["candidate-ios"]["expectedTraceBindings"]),
        )

    def test_complete_independently_declared_partition_is_accepted(self):
        protocol.validate_config(declared_shards())

    def test_partial_shard_declaration_is_rejected(self):
        value = declared_shards()
        del value["stages"][SHARDS[-1]]
        with self.assertRaisesRegex(protocol.ProtocolError, "shard"):
            protocol.validate_config(value)

    def test_overlapping_scenario_is_rejected_even_with_matching_trace_bindings(self):
        value = declared_shards()
        other = value["stages"][SHARDS[1]]
        other["requiredScenarioIds"].append("APP-14")
        other["expectedTraceBindings"].append({"platform": "ios", "scenarioId": "APP-14", "variantId": None})
        with self.assertRaisesRegex(protocol.ProtocolError, "shard"):
            protocol.validate_config(value)

    def test_missing_scenario_is_rejected_even_with_matching_trace_bindings(self):
        value = declared_shards()
        shard = value["stages"][SHARDS[0]]
        shard["requiredScenarioIds"].remove("APP-14")
        shard["expectedTraceBindings"] = [r for r in shard["expectedTraceBindings"] if r["scenarioId"] != "APP-14"]
        with self.assertRaisesRegex(protocol.ProtocolError, "shard"):
            protocol.validate_config(value)

    def test_missing_variant_is_rejected(self):
        value = declared_shards()
        value["stages"][SHARDS[0]]["expectedTraceBindings"].pop()
        with self.assertRaisesRegex(protocol.ProtocolError, "trace-binding"):
            protocol.validate_config(value)

    def test_unknown_shard_name_is_rejected(self):
        value = declared_shards()
        stage = copy.deepcopy(value["stages"][SHARDS[-1]])
        value["stages"]["candidate-ios-shard-5"] = stage
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate_config(value)

    def test_legacy_manifest_without_shards_is_still_accepted(self):
        value = config()
        for name in SHARDS:
            value["stages"].pop(name, None)
        protocol.validate_config(value)


class ShardExecutionTests(unittest.TestCase):
    def run_without_device(self, output, ids, *, subset=True, name=SHARDS[0], inventory=None):
        return controller.run_platform(
            'ios', candidate=ROOT, output=output, device=None,
            scenarios=inventory or ROOT / 'integration/scenarios.json',
            stage_id=name, required_scenario_ids=ids, scenario_subset=subset,
        )

    def test_subset_inventory_preserves_complete_variants_and_original_order(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'ios'
            result = self.run_without_device(output, PARTITIONS[0])
            self.assertEqual(result['classification'], 'NOT_RUN')
            copied = json.loads((output / 'scenarios.json').read_text())['scenarios']
            self.assertEqual([r['id'] for r in copied], PARTITIONS[0])
            self.assertEqual([v['id'] for v in copied[1]['variants']], [
                'http500-current', 'malformed-current', 'disconnect-current',
                'wrong-correlation-current', 'wrong-correlation-after-login-b',
            ])
            self.assertEqual(result['scenarioDigest'], protocol.digest_bytes((output / 'scenarios.json').read_bytes()))

    def test_unknown_empty_duplicate_or_unordered_subset_is_rejected(self):
        for ids in (['APP-NOT-FOUND'], [], ['APP-06', 'APP-06'], list(reversed(PARTITIONS[0]))):
            with self.subTest(ids=ids), tempfile.TemporaryDirectory() as directory:
                result = self.run_without_device(Path(directory) / 'ios', ids)
                self.assertEqual(result['classification'], 'INVALID_HISTORY')

    def test_subset_is_only_available_to_ios_app_shard_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_without_device(Path(directory) / 'ios', ['CTRL-N1-LOGOUT'],
                                            name='integration-controls', inventory=ROOT / 'integration/control-scenarios.json')
            self.assertEqual(result['classification'], 'INVALID_HISTORY')

    def test_full_inventory_mode_keeps_exact_membership_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_without_device(Path(directory) / 'ios', PARTITIONS[0], subset=False, name='candidate-ios')
            self.assertEqual(result['classification'], 'INVALID_HISTORY')

    def test_shard_stage_dispatch_creates_a_subset_report_without_claiming_native_pass(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {}, clear=True):
            output = Path(directory) / SHARDS[0]
            result = reproduce.stage(candidate=ROOT, stage_id=SHARDS[0], output=output)
            self.assertEqual(result['classification'], 'NOT_RUN')
            report = protocol.integration_report(output / 'report.json', config()['stages'][SHARDS[0]])
            self.assertEqual(report['requiredScenarioIds'], PARTITIONS[0])
            inventory = json.loads((output / 'ios/scenarios.json').read_text())['scenarios']
            self.assertEqual([r['id'] for r in inventory], PARTITIONS[0])

    def test_real_frozen_shard_attempt_is_bound_and_keeps_missing_device_not_run(self):
        with tempfile.TemporaryDirectory(prefix='shard-ledger-', dir=ROOT / 'reports/standalone') as directory:
            frozen = reproduce.freeze(ROOT, Path(directory) / ('freeze-' + Path(directory).name))
            manifest = Path(frozen['manifest'])
            output_root = ROOT / json.loads(manifest.read_text())['outputRoot']
            with patch.dict('os.environ', {'IOS_SIMULATOR_UDID': ''}):
                # Empty env value is invalid; omit the optional owned device entirely.
                import os
                del os.environ['IOS_SIMULATOR_UDID']
                result = reproduce.run_stages(candidate=ROOT, output=output_root, stages=[SHARDS[0]],
                                              manifest=manifest, manifest_digest=frozen['manifestDigest'])
            self.assertEqual(result['classification'], 'NOT_RUN')
            self.assertEqual(result['stageResults'][0]['bindingClassification'], 'PASS')
            self.assertEqual(json.loads((output_root / 'ledger-owner.json').read_text())['selectedStages'], [SHARDS[0]])


class ShardAggregationTests(unittest.TestCase):
    def checked_shards(self, classes=None):
        classes = classes or ['PASS'] * 4
        value = config()
        return {
            name: ({'classification': status}, Path('/unused') / name, value['stages'].get(name))
            for name, status in zip(SHARDS, classes)
        }

    def test_all_checked_shards_derive_pass_with_distinct_builds_and_devices(self):
        # Native replay is independently exercised below; this test owns the conjunction.
        def verified(root, stage, platform, *, candidate):
            index = SHARDS.index(root.name)
            selected = {'buildHash': 'sha256:' + str(index + 1) * 64,
                        'deviceHash': 'sha256:' + str(index + 5) * 64}
            return {}, selected, [{'scenarioId': sid, 'variantId': None, 'classification': 'PASS'}
                                  for sid in stage['requiredScenarioIds']]
        with patch.object(aggregate, '_verify_native_stage', side_effect=verified):
            result = aggregate.derive_ios_candidate(self.checked_shards(), config(), ROOT)
        self.assertEqual(result['classification'], 'PASS')
        self.assertEqual([r['stageId'] for r in result['shardResults']], list(SHARDS))
        self.assertEqual(len({r['buildHash'] for r in result['shardResults']}), 4)

    def test_every_non_pass_shard_is_propagated(self):
        for status in ('INFRA_FAILURE', 'INVALID_HISTORY', 'NOT_RUN', 'INCONCLUSIVE', 'SEMANTIC_FAIL'):
            with self.subTest(status=status):
                result = aggregate.derive_ios_candidate(self.checked_shards([status] * 4), config(), ROOT)
                self.assertEqual(result['classification'], status)

    def test_missing_shard_cannot_derive_pass(self):
        checked = self.checked_shards()
        del checked[SHARDS[-1]]
        with self.assertRaisesRegex(aggregate.AggregateError, 'shard'):
            aggregate.derive_ios_candidate(checked, config(), ROOT)

    def test_worst_shard_failure_wins(self):
        result = aggregate.derive_ios_candidate(
            self.checked_shards(['SEMANTIC_FAIL', 'INCONCLUSIVE', 'INVALID_HISTORY', 'INFRA_FAILURE']), config(), ROOT)
        self.assertEqual(result['classification'], 'INFRA_FAILURE')

    def test_partial_or_duplicate_shard_roots_are_rejected_before_loading_ledgers(self):
        for roots in ([Path('/a')], [Path('/a')] * 4):
            with self.subTest(roots=roots), self.assertRaisesRegex(aggregate.AggregateError, 'shard'):
                aggregate.load_ios_ledgers(Path('/aux'), roots, ROOT, config(), 'a' * 64, 'b' * 64)

    def test_old_full_ledger_is_rejected_in_shard_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol.write_json(root / 'suite-report.json', {
                'version': 1, 'classification': 'PASS', 'manifest': '/manifest', 'manifestDigest': 'a' * 64,
                'selectedStages': ['integration-red', 'candidate-ios', 'integration-controls', 'legacy-full'],
                'stageResults': [],
            })
            with self.assertRaisesRegex(aggregate.AggregateError, 'incomplete'):
                aggregate.load_ios_ledgers(root, [root / str(i) for i in range(4)], ROOT, config(), 'a' * 64, 'b' * 64)

    def test_all_physical_ledgers_share_the_attempt_and_elapsed_budgets(self):
        value = config()
        records = [{'stageId': name} for name in SHARDS]
        counts = aggregate.verify_attempt_budgets(records, [100.0] * 4, value)
        self.assertEqual(counts, {name: 1 for name in SHARDS})
        for rows, durations in (
            (records * 3, [100.0] * 12),
            ([{'stageId': 'integration-controls'}] * 3, [1.0] * 3),
            (records, [21600.0] * 4),
        ):
            with self.subTest(rows=rows, durations=durations), self.assertRaisesRegex(aggregate.AggregateError, 'budget'):
                aggregate.verify_attempt_budgets(rows, durations, value)

    def make_native_fixture(self, root, *, unsafe_success=False):
        root.mkdir()
        trace, server, ui = make_app02_trace(unsafe_success=unsafe_success)
        scenario = next(r for r in json.loads((ROOT / 'integration/scenarios.json').read_text())['scenarios'] if r['id'] == 'APP-02')
        verdict = check_trace(json.loads((ROOT / 'integration/contract.json').read_text()), scenario, trace, server, ui)
        self.assertEqual(verdict['classification'], 'SEMANTIC_FAIL' if unsafe_success else 'PASS')
        identity = {'scenarioId': 'APP-02', 'variantId': None}
        case = {**identity, **{field: verdict[field] for field in ('classification', 'violations', 'missingObservations')}}
        protocol.write_json(root / 'scenario-results.json', {'platform': 'ios', 'cases': [case]})
        (root / 'native-trace.jsonl').write_text(json.dumps({**identity, 'trace': trace}) + '\n')
        protocol.write_json(root / 'server-events.json', {'cases': [{**identity, 'runId': trace['runId'], 'events': server}]})
        protocol.write_json(root / 'ui-observations.json', {'cases': [{**identity, 'observations': ui}]})
        protocol.write_json(root / 'platform-report.json', {'buildHash': 'a' * 64})
        (root / 'screenshots').mkdir()
        protocol.write_json(root / 'screenshots/manifest.json', {'screenshots': []})

    def test_independent_history_replay_accepts_only_the_required_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'ios'
            self.make_native_fixture(root)
            stage = copy.deepcopy(config()['stages']['candidate-ios'])
            stage['requiredScenarioIds'] = ['APP-02']
            result = aggregate._recheck_platform_histories(root, 'ios', stage, ROOT)
            self.assertEqual([r['classification'] for r in result], ['PASS'])
            stage['requiredScenarioIds'].append('APP-03')
            with self.assertRaisesRegex(aggregate.AggregateError, 'membership'):
                aggregate._recheck_platform_histories(root, 'ios', stage, ROOT)

    def test_history_with_a_different_build_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'ios'
            self.make_native_fixture(root)
            protocol.write_json(root / 'platform-report.json', {'buildHash': 'b' * 64})
            stage = copy.deepcopy(config()['stages']['candidate-ios'])
            stage['requiredScenarioIds'] = ['APP-02']
            with self.assertRaisesRegex(aggregate.AggregateError, 'identity or build binding'):
                aggregate._recheck_platform_histories(root, 'ios', stage, ROOT)

    def test_semantic_violation_replay_uses_exact_json_wire_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'ios'
            self.make_native_fixture(root, unsafe_success=True)
            stage = copy.deepcopy(config()['stages']['candidate-ios'])
            stage['requiredScenarioIds'] = ['APP-02']
            result = aggregate._recheck_platform_histories(root, 'ios', stage, ROOT)
            self.assertEqual(result[0]['classification'], 'SEMANTIC_FAIL')
            path = root / 'scenario-results.json'
            recorded = json.loads(path.read_text())
            violation = next(r for r in recorded['cases'][0]['violations'] if isinstance(r['actual'], list))
            violation['actual'][1] = 'B'
            protocol.write_json(path, recorded)
            with self.assertRaisesRegex(aggregate.AggregateError, 'cannot be replayed'):
                aggregate._recheck_platform_histories(root, 'ios', stage, ROOT)


class ShardWorkflowTests(unittest.TestCase):
    def workflow(self):
        document = subprocess.check_output([
            'ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))',
            str(ROOT / '.github/workflows/integration.yml'),
        ], text=True)
        return json.loads(document)['jobs']

    def test_matrix_executes_each_shard_once_and_keeps_auxiliary_stages_separate(self):
        job = self.workflow()['ios-native']
        self.assertIn('strategy', job)
        self.assertFalse(job['strategy']['fail-fast'])
        rows = job['strategy']['matrix']['include']
        self.assertEqual({r['ledger']: r['stages'].split() for r in rows}, {
            'auxiliary': ['integration-red', 'integration-controls', 'legacy-full'],
            'shard-1': ['candidate-ios-shard-1'], 'shard-2': ['candidate-ios-shard-2'],
            'shard-3': ['candidate-ios-shard-3'], 'shard-4': ['candidate-ios-shard-4'],
        })
        upload = next(step for step in job['steps'] if step['name'] == 'Upload iOS portable ledger')
        self.assertIn('${{ matrix.ledger }}', upload['with']['name'])

    def test_acceptance_imports_distinct_matrix_artifacts_and_passes_all_shard_roots(self):
        steps = self.workflow()['native-acceptance']['steps']
        imports = [s for s in steps if s.get('name', '').startswith('Download iOS')]
        self.assertEqual(len(imports), 5)
        self.assertEqual(len({s['with']['path'] for s in imports}), 5)
        self.assertEqual(len({s['with']['name'] for s in imports}), 5)
        run = next(s['run'] for s in steps if s.get('name') == 'Recheck portable ledgers and derive final verdict')
        self.assertEqual(run.count('--ios-shard-ledger '), 4)
        for i in range(1, 5):
            self.assertIn(f'imported-${{RUN_LABEL}}-ios-shard-{i}', run)
        self.assertIn('--ios-ledger "reports/standalone/imported-${RUN_LABEL}-ios-auxiliary"', run)


if __name__ == "__main__":
    unittest.main()
