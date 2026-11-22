"""PFT-S V1.2 full-A rule-label study and fixed OOS ranker benchmark.

Research only. Reads the bound V4 QFQ panel through its logical parquet
reader, forms all features and weak setup labels at D, then evaluates later
outcomes by A-market session offsets. No production or trading decisions are
emitted.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

SCHEMA = "pft_s_v12_full_a.v1"
MODEL_SCHEMA = "pft_s_v12_full_a_models.v1"
BOUNDARY_EPS = 1e-12
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
DEFAULT_START = "20251101"
DEFAULT_ASOF = "20261120"
TRAIN_END = "20260831"
OOS_START = "20260901"
STATS_START = "20260501"
FRIDAY_D = "20261119"
HORIZONS = (1, 3, 5, 10)
FEATURE_NAMES = (
    "ret_1", "ret_5", "ret_20", "ret_60", "d_range_prev_close",
    "d_upper_wick_prev_close", "d_open_close_prev_close",
    "close_yellow_pct", "close_white_pct", "white_yellow_spread_pct",
    "close_bbi_pct", "vol5_vs_prior15", "range5_vs_prior15",
    "d_vr5", "d_range_vs_prior15", "close_vs_prior10_high",
    "close_vs_prior20_high", "close_vs_trailing30_high",
    "anchor_return", "anchor_vr5", "close_vs_anchor_low",
    "anchor_age", "low_held_anchor", "recent_below_pair",
    "prior5_vol_vs_prior15", "prior5_range_vs_prior15",
)
ALIASES = {
    "ts_code": ("ts_code",), "market_type": ("market_type",),
    "trade_date": ("trade_date",), "open": ("open",),
    "high": ("high",), "low": ("low",), "close": ("close",),
    "vol": ("vol", "volume"), "pct_chg": ("pct_chg", "change_pct"),
    "bbi": ("bbi",), "j": ("j", "j_value"),
    "zge_white_line": ("zge_white_line",),
    "zge_yellow_line": ("zge_yellow_line",),
}


class StudyError(RuntimeError):
    """Fail-closed panel, data, or output contract error."""


def _day(value: Any, name: str) -> str:
    text = str(value).strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise StudyError(f"INVALID_{name.upper()}:{value!r}")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise StudyError(f"INVALID_{name.upper()}:{value!r}") from exc
    return text


def _code(value: Any) -> str:
    result = str(value or "").strip().upper()
    if re.fullmatch(r"\d{6}", result):
        suffix = "BJ" if result.startswith(("4", "8", "920")) else (
            "SH" if result.startswith(("5", "6", "9")) else "SZ")
        result = f"{result}.{suffix}"
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", result):
        raise StudyError(f"INVALID_A_SHARE_CODE:{value!r}")
    return result


def _normalize_observed_column(series: Any, parser: Callable[[Any], str], field: str) -> Any:
    """Normalize observed unique values only; do not traverse unused category levels."""
    import pandas as pd
    values = series.astype("string")
    if values.isna().any():
        raise StudyError(f"PANEL_MISSING_{field.upper()}_KEY")
    mapping: dict[str, str] = {}
    for value in pd.unique(values):
        text = str(value)
        try:
            mapping[text] = parser(text)
        except StudyError as exc:
            raise StudyError(f"PANEL_INVALID_{field.upper()}_KEY:{text!r}") from exc
    return values.map(mapping)


def _num(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if value is None or isinstance(value, bool):
        raise StudyError(f"INVALID_NUMERIC:{name}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StudyError(f"INVALID_NUMERIC:{name}") from exc
    if not math.isfinite(number) or (not allow_zero and number <= 0):
        raise StudyError(f"INVALID_NUMERIC:{name}")
    return number


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def bind_current_panels(data_root: Path):
    """Reuse the existing V4 paired-selector/backtest identity binder."""
    from ops.pft_s_first_baseline import bind_current_panels as bind
    with bind(data_root) as binding:
        yield binding


def _arrow_date_value(schema: Any, field: str, day: str) -> Any:
    import pyarrow as pa
    dtype = schema.field(field).type
    if pa.types.is_integer(dtype):
        return int(day)
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return day
    if pa.types.is_date(dtype):
        return date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    raise StudyError(f"UNSUPPORTED_PANEL_DATE_TYPE:{dtype}")


def _read_panel(panel_path: Path, *, start_date: str, asof_date: str,
                warmup_days: int = 180) -> tuple[Any, dict[str, Any]]:
    """Read only the contracted logical columns and bounded date interval."""
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel_path)
    actual = {name.lower(): name for name in schema.names}
    columns: dict[str, str] = {}
    for semantic, candidates in ALIASES.items():
        found = next((actual[item] for item in candidates if item in actual), None)
        if found is None:
            raise StudyError(f"PANEL_REQUIRED_COLUMN_MISSING:{semantic}")
        columns[semantic] = found
    read_columns = list(dict.fromkeys(columns.values()))
    warmup_start = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=warmup_days)).strftime("%Y%m%d")
    filters = [
        (columns["trade_date"], ">=", _arrow_date_value(schema, columns["trade_date"], warmup_start)),
        (columns["trade_date"], "<=", _arrow_date_value(schema, columns["trade_date"], asof_date)),
    ]
    table = parquet.read_table(panel_path, columns=read_columns, filters=filters)
    import pandas as pd
    frame = table.select(read_columns).to_pandas().rename(
        columns={actual_name: semantic for semantic, actual_name in columns.items()})
    frame["market_type"] = frame["market_type"].fillna("").astype(str).str.strip().str.upper()
    # Some V4 blocks identify the A-share exchange directly in market_type.
    # Retain that real value for provenance instead of rewriting it to A_SHARE.
    a_market = {"A", "A_SHARE", "ASHARE", "CN_A", "A-SHARE", "SH", "SZ", "BJ"}
    frame = frame.loc[frame["market_type"].isin(a_market)].copy()
    frame["ts_code"] = _normalize_observed_column(frame["ts_code"], _code, "ts_code")
    # The panel's int32 trading dates have only a few hundred observed values;
    # normalize this small set rather than calling datetime.strptime per row.
    frame["trade_date"] = _normalize_observed_column(
        frame["trade_date"], lambda value: _day(value, "trade_date"), "trade_date")
    frame.sort_values(["ts_code", "trade_date"], kind="mergesort", inplace=True)
    if frame.duplicated(["ts_code", "trade_date"]).any():
        row = frame.loc[frame.duplicated(["ts_code", "trade_date"], keep=False)].iloc[0]
        raise StudyError(f"DUPLICATE_PANEL_KEY:{row.ts_code}:{row.trade_date}")
    return frame.reset_index(drop=True), {"projected_columns": list(ALIASES), "panel_rows": len(frame),
                  "warmup_start": warmup_start, "requested_start": start_date,
                  "asof_date": asof_date}


def read_official_top200(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load the supplied official rank snapshot; never manufacture its ranks."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise StudyError("OFFICIAL_TOP200_PATH_INVALID")
    before = path.stat()
    raw = path.read_bytes()
    if path.stat() != before:
        raise StudyError("OFFICIAL_TOP200_CHANGED_DURING_READ")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudyError("OFFICIAL_TOP200_NOT_VALID_UTF8_JSON") from exc
    top = payload.get("top200") if isinstance(payload, dict) else None
    if isinstance(top, dict):
        top = top.get("rows") or top.get("items")
    if not isinstance(top, list):
        raise StudyError("OFFICIAL_TOP200_ROWS_MISSING")
    indexed: dict[str, dict[str, Any]] = {}
    ranks: set[int] = set()
    for item in top:
        if not isinstance(item, dict):
            raise StudyError("OFFICIAL_TOP200_ROW_INVALID")
        symbol = _code(item.get("symbol"))
        try:
            rank = int(item.get("rank"))
            change = float(item.get("change_pct"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudyError("OFFICIAL_TOP200_RANK_OR_CHANGE_INVALID") from exc
        if rank < 1 or rank > 200 or rank in ranks or symbol in indexed or not math.isfinite(change):
            raise StudyError("OFFICIAL_TOP200_DUPLICATE_OR_OUT_OF_RANGE")
        ranks.add(rank)
        indexed[symbol] = {"rank": rank, "change_pct": change, "name": str(item.get("name") or "")}
    if len(indexed) != 200 or ranks != set(range(1, 201)):
        raise StudyError("OFFICIAL_TOP200_MUST_HAVE_200_UNIQUE_RANKS")
    return indexed, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw), "rows": len(indexed),
                     "asof_date": _day(payload.get("asof_date", DEFAULT_ASOF), "official_asof_date")}


def _valid_ohlcv(row: dict[str, Any]) -> dict[str, float]:
    vals = {name: _num(row.get(name), name, allow_zero=(name == "vol"))
            for name in ("open", "high", "low", "close", "vol")}
    if min(vals[key] for key in ("open", "high", "low", "close")) <= 0 or vals["vol"] < 0:
        raise StudyError("INVALID_OHLCV_RANGE")
    if vals["high"] < max(vals["open"], vals["close"], vals["low"]):
        raise StudyError("INVALID_OHLC_ENVELOPE")
    if vals["low"] > min(vals["open"], vals["close"], vals["high"]):
        raise StudyError("INVALID_OHLC_ENVELOPE")
    return vals


def _recent_yellow_pair(bars: list[dict[str, Any]]) -> bool:
    tail = bars[-5:]
    for first, second in zip(tail, tail[1:]):
        try:
            if (_num(first["close"], "close") < _num(first["zge_yellow_line"], "yellow", allow_zero=False)
                    and _num(second["close"], "close") < _num(second["zge_yellow_line"], "yellow", allow_zero=False)):
                return True
        except StudyError:
            continue
    return False


def _key_anchor(bars: list[dict[str, Any]]) -> tuple[int, dict[str, float]] | None:
    """Nearest prior K: >=3.5% up session and D-1..D-5 relative volume >=1.2."""
    for idx in range(len(bars) - 2, max(-1, len(bars) - 42), -1):
        if idx < 5:
            continue
        try:
            close = _num(bars[idx]["close"], "anchor_close", allow_zero=False)
            prev = _num(bars[idx - 1]["close"], "anchor_prev_close", allow_zero=False)
            volume = _num(bars[idx]["vol"], "anchor_volume")
            prev5 = [_num(row["vol"], "anchor_prev_volume") for row in bars[idx - 5:idx]]
            white = _num(bars[idx]["zge_white_line"], "anchor_white", allow_zero=False)
            yellow = _num(bars[idx]["zge_yellow_line"], "anchor_yellow", allow_zero=False)
            del white, yellow
        except StudyError:
            continue
        mean5 = sum(prev5) / 5.0
        if mean5 > 0 and close / prev - 1.0 >= 0.035 and volume / mean5 >= 1.2:
            low = _num(bars[idx]["low"], "anchor_low", allow_zero=False)
            return idx, {"anchor_return": close / prev - 1.0, "anchor_vr5": volume / mean5,
                         "anchor_low": low}
    return None


def _feature_row(bars: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    """Create causal D features and deterministic rule labels from D and prior bars."""
    if len(bars) < 61:
        raise StudyError("INSUFFICIENT_61_SESSION_HISTORY")
    values = [_valid_ohlcv(row) | {k: row[k] for k in (
        "trade_date", "ts_code", "market_type", "pct_chg", "bbi", "j",
        "zge_white_line", "zge_yellow_line")} for row in bars[-61:]]
    d = values[-1]
    prev = values[-2]
    close, high, low, open_, volume = (d[k] for k in ("close", "high", "low", "open", "vol"))
    prevclose = prev["close"]
    prior5 = values[-6:-1]
    prior15 = values[-20:-5]
    prior10 = values[-11:-1]
    prior20 = values[-21:-1]
    trailing30 = values[-30:]
    mean5v = sum(x["vol"] for x in prior5) / 5.0
    mean15v = sum(x["vol"] for x in prior15) / 15.0
    mean15r = sum((x["high"] - x["low"]) / x["close"] for x in prior15) / 15.0
    recent5v = sum(x["vol"] for x in values[-5:]) / 5.0
    recent5r = sum((x["high"] - x["low"]) / x["close"] for x in values[-5:]) / 5.0
    if mean15v <= 0 or mean15r <= 0:
        raise StudyError("ZERO_PRIOR15_BASELINE")
    white = _num(d["zge_white_line"], "white", allow_zero=False)
    yellow = _num(d["zge_yellow_line"], "yellow", allow_zero=False)
    bbi = _num(d["bbi"], "bbi", allow_zero=False)
    j = _num(d["j"], "j")
    recent_pair = _recent_yellow_pair(values)
    anchor = _key_anchor(values)
    anchor_idx, anchor_data = anchor if anchor is not None else (-1, {})
    prior10_high = max(x["high"] for x in prior10)
    prior20_high = max(x["high"] for x in prior20)
    high30 = max(x["high"] for x in trailing30)
    anchor_age = len(values) - 1 - anchor_idx if anchor is not None else -1
    anchor_close_hold = bool(anchor is not None and all(
        row["close"] >= anchor_data["anchor_low"] for row in values[anchor_idx + 1:]
    ))
    low_held = bool(anchor is not None and low > anchor_data["anchor_low"] and anchor_close_hold)
    d_range = (high - low) / prevclose
    d_vr5 = volume / mean5v if mean5v > 0 else -1.0
    upper_wick = (high - max(open_, close)) / prevclose
    close_yellow = close / yellow - 1.0
    drawdown30 = close / high30 - 1.0
    amp = (high - low) / prevclose
    g1 = white > yellow
    g2 = (
        close_yellow >= 0.35 and (upper_wick >= 0.03 or close < open_)
    ) or (
        close_yellow >= 0.25 and upper_wick >= 0.04 and d_vr5 >= 1.5
    ) or (drawdown30 <= -0.22 and amp >= 0.08)
    eligible = bool(g1 and not g2)

    # Setup rules are weak labels formed solely from the D and earlier bars.
    pullback = bool(
        eligible and anchor is not None and anchor_age >= 3 and low_held
        and close >= yellow and close <= prior10_high
        and not recent_pair and mean5v > 0 and d_vr5 <= 1.0 and (high - low) / close <= mean15r
        and recent5v / mean15v <= 0.8 and recent5r / mean15r <= 0.85
        and d_range / max(mean15r, 1e-12) <= 1.0
    )
    prior5r = sum((x["high"] - x["low"]) / x["close"] for x in prior5) / 5.0
    prevprev15 = values[-21:-6]
    prevprev15v = sum(x["vol"] for x in prevprev15) / 15.0 if len(prevprev15) == 15 else 0.0
    prevprev15r = (sum((x["high"] - x["low"]) / x["close"] for x in prevprev15) / 15.0
                   if len(prevprev15) == 15 else 0.0)
    prior5_compacted = bool(prevprev15v > 0 and prevprev15r > 0
                            and sum(x["vol"] for x in prior5) / 5.0 <= prevprev15v
                            and prior5r <= prevprev15r)
    readvance = bool(
        eligible and anchor is not None and low_held and anchor_age >= 4 and prior5_compacted
        and close > prior10_high and d_vr5 >= 1.2 and not recent_pair
    )

    prior_break = values[-26:-6]  # D-25 through D-6, excluding D.
    prior_pair = any(
        _num(a["close"], "close") < _num(a["zge_yellow_line"], "yellow", allow_zero=False)
        and _num(b["close"], "close") < _num(b["zge_yellow_line"], "yellow", allow_zero=False)
        for a, b in zip(prior_break, prior_break[1:])
    ) if len(prior_break) == 20 else False
    repair_idx = None
    if prior_pair:
        for i in range(1, len(values) - 1):
            if i < len(values) - 26 or i > len(values) - 8:
                continue
            if (values[i - 1]["close"] < values[i - 1]["zge_yellow_line"]
                    and values[i]["close"] < values[i]["zge_yellow_line"]):
                # Search only after a D-25..D-6 pair for the later repair pair.
                for jx in range(i + 1, len(values)):
                    if jx > len(values) - 2:
                        break
                    a, b = values[jx], values[jx + 1]
                    if (a["close"] > a["zge_white_line"] and a["close"] > a["zge_yellow_line"]
                            and b["close"] > b["zge_white_line"] and b["close"] > b["zge_yellow_line"]):
                        repair_idx = jx + 1
                if repair_idx is not None:
                    break
    relapse = False
    if repair_idx is not None:
        post = values[repair_idx + 1:]
        relapse = any(a["close"] < a["zge_yellow_line"] and b["close"] < b["zge_yellow_line"]
                      for a, b in zip(post, post[1:]))
    rebuild_anchor_ok = anchor is None or low_held
    rebuild = bool(eligible and prior_pair and repair_idx is not None and not relapse
                   and rebuild_anchor_ok
                   and close > white and close > yellow)

    feats = {
        "ret_1": close / prevclose - 1.0,
        "ret_5": close / values[-6]["close"] - 1.0,
        "ret_20": close / values[-21]["close"] - 1.0,
        "ret_60": close / values[-61]["close"] - 1.0,
        "d_range_prev_close": (high - low) / prevclose,
        "d_upper_wick_prev_close": upper_wick,
        "d_open_close_prev_close": (close - open_) / prevclose,
        "close_yellow_pct": close_yellow,
        "close_white_pct": close / white - 1.0,
        "white_yellow_spread_pct": white / yellow - 1.0,
        "close_bbi_pct": close / bbi - 1.0,
        "vol5_vs_prior15": recent5v / mean15v,
        "range5_vs_prior15": recent5r / mean15r,
        "d_vr5": d_vr5,
        "d_range_vs_prior15": ((high - low) / close) / mean15r,
        "close_vs_prior10_high": close / prior10_high - 1.0,
        "close_vs_prior20_high": close / prior20_high - 1.0,
        "close_vs_trailing30_high": drawdown30,
        "anchor_return": anchor_data.get("anchor_return", -1.0),
        "anchor_vr5": anchor_data.get("anchor_vr5", -1.0),
        "close_vs_anchor_low": close / anchor_data["anchor_low"] - 1.0 if anchor is not None else -1.0,
        "anchor_age": float(anchor_age),
        "low_held_anchor": float(low_held),
        "recent_below_pair": float(recent_pair),
        "prior5_vol_vs_prior15": sum(x["vol"] for x in prior5) / 5.0 / mean15v,
        "prior5_range_vs_prior15": prior5r / mean15r,
    }
    if any(not math.isfinite(x) for x in feats.values()):
        raise StudyError("NONFINITE_FEATURE")
    labels = {"pullback": pullback, "readvance": readvance, "rebuild": rebuild}
    screen = {"g1_w_gt_y": g1, "g2_veto": g2, "model_eligible": eligible,
              "raw_b1_bbi_w_y_j13": bool(bbi > white > yellow and j <= 13),
              **labels}
    extra = {"anchor_date": values[anchor_idx]["trade_date"] if anchor is not None else None,
             "anchor_age": anchor_age, "market_type": "A_SHARE", "d_close": close,
             "d_low": low, "d_high": high, "d_volume": volume,
             "yellow_line": yellow, "white_line": white,
             "previous10_high": prior10_high, "weak_labels": labels,
             "screen": screen, "recent_below_y_pair": recent_pair,
             "key_anchor_available": anchor is not None,
             "hard_pool_score": {
                 "pullback": -(recent5v / mean15v) - (recent5r / mean15r),
                 "readvance": d_vr5 + max(0.0, close / prior10_high - 1.0),
                 "rebuild": close / yellow - 1.0,
             }}
    return feats, extra


def _group_roll(frame: Any, column: str, window: int, *, shift: int = 0,
                operation: str = "mean") -> Any:
    """Pandas group rolling primitive; avoids per-security/per-day dict scans."""
    grouped = frame.groupby("ts_code", sort=False)[column]
    values = grouped.shift(shift) if shift else frame[column]
    by_code = values.groupby(frame["ts_code"], sort=False)
    def roll(series: Any) -> Any:
        rolling = series.rolling(window, min_periods=window)
        return getattr(rolling, operation)()
    return by_code.transform(roll)


def _vectorize_rows(frame: Any, *, start_date: str, asof_date: str,
                    stats_start: str = STATS_START) -> tuple[Any, dict[str, Any]]:
    """Build D-only features, weak labels, and market-session outcomes in bulk."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    numeric = ["open", "high", "low", "close", "vol", "pct_chg", "bbi", "j",
               "zge_white_line", "zge_yellow_line"]
    for name in numeric:
        out[name] = pd.to_numeric(out[name], errors="coerce")
    grouped = out.groupby("ts_code", sort=False)
    out["_seq"] = grouped.cumcount().astype("int32")
    out["_prev_close"] = grouped["close"].shift(1)
    out["_ret1"] = out["close"] / out["_prev_close"] - 1.0
    out["_prior5v"] = _group_roll(out, "vol", 5, shift=1)
    out["_prior15v"] = _group_roll(out, "vol", 15, shift=5)
    out["_prior15r"] = _group_roll(
        out.assign(_bar_range=(out["high"] - out["low"]) / out["close"]),
        "_bar_range", 15, shift=5,
    )
    out["_recent5v"] = _group_roll(out, "vol", 5)
    out["_recent5r"] = _group_roll(
        out.assign(_bar_range=(out["high"] - out["low"]) / out["close"]),
        "_bar_range", 5,
    )
    out["_d_vr5"] = out["vol"] / out["_prior5v"].replace(0, np.nan)
    out["_d_range"] = (out["high"] - out["low"]) / out["_prev_close"]
    out["_prior10high"] = _group_roll(out, "high", 10, shift=1, operation="max")
    out["_prior20high"] = _group_roll(out, "high", 20, shift=1, operation="max")
    out["_high30"] = _group_roll(out, "high", 30, operation="max")
    for days in (5, 20, 60):
        out[f"_ret{days}"] = out["close"] / grouped["close"].shift(days) - 1.0
    out["_upper_wick"] = (out["high"] - out[["open", "close"]].max(axis=1)) / out["_prev_close"]
    out["_close_yellow"] = out["close"] / out["zge_yellow_line"] - 1.0
    out["_drawdown30"] = out["close"] / out["_high30"] - 1.0
    out["_amp"] = (out["high"] - out["low"]) / out["_prev_close"]

    # The nearest qualifying prior K is selected from the preceding 40 bars.
    key_candidate = (out["_ret1"].ge(0.035) & out["_d_vr5"].ge(1.2)
                     & out["_prior5v"].gt(0))
    out["_key_candidate_seq"] = out["_seq"].where(key_candidate)
    key_prior = out.groupby("ts_code", sort=False)["_key_candidate_seq"].shift(1)
    out["_anchor_seq"] = key_prior.groupby(out["ts_code"], sort=False).transform(
        lambda series: series.rolling(40, min_periods=1).max())
    anchors = out.loc[key_candidate, ["ts_code", "_seq", "trade_date", "low", "_ret1", "_d_vr5"]].copy()
    anchors.rename(columns={"_seq": "_anchor_seq", "trade_date": "_anchor_date",
                            "low": "_anchor_low", "_ret1": "_anchor_return",
                            "_d_vr5": "_anchor_vr5"}, inplace=True)
    anchors["_anchor_seq"] = anchors["_anchor_seq"].astype(float)
    out = out.merge(anchors, how="left", on=["ts_code", "_anchor_seq"], sort=False,
                    validate="many_to_one")
    out.sort_values(["ts_code", "trade_date"], kind="mergesort", inplace=True)
    out.reset_index(drop=True, inplace=True)
    out["_anchor_available"] = out["_anchor_seq"].notna()
    out["_anchor_age"] = out["_seq"] - out["_anchor_seq"]
    out["_anchor_close_loss"] = (out["close"] < out["_anchor_low"]) & out["_anchor_available"]
    out["_any_anchor_close_loss"] = out.groupby(["ts_code", "_anchor_seq"], sort=False, dropna=True)[
        "_anchor_close_loss"].cummax()
    out["_low_held_anchor"] = (out["_anchor_available"] & (out["low"] > out["_anchor_low"])
                                & ~out["_any_anchor_close_loss"].fillna(False).astype(bool))

    below = out["close"] < out["zge_yellow_line"]
    above_both = ((out["close"] > out["zge_yellow_line"])
                  & (out["close"] > out["zge_white_line"]))
    previous_below = below.groupby(out["ts_code"], sort=False).shift(1).fillna(False)
    previous_above_both = above_both.groupby(out["ts_code"], sort=False).shift(1).fillna(False)
    out["_below_pair"] = below & previous_below
    out["_above_pair"] = above_both & previous_above_both
    out["_recent_below_pair"] = _group_roll(
        out.assign(_below_pair_num=out["_below_pair"].astype(float)),
        "_below_pair_num", 4, operation="max",
    ).fillna(0).gt(0)
    out["_below_pair_seq"] = out["_seq"].where(out["_below_pair"])
    # Pair endpoints at ages 6..24 mean both bars lie in D-25..D-6.
    prior_pair_source = out.groupby("ts_code", sort=False)["_below_pair_seq"].shift(6)
    out["_prior_pair_end_seq"] = prior_pair_source.groupby(out["ts_code"], sort=False).transform(
        lambda series: series.rolling(19, min_periods=1).max())
    out["_above_pair_seq"] = out["_seq"].where(out["_above_pair"])
    out["_latest_repair_seq"] = out.groupby("ts_code", sort=False)["_above_pair_seq"].ffill()
    out["_latest_below_pair_seq"] = out.groupby("ts_code", sort=False)["_below_pair_seq"].ffill()
    out["_rebuild_structure"] = (
        out["_prior_pair_end_seq"].notna()
        & (out["_latest_repair_seq"] > out["_prior_pair_end_seq"])
        & (out["_latest_below_pair_seq"].fillna(-1) <= out["_latest_repair_seq"])
        & above_both
    )

    ohlc_line_valid = (
        out[["open", "high", "low", "close", "zge_white_line", "zge_yellow_line"]].notna().all(axis=1)
        & out[["open", "high", "low", "close", "zge_white_line", "zge_yellow_line"]].gt(0).all(axis=1)
        & (out["high"] >= out[["open", "close", "low"]].max(axis=1))
        & (out["low"] <= out[["open", "close", "high"]].min(axis=1))
    )
    drow_valid = (ohlc_line_valid & out["vol"].gt(0) & out["bbi"].notna() & out["bbi"].gt(0))
    history_ready = out[["_ret5", "_ret20", "_ret60", "_prior15v", "_prior15r",
                         "_recent5v", "_recent5r", "_prior10high", "_prior20high", "_high30"]].notna().all(axis=1)
    out["feature_ready"] = drow_valid & history_ready
    line_valid = (out["zge_white_line"].notna() & out["zge_yellow_line"].notna()
                  & out["zge_white_line"].gt(0) & out["zge_yellow_line"].gt(0))
    out["g1_w_gt_y"] = line_valid & out["zge_white_line"].gt(out["zge_yellow_line"])
    out["g2_veto"] = ohlc_line_valid & out["vol"].ge(0) & (
        (out["_close_yellow"].ge(0.35 - BOUNDARY_EPS)
         & (out["_upper_wick"].ge(0.03 - BOUNDARY_EPS) | out["close"].lt(out["open"])) )
        | (out["_close_yellow"].ge(0.25 - BOUNDARY_EPS)
           & out["_upper_wick"].ge(0.04 - BOUNDARY_EPS)
           & out["_d_vr5"].ge(1.5 - BOUNDARY_EPS))
        | (out["_drawdown30"].le(-0.22 + BOUNDARY_EPS)
           & out["_amp"].ge(0.08 - BOUNDARY_EPS))
    )
    out["model_eligible"] = out["feature_ready"] & out["g1_w_gt_y"] & ~out["g2_veto"]
    out["raw_b1_known"] = (ohlc_line_valid & out["bbi"].notna() & out["bbi"].gt(0)
                           & out["j"].notna())
    out["raw_b1_bbi_w_y_j13"] = (out["raw_b1_known"] & out["bbi"].gt(out["zge_white_line"])
                                  & out["zge_white_line"].gt(out["zge_yellow_line"])
                                  & out["j"].le(13))
    mean5v = out["_prior5v"]
    prior5r = _group_roll(
        out.assign(_bar_range=(out["high"] - out["low"]) / out["close"]),
        "_bar_range", 5, shift=1,
    )
    prior5_preceding15v = _group_roll(out, "vol", 15, shift=6)
    prior5_preceding15r = _group_roll(
        out.assign(_bar_range=(out["high"] - out["low"]) / out["close"]),
        "_bar_range", 15, shift=6,
    )
    prior5_compacted = ((prior5_preceding15v > 0) & (prior5_preceding15r > 0)
                        & (mean5v <= prior5_preceding15v) & (prior5r <= prior5_preceding15r))
    anchor_ok = (~out["_anchor_available"] | out["_low_held_anchor"])
    out["pullback"] = (
        out["model_eligible"] & out["_anchor_available"] & out["_low_held_anchor"]
        & out["close"].ge(out["zge_yellow_line"]) & out["close"].le(out["_prior10high"])
        & ~out["_recent_below_pair"] & mean5v.gt(0) & out["_d_vr5"].le(1.0)
        & ((out["high"] - out["low"]) / out["close"]).le(out["_prior15r"])
        & (out["_recent5v"] / out["_prior15v"]).le(0.8)
        & (out["_recent5r"] / out["_prior15r"]).le(0.85)
    )
    out["readvance"] = (
        out["model_eligible"] & out["_anchor_available"] & out["_low_held_anchor"]
        & out["_anchor_age"].ge(4) & prior5_compacted & out["close"].gt(out["_prior10high"])
        & out["_d_vr5"].ge(1.2) & ~out["_recent_below_pair"]
    )
    out["rebuild"] = out["model_eligible"] & out["_rebuild_structure"] & anchor_ok
    out["union"] = out[["pullback", "readvance", "rebuild"]].any(axis=1)

    out["ret_1"] = out["_ret1"]
    out["ret_5"] = out["_ret5"]
    out["ret_20"] = out["_ret20"]
    out["ret_60"] = out["_ret60"]
    out["d_range_prev_close"] = out["_d_range"]
    out["d_upper_wick_prev_close"] = out["_upper_wick"]
    out["d_open_close_prev_close"] = (out["close"] - out["open"]) / out["_prev_close"]
    out["close_yellow_pct"] = out["_close_yellow"]
    out["close_white_pct"] = out["close"] / out["zge_white_line"] - 1.0
    out["white_yellow_spread_pct"] = out["zge_white_line"] / out["zge_yellow_line"] - 1.0
    out["close_bbi_pct"] = out["close"] / out["bbi"] - 1.0
    out["vol5_vs_prior15"] = out["_recent5v"] / out["_prior15v"]
    out["range5_vs_prior15"] = out["_recent5r"] / out["_prior15r"]
    out["d_vr5"] = out["_d_vr5"]
    out["d_range_vs_prior15"] = ((out["high"] - out["low"]) / out["close"]) / out["_prior15r"]
    out["close_vs_prior10_high"] = out["close"] / out["_prior10high"] - 1.0
    out["close_vs_prior20_high"] = out["close"] / out["_prior20high"] - 1.0
    out["close_vs_trailing30_high"] = out["_drawdown30"]
    out["anchor_return"] = out["_anchor_return"].fillna(-1.0)
    out["anchor_vr5"] = out["_anchor_vr5"].fillna(-1.0)
    out["close_vs_anchor_low"] = (out["close"] / out["_anchor_low"] - 1.0).where(out["_anchor_available"], -1.0)
    out["anchor_age"] = out["_anchor_age"].fillna(-1.0)
    out["low_held_anchor"] = out["_low_held_anchor"].astype(float)
    out["recent_below_pair"] = out["_recent_below_pair"].astype(float)
    out["prior5_vol_vs_prior15"] = mean5v / prior5_preceding15v
    out["prior5_range_vs_prior15"] = prior5r / prior5_preceding15r
    feature_values = out[list(FEATURE_NAMES)].to_numpy(dtype=float)
    out["feature_vector_finite"] = np.isfinite(feature_values).all(axis=1)
    out["feature_ready"] &= out["feature_vector_finite"]
    out["model_eligible"] = out["feature_ready"] & out["g1_w_gt_y"] & ~out["g2_veto"]
    for branch in ("pullback", "readvance", "rebuild"):
        out[branch] &= out["model_eligible"]
    out["union"] = out[["pullback", "readvance", "rebuild"]].any(axis=1)
    # No model column is a raw J/B1/B2/B3/BUY field or a future outcome.
    out["hard_score_pullback"] = -out["vol5_vs_prior15"] - out["range5_vs_prior15"]
    out["hard_score_readvance"] = out["d_vr5"].clip(lower=0) + out["close_vs_prior10_high"].clip(lower=0)
    out["hard_score_rebuild"] = out["close_yellow_pct"]

    visible = out["trade_date"].between(start_date, asof_date)
    out = out.loc[visible].copy()
    dates = sorted(out["trade_date"].unique().tolist())
    session_id = {day: idx for idx, day in enumerate(dates)}
    out["_market_session"] = out["trade_date"].map(session_id).astype("int32")
    # The target side is indexed by market-wide session number. A suspended or
    # absent security on T+n remains censored; its next available bar is not used.
    valid_bar = (out[["open", "high", "low", "close", "vol"]].notna().all(axis=1)
                 & out[["open", "high", "low", "close"]].gt(0).all(axis=1)
                 & out["vol"].gt(0)
                 & out["high"].ge(out[["open", "close", "low"]].max(axis=1))
                 & out["low"].le(out[["open", "close", "high"]].min(axis=1)))
    lookup = out.loc[valid_bar].set_index(["ts_code", "_market_session"])[["close"]]
    codes = out["ts_code"].to_numpy()
    session = out["_market_session"].to_numpy()
    close_d = out["close"].to_numpy(dtype=float)
    running_peak = close_d.copy()
    min_drawdown = np.zeros(len(out), dtype=float)
    path_complete = np.ones(len(out), dtype=bool)
    for offset in range(1, max(HORIZONS) + 1):
        target_index = pd.MultiIndex.from_arrays([codes, session + offset],
                                                 names=["ts_code", "_market_session"])
        future = lookup.reindex(target_index)
        future_close = future["close"].to_numpy(dtype=float)
        valid_path_bar = np.isfinite(future_close)
        path_complete &= valid_path_bar
        running_peak = np.maximum(running_peak, np.where(np.isfinite(future_close), future_close, running_peak))
        dd = np.divide(future_close, running_peak, out=np.full(len(out), np.nan),
                       where=np.isfinite(future_close) & (running_peak > 0)) - 1.0
        min_drawdown = np.minimum(min_drawdown, np.nan_to_num(dd, nan=0.0))
        if offset in HORIZONS:
            returns = future_close / close_d - 1.0
            out[f"return_t{offset}"] = returns
            observable_path = path_complete & np.isfinite(returns)
            out[f"min_path_dd_t{offset}"] = np.where(observable_path, min_drawdown, np.nan)
            out[f"path_observable_t{offset}"] = observable_path
    out.attrs["market_dates"] = dates
    return out, {"market_session_count": len(dates), "feature_names": list(FEATURE_NAMES),
                 "model_feature_contract": "D_and_prior_only; no J/B1/B2/B3/BUY/future fields",
                 "feature_ready_rows": int(out["feature_ready"].sum()),
                 "g1_pass_rows": int(out["g1_w_gt_y"].sum()),
                 "g2_veto_rows": int(out["g2_veto"].sum()),
                 "model_eligible_rows": int(out["model_eligible"].sum())}


def _episode_split(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Remove same-security prior-K anchor groups straddling the fixed date split."""
    import numpy as np
    out = frame.copy()
    anchor = out["_anchor_date"].fillna("").astype(str)
    out["_episode_id"] = np.where(anchor.ne(""), out["ts_code"] + "|K|" + anchor,
                                  out["ts_code"] + "|NO_K|" + out["trade_date"])
    train = out["model_eligible"] & out["trade_date"].between(DEFAULT_START, TRAIN_END)
    oos = out["model_eligible"] & out["trade_date"].between(OOS_START, DEFAULT_ASOF)
    train_groups = set(out.loc[train, "_episode_id"])
    oos_groups = set(out.loc[oos, "_episode_id"])
    crossing = train_groups & oos_groups
    train_keep = train & ~out["_episode_id"].isin(crossing)
    # Purge the training observations for crossing anchor groups. Their OOS
    # successors remain eligible once the training side has been removed.
    oos_keep = oos
    return out, {"cross_split_anchor_group_count": len(crossing),
                 "train_eligible_before_group_guard": int(train.sum()),
                 "oos_eligible_before_group_guard": int(oos.sum()),
                 "train_dropped_for_cross_split_anchor": int((train & ~train_keep).sum()),
                 "oos_retained_after_training_purge": int(oos_keep.sum()),
                 "train_mask": train_keep, "oos_safe_mask": oos_keep}


def _fit_models(frame: Any, split: dict[str, Any], *,
                progress: Callable[[str, str, dict[str, Any]], None] | None = None) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Perform the four fixed model fits once, with all transforms fit on TRAIN only."""
    import numpy as np
    import sklearn
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                                 roc_auc_score)
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    train_mask = split["train_mask"]
    safe_oos_mask = split["oos_safe_mask"]
    x_train_all = frame.loc[train_mask, list(FEATURE_NAMES)].to_numpy(dtype=float)
    if not len(x_train_all):
        raise StudyError("TRAIN_ELIGIBLE_EMPTY_AFTER_ANCHOR_GUARD")
    if not np.isfinite(x_train_all).all():
        raise StudyError("NONFINITE_TRAIN_FEATURES")
    models: dict[str, Any] = {}
    report: dict[str, Any] = {"schema": MODEL_SCHEMA, "feature_names": list(FEATURE_NAMES),
                              "sklearn_version": sklearn.__version__, "fit_count": 0,
                              "training": {}, "oos_weak_label_metrics": {},
                              "split_guard": {key: value for key, value in split.items()
                                              if not key.endswith("mask")}}
    predictions = frame[["ts_code", "trade_date", "model_eligible", "pullback", "readvance", "rebuild"]].copy()
    oos_predict_mask = frame["model_eligible"] & frame["trade_date"].between(OOS_START, DEFAULT_ASOF)
    x_oos_all = frame.loc[oos_predict_mask, list(FEATURE_NAMES)].to_numpy(dtype=float)
    if not np.isfinite(x_oos_all).all():
        raise StudyError("NONFINITE_OOS_FEATURES")
    oos_index = frame.index[oos_predict_mask]

    for track in ("pullback", "readvance"):
        y = frame.loc[train_mask, track].astype(int).to_numpy()
        if len(set(y.tolist())) != 2:
            raise StudyError(f"TRAIN_WEAK_LABEL_REQUIRES_BOTH_CLASSES:{track}")
        weights = np.where(y == 1, len(y) / (2.0 * y.sum()),
                           len(y) / (2.0 * (len(y) - y.sum())))
        lr = Pipeline([
            ("scale", StandardScaler()),
            ("classifier", LogisticRegression(C=1.0, penalty="l2", solver="lbfgs",
                                               class_weight="balanced", random_state=0,
                                               max_iter=1000, tol=1e-8)),
        ])
        hgb = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05,
                                             max_leaf_nodes=7, max_depth=3,
                                             l2_regularization=1.0,
                                             early_stopping=False, random_state=0)
        if progress:
            progress(f"{track}_lr", "FIT_STARTED", {"training_rows": int(len(y)), "positive": int(y.sum())})
        lr.fit(x_train_all, y)
        report["fit_count"] += 1
        if progress:
            progress(f"{track}_lr", "FIT_COMPLETED", {"fit_count": report["fit_count"]})
        if progress:
            progress(f"{track}_hgb", "FIT_STARTED", {"training_rows": int(len(y)), "positive": int(y.sum())})
        hgb.fit(x_train_all, y, sample_weight=weights)
        report["fit_count"] += 1
        if progress:
            progress(f"{track}_hgb", "FIT_COMPLETED", {"fit_count": report["fit_count"]})
        models[f"{track}_lr"] = lr
        models[f"{track}_hgb"] = hgb
        report["training"][track] = {"n": int(len(y)), "positive": int(y.sum()),
                                     "negative": int(len(y) - y.sum()),
                                     "positive_fraction": float(y.mean())}
        for model_name, model in (("lr", lr), ("hgb", hgb)):
            column = f"p_{track}_{model_name}"
            probability = model.predict_proba(x_oos_all)[:, 1]
            predictions[column] = np.nan
            predictions.loc[oos_index, column] = probability
            eval_mask = safe_oos_mask
            y_eval = frame.loc[eval_mask, track].astype(int).to_numpy()
            if not len(y_eval):
                metrics = {"n": 0, "status": "NO_SAFE_OOS_GROUPS"}
            else:
                x_eval = frame.loc[eval_mask, list(FEATURE_NAMES)].to_numpy(dtype=float)
                p_eval = model.predict_proba(x_eval)[:, 1]
                metrics = {"n": int(len(y_eval)), "positive": int(y_eval.sum()),
                           "negative": int(len(y_eval) - y_eval.sum()),
                           "accuracy_at_0_5": float(accuracy_score(y_eval, p_eval >= 0.5)),
                           "brier": float(brier_score_loss(y_eval, p_eval)),
                           "average_precision": float(average_precision_score(y_eval, p_eval))}
                metrics["roc_auc"] = float(roc_auc_score(y_eval, p_eval)) if len(set(y_eval)) == 2 else None
            report["oos_weak_label_metrics"][f"{track}_{model_name}"] = metrics
    if report["fit_count"] != 4:
        raise StudyError("REAL_MODEL_FIT_COUNT_MISMATCH")
    report["fit_policy"] = {
        "fit_count": 4, "tracks": ["pullback", "readvance"],
        "estimators": {
            "lr": {"type": "LogisticRegression", "C": 1.0, "penalty": "l2",
                   "solver": "lbfgs", "class_weight": "balanced", "random_state": 0,
                   "max_iter": 1000, "tol": 1e-8, "scaler": "StandardScaler_fit_on_train_only"},
            "hgb": {"type": "HistGradientBoostingClassifier", "max_iter": 100,
                    "learning_rate": 0.05, "max_leaf_nodes": 7, "max_depth": 3,
                    "l2_regularization": 1.0, "early_stopping": False,
                    "random_state": 0, "balanced_sample_weight": True},
        },
        "tuning_or_B_models": 0,
    }
    predictions.index = frame.index
    return models, report, predictions


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _append_progress(path: Path, stage: str, status: str,
                     details: dict[str, Any] | None = None) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(), "stage": stage,
             "status": status, "details": details or {}}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True,
                                allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_rows(path: Path, rows: Any) -> int:
    import pandas as pd
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return int(len(frame))


def _validate_output_dir(output_dir: Path, data_root: Path) -> Path:
    output_dir = Path(output_dir)
    data_root = Path(data_root).resolve()
    if not output_dir.is_absolute() or output_dir.exists() or output_dir.is_symlink():
        raise StudyError("OUTPUT_DIR_MUST_BE_NEW_ABSOLUTE_PATH")
    resolved = output_dir.parent.resolve() / output_dir.name
    if resolved == data_root or data_root in resolved.parents or resolved in data_root.parents:
        raise StudyError("OUTPUT_DIR_OVERLAPS_PANEL_DATA_ROOT")
    if not resolved.parent.is_dir():
        raise StudyError("OUTPUT_DIR_PARENT_MISSING")
    return resolved


def _daily_screen(frame: Any, *, start_date: str) -> Any:
    import pandas as pd
    rows = []
    view = frame.loc[frame["trade_date"].ge(start_date)]
    for day, group in view.groupby("trade_date", sort=True):
        d_ret = group["pct_chg"]
        valid_breadth = d_ret.notna() & group["vol"].gt(0) & group["close"].gt(0)
        up = int((d_ret[valid_breadth] > 0).sum())
        breadth_n = int(valid_breadth.sum())
        breadth = up / breadth_n if breadth_n else None
        rank_sources = set(group["top200_rank_source"].astype(str))
        rank_source = next(iter(rank_sources)) if len(rank_sources) == 1 else "MIXED_RANK_SOURCES"
        rows.append({
            "trade_date": day,
            "a_share_rows": int(len(group)),
            "feature_ready_count": int(group["feature_ready"].sum()),
            "feature_gap_count": int((~group["feature_ready"]).sum()),
            "g1_w_gt_y_count": int(group["g1_w_gt_y"].sum()),
            "g2_veto_count": int(group["g2_veto"].sum()),
            "g1_g2_model_eligible_count": int(group["model_eligible"].sum()),
            "raw_b1_bbi_gt_white_gt_yellow_j_le_13_count": int(group["raw_b1_bbi_w_y_j13"].sum()),
            "raw_b1_j_unknown_count": int((~group["raw_b1_known"]).sum()),
            "pullback_count": int(group["pullback"].sum()),
            "readvance_count": int(group["readvance"].sum()),
            "rebuild_count": int(group["rebuild"].sum()),
            "union_count": int(group["union"].sum()),
            "top200_count": int(group["top200_membership"].fillna(False).sum()),
            "top200_rank_source": rank_source,
            "top200_official_member_count": int(group["top200_rank_source"].eq("OFFICIAL_TOP200_OVERRIDE").sum()),
            "top200_historical_derived_count": int(group["top200_rank_source"].eq("REALIZED_D_PCT_CHG").sum()),
            "market_up_count": up,
            "market_breadth_denominator": breadth_n,
            "market_breadth_up_fraction": breadth,
            "market_breadth_over_50pct": (breadth > 0.5) if breadth is not None else None,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def _apply_top200_ranks(frame: Any, official: dict[str, dict[str, Any]],
                        official_meta: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Derive historical close-change ranks; replace the official snapshot day."""
    import numpy as np
    out = frame.copy()
    valid_trade = (out["pct_chg"].notna() & out["vol"].gt(0) & out["close"].gt(0)
                   & out[["open", "high", "low", "close"]].notna().all(axis=1)
                   & out["high"].ge(out[["open", "close", "low"]].max(axis=1))
                   & out["low"].le(out[["open", "close", "high"]].min(axis=1)))
    out["_valid_traded_for_rank"] = valid_trade
    out["historical_top200_rank"] = np.nan
    for _day_value, group in out.groupby("trade_date", sort=True):
        valid = group.loc[group["_valid_traded_for_rank"]]
        ranked = valid.sort_values(["pct_chg", "ts_code"], ascending=[False, True], kind="mergesort")
        out.loc[ranked.index, "historical_top200_rank"] = np.arange(1, len(ranked) + 1, dtype=int)
    out["top200_rank"] = out["historical_top200_rank"]
    out["top200_membership"] = out["historical_top200_rank"].le(200)
    out["top200_rank_source"] = np.where(out["_valid_traded_for_rank"],
                                         "REALIZED_D_PCT_CHG", "UNRANKED_NO_VALID_TRADE")
    official_date = official_meta["asof_date"]
    official_day = out["trade_date"].eq(official_date)
    override = out.loc[official_day, "ts_code"].map({key: int(value["rank"]) for key, value in official.items()})
    override = override.where(out.loc[official_day, "_valid_traded_for_rank"])
    out.loc[official_day, "top200_rank"] = override.to_numpy()
    out.loc[official_day, "top200_membership"] = override.notna().to_numpy()
    out.loc[official_day, "top200_rank_source"] = np.where(override.notna(),
                                                           "OFFICIAL_TOP200_OVERRIDE",
                                                           np.where(out.loc[official_day, "_valid_traded_for_rank"],
                                                                    "OFFICIAL_TOP200_NOT_IN_LIST",
                                                                    "OFFICIAL_DAY_NO_VALID_TRADE"))
    return out, {"official_asof_date": official_date,
                 "official_override_rows_present_in_panel": int((official_day & out["top200_membership"].fillna(False)).sum()),
                 "historical_rank_method": "descending_authoritative_pct_chg_for_realized_D; ties_by_ts_code",
                 "official_rank_override_applied": bool(official_day.any())}


def _join_future_top200(frame: Any) -> Any:
    """Attach exact T+1 realized daily and T+5 cumulative Top200 membership."""
    import numpy as np
    import pandas as pd
    out = frame.copy()
    ranked = out.loc[out["_valid_traded_for_rank"]].set_index(
        ["ts_code", "_market_session"])[["top200_rank", "top200_membership", "top200_rank_source"]]
    index1 = pd.MultiIndex.from_arrays([out["ts_code"].to_numpy(),
                                        out["_market_session"].to_numpy() + 1],
                                       names=["ts_code", "_market_session"])
    t1 = ranked.reindex(index1)
    out["top200_rank_t1"] = t1["top200_rank"].to_numpy()
    out["top200_member_t1"] = t1["top200_membership"].to_numpy()
    out["top200_source_t1"] = t1["top200_rank_source"].to_numpy()

    out["top200_rank_t5"] = np.nan
    out["top200_member_t5"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
    for _day_value, group in out.loc[out["return_t5"].notna()].groupby("trade_date", sort=True):
        ordered = group.sort_values(["return_t5", "ts_code"], ascending=[False, True], kind="mergesort")
        ranks = np.arange(1, len(ordered) + 1, dtype=int)
        out.loc[ordered.index, "top200_rank_t5"] = ranks
        out.loc[ordered.index, "top200_member_t5"] = pd.array(ranks <= 200, dtype="boolean")
    breadth_ret = out["pct_chg"]
    valid_breadth = breadth_ret.notna() & out["vol"].gt(0) & out["close"].gt(0)
    breadth = (breadth_ret[valid_breadth].gt(0).groupby(out.loc[valid_breadth, "trade_date"])
               .agg(["sum", "count"]))
    breadth["fraction"] = breadth["sum"] / breadth["count"].replace(0, np.nan)
    out["market_breadth_up_fraction"] = out["trade_date"].map(breadth["fraction"])
    out["market_breadth_over_50pct"] = out["market_breadth_up_fraction"].gt(0.5)
    return out


def _metric_row(selected: Any, *, horizon: int, branch: str, trade_date: str,
                ranker: str | None = None, top_k: int | None = None) -> dict[str, Any]:
    returns = selected[f"return_t{horizon}"].dropna()
    paths = selected[f"min_path_dd_t{horizon}"].dropna()
    n = int(len(selected))
    observed = int(len(returns))
    positive = int((returns > 0).sum())
    over5 = int((returns > 0.05).sum())
    if horizon == 1:
        benchmark = selected["top200_member_t1"]
        benchmark_offset = 1
    elif horizon == 5:
        benchmark = selected["top200_member_t5"]
        benchmark_offset = 5
    else:
        benchmark = None
        benchmark_offset = None
    if benchmark is None:
        benchmark_known = benchmark_hits = benchmark_noise = 0
        benchmark_fraction = None
    else:
        known = benchmark.notna()
        benchmark_known = int(known.sum())
        benchmark_hits = int((benchmark[known].astype(bool)).sum())
        benchmark_noise = int((~benchmark[known].astype(bool)).sum())
        benchmark_fraction = benchmark_hits / benchmark_known if benchmark_known else None
    row = {
        "trade_date": trade_date, "branch": branch, "horizon_market_sessions": horizon,
        "candidate_count": n, "observable_count": observed,
        "censored_count": n - observed,
        "mean_return": float(returns.mean()) if observed else None,
        "median_return": float(returns.median()) if observed else None,
        "return_gt_0_count": positive,
        "return_gt_0_fraction": positive / observed if observed else None,
        "return_gt_5pct_count": over5,
        "return_gt_5pct_fraction": over5 / observed if observed else None,
        "minimum_path_drawdown": float(paths.min()) if len(paths) else None,
        "path_observable_count": int(len(paths)),
        "path_censored_count": n - int(len(paths)),
        "drawdown_measure": "MIN_D_TO_TN_CLOSE_VS_RUNNING_CLOSE_PEAK",
        "censor_policy": "EXACT_MARKET_SESSION_OFFSET_ONLY",
        "top200_benchmark_offset": benchmark_offset,
        "top200_benchmark_eligible_count": benchmark_known,
        "top200_hit_count": benchmark_hits,
        "top200_noise_count": benchmark_noise,
        "top200_hit_fraction": benchmark_fraction,
    }
    if ranker is not None:
        row["ranker"] = ranker
    if top_k is not None:
        row["top_k"] = top_k
        row["selected_count"] = n
    return row


def _daily_strategy_metrics(frame: Any, *, stats_start: str) -> Any:
    import pandas as pd
    rows = []
    view = frame.loc[frame["trade_date"].ge(stats_start)]
    branches = {
        "W_GT_Y": "g1_w_gt_y", "RAW_B1": "raw_b1_bbi_w_y_j13",
        "PULLBACK": "pullback", "READVANCE": "readvance", "REBUILD": "rebuild", "UNION": "union",
    }
    scopes = [("ALL_D", view), ("BREADTH_GT_50", view.loc[view["market_breadth_over_50pct"]])]
    for scope, scoped in scopes:
        for branch, column in branches.items():
            candidates = scoped.loc[scoped[column]]
            for day, group in candidates.groupby("trade_date", sort=True):
                for horizon in HORIZONS:
                    row = _metric_row(group, horizon=horizon, branch=branch, trade_date=day)
                    row["breadth_filter"] = scope
                    rows.append(row)
    return pd.DataFrame(rows)


def _pooled_strategy_metrics(frame: Any, *, stats_start: str) -> list[dict[str, Any]]:
    import pandas as pd
    view = frame.loc[frame["trade_date"].ge(stats_start)]
    branches = {
        "W_GT_Y": "g1_w_gt_y", "RAW_B1": "raw_b1_bbi_w_y_j13",
        "PULLBACK": "pullback", "READVANCE": "readvance", "REBUILD": "rebuild", "UNION": "union",
    }
    scopes = [("ALL_D", view), ("BREADTH_GT_50", view.loc[view["market_breadth_over_50pct"]])]
    rows = []
    for scope, scoped in scopes:
        for branch, column in branches.items():
            selected = scoped.loc[scoped[column]]
            for horizon in HORIZONS:
                returns = selected[f"return_t{horizon}"].dropna()
                paths = selected[f"min_path_dd_t{horizon}"].dropna()
                if horizon == 1:
                    benchmark = selected["top200_member_t1"]
                elif horizon == 5:
                    benchmark = selected["top200_member_t5"]
                else:
                    benchmark = None
                if benchmark is None:
                    eligible = hits = noise = 0
                else:
                    known = benchmark.notna()
                    eligible = int(known.sum())
                    hits = int(benchmark[known].astype(bool).sum())
                    noise = int((~benchmark[known].astype(bool)).sum())
                rows.append({
                    "breadth_filter": scope, "branch": branch,
                    "horizon_market_sessions": horizon,
                    "day_count": int(selected["trade_date"].nunique()),
                    "candidate_count": int(len(selected)),
                    "observable_count": int(len(returns)),
                    "censored_count": int(len(selected) - len(returns)),
                    "pooled_mean_return": float(returns.mean()) if len(returns) else None,
                    "pooled_exact_median_return": float(returns.median()) if len(returns) else None,
                    "return_gt_0_count": int((returns > 0).sum()),
                    "return_gt_5pct_count": int((returns > 0.05).sum()),
                    "pooled_minimum_path_drawdown": float(paths.min()) if len(paths) else None,
                    "path_observable_count": int(len(paths)),
                    "top200_benchmark_offset": horizon if horizon in (1, 5) else None,
                    "top200_eligible_count": eligible, "top200_hit_count": hits,
                    "top200_noise_count": noise,
                    "top200_hit_fraction": hits / eligible if eligible else None,
                })
    return rows


def _oos_topk_metrics(frame: Any) -> Any:
    import pandas as pd
    rows = []
    pooled: dict[tuple[str, str, int, int], dict[str, Any]] = defaultdict(
        lambda: {"returns": [], "drawdowns": [], "top200_hits": 0, "top200_noise": 0,
                 "top200_eligible": 0, "candidate_count": 0, "day_count": 0})
    view = frame.loc[frame["trade_date"].ge(OOS_START) & frame["model_eligible"]]
    plans = {
        "pullback": [("LR", "p_pullback_lr"), ("HGB", "p_pullback_hgb"),
                     ("HARD_POOL", "hard_score_pullback")],
        "readvance": [("LR", "p_readvance_lr"), ("HGB", "p_readvance_hgb"),
                      ("HARD_POOL", "hard_score_readvance")],
        "rebuild": [("HARD_POOL", "hard_score_rebuild")],
    }
    for day, all_eligible in view.groupby("trade_date", sort=True):
        for branch, rankers in plans.items():
            for ranker, score_column in rankers:
                if ranker == "HARD_POOL":
                    pool = all_eligible.loc[all_eligible[branch]]
                else:
                    pool = all_eligible
                if len(pool) and pool[score_column].notna().any():
                    ranked = pool.sort_values([score_column, "ts_code"], ascending=[False, True],
                                              kind="mergesort")
                else:
                    ranked = pool.iloc[0:0]
                for top_k in (20, 50):
                    selected = ranked.head(top_k)
                    for horizon in HORIZONS:
                        rows.append(_metric_row(selected, horizon=horizon, branch=branch,
                                                trade_date=day, ranker=ranker, top_k=top_k))
                        key = (branch, ranker, top_k, horizon)
                        summary = pooled[key]
                        summary["candidate_count"] += int(len(selected))
                        summary["day_count"] += int(len(selected) > 0)
                        returns = selected[f"return_t{horizon}"].dropna()
                        summary["returns"].extend(returns.astype(float).tolist())
                        drawdowns = selected[f"min_path_dd_t{horizon}"].dropna()
                        summary["drawdowns"].extend(drawdowns.astype(float).tolist())
                        if horizon == 1:
                            benchmark = selected["top200_member_t1"]
                        elif horizon == 5:
                            benchmark = selected["top200_member_t5"]
                        else:
                            benchmark = None
                        if benchmark is not None:
                            known = benchmark.notna()
                            summary["top200_eligible"] += int(known.sum())
                            summary["top200_hits"] += int(benchmark[known].astype(bool).sum())
                            summary["top200_noise"] += int((~benchmark[known].astype(bool)).sum())
    daily = pd.DataFrame(rows)
    pooled_rows = []
    for (branch, ranker, top_k, horizon), summary in sorted(pooled.items()):
        returns = summary["returns"]
        pooled_rows.append({
            "branch": branch, "ranker": ranker, "top_k": top_k,
            "horizon_market_sessions": horizon, "day_count": summary["day_count"],
            "candidate_count": summary["candidate_count"], "observable_count": len(returns),
            "censored_count": summary["candidate_count"] - len(returns),
            "pooled_mean_return": float(pd.Series(returns).mean()) if returns else None,
            "pooled_exact_median_return": float(pd.Series(returns).median()) if returns else None,
            "pooled_minimum_path_drawdown": min(summary["drawdowns"]) if summary["drawdowns"] else None,
            "top200_eligible_count": summary["top200_eligible"],
            "top200_hit_count": summary["top200_hits"],
            "top200_noise_count": summary["top200_noise"],
            "top200_hit_fraction": (summary["top200_hits"] / summary["top200_eligible"]
                                     if summary["top200_eligible"] else None),
        })
    return daily, pooled_rows


def _audit_sample(frame: Any, *, target_count: int = 1600) -> Any:
    """Deterministic month x D-only weak-label stratification; never uses returns."""
    import pandas as pd
    view = frame.loc[frame["trade_date"].ge(OOS_START) & frame["model_eligible"]].copy()
    if not len(view):
        return view
    view["_month"] = view["trade_date"].str[:6]
    for name in ("pullback", "readvance", "rebuild"):
        view[name] = view[name].astype(bool)
    label_bits = (view["pullback"].astype(int).astype(str)
                  + view["readvance"].astype(int).astype(str)
                  + view["rebuild"].astype(int).astype(str))
    view["_stratum"] = view["_month"] + "|" + label_bits
    # Integer mixing of canonical code/date gives a stable deterministic order.
    code_num = pd.to_numeric(view["ts_code"].str.slice(0, 6), errors="coerce").fillna(0).astype("uint64")
    date_num = pd.to_numeric(view["trade_date"], errors="coerce").fillna(0).astype("uint64")
    view["_sample_key"] = (code_num * 11400714819323198485 + date_num * 14029467366897019727).astype("uint64")
    buckets: dict[str, list[int]] = {}
    for stratum, group in view.groupby("_stratum", sort=True):
        buckets[stratum] = group.sort_values(["_sample_key", "ts_code", "trade_date"],
                                             kind="mergesort").index.tolist()
    selected: list[int] = []
    depth = 0
    ordered_buckets = sorted(buckets)
    while len(selected) < min(target_count, len(view)):
        made_progress = False
        for stratum in ordered_buckets:
            values = buckets[stratum]
            if depth < len(values):
                selected.append(values[depth])
                made_progress = True
                if len(selected) >= target_count:
                    break
        if not made_progress:
            break
        depth += 1
    view = view.loc[selected].copy()
    view["audit_stratum"] = view["_stratum"]
    view.sort_values(["trade_date", "ts_code"], kind="mergesort", inplace=True)
    audit_columns = ["trade_date", "ts_code", "market_type", "audit_stratum",
                     "pullback", "readvance", "rebuild", "p_pullback_lr", "p_pullback_hgb",
                     "p_readvance_lr", "p_readvance_hgb", *FEATURE_NAMES]
    return view[audit_columns].reset_index(drop=True)


def _friday_rows(frame: Any, official: dict[str, dict[str, Any]], official_meta: dict[str, Any],
                 *, market_dates: list[str]) -> tuple[Any, dict[str, Any]]:
    import pandas as pd
    day = frame.loc[frame["trade_date"].eq(FRIDAY_D)].copy()
    if not len(day):
        raise StudyError(f"FRIDAY_REFERENCE_DAY_MISSING:{FRIDAY_D}")
    next_dates = [value for value in market_dates if value > FRIDAY_D]
    t1_day = next_dates[0] if next_dates else None
    official_matches_t1 = official_meta["asof_date"] == t1_day
    day["official_top200_rank"] = day["ts_code"].map({k: v["rank"] for k, v in official.items()})
    day["official_top200_change_pct"] = day["ts_code"].map({k: v["change_pct"] for k, v in official.items()})
    day["official_top200_name"] = day["ts_code"].map({k: v["name"] for k, v in official.items()})
    day["official_top200_asof_date"] = official_meta["asof_date"]
    day["official_rank_date_matches_market_t1"] = official_matches_t1
    day["market_t1_date"] = t1_day
    day["t1_return"] = day["return_t1"]
    day["t1_return_observable"] = day["return_t1"].notna()
    columns = ["trade_date", "ts_code", "market_type", "close", "feature_ready",
               "g1_w_gt_y", "g2_veto", "model_eligible", "raw_b1_bbi_w_y_j13",
               "pullback", "readvance", "rebuild", "union", "p_pullback_lr", "p_pullback_hgb",
               "p_readvance_lr", "p_readvance_hgb", "official_top200_rank",
               "historical_top200_rank", "top200_rank", "top200_rank_source",
               "official_top200_change_pct", "official_top200_name", "official_top200_asof_date",
               "official_rank_date_matches_market_t1", "market_t1_date", "t1_return",
               "t1_return_observable", "top200_rank_t1", "top200_member_t1",
               "top200_source_t1", "top200_rank_t5", "top200_member_t5"]
    return day[columns].sort_values("ts_code", kind="mergesort").reset_index(drop=True), {
        "reference_date": FRIDAY_D, "market_t1_date": t1_day,
        "official_top200_asof_date": official_meta["asof_date"],
        "official_rank_date_matches_market_t1": official_matches_t1,
        "observed_universe_rows": int(len(day)),
        "expected_universe_rows": 5572,
    }


def _save_model_state(path: Path, models: dict[str, Any], model_report: dict[str, Any],
                      panel_source: dict[str, Any], official_meta: dict[str, Any]) -> None:
    import joblib
    joblib.dump({"schema": MODEL_SCHEMA, "models": models,
                 "feature_names": list(FEATURE_NAMES), "fit_report": model_report,
                 "panel_source": panel_source, "official_top200_source": official_meta,
                 **FLAGS}, path, compress=3)


def run_once(*, data_root: Path, start_date: str = DEFAULT_START,
             asof_date: str = DEFAULT_ASOF, official_top200_path: Path,
             output_dir: Path) -> dict[str, Any]:
    """Read the current V4 generation, make four fixed fits, and write outputs."""
    start_date = _day(start_date, "start_date")
    asof_date = _day(asof_date, "asof_date")
    if start_date > TRAIN_END or asof_date < OOS_START or start_date > asof_date:
        raise StudyError("REQUESTED_DATES_DO_NOT_COVER_FIXED_TRAIN_AND_OOS_WINDOWS")
    if not data_root.is_absolute():
        raise StudyError("DATA_ROOT_MUST_BE_ABSOLUTE")
    output_dir = _validate_output_dir(output_dir, data_root)
    output_dir.mkdir(parents=False, exist_ok=False)
    progress_path = output_dir / "run_progress.jsonl"
    def progress(stage: str, status: str, details: dict[str, Any] | None = None) -> None:
        _append_progress(progress_path, stage, status, details)
    run_base: dict[str, Any] = {
        "schema": SCHEMA, "status": "RUNNING", "mode": "fit_and_evaluate",
        "start_date": start_date, "asof_date": asof_date,
        "fixed_windows": {"train_D_le": TRAIN_END, "oos_D_ge": OOS_START,
                          "strategy_statistics_D_ge": STATS_START},
        "output_dir": str(output_dir), **FLAGS,
    }
    progress("run", "STARTED", {"start_date": start_date, "asof_date": asof_date})
    _write_json(output_dir / "run_summary.json", run_base)
    try:
        official, official_meta = read_official_top200(official_top200_path)
        progress("official_top200", "READ_PASS", official_meta)
        with bind_current_panels(data_root) as (panel_path, source, recheck):
            if asof_date > source["asof_date"]:
                raise StudyError("REQUESTED_ASOF_AFTER_BOUND_PANEL_ASOF")
            progress("panel_binding", "BOUND", {"panel_path": str(panel_path),
                                                  "generation_id": source.get("generation_id"),
                                                  "asof_date": source.get("asof_date")})
            frame, panel_read = _read_panel(panel_path, start_date=start_date, asof_date=asof_date)
            if not len(frame):
                raise StudyError("A_SHARE_PANEL_ROWS_EMPTY_IN_REQUESTED_WINDOW")
            progress("panel_read", "READ_PASS", panel_read)
            frame, vector_meta = _vectorize_rows(frame, start_date=start_date, asof_date=asof_date)
            frame, top200_meta = _apply_top200_ranks(frame, official, official_meta)
            frame = _join_future_top200(frame)
            progress("causal_features_and_outcomes", "BUILD_PASS", {**vector_meta, **top200_meta})
            frame, split = _episode_split(frame)
            progress("model_fit", "STARTED", {key: value for key, value in split.items()
                                               if not key.endswith("mask")})
            models, model_report, predictions = _fit_models(frame, split, progress=progress)
            progress("model_fit", "ALL_FOUR_FITS_PASS", {"fit_count": model_report["fit_count"]})
            for col in ("p_pullback_lr", "p_pullback_hgb", "p_readvance_lr", "p_readvance_hgb"):
                frame[col] = predictions[col]
            daily_screen = _daily_screen(frame, start_date=max(start_date, STATS_START))
            daily_metrics = _daily_strategy_metrics(frame, stats_start=STATS_START)
            topk, topk_pooled = _oos_topk_metrics(frame)
            pooled_metrics = _pooled_strategy_metrics(frame, stats_start=STATS_START)
            audit = _audit_sample(frame, target_count=1600)
            market_dates = list(frame.attrs.get("market_dates", sorted(frame["trade_date"].unique())))
            friday, friday_meta = _friday_rows(frame, official, official_meta, market_dates=market_dates)
            recheck()
            progress("source_recheck", "PASS", {"generation_id": source.get("generation_id")})
            outputs = {
                "daily_screen_summary.csv": daily_screen,
                "daily_strategy_metrics.csv": daily_metrics,
                "oos_daily_topk_metrics.csv": topk,
                "nov19_full_a_friday_20261119.csv": friday,
                "oos_audit_sample.csv": audit,
            }
            counts = {}
            for name, value in outputs.items():
                counts[name] = _write_rows(output_dir / name, value)
                progress("artifact_write", "ARTIFACT_WRITTEN", {"name": name, "rows": counts[name]})
            _save_model_state(output_dir / "model_state.joblib", models, model_report, source, official_meta)
            progress("artifact_write", "MODEL_STATE_WRITTEN", {"name": "model_state.joblib"})
            _write_json(output_dir / "model_metrics.json", model_report)
            _write_json(output_dir / "pooled_metrics.json", {"strategy": pooled_metrics,
                                                               "oos_topk": topk_pooled})
            progress("run", "OUTPUTS_COMPLETE", {"fit_count": model_report["fit_count"],
                                                  "output_dir": str(output_dir)})
            artifacts = {}
            for path in sorted(output_dir.iterdir()):
                if path.name == "run_summary.json" or not path.is_file():
                    continue
                artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": _sha_file(path)}
            run_base.update({
                "status": "FIT_COMPLETED", "fit_count": model_report["fit_count"],
                "panel_source": source, "panel_read": panel_read,
                "official_top200_source": official_meta, "vectorized_run": vector_meta,
                "top200_rank_contract": top200_meta,
                "split_guard": model_report["split_guard"], "model_fit_policy": model_report["fit_policy"],
                "training_rows": model_report["training"],
                "oos_weak_label_metrics": model_report["oos_weak_label_metrics"],
                "pooled_metrics": {"strategy": pooled_metrics, "oos_topk": topk_pooled},
                "output_rows": counts, "friday_reference": friday_meta,
                "artifact_receipts": artifacts,
                "censor_policy": "EXACT_A_MARKET_SESSION_OFFSETS; MISSING_T+n_BAR_REMAINS_CENSORED",
                "drawdown_measure": "CLOSE_PATH_MDD; D_CLOSE_AND_EXACT_FUTURE_MARKET_SESSION_CLOSES",
                "weak_labels": "D_AND_PRIOR_ONLY_RULES; NOT_FORWARD_RETURN_LABELS",
                "next_action": "ROOT_PERFORMS_ACTUAL_FIT_AND_UPLOAD; RESEARCH_ONLY",
            })
            _write_json(output_dir / "run_summary.json", run_base)
            recheck()
            return run_base
    except Exception as exc:
        run_base.update({"status": "FAILED", "failure": {"type": type(exc).__name__, "reason": str(exc)}})
        try:
            progress("run", "FAILED", {"type": type(exc).__name__, "reason": str(exc)})
            _write_json(output_dir / "run_summary.json", run_base)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path,
                        default=Path(os.environ["V4_DATA_ROOT"]) if os.environ.get("V4_DATA_ROOT") else None)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--asof-date", default=DEFAULT_ASOF)
    parser.add_argument("--official-top200", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.data_root is None:
            raise StudyError("DATA_ROOT_REQUIRED_USE_V4_DATA_ROOT_OR_ARGUMENT")
        result = run_once(data_root=args.data_root, start_date=args.start_date,
                          asof_date=args.asof_date, official_top200_path=args.official_top200,
                          output_dir=args.output_dir)
        print(json.dumps({"status": result["status"], "fit_count": result["fit_count"],
                          "output_dir": result["output_dir"], "output_rows": result["output_rows"]},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (StudyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
