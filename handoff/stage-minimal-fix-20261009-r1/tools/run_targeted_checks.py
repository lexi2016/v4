"""Run the shipped source-slice/SSR checks. Does not start the application."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SUITES = [
    ("quote_author", "quote_fields", ["tests"], 65),
    ("writer_author", "receipt_binding", ["tests/test_owner_receipt_binding.py", "tests/test_slot_receipt_wiring.py"], 39),
    ("api_author", "api_ui", ["tests"], 28),
    ("clock_author", "entrypoint_clock", ["tests"], 29),
    ("quote_independent", "hk_entrypoint/quote_review", ["tests"], 15),
    ("api_independent", "hk_entrypoint/api_review", ["tests"], 34),
    ("writer_independent", "hk_entrypoint/receipt_review", ["tests"], 7),
    ("clock_independent", "hk_entrypoint/clock_review", ["tests"], 22),
]
NODE_SUITES = [
    ("ui_author", "ui_presentation", "tests/presentation.test.mjs", 23),
    ("ui_independent", "ui_review", "tests/independent_presentation.test.mjs", 25),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True, help="Confirmed Node 24 executable path")
    parser.add_argument("--output", type=Path, required=True, help="New directory outside this package")
    parser.add_argument("--ui-runtime", type=Path, default=ROOT/"work/ui_runtime")
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    if output == ROOT or ROOT in output.parents:
        parser.error("Evidence output must be outside the immutable delivery package")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", STAGE_UI_PHASE="after",
               STAGE_CLOCK_VARIANT="after", STAGE_QUOTE_PHASE="after",
               STAGE_UI_RUNTIME=str(args.ui_runtime.expanduser().absolute()))
    results=[]
    for name, relative, tests, expected in PYTHON_SUITES:
        path=output/name;path.mkdir()
        command=[sys.executable,"-m","pytest","-q","-p","no:cacheprovider",*tests,
                 "--junitxml="+str(path/"junit.xml")]
        results.append(run(name, ROOT/"work"/relative, command, path, env, expected, "pytest"))
    for name,relative,test,expected in NODE_SUITES:
        path=output/name;path.mkdir()
        command=[args.node,"--test","--test-reporter=tap",test]
        results.append(run(name,ROOT/"work"/relative,command,path,env,expected,"node"))
    report={"status":"PASS_SOURCE_AND_SSR_ONLY" if all(r["passed"] for r in results) else "FAIL",
            "python":sys.version,"platform":platform.platform(),"suites":results,
            "scope":"PINNED_SOURCE_SLICES_REAL_STORE_PROTOCOL_AND_COMPONENT_SSR_WITH_EXPLICIT_BOUNDARIES",
            "mac_integration":"NOT_RUN","deployment":"NOT_RUN","real_stage":"NOT_RUN",
            "api_ui":"NOT_RUN","natural":"NOT_RUN"}
    (output/"TEST_RESULTS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"suites":len(results),"output":str(output)},ensure_ascii=False),flush=True)
    return 0 if all(r["passed"] for r in results) else 1

def run(name,cwd,command,path,env,expected,kind):
    started=datetime.now(timezone.utc).isoformat()
    proc=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,timeout=120)
    (path/"stdout.log").write_text(proc.stdout)
    (path/"stderr.log").write_text(proc.stderr)
    if kind=="pytest":
        document=ET.parse(path/"junit.xml").getroot()
        suites=[document] if document.tag=="testsuite" else list(document.iter("testsuite"))
        counts={key:sum(int(s.get(key,"0")) for s in suites) for key in ("tests","failures","errors","skipped")}
    else:
        def count(label):
            match=re.search(r"^# "+label+r" (\d+)\s*$",proc.stdout,re.M)
            return int(match.group(1)) if match else None
        counts={"tests":count("tests"),"failures":count("fail"),"errors":count("cancelled"),"skipped":count("skipped")}
    passed=proc.returncode==0 and counts==dict(tests=expected,failures=0,errors=0,skipped=0)
    result={"name":name,"command":command,"cwd":str(cwd),"started_at_utc":started,
            "finished_at_utc":datetime.now(timezone.utc).isoformat(),"exit_code":proc.returncode,
            "expected_tests":expected,**counts,"passed":passed}
    (path/"execution.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"suite":name,**counts,"passed":passed}),flush=True)
    return result

if __name__=="__main__":
    raise SystemExit(main())
