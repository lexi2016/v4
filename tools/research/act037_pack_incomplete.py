#!/usr/bin/env python3
"""Package the terminal ACT-037 36-attempt ledger with the missing F01 E4A scores left null."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

import act037_e4 as e4


MISSING_ROWS = 4521
MISSING_SESSIONS = 10
EXPECTED_ARCHIVES = dict(zip(e4.ARMS, (11, 12, 12), strict=True))
RECOVERY_RUNNER_SHA = "bb3fcb47ce666e6358b26bdc797f9555709782b97d4013be11bd3ea79addb16b"
OUTPUTS = (
    "ACT037_E4_OOS_CORE.parquet",
    "ACT037_E4_METRICS.csv",
    "ACT037_E4_WEIGHT_SUMMARY.csv",
    "ACT037_RUN_AND_CLEANUP_RECEIPT.json",
)


def recover_scores(ctx, paths, states, binding_hash):
    assert set(states) == {(fold, arm) for fold in range(1, 13) for arm in e4.ARMS}
    records, weights, parts = [], [], []
    medians_by_fold, clip_counts_by_fold = {}, {}
    a, b, c = e4.ARMS
    for fold in range(1, 13):
        train, evaluate, x_train, x_eval, split = e4.feature_matrices(ctx, fold)
        keys = evaluate[e4.KEY].reset_index(drop=True).copy()
        for arm in e4.ARMS:
            state = states[fold, arm]
            started = state["FIT_STARTED"]
            assert started["input_binding_sha256"] == binding_hash
            assert started["feature_names"] == e4.FEATURES and started["missing_indicators"] == 0
            assert started["train_rows"] == len(train) and started["core_oos_rows"] == len(keys)
            assert started["fit_data_cutoff"] == int(split.fit_data_cutoff)
            assert started["first_test_D"] == int(split.test_first_D)
            weight_path, score_path = e4.model_paths(paths, fold, arm)
            if (fold, arm) == e4.FAILED_CANARY_KEY:
                assert len(keys) == MISSING_ROWS
                assert not weight_path.exists() and not score_path.exists()
                keys[e4.SCORES[arm]] = np.nan
                continue

            done = state["FIT_COMPLETED"]
            expected_id = hashlib.sha256(f"{binding_hash}|{fold}|{arm}".encode()).hexdigest()
            assert started["fit_id"] == done["fit_id"] == expected_id
            assert started["runner_sha256"] == done["runner_sha256"] == RECOVERY_RUNNER_SHA
            assert done["model_reload_prediction_max_abs_diff"] == 0.0
            assert done["prediction_calls"] == 2 and done["model_load_calls"] == 1
            assert Path(done["weight_file"]) == weight_path and Path(done["prediction_file"]) == score_path
            params = started["params"]
            if arm == a:
                assert params["objective"] == "huber" and params["alpha"] == 2.0
                assert started["target_clip"] == {"minimum": -10.0, "maximum": 10.0, "fit_only": True}
                target = train[e4.TARGET]
                counts = {"below_minus_10": int(target.lt(-10).sum()),
                          "above_plus_10": int(target.gt(10).sum())}
                assert counts == started["target_clip_counts"] == done["target_clip_counts"]
                clip_counts_by_fold[str(fold)] = counts
            else:
                assert started["target_clip"] is None
                assert started["target_clip_counts"] == done["target_clip_counts"] == {
                    "below_minus_10": 0, "above_plus_10": 0,
                }
            if arm == b:
                assert params["objective"] == "regression_l1"
            if arm == c:
                assert params["alpha"] == 10.0
                _, _, recomputed_medians = e4.huber_impute(x_train, x_eval)
                assert started["train_medians"] == recomputed_medians
                medians_by_fold[str(fold)] = recomputed_medians
            else:
                assert started["train_medians"] is None

            # Verify archive SHA and exact keyed score replay. This calls neither estimator method.
            score = e4.score_completed(paths, state, evaluate, fold, arm)
            keys[e4.SCORES[arm]] = score["score"].to_numpy()
            records.append({
                "fold": fold, "arm": arm, "fit_id": done["fit_id"],
                "weight_file": str(weight_path), "bytes": done["weight_bytes"],
                "sha256": done["weight_sha256"], "reload_max_abs_diff": 0.0,
                "reload_exact": True, "score_file": str(score_path), "score_sha256": done["prediction_sha256"],
                "train_rows": len(train), "core_oos_rows": len(evaluate),
            })

            coefficients, importance = done["huber_coefficients"], done["importance"]
            assert (coefficients is not None) == (arm == c)
            assert (importance is not None) == (arm != c)
            assert set(coefficients if arm == c else importance) == set(e4.FEATURES)
            for feature in e4.FEATURES:
                weights.append({
                    "row_type": "FOLD", "fold": fold, "arm": arm, "feature": feature,
                    "feature_count": len(e4.FEATURES), "missing_indicators": 0,
                    "dropped_features_leaked": False,
                    "huber_coefficient": coefficients[feature] if arm == c else None,
                    **({} if arm == c else importance[feature]),
                })
        parts.append(keys)
    assert Counter(row["arm"] for row in records) == EXPECTED_ARCHIVES
    assert set(paths["weights"].glob("ACT037_F*.joblib")) == {Path(row["weight_file"]) for row in records}
    return (pd.concat(parts, ignore_index=True), records, pd.DataFrame(weights),
            medians_by_fold, clip_counts_by_fold)


def summarize_weights(by_fold: pd.DataFrame) -> pd.DataFrame:
    measures = ["huber_coefficient", "gain", "gain_share", "split", "split_share"]
    group = by_fold.groupby(["arm", "feature"], sort=False)
    means = group[measures].mean().reset_index()
    means["folds_used"] = group["fold"].nunique().to_numpy()
    def same_sign_folds(values: pd.Series) -> int | None:
        coefficients = values.dropna()
        if coefficients.empty:
            return None
        return int(np.sign(coefficients).eq(np.sign(coefficients.mean())).sum())

    means["coefficient_same_sign_folds"] = group["huber_coefficient"].agg(same_sign_folds).to_numpy()
    means = means.assign(
        fold=0, feature_count=len(e4.FEATURES), missing_indicators=0, dropped_features_leaked=False,
        row_type=means["folds_used"].map({11: "MEAN_11_FOLDS", 12: "MEAN_12_FOLDS"}),
    )
    by_fold = by_fold.assign(folds_used=1)
    result = pd.concat([by_fold, means], ignore_index=True)
    assert len(result) == 950 and set(result["feature"]) == set(e4.FEATURES)
    return result


def assemble_core(ctx, scores: pd.DataFrame) -> pd.DataFrame:
    original = ctx["core_oos"]
    baseline_columns = list(e4.BASELINE_SCORES.values())
    final = original.merge(ctx["baseline"][e4.KEY + baseline_columns], on=e4.KEY,
                           how="left", validate="one_to_one")
    final = final.merge(scores, on=e4.KEY, how="left", validate="one_to_one")
    assert len(final) == e4.EXPECTED_CORE_OOS == len(scores)
    assert final["D"].nunique() == e4.EXPECTED_SESSIONS
    assert final["core_mask"].eq(True).all() and final["relevance"].notna().all()
    assert final["is_low_absorb"].sum() == e4.EXPECTED_LOW_ABSORB
    missing = final[e4.SCORES[e4.ARMS[0]]].isna()
    assert missing.equals(final["fold"].eq(1)) and missing.sum() == MISSING_ROWS
    assert final.loc[missing, "D"].nunique() == MISSING_SESSIONS
    complete_scores = [e4.SCORES[arm] for arm in e4.ARMS[1:]] + baseline_columns
    assert np.isfinite(final[complete_scores].to_numpy(dtype="float64")).all()
    columns = [
        *e4.KEY, "fold", "core_mask", "relevance", *e4.SCORES.values(), *baseline_columns,
        "is_low_absorb", e4.TARGET, e4.CLEAN, e4.TAIL, "regime",
        "days_since_20d_vol_peak", "amount_ratio_20",
    ]
    return final[columns].sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)


def summarize_metrics(ctx, final: pd.DataFrame):
    direct, paired = e4.all_metrics(ctx, final)
    first_arm = e4.ARMS[0]
    pool_counts = {
        "CORE": final.groupby("D").size(),
        "CORE_LOW_ABSORB": final.loc[final["is_low_absorb"]].groupby("D").size(),
    }
    for frame in (direct, paired):
        frame["planned_sessions"] = frame["sessions"]
        is_partial_arm = frame["arm"].eq(first_arm)
        frame["model_coverage"] = np.where(is_partial_arm, "F01_E4A_MISSING", "FULL")
        # Top-10 support counts exactly the scored or paired finite days, independent of RankIC ties.
        observed = frame["t2_top10_defined_days"].fillna(frame["t2_top10"].notna().astype(int))
        frame["sessions"] = observed.astype(int)
        frame.loc[is_partial_arm & frame["sessions"].lt(frame["planned_sessions"]), "candidate_count"] = (
            frame["candidate_count"] * frame["planned_sessions"].div(frame["sessions"].replace(0, np.nan))
        )
        frame.loc[is_partial_arm & frame["row_type"].eq("ALL_120D"), "row_type"] = "ALL_OBSERVED_110D"
        frame.loc[is_partial_arm & frame["row_type"].eq("PAIRED_ALL_120D"), "row_type"] = "PAIRED_ALL_OBSERVED_110D"
        daily = frame["row_type"].isin(("DAILY", "PAIRED_DAILY"))
        for scope, counts in pool_counts.items():
            mask = daily & frame["eval_scope"].eq(scope)
            frame.loc[mask, "pool_candidate_count"] = frame.loc[mask, "D"].map(counts)

    # Frozen paired means already skip null days. Recalculate denominator from finite Top-10 pairs.
    pair_days = paired.loc[paired["row_type"].eq("PAIRED_DAILY") & paired["t2_top10"].notna()]
    pair_columns = ["eval_scope", "arm", "comparison_baseline"]
    for level, dimensions in (
        ("PAIRED_ALL_120D", []), ("PAIRED_ALL_OBSERVED_110D", []),
        ("PAIRED_REGIME", ["regime"]), ("PAIRED_FOLD", ["fold"]),
    ):
        grouped = pair_days.groupby(pair_columns + dimensions + (
            [] if "fold" in dimensions else ["fold"]
        ))["t2_top10"].mean().reset_index()
        if "fold" not in dimensions:
            folded = (
                grouped.assign(wins=grouped["t2_top10"].gt(0).astype(int))
                .groupby(pair_columns + dimensions)["wins"].agg(["sum", "count"])
            )
        else:
            folded = grouped.set_index(pair_columns + dimensions)["t2_top10"].to_frame()
            folded = folded.assign(sum=folded["t2_top10"].gt(0).astype(int), count=1)
        for index, row in paired.loc[paired["row_type"].eq(level)].iterrows():
            key = tuple(row[column] for column in pair_columns + dimensions)
            if key in folded.index:
                wins, denominator = folded.loc[key, ["sum", "count"]].to_list()
            else:
                wins, denominator = np.nan, 0
            paired.loc[index, ["top10_win_folds", "fold_denominator"]] = wins, denominator

    primary = paired["comparison_baseline"].eq("E2B")
    observed = paired.loc[primary & paired["row_type"].eq("PAIRED_ALL_OBSERVED_110D")]
    assert len(observed) == 2 and observed["fold_denominator"].eq(11).all()
    assert observed["sessions"].eq(110).all()
    assert paired.loc[primary & paired["row_type"].eq("PAIRED_ALL_120D"), "fold_denominator"].eq(12).all()
    threshold = ctx["outer"]["policy"]["reference_not_admission"]
    gates = {}
    for arm in e4.ARMS:
        if arm == first_arm:
            gates[arm] = {"status": "CANNOT_CONFIRM", "scored_sessions": 110, "missing_fold": 1}
            continue
        own = direct.loc[direct["eval_scope"].eq("CORE") & direct["row_type"].eq("ALL_120D")
                         & direct["arm"].eq(arm)].iloc[0]
        compare = paired.loc[paired["eval_scope"].eq("CORE") & paired["row_type"].eq("PAIRED_ALL_120D")
                             & paired["arm"].eq(arm) & primary].iloc[0]
        assert own["sessions"] == 120 and compare["fold_denominator"] == 12
        checks = {
            "rank_ic": bool(own["rank_ic"] > threshold["rank_ic_gt"]),
            "top10_excess": bool(own["t2_top10"] >= threshold["top10_pp_ge"]),
            "pure_tail": bool(own["pure_tail_trap_top10"] <= threshold["tail_le"]),
            "wins_vs_e2b": bool(compare["top10_win_folds"] >= threshold["wins_vs_e2b_ge"]),
        }
        gates[arm] = {"status": "PASS_REFERENCE" if all(checks.values()) else "NOT_MET",
                      "threshold_checks": checks, "scored_sessions": 120}
    return pd.concat([direct, paired], ignore_index=True), gates


def pack(batch_root: Path, source_root: Path) -> dict:
    assert e4.sha256(Path(e4.__file__)) == RECOVERY_RUNNER_SHA
    paths = e4.runtime_paths(batch_root, source_root)
    ledger = paths["execution"] / "ACT037_EVENTS.jsonl"
    destinations = [paths["delivery"] / name for name in OUTPUTS]
    with (paths["execution"] / "RUN.lock").open("r") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not any(path.exists() for path in destinations), "existing ACT-037 delivery"
        ledger_before = e4.identity(ledger)
        events = e4.read_events(ledger)
        assert Counter(event["state"] for event in events) == {
            "FIT_STARTED": 36, "FIT_COMPLETED": 35, "FIT_FAILED": 1,
        }
        states = e4.event_states(events, e4.FAILED_CANARY_FIT_ID)
        ctx = e4.load_context(paths)
        binding = json.loads((paths["execution"] / "ACT037_INPUT_BINDING.json").read_text())
        binding_hash = hashlib.sha256(json.dumps(
            ctx["binding"], ensure_ascii=False, sort_keys=True, allow_nan=False,
        ).encode()).hexdigest()
        assert binding == {"binding": ctx["binding"], "binding_sha256": binding_hash}
        scores, archives, by_fold, medians, clip_counts = recover_scores(ctx, paths, states, binding_hash)
        weights = summarize_weights(by_fold)
        final = assemble_core(ctx, scores)
        metrics, gates = summarize_metrics(ctx, final)
        failed = states[e4.FAILED_CANARY_KEY]
        receipt = {
            "action_id": "ACT-037", "status": "INCOMPLETE_MISSING_F01_E4A",
            "fit_limit": 36,
            "actual_fit": {"total": 36, **dict.fromkeys(e4.ARMS, 12)},
            "fit_completed": {"total": 35, **EXPECTED_ARCHIVES}, "fit_failed": 1,
            "failed_fit": failed, "baseline_refit": 0, "additional_fit": 0, "simulation": 0,
            "research_only": True, "strict_pit": 0, "train_admitted": 0, "no_go_blocked": True,
            "production_allowed": False, "orders_sent": False, "buy_gate_updated": False,
            "knowledge_base_training_complete": False,
            "pack_operations": {"fit": 0, "prediction": 0, "simulation": 0},
            "prediction": "35 scored and archived fold models + 1 failed attempt without persisted score",
            "input_binding_sha256": binding_hash, "input_binding": ctx["binding"],
            "current_pointer_observed": ctx["current_pointer_observation"], "runtime": ctx["runtime"],
            "folds": ctx["by_fold"], "weights": archives, "weight_files_sha_verified": len(archives),
            "archive_reload_max_abs_diff_from_ledger": max(item["reload_max_abs_diff"] for item in archives),
            "all_35_weight_sha_verified": True, "all_35_reload_max_abs_diff_zero": True,
            "core_oos_keys": len(final), "sessions": final["D"].nunique(),
            "scored_sessions": dict(zip(e4.ARMS, (110, 120, 120), strict=True)),
            "missing_e4a_keys": MISSING_ROWS,
            "missing_e4a_dates": sorted(final.loc[final["fold"].eq(1), "D"].unique().tolist()),
            "regimes": final.groupby("regime")["D"].nunique().to_dict(),
            "low_absorb": {
                "keys": int(final["is_low_absorb"].sum()),
                "daily_mean": float(final["is_low_absorb"].sum() / e4.EXPECTED_SESSIONS),
                "daily_min": int(ctx["low_counts"].min()), "daily_max": int(ctx["low_counts"].max()),
            },
            "E4A_training_target_clip_counts_by_fold": clip_counts,
            "E4C_training_medians_by_fold": medians,
            "ACT030_E2B_ACT034_E3L2_core_rank_ic_mean": ctx["baseline_rank_ic_mean"],
            "feature_count": len(e4.FEATURES), "feature_names": e4.FEATURES,
            "dropped_features": sorted(e4.DROPPED),
            "constant_columns_excluded": ctx["const_evidence"], "missing_indicators": 0,
            "reference_gate_only": gates, "metrics_rows": len(metrics), "weight_summary_rows": len(weights),
            "ledger": ledger_before, "flags": ctx["outer"]["flags"],
            "ACT037_scope_sha256": e4.sha256(paths["scope"]),
            "runner_sha256": RECOVERY_RUNNER_SHA, "pack_runner_sha256": e4.sha256(Path(__file__)),
            "time_beijing": datetime.now().astimezone().isoformat(),
            "cleanup": {"status": "RUNTIME_CLEANUP_PENDING", "removed_bytes": 0},
        }
        paths["delivery"].mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".act037-incomplete-pack-", dir=batch_root) as staging:
            staged = [Path(staging) / name for name in OUTPUTS]
            e4.atomic_parquet(final, staged[0])
            e4.atomic_csv(metrics, staged[1])
            e4.atomic_csv(weights, staged[2])
            receipt["delivery_files"] = {
                target.name: {**e4.identity(src), "path": str(target)}
                for target, src in zip(destinations[:-1], staged[:-1], strict=True)
            }
            e4.atomic_json(staged[3], receipt)
            assert e4.identity(ledger) == ledger_before
            for source, target in zip(staged, destinations, strict=True):
                os.replace(source, target)
    return {key: receipt[key] for key in (
        "status", "actual_fit", "fit_completed", "fit_failed", "core_oos_keys",
        "scored_sessions", "missing_e4a_keys", "reference_gate_only", "delivery_files",
    )}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(pack(args.batch_root.resolve(), args.source_root.resolve()), ensure_ascii=False))
