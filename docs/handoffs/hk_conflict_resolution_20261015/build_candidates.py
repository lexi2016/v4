"""Prepare inactive code-only candidates and the owner admission sidecar."""
from pathlib import Path
import difflib
import gzip
import hashlib
import json
import os
import shutil
import stat
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from ops import api_release_integration as integration
from upstreams.v3_shared_data.shared_data import hk_history_resolution as resolution
H=Path(__file__).resolve().parent
RELEASES=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
OWNER=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2')
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,body):path.write_text(json.dumps(body,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def prepare_resolution():
    folder=OWNER/'history_resolution/20261015-r1'
    if folder.exists():raise RuntimeError('refusing to overwrite owner sidecar')
    folder.mkdir(parents=True)
    records=[json.loads(line) for line in gzip.open(H/'candidate_decisions.jsonl.gz','rt')]
    assert len(records)==30341 and len({(r['symbol'],r['date']) for r in records})==30341
    for record in records:
        record['rule_version']=resolution.RULE
        record['active']=True
        record['normal_history_admission']='REQUIRED_FIELDS_WINDOW_GATE'
    payload=b''.join(resolution.canonical(r)+b'\n' for r in records)
    (folder/'decisions.jsonl.gz').write_bytes(gzip.compress(payload,mtime=0))
    pointer=json.loads((OWNER/'panel_latest.json').read_text())
    cm=OWNER/pointer['manifest_relative'];c=json.loads(cm.read_text())
    descriptor=json.loads((OWNER/'research_history.json').read_text())
    b=Path(descriptor['source_descriptor']['sources']['B']['path'])
    contract=dict(schema_version=resolution.SCHEMA,rule_version=resolution.RULE,
        resolver_sha256=sha(resolution.__file__),research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
        append_policy='ALL_KEYS_ALL_COLUMNS_EXACT',baseline_C_max_date='20261014',B_max_date='20260911',
        decisions_relative='history_resolution/20261015-r1/decisions.jsonl.gz',decisions_sha256=sha(folder/'decisions.jsonl.gz'),
        decision_key_count=30341,primary_confirmed_keep_C=14079,primary_corrected=0,primary_quarantined=16262,
        bindings=dict(descriptor_relative='research_history.json',descriptor_sha256=sha(OWNER/'research_history.json'),
            B_relative=b.relative_to(OWNER).as_posix(),B_sha256=sha(b),C_panel_relative=c['panel_relative'],C_panel_sha256=c['panel_sha256'],
            C_manifest_relative=pointer['manifest_relative'],C_manifest_sha256=sha(cm)))
    write(folder/'manifest.json',contract)
    write(folder/'evidence-index.json',dict(profile_sha256=sha(H/'PROFILE_RECEIPT.json'),profile_review_sha256=sha(H/'PROFILE_REVIEW.json'),
        decision_input_sha256=sha(H/'candidate_decisions.jsonl.gz'),native_representation_only=True,
        units_verified=False,historical_PIT_verified=False,formal_529_channel='MISDATED_REPAIR_SOURCE',
        unverified_Futu84_Eastmoney23_not_restored=True))
    write(H/'history_resolution_latest.staged.json',dict(manifest_relative='history_resolution/20261015-r1/manifest.json',manifest_sha256=sha(folder/'manifest.json')))
    write(H/'RESOLUTION_MANIFEST.json',dict(contract=contract,manifest_sha256=sha(folder/'manifest.json'),
        ledger_uncompressed_sha256=hashlib.sha256(payload).hexdigest(),lost_keys=0,active_pointer_installed=False))

def delta(base,projection):
    entries=[];patch=[]
    for source in sorted(projection.rglob('*')):
        if not source.is_file():continue
        rel=source.relative_to(projection).as_posix();before=base/rel
        raw=before.read_bytes() if before.exists() else None;after=source.read_bytes()
        if raw==after:continue
        proof,count=integration._diff_proof(raw,after) if raw is not None else (None,None)
        entries.append(dict(path=rel,before_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
            after_sha256=sha(source),unified_diff_sha256=proof,unified_diff_hunk_count=count))
        patch.extend(difflib.unified_diff((raw or b'').decode('utf-8-sig').splitlines(True),after.decode('utf-8-sig').splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    return entries,''.join(patch)

def code_inventory(root):
    entries=integration.inventory_tree(root)
    return [r for r in entries if not any(part in ('.runtime','__pycache__','.pytest_cache') for part in Path(r['path']).parts)]

def generic(role,base,layout='app',revision='r1'):
    target=RELEASES/f'hk-history-adjudication-{role}-20261015-{revision}'
    if target.exists():raise RuntimeError('refusing to overwrite candidate '+role)
    before=code_inventory(base)
    target.mkdir();app=target/layout
    shutil.copytree(base,app,symlinks=True,ignore=shutil.ignore_patterns('.runtime','__pycache__','.pytest_cache'))
    assert code_inventory(app)==before
    entries,patch=delta(base,H/'source_projection'/role)
    for row in entries:
        source=H/'source_projection'/role/row['path'];dest=app/row['path']
        with integration._candidate_parent_writable(app,row['path']) as writable:
            if writable.exists():writable.chmod(stat.S_IMODE(writable.stat().st_mode)|stat.S_IWUSR)
            shutil.copy2(source,writable)
    after=code_inventory(app);changed={r['path'] for r in entries}
    unchanged=[r for r in before if r['path'] not in changed]
    assert unchanged==[r for r in after if r['path'] not in changed]
    assert code_inventory(base)==before
    manifest=dict(schema_version='v4.hk_adjudication_code_release.v1',activation_status='NOT_ACTIVATED',role=role,
        candidate=dict(root=str(target),app_root=str(app),release_id=target.name),
        base=dict(app_root=str(base),inventory_sha256=integration.inventory_digest(before),entry_count=len(before)),
        delta_entries=entries,non_delta_entry_count=len(unchanged),non_delta_inventory_sha256=integration.inventory_digest(unchanged),
        application_inventory=dict(entries=after,entry_count=len(after),aggregate_sha256=integration.inventory_digest(after)),
        runtime_state_copied=False,source_workspace_full_tree_copied=False)
    write(target/'release-manifest.json',manifest)
    (H/f'{role.upper()}_DELTA.patch').write_text(patch)
    write(H/f'{role.upper()}_DELTA_RECEIPT.json',dict(base=manifest['base'],entries=entries,non_delta_entry_count=len(unchanged),non_delta_inventory_sha256=manifest['non_delta_inventory_sha256']))
    return dict(candidate_root=str(target),app_root=str(app),base_root=str(base),manifest_sha256=sha(target/'release-manifest.json'),
        delta_paths=sorted(changed),non_delta_count=len(unchanged),inventory_sha256=manifest['application_inventory']['aggregate_sha256'])

def api(revision='r1'):
    active=integration.read_active_release(PLIST)
    base=Path(active['app_root']);target=RELEASES/f'hk-history-adjudication-api-20261015-{revision}'
    if target.exists():raise RuntimeError('refusing to overwrite API candidate')
    entries,patch=delta(base,H/'source_projection/api')
    write(H/'API_DELTA_RECEIPT.json',dict(schema_version=integration.DELTA_SCHEMA_VERSION,base=integration._base_binding(active),entries=entries))
    target.mkdir()
    details=integration.build_integrated_app(active_api_plist_path=PLIST,source_root=H/'source_projection/api',candidate_root=target,
        delta_receipt_path=H/'API_DELTA_RECEIPT.json',explicit_untracked_paths=tuple(r['path'] for r in entries if r['before_sha256'] is None))
    inventory=integration.inventory_tree(target/'app')
    manifest=dict(schema_version='v4.release_candidate.v1',activation_status='NOT_ACTIVATED',
        candidate=dict(root=str(target),app_root=str(target/'app'),release_id=target.name,module_role='gateway',module_contract_sha256=None,formal_release_root=str(RELEASES)),
        application_inventory=dict(entry_count=len(inventory),aggregate_sha256=integration.inventory_digest(inventory),entries=inventory),api_integration=details)
    write(target/'release-manifest.json',manifest)
    verification=integration.verify_api_release_candidate(candidate_root=target,active_api_plist_path=PLIST,
        expected_manifest_sha256=sha(target/'release-manifest.json'),active_pointer='base')
    (H/'API_DELTA.patch').write_text(patch)
    return dict(candidate_root=str(target),app_root=str(target/'app'),base_root=str(base),manifest_sha256=sha(target/'release-manifest.json'),verification=verification)

if __name__=='__main__':
    prepare_resolution()
    result=dict(api=api(),shared=generic('shared',RELEASES/'morning-upstream-time-20261015-r2/app/upstreams/v3_shared_data','app/upstreams/v3_shared_data'),
        scheduler=generic('scheduler',RELEASES/'hk-pool-fupan-isolation-20261015-r1/app'),
        materializer=generic('materializer',RELEASES/'20260929-manager-pytdx-close-r1/app'),
        reviewcore=generic('reviewcore',Path('/Users/lexi/Library/Application Support/com.lexi.review-core.local/app')),
        active_pointer_installed=False,services_changed=False)
    write(H/'PUBLICATION_RECEIPT.json',result)
    print(json.dumps({role:doc.get('manifest_sha256') for role,doc in result.items() if isinstance(doc,dict)},sort_keys=True))
