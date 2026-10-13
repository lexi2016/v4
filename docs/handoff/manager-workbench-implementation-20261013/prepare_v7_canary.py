"""Prepare isolated config, bind saved full-window material, or run ONE article.
No source requests or lease grant. Model invocation requires an explicit article.
"""
from pathlib import Path
import argparse,json,sys,time
from datetime import datetime
HERE=Path(__file__).resolve().parent;CANDIDATE=HERE/'deployment-deltas/isolated-api-candidate-v7-final/app'
sys.path.insert(0,str(CANDIDATE))
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import RunContext,HK,Lane,Phase,JobState
from v4.manager_workbench.inputs.capture_binding import publish,read_binding
from v4.manager_workbench.inputs import NativeAdapters


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture-receipt',required=True)
 p.add_argument('--execute-model',action='store_true');p.add_argument('--article-id');args=p.parse_args()
 if args.execute_model and not args.article_id:raise ValueError('EXPLICIT_SINGLE_ARTICLE_REQUIRED')
 proof=json.loads(Path(args.capture_receipt).read_text());isolated=Path(proof['root']).resolve()
 if '/T/mwb-live-capture-canary-' not in str(isolated):raise ValueError('KNOWN_ISOLATED_ROOT_REQUIRED')
 capture=isolated/'capture';lease=isolated/'leases';state=isolated/'derived-v7'
 cfg=WorkbenchConfig(state_root=state,capture_root=capture,capture_lease_root=lease,capture_enabled=False,
  manager_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research'),
  shared_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'),
  stage_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'),
  us_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data'),relation_root=Path('/Users/lexi/Desktop/学习/v4_app'),
  dynamic_source_bindings=True,codex_binary=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'))
 config=isolated/'v7-config.json';config.write_text(cfg.model_dump_json(indent=2)+'\n')
 ref=proof['product_ref'];ctx=RunContext(target_date='20261013',phase='RETROSPECTIVE',cutoff=datetime.now(HK).isoformat(),
   trigger='MANUAL',rules_version=cfg.rules_version)
 material_proof=isolated/'v7-material-preparation.json'
 if material_proof.exists():
  previous=json.loads(material_proof.read_text())
  if previous['original_product_ref']!=ref:raise ValueError('MATERIAL_PREPARATION_PRODUCT_CHANGED')
  pin=previous['binding_pin']
 elif args.execute_model:raise ValueError('PREPARE_MATERIAL_BEFORE_MODEL')
 else:pin=publish(cfg,{'saved_ref':ref},ctx,'isolated-full-window-v7')
 manifest,product=read_binding(cfg,pin,ctx)
 adapter=NativeAdapters(cfg);context=adapter.prepare_context(ctx);batch=adapter.load(Lane.ANNOUNCEMENT,context)
 eligible=[r['article_id'] for r in batch.records if r.get('body_complete') and r.get('membership_status')=='VERIFIED']
 out=dict(state='MATERIAL_PREPARED',candidate_app=str(CANDIDATE),config_path=str(config),state_root=str(state),target_date='20261013',phase='RETROSPECTIVE',
  original_product_ref=ref,binding_pin=pin,publication_window=manifest['window'],actual_cutoff=ctx.cutoff,
  full_observed_count=product['observed_count'],body_complete_count=sum(r['body_complete'] for r in product['rows']),
  eligible_article_ids=eligible,batch_gaps=batch.gaps,network_calls=0,model_calls=0,capture_enabled=False,lease_auto_granted=False)
 if args.execute_model:
  if args.article_id not in eligible:raise ValueError('ARTICLE_NOT_COMPLETE_OR_ELIGIBLE')
  from apps.api.v35_api.app import create_app
  from fastapi.testclient import TestClient
  app=create_app(data_root=isolated/'api-auxiliary-v7',manager_workbench_config=cfg)
  service=app.state.manager_workbench_service
  with TestClient(app) as client:
   job=service.submit('20261013',Phase.RETROSPECTIVE,lanes=[Lane.ANNOUNCEMENT],cutoff=datetime.now(HK),
     scope_refs={'canary_article_id':args.article_id,'canary_mode':'SINGLE_ARTICLE','capture_binding_pin':pin})
   last=time.monotonic()
   while True:
    job=service.jobs.get(job.job_id)
    if job.state not in {JobState.QUEUED,JobState.RUNNING}:break
    if time.monotonic()-last>=30:
     print(json.dumps({'progress_job_id':job.job_id,'state':job.state.value,'step':job.step}),flush=True);last=time.monotonic()
    time.sleep(.2)
   response=client.get('/api/v4/manager-workbench/days/20261013',params={'run_id':job.run_id,'phase':'RETROSPECTIVE'})
   data=response.json().get('data') or {};snapshot=data.get('snapshot') or {}
   plan=service.store.get_plan('20261013',run_id=job.run_id)
   out.update(state=job.state.value,job_id=job.job_id,run_id=job.run_id,product_sha256=snapshot.get('product_sha256'),
      article_id=args.article_id,http_status=response.status_code,counts=data.get('counts'),failure_code=job.failure_code,
      model_calls=len([r for r in job.execution_refs if r.get('role')]),execution_refs=job.execution_refs,
      immutable_saved_readback=bool(plan and plan.product_sha256==snapshot.get('product_sha256')),
      url=f"http://127.0.0.1:18873/manager-selection/?date=20261013&phase=RETROSPECTIVE&run_id={job.run_id}")
 output=isolated/('v7-single-canary.json' if args.execute_model else 'v7-material-preparation.json')
 output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False),flush=True)
 return 0 if not args.execute_model or out['state']=='SUCCEEDED' and out['immutable_saved_readback'] else 5

if __name__=='__main__':raise SystemExit(main())
