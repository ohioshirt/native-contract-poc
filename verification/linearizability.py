"""Bounded linearizability search; inventory, provenance and observations are external."""
import argparse
import json
import time
from pathlib import Path
from verification.async_contract import MAX_ID, RESPONSES, SIMPLE, step

TRIPLE = ('state', 'pendingRequestId', 'nextRequestId')


def require(condition, message):
    if not condition: raise ValueError(message)


def keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), f'{label}: exact keys {sorted(expected)} required')


def integer(value, low=0, high=MAX_ID):
    return type(value) is int and low <= value <= high


def token_shape(token, owners):
    keys(token, ('owner', 'requestId'), 'token')
    require(token['owner'] in owners and integer(token['requestId'], 1), 'invalid token owner/requestId')


def validate_workload(workload):
    keys(workload, ('version', 'scenarios'), 'workload')
    require(type(workload['version']) is int and workload['version'] == 1, 'workload version must be 1')
    require(isinstance(workload['scenarios'], list) and workload['scenarios'], 'scenarios must be nonempty array')
    names = set()
    for s in workload['scenarios']:
        keys(s, ('id','seed','owners','concurrentPhases','operations'), 'scenario')
        require(isinstance(s['id'], str) and s['id'] and s['id'] not in names, 'scenario ID empty/duplicate')
        names.add(s['id']); require(integer(s['seed']), 'seed must be nonnegative integer')
        require(isinstance(s['owners'], list) and s['owners'], 'owners must be nonempty array')
        owners = set()
        for owner in s['owners']:
            keys(owner, ('id','nextRequestId'), 'owner')
            require(isinstance(owner['id'], str) and owner['id'] and owner['id'] not in owners, 'owner ID empty/duplicate')
            owners.add(owner['id']); require(integer(owner['nextRequestId'],1), 'invalid initial nextRequestId')
        require(isinstance(s['operations'], list) and s['operations'], 'operations must be nonempty array')
        ids, ops = set(), {}
        for o in s['operations']:
            require(isinstance(o, dict), 'operation must be object')
            keys(o, ('id','owner','kind','phase','after') + (('event',) if o.get('kind') == 'handle' else ()), 'operation')
            require(isinstance(o['id'],str) and o['id'] and o['id'] not in ids, 'operation ID empty/duplicate')
            ids.add(o['id']); ops[o['id']] = o
            require(o['owner'] in owners and o['kind'] in ('handle','snapshot'), 'operation owner/kind invalid')
            require(integer(o['phase']), 'invalid phase')
            require(isinstance(o['after'],list) and all(isinstance(v,str) for v in o['after']) and len(set(o['after'])) == len(o['after']), 'after must be distinct IDs')
            if o['kind'] == 'handle':
                event = o['event']; require(isinstance(event,dict), 'event must be object')
                name = event.get('event')
                keys(event, ('event','tokenRef') if name in RESPONSES else ('event',), 'event')
                require(name in SIMPLE + RESPONSES, 'unknown event')
                if name in RESPONSES:
                    ref = event['tokenRef']; keys(ref, ('operationId','effectIndex'), 'tokenRef')
                    require(isinstance(ref['operationId'],str) and integer(ref['effectIndex']), 'invalid tokenRef')
        edges = {}
        for o in s['operations']:
            deps = set(o['after']) | {p['id'] for p in s['operations'] if p['phase'] < o['phase']}
            if o.get('event',{}).get('event') in RESPONSES: deps.add(o['event']['tokenRef']['operationId'])
            require(deps <= ids and o['id'] not in deps, 'missing/self dependency or token producer')
            if o.get('event',{}).get('event') in RESPONSES:
                producer = ops[o['event']['tokenRef']['operationId']]
                require(producer.get('event',{}).get('event') == 'TokenExpired', 'token producer must be TokenExpired')
            edges[o['id']] = deps
        done = set()
        while True:
            enabled = {i for i in ids-done if edges[i] <= done}
            if not enabled: break
            done |= enabled
        require(done == ids, 'cyclic workload dependencies')
        require(isinstance(s['concurrentPhases'],list) and all(integer(p) for p in s['concurrentPhases']) and len(set(s['concurrentPhases'])) == len(s['concurrentPhases']), 'invalid concurrent phases')
        for phase in s['concurrentPhases']:
            require(sum(o['phase'] == phase for o in s['operations']) >= 2, 'concurrent phase needs multiple callers')
    return workload


def validate_history(scenario, history, spec):
    keys(history, ('scenario','seed','trial','owners','operations'), 'history')
    require(history['scenario'] == scenario['id'] and history['seed'] == scenario['seed'] and type(history['seed']) is int, 'scenario/seed mismatch')
    require(integer(history['trial'],0,19), 'trial outside 0..19')
    require(history['owners'] == scenario['owners'], 'owner declarations mismatch')
    # Validate declaration types independently: Python equality must not accept True == 1.
    for owner in history['owners']:
        require(integer(owner['nextRequestId'],1), 'history initial allocator is not integer')
    require(isinstance(history['operations'],list), 'operations must be array')
    expected = {o['id']:o for o in scenario['operations']}; actual = {}
    stamps = set(); owners = {o['id'] for o in scenario['owners']}
    for row in history['operations']:
        require(isinstance(row,dict) and isinstance(row.get('id'),str), 'history operation missing ID')
        require(row['id'] in expected and row['id'] not in actual, 'unexpected/duplicate operation')
        template = expected[row['id']]
        keys(row, set(template)|{'invoke','return','result'}, 'history operation')
        metadata = {k:row[k] for k in template}
        if template['kind'] == 'handle' and template['event']['event'] in RESPONSES:
            keys(row['event'], ('event','tokenRef','token'), 'rendered response event')
            token_shape(row['event']['token'], owners)
            metadata['event'] = {k:v for k,v in row['event'].items() if k != 'token'}
        require(metadata == template and integer(row['phase']), 'operation input/inventory metadata mismatch')
        require(isinstance(row['after'],list), 'invalid after metadata')
        for stamp in (row['invoke'],row['return']):
            require(integer(stamp,1) and stamp not in stamps, 'timestamp missing/equal/not positive integer')
            stamps.add(stamp)
        require(row['invoke'] < row['return'], 'reversed invocation interval')
        result = row['result']; keys(result, ('snapshot','effects','rejection'), 'result')
        snapshot = result['snapshot']; keys(snapshot, TRIPLE, 'snapshot')
        require(snapshot['state'] in spec['states'], 'invalid snapshot state')
        for field in ('pendingRequestId','nextRequestId'):
            require(snapshot[field] is None or integer(snapshot[field],1), 'invalid snapshot request ID')
        require(isinstance(result['effects'],list), 'effects must be array')
        for effect in result['effects']:
            require(isinstance(effect,dict), 'effect must be object')
            if effect.get('effect') == 'RequestTokenRefresh':
                keys(effect, ('effect','token'), 'request effect'); token_shape(effect['token'], owners)
                require(effect['token']['owner'] == row['owner'], 'effect token owner differs from issuing owner')
            else:
                keys(effect, ('effect',), 'clear effect'); require(effect['effect'] == 'ClearCredentials', 'unknown effect')
        require(result['rejection'] in (None,'ForeignRequest','RequestIdExhausted'), 'unknown rejection')
        if row['kind'] == 'snapshot': require(result['effects'] == [] and result['rejection'] is None, 'snapshot has effects/rejection')
        actual[row['id']] = row
    require(set(actual) == set(expected), 'missing expected operations (including setup/snapshot)')
    rows = [actual[o['id']] for o in scenario['operations']]
    predecessors = [set() for _ in rows]
    for i,row in enumerate(rows):
        deps = set(row['after']) | {p['id'] for p in rows if p['phase'] < row['phase']}
        event = row.get('event',{})
        if event.get('event') in RESPONSES:
            ref = event['tokenRef']; producer = actual[ref['operationId']]
            require(producer['return'] < row['invoke'], 'future/unreturned token producer')
            effects = producer['result']['effects']
            require(integer(ref['effectIndex']) and ref['effectIndex'] < len(effects), 'nonexistent producing effect index')
            emitted = effects[ref['effectIndex']]
            require(emitted.get('effect') == 'RequestTokenRefresh' and event['token'] == emitted['token'], 'token provenance owner/number mismatch')
            deps.add(producer['id'])
        for ident in deps:
            require(actual[ident]['return'] < row['invoke'], 'phase/dependency edge violated')
        predecessors[i] = {j for j,other in enumerate(rows) if other['return'] < row['invoke']}
    coverage = {str(p): any(a['invoke'] < b['return'] and b['invoke'] < a['return'] for i,a in enumerate(rows) for b in rows[i+1:] if a['phase'] == b['phase'] == p) for p in scenario['concurrentPhases']}
    return rows, predecessors, coverage


def expected_result(spec, state, operation):
    owner = operation['owner']; event = operation.get('event')
    if operation['kind'] == 'snapshot': return {'snapshot': state, 'effects': [], 'rejection': None}
    if event['event'] in RESPONSES and event['token']['owner'] != owner:
        return {'snapshot': state, 'effects': [], 'rejection': 'ForeignRequest'}
    normalized = {'event':event['event']}
    if event['event'] in RESPONSES: normalized['requestId'] = event['token']['requestId']
    result = step(spec, state['state'], state['pendingRequestId'], state['nextRequestId'], normalized)
    effects = [{'effect':'RequestTokenRefresh','token':{'owner':owner,'requestId':e['requestId']}} if e['effect'] == 'RequestTokenRefresh' else e for e in result['effects']]
    return {'snapshot':{k:result[k] for k in TRIPLE}, 'effects':effects, 'rejection':result['rejection']}


class SearchLimit(Exception): pass


def search(scenario, rows, predecessors, spec, max_nodes, max_seconds):
    states = {o['id']:{'state':'Unauthenticated','pendingRequestId':None,'nextRequestId':o['nextRequestId']} for o in scenario['owners']}
    started = time.monotonic(); nodes = 0; failed = set()
    owners = sorted(states)
    def visit(done, current):
        nonlocal nodes
        if nodes >= max_nodes or time.monotonic()-started >= max_seconds: raise SearchLimit()
        nodes += 1
        if len(done) == len(rows): return []
        key = (frozenset(done), tuple(tuple(current[o][k] for k in TRIPLE) for o in owners))
        if key in failed: return None
        for i,operation in enumerate(rows):
            if i in done or not predecessors[i] <= done: continue
            result = expected_result(spec, current[operation['owner']], operation)
            if result != operation['result']: continue
            new = dict(current); new[operation['owner']] = result['snapshot']
            suffix = visit(done | {i}, new)
            if suffix is not None: return [operation['id']] + suffix
        failed.add(key); return None
    try:
        witness = visit(set(),states)
        return {'verdict':'PASS' if witness is not None else 'FAIL', 'witness':witness, 'searchNodes':nodes, 'seconds':time.monotonic()-started}
    except SearchLimit:
        return {'verdict':'INCONCLUSIVE','reason':'search budget exceeded','searchNodes':nodes,'seconds':time.monotonic()-started}


def check_document(workload, document, spec, *, max_operations=16, max_nodes=1000000, max_seconds=10):
    reports = []
    try:
        validate_workload(workload)
        keys(document, ('version','histories'), 'history document')
        require(type(document['version']) is int and document['version'] == 1, 'history version must be 1')
        require(isinstance(document['histories'],list), 'histories must be array')
        actual = {}
        for history in document['histories']:
            require(isinstance(history,dict) and isinstance(history.get('scenario'),str), 'history scenario missing')
            require(history['scenario'] not in actual, 'duplicate scenario history')
            actual[history['scenario']] = history
        require(set(actual) == {s['id'] for s in workload['scenarios']}, 'missing/unexpected scenario histories')
        for scenario in workload['scenarios']:
            rows, predecessors, coverage = validate_history(scenario, actual[scenario['id']], spec)
            if len(rows) > max_operations:
                report = {'verdict':'INCONCLUSIVE','reason':'operation bound exceeded'}
            else: report = search(scenario, rows, predecessors, spec, max_nodes, max_seconds)
            report.update(scenario=scenario['id'], concurrencyCoverage=coverage)
            if report['verdict'] == 'PASS' and not all(coverage.values()):
                report.update(verdict='INCONCLUSIVE',reason='no observed overlap in required concurrent phase')
            reports.append(report)
    except (ValueError, KeyError, TypeError) as error:
        return {'verdict':'INVALID_HISTORY','reason':str(error),'histories':reports}
    verdict = next((v for v in ('FAIL','INCONCLUSIVE') if any(r['verdict'] == v for r in reports)), 'PASS')
    return {'verdict':verdict,'histories':reports,'bounds':{'operations':max_operations,'nodes':max_nodes,'seconds':max_seconds}}


def read_json(path):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise ValueError(f'duplicate JSON key {key}')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workload',default=str(root/'verification/managed-workload.json'))
    parser.add_argument('--history',required=True); parser.add_argument('--report',required=True)
    parser.add_argument('--spec',default=str(root/'contract/specification.json'))
    args = parser.parse_args()
    try: result = check_document(read_json(args.workload),read_json(args.history),read_json(args.spec))
    except (OSError,ValueError) as error: result = {'verdict':'INFRA_FAILURE','reason':str(error)}
    Path(args.report).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return {'PASS':0,'FAIL':1,'INVALID_HISTORY':1,'INFRA_FAILURE':2,'INCONCLUSIVE':3}[result['verdict']]

if __name__ == '__main__': raise SystemExit(main())
