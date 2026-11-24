"""One-pass ACT039A Top200 diagnostics, bound to immutable predictions and pool keys."""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import resource
from collections import Counter
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as g
from ops import pft_act033a_replay as a33
from ops import pft_act034a_rules as r34
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36i
from ops import pft_act037a_inputs as a37i
from ops import pft_act038a_metrics as a38


OUT = a35.ROOT / "pft_act039a_top200_20261125"
SEAL = OUT / "TOP200_SELECTION_SEAL.json"
START = OUT / "METRICS_STARTED.json"
SUMMARY = OUT / "METRICS_SUMMARY.json"
CSV = OUT / "CODEX_MAC_ACT-039A_TOP200_STRATIFIED_METRICS_20261125.csv"
SCHEMA = "pft.act039a.top200_fixed_horizon_metrics.v1"
PREDICTION_SHA = "c482bbe36f1d7ce39146f1084c7137fb56b357fb443286400849ab8a54f60ace"
BASELINE_SHA = "21bdf2dbe8336012e151e521be2ecafd71b33c11c0971f62b5a47fed05368b26"
POOLS = ("TOP200_RET", "TOP200_PRODUCT")
MODES = ("BUYABLE", "THEORETICAL")
EXPOSURES = ("ALL_KEYS", "EXCLUDE_KNOWN_EXPOSURES")
HORIZONS = (1, 2, 3, 5)
TIER_LABELS = (*a38.TIERS, "HIGH_P_BORDERLINE_050_085", "NONE", "NULL")
PRED_STATUS = ("NOT_INFERRED_STRICT_OBSERVED_G1", "READY", "OTHER", "NULL")
BOARDS = ("MAIN_60_00", "CHINEXT", "STAR", "BJ")
THREE_STATES = ("TRUE", "FALSE", "NULL")
TACTIC_LABELS = (*a38.TACTICS, "OTHER", "NULL")
PRIMARY_DIMENSIONS = frozenset(("S_DECISION_STATE", "PREDICTION_STATUS", "EARLY_BORDERLINE_TIER",
                                "MAIN_TACTIC", "BEST_CANDIDATE_TACTIC", "CUSHION_PCT", "ANCHOR_AGE_SESSIONS",
                                "REPAIR_AGE", "STRICT_G1_FAILURE", "BOARD", "IS_ST"))
HEADLINE_CI = frozenset((("S_DECISION_STATE", "CONFIRMED_S"), ("S_DECISION_STATE", "UNKNOWN_P_GE_085"),
                         *(("EARLY_BORDERLINE_TIER", leaf) for leaf in a38.TIERS[:2]),
                         ("STRICT_G1_FAILURE", "FALSE"),
                         *((dimension, tactic) for dimension in ("MAIN_TACTIC", "BEST_CANDIDATE_TACTIC",
                              "MAIN_TACTIC_IN_CONFIRMED_S", "BEST_CANDIDATE_TACTIC_IN_UNKNOWN_BORDERLINE")
                           for tactic in a38.TACTICS)))
FEE, TAIL, CUTOFF = a38.FEE, a38.TAIL, a38.CUTOFF
MAX_BYTES = 9_500_000
POLICY = {
    "entry": "D+1 in verified 11/23-cutoff QFQ open basis. BUYABLE requires ACT038 same observed standard-cap proxy. THEORETICAL includes separately verified prices at known cap or with unresolved cap disposition. Missing/suspended/no-volume prices remain unpriced.",
    "target": "Horizon h is signal-relative exchange session D+h close in same QFQ basis. T+1 O2C is a price mark only under mainland T+1 rules. All lower-cap marks are measured as prices, with executable status separate. Last observed session 20261123.",
    "sources": "Prefer dated official G4DAY packages. Use ACT038 whole-date V4 inverse-affine archive proxy only when no official package. No cross-date ST transfer or partial official fallback.",
    "decision_state": "Use the exact frozen s_decision_state for every matched pool row, including any legacy UNKNOWN context stub. Stratify prediction disposition separately and in cross-cells. Null state includes explicit unmatched forecast rows.",
    "chinext_302": "Primary outcomes preserve ACT038 admission and benchmark parity. Audit 302.SZ entry and marked-close decisions independently with the confirmed ChiNext 20% board band in the same pass, without modifying primary labels or retuning.",
    "comparison": "Within each pool and D/h, all its buyable marks form the Top200 comparator. Both pools and entry modes use the same D-proven ACT038 full-A buyable comparator. Pure sensitivity excludes only exact known exposure keys from all numerators and comparator denominators without reranking; unmatched unknown exposure stays included.",
    "fee": FEE,
    "pure_tail_inclusive_net": TAIL,
    "go": "T+5 BUYABLE TOP200_RET with ALL_KEYS only. Completed marks >=100. Criterion one: pooled matched gain >=1pp, early and dev both positive, lower bound of paired 95% interval >0. Criterion two: pooled matched tail gap <=-3pp, early and dev both negative, upper bound <0. Each criterion assessed independently.",
    "inference": "4,000 draws, seed 3511, 5 consecutive original exchange-session block indices. Resample paired daily numerator and eligible group's mark-count denominator together. Empty pairs are excluded from the ratio. Intervals are descriptive and unadjusted for multiple groups.",
}


def require(ok, why):
    if not ok:
        raise a31.ContractError(f"ACT039A_METRICS_{why}")


def load_pool(seal_sha, dates):
    require(re.fullmatch(r"[0-9a-f]{64}", seal_sha), "EXPECTED_SEAL_SHA_REQUIRED")
    ref = {"path": str(SEAL), "sha256": seal_sha}
    seal = a31.read_ref(ref)
    require(seal["phase"] == "TOP200_SELECTION_SEALED" and seal["signal_dates"] == dates
            and seal["outcomes_opened"] is False, "POOL_SEAL_SCOPE")
    frames = []
    for source in seal["files"]:
        file = a33.checked(source)
        require(file.parent.is_relative_to(OUT) and file.suffix == ".parquet"
                and file.stat().st_size == source["bytes"] <= MAX_BYTES, "POOL_SHARD_IDENTITY")
        frame = pd.read_parquet(file)
        require(len(frame) == source["rows"] and sorted(frame.trade_date.unique()) == sorted(source["dates"]),
                "POOL_SHARD_COVERAGE")
        frames.append(frame)
    frame = pd.concat(frames, ignore_index=True).sort_values(["pool", "trade_date", "D_rank", "ts_code"])
    require(frame.pool.isin(POOLS).all() and frame.trade_date.isin(dates).all()
            and frame.ts_code.map(a31.a_share_instrument_rejection).isna().all()
            and not frame.duplicated(["pool", "trade_date", "ts_code"]).any()
            and frame.D_rank.between(1, 200).all()
            and not frame.duplicated(["pool", "trade_date", "D_rank"]).any(), "POOL_KEY_OR_RANK_DRIFT")
    require(frame.board.isin(BOARDS).all() and frame.board.eq("MAIN_60_00").eq(frame.ts_code.map(g.main_board)).all()
            and frame.s_decision_state.dropna().isin(a38.STATES[:3]).all(), "BOARD_OR_STATE_DRIFT")
    forecasts = frame.loc[frame.model_version.notna()]
    require(forecasts.model_version.eq("S_V3.0_FROZEN").all() and forecasts.model_commit.eq("fc528d9da0d6").all()
            and forecasts.train_cutoff_date.eq("20260831").all() and forecasts.is_strict_oos_post_cutoff.eq(True).all(),
            "MODEL_OR_OOS_DRIFT")
    return frame, ref, seal


def chinext_302_assessment(code, quote):
    """Compare corrected ChiNext caps without mutating the inherited primary tape."""
    legacy = a38.quote_assessments(code, quote)
    if (not (code.startswith("302") and code.endswith(".SZ")) or not quote["eligible_for_daily_gain_rank"]
            or quote.get("dated_st") is True
            or (quote["quote_evidence"] == a36i.OFFICIAL and quote.get("dated_st") is None)):
        return legacy
    previous = a31.positive(quote.get("prev_close"))
    if previous is None:
        return legacy
    upper = r34.cap_price(previous, Decimal("1.20"))
    floor = r34.cap_price(previous, Decimal(".80"))
    opened = quote["open"]
    if opened > upper + 1e-6:
        buy, buy_status = None, "CANNOT_CONFIRM_D1_CAP_EXCEPTION"
    elif opened >= upper - 1e-6:
        buy, buy_status = False, "STANDARD_CAP_AT_OPEN"
    else:
        buy, buy_status = True, "STANDARD_CAP_MODELED_OPEN"
    tag = "DIAGNOSTIC" if quote["quote_evidence"] == a36i.PROXY else "EXIT"
    if quote["low"] < floor - 1e-6:
        sell, sell_status = None, f"{tag}_STANDARD_CAP_EXCEPTION"
    elif quote["close"] <= floor + 1e-6:
        sell, sell_status = False, f"{tag}_CLOSE_AT_LOWER_CAP"
    else:
        sell, sell_status = True, f"{tag}_MODELED_CLOSE"
    return buy, buy_status, sell, sell_status


def execution_tape(sources, dates):
    """Use ACT038 quote and affine owners; keep verified at-cap opens for theory."""
    bound = a37i.bound(sources, CUTOFF)
    calendar = sources.calendar
    first_entry = calendar[calendar.index(dates[0]) + 1]
    history = a36i.read_history(bound, first_entry, CUTOFF, columns=a38.HISTORY_COLUMNS)
    require(sorted(history.trade_date.unique()) == calendar[calendar.index(first_entry):calendar.index(CUTOFF) + 1]
            and not history.duplicated(["trade_date", "ts_code"]).any(), "OUTCOME_V4_PROJECTION_DRIFT")
    basis = a36i.Basis(bound)
    events = {}
    for code in history.ts_code.unique():
        ledger = bound.symbols.get(code, {})
        first = str(ledger.get("history_start_date") or first_entry)
        events[code] = first, r34.affine_events(ledger, max(first_entry, first))
    tape, receipts, band_audit = {}, {}, {}
    for day, bars in history.groupby("trade_date", sort=True):
        if day in sources.quotes:
            official, reference = sources.quotes[day]
        else:
            official, reference = a31.day_quotes(day, sources.prior.inputs["days"][day])
        quotes, mode = a36i.quotes_for_day(bars, day, basis, official)
        snapshots = bars.set_index("ts_code").to_dict("index")
        rows, price_quality = [], Counter()
        for code, quote in quotes.items():
            first, ledger = events.get(code, (day, None))
            prices, quality = r34.verified_bar(snapshots.get(code), quote, day, ledger if first <= day else None)
            buy, buy_reason, sell, sell_reason = a38.quote_assessments(code, quote)
            rows.append((code, buy, buy_reason, prices.get("open"), prices.get("close"), sell, sell_reason,
                         r34.raw_ratio(quote, "open", "prev_close"), quote.get("dated_st")))
            if code.startswith("302") and code.endswith(".SZ"):
                new_buy, new_reason, new_sell, new_sell_reason = chinext_302_assessment(code, quote)
                band_audit[day, code] = {"trade_date": day, "ts_code": code, "quote_source": mode,
                                         "dated_st": quote.get("dated_st"), "raw_open": quote.get("open"),
                                         "raw_pre_close": quote.get("prev_close"), "open_gap": r34.raw_ratio(quote, "open", "prev_close"),
                                         "verified_open": prices.get("open"), "verified_close": prices.get("close"),
                                         "legacy_buyable": buy, "legacy_buy_status": buy_reason, "nominal_20pct_buyable": new_buy,
                                         "nominal_20pct_buy_status": new_reason, "legacy_exit_cap_clear": sell,
                                         "legacy_exit_status": sell_reason, "nominal_20pct_exit_cap_clear": new_sell,
                                         "nominal_20pct_exit_status": new_sell_reason}
            price_quality[quality] += 1
        table = pd.DataFrame(rows, columns=("ts_code", "buyable", "entry_status", "open_basis", "close_basis",
                                            "exit_cap_clear", "exit_status", "open_gap", "dated_st")).set_index("ts_code")
        tape[day] = table
        receipts[day] = {"source": mode, "official_receipt": reference, "quote_n": len(table),
                         "price_quality_counts": dict(price_quality)}
    return tape, receipts, band_audit, {"identity": bound.identity, "bounds": [first_entry, CUTOFF], "row_n": len(history),
                                        "symbol_n": history.ts_code.nunique(), "projection_bytes": int(history.memory_usage(deep=True).sum())}


def marks(codes, day, h, calendar, tape, receipts):
    idx = calendar.index(day)
    d1, end = calendar[idx + 1], calendar[idx + h]
    entry = tape[d1].reindex(codes)
    mature = end <= CUTOFF
    opening = entry.open_basis.to_numpy(dtype=float, na_value=np.nan)
    status = entry.entry_status.fillna("ENTRY_QUOTE_MISSING").to_numpy()
    buy = entry.buyable.eq(True).to_numpy()
    blocked = entry.buyable.eq(False).to_numpy()
    quotes = "RIGHT_CENSORED"
    target = np.full(len(codes), np.nan)
    sell_clear, sell_blocked = np.zeros(len(codes), dtype=bool), np.zeros(len(codes), dtype=bool)
    sell_reason = np.full(len(codes), "RIGHT_CENSORED", dtype=object)
    if mature:
        exit_book = tape[end].reindex(codes)
        target = exit_book.close_basis.to_numpy(dtype=float, na_value=np.nan)
        sell_clear, sell_blocked = exit_book.exit_cap_clear.eq(True).to_numpy(), exit_book.exit_cap_clear.eq(False).to_numpy()
        sell_reason = exit_book.exit_status.fillna("EXIT_QUOTE_MISSING").to_numpy()
        quotes = ("OFFICIAL_BOTH_LEGS" if all(receipts[date]["source"] == a36i.OFFICIAL for date in (d1, end))
                  else "HAS_ARCHIVE_PROXY_LEG")
    realized = np.isfinite(opening) & np.isfinite(target)
    values = np.divide(target, opening, where=realized, out=np.full(len(codes), np.nan)) - 1. - FEE
    return pd.DataFrame({"entry_date": d1, "target_date": end, "mature": mature, "quote_tier": quotes,
                         "entry_buyable": buy, "entry_blocked": blocked, "entry_status": status,
                         "entry_price": opening, "target_price": target, "exit_clear": sell_clear,
                         "exit_blocked": sell_blocked, "exit_status": sell_reason,
                         "entry_open_gap": entry.open_gap.to_numpy(), "entry_dated_st": entry.dated_st.to_numpy(),
                         "net_theoretical": values, "net_buyable": np.where(buy, values, np.nan)})


def return_profile(values):
    values = np.asarray(values)
    valid = values[np.isfinite(values)]
    n = len(valid)
    return n, float(valid.mean()) if n else None, float((valid <= TAIL + r34.EPS).mean()) if n else None


def chinext_302_impact(pool, export, calendar, audit):
    outputs = {}
    subsets = {name: pool.loc[pool.pool.eq(name), ["trade_date", "ts_code"]] for name in POOLS}
    subsets["ALL_A"] = export.loc[export.membership_source.isin(a38.DATED_MEMBERSHIP), ["trade_date", "ts_code"]]
    for pool_name, data in subsets.items():
        changes, counts = [], Counter()
        codes = data.ts_code.str.startswith("302") & data.ts_code.str.endswith(".SZ")
        for d, code in data.loc[codes].itertuples(index=False, name=None):
            i = calendar.index(d)
            entry = audit.get((calendar[i + 1], code))
            counts["signal_keys"] += 1
            if entry is None:
                counts["entry_quote_missing_n"] += 1
                continue
            counts["entry_quote_compared_n"] += 1
            changed = entry["legacy_buyable"] is not entry["nominal_20pct_buyable"]
            mark_change = {"signal_date": d, **entry, "matched_horizon_count_delta": {}}
            counts["entry_proxy_state_changed_n"] += changed
            for h in HORIZONS:
                target = audit.get((calendar[i + h], code))
                if target is None or entry["verified_open"] is None or target["verified_close"] is None:
                    continue
                legacy_mark = entry["legacy_buyable"] is True
                corrected_mark = entry["nominal_20pct_buyable"] is True
                counts[f"h{h}_verified_price_pairs_n"] += 1
                counts[f"h{h}_primary_buyable_marks_n"] += legacy_mark
                counts[f"h{h}_alternate_buyable_marks_n"] += corrected_mark
                counts[f"h{h}_exit_cap_state_changed_n"] += (legacy_mark and
                    target["legacy_exit_cap_clear"] is not target["nominal_20pct_exit_cap_clear"])
                if legacy_mark != corrected_mark:
                    mark_change["matched_horizon_count_delta"][str(h)] = int(corrected_mark) - int(legacy_mark)
                    mark_change[f"h{h}_net_if_nominal20_price"] = target["verified_close"] / entry["verified_open"] - 1. - FEE
            if changed:
                changes.append(mark_change)
        outputs[pool_name] = {"counts": dict(counts), "entry_changed_rows": changes}
    return outputs


def full_benchmarks(export, dates, calendar, tape, receipts, known, original):
    oracle = {(row["trade_date"], row["horizon"]): row for row in original["daily_benchmarks"]}
    books, parity, known_keys_by_date = {}, [], {}
    for day, group in export.groupby("trade_date", sort=True):
        codes = group.loc[group.membership_source.isin(a38.DATED_MEMBERSHIP), "ts_code"].tolist()
        not_exposed = np.array([(day, code) not in known for code in codes], dtype=bool)
        known_keys_by_date[day] = int((~not_exposed).sum())
        for h in HORIZONS:
            row = marks(codes, day, h, calendar, tape, receipts)
            values = row.net_buyable.to_numpy()
            entire = return_profile(values)
            pure = return_profile(values[not_exposed])
            books[day, h] = {"ALL_KEYS": entire, "EXCLUDE_KNOWN_EXPOSURES": pure}
            if h in a38.HORIZONS:
                frozen = oracle[day, h]
                n, mean, _ = entire
                same = mean == frozen["benchmark_net_mean"] if mean is None else (
                    frozen["benchmark_net_mean"] is not None and abs(mean - frozen["benchmark_net_mean"]) <= 1e-14)
                require(n == frozen["benchmark_n"] and same and row.quote_tier.iat[0] == frozen["quote_tier"],
                        f"ACT038_BENCHMARK_PARITY:{day}:{h}")
                parity.append((day, h))
    require(len(parity) == len(dates) * 3, "ACT038_BENCHMARK_PARITY_COVERAGE")
    return books, parity, known_keys_by_date


def cohort_masks(frame):
    state = frame.s_decision_state.astype("string").fillna("NULL_MISSING")
    status = frame.prediction_status.astype("string")
    status = status.where(status.isna() | status.isin(PRED_STATUS[:2]), "OTHER").fillna("NULL")
    tier = frame.early_borderline_tier.astype("string").fillna("NULL")
    masks = {("COHORT", "ALL"): np.ones(len(frame), dtype=bool)}

    def partition(dimension, values, labels):
        for label in labels:
            masks[dimension, label] = values.eq(label)

    partition("S_DECISION_STATE", state, a38.STATES)
    partition("PREDICTION_STATUS", status, PRED_STATUS)
    partition("EARLY_BORDERLINE_TIER", tier, TIER_LABELS)
    masks["S_DECISION_STATE", "UNKNOWN_P_GE_085"] = state.eq("UNKNOWN_BORDERLINE") & frame.projected_p_s.ge(.85)
    for key, label in (("main_tactic", "MAIN_TACTIC"), ("best_candidate_tactic", "BEST_CANDIDATE_TACTIC")):
        tactics = frame[key].astype("string").str.upper().str.removeprefix("S_").radd("S_")
        tactics = tactics.where(tactics.isna() | tactics.isin(a38.TACTICS), "OTHER").fillna("NULL")
        partition(label, tactics, TACTIC_LABELS)
        verdict = "CONFIRMED_S" if key == "main_tactic" else "UNKNOWN_BORDERLINE"
        for child in a38.TACTICS:
            masks[f"{label}_IN_{verdict}", child] = state.eq(verdict) & tactics.eq(child)
    for label in a38.STATES:
        for disposition in PRED_STATUS:
            masks["STATE_BY_PREDICTION_STATUS", f"{label}|{disposition}"] = state.eq(label) & status.eq(disposition)
    partition("BOARD", frame.board, BOARDS)
    masks["BOARD", "NON_MAIN"] = frame.board.ne("MAIN_60_00")
    for name, label in (("is_st", "IS_ST"), ("D_is_st", "D_DATED_IS_ST"), ("strict_g1_failure", "STRICT_G1_FAILURE")):
        values = frame[name].map({True: "TRUE", False: "FALSE"}).fillna("NULL")
        partition(label, values, THREE_STATES)
    cushion = frame.cushion_pct
    for label, low, high in (("LT_0", None, 0.), ("GE_0_LT_005", 0., .05), ("GE_005_LT_012", .05, .12),
                             ("GE_012_LT_020", .12, .20), ("GE_020", .20, None)):
        meets = cushion.notna()
        if low is not None:
            meets &= cushion.ge(low)
        if high is not None:
            meets &= cushion.lt(high)
        masks["CUSHION_PCT", label] = meets
    masks["CUSHION_PCT", "NULL"] = cushion.isna()
    for name, label in (("anchor_age_sessions", "ANCHOR_AGE_SESSIONS"), ("repair_age", "REPAIR_AGE")):
        age = frame[name]
        masks.update({(label, "LT_4"): age.lt(4), (label, "GE_4_LE_10"): age.between(4, 10),
                      (label, "GT_10"): age.gt(10), (label, "NULL"): age.isna()})
    return {key: pd.array(mask, dtype="boolean").to_numpy(dtype=bool, na_value=False) for key, mask in masks.items()}


def group_window_masks(dates, early, dev, pool_dates, product_dates, pool):
    result = {"ALL_53D": dates, "OOT_EARLY": early, "DEV_21D": dev}
    windows = {window: (calendar, {d for d in calendar if d in pool_dates}) for window, calendar in result.items()}
    if pool == POOLS[0]:
        observed = sorted(product_dates & pool_dates)
        chronology = dates[dates.index(observed[0]):dates.index(observed[-1]) + 1] if observed else []
        windows["PRODUCT_MATCHED_DAYS"] = chronology, set(observed)
    return windows


def bootstrap_indices(dates):
    n = len(dates)
    block, draws = a35.BLOCK_SESSIONS, a35.N_BOOTSTRAP
    if n < block:
        return None
    rng = np.random.default_rng(a35.SEED)
    starts = rng.integers(0, n - block + 1, (draws, (n + block - 1) // block))
    return (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :n]


def paired_ratio(terms, totals, indices):
    n_days = int((totals > 0).sum())
    effect = a38.safe(terms.sum(), totals.sum())
    if indices is None or n_days < a35.BLOCK_SESSIONS:
        return effect, None, None, 0
    denominator = totals[indices].sum(axis=1)
    numerator = terms[indices].sum(axis=1)
    usable = denominator > 0
    values = numerator[usable] / denominator[usable]
    bounds = np.quantile(values, [.025, .975]).tolist() if len(values) else [None, None]
    return effect, *bounds, len(values)


def split_outcomes(frame, h, calendar, tape, receipts, known):
    parts = []
    for day, group in frame.groupby("trade_date", sort=True):
        group = group.reset_index(drop=True)
        observed = marks(group.ts_code.tolist(), day, h, calendar, tape, receipts)
        observed["exact_known_exposure"] = [(day, code) in known for code in group.ts_code]
        parts.append(pd.concat((group, observed), axis=1))
    if parts:
        return pd.concat(parts, ignore_index=True)
    empty = marks([], calendar[calendar.index(a38.FIRST)], h, calendar, tape, receipts)
    empty["exact_known_exposure"] = pd.Series([], dtype=bool)
    return pd.concat((frame.reset_index(drop=True), empty), axis=1)


def day_books(frame):
    return {d: return_profile(group.net_buyable) for d, group in frame.groupby("trade_date", sort=True)}


def differences(daily, benchmark, chronology, indices):
    ordinals = {day: index for index, day in enumerate(chronology)}
    n = np.zeros(len(chronology), dtype=np.int64)
    net = np.zeros(len(chronology))
    tail = np.zeros(len(chronology))
    for day, stats in daily:
        base_n, base_mean, base_tail = benchmark.get(day, (0, None, None))
        if base_n:
            pos = ordinals[day]
            n[pos] = len(stats)
            net[pos] = float((stats - base_mean).sum())
            tail[pos] = float((stats <= TAIL + r34.EPS).sum()) - len(stats) * base_tail
    net_mean, net_low, net_high, valid = paired_ratio(net, n, indices)
    tail_mean, tail_low, tail_high, _ = paired_ratio(tail, n, indices)
    return {"mark_n": int(n.sum()), "days": int((n > 0).sum()), "net": net_mean, "net_low_95": net_low,
            "net_high_95": net_high, "tail": tail_mean, "tail_low_95": tail_low, "tail_high_95": tail_high,
            "valid_bootstrap_draws": valid}


def summarize_slice(frame, mode, topology, chronology, active_dates, mature_dates, pool_book, full_book, ci_indices):
    value_col = f"net_{mode.lower()}"
    values = frame[value_col].to_numpy(dtype=float, na_value=np.nan)
    valid = np.isfinite(values)
    opens = frame.entry_price.notna().to_numpy()
    buyable, blocked = frame.entry_buyable.to_numpy(dtype=bool), frame.entry_blocked.to_numpy(dtype=bool)
    mature = frame.mature.to_numpy(dtype=bool)
    exit_lower_cap = frame.exit_status.str.contains("AT_LOWER_CAP", regex=False).to_numpy(dtype=bool)
    eligible_open = opens & buyable if mode == "BUYABLE" else opens
    known = values[valid]
    dec = int(len(frame))
    n = len(known)
    require(int(eligible_open.sum()) == n + int((eligible_open & ~mature).sum())
            + int((eligible_open & mature & ~valid).sum()), "GROUP_MARK_CONSERVATION")
    official = frame.quote_tier.eq("OFFICIAL_BOTH_LEGS").to_numpy()
    proxy = frame.quote_tier.eq("HAS_ARCHIVE_PROXY_LEG").to_numpy()
    daily = [(d, p[value_col].to_numpy(dtype=float)) for d, p in frame.loc[valid].groupby("trade_date", sort=False)]
    effects = {f"{owner}_{k}": v for owner, comparator in (("pool_buyable", pool_book), ("all_a_buyable", full_book))
               for k, v in differences(daily, comparator, chronology, ci_indices).items()}
    lower = int((valid & exit_lower_cap).sum())
    wins = int((known > 0.).sum())
    tails = int((known <= TAIL + r34.EPS).sum())
    return {
        "span_session_days": len(chronology), "pool_available_days": len(active_dates),
        "cohort_signal_days": frame.trade_date.nunique(), "pool_mature_days": len(mature_dates),
        "pool_right_censored_days": len(active_dates) - len(mature_dates), "marked_days": len(daily),
        "signal_keys": dec, "prediction_unmatched_n": int(frame.prediction_join_status.eq("UNMATCHED").sum()),
        "known_exposure_remaining_n": int(frame.exact_known_exposure.sum()),
        "exposure_unknown_n": int(frame.known_previously_exposed.isna().sum()), **topology,
        "entry_known_buyable_n": int(buyable.sum()), "entry_known_blocked_n": int(blocked.sum()),
        "entry_unknown_n": int((~buyable & ~blocked).sum()),
        "entry_blocked_rate": a38.safe(blocked.sum(), dec),
        "entry_at_upper_cap_n": int(frame.entry_status.eq("STANDARD_CAP_AT_OPEN").sum()),
        "verified_open_price_n": int(opens.sum()), "verified_buyable_open_n": int((opens & buyable).sum()),
        "upper_cap_theoretical_marks_n": int((valid & frame.entry_status.eq("STANDARD_CAP_AT_OPEN").to_numpy()).sum()) if mode == "THEORETICAL" else 0,
        "right_censored_keys": int((~mature).sum()), "right_censored_verified_entries_n": int((eligible_open & ~mature).sum()),
        "mature_missing_close_mark_n": int((eligible_open & mature & ~valid).sum()),
        "mark_n": n, "net_mean": float(known.mean()) if n else None, "net_median": float(np.median(known)) if n else None,
        "net_win_n": wins, "net_win_rate": a38.safe(wins, n), "pure_tail_n": tails,
        "pure_tail_rate": a38.safe(tails, n), "exit_lower_cap_mark_n": lower, "exit_lower_cap_mark_rate": a38.safe(lower, n),
        "exit_cap_clear_mark_n": int((valid & frame.exit_clear.to_numpy(dtype=bool)).sum()),
        "exit_cap_unknown_mark_n": int((valid & ~frame.exit_clear.to_numpy(dtype=bool) & ~frame.exit_blocked.to_numpy(dtype=bool)).sum()),
        "official_mark_n": int((valid & official).sum()), "proxy_mark_n": int((valid & proxy).sum()),
        "official_net_mean": float(values[valid & official].mean()) if (valid & official).any() else None,
        "proxy_net_mean": float(values[valid & proxy].mean()) if (valid & proxy).any() else None, **effects,
    }


def go_screen(rows):
    accepted = []
    primary = {(r["window"], r["dimension"], r["level"]): r for r in rows
               if r["pool"] == POOLS[0] and r["measure"] == "BUYABLE" and r["exposure_scope"] == EXPOSURES[0]
               and r["horizon"] == 5 and r["dimension"] in PRIMARY_DIMENSIONS}
    for (window, dimension, level), row in primary.items():
        if window != "ALL_53D":
            continue
        early, dev = [primary[split, dimension, level] for split in ("OOT_EARLY", "DEV_21D")]
        enough = row["mark_n"] >= 100
        net, tail = row["pool_buyable_net"], row["pool_buyable_tail"]
        net_ci, tail_ci = row["pool_buyable_net_low_95"], row["pool_buyable_tail_high_95"]
        split_net = [r["pool_buyable_net"] for r in (early, dev)]
        split_tail = [r["pool_buyable_tail"] for r in (early, dev)]
        net_pass = (enough and net is not None and net >= .01 and net_ci is not None and net_ci > 0.
                    and all(x is not None and x > 0. for x in split_net))
        tail_pass = (enough and tail is not None and tail <= -.03 and tail_ci is not None and tail_ci < 0.
                     and all(x is not None and x < 0. for x in split_tail))
        control = (dimension in ("BOARD", "IS_ST", "PREDICTION_STATUS")
                   or level in ("NULL", "NULL_MISSING", "OTHER"))
        row.update({"go_leaf_kind": "NONMODEL_CONTROL" if control else "MODEL_STRATUM",
                    "go_screen": "CONTROL_PASS" if control and (net_pass or tail_pass) else
                                 "MODEL_PASS" if net_pass or tail_pass else
                                 "BELOW_100_MARKS" if not enough else "NO_GO",
                    "go_matched_net_pass": net_pass, "go_pure_tail_pass": tail_pass,
                    "go_early_net": split_net[0], "go_dev_net": split_net[1],
                    "go_early_tail": split_tail[0], "go_dev_tail": split_tail[1]})
        if net_pass or tail_pass:
            accepted.append(row)
    return accepted


ANOMALY_FIELDS = (
    "pool", "trade_date", "ts_code", "D_rank", "D_name", "D_return", "D_return_source", "board", "D_is_st",
    "D_close_at_upper_cap", "D_cap_status", "prediction_join_status", "s_decision_state", "prediction_status",
    "main_tactic", "best_candidate_tactic", "projected_p_s", "raw_p_s", "early_borderline_tier", "is_st",
    "cushion_pct", "anchor_age_sessions", "repair_age", "strict_g1_failure", "route_reasons", "missing_reason",
    "known_previously_exposed", "entry_date", "target_date", "entry_open_gap", "entry_status", "exit_status",
    "quote_tier", "entry_price", "target_price", "net_buyable", "net_theoretical",
)


def anomaly_rows(frame):
    valid = frame.loc[frame.net_buyable.notna()]
    hi_unknown = valid.s_decision_state.eq("UNKNOWN_BORDERLINE") & valid.projected_p_s.ge(.85)
    studies = (
        ("CONFIRMED_S_WORST", valid.loc[valid.s_decision_state.eq("CONFIRMED_S") & valid.net_buyable.le(TAIL + r34.EPS)], "net_buyable", True),
        ("UNKNOWN_P_GE_085_BEST", valid.loc[hi_unknown & valid.net_buyable.gt(0.)], "net_buyable", False),
        ("EXT1_WORST", valid.loc[valid.early_borderline_tier.eq(a38.TIERS[0])], "net_buyable", True),
        ("EXT3_BEST", valid.loc[valid.early_borderline_tier.eq(a38.TIERS[1])], "net_buyable", False),
        ("READVANCE_WORST", valid.loc[valid.best_candidate_tactic.str.lower().eq("readvance") & valid.net_buyable.le(TAIL + r34.EPS)], "net_buyable", True),
        ("UPPER_CAP_THEORETICAL_BEST", frame.loc[frame.entry_status.eq("STANDARD_CAP_AT_OPEN") & frame.net_theoretical.notna()], "net_theoretical", False),
    )
    output = []
    for label, subset, col, ascending in studies:
        ordered = subset.sort_values([col, "trade_date", "ts_code"], ascending=[ascending, True, True]).head(2)
        for sample in ordered.loc[:, list(ANOMALY_FIELDS)].to_dict("records"):
            output.append({"example": label, "horizon": 5, **a35.clean_record(sample)})
    return output


def aggregate(pool_frame, dates, early, dev, calendar, tape, receipts, full_books, full_exposed, known):
    product_days = set(pool_frame.loc[pool_frame.pool.eq(POOLS[1]), "trade_date"])
    rows, anomalies, comparator_proof, purity = [], [], [], []
    for pool in POOLS:
        pool_rows = pool_frame.loc[pool_frame.pool.eq(pool)]
        pool_days = set(pool_rows.trade_date)
        windows = group_window_masks(dates, early, dev, pool_days, product_days, pool)
        for h in HORIZONS:
            completed = split_outcomes(pool_rows, h, calendar, tape, receipts, known)
            if h == 5:
                anomalies.extend(anomaly_rows(completed))
            for exposure in EXPOSURES:
                included = completed if exposure == EXPOSURES[0] else completed.loc[~completed.exact_known_exposure]
                pool_book = day_books(included)
                full_book = {d: full_books[d, h][exposure] for d in dates}
                comparator_proof.extend({"pool": pool, "horizon": h, "exposure_scope": exposure, "trade_date": d,
                                         "pool_buyable_n": vals[0], "pool_buyable_net_mean": vals[1],
                                         "pool_buyable_tail_rate": vals[2]} for d, vals in pool_book.items())
                for window, (chronology, active_dates) in windows.items():
                    group = included.loc[included.trade_date.isin(active_dates)]
                    original = completed.loc[completed.trade_date.isin(active_dates)]
                    mature_dates = {d for d in active_dates if calendar[calendar.index(d) + h] <= CUTOFF}
                    topology = {"pool_rows_before_exposure_filter": len(original),
                                "pool_exact_exposure_removed_n": len(original) - len(group),
                                "pool_unmatched_retained_n": int(group.prediction_join_status.eq("UNMATCHED").sum()),
                                "full_a_exposure_keys_removed_n": sum(full_exposed[d] for d in active_dates) if exposure == EXPOSURES[1] else 0,
                                "full_a_verified_marks_exposure_removed_n": sum(full_books[d, h][EXPOSURES[0]][0] -
                                     full_books[d, h][exposure][0] for d in active_dates)}
                    if exposure == EXPOSURES[1]:
                        purity.append({"pool": pool, "horizon": h, "window": window, **topology})
                    masks = cohort_masks(group)
                    indices = bootstrap_indices(chronology)
                    for mode in MODES:
                        for (dimension, level), mask in masks.items():
                            slice_ = group.loc[mask]
                            primary_leaf = (pool == POOLS[0] and h == 5 and exposure == EXPOSURES[0]
                                            and mode == "BUYABLE" and window == "ALL_53D"
                                            and dimension in PRIMARY_DIMENSIONS and slice_.net_buyable.count() >= 100)
                            use_ci = indices if primary_leaf or (dimension, level) in HEADLINE_CI else None
                            stats = summarize_slice(slice_, mode, topology, chronology, active_dates, mature_dates, pool_book, full_book, use_ci)
                            rows.append({"pool": pool, "window": window, "measure": mode, "horizon": h,
                                         "horizon_meets_t_plus_one": h >= 2,
                                         "exposure_scope": exposure, "dimension": dimension, "level": level, **stats})
    require(all(row["pool_buyable_net"] is None or abs(row["pool_buyable_net"]) < 1e-14 for row in rows
                if row["dimension"] == "COHORT" and row["measure"] == "BUYABLE"), "POOL_BENCHMARK_CENTERING")
    return rows, go_screen(rows), anomalies, comparator_proof, purity


def write_csv(rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    encoded = buffer.getvalue().encode("utf-8-sig")
    require(len(encoded) <= MAX_BYTES, "TABLE_SIZE_CAP")
    pending = CSV.with_name(f".{CSV.name}.{os.getpid()}.pending")
    try:
        with pending.open("xb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        pending.replace(CSV)
    finally:
        pending.unlink(missing_ok=True)
    return a31.ref(CSV) | {"rows": len(rows), "bytes": len(encoded), "columns": len(fields)}


def run(seal_sha):
    t0 = perf_counter()
    sessions = a31.act028.ExchangeSessions()
    calendar = a37i.f35.exchange_days(sessions.schedule)
    dates = calendar[calendar.index(a38.FIRST):calendar.index(a38.LAST) + 1]
    pool, seal_ref, seal = load_pool(seal_sha, dates)
    export, export_days, pred_ref, pred = a38.checked_export(PREDICTION_SHA, calendar)
    require(export_days == dates and seal["original_forecast_files"] == pred["files"], "ORIGINAL_FORECAST_SHARDS_DRIFT")
    known = {(row["trade_date"], row["ts_code"]) for row in pred["prior_exposure"]}
    require(all((d, code) in known for d, code in pool.loc[pool.known_previously_exposed.eq(True).fillna(False),
                                                        ["trade_date", "ts_code"]].itertuples(index=False, name=None)),
            "POOL_EXPOSURE_RECEIPT_MISMATCH")
    t1 = perf_counter()
    started = a31.json_atomic(START, {"schema": SCHEMA, "phase": "OUTCOMES_OPEN_AUTHORIZED", "pool_seal": seal_ref,
                                    "forecast_seal": pred_ref, "policy": POLICY, "signal_dates": dates,
                                    "code": a31.ref(Path(__file__).resolve()), "fit_calls": a33.FIT_CALLS, **a31.FLAGS})
    original_ref = {"path": str(a38.SUMMARY), "sha256": BASELINE_SHA}
    original = a31.read_ref(original_ref)
    require(original["phase"] == "FORWARD_STATISTICS_COMPLETE" and original["prediction_seal"] == pred_ref,
            "ACT038_BASELINE_RECEIPT_DRIFT")
    sources = a37i.load_sources()
    require(sources.days == dates and sources.calendar == calendar, "CALENDAR_SCOPE_DRIFT")
    tape, quote_receipts, band_audit, reader = execution_tape(sources, dates)
    t2 = perf_counter()
    markets, parity, full_exposed = full_benchmarks(export, dates, calendar, tape, quote_receipts, known, original)
    t3 = perf_counter()
    rows, passed, cases, pool_proof, purity = aggregate(pool, dates, sources.oot, sources.dev, calendar, tape,
                                                      quote_receipts, markets, full_exposed, known)
    t4 = perf_counter()
    metrics = write_csv(rows)
    headline = [row for row in rows if row["window"] == "ALL_53D" and row["exposure_scope"] == EXPOSURES[0]
                and (row["dimension"] == "COHORT" or (row["dimension"], row["level"]) in HEADLINE_CI)]
    report = a31.json_atomic(SUMMARY, {"schema": SCHEMA, "phase": "FORWARD_STATISTICS_COMPLETE", "started": started,
        "pool_seal": seal_ref, "forecast_seal": pred_ref, "signal_dates": dates, "pool_input_keys": len(pool),
        "full_a_input_keys": len(export), "forward_statistics_count": 1, "fit_calls": a33.FIT_CALLS,
        "tuning_count": 0, "historical_PIT": "CANNOT_CONFIRM", "policy": POLICY, "csv": metrics,
        "reader": reader, "quote_receipts": quote_receipts, "ACT038_full_a_unchanged": original_ref,
        "benchmark_parity_day_horizons": len(parity), "bootstrap_draws": a35.N_BOOTSTRAP,
        "bootstrap_seed": a35.SEED, "bootstrap_sessions": a35.BLOCK_SESSIONS,
        "pool_actual_days": {p: sorted(set(pool.loc[pool.pool.eq(p), "trade_date"])) for p in POOLS},
        "headline": headline, "go_screen": [r for r in rows if "go_screen" in r], "go_passed_n": len(passed),
        "go_model_passed_n": sum(r["go_screen"] == "MODEL_PASS" for r in passed),
        "anomalies": cases, "known_exposure_keys_n": len(known), "pure_sensitivity": purity,
        "chinext_302_nominal20_impact": chinext_302_impact(pool, export, calendar, band_audit),
        "pool_daily_benchmarks": pool_proof,
        "full_a_daily_benchmarks": [{"trade_date": d, "horizon": h, "denominators": value} for (d, h), value in markets.items()],
        "runtime": {"seal_and_projection_read_seconds": t1 - t0, "V4_quote_read_seconds": t2 - t1,
                    "market_parity_seconds": t3 - t2, "strata_and_blocks_seconds": t4 - t3,
                    "wall_seconds_before_receipt": perf_counter() - t0,
                    "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, **a31.FLAGS})
    print(f"FORWARD_STATISTICS_COMPLETE {report['sha256']}", flush=True)


def self_check():
    calendar = ["20261116", "20261117", "20261118", "20261119", "20261120", "20261123", "20261124", "20261125", "20261126", "20261127"]
    day = calendar[0]
    codes = ["600001.SH", "600002.SH", "300001.SZ", "600003.SH"]
    market = pd.DataFrame({
        "buyable": [True, False, False, True], "open_basis": [10., 10., np.nan, 10.],
        "entry_status": ["STANDARD_CAP_MODELED_OPEN", "STANDARD_CAP_AT_OPEN", "ENTRY_NO_VOLUME", "STANDARD_CAP_MODELED_OPEN"],
        "close_basis": [9.03, 11., np.nan, 11.], "exit_cap_clear": [False, True, None, True],
        "exit_status": ["EXIT_CLOSE_AT_LOWER_CAP", "EXIT_MODELED_CLOSE", "EXIT_NO_VOLUME", "EXIT_MODELED_CLOSE"],
        "open_gap": [0., .1, np.nan, 0.], "dated_st": [False, False, None, True],
    }, index=codes)
    tape = {d: market for d in calendar[1:6]}
    source = {d: {"source": a36i.OFFICIAL} for d in calendar[1:6]}
    table = marks(codes, day, 5, calendar, tape, source)
    assert np.isclose(table.net_buyable.iat[0], -.10)
    assert np.isclose(table.net_theoretical.iat[1], .097) and np.isnan(table.net_buyable.iat[1])
    assert np.isnan(table.net_theoretical.iat[2]) and not marks(codes, calendar[1], 5, calendar, tape, source).mature.any()
    subset = pd.DataFrame({"trade_date": day, "ts_code": codes, "exact_known_exposure": [False, True, False, False],
                           "prediction_join_status": ["MATCHED", "MATCHED", "UNMATCHED", "MATCHED"],
                           "known_previously_exposed": [False, True, None, False]}).join(table)
    full = day_books(subset)
    rec = summarize_slice(subset, "THEORETICAL", {}, calendar[:5], {day}, {day}, full, full, None)
    assert rec["mark_n"] == 3 and rec["pure_tail_n"] == rec["upper_cap_theoretical_marks_n"] == rec["exit_lower_cap_mark_n"] == 1
    assert rec["prediction_unmatched_n"] == rec["exposure_unknown_n"] == 1
    assert np.isclose(rec["pool_buyable_net"], (.097 + .097 - .1)/3 - (.097 - .1)/2)
    selected = group_window_masks(calendar, calendar[:4], calendar[4:], set(calendar), {calendar[3], calendar[6]}, POOLS[0])["PRODUCT_MATCHED_DAYS"]
    assert selected == (calendar[3:7], {calendar[3], calendar[6]})
    ratio, low, high, n = paired_ratio(np.full(6, .01), np.ones(6, dtype=int), bootstrap_indices(calendar[:6]))
    assert np.allclose([ratio, low, high], .01) and n == a35.N_BOOTSTRAP
    synthetic = [{"window": w, "dimension": "BOARD", "level": "MAIN_60_00", "pool": POOLS[0], "measure": MODES[0],
                  "exposure_scope": EXPOSURES[0], "horizon": 5, "mark_n": 100, "pool_buyable_net": .012,
                  "pool_buyable_tail": -.031, "pool_buyable_net_low_95": .002, "pool_buyable_tail_high_95": -.001}
                 for w in ("ALL_53D", "OOT_EARLY", "DEV_21D")]
    review = go_screen(synthetic)
    assert review[0]["go_screen"] == "CONTROL_PASS" and review[0]["go_matched_net_pass"] and review[0]["go_pure_tail_pass"]
    q = {"name": "fixture", "quote_evidence": a36i.OFFICIAL, "dated_st": False,
         "eligible_for_daily_gain_rank": True, "prev_close": 10., "open": 11., "high": 11., "low": 8.5, "close": 8.5}
    assert a38.quote_assessments("302132.SZ", q)[0] is False and chinext_302_assessment("302132.SZ", q)[0] is True
    print("ACT039A_METRICS_SYNTHETIC_PASS", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run-frozen", action="store_true")
    action.add_argument("--self-check", action="store_true")
    parser.add_argument("--pool-seal-sha")
    args = parser.parse_args(argv)
    if args.self_check:
        self_check()
        return
    require(args.pool_seal_sha is not None, "EXPLICIT_POOL_SEAL_SHA_REQUIRED")
    with a31.exclusive_run(OUT):
        require(not any(path.exists() for path in (START, SUMMARY, CSV)), "OUTCOMES_ALREADY_STARTED")
        run(args.pool_seal_sha)


if __name__ == "__main__":
    main()
