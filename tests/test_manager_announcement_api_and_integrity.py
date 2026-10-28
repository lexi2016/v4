"""Actual router + original owner in isolated ASGI host, SIMULATED upstream.
Not the complete app, not a live API or native Mac acceptance.
"""
import hashlib,json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from announcement_autorun_fixtures import OwnerFixture,DAY
from v4.manager_research import workspace_announcements as owner


def test_real_router_post_calls_original_owner_get_does_not_collect(tmp_path,monkeypatch):
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    f=OwnerFixture(tmp_path,monkeypatch);f.add()
    app=FastAPI();app.include_router(create_manager_research_router(f.service))
    with TestClient(app) as client:
        initial=client.get('/api/v4/manager/research/announcements',params={'date':DAY})
        assert initial.status_code==200 and initial.json()['status']=='NOT_RUN' and not f.calls
        post=client.post('/api/v4/manager/research/announcements/refresh',params={'date':DAY})
        assert post.status_code==200 and post.json()['positive_observations']
        calls=len(f.calls)
        assert client.get('/api/v4/manager/research/announcements',params={'date':DAY}).status_code==200
        assert len(f.calls)==calls
        assert client.post('/api/v4/manager/research/announcements/refresh',params={'date':DAY},json={'schedule':True}).status_code==422
        assert client.post('/api/v4/manager/research/announcements/refresh',params={'date':DAY},headers={'origin':'https://example.com'}).status_code==403
        assert len(f.calls)==calls
    f.service.close()


def test_actual_workspace_keeps_latest_attempt_without_implicit_collection(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add();f.service.refresh_announcements(DAY)
    calls=len(f.calls)
    value=f.service.get_workspace(DAY,now=f.now)
    assert value['owner_chain']['announcements']['latest_attempt']['owner']==owner.OWNER
    assert value['announcement_observation']['latest_attempt']==value['announcement_review']['attempt']
    assert value['announcement_observation']['independent_of_strict_near_focus'] is True
    assert len(f.calls)==calls
    # Existing plan projection may fail or materialize from available isolated
    # inputs, but neither outcome may collect official announcements.
    try:f.service.refresh_workspace_plan(DAY)
    except (ValueError,RuntimeError,OSError):pass
    assert len(f.calls)==calls
    f.service.close()


@pytest.mark.parametrize('mutation',['directory_failed','pdf_drop_failed','pdf_label_unread'])
def test_original_raw_derivation_rejects_resealed_risk_hiding(tmp_path,monkeypatch,mutation):
    f=OwnerFixture(tmp_path,monkeypatch);f.add(text='The Company terminated the agreement.')
    f.service.refresh_announcements(DAY)
    path=f.service.store.root/'workspace_announcements'/DAY/'latest.json';p=json.loads(path.read_text())
    if mutation=='directory_failed':
        q=p['queries'][-1];q.update(status='FAILED',reason='SIMULATED',entries=[],rejected=[],directory_ref=None)
        p['documents']=[];p['pending_documents']=[]
    elif mutation=='pdf_drop_failed':
        p['documents'][0].update(body_ref=None,parse_status='FAILED',reason='PDF_PAGE_BUDGET_EXCEEDED')
    else:p['documents'][0].update(parse_status='BODY_UNREADABLE',reason='NO_READABLE_PDF_BODY')
    path.write_text(json.dumps(owner._seal(p)))
    assert f.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    f.service.close()


@pytest.mark.parametrize('mutate',[
    lambda s:s.update(verified_session='20260922'),
    lambda s:s['near'][0].update(prior60_session_count=59),
    lambda s:s['near'][0].update(oversold_flag=False),
    lambda s:s['near'][0].update(close=float('nan')),
    lambda s:s.update(input_identity=None),
])
def test_prior_oversold_missingness_not_promoted(tmp_path,monkeypatch,mutate):
    from v4.manager_research.announcement_observation import event_lane
    f=OwnerFixture(tmp_path,monkeypatch);f.add();review=f.service.refresh_announcements(DAY)
    screen=dict(verified_session='20260923',input_identity='a'*64,authority={},
        near=[dict(code='HK.09690',verified_session=20260923,oversold_flag=True,prior60_session_count=60,
                   close=10.26,prior60_session_high=13.91)])
    mutate(screen)
    lane=event_lane(review,screen,dict(plan_trade_date=DAY,market_session='20260923',research_cutoff=f.now.isoformat()))
    assert not lane['observations'] and len(lane['pending_observations'])==1
    f.service.close()


def test_frozen_same_input_plan_does_not_hide_new_announcement_attempt(tmp_path,monkeypatch):
    """Real store/readback function; only runtime state changes, no new sources."""
    from v4.manager_research.workspace import _readback_plan,PLAN_SCHEMA
    from v4.manager_research.workspace_projection import digest,FLAGS
    f=OwnerFixture(tmp_path,monkeypatch);f.service.refresh_announcements(DAY)
    saved=f.service.get_workspace(DAY,now=f.now)
    product=dict(schema_version=PLAN_SCHEMA,target_trade_date=DAY,run_id='c'*32,
        generated_at=f.now.isoformat(),input_identity=saved['input_identity'],workspace=saved,**FLAGS)
    product['sha256']=digest(product)
    f.service.store._write_atomic(f.service.store.root/'workspace_plans'/DAY/'latest.json',product)
    current=deepcopy(saved)
    attempt=deepcopy(current['announcement_review']['attempt']);attempt.update(state='FAILED',failure_reasons=['SIMULATED_LATER_FAILURE'])
    current['announcement_review'].update(status='FAILED',attempt=attempt)
    current['owner_chain']['announcements'].update(status='FAILED',latest_attempt=attempt)
    current['announcement_observation'].update(status='FAILED',latest_attempt=attempt)
    result=_readback_plan(f.service.store,DAY,current)
    assert result['plan_product']['consumed'] is True
    assert result['announcement_observation']==current['announcement_observation']
    assert result['announcement_observation']['latest_attempt']==result['owner_chain']['announcements']['latest_attempt']
    f.service.close()


@pytest.mark.parametrize('text',['The Company entered into an agreement.','The Company terminated the agreement.'])
def test_official_research_note_has_watch_only_action_and_is_store_safe(tmp_path,monkeypatch,text):
    from v4.manager_research.safety import assert_manager_safe_tree
    from v4.manager_research.announcement_observation import event_lane
    f=OwnerFixture(tmp_path,monkeypatch);f.add(text=text);view=f.service.refresh_announcements(DAY)
    claims=[*view['positive_observations'],*view['risk_alerts']]
    assert claims
    assert all(row['action']=='WATCH_ONLY' and row['research_note'] for row in claims)
    lane=event_lane(view,{},dict(plan_trade_date=DAY,market_session='20260923',research_cutoff=f.now.isoformat()))
    assert_manager_safe_tree(dict(announcement_review=view,announcement_observation=lane))
    f.service.close()


def test_real_workspace_plan_persists_official_view_without_relaxing_safety(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add();f.service.refresh_announcements(DAY)
    before=len(f.calls)
    result=f.service.refresh_workspace_plan(DAY)
    assert result['plan_product']['consumed'] is True
    assert result['announcement_observation']['official_documents']
    assert len(f.calls)==before
    f.service.close()
