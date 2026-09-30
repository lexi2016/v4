"""Offline contract tests. All invented issuers/notices are SYNTHETIC, not live evidence."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from v4.manager_research.workspace_projection import FLAGS, digest, timestamp
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.workspace_semantics import assess, sanitize_cards
from v4.manager_research.workspace_plan import temporal_role
from v4.manager_research.workspace_briefing import _recent
from v4.manager_research.research_evidence import company_evidence, collect_attention_evidence
from v4.manager_research.issuer_us_relations import material_us_relations

S='HK.01234'; NAME='示例科技'; US='XTEST'; SHA='a'*64
C={'plan_trade_date':'20260930','market_session':'20260929',
   'research_cutoff':'2026-09-30T09:00:00+08:00','focus_window_start':'2026-09-28T16:10:00+08:00',
   'source_dates':['20260928','20260929','20260930'],**FLAGS}
MASTER={S:{'name':NAME,'captured_at':'2026-09-29T08:00:00+08:00'}}
IDENTITY={'status':'OWNER_VERIFIED','source_date':'20260929','artifact_sha256':SHA,
          'manifest_sha256':'b'*64,'owner':'ORIGINAL_NATIVE_MASTER_TEST_BOUNDARY'}

def h(text):return hashlib.sha256(text.encode()).hexdigest()

def required_module(name):
    spec=importlib.util.find_spec('v4.manager_research.'+name)
    assert spec is not None, name+' consumer is missing'
    return importlib.import_module('v4.manager_research.'+name)

def mirror_doc(body=None):
    body=body or NAME+'公告，'+NAME+'已交付新增机器人订单，订单金额增长20%。'
    when='2026-09-29T12:00:00+08:00'
    refs=[dict(source_key='eastmoney-hk-announcement-request:'+str(i)*64,
               blob_sha256=str(i)*64,body_sha256=str(i+1)*64,retrieved_at=when,
               request={'source':'EASTMONEY_HK','method':'GET','url':'https://example.invalid/synthetic/'+str(i)},
               http_status=200) for i in (1,2,3)]
    return dict(schema_version='v4.manager_research.eastmoney_hk_document.v2',symbol=S,name=NAME,
        source='EASTMONEY_HK',source_identity='EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL',
        market_code='116',stock_code=S[3:],ann_type='H',art_code='AN202609290000000001',
        event_id=digest(['SYNTHETIC',body]),title=NAME+'业务公告',body_text=body,body_sha256=h(body),
        body_status='FULL_CONTENT_API_TEXT_VERIFIED',body_source='EASTMONEY_CONTENT_API_PAGES',
        body_pages=[dict(page_index=1,text=body,text_sha256=h(body),source_ref=refs[1])],
        content_page_count=1,document_sha256='d'*64,source_refs=refs,
        source_url='https://example.invalid/synthetic.pdf',available_at=when,retrieved_at=when,
        display_time_iso='2026-09-29T10:00:00+08:00',target_trade_date='20260930',capture_trade_date='20260929',
        publication_status='CANNOT_CONFIRM_FIRST_PUBLICATION',hkex_first_publication_verified=False,
        fresh_catalyst_eligible=False,focus_eligible=False,buy_allowed=False,**FLAGS)

def capture():
    return dict(source='EASTMONEY_HK',readback_status='VERIFIED',target_trade_date='20260929',
                run_id='1'*32,sha256='e'*64,generated_at='2026-09-29T12:00:01+08:00')

def material(body=None,**changes):
    body=body or NAME+'生产石油设备，'+NAME+'向US.'+US+'供应设备并签署合作合同。'
    row=dict(material_id=h(body),verification='OWNER_VERIFIED',source_refs=[dict(status='VERIFIED',payload_sha256=SHA)],
             source_row={'body_text':body},title=NAME+'公司业务',claim_type='SOURCE_STATEMENT',
             published_at='2026-09-29T10:00:00+08:00',available_at='2026-09-29T12:00:00+08:00',
             retrieved_at='2026-09-29T12:00:00+08:00',source_url='https://example.invalid/source',**FLAGS)
    row.update(changes);return row

def cards(m):
    return project_material_discovery([m],MASTER,IDENTITY,C)

def mirror_card(body=None):
    mod=required_module('announcement_materials');m=mod.mirror_material(mirror_doc(body),capture())
    result=cards(m);assert len(result)==1
    return result[0]

def connect_scope(codes=(S,)):
    return dict(status='OWNER_VERIFIED',target_trade_date='20260930',codes=list(codes),
       source={'source_date':'20260930','market':'HK_CONNECT','role':'HK_CONNECT_FULL_MARKET_AUTHORITY',
               'sha256':'f'*64,'observed_at':'2026-09-30T07:30:00+08:00'},
       identity=digest(['20260930',list(codes),'f'*64]),gaps=[])

def standing(card):
    claim=card['propositions'][-1]
    card['original_source_row']['business_relation_validity']={
      'schema_version':'v4.manager_research.business_relation_validity.v1',
      'status':'ACTIVE','issuer_symbol':S,'source_payload_sha256':SHA,
      'body_sha256':h(card['original_source_row']['body_text']),
      'source_field':claim['source_field'],'start':claim['start'],'end':claim['end'],
      'quote_sha256':h(claim['quote']),
      'valid_from':'2026-08-01T00:00:00+08:00','valid_until':'2026-12-01T00:00:00+08:00',
      'confirmed_at':'2026-08-01T12:00:00+08:00',
      'validity_basis':'ORIGINAL_SOURCE_OWNER_EXPLICIT_REVIEW_PERIOD_NOT_NEW_CAPTURE'}
    return card

def us_market():
    return dict(status='READY',mapping_eligible=True,captured_at='2026-09-30T05:00:00+08:00',
      raw_industry_up=[{'label':'石油','status':'READY','change_pct':3}],
      raw_individual_up=[{'symbol':US,'status':'READY','change_pct':4}],
      source_identity={'status':'VERIFIED','payload_sha256':'7'*64,'receipt_sha256':'8'*64,'manifest_sha256':'9'*64})


def test_mirror_time_is_separate_and_existing_company_consumer_accepts():
    card=mirror_card()
    assert card['published_at'] is None
    assert card['temporal_role']=='CURRENT_WINDOW_MIRROR_OBSERVATION'
    assert card['hkex_first_publication_verified'] is False
    assert _recent(card,C)
    result=company_evidence([], [card], timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert list(result)==[S]
    evidence=result[S][0]
    assert evidence['evidence_class']=='VERIFIED_MIRROR_COMPANY_MATERIAL_NOT_HKEX_FIRST_PUBLICATION'
    assert evidence['published_at'] is None and evidence['available_at']==card['available_at']

@pytest.mark.parametrize('body',[
    '本公司已交付新增机器人订单，订单金额增长20%。',
    '本公司已簽署機器人產品合作協議，取得新增訂單。',
])
def test_bound_first_person_uses_original_body_offsets(body):
    card=mirror_card(body)
    assert card['propositions']
    accepted,_=sanitize_cards([card]);assert len(accepted)==1
    for p in accepted[0]['propositions']:
        assert body[p['start']:p['end']]==p['quote']
        assert p['action_subject']==S and p['subject_role']!='ISSUER_EVENT'
    plain=material(body)
    assert assess(plain,NAME,S)['propositions']==[]

@pytest.mark.parametrize('mutation,reason',[
    (lambda d:d.update(body_sha256='0'*64),'BODY_SHA'),
    (lambda d:d.update(body_text=''),'BODY'),
    (lambda d:d.update(stock_code='99999'),'IDENTITY'),
    (lambda d:d.update(available_at=None),'CLOCK'),
    (lambda d:d.update(retrieved_at='not-a-clock'),'CLOCK'),
    (lambda d:d.update(published_at=d['display_time_iso']),'PUBLICATION'),
    (lambda d:d.update(hkex_first_publication_verified=True),'PUBLICATION'),
    (lambda d:d.update(available_at='2026-09-29T11:00:00+08:00',retrieved_at='2026-09-29T11:00:00+08:00'),'CLOCK'),
])
def test_mirror_adapter_rejects_invalid_source_fields(mutation,reason):
    mod=required_module('announcement_materials');d=mirror_doc();mutation(d)
    with pytest.raises(ValueError,match=reason):mod.mirror_material(d,capture())

def test_empty_or_unverified_capture_is_not_owner_attestation():
    mod=required_module('announcement_materials');cap=capture();cap['readback_status']='UNVERIFIED'
    with pytest.raises(ValueError):mod.mirror_material(mirror_doc(),cap)

@pytest.mark.parametrize('body',[
    NAME+'已回购100万股股份。',
    '本公司已購回100萬股股份。',
    NAME+'预计推出机器人产品。',
    NAME+'否认已签署机器人合作合同。',
])
def test_routine_or_unconfirmed_mirror_not_substantive_focus(body):
    mod=required_module('announcement_materials');m=mod.mirror_material(mirror_doc(body),capture())
    audit=[];result=project_material_discovery([m],MASTER,IDENTITY,C,rejection_audit=audit)
    assert result==[]
    assert audit


def test_old_mirror_not_new_just_because_acquired_today():
    mod=required_module('announcement_materials');d=mirror_doc();d['display_time_iso']='2026-09-25T10:00:00+08:00'
    m=mod.mirror_material(d,capture())
    assert temporal_role(m,C)=='BACKGROUND'
    assert not _recent(m,C)


def test_current_cutoff_blocks_late_source_refs_even_with_old_top_level_clocks():
    mod=required_module('announcement_materials');m=mod.mirror_material(mirror_doc(),capture())
    m['source_refs'][0]['retrieved_at']='2026-10-01T00:00:00+08:00'
    assert not mod.current_company_claim(m,timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))


def test_generic_research_missing_actual_acquisition_cannot_focus():
    c=cards(material(available_at=None,retrieved_at=None,collected_at='2026-09-29T12:00:00+08:00'))[0]
    assert not _recent(c,C)
    assert company_evidence([], [c],timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))=={}


def test_cross_capture_date_projection_is_bounded_not_relabelled():
    from v4.manager_research.workspace_announcements import _project_eastmoney_hk
    data=json.loads(Path(__file__).with_name('actual_eastmoney_product_20260929.json').read_text())
    docs,gaps=_project_eastmoney_hk(data,C)
    assert len(docs)==1
    assert docs[0]['capture_trade_date']=='20260929'
    assert docs[0]['target_trade_date']=='20260930'
    assert docs[0]['body_sha256']==data['documents'][0]['body_sha256']
    assert 'published_at' not in docs[0]
    with pytest.raises(ValueError):_project_eastmoney_hk(data,{**C,'source_dates':['20260930']})


def test_connect_gate_uses_target_authority_not_native_name():
    mod=required_module('connect_selection');c=cards(material())[0]
    out,rejected=mod.filter_cards([c],connect_scope());assert len(out)==1 and not rejected
    assert out[0]['connect_eligibility']=='VERIFIED_TARGET_UNIVERSE'
    for scope in [connect_scope(()),{**connect_scope(),'status':'CANNOT_CONFIRM'},{**connect_scope(),'target_trade_date':'20260929'}]:
        out,rejected=mod.filter_cards([c],scope,target_date='20260930')
        assert not out and rejected
    assert c['connect_eligibility']=='TARGET_DATE_NOT_CHECKED'


def test_synthetic_issuer_business_not_industry_keyword_only():
    c=cards(material(NAME+'发布石油行业研究报告。'))
    ind,direct,audit=material_us_relations(c,timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert not ind and not direct


def test_chinese_counterparty_name_does_not_create_us_identity():
    c=cards(material(NAME+'与外国药企达成研发和授权许可战略合作协议。'))
    ind,direct,audit=material_us_relations(c,timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert direct=={}


def test_current_two_source_us_mapping_preserves_raw_movers():
    c=cards(material())
    ev=collect_attention_evidence(market_screen={},stocks=[],material_cards=c,themes=[],
       announcement_observation={},us_market=us_market(),start=timestamp(C['focus_window_start']),cutoff=timestamp(C['research_cutoff']))
    assert S in ev.us_individual
    assert ev.us_individual[S][0]['hk_relation']['relation_temporal_role']=='CURRENT_WINDOW_RELATION_EVIDENCE'
    assert ev.us_mapping_diagnostics['raw_movers_retained_when_unmapped'] is True


def test_standing_relation_has_independent_validity_and_is_not_new_catalyst():
    c=cards(material(published_at='2026-08-01T10:00:00+08:00',available_at='2026-08-01T13:00:00+08:00',retrieved_at='2026-08-01T13:00:00+08:00'))[0]
    c=standing(c);before=deepcopy(c)
    ind,direct,audit=material_us_relations([c],timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert S in direct
    rel=direct[S][0]
    assert rel['relation_temporal_role']=='STANDING_RELATION_NOT_NEW_CATALYST'
    assert rel['issuer_published_at']==c['published_at']
    assert c==before
    assert not _recent(c,C)
    ev=collect_attention_evidence(market_screen={},stocks=[],material_cards=[c],themes=[],announcement_observation={},
       us_market=us_market(),start=timestamp(C['focus_window_start']),cutoff=timestamp(C['research_cutoff']))
    assert S in ev.us_individual and S not in ev.company

@pytest.mark.parametrize('change',[
  {'valid_until':'2026-09-01T00:00:00+08:00'},
  {'issuer_symbol':'HK.09876'},
  {'quote_sha256':'0'*64},
  {'source_payload_sha256':'0'*64},
  {'confirmed_at':'2026-10-01T00:00:00+08:00'},
  {'status':'REVOKED'},
])
def test_standing_contract_corruption_is_rejected(change):
    c=standing(cards(material(published_at='2026-08-01T10:00:00+08:00',available_at='2026-08-01T13:00:00+08:00',retrieved_at='2026-08-01T13:00:00+08:00'))[0])
    c['original_source_row']['business_relation_validity'].update(change)
    ind,direct,audit=material_us_relations([c],timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert not direct and all(x['reason']!='ACCEPTED' for x in audit)


def test_standing_contract_cannot_repair_missing_acquisition_time():
    c=standing(cards(material(published_at='2026-08-01T10:00:00+08:00',available_at=None,retrieved_at=None))[0])
    _,direct,audit=material_us_relations([c],timestamp(C['focus_window_start']),timestamp(C['research_cutoff']))
    assert not direct
    assert any('ACQUISITION' in ' '.join(x.get('rejection_reasons',[x['reason']])) for x in audit)


def test_same_source_does_not_count_as_independent_us_source():
    us=us_market();us['source_identity']['payload_sha256']=SHA
    ev=collect_attention_evidence(market_screen={},stocks=[],material_cards=cards(material()),themes=[],
      announcement_observation={},us_market=us,start=timestamp(C['focus_window_start']),cutoff=timestamp(C['research_cutoff']))
    assert not ev.us_industry and not ev.us_individual


def test_unanchored_legacy_ticker_metadata_cannot_bypass_relation_parser():
    legacy=dict(symbol=S,semantic_status='ACCEPTED',market='HK',related_us_symbols=[US],
       published_at='2026-09-29T10:00:00+08:00',available_at='2026-09-29T12:00:00+08:00',
       retrieved_at='2026-09-29T12:00:00+08:00',source_refs=[{'status':'VERIFIED','payload_sha256':SHA}],
       relationship_type='EXPLICIT_MENTION',identity_mapping_basis='LEGACY',relation_quote='石油行业上涨')
    ev=collect_attention_evidence(market_screen={},stocks=[],material_cards=[legacy],themes=[],
      announcement_observation={},us_market=us_market(),start=timestamp(C['focus_window_start']),cutoff=timestamp(C['research_cutoff']))
    assert not ev.us_individual


def test_mirror_does_not_become_sector_wide_new_publication():
    from v4.manager_research.workspace_briefing import _theme_fragments
    mod=required_module('announcement_materials')
    m=mod.mirror_material(mirror_doc(),capture())
    assert _theme_fragments(m,C)==[]


def test_quoted_partner_first_person_is_not_document_issuer():
    mod=required_module('announcement_materials')
    body='合作方表示，本公司已签署机器人合作合同。'
    m=mod.mirror_material(mirror_doc(body),capture())
    assert cards(m)==[]


def test_malformed_target_codes_fail_closed_not_exception():
    mod=required_module('connect_selection');scope=connect_scope();scope['codes']=[S,None]
    allowed,rejected=mod.filter_cards(cards(material()),scope)
    assert not allowed and rejected


def test_never_run_source_is_not_verified_empty(tmp_path):
    from v4.manager_research.workspace_announcements import read_selection_inputs
    service=SimpleNamespace(store=SimpleNamespace(root=tmp_path,_read=lambda p:None))
    got=read_selection_inputs(service,C)
    assert got['status']=='CANNOT_CONFIRM'
    assert got['gaps'] and not got['captures'] and not got['materials']


def test_membership_reader_keeps_real_witness_clock(monkeypatch,tmp_path):
    mod=required_module('connect_selection')
    import domains.manager_research_evidence as owner
    calls=[]
    source=connect_scope()['source'];source['available_at']='2026-09-30T10:00:00+08:00'
    def read(root,date,**kwargs):
        calls.append((root,date,kwargs));return SimpleNamespace(codes=(S,),source=deepcopy(source))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path))
    monkeypatch.setattr(owner,'read_universe_evidence',read)
    got=mod.read_scope(C)
    assert got['status']=='OWNER_VERIFIED' and calls[0][2]=={}
    assert got['source']['available_at']=='2026-09-30T10:00:00+08:00'
    c=cards(material())[0];first=mod.filter_cards([c],got)[0]
    source['available_at']='2026-09-30T10:01:00+08:00'
    second=mod.filter_cards([c],mod.read_scope(C))[0]
    assert first==second  # present witness isn't a fabricated source time or volatile plan key
    source['observed_at']='2026-09-30T09:01:00+08:00'
    assert mod.read_scope(C)['status']=='CANNOT_CONFIRM'


def test_mirror_capture_after_cutoff_and_bad_page_not_admitted():
    mod=required_module('announcement_materials')
    d=mirror_doc();d['body_pages'][0]['text']='篡改的正文'
    with pytest.raises(ValueError):mod.mirror_material(d,capture())
    d=mirror_doc();m=mod.mirror_material(d,capture())
    early={**C,'research_cutoff':'2026-09-29T11:59:59+08:00'}
    assert temporal_role(m,early)=='AFTER_CUTOFF_EXCLUDED'


def test_unrelated_named_issuer_in_mirror_does_not_get_candidate():
    mod=required_module('announcement_materials');m=mod.mirror_material(mirror_doc('另一企业已完成机器人产品交付，收入增长20%。'),capture())
    expanded={**MASTER,'HK.09876':{'name':'另一企业'}}
    assert project_material_discovery([m],expanded,IDENTITY,C)==[]


def test_current_owner_rejections_and_coverage_limits_are_not_lost(tmp_path):
    from v4.manager_research.workspace_announcements import read_selection_inputs
    svc=SimpleNamespace(store=SimpleNamespace(root=tmp_path,_read=lambda p:None))
    rejection={'art_code':'AN202609290000000001','reason':'EASTMONEY_HK_DISPLAY_TIME_OUTSIDE_CONSUMER_WINDOW'}
    review={'eastmoney_hk_capture':capture(),'eastmoney_hk_documents':[],
      'eastmoney_hk_gaps':['EASTMONEY_LIST_PAGE_NOT_EXHAUSTIVE'],
      'eastmoney_hk_selection_rejections':[rejection]}
    out=read_selection_inputs(svc,C,current_review=review)
    assert rejection in out['rejections']
    assert 'EASTMONEY_LIST_PAGE_NOT_EXHAUSTIVE' in out['gaps']
