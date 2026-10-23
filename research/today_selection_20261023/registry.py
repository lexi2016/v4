import sys,json,hashlib,os
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂');D=ROOT/'research/today_selection_20261023'
sys.path.insert(0,str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
from registry_adapter import OfficialRegistryAdapter
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def event(contract,event_type,stage,artifacts=(),metrics=None,decision=None):
 cp=Path(contract);c=json.loads(cp.read_text());ex=c['execution_id'];ad=OfficialRegistryAdapter();out=D/'registry';out.mkdir(exist_ok=True)
 spec=dict(schema_version='1.0',registry_event_id=ex+'_'+stage,registration_mode='LIVE_EXECUTION',route_id='A_SHARE_TODAY_SELECTION_20261023',experiment_id='A_SHARE_TODAY_SELECTION_20261023',execution_id=ex,track_id='A_SHARE_WINDOWS_ORIGINAL_FORMULA_DAILY_RESEARCH',stage=stage,event_type=event_type,occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='ACTUAL_LIVE_EVENT',contract_path=str(cp),input_sha256=sha(cp),code_sha256=c.get('code_sha256'),config_sha256=sha(cp),input_identity={'contract_sha256':sha(cp),'null_reasons':{'target_date_range':'NO_FUTURE_LABELS','checkpoint_ref':'NO_MODEL','global_unregistered_routes':'NOT_A_GLOBAL_AUDIT','global_contract_only':'NOT_A_GLOBAL_AUDIT'}},baseline_id='WINDOWS_INSTALLED_192_XG_QFQ1',one_variable='signal_date_20261022_for_20261023_all_A_research_selection',signal_date_range={'start':'2026-10-22','end':'2026-10-22'},target_date_range=None,truth_access='NOT_READ',sealed_status='NOT_ACCESSED',runtime={'owner':'/root/today_selection_writer','workers':1,'windows_writes':0},device='MAC_CONTROL_WINDOWS_INSTALLED_TDX_CPU',artifact_path=[str(cp),*[str(x) for x in artifacts]],artifact_paths=[str(cp),*[str(x) for x in artifacts]],checkpoint_ref=None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision or ('RUNNING' if event_type!='TERMINAL' else 'CANNOT_CONFIRM'),stop_reason='NONE' if event_type!='TERMINAL' else (decision or 'CANNOT_CONFIRM'),evidence_level='RESEARCH_ONLY_DAILY_SELECTION_NO_OUTCOME_EVALUATION',research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 with ad._locked():
  raw,es=ad._read_validated();same=[e for e in es if e['execution_id']==ex]
  if event_type=='RUN_STARTED':assert not same
  else:assert len([e for e in same if e['event_type']=='RUN_STARTED'])==1 and not any(e['event_type']=='TERMINAL' for e in same)
  ad._append_unlocked(raw,es,spec);raw,es=ad._read_validated();e=es[-1];sc=[x for x in es if x['route_id']==spec['route_id']]
  count=lambda xs:[len({x['route_id'] for x in xs}),len(xs),len({x['execution_id'] for x in xs}),sum(x['event_type']=='CORRECTION' for x in xs)]
  snap=dict(execution_id=ex,event_type=event_type,stage=stage,event_sha256=e['event_sha256'],registry_path=str(ad.registry_path),registry_sha256=hashlib.sha256(raw).hexdigest(),global_route_event_execution_correction_counts=count(es),scope_route_event_execution_correction_counts=count(sc),scope_open_executions=sorted({x['execution_id'] for x in sc if x['event_type']=='RUN_STARTED'}-{x['execution_id'] for x in sc if x['event_type']=='TERMINAL'}),scope_unregistered_route_count=0,scope_contract_only_count=0,global_unregistered_route_count=None,global_contract_only_count=None,unknown_reason='NOT_A_GLOBAL_DISCOVERY_AUDIT',external_registry_persistence='CANNOT_CONFIRM',remote_status='NOT_SYNCED',contract_path=str(cp),contract_sha256=sha(cp),code_sha256=c.get('code_sha256'))
  save(out/(stage+'.json'),snap)
  note=dict(stage=stage,decision=spec['decision'],registry=snap,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
  for n in ('CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md'):
   with (ROOT/n).open('a') as f:f.write('\n<!-- TODAY_SELECTION_20261023 -->\n'+json.dumps(note,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  ip=ROOT/'contracts/ACTIVE_RESEARCH_INDEX.json';idx=json.loads(ip.read_text());idx.setdefault('today_selection_20261023',{})[stage]=note;tmp=ip.with_suffix('.today.tmp');save(tmp,idx);os.replace(tmp,ip)
 return snap
if __name__=='__main__':
 cp,typ,stage=sys.argv[1:4];print(json.dumps(event(cp,typ,stage,sys.argv[4:]),ensure_ascii=False))
