#!/usr/bin/env python3
"""Run only this business delta on an explicitly selected isolated app."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--surface',choices=['business','cycle','all'],default='all')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    package=Path(__file__).resolve().parents[1];app=args.app.resolve(strict=True)
    pins=json.loads((package/'SOURCE_PINS.json').read_text())
    if 'releases' in app.parts or app.name=='v4_app':
        raise SystemExit('Use an isolated candidate, not canonical or a release.')
    expected={row['path']:row['after_sha256'] for row in pins['files']
              if row['surface']=='api' or args.surface in {'cycle','all'}}
    protected=pins['protected_unchanged']
    for rel,sha in {**expected,**protected}.items():
        if rel.endswith('workspace_plan_autorun.py') and args.surface=='business':continue
        path=app/rel
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise SystemExit('SOURCE_DRIFT:'+rel)
    args.output.mkdir(parents=True,exist_ok=False)
    files=['test_b1_history.py','test_us_business.py'] if args.surface=='business' else (
        ['test_b2_cycle.py'] if args.surface=='cycle' else ['test_b1_history.py','test_b2_cycle.py','test_us_business.py'])
    command=[sys.executable,'-m','pytest','-q','-c',str(package/'pytest.ini'),
        *[str(package/'tests'/name) for name in files], '--junitxml',str(args.output.resolve()/'junit.xml')]
    env=dict(os.environ);env['PYTHONPATH']=str(app)+os.pathsep+str(package/'tests')
    env['PYTHONDONTWRITEBYTECODE']='1';env.pop('PYTHONHOME',None)
    started=datetime.now(timezone.utc).isoformat()
    run=subprocess.run(command,cwd=app,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (args.output/'pytest.log').write_text(run.stdout)
    (args.output/'receipt.json').write_text(json.dumps(dict(command=command,app=str(app),surface=args.surface,
        started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),returncode=run.returncode,
        interpreter=sys.executable,python=sys.version,source_pins=expected,
        test_scope='SYNTHETIC_INPUTS_REAL_ORIGINAL_STORES_AND_PLAN_PIPELINE',
        live_provider=False,live_api=False,independent_reviewer='NOT_INFERRED_FROM_RUNNER',
        network_policy='SOCKET_CONNECT_DENIED_IN_TEST_FIXTURE'),indent=2)+'\n')
    print(run.stdout,end='');return run.returncode

if __name__=='__main__':raise SystemExit(main())
