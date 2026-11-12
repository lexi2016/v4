"""Bounded preparation using existing inventory helpers; no service/data writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
SOURCE=Path('/Users/lexi/.codex/worktrees/v192-source-binding-20261112/v4_app')
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-compaction-20261112-r1')
DEST=BASE.parent/'v4-v192-source-binding-20261112-r3'
sys.path.insert(0,str(SOURCE))
from ops.api_release_integration import inventory_tree, inventory_digest


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def clone(source,target):
    subprocess.run(['/bin/cp','-cR',str(source),str(target)],check=True)
def main():
    expected={'main':'c779dbf846b25891e45687be6ebdbb7c4766e683e117e10901fe601c688e3d30',
              'stage':'af3f7b25c1e9f8b421b9c98f60d084d8cc29f03ded8a43600152886509d4c59b'}
    delta=json.loads((HERE/'RUNTIME_DELTA_R3.json').read_bytes())
    for role,digest in expected.items():assert sha(BASE/role/'release-manifest.json')==digest
    for item in delta['entries']:
        source=Path(item['source']);prepared=Path(item['prepared'])
        assert (sha(source) if source.exists() else None)==item['before_sha256']
        assert sha(prepared)==item['after_sha256']
    DEST.mkdir(exist_ok=False)
    shared=DEST/'shared-package'
    clone(Path(delta['shared_base']),shared)
    for item in delta['entries']:
        if item['root']=='shared':shutil.copy2(item['prepared'],shared/item['path'])
    shared_inventory=inventory_tree(shared)
    summaries={}
    old_bind=None
    for role in ['main','stage']:
        target=DEST/role;target.mkdir();app=target/'app'
        clone(BASE/role/'app',app)
        old=json.loads((BASE/role/'release-manifest.json').read_bytes())
        base_entries=inventory_tree(BASE/role/'app')
        assert base_entries==old['application_inventory']['entries']
        before={r['path']:r for r in base_entries}
        if role=='main':
            for item in delta['entries']:
                if item['root']=='main':
                    path=app/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(item['prepared'],path)
        else:
            p=app/'stage_center_tick_config.json';config=json.loads(p.read_bytes())
            old_bind=config['research_owner_binding'];hist=config.setdefault('research_historical_owner_bindings',[])
            if old_bind not in hist:hist.append(old_bind)
            config['research_owner_binding']=summaries['main']['binding']
            config['release_id']=DEST.name+'-stage'
            save(p,config)
        entries=inventory_tree(app);after={r['path']:r for r in entries}
        changed=sorted(k for k in set(before)|set(after)if before.get(k)!=after.get(k))
        allowed={i['path']for i in delta['entries']if i['root']=='main'}if role=='main'else{'stage_center_tick_config.json'}
        assert set(changed)==allowed,(role,changed,allowed)
        manifest=copy.deepcopy(old)
        manifest.update(app_root=str(app),release_id=DEST.name+'-'+role,candidate=DEST.name,
            activation_status='PREPARED_NOT_ACTIVATED',deployment_status='PREPARED',
            generated_at=datetime.now(timezone.utc).isoformat(),parent_release_root=str(BASE/role),
            parent_manifest_sha256=expected[role],source_root=str(SOURCE))
        manifest['app_files']=[dict(path=r['path'],sha256=r['sha256'],size=r['size'])for r in entries if r.get('kind','file')=='file']
        manifest['application_inventory']=dict(entries=entries,aggregate_sha256=inventory_digest(entries))
        manifest['v192_source_binding']=dict(scope='EXACT_D11_D12_SOURCE_AND_FUTURE_DATE_BINDING',
            delta=changed,delta_receipt=dict(path=str(HERE/'RUNTIME_DELTA_R3.json'),sha256=sha(HERE/'RUNTIME_DELTA_R3.json')),
            oracle_sources_changed=False,api_changed=False,shared_package_root=str(shared),
            shared_inventory_sha256=inventory_digest(shared_inventory),
            previous_owner_binding=old_bind if role=='stage'else None)
        save(target/'release-manifest.json',manifest)
        binding=dict(app_root=str(app),manifest_path=str(target/'release-manifest.json'),
            manifest_sha256=sha(target/'release-manifest.json'),release_id=manifest['release_id'])
        summaries[role]=dict(binding=binding,changed=changed,non_delta_entries_preserved=len(before)-len(set(before)&allowed))
        label='com.lexi.v4.scheduler'if role=='main'else'com.lexi.stage-center.scheduler'
        original=Path.home()/'Library/LaunchAgents'/(label+'.plist')
        plist=plistlib.loads(original.read_bytes())
        assert plist['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256']==expected[role]
        def rebase(v):
            if isinstance(v,str):return v.replace(str(BASE/role/'app'),str(app))
            if isinstance(v,list):return [rebase(x)for x in v]
            if isinstance(v,dict):return {k:rebase(x)for k,x in v.items()}
            return v
        plist=rebase(plist);env=plist['EnvironmentVariables']
        env['V4_RELEASE_MANIFEST_PATH']=binding['manifest_path'];env['V4_RELEASE_MANIFEST_SHA256']=binding['manifest_sha256']
        if role=='main':env['V4_SHARED_PACKAGE_ROOT']=str(shared)
        # Local prepared plist only; it is neither installed nor loaded.
        pp=target/(label+'.prepared.plist');pp.write_bytes(plistlib.dumps(plist));pp.chmod(0o600)
        summaries[role]['original_plist']=dict(path=str(original),sha256=sha(original))
        summaries[role]['prepared_plist']=dict(path=str(pp),sha256=sha(pp))
    save(HERE/'INACTIVE_CANDIDATES_R3.json',dict(status='PREPARED_NOT_ACTIVATED',candidate_root=str(DEST),roles=summaries,
        shared_package_root=str(shared),shared_inventory_sha256=inventory_digest(shared_inventory),
        API_changed=False,services_changed=False,shared_store_written=False))
    print(json.dumps(dict(status='PREPARED_NOT_ACTIVATED',candidate_root=str(DEST),roles={k:v['changed']for k,v in summaries.items()})))
if __name__=='__main__':main()
