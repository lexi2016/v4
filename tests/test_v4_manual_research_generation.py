"""Real review POST -> assemble_runtime -> run_generation.

Only final SDK and raw transport fixtures. Persisted output fixtures test only
idempotent reads; they are NOT an alternative graph implementation.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api.review_router import create_review_router
from test_vibe_assembly import config_fixture
from test_vibe_model_factory import SdkFixture
from test_research_review_generation import _payload
from vibe_ownership_fixtures import focus


def binding_fixture(tmp_path, *, mutate=None, client_factory=SdkFixture):
    path, pin, code, tr, c = config_fixture(tmp_path)
    if mutate:
        mutate(c)
        path.write_text(json.dumps(c))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
    root = Path(c['state_root']) / 'reviews'
    doc = {'schema_version':'v4.manual_review_bindings.v1',
           'config_root':str(tmp_path), 'review_root':str(root),
           'dates':{'20260911':{'config':path.name,'config_sha256':pin,
                              'source_manifest_sha256':code}}}
    registry = tmp_path/'manual-bindings.json'
    registry.write_text(json.dumps(doc))
    registry_pin = hashlib.sha256(registry.read_bytes()).hexdigest()
    def client(*, bindings=registry, sha=registry_pin):
        app = FastAPI()
        app.include_router(create_review_router(tmp_path/'api-data', review_root=root,
            generation_bindings_path=bindings, generation_bindings_sha256=sha,
            _generation_transport=tr, _generation_client_factory=client_factory))
        return TestClient(app)
    return client, registry, doc, tr, c


def test_post_missing_server_binding_is_explicit_and_get_stays_read_only(tmp_path):
    app=FastAPI();app.include_router(create_review_router(tmp_path/'api-data'))
    client=TestClient(app)
    assert client.post('/api/v3/review/generate',json={'date':'20260911'}).status_code==503
    before=list(tmp_path.rglob('*'))
    response=client.get('/api/v3/review?date=20260911')
    assert response.status_code==200
    assert list(tmp_path.rglob('*'))==before
    assert response.json()['research_review']['status']=='CANNOT_CONFIRM'


@pytest.mark.parametrize('body',[
    {'date':'20260230'}, {'date':'2026-09-11'}, {'date':20260911},
    {'date':'20260911','config':'/etc/passwd'},
    {'date':'20260911','replace':True}, {'date':'20260911','command':'ignored'},
])
def test_body_only_accepts_one_real_date(tmp_path,body):
    factory,_,_,tr,_=binding_fixture(tmp_path)
    assert factory().post('/api/v3/review/generate',json=body).status_code==422
    assert not tr.calls


def test_date_without_its_own_config_is_refused(tmp_path):
    factory,_,_,tr,_=binding_fixture(tmp_path)
    response=factory().post('/api/v3/review/generate',json={'date':'20260914'})
    assert response.status_code==404
    assert response.json()['detail']['code']=='DATE_NOT_CONFIGURED'
    assert not tr.calls


def test_does_not_relabel_0911_data_asof_for_0914(tmp_path):
    factory,path,doc,tr,c=binding_fixture(tmp_path)
    doc['dates']['20260914']=doc['dates'].pop('20260911')
    path.write_text(json.dumps(doc))
    response=factory(sha=hashlib.sha256(path.read_bytes()).hexdigest()).post(
        '/api/v3/review/generate',json={'date':'20260914'})
    assert response.status_code==422
    assert response.json()['detail']['code']=='CONFIG_DATE_MISMATCH'
    assert not tr.calls and not (Path(c['state_root'])/'manual_generation').exists()


@pytest.mark.parametrize('which',['registry','config','source','escape','reader_root'])
def test_approved_identity_and_roots_fail_closed(tmp_path,which):
    factory,path,doc,tr,c=binding_fixture(tmp_path)
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if which=='registry':sha='0'*64
    elif which=='config':doc['dates']['20260911']['config_sha256']='0'*64
    elif which=='source':doc['dates']['20260911']['source_manifest_sha256']='0'*64
    elif which=='escape':doc['dates']['20260911']['config']='../assembly.json'
    else:doc['review_root']=str(tmp_path/'different')
    if which!='registry':
        path.write_text(json.dumps(doc));sha=hashlib.sha256(path.read_bytes()).hexdigest()
    response=factory(sha=sha).post('/api/v3/review/generate',json={'date':'20260911'})
    assert response.status_code==503
    assert not tr.calls and not (Path(c['state_root'])/'manual_generation').exists()


def test_cross_origin_cannot_trigger_paid_work(tmp_path):
    factory,_,_,tr,_=binding_fixture(tmp_path)
    response=factory().post('/api/v3/review/generate',json={'date':'20260911'},
                            headers={'Origin':'https://other.invalid'})
    assert response.status_code==403 and not tr.calls


def test_persisted_artifact_fixture_duplicate_makes_no_provider_calls(tmp_path):
    from domains.research_review_generation import write_exact_review
    calls=[]
    def sdk(**kw):calls.append(kw);return SdkFixture(**kw)
    factory,_,_,tr,c=binding_fixture(tmp_path,client_factory=sdk)
    root=Path(c['state_root'])/'reviews'
    write_exact_review(root,'20260911',_payload(),mode='PERSISTED_ARTIFACT_FIXTURE')
    before=(root/'2026-09-11.json').read_bytes()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _: factory().post('/api/v3/review/generate',json={'date':'20260911'}),range(4)))
    assert all(r.status_code==200 and r.json()['status']=='ALREADY_EXISTS' for r in responses)
    assert not tr.calls and not calls
    assert (root/'2026-09-11.json').read_bytes()==before
    result=factory().get('/api/v3/review?date=20260911').json()['research_review']
    assert result['status']=='READY'


def test_provider_failure_is_sanitized_and_second_click_does_not_retry(tmp_path):
    calls=[]
    def fail(**kw):
        import asyncio
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        calls.append(threading.get_ident())
        raise RuntimeError('SYNTHETIC_SECRET_DO_NOT_ECHO /private/credential/path')
    factory,_,_,tr,c=binding_fixture(tmp_path,client_factory=fail)
    first=factory().post('/api/v3/review/generate',json={'date':'20260911'})
    assert first.status_code==502
    assert 'SYNTHETIC_SECRET' not in first.text and '/private/' not in first.text
    second=factory().post('/api/v3/review/generate',json={'date':'20260911'})
    assert second.status_code==409
    assert len(calls)==1 and not tr.calls
    assert not (Path(c['state_root'])/'reviews'/'2026-09-11.json').exists()


def test_actual_api_real_graph_then_get_and_duplicate(tmp_path):
    clients=[]
    class FinalSdk(SdkFixture):
        def __init__(self, **kw):
            super().__init__(**kw);self.deep=bool(clients);self.calls=0
        def invoke(self,prompt):
            self.calls+=1
            return SimpleNamespace(content=json.dumps(focus()) if self.deep else
                '[离线合成分析] '+'只讨论固定输入，不是行情或投资建议。'*20)
    def factory_sdk(**kw):
        c=FinalSdk(**kw);clients.append(c);return c
    factory,_,_,tr,c=binding_fixture(tmp_path,client_factory=factory_sdk)
    response=factory().post('/api/v3/review/generate',json={'date':'20260911'})
    assert response.status_code==200,response.text  # Missing real LangGraph is failure, never skip.
    assert response.json()['status']=='READY_FOR_REVIEW'
    payload=factory().get('/api/v3/review?date=20260911').json()
    assert payload['research_review']['artifact_sha256']==response.json()['artifact_sha256']
    assert [x.calls for x in clients]==[5,1]
    before=dict(tr.calls)
    again=factory().post('/api/v3/review/generate',json={'date':'20260911'})
    assert again.json()['status']=='ALREADY_EXISTS'
    assert dict(tr.calls)==before and [x.calls for x in clients]==[5,1]
