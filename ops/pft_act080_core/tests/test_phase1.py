"""Eight contract checks with synthetic data and concrete state/identity oracles."""

import csv
from datetime import date, timedelta
from hashlib import sha256
from io import StringIO
import pickle

import pytest

from ops.pft_act080_core.archive import Chain, _chain_bars
from ops.pft_act080_core.core import Bar, Indicators, Provenance, ReplayState
from ops.pft_act080_core.run import compare_replays, replay_all, write_csv
from ops.pft_act080_core.split import split_evidence


SECURITY = "000058.SZ"
SOURCE = Provenance("a" * 64, "b" * 64, "c" * 64)


def _bar(day, close=10.0, volume=100.0):
    return Bar(day, close, close + 0.1, close - 0.1, close, volume)


def _event(day, arm="A", security=SECURITY):
    return sha256(f"ACT080_P1_V1|CANDIDATE|{security}|{day}|{arm}".encode("ascii")).hexdigest()


def _simple_bars(count):
    return [_bar((date(2024, 2, 1) + timedelta(days=i)).isoformat()) for i in range(count)]


def _inject_arms(monkeypatch, arms_by_date):
    compute = Indicators.advance

    def indicator(self, bar):
        return {**compute(self, bar), "_fixture_D": bar.trade_date}

    def arms(values):
        return arms_by_date.get(values["_fixture_D"], ())

    monkeypatch.setattr(Indicators, "advance", indicator)
    monkeypatch.setattr("ops.pft_act080_core.core.qualified_arms", arms)


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
        if i % 13 == 0:
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
    bars = _simple_bars(5)
    _inject_arms(monkeypatch, {bars[0].trade_date: ("A", "B", "C"), bars[4].trade_date: ("A", "B")})
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
    assert len(features) == len(rows) == 1 + 4
    for invalid in (bars[-1], bars[-2]):
        with pytest.raises(ValueError, match="repeated or out-of-order"):
            state.consume([invalid])


def test_04_cross_episode_and_security_cooldown(monkeypatch):
    bars = _simple_bars(19)
    for i in range(2, len(bars)):
        bars[i] = _bar(bars[i].trade_date, 8.0)
    arms = {0: ("A",), 2: ("B",), 4: ("B",), 6: ("C",), 12: ("A", "B"), 18: ("B",)}
    _inject_arms(monkeypatch, {bars[i].trade_date: rule for i, rule in arms.items()})
    rows, _ = ReplayState(SECURITY, SOURCE).consume(bars)
    assert rows[0]["structure_episode_id"] != rows[1]["structure_episode_id"]
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
    days = [(date(2023, 12, 10) + timedelta(days=i)).isoformat() for i in range(50)]
    bars = tuple(_bar(day, volume=0 if day == "2023-12-14" else 100) for day in days if day not in holidays)
    nonpositive = Bar(bars[1].trade_date, -0.2, 0.0, -0.3, -0.1, 100)
    bars = (bars[0], nonpositive, *bars[2:])
    _inject_arms(monkeypatch, {bar.trade_date: ("A",) for bar in bars})
    rows, _ = ReplayState(SECURITY, SOURCE).consume(bars)
    assert rows[1]["session_idx"] == 2 and rows[1]["gap_trading_days"] == 2
    by_idx = {r["session_idx"]: r for r in rows}
    unavailable_date = days.index("2024-01-04")
    assert by_idx[unavailable_date - len(holidays)]["trade_date"] == "2024-01-04"
    assert by_idx[unavailable_date - len(holidays)]["gap_trading_days"] == 4
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
    assert joined == expected and len(joined[0]) > 15
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
    for stop in (14, 79, 114, 180):
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
    assert first["trade_date"] == bars[13].trade_date
    assert first["Y"] is None and first["Y_slope"] is None and first["wy_opening"] is None
    weight, decay, t = 2 / 11, 9 / 11, 13
    expected_w = decay**t * bars[0].close * (1 + weight * t) + weight**2 * sum(
        (t - i + 1) * decay ** (t - i) * bars[i].close for i in range(1, t + 1)
    )
    assert first["W"] == pytest.approx(expected_w, rel=1e-12)
    print(f"prefix_bars_ledger_rows={print_checks} field_differences=0 numeric_error=0 na_position_differences=0")
