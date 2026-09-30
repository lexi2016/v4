#!/usr/bin/env python3
"""Read-only proof of canonical V4 -> configured release binding for Issue #8 R3."""
from __future__ import annotations
import argparse, hashlib, json, os, plistlib
from pathlib import Path

FILES = [
    "ops/macos_research_panel_daily.py",
    "ops/macos_research_panel_daily_collectors.py",
    "ops/macos_research_panel_daily_gate.py",
    "ops/ensure_hk_security_master.py",
    "infrastructure/scheduling/executor_registry.py",
    "infrastructure/scheduling/executor_registry_review.py",
    "contracts/runtime_workloads.json",
]

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--canonical", required=True)
    ap.add_argument("--plist", required=True)
    ap.add_argument("--output", required=True)
    ns=ap.parse_args()
    canonical=Path(ns.canonical).resolve()
    plist=Path(ns.plist).resolve()
    out=Path(ns.output)
    result={"schema_version":"v4.issue8.r3.source_release_binding.v1","status":"CANNOT_CONFIRM",
            "canonical_root":str(canonical),"plist":str(plist),"files":[],"gaps":[]}
    try:
        p=plistlib.loads(plist.read_bytes())
    except Exception as exc:
        result["gaps"].append("PLIST_READ_FAILED:"+type(exc).__name__)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)); return 2
    args=p.get("ProgramArguments") or []
    roots=[Path(x).resolve() for x in args if isinstance(x,str) and "/releases/" in x and x.endswith("/app")]
    if not roots:
        result["gaps"].append("CONFIGURED_RELEASE_APP_ROOT_NOT_FOUND")
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)); return 1
    release=roots[0]
    result["configured_release_root"]=str(release)
    manifest=release.parent/"release-manifest.json"
    if manifest.is_file():
        result["release_manifest_sha256"]=sha(manifest)
        try: result["release_manifest"]=json.loads(manifest.read_text())
        except Exception: result["gaps"].append("RELEASE_MANIFEST_JSON_INVALID")
    else:
        result["gaps"].append("RELEASE_MANIFEST_MISSING")
    all_equal=True
    for rel in FILES:
        c=canonical/rel; r=release/rel
        row={"path":rel,"canonical_exists":c.is_file(),"release_exists":r.is_file()}
        if c.is_file(): row["canonical_sha256"]=sha(c)
        if r.is_file(): row["release_sha256"]=sha(r)
        row["byte_equal"]=bool(c.is_file() and r.is_file() and row["canonical_sha256"]==row["release_sha256"])
        if not row["byte_equal"]: all_equal=False
        result["files"].append(row)
    git_head=canonical/".git"
    # Do not infer Git identity when .git is unavailable or indirect.
    result["canonical_git_identity"]="REQUIRES_SEPARATE_GIT_STATUS_CAPTURE"
    if not all_equal:
        result["gaps"].append("CANONICAL_RELEASE_RELEVANT_FILES_NOT_BYTE_EQUAL")
    activation=(result.get("release_manifest") or {}).get("activation_status")
    deployment=(result.get("release_manifest") or {}).get("deployment_status")
    if activation not in ("ACTIVATED","PASS") or deployment not in ("DEPLOYED","PASS"):
        result["gaps"].append("CONFIGURED_RELEASE_FORMAL_ACTIVATION_NOT_PROVEN")
    # PASS here means source mapping only. It does not claim deployment.
    result["source_mapping_status"]="PASS" if all_equal else "FAIL"
    result["status"]="PASS_SOURCE_MAPPING_ONLY" if all_equal else "CANNOT_CONFIRM"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if all_equal else 1

if __name__=="__main__": raise SystemExit(main())
