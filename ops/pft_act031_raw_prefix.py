"""Read the dated V4 QFQ owner recipe when its archived panel is unavailable."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ops import research_panel_qfq as qfq
from ops.pft_act031_frozen_forward import ContractError, read_ref
from ops.pft_act028_rebuild_maturity import date8

COLUMNS = ("ts_code", "trade_date", "market_type", "open", "high", "low", "close", "vol",
           "zge_white_line", "zge_yellow_line", "bbi", "tradeable_basic", "bars_since_list")


def bind_recipe(day, source):
    receipt = read_ref(source["producer_ref"])
    adjustment = source["adjustment_ref"]
    snapshot = read_ref(adjustment)
    roles = receipt.get("candidate_sha256", {})
    role = source.get("panel_role", "backtest")
    if (receipt.get("schema") != "a_share_qfq_panel_v1" or receipt.get("status") not in {"READY", "CANDIDATE_READY"}
            or date8(receipt.get("target_date")) != day or date8(receipt.get("asof_date")) != day
            or date8(snapshot.get("asof_date")) != day or date8(snapshot.get("coverage_end_date")) != day
            or receipt.get("generation_id") != source["source_generation"]
            or source.get("panel_sha256") != roles.get(role)
            or source.get("panel_path") != receipt.get("candidates", {}).get(role)
            or receipt.get("adjustment_snapshot") != adjustment
            or receipt.get("snapshot_file_sha256") != adjustment["sha256"]
            or receipt.get("input_sha256") != qfq.canonical_sha(snapshot)
            or snapshot.get("schema") not in {"a_share_qfq_adjustment_input_v1", "a_share_qfq_adjustment_input_research_cache_v1"}
            or (snapshot.get("price_basis"), snapshot.get("volume_basis"), snapshot.get("amount_basis"))
               != ("QFQ_ASOF", "QFQ_EVENT_VOLUME", "RAW_TURNOVER")):
        raise ContractError(f"ACT031_DATED_V4_RECIPE_IDENTITY_MISMATCH:{day}")
    driver_ref, formula_ref = source["driver_ref"], source["formula_ref"]
    if (driver_ref["sha256"] != receipt.get("driver_sha256") or formula_ref["sha256"] != receipt.get("formula_sha256")
            or formula_ref["sha256"] != source.get("formula_sha256")
            or driver_ref["sha256"] != qfq.DRIVER_SHA or formula_ref["sha256"] != qfq.FORMULA_SHA):
        raise ContractError(f"ACT031_DATED_V4_AUTHORITY_SHA_MISMATCH:{day}")
    driver, formula = qfq.authorities(Path(driver_ref["path"]), Path(formula_ref["path"]))
    quarantine = read_ref(receipt["quarantine_manifest"])
    if quarantine.get("generation_id") != source["source_generation"]:
        raise ContractError(f"ACT031_DATED_V4_QUARANTINE_GENERATION_MISMATCH:{day}")
    return snapshot, set(quarantine["reasons"]) | set(snapshot.get("quarantine_symbols", {})), driver, formula


def project_formula(adjusted, formula):
    """Project the pinned canonical compute_group_formula's W, Y and BBI."""
    close = adjusted.close
    ma = {length: close.rolling(length, min_periods=1).mean() for length in (3, 6, 12, 24, 14, 28, 57, 114)}
    adjusted["zge_white_line"] = formula.ema_by_group(formula.ema_by_group(close, 10), 10)
    adjusted["zge_yellow_line"] = (ma[14] + ma[28] + ma[57] + ma[114]) / 4.0
    adjusted["bbi"] = (ma[3] + ma[6] + ma[12] + ma[24]) / 4.0
    return adjusted


def retained_native_alias(code, reference, target):
    """Same-date V4 native-input copies are interchangeable only at exact SHA."""
    path = Path(reference["path"])
    number, exchange = code.split(".")
    market = exchange.lower()
    suffix = ("tdx", "vipdoc", market, "lday", f"{market}{number}.day")
    if not path.is_absolute() or tuple(path.parts[-5:]) != suffix:
        return None
    day_root = path.parents[4] / "receipts" / "formula_inputs" / str(target)
    pattern = f"*/vipdoc/{market}/lday/{path.name}"
    for candidate in sorted(day_root.glob(pattern)):
        if candidate.is_file() and candidate.resolve(strict=True) == candidate and qfq.sha(candidate) == reference["sha256"]:
            return {**reference, "path": str(candidate)}
    return None


def bound_raw_history(code, item, target, driver):
    references = list(item["raw_files"])
    substitutions = {}
    while True:
        paths = [Path(reference["path"]) for reference in references]
        unbound = next((i for i, path in enumerate(paths) if not path.is_file()), None)
        reason = "MISSING_BOUND_RAW_SOURCE"
        if unbound is None:
            stats = [path.stat() for path in paths]
            try:
                raw = qfq.resolved_raw_history(code, {**item, "raw_files": references}, target, driver)
            except qfq.QfqGateError as error:
                unbound = next((i for i, path in enumerate(paths)
                                if str(error) == f"SOURCE_BINDING_FAILED:{code}:{path}"), None)
                if unbound is None:
                    raise
                reason = "BOUND_RAW_SHA_UNAVAILABLE"
            else:
                if [path.stat() for path in paths] != stats:
                    raise ContractError(f"ACT031_DATED_V4_RAW_SOURCE_MOVED:{code}")
                return raw, None, list(substitutions.values())
        if unbound in substitutions:
            return None, reason, []
        original = references[unbound]
        alias = retained_native_alias(code, original, target)
        if alias is None:
            return None, reason, []
        references[unbound] = alias
        substitutions[unbound] = {"symbol": code, "original_path": original["path"],
                                  "alias_path": alias["path"], "sha256": alias["sha256"]}


def read_symbol(code, item, target, lower, driver, formula, *, aliases=None):
    if item.get("event_coverage_complete") is not True or not item.get("raw_files") or "events" not in item:
        raise ContractError(f"ACT031_DATED_V4_SYMBOL_RECIPE_INVALID:{code}")
    dates = [int(event["ex_date"]) for event in item["events"]]
    if (dates != sorted(set(dates)) or any(not int(item["history_start_date"]) < date <= target for date in dates)
            or any(not np.isfinite([float(event[key]) for key in ("a", "b", "volume_a")]).all()
                   or min(float(event["a"]), float(event["volume_a"])) <= 0 for event in item["events"])):
        raise ContractError(f"ACT031_DATED_V4_ADJUSTMENT_EVENTS_INVALID:{code}")
    raw, issue, substitutions = bound_raw_history(code, item, target, driver)
    if issue:
        return None, issue
    if aliases is not None:
        aliases.extend(substitutions)
    if raw.empty:
        return None, "NO_RAW_HISTORY_IN_DATED_RECIPE"
    if int(raw.trade_date.min()) != item["history_start_date"]:
        raise ContractError(f"ACT031_DATED_V4_HISTORY_START_CONFLICT:{code}")
    raw = raw.loc[raw.trade_date.between(item.get("compute_start_date") or item["history_start_date"], target)].reset_index(drop=True)
    if raw.empty or raw.trade_date.iloc[-1] != target:
        return None, "NO_EXACT_D_IN_BOUND_RAW_HISTORY"
    # Keep the original owner's raw corruption quarantine condition.
    amount_bits = raw.amount.to_numpy(dtype=np.float32).view(np.uint32)
    if ((amount_bits == 0x00400000) & raw.vol.eq(0).to_numpy()).any():
        return None, "ORIGINAL_RAW_FIELD_SIGNATURE_QUARANTINED"
    adjusted = project_formula(qfq.apply_adjustments(raw, item["events"], target), formula)
    adjusted["market_type"] = "BJ" if code.endswith(".BJ") else "A_SHARE"
    adjusted["tradeable_basic"] = (raw[["open", "high", "low", "close"]].gt(0).all(axis=1)
                                    & raw.amount.gt(0) & raw.vol.gt(0)).astype("int8")
    adjusted["bars_since_list"] = np.arange(1, len(adjusted) + 1)
    projected = adjusted.loc[adjusted.trade_date.ge(lower), list(COLUMNS)].copy()
    projected["trade_date"] = projected.trade_date.astype(str)
    return projected, None


def read_recovered(day, source, codes):
    """Read only a <=D causal projection, and keep omitted exact-D codes visible."""
    snapshot, quarantine, driver, formula = bind_recipe(day, source)
    target = int(day)
    lower = int((datetime.strptime(day, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d"))
    role = source.get("panel_role", "backtest")
    parts, omitted, aliases = [], defaultdict(list), []
    for code in sorted(codes):
        item = snapshot["symbols"].get(code)
        if code in quarantine:
            omitted["ORIGINAL_D_QUARANTINE"].append(code)
        elif item is None or role not in item.get("publish_roles", []):
            omitted["NO_D_RECIPE_FOR_ORIGINAL_ROLE"].append(code)
        else:
            frame, failed = read_symbol(code, item, target, lower, driver, formula, aliases=aliases)
            if failed:
                omitted[failed].append(code)
            else:
                parts.append(frame)
    result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
    result.attrs["recovery"] = {
        "mode": "V4_DATED_QFQ_OWNER_RECIPE_IN_MEMORY", "producer_ref": source["producer_ref"],
        "adjustment_ref": source["adjustment_ref"], "driver_ref": source["driver_ref"], "formula_ref": source["formula_ref"],
        "dated_symbol_requests": len(codes), "projected_symbols": len(parts), "projected_rows": len(result),
        "omitted_by_reason": dict(omitted), "same_sha_native_substitution_count": len(aliases),
        "same_sha_native_substitutions": aliases, "physical_panel_written": False,
    }
    return result
