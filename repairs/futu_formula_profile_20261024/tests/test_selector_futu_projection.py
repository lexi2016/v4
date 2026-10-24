from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pandas as pd
import pytest


J_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_READER = J_ROOT / "implementation/DATA_LAYER_INTERFACE.pre_futu_baseline.py"
CANDIDATE_READER = REPO_ROOT / "upstreams/v3_shared_data/shared_data/selector_data_layer_interface.py"
PROFILE_DIR = J_ROOT / "implementation/futu_qfq_profile_v1"
REAL_PANEL = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/"
    "selector_ready_panels/data_layer_daily_formula_increment_update_v1/"
    "selector_ready_current_to_20261023_20261024_103452/selector_ready_current_to_20261023.parquet"
)
ASOF = "20261023"
CODES = ["002612.SZ", "001283.SZ"]
EXPECTED = {
    "002612.SZ": {"zge_yellow_line": 15.648, "BBI": 15.818, "zge_white_line": 16.064, "ma60": 15.735},
    "001283.SZ": {"zge_yellow_line": 48.321, "BBI": 50.758, "zge_white_line": 48.892, "ma60": 46.290},
}


def _load_reader(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline_reader = _load_reader("selector_data_layer_baseline_test", BASELINE_READER)
candidate_reader = _load_reader("selector_data_layer_candidate_test", CANDIDATE_READER)
candidate_reader.FUTU_QFQ_PROFILE_DIR = PROFILE_DIR


def test_default_and_explicit_raw_reads_match_the_unmodified_reader(tmp_path):
    panel_path = tmp_path / "selector.parquet"
    expected = pd.DataFrame(
        {
            "trade_date": ["20261022", "20261023"],
            "ts_code": ["002612.SZ", "002612.SZ"],
            "open": [15.0, 15.5],
            "close": [15.2, 15.7],
            "BBI": [15.1, 15.6],
        }
    )
    expected.to_parquet(panel_path, index=False)
    options = {
        "columns": ["open", "close", "BBI"],
        "filters": [("ts_code", "=", "002612.SZ")],
        "panel_path": panel_path,
    }
    old_default = baseline_reader.load_selector_ready(**options)
    new_default = candidate_reader.load_selector_ready(**options)
    new_explicit_raw = candidate_reader.load_selector_ready(profile="RAW", **options)
    pd.testing.assert_frame_equal(old_default, expected)
    pd.testing.assert_frame_equal(new_default, old_default)
    pd.testing.assert_frame_equal(new_explicit_raw, old_default)


@pytest.mark.skipif(
    not (REAL_PANEL.is_file() and (PROFILE_DIR / "futu_formula_profile.json").is_file()),
    reason="requires the locally prepared two-stock engineering parity artifact",
)
def test_real_two_stock_futu_qfq_profile_via_original_reader_interface(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("FUTU_QFQ profile reads must never use network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    raw_columns = ["open", "high", "low", "close", "volume", "amount", "BBI", "zge_white_line", "zge_yellow_line", "ma60"]
    raw_options = {
        "columns": raw_columns,
        "filters": [("ts_code", "in", CODES)],
        "ts_codes": CODES,
        "panel_path": REAL_PANEL,
    }
    expected_raw = baseline_reader.load_selector_ready(**raw_options)
    default_raw = candidate_reader.load_selector_ready(**raw_options)
    explicit_raw = candidate_reader.load_selector_ready(profile="RAW", **raw_options)
    pd.testing.assert_frame_equal(default_raw, expected_raw)
    pd.testing.assert_frame_equal(explicit_raw, expected_raw)

    qfq = candidate_reader.load_selector_ready(
        columns=["open", "high", "low", "close", "BBI", "zge_white_line", "zge_yellow_line", "ma60"],
        filters=[("ts_code", "in", CODES)],
        ts_codes=CODES,
        panel_path=REAL_PANEL,
        profile="FUTU_QFQ_ASOF",
        asof=ASOF,
    )
    for code, expected in EXPECTED.items():
        row = qfq[(qfq["ts_code"] == code) & (qfq["trade_date"] == ASOF)]
        assert len(row) == 1
        actual = {column: round(float(row.iloc[0][column]), 3) for column in expected}
        assert actual == expected
    assert set(qfq["ts_code"]) == set(CODES)
    assert not {"volume", "amount", "B1", "B2", "B3", "J"}.intersection(qfq.columns)
    assert qfq.attrs["profile_metadata"]["price_basis"] == "FUTU_QFQ_ASOF"
    assert qfq.attrs["profile_metadata"]["volume_dependent_label_parity"] == "NOT_CLAIMED"

    meta = candidate_reader.get_panel_meta(
        panel_path=REAL_PANEL, include_dates=False, profile="FUTU_QFQ_ASOF", asof=ASOF,
    )
    assert meta["read_profile"]["source_panel_sha256"] == qfq.attrs["profile_metadata"]["source_panel_sha256"]
    assert meta["read_profile"]["historical_pit_certified"] is False
    assert "read_profile" not in candidate_reader.get_panel_meta(panel_path=REAL_PANEL, include_dates=False)


def test_reader_fails_closed_for_future_asof_and_uncached_symbols():
    if not REAL_PANEL.is_file() or not (PROFILE_DIR / "futu_formula_profile.json").is_file():
        pytest.skip("requires the locally prepared two-stock engineering parity artifact")
    projection = candidate_reader._load_futu_projection_module()
    with pytest.raises(projection.FutuProfileError, match="FUTU_PROFILE_FUTURE_ASOF"):
        candidate_reader.load_selector_ready(
            ts_codes=["002612.SZ"], panel_path=REAL_PANEL,
            profile="FUTU_QFQ_ASOF", asof="20261024",
        )
    with pytest.raises(projection.FutuProfileError, match="MISSING_FACTOR_COVERAGE"):
        candidate_reader.load_selector_ready(
            ts_codes=["600000.SH"], panel_path=REAL_PANEL,
            profile="FUTU_QFQ_ASOF", asof=ASOF,
        )
