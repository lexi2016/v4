from pathlib import Path
import importlib.util,json
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('v12',H/'display-repair-prepare-v12.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

def test_manager_asset_closure_never_replaces_other_pages(tmp_path):
 (tmp_path/'manager-selection').mkdir();(tmp_path/'assets').mkdir()
 (tmp_path/'manager-selection/index.html').write_text('<script src="/assets/manager.js"></script>')
 (tmp_path/'assets/manager.js').write_text('import "./shared.js";')
 (tmp_path/'assets/shared.js').write_text('export const shared=1;')
 (tmp_path/'assets/unrelated-page.js').write_text('parallel page untouched')
 payload=v.manager_assets(tmp_path)
 assert set(payload)=={'apps/web/dist/manager-selection/index.html','apps/web/dist/assets/manager.js','apps/web/dist/assets/shared.js'}

def test_actual_package_contains_exact_delta_and_preserves_formal_config():
 d=H/'.tmp/display-repair-v12-r1';r=json.loads((d/'receipt.json').read_bytes());plan=json.loads((d/'operator-plan.json').read_bytes())
 assert set(r['scheduler_delta_paths'])=={'v4/manager_workbench/api.py','v4/manager_workbench/display_read.py'}
 assert set(r['canonical_sync_paths'])==v.SOURCES
 assert all(p.startswith('apps/web/dist/assets/managerSelection-') or p=='apps/web/dist/manager-selection/index.html' for p in r['frontend_assets'])
 config=next(e for e in plan['entries'] if e['kind']=='config');assert config['before_sha256']==config['after_sha256']
 v.validate(plan,'apply')
 assert r['api_non_delta_preserved'] and r['scheduler_non_delta_preserved']
 assert v.sha((d/'operator-plan.json').read_bytes())==r['plan_sha256']
