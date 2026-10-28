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
from v4_migration.archive_preservation import verify_empty_archive_sources,preserve_empty_archive
from v4_migration.contracts import load_json,immutable_write_json

def main(argv=None):
    p=argparse.ArgumentParser(description='Verify and optionally preserve 66 historical empty artifacts; never deletes source')
    p.add_argument('--manifest',required=True,type=Path);p.add_argument('--source-root',required=True,type=Path);p.add_argument('--archive-root',type=Path);p.add_argument('--preflight-output',required=True,type=Path);p.add_argument('--preservation-output',type=Path);p.add_argument('--execute-preservation',action='store_true')
    a=p.parse_args(argv);m=load_json(a.manifest);pre=verify_empty_archive_sources(m,a.source_root);immutable_write_json(a.preflight_output,pre)
    out={'preflight':pre,'preservation_executed':False}
    if a.execute_preservation:
        if a.archive_root is None or a.preservation_output is None: raise SystemExit('ARCHIVE_ROOT_AND_OUTPUT_REQUIRED')
        r=preserve_empty_archive(m,a.source_root,a.archive_root,preflight=pre);immutable_write_json(a.preservation_output,r);out={'preflight':pre,'preservation':r,'preservation_executed':True}
    print(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2));return 0
if __name__=='__main__': raise SystemExit(main())
