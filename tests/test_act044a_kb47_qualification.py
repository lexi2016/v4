from ops.act044a_kb47_qualification import (
    f08_atom,
    happened_in_order,
    local_basis,
    qualify_b3,
    qualify_changan,
)


def test_f08_exact_endpoints_and_denominator_highest_close():
    # Long (7-1)/(9-1) = 75 and short (7-6.5)/(8.5-6.5) = 25.
    bars = [{'low': 1.0, 'close': 9.0, 'high': 91.0}] * 18
    bars += [{'low': 6.5, 'close': 8.5, 'high': 91.0},
             {'low': 6.5, 'close': 8.0, 'high': 92.0},
             {'low': 6.75, 'close': 7.0, 'high': 94.0}]
    assert f08_atom(bars) == (True, 75.0, 25.0)
    bars[-1]['close'] = 7.000001
    assert f08_atom(bars)[0] is False
    bars[-1]['close'] = 6.999999
    assert f08_atom(bars)[0] is False


def test_f08_missing_zero_denominator_and_window_cannot_be_false():
    flat = [{'low': 2.0, 'close': 2.0}] * 21
    assert f08_atom(flat) == (None, None, None)
    assert f08_atom(flat[:-1]) == (None, None, None)
    missing = [{'low': 1.0, 'close': 2.0}] * 20 + [{'low': None, 'close': 2.0}]
    assert f08_atom(missing)[0] is None


def test_b3_common_gate_and_branch_identity():
    assert qualify_b3(True, None, True) is True
    assert qualify_b3(None, True, True) is True
    assert qualify_b3(False, None, True) is None
    assert qualify_b3(False, False, True) is False
    assert qualify_b3(True, True, False) is False
    assert qualify_b3(True, None, None) is None


def test_changan_geometry_candidate_cannot_qualify():
    assert qualify_changan(True, None, True) == (None, 'CANDIDATE_ONLY')
    assert qualify_changan(True, None, False) == (False, 'CANDIDATE_ONLY')
    assert qualify_changan(True, False, True) == (False, 'CANDIDATE_ONLY')


def test_repair_clock_requires_same_identity_and_order_through_d():
    assert happened_in_order((1, 2, 3), True, 3) is True
    assert happened_in_order((1, 2, 3), False, 3) is False
    assert happened_in_order((1, 2, 4), True, 3) is False
    assert happened_in_order((1, 2, 2), True, 3) is False
    assert happened_in_order((1, 2, None), True, 3) is None
    assert happened_in_order((1, 2, 3), None, 3) is None


def test_segment_basis_gapped_effective_event_is_bounded_through_d():
    rows = [
        {'trade_date': i, 'D_ratio_hfq_segment': 1, 'D_bar_state': 'VALID_TDX_DAILY',
         'factor_known': True, 'D_close': 10.0, 'D_high': 12.0, 'D_low': 9.0, 'D_pre_close': 10.0}
        for i in [*range(1, 21), 22]
    ]
    rows[-1]['D_pre_close'] = 9.0
    snapshot = {'history_start_date': 1, 'event_coverage_complete': True, 'events': [
        {'ex_date': 21, 'a': 1.0, 'b': -1.0}, {'ex_date': 23, 'a': 1.0, 'b': -3.0},
    ]}
    basis, status = local_basis(rows, snapshot)
    assert status == 'ACT041A_EX_ACTION_D_BASIS_VERIFIED'
    assert basis[-1]['close'] == 10.0
    assert basis[-2]['close'] == 9.0
    rows[-1]['D_pre_close'] = 10.0
    assert local_basis(rows, snapshot) == (None, 'EFFECTIVE_PRE_CLOSE_LINK_UNVERIFIED')
