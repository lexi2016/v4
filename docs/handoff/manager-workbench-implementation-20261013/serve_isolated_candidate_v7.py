"""Coordinator-only temporary GET readback of a saved V7 single canary."""
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--proof',required=True);p.add_argument('--port',type=int,default=18873);args=p.parse_args()
if not 1024<=args.port<=65535 or args.port in {8873,8874,8875}:raise SystemExit('TEMP_PORT_REQUIRED')
HERE=Path(__file__).resolve().parent;candidate=HERE/'deployment-deltas/isolated-api-candidate-v7-final/app';sys.path.insert(0,str(candidate))
from v4.manager_workbench.config import load_config
from apps.api.v35_api.app import create_app
from fastapi.responses import JSONResponse
import uvicorn
proof=json.loads(Path(args.proof).read_text());cfg=load_config(proof['config_path'])
if cfg.capture_enabled:raise ValueError('SAVED_READBACK_CAPTURE_MUST_BE_DISABLED')
app=create_app(data_root=cfg.state_root.parent/'api-auxiliary-v7',manager_workbench_config=cfg)
@app.middleware('http')
async def read_only(request,call_next):
 if request.method not in {'GET','HEAD','OPTIONS'}:return JSONResponse({'temporary_verification':'SAVED_READBACK_ONLY'},status_code=403)
 return await call_next(request)
print(json.dumps(dict(url=f"http://127.0.0.1:{args.port}/manager-selection/?date={proof['target_date']}&phase={proof['phase']}&run_id={proof['run_id']}",model_calls=0,capture_enabled=False,formal_deployment=False)),flush=True)
uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
