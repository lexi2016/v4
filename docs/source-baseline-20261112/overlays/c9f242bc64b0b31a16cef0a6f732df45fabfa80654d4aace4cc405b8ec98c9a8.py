"""Issue8 synthetic unit scenarios plus explicitly identified frozen subtrees."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import pytest

from v4.manager_research import connect_selection as cs
from v4.manager_research.announcement_observation import event_lane
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace_projection import FLAGS, digest
from v4.manager_research.existing_materials import project_archive
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.issuer_us_relations import material_us_relations

CTX = dict(plan_trade_date='20261002', market_session='20260930',
           focus_window_start='2026-09-29T16:10:00+08:00',
           research_cutoff='2026-10-03T12:18:06.597568+08:00')
UNKNOWN = dict(status='CANNOT_CONFIRM', target_trade_date='20261002', codes=[],
               source=None, identity=None,
               gaps=['HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_V2_ARTIFACT_MISSING'])


def scope():
    source = dict(sha256='a'*64, source_date='20261002', market='HK_CONNECT',
                  role='HK_CONNECT_FULL_MARKET_AUTHORITY')
    return dict(status='OWNER_VERIFIED', target_trade_date='20261002', codes=['HK.01234'],
                source=source, identity=digest(['20261002',['HK.01234'],'a'*64]), gaps=[],
                calendar_applicability=dict(status='APPLICABLE',reason='HK_CONNECT_TRADING_DAY',
                    target_trade_date='20261002'))


def positive(symbol='HK.01234'):
    return dict(symbol=symbol, name='合成公司',event_id='e1',proposition_id='p1',
        document_sha256='b'*64, disposition='POSITIVE_OBSERVATION', action='WATCH_ONLY',
        published_at='2026-09-30T17:00:00+08:00',retrieved_at='2026-10-02T08:00:00+08:00',
        available_at='2026-10-02T08:01:00+08:00',focus_eligible=False,
        support=dict(disposition='POSITIVE_OBSERVATION',polarity='AFFIRMED',action_subject=symbol,
                     quote='Synthetic existing owner statement, not a real security'),
        evidence=[dict(body_ref={'body_sha256':'b'*64},source_url='https://issuer.invalid/fixture')],**FLAGS)


def review():
    p = positive()
    doc = {k:deepcopy(p[k]) for k in ('symbol','name','event_id','document_sha256','published_at','available_at','retrieved_at')}
    doc.update(body_status='BODY_PARSED')
    return dict(status='PARTIAL',official_documents=[doc],positive_observations=[p],
        coverage=dict(all_official_announcements_captured=False,positive_observation_count=1),
        gaps=['ISSUER_QUERY_FAILURES'],eastmoney_hk_status='PARTIAL',
        eastmoney_hk_gaps=['EASTMONEY_NON_EXHAUSTIVE'],eastmoney_hk_documents=[])


def attention(lane,screen=None,us=None,context=None):
    return build_research_attention('20261002',context=context or CTX,market_screen=screen or {},
        stocks=[],material_cards=[],themes=[],announcement_observation=lane,
        us_market=us or dict(status='READY',mapping_eligible=True,research_material_input={'complete':True},
                            raw_industry_up=[],raw_individual_up=[]))


@pytest.fixture
def synthetic_calendar(monkeypatch,tmp_path):
    """Native resolver, synthetic calendar JSON; never claimed to be active Mac JSON."""
    import contracts.trading_calendar as tc
    def market(derives=None, holidays=None, halves=None):
        return dict(label='SYNTHETIC_FIXTURE',derives_from=derives or [],
                    full_day_sessions=[{'start':'0930','end':'1600'}],half_day_sessions=[{'start':'0930','end':'1200'}],
                    full_day_close='1610',half_day_close='1210',half_days=halves or [],holiday_periods=holidays or [])
    payload=dict(schema_version=tc.SCHEMA_VERSION,year=2026,timezone='Asia/Shanghai',
        official_sources=[dict(market=k,name='SYNTHETIC_NOT_OFFICIAL',url='https://fixture.invalid/'+k) for k in tc.MARKET_KEYS],
        markets=dict(a_share=market(holidays=[{'name':'synthetic closure','start':'20261001','end':'20261007'}]),
                     hk_securities=market(halves=['20260928']),
                     hk_connect_southbound=market(['a_share','hk_securities'])))
    path=tmp_path/'synthetic_calendar.json';path.write_text(json.dumps(payload))
    monkeypatch.setattr(tc,'CALENDAR_PATH',path)
    return path


def test_closed_connect_is_not_applicable_even_when_membership_root_absent(monkeypatch,synthetic_calendar):
    monkeypatch.delenv('V4_MANAGER_UNIVERSE_ROOT',raising=False)
    ctx={**CTX,'calendar_sha256':hashlib.sha256(synthetic_calendar.read_bytes()).hexdigest()}
    out=cs.read_scope(ctx)
    assert out['calendar_applicability']['status']=='NOT_APPLICABLE'
    assert out['calendar_applicability']['hk_securities_state']=='FULL_TRADING_DAY'
    assert out['calendar_applicability']['hk_connect_state']=='NON_TRADING_DAY'
    assert out['status']=='CANNOT_CONFIRM' and out['codes']==[]
    assert out['gaps']==['HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND']
    formal=cs.selection_diagnostics({'target_trade_date':'20261002'}, {}, {}, out, [])['formal_selection']
    assert formal['status']=='NOT_APPLICABLE' and formal['reason']=='HK_CONNECT_NON_TRADING_DAY'


@pytest.mark.parametrize('problem',['missing_sha','drift','missing_file'])
def test_unverified_calendar_never_claims_closed_or_open(monkeypatch,synthetic_calendar,problem):
    monkeypatch.delenv('V4_MANAGER_UNIVERSE_ROOT',raising=False)
    ctx={**CTX,'calendar_sha256':hashlib.sha256(synthetic_calendar.read_bytes()).hexdigest()}
    if problem=='missing_sha':ctx.pop('calendar_sha256')
    if problem=='drift':ctx['calendar_sha256']='0'*64
    if problem=='missing_file':synthetic_calendar.unlink()
    out=cs.read_scope(ctx)
    assert out['calendar_applicability']['status']=='CANNOT_CONFIRM'


@pytest.mark.parametrize('date,expected',[('20260929','APPLICABLE'),('20260928','APPLICABLE'),('20261003','NOT_APPLICABLE')])
def test_calendar_full_half_and_weekend(monkeypatch,synthetic_calendar,date,expected):
    monkeypatch.delenv('V4_MANAGER_UNIVERSE_ROOT',raising=False)
    out=cs.read_scope({**CTX,'plan_trade_date':date,'calendar_sha256':hashlib.sha256(synthetic_calendar.read_bytes()).hexdigest()})
    assert out['calendar_applicability']['status']==expected


@pytest.mark.parametrize('app',['NOT_APPLICABLE','CANNOT_CONFIRM'])
def test_formal_gate_stays_empty_even_with_same_day_membership(app):
    s=scope();s['calendar_applicability']['status']=app
    value=dict(target_trade_date='20261002',stocks=[dict(symbol='HK.01234',name='fixture')],
               focus_symbols=['HK.01234'],company_events=[dict(symbol='HK.01234')],themes=[])
    before=deepcopy(value)
    out=cs.gate_workspace(value,s)
    assert out['stocks']==out['focus_symbols']==out['company_events']==[]
    assert value==before


def test_open_unknown_membership_not_promoted_and_prior_day_rejected():
    s={**deepcopy(UNKNOWN),'calendar_applicability':scope()['calendar_applicability']}
    formal=cs.selection_diagnostics({'target_trade_date':'20261002'}, {}, {}, s, [])['formal_selection']
    assert formal['status']=='CANNOT_CONFIRM'
    d1=scope();d1['source']['source_date']='20260930'
    accepted,rejected=cs.filter_cards([{'symbol':'HK.01234'}],d1)
    assert accepted==[] and rejected[0]['reason']=='TARGET_HK_CONNECT_MEMBERSHIP_DATE_OR_ROLE_MISMATCH'


def test_scope_filter_keeps_counts_gaps_and_original_lane_unchanged():
    lane=event_lane(review(),{},CTX);before=deepcopy(lane)
    scr,filtered=cs.evidence_view({'cards':[{'symbol':'HK.01234'}]},lane,UNKNOWN)
    assert filtered['official_documents']==[] and scr['cards']==[]
    diag=filtered['research_scope_diagnostics']
    assert diag['counts']['official_documents']=={'input':1,'admitted':0,'rejected':1}
    assert diag['status']=='CANNOT_CONFIRM' and diag['gaps']==UNKNOWN['gaps']
    assert lane==before
    a=attention(filtered,scr)
    assert a['status']=='READY_WITH_GAPS'
    assert a['coverage']['official_symbol_count']==0
    assert len(a['observation_only']['cards'])==1
    row=a['observation_only']['cards'][0]
    assert row['target_connect_membership']['status']=='CANNOT_CONFIRM'
    assert row['focus_eligible'] is row['qualified'] is row['buy_allowed'] is False
    assert a['cards']==[]
    assert 'ISSUER_QUERY_FAILURES' in a['gaps']
    assert 'EASTMONEY_NON_EXHAUSTIVE' in a['gaps']


def test_verified_scope_admits_fresh_official_evidence_only_and_does_not_create_focus():
    rv=review();rv['official_documents'].append({**rv['official_documents'][0],'symbol':'HK.09999'})
    scr,lane=cs.evidence_view({},event_lane(rv,{},CTX),scope())
    a=attention(lane,scr)
    assert [r['symbol'] for r in a['cards']]==['HK.01234']
    assert a['coverage']['official_symbol_count']==1
    assert a['existing_focus_rank_unchanged'] and a['stage_unchanged']
    assert a['observation_only']['cards'][0]['focus_eligible'] is False


@pytest.mark.parametrize('bad',['missing_retrieved','missing_available','late','stale','naive','wrong_subject','missing_ref','wrong_hash','duplicate'])
def test_observation_only_never_uses_invalid_or_duplicate_evidence(bad):
    rv=review();p=rv['positive_observations'][0]
    if bad=='missing_retrieved':p.pop('retrieved_at')
    if bad=='missing_available':p.pop('available_at')
    if bad=='late':p['available_at']='2026-10-04T01:00:00+08:00'
    if bad=='stale':p['published_at']='2026-09-01T01:00:00+08:00'
    if bad=='naive':p['available_at']='2026-10-02T01:00:00'
    if bad=='wrong_subject':p['support']['action_subject']='HK.09999'
    if bad=='missing_ref':p['evidence']=[]
    if bad=='wrong_hash':p['evidence'][0]['body_ref']['body_sha256']='z'*64
    if bad=='duplicate':rv['positive_observations'].append(deepcopy(p))
    scr,lane=cs.evidence_view({},event_lane(rv,{},CTX),UNKNOWN)
    a=attention(lane,scr)
    assert len(a['observation_only']['cards'])==(1 if bad=='duplicate' else 0)
    assert a['cards']==[]


def test_source_and_us_gap_statuses_remain_separate_not_ready():
    scr,lane=cs.evidence_view({},event_lane(review(),{},CTX),scope())
    us=dict(status='PARTIAL',mapping_eligible=True,gaps=['US_SOURCE_PARTIAL'],
            research_material_input={'complete':False,'gaps':['ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:fixture']})
    out=attention(lane,scr,us)
    assert out['status']=='READY_WITH_GAPS'
    assert out['input_diagnostics']['official_announcements']['status']=='PARTIAL'
    assert out['input_diagnostics']['eastmoney_selection']['status']=='PARTIAL'
    assert out['input_diagnostics']['us_relations']['assessment_state']=='NOT_EVALUATED'
    assert 'US_SOURCE_PARTIAL' in out['gaps']
    assert 'ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:fixture' in out['gaps']


def test_gap_only_change_changes_attention_identity_but_read_clock_does_not():
    scr,lane=cs.evidence_view({},event_lane(review(),{},CTX),UNKNOWN)
    a=attention(lane,scr)
    other=deepcopy(lane);other['gaps'].append('NEW_SOURCE_GAP')
    b=attention(other,scr)
    assert a['input_identity']!=b['input_identity']
    c=attention(lane,scr,context={**CTX,'research_cutoff':'2026-10-03T12:19:06.597568+08:00'})
    assert a['input_identity']==c['input_identity']


def archive_cards(clocks,body='星海科技与US.VRT签署数据中心设备供货协议。'):
    article=dict(article_id='synthetic-article',source_title='星海科技业务记录',body=body,themes=['DATA_CENTER'],
                 published_at='2026-09-30T17:00:00+08:00',**clocks)
    binding=dict(status='VERIFIED',payload_path='research/archives/20260930.json',payload_sha256='c'*64)
    materials,gaps=project_archive(dict(archive_date='20260930',articles=[article]),binding,'20260930')
    cards=project_material_discovery(materials,{'HK.01234':{'name':'星海科技'}},
        {'status':'OWNER_VERIFIED','artifact_sha256':'d'*64,'source_date':CTX['market_session']},CTX)
    return materials,cards,gaps


@pytest.mark.parametrize('missing',[None,'available_at','retrieved_at','both'])
def test_true_archive_clock_mapping_and_missing_clock_branches(missing):
    clocks=dict(retrieved_at='2026-10-02T08:00:00+08:00',available_at='2026-10-02T08:01:00+08:00')
    if missing=='both':clocks={}
    elif missing:clocks.pop(missing)
    materials,cards,gaps=archive_cards(clocks)
    assert len(cards)==1
    for field in ('available_at','retrieved_at'):
        assert materials[0][field]==cards[0][field]==clocks.get(field)
    inds,individuals,audit=material_us_relations(cards,datetime.fromisoformat(CTX['focus_window_start']),datetime.fromisoformat(CTX['research_cutoff']))
    if missing:
        assert not inds and not individuals
        assert 'ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:synthetic-article' in gaps
        assert 'ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID' in audit[0]['rejection_reasons']
    else:
        assert individuals and inds and not gaps


def test_legal_clocks_do_not_replace_independent_business_relationship():
    _,cards,gaps=archive_cards(dict(retrieved_at='2026-10-02T08:00:00+08:00',available_at='2026-10-02T08:01:00+08:00'),
                              body='星海科技发布营收增长公告。')
    assert cards and not gaps
    inds,individuals,audit=material_us_relations(cards,datetime.fromisoformat(CTX['focus_window_start']),datetime.fromisoformat(CTX['research_cutoff']))
    assert not inds and not individuals
    assert audit[0]['reason']=='NO_SUBJECT_BOUND_BUSINESS_OR_US_RELATION'


def test_frozen_positive_subtree_preserved_without_promoting_five_stocks():
    f=json.loads((Path(os.environ['V4_INPUT_ROOT'])/'evidence/FROZEN_SELECTED_FIELDS.json').read_text())
    # Exact supplied subtree. Does not fabricate the omitted 797 document rows.
    rv=f['announcement_review'];ctx=f['plan_context'];s=f['selection_diagnostics']['membership']
    sc,lane=cs.evidence_view({},event_lane(rv,{},ctx),s)
    out=attention(lane,sc,context=ctx)
    assert len(out['observation_only']['cards'])==9
    assert len({r['symbol'] for r in out['observation_only']['cards']})==5
    assert out['cards']==[] and out['status']=='READY_WITH_GAPS'
    assert all(r['target_connect_membership']['status']=='CANNOT_CONFIRM' for r in out['observation_only']['cards'])
    assert out['input_diagnostics']['official_announcements']['coverage']==rv['coverage']
    assert f['focus_symbols']==f['stocks']==[]


@pytest.mark.parametrize('bad',['unsafe_owner_flag','late_body_ref','late_directory_ref','bad_identity_shape'])
def test_retained_observation_rejects_unsafe_flags_late_refs_and_bad_identity(bad):
    rv=review();p=rv['positive_observations'][0]
    if bad=='unsafe_owner_flag':p['production_allowed']=True
    if bad=='late_body_ref':p['evidence'][0]['body_ref']['retrieved_at']='2026-10-04T08:00:00+08:00'
    if bad=='late_directory_ref':p['evidence'][0]['directory_ref']={'retrieved_at':'2026-10-04T08:00:00+08:00'}
    if bad=='bad_identity_shape':p['proposition_id']=['not-a-scalar']
    scr,lane=cs.evidence_view({},event_lane(rv,{},CTX),UNKNOWN)
    out=attention(lane,scr)
    assert out['observation_only']['cards']==[]


def test_two_source_join_still_needs_ready_us_evidence_with_legal_issuer_times():
    from v4.manager_research.research_evidence import collect_attention_evidence
    _,cards,_=archive_cards(dict(retrieved_at='2026-10-02T08:00:00+08:00',available_at='2026-10-02T08:01:00+08:00'))
    market=dict(status='READY',mapping_eligible=True,captured_at='2026-10-02T20:15:06Z',
        source_identity={'status':'VERIFIED','payload_sha256':'f'*64,'receipt_sha256':'1'*64,'manifest_sha256':'2'*64},
        raw_industry_up=[{'label':'数据中心','status':'READY','pct_change':1.0}],
        raw_individual_up=[{'symbol':'VRT','change_pct':2,'session_date':'20261002'}])
    def run(us):
        return collect_attention_evidence(market_screen=None,stocks=[],material_cards=cards,themes=[],
            announcement_observation=None,us_market=us,
            start=datetime.fromisoformat(CTX['focus_window_start']),cutoff=datetime.fromisoformat(CTX['research_cutoff']))
    ready=run(market)
    assert ready.us_industry and ready.us_individual
    blocked=run({**market,'mapping_eligible':False})
    assert not blocked.us_industry and not blocked.us_individual
