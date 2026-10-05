"""New target-day contract tests. Fixtures here are explicitly synthetic, not market evidence."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import importlib.util
import pytest

from v4.manager_research import existing_materials, workspace_discovery, workspace_projection

CUTOFF = '2026-09-20T23:10:00+08:00'
DATE = '20260921'


def planner():
    spec=importlib.util.find_spec('v4.manager_research.workspace_plan')
    assert spec is not None, 'native-calendar plan and per-stock planning module not implemented'
    from v4.manager_research import workspace_plan
    return workspace_plan


def context():
    return planner().plan_context(DATE, now=datetime.fromisoformat(CUTOFF))


def test_monday_includes_friday_not_future_monday():
    ctx=context()
    assert ctx['source_dates']==['20260917','20260918','20260919','20260920']
    assert ctx['market_session']=='20260918'
    assert ctx['plan_trade_date']==DATE
    assert ctx['focus_window_start']=='2026-09-17T16:10:00+08:00'
    assert ctx['focus_window_basis']=='TWO_COMPLETED_HK_SESSIONS_POST_CLOSE_WINDOW'
    assert ctx['research_cutoff']==CUTOFF


def test_two_completed_sessions_start_tuesday_window_at_older_session_close():
    ctx=planner().plan_context('20260922', now=datetime.fromisoformat('2026-09-22T00:23:09.863013+08:00'))
    assert ctx['market_session']=='20260921'
    assert ctx['market_session_close']=='2026-09-21T16:10:00+08:00'
    assert ctx['focus_window_start']=='2026-09-18T16:10:00+08:00'
    assert ctx['focus_window_basis']=='TWO_COMPLETED_HK_SESSIONS_POST_CLOSE_WINDOW'
    assert ctx['source_dates']==['20260918','20260919','20260920','20260921','20260922']


def test_half_day_close_is_native_and_can_anchor_window():
    ctx=planner().plan_context('20261230', now=datetime.fromisoformat('2026-12-30T00:30:00+08:00'))
    assert ctx['market_session']=='20261229'
    assert ctx['market_session_close']=='2026-12-29T16:10:00+08:00'
    assert ctx['focus_window_start']=='2026-12-24T12:10:00+08:00'
    assert ctx['source_dates']==['20261224','20261225','20261226','20261227','20261228','20261229','20261230']


def test_half_day_before_native_close_is_not_completed():
    ctx=planner().plan_context('20261230', now=datetime.fromisoformat('2026-12-24T12:09:00+08:00'))
    assert ctx['market_session']=='20261223'
    assert ctx['focus_window_start']=='2026-12-22T16:10:00+08:00'


def test_missing_half_day_close_is_an_explicit_calendar_gap(monkeypatch):
    from copy import deepcopy
    from dataclasses import replace
    from contracts import trading_calendar
    calendar=trading_calendar.load_market_calendar()
    markets=deepcopy(calendar.markets)
    markets['hk_securities']['half_day_close']=None
    monkeypatch.setattr(trading_calendar, 'load_market_calendar', lambda: replace(calendar, markets=markets))
    with pytest.raises(ValueError, match='PLAN_HALF_DAY_CLOSE_UNAVAILABLE'):
        planner().plan_context('20261230', now=datetime.fromisoformat('2026-12-30T00:30:00+08:00'))


def test_two_session_window_keeps_cutoff_and_close_boundaries():
    ctx=planner().plan_context('20260922', now=datetime.fromisoformat('2026-09-22T00:23:09.863013+08:00'))
    assert planner().temporal_role({'published_at':'2026-09-18T16:09:59+08:00'},ctx)=='BACKGROUND'
    assert planner().temporal_role({'published_at':'2026-09-18T16:10:00+08:00'},ctx)=='NEW_PLAN_PUBLICATION'
    assert planner().temporal_role({'published_at':'2026-09-21T13:45:49+08:00'},ctx)=='NEW_PLAN_PUBLICATION'
    assert planner().temporal_role({'published_at':'2026-09-22T00:23:10+08:00'},ctx)=='AFTER_CUTOFF_EXCLUDED'
    assert planner().temporal_role({'published_at':'2026-09-23T00:00:00+08:00'},ctx)=='AFTER_CUTOFF_EXCLUDED'


def test_hk_calendar_not_mainland_holiday():
    ctx=planner().plan_context('20260929', now=datetime.fromisoformat('2026-09-27T21:00:00+08:00'))
    assert ctx['market_session']=='20260925'


def test_before_close_uses_preceding_complete_session():
    ctx=planner().plan_context(DATE, now=datetime.fromisoformat('2026-09-18T15:59:00+08:00'))
    assert ctx['market_session']=='20260917'
    assert max(ctx['source_dates'])=='20260918'


def material(title='示例制药临床研究进展', quote='示例制药关键临床节点需确认。', published='2026-09-18T19:00:00+08:00', id='a'):
    return dict(material_id=id, original_article_id=id, verification='OWNER_VERIFIED',
        title=title, source_row={'stock_code':'601099','stock_name':'太平洋', 'evidence_sentence':quote},
        themes=['AI制药'], published_at=published, available_at=None, retrieved_at=None,
        source_refs=[{'status':'VERIFIED','payload_path':'research/archives/20260920.json','payload_sha256':'a'*64}],
        source_url='https://example.invalid/research/'+id, claim_type='RESEARCH_OPINION', archive_date='20260920')


def identity():
    return {'status':'OWNER_VERIFIED','source_date':'20260918','owner':'load_verified_hk_security_master',
            'artifact_sha256':'b'*64, 'manifest_sha256':'c'*64}


def discovered(rows=None, master=None):
    fn=getattr(workspace_discovery,'project_material_discovery',None)
    assert callable(fn), 'materials cannot create stocks independently of catalyst'
    return fn(rows or [material()], master or {'HK.09991':{'code':'HK.09991','name':'示例制药-B'}}, identity(), context())


def project(cards, mats):
    return workspace_projection.build_workspace(DATE, catalyst={'status':'NOT_MATERIALIZED','target_trade_date':DATE,'cards':[]},
        materials=mats,discovered_cards=cards, plan_context=context())


def test_empty_target_catalyst_stage_do_not_block_verified_material_stock():
    cards=discovered()
    assert len(cards)==1 and cards[0]['symbol']=='HK.09991'
    out=project(cards,[material()])
    assert out['summary']['stock_count']==1
    assert out['stocks'][0]['lanes']==['MATERIAL']
    assert next(x for x in out['lanes'] if x['lane']=='CATALYST')['state']=='NOT_RUN'
    assert out['summary']['formal_recommendation_count']==0
    assert out['stocks'][0]['connect_eligibility']!='VERIFIED_TARGET_UNIVERSE'


def test_six_digit_a_share_code_not_relabelled_as_hk():
    assert discovered([material('无香港主体的研究','A股太平洋经营分析')])==[]


def test_ambiguous_alias_not_mapped():
    assert discovered(master={'HK.09991':{'name':'示例制药-B'},'HK.09992':{'name':'示例制药-P'}})==[]


@pytest.mark.parametrize('pub', ['2026-09-21T10:00:00+08:00','2026-09-20T23:11:00+08:00'])
def test_future_material_excluded(pub):
    assert discovered([material(published=pub)])==[]


def test_missing_publication_not_counted_new():
    cards=discovered([material(published=None)])
    assert len(cards)==1 and cards[0]['temporal_role']=='PUBLICATION_UNKNOWN'
    out=project(cards,[material(published=None)])
    assert out['stocks'][0]['new_plan_publication_count']==0
    assert out['stocks'][0]['new_catalyst_count']==0


def test_old_background_not_new_plan_publication():
    cards=discovered([material(published='2026-09-16T17:00:00+08:00')])
    assert cards[0]['temporal_role']=='BACKGROUND'


def test_duplicate_materials_one_stock_preserve_all_relations():
    m1=material();m2={**m1,'material_id':'b'}
    cards=discovered([m1,m2])
    out=project(cards,[m1,m2])
    assert out['summary']['stock_count']==1
    s=out['stocks'][0]
    assert len(s['evidence'])==2 and s['event_group_count']==1
    assert s['new_plan_publication_count']==1 and s['new_catalyst_count']==0
    assert s['plan']['trigger_price'] is None and s['plan']['invalidation_price'] is None


def test_different_companies_have_different_evidence_bound_plans():
    rows=[material(), material('示例物流股东增持','示例物流股东计划增持，核查是否交割。', id='b')]
    cards=discovered(rows, {'HK.09991':{'name':'示例制药-B'},'HK.09992':{'name':'示例物流'}})
    out=project(cards,rows)
    plans=[s['plan'] for s in out['stocks']]
    assert len(plans)==2 and plans[0]['next_observation']!=plans[1]['next_observation']
    assert plans[0]['evidence_ids']!=plans[1]['evidence_ids']
    assert all(p['wait_conditions'] and p['key_risks'] and p['invalidation_conditions'] for p in plans)


def test_unverified_material_not_admitted():
    assert discovered([{**material(),'verification':'CANNOT_CONFIRM'}])==[]


def test_local_source_title_and_wechat_preserved():
    root=Path(__file__).resolve().parents[1]
    source=(root/'v4/manager_research/existing_materials.py').read_text()
    app=(root/'apps/api/v35_api/app.py').read_text()
    assert "article.get('title') or article.get('source_title')" in source
    assert 'wechat_archive_root=os.environ.get("V4_WECHAT_ARCHIVE_ROOT")' in app


def test_verified_price_not_rejected_merely_because_numeric():
    ctx=context();s={'symbol':'HK.09991','name':'示例制药','evidence':discovered()}
    quote={'verification':'OWNER_VERIFIED','symbol':'HK.09991','session_date':'20260918','currency':'HKD',
           'price_basis':'RAW','session_kind':'FULL_DAY_CLOSE','close':10.5,'pre_close':10.0,
           'low':9.8,'high':10.8,'amount':100_000_001,'amount_unit':'HKD',
           'authority_panel':{'owner':'V4_SHARED_HK_0_2_PANEL_AUTHORITY','panel_sha256':'e'*64},
           'source_refs':[{'owner':'CloseSnapshotStore.read_snapshot','payload_path':'hkconnect_close_snapshots/20260918.json','payload_sha256':'d'*64}]}
    p=planner().stock_plan(s,ctx,quote=quote)
    assert p['trigger_price']==10.5 and p['invalidation_price']==9.8
    assert p['criteria']['turnover_gt_100m_hkd']['status']=='PASS'
    assert p['criteria']['volume_expansion']['status']=='UNKNOWN'
    assert p['price_provenance']['symbol']=='HK.09991'
    assert p['price_provenance']['authority_panel']['panel_sha256']=='e'*64


@pytest.mark.parametrize('change', [{'currency':'USD'},{'session_date':DATE},{'verification':'UNVERIFIED'}, {'close':float('nan')}, {'price_basis':None}, {'symbol':'HK.09992'}])
def test_unverified_wrong_session_or_currency_quote_no_numeric(change):
    p=planner().stock_plan({'symbol':'HK.09991','name':'示例制药','evidence':discovered()},context(),quote={
        'verification':'OWNER_VERIFIED','symbol':'HK.09991','session_date':'20260918','currency':'HKD','price_basis':'RAW',
        'session_kind':'FULL_DAY_CLOSE','close':10.5,'low':9.8,'source_refs':[{'payload_sha256':'d'*64}],**change})
    assert p['trigger_price'] is None and p['invalidation_price'] is None


def test_original_service_future_plan_refresh_does_not_run_catalyst_producer(tmp_path):
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    assert callable(getattr(service,'refresh_workspace_plan',None)), 'original manager owner lacks future-plan refresh'
    before={p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_file()}
    first=service.get_workspace(DATE)
    after={p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_file()}
    assert after==before, 'read-only workspace GET wrote a file'
    saved=service.refresh_workspace_plan(DATE)
    assert saved['plan_product']['status']=='CURRENT'
    read=service.get_workspace(DATE)
    assert read['input_identity']==saved['input_identity']
    assert read['plan_product']['run_id']==saved['plan_product']['run_id']
    assert not (service.store.root/'workspace_runs').exists(), 'future plan ran historical catalyst refresh'
    assert (service.store.root/'workspace_plans'/DATE/'latest.json').is_file()
    assert read['summary']['formal_recommendation_count']==0


def test_missing_native_identity_is_gap_not_entire_workspace_exception(tmp_path):
    ctx=context()
    result=workspace_discovery.read_material_discovery([material()],ctx,tmp_path)
    assert result['cards']==[] and result['gaps']


def test_hk02_panel_witness_requires_target_manifest_and_checksum(tmp_path):
    planner_module=planner()
    asset=tmp_path/'assets'/'hk_0_2'
    panel_bytes=b'authority-panel-bytes'
    panel_sha=hashlib.sha256(panel_bytes).hexdigest()
    panel_dir=asset/'panels'/('20260918-'+panel_sha[:12])
    panel=panel_dir/'hkconnect_vipdoc_daily_panel.parquet'; panel.parent.mkdir(parents=True)
    panel.write_bytes(panel_bytes)
    manifest={
        'asset_schema_version':'v3_shared_data.hk_0_2_panel_asset.v2',
        'manifest_prepared_at':'2026-09-18T10:00:00+08:00',
        'panel_max_date':'20260918', 'panel_relative':str(panel.relative_to(asset)),
        'panel_sha256':panel_sha, 'panel_code_count':691, 'panel_rows':123,
        'source_contract':'tdx_vipdoc_71_day+verified_zero_trade_repairs',
        'research_only':True, 'production_allowed':False,
        'buy_gate_updated':False, 'orders_sent':False,
    }
    manifest_relative=str((panel_dir/'manifest.json').relative_to(asset))
    manifest_path=panel_dir/'manifest.json'; manifest_path.write_text(json.dumps(manifest))
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':manifest_relative}))
    witness,gaps=planner_module._read_hk02_panel_witness(tmp_path,'20260918')
    assert not gaps and witness['panel_sha256']==panel_sha and witness['price_currency']=='HKD'
    panel.write_bytes(b'tampered')
    witness,gaps=planner_module._read_hk02_panel_witness(tmp_path,'20260918')
    assert witness is None and gaps==['PLAN_HK_02_PANEL_AUTHORITY_CHECKSUM_MISMATCH']


def _write_hk02_revision(asset, day, directory, panel_bytes, prepared_at, *, recovery=None,
                         parent_panel_sha256=None):
    panel_sha=hashlib.sha256(panel_bytes).hexdigest()
    panel_dir=asset/'panels'/(directory+'-'+panel_sha[:12])
    panel_dir.mkdir(parents=True)
    panel=panel_dir/'hkconnect_vipdoc_daily_panel.parquet'
    panel.write_bytes(panel_bytes)
    manifest={
        'asset_schema_version':'v3_shared_data.hk_0_2_panel_asset.v2',
        'manifest_prepared_at':prepared_at,'panel_max_date':day,
        'panel_relative':str(panel.relative_to(asset)),'panel_sha256':panel_sha,
        'panel_code_count':716,'panel_rows':455948,
        'source_contract':'tdx_vipdoc_71_day+verified_zero_trade_repairs',
        'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
    }
    if recovery is not None:
        manifest.update(source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs+futu_history_gapfill',
                        history_recovery=recovery,parent_panel_sha256=parent_panel_sha256)
    manifest_path=panel_dir/'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    return str(manifest_path.relative_to(asset)),panel_sha


def _valid_history_recovery():
    return {
        'schema_version':'v4.hk_history_price_recovery.v1','source_date':'20260929',
        'requested_at':'2026-10-02T11:32:41.077000+08:00','received_at':'2026-10-02T04:13:04.458748+00:00',
        'row_count':696,'requested_code_count':696,'coverage_rate':1.0,
        'provider':'MIXED_PYTDX_HQ_DAILY_AND_FUTU_OPEND_HISTORY_KLINE','adjustment':'NONE',
        'natural_verified':False,
        'source_sha256':'c'*64,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
        'source_input_sha256':{'candidate':'a'*64},
    }


def test_hk02_panel_pointer_selects_verified_repair_only_after_it_is_available(tmp_path):
    asset=tmp_path/'assets'/'hk_0_2'
    asset.mkdir(parents=True)
    old_relative,old_sha=_write_hk02_revision(
        asset,'20260930','20260930',b'old exact panel','2026-09-30T09:20:05+08:00')
    new_relative,new_sha=_write_hk02_revision(
        asset,'20260930','20260930-history-20260929',b'repaired panel',
        '2026-10-02T06:04:00+00:00',recovery=_valid_history_recovery(),parent_panel_sha256=old_sha)
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':new_relative}))

    current,gaps=planner()._read_hk02_panel_witness(
        tmp_path,'20260930',research_cutoff='2026-10-02T14:05:00+08:00')
    assert not gaps and current['panel_sha256']==new_sha
    assert current['resolution']=='PANEL_LATEST_TARGET_OWNER_ASSET'
    assert current['history_source_date']=='20260929'

    historical,gaps=planner()._read_hk02_panel_witness(
        tmp_path,'20260930',research_cutoff='2026-10-02T13:00:00+08:00')
    assert not gaps and historical['panel_sha256']==old_sha
    assert historical['resolution']=='EXACT_DATE_IMMUTABLE_OWNER_ASSET_BEFORE_CUTOFF'


def test_hk02_panel_rejects_recovery_manifest_pinned_to_the_wrong_parent(tmp_path):
    asset=tmp_path/'assets'/'hk_0_2'
    asset.mkdir(parents=True)
    _old_relative,old_sha=_write_hk02_revision(
        asset,'20260930','20260930',b'original authoritative panel','2026-09-30T09:20:05+08:00')
    new_relative,_new_sha=_write_hk02_revision(
        asset,'20260930','20260930-history-20260929',b'repaired panel',
        '2026-10-02T06:04:00+00:00',recovery=_valid_history_recovery(),parent_panel_sha256='b'*64)
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':new_relative}))

    witness,gaps=planner()._read_hk02_panel_witness(
        tmp_path,'20260930',research_cutoff='2026-10-02T14:05:00+08:00')
    assert witness is None
    assert gaps==['PLAN_HK_02_PANEL_RECOVERY_PARENT_MISMATCH']


def test_hk02_panel_pointer_after_cutoff_fails_closed_without_older_revision(tmp_path):
    asset=tmp_path/'assets'/'hk_0_2'
    asset.mkdir(parents=True)
    new_relative,_=_write_hk02_revision(
        asset,'20260930','20260930-history-20260929',b'repaired panel',
        '2026-10-02T06:04:00+00:00',recovery=_valid_history_recovery(),parent_panel_sha256='b'*64)
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':new_relative}))
    witness,gaps=planner()._read_hk02_panel_witness(
        tmp_path,'20260930',research_cutoff='2026-10-02T13:00:00+08:00')
    assert witness is None and gaps==['PLAN_HK_02_PANEL_AFTER_RESEARCH_CUTOFF']


def test_hk02_panel_rejects_corrupt_pointed_recovery_manifest(tmp_path):
    asset=tmp_path/'assets'/'hk_0_2'
    asset.mkdir(parents=True)
    new_relative,_=_write_hk02_revision(
        asset,'20260930','20260930-history-20260929',b'repaired panel',
        '2026-10-02T06:04:00+00:00',recovery={**_valid_history_recovery(),'coverage_rate':0.99},
        parent_panel_sha256='b'*64)
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':new_relative}))
    witness,gaps=planner()._read_hk02_panel_witness(
        tmp_path,'20260930',research_cutoff='2026-10-02T14:05:00+08:00')
    assert witness is None and gaps==['PLAN_HK_02_PANEL_RECOVERY_LINEAGE_INVALID']


def test_amount_exactly_100m_does_not_pass():
    ctx=context()
    quote=dict(verification='OWNER_VERIFIED',symbol='HK.09991',session_date='20260918',currency='HKD',
        price_basis='RAW',session_kind='FULL_DAY_CLOSE',close=10.0,low=9.0,amount=100_000_000,amount_unit='HKD',
        source_refs=[{'payload_sha256':'d'*64}])
    p=planner().stock_plan({'symbol':'HK.09991','name':'示例制药','evidence':discovered()},ctx,quote=quote)
    assert p['criteria']['turnover_gt_100m_hkd']['status']=='FAIL'


def test_target_day_before_native_open_is_still_preopen_plan():
    ctx=planner().plan_context(DATE,now=datetime.fromisoformat('2026-09-21T00:09:00+08:00'))
    assert ctx['observation_phase']=='PREOPEN_PLAN'
    assert ctx['market_session']=='20260918'


def test_two_character_unique_chinese_issuer_in_delimited_title():
    fn=workspace_discovery.project_material_discovery
    cards=fn([material('【越疆】机器人研究','【越疆】订单等待核实。')],{'HK.09993':{'name':'越疆'}},identity(),context())
    assert len(cards)==1 and cards[0]['symbol']=='HK.09993'


def test_short_issuer_not_matched_inside_longer_company_name():
    fn=workspace_discovery.project_material_discovery
    assert fn([material('京东方研究','京东方订单')],{'HK.09993':{'name':'京东'}},identity(),context())==[]


@pytest.mark.parametrize(('text','master','expected'),[
    ('周大福创建订单待核',
     {'HK.00659':{'name':'周大福创建'},'HK.01929':{'name':'周大福'}},['HK.00659']),
    ('碧桂园服务订单待核',
     {'HK.06098':{'name':'碧桂园服务'},'HK.02007':{'name':'碧桂园'}},['HK.06098']),
    ('南方港股通红利政策变化',
     {'HK.03469':{'name':'南方港股通红利'},'HK.03432':{'name':'南方港股通'}},['HK.03469']),
])
def test_native_name_prefix_collision_uses_longest_non_overlapping_match(text,master,expected):
    cards=workspace_discovery.project_material_discovery(
        [material(title=text,quote=text)],master,identity(),context())
    assert [card['symbol'] for card in cards]==expected


def test_native_name_separate_source_positions_keep_both_issuers():
    text='周大福创建订单待核。周大福基本面待核。'
    master={'HK.00659':{'name':'周大福创建'},'HK.01929':{'name':'周大福'}}
    cards=workspace_discovery.project_material_discovery(
        [material(title=text,quote=text)],master,identity(),context())
    assert [card['symbol'] for card in cards]==['HK.00659','HK.01929']


def test_workspace_api_is_bodyless_same_origin_and_original_owner(tmp_path):
    import asyncio, httpx
    from fastapi import FastAPI
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    app=FastAPI();app.include_router(create_manager_research_router(service))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local.test') as c:
            before=list((tmp_path/'manager').rglob('*.json'))
            rejected=await c.post('/api/v4/manager/research/workspace/refresh?date='+DATE,json={'stocks':['HK.09991']})
            assert rejected.status_code==422
            cross=await c.post('/api/v4/manager/research/workspace/refresh?date='+DATE,headers={'Origin':'https://other.invalid'})
            assert cross.status_code==403
            assert list((tmp_path/'manager').rglob('*.json'))==before
            get=await c.get('/api/v4/manager/research/workspace?date='+DATE)
            assert get.status_code==200 and get.json()['plan_product']['status']=='NOT_MATERIALIZED'
            post=await c.post('/api/v4/manager/research/workspace/refresh?date='+DATE,headers={'Origin':'http://local.test'})
            assert post.status_code==200 and post.json()['plan_product']['consumed'] is True
            read=await c.get('/api/v4/manager/research/workspace?date='+DATE)
            assert read.json()['plan_product']['sha256']==post.json()['plan_product']['sha256']
    asyncio.run(run())


def test_tampered_saved_plan_not_presented_as_success(tmp_path):
    import json
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    service.refresh_workspace_plan(DATE)
    path=service.store.root/'workspace_plans'/DATE/'latest.json'
    value=json.loads(path.read_text());value['workspace']['summary']['stock_count']=99
    path.write_text(json.dumps(value))
    assert service.get_workspace(DATE)['plan_product']['status']=='READBACK_FAILED'


def test_source_dates_read_uses_context_not_fixed_natural_day_offsets():
    class Hourly:
        days=[]
        def list_slots(self,day,mode): self.days.append(day);return []
        def read_exact(self,*args,**kwargs):raise AssertionError('no slots')
    class Daily:
        def read_exact(self,day): return None
    class Source:
        hourly_store=Hourly();store=Daily()
    result=existing_materials.read_existing_materials(DATE,research_source=Source(),context=context())
    assert result['coverage']['window_dates']==['20260917','20260918','20260919','20260920']
    assert Source.hourly_store.days==['20260917','20260918','20260919','20260920']


def test_exact_date_saved_plan_cannot_hide_new_owner_failure(tmp_path):
    from copy import deepcopy
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.workspace import _readback_plan
    service=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    saved=service.refresh_workspace_plan(DATE)
    current=deepcopy(saved)
    current['lanes'][1]['state']='FAILED'
    current['lanes'][1]['failure_reasons']=['CONTROLLED_LATER_OWNER_ATTEMPT_FAILED']
    out=_readback_plan(service.store,DATE,current)
    assert out['plan_product']['consumed'] is True
    assert out['lanes'][1]['state']=='FAILED'
