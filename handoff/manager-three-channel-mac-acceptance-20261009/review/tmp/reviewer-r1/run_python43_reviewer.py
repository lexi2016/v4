#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
APP=E/"candidate/mac_source_v2"
PACKAGE=E/"incoming/manager-three-channel-repair-20261009"
RUNNER=PACKAGE/"tools/run_scoped_tests.py"
JUNIT=E/"review/tmp/reviewer-r1/python43.junit.xml"
TMP=Path(os.environ["V4_MANAGER_TEST_TMPDIR"]).resolve()
TMP.mkdir(parents=True,exist_ok=True)
os.environ["PYTHONDONTWRITEBYTECODE"]="1"
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
os.environ["TMPDIR"]=str(TMP)
tempfile.tempdir=str(TMP)
before_cwd=os.getcwd()
sys.argv=[str(RUNNER),"--app-root",str(APP),"--junitxml",str(JUNIT)]
exit_code=1
try:
    runpy.run_path(str(RUNNER),run_name="__main__")
    exit_code=0
except SystemExit as exc:
    exit_code=int(exc.code or 0)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
module_sources=[]
module_files=set()
for name,module in sorted(sys.modules.items()):
    raw_path=getattr(module,"__file__",None)
    if not raw_path: continue
    p=Path(raw_path).resolve()
    try: rel=p.relative_to(APP).as_posix()
    except ValueError: continue
    if (rel.startswith("apps/api/v35_api/") or rel.startswith("v4/manager_research/") or
        rel.startswith("upstreams/v3_shared_data/") or rel=="ops/run_manager_daily_announcement.py" or
        rel.startswith("tests/test_manager_") or rel=="tests/r3_scoped_loader.py"):
        if str(p) in module_files: continue
        module_files.add(str(p))
        module_sources.append({"module":name,"__file__":str(p),"relative_path":rel,"sha256":sha(p)})
canonical_code=[]
for name,module in sorted(sys.modules.items()):
    raw_path=getattr(module,"__file__",None)
    if not raw_path: continue
    p=Path(raw_path).resolve()
    if "/Users/lexi/Desktop/学习/v4_app/" in str(p) and ".venv/" not in str(p):
        canonical_code.append({"module":name,"__file__":str(p)})
identity={"schema_version":"scoped_python_test_identity.v1","cwd_before":before_cwd,"cwd_after":os.getcwd(),
          "python":sys.executable,"python_version":sys.version,"runner":str(RUNNER),
          "runner_sha256":sha(RUNNER),"app_root":str(APP),"junit_xml":str(JUNIT),
          "isolated_temp_root":str(TMP),"module_sources":module_sources,
          "canonical_code_modules":canonical_code,"result_exit_code":exit_code,
          "identity_pass":not canonical_code and bool(module_sources)}
print("PYTHON_MODULE_IDENTITY="+json.dumps(identity,ensure_ascii=False))
raise SystemExit(exit_code)
