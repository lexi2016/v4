"""API-only guard counterexamples; no launchctl, formal writes or candidate build."""
import importlib.util,json
from pathlib import Path
import pytest
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('recommendation_package',H/'independent-recommendations-prepare-r1.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

def test_fixed_api_base_rejects_parallel_root_plist_and_manifest_changes():
 raw=p.API.read_bytes();active=p.generic.read_active_release(p.API);p.guard_base(active,raw)
 for key,value in [('app_root',str(H/'.tmp/other/app')),('release_manifest_sha256','0'*64)]:
  wrong={**active,key:value}
  with pytest.raises(ValueError,match='EXACT_API_ACTIVE_BASE_DRIFT'):p.guard_base(wrong,raw)
 with pytest.raises(ValueError,match='EXACT_API_ACTIVE_BASE_DRIFT'):p.guard_base(active,raw+b' ')

def test_target_guard_allows_exact_seven_sources_and_only_api_plist():
 for rel in p.SOURCES:assert p.target_root(dict(kind='canonical',target=str(p.CANONICAL/rel)))==p.CANONICAL
 assert p.target_root(dict(kind='plist',target=str(p.API)))==p.API.parent
 for kind,target in [('plist',p.operator.SCHED),('config',p.H/'manager-workbench-v7.json'),('canonical',p.CANONICAL/'v4/manager_workbench/engines/oversold.py'),('saved_state',p.H/'snapshot.json')]:
  with pytest.raises(ValueError,match='API_ONLY_TARGET_FORBIDDEN'):p.target_root(dict(kind=kind,target=str(target)))

def test_plan_rejects_scheduler_even_before_any_launch_or_write():
 plan=dict(schema_version='manager_workbench.independent_recommendations.api_only.v1',plists=[dict(role='scheduler',label='com.lexi.v35.scheduler',formal_path=str(p.operator.SCHED))])
 with pytest.raises(ValueError,match='API_ONLY_SERVICE_SCOPE_REQUIRED'):p.validate(plan,'apply')

def test_asset_closure_has_no_other_frontend_entry():
 payload=p.assets(H/'.tmp/independent-recommendations-web-build-r1')
 assert 'apps/web/dist/manager-selection/index.html' in payload
 assert all(rel=='apps/web/dist/manager-selection/index.html' or rel.startswith('apps/web/dist/assets/') for rel in payload)
 assert not any('dailyResearchCommand' in rel or 'main-' in rel for rel in payload)


def test_manifest_is_written_from_actual_candidate_inventory(tmp_path):
 candidate=tmp_path/'test-api';app=candidate/'app';app.mkdir(parents=True);(app/'source.py').write_text('fixed source')
 path=p.write_manifest(candidate,dict(base='fixed'))
 value=json.loads(path.read_text());assert value['application_inventory']['entries']==p.inventory_tree(app)
 assert value['application_inventory']['aggregate_sha256']==p.inventory_digest(p.inventory_tree(app))
 assert value['candidate']['app_root']==str(app) and value['api_integration']==dict(base='fixed')


def test_staged_cwd_pythonpath_and_import_search_root_are_candidate(tmp_path):
 import os,subprocess,sys,plistlib
 app=tmp_path/'candidate/app';app.mkdir(parents=True);(app/'identity_probe.py').write_text('VALUE="candidate"')
 old=dict(WorkingDirectory=str(p.BASE_ROOT),ProgramArguments=['env','PYTHONPATH='+str(p.BASE_ROOT/'upstreams')+':'+str(p.BASE_ROOT),'python','-m','identity_probe'],EnvironmentVariables={})
 staged=p.stage_plist(plistlib.dumps(old),app,app.parent/'release-manifest.json','a'*64)
 assert staged['WorkingDirectory']==str(app)
 path=next(x.split('=',1)[1] for x in staged['ProgramArguments'] if x.startswith('PYTHONPATH='))
 assert path==str(app/'upstreams')+':'+str(app) and str(p.BASE_ROOT) not in path
 result=subprocess.run([sys.executable,'-B','-c','import identity_probe; print(identity_probe.__file__)'],cwd=staged['WorkingDirectory'],env={**os.environ,'PYTHONPATH':path},capture_output=True,text=True)
 assert result.returncode==0 and result.stdout.strip()==str(app/'identity_probe.py')
 old['WorkingDirectory']=str(tmp_path/'other')
 with pytest.raises(ValueError,match='API_WORKING_DIRECTORY_PREIMAGE_DRIFT'):p.stage_plist(plistlib.dumps(old),app,app.parent/'release-manifest.json','a'*64)
