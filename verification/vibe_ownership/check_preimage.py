"""Read-only patch pre/postimage validation; does not touch other Writer work."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def check(root: Path, manifest: dict, mode: str) -> list[str]:
    errors=[]
    for entry in manifest["changes"]:
        relative=Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            errors.append("INVALID_PATH:"+str(relative)); continue
        path=root/relative
        if any(p.is_symlink() for p in [path,*list(path.parents)[:-1]]):
            errors.append("SYMLINK:"+str(relative)); continue
        expected=entry["before_sha256"] if mode=="before" else entry["after_sha256"]
        if expected is None:
            if path.exists(): errors.append("MUST_BE_ABSENT:"+str(relative))
        elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            errors.append("SHA_DRIFT:"+str(relative))
    return errors


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--mode", choices=("before","after"), required=True)
    args=parser.parse_args()
    root=args.root.absolute()
    errors=check(root,json.loads(args.manifest.read_text()),args.mode)
    print(json.dumps({"status":"DRIFT_STOP" if errors else "MATCH", "mode":args.mode,"errors":errors},ensure_ascii=False))
    return 1 if errors else 0

if __name__=="__main__": raise SystemExit(main())
