"""Targeted P1 regression: live identity, not merely new files/READY rows."""
from pathlib import Path
from datetime import datetime,timezone
import copy,importlib.util
import pytest
p=Path(__file__).parents[1]/'docs/handoffs/a_daily_sop_closure_20261029/check_runtime.py'
spec=importlib.util.spec_from_file_location('activation_check',p);check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)

def state():
 e={'loaded':{},'forbidden_pre_control_pids':[100,200],'graph_config':{'sha256':'new graph'},'expected_graph_main':{'app_root':'/new/main'},'target_date':'20261029','main_launcher':'/new/main/launcher.sh','api_proof_module':{'path':'/new/api/domains/runtime_graph_evidence.py','sha256':'proof module'}}
 observed={}
 for role,pid in [('main',101),('api',201),('graph',None)]:
  root='/new/'+role;argv=['python','--config','/new/graph.json'] if role=='graph' else ['python',root+'/entry']
  e['loaded'][role]={'label':'v4.'+role,'argv':argv,'cwd':root,'process_executable':'/runtime/python','command_required':[role+'.module']}
  observed[role]={'loaded_argv':argv,'loaded_cwd':root,'pid':pid,'cwd':root,'command':'/runtime/python -m '+role+'.module'}
 proof={'schema_version':'v4.runtime_graph_authority.v1','config_sha256':'new graph','authority_identity':e['expected_graph_main'],'business_date':'20261029','runtime_binding':{'status':'VERIFIED','current_runtime_verified':True,'pid':101,'launcher':e['main_launcher']},'proof_runtime':{'pid':201,'module_file':e['api_proof_module']['path'],'module_sha256':'proof module'},'observed_at':datetime.now(timezone.utc).isoformat()}
 return e,observed,proof

def test_new_loaded_main_api_and_idle_graph_are_required_and_pass():
 e,o,p=state();r=check.verify_loaded(e,o,p);assert r['main']['pid']==101 and r['api']['pid']==201 and r['graph']['pid'] is None

@pytest.mark.parametrize('failure',['old_pid','old_root','old_loaded_argv','old_api_proof','old_graph_config'])
def test_old_running_identity_is_rejected_even_with_new_disk_templates(failure):
 e,o,p=state()
 if failure=='old_pid':o['api']['pid']=200
 if failure=='old_root':o['api']['cwd']='/old/api'
 if failure=='old_loaded_argv':o['main']['loaded_argv']=['python','/old/main/entry']
 if failure=='old_api_proof':p['proof_runtime']['module_file']='/old/api/domains/runtime_graph_evidence.py'
 if failure=='old_graph_config':p['config_sha256']='old graph'
 with pytest.raises(ValueError):check.verify_loaded(e,o,p)

@pytest.mark.parametrize('field',['generation_id','input_sha256','asof_date','verification_basis'])
def test_ready_getter_with_wrong_generation_snapshot_basis_or_date_rejected(field):
 expected=dict(generation_id='D29 generation',input_sha256='D29 input',artifact_sha256='D29 panel',asof_date=20261029,verification_basis='original reader hash',historical_PIT=False)
 payload=dict(status='READY',rows=[{'key':'value'}],identity=copy.deepcopy(expected),production_allowed=False,buy_gate_updated=False,orders_sent=False)
 assert check.verify_getter(payload,expected)==expected
 payload['identity'][field]='wrong'
 with pytest.raises(ValueError,match='IDENTITY_DRIFT'):check.verify_getter(payload,expected)
