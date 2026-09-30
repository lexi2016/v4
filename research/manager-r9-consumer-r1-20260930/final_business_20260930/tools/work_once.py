#!/usr/bin/env python3
"""One isolated application and new-risk test run. Never installs or calls a provider."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

PACKAGE = Path(__file__).resolve().parents[1]

def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def write(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)

def verify_package() -> None:
    manifest = json.loads((PACKAGE/'MANIFEST.json').read_text())
    for row in manifest['files']:
        path = PACKAGE/row['path']
        if path.is_symlink() or digest(path) != row['sha256']:
            raise ValueError('DELIVERY_FILE_MISMATCH:'+row['path'])

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base-app',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    verify_package()
    base=args.base_app.expanduser().resolve(); out=args.output.expanduser().resolve()
    if not base.is_dir() or out.exists() or out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError('REQUIRE_EXISTING_BASE_AND_NEW_SEPARATE_OUTPUT')
    pins=json.loads((PACKAGE/'SOURCE_PINS.json').read_text())
    actual={key:digest(base/key) for key in pins['business_profiles']['API6726']}
    profiles=[name for name,value in pins['business_profiles'].items() if value==actual]
    problems=[]
    if len(profiles)!=1:problems.append({'reason':'WHOLE_BUSINESS_PROFILE_MISMATCH','actual':actual})
    for rel,expected in pins['preserve'].items():
        if (base/rel).is_symlink() or digest(base/rel)!=expected:
            problems.append({'path':rel,'expected_sha256':expected,'actual_sha256':digest(base/rel)})
    seeded=[]
    for row in pins['delta']:
        if not row['new_in_this_batch']:continue
        path=base/row['path']; value=digest(path)
        if not path.exists():
            # Frozen supplied entry points may not yet be in the API app. They
            # are included only in this inactive development copy, never installed.
            seeded.append({'path':row['path'],'source_ref':row['source_ref'],
                           'target_runtime_binding':'CANNOT_CONFIRM'})
        elif path.is_symlink() or value!=row['before_sha256']:
            problems.append({'path':row['path'],'expected_sha256':row['before_sha256'],'actual_sha256':value})
    links=[str(p.relative_to(base)) for p in base.rglob('*') if p.is_symlink()]
    if links:problems.append({'reason':'BASE_SYMLINKS_REQUIRE_OWNED_COPY','paths':links})
    out.mkdir(parents=True)
    if problems:
        write(out/'ONE_INPUT_GAP_REPORT.json',{'status':'INPUT_BYTES_REQUIRED','gaps':problems,
            'source_app_changed':False,'installation_allowed':False})
        print('INPUT_BYTES_REQUIRED: see ONE_INPUT_GAP_REPORT.json');return 2
    app=out/'app'
    shutil.copytree(base,app,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc','*.log','.pytest_cache'))
    actions=[]
    for row in pins['delta']:
        rel=row['path'];dest=app/rel;source=PACKAGE/'after/app'/rel
        previous=digest(dest)
        if previous!=row['after_sha256']:
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(source.read_bytes())
        actions.append({'path':rel,'before_sha256':previous,'after_sha256':digest(dest)})
    expected={**pins['preserve'],**{r['path']:r['after_sha256'] for r in pins['delta']}}
    assert all(digest(app/rel)==sha for rel,sha in expected.items())
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(app)+os.pathsep+str(PACKAGE/'test_support'),
         'FINAL_APP_ROOT':str(app),'FINAL_IMPORT_RECEIPT':str(out/'import_receipt.json'),
         'PYTEST_ADDOPTS':'','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
    command=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','-c',str(PACKAGE/'pytest.ini'),str(PACKAGE/'tests'),
             '--junitxml='+str(out/'junit.xml')]
    start=datetime.now(timezone.utc).isoformat()
    with (out/'new_tests.log').open('w') as log:
        run=subprocess.run(command,cwd=app,env=env,stdout=log,stderr=subprocess.STDOUT,check=False)
    finish=datetime.now(timezone.utc).isoformat()
    counts={}
    if (out/'junit.xml').is_file():
        suites=ET.parse(out/'junit.xml').getroot().iter('testsuite')
        for suite in suites:
            for key in ('tests','failures','errors','skipped'):counts[key]=counts.get(key,0)+int(suite.get(key,'0'))
    unchanged=all(digest(app/rel)==sha for rel,sha in expected.items())
    success=run.returncode==0 and counts=={'tests':27,'failures':0,'errors':0,'skipped':0} and unchanged
    write(out/'WORK_RECEIPT.json',{'status':'ISOLATED_BUSINESS_TESTED_NOT_INSTALLED' if success else 'TEST_OR_IDENTITY_FAILED',
        'base_app':str(base),'app':str(app),'profile':profiles[0],'actions':actions,'provided_frozen_entries':seeded,
        'command':command,'started_at':start,'finished_at':finish,'exit_code':run.returncode,'counts':counts,
        'candidate_source_unchanged_by_tests':unchanged,'reused_suites_not_run':['API14','B1_US33','R3B10','F0_F2'],
        'IMPLEMENTED':'FROZEN_CODE_CANDIDATE','TESTED':'PASS_NEW_27' if success else 'FAILED',
        'REVIEWED':'CANNOT_CONFIRM','DEPLOYED':'CANNOT_CONFIRM','API_VERIFIED':'CANNOT_CONFIRM',
        'UI_VERIFIED':'CANNOT_CONFIRM','NATURAL_VERIFIED':'CANNOT_CONFIRM',
        'source_app_changed':False,'installation_allowed':False,'RESEARCH_ONLY':True,
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
    print('ISOLATED_BUSINESS_TESTED_NOT_INSTALLED' if success else 'TEST_OR_IDENTITY_FAILED')
    return 0 if success else (run.returncode or 3)

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError) as exc:
        print(type(exc).__name__+':'+str(exc),file=sys.stderr);raise SystemExit(2)
