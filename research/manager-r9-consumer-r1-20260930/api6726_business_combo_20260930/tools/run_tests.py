#!/usr/bin/env python3
"""Run unchanged B1/US assertions with the separately frozen API_6726 profile.

No pin fallback, workspace replacement, legacy autorun, or native B2 claim.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def load_profile(package: Path) -> dict:
    value=json.loads((package/'COMBINATION_PINS.json').read_text(encoding='utf-8'))
    if value.get('profile')!='API_6726_B1_US_ONLY':
        raise ValueError('COMBINATION_PROFILE_INVALID')
    return value


def check_sources(app: Path, expected: dict) -> dict:
    actual={}
    for rel,pin in expected.items():
        path=app/rel
        if (Path(rel).is_absolute() or '..' in Path(rel).parts or not path.is_file()
                or path.resolve()!=path or hashlib.sha256(path.read_bytes()).hexdigest()!=pin):
            raise ValueError('SOURCE_DRIFT:'+rel)
        actual[rel]=pin
    return actual


def selected_tests(package: Path, surface: str) -> list[Path]:
    if surface!='business':
        raise ValueError('B2_FINAL_CYCLE_BINDING_REQUIRED:see B2_ENTRY_STATUS.md')
    return [package/'original_business/tests'/name for name in ('test_b1_history.py','test_us_business.py')]


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--surface',choices=['business','cycle','all'],default='business')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    package=Path(__file__).resolve().parents[1]
    profile=load_profile(package);files=selected_tests(package,args.surface)
    app=args.app.resolve(strict=True);output=args.output.resolve()
    if 'releases' in app.parts or app.name=='v4_app' or 'deployment_r9' in app.parts:
        raise ValueError('ISOLATED_APP_REQUIRED')
    if output==app or app in output.parents:
        raise ValueError('TEST_OUTPUT_MUST_BE_OUTSIDE_APP')
    expected=profile['after_sha256']
    before=check_sources(app,expected)
    check_sources(package/'original_business',profile['test_sha256'])
    output.mkdir(parents=True,exist_ok=False)
    command=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','-c',str(package/'original_business/pytest.ini'),
        *map(str,files),'--junitxml',str(output/'junit.xml')]
    env=dict(os.environ);env['PYTHONPATH']=str(app)+os.pathsep+str(package/'original_business/tests')
    env['PYTHONDONTWRITEBYTECODE']='1';env.pop('PYTHONHOME',None)
    start=datetime.now(timezone.utc).isoformat()
    run=subprocess.run(command,cwd=app,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (output/'pytest.log').write_text(run.stdout,encoding='utf-8')
    after=check_sources(app,expected)
    counts=None
    if (output/'junit.xml').is_file():
        suites=list(ET.parse(output/'junit.xml').getroot().iter('testsuite'))
        counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    passed=run.returncode==0 and counts==dict(tests=profile['expected_tests'],failures=0,errors=0,skipped=0)
    receipt=dict(profile=profile['profile'],command=command,app=str(app),started_at=start,
        finished_at=datetime.now(timezone.utc).isoformat(),returncode=run.returncode,
        accepted_selected_scope=passed,counts=counts,source_pins_before=before,source_pins_after=after,
        interpreter=sys.executable,python=sys.version,test_files_sha256=profile['test_sha256'],
        test_scope='UNCHANGED_33_B1_US_ASSERTIONS_ON_NEW_API_REFERENCE_OR_NATIVE_ISOLATED_APP',
        old_14_rerun=False,b2=profile['b2'],live_provider=False,live_api=False,
        independent_review='NOT_INFERRED_FROM_RUNNER',deployment_allowed=False,
        network_policy='ORIGINAL_SOCKET_DENY_FIXTURE')
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(run.stdout,end='')
    return run.returncode if run.returncode else (0 if passed else 3)


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
