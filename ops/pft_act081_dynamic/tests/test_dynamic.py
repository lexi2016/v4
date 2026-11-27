"""Frozen gates and exact P1B identity behavior on synthetic histories."""

from datetime import date, timedelta

from ops.pft_act080_core.core import Bar, Cooldown
from ops.pft_act080_core.run import _compare
from ops.pft_act081_dynamic.replay import Mother, balance_checks, high_distribution, ordered_structure, replay, root_evidence
from ops.pft_act081_dynamic.run import check_cooldown, select_cohorts
from ops.pft_act081_dynamic.replay import CORE, STRICT
from ops.pft_act081_kb.features import B1, LEGACY

import pytest


def bar(i, op=100, close=100, volume=100, *, low=None, high=None):
    d = (date(2020, 1, 1) + timedelta(days=i)).isoformat()
    return Bar(d, op, max(op, close) + 0.2 if high is None else high, min(op, close) - 0.2 if low is None else low, close, volume)


def test_positive_single_and_reject_bearish_gap_up():
    history = [bar(i) for i in range(20)]
    assert root_evidence(history, bar(20, 101, 104, 200))[0] == "BULL_SINGLE"
    assert root_evidence(history, bar(20, 106, 104, 600)) is None
    assert root_evidence(history, bar(20, 99, 100, 600)) is None


def test_stack_uses_pre_cluster_volume_and_formation_minimum():
    history = [bar(i) for i in range(20)]
    history += [bar(20, 99.5, 100.3, 150), bar(21, 100, 101, 150)]
    today = bar(22, 100.7, 102, 150)
    evidence = root_evidence(history, today)
    assert evidence[0] == "BULL_STACK"
    wave = Mother.create("000001.SZ", 22, evidence)
    assert wave.floor == history[-2].low
    assert wave.bull_peak == 150
    assert wave.start_D != wave.day


def test_gentle_positive_uses_direction_and_volume_not_doji():
    history = [bar(0)]
    history += [bar(i, 100, 101, 25) for i in range(1, 6)]
    history += [bar(i, 101, 100, 30) for i in range(6, 10)]
    assert root_evidence(history, bar(10, 100, 101, 25))[0] == "GENTLE_RED_FAT"
    assert root_evidence(history, bar(10, 100, 101, 1)) is None
    assert root_evidence(history, bar(10, 101, 101, 10000)) is None


def test_mother_floor_equality_age_and_abnormal_pullback():
    anchor = bar(6, 103, 106, 200, low=100)
    wave = Mother.create("000001.SZ", 6, ("BULL_SINGLE", [anchor]))
    at_floor = bar(51, 101, 101, 10, low=100)
    assert wave.invalidation(51, at_floor, anchor, 1.0, False) == ""
    assert wave.invalidation(52, at_floor, anchor, 1.0, False) == "ANCHOR_EXPIRED"
    breached = bar(10, 103, 105, 10, low=99)
    assert wave.invalidation(10, breached, anchor, 1.0, False) == "ANCHOR_LOW_BREACHED"
    pullback = bar(11, 106, 104, 150, low=103)
    assert wave.invalidation(11, pullback, anchor, 1.0, False) == "S1_ABNORMAL_BEAR_PULLBACK"


def test_high_volume_wick_and_dark_candle_distribution():
    history = [bar(i, 100, 101, 100, low=99, high=103) for i in range(20)]
    assert high_distribution(history, bar(20, 101, 102, 200, high=106, low=100), 1.0)
    assert high_distribution(history, bar(20, 103, 100, 200, high=104, low=99), 1.0)
    assert not high_distribution(history, bar(20, 101, 102, 199, high=106, low=100), 1.0)


def test_dynamic_price_and_volume_are_strict_only_where_defined():
    history = [bar(i, 100, 100, 20, high=101, low=99) for i in range(10)]
    mother = Mother.create("000001.SZ", 0, ("BULL_SINGLE", [bar(0, 100, 101, 100)]))
    normal = bar(10, 100, 100.2, 75, high=100.8, low=99.3)
    criteria, mean = balance_checks(history, normal, 1, 100, 100, mother)
    assert mean == 2 and all(criteria.values())
    same_volume = bar(10, 100, 100.2, 100, high=100.8, low=99.3)
    criteria, _ = balance_checks(history, same_volume, 1, 100, 100, mother)
    assert not criteria["D_VOLUME_BELOW_TRUE_BULL_PEAK"]
    chase = bar(10, 100, 100.9, 35, high=101, low=99.9)
    criteria, _ = balance_checks(history, chase, 1, 100, 100, mother)
    assert not criteria["D_BODY_CONTRACTION"] and not criteria["D_NO_PRICE_PULSE_CHASE"]


def test_clear_two_leg_downshift_and_flat_platform():
    earlier = [bar(i, 100, 100) for i in range(5)]
    falling = [bar(i, 98, 98) for i in range(5, 10)]
    assert not ordered_structure(earlier + falling, 1.0)
    assert ordered_structure(earlier + [bar(i) for i in range(5, 10)], 1.0)


def test_future_shock_does_not_move_root_or_old_features():
    history = [bar(i, 100, 100) for i in range(125)]
    history += [bar(125, 101, 105, 250, low=100)]
    history += [bar(i, 102, 102, 30, high=102.2, low=101.8) for i in range(126, 136)]
    prior, events = replay("000001.SZ", history)
    future, future_events = replay("000001.SZ", [*history, bar(136, 104, 101, 250, low=98)])
    for old, now in ((prior, future[:len(prior)]), (events, [row for row in future_events if row["session_idx"] < len(prior)])):
        assert _compare(old, now)["cell_differences"] == 0
    assert prior[-1]["key_k_date"] == history[125].trade_date
    assert future[-1]["last_mother_end_reason"] == "ANCHOR_LOW_BREACHED"


def test_independent_cooldown_rolls_across_new_mother_and_strict_no_refill():
    clock = Cooldown()
    rows = []
    spec = [(10, "old", True, "FIRST"), (15, "new", True, None), (16, "new", False, "FIRST"),
            (22, "new", True, "REPEAT")]
    for idx, episode, strict, role in spec:
        rows.append({
            "security_id": "000001.SZ", "session_idx": idx, "structure_episode_id": episode, **clock.consider(idx, 1),
            "accepted_role": role, "strict_first_hit": strict and role == "FIRST", "strict_eligible_pre_cooldown": strict,
        })
    result = check_cooldown(rows)
    assert result["conservation_delta"] == 0 and result["rejected_gap_5"] == 1 and result["accepted_gap_6"] == 2
    rows[-1]["strict_first_hit"] = True
    with pytest.raises(ValueError, match="STRICT escaped"):
        check_cooldown(rows)


def test_clean_screen_no_replacement_and_zero_residual():
    def event(i, strict=False, stock="000001.SZ"):
        return {
            "security_id": stock, "structure_episode_id": str(i), "candidate_event_id": str(i),
            "D": bar(i).trade_date, "session_idx": i, "strict_first_hit": strict, "fold": "OOT",
        }
    core = [event(10, True), event(52), event(60, True), event(65, True, "002865.SZ")]
    refs = {"000001.SZ": [("R", bar(29).trade_date, 29)]}
    clean, junda, flow, proof = select_cohorts(core, [], [], refs, {})
    assert not clean[B1] and not clean[LEGACY]
    assert [row["session_idx"] for row in clean[CORE]] == [52, 60]
    assert [row["session_idx"] for row in clean[STRICT]] == [60]
    assert len(junda[CORE]) == 1 and len(proof) == 2
    assert flow[CORE]["residual_matches"] == 0
