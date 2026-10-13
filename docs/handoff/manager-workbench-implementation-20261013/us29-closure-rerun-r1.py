"""Only new reviewed US research classifications against frozen 3756 inputs.
No new quote, membership, market history, network, model, or formal-state write.
"""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,sys,collections
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sha=lambda raw:hashlib.sha256(raw).hexdigest()
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/3756008d713a4505be362d288ab9d504.json')
E=ROOT/'v4/manager_workbench/research_data/us_mapping_relation_evidence_20261013_v3.json'
V=ROOT/'v4/manager_workbench/research_data/us_mapping_relation_evidence_review_20261013_v3.json'
ESHA='2046fdafb69a8e4cb9d7de4f754ea69799b769c82351dd46499ba1b6a6ca567f';VSHA='33c4b45fae64f72a406e707d77cf5db93495ed3f1b15461d6d96da617696ed8b'
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();out=a.output.resolve()
 if out.exists() or not out.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('NEW_ISOLATED_OUTPUT_REQUIRED')
 spec=importlib.util.spec_from_file_location('accepted_calendar',HERE/'recover_cached_full_date.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.install_runtime()
 from v4.manager_workbench.contracts import PlanSnapshot,Lane,digest,Coverage
 from v4.manager_workbench.inputs.validation import owner_digest,batch
 from v4.manager_workbench.inputs.source_bindings import priority_review,checked_time
 from v4.manager_workbench.config import WorkbenchConfig
 from v4.manager_workbench.inputs.native import NativeAdapters
 from v4.manager_workbench.service import create_service
 from v4.manager_workbench.api import create_router
 from v4.manager_workbench import engines
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 oldraw=OLD.read_bytes();oldsha=sha(oldraw);old=PlanSnapshot.model_validate(json.loads(oldraw));inputsha=old.changes['input_snapshot_sha256'];material=json.loads((OLD.parent.parent/'input_snapshots'/f'{inputsha}.json').read_bytes())
 if digest(material)!=inputsha:raise ValueError('FROZEN_INPUT_SHA_MISMATCH')
 eraw=E.read_bytes();vraw=V.read_bytes()
 if sha(eraw)!=ESHA or sha(vraw)!=VSHA:raise ValueError('REVIEWED_PACKET_DRIFT')
 e=json.loads(eraw);v=json.loads(vraw)
 if v.get('status')!='PASS' or v['evidence_file_sha256']!=ESHA or e['artifact_sha256']!=v['recomputed_artifact_sha256'] or owner_digest({k:x for k,x in e.items() if k!='artifact_sha256'})!=e['artifact_sha256']:raise ValueError('PAIRED_REVIEW_INVALID')
 cfgraw=json.loads(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/config/manager-workbench-v7.json').read_bytes());cfgraw.update(state_root=str(out/'derived'),capture_enabled=False,capture_lease_token=None)
 cfg=WorkbenchConfig.model_validate(cfgraw);priority_review(cfg,e,v)
 cutoff=datetime.now(timezone.utc);checked_time(v['reviewed_at'],cutoff.isoformat())
 saved=copy.deepcopy(next(b for b in material['batches'] if b['lane']=='US_MAPPING'));original_records=copy.deepcopy(saved['records'])
 refs=[dict(relative=str(p.relative_to(ROOT)),sha256=hash_,owner=v['reviewer_identity'],available_at=v['reviewed_at']) for p,hash_ in [(E,ESHA),(V,VSHA)]]
 cards={(c['us_symbol'],c['hk_symbol'],c['relationship_type']):c for c in e['relations']};seen=set()
 for item in saved['records']:
  for relation in item.get('relations',[]):
   key=(item['us_symbol'],relation['target_symbol'],relation['relation_type']);card=cards.get(key)
   if not card:continue
   seen.add(key);relation.update(research_priority=card['research_priority'],research_priority_reason=card['research_priority_reason'],priority_assessment=copy.deepcopy(card['priority_assessment']),sha256=owner_digest(card),review_owner=v['reviewer_identity'],available_at=v['reviewed_at'],relation_source_refs=[*relation.get('relation_source_refs',[]),*refs])
  for assessment in item.get('reviewed_assessments',[]):
   candidate=next((a for a in e['symbol_assessments'] if a['us_symbol']==item['us_symbol']),None)
   if candidate:assessment.update(original=copy.deepcopy(candidate),assessment_sha256=owner_digest(candidate),review_owner=v['reviewer_identity'],available_at=v['reviewed_at'],source_refs=refs)
 if seen!=set(cards):raise ValueError('FROZEN_RELATION_SCOPE_CHANGED')
 # Raw quote, membership and historical evidence are retained on every original row.
 for olditem,newitem in zip(original_records,saved['records']):
  if any(olditem.get(k)!=newitem.get(k) for k in ('quote','source_session','source_sha256','owner','available_at')):raise ValueError('FROZEN_QUOTE_CHANGED')
  for oldrel,newrel in zip(olditem.get('relations',[]),newitem.get('relations',[])):
   if any(oldrel.get(k)!=newrel.get(k) for k in ('membership','target_symbol','target_name','publication_evidence','research_basis')):raise ValueError('FROZEN_RELATION_FACT_CHANGED')
 native=NativeAdapters(cfg)
 for p,h in [(E,ESHA),(V,VSHA)]:saved['evidence_refs'].append(native._ref(v['reviewer_identity'],'REVIEWED_US_HK_RELATIONS','20261012',h,str(p.relative_to(ROOT)),v['reviewed_at']).model_dump(mode='json'))
 class Frozen:
  def prepare_context(self,c):c=c.model_copy(deep=True);c.source_sessions=copy.deepcopy(material['context']['source_sessions']);return c
  def load(self,lane,c):
   if lane!=Lane.US_MAPPING:raise ValueError('ONLY_US_AUTHORIZED')
   return batch(c,lane,copy.deepcopy(saved['records']),copy.deepcopy(saved['evidence_refs']),saved['scope_description'],Coverage.model_validate(saved['coverage']),saved['gaps'],saved['universe_ref'])
 out.mkdir(parents=True);(out/'config.json').write_text(cfg.model_dump_json(indent=2)+'\n');s=create_service(cfg,Frozen(),engines,None)
 scope=copy.deepcopy(material['context']['scope_refs']);scope.pop('mwb_run_id',None);scope.pop('run_id',None);scope['frozen_material_replay']=dict(original_run_id=old.run_id,input_snapshot_sha256=inputsha,original_cutoff=material['context']['cutoff'],new_evidence_sha256=ESHA,new_review_sha256=VSHA,reviewed_at=v['reviewed_at'],authority='EXACT_SAVED_MARKET_AND_MEMBERSHIP_WITH_NEW_RESEARCH_CLASSIFICATION')
 try:job=s.submit('20261013','RETROSPECTIVE',lanes=[Lane.US_MAPPING],cutoff=cutoff,scope_refs=scope)
 finally:s.stop()
 job=s.jobs.get(job.job_id);plan=s.store.get_plan('20261013',run_id=job.run_id)
 if plan is None:raise ValueError('NEW_US_NOT_SAVED:'+str(job.failure_code))
 lane=next(l for l in plan.lanes if l.lane==Lane.US_MAPPING);app=FastAPI();app.include_router(create_router(s))
 with TestClient(app) as client:
  response=client.get('/api/v4/manager-workbench/days/20261013',params={'run_id':plan.run_id})
  if response.status_code!=200:raise ValueError('SAVED_API_READBACK_FAILED')
  (out/'day-http.json').write_text(json.dumps(response.json(),ensure_ascii=False,indent=2)+'\n')
 if sha(OLD.read_bytes())!=oldsha:raise ValueError('OLD_SNAPSHOT_CHANGED')
 proof=dict(status='SAVED_ISOLATED_US_API_VERIFIED',run_id=plan.run_id,job_id=job.job_id,job_state=job.state.value,actual_cutoff=plan.context.cutoff,target_date='20261013',phase='RETROSPECTIVE',source_session='20261012',product_sha256=plan.product_sha256,input_sha256=plan.input_sha256,original_run_id=old.run_id,original_snapshot_sha256=oldsha,original_input_sha256=inputsha,old_oversold_records_sha256=digest(next(b for b in material['batches'] if b['lane']=='OVERSOLD')['records']),new_evidence_sha256=ESHA,new_review_sha256=VSHA,source_coverage=lane.coverage.model_dump(mode='json'),relationship_row_counts=dict(collections.Counter(r['decision'] for r in lane.rows)),watch=[r for r in lane.rows if r['decision']=='CONDITIONAL_WATCH'],network_calls=0,model_calls=0,formal_writes=0)
 (out/'proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:x for k,x in proof.items() if k!='watch'},ensure_ascii=False))
if __name__=='__main__':main()
