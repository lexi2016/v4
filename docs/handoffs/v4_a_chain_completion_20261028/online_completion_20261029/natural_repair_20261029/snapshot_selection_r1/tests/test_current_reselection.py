from pathlib import Path
from copy import deepcopy
import hashlib,importlib.util,json,os,plistlib,shutil,subprocess,sys
import pytest
N=Path(__file__).resolve().parents[1];APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-stage/app');sys.path.insert(0,str(APP));import stage_center
spec=importlib.util.spec_from_file_location('stage_center.snapshot_selection',N/'sources/stage/stage_center/snapshot_selection.py');R=importlib.util.module_from_spec(spec);sys.modules[spec.name]=R;spec.loader.exec_module(R)
RESULT=json.loads((N/'evidence/REPRESENTATIVE_CANDIDATE_RESULT.json').read_bytes())['result']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def test_real_original_engine_result_and_existing_api_consumer_path(tmp_path):
 source=R.SupplementStore(N/'candidate_result').read('20261029','STAGE_0930_0935')
 assert source['selected_rows']==10 and source['rows'][0]['code']=='A.001318'
 assert source['algorithm_sha256']=='eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2'
 assert source['context_slot']=='1400' and source['context_rejections'][0]['rejected_slot']=='1500'
 assert R.clock(source['context_completion_finished_at'])<R.clock(source['captured_at'])<R.clock(source['scoring_evaluated_at'])
 assert all(r['news_quality_score'] is None and r['research_quality_score'] is None and r['research_bonus'] is None for r in source['rows'])
 assert source['original_stage_formal_selected_rows']==0 and source['natural_execution_verified'] is False
 code=r'''
from pathlib import Path
import sys,json,importlib.util
api=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-chart-20261029-r3-api/app');sys.path.insert(0,str(api));import stage_center
for name,rel in [('stage_center.snapshot_selection','stage_center/snapshot_selection.py'),('stage_center.consumer','stage_center/consumer.py')]:
 spec=importlib.util.spec_from_file_location(name,Path(sys.argv[1])/'sources/api'/rel);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
C=m.StageSelectionConsumer(sys.argv[2]);out=C.get('20261029','STAGE_0930_0935',markets=['A_SHARE']);assert out['markets']['A_SHARE']['rows']==[];assert len(out['snapshot_reselection']['markets']['A_SHARE']['rows'])==10
C._market_from_store_or_backfill=lambda *a,**k:{'market':'A_SHARE','status':'READY','selection_status':'READY','rows':[{'code':'A.301218'}],'selection_manifest_receipt_verified':True};m.read_stage_execution=lambda *a,**k:{'natural_verified':False}
assert C.get('20261029','STAGE_1300_1315',markets=['A_SHARE'])['snapshot_reselection']['status']=='FORMAL_RESULT_AVAILABLE'
print('API_SUPPLEMENTARY10_FORMAL_PREFERRED_PASS')
'''
 completed=subprocess.run([sys.executable,'-B','-c',code,str(N),str(N/'candidate_result')],capture_output=True,text=True);assert completed.returncode==0,completed.stdout+completed.stderr

def test_necessary_feature_missing_isolated_no_zero_imputation():
 from stage_center.snapshot_recovery import ObservationStore
 obs=ObservationStore(N/'candidate_result').read('20261029','STAGE_0930_0935');obs=deepcopy(obs);obs['rows']=obs['rows'][:2];obs['rows'][0]['turnover']=None
 ctx={'by_code':{},'slot':None,'source_evidence':[]}
 envelope,inputs,excluded,coverage=R.score(obs,ctx)
 assert len(inputs)==len(envelope['rows'])==len(excluded)==1
 assert inputs[0]['code']==obs['rows'][1]['code'] and inputs[0]['candidate']['score'] is None
 assert excluded[0]['reason']=='NECESSARY_QUOTE_FEATURE_MISSING_OR_INVALID:turnover'


def test_idempotent_observation_and_tamper_fail_closed(tmp_path):
 shutil.copytree(N/'candidate_result',tmp_path/'selection');root=tmp_path/'selection';store=R.SupplementStore(root);before={str(p):sha(p) for p in root.rglob('*.json')}
 from stage_center.snapshot_recovery import ObservationStore
 obs=ObservationStore(root).read('20261029','STAGE_0930_0935')
 # Same observation retries reuse its original scoring clock and sealed original context.
 assert store.publish(obs,{'unused':'not evaluated on retry'},R.now())['scoring_evaluated_at']==RESULT['scoring_evaluated_at']
 assert before=={str(p):sha(p) for p in root.rglob('*.json')}
 pointer=json.loads((root/store.pointer('20261029','STAGE_0930_0935')).read_bytes());path=root/store.prefix('20261029','STAGE_0930_0935',pointer['run'])/'context.json';path.write_bytes(path.read_bytes()+b' ')
 assert R.read_for_api(root,'20261029','STAGE_0930_0935')['status']=='CANNOT_CONFIRM'


def test_existing_observation_without_selection_continues_without_capture_and_formal_wins(tmp_path,monkeypatch):
 import stage_center.snapshot_recovery as Original
 source_root=N/'candidate_result';root=tmp_path/'selection';shutil.copytree(source_root/'snapshot_recovery',root/'snapshot_recovery')
 pointers=list((source_root/'snapshot_reselection/current').rglob('*.json'));pointer=json.loads(pointers[0].read_bytes());prefix=R.SupplementStore(source_root).prefix('20261029','STAGE_0930_0935',pointer['run']);ctx=json.loads((source_root/prefix/'context.json').read_bytes())
 calls=[]
 def skipped(*a,**k):calls.append('EXISTING_OBSERVATION_SKIP_NO_PROVIDER');return {'status':'NO_MISSING_OBSERVATION_TARGET','observations':[],'provider_invocations':0}
 monkeypatch.setattr(Original,'recover',skipped);monkeypatch.setattr(R,'context_for_snapshot',lambda *a:ctx)
 before={str(p):sha(p) for p in (root/'snapshot_recovery').rglob('*.json')}
 result=R.recover_and_select({'selection_root':str(root)},'20261029',stages=['STAGE_0930_0935'])
 selected=result['snapshot_reselection']['selections'][0]
 assert calls==[] and result['provider_invocations']==0 and selected['selected_rows']==10 and all(r['pool_score'] is None for r in selected['rows'])
 assert before=={str(p):sha(p) for p in (root/'snapshot_recovery').rglob('*.json')}
 monkeypatch.setattr(R,'selection_available',lambda *a:True)
 assert R.recover_and_select({'selection_root':str(root)},'20261029',stages=['STAGE_0930_0935'])['snapshot_reselection']['selections']==[]
 # This is the identical original verified-result predicate for A10 and READY_EMPTY.


def test_no_verified_context_uses_original_neutral_engine_without_fake_witness(monkeypatch):
 import stage_center.research_context as RC
 import infrastructure.research_store as RS
 from stage_center.snapshot_recovery import ObservationStore
 obs=ObservationStore(N/'candidate_result').read('20261029','STAGE_0930_0935')
 monkeypatch.setattr(RS.HourlyResearchStore,'list_slots',lambda *a,**k:[])
 def missing(*a,**k):raise RC.ResearchContextError('HOURLY_COMPLETION_WITNESS_MISSING')
 monkeypatch.setattr(RC,'load_research_context',missing)
 ctx=R.context_for_snapshot({'v4_research_data_root':'/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data'},obs)
 assert ctx['slot'] is None and ctx['by_code']=={} and 'NO_VERIFIED_RESEARCH_CONTEXT_AVAILABLE' in ctx['cannot_confirm']
 envelope,inputs,excluded,_=R.score(obs,ctx)
 assert len(envelope['rows'])==10 and not excluded and envelope['algorithm_sha256']=='eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2'
 assert all(r['news_quality_score'] is None and r['research_quality_score'] is None and r['pool_score'] is None for r in envelope['rows'])
 assert all(r['status']=='WATCH_ONLY' for r in envelope['rows'])

def test_verified_ready_empty_formal_result_skips_supplement_without_sdk(tmp_path,monkeypatch):
 from stage_center.selection import select_a_live_stage,SelectionStore
 import stage_center.snapshot_recovery as Original
 formal=select_a_live_stage([],'20261029','STAGE_0930_0935','a'*64,source_status='READY',requested_rows=0,source_evidence=('selection_contract=V3_TOP10_RECOMMENDATION',))
 assert formal['selection_status']=='READY_EMPTY';SelectionStore(tmp_path/'selection').publish(formal,market='A_SHARE')
 assert R.selection_available(tmp_path/'selection','20261029','STAGE_0930_0935')
 def forbidden(*a,**k):raise AssertionError('existing verified formal result must not start observation capture')
 monkeypatch.setattr(Original,'recover',forbidden)
 result=R.recover_and_select({'selection_root':str(tmp_path/'selection')},'20261029',stages=['STAGE_0930_0935'])
 assert result['snapshot_reselection']['selections']==[] and result['provider_invocations']==0
 assert SelectionStore(tmp_path/'selection').read_verified('20261029','STAGE_0930_0935','A_SHARE')['selection_status']=='READY_EMPTY'
