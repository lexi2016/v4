"""Generate C wire fixtures through the frozen actual A/B + FastAPI router.

Only synthetic native owner inputs are used. No business roots, model, socket,
or formal service is touched. Run from the repository with its Python runtime.
"""
import hashlib
import json
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from v4.manager_workbench import engines
from v4.manager_workbench.api import PREFIX, create_router
from v4.manager_workbench.contracts import Lane, Phase
from v4.manager_workbench.inputs import NativeAdapters
from v4.manager_workbench.service import create_service

helpers = runpy.run_path(str(ROOT / 'tests/manager_workbench/runtime/test_native_pipeline.py'))
captures = {}

def capture(name, client, method, path, **kwargs):
    response = getattr(client, method)(PREFIX + path, **kwargs)
    captures[name] = dict(method=method.upper(), path=path, params=kwargs.get('params'),
                          request_body=kwargs.get('json'), status=response.status_code, body=response.json())
    return response.json()

def scenario(folder, name, count, *, missing=False, corrupt=False):
    folder.mkdir()
    cfg = helpers['fixture'](folder, count=count)
    cfg.legacy_root = folder / 'legacy'
    old = cfg.legacy_root / '20261013'; old.mkdir(parents=True)
    (old / 'old.json').write_text(json.dumps({'schema_version':'legacy-fixture-v0','run_id':'legacy-fixture-run'}))
    cfg.source_bindings['close'] = {'20261013': {'evaluation_scope_ref':'synthetic-full-connect'}}
    if corrupt:
        cfg.source_bindings['hk_panel']['20261012']['manifest_sha256'] = '0'*64
    service = create_service(cfg, NativeAdapters(cfg), engines, object())
    app = FastAPI(); app.include_router(create_router(service)); client = TestClient(app)
    try:
        capture(name+'_not_run', client, 'get', '/days/20261014')
        lanes = ['OVERSOLD'] + (['ANNOUNCEMENT'] if missing else [])
        created = capture(name+'_created', client, 'post', '/runs', json={'target_date':'20261013','phase':'MANUAL','lanes':lanes})
        job = helpers['wait'](service, service.jobs.get(created['data']['job_id']))
        capture(name+'_job', client, 'get', '/runs/'+job.job_id)
        for offset in (0,50,100,150,200,250):
            capture(name+'_page_'+str(offset), client, 'get', '/days/20261013', params={'offset':offset,'limit':50})
        capture(name+'_filtered', client, 'get', '/days/20261013', params={'decision':'NOT_SELECTED','limit':50})
        capture(name+'_history', client, 'get', '/history', params={'date':'20261013'})
        capture(name+'_review_missing', client, 'get', '/reviews/20261013', params={'plan_run_id':job.run_id})
        if count and not corrupt:
            capture(name+'_detail', client, 'get', '/stocks/HK.00001', params={'date':'20261013','run_id':job.run_id})
        capture(name+'_404', client, 'get', '/runs/nonexistent')
        capture(name+'_422', client, 'get', '/days/20260230')
        capture(name+'_422_limit', client, 'get', '/days/20261013', params={'limit':201})
        if not missing and not corrupt:
            capture(name+'_409', client, 'post', '/runs/'+job.job_id+'/retry')
        if count and not corrupt:
            close = dict(market='HK_CONNECT',target_date='20261013',ranking_date='20261013',
                full_scope_verified=True,scope_ref='synthetic-full-connect',source_sha256='c'*64,
                owner='synthetic-close-owner',scope_count=20,
                rows=[dict(rank=i,symbol=f'HK.{i:05d}',actual_change=i/100) for i in range(1,21)])
            service.save_review(job.run_id,close)
            capture(name+'_review',client,'get','/reviews/20261013',params={'plan_run_id':job.run_id})
        # Actual router 503 produced by a failing storage read, no invented HTTP body.
        original = service.store.get_plan
        def unavailable(*args, **kwargs): raise OSError('synthetic storage unavailable')
        service.store.get_plan = unavailable
        capture(name+'_503',client,'get','/days/20261013')
        service.store.get_plan = original
    finally:
        service.jobs.stop(); client.close()

scratch = Path(__file__).parent / '.tmp'; scratch.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=scratch) as temporary:
    root = Path(temporary)
    scenario(root/'full','full',251)
    scenario(root/'partial','partial',251,missing=True)
    scenario(root/'unknown','unknown',1,corrupt=True)
    # A's empty synthetic native membership is deliberately unknown; use the
    # actual existing injected runtime Engine for a valid evaluated empty lane.
    rt = runpy.run_path(str(ROOT/'tests/manager_workbench/runtime/test_runtime.py'))
    service, engine, client = rt['make'](root/'empty', rt['Engine'](count=0))
    try:
        rt['done'](service,service.submit('20261013',Phase.MANUAL))
        capture('empty',client,'get','/days/20261013')
    finally: service.jobs.stop();client.close()
scratch.rmdir()
destination = Path(__file__).with_name('backend-http.json')
destination.write_text(json.dumps(captures,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'captures':len(captures),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),
                  'synthetic_only':True,'real_A_B_router':True,'models_called':0}))
