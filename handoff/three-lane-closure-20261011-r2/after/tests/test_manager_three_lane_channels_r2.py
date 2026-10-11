"""Projection accounting regressions; synthetic validated-reader boundaries only."""
from copy import deepcopy

import pytest

from test_manager_three_lane_channels_r1 import channel, three_lane_workspace, workspace
from test_manager_research_selection_ledger import _fixture


def announcement_value():
    value = three_lane_workspace()
    product = value['announcement_reviewed_analysis']['products'][0]
    product.update(stock_count=1, selected_stock_count=1, conditional_watch_count=0,
                   not_selected_stock_count=0, not_assessed_stock_count=0)
    return value


def test_unmapped_original_selected_identity_never_becomes_valid_zero():
    value = announcement_value()
    reference = value['announcement_reviewed_analysis']['research_references'][0]
    reference.update(stock_code='H5354', risk_notes=['Original risk assessment'])
    before = deepcopy(value)
    result = channel(value, 'ANNOUNCEMENT')
    assert result['status'] == 'PARTIAL'
    assert result['candidate_count'] is None
    assert result['rows'] == []
    assert result['unmapped_references'][0]['stock_code'] == 'H5354'
    assert result['unmapped_references'][0]['risk_notes'] == ['Original risk assessment']
    assert 'ANNOUNCEMENT_SELECTED_REFERENCE_ACCOUNTING_MISMATCH' in result['gaps']
    assert value == before


def test_mapped_result_and_risks_survive_an_unmapped_result():
    value = announcement_value()
    reviewed = value['announcement_reviewed_analysis']
    reviewed['products'][0].update(stock_count=2, selected_stock_count=2)
    reviewed['research_references'][0]['risk_notes'] = ['Original mapped risk']
    extra = deepcopy(reviewed['research_references'][0]); extra['stock_code'] = 'H5354'
    reviewed['research_references'].append(extra)
    result = channel(value, 'ANNOUNCEMENT')
    assert result['status'] == 'PARTIAL' and result['candidate_count'] == 1
    assert result['rows'][0]['symbol'] == 'HK.00003'
    assert result['rows'][0]['risk_notes'] == ['Original mapped risk']
    assert result['reference_accounting'][0]['expected_selected_count'] == 2
    assert result['reference_accounting'][0]['projected_selected_count'] == 1


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'negative', 'boolean', 'sum', 'unknown_count'])
def test_incomplete_or_invalid_owner_accounting_never_claims_complete(defect):
    value = announcement_value(); reviewed = value['announcement_reviewed_analysis']
    product = reviewed['products'][0]
    if defect == 'missing': reviewed['research_references'] = []
    elif defect == 'duplicate': reviewed['research_references'] *= 2
    elif defect == 'negative': product['selected_stock_count'] = -1
    elif defect == 'boolean': product['selected_stock_count'] = True
    elif defect == 'sum': product['stock_count'] = 2
    else: product.pop('selected_stock_count')
    result = channel(value, 'ANNOUNCEMENT')
    assert result['status'] == 'PARTIAL'
    assert len(result['rows']) <= 1
    if not result['rows']: assert result['candidate_count'] is None
    assert result['gaps']


def test_complete_nonempty_owner_exclusions_still_allow_zero():
    value = announcement_value(); reviewed = value['announcement_reviewed_analysis']
    reviewed['products'][0].update(selected_stock_count=0, not_selected_stock_count=1)
    reviewed['research_references'] = []
    result = channel(value, 'ANNOUNCEMENT')
    assert result['status'] == 'READY_EMPTY' and result['candidate_count'] == 0
    assert result['pending_count'] == 0 and result['gaps'] == []


def test_unarchived_oversold_exclusion_is_not_a_completed_zero():
    screen, _ = _fixture()
    screen.update(status='READY', strict=[], near=[], pending=[], cards=[], gaps=[])
    screen['coverage'].update(input_candidate_count=1, history_complete_count=1,
        history_pending_count=0, strict_count=0, near_candidate_count=0, selected_count=0,
        excluded_count=1, screen_unresolved_count=0, row_accounted_count=1)
    result = channel(workspace(screen, []))
    assert result['status'] == 'PARTIAL' and result['candidate_count'] is None
    assert result['coverage']['excluded_count'] == 1
    assert result['run_id'] is None
    assert 'OVERSOLD_RESULT_NOT_ARCHIVED' in result['gaps']
