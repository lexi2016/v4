from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, APIRouter, Depends
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from infrastructure.api_namespace import install_legacy_aliases, _routers, effective_api_routes, LegacyAliasRoute
from infrastructure.interprocess_lock import _decode_owner, owned_interprocess_lock
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from ops.v4_legacy_retirement import namespace_text, safe_child, OCR_FILES

ROOT = Path(__file__).resolve().parents[1]


def test_ancestor_symlink_rejected_before_any_write(tmp_path):
    root=tmp_path.resolve();outside=root/'outside';outside.mkdir();work=root/'work';work.mkdir()
    original=outside/'module.py';original.write_bytes(b'original');(work/'package').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='SYMLINK'):
        safe_child(work,'package/module.py')
    assert original.read_bytes()==b'original'


def test_namespace_preserves_immutable_schema_artifact_and_logical_workload():
    before='V35_DATA_ROOT apps.api.v35_api ops.run_v35_macos_scheduler /api/v3/research v3_5.dispatch_claim.v1 v35_zsxq_hourly_status_20261028.json stage_workbench'
    after=namespace_text(before)
    assert 'V4_DATA_ROOT' in after and 'apps.api.v4_api' in after and 'ops.run_v4_macos_scheduler' in after
    assert '/api/v4/research' in after
    for retained in ['v3_5.dispatch_claim.v1','v35_zsxq_hourly_status_20261028.json','stage_workbench']:
        assert retained in after


def test_nested_alias_post_calls_handler_and_dependency_once_and_reuses_idempotency():
    app=FastAPI();router=APIRouter(prefix='/api/v4/research');counts={'handler':0,'dependency':0,'write':0};completed={}
    def dep():counts['dependency']+=1
    @router.post('/jobs/{job_id}',dependencies=[Depends(dep)])
    def submit(job_id:str):
        counts['handler']+=1
        if job_id not in completed:
            counts['write']+=1;completed[job_id]={'job_id':job_id,'status':'PARTIAL','production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
        return completed[job_id]
    app.include_router(router);install_legacy_aliases(app,legacy_routes={"/api/v3/research/jobs/{job_id}":["POST"]})
    old=next(r for r in app.routes if isinstance(r,LegacyAliasRoute))
    _,_,new,_,dependant=next(row for row in effective_api_routes(app) if row[0]=='/api/v4/research/jobs/{job_id}')
    assert old.app is new.app and old.endpoint is new.endpoint and old.dependant is dependant
    c=TestClient(app);a=c.post('/api/v3/research/jobs/stable');assert a.status_code==200
    assert counts=={'handler':1,'dependency':1,'write':1}
    b=c.post('/api/v4/research/jobs/stable');assert a.json()==b.json()
    assert counts=={'handler':2,'dependency':2,'write':1}


def test_alias_collision_fails_before_install():
    app=FastAPI()
    @app.get('/api/v4/x')
    def x():return {}
    @app.get('/api/v3/x')
    def unrelated():return {}
    with pytest.raises(ValueError,match='COLLISION'):install_legacy_aliases(app,legacy_routes={'/api/v3/x':['GET']})


@pytest.fixture
def actual_app(tmp_path,monkeypatch):
    from apps.api.v4_api.app import create_app
    p=tmp_path.resolve()
    from domains._preselection_parts import source_validation
    date_role=source_validation._display_name_date_role
    monkeypatch.setattr(source_validation,"_display_name_date_role",lambda trade_date,**kwargs:date_role(trade_date,as_of=datetime(2026,10,28,12,0,tzinfo=ZoneInfo("Asia/Shanghai"))))
    # Never consume real storage or initiate source capture during candidate tests.
    for key in list(os.environ):
        if key.startswith(('V4_','V35_')):monkeypatch.delenv(key,raising=False)
    return create_app(data_root=p/'data',ledger_root=p/'ledger',stage_center_selection_root=p/'selection',manager_research_state_root=p/'manager')


def test_actual_combined_route_catalogue_and_get_parity(actual_app):
    expected=json.loads((ROOT/'tests/fixtures/v4_retirement/active_routes.json').read_text())
    canonical={p.replace('/api/v3/','/api/v4/'):methods for p,methods in expected.items()}
    canonical['/api/v4/research/opening-observation']=['get']  # separately user-approved read-only addition
    observed={p:sorted(m for m in methods if m in {'get','post','put','delete','patch','head','options'}) for p,methods in actual_app.openapi()['paths'].items()}
    assert observed==canonical
    assert actual_app.title=='V4'
    c=TestClient(actual_app)
    for suffix in ['meta/stages','preselection-pools?date=20261028']:
        old=c.get('/api/v3/'+suffix);new=c.get('/api/v4/'+suffix)
        assert old.status_code==new.status_code==200
        assert old.json()==new.json()


def test_actual_stage_post_alias_invokes_readonly_consumer_once(actual_app,monkeypatch):
    from stage_center.consumer import StageSelectionConsumer
    original=StageSelectionConsumer.ensure;calls=[]
    def counted(self,*args,**kwargs):calls.append((args,kwargs));return original(self,*args,**kwargs)
    monkeypatch.setattr(StageSelectionConsumer,'ensure',counted)
    c=TestClient(actual_app)
    a=c.post('/api/v3/stage-center/selection/ensure?date=20261028');assert a.status_code==200;assert len(calls)==1
    b=c.post('/api/v4/stage-center/selection/ensure?date=20261028');assert b.status_code==200;assert len(calls)==2
    assert a.json()==b.json();payload=a.json()
    assert payload['production_allowed'] is False and payload['buy_gate_updated'] is False and payload['orders_sent'] is False


def test_completed_legacy_ledger_claim_survives_release_and_env_rename(tmp_path,monkeypatch):
    ledger=ExecutionLedger(tmp_path.resolve());request=DispatchRequest('20261028','20261028','20261029','1700',DispatchMode.LIVE)
    old=ledger.try_claim_dispatch(request);assert old.acquired
    claim_path=ledger.root/old.relative_path;raw=claim_path.read_bytes();assert json.loads(raw)['schema_version']=='v3_5.dispatch_claim.v1'
    monkeypatch.setenv('V4_RELEASE_ID','renamed-new-release');again=ExecutionLedger(ledger.root).try_claim_dispatch(request)
    assert not again.acquired and again.run_id==old.run_id and claim_path.read_bytes()==raw


def test_completed_legacy_receipt_blocks_retry_when_release_changes(tmp_path):
    from ops.run_v4_macos_scheduler_due import _slot_blocks_retry,SHANGHAI
    root=tmp_path.resolve();p=root/'receipts/live/20261028/1700/prior.dispatch-receipt.json';p.parent.mkdir(parents=True);raw=json.dumps({'status':'SUCCEEDED','release_id':'old-v35','upstream_fingerprint':'old-input','finished_at':'2026-10-28T09:00:00Z'}).encode();p.write_bytes(raw)
    assert _slot_blocks_retry(root,'20261028','1700',moment=datetime(2026,10,28,18,0,tzinfo=SHANGHAI),release_id='new-v4',upstream_fingerprint='new-release-input')
    assert p.read_bytes()==raw


def test_live_old_schema_lock_is_preserved(tmp_path):
    p=tmp_path.resolve()/'queue.lock';raw=json.dumps({'schema_version':'v3_5_interprocess_lock.v1','pid':os.getpid(),'token':'old-owner'}).encode();p.write_bytes(raw)
    assert _decode_owner(raw)==(os.getpid(),'old-owner')
    with pytest.raises(ValueError):
        with owned_interprocess_lock(p,timeout_seconds=0,timeout_message='busy'):pytest.fail('old alive owner was displaced')
    assert p.read_bytes()==raw


def _load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


def test_ocr_helpers_immutable_and_geometry_and_archive_text_preserved():
    pins={'wechat_prepare_ocr.py':'980c9004a1fa38862708ee325970ab8adfebbd66661cb42f0f8318436eebe606','wechat_common.py':'25934b26357060e3322dcf393816383558a166a5a969244a7e4f1e8de4582446','wechat_macos_ocr.py':'be7e039d778babd32918da2b7d9620a7b3b9e98e6e62625840eaad1b6d4d834d'}
    for name in OCR_FILES:assert hashlib.sha256((ROOT/'components/wechat_ocr'/name).read_bytes()).hexdigest()==pins[name]
    common=_load(ROOT/'components/wechat_ocr/wechat_common.py','_v4_test_wechat_common')
    assert common.normalize_security_code(' 03625.hk ')=='03625.HK'
    assert common.article_body_text('<p>原始材料 A股</p><p>HK 独立</p>')=='原始材料 A股\nHK 独立'
    assert common.security_code_matches('03625','03625.HK')


def test_hk_identity_and_formula_representative_inputs():
    import pandas as pd
    from infrastructure.isolated_package_loader import load_isolated_package_module
    hk=load_isolated_package_module(ROOT/'components/hk_updater',package_directory='shared_data',module_leaf='hk_0_2',namespace_prefix='v4_retirement_hk')
    assert [hk._normalize_code(x) for x in ['03625.HK','HK.00068','00068.HK_CONNECT']]==['HK.03625','HK.00068','HK.00068']
    formula=_load(ROOT/'components/a_formula/build_canonical_formula_research_panel.py','_v4_retirement_formula')
    got=formula.tdx_sma(pd.Series([10.0,20.0,30.0]),3,1)
    assert list(got)==pytest.approx([10.0,40/3,170/9])


def test_active_launcher_requires_v4_environment_without_legacy_fallback(tmp_path):
    import subprocess
    old=tmp_path/'legacy';old.mkdir()
    p=subprocess.run(['/bin/bash',str(ROOT/'ops/launch_v4_macos_scheduler.sh')],env={'PATH':'/usr/bin:/bin','V35_RUNTIME_ROOT':str(old)},capture_output=True,text=True,timeout=5)
    assert p.returncode!=0 and 'V4_RUNTIME_ROOT is required' in p.stderr
    assert list(old.iterdir())==[]
