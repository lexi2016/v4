#!/usr/bin/env python3
"""Date-bound, additive producer for the frozen Zge skill R2 D28 screen."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

ASOF = "20261028"
GENERATION = "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29"
SELECTOR_SHA = "28e577a67e5b5b00a04ac181632d7e1e4e6cc0e4f34e1283f69d28896ec893fb"
RULESET_ID = "ZGE_SKILL_DAILY_CANDIDATES_R2"
QUARANTINE = 270
HISTORY_START = "20210801"
NAMESPACE = "LOCAL_RESEARCH_DEFAULT_OR_SKILL_EXPLICIT_AS_IN_R2"

SELECTOR_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/"
    "selector_ready_panels/data_layer_daily_formula_increment_update_v1/"
    "selector_ready_current_to_20261028_qfq_31d40c5900ced1b2/"
    "selector_ready_current_to_20261028.parquet"
)
INTERFACE_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/"
    "data_layer_interface_current/DATA_LAYER_INTERFACE.py"
)
RECEIPT_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/"
    "research_panel_daily/receipts/a-20261028.json"
)
TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/Z哥方法论")
RULESET_PATH = TASK_ROOT / "d28_rule_pool_luna_batch_20261030/RULESET_R2.json"
DESIGN_PATH = TASK_ROOT / "d28_rule_pool_luna_batch_20261030/SKILL_RULE_DESIGN_R2.md"
FIELD_PATH = TASK_ROOT / "d28_rule_pool_luna_batch_20261030/D28_FIELD_AVAILABILITY.json"
TURNOVER_MANIFEST = TASK_ROOT / "turnover_daily_history_20261030/overlay_input_d30_v1.json"
TURNOVER_D28 = TASK_ROOT / "turnover_daily_history_20261030/d28_turnover.parquet"
TURNOVER_MANIFEST_SHA = "0a11a384b021a287feffe3701a451de0576ee008e0e21d898d17bb272eee1746"
TURNOVER_D28_SHA = "a73e0bd2fcfd780c15a305366c27d9ab2c1c4e1fea8838fbf6d8c43f8f39c3ae"
TURNOVER_D28_MANIFEST_SHA = "5fe544deb22926d2ef696a2f49ca86d1e5008251cc7172c16edcddbbbabc602f"
G4_NO_VALID_D28_BAR = {"002717.SZ", "002827.SZ", "301468.SZ"}
LIFECYCLE_PATH = Path(
    "/Users/lexi/Desktop/学习/因子工厂/research/"
    "a_share_local_panel_completion_20261024/SECURITY_LIFECYCLE_GROUPS_R1.json"
)

GROUP_IDS = (
    "skill_r2_b1", "skill_r2_nana", "skill_r2_super_b1", "skill_r2_sb1",
    "skill_r2_b2", "skill_r2_b3", "skill_r2_parallel", "skill_r2_rebuild",
    "skill_r2_platform",
)
PANEL_COLUMNS = [
    "trade_date", "ts_code", "name", "market_type", "exchange",
    "open", "high", "low", "close", "volume", "turnover_rate_pct",
    "J", "zge_white_line", "zge_yellow_line",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def condition(
    condition_id: str, observed: Any, op: str, threshold: Any, *,
    formula: str, namespace: str = NAMESPACE,
) -> dict[str, Any]:
    left, right = number(observed), number(threshold)
    result: Optional[bool] = None
    if left is not None and right is not None:
        result = {
            "<=": lambda: left <= right,
            "<": lambda: left < right,
            ">=": lambda: left >= right,
            ">": lambda: left > right,
            "==": lambda: left == right,
        }[op]()
    return {
        "id": condition_id,
        "state": "UNKNOWN" if result is None else ("TRUE" if result else "FALSE"),
        "observed": scalar(observed),
        "op": op,
        "threshold": scalar(threshold),
        "formula": formula,
        "namespace": namespace,
    }


def event(condition_id: str, state: str, formula: str, *, anchor: Optional[str] = None,
          note: Optional[str] = None) -> dict[str, Any]:
    if state not in {"TRUE", "FALSE", "UNKNOWN"}:
        raise ValueError(state)
    return {
        "id": condition_id, "state": state, "observed": anchor, "op": "event_exists",
        "threshold": True, "formula": formula, "namespace": NAMESPACE, "note": note,
    }


def and_state(states: Iterable[str]) -> str:
    states = list(states)
    if "FALSE" in states:
        return "FALSE"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    return "TRUE"


def or_state(states: Iterable[str]) -> str:
    states = list(states)
    if "TRUE" in states:
        return "TRUE"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    return "FALSE"


def all_conditions(items: Iterable[dict[str, Any]]) -> str:
    return and_state(item["state"] for item in items)


def find_last(states: list[str], start: int, end: int) -> tuple[str, Optional[int]]:
    for index in range(end, start - 1, -1):
        if not 0 <= index < len(states) or states[index] == "UNKNOWN":
            # An unobserved later event prevents confirming an older anchor.
            return "UNKNOWN", None
        if states[index] == "TRUE":
            return "TRUE", index
    return "FALSE", None


def count_at_least(states: list[str], start: int, end: int, minimum: int) -> str:
    if start < 0 or end >= len(states) or end < start:
        return "UNKNOWN"
    values = states[start:end + 1]
    yes, maybe = values.count("TRUE"), values.count("UNKNOWN")
    if yes >= minimum:
        return "TRUE"
    if yes + maybe < minimum:
        return "FALSE"
    return "UNKNOWN"


def rolling(values: np.ndarray, window: int, op: str = "mean") -> np.ndarray:
    roll = pd.Series(values, dtype="float64").rolling(window, min_periods=window)
    if op == "mean":
        return roll.mean().to_numpy()
    if op == "max":
        return roll.max().to_numpy()
    if op == "min":
        return roll.min().to_numpy()
    raise ValueError(op)


def load_interface(path: Path):
    spec = importlib.util.spec_from_file_location("bound_v4_data_layer_interface", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bound data interface: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_receipt(receipt: dict[str, Any], panel_path: Path, asof: str) -> None:
    generation = receipt.get("formula", {}).get("authority", {}).get("generation_id")
    if receipt.get("target_date") != asof or generation != GENERATION:
        raise RuntimeError("D28 receipt target or generation mismatch")
    if str(receipt.get("selector")) != str(panel_path) or receipt.get("selector_sha256") != SELECTOR_SHA:
        raise RuntimeError("D28 receipt selector path or declared SHA mismatch")
    if (receipt.get("target_count"), receipt.get("accepted_count"), receipt.get("quarantine_count")) != (5808, 5538, QUARANTINE):
        raise RuntimeError("D28 receipt accepted/quarantine conservation mismatch")


def load_bound_projection(
    panel_path: Path = SELECTOR_PATH,
    interface_path: Path = INTERFACE_PATH,
    receipt_path: Path = RECEIPT_PATH,
    asof: str = ASOF,
    history_start: str = HISTORY_START,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validate_receipt(receipt, panel_path, asof)
    interface = load_interface(interface_path)
    meta = interface.get_panel_meta(panel_path=panel_path, include_dates=False)
    if meta.get("generation_id") != GENERATION or meta.get("path") != str(panel_path):
        raise RuntimeError("selector generation/path binding mismatch")
    projection = interface.load_selector_ready(
        columns=PANEL_COLUMNS,
        start_date=history_start,
        end_date=asof,
        filters=[("market_type", "in", ["A_SHARE", "BJ"])],
        panel_path=panel_path,
    )
    projection["trade_date"] = projection["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    projection["ts_code"] = projection["ts_code"].astype(str)
    if projection.empty or (projection["trade_date"] > asof).any():
        raise RuntimeError("empty or future-dated selector projection")
    if projection.duplicated(["ts_code", "trade_date"]).any():
        raise RuntimeError("duplicate selector (code,date) key")
    target = projection.loc[projection["trade_date"] == asof].copy()
    counts = target["exchange"].value_counts().to_dict()
    expected = {"SZ": 2893, "SH": 2317, "BJ": 328}
    if len(target) != 5538 or target["ts_code"].nunique() != 5538 or counts != expected:
        raise RuntimeError(f"D28 accepted-set mismatch: rows={len(target)}, exchanges={counts}")
    if not target["ts_code"].str.fullmatch(r"\d{6}\.(SH|SZ|BJ)").all():
        raise RuntimeError("non A-share/BJ code in target projection")
    source = {
        "receipt_path": str(receipt_path),
        "receipt_sha256_actual": sha256(receipt_path),
        "receipt_sha256_declared": receipt.get("sha256"),
        "selector_path": str(panel_path),
        "selector_sha256_declared": receipt.get("selector_sha256"),
        "selector_sha256_recomputed": False,
        "generation_id": meta.get("generation_id"),
        "price_basis": meta.get("price_basis"),
        "volume_basis": meta.get("volume_basis"),
        "market_basis": meta.get("market_basis"),
        "historical_pit_certified": meta.get("historical_pit_certified"),
        "authority_status": receipt.get("authority_status"),
        "receipt_status": receipt.get("status"),
        "accepted_rows": int(receipt.get("accepted_count", 0)),
        "quarantine_rows": int(receipt.get("quarantine_count", 0)),
        "projection_rows": int(len(projection)),
        "projection_dates": int(projection["trade_date"].nunique()),
        "history_start": history_start,
        "asof": asof,
        "target_rows": int(len(target)),
        "exchange_counts": counts,
    }
    return projection, target, source


def load_turnover_history(
    selected_codes: set[str], history_start: str,
    manifest_path: Path = TURNOVER_MANIFEST,
    *, verify_parts: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256(manifest_path) != TURNOVER_MANIFEST_SHA:
        raise RuntimeError("historical turnover overlay manifest SHA mismatch")
    if int(manifest.get("cutoff", -1)) != int(ASOF) or manifest.get("projection_generation_id") != GENERATION:
        raise RuntimeError("turnover overlay generation/cutoff mismatch")
    d28_ref = manifest.get("d28", {})
    d28_manifest_ref = manifest.get("d28_manifest", {})
    if (str(d28_ref.get("path")) != str(TURNOVER_D28)
            or d28_ref.get("sha256") != TURNOVER_D28_SHA
            or d28_manifest_ref.get("sha256") != TURNOVER_D28_MANIFEST_SHA):
        raise RuntimeError("D28 turnover overlay identity does not match frozen manifest")
    if sha256(Path(d28_manifest_ref["path"])) != TURNOVER_D28_MANIFEST_SHA:
        raise RuntimeError("D28 turnover manifest content SHA mismatch")
    frames, used = [], []
    for part in manifest.get("historical_parts", []):
        codes = sorted(selected_codes.intersection(map(str, part.get("codes", []))))
        if not codes:
            continue
        path = Path(part["path"])
        actual_hash = sha256(path) if verify_parts else part.get("sha256")
        if verify_parts and actual_hash != part.get("sha256"):
            raise RuntimeError(f"historical turnover part hash mismatch: {path}")
        frame = pd.read_parquet(
            path,
            columns=["ts_code", "trade_date", "turnover_rate_pct", "turnover_float_share_10k", "turnover_status"],
            filters=[("trade_date", ">=", int(history_start)),
                     ("trade_date", "<=", int(ASOF)), ("ts_code", "in", codes)],
        )
        frame["trade_date"] = frame["trade_date"].astype(str).str.zfill(8)
        frames.append(frame)
        used.append({"path": str(path), "sha256": actual_hash,
                     "sha256_check": "RECOMPUTED_PASS" if verify_parts else "MANIFEST_DECLARED_ONLY",
                     "codes": len(codes), "rows": len(frame)})
    repair = manifest.get("repair", {})
    repair_codes = sorted(selected_codes.intersection(map(str, repair.get("codes", []))))
    if repair_codes:
        path = Path(repair["path"])
        actual_hash = sha256(path) if verify_parts else repair.get("sha256")
        if verify_parts and actual_hash != repair.get("sha256"):
            raise RuntimeError(f"repair4 turnover part hash mismatch: {path}")
        frame = pd.read_parquet(
            path,
            columns=["ts_code", "trade_date", "turnover_rate_pct", "turnover_float_share_10k", "turnover_status"],
            filters=[("trade_date", ">=", int(history_start)),
                     ("trade_date", "<=", int(ASOF)), ("ts_code", "in", repair_codes)],
        )
        frame["trade_date"] = frame["trade_date"].astype(str).str.zfill(8)
        frame["_repair4"] = True
        frames.append(frame)
        used.append({"path": str(path), "sha256": actual_hash,
                     "sha256_check": "RECOMPUTED_PASS" if verify_parts else "MANIFEST_DECLARED_ONLY",
                     "codes": len(repair_codes),
                     "rows": len(frame), "replacement_status": repair.get("replacement_status")})
    overlay = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts_code", "trade_date", "turnover_rate_pct", "turnover_float_share_10k", "turnover_status"])
    if "_repair4" not in overlay:
        overlay["_repair4"] = False
    else:
        overlay["_repair4"] = overlay["_repair4"].fillna(False)
    overlay = overlay.sort_values(["ts_code", "trade_date", "_repair4"])
    overlay = overlay.drop_duplicates(["ts_code", "trade_date"], keep="last")
    if overlay.duplicated(["ts_code", "trade_date"]).any():
        raise RuntimeError("duplicate turnover overlay keys")
    receipt = {
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "manifest_sha256_declared": TURNOVER_MANIFEST_SHA,
        "cutoff": manifest.get("cutoff"),
        "projection_generation_id": manifest.get("projection_generation_id"),
        "history_parts_used": used,
        "history_rows": int(len(overlay)),
        "parts_sha256_recomputed": verify_parts,
        "precedence": ["selector_nonnull", "history_overlay_fill_null", "repair4_replacement", "D28_asof_overlay"],
        "free_turnover": "UNKNOWN; ordinary turnover is not substituted",
    }
    return overlay, receipt


def merge_turnover(projection: pd.DataFrame, history: pd.DataFrame,
                   d28_path: Path = TURNOVER_D28) -> pd.DataFrame:
    result = projection.copy()
    result["_selector_turnover"] = pd.to_numeric(result["turnover_rate_pct"], errors="coerce")
    if not history.empty:
        hist = history[["ts_code", "trade_date", "turnover_rate_pct"]].rename(
            columns={"turnover_rate_pct": "_history_turnover"})
        result = result.merge(hist, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
        result["turnover_rate_pct"] = result["_selector_turnover"].where(
            result["_selector_turnover"].notna(), pd.to_numeric(result["_history_turnover"], errors="coerce"))
        result = result.drop(columns=["_history_turnover"])
    else:
        result["turnover_rate_pct"] = result["_selector_turnover"]
    d28 = pd.read_parquet(d28_path, columns=["ts_code", "trade_date", "turnover_rate_pct", "turnover_status"])
    if sha256(d28_path) != TURNOVER_D28_SHA:
        raise RuntimeError("D28 turnover overlay parquet SHA mismatch")
    d28["trade_date"] = d28["trade_date"].astype(str).str.zfill(8)
    d28["ts_code"] = d28["ts_code"].astype(str)
    target = projection.loc[projection["trade_date"] == ASOF, ["ts_code", "trade_date"]]
    overlay_codes, target_codes = set(d28["ts_code"]), set(target["ts_code"])
    exact_pool = len(target) == 5538
    mismatch = (overlay_codes != target_codes) if exact_pool else not target_codes.issubset(overlay_codes)
    if d28["ts_code"].duplicated().any() or mismatch:
        raise RuntimeError("D28 turnover overlay does not conserve target code/date keys")
    if set(d28["trade_date"]) != {ASOF}:
        raise RuntimeError("D28 turnover overlay contains a non-D28 date")
    unpriced = set(d28.loc[d28["turnover_status"] == "G4_UNPRICED_OR_MISSING", "ts_code"])
    if unpriced != G4_NO_VALID_D28_BAR:
        raise RuntimeError(f"D28 unpriced/no-valid-bar set changed: {sorted(unpriced)}")
    d28 = d28.rename(columns={"turnover_rate_pct": "_d28_turnover", "turnover_status": "_d28_status"})
    result = result.merge(d28, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
    mask = result["trade_date"] == ASOF
    result.loc[mask, "turnover_rate_pct"] = pd.to_numeric(result.loc[mask, "_d28_turnover"], errors="coerce")
    result.loc[mask, "turnover_status"] = result.loc[mask, "_d28_status"]
    return result.drop(columns=["_selector_turnover", "_d28_turnover", "_d28_status"])


def lifecycle_exclusions(path: Path = LIFECYCLE_PATH, asof: str = ASOF):
    data = json.loads(path.read_text(encoding="utf-8"))
    excluded, details = {}, {}
    for item in data.get("groups", {}).get("delisted_verified", []):
        effective = str(item.get("delisting_effective_date", ""))
        if item.get("verified") is True and re.fullmatch(r"\d{8}", effective) and effective <= asof:
            code = str(item["ts_code"])
            excluded[code] = "VERIFIED_DELISTED_EFFECTIVE_ON_OR_BEFORE_ASOF"
            details[code] = {"delisting_effective_date": effective,
                             "review": item.get("accepted_review_literal"),
                             "review_ref": item.get("accepted_review_ref")}
    for item in data.get("groups", {}).get("historical_suspension", []):
        suspension_date = item.get("suspension_date")
        if item.get("verified") is True and str(suspension_date or "") == asof:
            code = str(item["ts_code"])
            excluded[code] = "VERIFIED_SUSPENSION_ON_ASOF"
            details[code] = {"suspension_date": asof, "review": item.get("accepted_review_literal")}
    return excluded, details


class StockSeries:
    """Shared session-aligned OHLCV and formula fields for a single code."""
    def __init__(self, frame: pd.DataFrame, calendar: list[str], asof: str, *, rebuild_only: bool = False):
        if frame["trade_date"].duplicated().any():
            raise RuntimeError("duplicate security date")
        self.calendar, self.asof = calendar, asof
        self.df = frame.set_index("trade_date").reindex(calendar)
        self.index = calendar.index(asof)
        self.open = self.arr("open")
        self.high = self.arr("high")
        self.low = self.arr("low")
        self.close = self.arr("close")
        self.volume = self.arr("volume")
        self.turnover = self.arr("turnover_rate_pct")
        self.j = self.arr("J")
        self.w = self.arr("zge_white_line")
        self.y = self.arr("zge_yellow_line")
        self.bbi = self.arr("BBI")
        prev_close = np.roll(self.close, 1)
        prev_close[0] = np.nan
        self.ret = np.full(len(calendar), np.nan)
        valid_prev = np.isfinite(prev_close) & (prev_close > 0)
        self.ret[valid_prev] = self.close[valid_prev] / prev_close[valid_prev] - 1
        self.amp = np.full(len(calendar), np.nan)
        self.amp[valid_prev] = (self.high[valid_prev] - self.low[valid_prev]) / prev_close[valid_prev]
        day_range = self.high - self.low
        valid_range = np.isfinite(day_range) & (day_range > 0)
        self.body = np.full(len(calendar), np.nan)
        self.upper = np.full(len(calendar), np.nan)
        self.body[valid_range] = np.abs(self.close[valid_range] - self.open[valid_range]) / day_range[valid_range]
        self.upper[valid_range] = (self.high[valid_range] - np.maximum(self.close[valid_range], self.open[valid_range])) / day_range[valid_range]
        self.v20 = np.roll(rolling(self.volume, 20), 1)
        self.v20[0] = np.nan
        self.v3 = rolling(self.volume, 3)
        self.high60prev = np.roll(rolling(self.high, 60, "max"), 1)
        self.high60prev[0] = np.nan
        self.high20prev = np.roll(rolling(self.high, 20, "max"), 1)
        self.low20prev = np.roll(rolling(self.low, 20, "min"), 1)
        self.high20prev[0] = self.low20prev[0] = np.nan
        self.up = [] if rebuild_only else self._up_states()
        self.shrink = [condition("shrink", self.v3[i] - 0.70 * self.v20[i], "<=", 0,
                                 formula="V3<=0.70*V20P")["state"] for i in range(len(calendar))]
        self.doji = [] if rebuild_only else [condition("doji", self.body[i], "<=", 0.25,
                               formula="BODY<=0.25")["state"] for i in range(len(calendar))]
        self.attack = self._attack_states()
        if not rebuild_only:
            self.down_attack = self._down_attack_states()
            self.b1_normal, self.b1_strict = self._b1_states()
            self.weekly = self._weekly_values()

    def arr(self, column: str) -> np.ndarray:
        if column not in self.df:
            return np.full(len(self.calendar), np.nan)
        return pd.to_numeric(self.df[column], errors="coerce").to_numpy(dtype="float64")

    def value(self, values: np.ndarray, i: int) -> Optional[float]:
        return number(values[i]) if 0 <= i < len(values) else None

    def date(self, i: Optional[int]) -> Optional[str]:
        return self.calendar[i] if i is not None and 0 <= i < len(self.calendar) else None

    def _up_states(self) -> list[str]:
        states = []
        for i in range(len(self.calendar)):
            if i < 5:
                states.append("UNKNOWN")
            else:
                states.append(and_state([
                    condition("w_gt_y", self.w[i] - self.y[i], ">", 0, formula="W>Y")["state"],
                    condition("w_slope_5", self.w[i] - self.w[i-5], ">", 0, formula="W(t)>W(t-5)")["state"],
                    condition("y_slope_5", self.y[i] - self.y[i-5], ">=", 0, formula="Y(t)>=Y(t-5)")["state"],
                ]))
        return states

    def _attack_states(self) -> list[str]:
        states = []
        for i in range(len(self.calendar)):
            states.append(and_state([
                condition("attack_return", self.ret[i], ">=", 0.04, formula="R>=0.04")["state"],
                condition("attack_green", self.close[i] - self.open[i], ">", 0, formula="C>O")["state"],
                condition("attack_volume", self.volume[i] - 1.5*self.v20[i], ">=", 0, formula="V>=1.5*V20P")["state"],
                condition("attack_body", self.body[i], ">=", 0.60, formula="BODY>=0.60")["state"],
            ]))
        return states

    def _down_attack_states(self) -> list[str]:
        return [and_state([
            condition("down_return", self.ret[i], "<=", -0.03, formula="R<=-0.03")["state"],
            condition("down_volume", self.volume[i] - 1.5*self.v20[i], ">=", 0, formula="V>=1.5*V20P")["state"],
        ]) for i in range(len(self.calendar))]

    def _b1_states(self):
        normal, strict = [], []
        for i in range(len(self.calendar)):
            core = and_state([
                self.up[i], self.shrink[i],
                condition("b1_ret_min", self.ret[i], ">=", -0.02, formula="R>=-0.02", namespace="SKILL_EXPLICIT")["state"],
                condition("b1_ret_max", self.ret[i], "<=", 0.018, formula="R<=0.018", namespace="SKILL_EXPLICIT")["state"],
                condition("b1_amp", self.amp[i], "<=", 0.07, formula="AMP<=0.07", namespace="SKILL_EXPLICIT")["state"],
                condition("b1_close_y", self.close[i] - 0.97*self.y[i], ">=", 0, formula="C>=0.97*Y")["state"],
            ])
            normal.append(and_state([core, condition("b1_j", self.j[i], "<=", 12, formula="J<=12", namespace="SKILL_EXPLICIT")["state"]]))
            strict.append(and_state([core, condition("b1_strict_j", self.j[i], "<=", -10, formula="J<=-10", namespace="SKILL_EXPLICIT")["state"]]))
        return normal, strict

    def _weekly_values(self) -> dict[str, Any]:
        dates = pd.to_datetime(pd.Series(self.calendar), format="%Y%m%d")
        friday = dates + pd.to_timedelta(4 - dates.dt.weekday, unit="D")
        last_by_week: dict[pd.Timestamp, int] = {}
        for i, end in enumerate(friday):
            if end <= pd.Timestamp(self.asof):
                last_by_week[end] = i
        ends = sorted(last_by_week)
        # Require a bar on each completed market week-end; suspended/missing rows remain unknown.
        if len(ends) < 234:
            return {"state": "UNKNOWN", "reason": "INSUFFICIENT_COMPLETED_WEEKS"}
        closes = np.asarray([self.close[last_by_week[end]] for end in ends], dtype="float64")
        weekly = pd.Series(closes)
        ma55 = weekly.rolling(55, min_periods=55).mean()
        ma144 = weekly.rolling(144, min_periods=144).mean()
        ma233 = weekly.rolling(233, min_periods=233).mean()
        k = len(ends) - 1
        vals = [ma55.iloc[k], ma144.iloc[k], ma233.iloc[k], ma55.iloc[k-1], ma144.iloc[k-1]]
        if any(pd.isna(value) for value in vals):
            return {"state": "UNKNOWN", "reason": "WEEKLY_WINDOW_HAS_MISSING_CLOSE"}
        return {"state": "TRUE", "week_end": ends[-1].strftime("%Y%m%d"),
                "ma55": float(vals[0]), "ma144": float(vals[1]), "ma233": float(vals[2]),
                "previous_ma55": float(vals[3]), "previous_ma144": float(vals[4])}

    def anchor(self, i: Optional[int]) -> Optional[dict[str, Any]]:
        if i is None:
            return None
        return {"trade_date": self.date(i), "high": self.value(self.high, i),
                "low": self.value(self.low, i), "close": self.value(self.close, i),
                "volume": self.value(self.volume, i)}

    def signal_event(self, condition_id: str, state: str, formula: str,
                     index: Optional[int], *, note: Optional[str] = None) -> dict[str, Any]:
        """Attach the compact inputs needed to audit a composite signal."""
        item = event(condition_id, state, formula, anchor=self.date(index), note=note)
        if index is not None and 0 <= index < len(self.calendar):
            v20 = self.value(self.v20, index)
            volume = self.value(self.volume, index)
            item["inputs"] = {
                "trade_date": self.date(index), "V": volume,
                "O": self.value(self.open, index), "C": self.value(self.close, index),
                "H": self.value(self.high, index), "L": self.value(self.low, index),
                "previous_close": self.value(self.close, index-1),
                "V3": self.value(self.v3, index), "V20P": v20,
                "V_over_V20P": volume / v20 if volume is not None and v20 is not None and v20 > 0 else None,
                "return": self.value(self.ret, index), "body": self.value(self.body, index),
                "W": self.value(self.w, index), "Y": self.value(self.y, index),
                "W_t_minus_5": self.value(self.w, index-5),
                "Y_t_minus_5": self.value(self.y, index-5),
            }
        return item

    def find_attack(self, start: int, end: int) -> tuple[str, Optional[int]]:
        return find_last(self.attack, max(0, start), end)

    def branch(self, group_id: str, seeds: list[dict[str, Any]], *,
               required: Optional[list[dict[str, Any]]] = None,
               enhancements: Optional[list[dict[str, Any]]] = None,
               anchor: Optional[int] = None, subtypes: Optional[list[str]] = None,
               notes: Optional[list[str]] = None) -> dict[str, Any]:
        required, enhancements = required or [], enhancements or []
        seed_state = all_conditions(seeds)
        required_state = all_conditions(required)
        if not enhancements:
            enhancement_state = "NOT_APPLICABLE"
        elif any(item["state"] == "UNKNOWN" for item in enhancements):
            enhancement_state = "UNKNOWN"
        elif any(item["state"] == "FALSE" for item in enhancements):
            enhancement_state = "FALSE"
        else:
            enhancement_state = "TRUE"
        if seed_state != "TRUE":
            state = seed_state
        elif required_state == "FALSE":
            state = "FILTERED"
        elif required_state == "UNKNOWN" or enhancement_state == "UNKNOWN":
            state = "PENDING_CHECK"
        else:
            state = "CHART_QUEUE"
        return {
            "group_id": group_id, "seed_state": seed_state, "required_state": required_state,
            "enhancement_state": enhancement_state, "state": state,
            "conditions": seeds + required + enhancements,
            "event_anchor": self.anchor(anchor), "subtypes": subtypes or [], "notes": notes or [],
            "risk_state": "NOT_EVALUATED", "risk_flags": [],
        }

    def b1_conditions(self, i: int, strict: bool = False) -> list[dict[str, Any]]:
        jmax = -10 if strict else 12
        return [
            self.signal_event("up_trend", self.up[i], "UP=W>Y and W>W[-5] and Y>=Y[-5]", i),
            self.signal_event("volume_shrink", self.shrink[i], "V3<=0.70*V20P", i),
            condition("return_min", self.ret[i], ">=", -0.02, formula="R>=-0.02", namespace="SKILL_EXPLICIT"),
            condition("return_max", self.ret[i], "<=", 0.018, formula="R<=0.018", namespace="SKILL_EXPLICIT"),
            condition("amplitude_max", self.amp[i], "<=", 0.07, formula="AMP<=0.07", namespace="SKILL_EXPLICIT"),
            condition("close_vs_yellow", self.close[i] - 0.97*self.y[i], ">=", 0,
                      formula="C>=0.97*Y", namespace="SKILL_EXPLICIT"),
            condition("J_gate", self.j[i], "<=", jmax, formula=f"J<={jmax}", namespace="SKILL_EXPLICIT"),
        ]

    def b1_result(self, i: int) -> dict[str, Any]:
        return {
            "normal": self.b1_normal[i],
            "strict": self.b1_strict[i],
            "low": self.value(self.low, i),
            "date": self.date(i),
        }

    def b2_result(self, i: int) -> dict[str, Any]:
        anchor_state, anchor_index = find_last(self.b1_normal, i - 3, i - 1)
        if anchor_index is None:
            return {
                "state": "UNKNOWN" if anchor_state == "UNKNOWN" else "FALSE",
                "anchor": None,
                "conditions": [event("prior_b1", anchor_state, "B1 numeric candidate in prior 1..3 sessions")],
            }
        items = [
            event("prior_b1", "TRUE", "B1 numeric candidate in prior 1..3 sessions", anchor=self.date(anchor_index)),
            condition("return_min", self.ret[i], ">=", 0.04, formula="R>=0.04", namespace="SKILL_EXPLICIT"),
            condition("J_max_exclusive", self.j[i], "<", 55, formula="J<55", namespace="SKILL_EXPLICIT"),
            condition("volume_increase", self.volume[i] - self.volume[i-1] if i > 0 else None,
                      ">", 0, formula="V(t)>V(t-1)", namespace="SKILL_EXPLICIT"),
            condition("green", self.close[i] - self.open[i], ">", 0, formula="C>O", namespace="SKILL_EXPLICIT"),
            condition("close_above_b1_low", self.close[i] - self.low[anchor_index], ">=", 0,
                      formula="C(t)>=L(B1)", namespace="SKILL_EXPLICIT"),
        ]
        items[0]["b1_normal_state"] = self.b1_normal[anchor_index]
        items[0]["b1_strict_state"] = self.b1_strict[anchor_index]
        items[0]["b1_anchor_low"] = self.value(self.low, anchor_index)
        items[0]["source_subtypes"] = [name for name, state in (
            ("B1_NORMAL", self.b1_normal[anchor_index]),
            ("B1_STRICT", self.b1_strict[anchor_index]),
        ) if state == "TRUE"]
        return {"state": all_conditions(items), "anchor": anchor_index, "conditions": items}

    @staticmethod
    def candle_recovery_state(doji_state: str, open_value: Any, close_value: Any) -> str:
        green = condition("green", number(close_value) - number(open_value)
                          if number(close_value) is not None and number(open_value) is not None else None,
                          ">", 0, formula="C>O")["state"]
        if doji_state == "TRUE" or green == "TRUE":
            return "TRUE"
        if doji_state == "FALSE" and green == "FALSE":
            return "FALSE"
        return "UNKNOWN"

    def sb1_prepattern(self, k: int) -> list[dict[str, Any]]:
        if k < 3:
            high_low = drift = None
        else:
            highs, lows, closes = self.high[k-3:k], self.low[k-3:k], self.close[k-3:k]
            high_low = (float(np.max(highs)/np.min(lows)-1)
                        if np.all(np.isfinite(highs)) and np.all(np.isfinite(lows)) and np.min(lows) > 0
                        else None)
            drift = (abs(float(closes[-1]/closes[0]-1))
                     if np.all(np.isfinite(closes)) and closes[0] > 0 else None)
        return [
            condition("prebreak_range", high_low, "<=", 0.07, formula="max(H3)/min(L3)-1<=0.07"),
            condition("prebreak_close_drift", drift, "<=", 0.03, formula="abs(lastC/firstC-1)<=0.03"),
        ]

    def sb1_breakdown(self, k: int) -> list[dict[str, Any]]:
        prior_low = (float(np.min(self.low[k-3:k]))
                     if k >= 3 and np.all(np.isfinite(self.low[k-3:k])) else None)
        return self.sb1_prepattern(k) + [
            condition("break_below_prior_low", self.close[k]-prior_low if prior_low is not None else None,
                      "<", 0, formula="C(k)<min(L(k-3..k-1))"),
            condition("breakdown_return", self.ret[k], "<=", -0.03, formula="R(k)<=-0.03"),
            condition("breakdown_volume", self.volume[k]-1.5*self.v20[k], ">=", 0,
                      formula="V(k)>=1.5*V20P(k)"),
        ]

    def rebuild_branch(self) -> dict[str, Any]:
        i = self.index
        # H. White/yellow crossover, attack on crossover or following session, pullback.
        event_states = ["FALSE"] * len(self.calendar)
        for k in range(max(1, i-20), i):
            cross_state = and_state([
                condition("cross_now", self.w[k]-self.y[k], ">", 0, formula="W(k)>Y(k)")["state"],
                condition("cross_previous", self.w[k-1]-self.y[k-1], "<=", 0,
                          formula="W(k-1)<=Y(k-1)")["state"],
            ])
            attack_options = [self.attack[k]] + ([self.attack[k+1]] if k+1 < i else [])
            event_states[k] = and_state([cross_state, or_state(attack_options)])
        event_state, cross_anchor = find_last(event_states, max(1, i-20), i-1)
        if cross_anchor is not None:
            attack_options = [cross_anchor] + ([cross_anchor+1] if cross_anchor+1 < i else [])
            attack_state = or_state([self.attack[k] for k in attack_options])
            possible_attacks = [k for k in attack_options if self.attack[k] != "FALSE"]
            anchor_uncertain = self.attack[attack_options[0]] == "UNKNOWN" and len(possible_attacks) > 1
            attack_index = None if anchor_uncertain else next(k for k in attack_options if self.attack[k] == "TRUE")
            support_checks = []
            for k in possible_attacks if anchor_uncertain else [attack_index]:
                segment_lows = self.low[cross_anchor:k+1]
                segment_low = float(np.min(segment_lows)) if np.all(np.isfinite(segment_lows)) else None
                check = condition("segment_support", self.close[i]-segment_low if segment_low is not None else None,
                                  ">=", 0, formula="C(t)>=low(crossover..ATTACK segment)")
                check["attack_date"] = self.date(k)
                support_checks.append(check)
            states = {item["state"] for item in support_checks}
            support = (support_checks[0] if len(support_checks) == 1 else
                       event("crossover_attack_segment_support", states.pop() if len(states) == 1 else "UNKNOWN",
                             "C(t)>=low(crossover..ATTACK segment) for all possible attack dates"))
            support["id"] = "crossover_attack_segment_support"
            if anchor_uncertain:
                support["possible_segments"] = support_checks
            rebuild = [
                event("white_yellow_crossover", "TRUE", "W(k)>Y(k), W(k-1)<=Y(k-1)", anchor=self.date(cross_anchor)),
                self.signal_event("attack_on_k_or_next", attack_state, "ATTACK on k or k+1 before t", attack_index,
                                  note="ATTACK date is uncertain" if anchor_uncertain else None),
                condition("white_above_yellow_today", self.w[i]-self.y[i], ">", 0, formula="W>Y"),
                condition("near_yellow", abs(self.close[i]/self.y[i]-1) if self.y[i] > 0 else None,
                          "<=", 0.03, formula="abs(C/Y-1)<=0.03"),
                condition("low_near_yellow", self.low[i]-1.03*self.y[i], "<=", 0, formula="L<=1.03*Y"),
                condition("close_above_yellow", self.close[i]-self.y[i], ">=", 0, formula="C>=Y"),
                self.signal_event("volume_shrink", self.shrink[i], "V3<=0.70*V20P", i),
                support,
            ]
            if anchor_uncertain:
                rebuild[1]["possible_attacks"] = [self.signal_event("attack", self.attack[k], "ATTACK", k)
                                                   for k in possible_attacks]
            rebuild_anchor = attack_index
        else:
            rebuild = [event("crossover_and_attack", event_state,
                             "crossover within prior 20 sessions; ATTACK on k or k+1")]
            rebuild_anchor = None
            anchor_uncertain = False
        result = self.branch(
            "skill_r2_rebuild", rebuild, anchor=rebuild_anchor,
            subtypes=["DOUBLE_LINE_REBUILD"] if cross_anchor is not None else [],
        )
        if anchor_uncertain:
            result["risk_anchor_uncertain"] = True
            result["crossover_anchor"] = self.anchor(cross_anchor)
        return result


    def branches(self) -> dict[str, dict[str, Any]]:
        i = self.index
        out: dict[str, dict[str, Any]] = {}

        # A. B1 standard/strict. A missing recent attack anchor is pending, not a false B1.
        b1_standard = self.b1_conditions(i, strict=False)
        b1_strict = self.b1_conditions(i, strict=True)
        b1_raw = all_conditions(b1_standard)
        attack_state, attack_index = self.find_attack(i-20, i-1)
        if attack_index is None:
            b1_required = [
                event("recent_attack_anchor", "UNKNOWN", "ATTACK in prior 1..20 sessions",
                      note="No confirmed attack reference; keep as pending subtype"),
                event("attack_low_support", "UNKNOWN", "C(t)>=L(recent ATTACK)"),
            ]
        else:
            b1_required = [
                self.signal_event("recent_attack_anchor", "TRUE", "ATTACK in prior 1..20 sessions", attack_index),
                condition("attack_low_support", self.close[i]-self.low[attack_index], ">=", 0,
                          formula="C(t)>=L(recent ATTACK)"),
            ]
        last_three = []
        search_end = i - 1
        attack_sequence_state = "TRUE"
        while len(last_three) < 3:
            event_state, event_index = self.find_attack(i-20, search_end)
            if event_index is None:
                attack_sequence_state = event_state
                break
            last_three.append(event_index)
            search_end = event_index - 1
        last_three.reverse()
        attack_turnover_inputs = [
            {"trade_date": self.date(k), "turnover_rate_pct": self.value(self.turnover, k)}
            for k in last_three
        ]
        if len(last_three) < 3 or attack_sequence_state != "TRUE":
            turnover_condition = event("cum_turnover_lt_38", "UNKNOWN",
                                       "sum(turnover_rate_pct of selected 3 ATTACK candles)<38.0 pct-points",
                                       note=f"Only {len(last_three)} ATTACK candles found in prior 20 sessions")
            turnover_condition["selected_attack_inputs"] = attack_turnover_inputs
            turnover_condition["required_attack_count"] = 3
        elif any(self.value(self.turnover, k) is None for k in last_three):
            turnover_condition = condition("cum_turnover_lt_38", None, "<", 38.0,
                                           formula="sum(turnover_rate_pct of selected 3 ATTACK candles)<38.0 pct-points",
                                           namespace="SKILL_EXPLICIT")
            turnover_condition["selected_attack_inputs"] = attack_turnover_inputs
            turnover_condition["missing_turnover_dates"] = [
                item["trade_date"] for item in attack_turnover_inputs
                if item["turnover_rate_pct"] is None
            ]
        else:
            turnover_condition = condition("cum_turnover_lt_38",
                                           sum(self.value(self.turnover, k) for k in last_three),
                                           "<", 38.0,
                                           formula="sum(turnover_rate_pct of selected 3 ATTACK candles)<38.0 pct-points",
                                           namespace="SKILL_EXPLICIT")
            turnover_condition["selected_attack_inputs"] = attack_turnover_inputs
        if self.weekly["state"] == "TRUE":
            weekly_conditions = [
                condition("weekly_ma_order",
                          min(self.weekly["ma55"]-self.weekly["ma144"],
                              self.weekly["ma144"]-self.weekly["ma233"]),
                          ">", 0, formula="weekly MA55>MA144>MA233"),
                condition("weekly_ma55_rising", self.weekly["ma55"]-self.weekly["previous_ma55"],
                          ">", 0, formula="completed-week MA55 rises"),
                condition("weekly_ma144_rising", self.weekly["ma144"]-self.weekly["previous_ma144"],
                          ">", 0, formula="completed-week MA144 rises"),
            ]
        else:
            weekly_conditions = [event("weekly_ma_enhancement", "UNKNOWN",
                                       "weekly MA55>MA144>MA233 and MA55/MA144 rise",
                                       note=self.weekly.get("reason"))]
        free_turnover = condition("free_turnover_lt_62", None, "<", 62.0,
                                  formula="sum(free_turnover_pct)<62.0 pct-points",
                                  namespace="SKILL_EXPLICIT")
        free_turnover["note"] = "No free-float denominator in the bound overlay; ordinary turnover is not substituted"
        standard_state, strict_state = all_conditions(b1_standard), all_conditions(b1_strict)
        out["skill_r2_b1"] = self.branch(
            "skill_r2_b1", b1_standard, required=b1_required,
            enhancements=weekly_conditions+[turnover_condition, free_turnover],
            anchor=attack_index,
            subtypes=([x for x, state in (("B1_NORMAL", standard_state), ("B1_STRICT", strict_state))
                       if state == "TRUE"] + ([] if attack_index is not None else ["NO_RECENT_ATTACK_REFERENCE"])),
            notes=["WEEKLY_USES_LAST_COMPLETED_WEEK", "FREE_TURNOVER_NOT_REPLACED_BY_ORDINARY_TURNOVER"],
        )
        out["skill_r2_b1"]["seed_state"] = b1_raw
        out["skill_r2_b1"]["strict_state"] = strict_state
        out["skill_r2_b1"]["conditions"].append(event("b1_strict_subtype", strict_state,
                                                       "B1 core and J<=-10"))
        out["skill_r2_b1"]["weekly_evidence"] = self.weekly

        # B. Anomaly shrink / Nana.
        nana_event_state, nana_anchor = self.find_attack(i-20, i-3)
        if nana_anchor is None:
            nana_core = [event("attack_anchor", nana_event_state, "ATTACK in t-20..t-3")]
            nana_extra = [event("two_attacks_in_five", "UNKNOWN",
                                "at least 2 ATTACK days in k and prior 4 sessions"),
                          condition("nana_j_negative", self.j[i], "<", 0, formula="J<0",
                                    namespace="SKILL_EXPLICIT")]
        else:
            nana_core = [
                self.signal_event("attack_anchor", "TRUE", "ATTACK in t-20..t-3", nana_anchor),
                self.signal_event("up_trend", self.up[i], "UP", i),
                self.signal_event("shrink", self.shrink[i], "V3<=0.70*V20P", i),
                condition("volume_vs_attack", self.v3[i], "<=", 0.60*self.volume[nana_anchor],
                          formula="V3(t)<=0.60*V(k)"),
                condition("close_below_attack_high", self.close[i], "<", self.high[nana_anchor],
                          formula="C(t)<H(k)"),
                condition("close_above_attack_low", self.close[i], ">=", self.low[nana_anchor],
                          formula="C(t)>=L(k)"),
            ]
            nana_extra = [
                event("two_attacks_in_five", count_at_least(self.attack, max(0, nana_anchor-4), nana_anchor, 2),
                      "at least 2 ATTACK days in k and prior 4 sessions"),
                condition("nana_j_negative", self.j[i], "<", 0, formula="J<0", namespace="SKILL_EXPLICIT"),
            ]
            nana_extra[0]["attack_inputs"] = [
                self.signal_event("attack", self.attack[k], "ATTACK", k)
                for k in range(max(0, nana_anchor-4), nana_anchor+1)
            ]
        out["skill_r2_nana"] = self.branch(
            "skill_r2_nana", nana_core, enhancements=nana_extra, anchor=nana_anchor,
            subtypes=["ANOMALY_SHRINK"] + (["NANA"] if nana_anchor is not None and
                      all_conditions(nana_extra) == "TRUE" else []),
        )

        # C. Super B1: attack, heavy down day within 5 sessions, then shrink stabilization.
        bear_state, bear_index = find_last(self.down_attack, max(0, i-5), i-1)
        prior_attack_state, prior_attack_index = ("UNKNOWN", None)
        if bear_index is not None:
            prior_attack_state, prior_attack_index = find_last(self.attack, max(0, i-20), bear_index-1)
            stabilization = self.candle_recovery_state(self.doji[i], self.open[i], self.close[i])
            super_core = [
                self.signal_event("prior_attack", prior_attack_state, "ATTACK in t-20..t-1, before k",
                                  prior_attack_index),
                self.signal_event("recent_heavy_down", "TRUE", "R<=-0.03 and V>=1.5*V20P in prior 1..5 sessions",
                                  bear_index),
                self.signal_event("up_trend", self.up[i], "UP", i),
                condition("J_negative", self.j[i], "<", 0, formula="J<0", namespace="SKILL_EXPLICIT"),
                condition("volume_vs_down_day", self.volume[i]-0.60*self.volume[bear_index], "<=", 0,
                          formula="V(t)<=0.60*V(k)"),
                condition("amplitude_max", self.amp[i], "<=", 0.07, formula="AMP<=0.07"),
                condition("close_above_down_low", self.close[i]-self.low[bear_index], ">=", 0,
                          formula="C(t)>=L(k)"),
                event("stabilization_candle", stabilization, "DOJI or C>O"),
            ]
        else:
            super_core = [event("recent_heavy_down", bear_state,
                                "R<=-0.03 and V>=1.5*V20P in prior 1..5 sessions")]
        out["skill_r2_super_b1"] = self.branch(
            "skill_r2_super_b1", super_core,
            enhancements=[event("reliable_limit_down_data", "UNKNOWN",
                                "exclude confirmed limit-down breakdown subtype",
                                note="Estimated price limit fields are not treated as authoritative")],
            anchor=prior_attack_index,
            subtypes=["SUPER_B1_STABILIZATION"] if bear_index is not None else [],
        )

        # D. SB1 observation on the breakdown day, or recovery candidate next day.
        today_sb1 = self.sb1_breakdown(i)
        yesterday_sb1 = self.sb1_breakdown(i-1) if i >= 1 else []
        if yesterday_sb1:
            yesterday_sb1 += [
                condition("recovery_close_above_low", self.close[i]-self.low[i-1], ">=", 0,
                          formula="C(t)>=L(k)"),
                condition("recovery_volume", self.volume[i]-self.volume[i-1], "<=", 0,
                          formula="V(t)<=V(k)"),
                event("recovery_candle", self.candle_recovery_state(self.doji[i], self.open[i], self.close[i]),
                      "C>O or DOJI"),
            ]
        today_state, yesterday_state = all_conditions(today_sb1), all_conditions(yesterday_sb1)
        if today_state == "TRUE":
            sb1_seed, sb1_type, sb1_anchor = today_sb1, ["SB1_BREAKDOWN_OBSERVATION"], i
        elif yesterday_state == "TRUE":
            sb1_seed, sb1_type, sb1_anchor = yesterday_sb1, ["SB1_NEXTDAY_RECOVERY_CANDIDATE"], i-1
        elif "UNKNOWN" in (today_state, yesterday_state):
            sb1_seed = [event("sb1_observation_or_recovery", "UNKNOWN",
                              "SB1 breakdown today or recovery after yesterday breakdown")]
            sb1_type, sb1_anchor = [], None
        else:
            sb1_seed = [event("sb1_observation_or_recovery", "FALSE",
                              "SB1 breakdown today or recovery after yesterday breakdown")]
            sb1_type, sb1_anchor = [], None
        out["skill_r2_sb1"] = self.branch("skill_r2_sb1", sb1_seed,
                                          anchor=sb1_anchor, subtypes=sb1_type)

        # E. B2 confirmation after an A-group B1 candidate.
        b2 = self.b2_result(i)
        out["skill_r2_b2"] = self.branch("skill_r2_b2", b2["conditions"],
                                         anchor=b2["anchor"],
                                         subtypes=["B2_CONFIRMATION"] if b2["state"] == "TRUE" else [])

        # F. Ordinary B3 and the stricter Changan sequence.
        if i >= 2:
            b1_t2 = self.b1_result(i-2)
            b2_yesterday = self.b2_result(i-1)
            small_green = and_state([
                self.doji[i],
                condition("green", self.close[i]-self.open[i], ">", 0, formula="C>O")["state"],
            ])
            green_small = or_state([self.doji[i], small_green])
            changan = [
                event("B1_at_t_minus_2", b1_t2["normal"], "A-group B1 numeric candidate at t-2",
                      anchor=self.date(i-2)),
                condition("J_t_minus_2", self.j[i-2], "<", -13, formula="J(t-2)<-13",
                          namespace="SKILL_EXPLICIT"),
                event("B2_at_t_minus_1", b2_yesterday["state"], "B2 candidate at t-1",
                      anchor=self.date(b2_yesterday["anchor"])),
                condition("abs_return_lt_2pct", abs(self.ret[i]) if number(self.ret[i]) is not None else None,
                          "<", 0.02, formula="abs(R)<0.02", namespace="SKILL_EXPLICIT"),
                condition("amplitude_lt_7pct", self.amp[i], "<", 0.07, formula="AMP<0.07",
                          namespace="SKILL_EXPLICIT"),
                condition("half_volume", self.volume[i]-0.50*self.volume[i-1], "<=", 0,
                          formula="V(t)<=0.50*V(t-1)"),
                condition("flat_open", abs(self.open[i]/self.close[i-1]-1) if self.close[i-1] > 0 else None,
                          "<=", 0.01, formula="abs(O/Cprev-1)<=0.01"),
                event("doji_or_small_green", green_small, "DOJI or small-bodied green; local BODY<=0.25"),
            ]
        else:
            changan = [event("changan_window", "UNKNOWN", "t-2 B1, t-1 B2, current small/quiet candle")]
        prior_b2_states = []
        for k in range(max(0, i-2), i):
            result = self.b2_result(k)
            prior_b2_states.append((k, result["state"]))
        prior_b2_state, prior_b2_position = find_last(
            [state for _, state in prior_b2_states], 0, len(prior_b2_states)-1)
        prior_b2 = prior_b2_states[prior_b2_position][0] if prior_b2_position is not None else None
        if prior_b2 is not None:
            ordinary_b3 = [
                event("prior_B2", "TRUE", "B2 in prior 1..2 sessions", anchor=self.date(prior_b2)),
                condition("small_candle", self.body[i], "<=", 0.25,
                          formula="BODY<=0.25; local small-body proxy"),
                condition("volume_below_B2", self.volume[i]-self.volume[prior_b2], "<", 0,
                          formula="V(t)<V(B2)"),
                condition("close_above_B2_low", self.close[i]-self.low[prior_b2], ">=", 0,
                          formula="C(t)>=L(B2)"),
            ]
        else:
            ordinary_b3 = [event("prior_B2", prior_b2_state,
                                 "B2 in prior 1..2 sessions")]
        ordinary_state, changan_state = all_conditions(ordinary_b3), all_conditions(changan)
        selected_b3 = ordinary_b3 if ordinary_state == "TRUE" else (
            changan if changan_state == "TRUE" else (
                ordinary_b3 if ordinary_state == "UNKNOWN" else changan if changan_state == "UNKNOWN"
                else [event("B3_pattern", "FALSE", "ordinary B3 or Changan")]))
        out["skill_r2_b3"] = self.branch(
            "skill_r2_b3", selected_b3,
            anchor=prior_b2 if ordinary_state == "TRUE" else (i-1 if changan_state == "TRUE" else None),
            subtypes=(["B3_ORDINARY"] if ordinary_state == "TRUE" else []) +
                     (["B3_CHANGAN"] if changan_state == "TRUE" else []),
            notes=["SMALL_GREEN_BODY_0.25_IS_LOCAL_RESEARCH_DEFAULT"],
        )
        out["skill_r2_b3"]["alternative_states"] = {
            "ordinary_b3": ordinary_state, "changan": changan_state,
        }
        out["skill_r2_b3"]["alternative_conditions"] = {
            "ordinary_b3": ordinary_b3, "changan": changan,
        }

        # G. Double-gun / parallel heavy attack.
        parallel_state, parallel_anchor = find_last(self.attack, max(0, i-10), i-2)
        if parallel_anchor is None:
            parallel = [event("prior_attack", parallel_state, "ATTACK in prior 2..10 sessions")]
            parallel_type = []
        else:
            mids = list(range(parallel_anchor+1, i))
            midpoint = (self.open[i]+self.close[i])/2
            midpoint_anchor = (self.open[parallel_anchor]+self.close[parallel_anchor])/2
            mid_conditions = []
            for k in mids:
                mid_conditions.extend([
                    condition("intermediate_volume", self.volume[k]-0.70*min(self.volume[parallel_anchor], self.volume[i]),
                              "<=", 0, formula="V(mid)<=0.70*min(V(k),V(t))"),
                    condition("intermediate_support", self.close[k]-self.low[parallel_anchor], ">=", 0,
                              formula="C(mid)>=L(k)"),
                ])
            parallel = [
                self.signal_event("today_attack", self.attack[i], "ATTACK(t)", i),
                self.signal_event("prior_attack", "TRUE", "ATTACK in prior 2..10 sessions", parallel_anchor),
                condition("body_midpoint_distance",
                          abs(midpoint-midpoint_anchor)/self.close[parallel_anchor] if self.close[parallel_anchor] > 0 else None,
                          "<=", 0.05, formula="abs(midpoint(t)-midpoint(k))/C(k)<=0.05"),
            ] + mid_conditions
            bearish_middle_count = sum(
                1 for k in mids if number(self.close[k]) is not None and number(self.open[k]) is not None
                and self.close[k] < self.open[k]
            )
            unknown_middle_count = sum(
                1 for k in mids if number(self.close[k]) is None or number(self.open[k]) is None
            )
            if bearish_middle_count > 4 or bearish_middle_count + unknown_middle_count < 4:
                four_bearish_state = "FALSE"
            elif unknown_middle_count:
                four_bearish_state = "UNKNOWN"
            else:
                four_bearish_state = "TRUE"
            parallel_type = ["PARALLEL_TWO_ATTACK"]
            if four_bearish_state == "TRUE":
                parallel_type.append("FOUR_BEARISH_MIDDLES")
        out["skill_r2_parallel"] = self.branch(
            "skill_r2_parallel", parallel, anchor=parallel_anchor, subtypes=parallel_type,
        )
        if parallel_anchor is not None:
            out["skill_r2_parallel"]["four_bearish_middles"] = {
                "state": four_bearish_state, "known_bearish_count": bearish_middle_count,
                "unknown_candle_count": unknown_middle_count,
            }

        # H. Reuse the same composite-event branch for full and incremental runs.
        out["skill_r2_rebuild"] = self.rebuild_branch()

        # I. Platform pattern. Market regime is missing and stays an enhancement UNKNOWN.
        start = i-20
        if start < 0:
            platform = [event("platform_window", "UNKNOWN", "complete prior 20 sessions")]
            platform_bounds = {"lower": None, "upper": None}
            platform_subtype = []
        else:
            h20, l20 = self.high[start:i], self.low[start:i]
            high_bound = float(np.max(h20)) if np.all(np.isfinite(h20)) else None
            low_bound = float(np.min(l20)) if np.all(np.isfinite(l20)) else None
            ratio = high_bound/low_bound-1 if high_bound is not None and low_bound is not None and low_bound > 0 else None
            volumes = self.volume[start:i]
            opens, closes, priors = self.open[start:i], self.close[start:i], self.v20[start:i]
            complete = np.isfinite(volumes) & np.isfinite(opens) & np.isfinite(closes)
            bull = complete & (closes > opens)
            bear = complete & (closes < opens)
            bull_indices = np.flatnonzero(bull)
            bear_indices = np.flatnonzero(bear)
            heavy_bull_states = [and_state([
                condition("green", closes[k]-opens[k], ">", 0, formula="C>O")["state"],
                condition("heavy_volume", volumes[k]-1.5*priors[k], ">=", 0,
                          formula="V>=1.5*V20P")["state"],
            ]) for k in range(len(volumes))]
            bull_count = count_at_least(heavy_bull_states, 0, len(heavy_bull_states)-1, 3)
            if not np.all(complete) or len(bull_indices) == 0 or len(bear_indices) == 0:
                dominance = "UNKNOWN"
            else:
                bv, ev = volumes[bull], volumes[bear]
                dominance = "TRUE" if bv.sum() > ev.sum() and bv.mean() > ev.mean() else "FALSE"
            platform = [
                condition("range_max", ratio, "<=", 0.15, formula="max(H20)/min(L20)-1<=0.15"),
                event("platform_bull_volume_days", bull_count, "at least 3 prior C>O and V>=1.5*V20P sessions"),
                event("bull_volume_dominance", dominance, "bull total/mean volume exceed bear total/mean"),
                condition("close_not_below_platform", self.close[i]-low_bound if low_bound is not None else None,
                          ">=", 0, formula="C(t)>=platform lower bound"),
            ]
            platform[1]["known_heavy_bull_dates"] = [self.date(start+k) for k, state in enumerate(heavy_bull_states) if state == "TRUE"]
            platform[1]["unknown_days"] = heavy_bull_states.count("UNKNOWN")
            platform[2]["inputs"] = {
                "bull_days": len(bull_indices), "bear_days": len(bear_indices),
                "bull_volume_sum": float(volumes[bull].sum()) if np.all(complete) and len(bull_indices) else None,
                "bear_volume_sum": float(volumes[bear].sum()) if np.all(complete) and len(bear_indices) else None,
                "bull_volume_mean": float(volumes[bull].mean()) if np.all(complete) and len(bull_indices) else None,
                "bear_volume_mean": float(volumes[bear].mean()) if np.all(complete) and len(bear_indices) else None,
            }
            platform_bounds = {"lower": low_bound, "upper": high_bound}
            platform_subtype = ["PLATFORM_BREAKOUT" if high_bound is not None and self.close[i] > high_bound
                                else "PLATFORM_CONSOLIDATION"]
        out["skill_r2_platform"] = self.branch(
            "skill_r2_platform", platform,
            enhancements=[event("market_bull_context", "UNKNOWN",
                                "market timing supports platform pattern",
                                note="D28 breadth fields unavailable; not assumed")],
            anchor=start if start >= 0 else None, subtypes=platform_subtype,
        )
        out["skill_r2_platform"]["platform_bounds"] = platform_bounds

        return out

    def risk_check(self, branch: dict[str, Any]) -> dict[str, Any]:
        if branch.get("risk_anchor_uncertain"):
            return {"state": "UNKNOWN", "flags": [], "conditions": [],
                    "unknown_checks": [{"id": "ATTACK_DATE_UNCERTAIN", "trade_date": None}]}
        anchor_date = (branch.get("event_anchor") or {}).get("trade_date")
        if not anchor_date:
            return {"state": "NOT_APPLICABLE", "flags": [], "conditions": [], "unknown_checks": []}
        anchor_index = self.calendar.index(anchor_date)
        flags, unknown_checks, all_conditions_seen = [], [], []
        for j in range(max(1, anchor_index+1), self.index+1):
            high_zone = condition("high_zone", self.high[j]-0.95*self.high60prev[j], ">=", 0,
                                  formula="H>=0.95*max(H prior 60 sessions)")
            distribution = [
                high_zone,
                condition("distribution_return", self.ret[j], "<=", -0.04, formula="R<=-0.04"),
                condition("distribution_volume", self.volume[j]-2.0*self.v20[j], ">=", 0,
                          formula="V>=2*V20P"),
                condition("distribution_bear", self.close[j]-self.open[j], "<", 0,
                          formula="C<O"),
                condition("distribution_body", self.body[j], ">=", 0.60, formula="BODY>=0.60"),
                condition("target_below_distribution_high", self.close[self.index]-self.high[j], "<", 0,
                          formula="C(t)<H(distribution event)"),
            ]
            state = all_conditions(distribution)
            all_conditions_seen.extend(distribution)
            if state == "TRUE":
                flags.append({"id": "HIGH_ZONE_HEAVY_DISTRIBUTION", "trade_date": self.date(j),
                              "conditions": distribution})
            elif state == "UNKNOWN":
                unknown_checks.append({"id": "HIGH_ZONE_HEAVY_DISTRIBUTION",
                                       "trade_date": self.date(j), "conditions": distribution})

            didi = [
                high_zone,
                condition("second_bear", self.close[j]-self.open[j], "<", 0, formula="C(j)<O(j)"),
                condition("first_bear", self.close[j-1]-self.open[j-1], "<", 0, formula="C(j-1)<O(j-1)"),
                condition("step_below_previous_low", self.close[j]-self.low[j-1], "<", 0,
                          formula="C(j)<L(j-1)"),
                condition("didi_volume", self.volume[j]-0.80*self.volume[j-1], ">=", 0,
                          formula="V(j)>=0.80*V(j-1)"),
            ]
            state = all_conditions(didi)
            all_conditions_seen.extend(didi)
            if state == "TRUE":
                flags.append({"id": "HIGH_ZONE_DIDI_STEPDOWN", "trade_date": self.date(j),
                              "conditions": didi})
            elif state == "UNKNOWN":
                unknown_checks.append({"id": "HIGH_ZONE_DIDI_STEPDOWN",
                                       "trade_date": self.date(j), "conditions": didi})
        # A failed breakout is a local risk proxy: within three sessions, the
        # close returns below the lower bound of the original 20-session range.
        for breakout_index in range(max(20, self.index-3), self.index):
            prior_high = float(np.max(self.high[breakout_index-20:breakout_index])) \
                if np.all(np.isfinite(self.high[breakout_index-20:breakout_index])) else None
            prior_low = float(np.min(self.low[breakout_index-20:breakout_index])) \
                if np.all(np.isfinite(self.low[breakout_index-20:breakout_index])) else None
            breakout_state = condition(
                "close_breakout", self.close[breakout_index]-prior_high if prior_high is not None else None,
                ">", 0, formula="C(breakout)>max(H prior 20 sessions)",
            )["state"]
            if breakout_state == "TRUE":
                failures = []
                for k in range(breakout_index+1, min(self.index, breakout_index+3)+1):
                    failed = condition(
                        "failed_breakout_return_to_platform",
                        self.close[k]-prior_low if prior_low is not None else None,
                        "<", 0, formula="C(k)<min(L original prior-20 platform)",
                    )
                    failed["trade_date"] = self.date(k)
                    failures.append(failed)
                check = [event("recent_breakout", "TRUE", "close breakout in prior 1..3 sessions",
                               anchor=self.date(breakout_index))] + failures
                failure_state = or_state(item["state"] for item in failures)
                if failure_state == "TRUE":
                    failure_date = next(item["trade_date"] for item in failures if item["state"] == "TRUE")
                    flags.append({"id": "FAILED_BREAKOUT", "trade_date": self.date(breakout_index),
                                  "failure_trade_date": failure_date,
                                  "conditions": check})
                elif failure_state == "UNKNOWN":
                    unknown_checks.append({"id": "FAILED_BREAKOUT",
                                           "trade_date": self.date(breakout_index),
                                           "conditions": check})
            elif breakout_state == "UNKNOWN":
                unknown_checks.append({"id": "FAILED_BREAKOUT",
                                       "trade_date": self.date(breakout_index),
                                       "conditions": [event("close_breakout", "UNKNOWN",
                                                            "C(breakout)>max(H prior 20 sessions)") ]})
        return {"state": "TRUE" if flags else ("UNKNOWN" if unknown_checks else "FALSE"),
                "flags": flags, "conditions": all_conditions_seen, "unknown_checks": unknown_checks}

    def warnings(self) -> list[dict[str, Any]]:
        i = self.index
        warnings = []
        upper = condition("long_upper_shadow_warning", self.upper[i], ">=", 0.40,
                          formula="UPPER>=0.40; warning only")
        if upper["state"] == "TRUE":
            warnings.append(upper)
        ret20 = self.close[i]/self.close[i-20]-1 if i >= 20 and self.close[i-20] > 0 else None
        surge = condition("return_20d_warning", ret20, ">=", 0.30,
                          formula="20-session return>=0.30; warning only")
        if surge["state"] == "TRUE":
            warnings.append(surge)
        return warnings


def unknown_branches(reason: str) -> dict[str, dict[str, Any]]:
    branches = {}
    for group_id in GROUP_IDS:
        item = event("target_day_data", "UNKNOWN", "target-day bar is not valid for screening", note=reason)
        branches[group_id] = {
            "group_id": group_id, "seed_state": "UNKNOWN", "required_state": "UNKNOWN",
            "enhancement_state": "UNKNOWN", "state": "UNKNOWN", "conditions": [item],
            "event_anchor": None, "subtypes": [], "notes": [reason],
            "risk_state": "NOT_EVALUATED", "risk_flags": [],
        }
    return branches


def resolve_branch_states(
    series: StockSeries, branches: dict[str, dict[str, Any]], *,
    identity_excluded: bool,
) -> None:
    for branch in branches.values():
        if branch["seed_state"] != "TRUE":
            branch["state"] = branch["seed_state"]
            continue
        risk = series.risk_check(branch)
        branch["risk_state"] = risk["state"]
        branch["risk_flags"] = risk["flags"]
        branch["risk_conditions"] = risk["conditions"]
        branch["risk_unknown_checks"] = risk["unknown_checks"]
        if risk["state"] == "TRUE":
            branch["state"] = "RISK_REVIEW"
        elif identity_excluded:
            branch["state"] = "IDENTITY_EXCLUDED"
        elif branch["required_state"] == "FALSE":
            branch["state"] = "FILTERED"
        elif (branch["required_state"] == "UNKNOWN"
              or branch["enhancement_state"] == "UNKNOWN"
              or risk["state"] == "UNKNOWN"):
            branch["state"] = "PENDING_CHECK"
        else:
            branch["state"] = "CHART_QUEUE"


def classify(branches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = [key for key, value in branches.items() if value["seed_state"] == "TRUE"]
    unknown = [key for key, value in branches.items() if value["seed_state"] == "UNKNOWN"]
    chart = [key for key, value in branches.items() if value["state"] == "CHART_QUEUE"]
    pending = [key for key, value in branches.items() if value["state"] == "PENDING_CHECK"]
    risk = [key for key, value in branches.items() if value["state"] == "RISK_REVIEW"]
    filtered = [key for key, value in branches.items()
                if value["state"] in {"FILTERED", "IDENTITY_EXCLUDED"}]
    if not raw:
        status = "UNKNOWN_WITHOUT_SEED" if unknown else "NOT_TRIGGERED"
    elif chart and pending:
        status = "MIXED_CHART_AND_PENDING"
    elif chart:
        status = "CHART_QUEUE"
    elif pending and risk:
        status = "MIXED_PENDING_AND_RISK"
    elif pending:
        status = "PENDING_CHECK"
    elif risk:
        status = "RISK_REVIEW"
    else:
        status = "FILTERED_RAW_HIT"
    return {
        "record_status": status,
        "raw_hit_group_ids": raw,
        "chart_queue_group_ids": chart,
        "chart_review_eligible_group_ids": chart + pending,
        "pending_group_ids": pending,
        "risk_review_group_ids": risk,
        "filtered_group_ids": filtered,
        "unknown_group_ids": unknown,
    }


def evaluate_code(
    code: str, frame: pd.DataFrame, calendar: list[str], asof: str, *,
    name: Any, exchange: Any, market_type: Any, turnover_status: Optional[str],
    lifecycle_reason: Optional[str], lifecycle_detail: Optional[dict[str, Any]],
    ruleset_sha256: str, writer_source_sha256: str, name_source_date: Optional[str] = None,
) -> dict[str, Any]:
    valid_bar = turnover_status != "G4_UNPRICED_OR_MISSING"
    if valid_bar:
        series = StockSeries(frame, calendar, asof)
        branches = series.branches()
        resolve_branch_states(series, branches, identity_excluded=bool(lifecycle_reason))
        warnings = series.warnings()
    else:
        reason = "TURNOVER_OVERLAY_G4_UNPRICED_OR_MISSING"
        branches = unknown_branches(reason)
        warnings = []
    summary = classify(branches)
    return {
        "ts_code": code,
        "name": scalar(name),
        "name_source_date": name_source_date,
        "exchange": scalar(exchange),
        "market_type": scalar(market_type),
        "asof": asof,
        "record_status": summary["record_status"],
        "identity_status": (
            "CONFIRMED_DELISTED" if lifecycle_reason == "VERIFIED_DELISTED_EFFECTIVE_ON_OR_BEFORE_ASOF"
            else "CONFIRMED_SUSPENDED" if lifecycle_reason == "VERIFIED_SUSPENSION_ON_ASOF"
            else "UNCONFIRMED_ST_STATUS"
        ),
        "identity_reason": lifecycle_reason,
        "identity_evidence": lifecycle_detail,
        "target_bar_status": turnover_status or "TURNOVER_STATUS_NOT_PROVIDED",
        "raw_hit_group_ids": summary["raw_hit_group_ids"],
        "chart_queue_group_ids": summary["chart_queue_group_ids"],
        "chart_review_eligible_group_ids": summary["chart_review_eligible_group_ids"],
        "pending_group_ids": summary["pending_group_ids"],
        "risk_review_group_ids": summary["risk_review_group_ids"],
        "filtered_group_ids": summary["filtered_group_ids"],
        "unknown_group_ids": summary["unknown_group_ids"],
        "branches": branches,
        "warning_flags": warnings,
        "chart_review": {"status": "NOT_REVIEWED", "reviewer": None, "result": None, "image_ref": None},
        "historical_success_statistics": {
            "status": "NO_SAME_RULESET_D2_D5_SERIES",
            "source_group_identity": None,
        },
        "ruleset_id": RULESET_ID,
        "ruleset_sha256": ruleset_sha256,
        "source_generation": GENERATION,
        "writer_source_sha256": writer_source_sha256,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _target_row_lookup(target: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result = {}
    for row in target.to_dict(orient="records"):
        result[str(row["ts_code"])] = row
    return result


def last_valid_name(frame: pd.DataFrame, asof: str) -> tuple[Optional[str], Optional[str]]:
    """Use only the latest nonblank name in the bound generation through as-of."""
    known = frame.loc[frame["trade_date"].astype(str) <= asof, ["trade_date", "name"]].copy()
    known = known.loc[known["name"].notna()]
    known["name"] = known["name"].astype(str).str.strip()
    known = known.loc[known["name"] != ""]
    if known.empty:
        return None, None
    item = known.loc[known["trade_date"].astype(str).idxmax()]
    return str(item["name"]), str(item["trade_date"])


def _evaluate_subset(
    projection: pd.DataFrame, target: pd.DataFrame, selected_codes: set[str],
    *, asof: str, exclusions: dict[str, str], lifecycle_details: dict[str, Any],
    ruleset_sha256: str, writer_source_sha256: str,
) -> list[dict[str, Any]]:
    calendar = sorted(projection["trade_date"].dropna().astype(str).unique().tolist())
    if not calendar or calendar[-1] != asof:
        raise RuntimeError("date calendar does not end at frozen as-of")
    target_map = _target_row_lookup(target)
    results = []
    relevant = projection.loc[projection["ts_code"].astype(str).isin(selected_codes)]
    for code, frame in relevant.groupby("ts_code", sort=False):
        code = str(code)
        if code not in target_map:
            continue
        row = target_map[code]
        reason = exclusions.get(code)
        name, name_source_date = last_valid_name(frame, asof)
        results.append(evaluate_code(
            code, frame, calendar, asof,
            name=name, name_source_date=name_source_date, exchange=row.get("exchange"),
            market_type=row.get("market_type"), turnover_status=row.get("turnover_status"),
            lifecycle_reason=reason, lifecycle_detail=lifecycle_details.get(code),
            ruleset_sha256=ruleset_sha256, writer_source_sha256=writer_source_sha256,
        ))
    if len(results) != len(selected_codes):
        missing = sorted(selected_codes - {row["ts_code"] for row in results})
        raise RuntimeError(f"selected code/date missing from projection: {missing[:10]}")
    return sorted(results, key=lambda row: row["ts_code"])


def _status_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def add_event_price_inputs(value: Any, series: StockSeries, date_index: dict[str, int]) -> None:
    """Enrich previously saved signal evidence from the same narrow OHLC prefix."""
    if isinstance(value, list):
        for entry in value:
            add_event_price_inputs(entry, series, date_index)
    elif isinstance(value, dict):
        inputs = value.get("inputs")
        if isinstance(inputs, dict) and inputs.get("trade_date"):
            day = inputs["trade_date"]
            if day not in date_index:
                raise RuntimeError(f"saved event outside H repair projection: {day}")
            k = date_index[day]
            inputs.update({"O": series.value(series.open, k), "C": series.value(series.close, k),
                           "H": series.value(series.high, k), "L": series.value(series.low, k),
                           "previous_close": series.value(series.close, k-1)})
        for entry in value.values():
            add_event_price_inputs(entry, series, date_index)


def h_repair_rows(previous_receipt: Path, codes: Optional[set[str]] = None,
                  history_start: str = "20260501") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recompute only H and its direct aggregation, enriching saved signal inputs."""
    old = json.loads(previous_receipt.read_text(encoding="utf-8"))
    if (old.get("asof") != ASOF or old.get("ruleset_id") != RULESET_ID
            or old.get("source", {}).get("generation_id") != GENERATION
            or old.get("counts", {}).get("accepted_target_rows") != 5538
            or old.get("counts", {}).get("quarantine_retained_separately") != QUARANTINE):
        raise RuntimeError("H repair predecessor identity mismatch")
    if sha256(RECEIPT_PATH) != old["source"]["receipt_sha256_actual"]:
        raise RuntimeError("H repair source receipt changed")
    validate_receipt(json.loads(RECEIPT_PATH.read_text(encoding="utf-8")), SELECTOR_PATH, ASOF)
    old_ref = old["artifacts"]["d28_all_5538_R2.jsonl"]
    old_path = Path(old_ref["path"])
    if sha256(old_path) != old_ref["sha256"]:
        raise RuntimeError("H repair predecessor output SHA changed")
    prior = {}
    with old_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if codes is None or row["ts_code"] in codes:
                prior[row["ts_code"]] = row
    selected = set(prior)
    if (codes is None and len(selected) != 5538) or (codes is not None and selected != codes):
        raise RuntimeError("H repair predecessor key set mismatch")
    interface = load_interface(INTERFACE_PATH)
    meta = interface.get_panel_meta(panel_path=SELECTOR_PATH, include_dates=False)
    if meta.get("generation_id") != GENERATION or meta.get("path") != str(SELECTOR_PATH):
        raise RuntimeError("H repair selector binding mismatch")
    columns = ["trade_date", "ts_code", "market_type", "exchange", "open", "high", "low", "close",
               "volume", "zge_white_line", "zge_yellow_line"]
    filters = [("market_type", "in", ["A_SHARE", "BJ"])]
    if codes is not None:
        filters.append(("ts_code", "in", sorted(codes)))
    projection = interface.load_selector_ready(columns=columns, start_date=history_start, end_date=ASOF,
                                               filters=filters, panel_path=SELECTOR_PATH)
    projection["trade_date"] = projection["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    projection["ts_code"] = projection["ts_code"].astype(str)
    if projection.duplicated(["ts_code", "trade_date"]).any() or (projection["trade_date"] > ASOF).any():
        raise RuntimeError("H repair duplicate or future input")
    target_codes = set(projection.loc[projection["trade_date"] == ASOF, "ts_code"])
    calendar = sorted(projection["trade_date"].unique().tolist())
    if target_codes != selected or not calendar or calendar[-1] != ASOF or len(calendar) < 81:
        raise RuntimeError("H repair projection misses target keys or required prior sessions")
    # A historical prefix can also contain securities absent from D28 admission.
    projection = projection.loc[projection["ts_code"].isin(selected)]
    date_index = {day: i for i, day in enumerate(calendar)}
    repair_sha = sha256(Path(__file__).resolve())
    changed = 0
    for code, frame in projection.groupby("ts_code", sort=False):
        row = prior[code]
        if row["target_bar_status"] != "G4_UNPRICED_OR_MISSING":
            series = StockSeries(frame, calendar, ASOF, rebuild_only=True)
            old_h = row["branches"]["skill_r2_rebuild"]
            new_h = series.rebuild_branch()
            resolve_branch_states(series, {"skill_r2_rebuild": new_h}, identity_excluded=bool(row["identity_reason"]))
            row["branches"]["skill_r2_rebuild"] = new_h
            add_event_price_inputs(row["branches"], series, date_index)
            if old_h != new_h:
                changed += 1
            row.update(classify(row["branches"]))
            row["h_repair_source_sha256"] = repair_sha
    info = {"predecessor_receipt": {"path": str(previous_receipt), "sha256": sha256(previous_receipt)},
            "repair_source": {"path": str(Path(__file__).resolve()), "sha256": repair_sha},
            "history_start": history_start, "projection_rows": int(len(projection)),
            "projection_dates": len(calendar), "H_branch_changed_rows": changed,
            "columns": columns, "scope": "H branch, direct risk/classification, OHLC event evidence only",
            "other_eight_rules_recomputed": False, "turnover_recomputed": False,
            "weekly_recomputed": False, "historical_returns_recomputed": False}
    return sorted(prior.values(), key=lambda row: row["ts_code"]), info


def run_h_repair(output_dir: Path, previous_receipt: Path, *, codes: Optional[set[str]] = None) -> dict[str, Any]:
    rows, info = h_repair_rows(previous_receipt, codes)
    output_dir.mkdir(parents=True, exist_ok=True)
    if codes is not None:
        pilot = {"schema": "zge_skill_d28_h_repair_pilot/1", "asof": ASOF,
                 "info": info, "rows": rows, "RESEARCH_ONLY": True,
                 "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        (output_dir / "h_repair_pilot.json").write_text(
            json.dumps(pilot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return pilot
    if len(rows) != 5538 or len({row["ts_code"] for row in rows}) != 5538:
        raise RuntimeError("H repair failed 5538 accepted-key conservation")
    old = json.loads(previous_receipt.read_text(encoding="utf-8"))
    candidates = [row for row in rows if row["raw_hit_group_ids"]]
    all_path = output_dir / "d28_all_5538_R2.jsonl"
    candidate_path = output_dir / "d28_candidate_union_R2.jsonl"
    _write_jsonl(all_path, rows)
    _write_jsonl(candidate_path, candidates)
    artifacts = {
        all_path.name: {"path": str(all_path), "rows": len(rows), "sha256": sha256(all_path)},
        candidate_path.name: {"path": str(candidate_path), "rows": len(candidates), "sha256": sha256(candidate_path)},
    }
    group_counts = {}
    for group in GROUP_IDS:
        subset = [row for row in candidates if group in row["raw_hit_group_ids"]]
        path = output_dir / f"{group}_D28.jsonl"
        _write_jsonl(path, subset)
        artifacts[path.name] = {"path": str(path), "rows": len(subset), "sha256": sha256(path)}
        group_counts[group] = len(subset)
    counts = dict(old["counts"])
    counts.update({
        "accepted_target_rows": len(rows), "quarantine_retained_separately": QUARANTINE,
        "candidate_union": len(candidates), "unique_candidate_codes": len({r["ts_code"] for r in candidates}),
        "group_memberships": group_counts, "record_status": _status_counts(rows, "record_status"),
        "target_bar_status": _status_counts(rows, "target_bar_status"),
        "pending_group_memberships": {g: sum(g in r["pending_group_ids"] for r in rows) for g in GROUP_IDS},
        "risk_group_memberships": {g: sum(g in r["risk_review_group_ids"] for r in rows) for g in GROUP_IDS},
    })
    old["counts"] = counts
    old["artifacts"] = artifacts
    old["h_repair"] = info
    old["run_parameters"]["incremental_h_repair_only"] = True
    old["run_parameters"]["other_eight_rules_reused"] = True
    old["run_parameters"]["saved_signal_ohlc_evidence_enriched"] = True
    (output_dir / "D28_RUN_RECEIPT_R2.json").write_text(
        json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return old


def run_pilot(
    output_dir: Path,
    codes: Iterable[str] = ("000001.SZ", "920510.BJ", "002717.SZ"),
    *, panel_path: Path = SELECTOR_PATH,
    interface_path: Path = INTERFACE_PATH,
    receipt_path: Path = RECEIPT_PATH,
    turnover_manifest_path: Path = TURNOVER_MANIFEST,
    turnover_d28_path: Path = TURNOVER_D28,
    lifecycle_path: Path = LIFECYCLE_PATH,
    asof: str = ASOF,
    history_start: str = HISTORY_START,
) -> dict[str, Any]:
    """Three-code canary using only exact D28 codes, before the full materialization."""
    selected = set(map(str, codes))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validate_receipt(receipt, panel_path, asof)
    interface = load_interface(interface_path)
    meta = interface.get_panel_meta(panel_path=panel_path, include_dates=False)
    if meta.get("generation_id") != GENERATION or meta.get("path") != str(panel_path):
        raise RuntimeError("pilot data binding does not match frozen D28 generation")
    projection = interface.load_selector_ready(
        columns=PANEL_COLUMNS, start_date=history_start, end_date=asof,
        filters=[("market_type", "in", ["A_SHARE", "BJ"]), ("ts_code", "in", sorted(selected))],
        panel_path=panel_path,
    )
    projection["trade_date"] = projection["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    projection["ts_code"] = projection["ts_code"].astype(str)
    target = projection.loc[projection["trade_date"] == asof].copy()
    if set(target["ts_code"]) != selected or target["ts_code"].duplicated().any():
        raise RuntimeError("pilot exact D28 code set is incomplete")
    turnover, turnover_receipt = load_turnover_history(
        selected, history_start, turnover_manifest_path, verify_parts=True)
    projection = merge_turnover(projection, turnover, turnover_d28_path)
    target = projection.loc[projection["trade_date"] == asof].copy()
    exclusions, details = lifecycle_exclusions(lifecycle_path, asof)
    config_sha = sha256(RULESET_PATH)
    code_sha = sha256(Path(__file__).resolve())
    rows = _evaluate_subset(projection, target, selected, asof=asof,
                            exclusions=exclusions, lifecycle_details=details,
                            ruleset_sha256=config_sha, writer_source_sha256=code_sha)
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "pilot_3_records.json"
    pilot = {
        "schema": "zge_skill_d28_pilot/1",
        "asof": asof,
        "generation_id": GENERATION,
        "ruleset_sha256": config_sha,
        "writer_source_sha256": code_sha,
        "codes": sorted(selected),
        "turnover": turnover_receipt,
        "rows": rows,
        "status_counts": _status_counts(rows, "record_status"),
        "PASS_SIGNAL": "all three exact code/date records resolved with tri-state evidence and no future anchor",
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    out.write_text(json.dumps(pilot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pilot


def run_screen(
    output_dir: Path, *, panel_path: Path = SELECTOR_PATH,
    interface_path: Path = INTERFACE_PATH, receipt_path: Path = RECEIPT_PATH,
    ruleset_path: Path = RULESET_PATH, design_path: Path = DESIGN_PATH,
    field_path: Path = FIELD_PATH, turnover_manifest_path: Path = TURNOVER_MANIFEST,
    turnover_d28_path: Path = TURNOVER_D28, lifecycle_path: Path = LIFECYCLE_PATH,
    asof: str = ASOF, history_start: str = HISTORY_START,
) -> dict[str, Any]:
    if asof != ASOF:
        raise RuntimeError(f"frozen ruleset only permits {ASOF}")
    ruleset = json.loads(ruleset_path.read_text(encoding="utf-8"))
    if ruleset.get("ruleset_id") != RULESET_ID or ruleset.get("asof") != ASOF:
        raise RuntimeError("ruleset identity/asof mismatch")
    if ruleset.get("source", {}).get("generation") != GENERATION:
        raise RuntimeError("ruleset source generation mismatch")
    output_dir.mkdir(parents=True, exist_ok=True)
    projection, target, source_receipt = load_bound_projection(
        panel_path, interface_path, receipt_path, asof, history_start)
    turnover_history, turnover_receipt = load_turnover_history(
        set(target["ts_code"].astype(str)), history_start, turnover_manifest_path)
    projection = merge_turnover(projection, turnover_history, turnover_d28_path)
    target = projection.loc[projection["trade_date"] == asof].copy()
    exclusions, lifecycle_detail = lifecycle_exclusions(lifecycle_path, asof)
    ruleset_sha = sha256(ruleset_path)
    writer_sha = sha256(Path(__file__).resolve())
    selected = set(target["ts_code"].astype(str))
    rows = _evaluate_subset(projection, target, selected, asof=asof,
                            exclusions=exclusions, lifecycle_details=lifecycle_detail,
                            ruleset_sha256=ruleset_sha, writer_source_sha256=writer_sha)
    if len(rows) != 5538 or len({row["ts_code"] for row in rows}) != 5538:
        raise RuntimeError("all-row output fails D28 code/date conservation")
    if any(row["asof"] != ASOF for row in rows):
        raise RuntimeError("row-level asof changed")
    for row in rows:
        for branch in row["branches"].values():
            anchor = branch.get("event_anchor")
            if anchor and anchor.get("trade_date") and anchor["trade_date"] > ASOF:
                raise RuntimeError("future branch anchor in output")

    rows.sort(key=lambda row: row["ts_code"])
    candidates = [row for row in rows if row["raw_hit_group_ids"]]
    all_path = output_dir / "d28_all_5538_R2.jsonl"
    candidate_path = output_dir / "d28_candidate_union_R2.jsonl"
    _write_jsonl(all_path, rows)
    _write_jsonl(candidate_path, candidates)
    group_counts = {}
    group_files = {}
    for group_id in GROUP_IDS:
        subset = [row for row in candidates if group_id in row["raw_hit_group_ids"]]
        path = output_dir / f"{group_id}_D28.jsonl"
        _write_jsonl(path, subset)
        group_files[path.name] = {"path": str(path), "rows": len(subset), "sha256": sha256(path)}
        group_counts[group_id] = len(subset)

    counts = {
        "accepted_target_rows": len(rows),
        "quarantine_retained_separately": QUARANTINE,
        "candidate_union": len(candidates),
        "unique_candidate_codes": len({row["ts_code"] for row in candidates}),
        "group_memberships": group_counts,
        "record_status": _status_counts(rows, "record_status"),
        "target_bar_status": _status_counts(rows, "target_bar_status"),
        "pending_group_memberships": {
            group: sum(group in row["pending_group_ids"] for row in rows) for group in GROUP_IDS
        },
        "risk_group_memberships": {
            group: sum(group in row["risk_review_group_ids"] for row in rows) for group in GROUP_IDS
        },
        "confirmed_lifecycle_matches_in_pool": len(set(target["ts_code"]) & set(exclusions)),
    }
    artifacts = {
        all_path.name: {"path": str(all_path), "rows": len(rows), "sha256": sha256(all_path)},
        candidate_path.name: {"path": str(candidate_path), "rows": len(candidates), "sha256": sha256(candidate_path)},
        **group_files,
    }
    run_receipt = {
        "schema": "zge_skill_d28_screen_run/1",
        "ruleset_id": RULESET_ID,
        "status": "MATERIALIZED_RESEARCH_ONLY",
        "asof": ASOF,
        "market_scope": "A_SHARE_SH_SZ_BJ",
        "enabled_groups": list(GROUP_IDS),
        "disabled_groups": {
            "skill_r2_brick": "SEMANTICS_UNMAPPED",
            "skill_r2_needle": "GEOMETRY_UNMAPPED",
        },
        "fundamental_screen": False,
        "industry_filter": False,
        "topn_or_score": False,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "source": source_receipt,
        "ruleset": {
            "path": str(ruleset_path), "sha256": sha256(ruleset_path),
            "design_path": str(design_path), "design_sha256": sha256(design_path),
            "field_availability_path": str(field_path), "field_availability_sha256": sha256(field_path),
        },
        "writer_source": {
            "path": str(Path(__file__).resolve()),
            "sha256": writer_sha,
        },
        "turnover": turnover_receipt,
        "lifecycle": {
            "path": str(lifecycle_path), "sha256": sha256(lifecycle_path),
            "scope": "CURRENT_HANDLED_ISSUE_LIST_ONLY_NOT_MARKET_WIDE_DAILY_SUSPENSION_ROSTER",
            "matched_codes": sorted(set(target["ts_code"]) & set(exclusions)),
        },
        "counts": counts,
        "semantics": {
            "numeric_hit_is_not_full_skill_certification": True,
            "unknown_does_not_become_zero_or_false": True,
            "candidate_union_retains_risk_and_pending_hits": True,
            "chart_review_eligible_includes_clean_and_pending_groups": True,
            "risk_hit_preserves_raw_hit": True,
            "new_rule_historical_success_rate": "CANNOT_CONFIRM; no same-definition D2/D5 history; no rebacktest",
            "legacy_groups_changed": False,
            "J_K_enabled": False,
        },
        "run_parameters": {
            "history_start": history_start,
            "one_full_bound_projection": True,
            "dates_after_asof_read": False,
            "key_conservation": "PASS",
            "quarantine_is_not_a_miss": True,
        },
        "artifacts": artifacts,
    }
    receipt_out = output_dir / "D28_RUN_RECEIPT_R2.json"
    receipt_out.write_text(json.dumps(run_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    return run_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asof", default=ASOF)
    parser.add_argument("--history-start", default=HISTORY_START)
    parser.add_argument("--pilot", action="store_true", help="run the 3-code preflight only")
    parser.add_argument("--codes", default="000001.SZ,920510.BJ,002717.SZ",
                        help="comma-separated pilot codes")
    parser.add_argument("--repair-h-from", type=Path,
                        help="repair only H and signal evidence from a bound predecessor receipt")
    args = parser.parse_args()
    if args.repair_h_from:
        result = run_h_repair(args.output_dir, args.repair_h_from,
                              codes=set(args.codes.split(",")) if args.pilot else None)
        print(json.dumps({"info": result.get("info", result.get("h_repair")),
                          "counts": result.get("counts")}, ensure_ascii=False, indent=2))
    elif args.pilot:
        result = run_pilot(args.output_dir, args.codes.split(","),
                           asof=args.asof, history_start=args.history_start)
        print(json.dumps({"status_counts": result["status_counts"],
                          "codes": result["codes"]}, ensure_ascii=False, indent=2))
        print(f"pilot={args.output_dir / 'pilot_3_records.json'}")
    else:
        result = run_screen(args.output_dir, asof=args.asof, history_start=args.history_start)
        print(json.dumps(result["counts"], ensure_ascii=False, indent=2, sort_keys=True))
        print(f"receipt={args.output_dir / 'D28_RUN_RECEIPT_R2.json'}")


if __name__ == "__main__":
    main()


