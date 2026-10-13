"""Coordinator-only temporary GET readback, using the exact active or explicit candidate."""
import argparse,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def resolve_candidate(args):
 sys.path.insert(0,str(ROOT))
 from ops.api_release_integration import read_active_release,inventory_tree,inventory_digest
 if args.candidate_app_root:
  candidate=Path(args.candidate_app_root).resolve(strict=True)
  if not candidate.is_relative_to(HERE) or not args.candidate_manifest_sha256:raise ValueError('EXACT_HANDOFF_CANDIDATE_MANIFEST_REQUIRED')
  expected=args.candidate_manifest_sha256
 else:
  active=read_active_release(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'))
  candidate=Path(active['app_root']);expected=active['release_manifest_sha256']
 mp=candidate.parent/'release-manifest.json';raw=mp.read_bytes();m=json.loads(raw)
 if sha(raw)!=expected or m.get('schema_version')!='v4.release_candidate.v1' or m['candidate']['app_root']!=str(candidate) or m['candidate']['root']!=str(candidate.parent):raise ValueError('CANDIDATE_MANIFEST_IDENTITY_DRIFT')
 inventory=inventory_tree(candidate)
 if inventory!=m['application_inventory']['entries'] or inventory_digest(inventory)!=m['application_inventory']['aggregate_sha256']:raise ValueError('CANDIDATE_INVENTORY_DRIFT')
 if args.reviewed_source_receipt:
  receipt=json.loads(Path(args.reviewed_source_receipt).read_text())
  for item in receipt['scope']:
   if sha((candidate/item['path']).read_bytes())!=item['after_sha256']:raise ValueError('REVIEWED_CANDIDATE_SOURCE_DRIFT:'+item['path'])
 return candidate,expected


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--proof',required=True);p.add_argument('--port',type=int,default=18873)
 p.add_argument('--candidate-app-root');p.add_argument('--candidate-manifest-sha256');p.add_argument('--reviewed-source-receipt');p.add_argument('--check-only',action='store_true');args=p.parse_args()
 if not 1024<=args.port<=65535 or args.port in {8873,8874,8875}:raise ValueError('TEMP_PORT_REQUIRED')
 candidate,manifest_sha=resolve_candidate(args);sys.path.insert(0,str(candidate))
 from v4.manager_workbench.config import load_config
 from v4.manager_workbench.store import WorkbenchStore
 proof=json.loads(Path(args.proof).read_text());cfg=load_config(proof['config_path'])
 if cfg.capture_enabled or cfg.capture_lease_token:raise ValueError('SAVED_READBACK_CAPTURE_MUST_BE_DISABLED')
 if not cfg.state_root.resolve().is_relative_to((HERE/'.tmp').resolve()) and '/T/mwb-live-capture-canary-' not in str(cfg.state_root.resolve()):raise ValueError('ISOLATED_STATE_REQUIRED')
 saved=WorkbenchStore(cfg.state_root).read_plan(proof['run_id'])
 if saved is None or saved.product_sha256!=proof['product_sha256'] or saved.context.target_date!=proof['target_date']:raise ValueError('SAVED_PROOF_IDENTITY_DRIFT')
 info=dict(url=f"http://127.0.0.1:{args.port}/manager-selection/?date={proof['target_date']}&phase={proof['phase']}&run_id={proof['run_id']}",candidate_app_root=str(candidate),candidate_manifest_sha256=manifest_sha,run_id=saved.run_id,product_sha256=saved.product_sha256,model_calls=0,capture_enabled=False,formal_deployment=False,check_only=args.check_only)
 if args.check_only:print(json.dumps(info),flush=True);return
 from apps.api.v35_api.app import create_app
 from fastapi.responses import JSONResponse
 import uvicorn
 app=create_app(data_root=cfg.state_root.parent/'api-auxiliary-saved-readback',manager_workbench_config=cfg)
 @app.middleware('http')
 async def read_only(request,call_next):
  if request.method not in {'GET','HEAD','OPTIONS'}:return JSONResponse({'temporary_verification':'SAVED_READBACK_ONLY'},status_code=403)
  return await call_next(request)
 print(json.dumps(info),flush=True)
 uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
if __name__=='__main__':main()
