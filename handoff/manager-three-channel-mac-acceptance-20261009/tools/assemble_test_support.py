#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
PACKAGE=E/"incoming/manager-three-channel-repair-20261009"
manifest=json.loads((PACKAGE/"test_source_manifest.json").read_text(encoding="utf-8"))
rows=manifest["unchanged_support"]
parser=argparse.ArgumentParser()
parser.add_argument("--targets",nargs="+",required=True)
args=parser.parse_args()
prepared=[]
def sha(raw): return hashlib.sha256(raw).hexdigest()
for raw_target in args.targets:
    target=Path(raw_target).resolve()
    if not target.is_dir() or target.is_symlink() or E/"candidate" not in target.parents:
        raise SystemExit("UNSAFE_OR_NONCANDIDATE_TEST_ROOT:"+str(target))
    pending=[]
    details=[]
    for row in rows:
        rel=PurePosixPath(row["path"])
        archive=PurePosixPath(row["archive_path"])
        if not row["path"] or rel.is_absolute() or ".." in rel.parts or str(rel)!=row["path"]:
            raise SystemExit("INVALID_SUPPORT_PATH:"+row["path"])
        if archive.is_absolute() or ".." in archive.parts or str(archive)!=row["archive_path"]:
            raise SystemExit("INVALID_ARCHIVE_PATH:"+row["archive_path"])
        src=PACKAGE/row["archive_path"]
        raw=src.read_bytes()
        if len(raw)!=row["bytes"] or sha(raw)!=row["sha256"]:
            raise SystemExit("SUPPORT_PAYLOAD_MISMATCH:"+row["path"])
        dst=target/Path(*rel.parts)
        current=target
        for part in rel.parts:
            current=current/part
            if current.is_symlink():
                raise SystemExit("SYMLINK_TARGET_REJECTED:"+row["path"])
        try: dst.resolve().relative_to(target)
        except ValueError: raise SystemExit("TARGET_ESCAPE:"+row["path"])
        if dst.exists():
            existing=dst.read_bytes()
            if existing!=raw:
                raise SystemExit("EXISTING_SUPPORT_DIFFERS:"+str(target)+":"+row["path"])
            state="EXISTING_MATCH"
        else:
            pending.append((dst,raw,row))
            state="TO_ADD"
        details.append({"path":row["path"],"archive_path":row["archive_path"],
                        "bytes":len(raw),"sha256":sha(raw),"state":state})
    prepared.append({"target":target,"pending":pending,"details":details})
# All destinations are checked before any support file is written.
for item in prepared:
    for dst,raw,row in item["pending"]:
        dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_bytes(raw)
receipts=[]
for item in prepared:
    target=item["target"]
    for detail in item["details"]:
        raw=(target/detail["path"]).read_bytes()
        detail["actual_bytes"]=len(raw)
        detail["actual_sha256"]=sha(raw)
        detail["pass"]=detail["bytes"]==len(raw) and detail["sha256"]==sha(raw)
    passed=all(x["pass"] for x in item["details"])
    receipt={"schema_version":"test_support_assembly.v1","target_root":str(target),
             "fixed_commit":"b19eb112bd641ca97cac1246af7c81d8873641f4",
             "support_count":len(item["details"]),
             "added_count":sum(x["state"]=="TO_ADD" for x in item["details"]),
             "existing_matching_count":sum(x["state"]=="EXISTING_MATCH" for x in item["details"]),
             "files":item["details"],"pass":passed}
    name=target.name
    (E/"evidence"/("test_support_"+name+".json")).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    receipts.append({"target":str(target),"support_count":receipt["support_count"],"added_count":receipt["added_count"],
                     "existing_matching_count":receipt["existing_matching_count"],"pass":passed})
print(json.dumps(receipts,ensure_ascii=False))
raise SystemExit(0 if all(x["pass"] for x in receipts) else 1)
