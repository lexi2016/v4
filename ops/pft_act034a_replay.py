"""Evaluate ACT-034A on the 21 already-frozen ACT-033A signal days."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import resource
from statistics import mean, median
import sys
from time import perf_counter

import pandas as pd

from ops import pft_act031_frozen_forward as act031
from ops import pft_act033a_groups as gates
from ops import pft_act033a_outcomes as previous_outcomes
from ops import pft_act033a_replay as previous
from ops import pft_act034a_rules as rules
from ops import research_panel_qfq as qfq

SCHEMA = "pft.act034a.research_replay.v1"
CUTOFF = rules.CUTOFF
PARENT_INPUT_SHA = "79911801a49564abb45ba839aa37023d8ffe4a01cafc380456aa7363c003793e"
PARENT_SEAL_SHA = "c341711a8db5f1aaf87fd5872bf7e6992ed94e81fcc28874b437b1f76c1cde7d"
PARENT_OUTCOME_SHA = "ed4f8803249ef1d11dae151e07860cba18fa009990dae30c6c4de9df5c6f15ff"
EXPECTED_FIRST, EXPECTED_LAST = "20261023", "20261120"
STRATEGIES = ("A1_EXIT", "B2_QUICK")
HORIZONS = (3, 5)
FIXED_FIELDS = ("trade_date", "ts_code", "group", "t3_gross", "t5_gross", "exit_t3_status", "exit_t5_status")
POLICY = {
    "sample": "Only the 21 ACT033A already-sealed days; 39 original unavailable days remain unscanned. The recent 20 informed prior ACT032 rules.",
    "A1_EXIT": "Original ACT033A A1 selections. Any known held-close invalidation, gross cost loss >=7%, or D+1 raw O2C <=-3% queues next-session open. T3 close unless positive gross and cutoff-QFQ close >= exact five-session MA5. An earlier queue takes precedence over T5, otherwise T5 hard close even with a same-close stop. All execution attempts end by T5 and cutoff.",
    "B2_QUICK": "Top5 by golden pure-head priority (cushion <=10%), then projected p descending (missing last) and symbol ascending. No p or stage gate for exact pure-head arm. D+1 official high/previous >=4% with close below upper cap, or official close/previous <=-3%, queues T2 open; otherwise T3 close. Attempts end by T3 and cutoff.",
    "C1": "Apply separately to the frozen A1 and B2 rosters, without refill. Exclude known D amount <100m CNY, five-session D QFQ return >15%, or D raw upper wick >3.5% of official previous close. Unresolved required C1 inputs are unknown unless a known veto determines rejection.",
    "B2_missing_finance": "Only joint known float cap >50bn and D-inclusive 20-session mean amplitude <3% vetoes. Either missing value alone leaves the candidate eligible on this atom.",
    "entry": "D+1 open, identical ACT031 raw standard-cap proxy, then require verified cutoff-basis fill price for economics. No B1 gap veto. No refill.",
    "sell": "ACT033A raw conservative closing proxy and analogous lower-cap opening proxy. On an impeded initial attempt, retry only at following opens through the original arm deadline and cutoff. T3 conditional close is a modeled closing-price convention using that same close and MA5.",
    "price": "Scoped V4 cutoff QFQ panel. Validate attributable open/close/low fields independently against dated raw official bars transformed by the cutoff snapshot. Rebase the frozen D anchor by events strictly after D and verify D close against official raw transformed to cutoff.",
    "fixed_t3_t5": "Fixed ACT033A A1 marks are reused with their original path completeness. B2 fixed marks use the same raw D1 O2C times cutoff-QFQ close continuation, requiring a contiguous valid path. Executable fixed samples require the exact terminal close sell proxy and validated cutoff-basis price.",
    "path_risk": "Minimum observed adjusted low from entry through close exit or the open print alone on an open exit. If unresolved, observations are bounded by the arm deadline, cutoff, or first unknown decision. Partial paths are counted separately. A terminal mark is never counted as a realized sale.",
    "statistics": "Trade equal-weight realized returns, 0.003 round-trip fee, win strictly positive; tail strictly below -10%. Daily pre-open weights are included for attribution. No compounding across overlapping holdings.",
}


def require(condition, problem):
    if not condition:
        raise act031.ContractError(f"ACT034A_{problem}")


def exact_ref(path, expected):
    reference = {"path": str(path), "sha256": expected}
    previous.checked(reference)
    return reference


def load_seal(root):
    run = root / "run"
    input_ref = exact_ref(root / "ACT033A_FROZEN_INPUTS.json", PARENT_INPUT_SHA)
    seal_ref = exact_ref(run / "signals" / "SEAL.json", PARENT_SEAL_SHA)
    inputs, seal = act031.read_ref(input_ref), act031.read_ref(seal_ref)
    dates, sessions = seal["evaluable_days"], inputs["observation_dates"]
    require(
        seal["input"] == input_ref and seal["fit_calls"] == previous.FIT_CALLS
        and seal["observations_opened_in_signal_phase"] is False
        and inputs["cutoff"] == sessions[-1] == CUTOFF
        and len(dates) == 21 and len(seal["unavailable_days"]) == 39
        and set(dates) | set(seal["unavailable_days"]) == set(inputs["signal_dates"])
        and dates[0] == EXPECTED_FIRST and dates[-1] == EXPECTED_LAST
        and dates == sessions[sessions.index(EXPECTED_FIRST):-1],
        "UPSTREAM_SCOPE_OR_SEAL_DRIFT",
    )
    return inputs, seal, input_ref, seal_ref


def select_rosters(inputs, seal):
    pieces, quotes_by_day, daily = [], {}, {}
    reference_by_day = {}
    for day in seal["evaluable_days"]:
        source = inputs["days"][day]
        checkpoint = act031.read_ref(seal["daily_receipts"][day])
        require(
            checkpoint["trade_date"] == day and checkpoint["input_source"] == source
            and checkpoint["plan"] == seal["plan"] and checkpoint["status"] == "SIGNALS_FROZEN",
            f"CHECKPOINT_IDENTITY_DRIFT:{day}",
        )
        reference_by_day[day] = checkpoint["groups"]
        frame = pd.read_parquet(previous.checked(checkpoint["groups"]))
        require(
            not frame.empty and not frame.ts_code.duplicated().any()
            and frame.trade_date.eq(day).all() and frame.feature_context_end.dropna().eq(day).all(),
            f"CHECKPOINT_ROSTER_DRIFT:{day}",
        )
        quotes, identity = act031.day_quotes(day, source)
        require(quotes is not None and identity == checkpoint["source_quotes"], f"D_RAW_QUOTE_DRIFT:{day}")
        quotes_by_day[day] = (quotes, identity)
        atoms = [rules.selection_atoms(row, rules.upper_wick(quotes.get(row.ts_code)))
                 for row in frame.itertuples(index=False)]
        frame = pd.concat([frame, pd.DataFrame.from_records(atoms)], axis=1)
        a1 = frame.loc[frame.A1.eq(True)].sort_values("A1_rank").copy()
        require(len(a1) == checkpoint["eligibility"]["groups"]["A1"]["selected_n"], f"A1_ROSTER_DRIFT:{day}")
        a1["strategy"], a1["selection_rank"] = "A1_EXIT", a1.A1_rank
        eligible = frame.loc[frame.b2_eligible.eq(True)]
        ranked = eligible.sort_values(["b2_golden_priority", "projected_p_s", "ts_code"],
                                     ascending=[False, False, True], na_position="last")
        b2 = ranked.head(5).copy()
        b2["strategy"], b2["selection_rank"] = "B2_QUICK", range(1, len(b2) + 1)
        for strategy_rows in (a1, b2):
            strategy_rows["preopen_equal_weight"] = 1 / len(strategy_rows) if len(strategy_rows) else None
            kept = strategy_rows.c1_pass.eq(True)
            strategy_rows["c1_preopen_equal_weight"] = None
            if kept.any():
                strategy_rows.loc[kept, "c1_preopen_equal_weight"] = 1 / int(kept.sum())
            pieces.append(strategy_rows)
        structural = frame.loc[frame.b2_structural.eq(True)]
        daily[day] = {
            "a1_selected_n": len(a1),
            "b2_structurally_eligible_n": len(structural),
            "b2_structural_unknown_n": int(frame.b2_structural.isna().sum()),
            "b2_eligible_n": len(eligible),
            "b2_filter_unknown_n": int(structural.b2_eligible.isna().sum()),
            "b2_slow_dividend_veto_n": int(structural.b2_slow_dividend_veto.sum()),
            "b2_eligible_missing_float_cap_n": int(eligible.b2_missing_float_cap.sum()),
            "b2_eligible_by_arm": dict(Counter(eligible.b2_arm)),
            "b2_selected_n": len(b2),
            "b2_selected_by_arm": dict(Counter(b2.b2_arm)),
        }
    rosters = pd.concat(pieces, ignore_index=True)
    require(int(rosters.strategy.eq("A1_EXIT").sum()) == 66, "ORIGINAL_A1_66_REQUIRED")
    # Persist only the selected D-only rows, in upstream source or new rank order.
    fields = [
        "trade_date", "ts_code", "name", "strategy", "selection_rank", "preopen_equal_weight", "c1_preopen_equal_weight",
        "final_state", "stage", "route_reasons", "main_tactic", "projected_p_s", "anchor_age_calendar_days",
        "invalidation_anchor_date", "invalidation_price", "close_d", "cushion", "vol_d", "vol_ma5_d",
        "return_d", "raw_bullish", "d_upper_wick", "amplitude_ma20", "float_mv_d_cny", "amount_d_cny", "return_5d",
        "b2_d_volume_ma5_ratio", "b2_arm", "b2_golden_priority", "b2_missing_float_cap",
        "b2_slow_dividend_inputs_complete", "c1_pass", "c1_veto_reasons", "c1_unknown_atoms",
    ]
    return rosters[fields], quotes_by_day, daily, reference_by_day


def read_cutoff(inputs, rosters, calendar):
    source = inputs["days"][CUTOFF]
    bound = act031.existing_panel(CUTOFF, source)
    require(bound is not None, "CUTOFF_PANEL_MISSING")
    receipt = act031.read_ref(source["producer_ref"])
    ref = receipt["adjustment_snapshot"]
    snapshot = act031.read_ref(ref)
    require(
        ref["sha256"] == receipt.get("snapshot_file_sha256")
        and qfq.canonical_sha(snapshot) == receipt.get("input_sha256")
        and snapshot.get("schema") in {"a_share_qfq_adjustment_input_v1", "a_share_qfq_adjustment_input_research_cache_v1"}
        and snapshot.get("asof_date") == snapshot.get("coverage_end_date") == int(CUTOFF)
        and snapshot.get("price_basis") == "QFQ_ASOF",
        "CUTOFF_SNAPSHOT_SCOPE_OR_IDENTITY_DRIFT",
    )
    start, _ = previous.previous_days(calendar.schedule, EXPECTED_FIRST, 1)
    panel = act031.read_panel(bound, start, CUTOFF, ("open", "close", "low", "vol", "tradeable_basic"),
                             codes=set(rosters.ts_code))
    bars = {code: group.set_index("trade_date").to_dict("index")
            for code, group in panel.groupby("ts_code", sort=False)}
    events = {code: rules.affine_events(snapshot["symbols"].get(code), day)
              for code, day in rosters.groupby("ts_code").trade_date.min().items()}
    return bars, events, start, {"panel": source, "adjustment_snapshot": ref, "rows": len(panel),
                                  "start": start, "end": CUTOFF, "price_tolerance": rules.PRICE_TOLERANCE}


def read_observations(inputs, observed, scope):
    observations = {}
    for day in inputs["observation_dates"][inputs["observation_dates"].index(EXPECTED_FIRST) + 1:]:
        quotes, identity = observed[day] if day in observed else act031.day_quotes(day, inputs["days"][day])
        ranks, rank_source = act031.rank_for_day(day, inputs["days"][day], quotes)
        observations[day] = {
            "quotes": {code: quote for code, quote in (quotes or {}).items() if code in scope},
            "quote_identity": identity, "ranks": ranks, "rank_source": rank_source,
            "rank_ref": inputs["days"][day].get("rank_ref"),
        }
    return observations


def prior_fixed(root, input_ref, seal_ref, cutoff_source, dates, rosters):
    path = root / "run" / "REPLAY_RECEIPT.json"
    ref = exact_ref(path, PARENT_OUTCOME_SHA)
    receipt = act031.read_ref(ref)
    require(receipt["input"] == input_ref and receipt["signal_seal"] == seal_ref
            and receipt["evaluable_days"] == dates and receipt["fit_calls"] == previous.FIT_CALLS
            and receipt["prior_cutoff_qfq"]["asof_date"] == CUTOFF
            and receipt["prior_cutoff_qfq"]["input"] == cutoff_source
            and receipt["new_cutoff_qfq"]["source"] == cutoff_source,
            "ACT033A_FIXED_OUTCOMES_IDENTITY_DRIFT")
    trade_ref = receipt["artifacts"]["trades"]
    original = pd.read_parquet(previous.checked(trade_ref), columns=list(FIXED_FIELDS))
    original = original.loc[original.group.eq("A1")].set_index(["trade_date", "ts_code"])
    a1 = rosters.loc[rosters.strategy.eq("A1_EXIT")].set_index(["trade_date", "ts_code"])
    require(len(original) == len(a1) and not original.index.has_duplicates
            and set(original.index) == set(a1.index), "ACT033A_FIXED_A1_ROSTER_DRIFT")
    return original.to_dict("index"), {"receipt": ref, "trades": trade_ref}


def fixed_comparisons(row, dates, quotes, prices, entry, original):
    fields = {}
    for horizon in HORIZONS:
        key = f"t{horizon}"
        target = dates[horizon - 1] if len(dates) >= horizon else None
        end_close = prices.get(target, {}).get("close")
        executable, status = (previous_outcomes.selling_outcome(row.ts_code, quotes.get(target))
                              if target else (None, "HORIZON_IMMATURE_AT_CUTOFF"))
        if entry is not None and executable is True and end_close is None:
            executable, status = None, "EXIT_PRICE_BASIS_UNCONFIRMED"
        fixed_exec = end_close / entry - 1 if entry is not None and executable is True else None
        if original is not None:
            mark = gates.finite(original[f"{key}_gross"])
            mark_status = original[f"exit_{key}_status"]
        else:
            mark = None
            mark_status = status
            closes = [prices.get(date, {}).get("close") for date in dates[:horizon]]
            d1_o2c = rules.raw_ratio(quotes.get(dates[0]), "close", "open")
            if entry is not None and target and None not in closes and d1_o2c is not None:
                mark = (1 + d1_o2c) * closes[-1] / closes[0] - 1
        fields.update({
            f"fixed_{key}_date": target,
            f"fixed_{key}_mark_gross": mark,
            f"fixed_{key}_mark_net": mark - rules.FEE if mark is not None else None,
            f"fixed_{key}_mark_exit_status": mark_status,
            f"fixed_{key}_executable_gross": fixed_exec,
            f"fixed_{key}_executable_net": fixed_exec - rules.FEE if fixed_exec is not None else None,
            f"fixed_{key}_exit_status": status,
        })
    return fields


def evaluate_row(row, observations, observed, bars, events, calendar, original):
    day, code, strategy = row.trade_date, row.ts_code, row.strategy
    position = calendar.index(day)
    forward = calendar[position + 1:]
    # Fixed comparisons require five sessions; dynamic deadlines remain arm-specific.
    relevant = forward[:5]
    d1 = relevant[0]
    quotes = {date: observations[date]["quotes"][code] for date in relevant if code in observations[date]["quotes"]}
    prices, evidence = {}, {}
    for date in relevant:
        prices[date], evidence[date] = rules.verified_bar(bars.get(date), quotes.get(date), date, events)
    d_quote = observed[day][0].get(code)
    d_bar, d_status = rules.verified_bar(bars.get(day), d_quote, day, events)
    rebased_close = rules.to_cutoff_basis(row.close_d, day, events)
    anchor_compatible = rules.same_price(d_bar.get("close"), rebased_close)
    anchor = rules.to_cutoff_basis(row.invalidation_price, day, events) if anchor_compatible else None
    price_path = {date: price["close"] for date, price in prices.items() if "close" in price}
    if anchor_compatible:
        price_path[day] = d_bar["close"]
    prior_day = calendar[position - 1]
    # Only D-1 can precede the signal day in the exact five-session T3 MA.
    prior_bar = bars.get(prior_day, {})
    if prior_bar.get("tradeable_basic") == 1 and act031.positive(prior_bar.get("vol")) is not None:
        price_path[prior_day] = act031.positive(prior_bar.get("close"))
    assessment = act031.opening_assessment(code, quotes.get(d1))
    opening = assessment["opening_buyable_proxy"]
    entry = prices[d1].get("open") if opening is True else None
    if entry is not None:
        if strategy == "A1_EXIT":
            result = rules.a1_exit(code, relevant, calendar, quotes, prices, entry, anchor, price_path)
        else:
            result = rules.b2_exit(code, relevant, quotes, prices)
        path = rules.path_low(relevant[:5 if strategy == "A1_EXIT" else 3], prices, result, entry)
    else:
        reason = "ENTRY_PRICE_BASIS_UNCONFIRMED" if opening is True else assessment["opening_status"]
        status = "KNOWN_UNFILLED_ENTRY" if opening is False else "ENTRY_UNCONFIRMED"
        result = rules.ExitOutcome(reason, status=status)
        path = {"worst_observed_path_gross": None, "path_sessions": 0, "path_observed_sessions": 0, "path_complete": None}
    gross = result.price / entry - 1 if result.price is not None else None
    exit_fields = asdict(result)
    rank = observations[d1]["ranks"].get(code)
    rank_source = observations[d1]["rank_source"]
    d1_move = rules.raw_ratio(quotes.get(d1), "close", "prev_close")
    know_rank = rank_source == "V4_OFFICIAL_TOP200" or (
        rank_source == "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK" and d1_move is not None)
    return {
        **row._asdict(), "d1_date": d1, "d1_raw_high_over_prev_close": rules.raw_ratio(quotes.get(d1), "high", "prev_close"),
        "d1_raw_close_over_prev_close": d1_move,
        "d1_raw_open_to_close": rules.raw_ratio(quotes.get(d1), "close", "open"),
        "d1_opening_gap": rules.raw_ratio(quotes.get(d1), "open", "prev_close"),
        "d1_top200_rank": rank, "d1_top200_rank_source": rank_source, "d1_top200_hit": rank is not None if know_rank else None,
        "opening_fillable_proxy": opening, "opening_status": assessment["opening_status"], "entry_basis_price": entry,
        "entry_time": "OPEN" if entry is not None else None,
        "a1_anchor_cutoff_qfq": anchor if strategy == "A1_EXIT" else None,
        "qfq_d_anchor_alignment": "VERIFIED" if anchor_compatible else d_status if not d_bar else "D_CLOSE_BASIS_UNCONFIRMED",
        "qfq_post_d_event_count": sum(int(day) < event[0] for event in events) if events is not None else None,
        "qfq_outcome_bars": json.dumps(evidence, separators=(",", ":")),
        "exit_reason": exit_fields.pop("reason"), "exit_status": exit_fields.pop("status"),
        "exit_signal_date": exit_fields.pop("signal_date"), "exit_time": exit_fields.pop("time"),
        "exit_basis_price": exit_fields.pop("price"),
        "exit_planned_time": exit_fields.pop("planned_time"),
        "exit_attempts": json.dumps(exit_fields.pop("attempts"), separators=(",", ":")),
        "exit_delay_sessions": (calendar.index(result.exit_date) - calendar.index(result.attempts[0]["date"])
                                if result.exit_date else None),
        "dynamic_gross": gross, "dynamic_net": gross - rules.FEE if gross is not None else None,
        "unrealized_deadline_mark_gross": result.cutoff_mark / entry - 1 if result.cutoff_mark is not None else None,
        **exit_fields, **path,
        **fixed_comparisons(row, relevant, quotes, prices, entry, original),
    }


def return_metrics(rows, prefix):
    values = [(row, row[f"{prefix}_gross"], row[f"{prefix}_net"])
              for row in rows if row[f"{prefix}_net"] is not None]
    n = len(values)
    if not n:
        return {"n": 0, "mean_gross": None, "mean_net": None, "median_net": None, "gross_win_rate": None,
                "net_win_rate": None, "gross_below_minus_10_n": None, "gross_below_minus_10_rate": None,
                "net_below_minus_10_n": None, "net_below_minus_10_rate": None, "worst_trade": None}
    gross = [value[1] for value in values]
    net = [value[2] for value in values]
    worst_row, worst_gross, worst_net = min(values, key=lambda x: x[2])
    gross_tail = sum(x < -.10 - rules.EPS for x in gross)
    net_tail = sum(x < -.10 - rules.EPS for x in net)
    return {
        "n": n, "mean_gross": mean(gross), "mean_net": mean(net), "median_net": median(net),
        "gross_win_rate": sum(x > rules.EPS for x in gross) / n, "net_win_rate": sum(x > rules.EPS for x in net) / n,
        "gross_below_minus_10_n": gross_tail, "gross_below_minus_10_rate": gross_tail / n,
        "net_below_minus_10_n": net_tail, "net_below_minus_10_rate": net_tail / n,
        "worst_trade": {"date": worst_row["trade_date"], "symbol": worst_row["ts_code"],
                        "gross": worst_gross, "net": worst_net},
    }


def paired(rows, baseline):
    common = [row for row in rows if row["dynamic_net"] is not None and row[f"{baseline}_net"] is not None]
    dynamic, fixed = return_metrics(common, "dynamic"), return_metrics(common, baseline)
    n = len(common)
    return {
        "n": n, "dynamic": dynamic, "fixed": fixed,
        "net_mean_difference": dynamic["mean_net"] - fixed["mean_net"] if n else None,
        "tail_rate_difference": dynamic["net_below_minus_10_rate"] - fixed["net_below_minus_10_rate"] if n else None,
        "net_win_rate_difference": dynamic["net_win_rate"] - fixed["net_win_rate"] if n else None,
    }


def path_metrics(rows):
    visible = [row for row in rows if row["worst_observed_path_gross"] is not None]
    complete = [row for row in visible if row["path_complete"]]
    marks = [row["unrealized_deadline_mark_gross"] for row in rows if row["unrealized_deadline_mark_gross"] is not None]
    worst = min(visible, key=lambda row: row["worst_observed_path_gross"]) if visible else None
    return {
        "observed_n": len(visible), "complete_path_n": len(complete), "partial_path_n": len(visible) - len(complete),
        "worst_observed_low": ({"date": worst["trade_date"], "symbol": worst["ts_code"],
                                "gross": worst["worst_observed_path_gross"],
                                "exit_status": worst["exit_status"], "path_complete": worst["path_complete"]}
                               if worst else None),
        "unrealized_deadline_mark_n": len(marks), "unrealized_deadline_mark_worst_gross": min(marks) if marks else None,
    }


def cohort_metrics(rows):
    rank = {}
    for source in ("V4_OFFICIAL_TOP200", "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"):
        observed = [row for row in rows if row["d1_top200_rank_source"] == source and row["d1_top200_hit"] is not None]
        rank[source] = {"observed": len(observed), "hits": sum(row["d1_top200_hit"] for row in observed)}
    comparisons = {}
    for horizon in HORIZONS:
        for basis in ("mark", "executable"):
            key = f"fixed_t{horizon}_{basis}"
            comparisons[key] = {"separate": return_metrics(rows, key), "matched": paired(rows, key)}
    return {
        "picked_n": len(rows),
        "opening_proxy_true_n": sum(row["opening_fillable_proxy"] is True for row in rows),
        "opening_proxy_false_n": sum(row["opening_fillable_proxy"] is False for row in rows),
        "opening_proxy_unknown_n": sum(row["opening_fillable_proxy"] is None for row in rows),
        "verified_entry_price_n": sum(row["entry_basis_price"] is not None for row in rows),
        "exit_status_counts": dict(Counter(row["exit_status"] for row in rows)),
        "exit_reason_counts": dict(Counter(row["exit_reason"] for row in rows)),
        "dynamic": return_metrics(rows, "dynamic"), "fixed_comparisons": comparisons,
        "path_risk": path_metrics(rows), "d1_top200_rank": rank,
    }


def summarize(details, days):
    results = {}
    for strategy in STRATEGIES:
        arm = [row for row in details if row["strategy"] == strategy]
        kept = [row for row in arm if row["c1_pass"] is True]
        before, after = cohort_metrics(arm), cohort_metrics(kept)
        b0, b1 = before["dynamic"], after["dynamic"]
        vetoed = [row for row in arm if row["c1_pass"] is False]
        results[strategy] = {
            "before_c1": before, "after_c1": after, "c1_vetoed_n": len(vetoed),
            "c1_unknown_n": len(arm) - len(kept) - len(vetoed),
            "c1_veto_reason_counts": dict(Counter(reason for row in vetoed for reason in row["c1_veto_reasons"].split("|"))),
            "c1_vetoed_dynamic": return_metrics(vetoed, "dynamic"),
            "c1_descriptive_net_mean_difference": b1["mean_net"] - b0["mean_net"] if b0["n"] and b1["n"] else None,
            "c1_descriptive_net_tail_rate_difference": (
                b1["net_below_minus_10_rate"] - b0["net_below_minus_10_rate"] if b0["n"] and b1["n"] else None),
            "daily": {day: {
                "picked_n": sum(row["trade_date"] == day for row in arm),
                "c1_kept_n": sum(row["trade_date"] == day for row in kept),
                "resolved_n": sum(row["trade_date"] == day and row["dynamic_net"] is not None for row in arm),
            } for day in days},
        }
    return results


def replay(root, output):
    start_time = perf_counter()
    inputs, parent_seal, input_ref, parent_ref = load_seal(root)
    dates = parent_seal["evaluable_days"]
    calendar = act031.act028.ExchangeSessions()
    require(previous.previous_days(calendar.schedule, CUTOFF, len(dates)) == [*dates, CUTOFF],
            "OBSERVATION_CALENDAR_DRIFT")
    rosters, observed, daily, checkpoints = select_rosters(inputs, parent_seal)
    output_code = {name: act031.ref(Path(__file__).resolve().with_name(name)) for name in (
        "pft_act034a_replay.py", "pft_act034a_rules.py")}
    seal_payload = {
        "schema": SCHEMA, "input": input_ref, "parent_selection_seal": parent_ref, "code": output_code,
        "checkpoints": checkpoints, "signal_dates": dates, "unavailable_signal_days": parent_seal["unavailable_days"],
        "observations_opened_in_signal_phase": False, "observed_cutoff": CUTOFF,
        "frozen_rosters": rosters.to_dict("records"), "daily_selection": daily,
        "policy": POLICY, "fit_calls": previous.FIT_CALLS, **act031.FLAGS,
    }
    selection_ref = act031.json_atomic(output / "SELECTION_SEAL.json", seal_payload)
    print(json.dumps({"phase": "SELECTION_SEALED", "strategies": rosters.strategy.value_counts().to_dict(),
                      "seal": selection_ref}), flush=True)
    bars, events, first, price_identity = read_cutoff(inputs, rosters, calendar)
    observations = read_observations(inputs, observed, set(rosters.ts_code))
    fixed, fixed_identity = prior_fixed(root, input_ref, parent_ref, inputs["days"][CUTOFF], dates, rosters)
    context_dates = [first, *dates, CUTOFF]
    details = []
    for row in rosters.itertuples(index=False):
        original = fixed[(row.trade_date, row.ts_code)] if row.strategy == "A1_EXIT" else None
        record = evaluate_row(row, observations, observed, bars.get(row.ts_code, {}), events[row.ts_code],
                              context_dates, original)
        details.append(record)
    detail_ref = act031.frame_atomic(output / "TRADE_DETAILS.csv", pd.DataFrame.from_records(details))
    result = {
        "schema": SCHEMA, "status": "RESEARCH_REPLAY_COMPLETE_21_OF_60", "observed_cutoff": CUTOFF,
        "selection_seal": selection_ref, "trade_details": detail_ref,
        "signal_dates": dates, "unavailable_signal_days": parent_seal["unavailable_days"],
        "latest_signal_date": dates[-1], "daily_selection": daily, "regimes": {day: parent_seal["regimes"][day] for day in dates},
        "observation_identity": {day: {key: value for key, value in data.items() if key not in {"quotes", "ranks"}}
                                 for day, data in observations.items()},
        "cutoff_price_identity": price_identity, "fixed_act033a_identity": fixed_identity,
        "strategy_metrics": summarize(details, dates), "policy": POLICY, "fit_calls": previous.FIT_CALLS, **act031.FLAGS,
        "runtime": {
            "wall_seconds_before_summary_write": perf_counter() - start_time,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        },
    }
    return act031.json_atomic(output / "SUMMARY.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--act033a", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root, output = args.act033a.resolve(strict=True), args.output.resolve()
    require(not output.is_relative_to(root), "OUTPUT_INSIDE_FROZEN_ACT033A_ROOT")
    with act031.exclusive_run(output):
        require(not (output / "SUMMARY.json").exists(), "OUTPUT_ALREADY_COMPLETE")
        summary = replay(root, output)
    print(json.dumps({"phase": "OUTCOMES_RECORDED", "summary": summary}), flush=True)


if __name__ == "__main__":
    main()
