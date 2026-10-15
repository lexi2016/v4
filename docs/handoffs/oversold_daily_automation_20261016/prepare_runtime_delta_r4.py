#!/usr/bin/env python3
"""Prepare and verify the two-file repair delta against the observed r4 base."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DOC_ROOT=Path(__file__).resolve().parent
SOURCE_ROOT=DOC_ROOT.parents[2]
RELEASE_ID="zsxq-pdf-ocr-scheduler-20261016-r4"
RUNTIME_ROOT=Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")/RELEASE_ID/"app"
RELEASE_MANIFEST=RUNTIME_ROOT.parent/"release-manifest.json"
RELEASE_MANIFEST_SHA256="4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91"
FILES={
    "v4/manager_workbench/oversold_daily.py":
        "1a88ac9c1bb3e1a2d68fff350a69204a65b7ebb782f27512bb4fc1c45f9b0583",
    "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py":
        "62513b42bcd133d3c447b9b797b81c19f43a306c9544ce97a11447db93b54e9e",
}
PREIMAGE_ROOT=DOC_ROOT/"runtime_preimage_r4"
CANDIDATE_ROOT=DOC_ROOT/"runtime_candidate_r4"
PATCH_PATH=DOC_ROOT/"runtime_exact_delta_r4.patch"
MANIFEST_PATH=DOC_ROOT/"runtime_exact_delta_r4.json"
RECEIPT_PATH=DOC_ROOT/"RUNTIME_PREPARED_RECEIPT_R4.md"


class DeltaError(RuntimeError):
    pass


def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path:Path)->str:
    return sha(path.read_bytes())


def _assert_base()->None:
    try:
        resolved=RUNTIME_ROOT.resolve(strict=True)
        manifest_bytes=RELEASE_MANIFEST.read_bytes()
    except OSError as error:
        raise DeltaError("R4_BASE_UNAVAILABLE") from error
    if resolved!=RUNTIME_ROOT or sha(manifest_bytes)!=RELEASE_MANIFEST_SHA256:
        raise DeltaError("R4_BASE_IDENTITY_CHANGED")
    for relative,expected in FILES.items():
        path=RUNTIME_ROOT/relative
        if not path.is_file() or file_sha(path)!=expected:
            raise DeltaError(f"R4_PREIMAGE_SHA_MISMATCH:{relative}")


def _patch_bytes(entries:list[dict])->bytes:
    pieces=[]
    for entry in entries:
        before=(PREIMAGE_ROOT/entry["path"]).read_text(encoding="utf-8").splitlines(keepends=True)
        after=(CANDIDATE_ROOT/entry["path"]).read_text(encoding="utf-8").splitlines(keepends=True)
        pieces.extend(difflib.unified_diff(before,after,fromfile=f"a/{entry['path']}",
            tofile=f"b/{entry['path']}",n=3))
    return "".join(pieces).encode("utf-8")


def prepare()->None:
    _assert_base()
    artifacts=(PREIMAGE_ROOT,CANDIDATE_ROOT,PATCH_PATH,MANIFEST_PATH,RECEIPT_PATH)
    if any(path.exists() for path in artifacts):
        raise DeltaError("R4_DELTA_ARTIFACT_ALREADY_EXISTS")
    entries=[]
    for relative,preimage_sha in FILES.items():
        source=SOURCE_ROOT/relative
        if not source.is_file():
            raise DeltaError(f"SOURCE_CANDIDATE_MISSING:{relative}")
        candidate_bytes=source.read_bytes()
        preimage_bytes=(RUNTIME_ROOT/relative).read_bytes()
        if sha(preimage_bytes)!=preimage_sha:
            raise DeltaError(f"R4_PREIMAGE_SHA_MISMATCH:{relative}")
        preimage_path=PREIMAGE_ROOT/relative
        candidate_path=CANDIDATE_ROOT/relative
        preimage_path.parent.mkdir(parents=True,exist_ok=True)
        candidate_path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(RUNTIME_ROOT/relative,preimage_path)
        shutil.copyfile(source,candidate_path)
        entries.append({
            "path":relative,
            "runtime_preimage_artifact":f"runtime_preimage_r4/{relative}",
            "runtime_preimage_sha256":preimage_sha,
            "candidate_artifact":f"runtime_candidate_r4/{relative}",
            "candidate_sha256":sha(candidate_bytes),
            "change":"replace only after exact r4 preimage comparison",
        })
    patch_bytes=_patch_bytes(entries)
    PATCH_PATH.write_bytes(patch_bytes)
    manifest={
        "status":"PREPARED_NOT_DEPLOYED",
        "release_id":RELEASE_ID,
        "runtime_root":str(RUNTIME_ROOT),
        "runtime_root_resolved":str(RUNTIME_ROOT.resolve()),
        "release_manifest_path":str(RELEASE_MANIFEST),
        "release_manifest_sha256":RELEASE_MANIFEST_SHA256,
        "scope":"Two-file OVERSOLD transport/cache repair only; no activation or live capture.",
        "files":entries,
        "patch":{"path":PATCH_PATH.name,"sha256":sha(patch_bytes)},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    receipt_lines=[
        "# r4 OVERSOLD repair candidate receipt",
        "",
        "Status: `PREPARED_NOT_DEPLOYED`.",
        "",
        f"Base release: `{RELEASE_ID}`.",
        f"Release manifest SHA-256: `{RELEASE_MANIFEST_SHA256}`.",
        f"Runtime root: `{RUNTIME_ROOT}`.",
        f"Prepared at: `{datetime.now(timezone.utc).isoformat()}`.",
        "",
        "Only `v4/manager_workbench/oversold_daily.py` and `upstreams/v3_shared_data/shared_data/hk_daily_supplement.py` differ from the observed base. The four previously accepted V4 runtime files retain their r4 bytes and are outside this delta.",
        "",
        "| File | r4 preimage SHA-256 | candidate SHA-256 |",
        "|---|---|---|",
    ]
    receipt_lines.extend(f"| `{item['path']}` | `{item['runtime_preimage_sha256']}` | `{item['candidate_sha256']}` |" for item in entries)
    receipt_lines.extend([
        "",
        f"Patch SHA-256: `{sha(patch_bytes)}`.",
        "",
        "No active file, scheduler identity, cursor, old run, plan, API, or UI was changed by preparation.",
        "",
    ])
    RECEIPT_PATH.write_text("\n".join(receipt_lines),encoding="utf-8")
    check()


def check()->None:
    _assert_base()
    try:
        manifest=json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        patch_bytes=PATCH_PATH.read_bytes()
    except OSError as error:
        raise DeltaError("R4_DELTA_ARTIFACT_MISSING") from error
    if (manifest.get("status")!="PREPARED_NOT_DEPLOYED"
            or manifest.get("release_id")!=RELEASE_ID
            or manifest.get("release_manifest_sha256")!=RELEASE_MANIFEST_SHA256
            or sha(patch_bytes)!=manifest.get("patch",{}).get("sha256")):
        raise DeltaError("R4_DELTA_MANIFEST_OR_PATCH_MISMATCH")
    if len(manifest.get("files",[]))!=len(FILES):
        raise DeltaError("R4_DELTA_FILE_SCOPE_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="oversold-r4-delta-check-") as temp_name:
        temp=Path(temp_name)
        for entry in manifest["files"]:
            preimage=DOC_ROOT/entry["runtime_preimage_artifact"]
            candidate=DOC_ROOT/entry["candidate_artifact"]
            if (file_sha(preimage)!=entry["runtime_preimage_sha256"]
                    or file_sha(candidate)!=entry["candidate_sha256"]):
                raise DeltaError(f"R4_DELTA_ARTIFACT_SHA_MISMATCH:{entry['path']}")
            destination=temp/entry["path"]
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(preimage,destination)
        import subprocess
        result=subprocess.run(["patch","-p1","-d",str(temp)],input=patch_bytes,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if result.returncode:
            raise DeltaError(result.stdout.decode("utf-8",errors="replace"))
        for entry in manifest["files"]:
            destination=temp/entry["path"]
            candidate=DOC_ROOT/entry["candidate_artifact"]
            if not destination.is_file() or destination.read_bytes()!=candidate.read_bytes():
                raise DeltaError(f"R4_STAGED_BYTES_MISMATCH:{entry['path']}")
    print("R4_RUNTIME_DELTA_CHECK_PASS; exact base and two candidate files verified; NOT_DEPLOYED")


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--prepare",action="store_true",help="snapshot current exact r4 preimages and workspace candidates")
    group.add_argument("--check",action="store_true",help="read-only exact-base and patch verification")
    args=parser.parse_args()
    try:
        prepare() if args.prepare else check()
    except (DeltaError,OSError,ValueError,KeyError) as error:
        parser.exit(2,f"R4_DELTA_BLOCKED: {error}\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
