"""Prepare two immutable role-specific overlays. Never activate or publish research."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import plistlib
import shutil
import sys

sys.dont_write_bytecode = True
DOC = Path(__file__).resolve().parent
WT = DOC.parents[2]
LOCAL = DOC / 'local_only'
RELEASES = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
PREPARED_SHA = '5877b60482ffa577a67fa089ce2c971eff7d29a2e344bde90219fb5da8ca1a8e'
NATIVE = 'v4/manager_workbench/inputs/native.py'
FUNCTION = '_security_master_identity'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def raw_sha(raw):
    return hashlib.sha256(raw).hexdigest()

def method(raw):
    tree = ast.parse(raw)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'NativeAdapters')
    found = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == FUNCTION]
    assert len(found) == 1
    node = found[0]
    lines = raw.splitlines(keepends=True)
    return sum(map(len, lines[:node.lineno-1])), sum(map(len, lines[:node.end_lineno]))

def changed(a, b, path=''):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        return [r for k in a for r in changed(a[k], b[k], path+'/'+k)]
    if isinstance(a, list):
        assert len(a) == len(b)
        return [r for i, (x, y) in enumerate(zip(a, b)) for r in changed(x, y, path+'/'+str(i))]
    return [] if a == b else [dict(path=path, before=a, after=b)]

def main():
    assert sha(DOC / 'PREPARED.json') == PREPARED_SHA
    prepared = json.loads((DOC / 'PREPARED.json').read_bytes())
    assert not (DOC / 'DEPLOYMENT_CANDIDATES.json').exists()
    LOCAL.mkdir(exist_ok=True)
    for rel, hashes in prepared['source_sha256'].items():
        assert sha(WT / rel) == hashes['after']
    r6 = RELEASES / 'announcement-transport-recovery-20261020-r6'
    tool = r6 / 'app/ops/api_release_integration.py'
    assert sha(tool) == '2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'
    spec = importlib.util.spec_from_file_location('preserved_inventory', tool)
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    roles = [
        dict(role='api', label='com.lexi.v35.api-only',
             parent=RELEASES/'workbench-calendar-api-20261020-r1',
             parent_manifest_sha256='d4b39f80c0b34271373617ccbd402a5927193e94e140f20feee4a08511a8189d',
             active_plist_sha256='4f341d12c05782895ed7d0d58ea1500d92971b345bef3e8b4db555a1956cc62c',
             base_plist=Path('/Users/lexi/.codex/worktrees/us-mapping-auto-close/v4_app/docs/handoffs/workbench_calendar_20261020/local_only/calendar-api-candidate.plist'),
             base_plist_sha256='5515167934594af314f2920e8b35a72d3330540f30129e7264b4e488c03a9ea8',
             candidate=RELEASES/'us-mapping-wiring-api-20261020-r1'),
        dict(role='scheduler', label='com.lexi.v35.scheduler',
             parent=RELEASES/'us-mapping-close-scheduler-20261020-r1',
             parent_manifest_sha256='d2d73d8417026d888bba9e8043c39b804b9ffdaa82b8a7c91cd322eb38ee8d95',
             active_plist_sha256='a88d2634041083f4ff7bb8904230666c3afc4100cce1a8a9e49469f1b8199b3c',
             base_plist=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist'),
             base_plist_sha256='a88d2634041083f4ff7bb8904230666c3afc4100cce1a8a9e49469f1b8199b3c',
             candidate=RELEASES/'us-mapping-wiring-scheduler-20261020-r1'),
    ]
    output = dict(state='PREPARED_PENDING_INCREMENTAL_REVIEW', source_prepared_sha256=PREPARED_SHA,
                  activation='NOT_RUN', research_publication='NOT_RUN', provider_calls=0, business_posts=0, roles=[])
    for role in roles:
        parent, candidate = role['parent'], role['candidate']
        actual_plist = Path('/Users/lexi/Library/LaunchAgents')/(role['label']+'.plist')
        assert sha(actual_plist) == role['active_plist_sha256'], 'ACTIVE_PLIST_DRIFT'
        assert not candidate.exists(), 'CANDIDATE_EXISTS_NEVER_OVERWRITE'
        assert sha(role['base_plist']) == role['base_plist_sha256']
        assert sha(parent/'release-manifest.json') == role['parent_manifest_sha256']
        manifest = json.loads((parent/'release-manifest.json').read_bytes())
        before = inv.inventory_tree(parent/'app')
        assert before == manifest['application_inventory']['entries']
        assert inv.inventory_digest(before) == manifest['application_inventory']['aggregate_sha256']
        projections = {}
        function_proof = None
        for rel, hashes in prepared['source_sha256'].items():
            original, accepted = (parent/'app'/rel).read_bytes(), (WT/rel).read_bytes()
            if role['role'] == 'scheduler' and rel == NATIVE:
                api_original = (r6/'app'/rel).read_bytes()
                assert raw_sha(api_original) == hashes['before']
                a, b = method(original)
                c, d = method(api_original)
                x, y = method(accepted)
                assert original[a:b] == api_original[c:d], 'FUNCTION_PREIMAGE_DIFFERS'
                # New import is local and the existing scheduler exports this same loader.
                bindings = parent/'app/v4/manager_workbench/inputs/source_bindings.py'
                assert 'def security_master(config, context):' in bindings.read_text()
                assert all(name in original.decode() for name in ['owner_digest', 'SafeRoot', 'raw_sha', 'import csv', 'import io'])
                projection = original[:a] + accepted[x:y] + original[b:]
                p, q = method(projection)
                assert projection[:p] == original[:a] and projection[q:] == original[b:]
                assert projection[p:q] == accepted[x:y]
                ast.parse(projection)
                function_proof = dict(name=FUNCTION, before_function_sha256=raw_sha(original[a:b]),
                    accepted_function_sha256=raw_sha(accepted[x:y]),
                    scheduler_before_sha256=raw_sha(original), scheduler_after_sha256=raw_sha(projection),
                    all_bytes_outside_function_preserved=True, source_bindings_sha256=sha(bindings),
                    dependency_evidence='Existing local security_master loader and existing native globals; no new global imports.')
                projections[rel] = projection
            else:
                assert raw_sha(original) == hashes['before']
                projections[rel] = accepted
        backup = LOCAL/(role['role']+'-original-active.plist')
        assert not backup.exists()
        backup.write_bytes(actual_plist.read_bytes())
        (LOCAL/(role['role']+'-expected-parent.plist')).write_bytes(role['base_plist'].read_bytes())
        shutil.copytree(parent, candidate, symlinks=True)
        for rel, raw in projections.items():
            target = candidate/'app'/rel
            mode = target.stat().st_mode & 0o777
            target.unlink()
            target.write_bytes(raw)
            target.chmod(mode)
        after = inv.inventory_tree(candidate/'app')
        aa, bb = ({r['path']:r for r in entries} for entries in [before, after])
        delta_paths = sorted(k for k in aa.keys() | bb.keys() if aa.get(k) != bb.get(k))
        assert set(delta_paths) == set(prepared['source_allowlist'])
        assert aa.keys() == bb.keys()
        assert all(aa[k] == bb[k] for k in aa.keys()-set(delta_paths))
        delta = [dict(path=k, before=aa[k], after=bb[k]) for k in delta_paths]
        identity = dict(manifest['candidate'])
        identity.update(root=str(candidate), app_root=str(candidate/'app'), release_id=candidate.name)
        if identity.get('formal_release_root') == str(parent):
            identity['formal_release_root'] = str(candidate)
        sidecars = {p.name:sha(p) for p in parent.iterdir() if p.is_file() and p.name != 'release-manifest.json'}
        assert all(sha(candidate/name) == value for name,value in sidecars.items())
        new_manifest = dict(schema_version='v4.release_candidate.v1', activation_status='PREPARED', candidate=identity,
            application_inventory=dict(entries=after, entry_count=len(after), aggregate_sha256=inv.inventory_digest(after)),
            task_overlay=dict(parent=str(parent), parent_manifest_sha256=role['parent_manifest_sha256'],
                source_prepared_sha256=PREPARED_SHA, source_worktree=str(WT), full_git_equivalence_claimed=False,
                delta=delta, all_non_delta_entries_preserved=True, parent_sidecars_retained_as_history=sidecars,
                scheduler_function_projection=function_proof,
                pending_dependency='calendar must be active and re-frozen before API activation' if role['role']=='api' else None))
        (candidate/'release-manifest.json').write_text(json.dumps(new_manifest,ensure_ascii=False,indent=2)+'\n')
        manifest_sha = sha(candidate/'release-manifest.json')
        def rebind(value):
            if isinstance(value,str):
                return value.replace(str(parent),str(candidate)).replace(parent.name,candidate.name).replace(role['parent_manifest_sha256'],manifest_sha)
            if isinstance(value,list):return [rebind(v) for v in value]
            if isinstance(value,dict):return {k:rebind(v) for k,v in value.items()}
            return value
        original = plistlib.loads(role['base_plist'].read_bytes())
        proposed = rebind(original)
        fields = changed(original,proposed)
        assert all(isinstance(row['before'],str) and row['after']==rebind(row['before']) for row in fields)
        proposal = LOCAL/(role['role']+'-candidate.plist')
        assert not proposal.exists()
        proposal.write_bytes(plistlib.dumps(proposed,sort_keys=False))
        output['roles'].append(dict(role=role['role'],label=role['label'],parent=str(parent),candidate=str(candidate),
            expected_parent_plist_sha256=role['base_plist_sha256'],actual_plist_at_prepare_sha256=sha(actual_plist),
            parent_manifest_sha256=role['parent_manifest_sha256'],candidate_manifest_sha256=manifest_sha,
            parent_inventory_sha256=inv.inventory_digest(before),candidate_inventory_sha256=inv.inventory_digest(after),
            before_entries=len(before),after_entries=len(after),exact_delta=delta,
            all_non_delta_entries_preserved=True,proposal_plist_sha256=sha(proposal),plist_delta=fields,
            function_projection=function_proof, all_static_assets_and_html_preserved=True))
    # No active pointer, source, configuration, business data or scheduler slot changed.
    for role in roles:
        p=Path('/Users/lexi/Library/LaunchAgents')/(role['label']+'.plist')
        assert sha(p)==role['active_plist_sha256'], 'ACTIVE_DRIFT_DURING_PREPARE'
    output['helper_sha256']=sha(Path(__file__))
    (DOC/'DEPLOYMENT_CANDIDATES.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in output.items() if k!='roles'},ensure_ascii=False))
    for row in output['roles']:
        print(json.dumps({k:v for k,v in row.items() if k not in ['exact_delta','plist_delta']},ensure_ascii=False))

def reuse_prepared_api():
    """Explicitly adopt exact already-created r1; never mutate it or accept scheduler drift."""
    assert sha(DOC/'PREPARED.json') == PREPARED_SHA
    stop = DOC/'DEPLOYMENT_PREPARE_STOP.json'
    assert sha(stop) == '3500c3708c8a6f31feb155f84e81165c54698b1df637b3758d7c0667abff3f99'
    previous = json.loads(stop.read_bytes())['api_partial_prepared']
    candidate = Path(previous['candidate'])
    parent = Path(previous['parent'])
    assert sha(candidate/'release-manifest.json') == '118d3d465007dd3d9fff05a462b17a4efb950e4cb891f345c59308eb0ea51e59'
    assert sha(parent/'release-manifest.json') == previous['parent_manifest_sha256']
    assert sha(LOCAL/'api-candidate.plist') == '9e6fa1a90073cbc32b76f86c157ba2c86145b28b08f0927986b5e13ecdbbca1e'
    tool = RELEASES/'announcement-transport-recovery-20261020-r6/app/ops/api_release_integration.py'
    assert sha(tool) == '2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'
    spec = importlib.util.spec_from_file_location('reuse_inventory',tool)
    inv=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    mm = []
    for root in [parent,candidate]:
        manifest=json.loads((root/'release-manifest.json').read_bytes())
        entries=inv.inventory_tree(root/'app')
        assert entries == manifest['application_inventory']['entries']
        assert inv.inventory_digest(entries) == manifest['application_inventory']['aggregate_sha256']
        mm.append({r['path']:r for r in entries})
    aa,bb=mm
    assert aa.keys()==bb.keys()
    prepared=json.loads((DOC/'PREPARED.json').read_bytes())
    delta=sorted(k for k in aa if aa[k]!=bb[k])
    assert set(delta)==set(prepared['source_allowlist'])
    for rel,hashes in prepared['source_sha256'].items():
        assert sha(WT/rel)==hashes['after']==sha(candidate/'app'/rel)
        assert sha(parent/'app'/rel)==hashes['before']
    output=dict(state='API_ONLY_PREPARED_PENDING_INDEPENDENT_REVIEW',
        source_prepared_sha256=PREPARED_SHA, helper_sha256=sha(Path(__file__)),
        explicit_reuse=True, candidate_rebuilt=False, original_stop_receipt_sha256=sha(stop),
        api=previous, scheduler=dict(state='PENDING_PARENT_DRIFT',accepted=False,activated=False,
            natural_automatic_wiring='NOT_DEPLOYED',stop_receipt_sha256=sha(stop)),
        activation='NOT_RUN',research_publication='NOT_RUN',provider_calls=0,business_posts=0)
    receipt=DOC/'DEPLOYMENT_CANDIDATES.json'
    assert not receipt.exists(), 'DO_NOT_REPLACE_FROZEN_API_RECEIPT'
    receipt.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(state=output['state'],receipt_sha256=sha(receipt),candidate_manifest_sha256=sha(candidate/'release-manifest.json'))))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Only explicit existing API r1 reuse is currently authorized.')
    parser.add_argument('--reuse-prepared-api',action='store_true',required=True)
    parser.parse_args()
    reuse_prepared_api()
