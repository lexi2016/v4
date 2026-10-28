"""Independent catalyst lane. Unit fixtures are SIMULATED; real probe is separate."""
from pathlib import Path
from datetime import datetime, timezone
import json,hashlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v35_api.app import create_app
from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.materials import MaterialStore

@pytest.fixture
def service(tmp_path):
    def stage(_):
        raise AssertionError('independent catalyst lane MUST NOT read Stage')
    s=ManagerResearchJobService(ManagerResearchStore(tmp_path/'state'),stage,None,material_store=MaterialStore(tmp_path/'state/materials'))
    yield s
    s.close()

def client(service):
    app=FastAPI(); app.include_router(create_manager_research_router(service)); return TestClient(app)

def bundle(tmp_path):
    now=datetime.now(timezone.utc).isoformat()
    text='SIMULATED Drug discovery news. Company HKEX: 1234 AI drug development.'
    raw=text.encode(); (tmp_path/'source.txt').write_bytes(raw)
    source=dict(source_id='s',url='https://example.org/simulated',path='source.txt',sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=now,representation='VERIFIED_WEB_EXCERPT',retrieval_method='test_fixture',verification_reference='SIMULATED')
    event=dict(event_key='e',title='SIMULATED AI drug discovery',published_date='2026-09-18',published_at=None,time_precision='DAY',themes=['AI_HEALTHCARE'],source_id='s',evidence_quote='Drug discovery news.',event_nature='OFFICIAL_PUBLICATION',mappings=[dict(symbol='HK.01234',name='Company',relationship_type='INDUSTRY_INFERENCE',rationale='SIMULATED industry overlap, no partnership claim',identity_source_id='s',identity_quote='Company HKEX: 1234',relation_source_id='s',relation_quote='AI drug development.')])
    obj=dict(schema_version='v4.manager_research.catalyst_admission.v1',target_trade_date='20260918',researcher='SIMULATED',research_kind='POST_HOC_RESEARCH',sources=[source],events=[event],limitations=['SIMULATED'])
    path=tmp_path/'admission.json'; path.write_text(json.dumps(obj)); return path, hashlib.sha256(path.read_bytes()).hexdigest()

@pytest.mark.parametrize('override', [True, False])
def test_api_news_data_root_binding_is_scoped_to_catalyst_lane(tmp_path, monkeypatch, override):
    api_root = tmp_path / 'api-data'
    hourly_root = tmp_path / 'hourly-news'
    if override:
        monkeypatch.setenv('V4_MANAGER_NEWS_DATA_ROOT', str(hourly_root))
    else:
        monkeypatch.delenv('V4_MANAGER_NEWS_DATA_ROOT', raising=False)
    app = create_app(data_root=api_root, shared_data_root=tmp_path / 'shared',
                     ledger_root=tmp_path / 'ledger', stage_center_selection_root=tmp_path / 'stage',
                     manager_research_state_root=tmp_path / 'state', current_date='20260918')
    service = app.state.manager_research_service
    try:
        assert service._catalyst_data_root == (hourly_root if override else api_root)
        assert service.store.root == tmp_path / 'state'
    finally:
        service.close()

def test_empty_stage_does_not_disable_independent_refresh(service):
    c=client(service)
    r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918')
    assert r.status_code==200
    assert r.json()['status']=='EMPTY'
    assert r.json()['can_refresh'] is True
    assert r.json()['stage_dependency'] is False

def test_admitted_evidence_renders_unknown_quotes_without_stage(service,tmp_path):
    path,sha=bundle(tmp_path)
    assert hasattr(service,'admit_catalyst_materials'), 'existing owner needs material admission entry'
    service.admit_catalyst_materials(path,expected_sha256=sha)
    c=client(service); r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918')
    assert r.status_code==200
    card=r.json()['cards'][0]
    assert card['symbol']=='HK.01234' and card['relationship_type']=='INDUSTRY_INFERENCE'
    assert card['volume_condition']=='UNKNOWN' and card['price_position']=='UNKNOWN'
    assert card['captured_at_target'] is False and card['temporal_classification']=='POST_HOC_RESEARCH'
    assert card['qualified'] is False and r.json()['buy_gate_updated'] is False
    assert c.get('/api/v4/manager/research/catalyst-observations?date=20260918').json()['cards']==r.json()['cards']

def test_browser_cannot_supply_sources(service):
    c=client(service)
    r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918',json={'symbol':'HK.01234'})
    assert r.status_code==422
    r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918',headers={'origin':'https://evil.invalid'})
    assert r.status_code==403

def admit_fixture(service,tmp_path,edit=None):
    path,_=bundle(tmp_path)
    if edit:
        obj=json.loads(path.read_bytes()); edit(obj); path.write_text(json.dumps(obj))
    service.admit_catalyst_materials(path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    c=client(service)
    assert c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918').status_code==200
    return c

def test_overseas_event_without_hk_mapping_keeps_theme_card(service,tmp_path):
    c=admit_fixture(service,tmp_path,lambda o:o['events'][0].update(mappings=[]))
    card=c.get('/api/v4/manager/research/catalyst-observations?date=20260918').json()['cards'][0]
    assert card['symbol'] is None and card['relationship_type']=='UNMAPPED'
    assert card['themes']==['AI_HEALTHCARE']

@pytest.mark.parametrize('attack',['rehash_projection','material_bytes','material_index'])
def test_real_get_rejects_disk_tampering_even_if_output_rehashed(service,tmp_path,attack):
    c=admit_fixture(service,tmp_path)
    path=service.store.root/'catalyst_observations/20260918.json'
    value=json.loads(path.read_bytes())
    if attack=='rehash_projection':
        value['cards'][0]['mapping_reason']='forged partnership'
        from v4.manager_research.contracts import sha256_json
        value['content_sha256']=sha256_json({k:v for k,v in value.items() if k!='content_sha256'})
        path.write_text(json.dumps(value))
    elif attack=='material_bytes':
        digest=value['cards'][0]['source_refs'][0]['sha256']
        (service.store.root/'materials/blobs'/digest).write_bytes(b'forged source')
    else:
        path=next((service.store.root/'materials/index').glob('*.json'))
        item=json.loads(path.read_bytes());item['url']='https://example.org/forged';path.write_text(json.dumps(item))
    r=c.get('/api/v4/manager/research/catalyst-observations?date=20260918')
    assert r.status_code==409 and 'cards' not in r.json()

def test_direct_link_requires_named_entity_in_event_quote(service,tmp_path):
    path,_=bundle(tmp_path);obj=json.loads(path.read_bytes());obj['events'][0]['mappings'][0]['relationship_type']='DIRECT';path.write_text(json.dumps(obj))
    with pytest.raises(ValueError,match='DIRECT_ENTITY'):
        service.admit_catalyst_materials(path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def test_after_close_event_is_not_attributed_to_morning(service,tmp_path):
    c=admit_fixture(service,tmp_path,lambda o:o['events'][0].update(published_at='2026-09-18T17:00:00+08:00',time_precision='SECOND'))
    card=c.get('/api/v4/manager/research/catalyst-observations?date=20260918').json()['cards'][0]
    assert card['temporal_classification']=='AFTER_CLOSE_RESEARCH' and card['captured_at_target'] is False

def test_exact_date_never_falls_back_to_other_admission(service,tmp_path):
    c=admit_fixture(service,tmp_path)
    assert c.get('/api/v4/manager/research/catalyst-observations?date=20260917').json()['cards']==[]

def test_shared_hourly_owner_theme_survives_empty_stage_and_no_quotes(service,tmp_path):
    from test_manager_r2_rework import make_news,APP,AS_OF
    from infrastructure.manager_input_attestation import publish_attestation
    path=make_news(tmp_path/'news',attest=False)
    value=json.loads(path.read_bytes())
    value['research_items'][0].update(title='SIMULATED AI 医药研发发布',themes=['AI医疗'],url='https://example.org/ai-drug-news')
    path.write_text(json.dumps(value,ensure_ascii=False))
    publish_attestation(path,data_root=tmp_path/'news',owner_root=APP,available_at=AS_OF.replace(minute=0,second=1))
    service._catalyst_data_root=tmp_path/'news';service._catalyst_news_owner_root=APP
    c=client(service);r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918')
    assert r.status_code==200, r.text
    assert len(r.json()['cards'])==1
    card=r.json()['cards'][0]
    assert card['relationship_type']=='UNMAPPED' and card['temporal_classification']=='CAPTURED_AT_TARGET'
    assert card['themes']==['AI_HEALTHCARE']
    assert c.get('/api/v4/manager/research/catalyst-observations?date=20260918').status_code==200

def test_hourly_replay_binds_complete_scan_window_including_unattested_archives(service,tmp_path):
    from test_manager_r2_rework import make_news,APP,AS_OF
    from infrastructure.manager_input_attestation import publish_attestation
    news=tmp_path/'news'
    positive=make_news(news,slot='1500',attest=False)
    value=json.loads(positive.read_bytes())
    value['research_items'][0].update(title='SIMULATED AI 医药研发发布',themes=['AI医疗'],url='https://example.org/ai-drug-news')
    positive.write_text(json.dumps(value,ensure_ascii=False))
    publish_attestation(positive,data_root=news,owner_root=APP,available_at=AS_OF.replace(minute=0,second=1))
    unattested=make_news(news,slot='1600',attest=False)
    service._catalyst_data_root=news;service._catalyst_news_owner_root=APP
    c=client(service)
    refreshed=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918')
    assert refreshed.status_code==200, refreshed.text
    body=refreshed.json()
    news_bindings=[b for b in body['input_bindings'] if b['kind']=='HOURLY_NEWS']
    assert len(news_bindings)==2
    assert any(b['publication_sha256'] is None for b in news_bindings)
    assert len(body['cards'])==1
    replayed=c.get('/api/v4/manager/research/catalyst-observations?date=20260918')
    assert replayed.status_code==200, replayed.text
    assert replayed.json()['input_bindings']==body['input_bindings']
    assert replayed.json()['gaps']==body['gaps']
    publication=service.store.root/'catalyst_observations/20260918.json'
    forged=json.loads(publication.read_bytes())
    next(binding for binding in forged['input_bindings'] if binding['kind']=='HOURLY_NEWS')['artifact_sha256']='0'*64
    from v4.manager_research.contracts import sha256_json
    forged['content_sha256']=sha256_json({k:v for k,v in forged.items() if k!='content_sha256'})
    publication.write_text(json.dumps(forged))
    assert c.get('/api/v4/manager/research/catalyst-observations?date=20260918').status_code==409

def test_english_healthcare_theme_requires_structured_classification():
    from domains.manager_catalyst_tracking import _themes
    row={'title':'SIMULATED Anthropic AI drug discovery','themes':['AI医疗']}
    assert _themes(row)==[]
    assert 'AI_HEALTHCARE' in _themes(row, include_extended_themes=True)
    assert 'AI_HEALTHCARE' not in _themes({'title':row['title']}, include_extended_themes=True)

def test_rehashed_publication_envelope_metadata_is_rejected(service,tmp_path):
    c=admit_fixture(service,tmp_path)
    path=service.store.root/'catalyst_observations/20260918.json'
    value=json.loads(path.read_bytes())
    value['gaps']=[]
    from v4.manager_research.contracts import sha256_json
    value['content_sha256']=sha256_json({k:v for k,v in value.items() if k!='content_sha256'})
    path.write_text(json.dumps(value))
    r=c.get('/api/v4/manager/research/catalyst-observations?date=20260918')
    assert r.status_code==409 and 'cards' not in r.json()

def test_refresh_rejects_forged_admission_receipt(service,tmp_path):
    c=admit_fixture(service,tmp_path)
    receipt=next((service.store.root/'catalyst_admissions/20260918').glob('*.receipt.json'))
    value=json.loads(receipt.read_bytes()); value['material_owner']='forged.owner'
    receipt.write_text(json.dumps(value))
    r=c.post('/api/v4/manager/research/catalyst-observations/refresh?date=20260918')
    assert r.status_code==409 and 'cards' not in r.json()

def test_malformed_publication_maps_to_typed_integrity_response(service,tmp_path):
    c=admit_fixture(service,tmp_path)
    (service.store.root/'catalyst_observations/20260918.json').write_text('{')
    r=c.get('/api/v4/manager/research/catalyst-observations?date=20260918')
    assert r.status_code==409 and 'cards' not in r.json()

def test_minute_precision_is_preserved_not_promoted_to_seconds(service,tmp_path):
    c=admit_fixture(service,tmp_path,lambda o:o['events'][0].update(published_at='2026-09-18T10:02:00+00:00',time_precision='MINUTE'))
    card=c.get('/api/v4/manager/research/catalyst-observations?date=20260918').json()['cards'][0]
    assert card['time_precision']=='MINUTE' and card['temporal_classification']=='AFTER_CLOSE_RESEARCH'
