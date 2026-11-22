from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import hashlib
from pathlib import Path

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


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


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


def test_structure_repair_is_opt_in_and_preserves_default_feature_set() -> None:
    case = {
        "security_id": "000001.SZ", "master_episode_group": "g1", "D": "20261120",
        "overall_s_label": "TRUE", "partition": "train", "exposure_status": "manual",
    }
    rows = _history("000001.SZ", "20261120", bars=65)
    columns = {"vol": "vol", "bbi": "bbi", "zge_white_line": "zge_white_line",
               "zge_yellow_line": "zge_yellow_line", "ma60": "ma60"}

    legacy, _gaps, _unknown, legacy_names = baseline._build_examples(
        [case], rows, columns, start_date="20260801",
    )
    repaired, _gaps, _unknown, repaired_names = baseline._build_examples(
        [case], rows, columns, start_date="20260801", structure_repair=True,
    )

    assert len(legacy) == 1
    assert len(legacy_names) == 16
    assert legacy[0]["structure_features"] is None
    assert len(repaired) == 1
    assert len(repaired_names) == 35
    assert repaired[0]["structure_features"] is not None
    assert repaired[0]["structure_diagnostics"]["target_date"] == "20261120"


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


def test_structure_repair_cli_flag_is_opt_in() -> None:
    base = baseline._parser().parse_args([
        "--cases", "/tmp/cases.csv", "--start-date", "20260801", "--asof-date", "20261120", "--preflight",
    ])
    repaired = baseline._parser().parse_args([
        "--cases", "/tmp/cases.csv", "--start-date", "20260801", "--asof-date", "20261120",
        "--preflight", "--structure-repair",
    ])
    assert base.structure_repair is False
    assert repaired.structure_repair is True


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
