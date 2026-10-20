"""Prepare one exact r8 overlay and metadata-only R2 publisher rebind. No activation."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import plistlib
import shutil
import sys

sys.dont_write_bytecode=True
DOC=Path(__file__).resolve().parent
LOCAL=DOC/'local_only/runtime'
PARENT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-workflow-20261020-r8')
CANDIDATE=PARENT.parent/'workbench-date-top20-api-20261020-r1'
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
PARENT_PLIST='5d5c01d354c10787b70fb56919fa0652592a49dc9ca003c6ef4e8c1b2ba7b41b'
PARENT_MANIFEST='0de62ef4d96018f56cfa2ebbf91470d64b292728c8623cd0a60dd5d9ac11332a'
OLD_DOC=Path('/Users/lexi/.codex/worktrees/us-mapping-wiring/v4_app/docs/handoffs/us_mapping_wiring_20261020')
OLD_WT=OLD_DOC.parents[2]
SOURCE_PREPARED='5877b60482ffa577a67fa089ce2c971eff7d29a2e344bde90219fb5da8ca1a8e'
R2_PUBLISHER='753d1fc6abfb62b3f869190dcf0b778523b223e142e8cdfebf270e7b50732a6d'
R2_RESULT='8318f44531ed40fa3e1b73da617c7fd7ceee0274348f7546f98b590e3c600be7'
FRONT_ALLOW={
 'apps/web/src/manager-workbench/Workbench.vue',
 'apps/web/src/manager-workbench/useWorkbench.ts',
 'apps/web/src/manager-workbench/api.ts',
 'apps/web/src/manager-workbench/types.ts',
 'apps/web/src/manager-workbench/workbench.css',
}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def raw_sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def pointer(value,path):
    assert path.startswith('/')
    for token in path[1:].split('/'):
        token=token.replace('~1','/').replace('~0','~')
        value=value[int(token)] if isinstance(value,list) else value[token]
    return value

def fields(a,b,path=''):
    if isinstance(a,dict):
        assert a.keys()==b.keys()
        return [row for k in a for row in fields(a[k],b[k],path+'/'+k)]
    if isinstance(a,list):
        assert len(a)==len(b)
        return [row for i,(x,y) in enumerate(zip(a,b)) for row in fields(x,y,path+'/'+str(i))]
    return [] if a==b else [dict(path=path,before=a,after=b)]

def prepare(binding_sha):
    binding_path=DOC/'RUNTIME_FRONTEND_BINDING.json'
    assert sha(binding_path)==binding_sha, 'FRONTEND_BINDING_RAW_SHA_DRIFT'
    binding=json.loads(binding_path.read_bytes())
    assert sha(PLIST)==PARENT_PLIST and sha(PARENT/'release-manifest.json')==PARENT_MANIFEST, 'PARENT_DRIFT'
    assert not CANDIDATE.exists(), 'CANDIDATE_EXISTS_NEVER_OVERWRITE'
    assert not (DOC/'RUNTIME_CANDIDATE_PREPARED.json').exists()
    front_receipt=Path(binding['frontend_prepared_path'])
    assert sha(front_receipt)==binding['frontend_prepared_sha256']
    prepared_front=json.loads(front_receipt.read_bytes())
    delta_receipt=Path(binding['frontend_delta_path'])
    assert sha(delta_receipt)==binding['frontend_delta_sha256']==prepared_front['delta_manifest_sha256']
    front=json.loads(delta_receipt.read_bytes())
    patch=Path(binding['frontend_patch_path'])
    assert sha(patch)==prepared_front['source_patch_sha256']==front['r8_source_overlay']['patch_sha256']
    assert binding['parent_manifest_sha256']==PARENT_MANIFEST
    for proof in binding['parent_proofs']:
        assert pointer(front,proof['pointer'])==proof['expected']
    assert sha(OLD_DOC/'PREPARED.json')==SOURCE_PREPARED
    source=json.loads((OLD_DOC/'PREPARED.json').read_bytes())
    tool=PARENT/'app/ops/api_release_integration.py'
    assert sha(tool)=='2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'
    spec=importlib.util.spec_from_file_location('retained_parent_inventory',tool)
    inv=importlib.util.module_from_spec(spec);spec.loader.exec_module(inv)
    old_manifest=json.loads((PARENT/'release-manifest.json').read_bytes())
    before=inv.inventory_tree(PARENT/'app')
    assert before==old_manifest['application_inventory']['entries']
    assert inv.inventory_digest(before)=='97b803c3e009e533e77089533171aec693e5f2f8a60a7317262cbdf093623595'
    source_root=Path(binding['source_root']).resolve()
    replacements={}
    for rel,hashes in source['source_sha256'].items():
        assert sha(PARENT/'app'/rel)==hashes['before']
        assert sha(OLD_WT/rel)==hashes['after']
        replacements[rel]=dict(source_file=str(OLD_WT/rel),sha256=hashes['after'],owner='accepted-backend')
    assert set(source['source_sha256'])=={
      'v4/manager_workbench/engines/us_mapping.py','v4/manager_workbench/engines/strict_us_selection.py','v4/manager_workbench/inputs/native.py'}
    for row in binding['source_files']:
        rel=row['path'];assert rel in FRONT_ALLOW and rel not in replacements
        assert Path(row['source_file']).resolve()==source_root/Path(rel).relative_to('apps/web')
        assert pointer(front,row['receipt_path_pointer'])==rel
        assert pointer(front,row['receipt_before_sha_pointer'])==row['parent_sha256']
        assert pointer(front,row['receipt_sha_pointer'])==row['sha256']
        assert sha(Path(row['source_file']))==row['sha256']
        assert sha(PARENT/'app'/rel)==row['parent_sha256']
        replacements[rel]=dict(source_file=row['source_file'],sha256=row['sha256'],owner='frontend-writer')
    assert binding['source_files'], 'MISSING_FRONTEND_SOURCE_OVERLAY'
    for row in binding['static_files']:
        rel=row['path'];assert rel not in replacements
        assert pointer(front,row['receipt_path_pointer'])==rel
        assert rel=='apps/web/dist/manager-selection/index.html' or rel.startswith('apps/web/dist/assets/')
        assert '..' not in Path(rel).parts
        assert pointer(front,row['receipt_sha_pointer'])==row['sha256']
        assert sha(Path(row['source_file']))==row['sha256']
        original=PARENT/'app'/rel
        if original.exists() and rel!='apps/web/dist/manager-selection/index.html':
            assert sha(original)==row['sha256'], 'OLD_HASHED_ASSET_COLLISION'
            continue
        replacements[rel]=dict(source_file=row['source_file'],sha256=row['sha256'],owner='frontend-build')
    assert 'apps/web/dist/manager-selection/index.html' in replacements
    live=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench')
    assert sha(live/'pointers/20261020/NEXT_DAY.json')=='81ea8ec394f2e874b381a9a2dba9206e9cd3eb40c98bf2e65c2766c95fdd11e4', 'SOURCE_POINTER_DRIFT'
    LOCAL.mkdir(parents=True,exist_ok=True)
    backup=LOCAL/'api-parent.plist';assert not backup.exists();backup.write_bytes(PLIST.read_bytes())
    shutil.copytree(PARENT,CANDIDATE,symlinks=True)
    for rel,row in replacements.items():
        dest=CANDIDATE/'app'/rel
        if dest.exists():
            mode=dest.stat().st_mode & 0o777;dest.unlink()
        else:mode=0o644
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(Path(row['source_file']).read_bytes());dest.chmod(mode)
        assert sha(dest)==row['sha256']
    after=inv.inventory_tree(CANDIDATE/'app')
    aa,bb=({r['path']:r for r in x} for x in [before,after])
    delta_paths=sorted(k for k in aa.keys()|bb.keys() if aa.get(k)!=bb.get(k))
    expected_delta={k for k,v in replacements.items() if k not in aa or aa[k]['sha256']!=v['sha256']}
    assert set(delta_paths)==expected_delta and not aa.keys()-bb.keys()
    assert all(aa[k]==bb[k] for k in aa.keys()-set(delta_paths))
    delta=[dict(path=k,before=aa.get(k),after=bb[k]) for k in delta_paths]
    assert sha(front_receipt)==binding['frontend_prepared_sha256'], 'FRONTEND_PREPARED_DRIFT'
    assert sha(delta_receipt)==binding['frontend_delta_sha256'], 'FRONTEND_DELTA_DRIFT'
    assert sha(patch)==binding['frontend_patch_sha256'], 'FRONTEND_PATCH_DRIFT'
    identity=dict(old_manifest['candidate']);identity.update(root=str(CANDIDATE),app_root=str(CANDIDATE/'app'),release_id=CANDIDATE.name)
    if identity.get('formal_release_root')==str(PARENT):identity['formal_release_root']=str(CANDIDATE)
    sidecars={p.name:sha(p) for p in PARENT.iterdir() if p.is_file() and p.name!='release-manifest.json'}
    assert all(sha(CANDIDATE/k)==v for k,v in sidecars.items())
    manifest=dict(schema_version='v4.release_candidate.v1',activation_status='PREPARED',candidate=identity,
      application_inventory=dict(entries=after,entry_count=len(after),aggregate_sha256=inv.inventory_digest(after)),
      task_overlay=dict(parent=str(PARENT),parent_manifest_sha256=PARENT_MANIFEST,parent_inventory_sha256=inv.inventory_digest(before),
        backend_source_prepared_sha256=SOURCE_PREPARED,frontend_prepared_sha256=sha(front_receipt),frontend_delta_sha256=sha(delta_receipt),frontend_binding_sha256=binding_sha,
        full_git_equivalence_claimed=False,delta=delta,all_non_delta_entries_preserved=True,parent_sidecars_retained_as_history=sidecars))
    manifest_path=CANDIDATE/'release-manifest.json';manifest_path.unlink();manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    msha=sha(manifest_path)
    def rebind(value):
        if isinstance(value,str):return value.replace(str(PARENT),str(CANDIDATE)).replace(PARENT.name,CANDIDATE.name).replace(PARENT_MANIFEST,msha)
        if isinstance(value,list):return [rebind(v) for v in value]
        if isinstance(value,dict):return {k:rebind(v) for k,v in value.items()}
        return value
    pl=plistlib.loads(backup.read_bytes());proposed=rebind(pl);plist_delta=fields(pl,proposed)
    allowed={'/WorkingDirectory','/EnvironmentVariables/PYTHONPATH','/EnvironmentVariables/V35_APP_ROOT','/EnvironmentVariables/V35_RELEASE_ID','/EnvironmentVariables/V35_RELEASE_MANIFEST_PATH','/EnvironmentVariables/V35_RELEASE_MANIFEST_SHA256'}
    for row in plist_delta:
        assert row['path'] in allowed or (row['path'].startswith('/ProgramArguments/') and row['before'].startswith(('V35_APP_ROOT=','V35_RELEASE_ID=','V35_RELEASE_MANIFEST_PATH=','V35_RELEASE_MANIFEST_SHA256=','PYTHONPATH='))), 'UNAPPROVED_PLIST_FIELD'
    proposal=LOCAL/'api-candidate.plist';assert not proposal.exists();proposal.write_bytes(plistlib.dumps(proposed,sort_keys=False))
    result=dict(state='PREPARED_NOT_ACTIVATED',parent=str(PARENT),candidate=str(CANDIDATE),parent_plist_sha256=PARENT_PLIST,
      parent_manifest_sha256=PARENT_MANIFEST,candidate_manifest_sha256=msha,parent_inventory_sha256=inv.inventory_digest(before),
      candidate_inventory_sha256=inv.inventory_digest(after),before_count=len(before),after_count=len(after),exact_delta=delta,
      all_non_delta_entries_preserved=True,all_old_assets_root_daily_html_preserved=True,proposal_sha256=sha(proposal),plist_delta=plist_delta,
      frontend_binding_sha256=binding_sha,frontend_prepared_sha256=sha(front_receipt),frontend_delta_sha256=sha(delta_receipt),backend_prepared_sha256=SOURCE_PREPARED,
      prepare_helper_sha256=sha(Path(__file__)),activated=False,published=False)
    receipt=DOC/'RUNTIME_CANDIDATE_PREPARED.json';receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    rebind_publisher(receipt,msha,sha(proposal))
    assert sha(PLIST)==PARENT_PLIST and sha(PARENT/'release-manifest.json')==PARENT_MANIFEST,'PARENT_DRIFT_DURING_PREPARE'
    assert sha(front_receipt)==binding['frontend_prepared_sha256'] and sha(delta_receipt)==binding['frontend_delta_sha256'], 'FRONTEND_RECEIPT_DRIFT_DURING_PREPARE'
    print(json.dumps(dict(state=result['state'],candidate_manifest_sha256=msha,candidate_receipt_sha256=sha(receipt),proposal_sha256=sha(proposal))))

def rebind_publisher(candidate_receipt,manifest_sha,proposal_sha):
    old_helper=OLD_DOC/'publish_wiring_result.py';old_result=OLD_DOC/'DEPLOYMENT_RESULT_PREPARED.json'
    assert sha(old_helper)==R2_PUBLISHER and sha(old_result)==R2_RESULT
    receipt=json.loads(old_result.read_bytes())
    for row in receipt['pipeline_files']:
        original=OLD_DOC/row['path'];assert sha(original)==row['sha256']
        relative=row['path'].replace('local_only/','local_only/runtime/',1)
        dest=DOC/relative;assert not dest.exists();dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,dest)
        assert sha(dest)==row['sha256'];row['path']=relative
    backend_copy=DOC/'RUNTIME_BACKEND_PREPARED.json';assert not backend_copy.exists();backend_copy.write_bytes((OLD_DOC/'PREPARED.json').read_bytes())
    text=old_helper.read_text()
    changes={
      "LOCAL=DOC/'local_only'":"LOCAL=DOC/'local_only/runtime'",
      "releases/us-mapping-wiring-api-20261020-r1":"releases/"+CANDIDATE.name,
      "DOC/'DEPLOYMENT_RESULT_PREPARED.json'":"DOC/'RUNTIME_RESULT_PREPARED.json'",
      "DOC/'PREPARED.json'":"DOC/'RUNTIME_BACKEND_PREPARED.json'",
      "DOC/'DEPLOYMENT_CANDIDATES.json'":"DOC/'RUNTIME_CANDIDATE_PREPARED.json'",
      "DOC/'DEPLOYMENT_PUBLICATION_RECEIPT.json'":"DOC/'RUNTIME_PUBLICATION_RECEIPT.json'",
      "DOC/'DEPLOYMENT_PUBLICATION_ROLLBACK_RECEIPT.json'":"DOC/'RUNTIME_PUBLICATION_ROLLBACK_RECEIPT.json'",
      'aa257878208f88c88a71441990ef54de7030fd4c23b2d1667152f304ae7ef04d':sha(candidate_receipt),
      '118d3d465007dd3d9fff05a462b17a4efb950e4cb891f345c59308eb0ea51e59':manifest_sha,
      '9e6fa1a90073cbc32b76f86c157ba2c86145b28b08f0927986b5e13ecdbbca1e':proposal_sha,
    }
    changed=[]
    for before,after in changes.items():
        count=text.count(before);assert count>0, 'R2_BINDING_TOKEN_MISSING'
        text=text.replace(before,after);changed.append(dict(before=before,after=after,count=count))
    publisher=DOC/'RUNTIME_PUBLISH_RESULT.py';assert not publisher.exists();publisher.write_text(text)
    receipt.update(helper_sha256=sha(publisher),candidate_receipt_sha256=sha(candidate_receipt),candidate_manifest_sha256=manifest_sha,
      rebind_provenance=dict(original_result_receipt_sha256=R2_RESULT,original_publisher_sha256=R2_PUBLISHER,
        metadata_only=True,pipeline_recomputed=False,original_artifacts_same_bytes=True))
    new_result=DOC/'RUNTIME_RESULT_PREPARED.json';assert not new_result.exists();new_result.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    proof=DOC/'RUNTIME_PUBLISHER_REBIND.json';assert not proof.exists();proof.write_text(json.dumps(dict(state='METADATA_ONLY_REBIND_PREPARED',
      original_helper_sha256=R2_PUBLISHER,new_helper_sha256=sha(publisher),original_result_receipt_sha256=R2_RESULT,
      new_result_receipt_sha256=sha(new_result),exact_text_rebindings=changed,all_pipeline_artifacts_byte_identical=True,
      immutable_expected_new_pointer_sha256='985b91b19eaaf878f87295f02d8f191d2aaf4bcc2150911522a5e2a68823a248',
      business_run_recomputed=False,actual_service_changes=0,actual_state_writes=0),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--frontend-binding-sha256',required=True)
    args=parser.parse_args();prepare(args.frontend_binding_sha256)
