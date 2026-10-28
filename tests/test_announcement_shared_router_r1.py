"""Synthetic ASGI contract check for the optional shared 03 integration patch.

Pass ANNOUNCEMENT_SHARED_ROUTER_FILE as the full path of the patched router.
Never claims a real Mac endpoint or scheduled owner result.
"""
import importlib.util
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def setup_router(monkeypatch):
    path = Path(os.environ['ANNOUNCEMENT_SHARED_ROUTER_FILE']).resolve()
    assert path.is_file(), path
    root = types.ModuleType('v4'); root.__path__ = []
    branch = types.ModuleType('v4.manager_research'); branch.__path__ = []
    projection = types.ModuleType('v4.manager_research.workspace_projection')
    projection.FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    projection.HK=ZoneInfo('Asia/Shanghai')
    store=types.ModuleType('v4.manager_research.store'); store.StoreError=type('StoreError',(Exception,),{})
    control=types.ModuleType('v4.manager_research.workspace_read_control')
    class WorkspaceReadError(Exception):
        code='WORKSPACE_READ_ERROR'
    control.WorkspaceReadError=WorkspaceReadError
    announces=types.ModuleType('v4.manager_research.workspace_announcements')
    calls=[]
    def read_audit(service,target,pub,*,cutoff=None,analysis_readback=None):
        calls.append((target,pub,cutoff))
        if getattr(service,'audit_fails',False):raise RuntimeError('TEST_UNAVAILABLE')
        return dict(status='RETROSPECTIVE_RESEARCH_ONLY',target_trade_date=target,
                    publication_date=pub,stock_count=None,stocks=[],validation_status='CANNOT_CONFIRM',
                    gaps=['TEST_MISSING_OWNER_RECEIPT'])
    announces.read_announcement_research_result=read_audit
    announces.read_analysis_consumption=lambda *a,**kw:dict(status='NOT_CONSUMED_INVALID',validation_status='CANNOT_CONFIRM')
    announces.validate_owner_analysis_import_receipt=lambda *a,**kw:(_ for _ in ()).throw(ValueError('BAD_OWNER_RECEIPT'))
    analysis=types.ModuleType('v4.manager_research.announcement_analysis')
    analysis.product_path=lambda store,target,pub:Path('/tmp')/'analysis.v1.json'
    analysis.import_registered_product=lambda svc,run,handoff,product:dict(import_status='IMPORTED',
        evidence_run_id=run,handoff_manifest_sha256=handoff,product_sha256=product)
    for obj in (root,branch,projection,store,control,announces,analysis):
        monkeypatch.setitem(sys.modules,obj.__name__,obj)
    spec=importlib.util.spec_from_file_location('announcement_patch_router',path)
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module,calls


class FakeStore:
    def _read(self,path):return {'schema_version':'CORRUPTED'}


class Service:
    def __init__(self):
        self.audit_fails=False
        self.store=FakeStore()
        self.snapshot=dict(target_trade_date='20261009',
            date_bindings=dict(plan_date='20261009',selection_date='20261009',announcement_date='20261008'),
            plan_product=dict(status='SOURCE_FAILED',consumed=False,sha256=None),
            read_context=dict(mode='HISTORICAL_AS_OF',status='SOURCE_FAILED',as_of='2026-10-09T09:30:00+08:00'),
            daily_channels=dict(schema_version='v4.manager_research.daily_channels.v1',
                channels=[{'channel':'ANNOUNCEMENT','candidate_count':None,'rows':[],'product_checks':[]},
                          {'channel':'HK_CONNECT','candidate_count':12,'rows':[{'symbol':'HK.00001'}]},
                          {'channel':'OVERSOLD','candidate_count':4,'rows':[]}]))
    def get_workspace(self,target,**kwargs):
        assert target=='20261009'
        return deepcopy(self.snapshot)
    def get_announcement_analysis(self,target,pub):
        return dict(target_trade_date=target,publication_date=pub,
            source_catalog=dict(status='COMPLETE'),analysis=dict(status='VERIFIED',product_sha256='a'*64))


def client_for(module,service):
    app=FastAPI()
    app.include_router(module.create_manager_research_router(service))
    return TestClient(app,raise_server_exceptions=True)


def test_workspace_adds_only_announcement_sidecar_and_keeps_read_cutoff(setup_router):
    module,calls=setup_router;svc=Service();before=deepcopy(svc.snapshot)
    with client_for(module,svc) as client:
        response=client.get('/api/v4/manager/research/workspace?date=20261009&view=historical')
    assert response.status_code==200,response.text
    data=response.json();c=data['daily_channels']['channels']
    assert calls==[('20261009','2026-10-08','2026-10-09T09:30:00+08:00')]
    assert data['plan_product']==before['plan_product']
    assert c[0]['candidate_count'] is None and c[0]['rows']==[]
    assert c[0]['research_result']['stock_count'] is None
    assert c[1:]==before['daily_channels']['channels'][1:]
    assert svc.snapshot==before


def test_research_failure_never_hides_other_lanes(setup_router):
    module,_=setup_router;svc=Service();svc.audit_fails=True
    with client_for(module,svc) as client:
        response=client.get('/api/v4/manager/research/workspace?date=20261009')
    assert response.status_code==200,response.text
    lanes=response.json()['daily_channels']['channels']
    assert lanes[0]['research_result']['status']=='CANNOT_CONFIRM'
    assert lanes[0]['candidate_count'] is None
    assert lanes[1]['candidate_count']==12 and lanes[2]['candidate_count']==4


def test_import_route_only_accepts_registered_references(setup_router):
    module,_=setup_router;svc=Service()
    envelope=dict(schema_version='v4.manager_research.announcement_analysis_import_ref.v1',
        evidence_run_id='e'*32,handoff_manifest_sha256='f'*64,product_sha256='a'*64)
    with client_for(module,svc) as client:
        response=client.post('/api/v4/manager/research/announcements/analysis/import',
            json=envelope,headers={'Origin':'http://testserver'})
        forged=client.post('/api/v4/manager/research/announcements/analysis/import',
            json=dict(envelope,selected_stocks=[{'symbol':'HK.00001'}]),headers={'Origin':'http://testserver'})
        no_origin=client.post('/api/v4/manager/research/announcements/analysis/import',json=envelope)
    assert response.status_code==200,response.text
    assert response.json()['evidence_run_id']=='e'*32
    assert forged.status_code==422 and no_origin.status_code==403


def test_analysis_invalid_receipt_is_visible_gap_not_http_409(setup_router):
    module,_=setup_router;svc=Service()
    with client_for(module,svc) as client:
        response=client.get('/api/v4/manager/research/announcements/analysis?date=20261009&publication_date=20261008')
    assert response.status_code==200,response.text
    result=response.json()
    assert result['owner_import_receipt'] is None
    assert result['owner_receipt_readback_status']=='CANNOT_CONFIRM'
    assert result['consumption_validation']['validation_status']=='CANNOT_CONFIRM'
    assert result['research_result']['stock_count'] is None
