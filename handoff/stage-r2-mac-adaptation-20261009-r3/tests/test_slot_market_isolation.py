"""Synthetic I/O fixtures; real runner, RawStore, selectors and SelectionStore.

The candidate-reader seam supplies a validated fixture. This file proves
market isolation/receipt behavior, not the Mac's real candidate inputs.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
from stage_center import runner as runtime
from stage_center.acquisition import SourceResult, StageUniverseBinding
from stage_center.candidate_input import CandidateInput
from stage_center.research_context import ResearchContextError
from stage_center.scheduler import DueDecision
from stage_center.selection import SelectionStore, select_hk_four_lane, select_a_live_stage
from stage_center._runner_parts.runner_receipts import _candidate_input_bindings

DATE = '20261009'
STAGE = 'STAGE_0930_0935'


def candidate(root):
    return CandidateInput(root, DATE, 'fixture/current.json', '1'*64, 'synthetic-a-input',
        tuple(f'A.{i:06d}' for i in range(1,217)), '2'*64, '3'*64, '4'*64, '5'*64,
        ('fixture=SYNTHETIC_TEST_ONLY',))


def raw_rows(market, count=12):
    return tuple({
        'batch_index': i, 'code': f'HK.{i+1:05d}' if market=='HK_CONNECT' else f'A.{i+1:06d}',
        'name': f'Fixture {i}', 'update_time': '2026-10-09 09:35:00',
        'last_price': 11+i/100, 'open_price': 10, 'high_price': 12, 'low_price': 9,
        'prev_close_price': 10, 'turnover': 10000000, 'volume': 1000000,
        'bid_price': 11, 'ask_price': 11.1, 'bid_vol': 1000, 'ask_vol': 1000,
        'window_start': '2026-10-09 09:30:00', 'window_end': '2026-10-09 09:35:00',
        'bar_count': 5, 'temporal_cutoff_safe': True,
        'candidate_lanes': ['LIVE_HKCONNECT_GAINER'], 'pct_chg': 10+i/10,
        'circular_market_cap_hkd_yi': 20,
    } for i in range(count))


def hk_builder(source, plan, raw):
    return select_hk_four_lane(source.rows, plan.trade_date, plan.stage_id, raw['artifact_sha256'],
        source_status=source.status, requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols, cannot_confirm=source.cannot_confirm,
        source_evidence=(*source.source_evidence, 'selection_contract=V3_TOP10_RECOMMENDATION'))


def a_builder(source, plan, raw):
    rows=[{**row,'qmt':{'lastPrice':row['last_price'],'open':row['open_price'],
        'lastClose':row['prev_close_price'],'high':row['high_price'],'low':row['low_price'],
        'amount':row['turnover'],'bidVol':[1000],'askVol':[1000]}} for row in source.rows]
    return select_a_live_stage(rows, plan.trade_date, plan.stage_id, raw['artifact_sha256'],
        source_status=source.status, requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols, cannot_confirm=source.cannot_confirm,
        source_evidence=(*source.source_evidence,'selection_contract=V3_TOP10_RECOMMENDATION'))


def setup_runner(tmp_path, monkeypatch, builders):
    c=candidate(tmp_path/'candidate')
    monkeypatch.setattr(runtime,'read_candidate_input',lambda *a,**kw:c)
    config=runtime.RunnerConfig(tmp_path/'candidate',tmp_path/'raw',tmp_path/'selection',tmp_path/'receipts',
        selection_builders=builders)
    sources={market:SourceResult('fixture', 'PARTIAL_WITH_ROWS' if market=='A_SHARE' else 'READY',
        raw_rows(market,205 if market=='A_SHARE' else 12),requested_rows=216 if market=='A_SHARE' else 12,
        missing_symbols=tuple(f'A.{i:06d}' for i in range(206,217)) if market=='A_SHARE' else (),
        source_evidence=('fixture=SYNTHETIC_TEST_ONLY',)) for market in ('A_SHARE','HK_CONNECT')}
    r=runtime.StageCenterRunner(config,collectors={m:(lambda p,m:m and sources[m]) for m in sources})
    r._execution_origin='MANUAL_REPLAY'
    d=DueDecision(stage_id=STAGE,trade_date=DATE,status='DUE',scheduled_at=None,idempotency_key='test',calendar={})
    return r,d


def test_a_witness_failure_does_not_prevent_hk_original_selection_publication(tmp_path,monkeypatch):
    reason='RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH'
    def invalid_a(*a,**kw):raise ResearchContextError(reason)
    r,d=setup_runner(tmp_path,monkeypatch,{'A_SHARE':invalid_a,'HK_CONNECT':hk_builder})
    result=r._run_one(d)
    hk=result['markets']['HK_CONNECT']
    assert hk.get('selected_rows')==10, result
    verified=SelectionStore(r.config.selection_root)._verify_run(DATE,STAGE,'HK_CONNECT',hk['run_id'])
    assert verified['envelope']['rows']==hk['rows']
    assert reason in result['markets']['A_SHARE']['cannot_confirm']
    assert result['markets']['A_SHARE']['requested_rows']==216
    assert result['markets']['A_SHARE']['observed_rows']==205
    assert result['selection_artifacts']['HK_CONNECT']['artifact_bytes_sha256']==verified['artifact_sha256']
    assert result['write_performed'] is True
    assert result['status']=='PARTIAL_WITH_ROWS'


def test_later_builder_failure_preserves_already_written_a_run_in_owner_receipt(tmp_path,monkeypatch):
    def invalid_hk(*a,**kw):raise ValueError('HK_FIXTURE_INVALID')
    r,d=setup_runner(tmp_path,monkeypatch,{'A_SHARE':a_builder,'HK_CONNECT':invalid_hk})
    result=r._run_one(d)
    a=result['markets']['A_SHARE']
    assert a.get('selected_rows')==10,result
    assert a['requested_rows']==216
    assert result['markets']['HK_CONNECT']['cannot_confirm']==['HK_FIXTURE_INVALID']
    assert result['selection_artifacts']['A_SHARE']['run_id']==a['run_id']
    history=result['receipt_history'];raw=(r.config.receipt_root/history['relative_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==history['sha256']
    assert json.loads(raw)['markets']['A_SHARE']['run_id']==a['run_id']


def test_research_input_binding_cannot_claim_d1_membership(tmp_path):
    b=StageUniverseBinding.ready(market='HK_CONNECT',trade_date=DATE,role='HK_CURRENT_DAY_RESEARCH',
        codes=('HK.00001',),source_run_id='research-fixture',sha256='6'*64,
        evidence=('hk_selection_mode=CURRENT_DAY_RESEARCH_ONLY',))
    item=_candidate_input_bindings(candidate(tmp_path),b,('HK_CONNECT',),a_candidate_missing=True)['HK_CONNECT']
    assert item['kind']=='HK_CURRENT_DAY_RESEARCH'
    assert item['membership_status']=='CANNOT_CONFIRM'
    assert item['binding_bytes_sha256']=='6'*64
    assert item['trio_status']=='CURRENT_RESEARCH_FILES_SHA_BOUND'


def test_owner_receipt_retains_manual_origin_and_observed_source_identity(tmp_path,monkeypatch):
    r,d=setup_runner(tmp_path,monkeypatch,{'A_SHARE':a_builder,'HK_CONNECT':hk_builder})
    result=r._run_one(d)
    assert result.get('execution_origin')=='MANUAL_REPLAY'
    assert result.get('RESEARCH_ONLY') is True
    code=result.get('runtime_source_identity')
    assert code and code['scope']=='LOADED_MODULE_PATHS_AND_OBSERVED_FILE_BYTES'
    assert code['memory_execution_attested'] is False
    assert code['files']['stage_center/runner.py']['sha256']==hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
    assert result.get('natural_verified') is not True
    for flag in ('production_allowed','buy_gate_updated','orders_sent'):assert result[flag] is False

@pytest.mark.parametrize('field,value',[('trade_date','20261008'),('stage_id','STAGE_0935_0940'),('market','A_SHARE')])
def test_writer_cannot_bind_selection_with_explicit_different_scope(tmp_path,monkeypatch,field,value):
    from stage_center._runner_parts.runner_receipts import _selection_artifact_binding
    r,d=setup_runner(tmp_path,monkeypatch,{'A_SHARE':a_builder,'HK_CONNECT':hk_builder})
    result=r._run_one(d);original=dict(result['markets']['HK_CONNECT']);original[field]=value
    with pytest.raises(ValueError,match='scope'):
        _selection_artifact_binding(SelectionStore(r.config.selection_root),DATE,STAGE,'HK_CONNECT',original)
