#!/usr/bin/env python3
from __future__ import annotations
import argparse,os,sys,json
from pathlib import Path

_SCRIPT_PATH = Path(os.path.abspath(__file__))
_PROJECT_ROOT = next(
    (parent for parent in _SCRIPT_PATH.parents if (parent / "v4_migration").is_dir() and not (parent / "v4_migration").is_symlink()),
    None,
)
if _PROJECT_ROOT is None:
    raise RuntimeError("V4_PROJECT_ROOT_NOT_FOUND")
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from v4_migration.duplicate_quarantine import verify_and_quarantine_duplicate
from v4_migration.contracts import load_json,immutable_write_json

def main(argv=None):
    p=argparse.ArgumentParser(description='Losslessly quarantine one duplicate-code artifact; no projection/winner')
    p.add_argument('--manifest',required=True,type=Path);p.add_argument('--source-root',required=True,type=Path);p.add_argument('--quarantine-root',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args(argv);m=load_json(a.manifest);items=m.get('items') or []
    if len(items)!=1: raise SystemExit('DUPLICATE_MANIFEST_MUST_HAVE_ONE_ITEM')
    r=verify_and_quarantine_duplicate(items[0],a.source_root,a.quarantine_root);immutable_write_json(a.output,r);print(json.dumps(r,ensure_ascii=False,sort_keys=True,indent=2));return 0
if __name__=='__main__': raise SystemExit(main())
