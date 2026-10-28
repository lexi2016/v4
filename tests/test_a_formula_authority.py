"""Focused tests for the V4 pure A formula authority and contract shape."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from ops import a_formula_increment as increment
from upstreams.v3_shared_data.shared_data import a_formula_authority as authority


CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "a_formula_field_contract_v0.csv"


def _bars() -> pd.DataFrame:
    dates = [20260828, 20260829, 20260901, 20260902, 20260903, 20260904]
    rows = []
    for code, base in (("600001.SH", 10.0), ("000001.SZ", 20.0)):
        for index, day in enumerate(dates):
            close = base + index * 0.25
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": day,
                    "raw_code": code[:6],
                    "exchange": code[-2:],
                    "market_type": "A",
                    "name": "fixture",
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 1_000 + index * 50,
                    "amount": 100_000 + index * 2_000,
                }
            )
    return pd.DataFrame(rows)


def test_formula_origin_and_key_order_are_stable() -> None:
    bars = _bars()
    result = authority.compute_partition_formula(bars)
    assert authority.ORIGIN_SHA256 == "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"
    assert list(result[["ts_code", "trade_date"]].itertuples(index=False, name=None)) == list(
        bars[["ts_code", "trade_date"]].itertuples(index=False, name=None)
    )
    assert len(result) == len(bars)
    last = result[result["ts_code"] == "600001.SH"].iloc[-1]
    expected_ma3 = bars.loc[bars["ts_code"].eq("600001.SH"), "close"].tail(3).mean()
    assert float(last["ma3"]) == pytest.approx(expected_ma3)
    previous = bars.loc[bars["ts_code"].eq("600001.SH"), "close"].iloc[-2]
    assert float(last["pct_chg"]) == pytest.approx((float(last["close"]) / previous - 1.0) * 100.0)
    for field in ("brick_buy", "brick_buy1_low_absorb", "brick_buy2_attack", "brick_exist_b", "brick_resonance1", "brick_resonance2", "brick_resonance"):
        assert field in result.columns
    enriched = increment.compute_formula_features(bars)
    assert set(("primary_buy_signal", "secondary_buy_signal")) <= set(enriched.columns)


def test_explicit_xdxr_columns_are_used_without_default_root() -> None:
    bars = _bars().query("ts_code == '600001.SH'").reset_index(drop=True)
    raw_previous = bars["close"].shift(1)
    bars["xdxr_fenhong"] = 0.0
    bars["xdxr_peigujia"] = 0.0
    bars["xdxr_songzhuangu"] = 0.0
    bars["xdxr_peigu"] = 0.0
    bars.loc[2, "xdxr_fenhong"] = 1.0
    adjusted = authority.apply_xdxr_pre_close(bars, raw_previous)
    assert adjusted.iloc[2] == pytest.approx(raw_previous.iloc[2] - 0.1)


def test_contract_is_exactly_187_plus_12() -> None:
    rows = increment.load_authoritative_contract_rows(CONTRACT)
    policy = increment.build_contract_policy(rows, CONTRACT)
    assert len(rows) == 199
    assert policy["official_count"] == 187
    assert policy["sidecar_count"] == 12
    with CONTRACT.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert [row["column"] for row in csv_rows if row["allowed_in_current"] == "yes"] == policy["official_columns"]
    assert set(policy["sidecar_columns"]) == set(increment.SIDEcar_COLUMNS)
