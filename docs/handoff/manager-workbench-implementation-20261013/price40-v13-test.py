from pathlib import Path
import copy,importlib.util,json
import pytest
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('v13',H/'price40-prepare-v13.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

def test_fixed_parallel_scheduler_compatibility_rejects_all_other_drift():
 base=json.loads((H/'price40-v13-base-r2.json').read_text());c=base['scheduler_manifest_compatibility'];root=Path(c['root']);plist=Path(v.SCHED).read_bytes();manifest=Path(base['base']['scheduler']['manifest_path']).read_bytes();actual=v.inventory_tree(root)
 assert v.scheduler_inventory(root,plist,manifest,actual,c)==actual
 for bad in ['plist','source','prefix','root']:
  a=copy.deepcopy(actual);cc=copy.deepcopy(c);pp=plist;rr=root
  if bad=='plist':pp+=b' '
  elif bad=='source':next(x for x in a if x['path'].startswith('v3_shared_data/') and x['kind']=='file')['sha256']='a'*64
  elif bad=='prefix':cc['prefixes'].append('other')
  else:rr=root/'unapproved'
  with pytest.raises(ValueError):v.scheduler_inventory(rr,pp,manifest,a,cc)
 # No arbitrary non-directory source exception.
 a=copy.deepcopy(actual);next(x for x in a if x['path']=='v4/manager_workbench/config.py')['sha256']='b'*64
 with pytest.raises(ValueError,match='NON_COMPATIBLE'):v.scheduler_inventory(root,plist,manifest,a,c)

def test_exact_package_changes_only_rule_config_and_allowed_delta():
 out=H/'.tmp/price40-v13-r1';r=json.loads((out/'receipt.json').read_bytes());plan=json.loads((out/'operator-plan.json').read_bytes())
 assert set(r['scheduler_delta_paths'])=={'v4/manager_workbench/engines/oversold.py','v4/manager_workbench/engines/common.py','v4/manager_workbench/config.py'}
 assert set(r['canonical_sync_paths'])==v.SOURCES
 assert all(p.startswith('apps/web/dist/assets/managerSelection-') or p=='apps/web/dist/manager-selection/index.html' for p in r['frontend_assets'])
 e=next(e for e in plan['entries'] if e['kind']=='config');before=json.loads(Path(e['backup']).read_text());after=json.loads(Path(e['source']).read_text())
 assert before.pop('rules_version')=='POSITIVE_OPERATING_RESEARCH_V1';assert after.pop('rules_version')=='POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2';assert before==after
 assert before['capture_enabled'] is False and before['scheduled_lanes']==['US_MAPPING','OVERSOLD']
 v.validate(plan,'apply');assert r['api_non_delta_preserved'] and r['scheduler_non_delta_preserved']
 assert v.sha((out/'operator-plan.json').read_bytes())==r['plan_sha256']
