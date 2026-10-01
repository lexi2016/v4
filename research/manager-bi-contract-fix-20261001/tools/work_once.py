#!/usr/bin/env python3
"""Apply this exact patch to an explicitly supplied ISOLATED app and run new tests.
Never call a provider, service, scheduler, package installer or deployment tool.
"""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True,help='Complete disposable app/source copy, never a configured release')
    parser.add_argument('--output',type=Path,required=True,help='New evidence directory outside app')
    args=parser.parse_args();app=args.app.resolve();out=args.output.resolve()
    if not app.is_dir() or 'releases' in app.parts or out==app or out.is_relative_to(app):
        parser.error('use an isolated app and a new external output directory')
    pins=json.loads((ROOT/'SOURCE_PINS.json').read_text())['files']
    before={r['path']:r['before_sha256'] for r in pins};after={r['path']:r['after_sha256'] for r in pins}
    observed={rel:sha(app/rel) if (app/rel).is_file() else None for rel in before}
    if observed not in (before,after):
        print(json.dumps({'status':'SOURCE_DRIFT','files':[{ 'path':k,'actual':v,'before':before[k],'after':after[k]} for k,v in observed.items()]},ensure_ascii=False));return 2
    out.mkdir(parents=True,exist_ok=False)
    receipt={'status':'NOT_RUN','source_before':observed,'python':sys.version,'app':str(app),'applied':False,
             'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'DEPLOYED':'NOT_RUN','API_VERIFIED':'NOT_RUN','UI_VERIFIED':'NOT_RUN'}
    try:
        if observed==before:
            for check in (True,False):
                cmd=['git','apply',*(['--check'] if check else []),str(ROOT/'runtime.patch')]
                run=subprocess.run(cmd,cwd=app,text=True,capture_output=True)
                (out/('patch_check.log' if check else 'patch_apply.log')).write_text(run.stdout+run.stderr)
                if run.returncode:raise RuntimeError('PATCH_APPLY_FAILED')
            receipt['applied']=True
        assert {rel:sha(app/rel) for rel in after}==after
        env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(app),str(ROOT/'tests')]);env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';env['PYTHONDONTWRITEBYTECODE']='1'
        env['BI_APP']=str(app);env['BI_OUTPUT']=str(out/'cases')
        cmd=[sys.executable,'-m','pytest','-c',str(ROOT/'pytest.ini'),str(ROOT/'tests/test_cross_boundary.py'),'-q','--tb=short','--junitxml='+str(out/'junit.xml')]
        run=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True)
        (out/'pytest.log').write_text(run.stdout+run.stderr);print(run.stdout+run.stderr)
        receipt.update(status='ISOLATED_CONTRACT_TESTED_NOT_LIVE_UI' if run.returncode==0 else 'TEST_FAILED',command=cmd,exit_code=run.returncode,source_after={rel:sha(app/rel) for rel in after})
        if receipt['source_after']!=after:raise RuntimeError('SOURCE_CHANGED_DURING_TEST')
        return run.returncode
    except (OSError,ValueError,RuntimeError,AssertionError) as exc:
        receipt.update(status='FAILED',error=type(exc).__name__,reason=str(exc));print(json.dumps(receipt,ensure_ascii=False));return 2
    finally:(out/'WORK_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':raise SystemExit(main())
