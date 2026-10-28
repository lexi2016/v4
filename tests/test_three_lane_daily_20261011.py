"""Daily projection contract tests with explicit synthetic source inputs.

Selection decisions are always produced by the original ledger. Receipt
fixtures exercise admission; they are not claims about a live owner run.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from v4.manager_research.research_attention import build_research_selection_ledger
from v4.manager_research.workspace import ATTEMPT_SCHEMA, seal_attempt
from v4.manager_research.workspace_daily_channels import build_daily_channels
from v4.manager_research.workspace_projection import FLAGS, digest

_spec = importlib.util.spec_from_file_location('three_lane_ledger_fixture',
    Path(__file__).with_name('test_manager_research_selection_ledger.py'))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def _source(*, empty=False, saved=True):
    screen, cards = fixture._fixture()
    if empty:
        screen.update(strict=[], near=[], pending=[], cards=[], gaps=[], status='READY')
        screen['coverage'].update(input_candidate_count=1, history_complete_count=1,
            history_pending_count=0, strict_count=0, near_candidate_count=0,
            selected_count=0, excluded_count=1, screen_unresolved_count=0, row_accounted_count=1)
        cards = []
    value = dict(target_trade_date=fixture.TARGET,
        date_bindings=dict(plan_date=fixture.TARGET, selection_date=fixture.TARGET, announcement_date=fixture.SESSION),
        plan_context=dict(market_session=fixture.SESSION, research_cutoff='2026-10-02T09:00:00+08:00'),
        input_identity='d' * 64, market_screen=screen,
        research_attention=dict(cards=cards,
            research_selection=build_research_selection_ledger(screen, cards, fixture.TARGET)),
        gaps=['UNRELATED_ANNOUNCEMENT_UNAVAILABLE'], **FLAGS)
    if saved:
        value['plan_product'] = dict(status='CURRENT', consumed=True,
            original_owner='ManagerResearchJobService.refresh_workspace_plan',
            run_id='1' * 32, sha256='e' * 64, generated_at='2026-10-02T09:00:00+08:00',
            execution_kind='MANUAL_REFRESH')
        value['workspace_plan_attempt'] = seal_attempt(dict(schema_version=ATTEMPT_SCHEMA,
            owner='ManagerResearchJobService.refresh_workspace_plan', target_trade_date=fixture.TARGET,
            run_id='1' * 32, input_identity=value['input_identity'], state='PARTIAL',
            failure_reasons=['UNRELATED_ANNOUNCEMENT_UNAVAILABLE'], execution_kind='MANUAL_REFRESH',
            started_at='2026-10-02T08:59:00+08:00', finished_at='2026-10-02T09:01:00+08:00', **FLAGS))
    return value


def _channel(value, channel='OVERSOLD'):
    return next(item for item in build_daily_channels(value)['channels'] if item['channel'] == channel)


def test_daily_uses_original_ledger_decisions_and_preserves_source_pointers():
    value = _source()
    before = deepcopy(value)
    daily = _channel(value)
    ledger = value['research_attention']['research_selection']
    assert daily['decision_identity'] == ledger['decision_identity']
    assert daily['coverage'] == ledger['coverage']
    assert daily['formal_selection_input'] is False
    assert daily['owner'] == 'v4.manager_research.research_attention.build_research_selection_ledger'
    assert daily['status'] == 'PARTIAL'
    assert daily['candidate_count'] == 1
    assert daily['pending_count'] == 1
    assert daily['watch_count'] == 1
    assert [row['symbol'] for row in daily['rows']] == ['HK.00001', 'HK.00002']
    for row, decision in zip(daily['rows'], ledger['decisions'][:2]):
        assert row['reason'] == decision['decision_reason']
        assert row['source_refs'] == decision['source_refs']
        assert row['research_priority'] == decision['research_priority']
    assert 'UNRELATED_ANNOUNCEMENT_UNAVAILABLE' not in daily['gaps']
    assert value == before


def test_strict_bucket_with_unverified_references_is_unresolved_not_selected():
    value = _source()
    screen = value['market_screen']
    screen['strict'][0]['source_refs'] = []
    value['research_attention']['research_selection'] = build_research_selection_ledger(
        screen, value['research_attention']['cards'], fixture.TARGET)
    daily = _channel(value)
    assert daily['candidate_count'] is None
    assert daily['pending_count'] == 2
    assert all(row['symbol'] != 'HK.00001' for row in daily['rows'])


def test_strict_bucket_without_original_ledger_cannot_become_final_research_selection():
    value = _source()
    value['research_attention'].pop('research_selection')
    daily = _channel(value)
    assert daily['status'] == 'CANNOT_CONFIRM'
    assert daily['rows'] == []
    assert daily['candidate_count'] is None
    assert 'ORIGINAL_RESEARCH_SELECTION_LEDGER_MISSING' in daily['gaps']


@pytest.mark.parametrize('mutation', ['decision', 'source', 'target', 'safety'])
def test_stale_or_tampered_ledger_never_bypasses_original_screen(mutation):
    value = _source()
    ledger = value['research_attention']['research_selection']
    if mutation == 'decision':
        ledger['decisions'][0]['decision_status'] = 'EXCLUDED'
    elif mutation == 'source':
        value['market_screen']['strict'][0]['source_refs'][0]['payload_sha256'] = 'f' * 64
    elif mutation == 'target':
        ledger['target_trade_date'] = '20261009'
    else:
        ledger['orders_sent'] = True
    daily = _channel(value)
    assert daily['status'] == 'CANNOT_CONFIRM'
    assert daily['rows'] == []
    assert daily['candidate_count'] is None
    assert 'ORIGINAL_RESEARCH_SELECTION_LEDGER_MISMATCH' in daily['gaps']


def test_verified_full_exclusion_is_zero_even_when_other_lane_is_missing():
    daily = _channel(_source(empty=True))
    assert daily['status'] == 'READY_EMPTY'
    assert daily['candidate_count'] == 0
    assert daily['pending_count'] == 0
    assert daily['run_id'] == '1' * 32
    assert daily['coverage']['excluded_count'] == 1
    assert daily['natural_run_verified'] is False


@pytest.mark.parametrize('empty', [False, True])
def test_unsaved_preview_cannot_claim_completed_selection_or_verified_zero(empty):
    daily = _channel(_source(empty=empty, saved=False))
    assert daily['status'] == 'PARTIAL'
    assert daily['candidate_count'] is None if empty else daily['candidate_count'] == 1
    assert daily['run_id'] is None
    assert daily['product_sha256'] is None
    assert 'RESEARCH_SELECTION_OWNER_PLAN_NOT_VERIFIED' in daily['gaps']


def test_impossible_owner_attempt_time_cannot_admit_saved_zero():
    value = _source(empty=True)
    attempt = value['workspace_plan_attempt']
    attempt['finished_at'] = '2026-10-02T08:59:30+08:00'
    value['workspace_plan_attempt'] = seal_attempt(attempt)
    daily = _channel(value)
    assert daily['status'] == 'PARTIAL'
    assert daily['candidate_count'] is None
    assert daily['run_id'] is None


def test_verified_product_attempt_is_not_replaced_by_a_later_failed_attempt():
    value = _source(empty=True)
    value['workspace_plan_product_attempt'] = deepcopy(value['workspace_plan_attempt'])
    value['workspace_plan_attempt'] = seal_attempt(dict(value['workspace_plan_attempt'],
        run_id='2' * 32, state='FAILED', failure_reasons=['LATER_ATTEMPT_FAILED']))
    daily = _channel(value)
    assert daily['status'] == 'READY_EMPTY'
    assert daily['run_id'] == '1' * 32


def test_workspace_focus_is_not_a_hk_stage_selection():
    value = _source()
    value['stocks'] = [dict(symbol='HK.00001', name='Fixture focus',
        connect_eligibility='VERIFIED_TARGET_UNIVERSE', why_watch=['Fixture material'])]
    value['focus_symbols'] = ['HK.00001']
    daily = _channel(value, 'HK_CONNECT')
    assert daily['candidate_count'] is None
    assert daily['rows'] == []
    assert 'HK_ORIGINAL_STAGE_SELECTION_NOT_AVAILABLE' in daily['gaps']


def _stage(value, *, count=2):
    target = fixture.TARGET
    rows = [dict(code=f'HK.{index + 1:05d}', name=f'Stage fixture {index + 1}',
        rank=count-index, order=index+1, lane_evidence=['ORIGINAL_LANE_FIXTURE'],
        formal_eligible=False, action_level='NO_BUY', trade_status='RESEARCH_ONLY', source_mode='LIVE')
        for index in range(count)]
    market = dict(trade_date=target, stage_id='STAGE_0935_0940', market='HK_CONNECT',
        status='READY' if rows else 'READY_EMPTY', selection_status='READY' if rows else 'READY_EMPTY',
        run_id='run-original-fixture', artifact_id='artifact-original-fixture',
        algorithm_id='original-algorithm-fixture', algorithm_sha256='a' * 64,
        raw_artifact_sha256='b' * 64, source_status='READY',
        requested_rows=count, source_rows=count, selected_rows=count, coverage_ratio=1,
        missing_symbols=[], cannot_confirm=[], source_evidence=[], rows=rows,
        selection_run_id='run-original-fixture', selection_manifest_sha256='c' * 64,
        selection_artifact_sha256='d' * 64, selection_receipt_sha256='e' * 64,
        selection_manifest_receipt_verified=True)
    scope = dict(status='OWNER_VERIFIED', gaps=[], codes=[row['code'] for row in rows],
        target_trade_date=target, membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
        source=dict(market='HK_CONNECT', role='HK_CONNECT_FULL_MARKET_AUTHORITY', source_date=target, sha256='f'*64),
        identity='f'*64)
    scope['identity'] = digest([target, scope['codes'], scope['source']['sha256']])
    value['selection_diagnostics'] = dict(membership=scope, connect_gaps=['ANNOUNCEMENT_MISSING'])
    value['stage_selection_readback'] = dict(schema_version='stage_center.selection_consumer.v1',
        response_source='SHARED_STAGE_CENTER', trade_date=target, stage_id=market['stage_id'],
        markets={'HK_CONNECT': market}, execution_evidence=dict(execution_verified=False,
            natural_verified=False, recorded_at='not-an-available-time',
            markets={'HK_CONNECT': {'selection_binding': 'BOUND_TO_VERIFIED_SELECTION'}}),
        write_performed=False, **FLAGS)
    value['read_context'] = dict(mode='CURRENT_DYNAMIC_PREVIEW')
    return market


def test_hk_uses_full_native_result_and_original_identity_without_plan_or_time_substitution():
    value = _source()
    native = _stage(value, count=61)
    daily = _channel(value, 'HK_CONNECT')
    assert daily['status'] == 'PARTIAL'
    assert daily['candidate_count'] == 61
    assert daily['run_id'] == native['run_id']
    assert daily['product_sha256'] == native['selection_manifest_sha256']
    assert daily['product_sha256'] != value['plan_product']['sha256']
    assert daily['generated_at'] is None
    assert daily['stage_id'] == 'STAGE_0935_0940'
    assert daily['natural_run_verified'] is False
    assert 'ANNOUNCEMENT_MISSING' not in daily['gaps']
    for row, original in zip(daily['rows'], native['rows']):
        for key in ('rank', 'order', 'formal_eligible', 'action_level', 'source_mode', 'trade_status'):
            assert row[key] == original[key]
        assert row['symbol'] == original['code']


@pytest.mark.parametrize('mutation,reason', [
    ('backfill', 'HK_BACKFILL_NOT_DAILY_SELECTION'),
    ('date', 'HK_ORIGINAL_STAGE_DATE_OR_MARKET_MISMATCH'),
    ('receipt', 'HK_SELECTION_TRIO_NOT_VERIFIED'),
    ('count', 'HK_ORIGINAL_STAGE_ROW_CONTRACT_INVALID'),
    ('historical', 'HK_STAGE_AVAILABILITY_AT_CUTOFF_NOT_VERIFIED'),
])
def test_hk_rejects_wrong_date_backfill_missing_trio_and_unproven_history(mutation, reason):
    value = _source()
    native = _stage(value)
    if mutation == 'backfill': native['selection_mode'] = 'BACKFILL'
    elif mutation == 'date': native['trade_date'] = '20261009'
    elif mutation == 'receipt': native.pop('selection_receipt_sha256')
    elif mutation == 'count': native['selected_rows'] += 1
    else: value['read_context']['mode'] = 'HISTORICAL_AS_OF'
    daily = _channel(value, 'HK_CONNECT')
    assert daily['status'] == 'CANNOT_CONFIRM'
    assert daily['candidate_count'] is None
    assert daily['rows'] == []
    assert reason in daily['gaps']


def test_hk_saved_empty_without_verified_execution_does_not_claim_zero():
    value = _source()
    _stage(value, count=0)
    daily = _channel(value, 'HK_CONNECT')
    assert daily['candidate_count'] is None
    assert daily['status'] in {'PARTIAL', 'CANNOT_CONFIRM'}
    assert daily['rows'] == []


def test_stage_readback_uses_canonical_rows_instead_of_truncated_alias():
    from v4.manager_research.workspace_daily_channels import stage_selection_readback
    value = _source()
    native = _stage(value, count=61)
    raw = deepcopy(value['stage_selection_readback'])
    raw['selection_markets'] = raw.pop('markets')
    raw['markets'] = {'HK': dict(native, rows=native['rows'][:50])}
    preserved = stage_selection_readback(raw)
    assert preserved['markets']['HK_CONNECT']['rows'] == native['rows']
    assert len(preserved['markets']['HK_CONNECT']['rows']) == 61
    raw['selection_markets']['HK_CONNECT'] = None
    assert stage_selection_readback(raw)['markets']['HK_CONNECT'] is None


def test_missing_stage_does_not_invent_null_safety_flags_or_block_partial_save(tmp_path):
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'real-owner-state'), None, None)
    try:
        result = service.refresh_workspace_plan('20261012')
        assert result['plan_product']['consumed'] is True
        assert result['workspace_plan_product_attempt']['state'] == 'PARTIAL'
        assert result['stage_selection_readback'] == {'markets': {'HK_CONNECT': None}}
        assert _channel(result, 'HK_CONNECT')['candidate_count'] is None
        assert service.get_workspace_plan('20261012')['sha256'] == result['plan_product']['sha256']
    finally:
        service.close()


def test_history_preserves_execution_context_for_original_saved_research_ledger(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from v4.manager_research import workspace as w, workspace_history as history
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.workspace_plan import plan_context
    from v4.manager_research.workspace_projection import build_workspace
    source = _source(empty=True)
    context = plan_context(fixture.TARGET, now=datetime.fromisoformat('2026-10-02T09:00:00+08:00'))
    body = build_workspace(fixture.TARGET, plan_context=context,
        catalyst=dict(status='READY_EMPTY', cards=[], gaps=[]), market_screen=source['market_screen'])
    body.update(date_bindings=source['date_bindings'], research_attention=source['research_attention'])
    execution = dict(trigger_kind='MANUAL', timing='ON_TIME', natural_run_verified=False,
        started_at='2026-10-02T08:59:00+08:00', finished_at='2026-10-02T09:01:00+08:00',
        scheduled_for='2026-10-02T08:58:00+08:00')
    product = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=fixture.TARGET, run_id='1'*32,
        owner='ManagerResearchJobService.refresh_workspace_plan', execution_kind='MANUAL_REFRESH',
        generated_at='2026-10-02T09:00:00+08:00', execution_context=execution,
        input_identity=body['input_identity'], workspace=body, **FLAGS)
    product['sha256'] = digest(product)
    attempt = seal_attempt(dict(source['workspace_plan_attempt'],
        input_identity=body['input_identity'], execution_context=execution))
    store = ManagerResearchStore(tmp_path / 'history-state')
    for name in ('latest', product['run_id']):
        store._write_atomic(store.root / 'workspace_plans' / fixture.TARGET / (name+'.json'), product)
        store._write_atomic(store.root / 'workspace_plan_runs' / fixture.TARGET / (name+'.json'), attempt)
    before = {str(p): p.read_bytes() for p in store.root.rglob('*.json')}
    # The historical admission, exact attempt and PIT gates are real; only
    # the external source reread is a controlled unchanged-source fixture.
    monkeypatch.setattr(w, '_compute_workspace', lambda *args, **kwargs: deepcopy(body))
    result = history.read_history(SimpleNamespace(store=store), fixture.TARGET)
    assert result['plan_product']['status'] == 'CURRENT', result['plan_product']
    assert result['plan_product']['execution_context'] == execution
    daily = _channel(result)
    assert daily['status'] == 'READY_EMPTY'
    assert daily['candidate_count'] == 0
    assert daily['run_id'] == product['run_id']
    assert daily['product_sha256'] == product['sha256']
    assert {str(p): p.read_bytes() for p in store.root.rglob('*.json')} == before
