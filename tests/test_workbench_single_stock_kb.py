import hashlib,json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure import research_workbench_host as wb


def _ref(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True))
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    generation='a'*64;input_sha='b'*64;numeric={'path':'/frozen/manifest.json','sha256':'c'*64}
    relocation=_ref(tmp_path/'relocation.json',{'mode':'ISOLATED_READ_ONLY'})
    gate=_ref(tmp_path/'gate.json',{'status':'PASS_RELOCATED_SOURCE_GATE','canonical_input_sha256':input_sha,'relocation_ref':relocation})
    identity={'relocation_sha256':relocation['sha256'],'source_gate_sha256':gate['sha256'],'source_generation':generation}
    candidate=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    assets={}
    for kind in ('kb','projection','html'):
        path=tmp_path/(kind+'.bin');path.write_bytes((kind+' test').encode());assets[kind]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    value={'schema':'v4.workbench.single_kb_binding.v1','symbol':'002865.SZ','name':'钧达股份','source_date':'2026-10-30','observation_date':'2026-11-02','source_generation':generation,'source_input_sha256':input_sha,'numeric_manifest':numeric,'candidate_pool_member':False,'historical_PIT':False,'candidate_identity':identity,'candidate_generation':candidate,'source_gate_receipt':gate,'source_relocation':relocation,'assets':assets,'fields_count':57,'rows':2311,**wb.FLAGS}
    binding=_ref(tmp_path/'single.json',value);host=wb.ResearchWorkbenchHost.__new__(wb.ResearchWorkbenchHost)
    host.binding={'single_stock_research':binding};host._view=lambda date,revision=None: {'source_generation':generation,'source_identity':{'input_sha256':input_sha},'manifest':numeric,'rows':[{'symbol':str(i)} for i in range(172)]} if revision in (None,generation) else (_ for _ in ()).throw(ValueError('REVISION_CONFLICT'))
    host._observation_date=lambda date:'2026-11-02';host.classifications=SimpleNamespace(close=lambda:None)
    return host,value,binding


def test_single_stock_binds_11_2_to_10_30_without_modifying_pool(fixture):
    host,value,_=fixture;before=host._view('2026-10-30')['rows'];answer=host.single_stock_research('2026-10-30','002865.SZ',value['source_generation'])
    assert answer['observation_date']=='2026-11-02' and answer['source_date']=='2026-10-30'
    assert answer['candidate_pool_member'] is False and len(before)==172
    assert host._view('2026-10-30')['rows']==before and answer['fields_count']==57
    assert answer['assets']['kb']['sha256']==value['assets']['kb']['sha256']


def test_wrong_date_symbol_generation_or_changed_asset_fails(fixture):
    host,value,_=fixture
    with pytest.raises(KeyError):host.single_stock_research('2026-11-02','002865.SZ')
    with pytest.raises(KeyError):host.single_stock_research('2026-10-30','000001.SZ')
    with pytest.raises(ValueError):host.single_stock_research('2026-10-30','002865.SZ','d'*64)
    with pytest.raises(ValueError,match='ASSET_SHA_CONFLICT'):host.single_stock_asset('2026-10-30','002865.SZ','kb','f'*64,value['source_generation'])
    Path(value['assets']['kb']['path']).write_text('changed')
    with pytest.raises(ValueError,match='SOURCE_SHA_DRIFT'):host.single_stock_asset('2026-10-30','002865.SZ','kb',value['assets']['kb']['sha256'],value['source_generation'])


def test_single_stock_http_endpoints_and_asset_headers(fixture,tmp_path,monkeypatch):
    host,value,_=fixture;outer=_ref(tmp_path/'outer.json',{'ok':True})
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',outer['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',outer['sha256'])
    monkeypatch.setattr(wb,'ResearchWorkbenchHost',lambda source,binding:host)
    app=FastAPI();app.include_router(wb.create_workbench_router(object()))
    with TestClient(app) as client:
        root='/workbench/days/2026-10-30/single-research/002865.SZ';result=client.get(root,params={'revision':value['source_generation']});assert result.status_code==200
        url=root+'/assets/html';response=client.get(url,params={'revision':value['source_generation'],'sha256':value['assets']['html']['sha256']})
        assert response.status_code==200 and response.content==b'html test'
        assert "frame-ancestors 'self'" in response.headers['content-security-policy']
        assert client.get(root,params={'revision':'f'*64}).status_code==409
