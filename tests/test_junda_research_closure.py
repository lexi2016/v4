import hashlib
import json
from pathlib import Path

import pytest

from ops.bootstrap_stock_event_history import retained_single_stock_statistics
from ops.research_panel_daily_product import materialize_bound_single_company, reference, FLAGS
from ops import research_panel_daily_product as daily_product


def test_history_uses_market_calendar_and_keeps_unknowns_and_unmatured():
    calendar=['2026-01-02','2026-01-05','2026-01-06','2026-01-07','2026-01-08','2026-01-09']
    days=[calendar[i] for i in (0,1,3,4,5)]  # 1/6 is a market day with no stock bar
    original={k:0 for k in ('user_v1_level1_buy_signal','user_v1_level2_buy_signal','user_v1_B1','user_v1_B2','user_v1_B3')}
    kb={k:False for k in ('kb_b1','kb_b2','kb_b3','kb_violence_k','kb_fanbao')}
    rows=[{'trade_date':int(d.replace('-','')),'original':dict(original),'kb':dict(kb)} for d in days]
    rows[0]['original']['user_v1_level1_buy_signal']=1
    rows[-1]['original']['user_v1_level1_buy_signal']=1
    rows[0]['kb']['kb_b2']=None
    prices=[{'date':d,'close':10+i} for i,d in enumerate(days)]
    identity={'source_generation':'a'*64,'input_sha256':'b'*64,'source_view_sha256':'c'*64,
              'formula_sha256':'d'*64,'kb_contract_sha256':'e'*64,'asof':calendar[-1]}
    result=retained_single_stock_statistics(rows,prices,calendar,identity)
    level1=next(g for g in result['groups'] if g['group_id']=='original_level1')
    b2=next(g for g in result['groups'] if g['group_id']=='kb_b2')
    assert level1['horizons']['d2']['missing_price']==1
    assert level1['horizons']['d2']['not_matured']==1
    assert level1['horizons']['d2']['valid']==0
    assert b2['coverage']['unknown_dates']==1 and b2['eligible_event_count']==0


def test_company_producer_checks_bound_symbol_and_source_dates(tmp_path):
    def save(name,value):
        p=tmp_path/name;p.write_text(json.dumps(value));return reference(p)
    symbol='002865.SZ';source='a'*64;sha='b'*64
    binding=save('binding.json',{'symbol':symbol,'source_date':'2026-10-30','observation_date':'2026-11-02',
        'candidate_pool_member':False,'candidate_generation':'c'*64,'source_generation':source,
        'source_input_sha256':sha,'numeric_manifest':{'path':'x','sha256':'d'*64},**FLAGS})
    candidate=save('candidate.json',{'candidate_generation':'c'*64,'binding':binding})
    def pdf(name):
        p=tmp_path/name;p.write_bytes(b'%PDF-test');return reference(p)
    f10=save('f10.json',{'symbol':symbol,'status':'OBSERVED','historical_PIT':False,'source_text':'text',
        'source_text_sha256':hashlib.sha256(b'text').hexdigest(),**FLAGS})
    received={'symbol':symbol,'asof':'2026-10-30','sources':{
        'tdx_f10':{'file':f10,'kind':'TDX_F10_CURRENT_SNAPSHOT'},
        'official_quarterly':{'file':pdf('filing.pdf'),'url':'https://example.com/f.pdf','available_date':'2026-10-22','kind':'COMPANY_FILING'}},
        'business_reported':{'value':'same stock'},'financials_reported':{},'shareholders_reported':{},'report_catalog':[],'stored_report':None}
    inp=save('received.json',received)
    result=materialize_bound_single_company(candidate_ref=candidate,received_ref=inp,output_root=tmp_path)
    shard=json.loads(Path(result['path']).read_text())
    assert shard['symbol']==symbol and shard['source_generation']==source and shard['report_catalog']==[]
    received['sources']['official_quarterly']['available_date']='2026-10-31'
    inp=save('received.json',received)
    with pytest.raises(ValueError,match='SINGLE_COMPANY_SOURCE_INVALID'):
        materialize_bound_single_company(candidate_ref=candidate,received_ref=inp,output_root=tmp_path)


def test_pufa_company_owner_requires_exact_parent_and_official_evidence(tmp_path,monkeypatch):
    def save(name,value):
        p=tmp_path/name;p.write_text(json.dumps(value));return reference(p)
    symbol='600000.SH';source='a'*64;source_input='b'*64;parent_generation='c'*64
    monkeypatch.setattr(daily_product,'A20_PUFA_PARENT_GENERATION',parent_generation)
    monkeypatch.setattr(daily_product,'A20_PUFA_SOURCE_GENERATION',source)
    monkeypatch.setattr(daily_product,'A20_PUFA_SOURCE_INPUT',source_input)
    manifest={'path':'/fixture/manifest.json','sha256':'d'*64}
    origin=save('origin.json',{'symbol':symbol,'source_date':'2026-10-30','observation_date':'2026-11-02',
        'generation':source,'input_sha256':source_input,'numeric_manifest':manifest,'historical_PIT':False,**FLAGS})
    wrapper=save('wrapper.json',{'symbol':symbol,'candidate_generation':parent_generation,'origin_binding':origin})
    index=save('index.json',{'source_date':'2026-10-30','observation_date':'2026-11-02','source_generation':source,
        'input_sha256':source_input,'candidate_generation':parent_generation,'numeric_manifest':manifest,
        'symbols':{symbol:{'status':'READY','binding':wrapper}},'historical_PIT':False,**FLAGS})
    identity={'symbol':symbol,'source_date':'2026-10-30','parent_generation':parent_generation,
        'parent_index_sha256':index['sha256'],'parent_binding_sha256':wrapper['sha256'],'origin_binding_sha256':origin['sha256']}
    candidate=save('candidate.json',{'schema':'v4.workbench.a20_hold_score_candidate.v1','identity':identity,
        'candidate_generation':hashlib.sha256(daily_product.canonical(identity)).hexdigest(),
        'parent_index':index,'parent_binding':wrapper,'origin_binding':origin,'historical_PIT':False,**FLAGS})
    pdf=tmp_path/'quarterly.pdf';pdf.write_bytes(b'%PDF-verified-fixture');pdf_ref=reference(pdf)
    listing=tmp_path/'listing.html';listing.write_text('listing');listing_ref=reference(listing)
    notice=tmp_path/'notice.pdf';notice.write_bytes(b'%PDF-notice');notice_ref=reference(notice)
    monkeypatch.setattr(daily_product,'A20_PUFA_OFFICIAL_PDF_SHA',pdf_ref['sha256'],raising=False)
    proof={'schema':'v4.a20.official_quarterly_evidence.v1','status':'ISSUER_SOURCE_VERIFIED_NOT_BOUND','symbol':symbol,
        'report_period_end':'2026-09-30','period_start':'2026-01-01','statement_scope':'CONSOLIDATED_GROUP',
        'currency':'CNY','original_unit':'CNY_MILLION','source':pdf_ref,'source_url':'https://example.test/quarterly.pdf',
        'original_values_million_cny':{'revenue':138133,'net_profit_parent':40572,'net_cash_flow_from_operating_activities':268604},
        'normalized_values_yuan':{'latest_revenue':138133000000,'latest_net_profit_parent':40572000000,'operating_cash_flow':268604000000},
        'operating_cash_flow_basis':'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES','issuer_index':{'ref':listing_ref,'display_date':'2026-10-30'},
        'issuer_sse_notice':{'ref':notice_ref,'stated_sse_disclosure_date':'2026-10-31'},
        'availability_asof_20261030_market_close':'CANNOT_CONFIRM','historical_PIT':False,**FLAGS}
    proof_ref=save('proof.json',proof);monkeypatch.setattr(daily_product,'A20_PUFA_OFFICIAL_EVIDENCE_SHA',proof_ref['sha256'],raising=False)
    text='◇600000 浦发银行 更新日期：2026-11-01◇';f10=save('f10.json',{'symbol':symbol,'status':'OBSERVED',
        'source_text':text,'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'historical_PIT':False,**FLAGS})
    fin={**proof['normalized_values_yuan'],'latest_report_period':'2026-09-30','monetary_unit':'元',
         'operating_cash_flow_basis':'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES','evidence_status':'OFFICIAL_FILING'}
    received={'symbol':symbol,'asof':'2026-10-30','sources':{'tdx_f10':{'file':f10,'kind':'TDX_F10_CURRENT_SNAPSHOT'},
        'official_quarterly':{'file':pdf_ref,'kind':'COMPANY_FILING','url':proof['source_url']}},
        'official_evidence':proof_ref,'business_reported':{},'financials_reported':fin,'shareholders_reported':{},
        'report_catalog':[],'stored_report':None,'historical_PIT':False,**FLAGS}
    received_ref=save('received.json',received)
    shard_ref=materialize_bound_single_company(candidate_ref=candidate,received_ref=received_ref,output_root=tmp_path)
    shard=json.loads(Path(shard_ref['path']).read_text())
    assert shard['financials_reported']['operating_cash_flow']==268604000000 and shard['official_evidence']==proof_ref
    assert shard['historical_PIT'] is False
    from infrastructure.research_workbench_host import ResearchWorkbenchHost
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost);host.binding={'a20_pufa_official_company':shard_ref}
    p={'source_generation':source,'source_identity':{'input_sha256':source_input},'manifest':manifest}
    official=host._scoped_pufa_official('2026-10-30',symbol,p)
    assert official['financials']['operating_cash_flow']==268604000000 and official['sse_notice_date']=='2026-10-31'
    assert host._scoped_pufa_official('2026-10-30','000001.SZ',p) is None
    corrupt={**shard,'source_generation':'e'*64};host.binding['a20_pufa_official_company']=save('bad-shard.json',corrupt)
    with pytest.raises(ValueError,match='F10_SCOPED_OFFICIAL_IDENTITY_CONFLICT'):
        host._scoped_pufa_official('2026-10-30',symbol,p)
    received['financials_reported']={**fin,'operating_cash_flow':268604000001};received_ref=save('received.json',received)
    with pytest.raises(ValueError,match='SINGLE_PUFA_EVIDENCE_CONFLICT'):
        materialize_bound_single_company(candidate_ref=candidate,received_ref=received_ref,output_root=tmp_path)
