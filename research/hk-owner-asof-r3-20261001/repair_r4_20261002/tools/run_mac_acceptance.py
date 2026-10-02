"""Run only HK repair contracts in a fresh temp directory, using caller's Python.

This script does not assemble/deploy the app, change permissions, clean old
pytest data, invoke live producers, or suppress failures. Use an isolated app.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--variant',choices=('active','canonical'),required=True)
    parser.add_argument('--suite',choices=('reported','full'),default='reported')
    args=parser.parse_args(argv)
    app=args.app_root.expanduser().resolve(strict=True)
    out=args.output_root.expanduser().resolve()
    out.mkdir(parents=True,exist_ok=False)
    tests=Path(__file__).resolve().parents[1]/'tests'
    # The 7 originally failing active cases, plus narrowly targeted contract
    # negatives. --full adds unchanged HK19 cases; neither choice runs A/Stage.
    original=tests/'test_hk_owner_asof_r3.py'
    targets=[str(original)] if args.suite=='full' else [
        f'{original}::test_real_shared_projector_stage_chain_has_capture_provenance',
        f'{original}::test_original_owner_invokes_existing_publisher_and_preserves_a_on_hk_only',
        f'{original}::test_original_scheduled_hk_only_cli_does_not_publish_a_missing_pool',
    ]
    if args.variant=='active': targets.append(str(tests/'test_hk_r9_contract_r4.py'))
    env=os.environ.copy();env['PYTHONPATH']=str(app);env['HK_R3_APP_ROOT']=str(app)
    env['PYTHONDONTWRITEBYTECODE']='1';env['TERM']=env.get('TERM') or 'dumb'
    paths=('infrastructure/preselection_pool_store.py',
           'infrastructure/scheduling/executor_registry.py',
           'infrastructure/scheduling/executor_registry_preselection.py',
           'stage_center/hk_universe_preflight.py',
           'upstreams/v3_shared_data/scripts/live_acquisition/universe.py',
           'upstreams/v3_shared_data/shared_data/store.py',
           'upstreams/v3_shared_data/shared_data/hk_security_master.py',
           'upstreams/v3_shared_data/shared_data/hk_0_2.py')
    identities={p:hashlib.sha256((app/p).read_bytes()).hexdigest() if (app/p).is_file() else None for p in paths}
    result={'variant':args.variant,'suite':args.suite,'python':sys.version,
        'executable':sys.executable,'platform':platform.platform(),'app_root':str(app),
        'source_sha256':identities,'live_data_acceptance':False,'deployment':False}
    # --basetemp disables numbered shared-root cleanup. It lives in a fresh
    # parent so pytest cannot delete a previous user's evidence directory.
    with tempfile.TemporaryDirectory(prefix='v4_hk_r4_') as fresh:
        cmd=[sys.executable,'-B','-m','pytest',*targets,'-q','--tb=short',
             '--basetemp',str(Path(fresh)/'pytest'),f'--junitxml={out / "junit.xml"}']
        result['command']=cmd
        with (out/'stdout.txt').open('wb') as stdout,(out/'stderr.txt').open('wb') as stderr:
            process=subprocess.run(cmd,cwd=app,env=env,stdout=stdout,stderr=stderr,check=False)
        result['exit_code']=process.returncode
        if (out/'junit.xml').is_file():
            suites=ET.parse(out/'junit.xml').getroot()
            nodes=[suites] if suites.tag=='testsuite' else list(suites.findall('testsuite'))
            result.update({k:sum(int(n.attrib.get(k,0)) for n in nodes)
                           for k in ('tests','failures','errors','skipped')})
            result['passed']=result['tests']-result['failures']-result['errors']-result['skipped']
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    # Cleanup exceptions are not caught or changed to success.
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return process.returncode


if __name__=='__main__':raise SystemExit(main())
