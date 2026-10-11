"""Original selection contracts, using synthetic inputs and no producer writes."""
from copy import deepcopy

import pytest

from test_manager_research_selection_ledger import TARGET, _fixture
from v4.manager_research.research_attention import build_research_selection_ledger
from v4.manager_research.workspace_daily_channels import build_daily_channels
from v4.manager_research.workspace_projection import FLAGS, digest


def workspace(screen, cards):
    return dict(target_trade_date=TARGET,
        date_bindings=dict(plan_date=TARGET, selection_date=TARGET, announcement_date='20260930'),
        market_screen=screen,
        research_attention=dict(research_selection=build_research_selection_ledger(screen, cards, TARGET)))


def channel(value, name='OVERSOLD'):
    return next(row for row in build_daily_channels(value)['channels'] if row['channel'] == name)


def test_daily_uses_original_ledger_decisions_and_keeps_complete_accounting():
    screen, cards = _fixture()
    value = workspace(screen, cards)
    before = deepcopy(value)
    result = channel(value)
    ledger = value['research_attention']['research_selection']
    assert result['owner'] == 'build_research_selection_ledger'
    assert [(r['symbol'], r['selection_status']) for r in result['rows']] == [
        ('HK.00001', 'SELECTED'), ('HK.00002', 'NEAR_CONDITION')]
    assert result['candidate_count'] == 1
    assert result['pending_count'] == 1
    assert result['coverage'] == ledger['coverage']
    assert result['input_identity'] == ledger['decision_identity']
    assert result['decision_ledger_ref'] == 'research_attention.research_selection'
    assert result['formal_selection_input'] is False
    assert result['as_of_claim'] == 'NONE_RETROSPECTIVE_RESEARCH'
    assert value == before


def test_strict_rows_without_original_research_priority_remain_unresolved():
    screen, _ = _fixture()
    result = channel(workspace(screen, []))
    assert result['status'] == 'PARTIAL'
    assert result['rows'] == []
    assert result['candidate_count'] is None
    assert result['pending_count'] == 3
    assert result['coverage']['excluded_count'] == 1


@pytest.mark.parametrize('broken', ['missing_ledger', 'wrong_target', 'wrong_source', 'wrong_decisions'])
def test_raw_screen_never_substitutes_for_missing_or_mismatched_ledger(broken):
    screen, cards = _fixture()
    value = workspace(screen, cards)
    ledger = value['research_attention']['research_selection']
    if broken == 'missing_ledger':
        value['research_attention'] = {}
    elif broken == 'wrong_target':
        ledger['target_trade_date'] = '20261005'
    elif broken == 'wrong_source':
        ledger['source_input_identity'] = 'f' * 64
    else:
        ledger['decisions'][0]['decision_reason'] = 'changed after original owner projection'
    result = channel(value)
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['candidate_count'] is None
    assert result['rows'] == []


@pytest.mark.parametrize('state', ['NOT_RUN', 'PENDING_SLOT', 'FAILED'])
def test_unrun_or_failed_screen_is_unknown_even_with_empty_lists(state):
    screen = dict(status=state, strict=[], near=[], pending=[], screen_unresolved=[], excluded=[])
    result = channel(workspace(screen, []))
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['source_status'] == state
    assert result['candidate_count'] is None
    assert result['pending_count'] is None
    assert result['input_identity'] is None


def test_complete_original_exclusion_is_a_valid_empty_research_selection():
    screen, _ = _fixture()
    screen.update(status='READY', strict=[], near=[], pending=[], cards=[], gaps=[])
    screen['coverage'].update(input_candidate_count=1, history_complete_count=1,
        history_pending_count=0, strict_count=0, near_candidate_count=0, selected_count=0,
        excluded_count=1, screen_unresolved_count=0, row_accounted_count=1)
    # R2 requires the same archive boundary that a post-save owner read emits.
    # The real save/GET counterpart lives in test_manager_three_lane_owner_readback_r2.
    from v4.manager_research.workspace import ATTEMPT_SCHEMA, seal_attempt
    value = workspace(screen, [])
    value['input_identity'] = '8'*64
    value['plan_product'] = dict(status='CURRENT',consumed=True,run_id='a'*32,sha256='b'*64,
        original_owner='ManagerResearchJobService.refresh_workspace_plan',
        generated_at='2026-10-02T08:00:00+08:00',execution_kind='MANUAL_REFRESH')
    value['workspace_plan_attempt'] = seal_attempt(dict(schema_version=ATTEMPT_SCHEMA,
        target_trade_date=TARGET,run_id='a'*32,owner='ManagerResearchJobService.refresh_workspace_plan',
        state='SUCCEEDED_EMPTY',execution_kind='MANUAL_REFRESH',input_identity=value['input_identity'],
        started_at='2026-10-02T08:00:00+08:00',finished_at='2026-10-02T08:00:00+08:00',
        failure_reasons=[],**FLAGS))
    result = channel(value)
    assert result['status'] == 'READY_EMPTY'
    assert result['candidate_count'] == 0
    assert result['pending_count'] == 0
    assert result['coverage']['excluded_count'] == 1
    assert result['rows'] == []


def test_source_paths_hashes_priority_and_original_row_locations_survive_summary():
    screen, cards = _fixture()
    result = channel(workspace(screen, cards))
    row = result['rows'][0]
    assert row['source_refs'] == screen['strict'][0]['source_refs']
    assert row['source_group'] == 'strict'
    assert row['source_row_indexes'] == [1]
    assert row['research_priority']['priority_rank'] == 1
    assert row['decision_reason_code'] == 'ORIGINAL_STRICT_TWO_GATE_PASSED'


def test_display_diagnostics_do_not_change_the_original_selection_ledger_identity():
    screen, cards = _fixture()
    before = build_research_selection_ledger(screen, cards, TARGET)
    screen['pending'][0].update(
        missing_prior60_dates=['20260825', '20260826', '20260827'],
        missing_previous5_dates=['20260925'], duplicate_prior60_dates=[], duplicate_previous5_dates=[],
        volume_source='V4_SHARED_HK_0_2_PANEL_AUTHORITY', volume_unit_status='NOT_PROVEN',
        history_numeric_status='PARTIAL_UNKNOWN',
        volume_provenance=dict(unit_status='NOT_PROVEN', gaps=['VOLUME_UNIT_OR_SCALE_NOT_PROVEN']))
    ledger = build_research_selection_ledger(screen, cards, TARGET)
    pending = next(row for row in ledger['decisions'] if row['symbol'] == 'HK.00003')
    assert pending['decision_status'] == 'UNRESOLVED'
    assert ledger == before
    screen['strict'][0].update(volume_source='ORIGINAL_VERIFIED_SOURCE',
        volume_unit_status='NOT_PROVEN',volume_provenance=dict(unit_status='NOT_PROVEN'))
    result = channel(workspace(screen, cards))
    assert result['rows'][0]['source_diagnostics']['volume_source'] == 'ORIGINAL_VERIFIED_SOURCE'
    assert result['input_diagnostics_ref'] == 'rebound_input_diagnostics'


HK_DATE = '20261009'
STAGE = 'STAGE_0935_0940'


def hk_workspace():
    """Synthetic response at the existing verified-reader boundary."""
    source = dict(source_date=HK_DATE, market='HK_CONNECT', role='HK_CONNECT_FULL_MARKET_AUTHORITY', sha256='a'*64)
    codes = ['HK.00001', 'HK.00002', 'HK.00999']
    membership = dict(status='OWNER_VERIFIED', target_trade_date=HK_DATE, codes=codes, source=source,
        membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
        identity=digest([HK_DATE, codes, source['sha256']]), gaps=[],
        calendar_applicability=dict(status='APPLICABLE', target_trade_date=HK_DATE))
    rows = [dict(code=code, name='Synthetic '+code, rank=rank, order=index+1,
        formal_eligible=False, action_level='NO_BUY', trade_status='WATCH_ONLY',
        lane_evidence=['ORIGINAL_FOUR_LANE_EVIDENCE'], source_mode='HK_CONNECT_STAGE')
        for index, (code, rank) in enumerate([('HK.00002', 2), ('HK.00001', 1)])]
    market = dict(trade_date=HK_DATE, stage_id=STAGE, market='HK_CONNECT',
        status='READY', selection_status='READY', source_status='READY',
        run_id='run-'+'b'*24, artifact_id='selection-'+'b'*24,
        selection_run_id='run-'+'b'*24, algorithm_id='ORIGINAL_ALGORITHM', algorithm_sha256='c'*64,
        raw_artifact_sha256='d'*64, selection_manifest_receipt_verified=True,
        selection_artifact_sha256='e'*64, selection_manifest_sha256='f'*64, selection_receipt_sha256='1'*64,
        requested_rows=100, source_rows=100, selected_rows=2, coverage_ratio=0.02,
        missing_symbols=[], cannot_confirm=[], rows=rows,
        source_evidence=['hk_d1_membership=exact_date_top100', 'hk_d1_status=STRICT_0_2_READY',
                         'hk_d1_sha256='+'2'*64, 'hk_d1_json_sha256='+'2'*64])
    execution = dict(status='SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED',
        trade_date=HK_DATE, stage_id=STAGE, observed_sha256='3'*64, receipt_path='/synthetic/runner/receipt.json',
        natural_verified=False, execution_verified=False,
        markets={'HK_CONNECT':dict(selection_binding='BOUND_TO_VERIFIED_SELECTION', selected_rows=2,
            declared_identity={key:market[key] for key in ('run_id','artifact_id','algorithm_sha256','raw_artifact_sha256')})})
    stage = dict(schema_version='stage_center.selection_consumer.v1', response_source='SHARED_STAGE_CENTER',
        trade_date=HK_DATE, stage_id=STAGE, selection_markets={'HK_CONNECT':market},
        execution_evidence=execution, write_performed=False, **FLAGS)
    return dict(target_trade_date=HK_DATE,
        date_bindings=dict(plan_date=HK_DATE, selection_date=HK_DATE, announcement_date='20261008'),
        plan_context=dict(plan_trade_date=HK_DATE, research_cutoff='2026-10-09T10:00:00+08:00'),
        selection_diagnostics=dict(status='READY', membership=membership, connect_gaps=[]),
        owner_chain=dict(focus_inputs=dict(status='READY', gaps=[])), stage_selection=stage,
        focus_symbols=['HK.00999'],
        stocks=[dict(symbol='HK.00999',name='Unrelated focus',connect_eligibility='VERIFIED_TARGET_UNIVERSE',why_watch=['not Stage'])])


def test_hk_consumes_original_stage_order_and_selection_identity_instead_of_workspace_focus():
    value = hk_workspace(); before = deepcopy(value)
    result = channel(value, 'HK_CONNECT')
    assert result['owner'] == 'StageSelectionConsumer/SelectionStore'
    assert [row['symbol'] for row in result['rows']] == ['HK.00002', 'HK.00001']
    assert [row['rank'] for row in result['rows']] == [2, 1]
    assert result['status'] == 'READY' and result['candidate_count'] == 2
    assert result['natural_run_verified'] is False
    assert result['run_id'] is None  # No saved plan was fabricated for this read.
    for row in result['rows']:
        assert row['formal_eligible'] is False and row['action_level'] == 'NO_BUY'
        ref = row['source_refs'][0]
        assert ref['run_id'] == 'run-'+'b'*24
        assert ref['payload_sha256'] == 'e'*64
        assert ref['receipt_sha256'] == '1'*64
        assert ref['raw_artifact_sha256'] == 'd'*64
    assert value == before


@pytest.mark.parametrize('broken', ['missing_stage', 'date', 'stage', 'trio', 'run', 'd1_sha',
    'd1_status', 'source_failed', 'membership', 'duplicate', 'duplicate_rank', 'empty_status',
    'cutoff', 'backfill', 'prior', 'replay', 'symbol_conflict', 'row_preselect', 'row_waiting',
    'row_reference_lane', 'execution_recovery', 'execution_backfill_id', 'row_order', 'row_production'])
def test_hk_unverified_or_recovery_source_never_falls_back_to_focus(broken):
    value = hk_workspace(); stage = value['stage_selection']; market = stage['selection_markets']['HK_CONNECT']
    if broken == 'missing_stage': value.pop('stage_selection')
    elif broken == 'date': market['trade_date'] = '20261008'
    elif broken == 'stage': market['stage_id'] = 'STAGE_0925'
    elif broken == 'trio': market.pop('selection_receipt_sha256')
    elif broken == 'run': market['selection_run_id'] = 'run-'+'f'*24
    elif broken == 'd1_sha': market['source_evidence'].append('hk_d1_binding_sha256='+'9'*64)
    elif broken == 'd1_status': market['source_evidence'].remove('hk_d1_status=STRICT_0_2_READY')
    elif broken == 'source_failed': market['source_status'] = 'CANNOT_CONFIRM'
    elif broken == 'membership': value['selection_diagnostics']['membership']['status'] = 'CANNOT_CONFIRM'
    elif broken == 'duplicate': market['rows'][1]['code'] = market['rows'][0]['code']
    elif broken == 'duplicate_rank': market['rows'][1]['rank'] = market['rows'][0]['rank']
    elif broken == 'empty_status': market['status'] = market['selection_status'] = 'READY_EMPTY'
    elif broken == 'cutoff': value['plan_context']['research_cutoff'] = '2026-10-09T09:30:00+08:00'
    elif broken == 'backfill': market['selection_mode'] = 'BACKFILL'
    elif broken == 'prior': market['source_evidence'].append('hk_d1_binding_mode=PRIOR_CONNECT_DATE_FALLBACK')
    elif broken == 'symbol_conflict': market['rows'][0].update(code='HK.00888', symbol='HK.00002')
    elif broken == 'row_preselect': market['rows'][0]['source_mode'] = 'HK_CONNECT_D1_PRESELECT_REFERENCE'
    elif broken == 'row_waiting': market['rows'][0]['second_filter_status'] = 'WAITING_0920_SECOND_FILTER'
    elif broken == 'row_reference_lane': market['rows'][0]['candidate_lanes'] = ['D1_PRESELECT_REFERENCE']
    elif broken == 'execution_recovery': stage['execution_evidence']['recovery_mode'] = 'HISTORICAL_BACKFILL'
    elif broken == 'execution_backfill_id': stage['execution_evidence']['backfill_run_id'] = 'original-backfill-run'
    elif broken == 'row_order': market['rows'][0]['order'] = True
    elif broken == 'row_production': market['rows'][0]['production_allowed'] = True
    else: stage['execution_evidence']['due_status'] = 'LATE_CATCHUP_REPLAY'
    result = channel(value, 'HK_CONNECT')
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['candidate_count'] is None and result['rows'] == []
    assert result['gaps']


def test_hk_valid_zero_requires_original_full_input_and_matching_selection_receipt():
    value = hk_workspace(); stage = value['stage_selection']; market = stage['selection_markets']['HK_CONNECT']
    market.update(status='READY_EMPTY', selection_status='READY_EMPTY', rows=[], selected_rows=0)
    stage['execution_evidence']['markets']['HK_CONNECT']['selected_rows'] = 0
    result = channel(value, 'HK_CONNECT')
    assert result['status'] == 'READY_EMPTY' and result['candidate_count'] == 0
    market.update(requested_rows=0, source_rows=0)
    result = channel(value, 'HK_CONNECT')
    assert result['status'] != 'READY_EMPTY' and result['candidate_count'] is None


def test_hk_selection_and_execution_are_separate_and_unbound_execution_is_partial():
    value = hk_workspace()
    value['stage_selection'].pop('execution_evidence')
    result = channel(value, 'HK_CONNECT')
    assert result['status'] == 'PARTIAL' and result['candidate_count'] == 2
    assert 'HK_STAGE_EXECUTION_SELECTION_BINDING_UNVERIFIED' in result['gaps']
    assert result['natural_run_verified'] is False
    assert len(result['rows']) == 2


def three_lane_workspace():
    """Synthetic values at the three original, already-verified read boundaries."""
    value = hk_workspace()
    screen, cards = _fixture()
    screen.update(target_trade_date=HK_DATE, verified_session='20261008')
    for group in ('strict', 'near', 'pending', 'excluded', 'screen_unresolved'):
        for row in screen[group]:
            row.update(target_monday=int(HK_DATE), verified_session=20261008)
    value['market_screen'] = screen
    value['research_attention'] = dict(research_selection=build_research_selection_ledger(screen, cards, HK_DATE))
    value['announcement_reviewed_analysis'] = dict(products=[dict(
        target_trade_date=HK_DATE, publication_date='2026-10-08', status='CONSUMED',
        selection_status='VERIFIED', stock_count=1, selected_stock_count=1,
        conditional_watch_count=0, not_selected_stock_count=0,
        not_assessed_stock_count=0, product_sha256='4'*64,
        source_manifest_sha256='6'*64,
        evidence_run_id='5'*32, owner_available_at='2026-10-09T09:20:00+08:00', gaps=[])],
        research_references=[dict(target_trade_date=HK_DATE, publication_date='2026-10-08',
            stock_code='HK.00003', stock_name='Synthetic reviewed announcement',
            research_status='SELECTED', selection_reasons=['Original reviewed reason'],
            product_sha256='4'*64, source_manifest_sha256='6'*64,
            article_refs=[dict(owner='original-announcement-owner', payload_sha256='7'*64)])])
    return value


@pytest.mark.parametrize('missing', ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'])
def test_missing_one_owner_does_not_erase_other_legal_channels_or_invent_zero(missing):
    value = three_lane_workspace()
    expected = {row['channel']:row for row in build_daily_channels(value)['channels']}
    assert [expected[name]['candidate_count'] for name in ('ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD')] == [1, 2, 1]
    value.pop({'ANNOUNCEMENT':'announcement_reviewed_analysis', 'HK_CONNECT':'stage_selection',
               'OVERSOLD':'research_attention'}[missing])
    before = deepcopy(value)
    actual = {row['channel']:row for row in build_daily_channels(value)['channels']}
    assert actual[missing]['status'] == 'CANNOT_CONFIRM'
    assert actual[missing]['candidate_count'] is None and actual[missing]['pending_count'] is None
    assert actual[missing]['rows'] == []
    for name in set(expected)-{missing}:
        assert actual[name] == expected[name]
    assert value == before


@pytest.mark.parametrize('broken', ['target', 'publication', 'consumption'])
def test_announcement_requires_original_exact_date_consumed_product(broken):
    value = three_lane_workspace()
    product = value['announcement_reviewed_analysis']['products'][0]
    key, changed = {'target':('target_trade_date','20261012'),
        'publication':('publication_date','2026-10-09'), 'consumption':('status','NOT_CONSUMED')}[broken]
    product[key] = changed
    result = channel(value, 'ANNOUNCEMENT')
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['candidate_count'] is None and result['rows'] == []
