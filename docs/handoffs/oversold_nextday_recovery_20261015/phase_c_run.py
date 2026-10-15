"""One fresh MANUAL OVERSOLD API run; never retry or mutate an old run."""
from datetime import datetime, timezone
import collections, hashlib, json, time, urllib.parse, urllib.request
from pathlib import Path
H=Path(__file__).resolve().parent;BASE='http://127.0.0.1:8873';PREFIX='/api/v4/manager-workbench';OLD='18425e50e6294f15a6bc02ac881c5af2'
def request(path,body=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'} if body else {})
 with urllib.request.urlopen(req,timeout=30) as r:raw=r.read()
 return json.loads(raw),hashlib.sha256(raw).hexdigest()
def write(path,value):
 with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 activation=json.loads((H/'phase_c_activation_r2.json').read_bytes());assert activation['status']=='CONFIG_ACTIVATED_HEALTHY'
 if (H/'phase_c_run_created.json').exists():
  created=json.loads((H/'phase_c_run_created.json').read_bytes());submitted=created['response'];oldsha=created['old_run_sha256_before']
 else:
  old,oldsha=request(PREFIX+'/runs/'+OLD)
  payload=dict(target_date='20261016',phase='MANUAL',lanes=['OVERSOLD'])
  submitted,_=request(PREFIX+'/runs',payload);created=dict(posted_at=datetime.now(timezone.utc).isoformat(),payload=payload,response=submitted,old_run_sha256_before=oldsha)
  write(H/'phase_c_run_created.json',created)
 identity=submitted['data'];jobid=identity['job_id'];runid=identity['run_id']
 print(json.dumps(dict(status='READ_SAVED_RUN',job_id=jobid,run_id=runid)),flush=True)
 for _ in range(60):
  status,_=request(PREFIX+'/runs/'+jobid)
  if status['state'] not in ['RUNNING','QUEUED']:break
  time.sleep(2)
 else:raise RuntimeError('HEALTHY_RUN_COMPLETION_PENDING_READ_EXISTING_ID_DO_NOT_REPOST')
 assert status['state'] in ['PARTIAL','SUCCEEDED'],status['state']
 ctx=status['data']['context'];assert ctx['target_date']=='20261016' and ctx['phase']=='MANUAL' and ctx['source_sessions']['hk_price']=='20261015'
 path=PREFIX+'/days/20261016?'+urllib.parse.urlencode(dict(phase='MANUAL',run_id=runid,offset=0,limit=200))
 response,_=request(path);data=response['data'];assert data['pagination']['total']==689
 rows=list(data['stocks'])
 for offset in [200,400,600]:
  page,_=request(PREFIX+'/days/20261016?'+urllib.parse.urlencode(dict(phase='MANUAL',run_id=runid,offset=offset,limit=200)))
  assert page['data']['counts']==data['counts'];rows+=page['data']['stocks']
 assert len(rows)==len({x['symbol'] for x in rows})==689
 lane_rows=[entry for stock in rows for entry in stock['lane_decisions']['OVERSOLD']]
 assert len(lane_rows)==689
 counts=collections.Counter(x['decision'] for x in lane_rows);assert counts==dict(SELECTED=21,CONDITIONAL_WATCH=171,NOT_SELECTED=373,UNASSESSED=124)
 selected_response,_=request(PREFIX+'/days/20261016/recommendations/OVERSOLD?'+urllib.parse.urlencode(dict(phase='MANUAL',run_id=runid,decision='SELECTED',offset=0,limit=200)))
 selected=selected_response['data']['stocks'];assert len(selected)==selected_response['data']['pagination']['total']==21
 old_after,aftersha=request(PREFIX+'/runs/'+OLD);assert oldsha==aftersha,'FAILED_OLD_RUN_CHANGED'
 safety={k:response[k] for k in ['RESEARCH_ONLY','production_allowed','buy_gate_updated','orders_sent']};assert safety==dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 pin=ctx['scope_refs']['owner_bindings']['hk_panel']['tdxpy_history'];assert pin['raw_sha256']=='7484c9312ffe565ca8778264456d4af01d5541d35005d2927274c35349188fc8'
 r=dict(schema_version='oversold-recovery-phase-c-receipt-v1',status='DEPLOYED_API_VERIFIED_PENDING_INDEPENDENT_LIVE_REVIEW',activation=activation,job_id=jobid,run_id=runid,job_state=status['state'],context=ctx,API_lane_state=response['state'],counts=selected_response['data']['counts'],aggregate_counts=data['counts'],aggregate_count_note='Existing aggregate maps lane NOT_SELECTED to top-level UNASSESSED; use OVERSOLD lane rows for real rejection and source-gap counts',decision_counts=dict(counts),actual_unique_rows=689,selected=[dict(symbol=x['symbol'],name=x.get('name'),reason=x.get('reason'),metrics=x.get('metrics'),name_source=x.get('name_source')) for x in selected],source_bound_pin=pin,safety=safety,failed_old_run=dict(run_id=OLD,sha256_before=oldsha,sha256_after=aftersha,unchanged=True,context=old_after['data']['context'],state=old_after['state']),snapshot_identity={k:data['snapshot'].get(k) for k in ['run_id','product_sha256','input_sha256','generated_at','available_at']},independent_live_review='PENDING',UI_VERIFIED='NOT_RUN_BY_WRITER',NATURAL_VERIFIED=False,completed_at=datetime.now(timezone.utc).isoformat())
 write(H/'phase_c_receipt.json',r)
 print(json.dumps(dict(run_id=runid,state=r['status'],counts=r['counts'],cutoff=ctx['cutoff'],selected=[dict(symbol=x['symbol'],name=x['name']) for x in r['selected']]),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
