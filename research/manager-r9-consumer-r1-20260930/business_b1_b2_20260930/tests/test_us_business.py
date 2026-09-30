"""Synthetic prose/provenance; original native parser and relation admission."""
from datetime import datetime
from copy import deepcopy
import pytest
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.issuer_us_relations import material_us_relations
from v4.manager_research.workspace_projection import digest

START=datetime.fromisoformat('2026-09-28T16:10:00+08:00')
CUT=datetime.fromisoformat('2026-09-30T09:29:30+08:00')
SYMBOL='HK.00001'


def cards(text,**overrides):
    row=dict(body_text=text);row.update(overrides.pop('source_row',{}))
    material=dict(material_id=digest(text),title='样本科技业务披露',source_kind='SYNTHETIC_VERIFIED_ARTICLE',
        verification='OWNER_VERIFIED',source_refs=[dict(status='VERIFIED',payload_sha256='a'*64)],
        source_row=row,claim_type='SOURCE_STATEMENT',published_at='2026-09-29T18:00:00+08:00',
        available_at='2026-09-29T18:01:00+08:00',retrieved_at='2026-09-29T18:01:00+08:00')
    material.update(overrides)
    context=dict(plan_trade_date='20260930',market_session='20260929',
        focus_window_start=START.isoformat(),research_cutoff=CUT.isoformat())
    audit=[]
    result=project_material_discovery([material],{SYMBOL:dict(name='样本科技')},
        dict(status='OWNER_VERIFIED',source_date='20260929',artifact_sha256='b'*64),context,rejection_audit=audit)
    return result,audit


@pytest.mark.parametrize('verb',['簽署','供應','授權','許可'])
def test_traditional_explicit_relation_survives_native_prose_pipeline(verb):
    text=('样本科技已增加供應NASDAQ:QTEST的產能。' if verb=='供應'
          else '样本科技已'+verb+'NASDAQ:QTEST使用相關技術。')
    got,rejected=cards(text)
    assert got, rejected
    industries,individuals,audit=material_us_relations(got,START,CUT)
    assert SYMBOL in individuals, audit
    assert individuals[SYMBOL][0]['related_us_symbols']==['QTEST']
    assert individuals[SYMBOL][0]['is_new_catalyst'] is False
    assert audit[0]['reason']=='ACCEPTED'


def test_traditional_business_vocabulary_uses_same_existing_theme():
    got,rejected=cards('样本科技已增加生物製藥產能。')
    assert got,rejected
    industries,individuals,audit=material_us_relations(got,START,CUT)
    assert SYMBOL in industries, audit
    assert industries[SYMBOL][0]['manager_theme']=='BIOMEDICINE'
    assert individuals=={}


@pytest.mark.parametrize('text,kwargs',[
    ('样本科技已签署与礼来的合作协议。',{'source_row':{'related_us_symbols':['LLY']}}),
    ('样本科技的生物医药业务增加。',{'source_row':{'related_us_symbols':['LLY']}}),
    ('样本科技并未授权NASDAQ:QTEST使用技术。',{}),
])
def test_names_metadata_or_negated_clause_do_not_create_us_individual_link(text,kwargs):
    got,_=cards(text,**kwargs)
    industries,individuals,audit=material_us_relations(got,START,CUT)
    assert individuals=={}


@pytest.mark.parametrize('changes,reason',[
    ({'available_at':None,'retrieved_at':None},'ISSUER_ACQUISITION_TIME_MISSING_OR_INVALID'),
    ({'available_at':'2026-09-30T10:00:00+08:00'},'ISSUER_ACQUISITION_TIME_OUTSIDE_WINDOW_OR_ORDER_INVALID'),
    ({'published_at':'2026-09-01T10:00:00+08:00'},'ISSUER_PUBLICATION_OUTSIDE_WINDOW'),
])
def test_clock_and_standing_contract_gates_remain_strict(changes,reason):
    got,rejected=cards('样本科技已签署NASDAQ:QTEST的合作协议。',**changes)
    # Discovery may reject future evidence earlier; neither stage admits it.
    industries,individuals,audit=material_us_relations(got,START,CUT)
    assert individuals=={}
    if got:assert any(reason in a['rejection_reasons'] for a in audit)


def test_no_rewrite_of_original_prose_span_or_source_clock():
    text='样本科技已簽署NASDAQ:QTEST使用相關技術。'
    got,_=cards(text);before=deepcopy(got)
    _,individuals,_=material_us_relations(got,START,CUT)
    assert SYMBOL in individuals
    rel=individuals[SYMBOL][0]
    assert text[rel['start']:rel['end']]==rel['issuer_quote']
    assert rel['issuer_available_at']=='2026-09-29T18:01:00+08:00'
    assert got==before


def test_original_relation_join_admits_explicit_ticker_and_keeps_unmapped_raw_mover():
    from v4.manager_research.research_evidence import collect_attention_evidence
    got,_=cards('样本科技已簽署NASDAQ:QTEST使用相關技術。')
    us=dict(status='READY',mapping_eligible=True,captured_at='2026-09-30T06:00:00+08:00',
        source_identity={'status':'VERIFIED','payload_sha256':'c'*64,'receipt_sha256':'d'*64,'manifest_sha256':'e'*64},raw_industry_up=[],
        raw_individual_up=[dict(status='READY',symbol='QTEST',pct_change=5),dict(status='READY',symbol='UNMAPPED',pct_change=8)])
    before=deepcopy(us)
    evidence=collect_attention_evidence(market_screen={},stocks=[],material_cards=got,themes=[],
        announcement_observation={},us_market=us,start=START,cutoff=CUT)
    assert SYMBOL in evidence.us_individual
    d=evidence.us_mapping_diagnostics
    assert d['accepted_hk_mapping_count']==1
    assert next(x for x in d['individual'] if x['symbol']=='UNMAPPED')['reason']=='NO_STRUCTURED_HK_US_RELATION'
    assert d['raw_movers_retained_when_unmapped'] is True and us==before
