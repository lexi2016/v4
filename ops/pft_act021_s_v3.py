"""ACT-021 S_V3.0: D-only review infrastructure, FIT=0, backtest=0.

Consumes controller-verified original ranks and the existing authoritative V4
logical Reader. No panel is produced. Outputs are research diagnostics, causal
events and a public blind challenge; ACT-022 owns any future calibration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any
import zipfile

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_act020_s_v2 as previous
from ops import pft_s_v12_full_a as v12

SCHEMA = "pft_act021_s_v3.v1"
TACTIC_VERSION = "ACT020_FROZEN_PROXY_PLUS_ACT021_OBSERVABLE_EVENTS_V1"
FEATURE_VERSION = "ACT020_21_CAUSAL_PRIMITIVES_V1"
MODEL_VERSION = "ACT020_FROZEN_RETROSPECTIVE_DIAGNOSTIC_ONLY"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
BATCH_FIELDS = ("market", "source_date", "observation_date", "decision_date", "top200_revision", "panel_generation", "schema_version", "tactic_rule_version", "feature_version", "model_version")
NUMERIC = ("open", "high", "low", "close", "vol", "zge_white_line", "zge_yellow_line", "bbi")
A_MARKETS = {"A", "A_SHARE", "ASHARE", "CN_A", "A-SHARE", "SH", "SZ", "BJ"}
REFUSAL_CODES = {"DATA_UNAVAILABLE", "EVIDENCE_CONFLICT", "EARLY_REPAIR", "ANCHOR_AMBIGUOUS", "MODEL_DISAGREE", "OUT_OF_DOMAIN", "GREY_PROB_BAND"}
DEDUCTIONS = {"WEAK_KEY_K": 12, "STICKY_WY": 10, "UNCONTRACTED_BASE": 8, "CLOSE_BELOW_WHITE": 12,
              "CLOSE_BELOW_ANCHOR": 25, "DEEP_DD30": 15, "UPPER_WICK_TRAP": 15, "STALE_ANCHOR": 10, "WEAK_VOL_EXPANSION": 10}
COUNTER_ZH = {"WEAK_KEY_K": "关键K实体、量能或推进证据不足", "STICKY_WY": "白黄线粘连且趋势弱", "UNCONTRACTED_BASE": "近段量幅未同时收缩",
              "CLOSE_BELOW_WHITE": "当前收盘低于当日收盘白线", "CLOSE_BELOW_ANCHOR": "观察窗内锚点曾被收盘跌破",
              "DEEP_DD30": "距近30根高点回撤较深", "UPPER_WICK_TRAP": "放量上影或冲高回落", "STALE_ANCHOR": "锚点已超过40根观察",
              "WEAK_VOL_EXPANSION": "前序放量多为收盘较前收下跌"}


class ContractError(RuntimeError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return v12._sha_file(Path(path))


def day(value: Any) -> str:
    return v12._day(value, "ACT021_day")


def clean(value: Any) -> Any:
    """JSON null retains missing numeric evidence; no NaN or false zero."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item"):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    previous.write_json(path, clean(value))


def checked_file(path: Any, expected: str) -> Path:
    result = Path(str(path))
    if not result.is_absolute() or result.is_symlink() or ".." in result.parts or not result.is_file():
        raise ContractError(f"UNSAFE_OR_MISSING_SOURCE:{result}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected)) or file_sha(result) != expected:
        raise ContractError(f"SOURCE_SHA_MISMATCH:{result}")
    return result


def load_groups(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = path.stat()
    raw = path.read_bytes()
    payload = json.loads(raw)
    if path.stat() != before or not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
        raise ContractError("RANK_PACKAGE_CHANGED_OR_INVALID")
    groups, keys = [], set()
    for original in payload["groups"]:
        g = dict(original)
        for name in ("source_date", "observation_date", "decision_date"):
            g[name] = day(g[name])
        if g["decision_date"] != g["source_date"] or g["observation_date"] < g["source_date"]:
            raise ContractError("RANK_DATE_BINDING")
        key = (g["source_date"], g["observation_date"])
        if key in keys:
            raise ContractError("DUPLICATE_RANK_GROUP")
        keys.add(key)
        if g.get("status") == "CANNOT_CONFIRM" and not g.get("rows"):
            if not g.get("reason"):
                raise ContractError("MISSING_GROUP_REQUIRES_REASON")
            groups.append(g)
            continue
        for name in ("top200_revision", "source_generation", "source_ref", "price_basis"):
            if not g.get(name):
                raise ContractError(f"RANK_BINDING_MISSING:{name}")
        rank_sha = g.get("ranking_sha256", g.get("ranking_sha"))
        if not re.fullmatch(r"[0-9a-f]{64}", str(rank_sha)):
            raise ContractError("RANK_SHA_REQUIRED")
        g["ranking_sha256"] = rank_sha
        rows = g.get("rows")
        if not isinstance(rows, list) or len(rows) != 200:
            raise ContractError("ORIGINAL_RANK_MUST_RETAIN_200")
        normalized = []
        for r in rows:
            rank = r.get("source_rank")
            if isinstance(rank, bool) or not isinstance(rank, int):
                raise ContractError("ORIGINAL_RANK_INTEGER_REQUIRED")
            normalized.append({"source_rank": rank, "ts_code": v12._code(r["ts_code"])})
        if {r["source_rank"] for r in normalized} != set(range(1, 201)) or len({r["ts_code"] for r in normalized}) != 200:
            raise ContractError("ORIGINAL_RANK_DUPLICATE_OR_GAP")
        g["rows"] = sorted(normalized, key=lambda r: r["source_rank"])
        for manifest in g.get("source_manifests", []):
            checked_file(manifest["path"], manifest["sha256"])
        groups.append(g)
    if not groups:
        raise ContractError("NO_RANK_GROUPS")
    return groups, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "group_count": len(groups)}


def bind_panel(g: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    """Per-group existing producer contract; no current/latest date substitution."""
    if not g.get("panel_path"):
        return None, {"status": "CANNOT_CONFIRM", "reason": g.get("panel_missing_reason", "EXACT_GENERATION_PANEL_UNAVAILABLE")}
    from ops.pft_s_first_baseline import _contract_identity
    from ops.research_panel_qfq import panel_contract
    panel = checked_file(g["panel_path"], g["panel_sha256"])
    contract = panel_contract(panel)
    identity, source = _contract_identity(g.get("panel_role", "backtest"), panel, contract)
    a_basis = identity.get("a_market_basis") or identity
    generation = g.get("panel_generation", g["source_generation"])
    if identity["generation_id"] != generation or source["asof_date"] != g["decision_date"]:
        raise ContractError("EXACT_PANEL_GENERATION_OR_DATE_MISMATCH")
    if a_basis.get("price_basis") != g["price_basis"]:
        raise ContractError("PANEL_PRICE_BASIS_MISMATCH")
    return panel, {"status": "BOUND", "identity": identity, "source": source,
                   "panel_generation": generation, "volume_basis": a_basis.get("volume_basis"),
                   "strict_le_d_scope": "observed daily bars only; generation/PIT authority remains controller-bound, not inferred"}


def read_group(panel: Path, g: dict[str, Any]) -> Any:
    """Single bounded logical read per group, requested symbols/columns only."""
    import pandas as pd
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel)
    actual = {n.lower(): n for n in schema.names}
    mapping = {}
    for semantic in (*previous.INPUTS, "bbi"):
        candidates = v12.ALIASES.get(semantic, (semantic,))
        found = next((actual[n] for n in candidates if n in actual), None)
        if found:
            mapping[semantic] = found
        elif semantic != "bbi":
            raise ContractError(f"PANEL_INPUT_COLUMN_MISSING:{semantic}")
    start = (datetime.strptime(g["decision_date"], "%Y%m%d")-timedelta(days=400)).strftime("%Y%m%d")
    filters = [(mapping["ts_code"], "in", [r["ts_code"] for r in g["rows"]]),
               (mapping["trade_date"], ">=", v12._arrow_date_value(schema, mapping["trade_date"], start)),
               (mapping["trade_date"], "<=", v12._arrow_date_value(schema, mapping["trade_date"], g["decision_date"]))]
    frame = parquet.read_table(panel, columns=list(mapping.values()), filters=filters).to_pandas().rename(columns={v:k for k,v in mapping.items()})
    if "bbi" not in frame:
        frame["bbi"] = float("nan")
    frame["trade_date"] = v12._normalize_observed_column(frame.trade_date, day, "trade_date")
    frame["ts_code"] = v12._normalize_observed_column(frame.ts_code, v12._code, "ts_code")
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise ContractError("DUPLICATE_PANEL_KEY")
    if not frame.market_type.astype(str).str.upper().isin(A_MARKETS).all():
        raise ContractError("A_HK_MARKET_BOUNDARY")
    if len(frame) and (frame.trade_date.max() > g["decision_date"] or not set(frame.ts_code) <= {r["ts_code"] for r in g["rows"]}):
        raise ContractError("READER_SCOPE_VIOLATION")
    for c in NUMERIC:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    return frame.sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)


def valid_bar(row: dict[str, Any], *, bbi: bool = False) -> bool:
    names = NUMERIC if bbi else NUMERIC[:-1]
    try:
        if not all(math.isfinite(float(row[n])) and float(row[n]) > 0 for n in names):
            return False
        return row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]
    except (KeyError, TypeError, ValueError):
        return False


def anchor_history(frame: Any) -> dict[str, Any]:
    """Causal root/management/repair event ledger in the bounded observed history.

    Every active event keeps its own minima and historical close failure. A
    later management/repair K cannot erase any preceding event's failure.
    The first observed root is explicitly left-censored to the Reader window.
    """
    rows = frame.to_dict("records")
    events: list[dict[str, Any]] = []
    damage = None
    previous_row = None
    prior_expansions = []
    for i, r in enumerate(rows):
        good = valid_bar(r)
        if not good:
            previous_row = None
            continue
        # Update existing anchors before recording a possible new D anchor.
        for e in events:
            e["min_low_since_anchor"] = min(e["min_low_since_anchor"], r["low"])
            e["min_close_since_anchor"] = min(e["min_close_since_anchor"], r["close"])
            if r["low"] < e["low"]:
                e["low_pierce_observation_dates"].append(r["trade_date"])
                if r["close"] >= e["low"]:
                    e["same_day_low_pierce_reclaim_dates"].append(r["trade_date"])
            if r["close"] < e["low"]:
                e["close_break_observation_dates"].append(r["trade_date"])
        if previous_row and r["close"] < r["zge_yellow_line"] and previous_row["close"] < previous_row["zge_yellow_line"]:
            damage = r["trade_date"]
        prior5 = rows[max(0, i-5):i]
        baseline = sum(float(x["vol"]) for x in prior5)/5 if len(prior5) == 5 and all(valid_bar(x) for x in prior5) else None
        prev = previous_row["close"] if previous_row else None
        body = (r["close"]-r["open"])/prev if prev else None
        advance = r["close"]/prev-1 if prev else None
        expansion = r["vol"]/baseline if baseline else None
        wick = (r["high"]-max(r["open"], r["close"]))/prev if prev else None
        impulse = prev and advance >= .035 and expansion is not None and expansion >= 1.2 and body >= .02 and wick <= .025
        repair = (damage is not None and previous_row is not None and r["close"] > max(r["zge_white_line"], r["zge_yellow_line"])
                  and body is not None and body >= .01 and expansion is not None and expansion >= 1.1 and r["close"] > previous_row["high"])
        if impulse or repair:
            role = "repair" if repair else ("root" if not any(e["role"] == "root" for e in events) else "management")
            event_id = digest([r["ts_code"], r["trade_date"], role])[:24]
            dimensions = {"body": {"observed": body, "denominator": "previous_valid_observed_close", "reference": .02},
                          "expansion": {"observed": expansion, "denominator": "mean_of_exact_five_prior_valid_bars", "reference": 1.2},
                          "advance": {"observed": advance, "denominator": "previous_valid_observed_close", "reference": .035}}
            score = sum(min(max(dimensions[k]["observed"]/dimensions[k]["reference"], 0), 1) for k in dimensions)/3*100
            events.append({"anchor_id": event_id, "date": r["trade_date"], "bar_index": i, "role": role,
                           "parent_anchor_id": events[-1]["anchor_id"] if events else None,
                           "low": r["low"], "mid": (r["open"]+r["close"])/2,
                           "quality_score": score, "quality_dimensions": dimensions,
                           "min_low_since_anchor": r["low"], "min_close_since_anchor": r["close"],
                           "low_pierce_observation_dates": [], "same_day_low_pierce_reclaim_dates": [], "close_break_observation_dates": [],
                           "damage_observation_date": damage if repair else None})
            if repair:
                damage = None
        if expansion is not None and expansion >= 1.2 and prev:
            prior_expansions.append({"observation_date": r["trade_date"], "bar_index": i,
                                     "close_vs_previous_close": advance, "candle_body_vs_previous_close": body,
                                     "close_direction": "UP" if advance > 0 else ("DOWN" if advance < 0 else "FLAT"),
                                     "candle_direction": "BULL" if body > 0 else ("BEAR" if body < 0 else "DOJI"),
                                     "relative_volume_prior5": expansion})
        previous_row = r
    if not rows:
        return {"events": [], "root": None, "active": None, "prior_expansion_price_volume": [], "window_left_censored": True}
    last = rows[-1]
    for e in events:
        e["low_pierced_recovered_flag"] = bool(e["same_day_low_pierce_reclaim_dates"])
        e["same_day_low_pierce_reclaim_current"] = bool(last["trade_date"] in e["same_day_low_pierce_reclaim_dates"])
        e["multi_day_close_recovery_current"] = bool(e["close_break_observation_dates"] and valid_bar(last) and last["close"] >= e["low"])
        e["close_broken_flag"] = bool(e["close_break_observation_dates"])
        e["current_close_below_anchor"] = bool(last["close"] < e["low"]) if valid_bar(last) else None
    return {"events": events, "root": next((e for e in events if e["role"] == "root"), None), "active": events[-1] if events else None,
            "prior_expansion_price_volume": [e for e in prior_expansions if 0 < len(rows)-1-e["bar_index"] <= 20],
            "window_left_censored": True,
            "window_start": rows[0]["trade_date"], "window_end": last["trade_date"],
            "old_close_failure_survives_new_anchor": any(e["close_broken_flag"] for e in events[:-1]),
            "line_cross_scope": "daily close compared with same-day observed end-of-day line; intraday timestamps UNKNOWN"}


def load_models(directory: Path | None, contract_path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only locally trusted, SHA-pinned ACT020 weights; never fit/recalibrate."""
    if directory is None and contract_path is None:
        return {}, {"status": "NOT_REQUESTED", "reference_exposed_security_dates": []}
    if directory is None or contract_path is None:
        raise ContractError("MODEL_DIRECTORY_AND_CONTRACT_REQUIRED_TOGETHER")
    contract = json.loads(contract_path.read_text())
    if contract.get("scope") != "RETROSPECTIVE_FROZEN_DIAGNOSTIC_ONLY" or contract.get("training_panel_generation") != previous.GENERATION:
        raise ContractError("MODEL_SCOPE_OR_TRAINING_GENERATION")
    if contract.get("features") not in (previous.FEATURE_UNITS, list(previous.FEATURES)):
        raise ContractError("MODEL_FEATURE_CONTRACT")
    ledger_path = checked_file(directory/"fit_ledger.json", contract["fit_ledger_sha256"])
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("S") != 4 or ledger.get("B") != 0 or ledger.get("tuning") != 0:
        raise ContractError("ACT020_FROZEN_FIT_LEDGER")
    models = {}
    for name in previous.MODEL_NAMES:
        weight = checked_file(directory/f"{name}.joblib", contract["weights_sha256"][name])
        receipt = ledger.get("models", {}).get(name, {})
        if receipt.get("state") != "COMPLETE" or receipt.get("weight_sha256") != file_sha(weight):
            raise ContractError("MODEL_WEIGHT_LEDGER_MISMATCH")
        models[name] = previous.load_weight(weight)
        expected = [0, 1] if name.startswith("binary") else [0, 1, 2, 3]
        if list(models[name].classes_) != expected:
            raise ContractError("MODEL_CLASS_ORDER")
    return models, {**contract, "status": "LOADED_TRUSTED_LOCAL", "contract_sha256": file_sha(contract_path),
                    "inference_scope": "retrospective frozen-model proxy, including dates before weight publication; not prospective or out-of-sample evaluation"}


def compatible(g: dict[str, Any], binding: dict[str, Any], contract: dict[str, Any]) -> bool:
    return (binding.get("status") == "BOUND" and binding.get("panel_generation") in contract.get("allowed_panel_generations", [])
            and g.get("price_basis") == contract.get("price_basis")
            and binding.get("volume_basis") == contract.get("volume_basis")
            and bool(g.get("series_formula_sha256")) and g.get("series_formula_sha256") == contract.get("series_formula_sha256"))


def frozen_inference(shape: dict[str, Any] | None, models: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    if not shape or not shape.get("feature_ready") or not models:
        return {}
    x = np.array([[shape[k] for k in previous.FEATURES]], dtype=float)
    if not np.isfinite(x).all():
        return {}
    result = {}
    for name, model in models.items():
        p = np.asarray(model.predict_proba(x), dtype=float)[0]
        if not np.isfinite(p).all() or (p < 0).any() or (p > 1).any() or not np.isclose(p.sum(), 1):
            raise ContractError("INVALID_FROZEN_PROBABILITY")
        if name.startswith("binary"):
            result[name] = {"raw_positive_probability": float(p[1])}
        else:
            result[name] = {"raw_tactic_probabilities": dict(zip(previous.CLASSES, map(float, p))),
                            "argmax_tactic": previous.CLASSES[int(p.argmax())]}
    return result


def contraction(frame: Any, field: str, *, recent: bool) -> dict[str, Any]:
    rows = frame.to_dict("records")
    # recent: D-4..D / D-19..D-5; prior: D-5..D-1 / D-20..D-6.
    offset = 0 if recent else 1
    end = len(rows)-offset
    numerator, denominator = rows[end-5:end], rows[end-20:end-5]
    names = {"vol": "volume", "amplitude": "(high-low)/close"}
    def mean(part: list[dict[str, Any]]) -> float | None:
        if not part or not all(valid_bar(r) for r in part):
            return None
        return sum(r["vol"] if field == "vol" else (r["high"]-r["low"])/r["close"] for r in part)/len(part)
    a = mean(numerator) if len(numerator) == 5 else None
    b = mean(denominator) if len(denominator) == 15 else None
    return {"ratio": a/b if a is not None and b is not None and b > 0 else None,
            "quantity": names[field], "numerator_mean": a, "denominator_mean": b,
            "numerator_dates": [r["trade_date"] for r in numerator], "denominator_dates": [r["trade_date"] for r in denominator],
            "window": "D-4..D / D-19..D-5" if recent else "D-5..D-1 / D-20..D-6"}


def evidence(code: str, observed: Any, rule: str, severity: str, dates: list[str]) -> dict[str, Any]:
    return {"code": code, "observed": clean(observed), "rule": rule, "severity": severity,
            "observation_date": dates[-1] if dates else None, "window": dates}



def observable_stage(frame: Any, shape: dict[str, Any] | None, history: dict[str, Any], ready: bool) -> tuple[str, dict[str, Any]]:
    """State and one-bar triggers are independent of tactic proxy classification."""
    if not ready:
        return "UNKNOWN", {name:None for name in ("VOL_BREAKOUT","RECLAIM_WHITE","RECLAIM_YELLOW","ANCHOR_LOW_PIERCE_RECOVER_CURRENT","CLOSE_BELOW_WHITE_CURRENT")}
    rows = frame.to_dict("records")
    current = rows[-1]
    prior = rows[-2] if len(rows) > 1 else None
    active = history["active"]
    flags = {"VOL_BREAKOUT": bool(shape["volume_ratio"] >= 1.2 and shape["resistance_distance"] > 0),
             "RECLAIM_WHITE": bool(prior and prior["close"] <= prior["zge_white_line"] and current["close"] > current["zge_white_line"]),
             "RECLAIM_YELLOW": bool(prior and prior["close"] <= prior["zge_yellow_line"] and current["close"] > current["zge_yellow_line"]),
             "ANCHOR_LOW_PIERCE_RECOVER_CURRENT": bool(active and current["low"] < active["low"] <= current["close"]),
             "CLOSE_BELOW_WHITE_CURRENT": bool(current["close"] < current["zge_white_line"])}
    # Uses causal damage/repair ages and observed anchor facts, never tactic.
    if shape.get("repair_age", -1) >= 0 and shape["repair_age"] < 2:
        stage = "EARLY_REPAIR"
    elif shape.get("active_damage"):
        stage = "DAMAGED"
    elif active and active["current_close_below_anchor"]:
        stage = "BELOW_ACTIVE_ANCHOR"
    elif shape.get("repair_age", -1) >= 2 and not shape.get("repair_failed"):
        stage = "POST_REPAIR"
    elif not active:
        stage = "UNANCHORED"
    elif shape["volume_compression"] < .9 and shape["range_compression"] < .9:
        stage = "CONSOLIDATION"
    else:
        stage = "ACTIVE_WAVE"
    return stage, flags

def review_row(g: dict[str, Any], rank: dict[str, Any], frame: Any,
               shape: dict[str, Any] | None, binding: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    rows = frame.to_dict("records")
    d = g["decision_date"]
    exact = bool(rows and rows[-1]["trade_date"] == d)
    history = anchor_history(frame)
    root, active = history["root"], history["active"]
    ready = bool(exact and shape and shape.get("feature_ready"))
    current = rows[-1] if exact else {}
    rule_tactic = shape.get("tactic", "UNKNOWN") if ready else "UNKNOWN"
    dates = [r["trade_date"] for r in rows]
    positive = []
    if ready:
        for item in str(shape.get("positive_evidence", "")).split("|"):
            if item:
                positive.append(evidence(item, True, "ACT020 frozen high-purity D-only mining proxy", "SUPPORT", dates[-21:]))
    codes = []
    if ready:
        if active and active["quality_score"] < 80:
            codes.append("WEAK_KEY_K")
        if abs(shape["line_spread"]) < .003 and abs(shape["white_slope"]) < .0003 and abs(shape["yellow_slope"]) < .0003:
            codes.append("STICKY_WY")
        if shape["volume_compression"] >= .9 or shape["range_compression"] >= .9:
            codes.append("UNCONTRACTED_BASE")
        if current["close"] < current["zge_white_line"]:
            codes.append("CLOSE_BELOW_WHITE")
        if any(e["close_broken_flag"] for e in history["events"]):
            codes.append("CLOSE_BELOW_ANCHOR")
        if shape["trailing_peak_distance"] < -.20:
            codes.append("DEEP_DD30")
        if shape["volume_ratio"] >= 2 and shape["wick_frac"] >= .025:
            codes.append("UPPER_WICK_TRAP")
        if active and len(rows)-1-active["bar_index"] > 40:
            codes.append("STALE_ANCHOR")
        if shape.get("prior_expansion_count", 0) >= 4 and shape.get("prior_expansion_nonbull", 0) >= 3:
            codes.append("WEAK_VOL_EXPANSION")
    counter_rules = {
        "WEAK_KEY_K": (active["quality_score"] if active else None, "anchor quality <80; mean capped(body/.02, expansion/1.2, advance/.035)*100"),
        "STICKY_WY": ({k:shape.get(k) for k in ("line_spread", "white_slope", "yellow_slope")} if shape else None, "abs(spread)<.003 and abs(each 5-bar slope)<.0003"),
        "UNCONTRACTED_BASE": ({k:shape.get(k) for k in ("volume_compression", "range_compression")} if shape else None, "recent5/prior15 volume>=.9 OR amplitude>=.9"),
        "CLOSE_BELOW_WHITE": (current.get("close"), "D close < observed D end-of-day white; no intraday crossing time"),
        "CLOSE_BELOW_ANCHOR": ([e["anchor_id"] for e in history["events"] if e["close_broken_flag"]], "any observed since-anchor close < that anchor's fixed low; historical, not necessarily current"),
        "DEEP_DD30": (shape.get("trailing_peak_distance") if shape else None, "D close / trailing30 high -1 < -.20"),
        "UPPER_WICK_TRAP": ({k:shape.get(k) for k in ("volume_ratio", "wick_frac")} if shape else None, "D volume/prior5>=2 AND upper wick/previous close>=.025"),
        "STALE_ANCHOR": (len(rows)-1-active["bar_index"] if active else None, "active anchor age >40 observed bars"),
        "WEAK_VOL_EXPANSION": (history["prior_expansion_price_volume"], "ACT020 last four prior expansions within20 contain >=3 close<previous close; candle body separate")}
    contra = [evidence(c, counter_rules[c][0], counter_rules[c][1], "HIGH" if DEDUCTIONS[c] >= 15 else "MEDIUM", dates if c == "CLOSE_BELOW_ANCHOR" else dates[-30:]) for c in codes]
    # Preserve ACT020 conflict evidence even if no ACT021 nine-code mapping exists.
    for item in str(shape.get("counterevidence", "") if shape else "").split("|"):
        if item:
            contra.append(evidence("ACT020_"+item, True, "ACT020 frozen D-only counterevidence", "HIGH", dates[-21:]))
    reasons = []
    if not ready:
        reasons.append("DATA_UNAVAILABLE")
    if ready and rule_tactic == "UNKNOWN" and positive and contra:
        reasons.append("EVIDENCE_CONFLICT")
    if ready and shape.get("repair_age", -1) >= 0 and shape["repair_age"] < 2:
        reasons.append("EARLY_REPAIR")
    if ready and active is None:
        reasons.append("ANCHOR_AMBIGUOUS")
    p = model.get("tactic_hgb", {}).get("raw_tactic_probabilities", {})
    p_binary = model.get("binary_hgb", {}).get("raw_positive_probability")
    model_tactic = model.get("tactic_hgb", {}).get("argmax_tactic")
    conflict = bool(p and rule_tactic in previous.CLASSES and model_tactic != rule_tactic)
    if conflict:
        reasons.append("MODEL_DISAGREE")
    if p_binary is not None and .2 < p_binary < .8:
        reasons.append("GREY_PROB_BAND")
    child = {c: p[c] for c in previous.CLASSES[:3]} if p else {}
    projected = max([p_binary, *child.values()]) if p_binary is not None and child else None
    probabilities = sorted(p.values(), reverse=True)
    margin = probabilities[0]-probabilities[1] if probabilities else None
    deduction = sum(DEDUCTIONS[c] for c in codes) if ready else None
    fixed_score = max(0., (85. if rule_tactic in previous.CLASSES[:3] else 20. if rule_tactic == "invalid_fake" else 50.)-(deduction or 0)) if ready else None
    state = "UNKNOWN_BORDERLINE"
    if ready and not reasons and rule_tactic in previous.CLASSES[:3]:
        state = "CONFIRMED_S"
    elif ready and not reasons and rule_tactic == "invalid_fake":
        state = "REJECTED_FAKE"
    sorted_tactics = sorted(p, key=lambda c:(-p[c], c)) if p else []
    stage, observable_triggers = observable_stage(frame, shape, history, ready)
    rv, ra = contraction(frame, "vol", recent=True), contraction(frame, "amplitude", recent=True)
    batch = {"market": "A", **{k:g[k] for k in ("source_date", "observation_date", "decision_date", "top200_revision")},
             "panel_generation": binding.get("panel_generation", g.get("panel_generation", g.get("source_generation"))),
             "schema_version": SCHEMA, "tactic_rule_version": TACTIC_VERSION, "feature_version": FEATURE_VERSION, "model_version": MODEL_VERSION}
    batch_id = digest(batch)
    classification_id = digest([batch_id, rank["source_rank"], rank["ts_code"]])
    result = {**batch, **rank, "universe_tag": "TOP200", "ranking_sha256": g["ranking_sha256"],
              "price_basis": g["price_basis"], "strict_le_d_verified": bool(exact and dates and max(dates) <= d),
              "evidence_ref": {"source_ref": g["source_ref"], "source_generation": g["source_generation"], "panel_sha256": g.get("panel_sha256"), "source_manifests": g.get("source_manifests", [])},
              "batch_id": batch_id, "s_decision_state": state,
              "purity_tier": "PSEUDO_WEAK" if rule_tactic == "invalid_fake" else ("TYPICAL_PERFECT" if state == "CONFIRMED_S" and not codes else "WATCHABLE"),
              "s_overall_prob": projected, "s_overall_score_100": fixed_score,
              "score_kind": "FIXED_RULE_DIAGNOSTIC_NOT_CALIBRATED", "score_status": "D_ONLY_RULE_PROXY" if ready else "CANNOT_CONFIRM",
              "probability_status": "RETROSPECTIVE_RAW_PROXY_UPWARD_HIERARCHY_PROJECTION_NOT_CALIBRATED" if projected is not None else "NOT_SCORED",
              "conformal_set_size": None, "uncertainty_score": 1-max(p.values()) if p else None,
              "refusal_flag": bool(reasons), "refusal_reasons": list(dict.fromkeys(reasons)),
              "primary_tactic": rule_tactic, "secondary_tactic": next((c for c in sorted_tactics if c != rule_tactic), None),
              "tactic_probs_json": p or None, "tactic_score_margin": margin,
              "stage_code": stage, "trigger_flags": observable_triggers,
              "wave_index": len(history["events"]) if history["events"] else None,
              "episode_id": digest([rank["ts_code"], root["date"]])[:24] if root else None,
              "root_anchor_id": root["anchor_id"] if root else None, "root_anchor_date": root["date"] if root else None, "root_anchor_low": root["low"] if root else None,
              "active_anchor_id": active["anchor_id"] if active else None, "active_anchor_date": active["date"] if active else None, "active_anchor_role": active["role"] if active else None,
              "active_anchor_low": active["low"] if active else None, "active_anchor_mid": active["mid"] if active else None, "parent_anchor_id": active["parent_anchor_id"] if active else None,
              "min_low_since_anchor": active["min_low_since_anchor"] if active else None, "min_close_since_anchor": active["min_close_since_anchor"] if active else None,
              "anchor_low_pierced_recovered_flag": active["low_pierced_recovered_flag"] if active else None,
              "anchor_low_pierced_recovered_scope":"since-anchor observed same-day low<fixed anchor low<=close; current and multi-day recovery separate in trace", "anchor_close_broken_flag": active["close_broken_flag"] if active else None,
              "anchor_quality_score": active["quality_score"] if active else None, "anchor_quality_dimensions": active["quality_dimensions"] if active else None,
              "support_white_line": current.get("zge_white_line"), "support_yellow_line": current.get("zge_yellow_line"), "invalidation_price": active["low"] if active else None,
              "rel_vol_contraction": rv["ratio"], "rel_amp_contraction": ra["ratio"],
              "contraction_denominators": {"recent_volume": rv, "recent_amplitude": ra, "prior_volume": contraction(frame,"vol",recent=False), "prior_amplitude": contraction(frame,"amplitude",recent=False)},
              "positive_evidence": positive, "contra_evidence": contra, "ce_deduction_pts": deduction, "ce_flag_codes": codes,
              "top_counter_evidence_zh": COUNTER_ZH[max(codes, key=DEDUCTIONS.get)] if codes else None,
              "human_review_priority": "HIGH" if reasons or codes else "NORMAL",
              "classification_id": classification_id, "classification_revision": 1, "reviewer_status": "DRAFT_NOT_HUMAN_REVIEWED",
              "reviewed_asof_d": None, "prior_revision_ref": None,
              "anchor_event_trace": history, "frozen_model_diagnostic": model,
              "model_rule_conflict": conflict, "model_argmax_tactic": model_tactic,
              "context_status": "READY" if ready else ("EXACT_D_MISSING" if not exact else "MISSING_OR_INVALID_CAUSAL_CONTEXT"),
              "context_observed_bars": len(rows), "strict_le_d_scope": "observed bar dates only; no claim of intraday or model publication PIT",
              "decision_scope": "fixed research mining proxy draft, not adjudicated human label; no calibrated confidence", **FLAGS}
    return clean(result)


def infer_batch(shapes: Any, models: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """One prediction call/model/group, never per-security fit or inference loops."""
    import numpy as np
    if not models or not len(shapes):
        return {}
    part = shapes.loc[shapes.feature_ready]
    if not len(part):
        return {}
    x = part.loc[:, list(previous.FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(x).all():
        raise ContractError("NONFINITE_FROZEN_INPUT")
    results = [{} for _ in range(len(part))]
    for name, model in models.items():
        probabilities = np.asarray(model.predict_proba(x), dtype=float)
        if (not np.isfinite(probabilities).all() or (probabilities < 0).any() or (probabilities > 1).any()
                or not np.allclose(probabilities.sum(axis=1), 1)):
            raise ContractError("INVALID_FROZEN_PROBABILITY")
        for result, p in zip(results, probabilities):
            result[name] = ({"raw_positive_probability": float(p[1])} if name.startswith("binary") else
                            {"raw_tactic_probabilities": dict(zip(previous.CLASSES, map(float, p))), "argmax_tactic": previous.CLASSES[int(p.argmax())]})
    return dict(zip(zip(part.ts_code, part.trade_date), results))


def blind_eligible(frame: Any, d: str) -> bool:
    rows = frame.tail(60).to_dict("records")
    return bool(len(rows) == 60 and rows[-1]["trade_date"] == d and all(valid_bar(r, bbi=True) for r in rows))


def select_blind(candidates: list[dict[str, Any]], *, seed: str = "ACT021_FROZEN_SELECTION_20261123") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Truthful disjoint quotas. Missing strata remain missing, never relabelled.

    Precommitted order prioritizes scarce actual conflicts and cross classes,
    then unknowns, then two samples in each rank quartile. One security maximum
    across the entire challenge, stronger than same-security/episode exclusion.
    """
    order = lambda c: digest([seed, c["review"]["classification_id"]])
    available = sorted(candidates, key=order)
    selected, used = [], set()
    counts = {}
    def take(bucket: str, pool: list[dict[str, Any]], n: int) -> None:
        count = 0
        if n <= 0:
            return
        for c in pool:
            code = c["review"]["ts_code"]
            if code in used:
                continue
            selected.append({**c, "private_bucket": bucket})
            used.add(code)
            count += 1
            if count == n:
                break
        counts[bucket] = counts.get(bucket, 0)+count
    take("ACTUAL_MODEL_RULE_CONFLICT", [c for c in available if c["review"]["model_rule_conflict"]], 8)
    # Prefer two/class, then fill only inside the same confident cross-class
    # stratum. At least one actual positive and negative proxy must exist.
    cross_pool = [c for c in available if c["review"]["primary_tactic"] in previous.CLASSES
                  and c["review"]["model_argmax_tactic"] == c["review"]["primary_tactic"]
                  and (c["review"]["tactic_probs_json"] or {}).get(c["review"]["primary_tactic"], 0) >= .70]
    has_positive = any(c["review"]["primary_tactic"] in previous.CLASSES[:3] for c in cross_pool)
    has_negative = any(c["review"]["primary_tactic"] == "invalid_fake" for c in cross_pool)
    if has_positive and has_negative:
        for tactic in previous.CLASSES:
            take("CROSS_CLASS_"+tactic.upper(), [c for c in cross_pool if c["review"]["primary_tactic"] == tactic], 2)
        while sum(v for k,v in counts.items() if k.startswith("CROSS_CLASS_")) < 8:
            remaining = [c for c in cross_pool if c["review"]["ts_code"] not in used]
            if not remaining:
                break
            remaining.sort(key=lambda c:(counts.get("CROSS_CLASS_"+c["review"]["primary_tactic"].upper(),0),order(c)))
            c = remaining[0]
            take("CROSS_CLASS_"+c["review"]["primary_tactic"].upper(), [c], 1)
    cross_allocation = {c:counts.get("CROSS_CLASS_"+c.upper(),0) for c in previous.CLASSES}
    counts["CROSS_CLASS_HIGH_CONF_PROXY"] = sum(cross_allocation.values())
    take("UNKNOWN_BORDERLINE", [c for c in available if c["review"]["s_decision_state"] == "UNKNOWN_BORDERLINE"], 16)
    for quartile in range(4):
        take(f"RANK_RANDOM_Q{quartile+1}", [c for c in available if (c["review"]["source_rank"]-1)//50 == quartile], 2)
    targets = {"ACTUAL_MODEL_RULE_CONFLICT": 8, "UNKNOWN_BORDERLINE": 16,
               "CROSS_CLASS_HIGH_CONF_PROXY":8, **{f"RANK_RANDOM_Q{i}":2 for i in range(1,5)}}
    missing = {k: targets[k]-counts.get(k,0) for k in targets if counts.get(k,0) < targets[k]}
    return selected, {"status": "COMPLETE_40" if len(selected) == 40 and not missing else "PARTIAL_QUOTA_SHORTFALL",
                      "requested": targets, "actual": counts, "shortfall": missing,
                      "selected_count": len(selected), "eligible_count": len(candidates),
                      "cross_class_actual_tactic_allocation":cross_allocation,
                      "cross_class_absent_eligible_tactics":[c for c in previous.CLASSES if not any(x["review"]["primary_tactic"]==c for x in cross_pool)],
                      "cross_class_positive_negative_available":bool(has_positive and has_negative),
                      "selection": "fixed hash ordering, one security globally; conflicts then four classes then unknown then rank quartiles",
                      "cross_class_high_confidence_definition": "raw frozen tactic HGB probability>=.70 and model argmax equals rule proxy; prefer2/class, fill within stratum by least represented actual tactic; require positive and negative",
                      "random_definition": "deterministic hash-random two per original-rank quartile among remaining unique securities; fixed seed, no outcomes",
                      "seed": seed, "quota_substitution": False, "cross_class_internal_fallback":True}


def public_case(candidate: dict[str, Any], case_id: str) -> dict[str, Any]:
    """Explicit public whitelist: normalized bars and ordinal anchor facts only."""
    frame = candidate["frame"].tail(60)
    rows = frame.to_dict("records")
    if not blind_eligible(frame, candidate["review"]["decision_date"]):
        raise ContractError("BLIND_REQUIRES_60_REAL_VALID_BARS")
    price_scale = rows[0]["close"]
    volume_scale = sum(r["vol"] for r in rows[:5])/5
    date_to_index = {r["trade_date"]:i for i,r in enumerate(rows)}
    bars = [{"bar_index":i, **{k:float(r[k]/price_scale) for k in ("open","high","low","close","zge_white_line","zge_yellow_line","bbi")},
             "relative_volume":float(r["vol"]/volume_scale)} for i,r in enumerate(rows)]
    anchors = []
    for event in candidate["review"]["anchor_event_trace"]["events"]:
        anchors.append({"role":event["role"], "bar_index":date_to_index.get(event["date"]),
                        "outside_visible_window":event["date"] not in date_to_index,
                        "low":float(event["low"]/price_scale), "body_mid":float(event["mid"]/price_scale)})
    result = {"case_id":case_id, "bars":bars, "anchor_facts":anchors,
              "missing_status":{"bars":"COMPLETE_60_OBSERVED", "anchor_history_left_censored":True,
                                "intraday_line_cross_time":"UNKNOWN"}}
    validate_public_case(result)
    return result


def validate_public_case(case: dict[str, Any]) -> None:
    if set(case) != {"case_id","bars","anchor_facts","missing_status"}:
        raise ContractError("PUBLIC_TOP_LEVEL_LEAK")
    if not re.fullmatch(r"[0-9a-f]{24}", case["case_id"]):
        raise ContractError("PUBLIC_ID_MUST_BE_OPAQUE")
    bar_keys = {"bar_index","open","high","low","close","zge_white_line","zge_yellow_line","bbi","relative_volume"}
    if len(case["bars"]) != 60 or [r["bar_index"] for r in case["bars"]] != list(range(60)):
        raise ContractError("PUBLIC_REAL_BAR_COUNT")
    for b in case["bars"]:
        if set(b) != bar_keys or not all(isinstance(b[k],(int,float)) and math.isfinite(b[k]) for k in bar_keys):
            raise ContractError("PUBLIC_BAR_LEAK_OR_INVALID")
    for a in case["anchor_facts"]:
        if set(a) != {"role","bar_index","outside_visible_window","low","body_mid"} or a["role"] not in {"root","management","repair"}:
            raise ContractError("PUBLIC_ANCHOR_LEAK")
        if (not isinstance(a["outside_visible_window"],bool) or (a["bar_index"] is None) != a["outside_visible_window"]
                or not all(isinstance(a[k],(int,float)) and not isinstance(a[k],bool) and math.isfinite(a[k]) and a[k] > 0 for k in ("low","body_mid"))):
            raise ContractError("PUBLIC_ANCHOR_VALUE_LEAK")
        if a["bar_index"] is not None and (isinstance(a["bar_index"],bool) or not isinstance(a["bar_index"],int) or not 0 <= a["bar_index"] < 60):
            raise ContractError("PUBLIC_ANCHOR_INDEX")
    if case["missing_status"] != {"bars":"COMPLETE_60_OBSERVED", "anchor_history_left_censored":True, "intraday_line_cross_time":"UNKNOWN"}:
        raise ContractError("PUBLIC_STATUS_LEAK")
    # No arbitrary free-text string from a source can reach the public payload.


def write_blind(candidates: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    selected, receipt = select_blind(candidates)
    public = output/"public_blind"
    public.mkdir()
    # IDs and order use system entropy; selection labels never enter filenames.
    shuffled = list(selected)
    secrets.SystemRandom().shuffle(shuffled)
    reveal = []
    manifest = []
    for c in shuffled:
        case_id = secrets.token_hex(12)
        payload = public_case(c, case_id)
        path = public/f"{case_id}.json"
        write_json(path, payload)
        r = c["review"]
        reveal.append({"case_id":case_id, "ts_code":r["ts_code"], "source_rank":r["source_rank"],
                       "source_date":r["source_date"], "observation_date":r["observation_date"], "decision_date":r["decision_date"],
                       "classification_id":r["classification_id"], "episode_id":r["episode_id"], "private_bucket":c["private_bucket"],
                       "draft_decision":r["s_decision_state"], "draft_tactic":r["primary_tactic"],
                       "raw_model_diagnostic":r["frozen_model_diagnostic"], "actual_model_rule_conflict":r["model_rule_conflict"],
                       "draft_differences":{"rule_tactic":r["primary_tactic"], "model_argmax_tactic":r["model_argmax_tactic"]},
                       "price_scale_first_close":float(c["frame"].tail(60).iloc[0].close),
                       "volume_scale_first_five_mean":float(c["frame"].tail(60).head(5).vol.mean())})
        manifest.append({"case_id":case_id, "file":path.name, "sha256":file_sha(path)})
    write_json(public/"manifest.json", {"schema":"ACT021_BLIND_ORDINAL_V1", "cases":manifest})
    (public/"README.txt").write_text("Review only these observed daily sequences, indices 0 through 59. Prices and lines share the first-close scale; volumes share the mean of the first five observations. No calendar, security or draft answer is provided. Anchor facts are observable event roles, not validated tactic answers. Left-censored history and intraday crossing times remain unknown. Return your case_id, D-only S/tactic view, anchor evidence, counterevidence and uncertainty.\n")
    zip_path = output/"public_blind.zip"
    with zipfile.ZipFile(zip_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(public.iterdir()):
            z.write(path,path.name)
    # Verify actual decompression and exact public file membership, not just ZIP headers.
    with zipfile.ZipFile(zip_path) as z:
        if z.testzip() is not None or set(z.namelist()) != {p.name for p in public.iterdir()}:
            raise ContractError("PUBLIC_ZIP_READBACK")
        for item in manifest:
            raw = z.read(item["file"])
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ContractError("PUBLIC_ZIP_SHA")
            validate_public_case(json.loads(raw))
    # Private plaintext is deliberately outside the public folder/ZIP. The
    # controller owns encryption and must not publish this file or receipt.
    private = output/"private_reveal.json"
    write_json(private, {"schema":SCHEMA,"selection_receipt":receipt,"cases":reveal})
    os.chmod(private, 0o600)
    return {**receipt,"public_zip":str(zip_path),"public_zip_sha256":file_sha(zip_path),
            "private_reveal":str(private),"private_reveal_status":"LOCAL_PLAINTEXT_CONTROLLER_ENCRYPTION_REQUIRED",
            "blind_scope":"answers/identities hidden from recipient; not an unexposed sealed statistical holdout"}


FIELD_GROUPS = {
    "1_identity": ("source_rank","ts_code","universe_tag","source_date","observation_date","decision_date","top200_revision","panel_generation","price_basis","strict_le_d_verified","evidence_ref"),
    "2_decision": ("s_decision_state","purity_tier","s_overall_prob","s_overall_score_100","score_kind","score_status","conformal_set_size","uncertainty_score","refusal_flag","refusal_reasons"),
    "3_tactic_stage": ("primary_tactic","secondary_tactic","tactic_probs_json","tactic_score_margin","stage_code","trigger_flags","wave_index"),
    "4_anchor": ("episode_id","root_anchor_id","root_anchor_date","root_anchor_low","active_anchor_id","active_anchor_date","active_anchor_role","active_anchor_low","active_anchor_mid","parent_anchor_id","min_low_since_anchor","min_close_since_anchor","anchor_low_pierced_recovered_flag","anchor_close_broken_flag","anchor_quality_score","support_white_line","support_yellow_line","invalidation_price","rel_vol_contraction","rel_amp_contraction"),
    "5_evidence": ("positive_evidence","contra_evidence","ce_deduction_pts","ce_flag_codes","top_counter_evidence_zh","human_review_priority"),
    "6_revision": ("classification_id","classification_revision","reviewer_status","reviewed_asof_d","prior_revision_ref")}


def run(rank_input: Path, output: Path, *, models_dir: Path | None = None,
        model_contract: Path | None = None, with_benchmark: bool = False,
        reader: Any = None, binder: Any = None) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    from ops import pft_act021_transform as transform
    groups, rank_identity = load_groups(rank_input)
    if output.exists():
        raise ContractError("NEW_OUTPUT_DIRECTORY_REQUIRED_NO_OVERWRITE")
    output.mkdir(parents=True)
    models, model_identity = load_models(models_dir, model_contract)
    exposure = {tuple(x) for x in model_identity.get("reference_exposed_security_dates", [])}
    all_review, candidates, batch_channels, receipts = [], [], [], []
    binder = binder or bind_panel
    reader = reader or read_group
    rechecks = []
    dropped_transform = 0
    benchmark_keys = []
    excluded_exposed = 0
    for g in groups:
        if not g.get("rows"):
            receipts.append({"source_date":g["source_date"],"observation_date":g["observation_date"],"status":"CANNOT_CONFIRM","reason":g["reason"],"rows":0})
            continue
        panel, binding = binder(g)
        usable_models = models if compatible(g,binding,model_identity) else {}
        frame = reader(panel,g) if panel is not None else pd.DataFrame(columns=[*previous.INPUTS,"bbi"])
        # Defensive truncation before feature/state code, even for injected readers.
        if len(frame):
            frame = frame.copy()
            frame["trade_date"] = frame.trade_date.map(day)
            frame = frame.loc[frame.trade_date.le(g["decision_date"])].sort_values(["ts_code","trade_date"],kind="mergesort")
            if frame.duplicated(["ts_code","trade_date"]).any() or not set(frame.ts_code) <= {r["ts_code"] for r in g["rows"]}:
                raise ContractError("INPUT_KEY_SCOPE")
            shapes = previous.causal_shapes(frame,start=g["decision_date"],end=g["decision_date"])
            shape_map = {r["ts_code"]:r for r in shapes.to_dict("records")}
        else:
            shapes, shape_map = pd.DataFrame(), {}
        model_map = infer_batch(shapes,usable_models)
        by_code = {code:part for code,part in frame.groupby("ts_code",sort=False)}
        group_rows = []
        for rank in g["rows"]:
            context = by_code.get(rank["ts_code"],frame.iloc[:0])
            model = model_map.get((rank["ts_code"],g["decision_date"]),{})
            r = review_row(g,rank,context,shape_map.get(rank["ts_code"]),binding,model)
            group_rows.append(r)
            if blind_eligible(context,g["decision_date"]):
                if (rank["ts_code"],g["decision_date"]) in exposure:
                    excluded_exposed += 1
                else:
                    candidates.append({"review":r,"frame":context.tail(60).copy()})
            if with_benchmark:
                try:
                    if not len(context) or context.iloc[-1].trade_date != g["decision_date"]:
                        raise ValueError("EXACT_D_MISSING")
                    batch_channels.append(transform.channels(context.tail(65)))
                    benchmark_keys.append((digest(["ACT021_BENCH_200",r["classification_id"]]),r["classification_id"]))
                except ValueError:
                    dropped_transform += 1
        all_review.extend(group_rows)
        receipts.append({"source_date":g["source_date"],"observation_date":g["observation_date"],"decision_date":g["decision_date"],
                         "rows":len(group_rows),"status":"PROCESSED" if panel is not None else "CANNOT_CONFIRM",
                         "source_binding":binding,"inference":"RETROSPECTIVE_FROZEN_PROXY" if usable_models else "NOT_SCORED_BASIS_OR_MODEL_UNAVAILABLE",
                         "context_counts":{key:sum(r["context_status"]==key for r in group_rows) for key in sorted({r["context_status"] for r in group_rows})}})
        if panel is not None:
            rechecks.append(g)
        print(json.dumps({"stage":"group_complete","source_date":g["source_date"],"rows":len(group_rows),"models":bool(usable_models)}),flush=True)
    ids = [r["classification_id"] for r in all_review]
    if len(ids) != len(set(ids)):
        raise ContractError("DUPLICATE_CLASSIFICATION")
    schema = {"schema_version":SCHEMA,"record_type":"schema","field_groups":FIELD_GROUPS,"batch_unique_key":BATCH_FIELDS,
              "null_policy":"unknown/missing remains null; UNKNOWN is never a negative", "fit_count":0,"backtest_count":0,
              "probability_projection":"pS=max(raw binary HGB, three positive tactic HGB children); invalid_fake is outside S; uncalibrated",
              "decision_policy":"ACT020 fixed weak rule proxy plus explicit refusal; model disagreement/grey .2..8 remains UNKNOWN; no binary .5 gate",
              "score_policy":"fixed 85 positive/20 fake/50 unknown minus disclosed evidence deductions; diagnostic points, not probability",
              "conformal_status":"NOT_FIT_ACT022_OWNS_CALIBRATION", "counter_deductions":DEDUCTIONS,
              "anchor_scope":"causal within bounded 400-calendar-day Reader window; root is first observed event, not unbounded lifetime root",
              "all_fields":list(all_review[0]) if all_review else [],**FLAGS}
    write_json(output/"review_schema.json",schema)
    with (output/"review_rows.jsonl").open("w") as stream:
        stream.write(json.dumps(schema,ensure_ascii=False,allow_nan=False)+"\n")
        for r in all_review:
            stream.write(json.dumps({"record_type":"review",**r},ensure_ascii=False,allow_nan=False)+"\n")
    blind = write_blind(candidates,output)
    bench = {"status":"NOT_RUN"}
    if with_benchmark:
        chosen = sorted(range(len(batch_channels)), key=lambda i:benchmark_keys[i][0])[:200]
        batch = np.stack([batch_channels[i] for i in chosen]) if chosen else np.empty((0,7,60))
        bench = {"status":"RUN" if len(batch) else "NO_ELIGIBLE_ACTUAL_INPUT",**transform.benchmark(batch),
                 "candidate_rows":len(all_review),"samples":len(batch),"eligible_rows":len(batch_channels),"dropped_rows":dropped_transform,
                 "sample_classification_ids":[benchmark_keys[i][1] for i in chosen],
                 "sample_scope":"fixed hash-selected up to200 actual candidate security-D rows with exact D and 65 valid observed bars; repeat securities across dates retained"}
        write_json(output/"benchmark.json",bench)
    for g in rechecks:
        binder(g)
    if file_sha(rank_input) != rank_identity["sha256"]:
        raise ContractError("RANK_PACKAGE_CHANGED_DURING_RUN")
    for g in groups:
        for manifest in g.get("source_manifests",[]):
            checked_file(manifest["path"],manifest["sha256"])
    summary = {"schema":SCHEMA,"rank_input":rank_identity,"groups":receipts,"review_rows":len(all_review),
               "actual_fit":{"S":0,"B":0,"tuning":0,"conformal":0},"backtest_count":0,"model_contract":model_identity,
               "blind":{**blind,"excluded_previously_exposed_exact_security_D":excluded_exposed},"benchmark":bench,
               "source_recheck":"PASS_NO_EXCEPTION","classification_status":"DRAFT_RESEARCH_PROXY_NOT_ADJUDICATED",
               "production_status":"NOT_DEPLOYED","api_status":"NOT_WRITTEN","ui_status":"NOT_RUN",**FLAGS}
    write_json(output/"summary.json",summary)
    write_json(output/"artifact_manifest.json", {"schema":SCHEMA,"files":[{"path":str(p.relative_to(output)),"bytes":p.stat().st_size,"sha256":file_sha(p),
                 "visibility":"PRIVATE_CONTROLLER_ENCRYPTION_REQUIRED" if p.name == "private_reveal.json" else "RESEARCH_REVIEW"} for p in sorted(output.rglob("*")) if p.is_file()]})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank-input",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--models-dir",type=Path)
    parser.add_argument("--model-contract",type=Path)
    parser.add_argument("--benchmark",action="store_true")
    args = parser.parse_args()
    result = run(args.rank_input,args.output,models_dir=args.models_dir,model_contract=args.model_contract,with_benchmark=args.benchmark)
    print(json.dumps({"review_rows":result["review_rows"],"blind_status":result["blind"]["status"],"fit":result["actual_fit"],"output":str(args.output)},ensure_ascii=False))


if __name__ == "__main__":
    main()
