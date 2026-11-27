from datetime import date, timedelta
from hashlib import sha256
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from ops.pft_act080_core.anchors import KeyKDetector
from ops.pft_act080_core.core import Bar, Provenance
from ops.pft_act080_core.run import _compare

from ops.pft_act081_kb.chart import numeric_bars
from ops.pft_act081_kb.evaluate import attach_outcomes, nonoverlap, outcomes, screen_clean, summary
from ops.pft_act081_kb.features import (
    B1, B2, AnchorVolume, KnowledgeReplay, b1_checks, bearish_retracement, runup_and_zone,
)
from ops.pft_act081_kb.run import _cooldown_audit


def bar(idx, o=10, h=10.05, l=9.96, c=10, v=1000):
    return Bar((date(2010, 1, 1) + timedelta(days=idx)).isoformat(), o, h, l, c, v)


def signed(stock="000001.SZ"):
    return KnowledgeReplay(stock, Provenance("x", "y", "z"))


def test_b1_thresholds_and_board_inclusive_anchor():
    before = bar(0, 5, 5.02, 4.98, 5)
    values = {"W": 5, "Y": 5}
    anchor = SimpleNamespace(key_k_low=5)
    at2 = b1_checks("000001.SZ", bar(1, 5, 5.11, 4.99, 5.10), before, values, anchor, 1, 0.5)
    assert not at2["small_move"] and at2["active_anchor"] and at2["half_peak"]
    at4 = bar(1, 5, 5.1, 4.9, 5.0)
    assert not b1_checks("000001.SZ", at4, before, values, anchor, 45, 0.5)["small_range"]
    for stock in ("300101.SZ", "301101.SZ", "688101.SH"):
        assert all(b1_checks(stock, at4, before, values, anchor, 45, 0.5).values())
        at7 = bar(1, 5, 5.2, 4.85, 5.0)
        assert not b1_checks(stock, at7, before, values, anchor, 45, 0.5)["small_range"]
    assert not b1_checks("000001.SZ", at4, before, values, anchor, 0, 0.5)["active_anchor"]
    assert not b1_checks("000001.SZ", at4, before, values, anchor, 46, 0.5)["active_anchor"]
    assert not b1_checks("000001.SZ", at4, before, values, anchor, 45, 0.50001)["half_peak"]


def test_peak_depth_and_fast_half_stay_causal():
    peak = AnchorVolume(0, 1000)
    assert peak.advance(0, bar(0, v=1000)) == (1001, None, None)
    assert peak.advance(1, bar(1, 10, 10.05, 9.95, 9.99, 600)) == (1001 / 601, 0.6, None)
    assert peak.advance(2, bar(2, v=1000))[1:] == (1.0, None)
    assert peak.advance(3, bar(3, v=500))[1:] == (0.5, True)
    assert peak.advance(4, bar(4, v=1300))[1:] == (1.3, True)
    assert peak.advance(5, bar(5, v=660))[1:] == (660 / 1300, None)
    for day in (6, 7):
        assert peak.advance(day, bar(day, v=660))[2] is (None if day == 6 else False)
    assert peak.advance(8, bar(8, v=100))[2] is False


def test_warning_and_position_exact_boundaries():
    up = bar(0, 10, 10.7, 9.99, 10.6, 1000)
    down = bar(1, 10.7, 10.8, 10.3, 10.31, 750)
    assert bearish_retracement(up, down, True)
    assert not bearish_retracement(up, down, False)
    assert not bearish_retracement(up, bar(1, 10.7, 10.8, 10.3, 10.31, 749), True)
    assert not bearish_retracement(up, bar(1, 10.8, 10.9, 10.6, 10.61, 750), True)
    assert runup_and_zone(13.5, [10] * 60)[1] == "LOW_FIRST_WAVE"
    assert runup_and_zone(13.500001, [10] * 60)[1] == "MID"
    assert runup_and_zone(18, [10] * 60)[1] == "HIGH_RUNUP"
    assert runup_and_zone(18, [10] * 59) == (None, None)


def test_gap_up_bearish_or_doji_breakout_is_not_prior_bull_volume():
    for opened in (10.8, 10.6, 10.5):
        detector = KeyKDetector()
        for i in range(27):
            detector.advance(bar(i))
        previous = bar(27, opened, 10.90, 10.30, 10.60, 1000)
        assert "BREAKOUT" in detector.advance(previous)
        current = bar(28, 10.7, 10.8, 10.3, 10.31, 750)
        assert bearish_retracement(previous, current, True) == (opened < previous.close)


def test_shared_gap_and_first_role_on_real_episode():
    history = [bar(i) for i in range(114)]
    history.append(bar(114, 10, 10.5, 9.98, 10.45, 2000))
    history.extend(bar(i, 10.45, 10.49, 10.38, 10.45, 1000) for i in range(115, 133))
    days, events = signed().consume(history)
    launch, *quiet = events
    assert launch["track"] == B2 and launch["accepted_role"] == "FIRST"
    assert quiet and {row["track"] for row in quiet} == {B1}
    assert {row["structure_episode_id"] for row in quiet} == {launch["structure_episode_id"]}
    observed = {row["gap_trading_days"]: row["accepted_flag"] for row in quiet}
    assert [observed[gap] for gap in (4, 5, 6)] == [False, False, True]
    assert [row["accepted_role"] for row in quiet if row["accepted_flag"]][:2] == ["FIRST", "REPEAT"]
    assert _cooldown_audit(events)["cross_track_session_intersection"] == 0
    prefix, events_before = signed().consume(history[:120])
    parity = _compare(days[:120], prefix) + _compare([row for row in events if row["session_idx"] < 120], events_before)
    assert parity["cell_differences"] == parity["na_position_differences"] == 0


def event(n, stock="X"):
    return {"security_id": stock, "session_idx": n, "candidate_event_id": f"{stock}{n}",
            "structure_episode_id": f"e{stock}{n}", "D": str(n)}


def test_clean_overlap_new_20_vs_old_10_and_adjacent_intervals():
    rows = [event(i) for i in (80, 81, 100, 110, 111)] + [event(100, "Y")]
    clean, proof = screen_clean(rows, {"X": [("r", "100", 100)]}, B1)
    assert [r["session_idx"] for r in clean] == [80, 111, 100]
    assert [r["event_session_idx"] for r in proof] == [81, 100, 110]
    assert proof[0]["exclusion_reason"] == "HOLDING_20_VS_10_OVERLAP"
    assert proof[-1]["exclusion_reason"] == "D_PLUS_MINUS_10"
    assert [r["session_idx"] for r in nonoverlap([event(i) for i in (0, 19, 20, 39, 40)])] == [0, 20, 40]


def test_new_horizon_uses_d1_open_and_retains_unknown():
    p = (tuple(map(str, range(25))), (10,) * 25, (11,) * 25, (9.29,) * 25)
    values = outcomes(p, 2)
    assert values["entry_D"] == "3" and values["T20_D"] == "22"
    assert values["T20"] == pytest.approx(0.097)
    assert values["tail_std"] and not values["tail_aux"]
    assert outcomes(p, 5)["T20"] is None
    assert outcomes(p, 24)["T5"] is None


def test_plot_numeric_feed_has_no_identity_and_exact_appended_future_parity():
    history = [bar(i) for i in range(200)]
    shown = numeric_bars(history)[-61:]
    assert len(shown) == 61 and len(shown[0]) == 7 and all(isinstance(val, (float, int)) for val in shown[0])
    with_future = history + [bar(200, 30.0, 31.0, 29.0, 30.0, 1e7)]
    assert shown == numeric_bars(with_future)[139:200]


def test_attach_outcomes_passes_t20_to_estimator_and_retains_partition_cutoff():
    dates = tuple(bar(i).trade_date for i in range(25))
    data = (dates, (10,) * 25, (11,) * 25, (9.29,) * 25)
    row = dict(event(2), D=dates[2])
    attach_outcomes([row], {"X": data})
    assert summary([row])["T20_mean"] == pytest.approx(0.097)
    attach_outcomes([row], {"X": data}, cutoff_exclusive=dates[22])
    assert summary([row])["T20_unknown"] == 1
    assert summary([row])["T10_mature"] == 1
    row["D"] = dates[3]
    with pytest.raises(ValueError, match="observed stock ordinal"):
        attach_outcomes([row], {"X": data})



def test_signed_p1b_runtime_checks_actual_imported_config(tmp_path, monkeypatch):
    from ops.pft_act081_kb import run

    actual = run.imported_files("ops.pft_act080_core", run.P1B_MODULES)
    actual["config.json"] = run.P1B_CONFIG_PATH
    path = tmp_path / "signed_fixture.zip"
    with ZipFile(path, "w") as archive:
        sums = []
        for filename, source in actual.items():
            member = f"ops/pft_act080_core/{filename}"
            value = source.read_bytes()
            archive.writestr(member, value)
            sums.append(f"{sha256(value).hexdigest()}  {member}")
        archive.writestr("SHA256SUMS.txt", "\n".join(sums))
    verified, checksums = run.verify_p1b_runtime(path)
    assert verified == 7 and set(checksums) == set(actual)
    wrong_config = tmp_path / "config.json"
    wrong_config.write_text("{}")
    monkeypatch.setattr(run, "P1B_CONFIG_PATH", wrong_config)
    with pytest.raises(ValueError, match="SHA-256 mismatch: config.json"):
        run.verify_p1b_runtime(path)
