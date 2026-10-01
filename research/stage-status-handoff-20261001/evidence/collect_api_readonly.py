# -*- coding: utf-8 -*-
from pathlib import Path
import json, urllib.request, urllib.parse, hashlib, datetime
from concurrent.futures import ThreadPoolExecutor

OUT = Path(__file__).parent
STAGES = ['STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500','STAGE_1545_1555']
requests = [(f'{date}_{stage}', '/api/v3/stage-center/selection', {'date':date,'stage':stage,'limit':'50'}) for date in ['20260928','20260929','20260930'] for stage in STAGES]
requests += [('catalog','/api/v1/runs/date-list',{}),('meta','/api/v3/meta/stages',{}),('health','/healthz',{}),('preselection_20260930','/api/v3/preselection-pools',{'date':'20260930','limit':'200'}),('preselection_20261008','/api/v3/preselection-pools',{'date':'20261008','limit':'200'})]
requests += [(f'workbench_{date}_{stage}', '/api/v3/workbench/stage', {'date':date,'stage':stage}) for date in ['20260928','20260929','20260930'] for stage in STAGES]
requests += [('tasks_20260930','/api/v3/tasks/status',{'date':'20260930'}),('safety','/readyz',{})]
(OUT/'api').mkdir(exist_ok=True)
def read(item):
    name,path,query=item
    url='http://127.0.0.1:8873'+path+('?' + urllib.parse.urlencode(query) if query else '')
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    try:
        existing=OUT/'api'/f'{name}.json'
        if existing.exists():
            raw=existing.read_bytes(); status=200
            prior=json.loads((OUT/'api_readback_index.json').read_text())
            stamp=next((r['observed_at'] for r in prior if r['name']==name),stamp)
        else:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Cache-Control':'no-cache'}),timeout=25) as response:
                raw=response.read(); status=response.status
        (OUT/'api'/f'{name}.json').write_bytes(raw)
        data=json.loads(raw)
        return {'name':name,'url':url,'observed_at':stamp,'http_status':status,'raw_sha256':hashlib.sha256(raw).hexdigest(),'file':f'api/{name}.json','response':data}
    except Exception as exc:
        return {'name':name,'url':url,'observed_at':stamp,'error':str(exc)}
with ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(read,requests))
(OUT/'api_readback_index.json').write_text(json.dumps([{k:v for k,v in row.items() if k!='response'} for row in results],ensure_ascii=False,indent=2)+'\n')
matrix=[]
for result in results:
    data=result.get('response',{})
    if result['name'].startswith('2026') or result['name'].startswith('workbench_'):
        key=result['name'].removeprefix('workbench_')
        row={'route':'workbench' if result['name'].startswith('workbench_') else 'formal_selection','date':key[:8],'stage':key[9:],'http_status':result.get('http_status'),'response_keys':list(data),'markets':{}}
        for key,lane in data.get('markets',{}).items():
            if not isinstance(lane,dict):continue
            rows=lane.get('rows',[])
            row['markets'][key]={'rows':len(rows) if isinstance(rows,list) else rows,**{k:lane.get(k) for k in ['status','run_id','backfill_run_id','runner_receipt_verified','selection_sha256','artifact_sha256','source_date','signal_date','cannot_confirm','reason']}}
        matrix.append(row)
(OUT/'current_api_matrix.json').write_text(json.dumps(matrix,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'read_requests':len(results),'errors':[r for r in results if 'error' in r],'matrix':[{'route':r['route'],'date':r['date'],'stage':r['stage'],'counts':{k:v['rows'] for k,v in r['markets'].items()}} for r in matrix]},ensure_ascii=False))
