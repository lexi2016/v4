import hashlib
import json
from pathlib import Path

import pytest

from ops.bootstrap_stock_event_history import retained_single_stock_statistics
from ops.research_panel_daily_product import materialize_bound_single_company, reference, FLAGS


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
