"""ACT-033A read-only execution projection and coverage-aware metrics."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates
from ops import pft_act033a_replay as replay

HORIZONS = (1, 3, 5)
FEE = .003
B2_GAP_MAX = .05
OUTCOME_POLICY = {
    "entry": "On D+1 raw standard-cap opening proxy over sealed D picks. Hold unfilled B2 gaps >5% in cash, with no refill.",
    "exit": "T1 is same-session D+1 close mark-to-market under mainland T+1. T3/T5 mark valid cutoff-basis QFQ paths. Exact raw no-volume, lower-limit closes and missing flags are recorded separately; lower-limit price risk remains in return and crash statistics.",
    "fees": "Deduct 0.003 total round-trip per filled symbol; T1 net is a costed MTM illustration.",
    "benchmark": "Same-D eligible all-A, gross, equal weight over symbols passing the same opening proxy and valid horizon price path. No B2 gap gate on the benchmark.",
    "excess": "Each measured strategy gross less same-D benchmark gross for the horizon.",
    "nav": "D+1 open-to-close costed MTM proxy. Equal weight across pre-open picks, known failed opens allocated cash; zero-pick verified days cash. Unknown inputs break paths. Segment NAV re-anchors at 1 after unavailable days. T3/T5 overlapping terminal outcomes are never compounded.",
    "style_proxy": "CircMV > RMB 50bn AND (D-inclusive trailing 20-session PIT turnover <1.5% or trailing 20-session QFQ amplitude <3%). Style proxy only.",
    "regime": "Exact-date official eligible all-A equal-weight closes/previous closes compounded over five sessions ending at D. Up >=1%, down <=-1%, else flat; any missing session gives UNKNOWN.",
    "availability": "D+1 outcome cutoff 20261123. First 40 include 7 on or before frozen training cutoff. Recent 20 informed ACT032 rule selection. Earlier post-fit retrospectively replayed with frozen weights.",
}


def opening_outcome(code, quote, gap_gate=False):
    assessment = act031.opening_assessment(code, quote)
    can_buy = assessment["opening_buyable_proxy"]
    gap = None
    if quote and act031.positive(quote.get("open")) and act031.positive(quote.get("prev_close")):
        gap = quote["open"] / quote["prev_close"] - 1
    if can_buy is True and gap_gate and not gates.lte(gap, B2_GAP_MAX):
        return False, "D1_B2_GAP_GT_5_PERCENT", gap
    return can_buy, assessment["opening_status"], gap


def selling_outcome(code, quote):
    if quote is None:
        return None, "EXIT_QUOTE_MISSING"
    if not quote["eligible_for_daily_gain_rank"]:
        return (False, "EXIT_NO_VOLUME") if quote.get("zero_volume") else (None, "EXIT_INVALID_BAR")
    band, previous = act031.inferred_band(code), act031.positive(quote.get("prev_close"))
    if band is None or previous is None or act031.special_treatment(quote.get("name")) is not False:
        return None, "EXIT_STANDARD_CAP_INPUT_UNKNOWN"
    floor = float((Decimal(str(previous)) * (1 - Decimal(band))).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    if quote["low"] < floor - 1e-6:
        return None, "EXIT_STANDARD_CAP_EXCEPTION"
    return (False, "EXIT_CLOSE_AT_LOWER_CAP") if quote["close"] <= floor + 1e-6 else (True, "EXIT_MODELED_CLOSE")


def load_prior_outcomes(inputs):
    refs = inputs["prior_act031"]
    source = act031.read_ref(refs["outcome_receipt"])
    if (source.get("signal_seal") != refs["signal_seal"] or source.get("input") != refs["inputs"]
            or source.get("outcome_cutoff") != replay.CUTOFF
            or source.get("evaluated_signal_days") != inputs["signal_dates"][-replay.RECENT_COUNT:]
            or source.get("fit_calls") != replay.FIT_CALLS):
        raise replay.ContractError("ACT033A_PRIOR_OUTCOME_IDENTITY_OR_CUTOFF_MISMATCH")
    fields = ["trade_date", "ts_code", "d1_date", "d1_top200_label_source", "d1_top200_rank", "d1_top200_hit",
              "d1_modeled_open_close_return",
              *[f"t{n}_{suffix}" for n in (3, 5) for suffix in ("date", "mature", "modeled_open_close_return")]]
    frame = pd.read_parquet(replay.checked(source["artifacts"]["rows"]), columns=fields)
    if (frame.duplicated(["trade_date", "ts_code"]).any()
            or sorted(frame.trade_date.unique()) != source["evaluated_signal_days"]):
        raise replay.ContractError("ACT033A_PRIOR_OUTCOME_ROSTER_DRIFT")
    return source, {day: part for day, part in frame.groupby("trade_date", sort=False)}


def numeric(value):
    return gates.finite(value)


def daily_execution(frame, observation_tail, observations):
    """Reuse ACT031 returns, apply the entry proxy, and retain exit impairments."""
    outcome = frame.copy()
    d1_quotes = observations[observation_tail[0]]["quotes"]
    proxies = [opening_outcome(code, d1_quotes.get(code)) for code in outcome.ts_code]
    outcome["opening_fillable"] = pd.array([row[0] for row in proxies], dtype="boolean")
    outcome["opening_status"] = [row[1] for row in proxies]
    outcome["opening_gap"] = [row[2] for row in proxies]
    outcome["exit_t1_status"] = "D1_CLOSE_MTM_T_PLUS_1"
    outcome["t1_gross"] = outcome.d1_modeled_open_close_return.where(outcome.opening_fillable.eq(True))
    for horizon in (3, 5):
        key = f"t{horizon}"
        if len(observation_tail) < horizon:
            outcome[f"exit_{key}_status"] = "HORIZON_IMMATURE_AT_CUTOFF"
            outcome[f"{key}_gross"] = np.nan
            continue
        quotes = observations[observation_tail[horizon - 1]]["quotes"]
        proxies = [selling_outcome(code, quotes.get(code)) for code in outcome.ts_code]
        gross = outcome[f"{key}_modeled_open_close_return"]
        outcome[f"exit_{key}_status"] = [row[1] for row in proxies]
        outcome[f"{key}_gross"] = gross.where(outcome.opening_fillable.eq(True))
    return outcome


def apply_strategy(frame, realized, day, regime, group, summary, tail):
    roster = frame.loc[frame[group]].copy()
    roster = roster.merge(realized, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
    roster["group"] = group
    roster["regime"] = regime
    roster["opening_fillable"] = roster.opening_fillable.astype("boolean")
    if group == "B1":
        gap_reject = roster.opening_fillable.fillna(False) & roster.opening_gap.gt(B2_GAP_MAX + 1e-12)
        roster.loc[gap_reject, "opening_fillable"] = False
        roster.loc[gap_reject, "opening_status"] = "D1_B2_GAP_GT_5_PERCENT"
    roster["t1_date"] = tail[0]
    daily = {"trade_date": day, "d1_date": tail[0], "regime": regime, "group": group,
             "picked_n": len(roster), "filled_n": int(roster.opening_fillable.fillna(False).sum()),
             "known_no_fill_n": int(roster.opening_fillable.eq(False).sum()),
             "open_unknown_n": int(roster.opening_fillable.isna().sum()),
             "filter_unknown_n": summary["unknown_n"],
             "dividend_proxy_n": int(roster.dividend_style_proxy.sum()),
             "dividend_proxy_known_n": int(roster.dividend_style_proxy.count())}
    # Preserve selection metrics even for explicit rank evidence gaps.
    for source, name in (("V4_OFFICIAL_TOP200", "official"), ("RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK", "fallback")):
        same_source = roster.d1_top200_label_source.eq(source)
        picked_hits = roster.loc[same_source, "d1_top200_hit"]
        filled_hits = roster.loc[same_source & roster.opening_fillable.eq(True), "d1_top200_hit"]
        daily[f"top200_{name}_n"] = int(picked_hits.count())
        daily[f"top200_{name}_hits"] = int(picked_hits.sum())
        daily[f"top200_{name}_filled_n"] = int(filled_hits.count())
        daily[f"top200_{name}_filled_hits"] = int(filled_hits.sum())
    for horizon in HORIZONS:
        key = f"t{horizon}"
        gross = realized[f"{key}_gross"]
        benchmark = gross.mean()
        roster[f"{key}_gross"] = roster[f"{key}_gross"].where(roster.opening_fillable.eq(True))
        roster[f"{key}_net"] = roster[f"{key}_gross"] - FEE
        roster[f"{key}_benchmark_gross"] = benchmark
        roster[f"{key}_excess"] = roster[f"{key}_gross"] - benchmark
        for metric in ("gross", "net", "excess"):
            daily[f"{key}_{metric}"] = numeric(roster[f"{key}_{metric}"].mean())
        daily[f"{key}_economic_n"] = int(roster[f"{key}_gross"].count())
        daily[f"{key}_benchmark_n"] = int(gross.count())
        daily[f"{key}_benchmark_gross"] = numeric(benchmark)
        daily[f"{key}_mature"] = len(tail) >= horizon
        if horizon != 1 and f"exit_{key}_status" in roster:
            impaired = roster[f"exit_{key}_status"].isin(("EXIT_NO_VOLUME", "EXIT_CLOSE_AT_LOWER_CAP"))
            unknown = roster[f"exit_{key}_status"].isin(("EXIT_QUOTE_MISSING", "EXIT_INVALID_BAR",
                                                       "EXIT_STANDARD_CAP_INPUT_UNKNOWN", "EXIT_STANDARD_CAP_EXCEPTION"))
            daily[f"{key}_filled_exit_impaired_n"] = int((roster.opening_fillable.eq(True) & impaired).sum())
            daily[f"{key}_filled_exit_unknown_n"] = int((roster.opening_fillable.eq(True) & unknown).sum())
    if summary["unknown_n"]:
        daily["status"] = "PARTIAL_FILTER_EVIDENCE"
    elif daily["open_unknown_n"] or daily["filled_n"] != daily["t1_economic_n"]:
        daily["status"] = "PARTIAL_OPEN_OR_MTM_EVIDENCE"
    else:
        daily["status"] = "EVALUATED"
    nav_usable = (daily["status"] == "EVALUATED"
                  and daily["open_unknown_n"] == 0 and daily["filled_n"] == daily["t1_economic_n"])
    daily["t1_costed_mtm_cash_weighted"] = (0.0 if not len(roster) else float(roster.t1_net.sum() / len(roster))) if nav_usable else None
    daily["t1_gross_mtm_cash_weighted"] = (0.0 if not len(roster) else float(roster.t1_gross.sum() / len(roster))) if nav_usable else None
    return roster, daily


def nav_curve(day_rows, dates):
    curves = []
    for group in gates.ALL_GROUPS:
        cohort = day_rows.loc[day_rows.group.eq(group)].set_index("trade_date")
        active, peak, segment = None, None, 0
        recent_nav, recent_peak = 1.0, 1.0
        for date in dates:
            row = cohort.loc[date]
            move = numeric(row.get("t1_costed_mtm_cash_weighted"))
            if move is None:
                active, peak = None, None
            else:
                if active is None:
                    active, peak, segment = 1.0, 1.0, segment + 1
                active *= 1 + move
                peak = max(peak, active)
            recent_drawdown = None
            if date in dates[-replay.RECENT_COUNT:]:
                recent_nav = None if recent_nav is None or move is None else recent_nav * (1 + move)
                if recent_nav is not None:
                    recent_peak = max(recent_peak, recent_nav)
                    recent_drawdown = recent_nav / recent_peak - 1
            curves.append({"trade_date": date, "d1_date": row.get("d1_date"), "group": group, "status": row.status,
                           "t1_costed_mtm_cash_weighted": move,
                           "known_segment": segment if active is not None else None,
                           "t1_costed_mtm_segment_nav": active,
                           "t1_costed_mtm_segment_drawdown": active / peak - 1 if active is not None else None,
                           "recent20_t1_costed_mtm_nav": recent_nav if date in dates[-replay.RECENT_COUNT:] else None,
                           "recent20_t1_costed_mtm_drawdown": recent_drawdown})
    return pd.DataFrame(curves)


def summarize(rows, daily, nav, dates):
    subsets = {
        "full60": dates,
        "early40": dates[:-replay.RECENT_COUNT],
        "early_postfit33": [d for d in dates[:-replay.RECENT_COUNT] if d > replay.TRAINING_END],
        "pre_or_on_fit7": [d for d in dates if d <= replay.TRAINING_END],
        "recent20_used_in_act032": dates[-replay.RECENT_COUNT:],
    }
    windows = {}
    for name, expected in subsets.items():
        by_regime = {}
        for regime in ("ALL", "UP", "FLAT", "DOWN", "UNKNOWN"):
            groups = {}
            for group in gates.ALL_GROUPS:
                day_rows = daily.loc[daily.trade_date.isin(expected) & daily.group.eq(group)]
                if regime != "ALL":
                    day_rows = day_rows.loc[day_rows.regime.eq(regime)]
                group_rows = rows.loc[rows.trade_date.isin(day_rows.trade_date) & rows.group.eq(group)]
                evaluated = day_rows.status.isin(["EVALUATED", "PARTIAL_FILTER_EVIDENCE", "PARTIAL_OPEN_OR_MTM_EVIDENCE"])
                unknown_days = day_rows.loc[~evaluated, "trade_date"].tolist()
                detail = {"requested_days": int(len(day_rows)), "evaluable_days": int(evaluated.sum()),
                          "unavailable_days": unknown_days, "filter_partial_days": int(day_rows.status.eq("PARTIAL_FILTER_EVIDENCE").sum()),
                          "economic_partial_days": int(day_rows.status.eq("PARTIAL_OPEN_OR_MTM_EVIDENCE").sum()),
                          "picked_n": int(len(group_rows)) if evaluated.any() else None}
                if evaluated.any():
                    detail.update({"filled_n": int(group_rows.opening_fillable.sum()),
                                   "known_unfilled_n": int(group_rows.opening_fillable.eq(False).sum()),
                                   "entry_unknown_n": int(group_rows.opening_fillable.isna().sum()),
                                   "dividend_proxy_n": int(group_rows.dividend_style_proxy.sum()),
                                   "dividend_proxy_known_n": int(group_rows.dividend_style_proxy.count())})
                    for label in ("official", "fallback"):
                        detail[f"top200_{label}_n"] = int(day_rows[f"top200_{label}_n"].sum())
                        detail[f"top200_{label}_hits"] = int(day_rows[f"top200_{label}_hits"].sum())
                        detail[f"top200_{label}_filled_n"] = int(day_rows[f"top200_{label}_filled_n"].sum())
                        detail[f"top200_{label}_filled_hits"] = int(day_rows[f"top200_{label}_filled_hits"].sum())
                    for n in (3, 5):
                        for state in ("impaired", "unknown"):
                            field = f"t{n}_filled_exit_{state}_n"
                            detail[field] = int(day_rows[field].sum())
                for n in HORIZONS:
                    key = f"t{n}"
                    for metric in ("gross", "net", "excess"):
                        values = group_rows[f"{key}_{metric}"]
                        count = int(values.count())
                        detail[f"{key}_mean_{metric}"] = numeric(values.mean())
                        detail[f"{key}_{metric}_n"] = count if evaluated.any() else None
                        detail[f"{key}_{metric}_win_rate"] = float(values.gt(0).sum() / count) if count else None
                        if metric == "net":
                            detail[f"{key}_median_net"] = numeric(values.median())
                for metric in ("gross", "net"):
                    count = detail[f"t5_{metric}_n"]
                    tail_n = int(group_rows[f"t5_{metric}"].lt(-.10).sum()) if count else None
                    detail[f"t5_{metric}_below_minus_10_n"] = tail_n
                    detail[f"t5_{metric}_below_minus_10_rate"] = tail_n / count if count else None
                if regime == "ALL" and name == "recent20_used_in_act032":
                    nav_rows = nav.loc[nav.group.eq(group) & nav.trade_date.isin(expected)]
                    detail["recent20_t1_nav_terminal"] = numeric(nav_rows.recent20_t1_costed_mtm_nav.iloc[-1])
                    detail["recent20_t1_mtm_max_drawdown"] = (numeric(nav_rows.recent20_t1_costed_mtm_drawdown.min())
                                                              if detail["recent20_t1_nav_terminal"] is not None else None)
                groups[group] = detail
            by_regime[regime] = groups
        windows[name] = by_regime
    return windows


def outcome_phase(inputs, input_ref, sessions, output):
    seal_path = output / "signals" / "SEAL.json"
    if not seal_path.is_file():
        raise replay.ContractError("ACT033A_SIGNALS_MUST_BE_SEALED_BEFORE_OUTCOMES")
    seal, records = replay.seal_records(inputs, input_ref, seal_path)
    seal_ref = act031.ref(seal_path)
    receipt_path = output / "REPLAY_RECEIPT.json"
    if receipt_path.is_file():
        existing = act031.read_ref(act031.ref(receipt_path))
        if existing.get("signal_seal") != seal_ref or existing.get("input") != input_ref:
            raise replay.ContractError("ACT033A_EXISTING_OUTCOME_IDENTITY_CHANGED")
        for reference in existing["artifacts"].values():
            replay.checked(reference)
        return existing
    prior_receipt, prior_by_day = load_prior_outcomes(inputs)
    dates, observations, sources = inputs["signal_dates"], inputs["observation_dates"], inputs["days"]
    available = seal["evaluable_days"]
    if not available:
        raise replay.ContractError("ACT033A_NO_EVALUABLE_SIGNAL_DAYS")
    observation_start = observations.index(available[0]) + 1
    obs = {}
    early_days = [date for date in available if date not in prior_by_day]
    early_d1 = {observations[observations.index(date) + 1] for date in early_days}
    for date in observations[observation_start:]:
        quotes, identity = act031.day_quotes(date, sources[date])
        ranks, rank_source = act031.rank_for_day(date, sources[date], quotes) if date in early_d1 else ({}, None)
        obs[date] = {"quotes": quotes or {}, "quote_identity": identity, "ranks": ranks, "rank_source": rank_source}
    prices = cutoff_identity = None
    if early_days:
        rosters = {day: pd.read_parquet(replay.checked(records[day]["eligible_all_a"])) for day in early_days}
        scope = set().union(*(set(frame.ts_code) for frame in rosters.values()))
        bound = act031.existing_panel(replay.CUTOFF, sources[replay.CUTOFF])
        if bound is not None and scope:
            raw = act031.read_panel(bound, early_days[0], replay.CUTOFF, ("open", "close", "vol", "tradeable_basic"), codes=scope)
            usable = raw.tradeable_basic.eq(1) & raw.vol.gt(0) & raw.open.gt(0) & raw.close.gt(0)
            prices = raw.loc[usable].pivot(index="ts_code", columns="trade_date", values="close")
            cutoff_identity = {"source": sources[replay.CUTOFF], "projected_rows": len(raw), "usable_rows": int(usable.sum())}
    all_rows, daily_rows = [], []
    for index, day in enumerate(dates):
        regime = seal["regimes"][day]["name"]
        tail = observations[index + 1:index + 6]
        record = records[day]
        if day in available:
            selection = pd.read_parquet(replay.checked(record["groups"]))
            start = prior_by_day.get(day)
            if start is None:
                start = act031.day_forward(rosters[day].assign(trade_date=day), day, observations, obs, prices)
            if not set(selection.ts_code) <= set(start.ts_code):
                raise replay.ContractError(f"ACT033A_OUTCOME_SIGNAL_KEYS_NOT_BOUND:{day}")
            realized = daily_execution(start, tail, obs)
        for group in gates.ALL_GROUPS:
            if day not in available:
                daily_rows.append({"trade_date": day, "d1_date": tail[0], "group": group, "regime": regime,
                                   "status": "CANNOT_CONFIRM_EXACT_D", "reason": record["reason"]})
            elif group in ("C1", *gates.C1_ARMS):
                unknown = record["eligibility"]["groups"][group]["unknown_n"]
                daily_rows.append({"trade_date": day, "d1_date": tail[0], "group": group, "regime": regime,
                                   "status": "UNDETERMINED_C1", "reason": "MISSING_EXECUTABLE_P5_15_LIQUIDITY_AND_VETO_CONTRACT",
                                   "filter_unknown_n": unknown})
            else:
                rows, metrics = apply_strategy(selection, realized, day, regime, group,
                                               record["eligibility"]["groups"][group], tail)
                all_rows.append(rows)
                daily_rows.append(metrics)
    rows = pd.concat(all_rows, ignore_index=True)
    daily = pd.DataFrame(daily_rows)
    nav = nav_curve(daily, dates)
    latest = daily.loc[daily.trade_date.eq(dates[-1])].copy()
    artifacts = {"trades": act031.frame_atomic(output / "TRADE_ROWS.parquet", rows),
                 "daily": act031.frame_atomic(output / "DAILY_METRICS.csv", daily),
                 "nav": act031.frame_atomic(output / "DAILY_MTM_NAV.csv", nav),
                 "latest": act031.frame_atomic(output / "LATEST_20261120.csv", latest),
                 "metrics": act031.json_atomic(output / "METRICS.json", {
                     "schema": replay.SCHEMA, "outcome_cutoff": replay.CUTOFF, "fit_calls": replay.FIT_CALLS,
                     "status": "PARTIAL", "evaluable_days": available, "unavailable_days": seal["unavailable_days"],
                     "training_overlap": [day for day in dates if day <= replay.TRAINING_END],
                     "recent20_exposure": "USED_TO_DEFINE_ACT032_RULES",
                     "regimes": seal["regimes"], "outcome_conventions": OUTCOME_POLICY,
                     "split_metrics": summarize(rows, daily, nav, dates), **act031.FLAGS}),
                 }
    receipt = {"schema": replay.SCHEMA, "status": "ACT033A_PARTIAL", "input": input_ref, "signal_seal": seal_ref,
               "prior_outcome_reuse": inputs["prior_act031"]["outcome_receipt"],
               "prior_cutoff_qfq": prior_receipt["cutoff_qfq"], "new_cutoff_qfq": cutoff_identity,
               "evaluable_days": available, "unavailable_days": seal["unavailable_days"], "expected_days": len(dates),
               "groups": list(gates.GROUPS), "outcome_conventions": OUTCOME_POLICY, "fit_calls": replay.FIT_CALLS,
               "outcome_quote_evidence": {day: item["quote_identity"] for day, item in obs.items()},
               "new_top200_outcome_evidence": {day: obs[day]["rank_source"] for day in early_d1},
               "artifacts": artifacts, **act031.FLAGS}
    act031.json_atomic(receipt_path, receipt)
    return receipt
