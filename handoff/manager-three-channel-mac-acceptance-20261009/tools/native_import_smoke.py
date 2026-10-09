#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import importlib
import json
import os
import sys
import traceback
from pathlib import Path
E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
APP=E/"candidate/mac_source_v2"
os.environ["PYTHONDONTWRITEBYTECODE"]="1"
sys.dont_write_bytecode=True
os.chdir(APP)
sys.path.insert(0,str(APP))
targets=[
    "v4.manager_research.workspace_plan",
    "v4.manager_research.workspace_announcements",
    "v4.manager_research.plan_owner_dispatch",
    "upstreams.v3_shared_data.shared_data.hk_security_master",
    "ops.run_manager_daily_announcement",
    "apps.api.v35_api.manager_research_router",
]
results=[]
for name in targets:
    try:
        module=importlib.import_module(name)
        path=getattr(module,"__file__",None)
        if path:
            resolved=Path(path).resolve()
            try: rel=resolved.relative_to(APP).as_posix(); within=True
            except ValueError: rel=None; within=False
            sha=hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.is_file() else None
        else:
            resolved=None;rel=None;within=False;sha=None
        result={"module":name,"status":"IMPORTED","__file__":str(resolved) if resolved else None,
                "relative_path":rel,"sha256":sha,"within_source_root":within}
    except BaseException as exc:
        result={"module":name,"status":"IMPORT_FAILED","error_type":type(exc).__name__,
                "error":str(exc),"traceback":traceback.format_exc()}
    print("NATIVE_IMPORT="+json.dumps(result,ensure_ascii=False))
    results.append(result)
canonical=[]
for name,module in sorted(sys.modules.items()):
    raw=getattr(module,"__file__",None)
    if not raw: continue
    p=Path(raw).resolve()
    if "/Users/lexi/Desktop/学习/v4_app/" in str(p) and ".venv/" not in str(p):
        canonical.append({"module":name,"__file__":str(p)})
passed=all(x["status"]=="IMPORTED" and x["within_source_root"] for x in results) and not canonical
receipt={"schema_version":"native_import_smoke.v1","cwd":os.getcwd(),"python":sys.executable,
         "python_version":sys.version,"app_root":str(APP),"targets":results,
         "canonical_code_modules":canonical,"server_started":False,"background_owner_started":False,
         "business_io":False,"pass":passed}
(E/"evidence/native_import_smoke.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("NATIVE_IMPORT_SUMMARY="+json.dumps({"pass":passed,"imported":sum(x["status"]=="IMPORTED" for x in results),
     "failed":sum(x["status"]=="IMPORT_FAILED" for x in results),"canonical_code_modules":len(canonical)},ensure_ascii=False))
raise SystemExit(0 if passed else 1)
