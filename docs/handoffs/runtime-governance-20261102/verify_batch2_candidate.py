"""Bounded actual-candidate checks; no servers, collectors or launchd mutation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--candidate", required=True, type=Path); parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(); args.evidence.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((args.candidate / "candidate_receipt.json").read_bytes())
    reports = []
    def run(role, name, code):
        row = receipt["roles"][role]; app = Path(row["app_root"]); manifest = app.parent / "release-manifest.json"
        env = os.environ.copy(); env.update(PYTHONPATH=str(app / "upstreams"), PYTHONDONTWRITEBYTECODE="1", V4_APP_ROOT=str(app), V4_RELEASE_ID=row["release_id"], V4_RELEASE_MANIFEST_PATH=str(manifest), V4_RELEASE_MANIFEST_SHA256=row["manifest_sha256"], VERIFY_TMP=str(args.evidence / name))
        child = subprocess.run([sys.executable, "-B", "-c", code], cwd=app, env=env, capture_output=True, text=True, timeout=90)
        (args.evidence / (name + ".stdout.txt")).write_text(child.stdout)
        (args.evidence / (name + ".stderr.txt")).write_text(child.stderr)
        reports.append({"role": role, "check": name, "exit_code": child.returncode, "status": "PASS" if child.returncode == 0 else "FAIL"})
        if child.returncode: raise RuntimeError(name + ":" + child.stderr[-2000:])
    run("api", "sop-http", '''
import os,json
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
root=Path(os.environ['VERIFY_TMP']);root.mkdir()
app=create_app(data_root=root/'data',ledger_root=root/'ledger',stage_center_selection_root=root/'selection',manager_research_state_root=root/'manager',research_data_root=root/'research',research_ledger_root=root/'researchledger',morning_news_data_root=root/'morning',preselection_source_root=root/'pools')
with TestClient(app) as client:
 response=client.get('/api/v4/operations/sop',params={'doc':'runtime-data-recovery'})
 assert response.status_code==200,response.text
 body=response.json();assert body['write_performed'] is False
 for token in ('replay-original','historical-minute','record-gap','CANNOT_CONFIRM','AFTERFACT_MINUTE_OBSERVATION'):assert token in body['content']
 print(json.dumps({'status':'PASS_ISOLATED_HTTP','sha256':body['sha256'],'bytes':body['bytes']}))
''')
    run("main", "manager-independent", '''
import json,os
from pathlib import Path
from types import SimpleNamespace
from contracts.runtime_tasks import DispatchRequest
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry,WorkloadExecutionError
from infrastructure.scheduling import executor_registry_research as research
registry=FixedExecutorRegistry(data_root=Path(os.environ['VERIFY_TMP'])/'data',stage_selection_root=Path(os.environ['VERIFY_TMP'])/'selection')
calls=[]
def manager(self,request,stage_result):
 calls.append(stage_result['status']);return {'status':'SUCCEEDED','attempt':1,'capture_status':'fixture'}
research._manager_close_recapture_after_stage_workbench=manager
registry._run=lambda *a,**k:{'status':'FAILED','exit_code':2}
request=DispatchRequest('20261030','20261030','20261030','1555','LIVE')
workload=SimpleNamespace(workload_id='fupan_review_start')
result=registry._run_stage_center_milestone(workload,request)
assert calls==['FAILED'] and result['stage_readback_status']=='FAILED' and result['manager_close_recapture_status']=='SUCCEEDED' and result['status']=='FAILED'
def failed_manager(*a,**k):raise WorkloadExecutionError({'status':'FAILED','exit_code':2,'attempt':2})
research._manager_close_recapture_after_stage_workbench=failed_manager
registry._run=lambda *a,**k:{'status':'SUCCEEDED','exit_code':0}
other=registry._run_stage_center_milestone(workload,request)
assert other['stage_readback_status']=='SUCCEEDED' and other['manager_close_recapture_status']=='FAILED' and other['manager_close_recapture']['attempt']==2
print(json.dumps({'status':'PASS_ISOLATED_FIXTURE','stage_fail_manager_attempted':result,'stage_success_manager_fail_separate':other}))
''')
    run("stage", "default-off-hook", '''
import json,sys
from types import SimpleNamespace
from infrastructure.stage_completion_hooks import deliver
calls=[]
def callback(**kwargs):calls.append(kwargs['receipt']['markets']['A_SHARE']['run_id']);return {'status':'READY'}
sys.modules['infrastructure.report_evidence_sidecar']=SimpleNamespace(on_stage_completed=callback)
original={'status':'READY','markets':{'A_SHARE':{'run_id':'fixture-run'}}};before=json.dumps(original)
args=dict(trade_date='20261030',stage_id='STAGE_1445_1500',receipt=original,settled=True,mode='NATURAL')
assert deliver(config={},**args)==[] and calls==[]
deliver(config={'report_evidence_sidecar_enabled':True},**args)
assert calls==['fixture-run'] and before==json.dumps(original)
print(json.dumps({'status':'PASS_ISOLATED_HOOK','receipt_unchanged':True}))
''')
    output = {"schema_version": "v4.runtime_batch2_candidate_checks.v1", "checks": reports, "source": str(Path(__file__).resolve()),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "candidate": str(args.candidate),
        "live_services_started": False, "collectors_run": False, "NATURAL_VERIFIED": "NOT_RUN"}
    (args.evidence / "RESULT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__": main()
