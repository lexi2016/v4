"""Re-screen the immutable 84eaf input snapshot, saving a new isolated two-lane run.
No upstream reads, transport, model, quota or formal-state writes.
"""
from pathlib import Path
import argparse,collections,copy,hashlib,importlib.util,json,sys
HERE=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/84eafbbb71ba4767a591d1a4286fe061.json')
OLD_SHA='ea5f7217ecd37824b467ff38a82ea88686d82827e3b3e18935e426aab53e10cf'
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--readback-only',action='store_true');a=p.parse_args();out=a.output.resolve()
 if (out.exists() and not a.readback_only) or not out.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('NEW_ISOLATED_OUTPUT_REQUIRED')
 spec=importlib.util.spec_from_file_location('accepted_calendar',HERE/'recover_cached_full_date.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.install_runtime()
 from v4.manager_workbench.contracts import PlanSnapshot,Lane,digest
 from v4.manager_workbench.config import WorkbenchConfig
 from v4.manager_workbench.service import create_service
 from v4.manager_workbench import engines
 from v4.manager_workbench.inputs.validation import batch
 from v4.manager_workbench.api import create_router
 from v4.manager_workbench.engines.oversold import PRICE40_RULES_VERSION
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 raw=OLD.read_bytes()
 if sha(raw)!=OLD_SHA:raise ValueError('OLD_SNAPSHOT_DRIFT')
 old=PlanSnapshot.model_validate(json.loads(raw));inputsha=old.changes['input_snapshot_sha256'];source=OLD.parent.parent/'input_snapshots'/f'{inputsha}.json';material=json.loads(source.read_bytes())
 if digest(material)!=inputsha:raise ValueError('FROZEN_INPUT_SHA_MISMATCH')
 wanted={Lane.US_MAPPING.value,Lane.OVERSOLD.value};saved={b['lane']:b for b in material['batches'] if b['lane'] in wanted}
 if set(saved)!=wanted:raise ValueError('FROZEN_TWO_LANES_MISSING')
 records_sha={lane:digest(b['records']) for lane,b in saved.items()}
 class Frozen:
  def prepare_context(self,context):
   context=context.model_copy(deep=True);context.source_sessions=copy.deepcopy(material['context']['source_sessions']);return context
  def load(self,lane,context):
   if lane.value not in saved:raise ValueError('LANE_NOT_REQUESTED')
   b=saved[lane.value]
   from v4.manager_workbench.contracts import Coverage
   return batch(context,lane,copy.deepcopy(b['records']),copy.deepcopy(b['evidence_refs']),b['scope_description'],Coverage.model_validate(b['coverage']),b['gaps'],b['universe_ref'])
 cfgraw=json.loads(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json').read_text());cfgraw.update(state_root=str(out/'derived'),rules_version=PRICE40_RULES_VERSION,capture_enabled=False,capture_lease_token=None)
 cfg=WorkbenchConfig.model_validate(cfgraw);cfgpath=out/'config.json'
 if not a.readback_only:
  out.mkdir(parents=True);cfgpath.write_text(cfg.model_dump_json(indent=2)+'\n')
 elif json.loads(cfgpath.read_text())!=cfg.model_dump(mode='json'):raise ValueError('REPLAY_CONFIG_DRIFT')
 service=create_service(cfg,Frozen(),engines,None);app=FastAPI();app.include_router(create_router(service))
 scope=copy.deepcopy(material['context']['scope_refs']);scope.pop('mwb_run_id',None);scope.pop('run_id',None);scope['frozen_material_replay']=dict(original_run_id=old.run_id,input_snapshot_sha256=inputsha,original_cutoff=material['context']['cutoff'],authority='EXACT_SAVED_INPUTS_NO_NEW_FACTS')
 try:
  if a.readback_only:
   attempts=list((out/'derived/manager_workbench/attempts').glob('*.json'))
   if len(attempts)!=1:raise ValueError('EXACT_SINGLE_SAVED_ATTEMPT_REQUIRED')
   job=service.jobs.get(json.loads(attempts[0].read_text())['job_id'])
  else:job=service.submit('20261013','RETROSPECTIVE',lanes=[Lane.US_MAPPING,Lane.OVERSOLD],scope_refs=scope)
 finally:service.stop()
 job=service.jobs.get(job.job_id);plan=service.store.get_plan('20261013',run_id=job.run_id)
 if not plan:raise ValueError('REPLAY_NOT_SAVED:'+str(job.failure_code))
 newmaterial=json.loads((out/'derived/manager_workbench/input_snapshots'/f"{plan.changes['input_snapshot_sha256']}.json").read_bytes())
 if digest(newmaterial)!=plan.changes['input_snapshot_sha256']:raise ValueError('NEW_INPUT_SHA_MISMATCH')
 if {b['lane']:digest(b['records']) for b in newmaterial['batches']}!=records_sha:raise ValueError('MATERIAL_RECORDS_CHANGED')
 over=next(l for l in plan.lanes if l.lane==Lane.OVERSOLD);oldover=next(l for l in old.lanes if l.lane==Lane.OVERSOLD)
 if len(over.rows)!=692 or sum(r['decision']!='UNASSESSED' for r in over.rows)!=662:raise ValueError('ORIGINAL_SCOPE_OR_ASSESSED_COUNT_CHANGED')
 canary=next(r for r in over.rows if r['symbol']=='HK.09927')
 if canary['decision']!='CONDITIONAL_WATCH' or canary['metrics']['price_threshold']!='29.388':raise ValueError('SERES_CANARY_FAILED')
 oldus=next(l for l in old.lanes if l.lane==Lane.US_MAPPING);newus=next(l for l in plan.lanes if l.lane==Lane.US_MAPPING)
 if oldus.rows!=newus.rows:raise ValueError('US_DECISIONS_CHANGED')
 with TestClient(app) as client:
  detail=client.get('/api/v4/manager-workbench/stocks/HK.09927',params={'date':'20261013','run_id':job.run_id})
  if detail.status_code!=200:raise ValueError('SAVED_API_READBACK_FAILED')
  (out/'seres-http.json').write_text(json.dumps(detail.json(),ensure_ascii=False,indent=2)+'\n')
 after=sha(OLD.read_bytes())
 if after!=OLD_SHA:raise ValueError('OLD_SNAPSHOT_CHANGED')
 proof=dict(status='SAVED_ISOLATED_API_VERIFIED',run_id=plan.run_id,job_id=job.job_id,job_state=job.state.value,config_path=str(cfgpath),target_date='20261013',phase='RETROSPECTIVE',actual_cutoff=plan.context.cutoff,rules_version=plan.context.rules_version,product_sha256=plan.product_sha256,input_sha256=plan.input_sha256,scope=692,assessed=662,unknown=30,old_counts=dict(collections.Counter(r['decision'] for r in oldover.rows)),new_counts=dict(collections.Counter(r['decision'] for r in over.rows)),canary=canary,selected_symbols=[r['symbol'] for r in over.rows if r['decision']=='SELECTED'],original_run_id=old.run_id,old_snapshot_raw_sha256=after,old_product_sha256=old.product_sha256,frozen_input_snapshot_sha256=inputsha,records_sha256=records_sha,us_saved_rows_unchanged=True,network_calls=0,model_calls=0,quota_calls=0,formal_state_writes=0)
 (out/'proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in proof.items() if k not in ('canary','selected_symbols')},ensure_ascii=False))
if __name__=='__main__':main()
