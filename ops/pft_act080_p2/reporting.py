"""Post-lock causal policy statistics and exact-date held-out case comparisons."""

from collections import defaultdict

from .contracts import JUNDA, METHOD
from .holdouts import JUNDA_CASES, _ordinal
from .outcomes import nonoverlap, pricing_outcomes, summarize


def _rank_contributions(rows):
    sums = defaultdict(float)
    for row in rows:
        if row["T5"] is not None:
            sums[row["security_id"]] += row["T5"]
    return sorted(sums, key=lambda stock: (-sums[stock], stock))[:3]


def _without(rows, stocks):
    return [row for row in rows if row["security_id"] not in stocks]


def _truncate(rows, prices, end_inclusive):
    end = "2026-11-21"
    return [{
        **r, **pricing_outcomes(prices[r["security_id"]], r["session_idx"], cutoff_exclusive=end),
    } for r in rows if r["D"] <= end_inclusive]


def compare_clean(selected, baseline, baseline_all, eligible, prices):
    top = _rank_contributions(selected)
    report = {}
    pops = {"P1B_SELECTED": selected, "V21_GRADE_A_FIRST": baseline, "V21_ALL_FIRST_REFERENCE": baseline_all}
    for name, population in pops.items():
        if len({row["structure_episode_id"] for row in population}) != len(population):
            raise ValueError(f"expected one FIRST row per wave in {name}")
        report[name] = {
            "main": summarize(population),
            "nonoverlap_T10": summarize(nonoverlap(population)),
            "equal_wave": summarize(population),
            "ex_P1B_top_three": summarize(_without(population, top)),
            "aligned_to_legacy_archive_end": summarize(_truncate(population, prices, METHOD["aligned_comparison_end"])),
        }
    report["P1B_ELIGIBLE_PRE_THRESHOLD"] = summarize(eligible)
    report["concentration"] = {
        "removed": top, "selection": "top three by sum of mature selected P1B T5, ties by security_id",
        "common_to_all_populations": True,
    }
    report["weighting"] = {
        "equal_wave": "Every policy cohort has exactly one FIRST row per unique wave, hence equal-wave equals main.",
        "overlap": "Greedy earlier D first by stock on [D+1,D+10] observed bars, fixed before outcomes.",
        "different_policy_supports": "Each policy contributes distinct exact trigger dates; common stock/price/screening, no claim of paired returns.",
    }
    leave_out = []
    for stock in sorted(set(prices) - {JUNDA}):
        for name, population in pops.items():
            leave_out.append({"left_out_security_id": stock, "policy": name, **summarize(_without(population, (stock,)))})
    return report, leave_out


def junda_cases(exact_raw, junda_new, legacy_all, prices):
    frozen_by_d = defaultdict(list)
    for event in legacy_all:
        frozen_by_d[event["D"]].append(event)
    new_by_d = {event["D"]: event for event in junda_new}
    rows = []
    for identifier, day, expected in JUNDA_CASES:
        candidates = exact_raw[day]
        prior = frozen_by_d[day]
        new = new_by_d.get(day)
        baseline_exact_a = any(r["legacy_A"] for r in prior)
        baseline_policy_a = any(r["legacy_A"] and r["role"] == "FIRST" and r["fold"] != "EXCLUDED" for r in prior)
        model_selected = new is not None and new["selected"] and new["fold"] != "EXCLUDED"
        if model_selected:
            reason = "FIRST_PASSES_FIXED_THRESHOLD"
        elif new is not None:
            reason = "FIRST_SPLIT_EXCLUDED" if new["fold"] == "EXCLUDED" else "FIRST_BELOW_FIXED_THRESHOLD"
        elif any(r["role"] for r in candidates):
            reason = "P1B_RELEASED_NON_FIRST"
        elif candidates:
            reason = "P1B_RAW_COOLDOWN_OR_DUPLICATE_REJECTED"
        else:
            reason = "NO_P1B_RAW_EXACT_D"
        idx = _ordinal(prices, JUNDA, day)
        rows.append({
            "case_id": identifier, "D": day, "expected": expected,
            "P1B_raw_arms": "|".join(r["arm"] for r in candidates),
            "P1B_released_roles": "|".join(r["role"] for r in candidates if r["role"]),
            "P1B_reject_reasons": "|".join(sorted({r["reject_reason"] for r in candidates if r["reject_reason"]})),
            "P1B_first_present": new is not None, "P1B_selected_policy": model_selected,
            "P1B_first_id": new["candidate_event_id"] if new is not None else None,
            "P1B_safety": new["safety_score"] if new is not None else None,
            "P1B_fold": new["fold"] if new is not None else None, "P1B_reason": reason,
            "V21_exact_D_tiers": "|".join(sorted({r["legacy_tier"] for r in prior})),
            "V21_exact_D_roles": "|".join(sorted({r["role"] for r in prior})),
            "V21_exact_A": baseline_exact_a, "V21_FIRST_POLICY_A": baseline_policy_a,
            "P1B_expected_direction_match": model_selected == (expected == "RECALL"),
            "V21_expected_direction_match": baseline_policy_a == (expected == "RECALL"),
            "V21_exact_A_expected_direction_match": baseline_exact_a == (expected == "RECALL"),
            **pricing_outcomes(prices[JUNDA], idx),
        })
    return rows


def research_gate(metrics, junda):
    current = metrics["P1B_SELECTED"]["main"]
    baseline = metrics["V21_GRADE_A_FIRST"]["main"]
    trimmed = metrics["P1B_SELECTED"]["ex_P1B_top_three"]
    finite = all(current[k] is not None and baseline[k] is not None for k in ("tail_std_rate", "T5_mean", "T5_median"))
    criteria = {
        "selected_primary_tail_lower": finite and current["tail_std_rate"] < baseline["tail_std_rate"],
        "selected_T5_mean_positive_and_higher": finite and current["T5_mean"] > max(0, baseline["T5_mean"]),
        "selected_T5_median_positive_and_higher": finite and current["T5_median"] > max(0, baseline["T5_median"]),
        "ex_top_three_T5_mean_not_negative": trimmed["T5_mean"] is not None and trimmed["T5_mean"] >= 0,
        "junda_seven_exact_D_no_degradation": sum(r["P1B_expected_direction_match"] for r in junda)
            >= sum(r["V21_expected_direction_match"] for r in junda),
    }
    return {"criteria": criteria, "all_observed_checks_met": all(criteria.values()),
            "status": "RESEARCH_GATES_MET" if all(criteria.values()) else "NOT_PROMOTED", "NO_GO": True}
