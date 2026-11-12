"""One bounded P2 identity refresh of the existing inactive R3 candidate."""
import hashlib,json,plistlib,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=Path('/Users/lexi/.codex/worktrees/v192-source-binding-20261112/v4_app')
sys.path.insert(0,str(SOURCE))
from ops.api_release_integration import inventory_tree,inventory_digest

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def main():
    plan=load(HERE/'INACTIVE_CANDIDATES_R3.json')
    old={'main':'58e9208b5ca5a1782abd75baf2952691de02ace03a7b8eab88b10f9394315dee','stage':'c789a929f6e9b03a27dba7e850ed7cb79ed4424b760549a80a76ddcdc546194b'}
    for role,v in plan['roles'].items():
        p=Path(v['binding']['manifest_path']);assert sha(p)==old[role]
        app=Path(v['binding']['app_root'])
        if role=='stage':
            cp=app/'stage_center_tick_config.json';config=load(cp)
            assert config['research_owner_binding']['manifest_sha256']==old['main']
            config['research_owner_binding']['manifest_sha256']=plan['roles']['main']['binding']['manifest_sha256']
            save(cp,config)
        manifest=load(p);entries=inventory_tree(app)
        manifest['app_files']=[dict(path=row['path'],sha256=row['sha256'],size=row['size'])for row in entries if row.get('kind','file')=='file']
        manifest['application_inventory']=dict(entries=entries,aggregate_sha256=inventory_digest(entries))
        manifest['v192_source_binding']['delta_receipt']['sha256']=sha(HERE/'RUNTIME_DELTA_R3.json')
        manifest['v192_legacy_metadata_review_repair']=dict(status='PENDING_INCREMENTAL_REVIEW',previous_manifest_sha256=old[role],previous_failed_frozen_sha256='a1046317c3814f37376ad080fe38e843a682289961412877915ebbc671694050',scope='EXACT_SHARED_RUN_ARTIFACT_PATH_WITH_OPTIONAL_METADATA_COMPATIBILITY')
        save(p,manifest);v['binding']['manifest_sha256']=sha(p)
        pp=Path(v['prepared_plist']['path']);plist=plistlib.loads(pp.read_bytes());plist['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256']=v['binding']['manifest_sha256'];pp.write_bytes(plistlib.dumps(plist));pp.chmod(0o600);v['prepared_plist']['sha256']=sha(pp)
    plan['incremental_review_repair']=dict(status='PENDING_INCREMENTAL_REVIEW',previous_failed_scope_sha256='a1046317c3814f37376ad080fe38e843a682289961412877915ebbc671694050')
    save(HERE/'INACTIVE_CANDIDATES_R3.json',plan)
    import runpy
    module=runpy.run_path(str(HERE/'prepare_control_assets.py'));module['main']()
if __name__=='__main__':main()
