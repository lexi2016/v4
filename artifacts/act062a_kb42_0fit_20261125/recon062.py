"""Reproduce the frozen 120-session seats and reconcile KB42 coverage at exact keys."""
from __future__ import annotations

from hashlib import sha256

import numpy as np
import pandas as pd

from common062 import ACT024, ACT034, ACT037, ACT046, module, csv_payload

KEYS = ["D", "ts_code"]
PORT_ANCHOR = "BLEND_E4B_E4C"
PORT_DUAL = "DUAL_5_5_E4B_E4C"
ARM_CORE = "CORE_BLEND"
ARM_FULL = "FULL_E3HUBER"
BOUND = (20260521, 20261113)
LANES = {
    "full_l50m":"full_l50m", "core_eligible":"core_eligible", "anchor_top50":"anchor_top50",
    "anchor_top10":"anchor_top10", "dual_core5":"dual_core5", "dual_full5":"dual_full5",
    "dual_top10":"dual_top10",
}
PUBLISHED = ["excess_t2_d1open", "excess_t3_d1open", "excess_t5_l50m_observed"]
RAW = ["t2_d1open_pct", "t3_d1open_pct", "t5_d1open_pct"]
MISS = ("NOT_IN_L50M", "IN_L50M_NOT_CORE", "IN_CORE_LOW_RANK", "ONLY_IN_FULL_TOP5", "CORE_CAPTURED")


def load_scores(usage):
    e3 = usage.json(ACT034 / "ACT034_RUN_AND_CLEANUP_RECEIPT.json")
    manifest_path = ACT024 / "DATA_1Y_MANIFEST.json"
    manifest = usage.json(manifest_path)
    assert usage.sources[str(manifest_path)]["sha256"] == e3["source_provenance"]["ACT024_bridge_manifest"]["sha256"]
    e4 = usage.json(ACT037 / "ACT037_F01_RECEIPT.json")
    part_refs = [x for x in e3["completed_prior_uploads"] if x["file"].startswith("ACT034_OOS_F")]
    assert {x["file"] for x in part_refs} == {"ACT034_OOS_F01-F06.parquet","ACT034_OOS_F07-F12.parquet"}
    full = pd.concat([usage.parquet(ACT034 / x["file"], KEYS + ["fold","score_e3huber","core_mask"], x)
                      for x in part_refs], ignore_index=True).sort_values(KEYS,ignore_index=True)
    core_path = ACT037 / "ACT037_E4_OOS_CORE_120D.parquet"
    core = usage.parquet(core_path,KEYS + ["fold","score_e4b","score_e4c","core_mask"],
                         e4["delivery_files"][core_path.name]).sort_values(KEYS,ignore_index=True)
    assert len(full) == 473307 and len(core) == 40578
    assert not full.duplicated(KEYS).any() and not core.duplicated(KEYS).any()
    assert core.core_mask.eq(True).all()
    id_cols = KEYS + ["fold"]
    pd.testing.assert_frame_equal(full.loc[full.core_mask,id_cols].reset_index(drop=True),
                                  core[id_cols],check_exact=True,check_dtype=False)
    dates = sorted(int(x) for x in full.D.unique())
    assert len(dates) == 120 and (dates[0],dates[-1]) == BOUND
    assert full.groupby("fold").D.nunique().to_dict() == {i:10 for i in range(1,13)}
    assert sorted(core.D.unique()) == dates
    return full,core,dates,manifest


def freeze_selections(full,core,usage):
    receipt046 = usage.json(ACT046 / "delivery/ACT046_0FIT_RUN_AND_CLEANUP_RECEIPT.json")
    path = ACT046 / "delivery/ACT046_FLAGSHIP_1200_SEATS_PIT_EXPOSURE_AUDIT.csv"
    fields = ["portfolio","D","fold","arm","ts_code","seat_id"]
    evidence = usage.csv(path, fields + ["record_type","seat_membership_status",*RAW,*PUBLISHED],
                         dtype={k:str for k in RAW+PUBLISHED})
    assert usage.sources[str(path)]["sha256"] == receipt046["local_validation"]["files"][path.name]["sha256"]
    old = evidence.loc[evidence.record_type.eq("SEAT")].copy()
    assert len(old) == 2400
    frozen_code = ACT046 / "freeze_seats.py"
    usage.pin(frozen_code)
    operation = module("act062_existing_act046",frozen_code)

    # The published rule consumes already frozen outputs. Its intermediate rank order is
    # ephemeral. The subsequent CSV carries only exact keys and ordinal rank/membership.
    source_order = core.groupby("D")[["score_e4b","score_e4c"]]
    historical_order = source_order.rank(method="average",pct=True).mean(axis=1)
    ordered_core = core[KEYS + ["fold"]].assign(_order=historical_order).sort_values(
        ["D","_order","ts_code"],ascending=[True,False,True],kind="stable")
    ordered_core["frozen_anchor_ordinal"] = ordered_core.groupby("D").cumcount()+1
    exact_order = source_order.rank(method="average").mean(axis=1)
    cutoff_ties = {
        threshold: int(sum(np.sort(group)[-threshold]==np.sort(group)[-threshold-1]
                           for _,group in exact_order.groupby(core.D)))
        for threshold in (5,10,50)
    }
    ranked_full = operation.top(full,"score_e3huber",5)[KEYS + ["fold"]].copy()
    ranked_full["full_leg_ordinal"] = ranked_full.groupby("D").cumcount()+1
    assert len(ranked_full) == 600 and ranked_full.merge(core[KEYS],on=KEYS).empty
    top10 = ordered_core.loc[ordered_core.frozen_anchor_ordinal.le(10)]
    top5 = ordered_core.loc[ordered_core.frozen_anchor_ordinal.le(5)]
    legs = pd.concat([
        top10.assign(portfolio=PORT_ANCHOR,arm=ARM_CORE,seat_id=top10.frozen_anchor_ordinal),
        top5.assign(portfolio=PORT_DUAL,arm=ARM_CORE,seat_id=top5.frozen_anchor_ordinal),
        ranked_full.assign(portfolio=PORT_DUAL,arm=ARM_FULL,seat_id=ranked_full.full_leg_ordinal+5),
    ], ignore_index=True)[fields].sort_values(["portfolio","D","seat_id"],ignore_index=True)
    old = old.sort_values(["portfolio","D","seat_id"],ignore_index=True)
    pd.testing.assert_frame_equal(legs.astype(old[fields].dtypes.to_dict()),old[fields],check_exact=True)
    assert legs.groupby(["portfolio","D"]).size().eq(10).all()
    old_seal = receipt046["seat_binding"]["seat_identity"]
    core_sig = old_seal["boundary_ties"]
    assert cutoff_ties[5] == core_sig["CORE_5"] and cutoff_ties[10] == core_sig["CORE_10"]
    seal_fields = ["portfolio","D","fold","arm","ts_code"]
    known_hash = sha256(csv_payload(legs[seal_fields].sort_values(seal_fields,ignore_index=True))).hexdigest()
    assert known_hash == old_seal["seat_key_sha256"]
    return legs,old,ordered_core,operation,receipt046,cutoff_ties


def load_label_index(usage,manifest,dates):
    columns = KEYS + RAW + PUBLISHED[:2] + ["excess_pure_tail_trap"]
    refs = [x for x in manifest["artifacts"]["partitions"]["Y"]
            if x["date_min"]<=dates[-1] and x["date_max"]>=dates[0]]
    labels = pd.concat([usage.parquet(ACT024 / x["file"],columns,x,
                                    filters=[("D",">=",dates[0]),("D","<=",dates[-1])])
                        for x in refs],ignore_index=True)
    labels = labels.loc[labels.D.isin(dates)].sort_values(KEYS,ignore_index=True)
    assert len(labels) == 477974 and not labels.duplicated(KEYS).any()
    assert labels.D.nunique() == 120
    labels[PUBLISHED[2]] = labels[RAW[2]] - labels.groupby("D")[RAW[2]].transform("median")
    return labels


def read(usage):
    full,core,dates,manifest = load_scores(usage)
    # Keep the five published seat keys and leg identities fixed before opening labels.
    seats,old,ordered_core,operation,receipt,ties = freeze_selections(full,core,usage)
    labels = load_label_index(usage,manifest,dates)
    index_join = full[KEYS].merge(labels[KEYS],on=KEYS,how="left",indicator=True,validate="one_to_one")
    assert len(index_join) == len(full) and index_join._merge.eq("both").all()
    measured = seats.merge(labels,on=KEYS,validate="many_to_one",sort=False)
    checked = measured[RAW + PUBLISHED].reset_index(drop=True)
    expected = old[RAW + PUBLISHED].reset_index(drop=True)
    assert not checked.isna().any().any()
    diffs = {k:float(np.max(np.abs(checked[k]-expected[k].astype(float)))) for k in checked}
    # The frozen audit CSV publishes 12 significant digits. The separate machine receipt is
    # checked against the unrounded aggregate in baseline_rows.
    assert max(diffs.values()) <= 5.01e-11
    for col in checked:
        assert [format(x, ".12g") for x in checked[col]] == expected[col].tolist(), col
    return dict(full=full,core=core,dates=dates,measured=measured,
                ordered_core=ordered_core,operation=operation,receipt=receipt,label_keys=len(labels),
                ties=ties,max_seat_label_diff=diffs,manifest_snapshot=manifest["snapshot"],
                tie_seats=int(old.seat_membership_status.eq("ORIGINAL_TIE_IDENTITY_CANNOT_CONFIRM").sum()),
                seat_ambiguity=old[["portfolio",*KEYS,"seat_membership_status"]])


def baseline_rows(binding):
    frozen = binding["receipt"]["seat_binding"]["matched"]
    op = binding["operation"]
    rows = []
    comparisons = {}
    for port, group in binding["measured"].groupby("portfolio",sort=True):
        values = op.measures(group)
        expected = frozen[port]["measures"]
        assert values.keys() == expected.keys()
        differences = {k:abs(values[k]-expected[k]) for k in expected}
        assert max(differences.values()) == 0, differences
        # Exact reproducibility at each published precision and exact time/seat identities.
        rounds = {k:round(values[k],2 if k.endswith("_pct") else 4) for k in values}
        assert rounds == {k:round(expected[k],2 if k.endswith("_pct") else 4) for k in expected}
        comparisons[port] = {"values":values, "published":rounds,
                             "max_abs_diff_vs_machine_receipt":max(differences.values()),
                             "day_seat_keys_exact":1200}
        rows.append({"row_type":"BASELINE","portfolio":port,"oos_days":120,"seats_n":1200,
                     **{f"baseline_{k}":v for k,v in values.items()}})
    identification = binding["receipt"]["seat_binding"]["seat_identity"]
    return rows, dict(coverage={"FULL_keys":473307,"CORE_keys":40578,"dates":120,
                                "date_min":BOUND[0],"date_max":BOUND[1],"ACT024_Y_keys_used_for_T5_center":binding["label_keys"]},
                      baseline=comparisons, exact_seat_key_sha256=identification["seat_key_sha256"],
                      cutoff_exact_ordinal_tie_days=binding["ties"],
                      original_tie_identity_cannot_confirm_seats=binding["tie_seats"],
                      seat_label_csv_max_abs_diff=binding["max_seat_label_diff"],
                      top50_identity_status="FROZEN_RANK_RULE_RECONSTRUCTION_NO_INDEPENDENT_OLD_TOP50_FILE",
                      act024_manifest_snapshot=binding["manifest_snapshot"])


def keyset(data):
    return set(data[KEYS].itertuples(index=False,name=None))


def memberships(binding,codes):
    full,core,order,measured = (binding[k] for k in ("full","core","ordered_core","measured"))
    f = full.loc[full.ts_code.isin(codes)]
    c = core.loc[core.ts_code.isin(codes)]
    ranks = order.loc[order.ts_code.isin(codes)]
    seats = measured.loc[measured.ts_code.isin(codes)].copy()
    anchor = seats.loc[seats.portfolio.eq(PORT_ANCHOR)]
    dual = seats.loc[seats.portfolio.eq(PORT_DUAL)]
    keys = {
        "full_l50m":keyset(f), "core_eligible":keyset(c),
        "anchor_top50":keyset(ranks.loc[ranks.frozen_anchor_ordinal.le(50)]),
        "anchor_top10":keyset(anchor), "dual_core5":keyset(dual.loc[dual.arm.eq(ARM_CORE)]),
        "dual_full5":keyset(dual.loc[dual.arm.eq(ARM_FULL)]), "dual_top10":keyset(dual),
    }
    assert keys["anchor_top10"] <= keys["anchor_top50"] <= keys["core_eligible"] <= keys["full_l50m"]
    assert not keys["dual_core5"] & keys["dual_full5"]
    assert keys["dual_top10"] == keys["dual_core5"] | keys["dual_full5"]
    return keys,seats,{
        (x.D,x.ts_code):int(x.frozen_anchor_ordinal) for x in ranks.itertuples(index=False)
    }


def miss_type(has):
    if has["dual_core5"]:
        return "CORE_CAPTURED"
    if has["dual_full5"]:
        return "ONLY_IN_FULL_TOP5"
    if has["core_eligible"]:
        return "IN_CORE_LOW_RANK"
    if has["full_l50m"]:
        return "IN_L50M_NOT_CORE"
    return "NOT_IN_L50M"


def event_records(waves,dates,keys,calendar,ranks):
    oos = waves.loc[waves.D.isin(dates)]
    ordinal = {int(day):i for i,day in enumerate(calendar)}
    valid = set(dates)
    events = []
    for event in oos.itertuples(index=False):
        at = ordinal[event.D]
        assert at == event.D_ordinal
        window = [int(day) for day in calendar[at-5:at+1] if int(day) in valid]
        assert window[-1] == event.D and 1 <= len(window) <= 6
        row = {"row_type":"EVENT","ts_code":event.security_id,"stock_name":event.name,
               "archetype":event.archetype,"D":event.D,"event_id":event.event_id,
               "event_group":event.event_group,"oos_window_observed_days":len(window),
               "oos_window_not_observed_days":6-len(window),"cohort":event.cohort,
               "exit_path_class":event.exit_path_class, "warning_relation_to_peak":event.warning_relation_to_peak,
               "warning_first_offset":event.warning_first_offset,"peak_day":event.peak_day,
               "event_D20_return_pct":event.close_ret_D20_pct}
        for lane,members in keys.items():
            observations = [d for d in window if (d,event.security_id) in members]
            row[f"d0_{lane}"] = event.D in observations
            row[f"window_{lane}"] = bool(observations)
            row[f"window_{lane}_days"] = len(observations)
            row[f"window_{lane}_matched_dates"] = "|".join(map(str,observations))
        row["d0_capture_class"] = miss_type({k:row[f"d0_{k}"] for k in keys})
        row["window_capture_class"] = miss_type({k:row[f"window_{k}"] for k in keys})
        row["d0_anchor_rank"] = ranks.get((event.D,event.security_id))
        recent_ranks = [ranks[d,event.security_id] for d in window if (d,event.security_id) in ranks]
        row["window_best_anchor_rank"] = min(recent_ranks) if recent_ranks else None
        events.append(row)
    return pd.DataFrame(events)


def add_returns(row,seats,prefix):
    row[f"{prefix}_seats_n"] = len(seats)
    for i,h in enumerate((2,3,5)):
        for label,col in (("raw",RAW[i]),("excess",PUBLISHED[i])):
            values = seats[col].dropna()
            row[f"{prefix}_t{h}_{label}_valid_n"] = len(values)
            row[f"{prefix}_t{h}_{label}_mean_pct"] = values.mean()
            row[f"{prefix}_t{h}_{label}_positive_rate"] = values.gt(0).mean() if len(values) else None


def summaries(stocks,members,seats,events):
    result = []
    settings = [(dict(row_type="STOCK",ts_code=code,stock_name=s["name"],archetype=s.archetype),{code})
                for code,s in stocks.iterrows()]
    settings += [(dict(row_type="ARCHETYPE",archetype=group),set(stocks.index[stocks.archetype.eq(group)]))
                 for group in "ABCD"]
    settings += [(dict(row_type="ALL_KB42"),set(stocks.index))]
    for base,codes in settings:
        local = seats.loc[seats.ts_code.isin(codes)]
        wave = events.loc[events.ts_code.isin(codes)]
        row = base | {"oos_days":120,"stock_n":len(codes),"eligible_stock_days_denominator":120*len(codes),
                      "event_n":len(wave),"event_hidden_n":int(wave.event_group.eq("hidden").sum()),
                      "event_visible_n":int(wave.event_group.eq("visible").sum())}
        for lane,key in members.items():
            stock_days = sum(code in codes for _,code in key)
            row[f"{lane}_stock_days"] = stock_days
            row[f"{lane}_stock_day_rate"] = stock_days / (120*len(codes))
            for scope in ("d0","window"):
                found = int(wave[f"{scope}_{lane}"].sum())
                row[f"{scope}_{lane}_event_n"] = found
                row[f"{scope}_{lane}_event_rate"] = found / len(wave) if len(wave) else None
        for scope in ("d0","window"):
            for reason in MISS:
                row[f"{scope}_capture_{reason.lower()}_n"] = int(wave[f"{scope}_capture_class"].eq(reason).sum())
        for name, mask in (
            ("anchor_top10",local.portfolio.eq(PORT_ANCHOR)),
            ("dual_top10",local.portfolio.eq(PORT_DUAL)),
            ("dual_core5",local.portfolio.eq(PORT_DUAL)&local.arm.eq(ARM_CORE)),
            ("dual_full5",local.portfolio.eq(PORT_DUAL)&local.arm.eq(ARM_FULL)),
        ):
            add_returns(row,local.loc[mask],name)
        result.append(row)
    return result


def seat_details(seats,waves,calendar,stocks,ambiguity):
    by_code = {code:group.sort_values("D_ordinal") for code,group in waves.groupby("security_id")}
    ordin = {int(day):i for i,day in enumerate(calendar)}
    seats = seats.merge(ambiguity,on=["portfolio",*KEYS],validate="one_to_one")
    details = []
    for seat in seats.itertuples(index=False):
        row = {k:getattr(seat,k) for k in ["portfolio","arm","seat_id","D","ts_code","fold","seat_membership_status",*RAW,*PUBLISHED]}
        ref = stocks.loc[seat.ts_code]
        row.update(row_type="SEAT",archetype=ref.archetype,stock_name=ref["name"],
                   high_divergence_act061a=bool(ref.high_divergence))
        events = by_code.get(seat.ts_code)
        if events is not None:
            advance = events.loc[events.D_ordinal.between(ordin[seat.D],ordin[seat.D]+5)]
        else:
            advance = None
        if advance is None or not len(advance):
            row.update(exit_event_join_status="NO_ACT061A_EVENT_AT_SEAT_OR_NEXT_5_SESSIONS",
                       exit_event_candidate_n=0)
        else:
            event = advance.iloc[0]
            lead = int(event.D_ordinal)-ordin[seat.D]
            row.update(exit_event_join_status="EXACT_D0" if not lead else "EARLIEST_ACT061A_EVENT_NEXT_5_SESSIONS",
                       exit_event_candidate_n=len(advance),exit_event_id=event.event_id,
                       exit_event_lead_sessions=lead,cohort=event.cohort,
                       exit_path_class=event.exit_path_class,
                       warning_relation_to_peak=event.warning_relation_to_peak,
                       warning_first_offset=event.warning_first_offset,
                       event_D20_return_pct=event.close_ret_D20_pct)
        details.append(row)
    if not details:
        return pd.DataFrame(columns=["row_type","portfolio","arm","exit_event_join_status","cohort","high_divergence_act061a",*RAW,*PUBLISHED])
    detail = pd.DataFrame(details)
    if "cohort" not in detail:
        detail["cohort"] = None
    return detail


def build(binding,inputs,cal):
    baseline,evidence = baseline_rows(binding)
    stocks = inputs["stocks"]
    keys,seats,ranks = memberships(binding,set(stocks.index))
    events = event_records(inputs["waves"],binding["dates"],keys,cal,ranks)
    assert len(events) == int(inputs["waves"].D.between(*BOUND).sum())
    assert not events.event_id.duplicated().any()
    summary = summaries(stocks,keys,seats,events)
    details = seat_details(seats,inputs["waves"],cal,stocks,binding["seat_ambiguity"])
    buckets = []
    for groups, group in details.groupby(["portfolio","arm","exit_event_join_status","cohort",
                                          "high_divergence_act061a"],dropna=False,sort=True):
        row = dict(zip(("portfolio","arm","exit_event_join_status","cohort","high_divergence_act061a"),groups,strict=True))
        row["row_type"] = "SEAT_EXIT_SUMMARY"
        add_returns(row,group,"matched_bucket")
        buckets.append(row)
    combined = pd.concat([pd.DataFrame(baseline + summary),events,details,pd.DataFrame(buckets)],ignore_index=True)
    all_stock = next(x for x in summary if x["row_type"]=="ALL_KB42")
    outcome = evidence | {
        "KB42_FULL_symbol_days":len(keys["full_l50m"]),"KB42_CORE_symbol_days":len(keys["core_eligible"]),
        "KB42_anchor_seats":all_stock["anchor_top10_seats_n"],"KB42_dual_seats":all_stock["dual_top10_seats_n"],
        "KB42_dual_CORE_seats":all_stock["dual_core5_seats_n"],"KB42_dual_FULL_seats":all_stock["dual_full5_seats_n"],
        "event_n":len(events), "event_groups":events.event_group.value_counts().to_dict(),
        "event_archetypes":events.archetype.value_counts().to_dict(),
        "d0_event_captures":{lane:int(events[f"d0_{lane}"].sum()) for lane in keys},
        "window_event_captures":{lane:int(events[f"window_{lane}"].sum()) for lane in keys},
        "d0_mutually_exclusive_capture_class":events.d0_capture_class.value_counts().to_dict(),
        "window_mutually_exclusive_capture_class":events.window_capture_class.value_counts().to_dict(),
        "partial_early_oos_window_events":int(events.oos_window_not_observed_days.gt(0).sum()),
        "seat_exit_join_status":details.exit_event_join_status.value_counts().to_dict(),
        "seat_exit_buckets":buckets,
    }
    assert len(combined.loc[combined.row_type.eq("STOCK")]) == 42
    assert len(combined.loc[combined.row_type.eq("ARCHETYPE")]) == 4
    return combined,outcome
