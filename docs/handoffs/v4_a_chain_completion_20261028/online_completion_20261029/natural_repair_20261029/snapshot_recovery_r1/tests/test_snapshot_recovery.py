from pathlib import Path
from copy import deepcopy
from datetime import datetime,timedelta
from types import SimpleNamespace
import hashlib,importlib.util,json,sys
import pytest
HERE=Path(__file__).resolve().parents[1]
APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-native-window-20261029-r1-stage/app')
sys.path.insert(0,str(APP))
spec=importlib.util.spec_from_file_location('recovery_candidate',HERE/'sources/stage/stage_center/snapshot_recovery.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
CAPTURE=HERE/'current_capture/snapshot.json';RECEIPT=HERE/'current_capture/CAPTURE_RECEIPT.json'
DATE='20261029';STAGES=['STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945']
FLAGS={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def test_existing_manual56_becomes_four_isolated_observations_without_requery(tmp_path):
 assert sha(CAPTURE)=='cd38accd9ed26d499e667d3bf2d4dec592de7ec67cd790f1a175ff8bfdbf2d31'
 config=json.loads((APP/'stage_center_tick_config.json').read_bytes());config['selection_root']=str(tmp_path/'selection')
 originals=[Path(config['receipt_root'])/DATE/s/'receipt.json' for s in STAGES];pins={str(p):sha(p) for p in originals}
 result=R.recover(config,DATE,stages=STAGES,input_path=CAPTURE,receipt_path=RECEIPT,manual=True)
 assert result['provider_invocations']==0 and len(result['observations'])==4 and result['formal_selected_rows']==0
 for item in result['observations']:
  assert item['mode']==R.MODE and item['observed_rows']==56 and item['requested_rows']==58
  assert len(item['rejected_rows'])==2 and set(item['missing_symbols'])=={'A.920249','A.920455'}
  assert item['after_original_cutoff'] is True and item['original_stage_cutoff_safe'] is False and item['natural_execution_verified'] is False
  assert item['captured_at']=='2026-10-29T15:19:00.106096+08:00'
  assert all(r['score'] is None and r['research_quality_score'] is None and r['action_level']=='WATCH_ONLY' for r in item['rows'])
  assert all(r['source_update_time']=='2026-10-29T15:00:00+08:00' for r in item['rows'])
 assert pins=={str(p):sha(p) for p in originals}
 assert not (tmp_path/'selection/selection_latest.json').exists()
 before={str(p):sha(p) for p in (tmp_path/'selection').rglob('*.json')}
 R.recover(config,DATE,stages=STAGES,input_path=CAPTURE,receipt_path=RECEIPT,manual=True)
 assert before=={str(p):sha(p) for p in (tmp_path/'selection').rglob('*.json')}
 observed=R.read_for_api(config['selection_root'],DATE,STAGES[0]);assert len(observed['markets']['A_SHARE']['rows'])==56
 pointer=Path(config['selection_root'])/R.ObservationStore(config['selection_root']).pointer(DATE,STAGES[0]);index=json.loads(pointer.read_bytes());artifact=Path(config['selection_root'])/index['artifact_relative'];artifact.write_bytes(artifact.read_bytes()+b' ')
 assert R.read_for_api(config['selection_root'],DATE,STAGES[0])['status']=='CANNOT_CONFIRM'

@pytest.mark.parametrize('fault',['future','zero','nan','wrongmarket','unknowncode'])
def test_invalid_rows_quarantine_individually_preserving_valid_and_times(fault):
 snap=json.loads(CAPTURE.read_bytes());codes=['A.002286','A.600252'];good=deepcopy(snap['rows'][0]);bad=deepcopy(snap['rows'][1]);bad['symbol']='A.600252'
 if fault=='future':bad['source_update_time']='2026-10-29 15:30:00'
 if fault=='zero':bad['last_price']=0
 if fault=='nan':bad['last_price']=float('nan')
 if fault=='wrongmarket':bad['symbol']='HK.02656'
 if fault=='unknowncode':bad['symbol']='A.999999'
 snap['rows']=[good,bad];rows,rejected,_,_=R.normalized_snapshot(snap,codes,R.clock('2026-10-29T15:20:00+08:00'))
 assert len(rows)==1 and rows[0]['code']=='A.002286' and len(rejected)==1
 assert rows[0]['source_update_time']=='2026-10-29T15:00:00+08:00'

def fake_config(tmp_path):
 config={'selection_root':str(tmp_path/'selection'),'receipt_root':str(tmp_path/'receipts'),'candidate_acquisition_root':str(tmp_path/'candidate'),'safety':FLAGS}
 for stage in STAGES[:2]:
  p=Path(config['receipt_root'])/DATE/stage/'receipt.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'trade_date':DATE,'stage_id':stage,'markets':{'A_SHARE':{'status':'CANNOT_CONFIRM','selected_rows':0,'cannot_confirm':['A_NATIVE_0925_SNAPSHOT_UNAVAILABLE' if stage==STAGES[0] else 'RESEARCH_SOURCE_WITNESS_INVALID:HOURLY_COMPLETION_WITNESS_MISSING']}},**FLAGS}))
 return config

def test_later_natural_stage_batches_old_empty_stage_once_no_timer_or_fail_write(tmp_path,monkeypatch):
 config=fake_config(tmp_path);candidate=SimpleNamespace(codes=('A.002286','A.600252','A.920249'),current_sha256='a'*64,run_id='candidate-original')
 import stage_center.candidate_input as CI
 monkeypatch.setattr(CI,'read_candidate_input',lambda *a: candidate)
 wall=R.clock('2026-10-29T09:35:06+08:00');calls=[]
 class Provider:
  def snapshot(self,codes,**kw):
   calls.append(tuple(codes));snap=deepcopy(json.loads(CAPTURE.read_bytes()));snap['capture_started_at']=snap['captured_at']=wall.isoformat();snap['rows']=[deepcopy(snap['rows'][0]),deepcopy(next(r for r in snap['rows'] if r['symbol']=='A.600252'))]
   for r in snap['rows']:r['source_update_time']='2026-10-29 09:30:00'
   return snap
 original={str(p):sha(p) for p in Path(config['receipt_root']).rglob('*.json')}
 result=R.after_natural_nodes(config,DATE,[{'stage_id':STAGES[1],'node_id':STAGES[1]}],provider=Provider(),wall=lambda:wall)
 assert result['provider_invocations']==1 and len(result['observations'])==2 and calls==[('A.002286','A.600252')]
 again=R.after_natural_nodes(config,DATE,[{'stage_id':STAGES[1],'node_id':STAGES[1]}],provider=Provider(),wall=lambda:wall)
 assert again['provider_invocations']==0 and len(calls)==1
 prep=R.after_natural_nodes(config,DATE,[{'node_id':'PRECAPTURE_A_0925'}],provider=Provider(),wall=lambda:wall)
 assert prep['provider_invocations']==0
 assert original=={str(p):sha(p) for p in Path(config['receipt_root']).rglob('*.json')}


def test_duplicate_conflict_and_boolean_price_are_quarantined():
 snap=json.loads(CAPTURE.read_bytes());a=deepcopy(snap['rows'][0]);b=deepcopy(a);b['last_price']+=1
 snap['rows']=[a,b]
 rows,rejected,_,_=R.normalized_snapshot(snap,[a['symbol']],R.now())
 assert not rows and rejected[0]['reason']=='DUPLICATE_QUOTE_IDENTITY'
 snap['rows']=[a];a['last_price']=True
 assert not R.normalized_snapshot(snap,[a['symbol']],R.now())[0]

def test_api_consumer_preserves_original_failure_and_prefers_formal_result(tmp_path):
 import subprocess
 config=json.loads((APP/'stage_center_tick_config.json').read_bytes());config['selection_root']=str(tmp_path/'selection')
 R.recover(config,DATE,stages=STAGES,input_path=CAPTURE,receipt_path=RECEIPT,manual=True)
 code=r"""
import sys,json,importlib.util
from pathlib import Path
api=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-daily-numeric283-20261029-r2-api/app')
sys.path.insert(0,str(api))
import stage_center
for name,path in [('stage_center.snapshot_recovery',Path(sys.argv[1])/'sources/api/stage_center/snapshot_recovery.py'),('stage_center.consumer',Path(sys.argv[1])/'sources/api/stage_center/consumer.py')]:
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
C=m.StageSelectionConsumer(sys.argv[2],execution_receipt_root=sys.argv[3])
original=C.get('20261029','STAGE_0930_0935',markets=['A_SHARE'])
assert original['markets']['A_SHARE']['rows']==[]
assert len(original['snapshot_recovery']['markets']['A_SHARE']['rows'])==56
assert original['execution_evidence']['natural_verified'] is False
formal={'market':'A_SHARE','status':'READY','selection_status':'READY','rows':[{'code':'SZ.301218'}],'selection_manifest_receipt_verified':True}
C._market_from_store_or_backfill=lambda *a,**k:dict(formal)
m.read_stage_execution=lambda *a,**k:{'natural_verified':False}
result=C.get('20261029','STAGE_1300_1315',markets=['A_SHARE'])
assert result['markets']['A_SHARE']['rows']==formal['rows']
assert result['snapshot_recovery']['status']=='FORMAL_RESULT_AVAILABLE'
assert result['snapshot_recovery']['markets']=={}
print('API_CONSUMER_PARALLEL56_FORMAL_PREFERRED_PASS')
"""
 result=subprocess.run([sys.executable,'-B','-c',code,str(HERE),config['selection_root'],config['receipt_root']],capture_output=True,text=True)
 assert result.returncode==0,result.stdout+result.stderr


def test_221_pool_complete_batches_preserve_each_capture_clock(tmp_path,monkeypatch):
 config=fake_config(tmp_path);codes=tuple(f'A.{600000+i}' for i in range(221))
 import stage_center.candidate_input as CI
 monkeypatch.setattr(CI,'read_candidate_input',lambda *a:SimpleNamespace(codes=codes,current_sha256='b'*64,run_id='pool221'))
 base=R.clock('2026-10-29T09:35:06+08:00');calls=[]
 class Provider:
  def snapshot(self,chunk,**kw):
   calls.append(tuple(chunk));t=base+timedelta(seconds=len(calls))
   return {'schema_version':'v3_5.read_only_quote_batch.v1','source':'FUTU_OPEND_READ_ONLY_SNAPSHOT','trade_date':DATE,'stage_id':R.MODE,'capture_started_at':t.isoformat(),'captured_at':t.isoformat(),'rows':[{'symbol':c,'last_price':5,'source_update_time':'2026-10-29 09:30:00'} for c in chunk],**FLAGS}
 result=R.recover(config,DATE,stages=STAGES[:2],provider=Provider(),wall=lambda:base+timedelta(seconds=3))
 assert list(map(len,calls))==[220,1] and result['provider_invocations']==2
 assert len(result['observations'])==2
 for a in result['observations']:
  assert a['observed_rows']==221 and [r['code'] for r in a['rows']]==list(codes)
  assert a['rows'][0]['captured_at']==(base+timedelta(seconds=1)).isoformat()
  assert a['rows'][-1]['captured_at']==(base+timedelta(seconds=2)).isoformat()
 assert len(list((Path(config['selection_root'])/'snapshot_recovery/captures').glob('*.json')))==1
