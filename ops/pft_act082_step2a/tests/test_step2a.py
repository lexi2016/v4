"""Unit-level Stage 2A controls. Synthetic fixtures are never attestations."""

from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import os
import stat

import pytest

from ops.pft_act080_core.core import Bar
from ops.pft_act082_step2a.calendar import (
    ExchangeCalendar, LabelUnavailable, build_labels, validate_purge, verify_actual_intervals, DEV_END,
)
from ops.pft_act082_step2a.evidence import canonical_json, evidence_payload
from ops.pft_act082_step2a.pipeline import (
    _mutate_future_only, diagnostics_by_stock, require_prepared_source, temporal_diagnostic,
)
from ops.pft_act082_step2a.render import PANELS, draw_panel, png_chunks
from ops.pft_act082_step2a.reviewer_vault import validate_review_channel, _observations_allowed, _scan_json
from ops.pft_act082_step2a.sampling import (
    B2_INITIAL, B3_EXPAND, B3_SHRINK, Candidate, group_frame, sample_frame, private_rows,
)
from ops.pft_act082_step2a.vault import (
    AES_MAGIC, audit_access, require_sealed_provenance, seal_mapping, select_sealed, write_envelope,
)
from ops.pft_act082_step2a.waves import JUNDA, continuation_screen, vault_b_cooldown

SHA = "1" * 64


def session_range(start, count):
    day = date.fromisoformat(start)
    collected = []
    while len(collected) < count:
        if day.weekday() < 5:
            collected.append(day.isoformat())
        day += timedelta(days=1)
    return tuple(collected)


def make_bar(day, idx):
    price = 10 + idx / 100
    return Bar(day, price, price + .07, price - .04, price + .02, 1_000 + .5 * idx)


def make_candidate(day, **kwargs):
    return Candidate("000010.SZ", "raw-wave", day, **kwargs)


def test_official_purge_calendar_exact_25():
    days = tuple(x for x in session_range("2025-09-30", 33) if not "2025-10-01" <= x <= "2025-10-08")
    cals = {market: ExchangeCalendar(market, days, SHA) for market in ("SH", "SZ", "BJ")}
    gap = validate_purge(cals)
    assert len(gap) == 25
    assert (gap[0], gap[-1]) == ("2025-10-09", "2025-11-12")
    wrong = dict(cals, SZ=ExchangeCalendar("SZ", tuple(x for x in days if x != "2025-10-21"), SHA))
    with pytest.raises(ValueError, match="purge calendar"):
        validate_purge(wrong)


def test_actual_label_dates_defer_suspended_but_refuse_missing():
    dates = session_range("2025-08-01", 45)
    bars = {day: make_bar(day, idx) for idx, day in enumerate(dates) if idx != 4}
    point = make_candidate(dates[3], mother_start_date=dates[0])
    cal = ExchangeCalendar("SZ", dates, SHA)
    with pytest.raises(LabelUnavailable, match="unconfirmed"):
        build_labels(point, bars, cal, frozenset())
    actual = build_labels(point, bars, cal, {dates[4]}, outcomes=True)
    assert actual["label_start_date"] == dates[5]
    assert actual["label_end_date_actual"] == dates[24]
    assert actual["t5_net"] == pytest.approx(bars[dates[9]].close / bars[dates[5]].open - 1.003)
    assert verify_actual_intervals([actual])["actual_information_intersections"] == 0
    with pytest.raises(ValueError, match="forbidden boundary"):
        verify_actual_intervals([dict(actual, label_end_date_actual="2025-10-09", t20_actual_date="2025-10-09",
                                      max_drawdown_t20_close_end_date="2025-10-09")])
    with pytest.raises(LabelUnavailable, match="outside DEV"):
        build_labels(make_candidate(dates[34], mother_start_date=dates[20]), bars, cal, frozenset())


def fake_frame():
    points = []
    for i in range(40):
        stock = f"{i:06}.SZ"
        for j in range(25):
            group = f"{i}/{j}"
            base = Candidate(stock, group, "2024-12-17", "2024-12-16", source_rule="RAW")
            after = Candidate(stock, group, "2025-01-02", "2024-12-16", source_rule="LATER")
            ongoing = Candidate(stock, group, "2025-01-03", "2024-12-16", source_rule="CONT")
            points += [(base, ()), (after, ("A", "C", B2_INITIAL)), (ongoing, (B3_SHRINK, B3_EXPAND))]
    return points


def test_d_first_probability_cut_not_filtered_by_coverage_or_cooldown():
    points = fake_frame()
    draw = sample_frame(group_frame(points))
    reordered = sample_frame(group_frame(reversed(points)))
    assert draw == reordered
    picked, pairs = private_rows(draw)
    assert len(picked) == 260 and len({row["wave_group_id"] for row in picked}) == 260
    assert len({row["blind_id"] for row in picked} | {p["relabel_blind_id"] for p in pairs}) == 300
    assert max(Counter(row["security_id"] for row in picked[:240]).values()) <= 8
    assert [row["stratum_probability"] for row in picked[:240] if row["bucket"] == "D"] == ["3/25"] * 120
    assert {row["selection_rule"] for row in picked[:240] if row["bucket"] == "D"} == {"RAW"}
    assert len({p["first_blind_id"] for p in pairs}) == 40
    assert Counter(row["batch"] for row in picked if row["agreement_audit_preregistered"]) == dict.fromkeys(range(1, 9), 3)
    assert Counter(row["coverage_subtype"] for row in picked[:240] if row["bucket"] == "B") == {
        B2_INITIAL: 20, B3_SHRINK: 10, B3_EXPAND: 10,
    }
    assert Counter(row["coverage_subtype"] for row in picked[240:] if row["bucket"] == "B") == {
        B2_INITIAL: 3, B3_SHRINK: 1, B3_EXPAND: 1,
    }
    selected = {row["coverage_subtype"]: row["D"] for row in picked if row["coverage_subtype"]}
    assert selected == {B2_INITIAL: "2025-01-02", B3_SHRINK: "2025-01-03", B3_EXPAND: "2025-01-03"}


def test_small_positive_continuation_accepts_both_relative_volume_paths_only_after_bull_launch():
    launch = Bar("2025-01-02", 10.0, 11.2, 9.8, 11.0, 1000)
    smaller = Bar("2025-01-03", 11.0, 11.3, 10.7, 11.2, 900)
    enlarged = Bar("2025-01-06", 11.0, 11.3, 10.7, 11.2, 1250)
    bearish = Bar("2025-01-03", 11.0, 11.3, 10.6, 10.7, 900)
    assert continuation_screen(smaller, launch) == B3_SHRINK
    assert continuation_screen(enlarged, launch) == B3_EXPAND
    assert continuation_screen(bearish, launch) is None
    assert continuation_screen(smaller, None) is None


def test_stock_diagnostics_are_disjoint_and_temporal_early_end_crossing_is_purged():
    stocks = [f"{i:06}.SZ" for i in range(40)]
    assigned = diagnostics_by_stock(stocks)
    assert assigned == diagnostics_by_stock(reversed(stocks))
    assert Counter(assigned.values()) == dict.fromkeys(range(1, 6), 8)
    assert temporal_diagnostic({
        "mother_start_date": "2024-07-01", "D": "2024-09-30", "label_end_date_actual": "2024-10-11",
    }) == ("PURGED_FROM_TEMPORAL_SPLIT_DIAGNOSTIC", True)
    assert temporal_diagnostic({
        "mother_start_date": "2024-10-01", "D": "2024-10-02", "label_end_date_actual": "2024-10-23",
    }) == ("RECENT_DIAGNOSTIC", False)
    assert temporal_diagnostic({
        "mother_start_date": "2024-07-01", "D": "2024-08-01", "label_end_date_actual": "2024-08-27",
    }) == ("DEV_EARLY", False)


def test_label_maximum_close_drawdown_observes_t20_endpoint():
    dates = session_range("2025-07-01", 33)
    day, closes = dates[2], [10., 12., 11., 9., 11.] + [10.] * 15
    bars = {d: Bar(d, 10, max(10, price) + .5, min(10, price) - .5, price, 1000)
            for d, price in zip(dates[2:23], [10., *closes], strict=True)}
    c = make_candidate(day, mother_start_date=dates[0])
    r = build_labels(c, bars, ExchangeCalendar("SZ", dates, SHA), set(), outcomes=True)
    assert r["max_drawdown_t20_close"] == -0.25
    assert r["max_drawdown_t20_close_end_date"] == r["label_end_date_actual"] == dates[22]


def test_prepared_source_drift_aborts():
    from ops.pft_act082_step2a.pipeline import _sources_sha

    applied_hash = _sources_sha()
    assert require_prepared_source({"source_code_sha256": applied_hash}) == applied_hash
    with pytest.raises(ValueError, match="prepared source code hash mismatch"):
        require_prepared_source({"source_code_sha256": "0" * 64})


def test_render_and_lock_reject_drift_before_creating_output_directories(tmp_path):
    from ops.pft_act082_step2a.lock_local import lock_dev
    from ops.pft_act082_step2a.pipeline import VAULT_B
    from ops.pft_act082_step2a.reviewer_vault import render_dev

    stage = tmp_path / "stage"
    private = stage / VAULT_B
    private.mkdir(parents=True)
    (private / "PRE_RENDER_LOCK.json").write_bytes(canonical_json({"source_code_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="prepared source code hash mismatch"):
        render_dev(stage)
    with pytest.raises(ValueError, match="prepared source code hash mismatch"):
        lock_dev(stage, tmp_path / "unused")
    assert set(stage.iterdir()) == {private}


def test_execution_gap_is_downstream_only_and_preserves_strict_gt5():
    a, b, c = [make_candidate(day, mother_start_date="2025-01-01")
               for day in ("2025-01-02", "2025-01-09", "2025-01-10")]
    same = Candidate(a.security_id, "other-wave", a.D, "2025-01-01")
    vals = vault_b_cooldown([(a, 0), (same, 0), (b, 5), (c, 6)])
    assert [vals[x]["exec_cooldown_isolated"] for x in (a, same, b, c)] == [True, False, False, True]
    assert vals[same]["exec_cooldown_reason"] == "DUPLICATE_SAME_DAY"
    assert vals[b]["exec_cooldown_reason"] == "COOLDOWN_LE5"
    assert vals[c]["exec_cooldown_gap_sessions"] == 6


def visual_case():
    sessions = session_range("2023-01-02", 402)
    D = "2024-06-12"
    week = ("2024-06-10", "2024-06-11", "2024-06-12", "2024-06-13", "2024-06-14")
    sessions = tuple(day for day in sessions if day != week[0])
    bars = tuple(make_bar(day, i) for i, day in enumerate(sessions) if day not in (week[1], "2024-06-07"))
    cal = ExchangeCalendar("SZ", sessions, SHA)
    point = make_candidate(D, mother_start_date=bars[170].trade_date,
                           root_dates=(bars[170].trade_date,))
    return bars, point, cal, {week[1]}


def test_weekly_partial_keeps_true_volume_and_separates_suspension_and_missing():
    bars, point, cal, stopped = visual_case()
    e = evidence_payload(bars, point, cal, stopped)
    assert len(e["daily_focus"]) == 36
    assert (e["wide_left_sessions"], len(e["daily_wide"])) == (240, 241)
    week = e["weekly"][-1]
    assert (week["elapsed"], week["scheduled"], week["observed"], week["suspended"], week["missing"]) == (2, 4, 1, 1, 0)
    assert week["partial"] and week["v"] == e["daily_wide"][-1]["v"]
    assert week["mean_v_per_elapsed_exchange_day"] == pytest.approx(week["v"] / 2)
    closed = e["weekly"][-2]
    assert not closed["partial"] and closed["missing"] == 1 and closed["week_status"] == "CLOSED_GAPPED"
    assert e["brick_reference"] == "UNVERIFIED_CLASSROOM_VERSION_REFERENCE_ONLY"
    assert all(k in e["daily_focus"][-1] for k in ("W", "Y", "K", "D_signal", "J"))


def test_numeric_and_all_png_bytes_invariant_to_cut_and_future_mutation():
    pytest.importorskip("PIL")
    bars, point, cal, stopped = visual_case()
    cut = tuple(b for b in bars if b.trade_date <= point.D)
    mutated = _mutate_future_only(bars, point.D)
    assert mutated != bars and mutated[:len(cut)] == cut
    states = [evidence_payload(b, point, cal, stopped) for b in (bars, cut, mutated)]
    assert len({canonical_json(e) for e in states}) == 1
    for panel in PANELS:
        versions = {draw_panel(e, panel) for e in states}
        assert len(versions) == 1
        assert set(png_chunks(next(iter(versions)))) == {b"IHDR", b"IDAT", b"IEND"}


@pytest.mark.parametrize("token", [
    '"trade": "000001.SH"', '"D": "2025-09-29"', '"t20_net": 0.5',
    '"selection_rule": "foo"', '"exec_cooldown_isolated": true', '"first_blind_id": "other"',
])
def test_review_leakage_scanner_catches_common_vectors(tmp_path, token):
    path = tmp_path / "test.json"
    path.write_text("{" + token + "}")
    with pytest.raises(ValueError, match="private/future"):
        _scan_json(path)


def test_review_channel_rejects_unencrypted_rerating_context(tmp_path):
    (tmp_path / "channel_a_relabel").mkdir()
    with pytest.raises(ValueError, match="raw channel A relabel"):
        validate_review_channel(tmp_path, locked_archive=True)


def test_review_numeric_allowlist_refuses_hidden_extra_field_or_strings():
    bars, point, cal, stopped = visual_case()
    e = evidence_payload(bars, point, cal, stopped)
    _observations_allowed(e)
    with pytest.raises(ValueError, match="unapproved anonymous"):
        _observations_allowed(dict(e, hidden="v"))
    changed = dict(e, daily_focus=[dict(row) for row in e["daily_focus"]])
    changed["daily_focus"][-1]["o"] = "中立"
    with pytest.raises(ValueError, match="non-anonymous numeric"):
        _observations_allowed(changed)


def profiles(n, prefix):
    return [{"security_id": f"{prefix + i:06}.SH", "asof": DEV_END,
             "market_cap": 100 + i, "volatility": .13 + i / 1000, "industry": str(i % 8)}
            for i in range(n)]


def test_sealed_selector_excludes_complete_exposure_and_rejects_future_profiles():
    dev = profiles(40, 600000)
    pool = dev + profiles(80, 610000)
    exposure = {row["security_id"] for row in dev} | {JUNDA, "610021.SH", "610059.SH"}
    selection = select_sealed(pool, dev, exposure)
    assert len(selection["rows"]) == 50
    assert Counter(row["stratum"] for row in selection["rows"]) == {"MAIN": 40, "HETEROGENEOUS": 10}
    assert not ({row["security_id"] for row in selection["rows"]} & exposure)
    with pytest.raises(ValueError, match="postcutoff"):
        select_sealed(pool + [dict(pool[-1], asof="2025-10-01")], dev, exposure)


def test_incomplete_sealed_provenance_fails_before_selection():
    receipt = {
        "exposure_complete": True, "official_calendar_verified": True, "frozen_all_a_qfq_verified": True,
        "precut_stratification_provenance_verified": True, "first_valid_stratum_source_date": DEV_END,
        "all_candidate_strata_max_source_date": DEV_END, "proven_precut_dev_profile_count": 40,
        "proven_precut_eligible_full_a_count": 50,
    }
    require_sealed_provenance(receipt)
    for incomplete in (
        dict(receipt, exposure_complete=False),
        dict(receipt, all_candidate_strata_max_source_date="2026-02-27"),
        dict(receipt, proven_precut_dev_profile_count=0),
        dict(receipt, proven_precut_eligible_full_a_count=49),
    ):
        with pytest.raises(ValueError, match="SEALED_BLOCKED"):
            require_sealed_provenance(incomplete)


def test_aes256_gcm_os_append_only_audit_and_no_png(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    private_keys = tmp_path / "keys"
    cipher = tmp_path / "sealed"
    mapping = {"example": "synthetic only, not a market mapping"}
    key = private_keys / "sealed.key"
    log = cipher / "ACCESS_AUDIT.jsonl"
    try:
        summary = seal_mapping(mapping, cipher, key)
        data = (cipher / "SEALED_OOT_V2_MAPPING.aesgcm").read_bytes()
        assert data.startswith(AES_MAGIC) and canonical_json(mapping) not in data
        assert sha256(data).hexdigest() == summary["ciphertext_sha256"]
        assert summary["sealed_png_count"] == 0 and audit_access(log)["OOT_OPEN_COUNT"] == 0
        assert len(key.read_bytes()) == 32 and stat.S_IMODE(key.stat().st_mode) == 0o600
        i = len(AES_MAGIC)
        # Opens a synthetic fixture to verify authenticated encryption, not a Stage 2A sealed population.
        value = AESGCM(key.read_bytes()).decrypt(data[i:i+12], data[i+12:], AES_MAGIC+b"SEALED_OOT_V2")
        assert value == canonical_json(mapping)
        with pytest.raises(OSError):
            log.write_text("illegal truncation")
        with pytest.raises(PermissionError):
            write_envelope(b"fixture", cipher / "bad.aesgcm", cipher / "wrong.key", "SYNTHETIC")
    finally:
        if log.exists():
            os.chflags(log, 0)

