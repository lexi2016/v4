#!/usr/bin/env python3
"""One command: copy a frozen isolated API, apply the unchanged B1/US patch, test.

The source app is read-only. Cycle/autorun/workspace are never installed by this tool.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
from run_tests import check_sources, load_profile


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-app',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    package=Path(__file__).resolve().parents[1]; original=package/'original_business'
    base=args.base_app.resolve(strict=True); output=args.output.resolve()
    if (output.exists() or base==output or base in output.parents or output in base.parents
            or package==output or package in output.parents or output in package.parents):
        raise ValueError('NEW_SIBLING_OUTPUT_REQUIRED')
    profile=load_profile(package)
    check_sources(base,profile['base_sha256'])
    for row in profile['api_changes']:
        if row['before_sha256'] is None and (base/row['path']).exists():
            raise ValueError('NEW_PATH_ALREADY_EXISTS:'+row['path'])
    # Reuse original manifest identities, without replaying or changing old evidence.
    manifest=json.loads((original/'MANIFEST.json').read_text(encoding='utf-8'))
    check_sources(original,{row['path']:row['sha256'] for row in manifest['files']})
    # Never follow source symlinks into an active tree or out-of-scope storage.
    for root,dirs,files in os.walk(base,followlinks=False):
        dirs[:]=[n for n in dirs if n not in {'.git','__pycache__'}]
        for name in dirs+files:
            if (Path(root)/name).is_symlink():
                raise ValueError('BASE_SYMLINK:'+str((Path(root)/name).relative_to(base)))
    output.mkdir(parents=True,exist_ok=False)
    candidate=output/'app'
    shutil.copytree(base,candidate,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','*.pyo','*.log'))
    check_sources(candidate,profile['base_sha256'])
    patch=original/'runtime.patch'
    command=['git','apply',str(patch)]
    check=subprocess.run(['git','apply','--check',str(patch)],cwd=candidate,capture_output=True,text=True)
    (output/'patch_check.log').write_text(check.stdout+check.stderr,encoding='utf-8')
    if check.returncode:raise ValueError('PATCH_CHECK_FAILED:see patch_check.log')
    applied=subprocess.run(command,cwd=candidate,capture_output=True,text=True)
    (output/'patch_apply.log').write_text(applied.stdout+applied.stderr,encoding='utf-8')
    if applied.returncode:raise ValueError('PATCH_APPLY_FAILED:see patch_apply.log')
    check_sources(candidate,profile['after_sha256'])
    check_sources(base,profile['base_sha256'])
    test=subprocess.run([sys.executable,str(package/'tools/run_tests.py'),'--app',str(candidate),
        '--surface','business','--output',str(output/'test_result')],cwd=package)
    summary=dict(schema_version='issue8.api6726.combo_application.v1',
        status='B1_US_APPLIED_AND_TESTED_B2_NOT_ADMITTED' if test.returncode==0 else 'TEST_FAILED',
        base_app=str(base),candidate_app=str(candidate),api_baseline=profile['api_review_commit'],
        original_business=profile['business_commit'],runtime_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        changed_paths=[r['path'] for r in profile['api_changes']],
        preserved_workspace=profile['base_sha256']['v4/manager_research/workspace.py'],
        preserved_autorun=profile['base_sha256']['v4/manager_research/workspace_plan_autorun.py'],
        b2=profile['b2'],test_returncode=test.returncode,finished_at=datetime.now(timezone.utc).isoformat(),
        independent_review='CANNOT_CONFIRM',deployment_allowed=False,production_allowed=False,
        buy_gate_updated=False,orders_sent=False)
    (output/'application_receipt.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('status','candidate_app','test_returncode')},ensure_ascii=False))
    return test.returncode


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
