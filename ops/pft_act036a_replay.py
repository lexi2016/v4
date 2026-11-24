"""ACT036A named DEV and early-window replay with locally labeled diagnostic inputs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, namedtuple
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import csv
from decimal import Decimal
import json
from math import isclose
from multiprocessing import get_context
import os
from pathlib import Path
import resource
from time import perf_counter
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as arrow

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as g
from ops import pft_act033a_replay as a33
from ops import pft_act033a_outcomes as o33
from ops import pft_act034a_replay as a34
from ops import pft_act034a_rules as r34
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as source

OUT = a35.ROOT / "pft_act036a_oot_20261124"
CSV_NAME = "CODEX_MAC_ACT-036A_50D_OOT_A1V2_B2V2_TRADES_20261124.csv"
SCHEMA = "pft.act036a.oot_research.v1"
LANES = ("A1_BASE", "A1_V2", "B2_BASE", "B2_V2_STRICT", "B2_V2_WIDE")
A1_BASE, A1_V2, B2_BASE, STRICT, WIDE = LANES
ACT035_DEV = {"path": str(a35.OUTPUT / a35.CSV_NAME),
              "sha256": "e881316cc3db4bf49ee8ec4bbb0e87cfab619557d251d204431f67dee72bcc4a"}
ACT032 = {"path": str(a35.ROOT / "pft_act032_sv2_grid_pk_20261123/PFT_V4_ACT032_CODEX_SV2_OOF_TEST_20261123.csv"),
          "sha256": "803db91a11906297a9902de5ef363cf7d39858de9c49d3ed4500f15a3ddaab4c"}
FIELDS_PFT = ("active_close_vs_low_pct", "vol_contraction_vs_platform", "anchor_age_sessions",
              "active_anchor_low", "active_anchor_source", "active_anchor_date", "intact_anchor",
              "V02", "V04", "V06", "pft_status")
DEV_FIELDS = ("source_scope", "trade_date", "ts_code", *f35.P515_FIELDS, *FIELDS_PFT)
TRUTH = frozenset(("l50m", "hard_climax", "intact_anchor", "V02", "V04", "V06"))
POLICY = {
    A1_BASE: "ACT034A frozen A1_EXIT+C1, with original daily caps and no refill. Exact ACT034A roster on DEV.",
    A1_V2: "Union original A1_BASE with exact UNKNOWN_BORDERLINE, main board 60.SH/00.SZ, POST_REPAIR, projected >=.90, active close margin (0,.10], contraction <=.75, anchor age >=8 sessions, V02/V04/V06 known false, active anchor intact and original C1, exact lone LINE_SPREAD_LT_0015 or an exact STRONG_BINARY_FAKE_HEAD_CONTRADICTION token, excluding rebuild repair age token.",
    B2_BASE: "ACT034A frozen B2_QUICK, no C1/re-rank on DEV.",
    STRICT: "ACT035A structure, amplitude20 >=3%, attack >=12pp, D bullish gain [1%,5%], wick <=3%, L50M, hard climax known false, circ mv <=30bn, cushion (.05,.12], drawdown [-8,-2]pp, observed peak age [3,10], decay <.75, amount ratio <=1.2.",
    WIDE: "STRICT with drawdown [-10,-1.5]pp, peak age [2,12], decay <=.80, amount ratio <=1.50.",
    "B2_PRIORITY": "Original golden pure-head first, projected score descending and exact code ascending, maximum 5/date.",
    "A1_EXIT": a34.POLICY["A1_EXIT"], "B2_QUICK_EXIT": a34.POLICY["B2_QUICK"],
    "RANK_SOURCE_STANDARD": ["V4_OFFICIAL_TOP200", "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK", source.RAW_DIAGNOSTIC],
    "DIAGNOSTIC_SCOPE": "Historical panel reconstruction, missing dated ST status, basis-dependent volume, cent reconstruction and theoretical QFQ pre-close. Historical PIT CANNOT_CONFIRM. Proxy rankings and prices have explicit source labels.",
    "EXPOSURE": "OOT_EARLY timing means after training cutoff. Sensitivity removes exact code/date matches in SHA-bound ACT035A external and ACT032 OOT-test records, with no replacement.",
}
FIT_ZERO = dict(a33.FIT_CALLS)
SIGNAL_SEAL = "SELECTION_SEAL.json"
START = "RUN_STARTED.json"
OUTCOMES = "OUTCOMES_CHECKPOINT.json"
SUMMARY = "SUMMARY.json"
POLICY_TREE = (A1_BASE, A1_V2, B2_BASE, STRICT, WIDE)
EXACT_LINE = "LINE_SPREAD_LT_0015"
STRONG = "STRONG_BINARY_FAKE_HEAD_CONTRADICTION"
EARLY_REBUILD = "REBUILD_REPAIR_AGE_LT_4D"
require = source.require


def projected_prior_inputs(sources):
    path = a33.checked(ACT035_DEV)
    locked = pd.read_csv(path, usecols=lambda n: n in set(DEV_FIELDS), dtype=str,
                         keep_default_na=False, encoding="utf-8-sig")
    dev = locked.loc[locked.source_scope.eq("FORWARD_ACT034A")].drop(columns="source_scope")
    for name in TRUTH:
        require(set(dev[name].unique()) <= {"True", "False", ""}, f"DEV_BOOLEAN_DRIFT:{name}")
        dev[name] = dev[name].map({"True": True, "False": False, "": None})
    for name in (*f35.P515_FIELDS, "active_close_vs_low_pct", "vol_contraction_vs_platform",
                 "anchor_age_sessions", "active_anchor_low"):
        if name not in TRUTH:
            dev[name] = pd.to_numeric(dev[name], errors="coerce")
    require(set(dev.trade_date) == set(sources.dev) and not dev.duplicated(["ts_code", "trade_date"]).any(),
            "ACT035_DEV_KEYS_DRIFT")
    previous = {d: {row["ts_code"]: a35.clean_record(row) for row in data.to_dict("records")}
                for d, data in dev.groupby("trade_date", sort=False)}
    observed_a35 = locked.loc[locked.source_scope.eq("EXTERNAL_ACT028_FROZEN"), ["trade_date", "ts_code"]]
    exposed_a35 = {(d, c) for d, c in observed_a35.itertuples(index=False, name=None) if d in sources.oot}
    a32 = pd.read_csv(a33.checked(ACT032), usecols=["security_id", "D", "split_role"], dtype=str,
                     keep_default_na=False, encoding="utf-8-sig")
    days = a32.D.map(a31.act028.date8)
    exposed_a32 = {(d, c) for d, c in zip(days, a32.security_id) if d in sources.oot}
    require(len(exposed_a35) == 21 and len(exposed_a32) == 3
            and len({key[0] for key in (exposed_a35 | exposed_a32)}) == 12
            and len(exposed_a35 | exposed_a32) == 24, "EXPOSURE_KEY_SCOPE_DRIFT")
    exposed = {key: [name for name, keys in (("ACT035A_EXTERNAL", exposed_a35), ("ACT032_OOT_TEST", exposed_a32))
                     if key in keys] for key in sorted(exposed_a35 | exposed_a32)}
    return previous, exposed


def route_allowed(route):
    if route is None or pd.isna(route) or not str(route):
        return None
    tags = tuple(route.split(";"))
    return EARLY_REBUILD not in tags and (tags == (EXACT_LINE,) or STRONG in tags)


def coarse_a1(row):
    return g.conjunction(
        row.get("final_state") == "UNKNOWN_BORDERLINE" if row.get("final_state") is not None else None,
        g.main_board(row["ts_code"]), row.get("stage") == "POST_REPAIR" if row.get("stage") is not None else None,
        g.gte(g.finite(row.get("projected_p_s")), .90), route_allowed(row.get("route_reasons")),
    )


def a1_atoms(row, feature, c1):
    return {
        "coarse": coarse_a1(row),
        "close_margin_0_10": g.within(feature.get("active_close_vs_low_pct"), 0., .10, lower_closed=False),
        "contraction_le_075": g.lte(feature.get("vol_contraction_vs_platform"), .75),
        "anchor_age_ge_8": g.gte(feature.get("anchor_age_sessions"), 8),
        "V02_known_false": g.negation(feature.get("V02")),
        "V04_known_false": g.negation(feature.get("V04")),
        "V06_known_false": g.negation(feature.get("V06")),
        "active_anchor_intact": feature.get("intact_anchor"),
        "c1": c1,
    }


def b2_atoms(row, feature, strict):
    atoms = a35.elastic_atoms(row["b2_structural"], row, feature)
    for field in ("float_cap_le_50bn", "actual_pullback_2_to_8pp", "bars_since_peak_3_to_10",
                  "post_peak_decay_lt_075", "amount_ratio_le_12"):
        del atoms[field]
    low, high = (-8, -2) if strict else (-10, -1.5)
    lo_age, hi_age = (3, 10) if strict else (2, 12)
    return atoms | {
        "float_cap_le_30bn": g.lte(row.get("float_mv_d_cny"), 30e9),
        "cushion_above05_le12": g.within(row.get("cushion"), .05, .12, lower_closed=False),
        "drawdown": g.within(feature.get("drawdown_from_prior20_high_pp"), low, high),
        "peak_age": g.within(feature.get("days_since_20d_vol_peak"), lo_age, hi_age),
        "decay": (g.negation(g.gte(feature.get("pullback_vol_decay_ratio"), .75)) if strict
                  else g.lte(feature.get("pullback_vol_decay_ratio"), .80)),
        "amount_ratio": g.lte(feature.get("amount_ratio_20"), 1.2 if strict else 1.50),
    }


def b2_sort(row):
    probability = g.finite(row.get("projected_p_s"))
    return not row["b2_golden_priority"], -probability if probability is not None else np.inf, row["ts_code"]


def add_counts(target, atoms):
    for name, value in atoms.items():
        target[name]["pass" if value is True else "reject" if value is False else "unknown"] += 1


def quote_c1(quote, feature):
    if not quote:
        return None
    return a35.fx_c1(quote, feature, r34.upper_wick(quote))


class AlreadyRebased:
    """The shared model and selection prefix is already on D basis."""

    def __init__(self, act030):
        self.act030 = act030

    def suffix(self, code, day, start):
        return ()

    def for_window(self, code, day, frame):
        if frame is None:
            return None, None
        require(frame.trade_date.iat[-1] <= day, "PFT_POST_D_BAR")
        return (frame, 0) if frame.trade_date.iat[-1] == day else (None, None)


def feature_rows(day, candidates, prefix, quotes, authority, calendar, act030):
    if not candidates:
        return {}
    scope = set(candidates)
    target = prefix.loc[prefix.ts_code.isin(scope)].copy()
    target["_valid_bar"] = f35.valid_bars({name: target[name].to_numpy() for name in f35.COLUMNS})
    histories = f35.observed_histories(target)
    indexed = {code: group.set_index("trade_date", drop=False) for code, group in histories.items()}
    codes = sorted(scope)
    ready = AlreadyRebased(act030)
    grid, _ = f35.p515_for_day(day, codes, calendar, indexed, ready, quotes)
    results = {}
    for idx, code in enumerate(codes):
        quote = quotes.get(code)
        row = candidates[code]
        features = f35.scalar_grid(grid, idx)
        l50m = features["l50m"]
        if authority == source.PROXY and quote and quote.get("dated_st") is None and code.endswith((".SH", ".SZ")):
            features["l50m"] = g.conjunction(quote["high"] > quote["low"],
                                           g.gte(features["median_amount20_cny"], f35.LIQUIDITY_CNY))
            if not features["d_basis_close"]:
                features["l50m"] = None
        features["l50m_exact_dated_ST"] = l50m
        if coarse_a1(row) is not False:
            hint = a31.act028.date8(row.get("invalidation_anchor_date"))
            features.update(f35.pft_measure(code, day, histories.get(code), hint, None, features, ready, calendar, quote))
            if authority == source.PROXY and features.get("pft_status") == "D_RAW_ALIGNED":
                features["pft_status"] = "D_REBASED_PANEL_INTERNAL_ALIGNMENT"
        results[code] = features
    return results


def selection_row(day, row, feature, lane, rank, c1, authority):
    is_a1 = lane in (A1_BASE, A1_V2)
    anchor = (feature.get("active_anchor_low") if lane == A1_V2 and row.get("extension_only") else
              row.get("invalidation_price"))
    return a35.clean_record({
        "trade_date": day, "ts_code": row["ts_code"], "name": row.get("name"), "lane": lane,
        "strategy": "A1_EXIT" if is_a1 else "B2_QUICK", "selection_rank": rank,
        "signal_quote_source": authority, "D_admission": row.get("D_admission", source.EXACT_ADMISSION),
        "final_state": row.get("final_state"), "stage": row.get("stage"), "route_reasons": row.get("route_reasons"),
        "projected_p_s": row.get("projected_p_s"), "feature_context_end": row.get("feature_context_end"),
        "extension_only": row.get("extension_only", False), "c1_pass": c1,
        "b2_arm": row.get("b2_arm"), "b2_golden_priority": row.get("b2_golden_priority"),
        "close_d": row.get("close_d") if row.get("close_d") is not None else feature.get("d_basis_close"),
        "invalidation_price": anchor, "d_amplitude20": row.get("amplitude_ma20"),
        "float_mv_d_cny": row.get("float_mv_d_cny"), "cushion": row.get("cushion"),
        "float_cap_source": row.get("float_cap_source") or ("EXACT_V4_PANEL_FINANCE" if row.get("float_mv_d_cny") else None),
        "float_cap_event_date": row.get("float_cap_event_date"), "float_cap_status": row.get("float_cap_status"),
        "return_d": row.get("return_d"), "d_upper_wick": row.get("d_upper_wick"),
        **{k: feature.get(k) for k in (*f35.P515_FIELDS, *FIELDS_PFT, "l50m_exact_dated_ST")},
    })


def select(day, signals, overlay, features, quotes, authority, existing=None, missing_states=0):
    signal_lookup = {r["ts_code"]: a35.clean_record(r) for r in signals.to_dict("records")}
    rows = {}
    for code, row in signal_lookup.items():
        base = row | (overlay.get(code) or {})
        if code in overlay:
            base |= r34.selection_atoms(SimpleNamespace(**base), r34.upper_wick(quotes.get(code)))
        else:
            base["b2_structural"] = False
        rows[code] = base
    if existing is None:
        a1_base = [(r["ts_code"], r["A1_rank"]) for r in rows.values() if r.get("A1") is True and r["c1_pass"] is True]
        b2_base = [(r["ts_code"], rank) for rank, r in enumerate(sorted(
            (r for r in rows.values() if r.get("b2_eligible") is True), key=b2_sort)[:5], 1)]
    else:
        a1_base = [(code, rec["selection_rank"]) for (code, strat), rec in existing.items()
                   if strat == "A1_EXIT" and rec["c1_pass"] is True]
        b2_base = [(code, rec["selection_rank"]) for (code, strat), rec in existing.items() if strat == "B2_QUICK"]
        require(all(code in overlay for code, _ in [*a1_base, *b2_base]), f"DEV_BASELINE_OUTSIDE_GROUPS:{day}")
    chosen = {lane: [] for lane in LANES}
    for lane, frozen in ((A1_BASE, a1_base), (B2_BASE, b2_base)):
        for code, rank in sorted(frozen, key=lambda pair: pair[1]):
            row = rows[code]
            if existing is not None:
                row = row | existing[code, "A1_EXIT" if lane == A1_BASE else "B2_QUICK"]
            chosen[lane].append(selection_row(day, row, features.get(code, {}), lane, rank, row["c1_pass"], authority))
    chosen[A1_V2] = [row | {"lane": A1_V2} for row in chosen[A1_BASE]]
    a1_counts, b2_counts, masks = defaultdict(Counter), {STRICT: defaultdict(Counter), WIDE: defaultdict(Counter)}, defaultdict(Counter)
    additions, b2 = [], {STRICT: [], WIDE: []}
    for code, row in rows.items():
        current = features.get(code, {})
        if coarse_a1(row) is not False:
            c1 = row.get("c1_pass") if code in overlay else quote_c1(quotes.get(code), current)
            atoms = a1_atoms(row, current, c1)
            add_counts(a1_counts, atoms)
            verdict = g.conjunction(*atoms.values())
            add_counts(masks, {A1_V2: verdict})
            if verdict is True:
                additions.append((code, row, current, c1))
        for lane in (STRICT, WIDE):
            if row["b2_structural"] is False:
                continue
            atoms = b2_atoms(row, current, lane == STRICT)
            add_counts(b2_counts[lane], atoms)
            verdict = g.conjunction(*atoms.values())
            add_counts(masks, {lane: verdict})
            if verdict is True:
                b2[lane].append((row, current))
    for code, row, current, c1 in sorted(additions):
        chosen[A1_V2].append(selection_row(day, row | {"extension_only": True}, current, A1_V2,
                                          len(chosen[A1_V2]) + 1, c1, authority))
    for lane in (STRICT, WIDE):
        for rank, (row, current) in enumerate(sorted(b2[lane], key=lambda pair: b2_sort(pair[0]))[:5], 1):
            chosen[lane].append(selection_row(day, row, current, lane, rank, row.get("c1_pass"), authority))
    return chosen, {
        "a1_added_n": len(additions), "eligible_on_gate_scope": dict(masks), "a1_extension_atoms": dict(a1_counts),
        "b2_atoms": b2_counts, "b2_above_daily_cap": {lane: max(0, len(b2[lane]) - 5) for lane in (STRICT, WIDE)},
        "missing_full_model_state_n": missing_states,
    }


def by_day_originals(sources):
    lookup = defaultdict(dict)
    for (day, code, strategy), record in a35.original_rosters(sources.previous).items():
        lookup[day][code, strategy] = record
    return lookup


def day_checkpoint(day, run_sha, chosen, audit):
    return {"schema": SCHEMA, "phase": "D_SIGNAL_RECORDED", "trade_date": day, "run_sha": run_sha,
            "selections": chosen, "audit": audit, **a31.FLAGS}


def read_checkpoint(path, day, run_sha):
    reference = a31.ref(path)
    row = a31.read_ref(reference)
    require(row["schema"] == SCHEMA and row["phase"] == "D_SIGNAL_RECORDED"
            and row["trade_date"] == day and row["run_sha"] == run_sha
            and set(row["selections"]) == set(LANES)
            and all(r["trade_date"] == day and r["lane"] == lane for lane, data in row["selections"].items()
                    for r in data), f"CHECKPOINT_IDENTITY_DRIFT:{day}")
    return row, reference


def signal_inputs_stats(signals, admission, frame, quote_source, official_ref, additional):
    return {"quote_evidence": quote_source, "official_ref": official_ref,
            "archive_d_rows_n": len(frame), "eligible_n": len(signals), "admission": admission,
            "prediction_status": signals.prediction_status.value_counts().to_dict(),
            "final_state": signals.final_state.value_counts().to_dict(), **additional}


def reconstruct_day(day, archive, finances, reader_basis, models, sessions, calendar, official, official_ref,
                    saved_signals=None, saved_overlays=None, saved_roster=None, saved_features=None, capital=None):
    chart_start = f35.earlier(day, source.FORECAST_HISTORY)
    prefix, restore = reader_basis.prefix(archive, day, chart_start)
    exact = prefix.loc[prefix.trade_date.eq(day)]
    quotes, authority = source.quotes_for_day(archive, day, reader_basis, official)
    eligible, admission = source.historical_admission(prefix, day, quotes, authority)
    if not eligible:
        return {lane: [] for lane in LANES}, None, {"status": "CANNOT_CONFIRM_NO_A_ADMITTED",
               "admission": admission, "quote_evidence": authority, "official_ref": official_ref, **restore}
    scoring = {code for code, row in eligible.items() if not a31.strict_g1(row["white"], row["yellow"])}
    history = prefix.loc[prefix.ts_code.isin(scoring), [*a31.old.INPUTS, "bbi"]]
    signals = a31.route_signals(eligible, history, day, models, sessions)
    require(signals.trade_date.eq(day).all() and signals.feature_context_end.dropna().eq(day).all()
            and not signals.ts_code.duplicated().any(), f"ACT031_CAUSAL_SIGNAL_KEY_DRIFT:{day}")
    position = calendar.index(day)
    days = calendar[position - 20:position + 1]
    scope = g.overlay_scope(signals)
    overlay_prefix = prefix.loc[prefix.ts_code.isin(scope)]
    overlay_prefix = overlay_prefix.merge(finances.loc[finances.ts_code.isin(scope)],
                                         on=["ts_code", "trade_date"], how="left", validate="one_to_one")
    all_groups, _ = g.select_day(signals, overlay_prefix, quotes, days)
    projected = all_groups.loc[all_groups.BASE | all_groups.b1_structural_eligible.fillna(True)]
    overlays = {row["ts_code"]: a35.clean_record(row) for row in projected.to_dict("records")}
    cap_counts = {}
    if capital is not None:
        overlays, cap_counts = source.recover_capital(day, overlays, quotes, capital)
    recovery = None
    if saved_overlays is not None:
        # Reconstructing unretained 10/23 scores earns admission only with
        # state/router/probability and recovered eligibility parity.
        recovery = saved_parity(signals, saved_signals, saved_overlays)
        if not recovery["passed"]:
            known, cap_counts = source.recover_capital(day, saved_overlays, quotes, capital) if capital is not None else (saved_overlays, {})
            chosen, audit = select(day, saved_signals, known, saved_features, quotes, authority, saved_roster,
                                   int(saved_signals.final_state.isna().sum()))
            return chosen, signals, signal_inputs_stats(signals, admission, exact, authority, official_ref,
                       {"status": "DEV_1023_RECOVERY_PARITY_FAILED_REUSE_KNOWN", "recovery": recovery,
                        "float_cap_reconstruction": cap_counts, **restore, **audit})
        overlays = overlays | saved_overlays
        if capital is not None:
            overlays, cap_counts = source.recover_capital(day, overlays, quotes, capital)
    candidates = {}
    for signal in signals.to_dict("records"):
        code = signal["ts_code"]
        row = a35.clean_record(signal)
        overlay = overlays.get(code)
        if coarse_a1(row) is not False or (overlay and r34.selection_atoms(SimpleNamespace(**overlay),
                r34.upper_wick(quotes.get(code)))["b2_structural"] is not False):
            candidates[code] = row
    current = feature_rows(day, candidates, prefix, quotes, authority, calendar, reader_basis.act030)
    chosen, audit = select(day, signals, overlays, current, quotes, authority, saved_roster)
    return chosen, signals, signal_inputs_stats(signals, admission, exact, authority, official_ref,
                        {"status": "SIGNALS_FROZEN", "recovery": recovery, "act031_score_attempts": len(scoring),
                         "float_cap_reconstruction": cap_counts,
                         **restore, **audit})


def saved_parity(signals, saved, overlays):
    exact = signals.set_index("ts_code").to_dict("index")
    fields = ("final_state", "stage", "route_reasons", "main_tactic", "invalidation_anchor_date")
    different = []
    for code, known in overlays.items():
        got = a35.clean_record(exact.get(code, {}))
        mismatched = [name for name in fields if got.get(name) != known.get(name)]
        score1, score2 = g.finite(got.get("projected_p_s")), g.finite(known.get("projected_p_s"))
        if score1 is None or score2 is None:
            score_match = score1 is score2
        else:
            score_match = isclose(score1, score2, rel_tol=0, abs_tol=1e-12)
        if not score_match:
            mismatched.append("projected_p_s")
        if mismatched:
            different.append({"ts_code": code, "fields": mismatched})
    saved_keys, inferred_keys = set(saved.ts_code), set(exact)
    return {"passed": not different and inferred_keys == saved_keys, "known_projected_n": len(overlays),
            "known_mismatches": different, "saved_universe_n": len(saved_keys), "inferred_universe_n": len(inferred_keys),
            "saved_missing_in_inference_n": len(saved_keys - inferred_keys),
            "inference_outside_saved_n": len(inferred_keys - saved_keys)}


_WORKER = None


def init_worker(reader, expected, calendar, snapshot_calendar, capital):
    from threadpoolctl import threadpool_limits

    global _WORKER
    arrow.set_cpu_count(1)
    arrow.set_io_thread_count(2)
    limits = threadpool_limits(limits=1)
    _WORKER = source.Basis(reader), source.load_model(expected), calendar, snapshot_calendar, limits, capital


def worker_batch(archive, finances, tasks, run_sha, checkpoint_root):
    basis, models, days, sessions, _, capital = _WORKER
    results = []
    for day, quotes, official_ref, prior in tasks:
        started = perf_counter()
        chosen, _, audit = reconstruct_day(day, archive, finances, basis, models, sessions, days, quotes,
                                          official_ref, *(prior or ()), capital=capital)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        audit |= {"elapsed_seconds": perf_counter() - started, "worker_pid": os.getpid(),
                  "worker_peak_rss_bytes": usage.ru_maxrss, "model_predict_heads": 2}
        payload = day_checkpoint(day, run_sha, chosen, audit)
        reference = a31.json_atomic(checkpoint_root / f"{day}.json", payload)
        print(json.dumps({"phase": "D_SIGNAL_RECORDED", "day": day, "counts": {k: len(v) for k, v in chosen.items()},
                          "admitted_n": audit.get("eligible_n"), "seconds": round(audit["elapsed_seconds"], 1),
                          "mode": audit["quote_evidence"], "reference": reference}), flush=True)
        results.append(day)
    return results


def worker_archive(reader):
    projected = {code: {name: item[name] for name in ("history_start_date", "event_coverage_complete", "events")
                        if name in item} for code, item in reader.symbols.items()}
    return source.Reader(reader.binding, projected, reader.asof, reader.identity)


def historical_jobs(pending, history, finance, sources, by_day, originals, days_per_batch):
    for off in range(0, len(pending), days_per_batch):
        days = pending[off:off + days_per_batch]
        first, last = days[0], days[-1]
        lo = f35.earlier(first, source.FORECAST_HISTORY)
        model_history = history.loc[history.trade_date.between(lo, last)].reset_index(drop=True)
        to_finance = finance.loc[finance.trade_date.between(
            sources.calendar[sources.calendar.index(first) - 20], last)].reset_index(drop=True)
        tasks = []
        for day in days:
            quotes, official = sources.official_days[day]
            prior = None
            if day == sources.dev[0]:
                prior = (sources.previous.all_signals[day], sources.previous.overlays[day],
                         originals[day], by_day[day])
            tasks.append((day, quotes, official, prior))
        yield model_history, to_finance, tasks


def history_read(sources, reader, pending):
    start = f35.earlier(pending[0], source.FORECAST_HISTORY)
    end = pending[-1]
    bars = source.read_history(reader, start, end)
    n = bars.ts_code.nunique()
    require(n > 0 and len(bars) <= n * 320, "SCOPED_READER_PROJECTION_TOO_LARGE")
    lo = sources.calendar[sources.calendar.index(pending[0]) - 20]
    finances = source.finance_history(reader, lo, end, set(bars.ts_code))
    audit = {"bounds": [start, end], "codes": n, "reader_rows": len(bars), "finance_rows": len(finances),
             "projected_memory_bytes": int(bars.memory_usage(index=True, deep=True).sum()
                                      + finances.memory_usage(index=True, deep=True).sum())}
    return bars, finances, audit


def run_signals(sources, reader, latest, by_day, originals, exposed, capital, start_ref, checkpoint_root, workers):
    checkpoint_root.mkdir(exist_ok=True)
    run_sha = start_ref["sha256"]
    pending = [d for d in [*sources.oot, sources.dev[0]] if not (checkpoint_root / f"{d}.json").exists()]
    reader_audit = {}
    # Recover completed day checkpoints only if they still bind the same start
    # identity. Re-inference applies only to missing days of this single run.
    for day in [*sources.oot, *sources.dev, source.LATEST]:
        path = checkpoint_root / f"{day}.json"
        if path.exists():
            read_checkpoint(path, day, run_sha)
    if pending:
        projected, finances, reader_audit = history_read(sources, reader, pending)
        if workers == 1:
            init_worker(worker_archive(reader), sources.model_expected, sources.calendar, sources.previous.calendar, capital)
            for batch in historical_jobs(pending, projected, finances, sources, by_day, originals, 3):
                worker_batch(*batch, run_sha, checkpoint_root)
        else:
            with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"), initializer=init_worker,
                     initargs=(worker_archive(reader), sources.model_expected, sources.calendar, sources.previous.calendar, capital)) as pool:
                jobs = iter(historical_jobs(pending, projected, finances, sources, by_day, originals, 2))
                running = {pool.submit(worker_batch, *batch, run_sha, checkpoint_root)
                           for batch in (next(jobs, None) for _ in range(workers)) if batch is not None}
                while running:
                    finished, running = wait(running, return_when=FIRST_COMPLETED)
                    for future in finished:
                        future.result()
                    for _ in finished:
                        batch = next(jobs, None)
                        if batch is not None:
                            running.add(pool.submit(worker_batch, *batch, run_sha, checkpoint_root))
    for day in sources.dev[1:]:
        path = checkpoint_root / f"{day}.json"
        if path.exists():
            continue
        official, off_ref = sources.official_days[day]
        signals = sources.previous.all_signals[day]
        overlays, cap_counts = source.recover_capital(day, sources.previous.overlays[day], official, capital)
        chosen, audit = select(day, signals, overlays, by_day[day], official, source.OFFICIAL, originals[day])
        a31.json_atomic(path, day_checkpoint(day, run_sha, chosen, {"status": "REUSED_ACT031_ACT035A_D",
                                      "eligible_n": len(signals), "official_ref": off_ref, "float_cap_reconstruction": cap_counts, **audit}))
    path = checkpoint_root / f"{source.LATEST}.json"
    if not path.exists():
        models = source.load_model(sources.model_expected)
        projection, finance, audit = history_read(sources, latest, [source.LATEST])
        official, off_ref = sources.official_days[source.LATEST]
        chosen, _, latest_audit = reconstruct_day(source.LATEST, projection, finance, source.Basis(latest), models,
                             sources.previous.calendar, sources.calendar, official, off_ref)
        a31.json_atomic(path, day_checkpoint(source.LATEST, run_sha, chosen, latest_audit | audit))
    dated = [*sources.oot, *sources.dev, source.LATEST]
    records = {day: read_checkpoint(checkpoint_root / f"{day}.json", day, run_sha)[1] for day in dated}
    evidence = {"schema": SCHEMA, "phase": "SELECTION_SEALED", "run_started": start_ref, "days": dated,
                "oot_dates": sources.oot, "dev_dates": sources.dev, "latest_date": source.LATEST,
                "historical_reader_projection": reader_audit, "checkpoints": records,
                "known_previously_exposed_keys": [{"trade_date": d, "ts_code": c, "sources": tags}
                                                 for (d, c), tags in exposed.items()],
                "cutoff": source.CUTOFF, "observations_opened_before_seal": False, **a31.FLAGS}
    return a31.json_atomic(OUT / SIGNAL_SEAL, evidence)


OFFICIAL_RANKS = frozenset(("V4_OFFICIAL_TOP200", "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"))
OUTCOME_KEYS = ("trade_date", "ts_code", "strategy")
OutcomeInput = namedtuple("OutcomeInput", (*OUTCOME_KEYS, "close_d", "invalidation_price"))


def evaluation_inputs(sources, latest, codes):
    days = sources.calendar[sources.calendar.index(sources.oot[0]) - 1:sources.calendar.index(source.CUTOFF) + 1]
    cutoff = source.read_history(latest, days[0], source.CUTOFF,
                                 columns=("open", "high", "low", "close", "vol", "pre_close", "amount", "tradeable_basic"))
    require(len(cutoff) <= len(days) * cutoff.ts_code.nunique(), "OUTCOME_PROJECTION_SCOPE_TOO_LARGE")
    basis = source.Basis(latest)
    observed, outcomes = {}, {}
    cutoff_days = {day: group for day, group in cutoff.groupby("trade_date", sort=False)}
    for day in days[1:]:
        official, identity = sources.official_days[day]
        quotes, mode = source.quotes_for_day(cutoff_days.get(day, cutoff.iloc[:0]), day, basis, official)
        ranks, rank_source = {}, "CANNOT_CONFIRM"
        if quotes:
            if mode == source.OFFICIAL:
                ranks, rank_source = a31.rank_for_day(day, sources.previous.inputs["days"][day], quotes)
            elif len(quotes) >= 200:
                roster = sorted(quotes.values(), key=lambda row: (-row["change_pct"], row["symbol"]))
                ranks = {row["symbol"]: idx for idx, row in enumerate(roster[:200], 1)}
                rank_source = source.RAW_DIAGNOSTIC
        scoped = {k: v for k, v in quotes.items() if k in codes}
        observed[day] = (scoped, identity)
        outcomes[day] = {"quotes": scoped, "ranks": {k: v for k, v in ranks.items() if k in codes},
                         "rank_source": rank_source, "quote_evidence": mode, "official_ref": identity,
                         "full_rank_universe_n": sum(r["eligible_for_daily_gain_rank"] for r in quotes.values())}
    bars = {code: group.set_index("trade_date").to_dict("index") for code, group in
            cutoff.loc[cutoff.ts_code.isin(codes)].groupby("ts_code", sort=False)}
    return outcomes, observed, bars, days, {"rows": len(cutoff), "symbols": cutoff.ts_code.nunique(),
                                           "bounds": [days[0], source.CUTOFF], "source": latest.identity,
                                           "projected_memory_bytes": int(cutoff.memory_usage(index=True, deep=True).sum())}


def attempt_known_rule(result, code, dates, start, timing, quotes, prices):
    """ACT034A attempt queue with a labelled alternative only for missing official inputs."""
    result.planned_time = timing
    if start >= len(dates):
        result.status = "EXIT_DUE_AFTER_CUTOFF"
        if dates:
            result.cutoff_mark = prices.get(dates[-1], {}).get("close")
        return result
    for offset, date in enumerate(dates[start:]):
        when = timing if offset == 0 else "OPEN"
        quote = quotes.get(date)
        if quote and quote.get("quote_evidence") == source.PROXY:
            feasible, why = diagnostic_sell(code, quote, when)
        else:
            feasible, why = (r34.opening_sell if when == "OPEN" else o33.selling_outcome)(code, quote)
        price = prices.get(date, {}).get(when.lower())
        if feasible is True and price is None:
            feasible, why = None, "EXIT_PRICE_BASIS_UNCONFIRMED"
        result.attempts.append({"date": date, "time": when, "fillable": feasible, "reason": why})
        if feasible is True:
            result.status = "MODELED_FILLED_DELAYED" if offset else "MODELED_FILLED"
            result.exit_date, result.time, result.price = date, when, price
            return result
    result.status = ("EXIT_BLOCKED_AT_DEADLINE" if all(a["fillable"] is False for a in result.attempts)
                     else "EXIT_UNRESOLVED_AT_DEADLINE")
    result.cutoff_mark = prices.get(dates[-1], {}).get("close")
    return result


def diagnostic_sell(code, quote, when):
    band, previous = a31.inferred_band(code), a31.positive(quote.get("prev_close"))
    if previous is None or band is None or quote.get("dated_st") is True:
        return None, "DIAGNOSTIC_STANDARD_CAP_INPUT_UNKNOWN"
    if not quote["eligible_for_daily_gain_rank"]:
        return (False, "DIAGNOSTIC_NO_VOLUME") if quote.get("zero_volume") else (None, "DIAGNOSTIC_INVALID_BAR")
    floor = r34.cap_price(previous, 1 - Decimal(band))
    test = quote["open"] if when == "OPEN" else quote["low"]
    actual = quote["open"] if when == "OPEN" else quote["close"]
    if test < floor - 1e-6:
        return None, "DIAGNOSTIC_STANDARD_CAP_EXCEPTION"
    if actual <= floor + 1e-6:
        return False, f"DIAGNOSTIC_{when}_AT_LOWER_CAP"
    return True, f"DIAGNOSTIC_MODELED_{when}"


def diagnostic_b2(code, dates, quotes, prices):
    dates = dates[:3]
    day = dates[0]
    quote = quotes.get(day)
    triggers = r34.quick_triggers(code, quote)
    if quote and quote.get("quote_evidence") == source.PROXY:
        previous, band = a31.positive(quote.get("prev_close")), a31.inferred_band(code)
        unlocked = None
        if previous is not None and band is not None:
            cap = r34.cap_price(previous, 1 + Decimal(band))
            if quote["high"] <= cap + 1e-6:
                unlocked = quote["close"] < cap - 1e-6
        triggers["D1_HIGH_GTE_4_AND_CLOSE_BELOW_CAP"] = g.conjunction(
            g.gte(r34.raw_ratio(quote, "high", "prev_close"), .04), unlocked)
        triggers["D1_CLOSE_LTE_MINUS_3_VS_REBASED_QFQ_PREV"] = triggers.pop(
            "D1_CLOSE_LTE_MINUS_3_VS_OFFICIAL_PREV")
    reason = r34.reason_string(triggers)
    if reason:
        return attempt_known_rule(r34.ExitOutcome(reason, signal_date=day), code, dates, 1, "OPEN", quotes, prices)
    if None in triggers.values():
        return r34.ExitOutcome("B2_D1_QUICK_TRIGGER_UNKNOWN", signal_date=day,
                               unknown_decision_atoms=r34.reason_string(triggers, None))
    if len(dates) < 3:
        return r34.ExitOutcome("PLANNED_HORIZON_NOT_REACHED", status="HORIZON_IMMATURE_AT_CUTOFF")
    return attempt_known_rule(r34.ExitOutcome("T3_PLANNED_CLOSE", signal_date=dates[2]),
                              code, dates, 2, "CLOSE", quotes, prices)


def diagnostic_a1(code, dates, context, quotes, prices, entry, anchor, ma_closes):
    dates = dates[:5]
    extension = {}
    for index, date in enumerate(dates):
        horizon = index + 1
        close = prices.get(date, {}).get("close")
        d1_o2c = r34.raw_ratio(quotes.get(date), "close", "open") if horizon == 1 else None
        triggers = r34.stop_triggers(close, anchor, entry, d1_o2c, horizon)
        reason = r34.reason_string(triggers)
        if horizon == 5:
            result = r34.ExitOutcome("T5_HARD_CLOSE", signal_date=date,
                t5_trigger_audit=reason or ("CANNOT_CONFIRM" if None in triggers.values() else "NONE"), **extension)
            return attempt_known_rule(result, code, dates, index, "CLOSE", quotes, prices)
        if reason:
            result = r34.ExitOutcome(reason, signal_date=date, **extension)
            return attempt_known_rule(result, code, dates, index + 1, "OPEN", quotes, prices)
        if None in triggers.values() and not quotes.get(date, {}).get("zero_volume"):
            return r34.ExitOutcome("A1_INTERMEDIATE_STOP_EVIDENCE_UNKNOWN", signal_date=date,
                                   unknown_decision_atoms=r34.reason_string(triggers, None), **extension)
        if horizon == 3:
            position = context.index(date)
            trailing = [ma_closes.get(s) for s in context[max(0, position - 4):position + 1]]
            ma5 = sum(trailing) / 5 if len(trailing) == 5 and None not in trailing else None
            extension = {"t3_ma5": ma5, "t3_close": close}
            if close is not None and close > entry + r34.EPS:
                if ma5 is None:
                    return r34.ExitOutcome("T3_EXTENSION_MA5_UNKNOWN", signal_date=date,
                                           unknown_decision_atoms="T3_MA5", **extension)
                if close >= ma5 - r34.EPS:
                    continue
            return attempt_known_rule(r34.ExitOutcome("T3_PLANNED_CLOSE", signal_date=date, **extension),
                                      code, dates, index, "CLOSE", quotes, prices)
    return r34.ExitOutcome("PLANNED_HORIZON_NOT_REACHED", status="HORIZON_IMMATURE_AT_CUTOFF", **extension)


def evaluate_with_tiers(row, observations, observed, bars, events, days):
    day, code, strategy = (row[k] for k in OUTCOME_KEYS)
    cursor = days.index(day)
    horizon = 5 if strategy == "A1_EXIT" else 3
    span = days[cursor + 1:cursor + 1 + horizon]
    relevant = days[cursor + 1:cursor + 6]
    authority = {d: observations[d]["quote_evidence"] for d in span}
    official_path = all(value == source.OFFICIAL for value in authority.values()) and observations[day]["quote_evidence"] == source.OFFICIAL
    d1 = relevant[0]
    if official_path:
        args = OutcomeInput(*(row[k] for k in OutcomeInput._fields))
        exact = a34.evaluate_row(args, observations, observed, bars, events, days, None)
        out = a35.outcome_record(exact)
        out["outcome_rule_source"] = "ACT034A_EXACT_OFFICIAL_QUOTE_PATH"
    else:
        quotes = {d: observed[d][0][code] for d in relevant if code in observed[d][0]}
        prices = {d: r34.verified_bar(bars.get(d), quotes.get(d), d, events)[0] for d in relevant}
        d_bar, d_status = r34.verified_bar(bars.get(day), observed[day][0].get(code), day, events)
        aligned = r34.same_price(d_bar.get("close"), r34.to_cutoff_basis(row["close_d"], day, events))
        anchor = r34.to_cutoff_basis(row["invalidation_price"], day, events) if aligned else None
        price_path = {d: v["close"] for d, v in prices.items() if "close" in v}
        if aligned:
            price_path[day] = d_bar["close"]
        prior = bars.get(days[cursor - 1], {})
        if prior.get("tradeable_basic") == 1 and a31.positive(prior.get("vol")) is not None:
            price_path[days[cursor - 1]] = a31.positive(prior.get("close"))
        opened = a31.opening_assessment(code, quotes.get(d1))
        fillable = opened["opening_buyable_proxy"]
        entry = prices[d1].get("open") if fillable is True else None
        if entry is not None:
            result = (diagnostic_a1(code, span, days, quotes, prices, entry, anchor, price_path) if strategy == "A1_EXIT"
                      else diagnostic_b2(code, span, quotes, prices))
            path = r34.path_low(span, prices, result, entry)
        else:
            reason = ("ENTRY_PRICE_BASIS_UNCONFIRMED" if fillable is True else opened["opening_status"])
            result = r34.ExitOutcome(reason, status="KNOWN_UNFILLED_ENTRY" if fillable is False else "ENTRY_UNCONFIRMED")
            path = {"worst_observed_path_gross": None, "path_complete": None}
        gross = result.price / entry - 1 if result.price is not None else None
        rank_source, rank = observations[d1]["rank_source"], observations[d1]["ranks"].get(code)
        rank_known = rank_source == "V4_OFFICIAL_TOP200" or (rank_source in
                     {"RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK", source.RAW_DIAGNOSTIC}
                      and quotes.get(d1, {}).get("eligible_for_daily_gain_rank") is True)
        out = {"d1_date": d1, "d1_top200_rank_source": rank_source, "d1_top200_rank": rank,
               "d1_top200_hit": rank is not None if rank_known else None,
               "opening_fillable_proxy": fillable, "opening_status": opened["opening_status"],
               "entry_basis_price": entry, "exit_date": result.exit_date, "exit_status": result.status,
               "exit_reason": result.reason, "exit_time": result.time, "dynamic_gross": gross,
               "dynamic_net": gross - r34.FEE if gross is not None else None,
               "qfq_d_anchor_alignment": ("REBASED_PANEL_INTERNAL_MATCH" if aligned else d_status),
               "outcome_rule_source": source.PROXY, **path}
    return out | {"d1_quote_evidence": observations[d1]["quote_evidence"],
                   "path_quote_evidence": "|".join(f"{d}:{label}" for d, label in authority.items())}


def frozen_rosters(selection_ref):
    seal = a31.read_ref(selection_ref)
    require(seal["phase"] == "SELECTION_SEALED" and seal["observations_opened_before_seal"] is False,
            "OUTCOME_REQUIRES_FROZEN_SELECTION")
    selections, audits = {}, {}
    run_sha = seal["run_started"]["sha256"]
    for day in seal["days"]:
        record = a31.read_ref(seal["checkpoints"][day])
        require(record["trade_date"] == day and record["run_sha"] == run_sha, f"OUTCOME_D_CHECKPOINT_DRIFT:{day}")
        selections[day] = record["selections"]
        audits[day] = record["audit"]
    return seal, selections, audits


def seal_outcome_scope(sources, observation_ref):
    return a31.json_atomic(OUT / OUTCOMES, {"schema": SCHEMA, "phase": "OUTCOME_REPLAY_STARTED",
                          "selection_seal": observation_ref, "signal_dates": [*sources.oot, *sources.dev],
                          "latest_date_excluded": source.LATEST, "cutoff": source.CUTOFF,
                          "forward_replay_count": 1, **a31.FLAGS})


def read_evaluated(path, day, outcome_ref):
    ref = a31.ref(path)
    obj = a31.read_ref(ref)
    require(obj["schema"] == SCHEMA and obj["outcome_ref"] == outcome_ref and obj["trade_date"] == day,
            f"OUTCOME_CHECKPOINT_DRIFT:{day}")
    require(all(r["trade_date"] == day for r in obj["rows"]), f"OUTCOME_CHECKPOINT_DATE_DRIFT:{day}")
    return obj["rows"], ref


def out_strategy(row):
    return tuple(row[k] for k in OUTCOME_KEYS)


def outcome_phase(sources, latest, selection_ref):
    seal, selections, signal_audits = frozen_rosters(selection_ref)
    frozen = [*sources.oot, *sources.dev]
    outcome_ref = seal_outcome_scope(sources, selection_ref)
    observed_dir = OUT / "outcomes"
    observed_dir.mkdir(exist_ok=True)
    completed = {day: read_evaluated(observed_dir / f"{day}.json", day, outcome_ref)
                 for day in frozen if (observed_dir / f"{day}.json").exists()}
    outstanding = [day for day in frozen if day not in completed]
    previous, previous_refs = a35.read_original_outcomes(a35.ROOT, sources.previous,
                      a35.original_rosters(sources.previous), selection_ref)
    cutoff_reads, quote_ident = {}, {}
    if outstanding:
        codes = {r["ts_code"] for day in outstanding for rows in selections[day].values() for r in rows}
        observations, observed, bars, days, cutoff_reads = evaluation_inputs(sources, latest, codes)
        quote_ident = {day: {k: v for k, v in p.items() if k not in {"quotes", "ranks"}}
                       for day, p in observations.items()}
        a31.json_atomic(OUT / "OUTCOME_INPUT_EVIDENCE.json", {
            "scope": {k: v for k, v in cutoff_reads.items() if k != "projected_memory_bytes"},
            "quote_and_rank_sources": quote_ident, "selection_seal": selection_ref, "cutoff": source.CUTOFF,
        })
        for day in outstanding:
            checks, details = {}, []
            for lane in LANES:
                for row in selections[day][lane]:
                    key = out_strategy(row)
                    if key in previous:
                        outcome = previous[key] | {"outcome_rule_source": "ACT034A_SAVED_ORIGINAL",
                                   "d1_quote_evidence": source.OFFICIAL, "path_quote_evidence": "ACT034A_SAVED_ORIGINAL"}
                    else:
                        outcome = checks.get(key)
                        if outcome is None:
                            adjustment = r34.affine_events(latest.symbols.get(row["ts_code"]), day, source.CUTOFF)
                            outcome = evaluate_with_tiers(row, observations, observed, bars.get(row["ts_code"], {}),
                                                          adjustment, days)
                            checks[key] = outcome
                    details.append(row | outcome)
            path = observed_dir / f"{day}.json"
            ref = a31.json_atomic(path, {"schema": SCHEMA, "trade_date": day, "outcome_ref": outcome_ref, "rows": details})
            completed[day] = details, ref
    elif (OUT / "OUTCOME_INPUT_EVIDENCE.json").exists():
        receipt = a31.read_ref(a31.ref(OUT / "OUTCOME_INPUT_EVIDENCE.json"))
        require(receipt["selection_seal"] == selection_ref, "OUTCOME_EVIDENCE_PARENT_DRIFT")
        cutoff_reads, quote_ident = receipt["scope"], receipt["quote_and_rank_sources"]
    outcome_rows = [row for day in frozen for row in completed[day][0]]
    refs = {day: completed[day][1] for day in frozen}
    exposure = {(r["trade_date"], r["ts_code"]): r["sources"] for r in seal["known_previously_exposed_keys"]}
    split = {d: "OOT_EARLY" for d in sources.oot} | {d: "DEV_21D" for d in sources.dev}
    all_rows = []
    for row in outcome_rows:
        key = row["trade_date"], row["ts_code"]
        tags = exposure.get(key, [])
        all_rows.append(row | {"window": split[key[0]], "known_previously_exposed": bool(tags),
                               "known_previously_exposed_sources": "|".join(tags)})
    for lane in LANES:
        for row in selections[source.LATEST][lane]:
            all_rows.append(row | {"window": "LATEST_1123", "exit_status": "NOT_RUN_LATEST_NOWCAST"})
    return all_rows, signal_audits, {"evaluation_inputs": cutoff_reads, "quote_sources": quote_ident,
                    "outcomes_started": outcome_ref, "day_outcome_receipts": refs, "prior_act034a": previous_refs}


def rates(rows, dates):
    out = a35.metrics(rows, len(dates))
    official = [r for r in rows if r["d1_top200_rank_source"] in OFFICIAL_RANKS]
    diagnostic = [r for r in rows if r["d1_top200_rank_source"] == source.RAW_DIAGNOSTIC]
    exact_outcome = [r for r in rows if r["outcome_rule_source"] != source.PROXY]
    proxy_outcome = [r for r in rows if r["outcome_rule_source"] == source.PROXY]
    ranked = ("rank_known_n", "rank_unknown_n", "rank_hits", "rank_hit_rate", "buyable_rank_known_n",
              "buyable_rank_unknown_n", "buyable_hits", "buyable_hit_rate")
    modeled = ("selected_n", "dynamic_executed_n", "dynamic_unresolved_n", "net_mean", "net_win_rate",
               "net_below_minus_10_n", "net_min")
    for name, group, fields in (("official_rank", official, ranked), ("panel_diagnostic_rank", diagnostic, ranked),
                                ("official_outcomes", exact_outcome, modeled), ("diagnostic_outcomes", proxy_outcome, modeled)):
        tab = a35.metrics(group, len(dates))
        out[name] = {k: tab[k] for k in fields}
    return out


def performance(rows, source_days, *, exclude_exposed=False):
    dates = set(source_days)
    audited = [r for r in rows if r["trade_date"] in dates]
    scoped = [r for r in audited if not (exclude_exposed and r["known_previously_exposed"])]
    grouped = {lane: [r for r in scoped if r["lane"] == lane] for lane in LANES}
    results = {lane: rates(current, source_days) for lane, current in grouped.items()}
    comparisons = {}
    for lane, baseline in ((A1_V2, A1_BASE), (STRICT, B2_BASE), (WIDE, B2_BASE)):
        arm, prior = grouped[lane], grouped[baseline]
        m, b = results[lane], results[baseline]
        stats = a35.bootstrap(tuple([(r["trade_date"], r) for r in group] for group in (arm, prior)), source_days)
        official = tuple([(r["trade_date"], r) for r in group if r["d1_top200_rank_source"] in OFFICIAL_RANKS]
                         for group in (arm, prior))
        stats["official_buyable_rank_hit_rate"] = a35.bootstrap(official, source_days)["buyable_rank_hit_rate"]
        target, reference = m["official_rank"]["buyable_hit_rate"], b["official_rank"]["buyable_hit_rate"]
        comparisons[lane] = {"baseline": baseline, "net_mean_delta_all_available_sources":
                           m["net_mean"] - b["net_mean"] if None not in (m["net_mean"], b["net_mean"]) else None,
                           "official_buyable_hit_rate_delta": target - reference if None not in (target, reference) else None,
                           "bootstrap": stats}
    return {"lanes": results, "comparisons": comparisons, "dates": source_days,
            "prior_exact_exposure_excluded": exclude_exposed, "rows_removed_no_refill": len(audited) - len(scoped),
            "selected_by_day": {d: {lane: sum(r["trade_date"] == d for r in group)
                                    for lane, group in grouped.items()} for d in source_days}}


def verify_dev_baselines(all_results):
    meta = all_results["DEV_21D"]["lanes"]
    a, b = meta[A1_BASE], meta[B2_BASE]
    require(a["selected_n"] == 52 and a["dynamic_executed_n"] == 42 and round(a["net_mean"] * 100, 2) == .53
            and a["net_below_minus_10_n"] == 0
            and b["selected_n"] == 34 and b["dynamic_executed_n"] == 30 and b["rank_hits"] == 2
            and round(b["net_mean"] * 100, 2) == -.06
            and b["ranks_by_source"]["V4_OFFICIAL_TOP200"]["rank_known_n"] == 28
            and b["ranks_by_source"]["RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"]["rank_known_n"] == 6,
            "DEV_BASELINE_ORACLE_FAILED")


def bind_start(sources, early, latest, capital_ref, workers):
    code = [Path(__file__).resolve(), Path(source.__file__).resolve(), Path(a31.__file__).resolve(),
            Path(f35.__file__).resolve(), Path(a34.__file__).resolve(), Path(r34.__file__).resolve()]
    return a31.json_atomic(OUT / START, {"schema": SCHEMA, "phase": "D_SIGNAL_PHASE_STARTED",
        "code": [a31.ref(p) for p in code],
        "sources": {"act034a": sources.previous.references["act034a"], "act035a_D_projection": ACT035_DEV,
                    "act032_exposure": ACT032, "model_plan": sources.model_receipt,
                    "model": sources.model_expected, "early_reader": early.identity, "latest_reader": latest.identity,
                    "capital": capital_ref},
        "policy": POLICY, "oot": sources.oot, "dev": sources.dev, "latest": source.LATEST, "workers": workers,
        "fit_calls": FIT_ZERO, **a31.FLAGS})


def run(workers):
    start = perf_counter()
    sources = source.load_sources()
    by_day, exposed = projected_prior_inputs(sources)
    originals = by_day_originals(sources)
    early = source.bind_reader(sources, f35.ASOF)
    latest = source.bind_reader(sources, source.LATEST)
    capital, capital_ref = source.capital_projection(early, sources.dev[-1])
    identity = bind_start(sources, early, latest, capital_ref, workers)
    input_done = perf_counter()
    path = OUT / SIGNAL_SEAL
    if path.exists():
        ref = a31.ref(path)
        require(a31.read_ref(ref)["run_started"] == identity, "RESUME_SELECTION_ROOT_DRIFT")
    else:
        ref = run_signals(sources, early, latest, by_day, originals, exposed, capital, identity, OUT / "signals", workers)
    print(json.dumps({"phase": "SELECTION_SEALED", "reference": ref}), flush=True)
    seal_time = perf_counter()
    rows, audits, outcome = outcome_phase(sources, latest, ref)
    windows = {"OOT_EARLY": sources.oot, "DEV_21D": sources.dev, "ALL_53D": [*sources.oot, *sources.dev]}
    results = {name: performance(rows, days) for name, days in windows.items()}
    verify_dev_baselines(results)
    sensitivity = {name: performance(rows, windows[name], exclude_exposed=True) for name in ("OOT_EARLY", "ALL_53D")}
    outcome_done = perf_counter()
    latest_rows = [r for r in rows if r["window"] == "LATEST_1123"]
    require(all("dynamic_net" not in row and "d1_date" not in row for row in latest_rows), "LATEST_FORWARD_FORBIDDEN")
    require(len(rows) == len({(r["trade_date"], r["ts_code"], r["lane"]) for r in rows}), "DELIVERABLE_DUPLICATE_KEYS")
    csv = a35.write_csv_atomic(OUT / CSV_NAME, rows)
    result = {"schema": SCHEMA, "phase": "FORWARD_REPLAY_COMPLETE", "status": "RESEARCH_ONLY",
        "cutoff": source.CUTOFF, "selection_seal": ref, "detail_csv": csv, "outcomes": outcome,
        "windows": results, "known_exposure_sensitivity": sensitivity, "signal_audits": audits,
        "latest": {"date": source.LATEST, "by_lane": dict(Counter(r["lane"] for r in latest_rows)),
                   "scope": len(latest_rows), "outcomes": "NOT_RUN"},
        "counterfactual_fee": r34.FEE, "fit_calls": FIT_ZERO, "forward_replay_count": 1,
        "model_inference_signal_days": [*sources.oot, sources.dev[0], source.LATEST],
        "boot": {"method": "paired moving 5-session blocks", "draws": a35.N_BOOTSTRAP, "seed": a35.SEED},
        "runtime": {"wall_seconds_before_summary": perf_counter() - start, "scope_and_identity_seconds": input_done - start,
                    "signals_seconds": seal_time - input_done, "outcomes_and_metrics_seconds": outcome_done - seal_time,
                    "csv_seconds": perf_counter() - outcome_done, "hardware_cpu_cores": os.cpu_count(), "workers": workers,
                    "worker_arrow_cpu_threads": 1, "worker_arrow_io_threads": 2, "worker_Blas_threads": 1,
                    "parent_arrow_threads": arrow.cpu_count(),
                    "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "worker_largest_peak_rss_bytes": max((a.get("worker_peak_rss_bytes", 0) for a in audits.values()), default=0),
                    "aggregate_peak_family_rss_bytes": "CANNOT_CONFIRM_REQUIRES_CONCURRENT_PS_SAMPLING",
                    "read_write_physical_bytes": "CANNOT_CONFIRM", "detail_csv_bytes": csv["bytes"], "upload_bytes": 0},
        "historical_pit": "CANNOT_CONFIRM", **a31.FLAGS}
    return a31.json_atomic(OUT / SUMMARY, result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", required=True, action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    require(1 <= args.workers <= 12, "WORKERS_OUTSIDE_BOUNDED_RUN_RESOURCE")
    arrow.set_cpu_count(min(8, os.cpu_count() or 1))
    with a31.exclusive_run(OUT):
        require(not (OUT / SUMMARY).exists(), "ONE_FORWARD_REPLAY_ALREADY_COMPLETE")
        result = run(args.workers)
    print(json.dumps({"phase": "FORWARD_REPLAY_COMPLETE", "reference": result}), flush=True)


if __name__ == "__main__":
    main()
