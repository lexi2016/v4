"""回归：load_selector_ready 必须接受与列类型不一致的过滤字面量。

历史缺陷：trade_date 存为 string，调用方传 int，pyarrow 抛
ArrowNotImplementedError(less_equal(string, int32))，日更链在读取阶段即中止。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1] / "upstreams" / "v3_shared_data" / "shared_data"
sys.path.insert(0, str(MODULE_DIR))

import selector_data_layer_interface as sdl  # noqa: E402


def _panel(tmp_path: Path) -> Path:
    frame = pd.DataFrame(
        {
            "trade_date": ["20260101", "20260102", "20260103"],
            "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "close": [10.0, 11.0, 12.0],
        }
    )
    path = tmp_path / "panel.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_int_filter_on_string_trade_date_is_coerced(tmp_path):
    path = _panel(tmp_path)
    frame = sdl.load_selector_ready(
        columns=["close"],
        filters=[("trade_date", ">=", 20260102), ("trade_date", "<=", 20260103)],
        panel_path=str(path),
    )
    assert sorted(frame["trade_date"].astype(str)) == ["20260102", "20260103"]


def test_string_filter_on_string_trade_date_still_works(tmp_path):
    path = _panel(tmp_path)
    frame = sdl.load_selector_ready(
        columns=["close"],
        filters=[("trade_date", ">=", "20260102")],
        panel_path=str(path),
    )
    assert sorted(frame["trade_date"].astype(str)) == ["20260102", "20260103"]


def test_filter_coercion_keeps_column_and_operator(tmp_path):
    path = _panel(tmp_path)
    coerced = sdl._coerce_filter_literals(
        [("trade_date", ">=", 20260102), ("ts_code", "=", "000001.SZ")], str(path)
    )
    assert coerced == [("trade_date", ">=", "20260102"), ("ts_code", "=", "000001.SZ")]
