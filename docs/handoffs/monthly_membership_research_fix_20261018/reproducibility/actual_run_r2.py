"""One authorized real-data submission; explicit read-only follow-up modes."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, sys, urllib.request
H=Path.cwd()/'docs/handoffs/monthly_membership_research_fix_20261018'
O=H/'local_only/actual_r2'; O.mkdir(exist_ok=True)
API='http://127.0.0.1:8873'
sha=lambda b:hashlib.sha256(b).hexdigest()
now=lambda:datetime.now(timezone.utc).isoformat()
def call(path,name,body=None):
    req=urllib.request.Request(API+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as r: raw=r.read();status=r.status
    (O/(name+'.json')).write_bytes(raw)
    return json.loads(raw),dict(http_status=status,response_sha256=sha(raw),response_bytes=len(raw),observed_at=now())
mode=sys.argv[1]
if mode=='submit':
    assert json.loads((H/'ROOT_API_ACTIVATION_RECEIPT.json').read_text())['status']=='DEPLOYED_API_HEALTH_IDENTITY_VERIFIED'
    assert not (O/'submit-intent.json').exists(), 'EXISTING_SUBMISSION_INTENT_DO_NOT_REPEAT_POST'
    body=dict(target_date='20261020',phase='MANUAL',lanes=['US_MAPPING'])
    with (O/'submit-intent.json').open('x') as f:json.dump(dict(request=body,at=now()),f)
    data,meta=call('/api/v4/manager-workbench/runs','submit-response',body)
    inner=data['data'];job=inner.get('job_id') or inner.get('run_id')
    assert job
    result=dict(request=body,job_id=job,run_id=inner.get('run_id') or job,status_url=inner.get('status_url') or '/api/v4/manager-workbench/runs/'+job,submission_count=1,state=data['state'],**meta)
    (H/'ROOT_RUN_SUBMISSION_R2.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
elif mode=='poll':
    sub=json.loads((H/'ROOT_RUN_SUBMISSION_R2.json').read_text());d,m=call(sub['status_url'],'job-response');v=d['data']
    result={k:v.get(k) for k in ['state','job_id','run_id','started_at','finished_at','step','failure_code']};result.update(m)
    (H/'ROOT_RUN_JOB_R2.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
elif mode=='read':
    sub=json.loads((H/'ROOT_RUN_SUBMISSION_R2.json').read_text());run=sub['run_id'];result={}
    for kind,path in [('day','/days/20261020'),('lane','/days/20261020/recommendations/US_MAPPING')]:
        d,m=call('/api/v4/manager-workbench'+path+'?run_id='+run+'&limit=50',kind+'-response')
        inner=d['data'];result[kind]=dict(state=d['state'],data_keys=list(inner),counts=inner.get('counts'),snapshot_run_id=(inner.get('snapshot') or {}).get('run_id'),**m)
        assert all(d.get(k)==v for k,v in dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False).items())
    result['run_id']=run
    (H/'ROOT_API_READBACK_R2.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
else:raise SystemExit('unknown mode')
