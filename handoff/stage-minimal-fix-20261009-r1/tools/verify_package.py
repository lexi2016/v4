"""Verify delivered bytes and exact forward/reverse patches; never deploy."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-only",action="store_true",help="Used before the final file manifest is created")
    args=parser.parse_args()
    if not args.source_only:
        manifest=json.loads((ROOT/"FILE_MANIFEST.json").read_text())
        for row in manifest["files"]:
            p=ROOT/row["path"]
            assert not p.is_symlink() and p.is_file(),row["path"]
            assert p.stat().st_size==row["size"] and digest(p)==row["sha256"],row["path"]
    mapping=json.loads((ROOT/"SOURCE_MAP.json").read_text())
    files=0
    for group in mapping["groups"]:
        with tempfile.TemporaryDirectory(prefix="v4_stage_delivery_verify_") as directory:
            candidate=Path(directory)
            for row in group["files"]:
                before,after=ROOT/row["before_path"],ROOT/row["after_path"]
                assert digest(before)==row["before_sha256"],row["before_path"]
                assert digest(after)==row["after_sha256"],row["after_path"]
                target=candidate/row["relative_path"]
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(before,target)
                files+=1
            patch=ROOT/group["patch"]
            for reverse in (False,True):
                flags=["--reverse"] if reverse else []
                subprocess.run(["git","apply",*flags,"--check",str(patch)],cwd=candidate,check=True,capture_output=True)
                subprocess.run(["git","apply",*flags,str(patch)],cwd=candidate,check=True,capture_output=True)
                for row in group["files"]:
                    assert digest(candidate/row["relative_path"])==row["before_sha256" if reverse else "after_sha256"]
    print(json.dumps({"status":"PASS","source_variants":files,"patch_groups":len(mapping["groups"]),
                      "roundtrip":"EXACT_BYTES","file_manifest_checked":not args.source_only}))

if __name__=="__main__":
    main()
