"""Local-only one official complete article; no raw materials in delivery receipt."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import tempfile
import time
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import HK,Phase,Lane,RunContext,JobState
from v4.manager_workbench.binding import create_native_binding
from v4.manager_workbench.service import create_service
from v4.manager_workbench.api import create_router
from v4.manager_workbench.cli import _canary_verified
from v4.manager_workbench.executors.codex import verify_review_pair

ROOT=Path(__file__).resolve().parent
# Reproduce API LaunchAgent's deliberate no-proxy environment without changing
# its plist or parent process. LocalCliRunner must derive the current system proxy.
for key in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):os.environ[key]=''
for key in ('NO_PROXY','no_proxy'):os.environ[key]='*'
temporary_root=ROOT.parents[2]/'tests/manager_workbench/runtime/.tmp'
temporary_root.mkdir(parents=True,exist_ok=True)
state=Path(tempfile.mkdtemp(prefix='real-single-article-',dir=temporary_root))
cfg=WorkbenchConfig(state_root=state/'derived',manager_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research'),
    shared_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'),
    stage_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'),
    us_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data'),relation_root=Path('/Users/lexi/Desktop/学习/v4_app'),
    dynamic_source_bindings=True,model_timeout_seconds=300,
    codex_binary=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'))
receipt=dict(state_directory=str(state),target_date='20261012',phase='RETROSPECTIVE',original_pit='CANNOT_CONFIRM',
    API_VERIFIED='NOT_RUN',UI_VERIFIED='NOT_RUN',DEPLOYED='NOT_RUN',production_allowed=False,orders_sent=False,
    parent_launch_environment={'proxy_variables':'empty','NO_PROXY':'*'},model=cfg.model,reasoning_effort='max')
service=None
try:
    binding=create_native_binding(cfg)
    runner=binding['executor'].runner
    actual_invocations=[]
    if runner:
        original_run=runner.run
        def record_run(**kwargs):
            from v4.manager_workbench.executors.local_cli import process_environment
            env=process_environment()
            actual_invocations.append(dict(role=kwargs['role'],argv=kwargs['argv'],
                env={k:env.get(k) for k in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','no_proxy','CODEX_BUNDLED_MODE')}))
            return original_run(**kwargs)
        runner.run=record_run
    if binding['executor'].runner is None:raise ValueError(binding['isolation_gap'])
    context=binding['adapters'].prepare_context(RunContext(target_date='20261012',phase=Phase.RETROSPECTIVE,
        cutoff=datetime.now(HK).isoformat(),trigger='MANUAL',rules_version=cfg.rules_version))
    batch=binding['adapters'].load(Lane.ANNOUNCEMENT,context)
    articles=[r for r in batch.records if r.get('original_event_id')=='36b118b7e6708979a4574f193764b703892a0644deb516e1c418fd451d479692' and r.get('body_complete')]
    if len(articles)!=1:raise ValueError('OFFICIAL_CANARY_NOT_UNIQUE')
    article=articles[0]
    if article['owner']!='HKEX_OFFICIAL':raise ValueError('OFFICIAL_CANARY_OWNER_MISMATCH')
    matched=[r for r in batch.evidence_refs if r.evidence_id in article['evidence_ids'] and r.sha256==article['source_sha256']]
    if not matched or any(r.owner!='HKEX_OFFICIAL' for r in matched):raise ValueError('OFFICIAL_CANARY_EVIDENCE_OWNER_MISMATCH')
    receipt.update(article_id=article['article_id'],body_sha256=article['body_sha256'],source_sha256=article['source_sha256'],source_owner=article['owner'],matched_source_evidence_ids=[r.evidence_id for r in matched],batch_input_sha256=batch.input_sha256)
    service=create_service(cfg,binding['adapters'],binding['engines'],binding['executor'])
    job=service.submit('20261012',Phase.RETROSPECTIVE,lanes=[Lane.ANNOUNCEMENT],
        scope_refs={'canary_article_id':article['article_id'],'canary_mode':'SINGLE_ARTICLE'},cutoff=datetime.fromisoformat(context.cutoff))
    deadline=time.monotonic()+650
    while time.monotonic()<deadline:
        job=service.jobs.get(job.job_id)
        if job.state not in {JobState.QUEUED,JobState.RUNNING}:break
        time.sleep(.2)
    plan=service.store.read_plan(job.run_id) if job.state in {JobState.SUCCEEDED,JobState.PARTIAL} else None
    receipt.update(job_id=job.job_id,run_id=job.run_id,job_state=job.state.value,failure_code=job.failure_code,failed_steps=job.failed_steps)
    executions=[r for r in job.execution_refs if r.get('role')]
    receipt['executions']=[{k:v for k,v in r.items() if k in {'role','model','reasoning_effort','execution_id','execution_identity','process_pid','input_sha256','source_sha256','body_sha256','material_sha256','output_sha256','event_sha256','started_at','finished_at','success','failure_code','isolation_proof','simulated'}} for r in executions]
    if plan:
        app=FastAPI();app.include_router(create_router(service))
        response=TestClient(app).get('/api/v4/manager-workbench/days/20261012',params={'run_id':plan.run_id})
        receipt.update(http_status=response.status_code,http_response_sha256=hashlib.sha256(response.content).hexdigest(),
            product_sha256=plan.product_sha256,saved_readback_sha_matches=service.store.read_plan(job.run_id).product_sha256==plan.product_sha256,
            decision=plan.stocks[0].decision.value if plan.stocks else None,gaps=plan.gaps,
            reader_reviewer_saved_api_verified=_canary_verified(job,plan,article['article_id']))
    receipt['actual_invocations']=actual_invocations
    receipt['prompt_version']=cfg.prompt_version
    receipt['status']='PASS' if receipt.get('reader_reviewer_saved_api_verified') else 'CANNOT_CONFIRM'
except Exception as exc:
    receipt.update(status='CANNOT_CONFIRM',error_type=type(exc).__name__,failure_code=str(exc) if str(exc).isupper() else 'LOCAL_CANARY_FAILED')
finally:
    if service:service.jobs.stop()
    (ROOT/'real-single-article-owner-fix-canary-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:receipt.get(k) for k in ['status','job_state','failure_code','decision','state_directory']}))
