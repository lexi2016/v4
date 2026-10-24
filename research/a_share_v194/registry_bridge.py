"""V194 scoped projection of the accepted official append-only registry bridge.
The root EXPERIMENT_REGISTRY is the only registry. Local JSON is a receipt.
"""
import sys,json,hashlib,os,importlib.util
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
HISTORY_ROOT=ROOT/'research/a_share_v194_full_history_20261024'
SUPPORTS_NEW_HISTORY_PROJECTION=True
class Helpers:
 FLAGS=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 @staticmethod
 def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
 @staticmethod
 def load(p):return json.loads(Path(p).read_text())
 @staticmethod
 def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
w=Helpers()

def projection_binding(c):
 """Bind receipt projections, while the official root registry stays unique."""
 b=c.get('registry_projection');assert isinstance(b,dict),'HISTORY_REGISTRY_PROJECTION_REQUIRED'
 root=Path(b.get('scope_root','')).resolve();assert root==HISTORY_ROOT.resolve(),'HISTORY_REGISTRY_SCOPE_ROOT_DRIFT'
 index=Path(b.get('index_path','')).resolve();receipts=Path(b.get('receipt_dir','')).resolve()
 assert index.is_relative_to(root) and index!=root,'HISTORY_REGISTRY_INDEX_OUTSIDE_SCOPE'
 assert receipts.is_relative_to(root) and receipts!=root,'HISTORY_REGISTRY_RECEIPTS_OUTSIDE_SCOPE'
 assert index.parent.is_dir() and receipts.is_dir(),'HISTORY_REGISTRY_PROJECTION_PARENT_MISSING'
 summaries=Path(b.get('summary_root','')).resolve();assert summaries==ROOT.resolve(),'OFFICIAL_ROOT_SUMMARY_ROOT_DRIFT'
 return index,receipts,summaries

def bound_official_adapter(c):
 b=c.get('runtime_registry_adapter');assert isinstance(b,dict),'OFFICIAL_ADAPTER_BINDING_REQUIRED'
 path=Path(b.get('path','')).resolve()
 expected=ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py'
 assert path==expected.resolve() and path.is_file(),'OFFICIAL_ADAPTER_PATH_DRIFT'
 assert w.sha(path)==b.get('sha256'),'OFFICIAL_ADAPTER_SHA_DRIFT'
 sys.path.insert(0,str(path.parent))
 spec=importlib.util.spec_from_file_location('v194_bound_official_registry_adapter',path)
 assert spec is not None and spec.loader is not None,'OFFICIAL_ADAPTER_IMPORT_UNAVAILABLE'
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 adapter=module.OfficialRegistryAdapter()
 assert adapter.registry_path.resolve()==(ROOT/'contracts/EXPERIMENT_REGISTRY.jsonl').resolve(),'OFFICIAL_REGISTRY_PATH_DRIFT'
 return adapter

def register(cp,event,stage,artifacts=(),metrics=None,decision='RUNNING'):
 cp=Path(cp).resolve();c=w.load(cp)
 ip,receipt_dir,summary_root=projection_binding(c)
 assert cp.is_relative_to(HISTORY_ROOT.resolve()/'contracts'),'HISTORY_CONTRACT_OUTSIDE_SCOPE'
 p=(receipt_dir/(c['execution_id']+'_'+stage+'_REGISTRY_RECEIPT.json')).resolve()
 assert p.parent==receipt_dir and not p.exists(),'HISTORY_REGISTRY_RECEIPT_PATH_INVALID_OR_EXISTS'
 for p,h in c.get('frozen_source_bindings',c.get('input_bindings',{})).items():assert w.sha(p)==h,'SOURCE_DRIFT:'+p
 ad=bound_official_adapter(c)
 spec=dict(schema_version='1.0',registry_event_id=c['execution_id']+'_'+stage,registration_mode='LIVE_EXECUTION',route_id=c['route_id'],experiment_id=c['route_id'],execution_id=c['execution_id'],track_id=c['track_id'],stage=stage,event_type=event,occurred_at=datetime.now(timezone.utc).isoformat(),occurred_at_reason='ACTUAL_LIVE_EVENT',contract_path=str(cp),input_sha256=c['input_sha256'],code_sha256=c['code_sha256'],config_sha256=w.sha(cp),input_identity=c.get('input_identity',c.get('input_bindings')),baseline_id=c['baseline_id'],one_variable=c['one_variable'],signal_date_range=c['signal_date_range'],target_date_range=c['target_date_range'],truth_access=c['truth_access'],sealed_status=c['sealed_status'],runtime=c['runtime'],device=c.get('device','MAC_LOCAL_CPU'),artifact_paths=[str(cp),*map(str,artifacts)],checkpoint_ref=str(artifacts[-1]) if artifacts and event=='CHECKPOINT' else None,deterministic_metrics={'truth_positive_denominator':None,'selection_slots':None,**(metrics or {})},decision=decision,stop_reason=decision if event=='TERMINAL' else 'NONE',evidence_level=c.get('evidence_level','ENGINEERING_CANARY_ONLY'),**w.FLAGS)
 with ad._locked():
  raw,es=ad._read_validated();same=[e for e in es if e['execution_id']==c['execution_id']]
  assert (not same if event=='RUN_STARTED' else len([e for e in same if e['event_type']=='RUN_STARTED'])==1 and not any(e['event_type']=='TERMINAL' for e in same)),'LIFECYCLE'
  ad._append_unlocked(raw,es,spec);raw,es=ad._read_validated();sc=[e for e in es if e['route_id']==c['route_id']]
  count=lambda a:dict(routes=len({x['route_id'] for x in a}),events=len(a),executions=len({x['execution_id'] for x in a}),corrections=sum(x['event_type']=='CORRECTION' for x in a))
  opened=lambda rows:sorted({e['execution_id'] for e in rows if e['event_type']=='RUN_STARTED'}-{e['execution_id'] for e in rows if e['event_type']=='TERMINAL'})
  receipt=dict(event_sha256=es[-1]['event_sha256'],registry_sha256=hashlib.sha256(raw).hexdigest(),registry_path=str(ad.registry_path),global_counts=count(es),scope_counts=count(sc),scope_open_executions=opened(sc),global_open_execution_count=len(opened(es)),global_open_execution_note='RAW_RUN_STARTED_MINUS_TERMINAL_NOT_CORRECTION_EFFECTIVE_AUDIT',scope_unregistered_route_count=0,scope_contract_only_count=0,global_unregistered_route_count=None,global_contract_only_count=None,count_gap_reason='GLOBAL_DISCOVERY_NOT_IN_SCOPE',external_registry_persistence='CANNOT_CONFIRM',stage=stage,decision=decision,**w.FLAGS)
  for n in ['CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md']:
   with (summary_root/n).open('a') as f:f.write('\n<!-- A_SHARE_V194_FULL_HISTORY_20261024 -->\n'+json.dumps(receipt,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
  j=w.load(ip) if ip.exists() else {'schema':'V194_REGISTRY_RECEIPT_PROJECTION_V1','authority':'ROOT_EXPERIMENT_REGISTRY_ONLY'};j[c['registry_summary_key']]=receipt;tmp=ip.with_suffix('.tmp')
  with tmp.open('w') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(tmp,ip)
 p=receipt_dir/(c['execution_id']+'_'+stage+'_REGISTRY_RECEIPT.json');w.save(p,receipt);return receipt
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('contract');p.add_argument('event');p.add_argument('stage');p.add_argument('--decision',default='RUNNING');p.add_argument('--artifact',action='append',default=[]);a=p.parse_args();print(json.dumps(register(a.contract,a.event,a.stage,a.artifact,decision=a.decision)))
