#!/usr/bin/env python3
"""Sample continuous A-share dates from the bound V4 research projection."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from pyarrow import parquet as pq

from p515_sample_frame import bind_source, sha256_file


START = "20260701"
BURN_START = "20260601"
END = "20261113"
SEED = "p515-r1.3-continuous-20261113-v1"
TARGET = 6000
MARKETS = ("SH", "SZ", "BJ")
RESEARCH = {
    "RESEARCH_ONLY": True,
    "NEW_ESTIMATOR_FIT": 0,
    "NEW_MODEL_PREDICT_COUNT": 0,
    "PRODUCTION_ALLOWED": False,
    "BUY_GATE_UPDATED": False,
    "ORDERS_SENT": False,
}
PROXIES = (
    "DOWNTREND_CONTINUATION_PROXY",
    "BREAKOUT_FAILURE_NEXT_SESSION_PROXY",
    "FALSE_INTRADAY_BREAKOUT_PROXY",
    "HIGH_VOLUME_AT_HIGH_PROXY",
    "HIGH_INTRADAY_REVERSAL_PROXY",
    "TREND_CONSOLIDATION_PROXY",
    "ORDINARY_REBOUND_PROXY",
    "NO_OBVIOUS_ATTACK_10D_PROXY",
    "STRONG_STOCK_D_ONLY_PROXY",
    "FAILURE_STOCK_D_ONLY_PROXY",
)
BREAKOUT = ["breakout", "double_breakout", "break_prev_high"]
PULLBACK = ["brick_pullback_shrink", "brick_pullback_white_b", "brick_pullback_yellow_b"]
BUY = ["primary_buy_signal", "secondary_buy_signal"]
COLUMNS = [
    "ts_code", "trade_date", "market_type", "exchange", "open", "high", "low", "close",
    "volume", "amount", "pct_chg", "amplitude_pct", "bar_close_pos", "upper_shadow_pct",
    "amount_ratio_20", "vol_ratio_60", "ma20", "ma60", "high_20", "high_20_prev", "market_cap_yi",
    "finance_source_date", "tdx_industry_code", "brick_buy2_attack", *BUY, *BREAKOUT, *PULLBACK,
]
ARCHIVE_FIELDS = ["D", "ts_code", "stable_security_id", "exchange", "original_state", "price_observed_D"]
STATE_UNKNOWN = {"", "UNKNOWN_DATA", "UNKNOWN_NO_EXACT_D_INPUT"}
SHA = re.compile(r"[a-f0-9]{64}")


def counts(series) -> dict:
    return {str(key): int(value) for key, value in series.value_counts(dropna=False).sort_index().items()}


def hash_csv(frame: pd.DataFrame) -> str:
    """Digest a key-ordered CSV in chunks, using a fixed numeric format."""
    digest = sha256()
    for start in range(0, len(frame), 32768):
        block = frame.iloc[start:start + 32768]
        digest.update(block.to_csv(index=False, header=start == 0, lineterminator="\n",
                                   float_format="%.17g").encode())
    return digest.hexdigest()


def calendar_sessions(calendar_path: Path, replay_root: Path) -> tuple[list[str], dict]:
    contract = json.loads(calendar_path.read_bytes())
    old_path = replay_root / "BACKTEST_CONTRACT.json"
    old = json.loads(old_path.read_bytes())
    source_sha = sha256_file(calendar_path)
    source_shas = {item["sha256"] for item in old["calendar_sources"]}
    if source_sha not in source_shas or contract["year"] != 2026 or contract["timezone"] != "Asia/Shanghai":
        raise ValueError("V4_CALENDAR_CONTRACT_MISMATCH")
    reference_path = replay_root / "BOUND_EXCHANGE_CALENDAR.json"
    reference_sha = sha256_file(reference_path)
    if reference_sha != old["calendar_bound"]["sha256"]:
        raise ValueError("REPLAY_CALENDAR_SHA_MISMATCH")
    reference = json.loads(reference_path.read_bytes())
    holidays = contract["markets"]["a_share"]["holiday_periods"]
    day = date.fromisoformat(BURN_START)
    last = date.fromisoformat(END)
    sessions = []
    while day <= last:
        key = day.strftime("%Y%m%d")
        if day.weekday() < 5 and not any(h["start"] <= key <= h["end"] for h in holidays):
            sessions.append(key)
        day += timedelta(days=1)
    for market in MARKETS:
        actual = [str(value) for value in reference[market] if BURN_START <= str(value) <= END]
        if actual != sessions:
            raise ValueError(f"REPLAY_V4_CALENDAR_DISAGREEMENT:{market}")
    return sessions, {
        "status": "V4_A_SHARE_AND_P5143_PER_EXCHANGE_REFERENCE_AGREE",
        "v4_calendar_sha256": source_sha,
        "replay_exchange_calendar_sha256": reference_sha,
        "replay_backtest_contract_sha256": sha256_file(old_path),
        "burn_start_inclusive": BURN_START,
        "calendar_row_not_suspension_certification": True,
    }


def panel_window(logical, sessions: list[str]) -> tuple[pd.DataFrame, dict]:
    """Stream the established overlay resolver once and retain only bounded columns and dates."""
    projections = []
    seen = 0
    non_a = Counter()
    raw_counts = Counter()
    date_values = pa.array(sessions, type=pa.string())
    tags = pa.array(["A_SHARE", "BJ"], type=pa.string())
    for batch in logical.iter_batches(batch_size=131072, columns=COLUMNS):
        table = pa.Table.from_batches([batch])
        seen += len(table)
        date_col = table["trade_date"]
        window = table.filter(pc.and_(pc.greater_equal(date_col, BURN_START), pc.less_equal(date_col, END)))
        if not len(window):
            continue
        a_mask = pc.is_in(window["market_type"], value_set=tags)
        window_a = window.filter(a_mask)
        dropped = window.filter(pc.invert(a_mask)).select(["trade_date", "market_type"])
        for row in dropped.to_pylist():
            if row["trade_date"] >= START:
                tag = str(row["market_type"])
                non_a[tag] += 1
        invalid_date = window_a.filter(pc.invert(pc.is_in(window_a["trade_date"], value_set=date_values)))
        if len(invalid_date):
            days = sorted(set(invalid_date["trade_date"].to_pylist()))
            raise ValueError(f"PANEL_A_ROW_OUTSIDE_BOUND_EXCHANGE_CALENDAR:{days}")
        if len(window_a):
            projections.append(window_a)
    if not projections:
        raise ValueError("BOUND_PANEL_CONTAINS_NO_WINDOW_ROWS")
    frame = pa.concat_tables(projections).replace_schema_metadata().to_pandas()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["ts_code"] = frame["ts_code"].astype(str)
    frame["observation_exchange"] = frame["ts_code"].str[-2:]
    code_ok = frame["ts_code"].str.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", na=False)
    exchanges = frame["exchange"].fillna("").str.upper().replace(
        {"SSE": "SH", "SHSE": "SH", "SZSE": "SZ", "BSE": "BJ", "BSEBJ": "BJ"})
    market_ok = frame["market_type"].eq("A_SHARE") & frame["observation_exchange"].isin(("SH", "SZ"))
    market_ok |= frame["market_type"].eq("BJ") & frame["observation_exchange"].eq("BJ")
    # A suffix corroborates identity only when the panel exchange agrees.
    valid_identity = code_ok & market_ok & exchanges.eq(frame["observation_exchange"])
    requested = frame["trade_date"].ge(START)
    raw_counts.update({
        "logical_rows_streamed_all_markets_all_history": seen,
        "window_panel_rows_with_a_or_bj_tag": int(requested.sum()),
        "window_non_a_or_bj_tag": int(sum(non_a.values())),
        "window_a_or_bj_tag_security_identity_conflict": int((requested & ~valid_identity).sum()),
        "window_bound_identity_rows": int((requested & valid_identity).sum()),
        "burn_identity_rows": int((~requested & valid_identity).sum()),
    })
    excluded = frame.loc[requested & ~valid_identity, ["trade_date", "ts_code", "market_type", "exchange"]]
    raw_counts["window_excluded_identity_reason_rows"] = len(excluded)
    frame = frame.loc[valid_identity].sort_values(["ts_code", "trade_date"], ignore_index=True)
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise ValueError("BOUND_PANEL_DUPLICATE_SECURITY_DATE")
    return frame, {
        **raw_counts,
        "window_excluded_non_a_by_tag": dict(sorted(non_a.items())),
        "window_identity_conflict_by_tag": counts(excluded["market_type"]),
        "window_identity_conflict_key_sha256": hash_csv(excluded) if len(excluded) else None,
    }


def marker(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    values = frame[columns]
    return pd.Series(np.select([values.eq(1).any(axis=1), values.eq(0).all(axis=1)],
                               ["TRUE", "FALSE"], default="UNKNOWN"), index=frame.index)


def tercile(frame: pd.DataFrame, name: str, dimensions: list[str], positive_only: bool = False) -> pd.Series:
    values = frame[name]
    good = np.isfinite(values) & values.ge(0)
    if positive_only:
        good &= values.gt(0)
    known = frame.loc[good, dimensions + [name, "ts_code"]].sort_values([*dimensions, name, "ts_code"])
    groups = known.groupby(dimensions, sort=False, observed=True)
    position = groups.cumcount()
    sizes = groups[name].transform("size")
    result = pd.Series("UNKNOWN", index=frame.index, dtype="str")
    result.loc[known.index] = np.array(["LOW", "MID", "HIGH"])[(position * 3 // sizes).to_numpy()]
    return result


def geometry(frame: pd.DataFrame, sessions: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    close, low, high, opening = (frame[field] for field in ("close", "low", "high", "open"))
    prices = frame[["close", "low", "high", "open"]]
    price_ok = np.isfinite(prices).all(axis=1) & prices.gt(0).all(axis=1)
    price_ok &= high.ge(prices[["close", "low", "open"]].max(axis=1) - 1e-8)
    price_ok &= low.le(prices[["close", "open"]].min(axis=1) + 1e-8)
    traded_proxy = np.isfinite(frame["amount"]) & frame["amount"].gt(0)
    traded_proxy &= np.isfinite(frame["volume"]) & frame["volume"].gt(0)
    buy = marker(frame, BUY)
    breakout = marker(frame, BREAKOUT)
    pullback = marker(frame, PULLBACK)
    ordinal = frame["trade_date"].map({key: position for position, key in enumerate(sessions)})
    security = frame["ts_code"]
    prev_session = ordinal.eq(ordinal.groupby(security, sort=False).shift(1).add(1))
    prior_threshold = frame["high_20_prev"]
    today_break = close.gt(prior_threshold.mul(1.001)) & prior_threshold.gt(0)
    breakout_observable = prior_threshold.gt(0) & price_ok & traded_proxy
    prior_confirmed = today_break & breakout_observable
    prior_break = prior_confirmed.groupby(security, sort=False).shift(1, fill_value=False) & prev_session
    prior_held_threshold = prior_threshold.groupby(security, sort=False).shift(1).where(prev_session)
    attack_native = marker(frame, ["brick_buy2_attack"])
    attack_observable = prior_threshold.gt(0) & price_ok & traded_proxy & attack_native.ne("UNKNOWN")
    attack = (attack_native.eq("TRUE") | today_break).astype(float).where(attack_observable)
    last_10 = attack.groupby(security, sort=False).rolling(10, min_periods=10).max()
    last_10 = last_10.droplevel(0).reindex(frame.index)
    complete_10 = ordinal.sub(ordinal.groupby(security, sort=False).shift(9)).eq(9)
    no_attack = last_10.eq(0) & complete_10
    ma20, ma60 = frame["ma20"], frame["ma60"]
    pct = frame["pct_chg"]
    near_high = frame["high_20"].gt(0) & close.div(frame["high_20"]).ge(0.90)
    top_zone = frame["high_20_prev"].gt(0) & high.div(frame["high_20_prev"]).ge(0.98)
    close_pos = frame["bar_close_pos"]
    volume_burst = frame["amount_ratio_20"].ge(1.8) & frame["vol_ratio_60"].ge(1.5)
    dev = pd.DataFrame(index=frame.index)
    dev["ordinary_rebound"] = (pct.ge(0.5) & close.lt(ma20) & breakout.eq("FALSE"))
    dev["downtrend_continuation"] = (pct.le(-1) & close.lt(ma20) & ma20.lt(ma60))
    dev["false_intraday_breakout"] = (prior_threshold.gt(0) & high.gt(prior_threshold.mul(1.001))
                                        & close.lt(prior_threshold.mul(0.999)))
    dev["prior_breakout_failure"] = prior_break & close.lt(prior_held_threshold.mul(0.999))
    dev["trend_consolidation"] = (ma20.gt(0) & ma20.gt(ma60) & close.div(ma20).sub(1).abs().le(0.02)
                                   & frame["amplitude_pct"].between(0, 3) & breakout.eq("FALSE"))
    dev["high_intraday_reversal"] = (top_zone & close_pos.between(0, 0.35)
                                      & frame["upper_shadow_pct"].ge(2))
    dev["high_volume_at_high"] = top_zone & near_high & volume_burst
    dev["no_obvious_attack"] = no_attack & breakout.eq("FALSE")
    dev["strong_stock"] = (pct.ge(3) & close.gt(ma20) & ma20.gt(ma60) & near_high & close_pos.between(0.65, 1))
    dev["failure_stock"] = (pct.le(-4) & close.lt(ma20) & close_pos.between(0, 0.35))
    controls = [
        dev["downtrend_continuation"], dev["prior_breakout_failure"], dev["false_intraday_breakout"],
        dev["high_volume_at_high"], dev["high_intraday_reversal"], dev["trend_consolidation"],
        dev["ordinary_rebound"], dev["no_obvious_attack"], dev["strong_stock"], dev["failure_stock"],
    ]
    frame["proxy_category"] = np.select([buy.eq("TRUE"), *controls],
                                         ["NATIVE_BUY_CONTEXT", *PROXIES], default="OTHER_NON_SIGNAL_PROXY")
    frame["exclusion_reason"] = np.select(
        [~price_ok, ~traded_proxy, buy.eq("UNKNOWN")],
        ["INVALID_OHLC_PANEL_ROW", "TRADING_ACTIVITY_UNCONFIRMED", "NATIVE_BUY_STATUS_UNKNOWN"],
        default="ELIGIBLE",
    )
    frame["native_buy_status"], frame["native_breakout_status"], frame["native_pullback_status"] = buy, breakout, pullback
    frame["previous_breakout_status"] = np.select(
        [prior_break, prev_session & breakout_observable.groupby(security, sort=False).shift(1, fill_value=False)],
        ["TRUE", "FALSE"], default="UNKNOWN")
    frame["previous_breakout_threshold"] = prior_held_threshold.where(prior_break)
    frame["previous_session_date"] = frame["trade_date"].groupby(security, sort=False).shift(1).where(prev_session)
    frame["attack_10d_state"] = np.select([no_attack, last_10.eq(1) & complete_10],
                                           ["NO_OBVIOUS_ATTACK", "ATTACK_MARKER_PRESENT"], default="UNKNOWN")
    frame["sample_proxy_flags"] = pd.Series("", index=frame.index, dtype="str")
    for field in dev:
        eligible_flag = dev[field].fillna(False)
        old = frame.loc[eligible_flag, "sample_proxy_flags"]
        frame.loc[eligible_flag, "sample_proxy_flags"] = np.where(old.eq(""), field, old + "|" + field)
    return frame


def old_pool(frame: pd.DataFrame, replay_root: Path) -> tuple[pd.DataFrame, dict]:
    """Use the pre-outcome archive's exact D/security state columns only."""
    freeze_path = replay_root / "repair/ALL_SELECTIONS_FREEZE.json"
    freeze = json.loads(freeze_path.read_bytes())
    archive = replay_root / "repair/selection/ALL_WINDOW_SCOPE_AND_EXCLUSIONS.parquet"
    source_sha = sha256_file(archive)
    if (freeze["all_scope_sha256"] != source_sha or freeze.get("outcome_reader_started") is not False
            or freeze.get("original_pool_binding_restored") is not True):
        raise ValueError("OLD_CONF_SCOPE_FREEZE_MISMATCH")
    old = pq.read_table(archive, columns=ARCHIVE_FIELDS).to_pandas()
    if old.duplicated(["D", "ts_code"]).any() or sorted(old["D"].unique()) != freeze["signal_dates"]:
        raise ValueError("OLD_CONF_SCOPE_KEY_OR_DATES_CONFLICT")
    native_identity = old["ts_code"].eq(old["stable_security_id"]) & old["ts_code"].str[-2:].eq(old["exchange"])
    valid_state = ~old["original_state"].fillna("").isin(STATE_UNKNOWN)
    old["archive_status"] = np.select(
        [old["price_observed_D"] & native_identity & old["original_state"].eq("BUYPOINT_CONFIRMED"),
         old["price_observed_D"] & native_identity & valid_state],
        ["PRESENT_CONF_IN_REPLAY_D", "OBSERVED_NOT_CONF_IN_REPLAY_D"], default="UNKNOWN_REPLAY_D_EVIDENCE")
    aliases = old.loc[~native_identity & old["ts_code"].str.endswith(".BJ"), ["ts_code", "stable_security_id"]]
    if aliases.groupby("ts_code")["stable_security_id"].nunique().gt(1).any():
        raise ValueError("ARCHIVED_BJ_ALIAS_MAP_CONFLICT")
    alias_codes = set(aliases["ts_code"])
    old["trade_date"] = old["D"].astype(str)
    calendar = [str(value) for value in freeze["signal_dates"]]
    ordinal = {key: index for index, key in enumerate(calendar)}
    old = old.sort_values(["ts_code", "trade_date"], ignore_index=True)
    verified = old["archive_status"].ne("UNKNOWN_REPLAY_D_EVIDENCE")
    confirmed = old["archive_status"].eq("PRESENT_CONF_IN_REPLAY_D")
    group = old["ts_code"]
    old["old_archive_prior_covered_sessions_n"] = verified.groupby(group, sort=False).cumsum() - verified
    old["old_archive_prior_conf_n"] = confirmed.groupby(group, sort=False).cumsum() - confirmed
    old["old_archive_prior_expected_sessions_n"] = old["trade_date"].map(ordinal)
    full_prior = old["old_archive_prior_covered_sessions_n"].eq(old["old_archive_prior_expected_sessions_n"])
    old["old_archive_prior_conf_status"] = np.select(
        [old["old_archive_prior_conf_n"].gt(0), full_prior & old["old_archive_prior_expected_sessions_n"].gt(0)],
        ["PRESENT_IN_PRIOR_REPLAY_WINDOW", "OBSERVED_NONE_IN_COMPLETE_PRIOR_REPLAY_WINDOW"],
        default="UNKNOWN_INSUFFICIENT_PRIOR_REPLAY_SCOPE")
    kept = ["ts_code", "trade_date", "archive_status", "old_archive_prior_covered_sessions_n",
            "old_archive_prior_expected_sessions_n", "old_archive_prior_conf_status"]
    frame = frame.merge(old[kept], on=["ts_code", "trade_date"], how="left", sort=False, validate="1:1")
    archive_matched = frame["archive_status"].notna()
    in_archive = frame["trade_date"].isin(calendar)
    frame["old_archive_scope_status"] = np.where(
        archive_matched, frame["archive_status"], np.where(in_archive, "UNKNOWN_NOT_IN_ARCHIVE_SCOPE", "UNKNOWN_OUTSIDE_ARCHIVE_DATES"))
    frame["old_archive_prior_conf_status"] = frame["old_archive_prior_conf_status"].fillna("UNKNOWN_NOT_BOUND_D")
    unresolved_alias = frame["ts_code"].isin(alias_codes)
    frame.loc[unresolved_alias & frame["exclusion_reason"].eq("ELIGIBLE"), "exclusion_reason"] = (
        "ARCHIVED_BJ_NATIVE_ALIAS_IDENTITY_NOT_DATE_RESOLVED"
    )
    return frame, {
        "source_relative": "repair/selection/ALL_WINDOW_SCOPE_AND_EXCLUSIONS.parquet",
        "source_sha256": source_sha, "pre_outcome_freeze_sha256": sha256_file(freeze_path),
        "columns_read": ARCHIVE_FIELDS, "date_start": calendar[0], "date_end": calendar[-1],
        "session_n": len(calendar), "source_rows": len(old), "archive_alias_rows": int((~native_identity).sum()),
        "archived_bj_alias_codes": len(alias_codes), "panel_window_rows_with_archived_bj_alias": int(unresolved_alias.sum()),
        "alias_policy": "Do not normalize unresolved legacy BJ codes into D-specific identities; exclude from eligible frame.",
        "source_exact_status_counts": counts(old["archive_status"]),
        "grade": "CURRENT_VERSION_RETROSPECTIVE_REPLAY_NONPIT",
        "meaning": "Exact native security and D compared only against saved P5.14.3 raw CONF state in 38 bound dates. Prior status uses earlier archived dates only.",
    }


def valid_industry(value):
    text = str(value).strip()
    return text if re.fullmatch(r"[A-Z0-9]{2,16}", text) else "UNKNOWN"


def sample_controls(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Allocate one draw to each populated stratum, then apportion remaining capacity."""
    frame = frame.copy()
    frame["cap_tier_as_stored_nonpit"] = tercile(frame, "market_cap_yi", ["trade_date"], positive_only=True)
    frame["industry_code_as_stored_nonpit"] = frame["tdx_industry_code"].map(valid_industry)
    frame["volatility_tier_amplitude_D"] = tercile(frame, "amplitude_pct", ["trade_date", "observation_exchange"])
    frame["liquidity_tier_turnover_D"] = tercile(frame, "amount", ["trade_date", "observation_exchange"], positive_only=True)
    day_returns = frame["pct_chg"].where(np.isfinite(frame["pct_chg"]))
    advances = day_returns.gt(0).astype(float).where(day_returns.notna())
    declines = day_returns.lt(0).astype(float).where(day_returns.notna())
    up = advances.groupby(frame["trade_date"]).transform("mean")
    down = declines.groupby(frame["trade_date"]).transform("mean")
    frame["market_regime_proxy"] = np.select([up.ge(0.60), down.ge(0.60), up.notna()],
                                               ["RISING_BREADTH_PROXY", "FALLING_BREADTH_PROXY", "MIXED_BREADTH_PROXY"],
                                               default="UNKNOWN")
    frame["sample_month"] = frame["trade_date"].str[:6]
    archive_confirmed = frame["old_archive_scope_status"].eq("PRESENT_CONF_IN_REPLAY_D")
    archive_non_confirmed = frame["old_archive_scope_status"].eq("OBSERVED_NOT_CONF_IN_REPLAY_D")
    native_confirmed = frame["native_buy_status"].eq("TRUE")
    frame["archive_stratum"] = np.select(
        [archive_confirmed, archive_non_confirmed], ["BOUND_ARCHIVE_CONF", "BOUND_ARCHIVE_NON_CONF"],
        default="UNKNOWN_ARCHIVE",
    )
    frame["research_sample_role"] = np.select(
        [archive_confirmed, native_confirmed, archive_non_confirmed],
        ["ARCHIVE_CONF_CONTROL", "NATIVE_BUY_CONTROL", "NATIVE_NON_BUY_WITH_ARCHIVE_NON_CONF"],
        default="NATIVE_NON_BUY_ARCHIVE_STATUS_UNKNOWN",
    )
    strata = ["sample_month", "observation_exchange", "cap_tier_as_stored_nonpit", "proxy_category", "archive_stratum"]
    frame["sampling_stratum"] = frame[strata].agg("|".join, axis=1)
    eligible = frame.loc[frame["exclusion_reason"].eq("ELIGIBLE")].copy()
    strata_counts = eligible.groupby("sampling_stratum", sort=True).size().rename("population_n").to_frame()
    target = min(len(eligible), max(len(strata_counts), TARGET))
    if not target:
        raise ValueError("NO_ELIGIBLE_STOCK_DAYS")
    capacity = strata_counts["population_n"] - 1
    remaining = target - len(strata_counts)
    apportioned = capacity * remaining / capacity.sum() if capacity.sum() else capacity
    first = apportioned.astype(int)
    strata_counts["sample_n"] = first + 1
    fractional = apportioned - first
    residue = int(target - strata_counts["sample_n"].sum())
    to_increment = fractional[capacity.gt(first)].sort_values(ascending=False, kind="stable").head(residue).index
    strata_counts.loc[to_increment, "sample_n"] += 1
    if int(strata_counts["sample_n"].sum()) != target or strata_counts["sample_n"].gt(strata_counts["population_n"]).any():
        raise ValueError("STRATIFIED_TARGET_INVARIANT")
    priority = (SEED + "|" + eligible["sampling_stratum"] + "|" + eligible["trade_date"] + "|" + eligible["ts_code"])
    eligible["sha256_rank_key"] = priority.map(lambda value: sha256(value.encode()).hexdigest())
    ordered = eligible.sort_values(["sampling_stratum", "sha256_rank_key", "ts_code", "trade_date"])
    ranks = ordered.groupby("sampling_stratum", sort=False).cumcount() + 1
    picked = ordered.loc[ranks.le(ordered["sampling_stratum"].map(strata_counts["sample_n"]))].copy()
    picked["rank_within_stratum"] = ranks.loc[picked.index]
    picked["population_stratum_n"] = picked["sampling_stratum"].map(strata_counts["population_n"])
    picked["selected_stratum_n"] = picked["sampling_stratum"].map(strata_counts["sample_n"])
    picked["inclusion_probability"] = picked["selected_stratum_n"] / picked["population_stratum_n"]
    check = picked.groupby("sampling_stratum", sort=True).size().rename("sample_n")
    if not check.equals(strata_counts["sample_n"]):
        raise ValueError("SAMPLE_QUOTA_MISMATCH")
    exclusions = {
        "by_reason": counts(frame["exclusion_reason"]),
        "excluded_keys_sha256": hash_csv(frame.loc[frame["exclusion_reason"].ne("ELIGIBLE"),
                                      ["trade_date", "ts_code", "exclusion_reason"]].sort_values(["trade_date", "ts_code"]))
                                  if frame["exclusion_reason"].ne("ELIGIBLE").any() else None,
    }
    return picked.sort_values(["trade_date", "ts_code"], ignore_index=True), strata_counts, exclusions


def frame_payload(picked: pd.DataFrame, generation: dict, descriptor: dict, source: dict) -> pd.DataFrame:
    result = pd.DataFrame({
        "sample_id": (picked["ts_code"] + "\x00" + picked["trade_date"]).map(
            lambda key: sha256(key.encode()).hexdigest()),
        "stable_security_id": picked["ts_code"],
        "observation_date": picked["trade_date"],
        "exchange": picked["observation_exchange"],
        "panel_generation_id": generation["generation_id"],
        "panel_selector_sha256": source["selector_sha256"],
    })
    raw = descriptor.get("projection", {}).get("raw_lineage", {})
    for role in ("archive", "native"):
        def raw_sha(code):
            value = raw.get(code, {}).get(role, "")
            return value if SHA.fullmatch(value) else "UNKNOWN"
        result[f"generation_declared_raw_{role}_sha256"] = picked["ts_code"].map(raw_sha)
    result["raw_prefix_status"] = "NOT_EXTRACTED_GENERATION_SOURCE_HASHES_ONLY"
    result["panel_price_basis"] = generation["market_basis"]["A"]["price_basis"]
    result["panel_volume_basis"] = generation["market_basis"]["A"]["volume_basis"]
    result["panel_amount_basis"] = generation["market_basis"]["A"]["amount_basis"]
    result["security_identity_status"] = "PANEL_NATIVE_EXCHANGE_AND_SUFFIX_CONCORDANT"
    result["raw_bar_integrity_status"] = "UNKNOWN_RAW_PREFIX_NOT_EXTRACTED"
    result["exchange_calendar_status"] = "OBSERVED_D_MATCHES_BOUND_CALENDAR"
    result["suspension_status"] = "UNKNOWN_POSITIVE_TURNOVER_PANEL_PROXY_ONLY"
    result["corporate_action_pit_status"] = "UNKNOWN_PANEL_HISTORICAL_PIT_UNCERTIFIED"
    result["sector_pit_status"] = "UNKNOWN_LEGACY_STATIC_SNAPSHOT"
    result["cap_pit_status"] = "UNKNOWN_LEGACY_STATIC_SNAPSHOT"
    result["label_status"] = "UNKNOWN_NO_ADJUDICATION"
    result["fit_eligible"] = False
    cap_date = pd.to_datetime(picked["finance_source_date"].map(
        lambda value: f"{int(value):08d}" if np.isfinite(value) and value >= 0 else ""), format="%Y%m%d", errors="coerce")
    d = pd.to_datetime(picked["trade_date"], format="%Y%m%d")
    result["as_stored_finance_source_date"] = cap_date.dt.strftime("%Y%m%d").fillna("UNKNOWN")
    result["as_stored_finance_age_days"] = d.sub(cap_date).dt.days.astype("Int64")
    result["as_stored_finance_age_status"] = np.select(
        [cap_date.isna(), cap_date.gt(d)], ["UNKNOWN_SOURCE_DATE", "SOURCE_DATE_AFTER_D_NONPIT"],
        default="SOURCE_DATE_NOT_AFTER_D_PIT_UNCERTIFIED")
    passthrough = [
        "cap_tier_as_stored_nonpit", "industry_code_as_stored_nonpit", "volatility_tier_amplitude_D",
        "liquidity_tier_turnover_D", "market_regime_proxy", "native_buy_status", "native_breakout_status",
        "native_pullback_status", "research_sample_role", "previous_breakout_status", "previous_session_date",
        "previous_breakout_threshold", "attack_10d_state", "proxy_category", "sample_proxy_flags",
        "old_archive_scope_status", "old_archive_prior_conf_status", "old_archive_prior_expected_sessions_n",
        "old_archive_prior_covered_sessions_n", "sampling_stratum", "rank_within_stratum",
        "population_stratum_n", "selected_stratum_n", "inclusion_probability", "sha256_rank_key",
    ]
    result = pd.concat([result, picked[passthrough]], axis=1)
    result["exclusion_reason"] = "NONE_ELIGIBLE_FOR_RESEARCH_SAMPLING_ONLY"
    return result


def coverage_report(manifest: dict) -> str:
    m = manifest
    pop, sample = m["population"], m["sample"]
    source = m["source"]
    lines = [
        "# P5.15 R1.3 全A股连续非买点候选样本框", "",
        f"固定窗口为 **{pop['date_start']}–{pop['date_end']}**，覆盖同一 V4 面板中沪深北各 {pop['calendar_session_n']} 个连续交易日。",
        f"窗口中的有效身份母体为 **{pop['identity_rows']:,}** 个股票日、**{pop['identity_unique_security_n']:,}** 只证券，研究抽样资格母体 **{pop['eligible_rows']:,}** 行。",
        f"本轮抽取 **{sample['rows']:,}** 行、**{sample['unique_sec_n']:,}** 个证券代码。原生非买点标记为否的 {sample['native_buy_status'].get('FALSE',0):,} 行中，旧回放明确 CONF 的保留为 CONF 对照。",
        f"互斥研究角色分布为 {sample['research_sample_role']}。",
        f"按日分母、{sample['strata_n']:,} 个抽样层的 N_h/n_h 与排除原因见 `SAMPLE_FRAME_SOURCE_AND_PROBABILITY_R1_3.json`。同股跨日重复为股票日观察。", "",
        "## 来源与抽样", "",
        f"- 逻辑 Parquet 代次 `{source['generation_id']}`，selector SHA-256 `{source['selector_sha256']}`，代次回执 SHA-256 `{source['generation_receipt_sha256']}`。同一代原 reader 流式读取。",
        "- 复权口径为当前代 QFQ_ASOF，金额为 RAW_TURNOVER，成交量为 QFQ_EVENT_VOLUME。历史 PIT 未认证。母体按实际可见面板定义，交易所完整历史上市名单尚未比对。",
        "- 同一 V4 2026 日历，与旧回放逐交易所日期文件逐项比对。正成交量和成交额仅用于研究筛查，停牌、公司行动及历史 PIT 独立保留 UNKNOWN。D 特征和回看只用至 D，未读 T+2 结果。",
        "- 市值取面板静态存储值的当日三分位；行业沿用 TDX 静态存储行业代码，补样不填假行业或市值。观察时点真实市值与行业 PIT 状态均未认证，不能将静态值作为正式训练特征。",
        "- 主层为年月 × 交易所 × 静态存储市值三分位 × 主形态代理 × 旧回放当日 CONF、非 CONF 或未知。各非空层至少一行，其余容量按层比例分配。使用固定种子的 SHA-256 排序无放回选取，设计包含概率为 n_h/N_h。日期全集固定，概率以已绑定日历范围和实际资格母体为条件。",
        f"- 源字节 SHA 记录的是发布代的原始行情血缘，样本行分别保存 archive/native 元数据 SHA。缺 archive 引用 {sample['raw_archive_sha_unknown_n']:,} 行，缺 native 引用 {sample['raw_native_sha_unknown_n']:,} 行。行级 RAW 前缀尚未导出，需按证券与 D 使用已认证 RAW 来源查找并核对后才可转 H1 候选输入。",
        "- 旧买点只引用 38 日的 P5.14.3 冻结回放范围，精确按原证券与 D 连接。旧回放指出的北交所遗留别名，缺当日独立证券身份认证时排除。可核列为档内原 CONF 状态，覆盖边界为此档案及回放版本。", "",
        "## 覆盖", "",
        "| 交易所 | 连续交易日 | 有效身份母体行 | 资格母体行 | 抽样行 |", "|---|---:|---:|---:|---:|",
    ]
    for exchange in MARKETS:
        lines.append(f"| {exchange} | {pop['observed_sessions'][exchange]} | {pop['identity_rows_by_exchange'][exchange]:,} | "
                     f"{pop['eligible_rows_by_exchange'][exchange]:,} | {sample['by_exchange'][exchange]:,} |")
    lines.extend(["", "| 抽样类别 | 资格母体 | 样本 |", "|---|---:|---:|"])
    for name, actual in sample["by_proxy"].items():
        lines.append(f"| {name} | {pop['eligible_by_proxy'][name]:,} | {actual:,} |")
    lines.extend([
        "", "候选区分采用以下 D 日可计算条件，逐行保留命中的多个条件和一个主类别。", "",
        "- 普通反弹：D 涨幅至少 0.5%，收盘低于 MA20，原生突破为否。",
        "- 下跌中继：D 跌幅至少 1%，收盘低于 MA20，且 MA20 低于 MA60。",
        "- 假突破：D 日高点超此前 20 日高点至少 0.1%，同日收盘低于该前高至少 0.1%。",
        "- 突破失败：该股上一交易日有有效成交并收于此前 20 日高点的 100.1% 以上；D 日收低于上一日该突破基准的 99.9%。缺上一交易日则状态为 UNKNOWN。",
        "- 正常趋势整理：MA20 高于 MA60，收盘距 MA20 至多 2%，D 日振幅不超过 3%，原生突破为否。",
        "- 高位冲高回落：D 高点至少为此前 20 日高点的 98%，收盘落在当日区间下 35%，上影至少 2 个百分点。",
        "- 高位爆量：D 高点至少为此前 20 日高点的 98%，收盘位于含 D 20 日高点的 90% 以上，原面板金额/20 日基准至少 1.8，量/60 日基准至少 1.5。派发保持未确认。",
        "- 无明显攻击：含 D 的 10 个连续交易日均可观察，以原砖型攻击标记和收盘突破组合检查，无命中且 D 日原突破为否。缺任一交易日、必要价格或攻击标记则 UNKNOWN。",
        "- 强势股候选：D 涨幅至少 3%，收盘高于 MA20、MA20 高于 MA60、靠近 20 日高点且收在当日价格区间上 35%。失败股候选使用 D 跌幅至少 4%、收盘低于 MA20 且落在当日价格区间下 35%。两个类别都由截止 D 的形态定义。",
        "- 未进入旧 CONF：同日观察且原回放状态可追溯并明确非 CONF。更严格的可用子集同时要求此证券所有已归档的先前日期有明确记录、且无此前 CONF。",
        "",
        f"- 已知非 CONF 同日状态样本 {sample['old_archive_scope_status'].get('OBSERVED_NOT_CONF_IN_REPLAY_D',0):,} 行；其中完整档内先前覆盖且过去无 CONF 的联合子集 {sample['non_conf_today_and_prior_replay_observed_none']:,} 行。",
        f"- 抽中静态已知行业代码 {sample['industry_known_distinct_n']:,} 种，缺行业 {sample['industry_unknown_n']:,} 行。静态市值大中小及未知分别为 {sample['cap_tiers']}，市场环境分布为 {sample['regime']}。",
        f"- 资格排除逐项计数为 {m['exclusions']['by_reason']}。全源可见记录、身份排除、窗口内港股剔除、资格排除、基表隔离证券标识详见源与概率清单。",
        f"- 合成及正式标签均未写入本表。实际拟合与预测均为 0。CSV SHA-256 `{m['output']['csv_sha256']}`。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pointer", "reader", "calendar", "old-replay-root", "output-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    output_dir = args.output_dir
    if not output_dir.is_dir():
        raise ValueError("OUTPUT_DIRECTORY_DOES_NOT_EXIST")
    source_path, descriptor, contract, generation, bound = bind_source(args.pointer, args.reader)
    selector_sha = sha256(bound["anchor_bytes"]).hexdigest()
    if selector_sha != generation["candidate_sha256"]["selector"] or contract["asof_date"] != int(END):
        raise ValueError("SELECTOR_CONTENT_OR_DATE_NOT_BOUND")
    if generation["field_basis"]["tdx_industry_code"]["basis"] != "LEGACY_STATIC_CONTEXT":
        raise ValueError("UNEXPECTED_TDX_INDUSTRY_BASIS")
    sessions, calendar_info = calendar_sessions(args.calendar, args.old_replay_root)
    dates = [day for day in sessions if START <= day <= END]
    logical = bound["reader_module"].LogicalFile(source_path)
    if not set(COLUMNS).issubset(logical.schema_arrow.names):
        raise ValueError(f"REQUIRED_COLUMNS_MISSING:{set(COLUMNS) - set(logical.schema_arrow.names)}")
    source = {
        "generation_id": generation["generation_id"], "selector_sha256": selector_sha,
        "selector_pointer_sha256": sha256(bound["pointer_bytes"]).hexdigest(),
        "logical_reader_sha256": sha256_file(args.reader),
        "publication_journal_sha256": sha256_file(bound["journal_path"]),
        "generation_receipt_sha256": sha256(bound["manifest_bytes"]).hexdigest(),
        "selector_storage_layout": generation["storage_layout"], "logical_rows": descriptor["rows"],
        "block_count": len(descriptor["blocks"]), "published": bound["journal"]["status"],
        "declared_pit_certified": generation["pit_certified"], "a_share_market_basis": generation["market_basis"]["A"],
        "raw_generation_input_sha256": generation["input_sha256"],
        "raw_lineage_policy": "Symbol-level references bound by selector descriptor; this sample did not extract/re-hash row-level RAW prefixes.",
        "descriptor_excluded_securities": descriptor.get("excluded_symbols", []),
        "columns_read": COLUMNS,
    }
    frame, population_read = panel_window(logical, sessions)
    print(json.dumps({"status": "PANEL_WINDOW_PROJECTED", "rows": len(frame),
                      "elapsed_seconds": round(time.monotonic()-started, 2)}), file=sys.stderr, flush=True)
    raw_window = frame.loc[frame["trade_date"].ge(START)]
    observed_days = {}
    for exchange in MARKETS:
        market_dates = sorted(raw_window.loc[raw_window["observation_exchange"].eq(exchange), "trade_date"].unique())
        if market_dates != dates:
            raise ValueError(f"INCOMPLETE_CONTIGUOUS_PANEL_COVERAGE:{exchange}:{sorted(set(dates)-set(market_dates))}")
        observed_days[exchange] = len(market_dates)
    population_sorted = raw_window.sort_values(["trade_date", "ts_code"])
    population_source_sha = hash_csv(population_sorted[COLUMNS])
    key_sha = hash_csv(population_sorted[["trade_date", "ts_code"]])
    frame = geometry(frame, sessions)
    frame = frame.loc[frame["trade_date"].ge(START)].reset_index(drop=True)
    frame, old_meta = old_pool(frame, args.old_replay_root)
    picked, quotas, exclusions = sample_controls(frame)
    release = frame_payload(picked, generation, descriptor, source)
    if len(release) != release[["stable_security_id", "observation_date"]].drop_duplicates().shape[0]:
        raise ValueError("SAMPLE_SECURITY_DATE_DUPLICATE")
    if int(sum(quotas["population_n"])) != int(frame["exclusion_reason"].eq("ELIGIBLE").sum()):
        raise ValueError("POPULATION_STRATA_ACCOUNTING")
    if release["fit_eligible"].any() or len(release) != len(picked):
        raise ValueError("RESEARCH_GATE_VIOLATION")
    eligible = frame.loc[frame["exclusion_reason"].eq("ELIGIBLE")]
    if sha256_file(args.pointer) != source["selector_pointer_sha256"] or sha256_file(source_path) != selector_sha:
        raise ValueError("PANEL_SOURCE_CHANGED_DURING_READ")
    covered = {
        "date_start": START, "date_end": END, "calendar_session_n": len(dates), "calendar_sessions": dates,
        "identity_rows": len(frame), "identity_unique_security_n": int(frame["ts_code"].nunique()),
        "eligible_rows": len(eligible), "eligible_unique_security_n": int(eligible["ts_code"].nunique()),
        "observed_sessions": observed_days, "identity_rows_by_exchange": counts(frame["observation_exchange"]),
        "eligible_rows_by_exchange": counts(eligible["observation_exchange"]),
        "eligible_by_proxy": counts(eligible["proxy_category"]),
        "eligible_old_archive_scope_status": counts(eligible["old_archive_scope_status"]),
        "identity_rows_by_date": counts(frame["trade_date"]), "eligible_rows_by_date": counts(eligible["trade_date"]),
        "source_projection_sha256": population_source_sha, "identity_key_sha256": key_sha,
        "projection_digest_format": "UTF8 CSV header and LF rows sorted trade_date,ts_code, float %.17g; no source panel rewrite",
    }
    selected = {
        "rows": len(release), "by_exchange": counts(release["exchange"]), "strata_n": len(quotas),
        "native_buy_status": counts(release["native_buy_status"]), "by_proxy": counts(release["proxy_category"]),
        "research_sample_role": counts(release["research_sample_role"]),
        "unique_sec_n": int(release["stable_security_id"].nunique()),
        "old_archive_scope_status": counts(release["old_archive_scope_status"]),
        "cap_tiers": counts(release["cap_tier_as_stored_nonpit"]),
        "industry_known_distinct_n": int(release.loc[
            release["industry_code_as_stored_nonpit"].ne("UNKNOWN"), "industry_code_as_stored_nonpit"
        ].nunique()),
        "raw_archive_sha_unknown_n": int(release["generation_declared_raw_archive_sha256"].eq("UNKNOWN").sum()),
        "raw_native_sha_unknown_n": int(release["generation_declared_raw_native_sha256"].eq("UNKNOWN").sum()),
        "industry_unknown_n": int(release["industry_code_as_stored_nonpit"].eq("UNKNOWN").sum()),
        "regime": counts(release["market_regime_proxy"]), "volatility_tiers": counts(release["volatility_tier_amplitude_D"]),
        "liquidity_tiers": counts(release["liquidity_tier_turnover_D"]),
        "non_conf_today_and_prior_replay_observed_none": int(
            (release["native_buy_status"].eq("FALSE") & release["old_archive_scope_status"].eq("OBSERVED_NOT_CONF_IN_REPLAY_D")
             & release["old_archive_prior_conf_status"].eq("OBSERVED_NONE_IN_COMPLETE_PRIOR_REPLAY_WINDOW")).sum()),
        "all_adjudication_unknown": True, "formal_fit_eligible_n": 0,
    }
    csv_path = output_dir / "FULL_A_UNIVERSE_NEGATIVE_SAMPLE_FRAME.csv"
    report_path = output_dir / "SAMPLE_FRAME_COVERAGE_R1_3.md"
    manifest_path = output_dir / "SAMPLE_FRAME_SOURCE_AND_PROBABILITY_R1_3.json"
    if any(p.exists() for p in (csv_path, report_path, manifest_path)):
        raise FileExistsError("R1.3 outputs already exist; use another fresh artifact directory.")
    release_bytes = release.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode()
    manifest = {
        "schema": "p515.full_a_contiguous_negative_sample_frame/1", **RESEARCH,
        "created_by_script_sha256": sha256_file(Path(__file__)), "source": source,
        "calendar": calendar_info, "archive_old_buy_context": old_meta, "population_read": population_read,
        "population": covered, "exclusions": exclusions, "sample": selected,
        "sampling": {"seed": SEED, "target_n": TARGET, "stratum_denominators": {
            key: {"population_n": int(row.population_n), "sample_n": int(row.sample_n)}
            for key, row in quotas.iterrows()
        }, "probability": "design n_h/N_h; SHA-256 deterministic hash-priority within stratum",
        "scope": "Observed mainland A-share panel rows with SH/SZ/BJ native exchange identity; research exclusions applied.",
        "stratum_fields": ["month", "exchange", "as_stored_nonpit_cap_tier", "proxy_category", "archived_conf_context"]},
        "output": {"filename": csv_path.name, "csv_sha256": sha256(release_bytes).hexdigest(),
                   "bytes": len(release_bytes)},
        "execution": {"python": sys.version.split()[0], "pandas": pd.__version__, "pyarrow": pa.__version__,
                      "wall_seconds": round(time.monotonic()-started, 3),
                      "peak_rss_reported_bytes_mac": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
    }
    csv_path.write_bytes(release_bytes)
    report_path.write_text(coverage_report(manifest), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "population_rows": len(frame), "eligible_rows": len(eligible),
                      "days": len(dates), "sample": selected, "csv_sha256": manifest["output"]["csv_sha256"],
                      "manifest_sha256": sha256_file(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
