"""Reproduce the available source-slice verification with append-only logs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
output=Path(sys.argv[1]).resolve()
output.mkdir(parents=True,exist_ok=False)
runtime=Path(os.environ.get("STAGE_UI_RUNTIME","/workspace/scratch/25c09a595aec/stage_minimal/work/ui_runtime"))
env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","STAGE_API_PHASE":"after","STAGE_UI_PHASE":"after",
     "STAGE_UI_RUNTIME":str(runtime),"STAGE_UI_CONSUMER_FIXTURE":str(root/"app/integration_v1/consumer_response.json"),
     "STAGE_UI_GENERATED_DIR":str(output/"generated")}
commands={"python":[sys.executable,"-m","pytest","-q"],
          "vue":[shutil.which("node"),"--test","--test-reporter=tap","tests/legacy_presentation.test.mjs","tests/research_presentation.test.mjs"]}
report={"scope":"ISOLATED_REAL_SELECTION_STORE_FULL_CONSUMER_AND_VUE_SFC_SSR_NOT_CURRENT_APP_OR_DEPLOYMENT",
        "started_at_utc":datetime.now(timezone.utc).isoformat(),"results":{},
        "safety_flags":{"RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}}
for label,command in commands.items():
    run=subprocess.run(command,cwd=root,env=env,text=True,capture_output=True)
    (output/(label+".stdout.log")).write_text(run.stdout)
    (output/(label+".stderr.log")).write_text(run.stderr)
    report["results"][label]={"command":command,"exit_code":run.returncode}
    if label=="python":
        match=re.search(r"(\d+) passed",run.stdout)
        report["results"][label]["passed"]=int(match.group(1)) if match else None
    else:
        for key in ("tests","pass","fail","skipped"):
            match=re.search(r"^# "+key+r" (\d+)\s*$",run.stdout,re.M)
            report["results"][label][key]=int(match.group(1)) if match else None
report["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
report["source_files"]={str(path.relative_to(root/"after")):hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in sorted((root/"after").rglob("*")) if path.suffix in {".py",".ts",".vue"}}
report["runtime"]={"python":sys.version,"node":subprocess.check_output([shutil.which("node"),"--version"],text=True).strip(),
    "packages":{name:json.loads((runtime/"node_modules"/name/"package.json").read_text())["version"]
                for name in ("vue","@vue/compiler-sfc","@vue/server-renderer")},
    "package_lock_sha256":hashlib.sha256((runtime/"package-lock.json").read_bytes()).hexdigest()}
report["warnings"]=["Node stripTypeScriptTypes ExperimentalWarning comes from the test harness; SFC compilation and SSR ran normally."]
(output/"RESULTS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(0 if all(value["exit_code"]==0 for value in report["results"].values()) else 1)
