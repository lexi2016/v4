#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
PACKAGE=E/"incoming/manager-three-channel-repair-20261009"
SOURCE=E/"candidate/mac_rollback_v2"
BASELINE=json.loads((E/"evidence/source_baseline_manifest_v2.json").read_text(encoding="utf-8"))
PROFILES=["api_r3_candidate","web_r3_candidate","test_delta"]
LOG_DIR=E/"evidence/rollback_commands"
LOG_DIR.mkdir(parents=True,exist_ok=True)
if not SOURCE.is_dir() or SOURCE.is_symlink():
    raise SystemExit("ROLLBACK_SOURCE_NOT_A_NEW_DIRECTORY")
env=os.environ.copy()
env["PYTHONDONTWRITEBYTECODE"]="1"
records=[]
def invoke(name,argv):
    start=time.monotonic()
    proc=subprocess.run(argv,cwd=SOURCE,env=env,capture_output=True,text=True)
    duration=time.monotonic()-start
    raw=(proc.stdout or "").encode("utf-8")+(proc.stderr or "").encode("utf-8")
    logfile=LOG_DIR/(name+".log")
    logfile.write_bytes(raw)
    records.append({"name":name,"argv":argv,"cwd":str(SOURCE),"exit_code":proc.returncode,
                    "elapsed_seconds":round(duration,6),"log":str(logfile),
                    "log_sha256":hashlib.sha256(raw).hexdigest()})
    if proc.returncode:
        raise RuntimeError("COMMAND_FAILED:"+name)
    return proc.stdout
def verify(profile,side):
    log=LOG_DIR/(f"verify_{side}_{profile}.log")
    proc=subprocess.run([sys.executable,str(PACKAGE/"tools/verify_delivery.py"),"--package",str(PACKAGE),
                         "--profile",profile,"--source-root",str(SOURCE),"--against",side],
                        cwd=SOURCE,env=env,capture_output=True,text=True)
    raw=(proc.stdout or "").encode("utf-8")+(proc.stderr or "").encode("utf-8")
    log.write_bytes(raw)
    records.append({"name":f"verify_{side}_{profile}","argv":[sys.executable,
        str(PACKAGE/"tools/verify_delivery.py"),"--package",str(PACKAGE),"--profile",profile,
        "--source-root",str(SOURCE),"--against",side],"cwd":str(SOURCE),"exit_code":proc.returncode,
        "elapsed_seconds":None,"log":str(log),"log_sha256":hashlib.sha256(raw).hexdigest()})
    if proc.returncode:
        raise RuntimeError("PROFILE_VERIFY_FAILED:"+side+":"+profile)
    return json.loads(proc.stdout)

try:
    before_checks={p:verify(p,"before") for p in PROFILES}
    for profile in PROFILES:
        patch=PACKAGE/"patches"/(profile+".patch")
        invoke("forward_check_"+profile,["git","-C",str(SOURCE),"apply","--check",str(patch)])
        invoke("forward_apply_"+profile,["git","-C",str(SOURCE),"apply",str(patch)])
    after_checks={p:verify(p,"after") for p in PROFILES}
    for profile in reversed(PROFILES):
        patch=PACKAGE/"patches"/(profile+".patch")
        invoke("reverse_check_"+profile,["git","-C",str(SOURCE),"apply","--reverse","--check",str(patch)])
        invoke("reverse_apply_"+profile,["git","-C",str(SOURCE),"apply","--reverse",str(patch)])
    restored_checks={p:verify(p,"before") for p in PROFILES}
    expected={x["path"]:{"bytes":x["bytes"],"sha256":x["sha256"]} for x in BASELINE["files"]}
    actual={}
    for path in SOURCE.rglob("*"):
        if path.is_symlink(): raise RuntimeError("UNEXPECTED_SYMLINK:"+str(path))
        if path.is_file():
            raw=path.read_bytes()
            actual[path.relative_to(SOURCE).as_posix()]={"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    exact=actual==expected
    receipt={"schema_version":"three_channel_temp_patch_rollback.v1","source_root":str(SOURCE),
             "profile_order_forward":PROFILES,"profile_order_reverse":list(reversed(PROFILES)),
             "before_profile_status":{k:v.get("status") for k,v in before_checks.items()},
             "after_profile_status":{k:v.get("status") for k,v in after_checks.items()},
             "restored_before_profile_status":{k:v.get("status") for k,v in restored_checks.items()},
             "baseline_file_count":len(expected),"restored_file_count":len(actual),
             "baseline_bytes":sum(x["bytes"] for x in expected.values()),
             "restored_bytes":sum(x["bytes"] for x in actual.values()),"exact_original_tree_restored":exact,
             "commands":records,"runtime_source_writes":True,"live_business_io":False,
             "deployment_claimed":False,"pass":exact and all(v.get("status")=="PASS" for v in restored_checks.values())}
    (E/"evidence/rollback_patch_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:receipt[k] for k in ["baseline_file_count","restored_file_count","baseline_bytes",
        "restored_bytes","exact_original_tree_restored","pass"]},ensure_ascii=False))
    raise SystemExit(0 if receipt["pass"] else 1)
except Exception as exc:
    fail={"schema_version":"three_channel_temp_patch_rollback.v1","source_root":str(SOURCE),
          "error":str(exc),"commands":records,"pass":False}
    (E/"evidence/rollback_patch_receipt.json").write_text(json.dumps(fail,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pass":False,"error":str(exc),"commands":len(records)},ensure_ascii=False))
    raise SystemExit(1)
