"""Eight contract checks with synthetic data and concrete state/identity oracles."""

import csv
from datetime import date, timedelta
from hashlib import sha256
from io import StringIO
import pickle

import pytest

from ops.pft_act080_core.anchors import ANCHOR_TAGS, KeyKDetector
from ops.pft_act080_core.archive import Chain, _chain_bars
from ops.pft_act080_core.core import Bar, Indicators, Provenance, ReplayState
from ops.pft_act080_core.run import _audit_stock, compare_replays, replay_all, write_csv
from ops.pft_act080_core.split import split_evidence


SECURITY = "000058.SZ"
SOURCE = Provenance("a" * 64, "b" * 64, "c" * 64)


def _bar(day, close=10.0, volume=100.0):
    return Bar(day, close, close + 0.1, close - 0.1, close, volume)


def _event(day, arm="A", security=SECURITY):
    return sha256(f"ACT080_P1_V1|CANDIDATE|{security}|{day}|{arm}".encode("ascii")).hexdigest()


def _simple_bars(count):
    return [_bar((date(2024, 2, 1) + timedelta(days=i)).isoformat()) for i in range(count)]


def _inject_arms(monkeypatch, arms_by_date, tags_by_date=None, geometry_by_date=None):
    compute = Indicators.advance
    if tags_by_date is None:
        tags_by_date = {min(arms_by_date): ("VIOLENT", "FUNDING_ACTIVITY")}
    if geometry_by_date is None:
        geometry_by_date = {}

    def indicator(self, bar):
        w, y, gap_atr = geometry_by_date.get(bar.trade_date, (8.0, 7.0, 0.5))
        return {**compute(self, bar), "W": w, "Y": y, "wy_opening_atr": gap_atr, "_fixture_D": bar.trade_date}

    def arms(values):
        return arms_by_date.get(values["_fixture_D"], ())

    def tags(self, bar):
        return tags_by_date.get(bar.trade_date, ())

    monkeypatch.setattr(Indicators, "advance", indicator)
    monkeypatch.setattr(KeyKDetector, "advance", tags)
    monkeypatch.setattr("ops.pft_act080_core.core.qualified_arms", arms)


def _detect_from(bars):
    detector = KeyKDetector()
    return [detector.advance(bar) for bar in bars]


def _verify_anchor_formulas():
    baseline = _simple_bars(31)
    spike = Bar(baseline[27].trade_date, 10.2, 10.6, 10.0, 10.5, 200)
    assert _detect_from([*baseline[:27], spike])[-1] == ANCHOR_TAGS
    assert "BREAKOUT" not in _detect_from([*baseline[:26], Bar(baseline[26].trade_date, 10.2, 10.6, 10.0, 10.5, 200)])[-1]
    second_spike = Bar(baseline[28].trade_date, 10.7, 11.2, 10.5, 11.1, 190)
    assert "BREAKOUT" not in _detect_from([*baseline[:27], spike, second_spike])[-1]
    at_vol_floor = Bar(spike.trade_date, 10.2, 10.6, 10.0, 10.5, 80)
    assert "BREAKOUT" not in _detect_from([*baseline[:27], at_vol_floor])[-1]
    at_high = Bar(spike.trade_date, 10.0, 10.1, 9.9, 10.1, 200)
    assert "BREAKOUT" not in _detect_from([*baseline[:27], at_high])[-1]
    invalid_flag = Bar(baseline[23].trade_date, 10, 10.1, 0, 10, 100)
    assert "BREAKOUT" not in _detect_from([*baseline[:23], invalid_flag, *baseline[24:27], spike])[-1]

    reversal = Bar(baseline[24].trade_date, 10.1, 10.4, 10.0, 10.35, 121)
    assert _detect_from([*baseline[:24], reversal])[-1] == ("REVERSAL",)
    equal_volume = Bar(reversal.trade_date, 10.1, 10.4, 10.0, 10.35, 120)
    assert _detect_from([*baseline[:24], equal_volume])[-1] == ()
    above_ma_yesterday = _bar(baseline[23].trade_date, 10.1)
    assert "REVERSAL" not in _detect_from([*baseline[:23], above_ma_yesterday, reversal])[-1]

    funding = _bar(baseline[1].trade_date, 10, 170)
    assert _detect_from([baseline[0], funding])[-1] == ("FUNDING_ACTIVITY",)
    no_volume_denominator = _bar(baseline[0].trade_date, 10, 0)
    assert _detect_from([no_volume_denominator, funding])[-1] == ()
    only_prev_volume = Bar(baseline[1].trade_date, 10.2, 10.6, 10.0, 10.5, 150)
    assert _detect_from([baseline[0], only_prev_volume])[-1] == ("VIOLENT", "FUNDING_ACTIVITY")
    prior = [_bar(baseline[i].trade_date, volume=volume) for i, volume in enumerate((40, 40, 40, 200))]
    only_ma5_volume = Bar(baseline[4].trade_date, 10.2, 10.6, 10.0, 10.5, 190)
    assert _detect_from([*prior, only_ma5_volume])[-1] == ("VIOLENT", "FUNDING_ACTIVITY")

def _run(state, bars, dates):
    return [
        (row["candidate_event_id"], row["gap_trading_days"], row["accepted_flag"], row["reject_reason"])
        for row in state.consume(bars)[0] if row["trade_date"] in dates
    ]


def _formula_fixture(count, start=date(2023, 7, 1)):
    bars = []
    for i in range(count):
        day = (start + timedelta(days=i)).isoformat()
        close = 10 + i / 1000
        if i % 13 == 0 or i == 113:
            bars.append(Bar(day, close, close + 0.52, close - 0.12, close + 0.5, 300))
        else:
            bars.append(Bar(day, close - 0.09, close + 0.13, close - 0.18, close, 50 + i % 5))
    return tuple(bars)


def test_01_strict_gap_4_5_6(monkeypatch):
    bars = _simple_bars(7)
    dates = [bars[i].trade_date for i in (0, 4, 5, 6)]
    _inject_arms(monkeypatch, {day: ("A",) for day in dates})
    rows = _run(ReplayState(SECURITY, SOURCE), bars, dates)
    assert rows == [
        (_event(dates[0]), None, True, ""),
        (_event(dates[1]), 4, False, "COOLDOWN_LE5"),
        (_event(dates[2]), 5, False, "COOLDOWN_LE5"),
        (_event(dates[3]), 6, True, ""),
    ]


def test_02_rejection_never_resets_cooldown(monkeypatch):
    bars = _simple_bars(13)
    _inject_arms(monkeypatch, {bar.trade_date: ("A",) for bar in bars})
    rows, _ = ReplayState(SECURITY, SOURCE).consume(bars)
    assert [row["candidate_event_id"] for row in rows if row["accepted_flag"]] == [
        _event(bars[i].trade_date) for i in (0, 6, 12)
    ]
    assert [
        (row["last_accepted_session_idx_before"], row["last_accepted_session_idx_after"], row["gap_trading_days"])
        for row in rows
    ] == [(None, 0, None)] + [(0, 0, i) for i in range(1, 6)] + [(0, 6, 6)] + [
        (6, 6, i) for i in range(1, 6)
    ] + [(6, 12, 6)]


def test_03_same_day_representative_and_input_order(monkeypatch):
    _verify_anchor_formulas()
    bars = _simple_bars(5)
    _inject_arms(
        monkeypatch,
        {bars[0].trade_date: ("A", "B", "C"), bars[4].trade_date: ("A", "B")},
        {bars[0].trade_date: ANCHOR_TAGS},
    )
    state = ReplayState(SECURITY, SOURCE)
    rows, features = state.consume(bars)
    assert [r["candidate_event_id"] for r in rows] == [
        _event(bars[i].trade_date, arm) for i, arm in ((0, "A"), (0, "B"), (0, "C"), (4, "A"), (4, "B"))
    ]
    assert [r["reject_reason"] for r in rows] == [
        "", "DUPLICATE_SAME_DAY", "DUPLICATE_SAME_DAY", "COOLDOWN_LE5", "DUPLICATE_SAME_DAY"
    ]
    assert [r["gap_trading_days"] for r in rows] == [None, 0, 0, 4, 4]
    assert state.session_idx == 4
    assert len({row["structure_episode_id"] for row in rows}) == 1
    assert all(row["anchor_primary_type"] == "BREAKOUT" and row["anchor_types"] == "|".join(ANCHOR_TAGS) for row in rows)
    assert all(row[f"anchor_{tag.lower()}"] for row in rows for tag in ANCHOR_TAGS)
    assert len(features) == len(rows) == 1 + 4
    for invalid in (bars[-1], bars[-2]):
        with pytest.raises(ValueError, match="repeated or out-of-order"):
            state.consume([invalid])


def test_04_cross_episode_and_security_cooldown(monkeypatch):
    bars = _simple_bars(19)
    bars[1] = _bar(bars[1].trade_date, bars[0].low)
    for i in range(2, len(bars)):
        bars[i] = _bar(bars[i].trade_date, 8.0)
    arms = {0: ("A",), 2: ("B",), 4: ("B",), 6: ("C",), 12: ("A", "B"), 18: ("B",)}
    _inject_arms(
        monkeypatch, {bars[i].trade_date: rule for i, rule in arms.items()},
        {bars[0].trade_date: ("VIOLENT", "FUNDING_ACTIVITY"), bars[2].trade_date: ("REVERSAL",)},
    )
    state = ReplayState(SECURITY, SOURCE)
    initial, _ = state.consume(bars[:2])
    assert state.episode.key_k_low == bars[1].close
    later, _ = state.consume(bars[2:])
    rows = initial + later
    assert rows[0]["structure_episode_id"] != rows[1]["structure_episode_id"]
    assert rows[1]["episode_start_reason"] == "AFTER_ANCHOR_LOW_BREAK"
    assert len({row["structure_episode_id"] for row in rows[1:]}) == 1
    assert rows[1]["key_k_date"] == bars[2].trade_date
    assert rows[1]["episode_role"] == "FIRST" and rows[1]["accepted_role"] is None
    assert rows[1]["reject_reason"] == "COOLDOWN_LE5"
    assert rows[1]["last_accepted_session_idx_before"] == rows[1]["last_accepted_session_idx_after"] == 0
    assert rows[2]["episode_role"] == "CONFIRM" and not rows[2]["accepted_flag"]
    assert [(r["session_idx"], r["accepted_role"]) for r in rows if r["accepted_flag"]] == [
        (0, "FIRST"), (6, "FIRST"), (12, "CONFIRM"), (18, "REPEAT")
    ]
    row = ReplayState("600000.SH", SOURCE).consume(bars[2:3])[0][0]
    assert row["candidate_event_id"] == _event(bars[2].trade_date, "B", "600000.SH")
    assert row["accepted_flag"] and row["gap_trading_days"] is None


def test_05_halt_missing_calendar_and_price_validity(monkeypatch):
    holidays = {"2024-01-01", "2024-01-02", "2024-01-03"}
    days = [(date(2023, 12, 14) + timedelta(days=i)).isoformat() for i in range(50)]
    bars = tuple(_bar(day, volume=0 if day == "2023-12-14" else 100) for day in days if day not in holidays)
    nonpositive = Bar(bars[1].trade_date, -0.2, 0.0, -0.3, -0.1, 100)
    bars = (bars[0], nonpositive, *bars[2:])
    _inject_arms(
        monkeypatch, {bar.trade_date: ("A",) for bar in bars},
        {bars[i].trade_date: ("FUNDING_ACTIVITY",) for i in (0, 2)},
    )
    rows, _ = ReplayState(SECURITY, SOURCE).consume(bars)
    assert rows[1]["session_idx"] == 2 and rows[1]["gap_trading_days"] == 2
    by_idx = {r["session_idx"]: r for r in rows}
    first_after = by_idx[days.index("2024-01-04") - len(holidays)]
    assert first_after["trade_date"] == "2024-01-04" and first_after["gap_trading_days"] == 6
    assert all(r["trade_date"] not in holidays and r["trade_date"] != nonpositive.trade_date for r in rows)
    assert any(r["trade_date"] == "2023-12-14" for r in rows)
    split_rows, boundaries = split_evidence(bars, rows)
    by_idx = {r["session_idx"]: r for r in split_rows}
    edge = boundaries[0]["first_on_or_after_obs_idx"]
    assert (boundaries[0]["observed_purge_sessions"], boundaries[0]["observed_embargo_sessions"]) == (10, 10)
    assert by_idx[edge - 10]["purge"] and not by_idx[edge - 11]["purge"]
    assert by_idx[edge + 9]["embargo"] and not by_idx[edge + 10]["embargo"]
    assert by_idx[edge + 10]["cross_period_episode"] and by_idx[edge + 10]["assigned_fold"] is None
    assert boundaries[1]["status"] == "NO_BARS_ON_OR_AFTER"
    header = "D,open,high,low,close,volume\n"
    duplicated = header + 2 * "2024-01-04,1,2,1,2,0\n"
    with pytest.raises(ValueError, match="repeated or out-of-order"):
        _chain_bars(SECURITY, duplicated.encode("ascii"))
    with pytest.raises(ValueError, match="invalid OHLC"):
        Bar("2024-01-04", float("inf"), 3, 1, 2, 0)

    sparse = tuple(_bar((date(2020, 1, 1) + timedelta(days=3 * i)).isoformat()) for i in range(125))
    arms = {bar.trade_date: ("A",) for bar in sparse}
    tags = {sparse[i].trade_date: ("FUNDING_ACTIVITY",) for i in (0, 123)}
    geometry = {bar.trade_date: (12.0, 13.0, -0.5) for bar in sparse}
    for i in (0, 60, 121, 122, 123, 124):
        geometry[sparse[i].trade_date] = (9.0, 10.2, -1.5)
    _inject_arms(monkeypatch, arms, tags, geometry)
    state = ReplayState(SECURITY, SOURCE)
    assert [row["session_idx"] for row in state.consume(sparse[:60])[0]] == [0]
    assert state.episode.last_maintenance_idx == 0
    assert state.consume(sparse[60:121])[0] == []
    assert state.episode.last_maintenance_idx == 60
    assert state.consume(sparse[121:123])[0] == [] and state.episode is None
    after_quiet, _ = state.consume(sparse[123:])
    assert after_quiet[0]["episode_start_reason"] == "AFTER_MAINTENANCE_EXPIRY"
    assert after_quiet[0]["gap_trading_days"] == 123

    spaced = _simple_bars(34)
    arms = {bar.trade_date: ("A",) for bar in spaced}
    tags = {spaced[i].trade_date: ("FUNDING_ACTIVITY",) for i in (0, 31)}
    _inject_arms(monkeypatch, arms, tags, {spaced[0].trade_date: (12.0, 13.0, -0.5)})
    aged, _ = ReplayState(SECURITY, SOURCE).consume(spaced)
    by_idx = {row["session_idx"]: row for row in aged}
    assert 0 not in by_idx and by_idx[1]["episode_role"] == "FIRST" and not by_idx[1]["episode_opened_D"]
    assert by_idx[29]["anchor_age_sessions"] == 29 and 30 not in by_idx
    assert by_idx[31]["episode_start_reason"] == "REPLACED_BY_NEW_KEY_K"
    assert by_idx[31]["structure_episode_id"] != by_idx[29]["structure_episode_id"]

def test_06_chunk_resume_and_output_partition(monkeypatch, tmp_path):
    bars = _formula_fixture(250)
    expected = ReplayState(SECURITY, SOURCE).consume(bars)
    state = ReplayState(SECURITY, SOURCE)
    joined = ([], [])
    start = 0
    for stop in (0, 13, 114, 198, 250):
        part = state.consume(bars[start:stop])
        for output, rows in zip(joined, part, strict=True):
            output.extend(rows)
        # This round trip stays in this process and uses its own trusted state bytes.
        state = pickle.loads(pickle.dumps(state))
        start = stop
    assert joined == expected and len(joined[0]) >= 10
    assert len({row["candidate_event_id"] for row in joined[0]}) == len(joined[0])
    monkeypatch.setattr("ops.pft_act080_core.run.CSV_CAP_BYTES", 32)
    values = [{"value": "测试" * i} for i in range(1, 5)]
    files = write_csv(tmp_path, "test", ("value",), values)
    assert [part["rows"] for part in files] == [2, 1, 1]
    restored = []
    for part in files:
        data = (tmp_path / part["name"]).read_bytes()
        assert len(data) == part["bytes"] <= 32 and sha256(data).hexdigest() == part["sha256"]
        restored.extend(csv.DictReader(StringIO(data.decode("utf-8"))))
    assert restored == values


def test_07_serial_equals_18_configured_processes():
    chains = [Chain(f"{i:06}.SZ", _formula_fixture(256), SOURCE) for i in range(18, 0, -1)]
    serial = replay_all(chains, 1)
    parallel = replay_all(chains, 18)
    proof = compare_replays(parallel, serial)
    assert len(serial) == len(parallel) == 18 and all(r["ledger"] for r in parallel)
    for result in parallel:
        accepted, rejected, _ = _audit_stock(result)
        assert len(accepted) + len(rejected) == len(result["ledger"])
    assert {r["pid"] for r in serial}.isdisjoint(r["pid"] for r in parallel)
    assert proof["cells_compared"] > 0
    assert {k: v for k, v in proof.items() if k != "cells_compared"} == {
        "row_count_difference": 0, "field_set_differences": 0,
        "na_position_differences": 0, "cell_differences": 0,
    }


def test_08_future_prefix_no_business_field_or_na_difference():
    bars = _formula_fixture(257)
    full = ReplayState(SECURITY, SOURCE).consume(bars)
    modified = tuple(_bar(bar.trade_date, 300.0, 0.0) for bar in bars[180:])
    changed = ReplayState(SECURITY, SOURCE).consume((*bars[:180], *modified))
    print_checks = []
    for stop in (114, 128, 159, 180):
        short = ReplayState(SECURITY, SOURCE).consume(bars[:stop])
        for short_rows, full_rows, changed_rows in zip(short, full, changed, strict=True):
            target = [r for r in full_rows if r["session_idx"] < stop]
            stress = [r for r in changed_rows if r["session_idx"] < stop]
            assert short_rows == target == stress and target
            for left, right in zip(short_rows, target, strict=True):
                assert [k for k, v in left.items() if v is None] == [k for k, v in right.items() if v is None]
                assert all(v.hex() == right[k].hex() for k, v in left.items() if type(v) is float)
        print_checks.append((stop, len(short[0])))
    first = full[1][0]
    assert first["trade_date"] == bars[113].trade_date
    assert first["Y"] is not None and first["Y_slope"] is None and first["wy_opening_slope"] is None
    assert first["anchor_age_sessions"] == 0 and first["key_k_low"] == bars[113].low
    weight, decay, t = 2 / 11, 9 / 11, 113
    expected_w = decay**t * bars[0].close * (1 + weight * t) + weight**2 * sum(
        (t - i + 1) * decay ** (t - i) * bars[i].close for i in range(1, t + 1)
    )
    assert first["W"] == pytest.approx(expected_w, rel=1e-12)
    print(f"prefix_bars_ledger_rows={print_checks} field_differences=0 numeric_error=0 na_position_differences=0")
