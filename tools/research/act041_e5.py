#!/usr/bin/env python3
"""ACT-041 FULL-only two-arm research run with a 24-attempt fail-closed ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd

import act037_e4 as e4


ACTION = "ACT-041"
BATCH = "ACT041_CODEX_E5_FULL_CLEAN_24FIT_20261124"
F01_BATCH = "ACT037_F01_CODEX_BACKFILL_20261124"
A = "E5A_FULL_HUBER_CLEAN"
B = "E5B_FULL_LGBM_HUBER"
ARMS = (A, B)
SCORES = {A: "score_e5a", B: "score_e5b", "E3HUBER": "score_e3huber", "E3L2": "score_e3l2"}
PAIRS = {A: "E3HUBER", B: "E3L2"}
DROPPED = {"volume_today_over_prior20_mean", "post_attack_up_bar_ratio", "prior5_highvol_bear"}
FEATURES = [feature for feature in [*e4.BASE20, *e4.ADD10] if feature not in DROPPED]
KEPT_CONSTANTS = ("hold_rise_base_low", "prior5_highvol_bear_unrecovered")
VOLUME_FIELDS = ("amount_ratio_20", "pullback_vol_decay_ratio")
CUTS = {20260820: 757271, 20261016: 891130}
OUTPUTS = ("ACT041_E5_OOS_FULL_120D.parquet", "ACT041_E5_METRICS_120D.csv",
           "ACT041_E5_WEIGHT_SUMMARY.csv", "ACT041_RUN_AND_CLEANUP_RECEIPT.json")
FIT_ORDER = tuple((fold, arm) for fold in range(1, 13) for arm in ARMS)
SCOPE_SHA = "f5fa055b204a7ac7945a89ddfc7c782648d99494ba358b61b9d33f768778e21d"
E4_RUNNER_SHA = "bb3fcb47ce666e6358b26bdc797f9555709782b97d4013be11bd3ea79addb16b"


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def verified(path: Path, sha: str) -> dict:
    identity = e4.identity(path)
    assert identity["sha256"] == sha, f"pinned SHA mismatch: {path}"
    return identity


def load_runtime(paths: dict) -> dict:
    vendor = paths["batch"] / "work" / "lightgbm_runtime"
    pinned = read_json(paths["runtime"])
    assert vendor.is_dir() and pinned["fit"] == pinned["prediction"] == pinned["simulation"] == 0
    sys.path.insert(0, str(vendor))
    import joblib
    import lightgbm
    import sklearn

    assert Path(lightgbm.__file__).resolve().is_relative_to(vendor.resolve())
    assert lightgbm.__version__ == pinned["lightgbm"] == "4.7.0"
    assert joblib.__version__ == pinned["joblib"] and sklearn.__version__ == pinned["sklearn"]
    assert sys.version.split()[0] == pinned["python"]
    return {**pinned, "interpreter": sys.executable, "lightgbm_import": lightgbm.__file__}


def paths_for(batch: Path, source: Path):
    assert batch.name == BATCH and batch.parent == source
    paths = e4.runtime_paths(batch, source)
    paths.update(scope=batch / "work" / "ACT041_SCOPE.json",
                 execution=batch / "work" / "ACT041_EXECUTION",
                 f01=source / F01_BATCH)
    paths["ledger"] = paths["execution"] / "ACT041_EVENTS.jsonl"
    paths["lock"] = paths["execution"] / "RUN.lock"
    paths["preflight"] = batch / "work" / "ACT041_PREFIX_GATE_RECEIPT.json"
    return paths


def rank_full(raw: pd.DataFrame) -> pd.DataFrame:
    return raw.groupby("D", sort=False)[FEATURES].rank(method="average", pct=True).astype("float32")


def read_prefix(source: dict, add10: Path, cutoff: int) -> pd.DataFrame:
    base_cols = [feature for feature in e4.BASE20 if feature in FEATURES]
    add_cols = [feature for feature in e4.ADD10 if feature in FEATURES]
    filters = [("D", "<=", cutoff)]
    x = pd.concat([
        pd.read_parquet(Path(source["delivery_dir"]) / piece["file"],
                        columns=[*e4.KEY, *base_cols], filters=filters)
        for piece in source["artifact_files"]["X"] if piece["date_min"] <= cutoff
    ], ignore_index=True)
    add = pd.read_parquet(add10, columns=[*e4.KEY, "feature_source_max_D", *add_cols], filters=filters)
    assert x[e4.KEY].equals(add[e4.KEY]) and not x.duplicated(e4.KEY).any()
    assert x["D"].le(cutoff).all() and add["feature_source_max_D"].le(add["D"]).all()
    return pd.concat([x, add[add_cols]], axis=1)


def physical_prefix_checks(ctx: dict) -> dict:
    proof = {}
    for cutoff, expected_keys in CUTS.items():
        prefix = read_prefix(ctx["act030_scope"]["source"], ctx["add10_path"], cutoff)
        mask = ctx["raw"]["D"].le(cutoff)
        assert len(prefix) == mask.sum() == expected_keys
        pd.testing.assert_frame_equal(prefix, ctx["raw"].loc[mask, [*e4.KEY, *FEATURES]].reset_index(drop=True),
                                      check_exact=True)
        actual = rank_full(prefix).to_numpy()
        expected = ctx["ranks"].loc[mask, FEATURES].to_numpy()
        assert np.array_equal(np.isnan(actual), np.isnan(expected))
        finite = np.isfinite(expected)
        maximum = float(np.max(np.abs(actual[finite] - expected[finite])))
        assert maximum == 0.0 and np.array_equal(actual, expected, equal_nan=True)
        proof[str(cutoff)] = {"keys": expected_keys, "features": 27, "cells_compared": int(finite.sum()),
                             "null_masks_equal": True, "key_order_exact": True, "max_abs_diff": maximum,
                             "method": "independent column-selected D<=cutoff parquet reads then FULL D0 rank"}
    return proof


def load_baselines(paths, act034_scope, act034_receipt, key_hint, raw_oos, scope):
    finish = {item["file"]: item for item in act034_receipt["completed_prior_uploads"]}
    summary = read_json(paths["act034"] / "delivery" / "ACT034_SUMMARY.json")["delivery_files"]
    shards, evidence = [], {}
    for file in ("ACT034_OOS_F01-F06.parquet", "ACT034_OOS_F07-F12.parquet"):
        item = finish[file]
        path = paths["act034"] / "delivery" / file
        assert Path(item["path"]) == path and item["success"] is True
        assert item["parent_id"] == act034_receipt["delivery_folder"].rsplit("/", 1)[-1]
        assert all(item[key] == summary[file][key] for key in ("sha256", "bytes"))
        e4.checked_identity(path, item)
        evidence[file] = {key: item[key] for key in ("id", "sha256", "bytes")}
        shards.append(pd.read_parquet(path))
    e3 = pd.concat(shards, ignore_index=True).sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    keys = [*e4.KEY, "fold", "core_mask"]
    assert len(e3) == 473307 and not e3.duplicated(e4.KEY).any()
    pd.testing.assert_frame_equal(e3[keys], key_hint.sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)[keys],
                                  check_exact=True)
    verified_cols = [*keys, "relevance", "score_e2a", "score_e2b"]
    base_path = Path(act034_scope["baseline"]["files"]["ACT030_OOS_PREDICTIONS.parquet"]["path"])
    evidence["ACT030_OOS_PREDICTIONS"] = verified(base_path, scope["source_sha256"]["act030_oos"])
    old = pd.read_parquet(base_path, columns=verified_cols).sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    pd.testing.assert_frame_equal(e3[verified_cols], old[verified_cols], check_exact=True)
    pd.testing.assert_frame_equal(e3[[*e4.KEY, "core_mask", "relevance"]],
                                  raw_oos[[*e4.KEY, "core_mask", "relevance"]], check_exact=True)
    columns = [SCORES[name] for name in PAIRS.values()]
    assert np.isfinite(e3[columns].to_numpy()).all()
    return e3[[*keys, "relevance", *columns]], evidence


def load_context(paths: dict) -> dict:
    scope_id = verified(paths["scope"], SCOPE_SHA)
    scope = read_json(paths["scope"])
    assert scope["action_id"] == ACTION and scope["fit_limit"] == len(FIT_ORDER) == 24
    assert scope["core"] is False and scope["expected_oos_keys"] == 473307
    assert scope["expected_sessions"] == 120 and scope["folds"] == 12
    assert scope["missing_indicators"] == 0 and scope["features"] == FEATURES and len(FEATURES) == 27
    assert set(scope["drop"]) == DROPPED
    assert scope["train_target_clip"] == [-10.0, 10.0]
    assert scope["baseline_pairs"] == PAIRS
    assert scope["physical_prefix_cuts"] == list(CUTS)
    assert (scope["cumulative_fit_before"], scope["cumulative_fit_after"]) == (219, 243)
    verified(Path(e4.__file__), E4_RUNNER_SHA)
    runtime = load_runtime(paths)

    prior = {
        "act024_manifest": paths["act024"] / "delivery" / "DATA_1Y_MANIFEST.json",
        "act030_scope": paths["act030"] / "ACT030_SCOPE.json",
        "act034_receipt": paths["act034"] / "delivery" / "ACT034_RUN_AND_CLEANUP_RECEIPT.json",
        "act034_summary": paths["act034"] / "delivery" / "ACT034_SUMMARY.json",
        "act034_add10": paths["act034"] / "work" / "ACT034_E3_ADD10.parquet",
        "act036_receipt": paths["act036"] / "ACT036_0FIT_EXPORT_RECEIPT.json",
        "act037_f01_receipt": paths["f01"] / "delivery" / "ACT037_F01_RECEIPT.json",
        "act037_f01_oos": paths["f01"] / "delivery" / "ACT037_E4_OOS_CORE_120D.parquet",
    }
    proof = {name: verified(path, scope["source_sha256"][name]) for name, path in prior.items()}
    reader036 = e4.load_module("act041_frozen_reader", paths["act036"] / "work" / "export_act036.py")
    receipt_path, act034_receipt, act034_scope, gate = reader036.anchor_inputs()
    assert receipt_path == prior["act034_receipt"]
    assert act034_receipt["stage2"]["actual_fit"] == 24 and act034_receipt["stage2"]["simulation"] == 0
    assert act034_receipt["stage1"]["ADD10_local_path"] == str(prior["act034_add10"])
    physical_path = paths["act034"] / "work" / "ACT034_E3_MATERIALIZATION_RECEIPT.json"
    proof["ACT034_physical_gate"] = verified(physical_path, gate["input_binding"]["physical_gate_receipt_sha256"])
    physical = read_json(physical_path)
    assert physical["state"] == "PASS_PHYSICAL_GATE" and physical["no_y_read"]
    assert physical["fit"] == physical["prediction"] == physical["simulation"] == 0
    assert physical["artifact"] == proof["act034_add10"]
    assert physical["source"]["manifest_sha256"] == proof["act024_manifest"]["sha256"]
    assert physical["source"]["generation_id"] == scope["frozen_generation"]["generation_id"]
    assert physical["physical_prefix_gate"] == gate["physical_prefix_gate"]
    for cutoff, expected in CUTS.items():
        check = physical["physical_prefix_gate"][str(cutoff)]
        assert check["keys_compared"] == expected and check["max_abs_diff"] == 0.0 and check["nan_masks_equal"]

    reader, raw, splits, dates, key_hint, provenance = reader036.load_frozen(
        act034_scope, act034_receipt, gate, [*e4.BASE20, *e4.ADD10], e4.ADD10,
    )
    act030_scope = reader.read_scope()
    assert proof["act024_manifest"] == provenance["ACT024_manifest"] and len(raw) == 987203
    assert len(splits) == 12 and list(splits["fold"]) == list(range(1, 13))
    regimes = pd.read_csv(act030_scope["source"]["regimes_file"])
    raw["regime"] = raw["D"].map(regimes.set_index("D")["regime"])
    raw["relevance"] = reader.make_relevance(raw)
    assert raw["regime"].notna().all()
    out = raw.loc[raw["ready"] & raw["D"].isin(dates),
                  [*e4.KEY, "core_mask", "relevance", e4.TARGET, e4.CLEAN, e4.TAIL, "regime", *VOLUME_FIELDS]]
    out = out.sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    assert len(out) == 473307 and len(dates) == out["D"].nunique() == 120 and out["core_mask"].sum() == 40578
    assert out.groupby("regime")["D"].nunique().to_dict() == {"ICE": 27, "RANGE": 68, "REBOUND": 25}
    baselines, baseline_proof = load_baselines(paths, act034_scope, act034_receipt, key_hint, out, scope)
    metric_file = paths["act034"] / "delivery" / "ACT034_METRICS.csv"
    metric_pin = next(item for item in act034_receipt["completed_prior_uploads"] if item["file"] == metric_file.name)
    assert Path(metric_pin["path"]) == metric_file and metric_pin["success"] is True
    e4.checked_identity(metric_file, metric_pin)
    proof["ACT034_OOS_metrics"] = e4.identity(metric_file)
    out = out.merge(baselines, on=[*e4.KEY, "core_mask", "relevance"], validate="one_to_one")
    assert len(out) == 473307 and out["fold"].between(1, 12).all()

    f01_receipt = read_json(prior["act037_f01_receipt"])
    assert f01_receipt["action_id"] == "ACT-037-F01" and f01_receipt["cumulative_fit_after"] == 219
    assert f01_receipt["fit_this_round"] == 1 and f01_receipt["flags"] == scope["flags"]
    assert f01_receipt["training_contract"]["locked_model_parameters"] == scope["objectives"][B]
    assert scope["objectives"][A] == {"alpha": 10.0, "epsilon": 1.65, "max_iter": 400, "tol": 1e-6}
    assert f01_receipt["delivery_files"][prior["act037_f01_oos"].name] == proof["act037_f01_oos"]
    core = pd.read_parquet(prior["act037_f01_oos"], columns=[
        *e4.KEY, "fold", "core_mask", "relevance", "score_e4a", "score_e4b", "score_e4c",
    ]).sort_values(e4.KEY, kind="mergesort").reset_index(drop=True)
    compare_cols = [*e4.KEY, "fold", "core_mask", "relevance"]
    pd.testing.assert_frame_equal(out.loc[out["core_mask"], compare_cols].reset_index(drop=True),
                                  core[compare_cols], check_exact=True)
    assert np.isfinite(core[["score_e4a", "score_e4b", "score_e4c"]].to_numpy()).all()

    historical = read_json(prior["act036_receipt"])
    assert historical["fit"] == historical["predict"] == historical["simulation"] == 0
    assert historical["flags"] == scope["flags"]
    weight_info = historical["files"]["ACT036_WEIGHT_FEATURE_EXPORT.csv"]
    historical_weight_path = paths["act036"] / "ACT036_WEIGHT_FEATURE_EXPORT.csv"
    assert Path(weight_info["path"]) == historical_weight_path
    e4.checked_identity(historical_weight_path, weight_info)
    proof["ACT036_weight_export"] = e4.identity(historical_weight_path)
    old_weights = pd.read_csv(historical_weight_path)

    ranks = rank_full(raw)
    assert ranks[FEATURES].isna().equals(raw[FEATURES].isna())
    retained = {feature: {"unique_raw_values": int(raw[feature].nunique()),
                          "varying_days": int(raw.groupby("D")[feature].nunique().gt(1).sum())}
                for feature in KEPT_CONSTANTS}
    assert all(item["unique_raw_values"] == 2 and item["varying_days"] > 0 for item in retained.values())
    binding = {"scope_sha256": scope_id["sha256"], "runner_sha256": e4.sha256(Path(__file__)),
               "prior_pins": proof, "act034_baselines": baseline_proof,
               "frozen_snapshot": provenance["ACT024_snapshot"], "frozen_projection_sha256": provenance["ACT024_source_input_SHA256"],
               "split": provenance["split"], "features": FEATURES}
    return {"outer": scope, "runtime": runtime, "reader": reader, "act030_scope": act030_scope,
            "raw": raw, "ranks": ranks, "splits": splits, "dates": dates, "oos": out, "core_e4": core,
            "historical_metrics": pd.read_csv(metric_file),
            "old_weights": old_weights, "retained": retained, "binding": binding,
            "add10_path": prior["act034_add10"], "add10_upstream_prefix": physical["physical_prefix_gate"]}


def fold_data(ctx: dict, fold: int):
    split = e4.fold_split(ctx["splits"], fold)
    reader, raw = ctx["reader"], ctx["raw"]
    train = reader.fit_rows(raw, split, core=False)
    test = reader.eval_rows(raw, split, core=False)
    assert len(train) == int(split.fit_rows)
    assert train["ready"].all() and train["fit_thinning_5session_selected"].all()
    assert train["label_end_5"].le(split.fit_data_cutoff).all()
    assert int(train["D"].max()) <= split.fit_data_cutoff < split.test_first_D == int(test["D"].min())
    assert train["core_mask"].any() and not train["core_mask"].all()
    expected = ctx["oos"].loc[ctx["oos"]["fold"].eq(fold), e4.KEY].reset_index(drop=True)
    pd.testing.assert_frame_equal(test[e4.KEY].reset_index(drop=True), expected, check_exact=True)
    x_train = ctx["ranks"].loc[train.index, FEATURES]
    x_test = ctx["ranks"].loc[test.index, FEATURES]
    return train, test, x_train, x_test, split


def validate_preflight(ctx: dict, paths: dict) -> dict:
    receipt = read_json(paths["preflight"])
    assert receipt["status"] == "PASS_NO_FIT" and receipt["fit"] == receipt["prediction"] == 0
    assert receipt["binding_sha256"] == digest(ctx["binding"])
    assert set(receipt["physical_prefix_checks"]) == set(map(str, CUTS))
    for cutoff, n in CUTS.items():
        check = receipt["physical_prefix_checks"][str(cutoff)]
        assert check["keys"] == n and check["max_abs_diff"] == 0.0
        assert check["null_masks_equal"] and check["key_order_exact"]
    return receipt


def fit_identity(binding_hash: str, fold: int, arm: str) -> str:
    return hashlib.sha256(f"{ACTION}|{binding_hash}|{fold}|{arm}".encode()).hexdigest()


def append_event(path: Path, state: str, **fields) -> None:
    record = {"action_id": ACTION, "state": state, "at": timestamp(), **fields}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_complete(ledger: Path, binding: dict):
    if not ledger.exists():
        return {}
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert 0 < len(events) <= 48 and len(events) % 2 == 0, "partial/corrupt ledger; FIT replay forbidden"
    binding_hash = digest(binding)
    completed = {}
    for index, (start, done) in enumerate(zip(events[::2], events[1::2], strict=True)):
        fold, arm = FIT_ORDER[index]
        expected_id = fit_identity(binding_hash, fold, arm)
        for event in (start, done):
            assert event["action_id"] == ACTION
            assert (event["fold"], event["arm"], event["fit_id"]) == (fold, arm, expected_id)
            assert event["binding_sha256"] == binding_hash
        assert start["state"] == "FIT_STARTED" and start["ordinal"] == index + 1
        assert done["state"] == "FIT_COMPLETED", "started FIT failed; replay forbidden"
        assert done["reload_max_abs_diff"] == 0.0 and done["prediction_calls"] == 2
        completed[(fold, arm)] = (start, done)
    return completed


def checkpoint_paths(paths: dict, fold: int, arm: str):
    suffix = "E5A" if arm == A else "E5B"
    assert arm in ARMS
    return (paths["weights"] / f"ACT041_F{fold:02d}_{suffix}.joblib",
            paths["execution"] / f"ACT041_SCORE_F{fold:02d}_{suffix}.parquet")


def make_model(arm: str, scope: dict):
    if arm == A:
        from sklearn.linear_model import HuberRegressor
        return HuberRegressor(**scope["objectives"][A])
    assert arm == B
    from lightgbm import LGBMRegressor
    return LGBMRegressor(**scope["objectives"][B])


def model_inputs(arm: str, x_train: pd.DataFrame, x_test: pd.DataFrame):
    assert list(x_train) == list(x_test) == FEATURES
    if arm == A:
        x_train = x_train.astype("float64")
        medians = x_train.median()
        assert np.isfinite(medians).all(), "missing training median"
        x_train, x_test = x_train.fillna(medians), x_test.astype("float64").fillna(medians)
        assert np.isfinite(x_train.to_numpy()).all() and np.isfinite(x_test.to_numpy()).all()
        return x_train, x_test, medians.to_dict()
    assert arm == B
    return x_train, x_test, None


def fit_one(ctx: dict, paths: dict, fold: int, arm: str, completed: dict, fold_gate: dict):
    index = len(completed)
    assert index < 24 and FIT_ORDER[index] == (fold, arm) and (fold, arm) not in completed
    weight, checkpoint = checkpoint_paths(paths, fold, arm)
    assert not weight.exists() and not checkpoint.exists(), "unbound checkpoint; FIT replay forbidden"
    train, test, x_train, x_test, split = fold_data(ctx, fold)
    x_train, x_test, medians = model_inputs(arm, x_train, x_test)
    raw_target = train[e4.TARGET].to_numpy(dtype="float64", copy=True)
    assert np.isfinite(raw_target).all()
    target = np.clip(raw_target, -10.0, 10.0)
    counts = {"below_minus_10": int((raw_target < -10.0).sum()),
              "above_plus_10": int((raw_target > 10.0).sum())}
    assert counts == {"below_minus_10": fold_gate["clip_low"], "above_plus_10": fold_gate["clip_high"]}
    assert (len(train), len(test)) == (fold_gate["train_rows"], fold_gate["oos_rows"])
    assert np.all((-10.0 <= target) & (target <= 10.0))
    oos_target = test[e4.TARGET].to_numpy(dtype="float64", copy=True)
    assert np.isfinite(oos_target).all()
    model = make_model(arm, ctx["outer"])
    params = model.get_params(deep=False)
    locked = ctx["outer"]["objectives"][arm]
    assert {key: params[key] for key in locked} == locked
    assert type(model).__name__ == ("HuberRegressor" if arm == A else "LGBMRegressor")
    assert (medians is not None) == (arm == A)

    binding_hash = digest(ctx["binding"])
    common = {"fold": fold, "arm": arm, "fit_id": fit_identity(binding_hash, fold, arm),
              "binding_sha256": binding_hash}
    append_event(paths["ledger"], "FIT_STARTED", **common, ordinal=index + 1,
                 train_rows=len(train), oos_rows=len(test), fit_data_cutoff=int(split.fit_data_cutoff),
                 first_test_D=int(split.test_first_D), pool="FULL", feature_names=FEATURES,
                 missing_indicators=0, training_target_clip=[-10.0, 10.0], clip_counts=counts,
                 training_medians=medians, locked_params=locked)
    try:
        model.fit(x_train, target)
        assert np.array_equal(raw_target, train[e4.TARGET].to_numpy(dtype="float64"))
        assert np.array_equal(oos_target, test[e4.TARGET].to_numpy(dtype="float64"))
        original = np.asarray(model.predict(x_test), dtype="float64")
        assert original.shape == (len(test),) and np.isfinite(original).all()

        import joblib
        payload = {"estimator": model, "features": FEATURES, "training_medians": medians, "fold": fold,
                   "arm": arm, "fit_id": common["fit_id"]}
        weight.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".act041-weight-", dir=weight.parent) as temp:
            pending = Path(temp) / weight.name
            joblib.dump(payload, pending, compress=3)
            with pending.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(pending, weight)
        archived = joblib.load(weight)
        assert archived["fit_id"] == common["fit_id"] and archived["features"] == FEATURES
        assert archived["fold"] == fold and archived["arm"] == arm and archived["training_medians"] == medians
        restored = archived["estimator"]
        assert type(restored) is type(model)
        replay = np.asarray(restored.predict(x_test), dtype="float64")
        assert np.array_equal(original, replay)
        reload_max = float(np.max(np.abs(original - replay)))
        weights = model_weights(arm, restored)
        scored = test[e4.KEY].reset_index(drop=True).assign(score=replay)
        e4.atomic_parquet(scored, checkpoint)
        pd.testing.assert_frame_equal(pd.read_parquet(checkpoint), scored, check_exact=True)
        append_event(paths["ledger"], "FIT_COMPLETED", **common, reload_max_abs_diff=reload_max,
                     prediction_calls=2, model_reload_calls=1, weight=e4.identity(weight),
                     score_checkpoint=e4.identity(checkpoint), model_weights=weights,
                     huber_n_iter=int(restored.n_iter_) if arm == A else None,
                     oos_target_unchanged=True)
    except BaseException as error:
        append_event(paths["ledger"], "FIT_FAILED", **common, error_type=type(error).__name__,
                     error=str(error)[:1200])
        raise


def model_weights(arm: str, restored) -> dict:
    if arm == A:
        assert restored.n_features_in_ == len(FEATURES)
        assert len(restored.coef_) == len(FEATURES) and np.isfinite(restored.coef_).all()
        return {feature: {"coefficient": float(value)} for feature, value in
                zip(FEATURES, restored.coef_, strict=True)}
    booster = restored.booster_
    assert booster.params["objective"] == "huber" and float(booster.params["alpha"]) == 2.0
    assert booster.feature_name() == FEATURES
    gain = booster.feature_importance(importance_type="gain")
    split = booster.feature_importance(importance_type="split")
    assert np.isfinite(gain).all() and np.all(gain >= 0) and np.all(split >= 0)
    assert gain.sum() > 0 and split.sum() > 0
    return {feature: {"gain": float(g), "gain_share": float(g / gain.sum()),
                      "split": int(s), "split_share": float(s / split.sum())}
            for feature, g, s in zip(FEATURES, gain, split, strict=True)}


def read_score(paths: dict, fold: int, arm: str, state, keys: pd.DataFrame) -> pd.Series:
    start, done = state
    weight, checkpoint = checkpoint_paths(paths, fold, arm)
    for path, record in ((weight, done["weight"]), (checkpoint, done["score_checkpoint"])):
        assert str(path) == record["path"]
        e4.checked_identity(path, record)
    assert start["pool"] == "FULL" and start["feature_names"] == FEATURES and start["missing_indicators"] == 0
    assert start["oos_rows"] == len(keys) and done["oos_target_unchanged"]
    assert start["training_target_clip"] == [-10.0, 10.0]
    score = pd.read_parquet(checkpoint)
    assert list(score) == [*e4.KEY, "score"]
    pd.testing.assert_frame_equal(score[e4.KEY], keys.reset_index(drop=True), check_exact=True)
    assert np.isfinite(score["score"]).all()
    return score["score"]


def run(ctx: dict, paths: dict, through_fold: int, threads: int) -> dict:
    assert threads == ctx["outer"]["objectives"][B]["n_jobs"] == 2
    gate = validate_preflight(ctx, paths)
    paths["execution"].mkdir(parents=True, exist_ok=True)
    with paths["lock"].open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = read_complete(paths["ledger"], ctx["binding"])
        assert through_fold == 1 or len(completed) >= 2, "complete F01 two-FIT canary first"
        for (fold, arm), state in completed.items():
            keys = ctx["oos"].loc[ctx["oos"]["fold"].eq(fold), e4.KEY]
            read_score(paths, fold, arm, state, keys)
        new_fits = 0
        for fold, arm in FIT_ORDER[len(completed):2 * through_fold]:
            fit_one(ctx, paths, fold, arm, completed, gate["folds"][str(fold)])
            completed = read_complete(paths["ledger"], ctx["binding"])
            new_fits += 1
            done = completed[(fold, arm)][1]
            print(json.dumps({"state": "FIT_COMPLETED", "fold": fold, "arm": arm,
                              "fit_started_total": len(completed), "reload_max_abs_diff": done["reload_max_abs_diff"]}),
                  flush=True)
    return {"status": "FIT_COMPLETE" if len(completed) == 24 else "CANARY_OR_PARTIAL",
            "fit_this_command": new_fits, "fit_total": len(completed), "simulation": 0}


CORE_SET_COLS = ("top10_core_members", "top10_overlap_e4a_e4c", "top10_overlap_e4b_e4c")


def top10(frame: pd.DataFrame, score: str) -> pd.DataFrame:
    return frame.sort_values([score, "ts_code"], ascending=[False, True], kind="mergesort").head(10)


def core_benchmarks(core: pd.DataFrame) -> dict:
    columns = ["score_e4a", "score_e4b", "score_e4c"]
    scores = core.groupby("D")[columns].rank(method="average", pct=True)
    blends = core[e4.KEY].assign(
        e4a_e4c=(scores["score_e4a"] + scores["score_e4c"]) * 0.5,
        e4b_e4c=(scores["score_e4b"] + scores["score_e4c"]) * 0.5,
    )
    return {int(day): tuple(set(top10(frame, name)["ts_code"]) for name in ("e4a_e4c", "e4b_e4c"))
            for day, frame in blends.groupby("D", sort=True)}


def metrics_table(ctx: dict, final: pd.DataFrame):
    references = core_benchmarks(ctx["core_e4"])
    rows = []
    for day, group in final.groupby("D", sort=True):
        fold, regime = int(group["fold"].iloc[0]), group["regime"].iloc[0]
        left, right = references[int(day)]
        assert len(left) == len(right) == 10
        for arm, field in SCORES.items():
            # Frozen ACT-037 daily metrics and tie rules, with only the input score remapped.
            row = e4.daily_metrics(group.assign(score_e4a=group[field]), e4.ARMS[0], "FULL", int(day), fold, regime)
            row["arm"] = arm
            selected = top10(group, field)
            assert len(selected) == 10
            row.update(top10_core_members=int(selected["core_mask"].sum()),
                       top10_overlap_e4a_e4c=int(selected["ts_code"].isin(left).sum()),
                       top10_overlap_e4b_e4c=int(selected["ts_code"].isin(right).sum()))
            for volume in VOLUME_FIELDS:
                row[f"score_raw_spearman__{volume}"] = e4.rank_ic(group[volume], group[field])
            rows.append(row)
    daily = pd.DataFrame(rows)
    assert len(daily) == 4 * 120 and daily["t2_top10"].notna().all()
    summary = summarize_metrics(daily, paired=False)

    paired_days = []
    for arm, baseline in PAIRS.items():
        chosen = daily.loc[daily["arm"].eq(arm)].sort_values("D").reset_index(drop=True)
        reference = daily.loc[daily["arm"].eq(baseline)].sort_values("D").reset_index(drop=True)
        keys = ["D", "fold", "regime"]
        pd.testing.assert_frame_equal(chosen[keys], reference[keys], check_exact=True)
        assert len(chosen) == 120
        deltas = [*e4.METRICS, *CORE_SET_COLS,
                  *(f"score_raw_spearman__{name}" for name in VOLUME_FIELDS)]
        paired_days.append(chosen.assign(
            row_type="PAIRED_DAILY", comparison_baseline=baseline, **(chosen[deltas] - reference[deltas]),
        ))
    paired = pd.concat(paired_days, ignore_index=True)
    paired_summary = summarize_metrics(paired, paired=True)
    all_direct = summary.loc[summary["row_type"].eq("ALL_120D")].set_index("arm")
    all_paired = paired_summary.loc[paired_summary["row_type"].eq("PAIRED_ALL_120D")].set_index("arm")
    assert all_paired["fold_denominator"].eq(12).all() and len(all_paired) == 2
    historical = ctx["historical_metrics"]
    old = historical.loc[historical["comparison"].eq("arm_value") & historical["eval_scope"].eq("FULL")
                         & historical["level"].eq("all_oos")].set_index("arm")
    parity_columns = {"rank_ic": "rank_ic_mean", "ndcg10": "ndcg10_mean",
                      "t2_top10": "t2_top10_mean", "pure_tail_trap_top10": "tail_top10_mean"}
    parity = {}
    for baseline in PAIRS.values():
        parity[baseline] = {column: abs(float(all_direct.loc[baseline, column] - old.loc[baseline, metric]))
                            for column, metric in parity_columns.items()}
        assert max(parity[baseline].values()) < 1e-10, f"official baseline metric replay differs for {baseline}"
    headlines = {}
    headline_columns = [*parity_columns, "clean_top10", *CORE_SET_COLS]
    for arm in SCORES:
        row = all_direct.loc[arm]
        entry = {column: float(row[column]) for column in headline_columns}
        entry.update(sessions=int(row["sessions"]),
                     score_raw_direction={feature: float(row[f"score_raw_spearman__{feature}"])
                                          for feature in VOLUME_FIELDS})
        for column in CORE_SET_COLS:
            entry[column + "_total"] = int(row[column + "_total"])
            entry[column + "_pct"] = float(row[column + "_pct"])
        if arm in PAIRS:
            paired_row = all_paired.loc[arm]
            entry.update(comparison_baseline=PAIRS[arm],
                         top10_win_folds=int(paired_row["top10_win_folds"]),
                         fold_denominator=12, top10_excess_delta_pp=float(paired_row["t2_top10"]))
        headlines[arm] = entry
    return pd.concat([daily, summary, paired, paired_summary], ignore_index=True), headlines, parity


def summarize_metrics(daily: pd.DataFrame, *, paired: bool) -> pd.DataFrame:
    results = []
    dimensions = ["eval_scope", "arm", *(["comparison_baseline"] if paired else [])]
    for level, suffix in (("ALL_120D", []), ("FOLD", ["fold"]), ("REGIME", ["regime"])):
        row_type = f"PAIRED_{level}" if paired else level
        group_keys = dimensions + suffix
        table = pd.DataFrame(e4.group_summary(daily, group_keys, row_type))
        extra = {}
        for column in CORE_SET_COLS:
            extra[column] = (column, "mean")
            extra[column + "_total"] = (column, "sum")
        if not paired:
            for field in VOLUME_FIELDS:
                name = f"score_raw_spearman__{field}"
                extra[name] = (name, "mean")
        table = table.merge(daily.groupby(group_keys).agg(**extra).reset_index(), on=group_keys, validate="one_to_one")
        for column in CORE_SET_COLS:
            table[column + "_pct"] = table[column + "_total"] / (10 * table["sessions"]) * 100.0
        if paired:
            fold_dimensions = group_keys if "fold" in group_keys else [*group_keys, "fold"]
            per_fold = daily.groupby(fold_dimensions)["t2_top10"].mean().reset_index()
            per_fold["win"] = per_fold["t2_top10"].gt(0).astype(int)
            wins = per_fold.groupby(group_keys)["win"].agg(
                top10_win_folds="sum", fold_denominator="count",
            ).reset_index()
            table = table.merge(wins, on=group_keys, validate="one_to_one")
        results.append(table)
    return pd.concat(results, ignore_index=True)


def signed_stats(values: pd.Series) -> dict:
    assert len(values) > 0 and np.isfinite(values).all()
    mean = float(values.mean())
    return {"coefficient_mean": mean, "coefficient_abs_mean": abs(mean),
            "coefficient_max_abs_across_folds": float(values.abs().max()),
            "coefficient_positive_folds": int(values.gt(0).sum()),
            "coefficient_negative_folds": int(values.lt(0).sum()),
            "coefficient_sign_match_folds": int(np.sign(values).eq(np.sign(mean)).sum())}


def weight_summary(states: dict, old_weights: pd.DataFrame):
    records = []
    for (fold, arm), (start, done) in states.items():
        assert start["missing_indicators"] == 0 and start["feature_names"] == FEATURES
        weights = done["model_weights"]
        assert set(weights) == set(FEATURES)
        for name, values in weights.items():
            records.append({"row_type": "FOLD", "fold": fold, "arm": arm, "feature": name, "fold_count": 1,
                            "dimension_count": 27, "missing_indicator_count": 0, **values})
    folds = pd.DataFrame(records)
    summary = []
    for (arm, name), frame in folds.groupby(["arm", "feature"], sort=False):
        assert frame["fold"].nunique() == 12
        weights = (signed_stats(frame["coefficient"]) if arm == A else {
            key + "_mean": float(frame[key].mean()) for key in ("gain", "gain_share", "split", "split_share")
        })
        summary.append({"row_type": "MEAN_12_FOLDS", "fold": 0, "arm": arm, "feature": name,
                        "fold_count": 12, "dimension_count": 27, "missing_indicator_count": 0, **weights})
    aggregates = pd.DataFrame(summary)
    weight_table = pd.concat([folds, aggregates], ignore_index=True)
    assert len(weight_table) == 27 * 26
    new_a = folds.loc[folds["arm"].eq(A)]
    new_a_means = aggregates.loc[aggregates["arm"].eq(A), "coefficient_abs_mean"]
    old_a = old_weights.loc[old_weights["arm"].eq("E3HUBER") & old_weights["feature"].isin([*e4.BASE20, *e4.ADD10])]
    assert len(old_a) == 12 * 30
    old_max_index = old_a["huber_coef"].abs().idxmax()
    new_max_index = new_a["coefficient"].abs().idxmax()
    heads = {
        "old_E3HUBER_max_abs_coefficient_any_fold": float(abs(old_a.loc[old_max_index, "huber_coef"])),
        "old_E3HUBER_max_abs_fold_mean": float(old_a.groupby("feature")["huber_coef"].mean().abs().max()),
        "new_E5A_max_abs_coefficient_any_fold": float(abs(new_a.loc[new_max_index, "coefficient"])),
        "new_E5A_max_abs_coefficient_feature": new_a.loc[new_max_index, "feature"],
        "new_E5A_max_abs_coefficient_fold": int(new_a.loc[new_max_index, "fold"]),
        "new_E5A_max_abs_fold_mean": float(new_a_means.max()),
        "high_volume_pair": {},
    }
    for feature in ("volume_today_over_prior20_mean", "amount_ratio_20"):
        heads["high_volume_pair"][feature] = {
            "old_E3HUBER": signed_stats(old_a.loc[old_a["feature"].eq(feature), "huber_coef"]),
            "new_E5A": signed_stats(new_a.loc[new_a["feature"].eq(feature), "coefficient"])
            if feature in FEATURES else {"status": "DROPPED"},
        }
    return weight_table, heads


def pack(ctx: dict, paths: dict) -> dict:
    gate = validate_preflight(ctx, paths)
    destination = [paths["delivery"] / name for name in OUTPUTS]
    with paths["lock"].open("r") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not any(path.exists() for path in destination), "ACT-041 delivery exists"
        ledger_id = e4.identity(paths["ledger"])
        states = read_complete(paths["ledger"], ctx["binding"])
        assert tuple(states) == FIT_ORDER and len(states) == 24
        final = ctx["oos"].copy()
        for arm in ARMS:
            final[SCORES[arm]] = np.nan
        for (fold, arm), state in states.items():
            mask = final["fold"].eq(fold)
            score = read_score(paths, fold, arm, state, final.loc[mask, e4.KEY])
            final.loc[mask, SCORES[arm]] = score.to_numpy(dtype="float64")
        assert np.isfinite(final[list(SCORES.values())].to_numpy()).all()
        pd.testing.assert_frame_equal(final[list(ctx["oos"])], ctx["oos"], check_exact=True)
        assert len(final) == 473307 and not final.duplicated(e4.KEY).any() and final["D"].nunique() == 120
        metrics, headlines, parity = metrics_table(ctx, final)
        published = final.drop(columns=list(VOLUME_FIELDS))
        assert not published.isna().any().any()
        weights, weight_heads = weight_summary(states, ctx["old_weights"])
        flags = ctx["outer"]["flags"]
        archives = [{"fold": fold, "arm": arm, "fit_id": done["fit_id"], "weight": done["weight"],
                     "score_checkpoint": done["score_checkpoint"], "prediction_calls": done["prediction_calls"],
                     "reload_max_abs_diff": done["reload_max_abs_diff"], "huber_n_iter": done["huber_n_iter"],
                     "clip_counts": start["clip_counts"], "train_rows": start["train_rows"], "oos_rows": start["oos_rows"],
                     "fit_data_cutoff": start["fit_data_cutoff"], "first_test_D": start["first_test_D"]}
                    for (fold, arm), (start, done) in states.items()]
        assert set(paths["weights"].glob("ACT041_F*.joblib")) == {Path(row["weight"]["path"]) for row in archives}
        receipt = {
            "action_id": ACTION, "status": "COMPLETE_24_FIT_RESEARCH_ONLY",
            "fit_limit": 24, "fit_this_round": 24, "fit_by_arm": dict.fromkeys(ARMS, 12),
            "cumulative_fit_before": 219, "cumulative_fit_after": 243, "fit_failed": 0,
            "canary_f01_fit_included": 2, "pack_operations": {"fit": 0, "prediction": 0, "simulation": 0},
            "baseline_refit": 0, "old_model_load": 0, "old_model_predict": 0, "simulation": 0,
            "simulated_trades": 0, "nav_backtests": 0, "slippage_runs": 0,
            "binding": ctx["binding"], "binding_sha256": digest(ctx["binding"]), "runtime": ctx["runtime"],
            "ledger": ledger_id, "archive": archives, "verified_weight_sha_count": len(archives),
            "max_reloaded_prediction_abs_diff": max(row["reload_max_abs_diff"] for row in archives),
            "physical_prefix_checks": gate["physical_prefix_checks"],
            "upstream_add10_prefix_gate": gate["upstream_add10_prefix_gate"],
            "rank_policy": ctx["outer"]["rank_policy"], "retained_full_variation": ctx["retained"],
            "feature_names": FEATURES, "feature_count": len(FEATURES), "drop": list(ctx["outer"]["drop"]),
            "missing_indicators": 0, "train_target_clipped_only": [-10.0, 10.0], "oos_target_exact": True,
            "full_oos_keys": len(final), "sessions": final["D"].nunique(), "missing_output_cells": 0,
            "regimes": final.groupby("regime")["D"].nunique().to_dict(), "headlines": headlines,
            "historical_full_metric_csv_replay_abs_diff": parity, "weight_headlines": weight_heads,
            "baseline_denominator": "same FULL OOS keys and raw unclipped targets; ACT-034 trained in CORE",
            "folds": gate["folds"], "metrics_rows": len(metrics), "weight_rows": len(weights),
            "cleanup": {"status": "RUNTIME_CLEANUP_PENDING", "removed_bytes": 0},
            "flags": flags, **flags, "time_beijing": timestamp(),
        }
        paths["delivery"].mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".act041-pack-", dir=paths["batch"]) as temp:
            staged = [Path(temp) / name for name in OUTPUTS]
            e4.atomic_parquet(published, staged[0])
            pd.testing.assert_frame_equal(pd.read_parquet(staged[0]), published, check_exact=True)
            e4.atomic_csv(metrics, staged[1])
            e4.atomic_csv(weights, staged[2])
            receipt["delivery_files"] = {
                target.name: {**e4.identity(source), "path": str(target)}
                for target, source in zip(destination[:-1], staged[:-1], strict=True)
            }
            assert e4.identity(paths["ledger"]) == ledger_id
            e4.atomic_json(staged[3], receipt)
            for source, target in zip(staged, destination, strict=True):
                os.replace(source, target)
    return {key: receipt[key] for key in ("status", "fit_this_round", "cumulative_fit_after",
                                         "full_oos_keys", "headlines", "weight_headlines", "delivery_files")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    execute = commands.add_parser("run")
    execute.add_argument("--through-fold", type=int, choices=(1, 12), required=True)
    execute.add_argument("--threads", type=int, choices=(2,), default=2)
    commands.add_parser("pack")
    args = parser.parse_args()
    paths = paths_for(args.batch_root.resolve(), args.source_root.resolve())
    ctx = load_context(paths)
    if args.command == "preflight":
        result = preflight(ctx, paths)
    elif args.command == "run":
        result = run(ctx, paths, args.through_fold, args.threads)
    else:
        result = pack(ctx, paths)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


def preflight(ctx: dict, paths: dict) -> dict:
    assert not paths["ledger"].exists()
    folds = {}
    for fold in range(1, 13):
        train, test, _, _, split = fold_data(ctx, fold)
        target = train[e4.TARGET].to_numpy(dtype="float64")
        assert np.isfinite(target).all()
        folds[str(fold)] = {"train_rows": len(train), "oos_rows": len(test),
                            "fit_data_cutoff": int(split.fit_data_cutoff),
                            "first_test_D": int(split.test_first_D),
                            "clip_low": int((target < -10.0).sum()), "clip_high": int((target > 10.0).sum())}
    receipt = {"action_id": ACTION, "status": "PASS_NO_FIT", "fit": 0, "prediction": 0, "simulation": 0,
               "binding_sha256": digest(ctx["binding"]), "physical_prefix_checks": physical_prefix_checks(ctx),
               "upstream_add10_prefix_gate": ctx["add10_upstream_prefix"], "folds": folds,
               "full_oos_keys": len(ctx["oos"]), "retained_full_variation": ctx["retained"]}
    if paths["preflight"].exists():
        assert read_json(paths["preflight"]) == receipt
    else:
        e4.atomic_json(paths["preflight"], receipt)
    return receipt


if __name__ == "__main__":
    main()
