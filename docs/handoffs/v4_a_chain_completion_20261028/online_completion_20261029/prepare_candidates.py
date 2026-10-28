"""One-shot new immutable release preparation. No plist or lifecycle writes."""
from pathlib import Path
import importlib.util,sys,json,hashlib,shutil,difflib,os

HERE=Path(__file__).resolve().parent
RELEASES=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
API_BASE=RELEASES/'daily-r19-profile-20261029-r1-api'
STAGE_BASE=RELEASES/'v4-retirement-20261028-stage'
API=RELEASES/'a-chain-completion-20261029-r1-api'
STAGE=RELEASES/'a-chain-completion-20261029-r1-stage'
PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist')
R19_CONTROL=Path('/Users/lexi/Desktop/学习/因子工厂/research/original_daily_panel_r19_integration_20261029_r1/control_v4')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    assert not API.exists() and not STAGE.exists(),'New release path already exists; never overwrite'
    pins=json.loads((HERE/'SCOPE.json').read_text())['READONLY_BASELINES']
    for owner,root in [('api',API_BASE),('stage',STAGE_BASE)]:
        assert sha((root/'release-manifest.json').read_bytes())==pins[owner]['manifest_sha256']
    control=HERE/'control';control.mkdir(exist_ok=True)
    contract=R19_CONTROL/'api_module_contracts.current-v4.json'
    assert sha(contract.read_bytes())=='a785856ccacb0fb238d780a1bc0f1ceacfaf9b477f7661d86c7d5d4e3898e048'
    shutil.copy2(contract,control/contract.name)
    operator=R19_CONTROL/'publication_operator.py'
    assert sha(operator.read_bytes())=='6e55505f01ffb6f3c91491b54f6200e2910e803eb4827459c964ddbfaded3050'
    shutil.copy2(operator,control/operator.name)
    sys.path.insert(0,str(API_BASE/'app'))
    integ=module(API_BASE/'app/ops/api_release_integration.py','a_chain_prepare_integration')
    integ.MODULE_CONTRACT_PATH=control/contract.name
    active=integ.read_active_release(PLIST)
    assert active['release_manifest_sha256']==pins['api']['manifest_sha256']
    entries=[]
    for relative in ['apps/api/v4_api/app.py','apps/api/v4_api/review_router.py']:
        before=(API_BASE/'app'/relative).read_bytes();after=(HERE/'sources/api'/relative).read_bytes()
        proof,count=integ._diff_proof(before,after)
        entries.append(dict(path=relative,before_sha256=sha(before),after_sha256=sha(after),unified_diff_sha256=proof,unified_diff_hunk_count=count))
    receipt=dict(schema_version=integ.DELTA_SCHEMA_VERSION,base=integ._base_binding(active),entries=entries)
    delta_path=HERE/'API_DELTA_RECEIPT.json';write(delta_path,receipt)
    API.mkdir()
    integration=integ.build_integrated_app(active_api_plist_path=PLIST,source_root=HERE/'sources/api',candidate_root=API,delta_receipt_path=delta_path)
    # Only the private candidate delta files are chmod'ed; base inodes are not shared.
    for entry in entries:(API/'app'/entry['path']).chmod(0o444)
    shutil.copytree(API_BASE/'research-panel',API/'research-panel',copy_function=os.link,symlinks=True)
    shutil.copy2(API_BASE/'research-panel-assets.json',API/'research-panel-assets.json')
    assets=json.loads((API/'research-panel-assets.json').read_text())['files'];assert len(assets)==452
    for item in assets:assert sha((API/'research-panel'/item['path']).read_bytes())==item['sha256']
    manifest=json.loads((API_BASE/'release-manifest.json').read_text())
    manifest['candidate']=dict(manifest['candidate'],root=str(API),app_root=str(API/'app'),release_id=API.name)
    manifest['api_integration']=integration
    inventory=integ.inventory_tree(API/'app')
    manifest['application_inventory']=dict(entries=inventory,entry_count=len(inventory),aggregate_sha256=integ.inventory_digest(inventory))
    manifest['app_files']=inventory
    manifest['research_panel']=dict(manifest['research_panel'],root=str(API/'research-panel'),asset_manifest=str(API/'research-panel-assets.json'))
    manifest['external_module_contract']=dict(manifest['external_module_contract'],path=str(control/contract.name))
    write(API/'release-manifest.json',manifest)
    api_sha=sha((API/'release-manifest.json').read_bytes())
    api_verified=integ.verify_api_release_candidate(candidate_root=API,active_api_plist_path=PLIST,expected_manifest_sha256=api_sha)
    STAGE.mkdir();shutil.copytree(STAGE_BASE/'app',STAGE/'app',symlinks=True)
    baseline=json.loads((STAGE_BASE/'release-manifest.json').read_text())
    assert integ.inventory_tree(STAGE/'app')==baseline['application_inventory']['entries']
    relative='infrastructure/stage_quote_provider.py'
    shutil.copy2(HERE/'sources/stage'/relative,STAGE/'app'/relative)
    inventory=integ.inventory_tree(STAGE/'app')
    old={e['path']:e for e in baseline['application_inventory']['entries']}
    changed=[e['path'] for e in inventory if old.get(e['path'])!=e]
    assert changed==[relative],changed
    baseline['candidate']=dict(baseline['candidate'],root=str(STAGE),app_root=str(STAGE/'app'),release_id=STAGE.name)
    baseline['app_root']=str(STAGE/'app');baseline['release_id']=STAGE.name
    baseline['application_inventory']=dict(entries=inventory,entry_count=len(inventory),aggregate_sha256=integ.inventory_digest(inventory))
    baseline['app_files']=inventory
    write(STAGE/'release-manifest.json',baseline)
    result=dict(status='IMMUTABLE_NEW_CANDIDATES_PREPARED_NOT_ACTIVATED',api=dict(root=str(API),manifest_sha256=api_sha,inventory_count=len(manifest['app_files']),assets_count=452,assets_manifest_sha256=sha((API/'research-panel-assets.json').read_bytes()),verification=api_verified),stage=dict(root=str(STAGE),manifest_sha256=sha((STAGE/'release-manifest.json').read_bytes()),inventory_count=len(inventory),changed_paths=changed,all_non_delta_inventory_entries_preserved=True),service_actions=0,plist_writes=0,data_writes=0)
    write(HERE/'CANDIDATES.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
