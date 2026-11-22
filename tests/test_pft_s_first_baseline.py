from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import hashlib
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import pft_s_first_baseline as baseline
from ops import pft_s_structure_features as structure


def _history(code: str, target: str, *, zero_on_target: bool = False, bars: int = 65) -> list[dict[str, object]]:
    end = date(int(target[:4]), int(target[4:6]), int(target[6:8]))
    rows = []
    for offset in range(bars - 1, -1, -1):
        day = (end - timedelta(days=offset)).strftime("%Y%m%d")
        zero = zero_on_target and offset == 0
        rows.append({
            "trade_date": day,
            "ts_code": code,
            "exchange": code.rsplit(".", 1)[1],
            "market_type": "A",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.1,
            "vol": 0 if zero else 1000 + offset,
            "bbi": 9.9,
            "zge_white_line": 10.2,
            "zge_yellow_line": 9.8,
            "ma60": 9.7,
        })
    return rows


def _fake_panel(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]) -> None:
    @contextmanager
    def bound(_root: Path):
        yield Path("/synthetic/backtest.parquet"), {
            "asof_date": "20261120",
            "generation_id": "synthetic-generation",
            "input_sha256": "a" * 64,
            "backtest": {"path": "/synthetic/backtest.parquet", "panel_sha256": "b" * 64},
            "selector": {"path": "/synthetic/selector.parquet", "panel_sha256": "c" * 64},
        }, lambda: None

    monkeypatch.setattr(baseline, "bind_current_panels", bound)
    monkeypatch.setattr(
        baseline,
        "_panel_rows",
        lambda *_args, **_kwargs: (rows, {
            "trade_date": "trade_date", "ts_code": "ts_code", "exchange": "exchange",
            "market_type": "market_type", "open": "open", "high": "high", "low": "low",
            "close": "close", "vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
            "zge_yellow_line": "zge_yellow_line", "ma60": "ma60",
        }),
    )


def _gate_rows() -> list[dict[str, object]]:
    rows = _history("000001.SZ", "20261120", bars=65)
    for row in rows[:-1]:
        row.update(open=9.9, high=10.0, low=9.5, close=10.0, vol=100.0,
                   zge_white_line=10.1, zge_yellow_line=9.8)
    rows[-1].update(open=9.9, high=10.5, low=9.5, close=10.0, vol=100.0,
                    zge_white_line=10.1, zge_yellow_line=9.8)
    return rows


def _gate(rows: list[dict[str, object]]) -> dict[str, object]:
    return baseline._inference_gate(rows, target_date="20261120")


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_g1_requires_white_strictly_above_yellow() -> None:
    rows = _gate_rows()
    rows[-1]["zge_white_line"] = 9.8
    rows[-1]["zge_yellow_line"] = 9.8
    equal = _gate(rows)
    assert equal["G1_signed_white_minus_yellow"] == 0.0
    assert equal["G1_pass"] is False
    assert equal["gate_would_veto"] is True
    assert equal["gate_hard_prediction"] == "FALSE"

    rows[-1]["zge_white_line"] = 9.800001
    above = _gate(rows)
    assert above["G1_pass"] is True
    assert above["gate_would_veto"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("zge_white_line", None, "MISSING_G1_WHITE_OR_YELLOW_LINE"),
        ("zge_yellow_line", "not-a-number", "INVALID_G1_WHITE_OR_YELLOW_LINE"),
        ("zge_white_line", 0.0, "INVALID_G1_WHITE_OR_YELLOW_LINE"),
    ],
)
def test_missing_or_invalid_g1_line_becomes_preflight_gap(
    field: str, value: object, reason: str,
) -> None:
    case = {
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }
    rows = _history("000001.SZ", "20261120", bars=65)
    rows[-1][field] = value

    examples, gaps, unknown_exclusions, _feature_names = baseline._build_examples(
        [case], rows,
        {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
         "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"},
        start_date="20260801",
    )

    assert examples == []
    assert unknown_exclusions == []
    assert gaps[0]["reason"] == reason


def test_g2_branch_1_includes_exact_35_percent_boundary() -> None:
    rows = _gate_rows()
    rows[-1].update(open=13.0, high=13.5, low=12.0, close=13.5,
                    zge_white_line=11.0, zge_yellow_line=10.0)

    gate = _gate(rows)

    assert gate["G2_close_yellow_pct"] == pytest.approx(0.35)
    assert gate["G2_branch_results"]["G2_CLOSE_YELLOW_GE_35"] is True
    assert gate["gate_would_veto"] is True


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("exact", True),
        ("close_below", False),
        ("wick_below", False),
        ("volume_below", False),
    ],
)
def test_g2_branch_2_has_inclusive_boundaries_for_all_three_conditions(change: str, expected: bool) -> None:
    rows = _gate_rows()
    for row in rows[-6:-1]:
        row["vol"] = 100.0
    rows[-1].update(open=12.5, high=12.9, low=12.0, close=12.5, vol=150.0,
                    zge_white_line=11.0, zge_yellow_line=10.0)
    if change == "close_below":
        rows[-1]["close"] = 12.499999
    elif change == "wick_below":
        rows[-1]["high"] = 12.899999
    elif change == "volume_below":
        rows[-1]["vol"] = 149.999

    gate = _gate(rows)

    assert gate["G2_branch_results"]["G2_CLOSE_YELLOW_GE_25_WICK_GE_4_VR5_GE_1_5"] is expected
    assert gate["gate_would_veto"] is expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [("exact", True), ("drawdown_above", False), ("amplitude_below", False)],
)
def test_g2_branch_3_has_inclusive_drawdown_and_amplitude_boundaries(change: str, expected: bool) -> None:
    rows = _gate_rows()
    rows[-1].update(open=7.8, high=8.2, low=7.4, close=7.8, vol=100.0,
                    zge_white_line=10.1, zge_yellow_line=9.8)
    if change == "drawdown_above":
        rows[-1]["close"] = 7.800001
    elif change == "amplitude_below":
        rows[-1]["low"] = 7.400001

    gate = _gate(rows)

    assert gate["G2_branch_results"]["G2_DRAWDOWN_LE_MINUS_22_AMPLITUDE_GE_8"] is expected
    assert gate["gate_would_veto"] is expected


def test_identity_only_preflight_reports_coverage_and_never_fits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_path = _write_csv(
        tmp_path / "case_keys.csv",
        "security_id,master_episode_group,D,source_views",
        ["688121.SH,episode-1,20261029,manual_review"],
    )
    _fake_panel(monkeypatch, _history("688121.SH", "20261029", zero_on_target=True, bars=65))
    monkeypatch.setattr(baseline, "_fit_and_materialize", lambda *_a, **_k: pytest.fail("identity preflight fit"))

    report = baseline.preflight(
        data_root=tmp_path,
        cases_path=cases_path,
        start_date="20260801",
        asof_date="20261120",
    )

    assert report["status"] == "PREFLIGHT_IDENTITY_ONLY"
    assert report["fit_status"] == "NOT_RUN_PREFLIGHT_ONLY"
    assert report["coverage"]["joint_labels_present"] is False
    assert report["coverage"]["cases"] == 1
    assert report["coverage"]["input_gap_case_count"] == 0
    assert len(report["coverage"]["zero_volume_D_case_ids"]) == 1


def test_zero_volume_unknown_is_visible_but_does_not_block_labeled_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "security_id,master_episode_group,D,overall_s_label,partition,exposure_status",
        [
            "000001.SZ,g1,20261120,TRUE,train,manual",
            "000002.SZ,g2,20261120,FALSE,train,manual",
            "000003.SZ,g3,20261120,TRUE,validation,manual",
            "000004.SZ,g4,20261120,FALSE,validation,manual",
            "688121.SH,g5,20261029,UNKNOWN,validation,zero_volume_unknown",
        ],
    )
    rows = []
    for code in ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"):
        rows.extend(_history(code, "20261120"))
    rows.extend(_history("688121.SH", "20261029", zero_on_target=True))
    _fake_panel(monkeypatch, rows)

    report = baseline.preflight(
        data_root=tmp_path,
        cases_path=cases_path,
        start_date="20260801",
        asof_date="20261120",
    )

    assert report["status"] == "PREFLIGHT_READY_UNSIGNED"
    assert report["coverage"]["input_gap_case_count"] == 0
    assert report["coverage"]["unknown_case_count"] == 1
    assert len(report["coverage"]["zero_volume_D_case_ids"]) == 1
    assert report["partition_policy"]["validation_development_exposed"] is True


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([
            "000001.SZ,g1,20261101,TRUE,train,manual",
            "000002.SZ,g1,20261102,UNKNOWN,validation,manual",
        ], "EPISODE_CROSSES_PARTITIONS"),
        ([
            "000001.SZ,g1,20261101,TRUE,train,manual",
            "000001.SZ,g2,20261102,UNKNOWN,validation,manual",
        ], "SECURITY_CROSSES_PARTITIONS"),
    ],
)
def test_partition_leakage_is_rejected_even_when_other_label_is_unknown(
    tmp_path: Path, rows: list[str], expected: str,
) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "security_id,master_episode_group,D,overall_s_label,partition,exposure_status",
        rows,
    )
    with pytest.raises(baseline.BaselineError, match=expected):
        baseline._read_cases(cases_path, start_date="20261101", asof_date="20261120")


def test_optional_worklist_case_id_is_preserved(tmp_path: Path) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "case_id,security_id,master_episode_group,D,overall_s_label,partition,exposure_status,source_views",
        ["PFT-S-CASE-000410-SZ-20261119-NUMERIC_PREFIX,000410.SZ,g1,20261119,TRUE,train,manual,source-A"],
    )
    cases, identity = baseline._read_cases(cases_path, start_date="20261101", asof_date="20261120")
    assert identity["joint_label_columns_present"] is True
    assert baseline._case_id(cases[0]) == "PFT-S-CASE-000410-SZ-20261119-NUMERIC_PREFIX"
    assert cases[0]["source_views"] == "source-A"


def test_exact_stock_episode_date_duplicates_consolidate_source_views(tmp_path: Path) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "security_id,master_episode_group,D,overall_s_label,partition,exposure_status,source_views",
        [
            "000001.SZ,g1,20261119,TRUE,train,manual,source-B",
            "000001.SZ,g1,20261119,TRUE,train,manual,source-A",
        ],
    )
    cases, identity = baseline._read_cases(cases_path, start_date="20261101", asof_date="20261120")
    assert identity["exact_duplicate_rows_removed"] == 1
    assert len(cases) == 1
    assert cases[0]["source_views"] == "source-A;source-B"


def test_legacy_duplicate_metadata_does_not_change_numeric_case_identity(tmp_path: Path) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "security_id,master_episode_group,D,overall_s_label,partition,exposure_status,risk_tag,source_views",
        [
            "000001.SZ,g1,20261119,TRUE,train,manual,legacy-a,source-A",
            "000001.SZ,g1,20261119,TRUE,train,manual,legacy-b,source-B",
        ],
    )
    cases, identity = baseline._read_cases(cases_path, start_date="20261101", asof_date="20261120")
    assert identity["exact_duplicate_rows_removed"] == 1
    assert len(cases) == 1
    assert cases[0]["source_views"] == "source-A;source-B"


def test_v11_structure_features_are_default_and_use_nonduplicated_names() -> None:
    case = {
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }
    rows = _history("000001.SZ", "20261120", bars=65)
    columns = {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
               "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"}

    examples, gaps, _unknown, feature_names = baseline._build_examples(
        [case], rows, columns, start_date="20260801",
    )
    assert not gaps
    assert len(examples) == 1
    assert examples[0]["structure_features"] is not None
    assert examples[0]["structure_diagnostics"]["target_date"] == "20261120"
    assert {"y_consec2_5b", "repaired_prior_break", "surge_low_intact"}.issubset(feature_names)
    assert {"volume_5_vs_prior15", "range_5_vs_prior15", "d_volume_vs_prior5_mean",
            "d_range_vs_prior15_mean", "d_close_above_white_line_tri",
            "d_close_above_yellow_line_tri", "yellow_active_confirmed_break_tri",
            "d_close_breaks_prior10_high_tri", "d_close_breaks_prior20_high_tri"}.issubset(feature_names)
    assert "yellow_2below_historical_tri" not in feature_names
    assert "yellow_2below_historical_tri" in examples[0]["structure_features"]
    assert not {"price_action_readvance_prior10_high_tri", "price_action_readvance_prior20_high_tri",
                "price_action_rebuild_after_prior_yellow_break_tri"}.intersection(feature_names)


@pytest.mark.parametrize("kind", ["pullback", "readvance"])
def test_v11_branch_interactions_encode_contraction_and_volume_confirmed_readvance(kind: str) -> None:
    case = {
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }
    rows = _history("000001.SZ", "20261120", bars=65)
    for row in rows:
        row.update(open=10.0, high=10.2, low=9.8, close=10.1, vol=1000.0,
                   zge_white_line=10.2, zge_yellow_line=9.8)
    anchor = rows[-12]
    rows[-13]["close"] = 10.0
    anchor.update(open=10.2, high=10.6, low=9.2, close=10.5, vol=1300.0)
    rows[-8]["high"] = 10.6
    if kind == "pullback":
        rows[-1].update(open=10.2, high=10.4, low=10.1, close=10.3, vol=500.0)
    else:
        rows[-1].update(open=10.8, high=11.2, low=10.8, close=11.0, vol=2000.0)

    examples, gaps, _unknown, _names = baseline._build_examples(
        [case], rows,
        {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
         "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"},
        start_date="20260801",
    )

    assert not gaps
    assert len(examples) == 1
    features = examples[0]["features"]
    assert features["surge_low_intact"] == 1.0
    if kind == "pullback":
        expected = max(0.0, 1.0 - features["d_volume_vs_prior5_mean"]) * max(
            0.0, 1.0 - features["d_range_vs_prior15_mean"],
        )
        assert features["d_volume_vs_prior5_mean"] < 1.0
        assert features["d_close_above_yellow_line_tri"] == 1.0
        assert features["d_close_breaks_prior10_high_tri"] == 0.0
        assert features["pullback_strength"] == pytest.approx(expected)
        assert features["re_advance_strength"] == 0.0
    else:
        expected = max(0.0, features["d_volume_vs_prior5_mean"] - 1.0) * max(
            0.0, features["d_close_vs_prior10_high_pct"],
        )
        assert features["d_volume_vs_prior5_mean"] > 1.0
        assert features["d_close_breaks_prior10_high_tri"] == 1.0
        assert features["re_advance_strength"] == pytest.approx(expected)
        assert features["pullback_strength"] == 0.0


def test_yellow_diagnostics_recover_true_start_for_left_clipped_window() -> None:
    rows = _history("000001.SZ", "20261120", bars=24)
    for index, row in enumerate(rows):
        row["zge_yellow_line"] = 10.0
        row["close"] = 9.9 if 2 <= index <= 9 else 10.1

    features, diagnostic = structure.structure_repair_features(rows, target_date="20261120")
    window_features, _ = structure._yellow_state(rows[-16:], "20261120")

    assert diagnostic["yellow_window_observed_sessions"] == 16
    assert diagnostic["yellow_latest_event_clipped_left"] is True
    assert diagnostic["yellow_latest_event_start_known"] is True
    assert diagnostic["yellow_latest_event_start_date"] == rows[2]["trade_date"]
    assert diagnostic["yellow_latest_event_confirmed_date"] == rows[3]["trade_date"]
    assert diagnostic["yellow_latest_event_window_observed_start_date"] == rows[8]["trade_date"]
    assert diagnostic["yellow_latest_event_window_observed_confirm_date"] == rows[9]["trade_date"]
    assert diagnostic["yellow_latest_event_repaired"] == "TRUE"
    assert {key: features[key] for key in window_features} == window_features


def test_missing_yellow_line_is_unknown_not_false() -> None:
    rows = _history("000001.SZ", "20261120", bars=65)
    rows[-1]["zge_yellow_line"] = None

    features, diagnostic = structure.structure_repair_features(rows, target_date="20261120")

    assert diagnostic["yellow_current_relation"] == "UNKNOWN"
    assert diagnostic["yellow_current_below_consecutive_status"] == "UNKNOWN"
    assert diagnostic["yellow_active_confirmed_break"] == "UNKNOWN"
    assert features["yellow_line_D_available"] == 0.0
    assert features["yellow_active_confirmed_break_tri"] == -1.0


def test_yellow_active_break_uses_observed_pair_but_keeps_duration_unknown() -> None:
    two_below = _history("000001.SZ", "20261120", bars=65)
    two_below[-3]["zge_yellow_line"] = None
    two_below[-3]["close"] = 9.9
    two_below[-2]["zge_yellow_line"] = 10.0
    two_below[-1]["zge_yellow_line"] = 10.0
    two_below[-2]["close"] = 9.9
    two_below[-1]["close"] = 9.9

    features, diagnostic = structure.structure_repair_features(two_below, target_date="20261120")

    assert diagnostic["yellow_current_below_observed_consecutive_count"] == 2
    assert diagnostic["yellow_current_below_consecutive_count"] is None
    assert diagnostic["yellow_current_below_duration_status"] == "MISSING_PREVIOUS_RELATION"
    assert features["yellow_current_below_run_count"] == -1.0
    assert diagnostic["yellow_active_confirmed_break"] == "TRUE"
    assert features["yellow_active_confirmed_break_tri"] == 1.0

    one_below = _history("000001.SZ", "20261120", bars=65)
    one_below[-2]["zge_yellow_line"] = None
    one_below[-2]["close"] = 9.9
    one_below[-1]["zge_yellow_line"] = 10.0
    one_below[-1]["close"] = 9.9

    one_feature_vector, one_diagnostic = structure.structure_repair_features(one_below, target_date="20261120")

    assert one_diagnostic["yellow_current_below_observed_consecutive_count"] == 1
    assert one_diagnostic["yellow_current_below_consecutive_count"] is None
    assert one_diagnostic["yellow_current_below_duration_status"] == "MISSING_PREVIOUS_RELATION"
    assert one_diagnostic["yellow_active_confirmed_break"] == "UNKNOWN"
    assert one_feature_vector["yellow_active_confirmed_break_tri"] == -1.0


def test_key_k_proxy_audits_probe_recovery_and_prior_close_break() -> None:
    rows = _history("000001.SZ", "20261120", bars=65)
    anchor_index = len(rows) - 12
    anchor = rows[anchor_index]
    anchor.update(open=10.0, high=10.7, low=9.2, close=10.5, vol=1300)
    rows[anchor_index - 1]["close"] = 10.0
    for row in rows[anchor_index - 5:anchor_index]:
        row["vol"] = 1000
    rows[-2].update(open=9.2, high=9.4, low=8.8, close=9.0)
    rows[-1].update(open=9.4, high=10.3, low=9.1, close=10.2)

    features, diagnostic = structure.structure_repair_features(rows, target_date="20261120")

    assert diagnostic["key_k_candidate_date"] == anchor["trade_date"]
    assert diagnostic["key_k_candidate_return_pct"] == pytest.approx(0.05)
    assert diagnostic["key_k_candidate_relative_prev5_volume"] == pytest.approx(1.3)
    assert diagnostic["key_k_earlier_close_break_historical"] == "TRUE"
    assert diagnostic["key_k_D_intraday_probe_recovered"] == "TRUE"
    assert diagnostic["key_k_reclaim_low_on_D"] == "TRUE"
    assert diagnostic["key_k_presently_under_low"] == "FALSE"
    assert diagnostic["key_k_D_close_above_body_midpoint"] == "FALSE"
    assert features["key_k_D_intraday_probe_recovered_tri"] == 1.0


def test_v11_cli_uses_structure_features_without_opt_in_flag() -> None:
    base = baseline._parser().parse_args([
        "--cases", "/tmp/cases.csv", "--start-date", "20260801", "--asof-date", "20261120", "--preflight",
    ])
    assert base.preflight is True
    assert not hasattr(base, "structure_repair")


def test_zero_volume_decided_case_is_an_input_gap(tmp_path: Path) -> None:
    cases = [{
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }]
    examples, gaps, unknown_exclusions, _feature_names = baseline._build_examples(
        cases,
        _history("000001.SZ", "20261120", zero_on_target=True),
        {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
         "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"},
        start_date="20260801",
    )
    assert examples == []
    assert unknown_exclusions == []
    assert gaps[0]["reason"] == "ZERO_D_VOLUME_WITH_DECIDED_LABEL"


def test_exact_d_and_minimum_history_gaps_are_reported() -> None:
    cases = [{
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }]
    examples, gaps, _unknown_exclusions, _feature_names = baseline._build_examples(
        cases,
        _history("000001.SZ", "20261120", bars=59),
        {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
         "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"},
        start_date="20260801",
    )
    assert examples == []
    assert gaps[0]["reason"] == "INSUFFICIENT_HISTORY"
    assert gaps[0]["available_bars"] == "59"


def test_causal_window_features_react_to_d_minus_10_and_ignore_post_d() -> None:
    rows = _history("000001.SZ", "20261120", bars=65)
    columns = {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
               "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"}
    baseline_vector = baseline._feature_values(rows, columns, target_date="20261120")

    changed_past = [dict(row) for row in rows]
    d_minus_10 = (date(2026, 11, 20) - timedelta(days=10)).strftime("%Y%m%d")
    next(row for row in changed_past if row["trade_date"] == d_minus_10)["vol"] *= 4
    changed_vector = baseline._feature_values(changed_past, columns, target_date="20261120")
    assert changed_vector["volume_5_vs_prior15"] != baseline_vector["volume_5_vs_prior15"]

    post_d = [*rows, {**rows[-1], "trade_date": "20261121", "close": 1000.0,
                      "high": 1100.0, "low": 900.0, "vol": 10**9}]
    future_vector = baseline._feature_values(post_d, columns, target_date="20261120")
    assert future_vector == baseline_vector


def test_model_probability_loader_uses_serialized_numeric_weights() -> None:
    import numpy as np

    payload = {"scaler_mean": [0.0], "scaler_scale": [1.0],
               "coefficient_true": [1.0], "intercept": 0.0}
    probabilities = baseline._manual_probabilities(payload, np.asarray([[0.0], [1.0]]))
    assert probabilities[0] == pytest.approx(0.5)
    assert probabilities[1] == pytest.approx(1.0 / (1.0 + np.exp(-1.0)))


def test_fit_uses_all_decided_train_rows_but_predicts_only_ungated_decided_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np
    import sklearn.linear_model
    import sklearn.pipeline
    import sklearn.preprocessing

    calls: list[int] = []
    fit_state: dict[str, object] = {}

    class FakeLogisticRegression:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class FakeStandardScaler:
        pass

    class FakePipeline:
        def __init__(self, steps: list[tuple[str, object]]) -> None:
            self.named_steps = dict(steps)

        def fit(self, matrix: object, labels: object) -> "FakePipeline":
            x = np.asarray(matrix, dtype=float)
            y = np.asarray(labels, dtype=int)
            fit_state["rows"] = len(y)
            fit_state["labels"] = y.tolist()
            self.named_steps["scale"].mean_ = x.mean(axis=0)
            self.named_steps["scale"].scale_ = np.ones(x.shape[1])
            self.named_steps["logistic"].classes_ = np.asarray([0, 1])
            self.named_steps["logistic"].coef_ = np.zeros((1, x.shape[1]))
            self.named_steps["logistic"].intercept_ = np.asarray([0.0])
            return self

        def predict_proba(self, matrix: object) -> object:
            x = np.asarray(matrix, dtype=float)
            calls.append(len(x))
            probabilities = np.full(len(x), 0.5)
            return np.column_stack((1.0 - probabilities, probabilities))

    monkeypatch.setattr(sklearn.linear_model, "LogisticRegression", FakeLogisticRegression)
    monkeypatch.setattr(sklearn.preprocessing, "StandardScaler", FakeStandardScaler)
    monkeypatch.setattr(sklearn.pipeline, "Pipeline", FakePipeline)

    def example(case_id: str, partition: str, label: str, *, veto: str = "") -> dict[str, object]:
        return {
            "case_id": case_id, "security_id": "000001.SZ", "master_episode_group": case_id,
            "D": "20261120", "overall_s_label": label, "partition": partition,
            "exposure_status": "manual", "source_views": "", "features": {"f": float(len(case_id))},
            "structure_features": None, "structure_diagnostics": None, "history_bars": 65,
            "d_volume": 100.0, "zero_volume_on_D": False,
            "inference_gate": {
                "G1_pass": veto != "G1", "G2_branch_triggers": ["G2_TEST"] if veto == "G2" else [],
                "gate_would_veto": bool(veto), "gate_reason": veto,
            },
            "gate_would_disagree_with_signed_label": bool(veto and label == "TRUE") if label != "UNKNOWN" else None,
        }

    examples = [
        example("T1", "train", "TRUE", veto="G1"),
        example("T2", "train", "FALSE"),
        example("T3", "train", "TRUE"),
        example("T4", "train", "FALSE", veto="G2"),
        example("V1", "validation", "TRUE", veto="G1"),
        example("V2", "validation", "FALSE"),
        example("V3", "validation", "UNKNOWN"),
    ]
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    report = {
        "coverage": {
            "feature_names": ["f"], "unknown_case_count": 1,
            "inference_gate_precheck": baseline._gate_precheck_support(examples),
        },
    }

    result = baseline._fit_and_materialize(report, examples, output_dir, before_write=lambda: None)

    assert fit_state["rows"] == 4
    assert fit_state["labels"] == [1, 0, 1, 0]
    assert result["model"]["class_weight"] == "balanced"
    assert result["model_artifact"]["training_case_ids"] == ["T1", "T2", "T3", "T4"]
    assert calls == [3]  # T2, T3 and V2 only; vetoed rows never reach predict_proba.
    assert result["model_load_check"]["prediction_count"] == 3
    assert result["metrics"]["training"]["n"] == 4
    assert result["metrics"]["validation_whole_policy"]["n"] == 2
    assert result["metrics"]["validation_whole_policy"]["n_expected_all_decided_validation_rows"] == 2
    assert len(result["metrics"]["gate_signed_label_conflicts"]) == 2
    assert result["metrics"]["veto_rows_receive_model_probability"] is False

    with (output_dir / "predictions.csv").open(encoding="utf-8", newline="") as stream:
        predictions = {row["case_id"]: row for row in csv.DictReader(stream)}
    assert predictions["T1"]["prediction"] == "FALSE"
    assert predictions["T1"]["probability_true"] == ""
    assert float(predictions["T1"]["effective_decision_score"]) == 0.0
    assert predictions["V1"]["probability_true"] == ""
    assert predictions["V3"]["overall_s_label"] == "UNKNOWN"
    assert predictions["V3"]["scored"] == "False"
    assert predictions["V3"]["probability_true"] == ""


def test_existing_output_path_is_rejected_before_any_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_path = _write_csv(
        tmp_path / "joint.csv",
        "security_id,master_episode_group,D,overall_s_label,partition,exposure_status",
        [
            "000001.SZ,g1,20261120,TRUE,train,manual",
            "000002.SZ,g2,20261120,FALSE,train,manual",
            "000003.SZ,g3,20261120,TRUE,validation,manual",
            "000004.SZ,g4,20261120,FALSE,validation,manual",
        ],
    )
    rows = []
    for code in ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"):
        rows.extend(_history(code, "20261120"))
    _fake_panel(monkeypatch, rows)
    existing_output = tmp_path / "already-used"
    existing_output.mkdir()
    monkeypatch.setattr(baseline, "_fit_and_materialize", lambda *_a, **_k: pytest.fail("fit ran before output validation"))

    with pytest.raises(baseline.BaselineError, match="OUTPUT_DIR_MUST_BE_NEW_ABSOLUTE_PATH"):
        baseline.run_once(
            data_root=tmp_path,
            cases_path=cases_path,
            start_date="20260801",
            asof_date="20261120",
            expected_sha256=hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            output_dir=existing_output,
        )
