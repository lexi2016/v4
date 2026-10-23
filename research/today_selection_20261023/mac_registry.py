"""Explicit-profile registry writer; no market data reads or formula evaluation."""
import sys,json,os,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parent;ROOT=D.parent.parent
sys.path.insert(0,str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
from registry_adapter import OfficialRegistryAdapter
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def register(contract,event_type,stage,artifacts=(),metrics=None,decision=None):
 cp=Path(contract).resolve();c=json.loads(cp.read_text());ex=c['execution_id'];route=c['route_id'];assert event_type in ('RUN_STARTED','CHECKPOINT','TERMINAL')
 for field in ['track_id','baseline_id','device','runtime','code_sha256','input_sha256','input_identity','signal_date_range','target_date_range','truth_access','sealed_status','one_variable','evidence_level']:assert field in c,'MISSING_EXPLICIT_PROFILE:'+field
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
 spec=dict(schema_version='1.0',registry_event_id=ex+'_'+stage,registration_mode='LIVE_EXECUTION',route_id=route,experiment_id=route,execution_id=ex,track_id=c['track_id'],stage=stage,event_type=event_type,occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='ACTUAL_LIVE_EVENT',contract_path=str(cp),input_sha256=c['input_sha256'],code_sha256=c['code_sha256'],config_sha256=sha(cp),input_identity=c['input_identity'],baseline_id=c['baseline_id'],one_variable=c['one_variable'],signal_date_range=c['signal_date_range'],target_date_range=c['target_date_range'],truth_access=c['truth_access'],sealed_status=c['sealed_status'],runtime=c['runtime'],device=c['device'],artifact_paths=[str(cp),*[str(Path(x).resolve()) for x in artifacts]],checkpoint_ref=None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision or ('RUNNING' if event_type!='TERMINAL' else 'CANNOT_CONFIRM'),stop_reason='NONE' if event_type!='TERMINAL' else (decision or 'CANNOT_CONFIRM'),evidence_level=c['evidence_level'],price_basis=c.get('price_basis'),registrar_source_sha256=sha(__file__),research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 ad=OfficialRegistryAdapter()
 with ad._locked():
  raw,es=ad._read_validated();same=[e for e in es if e['execution_id']==ex]
  if event_type=='RUN_STARTED':assert not same,'DUPLICATE_EXECUTION_ID'
  else:assert len([e for e in same if e['event_type']=='RUN_STARTED'])==1 and not any(e['event_type']=='TERMINAL' for e in same),'INVALID_LIFECYCLE'
  ad._append_unlocked(raw,es,spec);raw,es=ad._read_validated();sc=[e for e in es if e['route_id']==route];count=lambda xs:[len({e['route_id'] for e in xs}),len(xs),len({e['execution_id'] for e in xs}),sum(e['event_type']=='CORRECTION' for e in xs)]
  snap=dict(execution_id=ex,route_id=route,event_type=event_type,stage=stage,event_sha256=es[-1]['event_sha256'],registry_path=str(ad.registry_path),registry_sha256=hashlib.sha256(raw).hexdigest(),global_route_event_execution_correction_counts=count(es),scope_route_event_execution_correction_counts=count(sc),scope_open_executions=sorted({e['execution_id'] for e in sc if e['event_type']=='RUN_STARTED'}-{e['execution_id'] for e in sc if e['event_type']=='TERMINAL'}),scope_unregistered_route_count=0,scope_contract_only_count=0,global_unregistered_route_count=None,global_contract_only_count=None,unknown_reason='NOT_A_GLOBAL_DISCOVERY_AUDIT',external_registry_persistence='CANNOT_CONFIRM',remote_status='NOT_SYNCED',contract_path=str(cp),contract_sha256=sha(cp),code_sha256=c['code_sha256'],input_sha256=c['input_sha256'],track_id=c['track_id'],baseline_id=c['baseline_id'],device=c['device'],price_basis=c.get('price_basis'))
  (D/'registry').mkdir(exist_ok=True);save(D/'registry'/(stage+'.json'),snap);note=dict(stage=stage,decision=spec['decision'],registry=snap,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
  for n in ['CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md']:
   with (ROOT/n).open('a') as f:f.write('\n<!-- TODAY_SELECTION_20261023 -->\n'+json.dumps(note,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  ip=ROOT/'contracts/ACTIVE_RESEARCH_INDEX.json';idx=json.loads(ip.read_text());idx.setdefault('today_selection_20261023',{})[stage]=note;tmp=ip.with_suffix('.today.tmp');save(tmp,idx);os.replace(tmp,ip)
 return snap
