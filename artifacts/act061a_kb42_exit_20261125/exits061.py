"""ACT-061A frozen Reader exit research and paired SVG export (strict 0 FIT)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import gc
from hashlib import sha256
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np
import pandas as pd
import pyarrow as pa
from scipy import stats
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "act060a_kb35_20261125"))
import compute060 as prev

BASE = "5477c6a3440fdec9dbf7d90b61e520e74fe9626b"
WAVES = "ACT061A_KB42_562_EXIT_PATHS.csv"
SUMMARY = "ACT061A_KB42_STOCK_EXIT_SUMMARY.csv"
PACK = "ACT061A_EXIT_PAIRS_SVG_PACK.zip"
CLASSES = ("NEVER_BOTH_ABOVE", "RECOVER_AND_HOLD", "WARN_THEN_REPAIR", "UNRECOVERED_BY_D20")
GROUPS = ("POSITIVE_PEAK_NEGATIVE_D20", "COMPLEMENT_411")
CANARY = "920748.BJ"
CANARY_EVIDENCE = "ACT061A_EXIT_CANARY_COUNTER_FIX.json"
TIMING = ("BEFORE_PEAK", "AT_PEAK", "AFTER_PEAK", "NO_WARN", "CANNOT_CONFIRM")
TIMELINE = ("offset", "date", "bar_status", "white_state", "yellow_state", "white_downcross",
            "yellow_downcross", "warning_hits", "warning_unknown_types")
MASK = {True: "1", False: "0", None: "?"}
PRE_FIELDS = ("volume_mean3_vs_prev20", "amplitude_mean5_vs_prev20", "dd20_max_close_drawdown_pct",
              "close_vs_white_d1_pct", "close_vs_yellow_d1_pct")
PEAK_FIELDS = tuple(f"peak_{day}_{metric}" for day in ("m1", "D0") for metric in (
    "volume_prev5_ratio", "upper_wick_range_ratio", "close_vs_high_pct", "bearish_body_pct"))
TEST_FIELDS = PRE_FIELDS + ("D_close_vs_Dm1_pct", "D_high_vs_Dm1_pct", "D_volume_vs_prior5_ratio") + PEAK_FIELDS + (
    "first_loss_to_recovery_sessions", "peak_post5_max_dd_pct")
BINARY_FIELDS = ("Dm1_both_above", "both_recovery_after_loss", "post_warning_new_high", "post_warning_line_repair")
RULES = {
    "line": "On the frozen D-basis, C >= line counts as above. A downcross compares adjacent valid slots, including D-1 -> D, with previous C >= line and current C < line. Unknowns never bridge gaps.",
    "warning": "Union on D+1..D+20: (H-max(O,C))/(H-L) >= .50 with (H-L)/L >= .03; or C<O and C/H <= .95; or V >= 2 x mean of prior five consecutive valid D-basis volumes, C <= 1.01 x previous C and C <= (H+L)/2; or white or yellow adjacent downcross. H=L cannot trigger wick. All simultaneous observed triggers retained, with earlier missing triggers making the first warning provisional.",
    "repair": "First both-line loss is the first known non-both state after first known both. First structural recovery is a later known both state. Post-warning line repair is first later both after a known non-both state at or after the warning. New high is strict H > all valid highs D..first-warning, requiring a fully known baseline; an observed new high still establishes a hit when later bars are missing.",
    "classification": "On the 20-bar cohort, first test no observed both-above in D..D+20; then D20 not confirmed both; then a confirmed both-line recovery after loss, post-warning line repair, or post-warning strict new high; all remaining waves close above both with no observed repair and classify RECOVER_AND_HOLD. Any unknown line evidence is flagged separately; unknown D20 is not observed failure.",
    "basis": "Peak is earliest highest D-basis H in D+1..D+20. Raw same-D price subtraction and sign precede percentage conversion. D+5/+10/+20 use the exact closes relative to D close. Peak+1..+5 prior frozen low drawdown can extend past D+20 only as far as the frozen date.",
    "pair": "Within each stock, require both peaks >=20%, the retained wave has D20 >=10% and holds >=50% of its peak, and the relapse wave is strictly positive peak with negative D20. Choose max retained D20 and min relapse D20, ties higher peak then earlier D. Rank stocks by within-stock D20 gap, descending, then security ID. Reserve the top qualifying stock in each archetype and fill to 12 by rank. These are post-outcome extremes for retrospective review.",
    "stats": "Pooled Mann-Whitney U with Cliff delta or two-sided Fisher with odds ratio and risk difference; within-stock contrast uses one difference in medians/rates per common stock and two-sided Wilcoxon (zero_method=wilcox), with median effect; differences are relapse minus complement. Kruskal-Wallis compares the per-stock differences across archetypes for strata with at least two stocks per archetype. BH across every reported finite p-value. Reverse-selected, overlapping waves and shared stocks limit calibration. Pooled and within-stock results are descriptive and exploratory, not prospective or causal.",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_bytes(rows):
    fields = list(dict.fromkeys(field for row in rows for field in row))
    handle = StringIO(newline="")
    writer = csv.DictWriter(handle, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8-sig")


def checked(path, fingerprint):
    return prev.assert_identity(path, fingerprint)


def load_frozen(batch):
    past59 = batch.parent / "act059a_kb42_20261125"
    past60 = batch.parent / "act060a_kb35_20261125"
    sys.path.insert(0, str(past59))
    import case_c
    import wave_b
    from metric_a import OLD

    prev.OLD, prev.wave_b, prev.case_c = OLD, wave_b, case_c
    manifestfile = batch / "inputs/source_manifest.json"
    manifest = OLD.read_json(manifestfile)
    sources = {"manifest": OLD.identity(manifestfile)}
    for name, stamp in manifest["local_inputs"].items():
        sources[name] = checked(batch / "inputs" / name, stamp)
    for name, stamp in manifest["accepted_local_inputs"].items():
        source = batch.parents[1] / name
        sources[source.name] = checked(source, stamp)

    final59 = OLD.read_json(past59 / "ACT059A_FINAL_DELIVERY_VERIFIED.json")
    final60 = OLD.read_json(past60 / "ACT060A_FINAL_DELIVERY_VERIFIED.json")
    assert final60["source_commit"] == BASE
    wave59 = past59 / "delivery/ACT059A_108_WAVES_SUPPLEMENT.csv"
    wave60 = past60 / "delivery/ACT060A_KB35_2Y_WAVES_ALL.csv"
    for path, entries in ((wave59, final59["outputs"]), (wave60, final60["files"])):
        checked(path, next(entry for entry in entries if entry["name"] == path.name))
    cards = read_csv(past60 / "inputs/02_ACT058B_KB42_CARDS.csv")
    assert Counter(row["archetype_frozen"] for row in cards) == Counter(A=18, B=16, C=7, D=1)
    roster = {row["security_id"]: row for row in cards}
    assert len(roster) == 42
    source59 = read_csv(wave59)
    source60 = read_csv(wave60)
    assert (len(source59), len(source60)) == (108, 475)
    keys59 = {row["security_id"] for row in source59}
    keys60 = {row["security_id"] for row in source60}
    assert keys59 == set(OLD.WAVES) and not keys59 & keys60
    assert set(roster) - (keys59 | keys60) == {"600016.SH"}
    sources_rows = [row | {"source_batch": action} for action, rows in (
        ("ACT-059A", source59), ("ACT-060A", source60)) for row in rows]
    prof, events, _, _, r56, r50, stamps = OLD.frozen_inputs()
    receipt58 = OLD.read_json(OLD.ROOT / "evidence/compute_receipt.json")
    receipt60 = OLD.read_json(past60 / "evidence/ACT060A_COMPUTE_RECEIPT.json")
    for name, stamp in stamps.items():
        for ref in (receipt58["source_identity"][name], receipt60["sources"][name]):
            assert (stamp["sha256"], stamp["bytes"]) == (ref["sha256"], ref["bytes"]), name
    for card in prof.itertuples():
        original = roster[card.security_id]
        assert (original["name"], original["archetype_frozen"], int(original["all_reverse_events"])) == (
            card.name, card.archetype, card.all_event_n)
    recent = events.loc[events.D.between(int(OLD.START), int(OLD.END))]
    frozen = {(row.security_id, str(row.D)): (int(row.exchange_session_ordinal), bool(row.full20))
              for row in recent.itertuples()}
    assert len(frozen) == len(recent) == len(sources_rows)
    for src in sources_rows:
        code, day = src["security_id"], src["D"]
        assert (src["name"], src["archetype"]) == (roster[code]["name"], roster[code]["archetype_frozen"])
        assert frozen[code, day] == (int(src["D_ordinal"]), src["path_status"] == "COMPLETE")
        assert src["event_id"] == f"{code}/{day}"
    assert len({row["event_id"] for row in sources_rows}) == len(frozen)
    pairs = read_csv(past60 / "delivery/ACT060A_KB35_REP_AND_CONTROL_70.csv")
    fallback, = [row for row in pairs if row["security_id"] == "600016.SH" and row["role"] == "MAIN_REVERSE_EVENT"]
    assert fallback["sample_window"] == "FALLBACK_HISTORY" and fallback["full20"] == "True"
    return roster, sources_rows, r56, r50, receipt58, sources | stamps, fallback["case_id"]


def number(value):
    return float(value) if value not in (None, "") else None


def line_state(bar, index):
    return None if bar is None or bar[index] is None else bool(bar[3] >= bar[index])


def all_lines(states):
    if False in states:
        return False
    return None if None in states else True


def first_state(values, start, end, calendar, at, prefix):
    check = [(i, values[i]) for i in range(start, end + 1)]
    result = prev.wave_b.summarize_first([i for i, hit in check if hit is True],
                                        [(i, "UNKNOWN") for i, hit in check if hit is None],
                                        calendar, at, start, end)
    return {f"{prefix}_{key}": val for key, val in result.items() if key != "window_unavailable_slots"}


def after_trigger(states, start, end):
    if start is None:
        return None, None, 0
    unknown = 0
    for i in range(start, end + 1):
        if states[i] is True:
            return i, True, unknown
        unknown += states[i] is None
    return None, None if unknown else False, unknown


def calc_warnings(bars, offset, down):
    previous = bars[offset - 1]
    bar = bars[offset]
    wick = fade = stalled = None
    if bar is not None:
        o, hi, lo, close, v, *_ = bar
        wick = hi > lo and (hi - max(o, close)) / (hi - lo) >= .50 and (hi - lo) / lo >= .03
        fade = close < o and close / hi <= .95
        prior = [bars[j] for j in range(offset - 5, offset)]
        if all(item is not None for item in prior):
            v5 = float(np.mean([item[4] for item in prior]))
            stalled = v >= 2 * v5 and close <= 1.01 * previous[3] and close <= (hi + lo) / 2
    return {"LONG_UPPER_WICK": wick, "BEARISH_HIGH_FADE": fade, "VOLUME_STALL": stalled,
            "WHITE_DOWNCROSS": down[offset][0], "YELLOW_DOWNCROSS": down[offset][1]}


def line_details(slots, stock, at, peak, full):
    bars = {row[0]: row[-1] for row in slots}
    days = {row[0]: row[1] for row in slots}
    status = {row[0]: row[2] for row in slots}
    states = {i: tuple(line_state(bars[i], j) for j in (5, 6)) for i in range(-1, 21)}
    both = {i: all_lines(pair) for i, pair in states.items()}
    stable = {i: "".join(MASK[x] for x in pair) for i, pair in states.items()}
    crossing = {i: tuple(None if None in (older, now) else older and not now
                        for older, now in zip(states[i-1], states[i], strict=True)) for i in range(21)}
    details = first_state(both, 0, 20, stock.calendar, at, "first_both_above")
    for j, line in enumerate(("white", "yellow")):
        details.update(first_state({i: v[j] for i, v in crossing.items()}, 0, 20, stock.calendar, at,
                                   f"first_{line}_downcross"))
        down = details[f"first_{line}_downcross_first_offset"]
        recovery, confirmed, earlier_missing = after_trigger(
            {i: v[j] for i, v in states.items()}, down + 1 if down is not None else None, 20)
        details.update({f"first_{line}_recover_offset": recovery, f"first_{line}_recover_date": days.get(recovery),
                        f"{line}_recovery_after_downcross": confirmed,
                        f"{line}_recover_preceding_unknown_n": earlier_missing})
    initial = details["first_both_above_first_offset"]
    lost, lost_obs, lost_prior_unknown = after_trigger(
        {i: None if v is None else not v for i, v in both.items()},
        initial + 1 if initial is not None else None, 20)
    recovery, recovered, recovery_prior_unknown = after_trigger(both, lost + 1 if lost is not None else None, 20)
    flags = {i: calc_warnings(bars, i, crossing) for i in range(1, 21)}
    warnings = {i: True if any(f.values()) else None if None in f.values() else False for i, f in flags.items()}
    details.update(first_state(warnings, 1, 20, stock.calendar, at, "warning"))
    first = details["warning_first_offset"]
    warn_hit = None if first is None else "|".join(name for name, result in flags[first].items() if result)
    if first is None:
        warn_timing = "NO_WARN" if all(x is False for x in warnings.values()) else "CANNOT_CONFIRM"
    elif peak is None:
        warn_timing = "CANNOT_CONFIRM"
    else:
        warn_timing = "BEFORE_PEAK" if first < peak else "AFTER_PEAK" if first > peak else "AT_PEAK"
    new_high = repaired = None
    new_high_offset = repair_offset = None
    if first is not None:
        prior = [bars[i] for i in range(first + 1)]
        if all(item is not None for item in prior):
            max_before = max(item[1] for item in prior)
            hi = {i: None if bars[i] is None else bars[i][1] > max_before for i in range(first + 1, 21)}
            new_high_offset, new_high, _ = after_trigger(hi, first + 1, 20)
        warning_loss, warning_loss_obs, _ = after_trigger(
            {i: None if v is None else not v for i, v in both.items()}, first, 20)
        if warning_loss is not None:
            repair_offset, repaired, _ = after_trigger(both, warning_loss + 1, 20)
        elif warning_loss_obs is False:
            repaired = False
    if not full:
        path_class = None
    elif initial is None:
        path_class = CLASSES[0]
    elif both[20] is not True:
        path_class = CLASSES[3]
    elif recovered or repaired or new_high:
        path_class = CLASSES[2]
    else:
        path_class = CLASSES[1]
    timeline = [(i, days[i], status[i], *[MASK[x] for x in states[i]], *crossing[i],
                 None if i == 0 else [key for key, value in flags[i].items() if value],
                 None if i == 0 else [key for key, value in flags[i].items() if value is None]) for i in range(21)]
    return details | {
        "Dm1_line_state": stable[-1], "Dm1_both_above": both[-1], "D_line_state": stable[0],
        "D20_line_state": stable[20], "line_unknown_slots_D0_D20_n": sum("?" in stable[i] for i in range(21)),
        "both_line_loss_observed": lost_obs, "first_both_loss_offset": lost, "first_both_loss_date": days.get(lost),
        "first_both_loss_earlier_unknown_n": lost_prior_unknown, "first_both_recovery_offset": recovery,
        "first_both_recovery_date": days.get(recovery), "both_recovery_after_loss": recovered,
        "both_recovery_earlier_unknown_n": recovery_prior_unknown,
        "first_loss_to_recovery_sessions": recovery - lost if recovery is not None else None,
        "warning_first_kinds": warn_hit, "warning_relation_to_peak": warn_timing,
        "warning_relation_evidence": "CONFIRMED" if full and (warn_timing == "NO_WARN" or
            details["warning_first_status"] == "FIRST_CONFIRMED_WITHIN_WINDOW") else "OBSERVED_ONLY_OR_UNKNOWN",
        "post_warning_new_high": new_high, "post_warning_new_high_offset": new_high_offset,
        "post_warning_new_high_date": days.get(new_high_offset), "post_warning_line_repair": repaired,
        "post_warning_line_repair_offset": repair_offset, "post_warning_line_repair_date": days.get(repair_offset),
        "exit_path_class": path_class,
        "exit_path_evidence": ("INCOMPLETE_20BARS" if not full else "KNOWN_LINE_PATH" if
                               all("?" not in stable[i] for i in range(21)) else "PARTIAL_LINE_EVIDENCE"),
        "line_timeline_D0_D20_json": prev.compact(timeline),
    }


def event(stock, src):
    at = int(src["D_ordinal"])
    assert str(stock.calendar[at]) == src["D"]
    slots = prev.path_context(stock, at)
    by_day = {row[0]: row[-1] for row in slots}
    bars = tuple(by_day[i] for i in range(21))
    statuses = tuple(row[2] for row in slots[10:])
    outcomes = prev.wave_b.outcomes(bars, statuses, stock.calendar, at, prev.wave_b.ENDPOINTS)
    peak = prev.peak_metrics(stock, at, bars, outcomes)
    for key in ("peak_day", "peak_D", "observed_sessions"):
        assert str(peak[key] if peak[key] is not None else "") == src[key], (src["event_id"], key)
    assert peak["peak_status"] == src["peak_status"], src["event_id"]
    full = peak["full20"]
    assert full == (src["path_status"] == "COMPLETE"), src["event_id"]
    for key, actual in (("peak_high_d_basis", peak["peak_high_d_basis"]),
                        ("d_close_basis", outcomes["D_basis_close_verified"]),
                        ("raw_max_rise_pct", peak["raw_max_rise_pct_same_basis_exact"]), *(
        (f"close_ret_D{h}_{name}", outcomes[f"close_ret_D{h}_{name}"])
        for h in prev.wave_b.ENDPOINTS for name in ("close_d_basis", "pct")
    )):
        expected = number(src[key])
        assert (actual is None) == (expected is None), (src["event_id"], key)
        if actual is not None:
            assert np.isclose(expected, actual, rtol=3e-11, atol=3e-12), (src["event_id"], key, expected, actual)
    if src["source_batch"] == "ACT-060A":
        assert src["peak_minus_D20_sign"] == peak["peak_minus_D20_sign"], src["event_id"]
        assert src["positive_peak_negative_D20"] == ("" if not full else str(peak["positive_peak_negative_D20"]))
    if full:
        assert peak["positive_peak_negative_D20"] is not None
    post = prev.post_peak(stock, at, peak)
    assert int(src["peak_post5_observed_sessions"]) == post["peak_post5_observed_sessions"], src["event_id"]
    legacy_dd = number(src["peak_post5_max_dd_pct"])
    actual_dd = post["peak_post5_max_dd_pct"]
    assert (legacy_dd is None and actual_dd is None) or (
        legacy_dd is not None and actual_dd is not None and np.isclose(actual_dd, legacy_dd, rtol=3e-11, atol=3e-12)), src["event_id"]
    d0, d1 = bars[0], by_day[-1]
    prior5 = [by_day[i] for i in range(-5, 0)]
    metrics = {key: number(src[key]) for key in PRE_FIELDS + PEAK_FIELDS}
    metrics |= {"D_close_vs_Dm1_pct": (d0[3] / d1[3] - 1) * 100 if d1 else None,
                "D_high_vs_Dm1_pct": (d0[1] / d1[3] - 1) * 100 if d1 else None,
                "D_volume_vs_prior5_ratio": d0[4] / float(np.mean([x[4] for x in prior5])) if all(prior5) else None}
    core = {field: src[field] for field in ("event_id", "security_id", "name", "archetype", "D", "D_ordinal",
                                            "source_batch", "event_group")}
    cohort = GROUPS[0] if peak["positive_peak_negative_D20"] else GROUPS[1]
    return (core | {"cohort": cohort if full else "INCOMPLETE_20BARS", "sample_status": "COMPLETE_20BARS" if full else "INCOMPLETE_20BARS"}
            | peak | {field: value for field, value in outcomes.items() if field.startswith(("D_basis_close", "close_ret_"))}
            | post | metrics | line_details(slots, stock, at, peak["peak_day"], full)), slots


def median(values):
    return float(np.median(values)) if values else None


def groups_for(rows, field):
    return [[row[field] for row in rows if row["cohort"] == group and row[field] is not None] for group in GROUPS]


def run_tests(full, per_code):
    tests = []
    fields = TEST_FIELDS + BINARY_FIELDS
    for field in fields:
        a, b = groups_for(full, field)
        binary = field in BINARY_FIELDS
        base = {"section": "TEST", "metric": field, "n_relapse": len(a), "n_complement": len(b),
                "null_relapse": 151 - len(a), "null_complement": 411 - len(b),
                "relapse_stat": float(np.mean(a)) if a and binary else median(a),
                "complement_stat": float(np.mean(b)) if b and binary else median(b)}
        if a and b:
            if binary:
                table = [[sum(a), len(a)-sum(a)], [sum(b), len(b)-sum(b)]]
                odds, p_value = stats.fisher_exact(table, alternative="two-sided")
                effect = float(np.mean(a) - np.mean(b))
                tests.append(base | {"test": "POOLED_FISHER", "p_value": float(p_value), "effect": effect,
                                     "effect_measure": "RISK_DIFFERENCE_RELAPSE_MINUS_COMPLEMENT",
                                     "odds_ratio": "INF" if np.isinf(odds) else None if np.isnan(odds) else float(odds),
                                     "fisher_relapse_true": sum(a), "fisher_complement_true": sum(b)})
            else:
                u, p_value = stats.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic")
                tests.append(base | {"test": "POOLED_MANN_WHITNEY_U", "test_stat": float(u), "p_value": float(p_value),
                                     "effect": float(2 * u / (len(a) * len(b)) - 1),
                                     "effect_measure": "CLIFF_DELTA_RELAPSE_MINUS_COMPLEMENT"})
        by_arch = defaultdict(list)
        counts = [0, 0]
        stock_effects = {}
        for code, rows in per_code.items():
            x, y = groups_for(rows, field)
            if not x or not y:
                continue
            effect = float(np.mean(x) - np.mean(y)) if binary else median(x) - median(y)
            by_arch[rows[0]["archetype"]].append(effect)
            stock_effects[code] = {"n_relapse": len(x), "n_complement": len(y), "effect": effect}
            counts[0] += len(x)
            counts[1] += len(y)
        effects = [x["effect"] for x in stock_effects.values()]
        evidence = {"section": "TEST", "metric": field, "paired_stock_n": len(effects), "n_relapse": counts[0],
                    "n_complement": counts[1], "stock_effects_json": prev.compact(stock_effects),
                    "archetype_stock_n_json": prev.compact({arch: len(by_arch[arch]) for arch in "ABCD"})}
        if len(effects) >= 2:
            statistic, p_value = stats.wilcoxon(effects, alternative="two-sided", zero_method="wilcox") if any(effects) else (0., 1.)
            tests.append(evidence | {"test": "WITHIN_STOCK_WILCOXON", "effect": median(effects),
                                     "effect_measure": "MEDIAN_OF_STOCK_RELAPSE_MINUS_COMPLEMENT",
                                     "paired_nonzero_stock_n": sum(x != 0 for x in effects),
                                     "test_stat": float(statistic), "p_value": float(p_value)})
        included = {arch: values for arch, values in by_arch.items() if len(values) >= 2}
        if len(included) >= 2:
            samples = [x for values in included.values() for x in values]
            statistic, p_value = stats.kruskal(*included.values()) if len(set(samples)) > 1 else (0., 1.)
            tests.append(evidence | {"test": "ACROSS_ARCHETYPES_KRUSKAL_WALLIS_STOCK_EFFECTS", "effect":
                                     max(0., float((statistic - len(included) + 1) / (len(samples)-len(included)))),
                                     "effect_measure": "EPSILON_SQUARED", "test_stat": float(statistic),
                                     "archetypes_tested": "|".join(sorted(included)), "tested_stock_n": len(samples),
                                     "archetype_effect_medians_json": prev.compact({k: median(v) for k, v in included.items()}),
                                     "p_value": float(p_value)})
    q_values = stats.false_discovery_control([row["p_value"] for row in tests], method="bh")
    for row, q in zip(tests, q_values, strict=True):
        row["p_bh"] = float(q)
    return tests


def pairs_for(per_code):
    candidates = []
    for code, rows in per_code.items():
        strong = [x for x in rows if x["raw_max_rise_pct_same_basis_exact"] >= 20]
        held = [x for x in strong if x["close_ret_D20_pct"] >= 10 and
                x["close_ret_D20_pct"] >= x["raw_max_rise_pct_same_basis_exact"] / 2]
        lost = [x for x in strong if x["cohort"] == GROUPS[0]]
        if held and lost:
            hold = min(held, key=lambda x: (-x["close_ret_D20_pct"], -x["raw_max_rise_pct_same_basis_exact"], x["D"]))
            relapse = min(lost, key=lambda x: (x["close_ret_D20_pct"], -x["raw_max_rise_pct_same_basis_exact"], x["D"]))
            candidates.append({"security_id": code, "archetype": hold["archetype"], "hold": hold, "relapse": relapse,
                               "d20_gap_pp": hold["close_ret_D20_pct"] - relapse["close_ret_D20_pct"],
                               "hold_candidate_n": len(held), "relapse_candidate_n": len(lost)})
    candidates.sort(key=lambda x: (-x["d20_gap_pp"], x["security_id"]))
    reserves = dict((row["archetype"], row["security_id"]) for row in reversed(candidates))
    selected = set(reserves.values())
    for pair in candidates:
        if len(selected) < 12:
            selected.add(pair["security_id"])
    return candidates, [pair for pair in candidates if pair["security_id"] in selected]


def stock_summary(roster, waves, full, grouped, candidates, picked, fallback):
    out = []
    candidate_by = {row["security_id"]: row for row in candidates}
    picked_codes = {row["security_id"] for row in picked}
    all_by = defaultdict(list)
    for row in waves:
        all_by[row["security_id"]].append(row)
    for code, card in sorted(roster.items()):
        rows = grouped.get(code, [])
        by_path = Counter(row["exit_path_class"] for row in rows)
        by_timing = Counter(row["warning_relation_to_peak"] for row in rows)
        by_cohort = Counter(row["cohort"] for row in rows)
        candidate = candidate_by.get(code)
        stock = {"section": "STOCK", "security_id": code, "name": card["name"], "archetype": card["archetype_frozen"],
                 "event_n": len(all_by[code]), "complete_n": len(rows), "incomplete_n": len(all_by[code])-len(rows),
                 "coverage": "HAS_COMPLETE_IN_2Y" if rows else "0_IN_2Y",
                 "historical_fallback_case_id_outside_denominator": fallback if code == "600016.SH" else None,
                 "relapse_n": by_cohort[GROUPS[0]], "complement_n": by_cohort[GROUPS[1]],
                 "relapse_rate": by_cohort[GROUPS[0]] / len(rows) if rows else None,
                 "high_divergence": candidate is not None, "selected_svg_pair": code in picked_codes}
        if candidate:
            stock.update({"hold_case_id": candidate["hold"]["event_id"], "relapse_case_id": candidate["relapse"]["event_id"],
                          "D20_gap_pp": candidate["d20_gap_pp"], "hold_candidate_n": candidate["hold_candidate_n"],
                          "relapse_candidate_n": candidate["relapse_candidate_n"]})
        for key in ("peak_day", "raw_max_rise_pct_same_basis_exact", "close_ret_D20_pct", "peak_post5_max_dd_pct"):
            stock[f"median_{key}"] = median([row[key] for row in rows if row[key] is not None])
            a, b = groups_for(rows, key)
            stock[f"relapse_median_{key}"], stock[f"complement_median_{key}"] = median(a), median(b)
        stock.update({key: by_path[key] for key in CLASSES} | {key: by_timing[key] for key in TIMING})
        out.append(stock)
    path_counts = Counter((x["archetype"], x["cohort"], x["exit_path_class"]) for x in full)
    for arch in "ABCD":
        for group in GROUPS:
            for kind in CLASSES:
                out.append({"section": "CROSSTAB", "archetype": arch, "cohort": group, "exit_path_class": kind,
                            "cell_n": path_counts[arch, group, kind]})
    return out


def mark_for(row, offset_key, date_key):
    return row[offset_key], row[date_key]


def draw(row, slots, role):
    white = mark_for(row, "first_white_downcross_first_offset", "first_white_downcross_first_date")
    yellow = mark_for(row, "first_yellow_downcross_first_offset", "first_yellow_downcross_first_date")
    structural = mark_for(row, "first_both_recovery_offset", "first_both_recovery_date")
    recovery = structural if structural[0] is not None else mark_for(row, "post_warning_line_repair_offset", "post_warning_line_repair_date")
    old_row = row | {"bars_Dm10_to_Dp20_json": prev.compact(slots), "sample_window": "正峰保持" if role == "HOLD" else "正峰负 D+20",
                     "any_frozen_signal_first_status": row["first_white_downcross_first_status"],
                     "any_frozen_signal_first_offset": white[0], "any_frozen_signal_first_date": white[1],
                     "warning_any_first_offset": row["warning_first_offset"], "warning_any_first_date": row["warning_first_date"],
                     "warning_any_first_status": row["warning_first_status"]}
    chart = prev.draw_chart(old_row)
    prev.verify_chart(chart, old_row)
    ns = prev.case_c.NS
    ET.register_namespace("", ns.strip("{}"))
    root = ET.fromstring(chart)
    root.attrib.update({"data-event-id": row["event_id"], "data-role": role, "data-archetype": row["archetype"],
                        "data-source-basis": "FROZEN_READER_QFQ"})
    title = root.find(ns + "title")
    title.text = f"{row['name']} {row['security_id']} · {old_row['sample_window']}"
    metadata = ET.SubElement(root, ns + "metadata")
    add = (("yellow_down", "首次破黄", yellow, "#a66900", 30), ("recovery", "首次收复双线", recovery, "#056a52", 357))
    expected = {"event": (0, row["D"]), "peak": (row["peak_day"], row["peak_D"]),
                "warning": (row["warning_first_offset"], row["warning_first_date"]), "white_down": white,
                "yellow_down": yellow, "recovery": recovery}
    def details(mark, uncertain):
        off, day = mark
        if off is not None:
            return f"{prev.case_c.display_date(day)} D{off:+d}" + ("＊" if uncertain else "")
        return "存在缺证" if uncertain else "窗口内无已知命中"

    def label(x, y, value, fill):
        root.append(ET.fromstring(prev.case_c.label(x, y, value, fill=fill, **{"class": "marker"})))

    for element in root.findall(ns + "text"):
        val = element.text or ""
        if val.startswith("首个冻结信号"):
            element.text = f"首次破白   {details(white, row['first_white_downcross_first_status'] in ('EARLIEST_OBSERVED_PARTIAL', 'UNAVAILABLE'))}"
        elif val.startswith("首次警示"):
            element.text = f"首次警示   {details(expected['warning'], row['warning_first_status'] in ('EARLIEST_OBSERVED_PARTIAL', 'UNAVAILABLE'))}"
    old_white = root.find(f'{ns}g[@data-marker="signal"]')
    if old_white is not None:
        old_white.set("data-marker", "white_down")
    for key, title, value, color, x in add:
        missing = (row["first_yellow_downcross_first_status"] in ("EARLIEST_OBSERVED_PARTIAL", "UNAVAILABLE") if key == "yellow_down"
                   else bool(row["both_recovery_earlier_unknown_n"] or row["line_unknown_slots_D0_D20_n"]))
        label(x, 127, f"{title}   {details(value, missing)}", color)
        off, day = value
        if off is None:
            continue
        x_pos = 104 + (off + 10.5) * ((1328 - 104) / 31)
        group = ET.SubElement(root, ns + "g", {"data-marker": key, "data-offset": str(off), "data-date": day})
        line = ET.SubElement(group, ns + "line", {"x1": f"{x_pos:.2f}", "x2": f"{x_pos:.2f}", "y1": "155", "y2": "557",
                                                   "stroke": color, "stroke-width": "1", "stroke-dasharray": "3 2"})
        assert line.get("x1") == line.get("x2")
        ET.SubElement(group, ns + "circle", {"cx": f"{x_pos:.2f}", "cy": "155", "r": "3", "fill": color})
    label(685, 127, f"峰涨 {row['raw_max_rise_pct_same_basis_exact']:+.2f}%   D+20 {row['close_ret_D20_pct']:+.2f}%", "#152239")
    metadata.text = prev.compact({"id": row["event_id"], "role": role, "marks": expected,
                                  "bars_sha256": sha256(prev.compact(slots).encode()).hexdigest(),
                                  "line_class": row["exit_path_class"], "geometry": {"slots": 31, "left": 104, "right": 1328}})
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parsed = ET.fromstring(data)
    groups = {node.get("data-marker"): node for node in parsed.findall(f'{ns}g[@data-marker]')}
    assert set(groups) == {key for key, value in expected.items() if value[0] is not None}
    dates = {node.get("data-slot"): node.get("data-date") for node in parsed.findall(f'{ns}g[@data-slot]')}
    assert len(dates) == 31 and parsed.get("data-event-id") == row["event_id"]
    for key, group in groups.items():
        off, day = expected[key]
        assert group.get("data-offset") == str(off) and group.get("data-date") == day == dates[str(off)]
        marker_x = f"{104 + (off + 10.5) * ((1328 - 104) / 31):.2f}"
        assert group.find(ns + "line").get("x1") == marker_x
    return data


def svg_pack(picked, contexts):
    members = {}
    pair_rows = []
    for i, pair in enumerate(picked, start=1):
        info = {key: pair[key] for key in ("security_id", "archetype", "d20_gap_pp", "hold_candidate_n", "relapse_candidate_n")}
        info["pair_id"] = f"{i:02d}_{pair['security_id']}"
        for role in ("HOLD", "RELAPSE"):
            row = pair[role.lower()]
            member = f"{info['pair_id']}_{role}_{row['D']}.svg"
            slots = contexts[row["event_id"]]
            assert len(slots) == 31 and slots[10][1] == row["D"]
            members[member] = draw(row, slots, role)
            info[f"{role.lower()}_svg"] = member
            info[f"{role.lower()}_event_id"] = row["event_id"]
            info[f"{role.lower()}_svg_sha256"] = sha256(members[member]).hexdigest()
            info[f"{role.lower()}_svg_bytes"] = len(members[member])
        pair_rows.append(info)
    members["PAIR_INDEX.csv"] = csv_bytes(pair_rows)
    members["README.txt"] = ("ACT-061A / observational research / 0 FIT\n\n" + RULES["pair"] + "\n\n"
          "Each chart uses its own raw Reader QFQ price and volume scale. The horizontal axis lists D-10..D+20 "
          "exchange-session slots. Gaps have a marked position instead of interpolated data. Marker ＊ denotes provisional first observation.\n\n"
          + RULES["line"] + "\n\n" + RULES["warning"] + "\n\n" + RULES["repair"] + "\n").encode()
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in members.items():
            archive.writestr(ZipInfo(name, date_time=(2026, 11, 25, 0, 0, 0)), data, compress_type=ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue(), members, pair_rows


def verify_universe(waves, full, canary):
    census = Counter((row["source_batch"], row["full20"]) for row in waves)
    paths = Counter(row["exit_path_class"] for row in full)
    cohorts = Counter(row["cohort"] for row in full)
    signs = Counter({key: 0 for key in ("POSITIVE", "NEGATIVE", "ZERO", "UNAVAILABLE")})
    signs.update(row["peak_minus_D20_sign"] for row in waves)
    phases = Counter(row["warning_relation_to_peak"] for row in full)
    line_evidence = Counter(row["exit_path_evidence"] for row in full)
    assert set(paths) <= set(CLASSES) and sum(paths.values()) == len(full)
    assert all(row["exit_path_class"] is None and row["cohort"] == "INCOMPLETE_20BARS"
               for row in waves if not row["full20"])
    for row in waves:
        full20 = row["full20"]
        timeline = json.loads(row["line_timeline_D0_D20_json"])
        assert [slot[0] for slot in timeline] == list(range(21)) and timeline[0][1] == row["D"]
        assert all(slot[2] == "OBSERVED" for slot in timeline) == full20
        assert row["D20_line_state"] == "".join(timeline[-1][3:5])
        raw = row["peak_minus_D20_price"]
        if raw is not None:
            expected = row["peak_high_d_basis"] - row["close_ret_D20_close_d_basis"]
            assert raw == expected and row["peak_minus_D20_pct"] == raw / row["D_basis_close_verified"] * 100
            assert row["peak_minus_D20_sign"] == ("POSITIVE" if raw > 0 else "NEGATIVE" if raw < 0 else "ZERO")
        if full20:
            observed_both = any(slot[3:5] == ["1", "1"] for slot in timeline)
            assert observed_both == (row["exit_path_class"] != CLASSES[0])
            if observed_both:
                assert (row["exit_path_class"] == CLASSES[3]) == (row["D20_line_state"] != "11")
    if canary:
        assert len(waves) == len(full) == 22 and cohorts == {GROUPS[0]: 7, GROUPS[1]: 15}
    else:
        assert census == {("ACT-059A", True):107, ("ACT-059A", False):1, ("ACT-060A", True):455, ("ACT-060A", False):20}
        assert signs == {"POSITIVE": 549, "NEGATIVE": 0, "ZERO": 13, "UNAVAILABLE": 21}
        assert cohorts == {GROUPS[0]: 151, GROUPS[1]: 411}
        assert Counter((row["archetype"], row["cohort"]) for row in full) == {
            (arch, group): count for arch, counts in zip("ABCD", [(43,122),(72,193),(29,81),(7,15)], strict=True)
            for group, count in zip(GROUPS, counts, strict=True)}
    return {"event_n": len(waves), "full20_n": len(full), "incomplete_n": len(waves)-len(full), "paths": paths,
            "cohorts": cohorts, "signs": signs, "warning_phases": phases, "line_evidence": line_evidence,
            "full_D20_state": Counter(row["D20_line_state"] for row in full),
            "zero_keys": [row["event_id"] for row in waves if row["peak_minus_D20_sign"] == "ZERO"]}


def verify_package(data, members, paired, canary):
    with ZipFile(BytesIO(data)) as archive:
        assert len(data) <= 2_000_000 and archive.testzip() is None
        assert len(archive.namelist()) == len(members) == len(paired)*2+2
        for name, content in members.items():
            assert archive.read(name) == content
    assert len(paired) == (1 if canary else 12)
    assert len({row["security_id"] for row in paired}) == len(paired)
    assert {row["archetype"] for row in paired} == (set("D") if canary else set("ABCD"))
    for row in paired:
        assert row["hold_event_id"].split("/")[0] == row["relapse_event_id"].split("/")[0] == row["security_id"]
        assert row["hold_event_id"] != row["relapse_event_id"]


def verify_summary(rows, data, waves, source_full_n):
    read = list(csv.DictReader(StringIO(data.decode("utf-8-sig"))))
    assert len(read) == len(rows) and [x["section"] for x in read] == [x["section"] for x in rows]
    stocks = [row for row in read if row["section"] == "STOCK"]
    tab = [row for row in read if row["section"] == "CROSSTAB"]
    p_values = [row for row in read if row["section"] == "TEST"]
    assert len(stocks) == 42 and len({row["security_id"] for row in stocks}) == 42
    assert sum(int(row["event_n"]) for row in stocks) == len(waves)
    assert sum(int(row["complete_n"]) for row in stocks) == source_full_n
    assert len(tab) == 32 and sum(int(row["cell_n"]) for row in tab) == source_full_n
    assert len({(r["archetype"], r["cohort"], r["exit_path_class"]) for r in tab}) == 32
    assert all(0 <= float(r["p_value"]) <= float(r["p_bh"]) <= 1 for r in p_values)
    assert {r["test"] for r in p_values} == {"POOLED_MANN_WHITNEY_U", "POOLED_FISHER", "WITHIN_STOCK_WILCOXON", "ACROSS_ARCHETYPES_KRUSKAL_WALLIS_STOCK_EFFECTS"}
    zero, = [row for row in stocks if row["coverage"] == "0_IN_2Y"]
    assert zero["security_id"] == "600016.SH" and zero["historical_fallback_case_id_outside_denominator"].startswith("600016.SH/")


def stamp_files(payloads, output):
    stamps = {}
    for name, data in payloads.items():
        assert len(data) <= 9_500_000, (name, len(data))
        target = output / name
        if target.exists():
            raise FileExistsError(target)
        stamps[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest(), "path": str(target)}
    for name, data in payloads.items():
        with (output / name).open("xb") as handle:
            handle.write(data)
        checked(output / name, stamps[name])
    return stamps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--canary", action="store_true")
    args = parser.parse_args()
    batch = args.batch.resolve()
    evidence = batch / "evidence" / (CANARY_EVIDENCE if args.canary else "ACT061A_EXIT_EVIDENCE.json")
    if evidence.exists():
        raise FileExistsError(evidence)
    if not args.canary:
        original = json.loads((batch / "evidence" / CANARY_EVIDENCE).read_text())
        assert original["status"] == "PASS_ONE_KB42_EXIT_STOCK_AND_SVG_PAIR"
        assert original["source"]["sha256"] == sha256(Path(__file__).read_bytes()).hexdigest()

    elapsed, cpu = {}, {}
    start, cpu_start = perf_counter(), process_time()
    wall_prev, cpu_prev = start, cpu_start
    def checkpoint(name):
        nonlocal wall_prev, cpu_prev
        wall, now_cpu = perf_counter(), process_time()
        elapsed[name], cpu[name] = wall - wall_prev, now_cpu - cpu_prev
        wall_prev, cpu_prev = wall, now_cpu
        print(f"{name} {elapsed[name]:.3f}s", flush=True)

    pa.set_cpu_count(4)
    pa.set_io_thread_count(2)
    with threadpool_limits(limits=1):
        roster, source_rows, r56, r50, prior, sources, fallback = load_frozen(batch)
        codes = {CANARY} if args.canary else set(roster)
        cfg, frame, calendar, binding = prev.project_reader(codes, r56, r50, prior)
        checkpoint("reading")
        by_stock = defaultdict(list)
        for row in source_rows:
            by_stock[row["security_id"]].append(row)
        waves, contexts = [], {}
        for code, daily in frame.groupby("canonical", sort=True):
            stock = prev.OLD.Stock(code, daily, cfg["events"][code], calendar)
            for src in sorted(by_stock[code], key=lambda x: x["D"]):
                row, bars = event(stock, src)
                waves.append(row)
                if row["full20"]:
                    contexts[row["event_id"]] = bars
        full = [row for row in waves if row["full20"]]
        grouped = defaultdict(list)
        for row in full:
            grouped[row["security_id"]].append(row)
        candidates, picked = pairs_for(grouped)
        pack, members, pair_rows = svg_pack(picked, contexts)
        payloads, test_rows, summary, stamps = {}, [], [], {}
        if not args.canary:
            test_rows = run_tests(full, grouped)
            summary = stock_summary(roster, waves, full, grouped, candidates, picked, fallback) + test_rows
            for row in pair_rows:
                for role in ("hold", "relapse"):
                    other = "relapse" if role == "hold" else "hold"
                    item = next(x for x in full if x["event_id"] == row[f"{role}_event_id"])
                    item.update({"svg_pair_id": row["pair_id"], "svg_member": row[f"{role}_svg"],
                                 "svg_counterpart_event_id": row[f"{other}_event_id"]})
            payloads = {WAVES: csv_bytes(waves), SUMMARY: csv_bytes(summary), PACK: pack}
        checkpoint("calculation")
        census = verify_universe(waves, full, args.canary)
        verify_package(pack, members, pair_rows, args.canary)
        if not args.canary:
            verify_summary(summary, payloads[SUMMARY], waves, len(full))
            wave_csv = list(csv.DictReader(StringIO(payloads[WAVES].decode("utf-8-sig"))))
            assert [row["event_id"] for row in wave_csv] == [row["event_id"] for row in waves]
            assert [row["svg_member"] for row in wave_csv if row["svg_member"]] == [row["svg_member"] for row in waves if "svg_member" in row]
            stamps = stamp_files(payloads, batch / "delivery")
        checkpoint("verification")
        result = {
            "action": "ACT-061A", "status": "PASS_ONE_KB42_EXIT_STOCK_AND_SVG_PAIR" if args.canary else
                          "PASS_42_ALIGNED_STOCKS_583_WAVES_562_CLASSIFIED_AND_12_LINKED_SVG_PAIRS",
            "created_utc": datetime.now(timezone.utc).isoformat(), "base_commit": BASE,
            "source": prev.OLD.identity(Path(__file__)), "sources": sources, "reader": binding,
            "window": [prev.OLD.START, prev.OLD.END], "census": census, "rules": RULES,
            "timeline_layout": TIMELINE, "stock_roster_n": len(codes), "historical_fallback_outside_denominator": fallback,
            "svg_pair_n": len(pair_rows), "svg_bytes": len(pack), "svg_member_n": len(members)-2,
            "high_divergence_stocks": [{"security_id": item["security_id"], "archetype": item["archetype"],
                  "name": roster[item["security_id"]]["name"], "gap_pp": item["d20_gap_pp"],
                  "hold_event_id": item["hold"]["event_id"], "relapse_event_id": item["relapse"]["event_id"]} for item in candidates],
            "cohort_descriptive": {group: {field: {"valid_n": len(v), "median": median(v)} for field in (
                "peak_day", "raw_max_rise_pct_same_basis_exact", "close_ret_D20_pct", "peak_post5_max_dd_pct",
                "warning_first_offset", "first_loss_to_recovery_sessions") if (v := [row[field] for row in full
                        if row["cohort"] == group and row[field] is not None])} for group in GROUPS},
            "cross_tab": [row for row in summary if row["section"] == "CROSSTAB"],
            "test_n": len(test_rows), "test_fdr_lt_point05_n": sum(row["p_bh"] < .05 for row in test_rows),
            "tests": [{k:v for k,v in r.items() if k != "stock_effects_json"} for r in test_rows],
            "pairs": pair_rows, "outputs": stamps,
            "governance": {"FIT": 0, "model_fit": 0, "preprocess_fit": 0, "cluster_fit": 0, "model_load": 0,
                "prediction": 0, "new_scoring": 0, "tuning": 0, "simulated_trades": 0, "production_writes": 0,
                "orders": 0, "cumulative_research_FIT": 291, "RESEARCH_ONLY": True, "STRICT_PIT": 0,
                "TRAIN_ADMITTED": 0, "NO_GO_BLOCKED": True, "production_allowed": False, "orders_sent": False,
                "buy_gate_updated": False},
            "cleanup": {"temporary_files_created": 0, "temporary_files_removed": 0, "temporary_files_remaining": 0,
                        "reader_copies_written": 0},
        }
        del frame, cfg, contexts, waves, full, grouped, candidates, picked, pack, members, payloads, test_rows
        gc.collect()
        checkpoint("cleanup")
    result["runtime"] = {"wall_s": elapsed | {"upload": None}, "cpu_s": cpu, "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         "logical_cores": os.cpu_count(), "arrow_cpu_threads": 4, "arrow_io_threads": 2,
                         "blas_threads": 1, "python": sys.executable, "python_version": sys.version.split()[0],
                         "physical_io_bytes": None, "named_input_bytes": sum(x["bytes"] for x in sources.values()),
                         "retained_reader_memory_bytes": binding["retained_deep_bytes"],
                         "output_bytes": sum(x["bytes"] for x in stamps.values())}
    prev.write_json_exclusive(evidence, result)
    print(prev.compact({"status": result["status"], "evidence": str(evidence), "census": result["census"],
                       "high_divergence_n": len(result["high_divergence_stocks"]), "svg_pair_n": len(pair_rows),
                       "test_n": len(result["tests"])}), flush=True)


if __name__ == "__main__":
    main()
