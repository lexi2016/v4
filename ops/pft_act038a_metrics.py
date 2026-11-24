"""ACT-038A fixed-horizon outcome statistics for the sealed S_V3 export."""
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
from ops import pft_act033a_outcomes as o33
from ops import pft_act033a_replay as a33
from ops import pft_act034a_rules as r34
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36i
from ops import pft_act036a_replay as a36
from ops import pft_act037a_inputs as a37i


OUT = a35.ROOT / "pft_act038a_oos_export_20261124"
EXPORT_SEAL = OUT / "PREDICTION_SEAL.json"
METRICS_STARTED = OUT / "METRICS_STARTED.json"
SUMMARY = OUT / "METRICS_SUMMARY.json"
CSV = OUT / "CODEX_MAC_ACT-038A_SV3_53D_STRATIFIED_METRICS_20261124.csv"
SCHEMA = "pft.act038a.fixed_horizon_metrics.v1"
FIRST, LAST, CUTOFF = "20260901", "20261120", "20261123"
HORIZONS = (2, 3, 5)
FEE = r34.FEE
TAIL = -.10
SCOPES = ("ALL_A", "MAIN_60_00")
WINDOWS = ("ALL_53D", "202609", "202610", "202611", "OOT_EARLY", "DEV_21D")
STATES = ("CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE", "NULL_MISSING")
TACTICS = ("S_PULLBACK", "S_REBUILD", "S_READVANCE")
TIERS = ("EXT1_LINE_SPREAD_CLEAN", "EXT3_STRONG_HEAD_CONFLICT", "PURE_HEAD_CONFLICT")
STRATA = ("ALL", *STATES, "UNKNOWN_BORDERLINE_RAW", "UNKNOWN_P_GE_050_LT_085", "UNKNOWN_P_GE_085", *TIERS,
          *(f"{state}:{tactic}" for state in STATES[:2] for tactic in TACTICS))
SIGNAL_COLUMNS = ("trade_date", "ts_code", "s_decision_state", "main_tactic", "best_candidate_tactic",
                  "projected_p_s", "early_borderline_tier", "is_st", "model_version", "model_commit",
                  "train_cutoff_date", "is_strict_oos_post_cutoff", "missing_reason", "membership_source")
HISTORY_COLUMNS = ("open", "high", "low", "close", "vol", "pre_close", "amount", "tradeable_basic")
DATED_MEMBERSHIP = ("DATED_OFFICIAL", "DATED_V4_READER_D_BAR", "DATED_FROZEN_ELIGIBLE_KEY")
UNCONFIRMED_MEMBERSHIP = "PRIOR_V4_EXISTENCE_D_ACTIVITY_UNCONFIRMED"
ST_BAND_SOURCES = {
    "SH_MAIN": "https://star.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml",
    "SZ_MAIN": "https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020260424690713346617.pdf",
    "SZ_EFFECTIVE": "https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html",
}
POLICY = {
    "entry": "D+1 opening proxy under the observed dated standard board band; at upper cap or zero volume is blocked. No ST status is carried across dates. The ACT036 whole-date rebase proxy does not prove historical names or market execution.",
    "exit": "D+h close mark, h in (2,3,5) as exchange sessions after D. Both legs must reconcile to the same cutoff QFQ basis. Valid lower-limit close marks remain in the loss statistics and their exit impairment is separate. Between-leg marks are unnecessary.",
    "benchmark": "Each D/h full-A equal-weight benchmark uses exported keys proven by the exact D V4 row, exact D official quote roster or exact D sealed frozen roster, identical eligible entry/close marks and 30bps. MAIN_60_00 uses the same benchmark. Prior-only listing evidence cannot admit D membership. All broad states including NULL remain eligible.",
    "state": "Frozen export states are preserved. Primary NULL_MISSING includes a null state or a legacy UNKNOWN stub without READY raw heads and without a finite frozen projected score. UNKNOWN_BORDERLINE_RAW preserves all emitted unknown states. A strict-G1 REJECTED_FAKE is valid regardless of shadow score availability.",
    "net_fee": FEE,
    "pure_tail_inclusive_net": TAIL,
    "strict_cutoff": CUTOFF,
    "paired_bootstrap": "Equal-weight same-date mean net-return differences UNKNOWN minus CONFIRMED. Moving 5-session blocks over D chronology including missing placeholders, then omit unpaired cells. Split descriptive intervals are unadjusted.",
}


def require(condition, reason):
    if not condition:
        raise a31.ContractError(f"ACT038A_METRICS_{reason}")


def checked_export(seal_sha, calendar):
    require(re.fullmatch(r"[0-9a-f]{64}", seal_sha), "EXPECTED_SEAL_SHA_INVALID")
    reference = {"path": str(EXPORT_SEAL), "sha256": seal_sha}
    seal = a31.read_ref(reference)
    dates = calendar[calendar.index(FIRST):calendar.index(LAST) + 1]
    require(len(dates) == 53 and seal["phase"] == "PREDICTIONS_SEALED"
            and seal["signal_dates"] == dates and seal["outcomes_opened"] is False,
            "PREDICTION_SEAL_SCOPE")
    expected_shards = set(dates)
    parts = []
    for shard in seal["files"]:
        path = a33.checked(shard)
        require(path.parent.is_relative_to(OUT) and path.suffix == ".parquet"
                and path.stat().st_size == shard["bytes"] <= 9_500_000, "SHARD_BYTES_OR_LOCATION")
        part = pd.read_parquet(path, columns=list(SIGNAL_COLUMNS))
        present = sorted(part.trade_date.unique().tolist())
        require(len(part) == shard["rows"] and present == sorted(shard["dates"])
                and set(present) <= expected_shards, "SHARD_KEYS_OR_DATES")
        expected_shards.difference_update(present)
        parts.append(part)
    require(not expected_shards and len(parts) in range(3, 7), "EXPORT_SHARD_COVERAGE")
    export = pd.concat(parts, ignore_index=True)
    require(not export.duplicated(["trade_date", "ts_code"]).any() and export.ts_code.notna().all()
            and export.ts_code.map(a31.a_share_instrument_rejection).isna().all()
            and export.model_version.eq("S_V3.0_FROZEN").fillna(False).all()
            and export.model_commit.eq("fc528d9da0d6").fillna(False).all()
            and export.train_cutoff_date.eq("20260831").fillna(False).all()
            and export.trade_date.gt(export.train_cutoff_date).all()
            and export.is_strict_oos_post_cutoff.eq(True).fillna(False).all(), "EXPORT_KEY_OR_OOS_INVARIANT")
    require(export.s_decision_state.dropna().isin(STATES[:3]).all(), "UNKNOWN_FROZEN_STATE")
    require(export.missing_reason.isin(("READY", "INSUFFICIENT_65_BARS", "MISSING_CONTEXT", "SUSPENDED_OR_OUT_OF_UNIVERSE")).all()
            and export.membership_source.isin((*DATED_MEMBERSHIP, UNCONFIRMED_MEMBERSHIP)).all()
            and export.early_borderline_tier.isin((*TIERS, "HIGH_P_BORDERLINE_050_085", "NONE")).all(),
            "EXPORT_DISPOSITION_OR_TIER_DRIFT")
    return export, dates, reference, seal


def quote_assessments(code, quote):
    """Use dated ST evidence only where a corresponding band is evidenced."""
    if quote is None:
        return None, "ENTRY_QUOTE_MISSING", None, "EXIT_QUOTE_MISSING"
    if not quote["eligible_for_daily_gain_rank"]:
        if quote.get("zero_volume") is True:
            return False, "ENTRY_NO_VOLUME", False, "EXIT_NO_VOLUME"
        return None, "ENTRY_INVALID_BAR", None, "EXIT_INVALID_BAR"
    is_st = quote.get("dated_st")
    if is_st is True and not g.main_board(code):
        return None, "ENTRY_DATED_OFF_MAIN_ST_BAND_UNKNOWN", None, "EXIT_DATED_OFF_MAIN_ST_BAND_UNKNOWN"
    if is_st is None and quote["quote_evidence"] == a36i.OFFICIAL:
        return None, "ENTRY_OFFICIAL_NAME_UNKNOWN", None, "EXIT_OFFICIAL_NAME_UNKNOWN"
    opening = a31.opening_assessment(code, quote)
    buy, buy_reason = opening["opening_buyable_proxy"], opening["opening_status"]
    if is_st is True:
        # The post-July-6 2026 SSE/SZSE main-board ST band is the ordinary 10%.
        previous = a31.positive(quote.get("prev_close"))
        floor = r34.cap_price(previous, Decimal(".90")) if previous is not None else None
        if floor is None:
            sell, sell_reason = None, "EXIT_STANDARD_CAP_INPUT_UNKNOWN"
        elif quote["low"] < floor - 1e-6:
            sell, sell_reason = None, "EXIT_STANDARD_CAP_EXCEPTION"
        elif quote["close"] <= floor + 1e-6:
            sell, sell_reason = False, "EXIT_CLOSE_AT_LOWER_CAP"
        else:
            sell, sell_reason = True, "EXIT_MODELED_CLOSE"
    elif quote["quote_evidence"] == a36i.PROXY:
        sell, sell_reason = a36.diagnostic_sell(code, quote, "CLOSE")
    else:
        sell, sell_reason = o33.selling_outcome(code, quote)
    return buy, buy_reason, sell, sell_reason


def execution_tape(sources, dates):
    bound = a37i.bound(sources, CUTOFF)
    lo = sources.calendar[sources.calendar.index(dates[0]) + 1]
    history = a36i.read_history(bound, dates[0], CUTOFF, columns=HISTORY_COLUMNS)
    bounds = sources.calendar[sources.calendar.index(dates[0]):sources.calendar.index(CUTOFF) + 1]
    require(sorted(history.trade_date.unique().tolist()) == bounds
            and not history.duplicated(["trade_date", "ts_code"]).any(), "OUTCOME_READER_DATE_OR_KEY_DRIFT")
    identity = {"reader": bound.identity, "rows": len(history), "symbols": history.ts_code.nunique(),
                "bounds": [dates[0], CUTOFF], "projected_memory_bytes": int(history.memory_usage(deep=True).sum())}
    basis = a36i.Basis(bound)
    event_proof = {}
    for code in history.ts_code.unique():
        ledger = bound.symbols.get(code, {})
        first = str(ledger.get("history_start_date") or lo)
        event_proof[code] = first, r34.affine_events(ledger, max(lo, first))
    tape, receipts, d_universe = {}, {}, {}
    for day, bars in history.groupby("trade_date", sort=True):
        if day in sources.quotes:
            official, reference = sources.quotes[day]
        else:
            official, reference = a31.day_quotes(day, sources.prior.inputs["days"][day])
        if day in dates:
            d_universe[day] = {"cutoff_reader_D_keys": set(bars.ts_code), "official_D_keys": set(official or ())}
        if day < lo:
            continue
        quotes, mode = a36i.quotes_for_day(bars, day, basis, official)
        records = bars.set_index("ts_code").to_dict("index")
        rows = []
        for code, quote in quotes.items():
            first, events = event_proof.get(code, (day, None))
            prices, quality = r34.verified_bar(records.get(code), quote, day, events if first <= day else None)
            buy, buy_reason, sell, sell_reason = quote_assessments(code, quote)
            rows.append((code, buy, buy_reason, prices.get("open") if buy is True else None,
                         prices.get("close"), sell, sell_reason, quality, quote.get("dated_st")))
        tapes = pd.DataFrame(rows, columns=("ts_code", "buyable", "entry_status", "entry_basis", "close_basis",
                                            "exit_cap_clear", "exit_status", "price_quality", "dated_st")).set_index("ts_code")
        tape[day] = tapes
        receipts[day] = {"source": mode, "official_receipt": reference, "quote_n": len(tapes),
                         "basis_quality_counts": dict(Counter(tapes.price_quality)),
                         "entry_status_counts": dict(Counter(tapes.entry_status)),
                         "exit_status_counts": dict(Counter(tapes.exit_status))}
    return tape, receipts, identity, d_universe


def selectors(frame):
    emitted = frame.s_decision_state.astype("string")
    raw_unknown = emitted.eq("UNKNOWN_BORDERLINE").fillna(False)
    projected = frame.projected_p_s
    ready = frame.missing_reason.eq("READY").fillna(False) | np.isfinite(projected.to_numpy(dtype=float, na_value=np.nan))
    state = emitted.mask(raw_unknown & ~ready).fillna("NULL_MISSING")
    tactic = {col: frame[col].astype("string").str.upper().str.removeprefix("S_").radd("S_")
              for col in ("main_tactic", "best_candidate_tactic")}
    unknown = state.eq("UNKNOWN_BORDERLINE")
    strata = {"ALL": np.ones(len(frame), dtype=bool), **{name: state.eq(name).to_numpy() for name in STATES},
              "UNKNOWN_BORDERLINE_RAW": raw_unknown,
              "UNKNOWN_P_GE_050_LT_085": unknown & projected.ge(.50) & projected.lt(.85),
              "UNKNOWN_P_GE_085": unknown & projected.ge(.85)}
    strata |= {name: unknown & frame.early_borderline_tier.eq(name) for name in TIERS}
    strata |= {f"{name}:{child}": state.eq(name) & tactic[col].eq(child) for name, col in
               zip(STATES[:2], tactic, strict=True) for child in TACTICS}
    return {name: pd.array(mask, dtype="boolean").to_numpy(dtype=bool, na_value=False) for name, mask in strata.items()}


def daily_cells(frame, day, dates, tape, sources):
    scopes = {"ALL_A": np.ones(len(frame), dtype=bool), "MAIN_60_00": frame.ts_code.map(g.main_board).to_numpy()}
    strata = selectors(frame)
    cursor = dates.index(day)
    buy_day = dates[cursor + 1]
    entry = tape[buy_day].reindex(frame.ts_code)
    declared_d = frame.membership_source.isin(DATED_MEMBERSHIP).to_numpy()
    buyable = declared_d & entry.buyable.eq(True).to_numpy()
    blocked = declared_d & entry.buyable.eq(False).to_numpy()
    entry_basis = entry.entry_basis.to_numpy(dtype=float, na_value=np.nan)
    valid_open = buyable & np.isfinite(entry_basis)
    dated_st = entry.dated_st.eq(True).to_numpy()
    feature_st = frame.is_st.eq(True).fillna(False).to_numpy(dtype=bool)
    feature_st_missing = frame.is_st.isna().to_numpy()
    receipts, cells = [], []
    for h in HORIZONS:
        end_day = dates[cursor + h]
        mature = end_day <= CUTOFF
        quote_tier = "RIGHT_CENSORED"
        no_marks = np.full(len(frame), np.nan)
        close_basis, exit_evidence = no_marks, None
        if mature:
            target = tape[end_day].reindex(frame.ts_code)
            close_basis = target.close_basis.to_numpy(dtype=float, na_value=np.nan)
            exit_evidence = target.exit_cap_clear
            quote_tier = "OFFICIAL_BOTH_LEGS" if all(sources[d]["source"] == a36i.OFFICIAL for d in (buy_day, end_day)) else "HAS_ARCHIVE_PROXY_LEG"
        covered = valid_open & np.isfinite(close_basis)
        returns = np.divide(close_basis, entry_basis, where=covered, out=no_marks.copy()) - 1. - FEE
        benchmark_n = int(covered.sum())
        bmark = float(returns[covered].mean()) if benchmark_n else None
        wins = covered & (returns > 0.)
        tails = covered & (returns <= TAIL + r34.EPS)
        receipts.append({"trade_date": day, "entry_date": buy_day, "target_date": end_day, "horizon": h,
                         "mature": mature, "quote_tier": quote_tier, "benchmark_n": benchmark_n,
                         "d_membership_proven_n": int(declared_d.sum()), "d_membership_export_only_n": int((~declared_d).sum()),
                         "benchmark_net_mean": bmark})
        for scope in SCOPES:
            for name in STRATA:
                members = scopes[scope] & strata[name]
                marks = members & covered
                n = int(marks.sum())
                record = {"trade_date": day, "horizon": h, "scope": scope, "stratum": name,
                          "mature": mature, "quote_tier": quote_tier, "signal_keys": int(members.sum()),
                          "d_membership_proven_n": int((members & declared_d).sum()),
                          "d_membership_export_only_n": int((members & ~declared_d).sum()),
                          "entry_buyable_proxy_n": int((members & buyable).sum()),
                          "entry_known_blocked_n": int((members & blocked).sum()),
                          "entry_unknown_n": int((members & declared_d & ~buyable & ~blocked).sum()),
                          "entry_basis_unverified_n": int((members & buyable & ~valid_open).sum()),
                          "entry_verified_n": int((members & valid_open).sum()),
                          "right_censored_verified_entry_n": int((members & valid_open).sum()) if not mature else 0,
                          "mature_missing_close_mark_n": int((members & valid_open & ~covered).sum()) if mature else 0,
                          "signal_st_n": int((members & feature_st).sum()),
                          "signal_is_st_unknown_n": int((members & feature_st_missing).sum()),
                          "entry_dated_st_mark_n": int((marks & dated_st).sum()),
                          "mark_n": n, "net_sum": float(returns[marks].sum()),
                          "excess_sum": float((returns[marks] - bmark).sum()) if n else 0.,
                          "win_n": int((members & wins).sum()), "tail_n": int((members & tails).sum()),
                          "exit_cap_clear_n": int((marks & exit_evidence.eq(True).to_numpy()).sum()) if n else 0,
                          "exit_cap_blocked_n": int((marks & exit_evidence.eq(False).to_numpy()).sum()) if n else 0}
                cells.append(record)
    return cells, receipts


def windows(dates, early, dev):
    return {"ALL_53D": dates, **{month: [day for day in dates if day.startswith(month)] for month in WINDOWS[1:4]},
            "OOT_EARLY": early, "DEV_21D": dev}


def safe(num, den):
    return float(num / den) if den else None


def summarize_slice(group):
    count_columns = ("signal_keys", "d_membership_proven_n", "d_membership_export_only_n", "entry_buyable_proxy_n", "entry_known_blocked_n", "entry_unknown_n",
                     "entry_basis_unverified_n", "entry_verified_n", "right_censored_verified_entry_n",
                     "mature_missing_close_mark_n", "signal_st_n", "signal_is_st_unknown_n", "entry_dated_st_mark_n",
                     "mark_n", "win_n", "tail_n", "exit_cap_clear_n", "exit_cap_blocked_n")
    sums = {name: int(group[name].sum()) for name in count_columns}
    valid = group.loc[group.mark_n.gt(0)]
    exact = valid.loc[valid.quote_tier.eq("OFFICIAL_BOTH_LEGS")]
    proxy = valid.loc[valid.quote_tier.eq("HAS_ARCHIVE_PROXY_LEG")]
    n = sums["mark_n"]
    require(sums["entry_buyable_proxy_n"] + sums["entry_known_blocked_n"] + sums["entry_unknown_n"]
            == sums["d_membership_proven_n"] and sums["d_membership_proven_n"] + sums["d_membership_export_only_n"] == sums["signal_keys"]
            and sums["entry_verified_n"] == n + sums["right_censored_verified_entry_n"] + sums["mature_missing_close_mark_n"],
            "ENTRY_OR_HORIZON_DENOMINATOR_DRIFT")
    return {**sums, "mature_days": int(group.mature.sum()), "right_censored_days": int((~group.mature).sum()),
            "marked_signal_days": len(valid), "net_mean": safe(valid.net_sum.sum(), n),
            "matched_all_a_excess_mean": safe(valid.excess_sum.sum(), n),
            "day_equal_net_mean": float((valid.net_sum / valid.mark_n).mean()) if n else None,
            "day_equal_excess_mean": float((valid.excess_sum / valid.mark_n).mean()) if n else None,
            "net_win_rate": safe(sums["win_n"], n), "pure_tail_rate": safe(sums["tail_n"], n),
            "marked_exit_cap_unknown_n": n - sums["exit_cap_clear_n"] - sums["exit_cap_blocked_n"],
            "official_mark_days": len(exact), "official_mark_n": int(exact.mark_n.sum()),
            "official_net_mean": safe(exact.net_sum.sum(), exact.mark_n.sum()),
            "official_excess_mean": safe(exact.excess_sum.sum(), exact.mark_n.sum()),
            "proxy_mark_days": len(proxy), "proxy_mark_n": int(proxy.mark_n.sum()),
            "proxy_net_mean": safe(proxy.net_sum.sum(), proxy.mark_n.sum()),
            "proxy_excess_mean": safe(proxy.excess_sum.sum(), proxy.mark_n.sum())}


def paired_intervals(delta, block=a35.BLOCK_SESSIONS, draws=a35.N_BOOTSTRAP, seed=a35.SEED):
    """Paired D means, resampling contiguous original exchange-session blocks."""
    finite = np.isfinite(delta)
    n = int(finite.sum())
    mean = float(delta[finite].mean()) if n else None
    if n < block:
        return mean, None, None, 0
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(delta) - block + 1, (draws, (len(delta) + block - 1) // block))
    indices = (starts[:, :, None] + np.arange(block)).reshape(draws, -1)[:, :len(delta)]
    samples = delta[indices]
    denominators = np.isfinite(samples).sum(axis=1)
    estimates = np.nansum(samples, axis=1)[denominators > 0] / denominators[denominators > 0]
    bounds = np.quantile(estimates, [.025, .975]).tolist() if len(estimates) else [None, None]
    return mean, *bounds, len(estimates)


def paired_slice(unknown, confirmed, dates):
    left = unknown.set_index("trade_date").reindex(dates)
    right = confirmed.set_index("trade_date").reindex(dates)
    mask = (left.mark_n > 0) & (right.mark_n > 0)
    official = mask & left.quote_tier.eq("OFFICIAL_BOTH_LEGS")
    result = {"paired_days": int(mask.sum()), "paired_official_days": int(official.sum()),
              "paired_proxy_days": int((mask & ~official).sum()),
              "paired_daily_days_unknown_ahead_n": 0}
    for name, col in (("net", "net_sum"), ("win_rate", "win_n"), ("pure_tail_rate", "tail_n")):
        delta = ((left[col] / left.mark_n) - (right[col] / right.mark_n)).where(mask).to_numpy(dtype=float)
        mean, lower, upper, valid = paired_intervals(delta)
        result.update({f"paired_{name}_difference": mean, f"paired_{name}_low_95": lower,
                       f"paired_{name}_high_95": upper, f"paired_{name}_valid_draws": valid,
                       f"paired_{name}_official_difference": float(delta[official.to_numpy()].mean()) if official.any() else None})
        if name == "net":
            result["paired_daily_days_unknown_ahead_n"] = int((delta > 0.).sum())
    return result


def aggregate(cells, date_windows):
    frame = pd.DataFrame(cells)
    rows = []
    for window in WINDOWS:
        dates = date_windows[window]
        by = frame.loc[frame.trade_date.isin(dates)].groupby(["scope", "horizon", "stratum"], sort=False)
        for scope in SCOPES:
            for h in HORIZONS:
                base = {"window": window, "signal_days": len(dates), "scope": scope, "horizon": h}
                for name in STRATA:
                    rows.append({**base, "record_type": "STRATUM", "stratum": name,
                                 **summarize_slice(by.get_group((scope, h, name)))})
                unknown = by.get_group((scope, h, "UNKNOWN_BORDERLINE"))
                raw_unknown = by.get_group((scope, h, "UNKNOWN_BORDERLINE_RAW"))
                confirmed = by.get_group((scope, h, "CONFIRMED_S"))
                rows.append({**base, "record_type": "PAIRED", "stratum": "UNKNOWN_MINUS_CONFIRMED",
                             **paired_slice(unknown, confirmed, dates)})
                rows.append({**base, "record_type": "PAIRED", "stratum": "UNKNOWN_RAW_MINUS_CONFIRMED",
                             **paired_slice(raw_unknown, confirmed, dates)})
    return rows


def write_metrics(rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    encoded = buffer.getvalue().encode("utf-8-sig")
    require(len(encoded) <= 9_500_000, "METRICS_CSV_BUDGET")
    temporary = CSV.with_name(f".{CSV.name}.{os.getpid()}.pending")
    try:
        with temporary.open("xb") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(CSV)
    finally:
        temporary.unlink(missing_ok=True)
    return a31.ref(CSV) | {"rows": len(rows), "bytes": len(encoded), "columns": len(fields)}


def run(seal_sha):
    start = perf_counter()
    sessions = a31.act028.ExchangeSessions()
    calendar = a37i.f35.exchange_days(sessions.schedule)
    export, dates, export_ref, seal = checked_export(seal_sha, calendar)
    sealed = perf_counter()
    marker = a31.json_atomic(METRICS_STARTED, {"schema": SCHEMA, "phase": "OUTCOMES_OPEN_AUTHORIZED",
                             "code": a31.ref(Path(__file__).resolve()), "prediction_seal": export_ref,
                             "signal_dates": dates, "forward_statistics_count": 1, "policy": POLICY,
                             "fit_calls": a33.FIT_CALLS, **a31.FLAGS})
    sources = a37i.load_sources()
    require(sources.days == dates and sources.calendar == calendar, "PRIOR_FROZEN_CALENDAR_DRIFT")
    tape, quote_receipts, reader, d_universe = execution_tape(sources, dates)
    read = perf_counter()
    cells, day_receipts, universe_audit = [], [], {}
    for day, group in export.groupby("trade_date", sort=True):
        keys = set(group.ts_code)
        declared = set(group.loc[group.membership_source.isin(DATED_MEMBERSHIP), "ts_code"])
        official_keys = d_universe[day]["official_D_keys"]
        reader_keys = d_universe[day]["cutoff_reader_D_keys"]
        require(official_keys <= declared, f"OFFICIAL_D_KEYS_NOT_COVERED_BY_EXPORT:{day}:{len(official_keys - declared)}")
        universe_audit[day] = {"D_export_keys_n": len(keys), "D_proven_keys_n": len(declared),
                               "D_official_keys_n": len(official_keys), "D_cutoff_reader_keys_n": len(reader_keys),
                               "D_cutoff_reader_missing_export_n": len(reader_keys - keys),
                               "D_export_proven_missing_cutoff_reader_n": len(declared - reader_keys)}
        day_cells, verified = daily_cells(group, day, calendar, tape, quote_receipts)
        cells.extend(day_cells)
        day_receipts.extend(verified)
    rows = aggregate(cells, windows(dates, sources.oot, sources.dev))
    require(len(rows) == len(WINDOWS) * len(SCOPES) * len(HORIZONS) * (len(STRATA) + 2), "AGGREGATE_SCOPE")
    computed = perf_counter()
    csv_ref = write_metrics(rows)
    digest = a31.json_atomic(SUMMARY, {"schema": SCHEMA, "phase": "FORWARD_STATISTICS_COMPLETE",
                            "started": marker, "prediction_seal": export_ref, "export_files": seal["files"],
                            "signal_dates": dates, "input_keys": len(export), "reader": reader,
                            "quote_receipts": quote_receipts, "daily_benchmarks": day_receipts, "d_universe_audit": universe_audit,
                            "daily_paired_cells": [row for row in cells if row["stratum"] in (*STATES[:2], "UNKNOWN_BORDERLINE_RAW")],
                            "statistics_csv": csv_ref, "statistics": rows, "historical_PIT": "CANNOT_CONFIRM",
                            "fit_calls": a33.FIT_CALLS, "forward_statistics_count": 1, "policy": POLICY,
                            "main_board_ST_sources": ST_BAND_SOURCES, "bootstrap_seed": a35.SEED,
                            "bootstrap_draws": a35.N_BOOTSTRAP, "bootstrap_sessions": a35.BLOCK_SESSIONS,
                            "runtime": {"seal_validation_seconds": sealed - start, "reader_and_quote_seconds": read - sealed,
                                        "metrics_compute_seconds": computed - read, "wall_seconds_before_receipt": perf_counter() - start,
                                        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, **a31.FLAGS})
    print(f"FORWARD_STATISTICS_COMPLETE {digest['sha256']}", flush=True)


def self_check():
    dates = ["20261116", "20261117", "20261118", "20261119", "20261120", "20261123", "20261124"]
    day = dates[0]
    frame = pd.DataFrame({"ts_code": ["000001.SZ", "600001.SH", "300002.SZ", "600003.SH"],
                          "s_decision_state": ["CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE", None],
                          "main_tactic": ["S_PULLBACK", None, None, None],
                          "best_candidate_tactic": ["pullback", "rebuild", "readvance", None],
                          "early_borderline_tier": ["NONE", "EXT3_STRONG_HEAD_CONFLICT", "NONE", "NONE"],
                          "projected_p_s": [.91, .85, np.nan, np.nan], "is_st": [False, True, None, None],
                          "missing_reason": ["READY", "READY", "MISSING_CONTEXT", "MISSING_CONTEXT"],
                          "membership_source": [DATED_MEMBERSHIP[0]] * 4})
    market = pd.DataFrame({"buyable": [True, True, False, True], "entry_basis": [10., 10., np.nan, 10.],
                           "close_basis": [9.03, 11., 10., 10.], "exit_cap_clear": [False, True, True, None],
                           "dated_st": [False, True, None, None]}, index=frame.ts_code)
    tape = {date: market for date in dates[1:6]}
    quote_sources = {date: {"source": a36i.OFFICIAL} for date in dates[1:6]}
    quote_sources[dates[3]]["source"] = a36i.PROXY
    cells, benchmark = daily_cells(frame, day, dates, tape, quote_sources)
    records = {(x["scope"], x["horizon"], x["stratum"]): x for x in cells}
    base = records["ALL_A", 2, "ALL"]
    assert base["mark_n"] == 3 and base["tail_n"] == 1 and base["entry_known_blocked_n"] == 1
    assert base["exit_cap_blocked_n"] == 1 and abs(base["excess_sum"]) < r34.EPS
    assert records["MAIN_60_00", 3, "UNKNOWN_BORDERLINE:S_REBUILD"]["mark_n"] == 1
    assert records["ALL_A", 2, "UNKNOWN_P_GE_085"]["mark_n"] == 1
    assert records["ALL_A", 2, "UNKNOWN_P_GE_050_LT_085"]["mark_n"] == 0
    assert benchmark[1]["quote_tier"] == "HAS_ARCHIVE_PROXY_LEG"
    changed = frame.assign(missing_reason=["READY", "MISSING_CONTEXT", "MISSING_CONTEXT", "MISSING_CONTEXT"],
                           projected_p_s=[.91, np.nan, np.nan, np.nan],
                           membership_source=[DATED_MEMBERSHIP[0]] * 3 + [UNCONFIRMED_MEMBERSHIP])
    edge, _ = daily_cells(changed, day, dates, tape, quote_sources)
    edge = {(x["scope"], x["horizon"], x["stratum"]): x for x in edge}
    assert edge["ALL_A", 2, "UNKNOWN_BORDERLINE"]["mark_n"] == 0 and edge["ALL_A", 2, "UNKNOWN_BORDERLINE_RAW"]["mark_n"] == 1
    assert edge["ALL_A", 2, "NULL_MISSING"]["mark_n"] == edge["ALL_A", 2, "NULL_MISSING"]["d_membership_export_only_n"] == 1
    _, late = daily_cells(frame, dates[1], dates, tape, quote_sources)
    assert late[-1]["quote_tier"] == "RIGHT_CENSORED" and late[-1]["target_date"] == dates[-1]
    assert quote_assessments("600001.SH", {"quote_evidence": a36i.OFFICIAL, "name": "*ST示例", "dated_st": True,
           "prev_close": 10., "open": 11., "high": 11., "low": 10.5, "close": 10.5,
           "eligible_for_daily_gain_rank": True}) == (False, "STANDARD_CAP_AT_OPEN", True, "EXIT_MODELED_CLOSE")
    mean, lo, hi, valid = paired_intervals(np.array([.05, .05, .05, .05, np.nan, .05]))
    assert np.isclose(mean, .05) and np.isclose(lo, .05) and np.isclose(hi, .05) and valid == a35.N_BOOTSTRAP
    assert paired_intervals(np.array([.05, .05, .05, .05, np.nan, np.nan])) == (.05, None, None, 0)
    print("ACT038A_METRICS_SYNTHETIC_PASS", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run-frozen", action="store_true")
    action.add_argument("--self-check", action="store_true")
    parser.add_argument("--export-seal-sha")
    args = parser.parse_args(argv)
    if args.self_check:
        self_check()
        return
    require(args.export_seal_sha is not None, "EXACT_EXPORT_SEAL_SHA_REQUIRED")
    with a31.exclusive_run(OUT):
        require(not any(path.exists() for path in (METRICS_STARTED, SUMMARY, CSV)), "FORWARD_STATISTICS_ALREADY_STARTED")
        run(args.export_seal_sha)


if __name__ == "__main__":
    main()
