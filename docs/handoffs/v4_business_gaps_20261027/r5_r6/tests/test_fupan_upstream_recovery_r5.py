import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

CASE = Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027/operations/two_pool_upstream_r5')
FLAGS = {'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}

@pytest.fixture(params=['daily', 'pool'])
def owner(request):
    for name in list(sys.modules):
        if name == 'review_core' or name.startswith('review_core.'):
            del sys.modules[name]
    sys.path.insert(0, str(CASE / ('fupan_candidate_' + request.param + '_r2')))
    try:
        yield importlib.import_module('review_core.review')
    finally:
        sys.path.pop(0)

@pytest.fixture
def evidence(tmp_path):
    selector=str(tmp_path/'selector.parquet'); sha='a'*64; generation='b'*64
    formula=dict(target_date='20261027', asof_date='20261027', status='READY', pit_certified=False, selector_pointer_ready=True, selector_sha256=sha, selector=selector, generation_id=generation, **FLAGS)
    a=dict(target_date='20261027',status='PARTIAL',authority_status='REBUILD_REQUIRED',reason='A_SYNC_AUTHORITY_REBUILD_REQUIRED',selector_sha256=sha,selector=selector,formula=formula,accepted_count=5538,target_count=5808,quarantine_count=270,**FLAGS)
    result=dict(workload_id='research_panel_daily_a',status='SUCCEEDED',reason=a['reason'],accepted_count=5538,target_count=5808,quarantine_count=270)
    dispatch=dict(schema_version='v3_5.dispatch.v1',mode='LIVE',business_date='20261027',target_date='20261027',selected_workload_ids=['research_panel_daily_a'],workload_results=[result],finished_at='2026-10-27T11:02:56+00:00',**FLAGS)
    refs={}
    for prefix,doc in [('a_receipt',a),('dispatch_receipt',dispatch)]:
        p=tmp_path/(prefix+'.json'); raw=json.dumps(doc).encode();p.write_bytes(raw);refs[prefix+'_path']=str(p);refs[prefix+'_sha256']=hashlib.sha256(raw).hexdigest()
    return dict(schema_version='review_core.qfq_partial_coverage.v1',source_date='20261027',target_date='20261028',selector_sha256=sha,selector_path=selector,generation_id=generation,available_at='2026-10-27T11:02:56+00:00',accepted_count=5538,target_count=5808,quarantine_count=270,selector_rows=5538,tdx_daily_rows=5537,authority_status='PARTIAL',pit_certified=False,pre_cutoff_capture_verified=False,source_merge_role='SOURCE_ONLY',stage_selection_eligible=False,**FLAGS,**refs)

def payload(evidence):
    return dict(trade_date='20261027',market_scope='FULL_MARKET',market_completeness='PARTIAL_COVERAGE',coverage_evidence=evidence)

def test_both_owner_versions_accept_only_bound_partial(owner,evidence):
    assert owner._market_contract(payload(evidence)) == ('FULL_MARKET','PARTIAL_COVERAGE')
    for key,value in [('source_date','20261026'),('pit_certified',True),('production_allowed',True),('target_count',5809),('selector_sha256','f'*64),('available_at','2026-10-27T09:30:00+00:00')]:
        bad=copy.deepcopy(evidence);bad[key]=value
        with pytest.raises(owner.ReviewBundleValidationError):owner._market_contract(payload(bad))
    Path(evidence['a_receipt_path']).write_text('{}')
    with pytest.raises(owner.ReviewBundleValidationError):owner._market_contract(payload(evidence))

def test_daily_partial_has_no_market_breadth(evidence):
    for name in list(sys.modules):
        if name == 'review_core' or name.startswith('review_core.'): del sys.modules[name]
    sys.path.insert(0,str(CASE/'fupan_candidate_daily_r2'))
    try:
        pipeline=importlib.import_module('review_core.review_pipeline')
        page=pipeline._mark_page_scope({'trade_date':'20261027','market_rows':[{'metric':'上涨/下跌'}], 'summary_cards':[{'title':'市场宽度'}]},'FULL_MARKET',[{}],evidence)
        assert page['market_rows']==[]
        assert page['market_completeness']=='PARTIAL_COVERAGE'
        assert page['summary_cards'][0]['title']=='部分覆盖'
    finally: sys.path.pop(0)

def test_readiness_must_match_coverage_and_remain_uncertified(owner,evidence):
    p=payload(evidence)
    p['readiness']={'selector':{'pit_safe':False,'status':'CANNOT_CONFIRM','source_date':'20261027','target_trade_date':'20261028','selector_sha256':evidence['selector_sha256']}}
    assert owner._market_contract(p)[1]=='PARTIAL_COVERAGE'
    for key,value in [('pit_safe',True),('status','READY'),('target_trade_date','20261029'),('selector_sha256','f'*64)]:
        bad=copy.deepcopy(p);bad['readiness']['selector'][key]=value
        with pytest.raises(owner.ReviewBundleValidationError):owner._market_contract(bad)

def test_pool_rejects_wrong_target_without_rows(monkeypatch):
    for name in list(sys.modules):
        if name == 'review_core' or name.startswith('review_core.'): del sys.modules[name]
    sys.path.insert(0,str(CASE/'fupan_candidate_pool_r2'))
    try:
        pool=importlib.import_module('review_core.fupan_pool')
        source={'signal_date':'20261027','status':'PARTIAL','rows':[{'code':'SH.600000'}], 'cannot_confirm':['SELECTOR_CUTOFF_MISSING'], 'provenance':{'coverage_evidence':{'target_date':'20261028'}}}
        monkeypatch.setattr(pool,'load_review_bundle_source',lambda *args,**kwargs:source)
        assert pool.build_fupan_review_pool('20261027','20261028','/none','/none')['row_count']==1
        bad=pool.build_fupan_review_pool('20261027','20261029','/none','/none')
        assert bad['status']=='CANNOT_CONFIRM' and bad['row_count']==0
        assert 'SOURCE_TARGET_DATE_MISMATCH' in bad['cannot_confirm']
    finally: sys.path.pop(0)
