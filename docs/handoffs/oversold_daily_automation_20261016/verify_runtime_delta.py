#!/usr/bin/env python3
"""Apply the prepared unified delta to saved preimages in a temporary tree."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT=Path(__file__).resolve().parent


def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def main()->int:
    manifest=json.loads((ROOT/"runtime_exact_delta.json").read_text(encoding="utf-8"))
    patch_path=ROOT/manifest["patch"]["path"]
    patch_bytes=patch_path.read_bytes()
    if sha(patch_bytes)!=manifest["patch"]["sha256"]:
        raise SystemExit("RUNTIME_PATCH_SHA_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="oversold-runtime-delta-check-") as temp_name:
        temp=Path(temp_name)
        for entry in manifest["files"]:
            preimage=entry["runtime_preimage_artifact"]
            if preimage is None:
                continue
            source=ROOT/preimage
            if sha(source.read_bytes())!=entry["runtime_preimage_sha256"]:
                raise SystemExit(f"RUNTIME_PREIMAGE_ARTIFACT_SHA_MISMATCH:{entry['path']}")
            target=temp/entry["path"]
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
        result=subprocess.run(["patch","-p1","-d",str(temp)],input=patch_bytes,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if result.returncode:
            raise SystemExit(result.stdout.decode("utf-8",errors="replace"))
        for entry in manifest["files"]:
            target=temp/entry["path"]
            candidate=ROOT/entry["candidate_artifact"]
            if not target.is_file() or sha(target.read_bytes())!=entry["candidate_sha256"]:
                raise SystemExit(f"STAGED_CANDIDATE_SHA_MISMATCH:{entry['path']}")
            if target.read_bytes()!=candidate.read_bytes():
                raise SystemExit(f"STAGED_CANDIDATE_BYTES_MISMATCH:{entry['path']}")
    print(f"STAGED_RUNTIME_DELTA_PASS; all {len(manifest['files'])} outputs match candidate SHAs")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
