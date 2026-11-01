"""Actual Main/Stage entry fixtures and actual unified ASGI readback only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ENTRY = r'''
import copy,hashlib,json,os,time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from infrastructure.report_evidence_index import PdfOwner
from stage_center.selection import SelectionStore
root=Path(os.environ['VERIFY_ROOT']);root.mkdir(parents=True)
selection=Path(os.environ['VERIFY_SELECTION']);receipts=Path(os.environ['VERIFY_RECEIPTS'])
date='20261030';stage='STAGE_1445_1500';original_path=receipts/date/stage/'receipt.json'
raw=original_path.read_bytes();original=json.loads(raw);store=SelectionStore(selection)
watched=[original_path,selection/'latest.json']
for market,lane in original['markets'].items():
 verified=store._verify_run(date,stage,market,lane['run_id'])
 directory=selection/'selection_runs'/date/store._role(stage,market)/lane['run_id']
 watched.extend(directory/name for name in ('artifact.csv','manifest.json','receipt.json'))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched if p.exists()}
owner=PdfOwner(os.environ['V4_RESEARCH_DATA_ROOT']);owner_file=Path(owner.owner.__file__)
assert owner_file.name=='report_evidence_pdf_owner.py'
assert hashlib.sha256(owner_file.read_bytes()).hexdigest()=='f567de644f88f9db18a82bde7d3c6d93b31f79bca806141d7f51d30dc0189cde'
def invoke(enabled):
 os.environ['V4_STAGE_REPORT_EVIDENCE_ENABLED']='1' if enabled else '0'
 started=time.perf_counter()
 if os.environ['VERIFY_ROLE']=='stage':
  from ops import run_stage_center_nodes as entry
  from ops._run_stage_center_nodes_parts import stage_dispatch
  cfg=json.loads((Path(os.environ['V4_APP_ROOT'])/'stage_center_tick_config.json').read_bytes())
  cfg.update(selection_root=str(selection),receipt_root=str(receipts),close_review_completion_enabled=False,report_evidence_sidecar_enabled=enabled)
  with patch.object(stage_dispatch,'__dispatch_stage_body',return_value=copy.deepcopy(original)):
   value=entry._dispatch_stage(cfg,date,stage,datetime.fromisoformat('2026-10-30T15:00:00+08:00'),mode='NATURAL')
  assert value==original
 else:
  from ops.run_stage_center_milestone import run_milestone
  value=run_milestone(node='FUPAN_CLOSE_MATERIALS',date=date,data_root=root/'milestone-output',selection_root=selection,retry_wait_seconds=0)
  assert value['status'] in {'READY','READY_EMPTY','PARTIAL_WITH_ROWS'}
 return time.perf_counter()-started
sidecars=Path(os.environ['V4_REPORT_EVIDENCE_SIDECAR_ROOT'])
off=invoke(False);assert not sidecars.exists()
on=invoke(True);assert on<2.0,('completion callback blocked',on)
jobs=list((sidecars/'jobs').glob('*.job.json'));assert len(jobs)==1
job=jobs[0].name.removesuffix('.job.json');result_path=sidecars/'jobs'/(job+'.receipt.json')
def wait_result(path):
 for _ in range(550):
  value=json.loads(path.read_bytes())
  if value['status'] in {'COMPLETED','FAILED'}:return value
  time.sleep(.1)
 raise AssertionError('WORKER_IN_FLIGHT_PRESERVED_NO_KILL')
completed=wait_result(result_path);assert completed['status']=='COMPLETED',completed
assert len(completed['result']['items'])==2,completed
for item in completed['result']['items']:
 assert item['status'] in {'MATERIALIZED','REUSED'}
 materialized=json.loads(Path(item['path']).read_bytes())
 assert materialized['selection_scores_used'] is False
 assert materialized['binding']['runner_verification_scope']=='PERSISTED_DECLARATION_AND_SELECTION_TRIO_ONLY_NOT_NATURAL_EXECUTION'
 for row in materialized['rows']:
  result=row['evidence'];assert result['mode']=='historical_evidence'
  cutoff=datetime.fromisoformat(result['as_of'])
  for hit in result['hits']:assert datetime.fromisoformat(hit['available_at'])<=cutoff
old=result_path.read_bytes();repeat=invoke(True);assert result_path.read_bytes()==old and len(list((sidecars/'jobs').glob('*.job.json')))==1
# An unavailable derived index must fail only the worker. Keep original scores,
# Stage statuses and receipt bytes unchanged, and do not retry the same failure.
os.environ['V4_REPORT_EVIDENCE_SIDECAR_ROOT']=str(root/'fault-sidecars')
os.environ['V4_REPORT_EVIDENCE_INDEX_ROOT']=str(root/'missing-index')
fault_seconds=invoke(True);assert fault_seconds<2
fault_path=next((root/'fault-sidecars/jobs').glob('*.receipt.json'))
failed=wait_result(fault_path);assert failed['status']=='FAILED',failed
failure_before=fault_path.read_bytes();invoke(True);assert fault_path.read_bytes()==failure_before
after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched if p.exists()};assert before==after
print(json.dumps({'status':'PASS_ACTUAL_ENTRY_FIXTURE','role':os.environ['VERIFY_ROLE'],'entry':'ops.run_stage_center_nodes._dispatch_stage with original committed producer result seam' if os.environ['VERIFY_ROLE']=='stage' else 'ops.run_stage_center_milestone.run_milestone actual selection consumer',
 'callback_seconds':{'off':off,'submit':on,'repeat':repeat,'fault_submit':fault_seconds},'worker_seconds':completed['wall_seconds'],'worker_pid':completed['worker_pid'],
 'job_id':job,'job_receipt':str(result_path),'fault_receipt':str(fault_path),'original_sha256':before,'original_bytes_unchanged':True,
 'alias':str(owner_file),'alias_sha256':hashlib.sha256(owner_file.read_bytes()).hexdigest(),'scope':'exact D30 Stage two markets; frozen 3-document index only; does not certify full-corpus latency or natural execution'}))
'''

API = r'''
import hashlib,json,os,time
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
from infrastructure.report_evidence_index import PdfOwner
root=Path(os.environ['VERIFY_ROOT']);root.mkdir(parents=True)
owner=PdfOwner(os.environ['V4_RESEARCH_DATA_ROOT']);assert Path(owner.owner.__file__).name=='zsxq_pdf_ingestion.py'
app=create_app(data_root=root/'data',ledger_root=root/'ledger',stage_center_selection_root=Path(os.environ['VERIFY_SELECTION']),manager_research_state_root=root/'manager',research_data_root=Path(os.environ['V4_RESEARCH_DATA_ROOT']),research_ledger_root=root/'research-ledger',morning_news_data_root=root/'morning',preselection_source_root=root/'pools')
with TestClient(app) as client:
 started=time.perf_counter()
 response=client.get('/api/v4/research/evidence-search',params={'text':'2026-2028年EPS','security':'301216','market':'A'})
 assert response.status_code==200,response.text
 value=response.json();assert value['vector_succeeded'] and value['hits'],value
 hit=value['hits'][0];original=client.get(hit['original_url'])
 assert original.status_code==200,original.text
 assert original.json()['receipt']['verified_pdf_sha256']==hit['pdf_sha256']
 conflict=client.get('/api/v4/research/evidence-search',params={'text':'2026-2028年EPS','security':'301216','market':'HK'});assert conflict.status_code==200 and not conflict.json()['hits']
 missing_cutoff=client.get('/api/v4/research/evidence-search',params={'text':'test','mode':'historical_evidence'});assert missing_cutoff.status_code==422
 sop=client.get('/api/v4/operations/sop',params={'doc':'runtime-data-recovery'});assert sop.status_code==200 and sop.json()['write_performed'] is False
 sidecar=client.get('/api/v4/research/stage-report-evidence',params={'date':'20261030','stage':'STAGE_1445_1500','selection_run':'run-22c6287060ceb523fbd7f774','market':'A_SHARE'})
 assert sidecar.status_code==200 and sidecar.json()['status']=='EXPLANATION_ONLY',sidecar.text
 print(json.dumps({'status':'PASS_UNIFIED_ACTUAL_ASGI_HTTP','search_hits':len(value['hits']),'search_mode':value['search_mode'],'generation':value['index_generation'],
 'query_coverage':value['query_coverage'],'original_document_http':original.status_code,'sidecar_http':sidecar.status_code,'sop_http':sop.status_code,'wall_seconds':time.perf_counter()-started,
 'owner_module':owner.owner.__file__,'owner_sha256':hashlib.sha256(Path(owner.owner.__file__).read_bytes()).hexdigest(),'scope':'3-document native sample; no full-corpus performance or UI claim'}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','evidence','index','data-root','selection','receipts','bridge'): parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();args.evidence.mkdir(parents=True,exist_ok=False)
    candidate=json.loads((args.candidate/'candidate_receipt.json').read_bytes());reports=[]
    def run(role,code):
        row=candidate['roles'][role];app=Path(row['app_root'])
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(app/'upstreams'),'V4_APP_ROOT':str(app),'V4_RELEASE_ID':row['release_id'],
            'V4_RELEASE_MANIFEST_PATH':str(app.parent/'release-manifest.json'),'V4_RELEASE_MANIFEST_SHA256':row['manifest_sha256'],
            'STAGE_CENTER_CONFIG':str(app/'stage_center_tick_config.json'),'V4_RESEARCH_DATA_ROOT':str(args.data_root),'V4_RUNTIME_GRAPH_INBOX':'',
            'V4_REPORT_EVIDENCE_INDEX_ROOT':str(args.index),'V4_REPORT_EVIDENCE_LOCAL_BRIDGE':str(args.bridge),
            'V4_REPORT_EVIDENCE_SIDECAR_ROOT':str(args.evidence/role/'sidecars'),'VERIFY_ROOT':str(args.evidence/role),'VERIFY_ROLE':role,
            'VERIFY_SELECTION':str(args.selection),'VERIFY_RECEIPTS':str(args.receipts)}
        if role=='api':env['V4_REPORT_EVIDENCE_SIDECAR_ROOT']=str(args.evidence/'stage/sidecars')
        child=subprocess.run([sys.executable,'-B','-c',code],cwd=app,env=env,capture_output=True,text=True)
        (args.evidence/(role+'.stdout.txt')).write_text(child.stdout);(args.evidence/(role+'.stderr.txt')).write_text(child.stderr)
        if child.returncode:raise RuntimeError(role+':'+child.stderr[-2000:])
        value=json.loads(child.stdout.strip().splitlines()[-1]);reports.append(value)
    run('main',ENTRY);run('stage',ENTRY);run('api',API)
    result={'schema_version':'v4.unified_actual_entry_checks.v1','candidate':str(args.candidate),'checks':reports,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'sample_index':str(args.index),'no_production_services_changed':True,'NATURAL_VERIFIED':'NOT_RUN','UI':'NOT_RUN'}
    (args.evidence/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
