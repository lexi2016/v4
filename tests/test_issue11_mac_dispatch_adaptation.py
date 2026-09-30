"""Synthetic dispatch tests against the exact Mac-only branches; no real recovery."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from ops import run_stage_center_nodes as nodes
from test_issue11_a_auction_recovery import case, DATE, STAGE, NOW, canonical


def test_public_repair_keeps_mac_late_observation_annotation(case):
    case.cfg.pop('_issue11_explicit_request', None)
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE,
        status='LATE_CATCHUP_REPLAY', scheduled_at=NOW.replace(hour=9, minute=25))
    case.runner.due_decisions = lambda *args, **kwargs: [decision]
    result = nodes.run_nodes(case.cfg, trade_date=DATE, evaluated_at=NOW,
                             explicit_node=STAGE, runner=case.runner)
    assert result['nodes'][0]['repair_recovery_attempt_count'] == 1
    assert len(case.calls) == 1
    assert case.calls[0].same_day_late_observation_recovery is True


@pytest.mark.parametrize('change,expected_calls', [
    ('none', 1), ('exhausted', 0), ('other_error', 0), ('already_hk_rows', 0),
    ('natural', 0), ('wrong_day', 0), ('unsafe', 0), ('wrong_outcome', 0)])
def test_mac_settled_partial_branch_keeps_original_budget_and_scope(case, change, expected_calls):
    for key in ('a_0925_recovery_authorization', 'a_0925_recovery_authorization_sha256', '_issue11_explicit_request'):
        case.cfg.pop(key, None)
    receipt = deepcopy(case.old)
    receipt.update(node_id=STAGE, dispatch_mode='RECOVERY', status='PARTIAL_WITH_ROWS',
                   node_outcome='SETTLED_PARTIAL', node_attempt_count=1, retry_exhausted=False)
    receipt['markets']['A_SHARE']['selected_rows'] = 10
    receipt['markets']['HK_CONNECT'] = dict(market='HK_CONNECT', status='CANNOT_CONFIRM',
        source_status='CANNOT_CONFIRM', selection_status='CANNOT_CONFIRM', selected_rows=0,
        write_performed=False, cannot_confirm=['HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE'])
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status='LATE_CATCHUP_REPLAY',
                               scheduled_at=NOW.replace(hour=9, minute=25))
    if change == 'exhausted': receipt['node_attempt_count'] = 3
    if change == 'other_error': receipt['markets']['HK_CONNECT']['cannot_confirm'] = ['OTHER']
    if change == 'already_hk_rows': receipt['markets']['HK_CONNECT']['selected_rows'] = 10
    if change == 'wrong_day': decision.trade_date = '20260929'
    if change == 'unsafe': receipt['orders_sent'] = True
    if change == 'wrong_outcome': receipt['node_outcome'] = 'SETTLED'
    case.path.write_bytes(canonical(receipt))
    case.runner.due_decisions = lambda *args, **kwargs: [decision]
    def run_one(d):
        assert d.same_day_late_observation_recovery is True
        case.calls.append(d)
        return {**receipt, 'write_performed': True}
    case.runner._run_one = run_one
    result = nodes._dispatch_stage(case.cfg, DATE, STAGE, NOW,
        mode='NATURAL' if change == 'natural' else 'RECOVERY', runner=case.runner)
    assert len(case.calls) == expected_calls
    if expected_calls:
        assert result['node_attempt_count'] == 2
        assert result['markets']['A_SHARE']['selected_rows'] == 10
        assert 'repair_recovery_attempt_count' not in result
    else:
        assert result['status'] == 'SKIPPED_ALREADY_SETTLED'
    assert not (case.path.parent/'a_0925_issue11_recovery.json').exists()
