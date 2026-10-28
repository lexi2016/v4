"""Synthetic issuer names and statements; NOT live beneficiaries or historical data."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import pytest
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.research_evidence import (
    collect_attention_evidence,
    structured_us_issuer_relations,
    verified_theme_relations,
)
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.us_market_bridge import project_us_market

CTX={'plan_trade_date':'20260928','market_session':'20260925',
     'research_cutoff':'2026-09-28T08:00:00+08:00','focus_window_start':'2026-09-24T16:10:00+08:00'}
START=datetime.fromisoformat(CTX['focus_window_start']);END=datetime.fromisoformat(CTX['research_cutoff'])
MASTER={'HK.01234':{'name':'星海科技','a_share_code':'600001'}}
IDENTITY={'status':'OWNER_VERIFIED','source_date':'20260925','artifact_sha256':'a'*64,
          'owner':'NATIVE_TEST_MASTER','manifest_sha256':'b'*64}
REF={'status':'VERIFIED','payload_sha256':'c'*64,'payload_path':'research/fixture.json',
     'receipt_sha256':'d'*64,'manifest_sha256':'e'*64}

def material(text,**extra):
    row={'article_id':'fixture','body':text,**extra}
    return {'material_id':'fixture','original_article_id':'fixture','title':'星海科技业务记录',
      'verification':'OWNER_VERIFIED','source_row':row,'source_refs':[deepcopy(REF)],
      'published_at':'2026-09-25T12:00:00+08:00','retrieved_at':'2026-09-25T12:01:00+08:00',
      'available_at':'2026-09-25T12:02:00+08:00','source_url':'https://issuer.invalid/report'}

def cards(m):return project_material_discovery([m],MASTER,IDENTITY,CTX)
def us(label='数据中心',symbol='VRT'):
    return {'status':'READY','mapping_eligible':True,'captured_at':'2026-09-25T20:15:06Z',
      'expected_us_session':'20260925','source_identity':{'status':'VERIFIED','payload_sha256':'f'*64,
      'receipt_sha256':'1'*64,'manifest_sha256':'2'*64},
      'raw_industry_up':[{'label':label,'status':'READY','pct_change':1.0,'proxy_symbols':['TEST']}],
      'raw_individual_up':[{'symbol':symbol,'change_pct':2,'session_date':'20260925'}]}

def collect(rows,market=None,themes=None):
    return collect_attention_evidence(market_screen=None,stocks=[],material_cards=rows,themes=themes or [],
        announcement_observation=None,us_market=market or us(),start=START,cutoff=END)

@pytest.mark.parametrize('label,term',[
 ('光伏','光伏组件'),('新能源','风电设备'),('半导体','半导体芯片'),('存储','存储芯片'),
 ('CPO','光互连CPO'),('数据中心','数据中心液冷设备'),('银行金融','商业银行贷款'),
 ('电网','电网设备'),('铜/有色','铜矿'),('军工','军工设备'),('黄金','黄金矿山'),
 ('消费','消费品'),('卫星','卫星设备'),('锂电池','锂电池'),('机器人','工业机器人'),
 ('自动驾驶','自动驾驶系统')])
def test_native_issuer_business_proposition_reaches_us_industry_without_third_theme_article(label,term):
    c=cards(material(f'星海科技发布{term}业务订单增长公告。'))
    assert c, 'real native issuer projection must produce the fixture card'
    e=collect(c,us(label))
    assert 'HK.01234' in e.us_industry
    mapping=e.us_industry['HK.01234'][0]
    assert mapping['hk_relation']['issuer_quote']
    assert mapping['hk_relation']['source_refs'][0]['payload_sha256']=='c'*64
    assert mapping['source_identity']['payload_sha256']=='f'*64
    assert mapping['hk_relation']['connect_eligibility']=='TARGET_DATE_NOT_CHECKED'

@pytest.mark.parametrize('ticker',['VRT','COHR','LITE','NVDA'])
def test_explicit_owner_us_symbol_reaches_same_issuer_relation(ticker):
    c=cards(material(f'星海科技与US.{ticker}签署数据中心设备供货协议。',related_us_symbols=[ticker]))
    e=collect(c,us(symbol=ticker))
    assert 'HK.01234' in e.us_individual
    assert e.us_mapping_diagnostics['accepted_hk_mapping_count']>=1

@pytest.mark.parametrize('mutation', ['missing_time','late_time','bad_time','wrong_identity','cross_market',
                                      'no_refs','unverified_ref','metadata_only','negated','third_party'])
def test_bad_relation_is_not_manufactured_to_make_nonzero(mutation):
    m=material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT'])
    if mutation=='missing_time':m.update(available_at=None,retrieved_at=None)
    if mutation=='late_time':m['available_at']='2026-09-28T08:00:01+08:00'
    if mutation=='bad_time':m['available_at']='yesterday'
    if mutation=='no_refs':m['source_refs']=[]
    if mutation=='unverified_ref':m['source_refs']=[{**REF,'status':'CANNOT_CONFIRM'}]
    if mutation=='metadata_only':m['source_row']['body']='星海科技发布数据中心业务订单增长公告。'
    if mutation=='negated':m['source_row']['body']='星海科技否认与US.VRT签署数据中心设备供货协议。'
    if mutation=='third_party':m['source_row']['body']='星海科技发布营收公告。另一家公司与US.VRT签署数据中心合作协议。'
    c=cards(m)
    if mutation=='wrong_identity':
        for row in c: row['identity_source']['status']='UNVERIFIED'
    if mutation=='cross_market':
        for row in c:
            for p in row['propositions']:p['effect_scope']='A_SHARE_CAPITAL_ACTION_NOT_H_SHARE_FLOW'
    e=collect(c)
    assert not e.us_individual
    assert e.us_mapping_diagnostics['individual'][0]['reason']!='ACCEPTED'


def test_conflicting_late_clock_cannot_hide_behind_earlier_clock():
    row={'symbol':'HK.01234','relationship_type':'INDUSTRY_INFERENCE','issuer_quote':'fixture',
      'issuer_published_at':'2026-09-25T12:00:00+08:00','issuer_available_at':'2026-09-25T12:02:00+08:00',
      'issuer_retrieved_at':'2026-09-28T09:00:00+08:00','source_refs':[REF]}
    e=collect([],themes=[{'theme':'DATA_CENTER','mappings':[row]}])
    assert not e.us_industry


@pytest.mark.parametrize('clocks',[
    pytest.param({},id='missing-both'),
    pytest.param({'issuer_available_at':'2026-09-25T12:02:00+08:00'},id='issuer-available-only'),
    pytest.param({'issuer_retrieved_at':'2026-09-25T12:03:00+08:00'},id='issuer-retrieved-only'),
    pytest.param({'available_at':'2026-09-25T12:02:00+08:00'},id='available-only'),
    pytest.param({'retrieved_at':'2026-09-25T12:03:00+08:00'},id='retrieved-only'),
    pytest.param({'first_seen_at':'2026-09-25T12:02:00+08:00'},id='first-seen-only'),
    pytest.param({'collected_at':'2026-09-25T12:02:00+08:00'},id='collected-only'),
])
def test_legacy_theme_requires_explicit_availability_and_retrieval_pair(clocks):
    row={'symbol':'HK.01234','relationship_type':'INDUSTRY_INFERENCE','issuer_quote':'Synthetic issuer business exposure',
      'issuer_published_at':'2026-09-25T12:00:00+08:00','source_refs':[REF],**clocks}
    audit=[]
    result=verified_theme_relations([{'theme':'DATA_CENTER','mappings':[row]}],START,END,audit=audit)
    assert not result
    assert audit[0]['reason']=='ISSUER_ACQUISITION_TIME_MISSING_INVALID_OR_OUTSIDE_WINDOW'


@pytest.mark.parametrize('pair',[
    pytest.param({'issuer_available_at':'2026-09-25T12:02:00+08:00',
                  'issuer_retrieved_at':'2026-09-25T12:03:00+08:00'},id='issuer-clock-pair'),
    pytest.param({'available_at':'2026-09-25T12:02:00+08:00',
                  'retrieved_at':'2026-09-25T12:03:00+08:00'},id='normalized-clock-pair'),
])
def test_legacy_theme_accepts_explicit_clock_pair_when_all_present_clocks_are_valid(pair):
    row={'symbol':'HK.01234','relationship_type':'INDUSTRY_INFERENCE','issuer_quote':'Synthetic issuer business exposure',
      'issuer_published_at':'2026-09-25T12:00:00+08:00','source_refs':[REF],**pair}
    audit=[]
    result=verified_theme_relations([{'theme':'DATA_CENTER','mappings':[row]}],START,END,audit=audit)
    assert 'HK.01234' in result
    assert audit[0]['reason']=='ACCEPTED'


@pytest.mark.parametrize('extra_clock',[
    pytest.param({'first_seen_at':'bad'},id='invalid-first-seen'),
    pytest.param({'collected_at':'2026-09-28T09:00:00+08:00'},id='late-collected'),
])
def test_legacy_theme_rejects_any_invalid_or_late_clock_even_with_explicit_pair(extra_clock):
    row={'symbol':'HK.01234','relationship_type':'INDUSTRY_INFERENCE','issuer_quote':'Synthetic issuer business exposure',
      'issuer_published_at':'2026-09-25T12:00:00+08:00','available_at':'2026-09-25T12:02:00+08:00',
      'retrieved_at':'2026-09-25T12:03:00+08:00','source_refs':[REF],**extra_clock}
    audit=[]
    result=verified_theme_relations([{'theme':'DATA_CENTER','mappings':[row]}],START,END,audit=audit)
    assert not result
    assert audit[0]['reason']=='ISSUER_ACQUISITION_TIME_MISSING_INVALID_OR_OUTSIDE_WINDOW'


@pytest.mark.parametrize('clocks',[
    pytest.param({},id='missing-both'),
    pytest.param({'available_at':'2026-09-25T12:02:00+08:00'},id='available-only'),
    pytest.param({'retrieved_at':'2026-09-25T12:03:00+08:00'},id='retrieved-only'),
    pytest.param({'first_seen_at':'2026-09-25T12:02:00+08:00'},id='first-seen-only'),
    pytest.param({'collected_at':'2026-09-25T12:02:00+08:00'},id='collected-only'),
])
def test_structured_us_issuer_relation_requires_explicit_availability_and_retrieval_pair(clocks):
    row={'symbol':'HK.01234','semantic_status':'ACCEPTED','related_us_symbols':['VRT'],
      'published_at':'2026-09-25T12:00:00+08:00','source_refs':[REF],**clocks}
    assert not structured_us_issuer_relations([row],START,END)


def test_structured_us_issuer_relation_accepts_valid_normalized_pair_only_when_all_clocks_are_valid():
    row={'symbol':'HK.01234','semantic_status':'ACCEPTED','related_us_symbols':['VRT'],
      'published_at':'2026-09-25T12:00:00+08:00','source_refs':[REF],
      'available_at':'2026-09-25T12:02:00+08:00','retrieved_at':'2026-09-25T12:03:00+08:00'}
    assert 'HK.01234' in structured_us_issuer_relations([row],START,END)
    row['first_seen_at']='2026-09-28T09:00:00+08:00'
    assert not structured_us_issuer_relations([row],START,END)


def test_invalid_or_duplicate_source_not_independent():
    c=cards(material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT']))
    u=us();u['source_identity']['payload_sha256']='c'*64
    assert not collect(c,u).us_individual
    u=us();u['source_identity']['status']='UNVERIFIED'
    assert not collect(c,u).us_individual


def test_top_level_future_us_capture_rejected_even_if_eligible_flag_set():
    c=cards(material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT']))
    u=us();u['captured_at']='2026-09-28T08:00:01+08:00'
    assert not collect(c,u).us_individual


def test_bridge_does_not_publish_an_uncomputed_zero():
    class MissingReader:
        def read_exact_session(self,date):return None,None
    out=project_us_market(MissingReader(),'20260928',CTX)
    assert out['mapping_diagnostics']['accepted_hk_mapping_count'] is None
    assert out['mapping_diagnostics']['status']=='NOT_COMPUTED_BY_BRIDGE'


def test_material_rejection_reasons_are_signal_level_not_only_generic_zero():
    m=material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT'])
    c=cards(m)
    c[0]['available_at']='2026-09-28T09:00:00+08:00'
    e=collect(c)
    d=e.us_mapping_diagnostics
    assert d['source_material_card_count']>0
    assert d['individual'][0]['rejected_candidates']
    assert any('TIME' in r['reason'] or 'CUTOFF' in r['reason'] for r in d['individual'][0]['rejected_candidates'])


@pytest.mark.parametrize('label,text', [('光伏','风电设备'),('CPO','数据中心设备'),('半导体','人工智能服务器')])
def test_native_industry_relation_is_not_broadened_by_umbrella_taxonomy(label,text):
    c=cards(material(f'星海科技发布{text}业务订单增长公告。'))
    assert not collect(c,us(label)).us_industry


def test_no_us_metadata_can_extract_explicit_exchange_symbol_but_not_plain_topic():
    c=cards(material('星海科技与US.VRT签署数据中心设备供货协议。'))
    assert 'HK.01234' in collect(c).us_individual


def test_pit_two_source_pass_preserves_unverified_connect_membership_as_research_only():
    c=cards(material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT']))
    membership={'status':'CANNOT_CONFIRM','target_trade_date':'20260928','research_only':True}
    for row in c:row['target_connect_membership']=membership
    result=collect(c)
    diagnostic=result.us_mapping_diagnostics
    assert diagnostic['assessment_state']=='ASSESSED_WITH_RELATIONS'
    assert diagnostic['accepted_hk_mapping_count']>=1
    relation=result.us_individual['HK.01234'][0]['hk_relation']
    assert relation['target_connect_membership']==membership
    assert relation['source_refs'] and relation['available_at']
    assert diagnostic['relation_gate']=='TWO_SOURCE_PIT_VERIFIED_REQUIRED'


def test_pit_rejection_and_cross_date_us_capture_never_publish_a_zero():
    late=cards(material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT']))
    late[0]['available_at']='2026-09-28T08:00:01+08:00'
    rejected=collect(late).us_mapping_diagnostics
    assert rejected['assessment_state']=='INSUFFICIENT'
    assert rejected['accepted_hk_mapping_count'] is None
    assert rejected['individual'][0]['rejected_candidates']

    valid=cards(material('星海科技与US.VRT签署数据中心设备供货协议。',related_us_symbols=['VRT']))
    market=us();market['captured_at']='2026-09-28T08:00:01+08:00'
    cross_date=collect(valid,market).us_mapping_diagnostics
    assert cross_date['assessment_state']=='NOT_EVALUATED'
    assert cross_date['accepted_hk_mapping_count'] is None
    assert cross_date['mapping_eligible'] is False
    assert cross_date['assessment_reasons']==['US_MAPPING_INPUT_NOT_ELIGIBLE']


def test_us_only_card_keeps_native_name_negative_direction_and_action_boundary():
    c=cards(material('星海科技披露对US.VRT的数据中心供货订单下降。',related_us_symbols=['VRT']))
    result=build_research_attention('20260928',context=CTX,market_screen=None,stocks=[],material_cards=c,
         themes=[],announcement_observation=None,us_market=us())
    card=result['cards'][0]
    assert card['name']=='星海科技'
    relations=card['research_relationships']
    assert any(r['direction']=='NEGATIVE_OR_RISK' for r in relations)
    assert all(r['source_refs'] and r['acquired_at'] and r['invalidation'] for r in relations)
    assert card['production_allowed'] is False and card['orders_sent'] is False
    assert card['decision']['state']=='COMPANY_EVIDENCE_WAIT_MARKET'


def test_action_clause_cannot_be_replaced_without_matching_source_quote():
    c=cards(material('星海科技发布数据中心设备业务订单增长公告。'))
    for p in c[0]['propositions']:
        p['action_quote']='与US.VRT签署数据中心设备供货协议'
    assert not collect(c).us_individual


@pytest.mark.parametrize('field',['payload_sha256','receipt_sha256','manifest_sha256'])
def test_native_us_join_requires_well_formed_complete_us_lineage(field):
    c=cards(material('星海科技与US.VRT签署数据中心设备供货协议。'))
    u=us();u['source_identity'][field]='z'*64
    assert not collect(c,u).us_individual


def test_real_style_legacy_theme_rejection_keeps_the_reason_and_source():
    row={'symbol':'HK.01234','relationship_type':'INDUSTRY_INFERENCE','issuer_quote':'星海科技发布工业机器人产品。',
      'issuer_published_at':'2026-09-24T11:06:00+08:00','issuer_available_at':'2026-09-26T12:02:00+08:00',
      'source_refs':[REF]}
    e=collect([],us('机器人'),themes=[{'theme':'ROBOTICS','mappings':[row]}])
    rejected=e.us_mapping_diagnostics['industry'][0]['rejected_candidates']
    assert len(rejected)==1
    assert rejected[0]['reason']=='ISSUER_PUBLICATION_OUTSIDE_WINDOW'
    assert rejected[0]['source_refs']==[REF]


def test_malformed_original_row_is_isolated_not_global_mapping_crash():
    c=cards(material('星海科技发布光伏组件业务订单增长公告。'))
    c[0]['original_source_row']=['malformed']
    c[0]['propositions']=[]
    c[0]['related_us_symbols']=['VRT']
    assert not collect(c).us_individual
