"""ACT037A: freeze timing and Friday lists, then reuse the ACT036 path outcomes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from decimal import Decimal
from math import prod
from multiprocessing import get_context
import os
from pathlib import Path
import resource
from statistics import mean
from time import perf_counter
from types import SimpleNamespace

import pandas as pd
import pyarrow as arrow

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as g
from ops import pft_act033a_replay as a33
from ops import pft_act034a_rules as r34
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36i
from ops import pft_act036a_replay as a36
from ops import pft_act037a_inputs as data

OUT = data.OUTPUT
CSV_NAME = "CODEX_MAC_ACT-037A_TIMING_AND_1120_TO_1123_DETAIL_20261124.csv"
TRACKS = ("A1_BASE", "A1_BASE_EXT3")
GATES = ("T0", "T1", "T2", "T3")
FRIDAY_LAYERS = ("FORMAL_A", "FORMAL_B", "ALL_CONFIRMED", "MAIN_UNKNOWN_TOP20")
FORMAL_ARMS = ("A1_BASE", "EXT3", "B2_BASE", "B2_V2_STRICT", "B2_V2_WIDE")
FIT_ZERO = dict(a33.FIT_CALLS)
require = data.require
POLICY = {
    "T0": "No timing filter.",
    "T1": "3<=CONFIRMED_S<=120 and DAMAGED share of the full eligible universe <=.70, incl G1. If missing stages matter, compare the adverse and favorable bounds; unknown gates do not enter.",
    "T2": "Arithmetic mean of ACT013 cw_share, cy_share and wy_share >= .3619; standalone WY is an audit column only.",
    "T3": "ACT033A five-session compounded equal-weight close/prev-close > -1%, using official daily package when bound, else separately flagged V4 archived rebase proxy. Without full five dates the gate is unknown.",
    "EXT3": "Subset of frozen ACT036 A1_V2 extension_only with exact STRONG_BINARY_FAKE_HEAD_CONTRADICTION token and same selected active-anchor cushion m/(1+m) in (0,.10], where m=D close/active low−1; no alternate candidates.",
    "cutoff": data.MONDAY,
}


def gate_values(stage, width, market):
    confirmed = stage.get("confirmed_n")
    confirmed_range = g.within(confirmed, 3, 120)
    worst = g.lte(stage["damaged_share_all_eligible_max"], .70)
    lower = g.lte(stage["damaged_share_all_eligible_min"], .70)
    damage_pass = True if worst is True else False if lower is False else None
    return {"T0": True, "T1": g.conjunction(confirmed_range, damage_pass),
            "T2": g.gte(width.get("composite_breadth_share"), .3619),
            "T3": g.negation(g.lte(market["trailing_5_return"], -.01))}


def ext3_row(row):
    if row.get("extension_only") is not True:
        return False, None
    m = g.finite(row.get("active_close_vs_low_pct"))
    cushion = m / (1 + m) if m is not None and m > 0 else None
    reasons = tuple((row.get("route_reasons") or "").split(";"))
    passed = (a36.STRONG in reasons and a36.EARLY_REBUILD not in reasons
              and g.within(cushion, 0, .10, lower_closed=False) is True)
    if passed:
        require(a36.coarse_a1(row) is True
                and g.within(m, 0, .10, lower_closed=False) is True
                and g.lte(row.get("vol_contraction_vs_platform"), .75) is True
                and g.gte(row.get("anchor_age_sessions"), 8) is True
                and all(row.get(k) is False for k in ("V02", "V04", "V06"))
                and row.get("intact_anchor") is True and row.get("c1_pass") is True,
                "ACT036_EXT3_D_PREDICATE_DRIFT")
    return passed, cushion


def track_for_day(frozen):
    base = [row | {"EXT3_member": False, "EXT3_cushion": None} for row in frozen["A1_BASE"]]
    extension = []
    for row in frozen["A1_V2"]:
        passed, margin = ext3_row(row)
        if passed:
            extension.append(row | {"EXT3_member": True, "EXT3_cushion": margin})
    require(len({r["ts_code"] for r in [*base, *extension]}) == len(base) + len(extension),
            "TRACK_DUPLICATE_CODE")
    return {"A1_BASE": base, "A1_BASE_EXT3": [*base, *extension]}, extension


_STAGE_WORKER = None


def stage_init(reader):
    from threadpoolctl import threadpool_limits

    global _STAGE_WORKER
    arrow.set_cpu_count(1)
    arrow.set_io_thread_count(1)
    _STAGE_WORKER = a36i.Basis(reader), threadpool_limits(limits=1)


def stage_task(projection, jobs, root, parent_sha):
    basis, _ = _STAGE_WORKER
    for day, official, saved, audit, dev0, original_checkpoint in jobs:
        start = perf_counter()
        result = data.stage_stats(day, projection, basis, official, saved, audit, dev0, original_checkpoint)
        obj = {"schema": data.SCHEMA, "trade_date": day, "run_sha": parent_sha, "stats": result,
               "seconds": perf_counter() - start, "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        receipt = a31.json_atomic(root / f"{day}.json", obj)
        print(f"D_STAGE_RECORDED {day} {result['damaged_n']}/{result['eligible_n']} "
              f"unknown={result['stage_unknown_n']} s={obj['seconds']:.2f} {receipt['sha256'][:8]}", flush=True)


def stage_checkpoint(path, day, start_sha):
    ref = a31.ref(path)
    obj = a31.read_ref(ref)
    require(obj["schema"] == data.SCHEMA and obj["trade_date"] == day and obj["run_sha"] == start_sha,
            f"STAGE_CHECKPOINT_DRIFT:{day}")
    return obj, ref


def stage_batches(projection, days, sources):
    dev0 = sources.dev[0]
    for offset in range(0, len(days), 2):
        batch = days[offset:offset + 2]
        frame = projection.loc[projection.trade_date.between(f35.earlier(batch[0], data.WINDOW), batch[-1])]
        jobs = []
        for day in batch:
            official, _ = sources.quotes[day]
            saved = sources.prior.all_signals.get(day)
            audit = dict(sources.checkpoints[day]["audit"])
            if day == dev0:
                audit |= {"confirmed_exact_from_projection": int(saved.final_state.eq("CONFIRMED_S").sum())}
            orig = sources.prior.references["checkpoints"].get(day, {}).get("signal_or_universe")
            jobs.append((day, official, saved, audit, dev0, orig))
        yield frame, jobs


def timing_stage(sources, reader, run, workers):
    root = OUT / "stage"
    root.mkdir(exist_ok=True)
    pending = [d for d in sources.days if not (root / f"{d}.json").exists()]
    market_cache = OUT / "MARKET_D_ONLY.json"
    if pending or not market_cache.exists():
        pending_scope = sorted(set([*pending, *data.WARMUP, data.FRIDAY]))
        projection, audit = data.archived_stage_read(sources, reader, pending_scope)
        if not market_cache.exists():
            basis = a36i.Basis(reader)
            days = [*data.WARMUP, *sources.days]
            exact_window = projection.loc[projection.trade_date.isin(days)]
            local = {d: data.market_close_day(exact_window, d, basis, *sources.quotes[d]) for d in days}
            receipt = a31.json_atomic(market_cache, {"run_sha": run["sha256"], "reader_projection": audit,
                                                      "daily_close": local})
        else:
            receipt = a31.ref(market_cache)
        if pending:
            init = (a36.worker_archive(reader),)
            jobs = iter(stage_batches(projection, pending, sources))
            if workers == 1:
                stage_init(*init)
                for batch in jobs:
                    stage_task(*batch, root, run["sha256"])
            else:
                with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"),
                                         initializer=stage_init, initargs=init) as executor:
                    inflight = {executor.submit(stage_task, *batch, root, run["sha256"])
                                for batch in (next(jobs, None) for _ in range(workers)) if batch is not None}
                    while inflight:
                        done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                        for future in done:
                            future.result()
                        for _ in done:
                            batch = next(jobs, None)
                            if batch:
                                inflight.add(executor.submit(stage_task, *batch, root, run["sha256"]))
    else:
        receipt = a31.ref(market_cache)
    evidence = a31.read_ref(receipt)
    require(evidence["run_sha"] == run["sha256"], "MARKET_D_ONLY_IDENTITY_DRIFT")
    computed = {day: stage_checkpoint(root / f"{day}.json", day, run["sha256"]) for day in sources.days}
    return computed, receipt, evidence


def original_eligibility(row, overlay, quote):
    if not overlay:
        return {"ACT033A_group_projection": False}
    base = row | overlay
    wick = r34.upper_wick(quote)
    b2 = r34.selection_atoms(SimpleNamespace(**base), wick)
    a1_atoms = {
        "main_board": g.main_board(row["ts_code"]),
        "confirmed": row.get("final_state") == "CONFIRMED_S",
        "tactic_pullback_or_rebuild": row.get("main_tactic") in ("pullback", "rebuild"),
        "projected_ge_085": g.gte(g.finite(row.get("projected_p_s")), .85),
        "anchor_age_calendar_ge_8": g.gte(base.get("anchor_age_calendar_days"), 8),
        "cushion_above0_to10pct": g.within(base.get("cushion"), 0, .10, lower_closed=False),
        "post_repair": row.get("stage") == "POST_REPAIR",
        "A1_volume_gate": base.get("a1_volume_gate"), "A1_price_gate": base.get("a1_price_gate"),
    }
    b2_atoms = {
        "structural": b2["b2_structural"],
        "vol_over_ma5_ge_115": g.gte(b2["b2_d_volume_ma5_ratio"], 1.15),
        "return_1_85pct": g.within(base.get("return_d"), .01, .085),
        "bullish": base.get("raw_bullish"),
        "wick_le_3pct": g.lte(wick, .03),
        "slow_dividend_veto_clear": not b2["b2_slow_dividend_veto"],
    }
    fields = ("BASE", "A0_eligible", "A0", "A0_rank", "A1_eligible", "A1", "A1_rank", "B1_eligible",
              "B1", "B1_rank", "b1_structural_eligible", "b2_failed_atoms", "b2_unknown_atoms")
    return {"ACT033A_group_projection": True} | {f"ACT033A_{k}": base.get(k) for k in fields} | {
        "ACT033A_A1_failed": "|".join(k for k, v in a1_atoms.items() if v is False),
        "ACT033A_A1_unknown": "|".join(k for k, v in a1_atoms.items() if v is None),
        "ACT034A_B2_eligible": b2["b2_eligible"], "ACT034A_B2_structural": b2["b2_structural"],
        "ACT034A_B2_arm": b2["b2_arm"],
        "ACT034A_B2_failed": "|".join(k for k, v in b2_atoms.items() if v is False),
        "ACT034A_B2_unknown": "|".join(k for k, v in b2_atoms.items() if v is None),
        "ACT034A_C1_pass": b2["c1_pass"], "ACT034A_C1_veto_reasons": b2["c1_veto_reasons"],
        "ACT034A_C1_unknown_atoms": b2["c1_unknown_atoms"],
    }


def board(code):
    if g.main_board(code):
        return "SH_MAIN" if code.endswith(".SH") else "SZ_MAIN"
    if code.endswith(".BJ"):
        return "BJ"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("300", "301")):
        return "CHINEXT"
    return "OTHER_A"


def friday_selections(sources, reader):
    day = data.FRIDAY
    original = sources.checkpoints[day]["selections"]
    tracks, extension = track_for_day(original)
    arms = {"A1_BASE": original["A1_BASE"], "EXT3": extension} | {arm: original[arm] for arm in FORMAL_ARMS[2:]}
    sizes = {arm: len(rows) for arm, rows in arms.items()}
    require(sizes == {"A1_BASE": 4, "EXT3": 3, "B2_BASE": 3, "B2_V2_STRICT": 0, "B2_V2_WIDE": 0},
            "FRIDAY_FROZEN_FORMAL_ROSTER_COUNTS_DRIFT")
    known_sets = {"A1_BASE": {"002832.SZ", "601077.SH", "600754.SH", "601928.SH"},
                  "EXT3": {"000415.SZ", "000902.SZ", "601838.SH"},
                  "B2_BASE": {"600098.SH", "600295.SH", "601000.SH"}}
    require(all({row["ts_code"] for row in arms[k]} == v for k, v in known_sets.items()), "FRIDAY_FORMAL_CODE_DRIFT")
    signals = sources.prior.all_signals[day]
    counts = signals.final_state.value_counts().to_dict()
    require(len(signals) == 5338 and counts == {"REJECTED_FAKE": 5218, "UNKNOWN_BORDERLINE": 83, "CONFIRMED_S": 37},
            "FRIDAY_ACT031_ORACLE_DRIFT")
    early = signals.loc[signals.final_state.eq("CONFIRMED_S") | signals.final_state.eq("UNKNOWN_BORDERLINE") &
                         signals.ts_code.map(g.main_board) & signals.projected_p_s.ge(.80)]
    scope = set(early.ts_code) | {row["ts_code"] for arm in arms.values() for row in arm}
    prefix = a36i.read_history(reader, day, day, scope, columns=("close",))
    closes = {code: a31.positive(close) for code, close in zip(prefix.ts_code, prefix.close)}
    selected = defaultdict(dict)
    for arm, rows in arms.items():
        for row in rows:
            selected[row["ts_code"]][arm] = row
    original_rows = {}
    for row in early.to_dict("records"):
        code = row["ts_code"]
        original_rows[code] = a35.clean_record(row)
    identifiers = {code: a35.clean_record(row) for code, row in
                   zip(signals.ts_code, signals.to_dict("records")) if code in scope}
    groups = sources.prior.overlays[day]
    quotes, _ = sources.quotes[day]
    observed_unknown = [row for code, row in original_rows.items() if row["final_state"] == "UNKNOWN_BORDERLINE"
                        and g.gte(closes.get(code), a31.positive(row["invalidation_price"])) is True
                        and a31.positive(row["invalidation_price"]) is not None]
    unknown_ranked = sorted(observed_unknown, key=lambda row: (-row["projected_p_s"], row["ts_code"]))[:20]
    members = {
        "FORMAL_A": [row["ts_code"] for row in tracks["A1_BASE_EXT3"]],
        "FORMAL_B": sorted({row["ts_code"] for arm in FORMAL_ARMS[2:] for row in arms[arm]}),
        "ALL_CONFIRMED": sorted(code for code, row in original_rows.items() if row["final_state"] == "CONFIRMED_S"),
        "MAIN_UNKNOWN_TOP20": [row["ts_code"] for row in unknown_ranked],
    }
    memberships = defaultdict(list)
    for layer, codes in members.items():
        for code in codes:
            memberships[code].append(layer)
    output = []
    for layer, codes in members.items():
        for order, code in enumerate(codes, 1):
            row = identifiers[code]
            picks = selected[code]
            frozen_model = row["invalidation_price"]
            ext3_anchor = picks.get("EXT3", {}).get("invalidation_price")
            path_arm = ("EXT3" if layer == "FORMAL_A" and "EXT3" in picks else "A1_BASE"
                        if layer == "FORMAL_A" else next((name for name in FORMAL_ARMS[2:] if name in picks), None)
                        if layer == "FORMAL_B" else None)
            archived_path_anchor = picks.get(path_arm, {}).get("invalidation_price")
            active = archived_path_anchor if archived_path_anchor is not None else frozen_model
            raw_quote = quotes.get(code, {})
            qfq_close, raw_close = closes.get(code), a31.positive(raw_quote.get("close"))
            alignment = r34.same_price(qfq_close, raw_close) if None not in (qfq_close, raw_close) else None
            anchor_source = f"ACT036_{path_arm}_PATH" if archived_path_anchor is not None else "ACT031_FROZEN_MODEL"
            output.append({"record_type": "FRIDAY_MONDAY", "trade_date": day, "ts_code": code,
                "observation_layer": layer, "layer_order": order, "name": row["name"], "board": board(code),
                "all_layer_memberships": "|".join(memberships[code]), "layer_overlap_count": len(memberships[code]),
                "frozen_state": row["final_state"], "frozen_stage": row["stage"], "frozen_route_reasons": row["route_reasons"],
                "projected_p_s": row["projected_p_s"], "friday_close_qfq_d": qfq_close,
                "friday_official_raw_close": raw_close, "friday_d_qfq_official_raw_close_match": alignment,
                "friday_model_invalidation_qfq_d": frozen_model, "friday_ext3_active_anchor_qfq_d": ext3_anchor,
                "friday_path_anchor_qfq_d": active, "friday_layer_anchor_source": anchor_source,
                "EXT3_cushion": picks.get("EXT3", {}).get("EXT3_cushion"),
                **{f"formal_{arm}": arm in picks for arm in FORMAL_ARMS},
                **{f"{arm}_original_rank": picks.get(arm, {}).get("selection_rank") for arm in FORMAL_ARMS},
                **original_eligibility(row, groups.get(code), quotes.get(code))})
    potential = [row for row in original_rows.values() if row["final_state"] == "UNKNOWN_BORDERLINE"]
    eligibility = Counter()
    for row in potential:
        code, anchor = row["ts_code"], a31.positive(row.get("invalidation_price"))
        close = closes.get(code)
        eligibility["CANNOT_CONFIRM_D_CLOSE_OR_ANCHOR" if None in (anchor, close) else
                    "PASS_CLOSE_GE_ANCHOR" if close >= anchor - r34.EPS else "REJECT_CLOSE_LT_ANCHOR"] += 1
    audit = {"formal_arms": sizes, "layer_counts": {layer: len(codes) for layer, codes in members.items()},
             "eligible_market_n": len(signals), "final_state": counts, "raw_W_lt_Y_count": int(signals.white.lt(signals.yellow).sum()),
             "main_unknown_p_ge_080_n": len(potential), "main_unknown_close_filter": dict(eligibility),
             "confirmed_roster_main_board_n": sum(g.main_board(code) for code in members["ALL_CONFIRMED"])}
    return output, audit


def seal_phase(sources, reader, run, workers):
    d_stage, market_ref, market = timing_stage(sources, reader, run, workers)
    friday, friday_audit = friday_selections(sources, reader)
    timing = {}
    rosters = {}
    for day in sources.days:
        stage, _ = d_stage[day]
        breadth = sources.breadth.get(day, {})
        t3 = data.market_window(day, sources.calendar, market["daily_close"])
        gates = gate_values(stage["stats"], breadth, t3)
        timing[day] = {"stage": stage["stats"], "breadth": breadth, "market_return_5d": t3,
                       "timing_gates": gates}
        daily, _ = track_for_day(sources.checkpoints[day]["selections"])
        rosters[day] = daily
    body = {"schema": data.SCHEMA, "phase": "SELECTION_SEALED", "run_start": run,
            "signal_dates": sources.days, "scope_count": len(sources.days) + 1,
            "oot_dates": sources.oot, "dev_dates": sources.dev, "cutoff": data.MONDAY,
            "stage_receipts": {day: d_stage[day][1] for day in sources.days}, "market_receipt": market_ref,
            "stage_reader_projection": market["reader_projection"], "timing_by_day": timing, "rosters": rosters,
            "friday_by_layer": friday, "friday_audit": friday_audit, "policy": POLICY,
            "sleeve_policy": "Five independent 20% sleeves, rotate with every signal day whether selected, blocked or empty; equal within-day allocations; preserve cash for known unfilled. No turnover into an unresolved prior same-sleeve cohort. Marks checked against 11/23 official close and cutoff QFQ before valuation.",
            "prior_outcomes_opened_before_seal": False, "monday_official_opened_before_seal": False,
            "fit_calls": FIT_ZERO, "predict_count": 0, "model_load_count": 0, **a31.FLAGS}
    return a31.json_atomic(OUT / data.SEAL_NAME, body)


def load_prior_outcomes(seal_ref):
    seal = a31.read_ref(seal_ref)
    require(seal["phase"] == "SELECTION_SEALED" and seal["scope_count"] == 54, "FRESH_INPUT_SEAL_REQUIRED")
    old = a31.read_ref(data.ACT036_SUMMARY_EXPECTED)
    require(old["selection_seal"] == data.ACT036_SEAL and old["phase"] == "FORWARD_REPLAY_COMPLETE"
            and old["forward_replay_count"] == 1 and old["cutoff"] == data.MONDAY, "ACT036_OUTCOME_RUN_DRIFT")
    rows = a35.read_dated_csv(a33.checked(data.ACT036_DELIVERY))
    require(len(rows) == 467 and len({(r["trade_date"], r["ts_code"], r["lane"]) for r in rows}) == 467,
            "ACT036_DELIVERY_KEY_DRIFT")
    outcomes = {}
    for row in rows:
        if row["window"] == "LATEST_1123":
            require(row["trade_date"] == data.MONDAY and not row["dynamic_net"] and not row["d1_date"],
                    "ACT036_LATEST_ILLEGAL_OUTCOME")
            continue
        key = row["trade_date"], row["ts_code"], row["lane"]
        outcomes[key] = a35.outcome_record(row) | {
            k: row[k] or None for k in ("window", "outcome_rule_source", "d1_quote_evidence", "path_quote_evidence")}
        outcomes[key]["known_previously_exposed"] = row["known_previously_exposed"] == "True"
    for day, tracks in seal["rosters"].items():
        for picks in tracks.values():
            for row in picks:
                key = day, row["ts_code"], row["lane"]
                require(key in outcomes, f"FROZEN_SELECTION_OUTCOME_MISSING:{key}")
    return seal, outcomes


def timed_entries(seal, outcomes):
    arms = {}
    for track in TRACKS:
        for gate in GATES:
            daily = {}
            for day, row in seal["timing_by_day"].items():
                pre = seal["rosters"][day][track]
                verdict = row["timing_gates"][gate]
                stocks = []
                if verdict is True:
                    for pick in pre:
                        outcome = outcomes[day, pick["ts_code"], pick["lane"]]
                        stocks.append({"record_type": "TIMING_TRADE", "trade_date": day, "ts_code": pick["ts_code"],
                                       "name": pick["name"], "track": track, "timing_gate": gate,
                                       "frozen_trade_lane": pick["lane"], "selection_rank": pick["selection_rank"],
                                       "EXT3_member": pick["EXT3_member"], "EXT3_cushion": pick["EXT3_cushion"],
                                       "active_close_vs_low_pct": pick.get("active_close_vs_low_pct"),
                                       "frozen_route_reasons": pick.get("route_reasons"),
                                       "projected_p_s": pick.get("projected_p_s"),
                                       "signal_quote_source": pick.get("signal_quote_source"), **outcome})
                daily[day] = {"gate": verdict, "before_timing_n": len(pre), "trades": stocks}
            arms[track, gate] = daily
    return arms


def monday_inputs(sources, reader, scope):
    refs = sources.prior.inputs["days"][data.MONDAY]
    quotes, official = a31.day_quotes(data.MONDAY, refs)
    require(quotes and official, "MONDAY_OFFICIAL_PACKAGE_REQUIRED")
    rank, rank_source = a31.rank_for_day(data.MONDAY, refs, quotes)
    require(rank_source == "V4_OFFICIAL_TOP200" and len(rank) == 200, "MONDAY_EXACT_OFFICIAL_TOP200_REQUIRED")
    frame = a36i.read_history(reader, data.MONDAY, data.MONDAY, scope,
                              columns=("open", "high", "low", "close", "vol", "tradeable_basic"))
    bars = {row["ts_code"]: row for row in frame.to_dict("records")}
    benchmark_all = [quote for quote in quotes.values() if quote["eligible_for_daily_gain_rank"]]
    open_proxies = {quote["symbol"]: a31.opening_assessment(quote["symbol"], quote)
                    for quote in benchmark_all}
    buyable = [quote for quote in benchmark_all if open_proxies[quote["symbol"]]["opening_buyable_proxy"] is True]
    full = {"eligible_quote_n": len(benchmark_all),
            "full_a_ew_close_vs_prev": mean(quote["change_pct"] / 100 for quote in benchmark_all),
            "full_a_ew_raw_o2c": mean(quote["close"] / quote["open"] - 1 for quote in benchmark_all),
            "opening_buyable_n": len(buyable), "opening_known_unbuyable_n": sum(
                stat["opening_buyable_proxy"] is False for stat in open_proxies.values()),
            "opening_unknown_n": sum(stat["opening_buyable_proxy"] is None for stat in open_proxies.values()),
            "full_a_ew_buyable_o2c_net": mean(quote["close"] / quote["open"] - 1 - r34.FEE for quote in buyable)
                                        if buyable else None,
            "rank_source": rank_source, "official": official, "rank_reference": refs["rank_ref"]}
    return quotes, rank, bars, full


def monday_mark(bars, quotes, code):
    # At the authoritative 11/23 asof endpoint no later event can touch the
    # raw OHLC. Compare exact raw close with the stored cutoff QFQ close.
    return r34.verified_bar(bars.get(code), quotes.get(code), data.MONDAY, ())[0].get("close")


def friday_outcomes(friday, quotes, ranks, bars, reader, width, benchmark):
    results = []
    for row in friday:
        code = row["ts_code"]
        quote = quotes.get(code)
        opened = a31.opening_assessment(code, quote)
        buyable = opened["opening_buyable_proxy"]
        gap = r34.raw_ratio(quote, "open", "prev_close")
        raw_o2c = r34.raw_ratio(quote, "close", "open")
        core = bool(quote and quote["eligible_for_daily_gain_rank"])
        one_price = (quote["open"] == quote["high"] == quote["low"] == quote["close"]) if core else None
        events = r34.affine_events(reader.symbols.get(code), data.FRIDAY, data.MONDAY)
        monday, quality = r34.verified_bar(bars.get(code), quote, data.MONDAY, events)
        invalidation = r34.to_cutoff_basis(row["friday_path_anchor_qfq_d"], data.FRIDAY, events)
        model_anchor = r34.to_cutoff_basis(row["friday_model_invalidation_qfq_d"], data.FRIDAY, events)
        ext3_anchor = r34.to_cutoff_basis(row["friday_ext3_active_anchor_qfq_d"], data.FRIDAY, events)
        low, close = monday.get("low"), monday.get("close")
        friday_aligned = row["friday_d_qfq_official_raw_close_match"] is True
        anchored = invalidation is not None and friday_aligned
        watched_5m = g.within(gap, .03, .05) if row["observation_layer"] == "FORMAL_B" else None
        market_day_gate_pass = None if gap is None else gap <= .05 + r34.EPS
        result = row | {
            "observation_date": data.MONDAY, "Monday_official_name": quote.get("name") if quote else None,
            "Monday_official_prev_close": quote.get("prev_close") if core else None,
            **{f"Monday_raw_{k}": quote.get(k) if core else None for k in ("open", "high", "low", "close")},
            "Monday_gap": gap, "Monday_high_vs_prev": r34.raw_ratio(quote, "high", "prev_close"),
            "Monday_low_vs_prev": r34.raw_ratio(quote, "low", "prev_close"),
            "Monday_cc": r34.raw_ratio(quote, "close", "prev_close"), "Monday_raw_o2c": raw_o2c,
            "Monday_board_cap_buyable": buyable, "Monday_opening_status": opened["opening_status"],
            "Monday_inferred_upper_cap": opened["inferred_upper_limit"], "Monday_one_price": one_price,
            "Monday_one_price_upper_cap": opened["one_price_upper_limit"],
            "Monday_buyable_o2c_net": raw_o2c - r34.FEE if buyable is True and raw_o2c is not None else None,
            "Monday_V1_gap_at_most_5pct": market_day_gate_pass,
            "Monday_V1_B2_5m_confirmation_needed": watched_5m,
            "Monday_V1_B2_5m_confirmation_status": "CANNOT_CONFIRM_DAILY_BAR_ONLY" if watched_5m is True else None,
            "Monday_rank": ranks.get(code), "Monday_top200_hit": code in ranks,
            "Monday_rank_source": "V4_OFFICIAL_TOP200",
            "Friday_invalidation_at_cutoff_basis": invalidation,
            "Friday_model_invalidation_at_cutoff_basis": model_anchor,
            "Friday_EXT3_active_anchor_at_cutoff_basis": ext3_anchor,
            "Monday_low_below_model_invalidation": low < model_anchor - r34.EPS if friday_aligned and None not in (low, model_anchor) else None,
            "Monday_close_below_model_invalidation": close < model_anchor - r34.EPS if friday_aligned and None not in (close, model_anchor) else None,
            "Monday_low_below_EXT3_active_anchor": low < ext3_anchor - r34.EPS if friday_aligned and None not in (low, ext3_anchor) else None,
            "Monday_close_below_EXT3_active_anchor": close < ext3_anchor - r34.EPS if friday_aligned and None not in (close, ext3_anchor) else None,
            "Monday_cutoff_qfq_low": low, "Monday_cutoff_qfq_close": close,
            "Monday_cutoff_qfq_validation": quality,
            "Monday_intraday_low_below_invalidation": low < invalidation - r34.EPS if anchored and low is not None else None,
            "Monday_close_below_invalidation": close < invalidation - r34.EPS if anchored and close is not None else None,
            **{f"Friday_{k}": v for k, v in width.items()},
        }
        for label, reference in (("Monday_cc", "full_a_ew_close_vs_prev"),
                                 ("Monday_raw_o2c", "full_a_ew_raw_o2c"),
                                 ("Monday_buyable_o2c_net", "full_a_ew_buyable_o2c_net")):
            value, baseline = result[label], benchmark[reference]
            result[f"{label}_minus_market"] = value - baseline if None not in (value, baseline) else None
        results.append(result)
    return results


def average_known(rows, name):
    values = [row[name] for row in rows if row.get(name) is not None]
    return {"known_n": len(values), "mean": mean(values) if values else None}


def friday_metrics(friday):
    memberships = {layer: [r for r in friday if r["observation_layer"] == layer] for layer in FRIDAY_LAYERS}
    for arm in FORMAL_ARMS:
        base = "FORMAL_A" if arm in {"A1_BASE", "EXT3"} else "FORMAL_B"
        memberships[arm] = [r for r in memberships[base] if r[f"formal_{arm}"]]
    output = {}
    for group, rows in memberships.items():
        n = len(rows)
        values = [r["Monday_buyable_o2c_net"] for r in rows if r["Monday_buyable_o2c_net"] is not None]
        market = {"symbols": n, "one_price_n": sum(r["Monday_one_price"] is True for r in rows),
                  "known_buyable_n": sum(r["Monday_board_cap_buyable"] is True for r in rows),
                  "known_unbuyable_n": sum(r["Monday_board_cap_buyable"] is False for r in rows),
                  "unknown_buyability_n": sum(r["Monday_board_cap_buyable"] is None for r in rows),
                  "top200_hits": sum(r["Monday_top200_hit"] is True for r in rows),
                  "buyable_top200_hits": sum(r["Monday_top200_hit"] is True and r["Monday_board_cap_buyable"] is True for r in rows),
                  "positive_exec_net_n": sum(v > 0 for v in values),
                  "nonpositive_exec_net_n": sum(v <= 0 for v in values),
                  "exec_net_min": min(values) if values else None,
                  "exec_net_below_minus10_n": sum(v < -.10 - r34.EPS for v in values)}
        for field in ("Monday_gap", "Monday_high_vs_prev", "Monday_low_vs_prev", "Monday_cc",
                      "Monday_raw_o2c", "Monday_buyable_o2c_net", "Monday_cc_minus_market",
                      "Monday_raw_o2c_minus_market", "Monday_buyable_o2c_net_minus_market"):
            market[field] = average_known(rows, field)
        for field in ("Monday_cc", "Monday_raw_o2c"):
            market[field]["positive_n"] = sum(r.get(field) is not None and r[field] > 0 for r in rows)
        for field in ("Monday_intraday_low_below_invalidation", "Monday_close_below_invalidation"):
            market[field] = {"known_n": sum(r[field] is not None for r in rows),
                             "triggered_n": sum(r[field] is True for r in rows)}
        output[group] = market
    return output


def sleeve_nav(daily, dates, marks):
    """Five independently reinvested sleeves with chronological settlement checks."""
    capital = [.2] * 5
    last_exit = [None] * 5
    locked = [False] * 5
    marked_gain = [0.] * 5
    realized_gain = 0.
    proof = Counter()
    for index, day in enumerate(dates):
        position = index % 5
        trades = daily[day]["trades"]
        if not trades:
            continue
        entries = {row["d1_date"] for row in trades}
        require(len(entries) == 1 and None not in entries and next(iter(entries)) > day,
                f"NAV_ENTRY_SESSION_DRIFT:{day}")
        entry_day = next(iter(entries))
        if locked[position]:
            proof["new_cohort_suppressed_for_unresolved_prior_sleeve"] += 1
            continue
        require(last_exit[position] is None or last_exit[position] < entry_day, f"NAV_SLEEVE_OVERLAP:{day}")
        per_name = capital[position] / len(trades)
        cohort_gain = 0.
        for row in trades:
            fill = row["opening_fillable_proxy"]
            entry = row["entry_basis_price"]
            value, exit_day = row["dynamic_net"], row["exit_date"]
            if fill is False:
                require(value is None and exit_day is None, "NAV_UNFILLED_ROW_HAS_EXIT")
                proof["known_unfilled_allocations_left_cash"] += 1
            elif fill is not True or entry is None:
                locked[position] = True
                proof["unknown_entry_allocations"] += 1
            elif value is not None:
                require(exit_day and entry_day <= exit_day <= data.MONDAY, "NAV_VERIFIED_EXIT_SESSION_DRIFT")
                cohort_gain += per_name * value
                current = last_exit[position]
                last_exit[position] = max(current, exit_day) if current else exit_day
                proof["realized_allocations"] += 1
            else:
                locked[position] = True
                mark = marks.get(row["ts_code"])
                if mark is None:
                    proof["unsettled_without_verified_mark_allocations"] += 1
                else:
                    marked_gain[position] += per_name * (mark / entry - 1 - r34.FEE)
                    proof["unsettled_with_verified_mark_allocations"] += 1
        capital[position] += cohort_gain
        realized_gain += cohort_gain
    incomplete = (proof["unknown_entry_allocations"] or proof["unsettled_without_verified_mark_allocations"]
                  or proof["new_cohort_suppressed_for_unresolved_prior_sleeve"])
    complete = not incomplete
    return {"status": "COMPLETE_CUTOFF_COSTED_MARKS" if complete else "CANNOT_CONFIRM",
            "cutoff_nav": sum(capital) + sum(marked_gain) if complete else None,
            "starting_capital": 1.0, "sleeves": 5, "cash_weight_each": .2,
            "credited_realized_pnl_vs_initial_capital": realized_gain,
            "costed_unsettled_mark_pnl_vs_initial_capital": sum(marked_gain),
            "unsettled_sleeves": sum(locked), "audit_counts": dict(proof),
            "interpretation": "Known realized sleeve gains and conditional marked contribution; incomplete when an entry or mark is unknown or locked cash limits later planned cohorts."}


def close_of_entry_day_flat_status(all_trade_rows, when):
    uncertain = False
    for row in all_trade_rows:
        entry_day, exit_day, fillable = row["d1_date"], row["exit_date"], row["opening_fillable_proxy"]
        if not entry_day or entry_day > when or fillable is False or (exit_day and exit_day <= when):
            continue
        if fillable is True and row["entry_basis_price"] is not None and (
                entry_day == when or exit_day is not None
                or row["exit_status"] in {"HORIZON_IMMATURE_AT_CUTOFF", "EXIT_DUE_AFTER_CUTOFF"}):
            return False
        uncertain = True
    return None if uncertain else True


def timing_metrics(arms, sources, marks):
    windows = {"OOT_EARLY": sources.oot, "DEV_21D": sources.dev, "ALL_53D": sources.days} | {
        name: [day for day in sources.days if day.startswith(prefix)] for name, prefix in
        (("SEP", "202609"), ("OCT", "202610"), ("NOV", "202611"))}
    results, detailed = {}, []
    days = sources.calendar
    for name, dates in windows.items():
        results[name] = {}
        for track in TRACKS:
            results[name][track] = {}
            paired_baseline = [(day, row) for day in dates for row in arms[track, "T0"][day]["trades"]]
            for gate in GATES:
                daily = arms[track, gate]
                trade_pairs = [(day, row) for day in dates for row in daily[day]["trades"]]
                trades = [row for _, row in trade_pairs]
                metrics = a36.rates(trades, dates)
                adjusted_ci = a35.bootstrap((trade_pairs, paired_baseline), dates)["executed_net_mean"]
                all_eligible = [row for day in sources.days for row in daily[day]["trades"]]
                flat = [close_of_entry_day_flat_status(all_eligible, days[days.index(day) + 1]) for day in dates]
                values = [row for row in trades if row["dynamic_net"] is not None]
                baseline = [row for _, row in paired_baseline if row["dynamic_net"] is not None]
                delta = mean(row["dynamic_net"] for row in values) - mean(row["dynamic_net"] for row in baseline) if values and baseline else None
                status = {
                    "gate_pass_days": sum(daily[d]["gate"] is True for d in dates),
                    "gate_reject_days": sum(daily[d]["gate"] is False for d in dates),
                    "gate_unknown_days": sum(daily[d]["gate"] is None for d in dates),
                    "would_pick_but_gate_blocked_days": sum(daily[d]["before_timing_n"] > 0 and daily[d]["gate"] is False for d in dates),
                    "would_pick_but_gate_unknown_days": sum(daily[d]["before_timing_n"] > 0 and daily[d]["gate"] is None for d in dates),
                    "timing_pass_and_no_preselected_signal_days": sum(daily[d]["gate"] is True and daily[d]["before_timing_n"] == 0
                                                                    for d in dates),
                    "no_new_selection_days_including_timing": sum(not daily[d]["trades"] for d in dates),
                    "D1_close_flat_known_days": sum(v is True for v in flat),
                    "D1_close_nonflat_known_days": sum(v is False for v in flat),
                    "D1_close_flat_unknown_days": sum(v is None for v in flat),
                }
                results[name][track][gate] = {"trade": metrics, "days": status, "five_sleeve_nav": sleeve_nav(daily, dates, marks),
                                              "net_mean_lift_vs_track_T0": delta, "paired_moving_5day": adjusted_ci}
                if name == "ALL_53D":
                    for day, is_flat in zip(dates, flat):
                        row = daily[day]
                        detailed.append({"record_type": "TIMING_DAY", "trade_date": day, "track": track, "timing_gate": gate,
                                         "gate_passed": row["gate"], "pre_timing_selected_n": row["before_timing_n"],
                                         "timing_selected_n": len(row["trades"]), "D1_close_flat": is_flat})
                        detailed.extend(row["trades"])
    return results, detailed


def total_outcomes(sources, seal_ref):
    seal, outcomes = load_prior_outcomes(seal_ref)
    armed = timed_entries(seal, outcomes)
    settled_marks_needed = {r["ts_code"] for arm in armed.values() for day in arm.values() for r in day["trades"]
                            if r["opening_fillable_proxy"] is True and r["entry_basis_price"] is not None
                            and r["dynamic_net"] is None}
    scope = settled_marks_needed | {r["ts_code"] for r in seal["friday_by_layer"]}
    reader = data.bound(sources, data.MONDAY)
    quotes, ranks, bars, benchmark = monday_inputs(sources, reader, scope)
    marks = {code: monday_mark(bars, quotes, code) for code in sorted(settled_marks_needed)}
    for arm in armed.values():
        for cohort in arm.values():
            for row in cohort["trades"]:
                if row["dynamic_net"] is None and row["entry_basis_price"] is not None:
                    mark = marks.get(row["ts_code"])
                    row["cutoff_qfq_mark_20261123"] = mark
                    row["cutoff_costed_mark_return"] = mark / row["entry_basis_price"] - 1 - r34.FEE if mark is not None else None
    friday = friday_outcomes(seal["friday_by_layer"], quotes, ranks, bars, reader, sources.breadth[data.FRIDAY], benchmark)
    levels = {"market_benchmark": benchmark, "layers_and_arms": friday_metrics(friday),
              "friday_rosters": seal["friday_audit"],
              "friday_breadth_source": sources.breadth_identity,
              "cutoff_mark_symbols": len(marks), "cutoff_mark_symbols_known": sum(v is not None for v in marks.values()),
              "monday_reader": reader.identity}
    timing, detail = timing_metrics(armed, sources, marks)
    detail.extend(friday)
    detail.append({"record_type": "MONDAY_MARKET_BASELINE", "trade_date": data.MONDAY,
                   **{k: v for k, v in benchmark.items() if not isinstance(v, dict)}})
    for day, evidence in seal["timing_by_day"].items():
        s, b, m = evidence["stage"], evidence["breadth"], evidence["market_return_5d"]
        detail.append({"record_type": "TIMING_EVIDENCE", "trade_date": day,
                       **{key: s[key] for key in ("eligible_n", "confirmed_n", "stage_known_n", "stage_unknown_n", "damaged_n",
                                                 "damaged_share_all_eligible_min", "damaged_share_all_eligible_max",
                                                 "damaged_share_known_stage", "quote_source", "signal_scope_status")},
                       **b, "market_trailing_5d": m["trailing_5_return"], "market_trailing_5d_source": m["source"],
                       **{f"gate_{name}": result for name, result in evidence["timing_gates"].items()}})
    return timing, levels, detail


def bind_start(sources, reader, workers):
    files = [Path(__file__).resolve(), Path(data.__file__).resolve(), Path(a31.old.__file__).resolve(),
             Path(a31.review.__file__).resolve(), Path(a36i.__file__).resolve()]
    obj = {"schema": data.SCHEMA, "phase": "D_ONLY_STARTED", "ACT036_selection": data.ACT036_SEAL,
           "ACT036_day_checkpoints": sources.checkpoint_refs,
           "ACT036_outcome_summary_declared": data.ACT036_SUMMARY_EXPECTED,
           "ACT036_delivery_csv_declared": data.ACT036_DELIVERY, "ACT013_width": sources.breadth_identity,
           "ACT031_and_ACT034_inputs": sources.prior.references, "V4_stage_reader": reader.identity,
           "signal_days": sources.days, "warmup_sessions": list(data.WARMUP), "cutoff": data.MONDAY,
           "code": [a31.ref(path) for path in files], "policy": POLICY, "workers": workers,
           "fit": FIT_ZERO, "predict": 0, "model_load": 0, **a31.FLAGS}
    return a31.json_atomic(OUT / data.RUN_START, obj)


def run(workers):
    start = perf_counter()
    sources = data.load_sources()
    reader = data.bound(sources, data.FRIDAY)
    execution = bind_start(sources, reader, workers)
    setup = perf_counter()
    selection_path = OUT / data.SEAL_NAME
    if selection_path.exists():
        seal_ref = a31.ref(selection_path)
        require(a31.read_ref(seal_ref)["run_start"] == execution, "RESUME_SELECTION_IDENTITY_DRIFT")
    else:
        seal_ref = seal_phase(sources, reader, execution, workers)
    print("SELECTION_SEALED", seal_ref["sha256"], flush=True)
    sealed = perf_counter()
    a31.json_atomic(OUT / "OUTCOME_REPLAY_STARTED.json", {"schema": data.SCHEMA, "scope_count": 54, "cutoff": data.MONDAY,
                    "fresh_seal": seal_ref, "forward_replay_count": 1, "outcomes_source": data.ACT036_DELIVERY})
    projected = OUT / "OUTCOME_PROJECTION.json"
    if projected.exists():
        out_ref = a31.ref(projected)
        saved = a31.read_ref(out_ref)
        require(saved["fresh_seal"] == seal_ref, "OUTCOME_PROJECTION_IDENTITY_DRIFT")
        timing, monday, rows = saved["timing"], saved["monday"], saved["rows"]
    else:
        timing, monday, rows = total_outcomes(sources, seal_ref)
        out_ref = a31.json_atomic(projected, {"schema": data.SCHEMA, "fresh_seal": seal_ref,
                                              "timing": timing, "monday": monday, "rows": rows})
    generated = perf_counter()
    csv_ref = a35.write_csv_atomic(OUT / CSV_NAME, rows)
    final_seal = a31.read_ref(seal_ref)
    stages = [a31.read_ref(ref) for ref in final_seal["stage_receipts"].values()]
    finish = perf_counter()
    result = {"schema": data.SCHEMA, "phase": "FORWARD_REPLAY_COMPLETE", "cutoff": data.MONDAY,
              "selection_seal": seal_ref, "outcome_projection": out_ref, "detail_csv": csv_ref,
              "signal_dates": sources.days, "scope_count": 54, "T2_authority": sources.breadth_identity,
              "friday_D_state": final_seal["timing_by_day"][data.FRIDAY],
              "timing": timing, "monday": monday, "fee": r34.FEE, "policy": POLICY,
              "bootstrap": {"method": "paired contiguous five-session moving blocks", "seed": a35.SEED, "draws": a35.N_BOOTSTRAP},
              "runtime": {"wall_seconds_before_summary": finish - start, "setup_seconds": setup - start,
                          "signal_and_stage_seconds": sealed - setup, "re_evaluation_seconds": generated - sealed,
                          "csv_and_evidence_seconds": finish - generated, "cores": os.cpu_count(), "workers": workers,
                          "worker_blas": 1, "worker_arrow": 1, "main_arrow": arrow.cpu_count(),
                          "peak_parent_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                          "largest_worker_peak_rss_bytes": max(s["worker_peak_rss_bytes"] for s in stages),
                          "aggregate_family_peak_rss_bytes": "CANNOT_CONFIRM_WITHOUT_CONCURRENT_SAMPLING",
                          "read_write_physical_bytes": "CANNOT_CONFIRM", "csv_written_bytes": csv_ref["bytes"],
                          "upload_bytes": 0},
              "fit_calls": FIT_ZERO, "predict_count": 0, "model_load_count": 0, "forward_replay_count": 1,
              "historical_PIT": "CANNOT_CONFIRM", **a31.FLAGS}
    return a31.json_atomic(OUT / "SUMMARY.json", result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", required=True, action="store_true")
    parser.add_argument("--workers", type=int, default=10)
    arguments = parser.parse_args(argv)
    require(1 <= arguments.workers <= 12, "WORKER_RESOURCE_SCOPE")
    arrow.set_cpu_count(min(8, os.cpu_count() or 1))
    with a31.exclusive_run(OUT):
        require(not (OUT / "SUMMARY.json").exists(), "ONE_FORWARD_ALREADY_COMPLETE")
        ref = run(arguments.workers)
    print("FORWARD_REPLAY_COMPLETE", ref["sha256"], flush=True)


if __name__ == "__main__":
    main()
