"""Supersede only unactivated r1 Stage metadata without changing that release."""
from pathlib import Path
import json,hashlib,shutil,importlib.util,sys
HERE=Path(__file__).resolve().parent
RELEASES=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases')
old=RELEASES/'a-chain-completion-20261029-r1-stage'
new=RELEASES/'a-chain-completion-20261029-r2-stage'
assert not new.exists(),'Never overwrite an existing candidate'
expected='d19ee3eec2d81006e4d33bbbbc5d6bd85f58316c2d4170f94ee397b8c10d8451'
assert hashlib.sha256((old/'release-manifest.json').read_bytes()).hexdigest()==expected
new.mkdir();shutil.copytree(old/'app',new/'app',symlinks=True)
path=new/'app/stage_center_tick_config.json';config=json.loads(path.read_text())
assert config['research_owner_binding']['manifest_sha256']=='0bfa9101422d165a4a8161028dc2e3acc9082222d1c09c19075edf76dbb460d7'
config['release_id']=new.name;path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
api=RELEASES/'daily-r19-profile-20261029-r1-api/app';sys.path.insert(0,str(api))
spec=importlib.util.spec_from_file_location('a_chain_stage_seal',api/'ops/api_release_integration.py');integ=importlib.util.module_from_spec(spec);spec.loader.exec_module(integ)
manifest=json.loads((old/'release-manifest.json').read_text())
manifest['candidate']=dict(manifest['candidate'],root=str(new),app_root=str(new/'app'),release_id=new.name)
manifest['app_root']=str(new/'app');manifest['release_id']=new.name
inventory=integ.inventory_tree(new/'app')
manifest['application_inventory']=dict(entries=inventory,entry_count=len(inventory),aggregate_sha256=integ.inventory_digest(inventory));manifest['app_files']=inventory
(new/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
record=json.loads((HERE/'CANDIDATES.json').read_text())
record['superseded_stage_r1']=dict(record['stage'],reason='Unactivated inherited legacy config.release_id; r1 bytes retained and never overwritten')
record['stage']=dict(root=str(new),manifest_sha256=hashlib.sha256((new/'release-manifest.json').read_bytes()).hexdigest(),inventory_count=len(inventory),changed_paths=['infrastructure/stage_quote_provider.py','stage_center_tick_config.json'],config_release_id=config['release_id'],config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),research_owner_binding=config['research_owner_binding'],config_other_fields_unchanged=True)
(HERE/'CANDIDATES.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record['stage'],indent=2))
