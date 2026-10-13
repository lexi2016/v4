"""Submit exactly US_MAPPING+OVERSOLD to the existing formal API; no state override.
Requires deployment of the approved adapter/config first. Uses existing service,
immutable save, full pagination and progress endpoints, without a model call.
"""
from pathlib import Path
import argparse,collections,json,time,urllib.request
HERE=Path(__file__).resolve().parent

def request(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8873/api/v4/manager-workbench'+path,
       data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='GET' if body is None else 'POST')
 with urllib.request.urlopen(req,timeout=15) as response:return json.loads(response.read())

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--target-date',default='20261013');a=p.parse_args()
 out=a.output.resolve()
 if out.exists() or not out.is_relative_to((HERE/'.tmp').resolve()):raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 out.mkdir(parents=True)
 submitted=request('/runs',dict(target_date=a.target_date,phase='RETROSPECTIVE',lanes=['US_MAPPING','OVERSOLD']))['data']
 (out/'submitted.json').write_text(json.dumps(submitted,indent=2)+'\n');print(json.dumps(submitted),flush=True)
 while True:
  job=request('/runs/'+submitted['job_id'])['data'];(out/'progress.json').write_text(json.dumps(job,indent=2)+'\n')
  if job['state'] in {'SUCCEEDED','PARTIAL','FAILED','CANCELLED'}:break
  time.sleep(1)
 if not job.get('run_id'):raise ValueError('FORMAL_DUAL_LANE_RUN_NOT_SAVED')
 pages=[];rows=[];offset=0
 while True:
  data=request('/days/'+a.target_date+'?run_id='+job['run_id']+'&offset='+str(offset)+'&limit=200');pages.append(data);rows.extend(data['data']['stocks'])
  if len(rows)>=data['data']['pagination']['total']:break
  offset+=200
 if len(rows)!=len({r['symbol'] for r in rows}):raise ValueError('FORMAL_FULL_PAGINATION_IDENTITY_INVALID')
 (out/'http-pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2)+'\n')
 proof=dict(job=job,observed_stock_count=len(rows),counts=pages[0]['data']['counts'],
    decisions=dict(collections.Counter(r['decision'] for r in rows)),selected_symbols=[r['symbol'] for r in rows if r['decision']=='SELECTED'],
    state_root_overrides=0,page_url='http://127.0.0.1:8873/manager-selection/?date='+a.target_date+'&phase=RETROSPECTIVE&run_id='+job['run_id'])
 (out/'receipt.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
