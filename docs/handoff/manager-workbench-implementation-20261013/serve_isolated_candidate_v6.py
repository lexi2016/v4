"""Temporary candidate UI/API readback. Explicit invocation by the coordinator.

No scheduler, model rerun, original state write, or production activation. Stop
this foreground process after inspection. POST is blocked for saved-readback.
"""
import argparse
import json
import sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--case',choices=['real','synthetic'],required=True)
parser.add_argument('--port',type=int,default=18873)
args=parser.parse_args()
if not 1024<=args.port<=65535 or args.port in {8873,8874,8875}:raise SystemExit('TEMP_PORT_REQUIRED')
HANDOFF=Path(__file__).resolve().parent
CANDIDATE=HANDOFF/'deployment-deltas/isolated-api-candidate-v6/app'
sys.path.insert(0,str(CANDIDATE))
from apps.api.v35_api.app import create_app
from fastapi.responses import JSONResponse
from v4.manager_workbench.config import WorkbenchConfig
import uvicorn
if args.case=='synthetic':
    proof=json.loads((HANDOFF/'integration-active-api-v6-http-receipt.json').read_text())
    config=WorkbenchConfig.model_validate(json.loads(Path(proof['config_path']).read_text()))
    date='20261013';phase='MANUAL';run=proof['run_id']
else:
    proof=json.loads((HANDOFF/'real-single-article-owner-identity-v3-canary-receipt.json').read_text())
    config=WorkbenchConfig(state_root=Path(proof['state_directory'])/'derived',
        manager_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research'),
        shared_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'),
        stage_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'),
        us_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data'),relation_root=Path('/Users/lexi/Desktop/学习/v4_app'),
        dynamic_source_bindings=True,codex_binary=Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'))
    date='20261012';phase='RETROSPECTIVE';run=proof['run_id']
app=create_app(data_root=config.state_root.parent/'api-auxiliary',manager_workbench_config=config)
@app.middleware('http')
async def saved_readback_only(request,call_next):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        return JSONResponse({'temporary_verification':'SAVED_READBACK_ONLY'},status_code=403)
    return await call_next(request)
print(json.dumps(dict(case=args.case,plan_run_id=run,url=f'http://127.0.0.1:{args.port}/manager-selection/?date={date}&phase={phase}&run_id={run}',
    state_root=str(config.state_root),new_model_execution='DISABLED_FOR_READBACK',formal_deployment=False)),flush=True)
uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
