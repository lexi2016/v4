"""Synthetic upstream inputs -> unmocked indexed Python producer functions.
No provider calls, eligibility publication, live API or price data are used.
"""
from copy import deepcopy
from hashlib import sha256
from datetime import datetime
import json
from v4.manager_research import workspace_announcements as announcements
from v4.manager_research.announcement_observation import event_lane
from v4.manager_research.announcement_materials import mirror_material
from v4.manager_research.workspace_discovery import project_material_discovery
from v4.manager_research.research_attention import build_research_attention
from v4.manager_research.workspace_projection import FLAGS, digest, build_workspace, timestamp
from v4.manager_research.workspace_semantics import prose_sources

DAY = '20260930'
CONTEXT = dict(plan_trade_date=DAY, market_session='20260929',
    research_cutoff='2026-09-30T09:28:00+08:00', focus_window_start='2026-09-28T16:10:00+08:00',
    source_dates=['20260928','20260929','20260930'])
NAMES = {'HK.01234':{'name':'星海科技'}, 'HK.05678':{'name':'海辰科技'}}
IDENTITY = dict(status='OWNER_VERIFIED',source_date='20260929',artifact_sha256='a'*64,
    manifest_sha256='b'*64,owner='SYNTHETIC_NATIVE_MASTER_BOUNDARY')
SOURCE_REF = dict(status='VERIFIED',payload_sha256='c'*64,payload_path='synthetic/original-article.json',
    receipt_sha256='d'*64,manifest_sha256='e'*64)
ART='AN202609290000000001'


def ordinary(text='星海科技与US.VRT签署数据中心设备供货协议。', **changes):
    m=dict(material_id='synthetic-article', original_article_id='synthetic-article',
        title='星海科技业务记录', verification='OWNER_VERIFIED',
        source_row={'article_id':'synthetic-article','body':text,'related_us_symbols':['VRT']},
        source_refs=[deepcopy(SOURCE_REF)],claim_type='SOURCE_STATEMENT',
        published_at='2026-09-29T12:00:00+08:00',
        retrieved_at='2026-09-29T12:01:00+08:00', available_at='2026-09-29T12:02:00+08:00',
        source_url='https://issuer.invalid/synthetic',**FLAGS)
    m.update(changes)
    return m


def old_material():
    m=ordinary(published_at='2026-09-01T12:00:00+08:00',retrieved_at='2026-09-01T12:01:00+08:00',
        available_at='2026-09-01T12:02:00+08:00')
    cards=project_material_discovery([m],NAMES,IDENTITY,CONTEXT)
    assert cards
    claim=cards[0]['issuer_business_relations'][0]
    body=dict(prose_sources(cards[0]))[claim['source_field']]
    m['source_row']['business_relation_validity']=dict(
        schema_version='v4.manager_research.business_relation_validity.v1',status='ACTIVE',
        issuer_symbol='HK.01234',validity_basis='ORIGINAL_SOURCE_OWNER_EXPLICIT_REVIEW_PERIOD_NOT_NEW_CAPTURE',
        body_sha256=sha256(body.encode()).hexdigest(),quote_sha256=sha256(claim['issuer_quote'].encode()).hexdigest(),
        source_field=claim['source_field'],start=claim['start'],end=claim['end'],source_payload_sha256=SOURCE_REF['payload_sha256'],
        valid_from='2026-09-01T00:00:00+08:00',confirmed_at='2026-09-01T12:01:00+08:00',
        valid_until='2026-10-01T00:00:00+08:00')
    return m


def us_market():
    return dict(schema_version='v4.manager_research.us_market_bridge.v1',target_trade_date=DAY,
        research_cutoff=CONTEXT['research_cutoff'],status='PARTIAL', mapping_eligible=True,
        captured_at='2026-09-30T05:10:00+08:00',expected_us_session='20260929',
        coverage_scope='FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET',
        coverage={},gaps=['SYNTHETIC_UPSTREAM_NOT_LIVE'],
        source_identity=dict(status='VERIFIED',payload_sha256='f'*64,receipt_sha256='1'*64,manifest_sha256='2'*64),
        raw_industry_up=[dict(label='数据中心',status='READY',pct_change=1.2,proxy_symbols=['VRT'],
            instrument_classification='INDUSTRY_PROXY_NOT_FULL_MARKET_SECURITY_SCREEN')],
        raw_individual_up=[dict(symbol='VRT',change_pct=2,session_date='20260929',
            instrument_classification='CONFIGURED_US_SYMBOL_NOT_FULL_MARKET_SCREEN')],**FLAGS)


def ref(url, body, at='2026-09-29T18:02:00+08:00'):
    request=dict(source='EASTMONEY_HK',method='GET',url=url)
    # Upstream HTTP envelopes are synthetic; no claim of original capture/store verification.
    b=body.encode() if isinstance(body,str) else body
    return dict(request=request,source_key='eastmoney-hk-request:'+digest(request),
        body_sha256=sha256(b).hexdigest(),blob_sha256=sha256(b'fixture envelope:'+b).hexdigest(),
        retrieved_at=at,http_status=200,final_url=url,from_cache=False)


def raw_doc(symbol='HK.01234', text='本公司新增与US.VRT合作的数据中心设备订单。', art=ART):
    code=symbol[3:]
    listed=ref('https://np-anotice-stock.eastmoney.com/api/security/ann?ann_type=H&page_index=1&stock_list='+code,json.dumps({'code':code,'art':art}))
    content=ref(f'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art}&page_index=1',text)
    pdf=ref(f'https://pdf.dfcfw.com/pdf/H2_{art}_1.pdf', b'%PDF-synthetic-upstream-boundary')
    return dict(code=symbol,name=NAMES[symbol]['name'],source='EASTMONEY_HK',
        row=dict(art_code=art, market_code='116', stock_code=code, ann_type='H',title=NAMES[symbol]['name']+'业务公告',
            notice_date='2026-09-29 00:00:00', display_time='2026-09-29 18:00:00:000',
            display_time_iso='2026-09-29T18:00:00+08:00',listing_ref=listed),
        content_refs=[content],pdf_ref=pdf, available_at=content['retrieved_at'],
        content_notice_date='2026-09-29 00:00:00',content_display_time='2026-09-29 18:00:00',
        document_sha256=pdf['body_sha256'],pdf_bytes=100,pdf_page_count=1,
        body_status='FULL_CONTENT_API_TEXT_VERIFIED',body_source='EASTMONEY_CONTENT_API_PAGES',
        body_text=text,body_sha256=sha256(text.encode()).hexdigest(),
        body_pages=[dict(page_index=1,text=text,text_sha256=sha256(text.encode()).hexdigest(),source_ref=content)],
        content_page_count=1,pdf_text_extraction_status='UNVERIFIED_ENCODING')


def project_docs(docs):
    product=dict(target_trade_date=DAY,documents=docs,context=CONTEXT,
        generated_at='2026-09-30T09:20:00+08:00')
    projected,gaps=announcements._project_eastmoney_hk(product,CONTEXT)
    return projected,gaps


def mirror(doc=None):
    projected,_=project_docs([doc or raw_doc()])
    capture=dict(source='EASTMONEY_HK',readback_status='VERIFIED',sha256='3'*64,run_id='4'*32,target_trade_date=DAY)
    return mirror_material(projected[0],capture)


def observation(docs):
    projected,gaps=project_docs(docs)
    return event_lane(dict(status='NOT_RUN',eastmoney_hk_status='PARTIAL',eastmoney_hk_documents=projected,
        eastmoney_hk_gaps=gaps,coverage={},gaps=[],capture_runs=[]),{},CONTEXT)


def make_case(name):
    docs=[];mats=[];u=us_market();expected=0
    if name in {'multi_instance','repeat_instance','two_issuers'}:
        one=raw_doc()
        two=raw_doc(text='本公司已签署与US.VRT的数据中心设备供货协议，订单金额增加20%。')
        three=raw_doc('HK.05678')
        docs=([one,two,three] if name=='multi_instance' else [one,deepcopy(one)] if name=='repeat_instance' else [one,three])
    elif name=='native_current':mats=[ordinary()];expected=2
    elif name=='mixed_issuers':
        second=ordinary('海辰科技与US.VRT签署数据中心设备供货协议。',material_id='synthetic-second',original_article_id='synthetic-second')
        mats=[old_material(),second];expected=4
    elif name=='native_industry':mats=[ordinary('星海科技发布数据中心设备业务订单增长公告。')];expected=1
    elif name=='native_individual':mats=[ordinary('星海科技与US.VRT签署产品供货协议。')];expected=1
    elif name=='standing':mats=[old_material()];expected=2
    elif name=='mirror':docs=[raw_doc()];mats=[mirror(docs[0])];expected=2
    elif name=='mirror_company_only':docs=[raw_doc(text='本公司已获得工业机器人设备新增订单。')];mats=[mirror(docs[0])];expected=0
    elif name=='risk_explanation':mats=[ordinary('星海科技与US.VRT签署数据中心设备供货协议。星海科技订单减少20%。')];expected=2
    elif name=='missing_hk_source':m=ordinary();m['source_refs']=[];mats=[m]
    elif name=='missing_clock':m=ordinary();m['available_at']=None;mats=[m]
    elif name=='late_acquisition':m=ordinary();m['available_at']='2026-09-30T09:28:01+08:00';mats=[m]
    elif name=='us_after_cutoff':mats=[ordinary()];u['captured_at']='2026-09-30T09:28:01+08:00'
    elif name=='missing_us_source':mats=[ordinary()];u['source_identity']={}
    elif name=='same_source':mats=[ordinary()];u['source_identity']['payload_sha256']=SOURCE_REF['payload_sha256']
    elif name=='expired_standing':m=old_material();m['source_row']['business_relation_validity']['valid_until']=CONTEXT['research_cutoff'];mats=[m]
    elif name=='bad_standing_span':m=old_material();m['source_row']['business_relation_validity']['quote_sha256']='0'*64;mats=[m]
    elif name=='unconfirmed_standing':m=old_material();m['claim_type']='RESEARCH_OPINION';mats=[m]
    elif name=='company_name_only':mats=[ordinary('星海科技与礼来签署产品供货协议。')];u['raw_industry_up']=[];u['raw_individual_up'][0]['symbol']='LLY'
    else:raise ValueError(name)
    cards=project_material_discovery(mats,NAMES,IDENTITY,CONTEXT)
    # Supplied, isolated target membership evidence boundary; use the actual filter.
    from v4.manager_research.connect_selection import filter_cards
    codes=sorted(NAMES)
    scope=dict(status='OWNER_VERIFIED',codes=codes,target_trade_date=DAY,
        membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
        source=dict(source_date=DAY,market='HK_CONNECT',role='HK_CONNECT_FULL_MARKET_AUTHORITY',sha256='5'*64),
        identity=digest([DAY,codes,'5'*64]))
    cards,rejected=filter_cards(cards,scope,target_date=DAY)
    lane=observation(docs)
    attention=build_research_attention(DAY,context=CONTEXT,market_screen=None,stocks=[],material_cards=cards,
        themes=[],announcement_observation=lane,us_market=u)
    # The envelope is produced by the original workspace builder, not a manually
    # maintained TS-shaped fixture. Source acquisition/whole-service IO is out of scope.
    value=build_workspace(DAY,catalyst={'target_trade_date':DAY,'status':'NOT_RUN'},plan_context=CONTEXT)
    value.update(announcement_observation=lane,us_market_attention=u,research_attention=attention)
    # Only whole-owner IO/assembly is substituted: individual producer functions
    # above and the existing GET envelope/read_context wrapper execute unchanged.
    # This does not claim an end-to-end service/8873 runtime invocation.
    from unittest.mock import patch
    from v4.manager_research import workspace as owner
    with patch.object(owner, '_compute_workspace', return_value=value):
        value=owner.get_workspace(None,DAY,include_saved=False,view='dynamic',now=timestamp(CONTEXT['research_cutoff']))
    actual=attention['us_mapping_diagnostics']['accepted_hk_mapping_count']
    return dict(name=name,expected_mapping_count=expected,actual_mapping_count=actual,
        material_cards=cards,workspace=value)

CASES=['multi_instance','repeat_instance','two_issuers','native_current','native_industry','native_individual',
    'standing','mixed_issuers','mirror','mirror_company_only','risk_explanation','missing_hk_source','missing_clock',
    'late_acquisition','us_after_cutoff','missing_us_source','same_source','expired_standing','bad_standing_span',
    'unconfirmed_standing','company_name_only']

if __name__=='__main__':
    import sys
    result=[make_case(n) for n in CASES]
    with open(sys.argv[1],'w') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    for c in result:print(c['name'],c['actual_mapping_count'],c['expected_mapping_count'],len(c['workspace']['research_attention']['cards']))
