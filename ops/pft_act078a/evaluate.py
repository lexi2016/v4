"""Frozen ACT-078A evaluation, audit ledger and renderer inputs."""

from time import perf_counter

import joblib
import numpy as np
import pandas as pd

import data as source
import models as model
from task import GOVERNANCE, RUN_MODULES, claim, code_identity, elapsed, file_identity, profile, read_json, write_json

JUNDA = "002865.SZ"
NAMED = {
    "#04": ("2021-03-22", "DOWNGRADE"), "#06": ("2021-02-23", "DOWNGRADE"),
    "#31": ("2025-02-26", "DOWNGRADE"), "#15": ("2024-09-24", "RECALL"),
    "#32": ("2023-06-02", "RECALL"), "#34": ("2022-11-01", "RECALL"),
    "#39": ("2020-11-24", "RECALL"),
}
CHART_METRICS = (*source.BASE_AXIS, "w_slope_5d", "w_slope_10d", "y_slope_10d",
                 "y_slope_20d", "low60_gain", "breadth_41_above_w")
CSV_METRICS = ("t2_win_rate", "t2_mean", "t5_mean", "t10_mean", "t5_median", "t10_median", "mae5_mean", "tail_rate")
V21_TIER_RANK = {model.V21_A: 3, model.V21_POSITIVE[1]: 2, model.V21_POSITIVE[2]: 2, "C级_高位或弱市警示": 1}
V22_TIER_RANK = {"A": 3, "B": 2, "C": 1}


def json_scalar(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def score_status(frame):
    independent = frame.trigger_role.eq("FIRST")
    valid_scores = frame.candidate_tier.ne("UNSCORED")
    frame["matched_scored_first"] = independent & valid_scores
    frame["baseline_A"] = independent & frame.visual_tier.eq(model.V21_A)
    frame["candidate_A"] = independent & frame.candidate_tier.eq("A")
    maturity_fields = {2: "maturity_2_D", 5: "maturity_5_D", 10: "maturity_10_D"}
    cutoffs = frame.period.map({"TRAIN": source.VAL_START, "VAL": source.OOT_START, "OOT": "2026-11-27"})
    for horizon, column in maturity_fields.items():
        frame[f"mature_{horizon}"] = frame[column].lt(cutoffs).fillna(False)
    frame["pair_status"] = np.select(
        [
            frame.period.ne(frame.episode_period),
            frame.trigger_role.eq("CONFIRM"),
            frame.trigger_role.eq("REPEAT"),
            ~valid_scores,
            frame.baseline_A & frame.candidate_A,
            frame.baseline_A,
            frame.candidate_A,
        ],
        [
            "DROPPED_GROUP_FIRST_IN_EARLIER_PERIOD", "DROPPED_CONFIRM_DUPLICATE",
            "DROPPED_REPEAT_DUPLICATE", "DROPPED_NO_TRAIN_OOF_WARMUP",
            "BOTH_A", "BASELINE_A_ONLY", "CANDIDATE_A_ONLY",
        ],
        default="NEITHER_A",
    )
    frame["outcome_status"] = np.select(
        [~frame.mature_2, ~frame.mature_5, ~frame.mature_10],
        ["T2_T5_T10_IMMATURE", "T5_T10_IMMATURE", "T10_IMMATURE"], default="T10_MATURE",
    )
    return frame


def metric_stats(selected, population):
    t2 = selected.loc[selected.mature_2, "t2_net"].dropna()
    t5 = selected.loc[selected.mature_5, "t5_net"].dropna()
    t10 = selected.loc[selected.mature_10, "t10_net"].dropna()
    mae = selected.loc[selected.mature_5, "mae5_net"].dropna()
    tail = selected.loc[selected.mature_5, "tail_std"].dropna()
    results = (
        t2.gt(0).mean(), t2.mean(), t5.mean(), t10.mean(), t5.median(),
        t10.median(), mae.mean(), tail.mean(),
    )
    return {
        **{k: json_scalar(v) for k,v in zip(CSV_METRICS, results)},
        "independent_episode_n": int(selected.structure_episode_id.nunique()),
        "repeat_triggers_in_selected_episodes_n": int(
            (population.trigger_role.ne("FIRST") & population.structure_episode_id.isin(selected.structure_episode_id)).sum()
        ),
        "unique_stocks": int(selected.security_id.nunique()),
        "t2_mature_n": len(t2), "t5_mature_n": len(t5), "t10_mature_n": len(t10),
        "mae5_mature_n": len(mae), "tail_mature_n": len(tail),
    }


def top_contributors(selected):
    contributors = (
        selected.loc[selected.mature_5].groupby("security_id", sort=True)
        .t5_net.agg(trades="count", sum_equal_notional_t5_net="sum").reset_index()
        .sort_values(["sum_equal_notional_t5_net", "security_id"], ascending=[False, True])
        .head(3)
    )
    return contributors.to_dict(orient="records")


def calculate_metrics(audit):
    slices = {
        "ALL_41": audit, "TRAIN": audit[audit.period.eq("TRAIN")],
        "VAL_2024": audit[audit.period.eq("VAL")], "OOT_2025_2026": audit[audit.period.eq("OOT")],
        "JUNDA_ALL": audit[audit.security_id.eq(JUNDA)],
        "JUNDA_VAL": audit[audit.security_id.eq(JUNDA) & audit.period.eq("VAL")],
        "JUNDA_OOT": audit[audit.security_id.eq(JUNDA) & audit.period.eq("OOT")],
    }
    output, sensitivity = [], {}
    for name, population in slices.items():
        shared = population[population.matched_scored_first]
        independent = population[population.trigger_role.eq("FIRST")]
        baseline = shared[shared.baseline_A]
        candidate = shared[shared.candidate_A]
        both = shared[shared.baseline_A & shared.candidate_A]
        families = {
            "V21_A_SAME_D_UNIVERSE": baseline, "V22_A_SAME_D_UNIVERSE": candidate,
            "BOTH_A_INTERSECTION": both, "V21_A_ALL_FIRST_REFERENCE": independent[independent.baseline_A],
        }
        for policy, group in families.items():
            output.append({"slice": name, "policy": policy, "common_scored_first_n": len(shared),
                           "any_first_n": len(independent), "duplicate_trigger_total_n": len(population)-len(independent),
                           **metric_stats(group, population)})
        top3 = top_contributors(candidate)
        common_excluded = [x["security_id"] for x in top3]
        baseline_only_top3 = [x["security_id"] for x in top_contributors(baseline)]
        excluded_candidate, excluded_baseline = (
            group[~group.security_id.isin(common_excluded)] for group in (candidate, baseline)
        )
        sensitivity[name] = {
            "common_exclusion_basis": "largest equal-notional V2.2 A T+5 P&L contributions",
            "common_excluded": common_excluded, "top3_v22": top3,
            "baseline_own_top3_reference": baseline_only_top3,
            "v22_after_common_exclusion": metric_stats(excluded_candidate, population),
            "v21_after_common_exclusion": metric_stats(excluded_baseline, population),
        }
    return output, sensitivity


def named_cases(audit):
    result = []
    for case, (date, intent) in NAMED.items():
        match = audit[audit.security_id.eq(JUNDA) & audit.D.eq(date)]
        source.require(len(match) == 1, f"Missing exact case {case}")
        exact = match.iloc[0]
        anchor = audit[audit.structure_episode_id.eq(exact.structure_episode_id) & audit.trigger_role.eq("FIRST")]
        source.require(len(anchor) == 1, f"Missing independent case anchor {case}")
        anchor = anchor.iloc[0]
        exact_rank = V22_TIER_RANK.get(exact.candidate_tier)
        prior_rank = V21_TIER_RANK[exact.visual_tier]
        if intent == "DOWNGRADE":
            passed = exact_rank is not None and exact_rank < prior_rank
            status = "EXACT_D_SCORE_DOWNGRADED" if passed else "EXACT_D_SCORE_NOT_DOWNGRADED"
        else:
            retained = exact.candidate_tier in model.V22_POSITIVE and anchor.candidate_tier in model.V22_POSITIVE
            passed = bool(retained)
            status = ("INDEPENDENT_FIRST_RETAINED" if exact.trigger_role == "FIRST" else "RETAINED_AS_CONFIRMATION") if retained else "RECALL_NOT_ESTABLISHED"
        result.append({
            "case": case, "D": date, "intent": intent, "passed": bool(passed), "verdict": status,
            "security_id": JUNDA, "structure_episode_id": exact.structure_episode_id,
            "trigger_role": exact.trigger_role, "pair_status": exact.pair_status, "period": exact.period,
            "baseline_tier_exact_D": exact.visual_tier, "candidate_tier_exact_D": exact.candidate_tier,
            "candidate_score_exact_D": json_scalar(exact.score), "score_source_exact_D": json_scalar(exact.score_source),
            "first_D": anchor.D, "baseline_tier_first_D": anchor.visual_tier,
            "candidate_tier_first_D": anchor.candidate_tier, "candidate_score_first_D": json_scalar(anchor.score),
            "candidate_score_source_first_D": json_scalar(anchor.score_source),
            **{key: json_scalar(exact[key]) for key in (*CHART_METRICS, *source.OUTCOMES)},
        })
    return result


def promotion_result(metrics, sensitivity, cases):
    oot = {record["policy"]: record for record in metrics if record["slice"] == "OOT_2025_2026"}
    baseline, candidate = oot["V21_A_SAME_D_UNIVERSE"], oot["V22_A_SAME_D_UNIVERSE"]
    after = sensitivity["OOT_2025_2026"]["v22_after_common_exclusion"]["t5_mean"]
    has_comp = baseline["tail_mature_n"] > 0 and candidate["tail_mature_n"] > 0
    verdict = {r["case"]: r["passed"] for r in cases}
    gates = {
        "oot_tail_rate_same_or_lower": has_comp and candidate["tail_rate"] <= baseline["tail_rate"],
        "oot_t5_mean_improved": has_comp and candidate["t5_mean"] > baseline["t5_mean"],
        "oot_t5_median_improved": has_comp and candidate["t5_median"] > baseline["t5_median"],
        "oot_excluding_common_top3_t5_mean_positive": after is not None and after > 0,
        "junda_overheat_04_06_downgraded": verdict["#04"] and verdict["#06"],
        "junda_31_downgraded": verdict["#31"],
        "junda_15_32_34_39_recall_supported": all(verdict[k] for k in ("#15", "#32", "#34", "#39")),
    }
    return {"all_quantitative_and_case_gates": all(gates.values()), "gates": gates,
            "status": "RESEARCH_GATES_PASS_GEMINI_PENDING" if all(gates.values()) else "NOT_PROMOTED",
            "production_safety_lock": "NO_GO"}


def chart_inputs(audit, chains, period="OOT"):
    a = audit[audit.period.eq(period) & audit.candidate_A]
    ordered = a.assign(junda=a.security_id.eq(JUNDA)).sort_values(
        ["junda", "score", "D", "security_id"], ascending=[False, False, True, True]
    )
    chosen = ordered.head(36)
    measured = {key: source.price_features(chains[key]) for key in chosen.security_id.unique()}
    blind, post = [], []
    for row in chosen.itertuples(index=False):
        frame = measured[row.security_id]
        pos = frame.index.get_loc(row.D)
        info = {
            "chart_id": f"{row.security_id}@{row.D}", "security_id": row.security_id,
            "name": row.name, "D": row.D, "candidate_tier": row.candidate_tier, "score": row.score,
            "metrics_d": {key: json_scalar(getattr(row, key)) for key in CHART_METRICS},
        }
        for left, right, collection in ((-20, 0, blind), (-10, 10, post)):
            clipped = frame.iloc[max(0,pos+left):pos+right+1][["open", "high", "low", "close", "volume", "W", "Y"]]
            bars = [{"D": day, "offset": position, **{field: json_scalar(v) for field,v in values.items()}}
                    for position, (day, values) in enumerate(clipped.iterrows(), start=max(-pos,left))]
            record = {**info, "bars": bars}
            if collection is post:
                record["outcomes"] = {key: json_scalar(getattr(row,key)) for key in source.OUTCOMES}
            collection.append(record)
    source.require(len(blind)==len(post) <=36, "Chart count lock")
    source.require(all(all(bar["offset"] <= 0 and bar["D"] <= row["D"] for bar in row["bars"]) for row in blind), "Blind chart lead")
    source.require(all(len(row["bars"]) == 21 for row in blind), "Blind chart warmup missing")
    skipped = int(ordered.security_id.eq(JUNDA).sum()-chosen.security_id.eq(JUNDA).sum())
    return blind, post, {"chart_n": len(chosen), "eligible_top_tier_episode_n": len(ordered),
                         "eligible_junda_n": int(ordered.security_id.eq(JUNDA).sum()), "junda_skipped_due_to_limit_n": skipped}


def verify_lock(root):
    run, evidence = root / "run", root / "evidence"
    lock_path = run / "FROZEN_RANK_LOCK.json"
    lock = read_json(lock_path)
    source.require(lock["status"] == "TRAIN_AND_VAL_LOCKED" and lock["locked_before_oot"], "No frozen rank lock")
    source.require(lock["code_identity"] == code_identity(RUN_MODULES), "Executable drift after lock")
    source.require(lock["fit_completed"] == lock["fit_started"] == model.FIT_CAP and lock["fit_after_lock"] == 0, "FIT budget")
    source.require(lock["tuning"] == 0 and lock["governance"] == GOVERNANCE and lock["feature_order"] == list(source.FEATURES),
                   "Governance, ordering, or tuning drift")
    files = [run / "fit_journal.jsonl", run / "pre_oot_scores.parquet", evidence / "prep_receipt.json"]
    identities = [lock["fit_journal"], lock["pre_oot_scores"], lock["prep_receipt"]]
    weights = {}
    for family, receipt in lock["refit_weights"].items():
        path = run / "weights" / receipt["name"]
        weights[family] = path
        files.append(path)
        identities.append(receipt)
    source.require(set(weights) == set(model.FAMILY_NAMES), "Four-model identity")
    source.require([file_identity(p) for p in files] == identities, "Frozen fit file changed")
    return lock, lock_path, weights, files


def oot(root):
    started = perf_counter()
    run = root / "run"
    stages = {}
    mark = perf_counter()
    lock, lock_path, weight_paths, lock_files = verify_lock(root)
    prep_receipt = read_json(root / "evidence" / "prep_receipt.json")
    sources = root / "sources"
    source_paths = [sources / key for key in prep_receipt["sources"]]
    for path in source_paths:
        source.require(source.sha_file(path) == prep_receipt["sources"][path.name]["sha256"], f"Frozen archive drift {path.name}")
    weights = {k: joblib.load(path) for k, path in weight_paths.items()}
    stages["freeze_and_source_integrity"] = elapsed(mark)

    # A permanent exclusive claim is created before parsing any OOT outcomes.
    # The checkpoint supports reporting any subsequent partial failure.
    claim(run / "OOT_OPEN_CLAIM.json", "SINGLE_OOT_OPEN")
    open_marker = file_identity(run / "OOT_OPEN_CLAIM.json")
    mark = perf_counter()
    chains, _ = source.raw_chains(sources, source.RAW_ASOF, prep_receipt["sources"])
    cohort, detailed = source.read_frozen(sources, open_outcomes=True)
    breadth = source.breadth_frame(chains)
    features = source.feature_join(cohort, chains, breadth)
    all_labeled = source.outcome_join(features, chains)
    parity = source.frozen_parity(all_labeled, detailed, source.FROZEN_END)
    late_breadth = source.source_breadth_parity(sources, breadth, source.RAW_ASOF)
    stages["single_oot_load_and_frozen_pair_parity"] = elapsed(mark)

    mark = perf_counter()
    pre_slice = all_labeled[all_labeled.D.lt(source.OOT_START)]
    pre = pd.read_parquet(run / "pre_oot_scores.parquet")
    pre_audit = pre_slice.merge(pre, on=["security_id", "D"], how="left", validate="one_to_one")
    oot_slice = all_labeled[all_labeled.D.ge(source.OOT_START)]
    oot_features = oot_slice[oot_slice.episode_period.eq("OOT")]
    predictions = model.predictions(weights, oot_features)
    oot_audit = model.tiered(oot_slice, predictions, lock)
    oot_audit["score_source"] = pd.NA
    oot_audit.loc[oot_features.index, "score_source"] = "OOT_FROZEN_TRAIN"
    audit = score_status(pd.concat([pre_audit, oot_audit], ignore_index=True).sort_values(["security_id","D"]))
    source.require(len(audit) == 3856 and audit.matched_scored_first.sum() > 0, "Complete pair ledger")
    source.require(audit.loc[audit.period.eq("OOT") & audit.trigger_role.eq("FIRST"), "matched_scored_first"].all(),
                   "Missing frozen OOT scores")
    stages["fixed_scores_match_groups_and_apply_maturity"] = elapsed(mark)

    mark = perf_counter()
    metrics, sensitivity = calculate_metrics(audit)
    cases = named_cases(audit)
    verdict = promotion_result(metrics, sensitivity, cases)
    blind, post, chart_status = chart_inputs(audit, chains)
    available = []
    day_set = sorted({day for chain in chains.values() for day in chain.index if day > source.FROZEN_END})
    for day in day_set:
        available.append({"D": day, "raw_41_stocks_present": sum(day in chain.index for k,chain in chains.items() if k != "000001.SH"),
                          "baseline_v21_keys": 0, "pair_status": "UNPAIRED_FROZEN_BASELINE_UNAVAILABLE"})
    artifacts = {
        "paired_trigger_ledger.csv": audit,
        "paired_metrics.csv": pd.DataFrame(metrics),
        "junda_cases.csv": pd.DataFrame(cases),
        "unpaired_source_dates.csv": pd.DataFrame(available),
    }
    for name, frame in artifacts.items():
        with (run / name).open("x", encoding="utf-8", newline="") as file:
            frame.to_csv(file, index=False)
    for name, records in (("chart_d_only.json", blind), ("chart_post.json", post), ("top3_sensitivity.json", sensitivity)):
        write_json(run / name, records)
    stages["metrics_named_cases_and_chart_contract"] = elapsed(mark)
    products = [run / name for name in [*artifacts, "chart_d_only.json", "chart_post.json", "top3_sensitivity.json"]]
    last = run / "OOT_EVALUATION_RECEIPT.json"
    receipt = {
        "status": "SINGLE_OOT_PASS_MECHANICS", "promotion": verdict, "governance": GOVERNANCE,
        "fit_started": model.FIT_CAP, "fit_completed": model.FIT_CAP, "fit_after_lock": 0, "oot_open_count": 1,
        "lock_sha256": source.sha_file(lock_path), "open_marker": open_marker,
        "record_counts_by_pair_status": {k: int(v) for k,v in audit.pair_status.value_counts().items()},
        "maturity_by_period_at_stage_cut": {k: {f"mature_{h}": int(g[f"mature_{h}"].sum()) for h in (2,5,10)}
                                             for k,g in audit.groupby("period")},
        "paired_rows": len(audit), "all_frozen_label_parity": parity, "all_breadth_source_parity": late_breadth,
        "paired_D_last": source.FROZEN_END, "raw_asof": source.RAW_ASOF, "unpaired_days": available,
        "chart": chart_status, "products": [file_identity(p) for p in products],
        "resource": profile(started, "oot", stages, [lock_path, *lock_files, *source_paths], products),
    }
    write_json(last, receipt)
    return {k: receipt[k] for k in ("status","promotion","record_counts_by_pair_status","paired_rows","chart")}
