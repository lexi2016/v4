import hashlib, json, sys
from pathlib import Path
E=Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_MAC_ACCEPTANCE_20261009")
OUT=E/"review/tmp/reviewer-r1"
SRC=E/"candidate/mac_source_v2"
ROLL=E/"candidate/mac_rollback_v2"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inv(root):
    files={}
    links={}
    for p in sorted(root.rglob("*")):
        rel=p.relative_to(root).as_posix()
        if p.is_symlink():
            links[rel]=str(p.readlink())
        elif p.is_file():
            files[rel]={"bytes":p.stat().st_size,"sha256":sha(p)}
    return {"files":files,"symlinks":links}
candidate=inv(SRC)
rollback=inv(ROLL)
(E/"review/tmp/reviewer-r1/candidate_tree_current.json").write_text(json.dumps(candidate,sort_keys=True,indent=2)+"\n")
base=json.loads((E/"evidence/source_baseline_manifest_v2.json").read_text())
patch=json.loads((E/"evidence/source_patch_diff_receipt.json").read_text())
support=json.loads((E/"evidence/test_support_mac_source_v2.json").read_text())
rollback_receipt=json.loads((E/"evidence/rollback_copy_receipt.json").read_text())
rollback_support=json.loads((E/"evidence/test_support_mac_rollback_v2.json").read_text())
native=json.loads((E/"evidence/native_import_smoke.json").read_text())
base_rows={x["path"]:x for x in base["files"]}
changed=patch["changed_existing"]
added=patch["added_files"]
support_rows={x["path"]:x for x in support["files"]}
errors=[]
expected=set(base_rows)|set(added)|{p for p,r in support_rows.items() if r["state"]=="TO_ADD"}
if set(candidate["files"])!=expected:
    errors.append({"check":"candidate_exact_path_set","missing":sorted(expected-set(candidate["files"]))[:30],"extra":sorted(set(candidate["files"])-expected)[:30]})
for path,row in base_rows.items():
    if path in changed: continue
    actual=candidate["files"].get(path)
    if not actual or actual["sha256"]!=row["sha256"] or actual["bytes"]!=row["bytes"]:
        errors.append({"check":"baseline_preserved","path":path})
for path,row in changed.items():
    actual=candidate["files"].get(path)
    if not actual or actual["sha256"]!=row["sha256"] or actual["bytes"]!=row["bytes"]:
        errors.append({"check":"delivery_changed_file","path":path})
for path,row in added.items():
    actual=candidate["files"].get(path)
    if not actual or actual["sha256"]!=row["sha256"] or actual["bytes"]!=row["bytes"]:
        errors.append({"check":"delivery_added_file","path":path})
for path,row in support_rows.items():
    actual=candidate["files"].get(path)
    if not actual or actual["sha256"]!=row["sha256"] or actual["bytes"]!=row["bytes"]:
        errors.append({"check":"test_support_file","path":path})
protected=[]
for row in patch["protected_issue32_files"]:
    actual=candidate["files"].get(row["path"],{})
    ok=actual.get("sha256")==row["expected_sha256"]
    protected.append({"path":row["path"],"actual_sha256":actual.get("sha256"),"expected_sha256":row["expected_sha256"],"pass":ok})
    if not ok: errors.append({"check":"issue32_protected","path":row["path"]})
native_checks=[]
for row in native["targets"]:
    p=SRC/row["relative_path"]
    ok=(p.is_file() and p.resolve()==SRC/row["__file__"] and sha(p)==row["sha256"] and p.resolve().is_relative_to(SRC))
    native_checks.append({"module":row["module"],"pass":ok,"relative_path":row["relative_path"],"sha256":sha(p) if p.is_file() else None})
    if not ok: errors.append({"check":"native_import_evidence","module":row["module"]})
if native["canonical_code_modules"] or native["server_started"] or native["background_owner_started"] or native["business_io"]:
    errors.append({"check":"native_import_scope"})
rollback_files={x["path"]:{"bytes":x["bytes"],"sha256":x["sha256"]} for x in rollback_receipt["files"]}
rollback_added={x["path"]:{"bytes":x["bytes"],"sha256":x["sha256"]} for x in rollback_support["files"] if x["state"]=="TO_ADD"}
rollback_expected={**rollback_files,**rollback_added}
rollback_match=(rollback["files"]==rollback_expected and not rollback["symlinks"])
if not rollback_match:
    errors.append({"check":"rollback_full_tree_plus_test_support","actual_files":len(rollback["files"]),"baseline_files":len(rollback_files),"support_files":len(rollback_added),"symlinks":rollback["symlinks"]})
pre=json.loads((E/"review/tmp/reviewer-r1/candidate_tree_pretests.json").read_text())
candidate_unchanged=(candidate["files"]==pre["files"] and candidate["symlinks"]==pre["symlinks"])
if not candidate_unchanged:
    errors.append({"check":"candidate_unchanged_during_reviewer_tests"})
report={"candidate_file_count":len(candidate["files"]),"candidate_bytes":sum(x["bytes"] for x in candidate["files"].values()),
        "candidate_symlinks":candidate["symlinks"],"expected_file_count":len(expected),
        "baseline_unchanged_verified":len(base_rows)-len(changed),"delivery_changed_verified":len(changed),
        "delivery_added_verified":len(added),"test_support_verified":len(support_rows),
        "protected_issue32":protected,"native_import_evidence":native_checks,
        "native_import_pass":native["pass"],"rollback_file_count":len(rollback["files"]),
        "rollback_baseline_restored_with_only_support":rollback_match,"candidate_unchanged_during_reviewer_tests":candidate_unchanged,
        "errors":errors,"pass":not errors}
(OUT/"integrity_initial.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
print(json.dumps(report,ensure_ascii=False,sort_keys=True))
