from __future__ import annotations
import json
from pathlib import Path
import pytest
from fastapi import FastAPI, APIRouter, Depends
from fastapi.testclient import TestClient
from infrastructure.api_namespace import install_legacy_aliases, effective_api_routes, LegacyAliasRoute
from tests.test_v4_legacy_retirement import actual_app

ROOT=Path(__file__).resolve().parents[1]


def test_exact_all42_original_paths_methods_and_handler_dependencies(actual_app):
    expected=json.loads((ROOT/'contracts/v4_legacy_api_aliases.json').read_text())['routes']
    aliases={r.path:r for r in actual_app.routes if isinstance(r,LegacyAliasRoute)}
    assert len(expected)==42
    assert set(aliases)==set(expected)|{'/api/v3/research/opening-observation'}
    assert {path:sorted(aliases[path].methods) for path in expected}==expected
    assert aliases['/api/v3/research/opening-observation'].methods=={'GET'}
    canonical={path:(route,dependant) for path,_,route,_,dependant in effective_api_routes(actual_app)}
    for path,alias in aliases.items():
        route,dep=canonical[path.replace('/api/v3/','/api/v4/',1)]
        assert alias.app is route.app and alias.endpoint is route.endpoint and alias.dependant is dep
    original=json.loads((ROOT/'tests/fixtures/v4_retirement/active_routes.json').read_text())
    for path in original:
        if path.startswith('/api/v4/'):
            assert path.replace('/api/v4/','/api/v3/',1) not in aliases


@pytest.mark.parametrize('suffix',[
    'research/wechat/materials',
    'research/wechat/materials/6cb2856a7106340eecda8f2bdf98a2886669d15a02eaaa94ff8ca834262ad579',
    'research/wechat/materials/6cb2856a7106340eecda8f2bdf98a2886669d15a02eaaa94ff8ca834262ad579/artifacts/source_IMAGE001',
])
def test_actual_nested_wechat_empty_input_status_and_body_parity(actual_app,suffix):
    c=TestClient(actual_app);old=c.get('/api/v3/'+suffix);new=c.get('/api/v4/'+suffix)
    assert old.status_code==new.status_code and old.content==new.content
    assert old.status_code!=404


def test_real_nested_wechat_router_parameters_artifact_and_include_dependency():
    from apps.api.v4_api.wechat_research_router import create_wechat_research_router
    calls=[];deps=[]
    class Reader:
        def list_materials(self,**kwargs):calls.append(('list',kwargs));return {'status':'READY','items':[{'record_id':'record-1'}]}
        def detail(self,record_id):calls.append(('detail',record_id));return {'status':'PARTIAL','record_id':record_id,'production_allowed':False}
        def artifact(self,record_id,artifact_id):calls.append(('artifact',record_id,artifact_id));return b'original image bytes','IMAGE001.jpg','image/jpeg'
    def dependency():deps.append(1)
    app=FastAPI();outer=APIRouter(prefix='/api/v4/research');outer.include_router(create_wechat_research_router(Reader()))
    app.include_router(outer,dependencies=[Depends(dependency)])
    routes={'/api/v3/research/wechat/materials':['GET'],'/api/v3/research/wechat/materials/{record_id}':['GET'],'/api/v3/research/wechat/materials/{record_id}/artifacts/{artifact_id}':['GET']}
    install_legacy_aliases(app,legacy_routes=routes);c=TestClient(app)
    for suffix in ['materials','materials/record-1','materials/record-1/artifacts/source_IMAGE001']:
        before=len(calls);old=c.get('/api/v3/research/wechat/'+suffix);assert len(calls)==before+1
        new=c.get('/api/v4/research/wechat/'+suffix);assert len(calls)==before+2
        assert old.status_code==new.status_code==200 and old.content==new.content
        assert old.headers.get('content-disposition')==new.headers.get('content-disposition')
    assert len(deps)==len(calls)==6
    assert calls[-1]==('artifact','record-1','source_IMAGE001')
    # Original APIRoute GET contract did not accept HEAD.
    assert c.head('/api/v3/research/wechat/materials').status_code==405


def test_nested_post_inherited_prefix_dependency_and_body_execute_once():
    from fastapi.responses import JSONResponse
    class IncludedResponse(JSONResponse):
        def __init__(self,*args,**kwargs):
            kwargs['headers']={**(kwargs.get('headers') or {}),'X-Inherited-Response':'same-owner'}
            super().__init__(*args,**kwargs)
    app=FastAPI();inner=APIRouter(prefix='/research/jobs');calls=[];deps=[];stored={}
    def dep():deps.append(1)
    @inner.post('/{job_id}')
    def submit(job_id:str,payload:dict):
        calls.append((job_id,payload));stored.setdefault(job_id,payload);return {'id':job_id,'stored':stored[job_id]}
    parent=APIRouter(prefix='/api/v4',default_response_class=IncludedResponse)
    parent.include_router(inner);app.include_router(parent,dependencies=[Depends(dep)])
    install_legacy_aliases(app,legacy_routes={'/api/v3/research/jobs/{job_id}':['POST']});c=TestClient(app)
    old=c.post('/api/v3/research/jobs/original',json={'value':'原始输入'});assert old.status_code==200
    assert calls==[('original',{'value':'原始输入'})] and len(deps)==1
    new=c.post('/api/v4/research/jobs/original',json={'value':'原始输入'});assert new.json()==old.json()
    assert old.headers['x-inherited-response']==new.headers['x-inherited-response']=='same-owner'
    assert len(calls)==len(deps)==2 and len(stored)==1
