"""Final parameter and four-role delta checks only; no live actions."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import importlib.util,json,plistlib,sys
import pytest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_final_four_control',HERE/'four_role_control.py');C=importlib.util.module_from_spec(spec);sys.modules[spec.name]=C;spec.loader.exec_module(C)
PLAN=json.loads((HERE/'PLAN.json').read_bytes())

def test_exact_stage_delta_api_pointer_only_and_graph_history_preserved():
 p=PLAN;r=p['releases'][0];assert len(p['releases'])==1 and r['role']=='stage'
 assert set(r['delta'])=={'infrastructure/stage_quote_provider.py','stage_center_tick_config.json'}
 old_cfg=json.loads((Path(r['baseline_manifest']).parent/'app/stage_center_tick_config.json').read_bytes());new_cfg=json.loads((Path(r['candidate_app'])/'stage_center_tick_config.json').read_bytes())
 old_cfg['release_id']=r['release_id'];assert old_cfg==new_cfg
 api=C.row(p,'api');old=plistlib.loads(Path(api['before_file']).read_bytes());new=plistlib.loads(Path(api['after_file']).read_bytes());old['EnvironmentVariables']['V4_RUNTIME_GRAPH_CONFIG']=p['graph']['final'];assert old==new
 assert api['old_app_root']==api['new_app_root']==p['api_app_root'] and p['api_release_id']=='v4-a-share-empty-state-20261029-r1-api'
 baseline=json.loads(Path(p['graph']['baseline']).read_bytes());graph=json.loads(Path(p['graph']['candidate']).read_bytes())
 assert {k:v for k,v in baseline.items() if k not in ['entry_sources','stage_catalog_source']}=={k:v for k,v in graph.items() if k not in ['entry_sources','stage_catalog_source']}
 for k,v in baseline['entry_sources'].items():
  if not k.startswith('STAGE_'):assert graph['entry_sources'][k]==v
 history=json.loads(Path(p['graph']['binding_manifest']).read_bytes())['historical_evidence_only']
 assert history['manifest_sha256']==r['baseline_manifest_sha256'] and history['authorizes_current_producer'] is False and history['certifies_natural_pass'] is False


def test_fixed22_rendered_helper_excludes_main_and_keeps_supervisor_body():
 p=PLAN;table=C.recovery.fixed_cli_table(p)
 assert table.count('static char *const ')==22 and 'main_' not in table and 'com.lexi.v4.scheduler' not in table
 assert table in (HERE/'bounded_launchctl.c').read_text()
 previous=HERE.parents[1]/'control_r4/bounded_launchctl.c';current=(HERE/'bounded_launchctl.c').read_text();before=previous.read_text()
 assert current[current.index('static volatile sig_atomic_t'):]==before[before.index('static volatile sig_atomic_t'):]
 op='0'*32;identity={'pid':999999,'ps_sha256':'0'*64};h={'operation_id':op,'root_ack_dir':'/private/var/tmp/v4-a-chain-nextspawn-'+op,'expires_epoch':1,'reverse':False,'identities':{r:None for r in C.ROLES},'guardian':dict(identity,ready_sha256='0'*64)}
 shell=C.recovery.root_helper(p,h,identity,'0'*64,HERE)
 assert 'com.lexi.v4.scheduler' not in shell and '/main.intent' not in shell
 assert all('bounded_cli '+r+'_arm_debug ' in shell for r in C.ROLES)
 assert 'CLI_OUTCOME_UNKNOWN_NO_AUTOMATIC_RESTORE' in shell


def test_main_readonly_identity_drift_stops_without_lifecycle(monkeypatch):
 ops=C.Live(PLAN);commands=[]
 monkeypatch.setattr(ops,'identity',lambda pid:None)
 monkeypatch.setattr(ops,'service_label',lambda label:commands.append(label))
 with pytest.raises(C.Stop,match='READONLY_MAIN_IDENTITY_CHANGED'):ops.main_unchanged()
 assert commands==[]
 for role in ['main','unknown']:
  with pytest.raises(C.Stop):C.Recipe({}, {}, None, {}, None).step(role)


def synthetic_handoff(at):
 p=PLAN;epoch=datetime.fromisoformat('2026-10-29T'+at+'+08:00').timestamp();api={'pid':2001,'ps_text':'fixture API\n','ps_sha256':C.sha(b'fixture API\n')}
 h={'operation_id':'0'*32,'plan_sha256':C.sha(C.canonical(p)),'reverse':False,'root_ack_dir':'/private/var/tmp/v4-a-chain-nextspawn-'+'0'*32,'observed_epoch':epoch,'expires_epoch':epoch+60,'main_readonly_identity':p['main_readonly']['identity'],'identities':{r:(api if r=='api' else None) for r in C.ROLES},'role_observations':{r:{} for r in C.ROLES},'data_pins':['presence_only_fixture'],'data_stats':['presence_only_fixture']}
 for key in ('legitimate_daily_producer_complete','all_daily_descendants_absent','no_active_dependent_api_query','api_brief_new_connection_gap_coordinated','pdf_admission_disabled_by_existing_time_window','no_live_pdf_child','no_parallel_lifecycle_owner','all_current_main_children_and_jobs_finished','all_accepted_manual_jobs_finished','scheduler_queue_empty_or_original_observations_durable','all_auxiliary_jobs_naturally_finished'):h[key]=True
 return h,epoch

def test_main_calendar_margin_and_fresh_readonly_identity_still_required(monkeypatch):
 h,epoch=synthetic_handoff('13:21:00');monkeypatch.setattr(C.time,'time',lambda:epoch)
 assert C.handoff(PLAN,h) is True
 bad=deepcopy(h);bad['main_readonly_identity']=None
 with pytest.raises(C.Stop,match='FRESH_MAIN_READONLY_IDENTITY_REQUIRED'):C.handoff(PLAN,bad)
 h,epoch=synthetic_handoff('13:04:00');monkeypatch.setattr(C.time,'time',lambda:epoch)
 with pytest.raises(C.Stop,match='MAIN_WINDOW_CONFLICT'):C.handoff(PLAN,h)
