"""Scope projection only; append/validation/locking use the existing official adapter."""
import json, hashlib, importlib.util, sys, os
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
OUT=ROOT/'research/a_share_v4_second_selection_top100_20261025'
AD=ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py'
FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def register(cp,event,stage,artifacts=(),metrics=None,decision='RUNNING'):
 cp=Path(cp); c=json.loads(cp.read_text());sys.path.insert(0,str(AD.parent))
 spec=importlib.util.spec_from_file_location('official_adapter',AD);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);ad=m.OfficialRegistryAdapter()
 e=dict(schema_version='1.0',registry_event_id=c['execution_id']+'_'+stage,registration_mode='LIVE_EXECUTION',route_id=c['route_id'],experiment_id=c['route_id'],execution_id=c['execution_id'],track_id='A_SHARE_SAVED_SECOND_SELECTION_DESCRIPTIVE',stage=stage,event_type=event,occurred_at=datetime.now(timezone.utc).isoformat(),contract_path=str(cp),input_sha256=c.get('input_sha256'),input_sha256_reason=c.get('input_sha256_reason'),code_sha256=c.get('code_sha256'),config_sha256=sha(cp),baseline_id='SAVED_ACTUAL_V4_SELECTED_LISTS',one_variable='NONE_DESCRIPTIVE_AUDIT',signal_date_range=c.get('signal_date_range'),target_date_range=c.get('signal_date_range'),truth_access=c.get('truth_access','NOT_READ'),sealed_status='NO_NEW_SEALED_DATA_DESCRIPTIVE_ONLY',runtime={'python':sys.executable},device='MAC_LOCAL_CPU',artifact_paths=[str(cp),*map(str,artifacts)],checkpoint_ref=str(artifacts[-1]) if artifacts and event=='CHECKPOINT' else None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision,stop_reason=decision if event=='TERMINAL' else 'NONE',evidence_level='DIRECTION_ONLY',**FLAGS)
 with ad._locked():
  raw,es=ad._read_validated();same=[x for x in es if x['execution_id']==c['execution_id']]
  assert not same if event=='RUN_STARTED' else any(x['event_type']=='RUN_STARTED' for x in same) and not any(x['event_type']=='TERMINAL' for x in same)
  ad._append_unlocked(raw,es,e);raw,es=ad._read_validated();scope=[x for x in es if x['route_id']==c['route_id']]
  def counts(a):return dict(routes=len({x['route_id'] for x in a}),events=len(a),executions=len({x['execution_id'] for x in a}),corrections=sum(x['event_type']=='CORRECTION' for x in a))
  receipt=dict(schema='SECOND_SELECTION_REGISTRY_RECEIPT_V1',route_id=c['route_id'],execution_id=c['execution_id'],event_type=event,stage=stage,event_sha256=es[-1]['event_sha256'],registry_path=str(ad.registry_path),registry_sha256=hashlib.sha256(raw).hexdigest(),global_counts=counts(es),scope_counts=counts(scope),global_unregistered_route_count=None,global_contract_only_count=None,count_gap_reason='GLOBAL_INVENTORY_OUTSIDE_SCOPE',scope_unregistered_route_count=0,scope_contract_only_count=0,external_persistence='CANNOT_CONFIRM',decision=decision,**FLAGS)
  for n in ['CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md']:
   with (ROOT/n).open('a') as f:f.write('\n<!-- A_SHARE_V4_SECOND_SELECTION_TOP100_20261025 -->\n'+json.dumps(receipt,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  save(OUT/'INDEX.json',receipt)
 save(OUT/'receipts'/f"{c['execution_id']}_{stage}.json",receipt);return receipt
if __name__=='__main__':
 print(json.dumps(register(*sys.argv[1:4]),ensure_ascii=False))
