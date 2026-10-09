#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from pathlib import Path
E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009").resolve()
P=E/"incoming/manager-three-channel-repair-20261009"
R=E/"candidate/mac_source_v2"
package_manifest=json.loads((P/"source_manifest.json").read_text(encoding="utf-8"))
baseline_manifest=json.loads((E/"evidence/source_baseline_manifest_v2.json").read_text(encoding="utf-8"))
baseline={x["path"]:x for x in baseline_manifest["files"]}
def sha(raw): return hashlib.sha256(raw).hexdigest()
actual={}
for p in R.rglob("*"):
    if p.is_symlink(): raise SystemExit("UNEXPECTED_SOURCE_SYMLINK:"+str(p))
    if p.is_file():
        raw=p.read_bytes()
        actual[p.relative_to(R).as_posix()]={"bytes":len(raw),"sha256":sha(raw)}
expected_paths=set(baseline)
changed={}
added={}
for row in package_manifest["files"]:
    if row["after_sha256"] is None: continue
    path=row["path"]
    after={"bytes":row["after_bytes"],"sha256":row["after_sha256"]}
    if row["before_sha256"] is None:
        added[path]=after
    elif row["before_sha256"] != row["after_sha256"]:
        changed[path]={"before_bytes":row["before_bytes"],"before_sha256":row["before_sha256"],**after,
                       "profile":row["profile"],"change":row["change"]}
    else:
        expected_paths.add(path)
expected_paths |= set(added)
unexpected=sorted(set(actual)-expected_paths)
missing=sorted(expected_paths-set(actual))
mismatches=[]
for path,expected in baseline.items():
    if path in changed: continue
    if actual.get(path)!= {"bytes":expected["bytes"],"sha256":expected["sha256"]}:
        mismatches.append({"path":path,"expected":expected,"actual":actual.get(path)})
for path,expected in {**added,**{k:{"bytes":v["bytes"],"sha256":v["sha256"]} for k,v in changed.items()}}.items():
    if actual.get(path)!=expected:
        mismatches.append({"path":path,"expected":expected,"actual":actual.get(path)})
preserved=[]
for row in package_manifest.get("preserve",[]):
    if "api_r3_candidate" in row["profiles"]:
        raw=(R/row["path"]).read_bytes()
        preserved.append({"path":row["path"],"expected_sha256":row["sha256"],"actual_sha256":sha(raw),"pass":sha(raw)==row["sha256"]})
passed=not unexpected and not missing and not mismatches and all(x["pass"] for x in preserved)
receipt={"schema_version":"three_channel_patch_tree_diff.v1","source_root":str(R),
         "baseline_file_count":len(baseline),"after_file_count":len(actual),
         "unchanged_baseline_file_count":len(baseline)-len(changed),
         "changed_existing":changed,"added_files":added,"unexpected":unexpected,"missing":missing,
         "mismatches":mismatches,"protected_issue32_files":preserved,"pass":passed,
         "current_runtime_source_verified":False,"deployment_or_live_integration_claimed":False}
(E/"evidence/source_patch_diff_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"baseline_file_count":len(baseline),"after_file_count":len(actual),
    "unchanged_baseline_file_count":receipt["unchanged_baseline_file_count"],
    "changed_existing":len(changed),"added":len(added),"unexpected":len(unexpected),
    "missing":len(missing),"mismatches":len(mismatches),"protected_all_pass":all(x["pass"] for x in preserved),"pass":passed},ensure_ascii=False))
raise SystemExit(0 if passed else 1)
