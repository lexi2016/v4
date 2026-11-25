"""One frozen knowledge-base row per stock, with evidence time kept explicit."""
from __future__ import annotations

from collections import Counter
from zipfile import ZipFile

import numpy as np
import pandas as pd

from common062 import ACT050, ACT056, ACT057, ACT058, ACT061, ROOT

FAMILIES = ("S-Pullback", "S-ReAdvance", "S-Rebuild", "E-Reversal")
PATHS = ("NEVER_BOTH_ABOVE", "RECOVER_AND_HOLD", "WARN_THEN_REPAIR", "UNRECOVERED_BY_D20")
RELATIONS = ("BEFORE_PEAK", "AT_PEAK", "AFTER_PEAK", "NO_WARN", "CANNOT_CONFIRM")
LOW_WICK_NAMES = frozenset(("安德利", "幸福蓝海", "宝丰能源", "福莱新材", "新风光", "华纳药厂"))
PRE_COLUMNS = (
    "amplitude_mean_d5_d1_pct", "dd20_max_close_drawdown_pct", "lower_wick_support_fraction_5",
    "close_vs_white_d1_pct", "close_vs_yellow_d1_pct", "white_vs_yellow_d1_pct",
    "close_above_white_fraction_5", "close_above_yellow_fraction_5",
)
RELAPSE = "POSITIVE_PEAK_NEGATIVE_D20"
HOLD = "COMPLEMENT_411"
SOURCE_ARCHETYPES = {0:"B", 1:"C", 2:"A", 3:"D"}


def load(usage, batch):
    final = usage.json(ACT061 / "ACT061A_FINAL_DELIVERY_VERIFIED.json")
    inputs = {}
    for key, name in (
        ("waves", "ACT061A_KB42_562_EXIT_PATHS.csv"),
        ("summary_raw", "ACT061A_KB42_STOCK_EXIT_SUMMARY.csv"),
        ("controls", "ACT061A_KB42_CLEAN_CONTROLS_84.csv"),
        ("pair_zip", "ACT061A_EXIT_PAIRS_SVG_PACK.zip"),
    ):
        path = ACT061 / "delivery" / name
        target = next(row for row in final["files"] if row["name"] == name)
        if key != "pair_zip":
            inputs[key] = usage.csv(path)
            actual = usage.sources[str(path)]
        else:
            inputs[key] = path
            actual = usage.pin(path)
        assert (actual["bytes"], actual["sha256"]) == (target["bytes"], target["sha256"])
    assert final["git_commit"] == "96a5efe0d2ea70aa89b0e66f5662250c95246fdc"
    wave = inputs["waves"]
    assert len(wave) == 583 and not wave.duplicated(["security_id", "D"]).any()
    assert wave.cohort.value_counts().to_dict() == {HOLD: 411, RELAPSE: 151, "INCOMPLETE_20BARS": 21}
    assert wave.full20.eq(wave.cohort.ne("INCOMPLETE_20BARS")).all()
    assert wave.peak_minus_D20_sign.value_counts().to_dict() == {"POSITIVE": 549, "ZERO": 13, "UNAVAILABLE": 21}
    summary = inputs["summary_raw"]
    assert Counter(summary.section) == {"STOCK":42, "TEST":66, "CROSSTAB":32}
    stocks = summary.loc[summary.section.eq("STOCK")].set_index("security_id", verify_integrity=True)
    assert len(stocks) == 42 and Counter(stocks.archetype) == {"A":18, "B":16, "C":7, "D":1}
    assert set(stocks.index) - set(wave.security_id) == {"600016.SH"}
    inputs["stocks"] = stocks
    controls = inputs["controls"]
    assert Counter(controls.role) == {"MAIN_REVERSE_EVENT": 42, "SAME_STOCK_ORDINARY_CONTROL": 42}
    assert controls.security_id.nunique() == 42 and set(controls.security_id) == set(stocks.index)
    assert controls.complete_20bars.eq(True).all() and controls.overlap_days.eq(0).all()
    inputs["df56"] = read_056(usage, batch)
    file057 = ACT057 / "delivery/ACT057_LOCAL_KB42_STOCK_EXIT_PROFILES.csv"
    final057 = usage.json(ACT057 / "ACT057_LOCAL_FINAL_DELIVERY_VERIFIED.json")
    inputs["prof"] = usage.csv(file057).set_index("security_id", verify_integrity=True)
    check_expected(usage, file057, final057)
    file058 = ACT058 / "delivery/ACT058A_KB42_HIDDEN_PRECURSOR_STATS.csv"
    final058 = usage.json(ACT058 / "ACT058A_FINAL_DELIVERY_VERIFIED.json")
    inputs["stats058"] = usage.csv(file058)
    check_expected(usage, file058, final058)
    assert len(inputs["stats058"]) == 1578
    assert set(inputs["prof"].index) == set(stocks.index)
    return inputs


def check_expected(usage, path, receipt):
    entries = receipt.get("files", receipt.get("outputs"))
    if isinstance(entries, dict):
        expected = entries[path.name]
    else:
        expected = next(row for row in entries if row["name"] == path.name)
    actual = usage.sources[str(path)]
    assert (actual["bytes"], actual["sha256"]) == (expected["bytes"], expected["sha256"]), path


def read_056(usage, batch):
    path = batch / "input_ingress/act056b_stock_cards.json"
    src = usage.json(path)
    assert usage.sources[str(path)]["sha256"] == "be077b820778027776e808b4977eb9d721d8792baeb724c37f8ea1587531a7f4"
    values = src["values"]
    assert values[5][:3] == ["Security ID", "Security Name", "Archetype ID"]
    assert len(values[6:47]) == 41
    result = pd.DataFrame(values[6:47], columns=values[5]).set_index("Security ID", verify_integrity=True)
    manual = batch / "input_ingress/ACT061B_KB42_MANUAL_V1_3.md"
    usage.pin(manual, {"bytes": 265994, "sha256": "a89b5d28ea1a73910ed2b6c8de722f2307fdef6f1405838633200c54a13e939d"})
    return result


def read_buy_signals(usage, sources):
    files = [
        (ACT050 / "PFT_V4_ACT050_CODEX_KB47_FULLLIFE_PACK_20261125.zip", "kb47_all_signals_and_breakouts.csv", "zip_path"),
        (ACT056 / "delivery/ACT056A_000547_HTFZ_FULLLIFE_PACK.zip", "000547_all_signals_and_breakouts.csv", "htfz_path"),
    ]
    from io import BytesIO
    parts = []
    for path, member, key in files:
        usage.pin(path, sources[key])
        with ZipFile(path) as package:
            buf = package.read(member)
            usage.direct_read_bytes += package.getinfo(member).compress_size
        usage.projected_decoded_bytes += len(buf)
        parts.append(pd.read_csv(BytesIO(buf), usecols=["security_id", "D", "t5_close", *FAMILIES]))
    frame = pd.concat(parts, ignore_index=True)
    assert not frame.duplicated(["security_id", "D"]).any()
    assert set(frame.security_id) == set(sources["roster"])
    assert not frame[list(FAMILIES)].isna().any().any()
    return frame


def build(inputs, stores, old, all_events, buy):
    waves, controls, summary = (inputs[k] for k in ("waves", "controls", "stocks"))
    pref = inputs["df56"]
    assert set(pref.index) == set(summary.index) - {"000547.SZ"}
    out = []
    for code, profile in inputs["prof"].sort_index().iterrows():
        stock = stores[code]
        ref = summary.loc[code]
        local = waves.loc[waves.security_id.eq(code)]
        recent = local.loc[local.full20]
        events = all_events.loc[all_events.security_id.eq(code)]
        history = buy.loc[buy.security_id.eq(code)]
        pair = controls.loc[controls.security_id.eq(code)].set_index("role", verify_integrity=True)
        main, ordinary = [pair.loc[k] for k in ("MAIN_REVERSE_EVENT", "SAME_STOCK_ORDINARY_CONTROL")]
        assert len(events) == profile.all_event_n and int(events.hidden.sum()) == profile.hidden_n
        assert (ref["name"],ref.archetype) == (profile["name"], profile.archetype)
        if code in pref.index:
            stock_card = pref.loc[code]
            assert stock_card["Security Name"] == ref["name"]
            assert SOURCE_ARCHETYPES[int(stock_card["Archetype ID"])] == ref.archetype
        else:
            stock_card = {}
        reference_r = (pd.to_numeric(recent.warning_first_offset, errors="coerce"))
        repair_at = pd.to_numeric(recent.post_warning_line_repair_offset, errors="coerce")
        true_pairs = (repair_at - reference_r).loc[recent.post_warning_line_repair.eq(True)]
        assert true_pairs.dropna().ge(0).all()
        valid_new = recent.post_warning_new_high.dropna()
        assert (len(local),len(recent)) == (int(ref.event_n),int(ref.complete_n))
        sample_groups = int(ref.relapse_n), int(ref.complement_n)
        enough = min(sample_groups) >= 5
        paired_pre = old.features(stock, np.array([main.D_ordinal, ordinary.D_ordinal], dtype=int))
        # Physical D-1 reads only. Reverse selection and matched-pair roles are historical labels.
        pre = old.features(stock, events.exchange_session_ordinal.to_numpy(dtype=int))
        assert len(pre) == len(events)
        pre_scope = "ACT058A_FORMULAS_ALL_ACT057_REVERSE_EVENT_ANCHORS_HISTORICAL_AGGREGATE"
        row = {
            "ts_code":code, "stock_name":ref["name"], "frozen_archetype":ref.archetype,
            "identity_source":"ACT056B+ACT057+ACT061A",
            "identity_act056b_legacy_archetype_id":stock_card.get("Archetype ID"),
            "identity_all_history_breakouts_n":int(profile.all_event_n),
            "identity_all_history_hidden_n":int(profile.hidden_n),
            "identity_all_history_hidden_rate":float(profile.hidden_rate),
            "identity_recent2y_total_n":int(ref.event_n),
            "identity_recent2y_complete20_n":int(ref.complete_n),
            "identity_recent2y_incomplete20_n":int(ref.incomplete_n),
            "identity_recent2y_coverage":ref.coverage,
            "strict_d0_causal_window_rule": "ACT058A_D_MINUS_25_TO_D_MINUS_1_EACH_ANCHOR; STOCK_SUMMARIES_NOT_POINT_IN_TIME",
            "strict_d0_causal_pre_summary_source":pre_scope,
            "strict_d0_causal_pair_pre_source":"ACT061A_84_CLEAN_CONTROLS+ACT058A_FROZEN_FORMULAS",
            "strict_d0_causal_main_d1_line_state":main.D_minus_1_line_state,
            "strict_d0_causal_control_d1_line_state":ordinary.D_minus_1_line_state,
            "historical_buy_preference_frozen_asof":"2026-11-20",
            "historical_buy_preference_source":"ACT050/ACT056A_FROZEN_SIGNAL_DATES; T5_IS_POST_SIGNAL_HISTORICAL",
            "historical_act056b_best_pattern":stock_card.get("Best Pattern"),
            "historical_act056b_best_pattern_n":stock_card.get("Best N"),
            "historical_act056b_best_t5_source_units":stock_card.get("Best T+5 Return"),
            "historical_act056b_worst_pattern":stock_card.get("Worst Pattern"),
            "historical_act056b_worst_t5_source_units":stock_card.get("Worst T+5 Return"),
            "historical_matched_control_status":ordinary.matching_status,
            "historical_matched_control_tier":ordinary.match_tier,
            "historical_matched_main_scope":main.main_sample_window,
            "post_d_exit_monitor_only_long_upper_wick_peak_ge40_rate":profile.full20__peak_D0_wick_ge_40_rate,
            "post_d_exit_monitor_only_long_upper_wick_peak_ge40_hits":profile.full20__peak_D0_wick_ge_40_n,
            "post_d_exit_monitor_only_long_upper_wick_peak_ge40_denominator":profile.full20__peak_D0_upper_wick_range_ratio_n,
            "post_d_exit_monitor_only_alt_peak_pm1_ge40_rate":profile.full20__peak_3_wick_ge_40_rate,
            "post_d_exit_monitor_only_historical_peak5_dd_median_pct":profile.peak5__peak_post5_max_dd_pct_median,
            "post_d_exit_monitor_only_historical_peak5_dd_valid_n":profile.peak5__peak_post5_max_dd_pct_n,
            "post_d_exit_monitor_only_historical_selloff_speed_median_pp_session":profile.peak5__peak_post5_dd_speed_pp_per_session_median,
            "post_d_exit_monitor_only_historical_selloff_speed_valid_n":profile.peak5__peak_post5_dd_speed_pp_per_session_n,
            "post_d_exit_monitor_only_recent_relapse_n":sample_groups[0],
            "post_d_exit_monitor_only_recent_hold_n":sample_groups[1],
            "post_d_exit_monitor_only_recent_relapse_rate":ref.relapse_rate,
            "post_d_exit_monitor_only_new_high_after_warning_n":int(valid_new.eq(True).sum()),
            "post_d_exit_monitor_only_new_high_after_warning_valid_n":len(valid_new),
            "post_d_exit_monitor_only_new_high_after_warning_rate":valid_new.eq(True).mean() if len(valid_new) else None,
            "post_d_exit_monitor_only_warning_to_repair_median_sessions":true_pairs.median(),
            "post_d_exit_monitor_only_warning_to_repair_valid_n":int(true_pairs.notna().sum()),
            "post_d_exit_monitor_only_high_divergence_act061a":bool(ref.high_divergence),
            "post_d_exit_monitor_only_extreme_pair_d20_gap_pp":ref.D20_gap_pp,
            "boundary_low_upper_wick_act061b":ref["name"] in LOW_WICK_NAMES,
            "boundary_recent_descriptive_sample_status":"BOTH_GROUPS_AT_LEAST_5" if enough else (
                "NO_RECENT_EVENTS" if not len(local) else "AT_LEAST_ONE_GROUP_BELOW_5"),
            "boundary_causal_conversion":"PRE_FIELDS_REQUIRE_ASOF_FEATURE_REBUILD; POST_D_FIELDS_TARGET_ONLY",
            "boundary_training_admission":"NOT_ADMITTED",
            "boundary_known_reverse_case_limit":"HISTORICAL_REVERSE_SELECTION; ONLY_ONE_CONTROL_PAIR; NOT_FORWARD_VALIDATION",
            "boundary_repair_status_missing_n":int(recent.post_warning_line_repair.isna().sum()),
            "boundary_warn_earliest_incomplete_n":int(recent.warning_earlier_unavailable_n.gt(0).sum()),
        }
        if code == "600016.SH":
            row["boundary_known_reverse_case_limit"] += "; 0_IN_2Y; HISTORICAL_MAIN_20241114_ONLY"
        if code == "688621.SH":
            row["boundary_known_reverse_case_limit"] += "; 20250515_WARN_FIRST_OBSERVED_D_PLUS_5_EARLIER_2_MISSING"
        if ref.archetype == "D":
            row["boundary_known_reverse_case_limit"] += "; ARCHETYPE_D_ONE_STOCK"
        for group in PATHS + RELATIONS:
            row[f"post_d_exit_monitor_only_{group.lower()}_n"] = int(ref[group])
        for field in PRE_COLUMNS:
            values = pre[field]
            row[f"strict_d0_causal_hist_{field}_median"] = values.median()
            row[f"strict_d0_causal_hist_{field}_valid_n"] = int(values.notna().sum())
            row[f"strict_d0_causal_matched_pre_{field}_net"] = paired_pre[field].iloc[0] - paired_pre[field].iloc[1]
        for horizon in [5, 10, 20]:
            field = f"close_ret_D{horizon}_pct"
            row[f"post_d_exit_monitor_only_control_Dp{horizon}_net_pp"] = main[field] - ordinary[field]
        for family in FAMILIES:
            hits = history.loc[history[family].eq(True)]
            observed = hits.t5_close.dropna()
            name = family.lower().replace("-","_")
            row[f"historical_buy_{name}_hits_n"] = len(hits)
            row[f"historical_buy_{name}_t5_valid_n"] = len(observed)
            row[f"historical_buy_{name}_t5_mean_pct"] = observed.mean() * 100
            row[f"historical_buy_{name}_t5_positive_rate"] = observed.gt(0).mean() if len(observed) else None
        out.append(row)
    frame = pd.DataFrame(out)
    assert frame.ts_code.is_unique and len(frame) == 42
    assert frame.identity_all_history_breakouts_n.sum() == 3374
    assert frame.identity_all_history_hidden_n.sum() == 3244
    assert frame.identity_recent2y_total_n.sum() == 583
    assert frame.identity_recent2y_complete20_n.sum() == 562
    assert frame.post_d_exit_monitor_only_recent_relapse_n.sum() == 151
    assert frame.boundary_low_upper_wick_act061b.sum() == 6
    return frame
