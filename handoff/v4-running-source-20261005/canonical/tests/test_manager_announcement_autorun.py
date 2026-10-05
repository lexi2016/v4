"""SIMULATED transport/data; actual original owner/provider/parser/store paths."""
from datetime import timedelta
from copy import deepcopy
import json
import pytest
from announcement_autorun_fixtures import OwnerFixture, DAY
from v4.manager_research import announcement_source as source
from v4.manager_research import workspace_announcements as owner


def scheduled(f, priorities=()):
    return f.service.refresh_announcements(DAY, schedule={
        'policy':'BALANCED_V1','now':f.now.isoformat(),'priority_codes':list(priorities)})


def test_original_owner_manual_capture_and_read_are_offline_and_revalidated(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch); f.add()
    value=f.service.refresh_announcements(DAY)
    assert value['status']=='PARTIAL'
    assert len(value['positive_observations'])==1
    calls=len(f.calls); again=f.service.get_announcements(DAY)
    assert len(f.calls)==calls and again['product_identity']==value['product_identity']
    ref=again['positive_observations'][0]['evidence'][0]['body_ref']
    path=f.materials.root/f.materials._blob_relative(ref['blob_sha256'])
    path.write_bytes(b'corrupted')
    assert f.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    f.service.close()


def test_scheduled_cycle_uses_same_owner_and_duplicate_minute_does_not_request(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch); f.add()
    first=scheduled(f); calls=len(f.calls)
    second=scheduled(f)
    assert len(f.calls)==calls
    assert first['attempt']['execution_kind']=='SCHEDULED_REFRESH'
    assert second['attempt']['run_id']==first['attempt']['run_id']
    assert first['coverage']['directory_exhaustion']=='UNVERIFIED'
    assert first['coverage']['natural_run_verified'] is False
    assert first['positive_observations']
    f.service.close()


def test_rollover_sees_post_start_publication_preserves_both_run_provenance(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch); f.add(minute=0,slug='old'); f.add(minute=2,slug='later')
    first=scheduled(f); assert len(first['positive_observations'])==1
    f.now+=timedelta(minutes=3)
    second=scheduled(f)
    assert len(second['official_documents'])==2
    assert len(second['capture_runs'])==2
    assert second['capture_runs'][0]['query_as_of']!=second['capture_runs'][1]['query_as_of']
    assert any('later' in doc['source_url'] for doc in second['official_documents'])
    f.service.close()


def test_fair_rotation_reaches_high_code_without_ascending_restart(tmp_path,monkeypatch):
    codes=[f'HK.{n:05d}' for n in range(1,42)]+['HK.09690']
    f=OwnerFixture(tmp_path,monkeypatch,codes)
    seen=set()
    for _ in range(3):
        value=scheduled(f);seen.update(value['attempt']['selected_issuers']);f.now+=timedelta(minutes=1)
    assert seen==set(codes)
    assert value['coverage']['queried_issuer_count']==len(codes)
    f.service.close()


def test_important_high_code_is_served_without_displacing_fair_quota(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch,[f'HK.{n:05d}' for n in range(1,61)]+['HK.09690'])
    value=scheduled(f,['HK.09690'])
    assert 'HK.09690' in value['attempt']['selected_issuers']
    assert len(value['attempt']['fair_issuers'])==20
    assert value['attempt']['policy_status']=='PROPOSAL_ONLY'
    f.service.close()


def test_failed_new_query_does_not_erase_previously_observed_risk(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch); f.add(text='The Company terminated the agreement.')
    first=scheduled(f); assert first['risk_alerts']
    f.now+=timedelta(minutes=1); f.fail.add('HK.09690')
    value=scheduled(f)
    assert value['risk_alerts'] and value['coverage']['failed_issuers']
    assert value['status']=='PARTIAL'
    f.service.close()


def test_original_over_budget_pdf_is_saved_as_document_failure_not_whole_batch(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add(pages=60)
    value=f.service.refresh_announcements(DAY)
    assert value['status']=='PARTIAL'
    assert value['pending_review'][0]['reason']=='PDF_PAGE_BUDGET_EXCEEDED'
    calls=len(f.calls);assert f.service.get_announcements(DAY)['status']=='PARTIAL';assert len(f.calls)==calls
    f.service.close()


def test_event_lane_uses_prior_oversold_without_waiting_for_today_volume():
    from v4.manager_research.announcement_observation import event_lane
    context=dict(plan_trade_date=DAY,market_session='20260923',research_cutoff='2026-09-24T08:01:00+08:00')
    screen=dict(status='READY',verified_session='20260923',input_identity='a'*64,
        authority={'source':'SIMULATED'},cards=[],strict=[],near=[dict(code='HK.09690',name='Fixture',
        verified_session=20260923,oversold_flag=True,prior60_session_count=60,close=10.26,
        prior60_session_high=13.91,oversold_cutoff_80pct_prior60_high=11.128,volume_ratio_5d=.59)],pending=[])
    review=dict(status='PARTIAL',attempt=None,product_identity={'sha256':'b'*64},coverage={'directory_exhaustion':'UNVERIFIED'},gaps=[],
        official_documents=[dict(symbol='HK.09690',name='Fixture',event_id='c'*64,title='official entry',
        published_at='2026-09-24T08:00:00+08:00',available_at='2026-09-24T08:00:00+08:00',retrieved_at='2026-09-24T08:00:00+08:00',
        source_url='https://www1.hkexnews.hk/fixture.pdf',source_refs=[{'SIMULATED':True}],body_status='BODY_UNREAD',document_sha256=None)])
    before=deepcopy(screen)
    value=event_lane(review,screen,context)
    assert value['observations'][0]['observation_status']=='PRIOR_OVERSOLD_OFFICIAL_OBSERVATION'
    assert value['observations'][0]['intraday_price_volume']['status']=='UNKNOWN'
    assert value['observations'][0]['focus_eligible'] is False
    assert screen==before


def test_manual_refresh_after_automatic_remains_visible_and_keeps_auto_run(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add(slug='auto')
    first=scheduled(f)
    f.now+=timedelta(minutes=3);f.add(minute=2,slug='manual')
    second=f.service.refresh_announcements(DAY)
    assert len(second['official_documents'])==2
    assert len(second['capture_runs'])==2
    assert second['attempt']['execution_kind']=='MANUAL_REFRESH'
    f.service.close()


def test_missing_autorun_index_cannot_hide_committed_documents(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add()
    scheduled(f)
    (f.service.store.root/'workspace_announcements'/DAY/'autorun.json').unlink()
    assert f.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    f.service.close()


def test_resealed_index_cannot_drop_negative_run_and_get_never_repairs(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add(text='The Company terminated the agreement.')
    scheduled(f)
    path=f.service.store.root/'workspace_announcements'/DAY/'autorun.json'
    state=json.loads(path.read_text());state['runs']={};path.write_text(json.dumps(owner._seal(state)))
    before=path.read_bytes();calls=len(f.calls)
    assert f.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    assert path.read_bytes()==before and len(f.calls)==calls
    # Only a later explicit writer may recover the still-committed originals.
    f.now+=timedelta(minutes=1)
    assert scheduled(f)['risk_alerts']
    f.service.close()


def test_document_queue_resume_keeps_old_cutoff_and_reuses_original_pdf(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch)
    for i in range(6):f.add(slug=str(i),text=f'The Company entered into agreement {i}.')
    parser_calls=[];original_parser=source.extract_pdf_pages
    def counted_parser(raw,**kwargs):
        parser_calls.append(raw)
        return original_parser(raw,**kwargs)
    monkeypatch.setattr(source,'extract_pdf_pages',counted_parser)
    first=scheduled(f);original=first['capture_runs'][0]
    assert first['coverage']['pending_document_count']==2
    assert len(parser_calls)==4
    f.now+=timedelta(minutes=1);second=scheduled(f)
    resumed=next(r for r in second['capture_runs'] if r['run_id']==original['run_id'])
    assert resumed['query_as_of']==original['query_as_of'] and resumed['revision']==3
    pdfcalls=[x['url'] for x in f.calls if x['url'].endswith('.pdf')]
    assert len(pdfcalls)==len(set(pdfcalls))==6
    assert len(parser_calls)==6
    f.service.close()


def test_cookie_prime_and_exact_query_form_are_recorded(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add();scheduled(f)
    physical=f.calls
    from v4.manager_research.hkex_provider import TITLE_SEARCH_URL
    posts=[(i,c) for i,c in enumerate(physical) if c['method']=='POST']
    assert len(posts)==2
    for i,c in posts:
        assert physical[i-1]['method']=='GET' and physical[i-1]['url'].startswith(TITLE_SEARCH_URL+'?')
        assert b'stockId=' in c['body'] and b'from=' in c['body'] and b'to=' in c['body']
    f.service.close()


def test_request_budget_exhaustion_is_partial_and_not_fictitious_coverage(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch,[f'HK.{i:05d}' for i in range(1,41)])
    from v4.manager_research import announcement_autorun as auto
    from v4.manager_research.announcement_source import CaptureBudget
    monkeypatch.setattr(auto,'CaptureBudget',lambda:CaptureBudget(max_requests=5))
    value=scheduled(f)
    assert value['attempt']['provider_request_count']==5
    assert value['coverage']['queried_issuer_count']==2
    assert len(value['coverage']['pending_issuers'])==38
    assert len(value['attempt']['input_coverage']['unqueried_selected_issuers'])==18
    f.service.close()


def test_same_date_restart_uses_durable_cursor_and_duplicate_gate(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch,[f'HK.{i:05d}' for i in range(1,61)])
    first=scheduled(f);f.service.close();calls=len(f.calls)
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    f.service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'state'),None,f.provider,
        material_store=f.materials,workspace_security_master_root=f.master)
    assert scheduled(f)['attempt']['run_id']==first['attempt']['run_id'] and len(f.calls)==calls
    f.now+=timedelta(minutes=1);second=scheduled(f)
    assert set(second['attempt']['fair_issuers']).isdisjoint(first['attempt']['fair_issuers'])
    f.service.close()


def test_native_master_failure_is_an_attempt_not_a_false_not_run(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.service._workspace_security_master_root=None
    with pytest.raises(ValueError,match='ANNOUNCEMENT_NATIVE_MASTER_ROOT_NOT_BOUND'):scheduled(f)
    value=f.service.get_announcements(DAY)
    assert value['attempt']['state']=='FAILED'
    assert 'ANNOUNCEMENT_NATIVE_MASTER_ROOT_NOT_BOUND' in value['attempt']['failure_reasons']
    assert not f.calls
    f.service.close()


def test_pdf_parse_cache_reuses_body_but_revalidates_raw_each_get(tmp_path,monkeypatch):
    f=OwnerFixture(tmp_path,monkeypatch);f.add(text='Unique cached source for raw revalidation 20261003.')
    scheduled(f);f.now+=timedelta(minutes=1);scheduled(f)
    first=f.service.get_announcements(DAY)
    assert first['coverage']['source_revalidation']['pdf_reparses']==0
    assert first['coverage']['source_revalidation']['raw_reference_reads']>0
    ref=first['official_documents'][0]['source_refs'][-1]
    (f.materials.root/f.materials._blob_relative(ref['blob_sha256'])).write_bytes(b'changed after GET')
    assert f.service.get_announcements(DAY)['status']=='READBACK_FAILED'
    f.service.close()
