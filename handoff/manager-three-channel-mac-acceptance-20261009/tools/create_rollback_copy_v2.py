#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path
E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
source=E/"candidate/mac_source_v2"
target=E/"candidate/mac_rollback_v2"
manifest=json.loads((E/"evidence/source_baseline_manifest_v2.json").read_text(encoding="utf-8"))
expected={x["path"]:{"bytes":x["bytes"],"sha256":x["sha256"]} for x in manifest["files"]}
if target.exists() or target.is_symlink():
    raise SystemExit("ROLLBACK_TARGET_ALREADY_EXISTS")
def inventory(root: Path):
    out={}
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError("SYMLINK_NOT_EXPECTED:"+str(p))
        if p.is_file():
            raw=p.read_bytes()
            out[p.relative_to(root).as_posix()]={"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    return out
before=inventory(source)
if before != expected:
    raise SystemExit("SOURCE_BASELINE_DIFFERS:"+json.dumps({
        "missing":sorted(set(expected)-set(before)),
        "extra":sorted(set(before)-set(expected)),
        "different":[p for p in expected.keys() & before.keys() if expected[p]!=before[p]]
    }))
shutil.copytree(source,target,copy_function=shutil.copy2,symlinks=False)
after=inventory(target)
passed=after==expected
receipt={"schema_version":"rollback_copy_receipt.v1","source_root":str(source),"rollback_root":str(target),
         "baseline_file_count":len(expected),"copied_file_count":len(after),
         "baseline_bytes":sum(x["bytes"] for x in expected.values()),
         "copied_bytes":sum(x["bytes"] for x in after.values()),"exact_match":passed,
         "symlink_count":0,"files":[{"path":p,**after[p]} for p in sorted(after)]}
(E/"evidence/rollback_copy_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:receipt[k] for k in ["rollback_root","baseline_file_count","copied_file_count","baseline_bytes","copied_bytes","exact_match"]},ensure_ascii=False))
raise SystemExit(0 if passed else 1)
