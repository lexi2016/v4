"""Trace two frozen OOS selection legs without loading a model or scoring a case."""
from __future__ import annotations

from collections import Counter
import operator

import numpy as np
import pandas as pd

from inputs063 import ACT020, ACT030
from common062 import ACT024
from recon062 import freeze_selections, load_scores

KEY = ["D", "ts_code"]
LABELS = ["excess_t2_d1open", "excess_t3_d1open", "excess_pure_tail_trap", "excess_clean_winner"]
THRESHOLDS = {
    "close_vs_white_pp": ("gt", 0), "close_vs_yellow_pp": ("gt", 0),
    "hold_rise_base_low": ("eq", 1), "prior5_highvol_bear_unrecovered": ("eq", 0),
    "drawdown_from_prior20_high_pp": ("ge", -8), "prior_attack_runup_pp": ("ge", 12),
    "prior20_peak_relative_volume": ("ge", 1.8), "prior20_volatility_pp": ("le", 5),
}
OPS = {key: getattr(operator, key) for key in ("gt", "ge", "le", "eq")}
L50_ABSENT = "L50M_GATE"
READY_ABSENT = "L50M_PRESENT_OOS_NOT_READY"
FULL_RANK = "FULL_RANK_MISS_AND_CORE_GATE"
CORE_RANK = "CORE_ELIGIBLE_BOTH_LEGS_RANK_MISS"


def unique(frame):
    return frame.set_index(KEY, verify_integrity=True)


def as_bool(value):
    assert value in (True, False, "True", "False"), value
    return value in (True, "True")


def project(usage, manifest, kind, cols, days, codes):
    refs = [x for x in manifest["artifacts"]["partitions"][kind]
            if x["date_min"] <= max(days) and x["date_max"] >= min(days)]
    frames = [usage.parquet(ACT024 / x["file"], KEY + cols, x,
                            filters=[("D", "in", sorted(days)), ("ts_code", "in", sorted(codes))])
              for x in refs]
    return pd.concat(frames, ignore_index=True)


def daily_ranks(frame, field, immediate, prefix, tie_space=None):
    by = frame.groupby("D", sort=False)
    assert frame[field].notna().all()
    frame[prefix+"_pool_n"] = by[field].transform("size")
    frame[prefix+"_raw_value_percentile"] = by[field].rank(method="average", pct=True)
    frame = frame.sort_values(["D", field, "ts_code"], ascending=[True,False,True], kind="stable").copy()
    by = frame.groupby("D", sort=False)
    frame[prefix+"_ordinal"] = by.cumcount()+1
    measures = []
    for n in immediate:
        winners = frame.loc[frame[prefix+"_ordinal"].le(n)]
        assert winners.groupby("D").size().eq(n).all()
        cutoff = winners.loc[winners[prefix+"_ordinal"].eq(n)].set_index("D")
        p = prefix + f"_top{n}"
        frame[p+"_cutoff_value"] = frame.D.map(cutoff[field])
        frame[p+"_delta_event_minus_cutoff"] = frame[field] - frame[p+"_cutoff_value"]
        by21 = frame.loc[frame[prefix+"_ordinal"].eq(n+1)].set_index("D")
        tie_key = tie_space or field
        frame[p+"_cutline_field_tie"] = frame.D.map(cutoff[field].eq(by21[field]))
        frame[p+"_cutline_exact_rank_tie"] = frame.D.map(cutoff[tie_key].eq(by21[tie_key]))
        frame[p+"_event_tied_with_cutline_exact"] = frame[tie_key].eq(frame.D.map(cutoff[tie_key]))
        measures.extend((p+"_cutoff_value",p+"_delta_event_minus_cutoff",p+"_cutline_field_tie",
                         p+"_cutline_exact_rank_tie",p+"_event_tied_with_cutline_exact"))
        if n == 5:
            median = winners.groupby("D")[field].median()
            pctmedian = winners.groupby("D")[prefix+"_raw_value_percentile"].median()
            frame[p+"_selected_median_value"] = frame.D.map(median)
            frame[p+"_selected_median_percentile"] = frame.D.map(pctmedian)
            frame[p+"_delta_event_minus_selected_median"] = frame[field]-frame[p+"_selected_median_value"]
            frame[p+"_delta_event_pctile_minus_selected_median"] = (
                frame[prefix+"_raw_value_percentile"]-frame[p+"_selected_median_percentile"])
            measures.extend([p+v for v in ("_selected_median_value","_selected_median_percentile",
                                           "_delta_event_minus_selected_median","_delta_event_pctile_minus_selected_median")])
    return frame[KEY+[field,prefix+"_ordinal",prefix+"_pool_n",prefix+"_raw_value_percentile",*measures]]


def load(usage, recon, waves, calendar):
    f, c, dates, manifest = load_scores(usage)
    manifest_id = usage.sources[str(ACT024 / "DATA_1Y_MANIFEST.json")]
    scope = usage.json(ACT030 / "ACT030_SCOPE.json")
    assert scope["action_id"] == "ACT-030" and scope["status"] == "FROZEN"
    assert scope["source"]["manifest_sha256"] == manifest_id["sha256"]
    assert scope["source"]["artifact_files"] == manifest["artifacts"]["partitions"]
    assert {k: tuple(v) for k,v in scope["core_rules"].items()} == THRESHOLDS
    usage.pin(ACT030 / "run_act030.py")
    usage.pin(ACT020 / "reopen/ACT020_proxy_fit.py")
    usage.pin(ACT020 / "delivery/ACT020_prepare.py")
    usage.pin(ACT024.parent / "work/build_act024.py")
    legs, _, ordered, _, frozen, ties = freeze_selections(f, c, usage)
    dayset = frozenset(dates)
    events = waves.loc[waves.D.isin(dates), ["event_id","security_id","D","D_ordinal","name","archetype","event_group"]].copy()
    events = events.rename(columns={"security_id":"ts_code"})
    compare = events.merge(recon, on=["event_id","ts_code","D","archetype","event_group"], validate="one_to_one")
    assert len(events) == len(compare) == len(recon) == 162
    assert all(int(calendar[int(x.D_ordinal)]) == x.D for x in events.itertuples(index=False))
    codes = set(events.ts_code)
    days = {int(calendar[event.D_ordinal+k]) for event in events.itertuples(index=False)
            for k in range(-5,1)} & dayset
    proj_x = project(usage, manifest, "X", list(THRESHOLDS), days, codes)
    assert proj_x[list(THRESHOLDS)].dtypes.astype(str).eq("float32").all()
    proj_y = project(usage, manifest, "Y", LABELS, days, codes)
    proj_key = project(usage, manifest, "KEYMETA", ["warmup_bars_prior_cap120"], days, codes)
    bridge_path = ACT020 / "bridge/ACT020_POOL_LIQUIDITY_D0_ST_PROXY.parquet"
    b = usage.parquet(bridge_path, KEY+["Pool_L50M","ST_proxy_status","st_source_D","adv20_median_yuan","flat_ohlc_D0"],
                     manifest["provenance"]["ACT020_frozen_shared_mask"],
                     filters=[("D","in",sorted(days)),("ts_code","in",sorted(codes))])
    x, y, meta, bridge = map(unique,[proj_x,proj_y,proj_key,b])
    assert x.sort_index().index.equals(y.sort_index().index)
    assert x.sort_index().index.equals(meta.sort_index().index)
    selected = bridge[bridge.Pool_L50M]
    assert x.sort_index().index.equals(selected.sort_index().index)
    admission = x.join(meta, validate="one_to_one").join(y, validate="one_to_one")
    admission["ready"] = admission.warmup_bars_prior_cap120.ge(120)&admission[LABELS].notna().all(axis=1)
    core_ok = pd.Series(True,index=admission.index)
    for name, (op, threshold) in THRESHOLDS.items():
        core_ok &= OPS[op](admission[name].astype("float64"),threshold).fillna(False)
    admission["gate_core_all"] = core_ok
    actual = unique(f[f.D.isin(days)&f.ts_code.isin(codes)])
    assert admission[admission.ready].sort_index().index.equals(actual.sort_index().index)
    assert admission.loc[actual.index,"gate_core_all"].equals(actual.core_mask.rename("gate_core_all"))
    return f, c, dates, legs, ordered, frozen, ties, compare, admission, bridge


def ranked_pools(full, core, order, legs, days):
    core = core.merge(order[KEY+["_order"]], on=KEY, validate="one_to_one")
    core = core.loc[core.D.isin(days),KEY+["score_e4b","score_e4c","_order"]].copy()
    core["frozen_core_exact_rank_sum"] = core.groupby("D")[["score_e4b","score_e4c"]].rank(method="average").sum(axis=1)
    core = core.rename(columns={"_order":"frozen_core_mean_input_rank_pct"})
    rc = daily_ranks(core, "frozen_core_mean_input_rank_pct", (5,10), "core",
                     tie_space="frozen_core_exact_rank_sum")
    full = full.loc[full.D.isin(days),KEY+["score_e3huber"]]
    rf = daily_ranks(full,"score_e3huber",(5,),"full")
    for ordered, portfolio, leg, column, limit in (
        (rf,"DUAL_5_5_E4B_E4C","FULL_E3HUBER","full_ordinal",5),
        (rc,"DUAL_5_5_E4B_E4C","CORE_BLEND","core_ordinal",5),
        (rc,"BLEND_E4B_E4C","CORE_BLEND","core_ordinal",10),
    ):
        ranked = ordered.loc[ordered[column].le(limit),KEY].sort_values(KEY,ignore_index=True)
        selected = legs.loc[legs.D.isin(days)&legs.portfolio.eq(portfolio)&legs.arm.eq(leg),KEY]
        pd.testing.assert_frame_equal(ranked,selected.sort_values(KEY,ignore_index=True),check_dtype=False)
    return unique(rf), unique(rc)


def liquidity_reasons(code, row):
    reasons = ["BJ_EXCLUDED_BY_CONTRACT"] if code.endswith(".BJ") else []
    if row is None:
        return reasons + ["ACT020_WITNESS_MISSING_CANNOT_CONFIRM"]
    amount = row.adv20_median_yuan
    if not np.isfinite(amount):
        reasons.append("ADV20_MISSING")
    elif amount < 50_000_000:
        reasons.append("ADV20_MEDIAN_LT_50M")
    if row.flat_ohlc_D0:
        reasons.append("FLAT_OHLC_D0")
    if str(row.ST_proxy_status).startswith("EXCLUDED"):
        reasons.append(str(row.ST_proxy_status))
    if bool(row.Pool_L50M):
        assert not reasons
    if not bool(row.Pool_L50M) and not reasons:
        reasons.append("POOL_FALSE_EXACT_CAUSE_CANNOT_CONFIRM")
    return reasons


def gate_fields(row):
    failed, missing, values = [], [], {}
    for name, (op, threshold) in THRESHOLDS.items():
        value = float(row[name])
        known = np.isfinite(value)
        passed = known and OPS[op](value,threshold)
        status = ("PASS" if passed else "FAIL") if known else "MISSING_FAILS_FROZEN_AND"
        values[f"core_x_{name}"] = value if known else None
        values[f"core_pred_{name}"] = status
        if not passed and known:
            failed.append(name)
        if not known:
            missing.append(name)
    values["core_failed_predicates"] = "|".join(failed)
    values["core_missing_predicates"] = "|".join(missing)
    assert bool(row.gate_core_all) == (not failed and not missing)
    return values


def by_day(base, offset, dates, admission, bridge, full, core):
    row = base | {"row_type":"EVENT_DAY","relative_offset":offset,"session_D":dates[offset]}
    key = (dates[offset],base["ts_code"])
    if key[0] not in full.attrs["oos_sessions"]:
        return row | {"day_status":"LEFT_TRUNCATED_NOT_IN_FROZEN_120D"}
    in_full, in_core = key in full.index, key in core.index
    if in_full:
        row.update(full.loc[key].to_dict())
    if in_core:
        row.update(core.loc[key].to_dict())
    frozen_raw = bridge.loc[key] if key in bridge.index else None
    pre = admission.loc[key] if key in admission.index else None
    liquidity = liquidity_reasons(key[1],frozen_raw)
    if frozen_raw is not None:
        assert bool(frozen_raw.Pool_L50M) == (pre is not None)
    if pre is not None:
        assert bool(pre.ready) == in_full and bool(pre.gate_core_all and pre.ready) == in_core
        row.update(gate_fields(pre))
        row["core_predicate_scope"] = "FROZEN_L50M_X_FLOAT32_TO_FLOAT64"
    else:
        row["core_predicate_scope"] = "NOT_APPLICABLE_OUTSIDE_L50M_X"
    full_top = in_full and int(row["full_ordinal"]) <= 5
    core_top = in_core and int(row["core_ordinal"]) <= 5
    core_top10 = in_core and int(row["core_ordinal"]) <= 10
    reason = CORE_RANK if in_core else FULL_RANK if in_full else READY_ABSENT if pre is not None else L50_ABSENT
    if full_top or core_top:
        reason = "DUAL_CAPTURED"
    return row | dict(day_status="OBSERVED_IN_FROZEN_120D", attr_main=reason, act024_raw_l50m=pre is not None,
                      raw_gate_reasons="|".join(liquidity),
                      act020_raw_key_status="FOUND" if frozen_raw is not None else "MISSING",
                      st_proxy_status=None if frozen_raw is None else frozen_raw.ST_proxy_status,
                      st_source_D=None if frozen_raw is None else frozen_raw.st_source_D,
                      flat_ohlc_D0=None if frozen_raw is None else bool(frozen_raw.flat_ohlc_D0),
                      adv20_median_yuan=None if frozen_raw is None else frozen_raw.adv20_median_yuan,
                      oos_warmup_prior=None if pre is None else pre.warmup_bars_prior_cap120,
                      oos_ready_missing_labels=None if pre is None else "|".join(k for k in LABELS if pd.isna(pre[k])),
                      full_scored_oos_ready=in_full, core_eligible=in_core, dual_full5=full_top,
                      dual_core5=core_top, anchor_top10=core_top10,
                      anchor_top50=in_core and int(row["core_ordinal"])<=50,
                      core_comparison_value_kind="FROZEN_E4B_E4C_INPUT_RANK_PERCENTILE_MEAN" if in_core else None,
                      core_raw_blend_unavailable="NO_MATERIALIZED_RAW_BLEND_SCORE" if in_core else None)


def event_summary(base, trace, event):
    days = [row for row in trace if "attr_main" in row]
    slot = days[-1]
    full_hits = [row["full_scored_oos_ready"] for row in days]
    core_hits = [row["core_eligible"] for row in days]
    lanes = {
        "full_l50m":"full_scored_oos_ready","core_eligible":"core_eligible",
        "anchor_top50":"anchor_top50","anchor_top10":"anchor_top10","dual_core5":"dual_core5","dual_full5":"dual_full5",
    }
    for source, actual in lanes.items():
        assert as_bool(getattr(event,f"d0_{source}")) == slot[actual], (event.event_id,source)
        assert as_bool(getattr(event,f"window_{source}")) == any(row[actual] for row in days), (event.event_id,source)
    assert len(days) == int(event.oos_window_observed_days)
    assert not any(row["dual_core5"] or row["dual_full5"] for row in days)
    best = CORE_RANK if any(core_hits) else FULL_RANK if any(full_hits) else (
        READY_ABSENT if any(row["act024_raw_l50m"] for row in days) else L50_ABSENT)
    partial = len(days) != 6
    result = base | dict(row_type="EVENT_SUMMARY", day_status="LEFT_TRUNCATED" if partial else "COMPLETE_6",
                         attr_main="LEFT_TRUNCATED_FRONT_WINDOW" if partial else best,
                         observed_window_main=best, d0_main=slot["attr_main"],
                         observed_days=len(days), left_truncated_days=6-len(days),
                         raw_l50m_day_n=sum(q["act024_raw_l50m"] for q in days),
                         full_ready_day_n=sum(full_hits), core_day_n=sum(core_hits), dual_full5=False,
                         dual_core5=False, anchor_top10=any(q["anchor_top10"] for q in days),
                         anchor_top50=any(q["anchor_top50"] for q in days))
    return result


def summarize(rows, ties, frozen):
    summaries = [row for row in rows if row["row_type"]=="EVENT_SUMMARY"]
    all_days = [row for row in rows if row["row_type"]=="EVENT_DAY"]
    days = [row for row in all_days if "attr_main" in row]
    assert len(summaries) == 162 and len(all_days) == 972
    assert Counter(x["day_status"] for x in summaries) == {"COMPLETE_6":157,"LEFT_TRUNCATED":5}
    assert sum(x["left_truncated_days"] for x in summaries) == len(all_days)-len(days)
    assert sum(x["anchor_top10"] for x in summaries) == 1
    d0 = [x for x in days if x["relative_offset"]==0]
    assert len(d0)==162
    facts = dict(coverage=dict(oos_sessions=120,full_keys=473307,core_keys=40578,frozen_seats=2400),
                 frozen_seat_sha256=frozen["seat_binding"]["seat_identity"]["seat_key_sha256"],
                 core_session_cutoff_exact_rank_ties=ties,events=162,complete_events=157,left_truncated_events=5,
                 scheduled_slots=len(all_days),observed_slots=len(days),left_truncated_slots=len(all_days)-len(days),
                 event_primary=dict(Counter(x["attr_main"] for x in summaries)),
                 event_observed_primary=dict(Counter(x["observed_window_main"] for x in summaries)),
                 d0_primary=dict(Counter(x["attr_main"] for x in d0)),
                 day_primary=dict(Counter(x["attr_main"] for x in days)),
                 raw_gate_day_flags=dict(Counter(y for x in days for y in x["raw_gate_reasons"].split("|") if y)),
                 core_failed_predicate_day_flags=dict(Counter(y for x in days if x["attr_main"]==FULL_RANK
                            for y in x["core_failed_predicates"].split("|") if y)),
                 core_missing_predicate_day_flags=dict(Counter(y for x in days if x["attr_main"]==FULL_RANK
                            for y in x["core_missing_predicates"].split("|") if y)),
                 d0_dual=0,observed_window_dual=0,d0_anchor_top10=sum(x["anchor_top10"] for x in d0),
                 observed_window_anchor_top10=sum(x["anchor_top10"] for x in summaries),
                 eight_atomic_core_predicates=THRESHOLDS)
    return facts


def build(bundle, calendar):
    full, core, dates, legs, order, frozen, ties, events, admission, bridge = bundle
    days = {int(calendar[event.D_ordinal+k]) for event in events.itertuples(index=False)
            for k in range(-5,1)} & set(dates)
    full, core = ranked_pools(full,core,order,legs,days)
    full.attrs["oos_sessions"] = set(dates)
    rows = []
    for event in events.sort_values(["D","ts_code"]).itertuples(index=False):
        base = dict(event_id=event.event_id,ts_code=event.ts_code,name=event.name,archetype=event.archetype,
                    event_D=int(event.D),event_group=event.event_group)
        cal = {k:int(calendar[event.D_ordinal+k]) for k in range(-5,1)}
        timeline = [by_day(base,k,cal,admission,bridge,full,core) for k in range(-5,1)]
        rows.append(event_summary(base,timeline,event))
        rows.extend(timeline)
    return pd.DataFrame(rows),summarize(rows,ties,frozen)
