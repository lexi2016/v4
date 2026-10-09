#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
PACKAGE=E/"incoming/manager-three-channel-repair-20261009"
app=Path(os.environ["V4_MANAGER_REPRO_ROOT"]).resolve(strict=True)
tmp=Path(os.environ["V4_MANAGER_TEST_TMPDIR"]).resolve()
tmp.mkdir(parents=True,exist_ok=True)
os.environ["PYTHONDONTWRITEBYTECODE"]="1"
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
os.environ["TMPDIR"]=str(tmp)
tempfile.tempdir=str(tmp)
os.chdir(app)
for path in reversed((app,app/"upstreams",app/"tests")):
    sys.path.insert(0,str(path))
import r3_scoped_loader
if Path(r3_scoped_loader.__file__).resolve()!=app/"tests/r3_scoped_loader.py":
    raise RuntimeError("SCOPED_LOADER_SOURCE_MISMATCH")
r3_scoped_loader.install()
for name in ("v4.manager_research","infrastructure.scheduling"):
    parent,child=name.rsplit(".",1)
    setattr(sys.modules[parent],child,sys.modules[name])
import pytest
test_id="tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection"
junit=Path(os.environ["V4_MANAGER_REPRO_JUNIT"]).resolve()
exit_code=pytest.main(["-q","-p","no:cacheprovider","--tb=short",test_id,"--junitxml",str(junit)])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
source_module=[]
for name,module in sorted(sys.modules.items()):
    raw=getattr(module,"__file__",None)
    if not raw: continue
    p=Path(raw).resolve()
    try: rel=p.relative_to(app).as_posix()
    except ValueError: continue
    if rel.startswith("v4/manager_research/") or rel.startswith("tests/test_manager_"):
        source_module.append({"module":name,"__file__":str(p),"relative_path":rel,"sha256":sha(p)})
identity={"schema_version":"known_failure_repro_identity.v1","cwd":os.getcwd(),"target_root":str(app),
          "python":sys.executable,"python_version":sys.version,"test_id":test_id,
          "junit_xml":str(junit),"isolated_temp_root":str(tmp),"module_sources":source_module,
          "pytest_exit_code":int(exit_code)}
print("KNOWN_FAILURE_MODULE_IDENTITY="+json.dumps(identity,ensure_ascii=False))
raise SystemExit(int(exit_code))
