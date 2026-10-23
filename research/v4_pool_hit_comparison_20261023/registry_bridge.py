"""Thin scoped bridge to the existing official append-only registry adapter.
No independent registry; preserve old weekly authority key and all source bytes.
"""
import sys,json,hashlib,os
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
class Helpers:
 FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 @staticmethod
 def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
 @staticmethod
 def load(p):return json.loads(Path(p).read_text())
 @staticmethod
 def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
w=Helpers()

def register(cp,event,stage,artifacts=(),metrics=None,decision='RUNNING'):
 cp=Path(cp);c=w.load(cp)
 for p,h in c.get('frozen_source_bindings',c.get('input_bindings',{})).items():assert w.sha(p)==h,'SOURCE_DRIFT:'+p
 sys.path.insert(0,str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
 from registry_adapter import OfficialRegistryAdapter
 ad=OfficialRegistryAdapter()
 spec=dict(schema_version='1.0',registry_event_id=c['execution_id']+'_'+stage,registration_mode='LIVE_EXECUTION',route_id=c['route_id'],experiment_id=c['route_id'],execution_id=c['execution_id'],track_id=c['track_id'],stage=stage,event_type=event,occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='ACTUAL_LIVE_EVENT',contract_path=str(cp),input_sha256=c['input_sha256'],code_sha256=c['code_sha256'],config_sha256=w.sha(cp),input_identity=c.get('input_identity',c.get('input_bindings')),baseline_id=c['baseline_id'],one_variable=c['one_variable'],signal_date_range=c['signal_date_range'],target_date_range=c['target_date_range'],truth_access=c['truth_access'],sealed_status=c['sealed_status'],runtime=c['runtime'],device=c.get('device','MAC_LOCAL_CPU'),artifact_paths=[str(cp),*map(str,artifacts)],checkpoint_ref=str(artifacts[-1]) if artifacts and event=='CHECKPOINT' else None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision,stop_reason=decision if event=='TERMINAL' else 'NONE',evidence_level='OPENBOOK_DESCRIPTIVE_DIAGNOSTIC_ONLY',**w.FLAGS)
 with ad._locked():
  raw,es=ad._read_validated();same=[e for e in es if e['execution_id']==c['execution_id']]
  assert (not same if event=='RUN_STARTED' else len([e for e in same if e['event_type']=='RUN_STARTED'])==1 and not any(e['event_type']=='TERMINAL' for e in same)),'LIFECYCLE'
  ad._append_unlocked(raw,es,spec);raw,es=ad._read_validated();sc=[e for e in es if e['route_id']==c['route_id']]
  count=lambda a:dict(routes=len({x['route_id'] for x in a}),events=len(a),executions=len({x['execution_id'] for x in a}),corrections=sum(x['event_type']=='CORRECTION' for x in a))
  opened=lambda rows:sorted({e['execution_id'] for e in rows if e['event_type']=='RUN_STARTED'}-{e['execution_id'] for e in rows if e['event_type']=='TERMINAL'})
  receipt=dict(event_sha256=es[-1]['event_sha256'],registry_sha256=hashlib.sha256(raw).hexdigest(),registry_path=str(ad.registry_path),global_counts=count(es),scope_counts=count(sc),scope_open_executions=opened(sc),global_open_execution_count=len(opened(es)),global_open_execution_note='RAW_RUN_STARTED_MINUS_TERMINAL_NOT_CORRECTION_EFFECTIVE_AUDIT',scope_unregistered_route_count=0,scope_contract_only_count=0,global_unregistered_route_count=None,global_contract_only_count=None,count_gap_reason='GLOBAL_DISCOVERY_NOT_IN_SCOPE',external_registry_persistence='CANNOT_CONFIRM',stage=stage,decision=decision,**w.FLAGS)
  for n in ['CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md']:
   with (ROOT/n).open('a') as f:f.write('\n<!-- V4_POOL_HIT_COMPARISON_20261023 -->\n'+json.dumps(receipt,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  ip=ROOT/'contracts/ACTIVE_RESEARCH_INDEX.json';j=w.load(ip);j[c['registry_summary_key']]=receipt;tmp=ip.with_suffix('.v4_pool_hit.tmp')
  with tmp.open('w') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(tmp,ip)
 p=cp.parent/(stage+'_REGISTRY_RECEIPT.json');w.save(p,receipt);return receipt
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('contract');p.add_argument('event');p.add_argument('stage');p.add_argument('--decision',default='RUNNING');p.add_argument('--artifact',action='append',default=[]);a=p.parse_args();print(json.dumps(register(a.contract,a.event,a.stage,a.artifact,decision=a.decision)))
