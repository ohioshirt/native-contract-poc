"""Independent finite numeric reduction plus exhaustive product exploration.

IDs 1..3 are a test instantiation, not a production schema. Issued sets are
proof instrumentation; native snapshots do not expose them.
"""
import argparse
from collections import deque
import json
from pathlib import Path
from verification.async_contract import step

OWNERS = ('A','B')
BOUND = 3


def snapshot(local):
    return dict(zip(('state','pendingRequestId','nextRequestId'),local[:3]))


def independent_reduce(spec, local, owner, event, mutant=None):
    """Direct finite rules from rows. Does not call/import the oracle reducer."""
    state, pending, allocator, issued = local
    effects, rejection = [], None
    name = event['event']
    if name == 'Snapshot': return local, {'snapshot':snapshot(local),'effects':[],'rejection':None}
    response = name in ('RefreshSucceeded','RefreshFailed')
    foreign = response and event['tokenOwner'] != owner
    if foreign and mutant != 'owner-check-removed':
        return local, {'snapshot':snapshot(local),'effects':[],'rejection':'ForeignRequest'}
    row = next(r for r in spec['async']['transitions'] if r['state'] == state and r['event'] == name)
    enabled = row['guard'] == 'always' or (state == 'Refreshing' and pending is not None and pending == event.get('requestId'))
    if enabled:
        action = row['pendingAction']
        if action == 'allocate' and allocator is None:
            rejection = 'RequestIdExhausted'
        else:
            state = row['nextState']
            allocated = None
            if action == 'clear': pending = None
            if action == 'allocate':
                allocated = allocator; pending = allocated
                allocator = None if allocated == BOUND else allocated+1
                issued = issued | {allocated}
            for effect in row['effects']:
                if effect == 'RequestTokenRefresh': effects.append({'effect':effect,'requestId':allocated})
                else: effects.append({'effect':effect})
    if mutant == 'reset-on-logout' and name == 'Logout': allocator = 1
    new = (state,pending,allocator,frozenset(issued))
    return new, {'snapshot':snapshot(new),'effects':effects,'rejection':rejection}


def oracle_result(spec, local, owner, event):
    if event['event'] == 'Snapshot': return {'snapshot':snapshot(local),'effects':[],'rejection':None}
    if 'tokenOwner' in event and event['tokenOwner'] != owner:
        return {'snapshot':snapshot(local),'effects':[],'rejection':'ForeignRequest'}
    normalized = {k:v for k,v in event.items() if k != 'tokenOwner'}
    result = step(spec, local[0],local[1],local[2],normalized,request_id_max=BOUND)
    return {'snapshot':{k:result[k] for k in ('state','pendingRequestId','nextRequestId')}, 'effects':result['effects'], 'rejection':result['rejection']}


def invariant(before, after, owner, event, result):
    state,pending,allocator,issued = after
    if (pending is not None) != (state == 'Refreshing'): return 'PendingIffRefreshing'
    if pending is not None and (pending not in issued or not 1 <= pending <= BOUND): return 'PendingIssued'
    rank = lambda ident: BOUND+1 if ident is None else ident
    if rank(allocator) < rank(before[2]): return 'AllocatorMonotonicity'
    if allocator is not None and any(i >= allocator for i in issued): return 'AllocatorMonotonicity'
    if event['event'] in ('RefreshSucceeded','RefreshFailed'):
        if event['tokenOwner'] != owner:
            if after != before or result['effects'] or result['rejection'] != 'ForeignRequest': return 'OwnerIsolation'
        elif before[0] != 'Refreshing' or before[1] != event['requestId']:
            if after != before or result['effects'] or result['rejection'] is not None: return 'StaleResponseSafety'
    for effect in result['effects']:
        if effect['effect'] == 'RequestTokenRefresh' and effect['requestId'] in before[3]: return 'NoIdReuse'
    if event['event'] == 'TokenExpired' and before[0] == 'Authenticated' and before[2] is None:
        if after != before or result['effects'] or result['rejection'] != 'RequestIdExhausted': return 'AtomicExhaustion'
    return None


def actions(product_state):
    issued = [(OWNERS[i], ident) for i,local in enumerate(product_state) for ident in sorted(local[3])]
    for owner in OWNERS:
        for event in ('LoginSucceeded','Logout','TokenExpired','Snapshot'):
            yield owner, {'event':event}
        for token_owner,ident in issued:
            for event in ('RefreshSucceeded','RefreshFailed'):
                yield owner, {'event':event,'tokenOwner':token_owner,'requestId':ident}


def explore(spec, mutant=None):
    if mutant not in (None,'reset-on-logout','owner-check-removed'): raise ValueError('unknown mutant')
    if spec['async']['initialState'] != 'Unauthenticated' or spec['async']['requestIdMin'] != 1:
        raise ValueError('finite instantiation requires Unauthenticated and min=1')
    start = tuple(('Unauthenticated',None,1,frozenset()) for _ in OWNERS)
    queue = deque([start]); parent = {start:None}; edges = 0
    def trace(state, last):
        path = [last]
        while parent[state] is not None:
            prev,record = parent[state]; path.append(record); state = prev
        return list(reversed(path))
    while queue:
        current = queue.popleft()
        for owner,event in actions(current):
            edges += 1; index = OWNERS.index(owner); before = current[index]
            after,result = independent_reduce(spec,before,owner,event,mutant)
            record = {'owner':owner,'event':event,'before':snapshot(before),'after':snapshot(after),'issuedBefore':sorted(before[3]),'issuedAfter':sorted(after[3]),'effects':result['effects'],'rejection':result['rejection']}
            violation = invariant(before,after,owner,event,result)
            if violation:
                return {'verdict':'COUNTEREXAMPLE','mutant':mutant,'invariant':violation,'bound':{'owners':2,'min':1,'max':BOUND},'trace':trace(current,record),'states':len(parent),'edges':edges}
            if mutant is None:
                expected = oracle_result(spec,before,owner,event)
                if result != expected:
                    return {'verdict':'FAIL','invariant':'OracleCorrespondence','expected':expected,'observed':result,'trace':trace(current,record),'states':len(parent),'edges':edges}
            successor = list(current); successor[index] = after; successor = tuple(successor)
            if successor not in parent:
                parent[successor] = (current,record); queue.append(successor)
    return {'verdict':'PASS','mutant':mutant,'bound':{'owners':2,'min':1,'max':BOUND},'states':len(parent),'edges':edges,'correspondenceChecked':mutant is None}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',default=str(root/'contract/specification.json')); parser.add_argument('--output',required=True)
    args = parser.parse_args(); out = Path(args.output); out.mkdir(parents=True,exist_ok=True)
    spec = json.loads(Path(args.spec).read_text())
    results = {'base':explore(spec),'reset-on-logout':explore(spec,'reset-on-logout'),'owner-check-removed':explore(spec,'owner-check-removed')}
    passed = results['base']['verdict'] == 'PASS' and results['reset-on-logout'].get('invariant') == 'AllocatorMonotonicity' and results['owner-check-removed'].get('invariant') == 'OwnerIsolation'
    report = {'verdict':'PASS' if passed else 'FAIL','results':results}
    (out/'numeric-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2)); return 0 if passed else 1

if __name__ == '__main__': raise SystemExit(main())
