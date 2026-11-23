#!/usr/bin/env python3
"""Backfill only the authorized ACT-037 E4A F01 fold, then pack stored OOS scores."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

import act037_e4 as e4


ACTION = "ACT-037-F01"
FOLD, ARM = e4.FAILED_CANARY_KEY
OLD_RUNNER_SHA = "bb3fcb47ce666e6358b26bdc797f9555709782b97d4013be11bd3ea79addb16b"
OLD_A_WEIGHTS = {e4.ARMS[0]: 11, e4.ARMS[1]: 12, e4.ARMS[2]: 12}
EXPECTED_CLIP = {"minimum": -10.0, "maximum": 10.0, "fit_only": True}
EXPECTED_CLIP_COUNTS = {"below_minus_10": 155, "above_plus_10": 730}
CORE_KEYS = 40578
F01_KEYS = 4521
OUTPUTS = (
    "ACT037_E4_OOS_CORE_120D.parquet",
    "ACT037_E4_METRICS_120D.csv",
    "ACT037_F01_RECEIPT.json",
)
A_SCORE = e4.SCORES[ARM]


def digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, allow_nan=False,
    ).encode()).hexdigest()


def verify_file(path: Path, expected_hash: str) -> dict:
    observed = e4.identity(path)
    assert observed["sha256"] == expected_hash, f"frozen SHA-256 mismatch: {path}"
    return observed


def paths_for(batch_root: Path, prior_root: Path, source_root: Path):
    assert batch_root.parent == prior_root.parent == source_root and batch_root != prior_root
    new = e4.runtime_paths(batch_root, source_root)
    prior = e4.runtime_paths(prior_root, source_root)
    new["execution"] = batch_root / "work" / "ACT037_F01_EXECUTION"
    return new, prior


def load_frozen(batch_root: Path, prior_root: Path, source_root: Path):
    new, prior = paths_for(batch_root, prior_root, source_root)
    scope_path = new["batch"] / "work" / "ACT037_F01_SCOPE.json"
    scope = json.loads(scope_path.read_text())
    assert scope["action_id"] == ACTION and scope["fit_limit"] == 1
    assert (scope["fold"], scope["arm"]) == (FOLD, ARM)
    assert (scope["cumulative_fit_before"], scope["cumulative_fit_after"]) == (218, 219)
    assert scope["frozen_runner_sha256"] == OLD_RUNNER_SHA == e4.sha256(Path(e4.__file__))

    prior_receipt = prior["delivery"] / "ACT037_RUN_AND_CLEANUP_RECEIPT.json"
    prior_oos = prior["delivery"] / "ACT037_E4_OOS_CORE.parquet"
    prior_ledger = prior["execution"] / "ACT037_EVENTS.jsonl"
    receipt_id = verify_file(prior_receipt, scope["old_receipt_sha256"])
    oos_id = verify_file(prior_oos, scope["old_oos_sha256"])
    ledger_id = verify_file(prior_ledger, scope["old_event_ledger_sha256"])
    receipt = json.loads(prior_receipt.read_text())
    assert receipt["action_id"] == "ACT-037" and receipt["status"] == "INCOMPLETE_MISSING_F01_E4A"
    assert receipt["fit_limit"] == 36 and receipt["fit_failed"] == 1
    assert receipt["actual_fit"] == {"total": 36, **dict.fromkeys(e4.ARMS, 12)}
    assert receipt["fit_completed"] == {"total": 35, **OLD_A_WEIGHTS}
    assert receipt["all_35_weight_sha_verified"] and receipt["all_35_reload_max_abs_diff_zero"]
    assert receipt["archive_reload_max_abs_diff_from_ledger"] == 0.0
    assert receipt["baseline_refit"] == receipt["simulation"] == 0
    assert receipt["runner_sha256"] == OLD_RUNNER_SHA
    assert receipt["ledger"] == ledger_id and receipt["delivery_files"][prior_oos.name] == oos_id
    assert receipt["missing_e4a_keys"] == F01_KEYS
    assert receipt["flags"] == scope["flags"]
    assert e4.sha256(prior["scope"]) == receipt["ACT037_scope_sha256"]

    events = e4.read_events(prior_ledger)
    assert Counter(event["state"] for event in events) == {
        "FIT_STARTED": 36, "FIT_COMPLETED": 35, "FIT_FAILED": 1,
    }
    states = e4.event_states(events, e4.FAILED_CANARY_FIT_ID)
    assert states[FOLD, ARM] == receipt["failed_fit"]

    # Source and historic cohort are read through the original reviewed reader;
    # only the ephemeral LightGBM vendor may come from the new batch.
    ctx = e4.load_context({**new, "scope": prior["scope"]})
    binding = json.loads((prior["execution"] / "ACT037_INPUT_BINDING.json").read_text())
    prior_binding_hash = digest(ctx["binding"])
    assert binding == {"binding": ctx["binding"], "binding_sha256": prior_binding_hash}
    assert ctx["binding"] == receipt["input_binding"] and prior_binding_hash == receipt["input_binding_sha256"]
    assert ctx["outer"]["flags"] == scope["flags"]
    new_binding = {
        "action_id": ACTION, "fit_limit": 1, "fold": FOLD, "arm": ARM,
        "source_binding_sha256": prior_binding_hash, "scope_sha256": e4.sha256(scope_path),
        "prior_receipt_sha256": receipt_id["sha256"], "prior_oos_sha256": oos_id["sha256"],
        "prior_event_ledger_sha256": ledger_id["sha256"],
        "fit_runner_sha256": OLD_RUNNER_SHA, "wrapper_sha256": e4.sha256(Path(__file__)),
    }
    return new, prior, ctx, states, receipt, new_binding, {
        "receipt": receipt_id, "oos": oos_id, "event_ledger": ledger_id,
    }


def load_prior_scores(prior, ctx, states, receipt, oos_id):
    old = pd.read_parquet(oos_id["path"]).sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    assert len(old) == CORE_KEYS and old["D"].nunique() == 120 and not old.duplicated(e4.KEY).any()
    assert old[A_SCORE].isna().equals(old["fold"].eq(FOLD)) and old[A_SCORE].isna().sum() == F01_KEYS
    assert sorted(old.loc[old["fold"].eq(FOLD), "D"].unique().tolist()) == receipt["missing_e4a_dates"]
    candidate = ctx["core_oos"].sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    pd.testing.assert_frame_equal(old[list(candidate)], candidate, check_exact=True)
    baseline = ctx["baseline"].sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    base_score_cols = list(e4.BASELINE_SCORES.values())
    pd.testing.assert_frame_equal(old[e4.KEY + base_score_cols], baseline[e4.KEY + base_score_cols], check_exact=True)
    receipt_weights = {(item["fold"], item["arm"]): item for item in receipt["weights"]}
    assert len(receipt_weights) == len(receipt["weights"]) == 35
    assert set(receipt_weights) == set(states) - {e4.FAILED_CANARY_KEY}
    archive_max = dict.fromkeys(e4.ARMS, 0.0)
    for (fold, arm), recorded in sorted(receipt_weights.items()):
        state = states[fold, arm]
        start, done = state["FIT_STARTED"], state["FIT_COMPLETED"]
        weight, score_path = e4.model_paths(prior, fold, arm)
        assert start["fit_id"] == done["fit_id"] == recorded["fit_id"]
        assert start["runner_sha256"] == done["runner_sha256"] == OLD_RUNNER_SHA
        assert start["input_binding_sha256"] == receipt["input_binding_sha256"]
        assert done["weight_sha256"] == recorded["sha256"] and done["weight_bytes"] == recorded["bytes"]
        assert done["prediction_sha256"] == recorded["score_sha256"]
        assert done["weight_file"] == recorded["weight_file"] == str(weight)
        assert done["prediction_file"] == recorded["score_file"] == str(score_path)
        assert done["model_reload_prediction_max_abs_diff"] == recorded["reload_max_abs_diff"] == 0
        evaluate = old.loc[old["fold"].eq(fold)]
        score = e4.score_completed(prior, state, evaluate, fold, arm)
        observed = score["score"].to_numpy(dtype="float64")
        expected = evaluate[e4.SCORES[arm]].to_numpy(dtype="float64")
        assert recorded["core_oos_rows"] == start["core_oos_rows"] == len(observed)
        assert np.array_equal(observed, expected), f"old OOS and saved scores differ F{fold:02d}/{arm}"
        archive_max[arm] = max(archive_max[arm], float(np.max(np.abs(observed - expected))))
    assert set(prior["weights"].glob("ACT037_F*.joblib")) == {
        Path(item["weight_file"]) for item in receipt_weights.values()
    }
    assert not any(path.exists() for path in e4.model_paths(prior, FOLD, ARM))
    return old, archive_max


def verify_f01(ctx, threads: int) -> dict:
    train, evaluate, x_train, x_eval, split = e4.feature_matrices(ctx, FOLD)
    assert len(train) == 16508 and len(evaluate) == F01_KEYS
    assert int(split.fit_data_cutoff) == 20260520 and int(split.test_first_D) == 20260521
    assert train["label_end_5"].le(20260520).all()
    assert list(x_train.columns) == list(x_eval.columns) == e4.FEATURES and len(e4.FEATURES) == 25
    assert not set(x_train.columns) & e4.DROPPED
    target = train[e4.TARGET].to_numpy(dtype="float64")
    assert np.isfinite(target).all()
    counts = {"below_minus_10": int((target < -10).sum()), "above_plus_10": int((target > 10).sum())}
    assert counts == EXPECTED_CLIP_COUNTS
    short_arm = e4.ARM_LABELS[ARM]
    assert short_arm == "E4A"
    params = e4.tree_parameters(ctx["outer"], short_arm, threads)
    assert params["objective"] == "huber" and params["alpha"] == 2.0
    assert params.get("max_depth", -1) == -1
    return {"train_rows": len(train), "core_oos_rows": len(evaluate), "fit_data_cutoff": 20260520,
            "first_test_D": 20260521, "training_target_clip": EXPECTED_CLIP,
            "training_target_clip_counts": counts, "locked_model_parameters": params}


def verified_new_state(new, events_path: Path, binding: dict) -> dict:
    events = e4.read_events(events_path)
    assert [event["state"] for event in events] == ["FIT_STARTED", "FIT_COMPLETED"]
    start, done = events
    expected_id = hashlib.sha256(f"{digest(binding)}|{FOLD}|{ARM}".encode()).hexdigest()
    assert expected_id != e4.FAILED_CANARY_FIT_ID
    assert all((event["fold"], event["arm"]) == (FOLD, ARM) for event in events)
    assert start["fit_id"] == done["fit_id"] == expected_id and start["ordinal"] == 1
    assert start["runner_sha256"] == done["runner_sha256"] == OLD_RUNNER_SHA
    assert start["input_binding_sha256"] == digest(binding)
    assert start["target_clip"] == EXPECTED_CLIP
    assert start["target_clip_counts"] == done["target_clip_counts"] == EXPECTED_CLIP_COUNTS
    assert start["model_class"] == "LGBMRegressor" and start["train_medians"] is None
    assert start["params"]["objective"] == "huber" and start["params"]["alpha"] == 2.0
    assert start["feature_names"] == e4.FEATURES and start["missing_indicators"] == 0
    assert start["train_rows"] == 16508 and start["core_oos_rows"] == F01_KEYS
    assert start["fit_data_cutoff"] == 20260520 and start["first_test_D"] == 20260521
    assert done["model_reload_prediction_max_abs_diff"] == 0.0
    assert done["prediction_calls"] == 2 and done["model_load_calls"] == 1
    weight, score = e4.model_paths(new, FOLD, ARM)
    assert done["weight_file"] == str(weight) and done["prediction_file"] == str(score)
    assert set(new["weights"].glob("ACT037_F*.joblib")) == {weight}
    return {"FIT_STARTED": start, "FIT_COMPLETED": done}


def run_once(new, ctx, binding, threads: int) -> dict:
    new["execution"].mkdir(parents=True, exist_ok=True)
    events_path = new["execution"] / "ACT037_F01_EVENTS.jsonl"
    binding_path = new["execution"] / "ACT037_F01_INPUT_BINDING.json"
    with (new["execution"] / "RUN.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not events_path.exists(), "F01 fit ledger already exists; replay forbidden"
        assert not any(path.exists() for path in e4.model_paths(new, FOLD, ARM)), "F01 checkpoint exists"
        binding_record = {"binding": binding, "binding_sha256": digest(binding)}
        if binding_path.exists():
            assert json.loads(binding_path.read_text()) == binding_record
        else:
            e4.atomic_json(binding_path, binding_record)
        checks = verify_f01(ctx, threads)
        e4.fit_one(ctx, new, events_path, FOLD, ARM, threads, digest(binding), {})
        state = verified_new_state(new, events_path, binding)
        score = e4.score_completed(new, state, ctx["core_oos"].loc[ctx["core_oos"]["fold"].eq(FOLD)], FOLD, ARM)
        assert len(score) == F01_KEYS
    return {"status": "F01_FIT_COMPLETED", "fit_this_command": 1, "simulation": 0,
            "cumulative_fit": 219, "validation": checks, "ledger": e4.identity(events_path)}


def assemble(ctx, prior_oos: pd.DataFrame, score: pd.DataFrame):
    updated = prior_oos.copy()
    f01 = updated["fold"].eq(FOLD)
    assert score[e4.KEY].reset_index(drop=True).equals(updated.loc[f01, e4.KEY].reset_index(drop=True))
    updated.loc[f01, A_SCORE] = score["score"].to_numpy(dtype="float64")
    predictions = updated[e4.KEY + list(e4.SCORES.values())]
    final = e4.assemble_core_output(ctx, predictions)
    assert np.isfinite(final[list(e4.SCORES.values())].to_numpy(dtype="float64")).all()
    pd.testing.assert_frame_equal(prior_oos.drop(columns=A_SCORE), final.drop(columns=A_SCORE), check_exact=True)
    pd.testing.assert_frame_equal(prior_oos.loc[~f01], final.loc[~f01], check_exact=True)
    assert np.array_equal(final.loc[f01, A_SCORE].to_numpy(), score["score"].to_numpy())
    maxima = {}
    for name, column in {**e4.SCORES, **e4.BASELINE_SCORES}.items():
        comparable = prior_oos[column].notna()
        difference = final.loc[comparable, column] - prior_oos.loc[comparable, column]
        maxima[name] = float(difference.abs().max())
    assert all(value == 0.0 for value in maxima.values())
    return final, maxima


def metrics_and_gates(ctx, final: pd.DataFrame):
    direct, paired = e4.all_metrics(ctx, final)
    direct_summary = direct.loc[direct["row_type"].eq("ALL_120D")]
    assert len(direct_summary) == 12 and direct_summary["sessions"].eq(120).all()
    aggregate = paired.loc[paired["row_type"].eq("PAIRED_ALL_120D")]
    assert len(aggregate) == 18 and aggregate["fold_denominator"].eq(12).all()
    threshold = ctx["outer"]["policy"]["reference_not_admission"]
    result = {}
    for pool in ("CORE", "CORE_LOW_ABSORB"):
        result[pool] = {}
        for arm in e4.ARMS:
            row = direct_summary.loc[direct_summary["arm"].eq(arm)
                                     & direct_summary["eval_scope"].eq(pool)].iloc[0]
            comparisons = aggregate.loc[aggregate["arm"].eq(arm) & aggregate["eval_scope"].eq(pool)]
            wins = dict(zip(comparisons["comparison_baseline"], comparisons["top10_win_folds"].astype(int)))
            assert set(wins) == set(e4.BASELINE_SCORES)
            metrics = {name: float(row[name]) for name in (
                "rank_ic", "ndcg10", "t2_top10", "clean_top10", "pure_tail_trap_top10", "candidate_count",
            )}
            assert np.isfinite(list(metrics.values())).all()
            result[pool][arm] = {**metrics, "wins_vs_e2b": wins["E2B"], "wins_vs_e3l2": wins["E3L2"],
                                 "fold_denominator": 12, "sessions": 120}
            if pool == "CORE":
                checks = {
                    "rank_ic": bool(row["rank_ic"] > threshold["rank_ic_gt"]),
                    "top10_excess": bool(row["t2_top10"] >= threshold["top10_pp_ge"]),
                    "pure_tail": bool(row["pure_tail_trap_top10"] <= threshold["tail_le"]),
                    "wins_vs_e2b": wins["E2B"] >= threshold["wins_vs_e2b_ge"],
                }
                result[pool][arm]["reference_gate"] = "PASS_REFERENCE" if all(checks.values()) else "NOT_MET"
                result[pool][arm]["threshold_checks"] = checks
    return pd.concat([direct, paired], ignore_index=True), result


def pack(new, ctx, prior_oos, binding, prior_ids, archive_max) -> dict:
    events_path = new["execution"] / "ACT037_F01_EVENTS.jsonl"
    destinations = [new["delivery"] / name for name in OUTPUTS]
    with (new["execution"] / "RUN.lock").open("r") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not any(path.exists() for path in destinations), "existing ACT-037-F01 delivery"
        binding_path = new["execution"] / "ACT037_F01_INPUT_BINDING.json"
        assert json.loads(binding_path.read_text()) == {"binding": binding, "binding_sha256": digest(binding)}
        state = verified_new_state(new, events_path, binding)
        done = state["FIT_COMPLETED"]
        score = e4.score_completed(new, state, prior_oos.loc[prior_oos["fold"].eq(FOLD)], FOLD, ARM)
        final, maxima = assemble(ctx, prior_oos, score)
        assert len(final) == CORE_KEYS and final["D"].nunique() == 120
        assert int(final["is_low_absorb"].sum()) == 18238
        metrics, headlines = metrics_and_gates(ctx, final)
        flags = ctx["outer"]["flags"]
        weight, score_path = e4.model_paths(new, FOLD, ARM)
        receipt = {
            "action_id": ACTION, "status": "COMPLETE_F01_BACKFILL_RESEARCH_ONLY",
            "fit_limit": 1, "fit_this_round": 1, "fit_prior_round": 36, "fit_prior_round_success": 35,
            "cumulative_fit_before": 218, "cumulative_fit_after": 219,
            "pack_operations": {"fit": 0, "prediction": 0, "simulation": 0},
            "old_model_load": 0, "old_model_predict": 0, "baseline_refit": 0, "simulation": 0,
            "fold": FOLD, "arm": ARM, "new_weight": e4.identity(weight),
            "new_score_checkpoint": e4.identity(score_path), "new_fit_id": done["fit_id"],
            "original_failed_fit_id": e4.FAILED_CANARY_FIT_ID,
            "new_weight_reload_max_abs_diff": done["model_reload_prediction_max_abs_diff"],
            "fit_binding": binding, "fit_binding_sha256": digest(binding),
            "training_contract": verify_f01(ctx, state["FIT_STARTED"]["params"]["n_jobs"]),
            "prior_artifacts": prior_ids, "new_event_ledger": e4.identity(events_path),
            "prior_folds_reused_exactly": 35,
            "saved_prior_score_to_prior_oos_max_abs_diff_by_arm": archive_max,
            "prior_oos_to_completed_max_abs_diff_on_previously_finite_rows_by_group": maxima,
            "non_f01_exact": True, "baseline_exact": True, "relevance_exact": True,
            "non_f01_score_max_abs_diff": 0.0, "baseline_score_max_abs_diff": 0.0,
            "core_oos_keys": len(final), "sessions": final["D"].nunique(),
            "low_absorb_keys": int(final["is_low_absorb"].sum()),
            "f01_added_keys": F01_KEYS, "f01_added_dates": sorted(score["D"].unique().tolist()),
            "regimes": final.groupby("regime")["D"].nunique().to_dict(),
            "headlines": headlines, "flags": flags, **flags,
            "cleanup": {"status": "RUNTIME_CLEANUP_PENDING", "removed_bytes": 0},
            "time_beijing": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
        new["delivery"].mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".act037-f01-pack-", dir=new["batch"]) as temp:
            staged = [Path(temp) / name for name in OUTPUTS]
            e4.atomic_parquet(final, staged[0])
            pd.testing.assert_frame_equal(pd.read_parquet(staged[0]), final, check_exact=True)
            e4.atomic_csv(metrics, staged[1])
            receipt["delivery_files"] = {
                target.name: {**e4.identity(src), "path": str(target)}
                for target, src in zip(destinations[:-1], staged[:-1], strict=True)
            }
            for pinned in prior_ids.values():
                e4.checked_identity(Path(pinned["path"]), pinned)
            assert e4.identity(events_path) == receipt["new_event_ledger"]
            e4.atomic_json(staged[2], receipt)
            for source, target in zip(staged, destinations, strict=True):
                os.replace(source, target)
    return {key: receipt[key] for key in (
        "status", "fit_this_round", "cumulative_fit_after", "new_weight_reload_max_abs_diff",
        "core_oos_keys", "sessions", "headlines", "delivery_files",
    )}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="validate inputs, feature matrices, and previous scores with zero FIT")
    commands.add_parser("pack", help="assemble full OOS and metrics with zero FIT")
    run = commands.add_parser("run", help="attempt the single authorized F01 FIT")
    run.add_argument("--threads", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    new, prior, ctx, states, receipt, binding, prior_ids = load_frozen(
        args.batch_root.resolve(), args.prior_root.resolve(), args.source_root.resolve(),
    )
    old, archive_max = load_prior_scores(prior, ctx, states, receipt, prior_ids["oos"])
    if args.command == "preflight":
        result = {"status": "PASS_NO_FIT", "fit_this_command": 0, "simulation": 0,
                  "prior_scored_checkpoints_verified": 35, "core_oos_keys": len(old),
                  "archived_score_to_oos_group_max_abs_diff": archive_max,
                  "validation": verify_f01(ctx, 2), "binding": binding}
    elif args.command == "run":
        result = run_once(new, ctx, binding, args.threads)
    else:
        result = pack(new, ctx, old, binding, prior_ids, archive_max)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
