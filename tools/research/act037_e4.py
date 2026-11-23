#!/usr/bin/env python3
"""ACT-037 CORE25 robust-loss experiment with a strict 36-fit ledger."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


BASE20 = [
    "bar_close_pos", "pierce_white_recover", "pierce_yellow_recover", "close_vs_white_pp",
    "close_vs_yellow_pp", "drawdown_from_prior20_high_pp", "distance_from_rise_base_low_pp",
    "hold_rise_base_low", "upper_shadow_range_fraction", "upper_shadow_pct", "amplitude_pct",
    "prior5_highvol_bear", "prior5_highvol_bear_unrecovered", "worst_flagged_bear_prior5_pp",
    "prior_attack_runup_pp", "prior20_peak_relative_volume", "amount_ratio_20",
    "volume_today_over_prior20_mean", "prior20_volatility_pp", "J",
]
ADD10 = [
    "days_since_20d_vol_peak", "pullback_vol_decay_ratio", "white_yellow_spread_slope5",
    "struct_integrity_score", "post_attack_up_bar_ratio", "close_vs_keyk_mid_pp",
    "root_anchor_mid_dist_pp", "yellow_breach_recovery_state", "days_since_yellow_recovery",
    "keyk_low_hold_streak",
]
DROPPED = {
    "hold_rise_base_low",
    "prior5_highvol_bear_unrecovered",
    "volume_today_over_prior20_mean",
    "post_attack_up_bar_ratio",
    "prior5_highvol_bear",
}
FEATURES = [name for name in [*BASE20, *ADD10] if name not in DROPPED]
KEY = ["D", "ts_code"]
ARMS = ("E4A_LGBM_HUBER", "E4B_LGBM_L1", "E4C_HUBER_CLEAN")
ARM_LABELS = {
    "E4A_LGBM_HUBER": "E4A",
    "E4B_LGBM_L1": "E4B",
    "E4C_HUBER_CLEAN": "E4C",
}
FAILED_CANARY_KEY = (1, ARMS[0])
FAILED_CANARY_FIT_ID = "2edc7b8aa3ab0b25bb121dc8205c83db97db5670dbbc679f3e03f6a7f7cfe0cc"
FAILED_CANARY_RUNNER_SHA = "6eecb1c7547eb14b0c7eacf1b733ba782e3512617c0201716775fd5b38eebf2c"
SCORES = {
    "E4A_LGBM_HUBER": "score_e4a",
    "E4B_LGBM_L1": "score_e4b",
    "E4C_HUBER_CLEAN": "score_e4c",
}
BASELINE_SCORES = {
    "E2A": "score_e2a",
    "E2B": "score_e2b",
    "E3L2": "score_e3l2",
}
METRICS = [
    "rank_ic", "ndcg10",
    "t2_top5", "t2_top10", "t2_top20",
    "precision_top5", "precision_top10", "precision_top20",
    "clean_top5", "clean_top10", "clean_top20",
    "pure_tail_trap_top5", "pure_tail_trap_top10", "pure_tail_trap_top20",
]
EXPECTED_CORE_OOS = 40578
EXPECTED_SESSIONS = 120
EXPECTED_LOW_ABSORB = 18238
TARGET = "excess_t2_d1open"
TAIL = "excess_pure_tail_trap"
CLEAN = "excess_clean_winner"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def checked_identity(path: Path, expected: dict[str, Any]) -> None:
    assert path.is_file(), f"missing frozen input {path}"
    assert path.stat().st_size == int(expected["bytes"]), f"size changed {path}"
    assert sha256(path) == expected["sha256"], f"SHA-256 changed {path}"


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp" + path.suffix)
    frame.to_parquet(temporary, index=False, compression="zstd")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp" + path.suffix)
    frame.to_csv(temporary, index=False)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen source helper {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def runtime_paths(batch_root: Path, source_root: Path) -> dict[str, Path]:
    return {
        "batch": batch_root,
        "scope": batch_root / "work" / "ACT037_FROZEN_EXECUTION_SCOPE.json",
        "runtime": batch_root / "work" / "ACT037_RUNTIME_BOOTSTRAP.json",
        "act030": source_root / "ACT030_CODEX_PHASE2_E1_E2_20261123",
        "act034": source_root / "ACT034_CODEX_E3_ADD10_GATE_AND_24FIT_20261123",
        "act036": source_root / "ACT036_CODEX_0FIT_WEIGHT_IC_EXPORT_20261123",
        "act024": source_root / "ACT024_CODEX_1Y_LIQUID_BRIDGE_20261123",
        "weights": batch_root / "archive" / "weights",
        "execution": batch_root / "work" / "ACT037_EXECUTION",
        "delivery": batch_root / "delivery",
    }


def verify_outer_scope(paths: dict[str, Path]) -> dict[str, Any]:
    assert paths["scope"].is_file(), f"missing parent-frozen scope {paths['scope']}"
    scope = json.loads(paths["scope"].read_text(encoding="utf-8"))
    assert scope["action_id"] == "ACT-037" and scope["allow_fit"] is True
    assert scope["fit_limit"] == 36 and scope["baseline_refit"] == 0 and scope["simulate"] == 0
    assert scope["expected"] == {
        "CORE_OOS": EXPECTED_CORE_OOS,
        "folds": 12,
        "regimes": {"ICE": 27, "RANGE": 68, "REBOUND": 25},
        "sessions": EXPECTED_SESSIONS,
    }
    assert set(scope["drop"]) == DROPPED
    assert scope["flags"] == {
        "RESEARCH_ONLY": True, "STRICT_PIT": 0, "TRAIN_ADMITTED": 0,
        "NO_GO_BLOCKED": True, "production_allowed": False, "orders_sent": False,
        "buy_gate_updated": False, "knowledge_base_training_complete": False,
    }
    assert scope["policy"]["low_absorb"] == (
        "raw days_since_20d_vol_peak >= 1 AND raw amount_ratio_20 <= 1.2"
    )
    assert scope["policy"]["primary_fold_comparator"] == (
        "ACT030 E2B Top10 target arithmetic mean strict greater"
    )
    assert set(FEATURES) == set(scope["source"].get("E4_CORE25", FEATURES))
    assert len(FEATURES) == 25 and len(set(FEATURES)) == 25
    return scope


def add_runtime_vendor(paths: dict[str, Path]) -> dict[str, Any]:
    bootstrap = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    assert bootstrap["fit"] == bootstrap["prediction"] == bootstrap["simulation"] == 0
    vendor = paths["batch"] / "work" / "lightgbm_runtime"
    assert vendor.is_dir(), "parent-pinned LightGBM runtime is missing"
    sys.path.insert(0, str(vendor))
    import joblib
    import lightgbm
    import sklearn
    from lightgbm import LGBMRegressor
    from sklearn.linear_model import HuberRegressor

    assert lightgbm.__version__ == bootstrap["lightgbm"]
    assert lightgbm.__version__ == "4.7.0"
    assert Path(lightgbm.__file__).resolve().is_relative_to(vendor.resolve())
    assert sklearn.__version__ == bootstrap["sklearn"]
    assert joblib.__version__ == bootstrap["joblib"]
    assert HuberRegressor is not None

    scope = json.loads(paths["scope"].read_text(encoding="utf-8"))
    tree_params = {key: scope["objectives"]["E4A"][key] for key in (
        "n_estimators", "learning_rate", "num_leaves", "min_child_samples",
        "reg_lambda", "random_state", "deterministic", "force_col_wise",
    )}
    huber = LGBMRegressor(objective="huber", alpha=2.0, n_jobs=1, verbosity=-1, **tree_params)
    l1 = LGBMRegressor(objective="regression_l1", n_jobs=1, verbosity=-1, **tree_params)
    assert huber.get_params(deep=False)["objective"] == "huber"
    assert float(huber.get_params(deep=False)["alpha"]) == 2.0
    assert l1.get_params(deep=False)["objective"] == "regression_l1"
    assert int(huber.get_params(deep=False)["n_estimators"]) == 200
    assert int(l1.get_params(deep=False)["n_estimators"]) == 200
    return {
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "lightgbm": lightgbm.__version__,
        "lightgbm_path": str(Path(lightgbm.__file__).resolve()),
        "joblib": joblib.__version__,
        "sklearn": sklearn.__version__,
        "huber_alpha2_constructor": True,
        "regression_l1_constructor": True,
    }


def load_context(paths: dict[str, Path]):
    outer = verify_outer_scope(paths)
    runtime = add_runtime_vendor(paths)
    act030_dir = paths["act030"]
    act034_dir = paths["act034"]
    act036_dir = paths["act036"]
    act030 = load_module("act037_act030_frozen", act030_dir / "run_act030.py")
    act030_scope = act030.read_scope()

    act036 = load_module("act037_act036_frozen_reader", act036_dir / "work" / "export_act036.py")
    receipt_path, act034_receipt, act034_scope, gate = act036.anchor_inputs()
    assert act034_scope["action_id"] == "ACT-034"
    assert act034_scope["features_BASE20"] == BASE20
    assert act034_scope["features_ADD10"] == ADD10
    assert act034_scope["objectives"]["E3_LGBM_L2"] == act030_scope["model_parameters"]["tree"]
    assert act034_receipt["stage2"]["actual_fit"] == 24
    assert act034_receipt["stage2"]["simulation"] == 0
    assert act034_receipt["stage2"]["input_binding"]["source_manifest_sha256"] == (
        act030_scope["source"]["manifest_sha256"]
    )

    act034_scope_path = act034_dir / "ACT034_SCOPE.json"
    act034_scope_receipt = outer["source"]["ACT034_scope"]
    checked_identity(act034_scope_path, {
        "bytes": act034_scope_receipt["size"],
        "sha256": act034_scope_receipt["sha256"],
    })
    act034_runner = load_module("act037_act034_frozen_runner", act034_dir / "e3_experiment.py")
    context = act034_runner.frozen_context(act034_runner.read_scope(), require_gate=True)
    assert context["gate"]["report_sha256"] == act034_receipt["stage2"]["input_binding"]["phase1_report_sha256"]

    act036_run = paths["act036"] / "ACT036_0FIT_EXPORT_RECEIPT.json"
    checked_identity(act036_run, {
        "bytes": outer["source"]["ACT036_run"]["size"],
        "sha256": outer["source"]["ACT036_run"]["sha256"],
    })
    act036_receipt = json.loads(act036_run.read_text(encoding="utf-8"))
    assert act036_receipt["action_id"] == "ACT-036"
    assert act036_receipt["fit"] == 0
    assert act036_receipt["predict"] == 0
    assert act036_receipt["simulation"] == 0

    # ACT-036's reader is bound to the ACT-024 generation. It records the current
    # pointer as an observation and keeps all feature and label reads on frozen
    # projection shards even when the live pointer has advanced.
    reader, raw, splits, dates, oos_keys, provenance = act036.load_frozen(
        act034_scope, act034_receipt, gate, [*BASE20, *ADD10], ADD10
    )
    assert reader is not None
    assert provenance["ACT024_manifest"]["sha256"] == act030_scope["source"]["manifest_sha256"]
    assert provenance["ACT024_snapshot"]["generation_id"] == (
        act034_scope["source"]["snapshot"]["generation_id"]
    )
    assert len(raw) == 987203 and raw[KEY].duplicated().sum() == 0
    assert set([*KEY, *BASE20, *ADD10, TARGET, TAIL, CLEAN, "label_end_5"]).issubset(raw.columns)
    assert int((raw.ready & raw.D.isin(dates)).sum()) == 473307
    assert len(splits) == 12 and len(dates) == EXPECTED_SESSIONS
    assert len(oos_keys) == 473307 and oos_keys.D.nunique() == EXPECTED_SESSIONS
    assert int(oos_keys.core_mask.astype(bool).sum()) == EXPECTED_CORE_OOS
    assert not oos_keys.duplicated(KEY).any()
    regimes_path = Path(act030_scope["source"]["regimes_file"])
    regimes = pd.read_csv(regimes_path)
    raw["regime"] = raw.D.map(regimes.set_index("D").regime)
    assert raw.regime.notna().all()
    raw["relevance"] = act030.make_relevance(raw)
    assert int(raw.loc[raw.ready & raw.D.isin(dates), "relevance"].notna().sum()) == 473307

    core = raw.core_mask.astype(bool)
    const_evidence = {}
    for feature in ("hold_rise_base_low", "prior5_highvol_bear_unrecovered"):
        values = raw.loc[core, feature]
        unique = values.drop_duplicates()
        assert len(unique) == 1, f"expected CORE constant is not constant: {feature}"
        const_evidence[feature] = {
            "unique_values": 1,
            "value": float(unique.iloc[0]),
            "rows": int(len(values)),
        }

    # Feature percentile rank uses every D0 CORE key before warm-up, label
    # maturity, fold assignment or thinning. Natural NaNs survive for trees.
    raw_features = raw[[*KEY, *FEATURES]]
    core_features = raw_features.loc[core, FEATURES]
    core_days = raw.loc[core, "D"]
    ranked_core = core_features.groupby(core_days, sort=False).rank(
        pct=True, method="average"
    ).astype("float32")
    assert ranked_core.index.equals(core_features.index)
    assert ranked_core[FEATURES].isna().equals(core_features[FEATURES].isna())
    rank_matrix = pd.DataFrame(np.nan, index=raw.index, columns=FEATURES, dtype="float32")
    rank_matrix.loc[ranked_core.index, FEATURES] = ranked_core[FEATURES].to_numpy()
    assert rank_matrix.loc[core, FEATURES].isna().equals(raw.loc[core, FEATURES].isna())
    assert not rank_matrix.loc[~core, FEATURES].notna().any().any()

    raw["is_low_absorb"] = (
        pd.to_numeric(raw["days_since_20d_vol_peak"], errors="coerce").ge(1)
        & pd.to_numeric(raw["amount_ratio_20"], errors="coerce").le(1.2)
    )
    full_oos_core = raw.loc[
        raw.ready & raw.D.isin(dates) & raw.core_mask.astype(bool),
        KEY + ["relevance", "regime", TARGET, CLEAN, TAIL, "is_low_absorb",
               "days_since_20d_vol_peak", "amount_ratio_20"],
    ].copy()
    full_oos_core = full_oos_core.merge(
        oos_keys.loc[oos_keys.core_mask.astype(bool), KEY + ["fold", "core_mask"]],
        on=KEY, how="left", validate="one_to_one",
    )
    full_oos_core = full_oos_core.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert len(full_oos_core) == EXPECTED_CORE_OOS
    assert full_oos_core.D.nunique() == EXPECTED_SESSIONS
    assert not full_oos_core.duplicated(KEY).any()
    low_counts = full_oos_core.groupby("D", sort=True).is_low_absorb.sum().astype(int)
    assert len(low_counts) == EXPECTED_SESSIONS
    assert int(low_counts.sum()) == EXPECTED_LOW_ABSORB
    assert int(low_counts.min()) == 25 and int(low_counts.max()) == 391

    baseline, baseline_hashes = load_baseline_outputs(
        paths, act030_scope, act034_scope, act034_dir, oos_keys
    )
    pinned_pointer = outer["source"]["current_pointer_observed"]
    assert baseline.D.nunique() == EXPECTED_SESSIONS
    expected_core_keys = full_oos_core[KEY].reset_index(drop=True)
    actual_core_keys = oos_keys.loc[oos_keys.core_mask.astype(bool), KEY].sort_values(
        KEY, kind="mergesort"
    ).reset_index(drop=True)
    assert expected_core_keys.equals(actual_core_keys)

    by_fold = {}
    expected_fit_rows = []
    for split in splits.itertuples(index=False):
        fold = int(split.fold)
        train = reader.fit_rows(raw, split, core=True)
        evaluate = reader.eval_rows(raw, split, core=True)
        expected_fit_rows.append(len(train))
        assert train.core_mask.astype(bool).all() and evaluate.core_mask.astype(bool).all()
        assert train.label_end_5.le(int(split.fit_data_cutoff)).all()
        assert len(evaluate) == int(oos_keys.loc[
            oos_keys.fold.eq(fold) & oos_keys.core_mask.astype(bool)
        ].shape[0])
        by_fold[fold] = {"train_rows": int(len(train)), "core_oos_rows": int(len(evaluate))}
    assert expected_fit_rows == [16508, 18177, 18673, 19182, 19709, 20135,
                                 20806, 21638, 22525, 23441, 24291, 24707]
    assert sum(item["core_oos_rows"] for item in by_fold.values()) == EXPECTED_CORE_OOS
    baseline_rank_ic = historical_core_rank_ic(
        full_oos_core, baseline, expected={"E2B": -0.015492, "E3L2": -0.007336}
    )

    binding = {
        "action_id": "ACT-037",
        "outer_scope_sha256": sha256(paths["scope"]),
        "ACT024_manifest": provenance["ACT024_manifest"],
        "ACT024_snapshot": provenance["ACT024_snapshot"],
        "ACT024_frozen_projection_hashes": provenance["ACT024_source_input_SHA256"],
        "ACT024_split": provenance["split"],
        "ACT030_runner_sha256": sha256(act030_dir / "run_act030.py"),
        "ACT030_scope_sha256": sha256(act030_dir / "ACT030_SCOPE.json"),
        "ACT030_baseline_outputs": baseline_hashes,
        "ACT034_scope_sha256": sha256(act034_dir / "ACT034_SCOPE.json"),
        "ACT034_run_receipt_sha256": sha256(receipt_path),
        "ACT034_gate_sha256": sha256(
            act034_dir / "delivery" / "ACT034_E3_FEATURE_GATE_AND_CORR.json"
        ),
        "ACT034_oos_shards": [
            identity(act034_dir / "delivery" / "ACT034_OOS_F01-F06.parquet"),
            identity(act034_dir / "delivery" / "ACT034_OOS_F07-F12.parquet"),
        ],
        "ACT036_0FIT_receipt": identity(act036_run),
        "frozen_run_start_pointer_observation": pinned_pointer,
        "features": FEATURES,
        "dropped_features": sorted(DROPPED),
        "core_constant_evidence": const_evidence,
        "training_rows_by_fold": {str(fold): value["train_rows"] for fold, value in by_fold.items()},
        "core_oos_rows_by_fold": {str(fold): value["core_oos_rows"] for fold, value in by_fold.items()},
        "oos_days": EXPECTED_SESSIONS,
        "core_oos_keys": EXPECTED_CORE_OOS,
        "low_absorb_keys": int(low_counts.sum()),
        "low_absorb_day_count": int(low_counts.count()),
        "fit": 0,
        "prediction": 0,
        "simulation": 0,
    }
    json_binding = json.loads(json.dumps(binding, sort_keys=True, allow_nan=False))
    assert json_binding == binding
    return {
        "outer": outer,
        "runtime": runtime,
        "reader": reader,
        "raw": raw,
        "splits": splits,
        "test_dates": list(map(int, dates)),
        "ranks": rank_matrix,
        "core_oos": full_oos_core,
        "baseline": baseline,
        "baseline_hashes": baseline_hashes,
        "baseline_rank_ic_mean": baseline_rank_ic,
        "binding": binding,
        "by_fold": by_fold,
        "provenance": provenance,
        "current_pointer_observation": provenance["current_selector_pointer_observed"],
        "const_evidence": const_evidence,
        "low_counts": low_counts,
    }


def load_baseline_outputs(paths, act030_scope, act034_scope, act034_dir, oos_keys):
    baseline_desc = act034_scope["baseline"]["files"]
    base_full_desc = baseline_desc["ACT030_OOS_PREDICTIONS.parquet"]
    full_path = Path(base_full_desc["path"])
    checked_identity(full_path, {
        "bytes": base_full_desc["bytes"], "sha256": base_full_desc["sha256"]
    })
    base_full = pd.read_parquet(full_path)
    expected_base_columns = [
        "D", "ts_code", "fold", "core_mask", "relevance",
        "score_e1a", "score_e1b", "score_e2a", "score_e2b", "score_e2c",
    ]
    assert list(base_full.columns) == expected_base_columns
    assert len(base_full) == 473307 and not base_full.duplicated(KEY).any()

    act030_parts = []
    for filename in ("ACT030_OOS_F01-F06.parquet", "ACT030_OOS_F07-F12.parquet"):
        item = baseline_desc[filename]
        path = Path(item["path"])
        checked_identity(path, {"bytes": item["bytes"], "sha256": item["sha256"]})
        act030_parts.append(pd.read_parquet(path))
    base_sliced = pd.concat(act030_parts, ignore_index=True).sort_values(
        KEY, kind="mergesort"
    ).reset_index(drop=True)
    base_full_sorted = base_full.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert base_full_sorted.equals(base_sliced)

    e3_proofs = json.loads(
        (paths["act034"] / "delivery" / "ACT034_SUMMARY.json").read_text(encoding="utf-8")
    )["delivery_files"]
    act034_receipt = json.loads(
        (act034_dir / "delivery" / "ACT034_RUN_AND_CLEANUP_RECEIPT.json").read_text(encoding="utf-8")
    )
    receipted_e3 = {
        item["file"]: item for item in act034_receipt["completed_prior_uploads"]
    }
    e3_parts = []
    for filename in ("ACT034_OOS_F01-F06.parquet", "ACT034_OOS_F07-F12.parquet"):
        desc = receipted_e3[filename]
        assert desc["success"] is True and desc["parent_id"] == act034_receipt["delivery_folder"].rsplit("/", 1)[-1]
        path = Path(desc["path"])
        checked_identity(path, desc)
        assert (
            e3_proofs[filename]["bytes"] == desc["bytes"]
            and e3_proofs[filename]["sha256"] == desc["sha256"]
        ), f"ACT-034 summary and delivery receipt disagree for {filename}"
        e3_parts.append(pd.read_parquet(path))
    e3 = pd.concat(e3_parts, ignore_index=True).sort_values(
        KEY, kind="mergesort"
    ).reset_index(drop=True)
    expected_e3_columns = [
        "D", "ts_code", "fold", "core_mask", "relevance",
        "score_e2a", "score_e2b", "score_e3l2", "score_e3huber",
    ]
    assert list(e3.columns) == expected_e3_columns
    assert len(e3) == 473307 and not e3.duplicated(KEY).any()
    assert e3[KEY + ["fold", "core_mask", "relevance"]].equals(
        base_full_sorted[KEY + ["fold", "core_mask", "relevance"]]
    )
    for score_name in ("score_e2a", "score_e2b"):
        assert np.array_equal(
            e3[score_name].to_numpy(dtype="float64"),
            base_full_sorted[score_name].to_numpy(dtype="float64"),
        ), f"ACT-034 {score_name} no longer matches zero-fit ACT-030 output"
    assert e3[["score_e2a", "score_e2b", "score_e3l2"]].notna().all().all()
    assert np.isfinite(e3[["score_e2a", "score_e2b", "score_e3l2"]].to_numpy()).all()

    key_check = oos_keys.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    assert e3[KEY + ["fold", "core_mask"]].equals(key_check[KEY + ["fold", "core_mask"]])
    core = e3.loc[e3.core_mask.astype(bool)].copy().sort_values(KEY, kind="mergesort").reset_index(drop=True)
    full_core = base_full_sorted.loc[base_full_sorted.core_mask.astype(bool)].copy().sort_values(
        KEY, kind="mergesort"
    ).reset_index(drop=True)
    assert len(core) == len(full_core) == EXPECTED_CORE_OOS
    assert core.relevance.equals(full_core.relevance)
    result = core[KEY + ["fold", "core_mask", "relevance",
                         "score_e2a", "score_e2b", "score_e3l2"]].copy()
    assert not result[KEY].duplicated().any()
    hashes = {
        "ACT030_OOS_PREDICTIONS": identity(full_path),
        "ACT030_OOS_F01-F06": identity(Path(baseline_desc["ACT030_OOS_F01-F06.parquet"]["path"])),
        "ACT030_OOS_F07-F12": identity(Path(baseline_desc["ACT030_OOS_F07-F12.parquet"]["path"])),
        "ACT034_OOS_F01-F06": identity(Path(e3_proofs["ACT034_OOS_F01-F06.parquet"]["path"])),
        "ACT034_OOS_F07-F12": identity(Path(e3_proofs["ACT034_OOS_F07-F12.parquet"]["path"])),
        "ACT034_remote_upload_receipts": [
            {key: receipted_e3[name][key] for key in
             ("file", "id", "bytes", "sha256", "url", "parent_id", "success")}
            for name in ("ACT034_OOS_F01-F06.parquet", "ACT034_OOS_F07-F12.parquet")
        ],
        "ACT030_scope": identity(paths["act030"] / "ACT030_SCOPE.json"),
        "ACT034_summary": identity(paths["act034"] / "delivery" / "ACT034_SUMMARY.json"),
    }
    return result, hashes


def preflight(args) -> None:
    paths = runtime_paths(args.batch_root, args.source_root)
    ctx = load_context(paths)
    synthetic = synthetic_pack_check(ctx["outer"])
    events = read_events(paths["execution"] / "ACT037_EVENTS.jsonl")
    starts = [event for event in events if event["state"] == "FIT_STARTED"]
    output = {
        "status": "PASS_NO_FIT" if not starts else "PASS_NO_NEW_FIT_PREFLIGHT",
        "action_id": "ACT-037",
        "fit_this_command": 0,
        "prediction_this_command": 0,
        "simulation": 0,
        "fit_started_prior": len(starts),
        "fit_completed_prior": sum(event["state"] == "FIT_COMPLETED" for event in events),
        "core_oos_keys": len(ctx["core_oos"]),
        "core_oos_sessions": ctx["core_oos"].D.nunique(),
        "baseline_core_rank_ic_mean": ctx["baseline_rank_ic_mean"],
        "current_pointer_observation": ctx["current_pointer_observation"],
        "low_absorb_keys": ctx["binding"]["low_absorb_keys"],
        "low_absorb_mean_daily_candidates": (
            ctx["binding"]["low_absorb_keys"] / EXPECTED_SESSIONS
        ),
        "low_absorb_min_daily_candidates": int(ctx["low_counts"].min()),
        "low_absorb_max_daily_candidates": int(ctx["low_counts"].max()),
        "regimes": ctx["raw"].loc[
            ctx["raw"].ready & ctx["raw"].D.isin(ctx["test_dates"]) & ctx["raw"].core_mask,
            ["D", "regime"],
        ].drop_duplicates("D").groupby("regime").D.nunique().to_dict(),
        "folds": ctx["by_fold"],
        "feature_count": len(FEATURES),
        "feature_order": FEATURES,
        "core_constant_dropped": ctx["const_evidence"],
        "rank_policy": ctx["outer"]["rank_policy"],
        "source_binding": ctx["binding"],
        "runtime": ctx["runtime"],
        "flags": ctx["outer"]["flags"],
        "synthetic_zero_fit_pack_check": synthetic,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all(event.get("action_id") == "ACT-037" for event in events)
    return events


def append_event(path: Path, state: str, **fields) -> dict[str, Any]:
    event = {"action_id": "ACT-037", "state": state,
             "at": datetime.now().astimezone().isoformat(), **fields}
    payload = (json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("short ACT-037 event ledger write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps(event, ensure_ascii=False, sort_keys=True), flush=True)
    return event


def event_states(events: list[dict[str, Any]], acknowledged_failed_fit: str | None = None
                 ) -> dict[tuple[int, str], dict[str, dict[str, Any]]]:
    states: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    for event in events:
        if event.get("state") not in {"FIT_STARTED", "FIT_COMPLETED", "FIT_FAILED"}:
            continue
        key = (int(event["fold"]), str(event["arm"]))
        stage = event["state"]
        assert stage not in states.setdefault(key, {}), f"duplicate {stage} event for {key}"
        states[key][stage] = event
    for key, state in states.items():
        assert "FIT_STARTED" in state, f"terminal model event without FIT_STARTED: {key}"
        assert not ("FIT_COMPLETED" in state and "FIT_FAILED" in state)
        if "FIT_STARTED" in state and not ({"FIT_COMPLETED", "FIT_FAILED"} & set(state)):
            raise RuntimeError(f"FIT_STARTED without terminal event, refusing replay of {key}")
        if "FIT_FAILED" in state and (
            key != FAILED_CANARY_KEY or acknowledged_failed_fit != FAILED_CANARY_FIT_ID
        ):
            raise RuntimeError(f"FIT_FAILED freezes ACT-037 continuation at {key}")
    started = [event for event in events if event["state"] == "FIT_STARTED"]
    assert len(started) == len({(event["fold"], event["arm"]) for event in started})
    assert len(started) <= 36, "36-FIT ceiling exceeded"
    if acknowledged_failed_fit is not None:
        assert acknowledged_failed_fit == FAILED_CANARY_FIT_ID
        failed_canary = states[FAILED_CANARY_KEY]
        assert set(failed_canary) == {"FIT_STARTED", "FIT_FAILED"}
        assert failed_canary["FIT_STARTED"]["ordinal"] == 1
        assert failed_canary["FIT_FAILED"]["error_type"] == "AssertionError"
        for event in failed_canary.values():
            assert event["fit_id"] == FAILED_CANARY_FIT_ID
            assert event["runner_sha256"] == FAILED_CANARY_RUNNER_SHA
    return states


def fold_split(splits: pd.DataFrame, fold: int):
    rows = splits.loc[splits.fold.eq(fold)]
    assert len(rows) == 1
    return next(rows.itertuples(index=False))


def tree_parameters(scope: dict[str, Any], arm: str, threads: int) -> dict[str, Any]:
    locked = scope["objectives"][arm]
    keys = (
        "n_estimators", "learning_rate", "num_leaves", "min_child_samples",
        "reg_lambda", "random_state", "deterministic", "force_col_wise",
    )
    result = {key: locked[key] for key in keys}
    result.update({"n_jobs": threads, "verbosity": -1})
    if arm == "E4A":
        result.update({"objective": "huber", "alpha": 2.0})
    elif arm == "E4B":
        result.update({"objective": "regression_l1"})
    else:
        raise AssertionError(f"unknown E4 tree arm {arm}")
    assert result["n_estimators"] == 200 and result["learning_rate"] == 0.045
    assert result["num_leaves"] == 15 and result["min_child_samples"] == 100
    assert result["reg_lambda"] == 4 and result["random_state"] == 20261123
    return result


def make_model(arm: str, scope: dict[str, Any], threads: int):
    if arm in ("E4A", "E4B"):
        from lightgbm import LGBMRegressor
        return LGBMRegressor(**tree_parameters(scope, arm, threads))
    if arm == "E4C":
        from sklearn.linear_model import HuberRegressor
        params = scope["objectives"]["E4C"]
        assert params["missing_indicators"] == 0 and params["alpha"] == 10.0
        return HuberRegressor(
            alpha=10.0,
            epsilon=float(params["epsilon"]),
            max_iter=int(params["max_iter"]),
            tol=float(params["tol"]),
        )
    raise AssertionError(f"unknown ACT-037 arm {arm}")


def feature_matrices(ctx, fold: int):
    reader = ctx["reader"]
    raw = ctx["raw"]
    split = fold_split(ctx["splits"], fold)
    train = reader.fit_rows(raw, split, core=True)
    evaluate = reader.eval_rows(raw, split, core=True)
    assert train.core_mask.astype(bool).all() and evaluate.core_mask.astype(bool).all()
    assert train.label_end_5.le(int(split.fit_data_cutoff)).all()
    assert len(train) == ctx["by_fold"][fold]["train_rows"]
    assert len(evaluate) == ctx["by_fold"][fold]["core_oos_rows"]
    x_train = ctx["ranks"].loc[train.index, FEATURES].copy()
    x_eval = ctx["ranks"].loc[evaluate.index, FEATURES].copy()
    assert list(x_train.columns) == FEATURES and list(x_eval.columns) == FEATURES
    assert x_train.index.equals(train.index) and x_eval.index.equals(evaluate.index)
    assert not (set(x_train.columns) & DROPPED) and not (set(x_eval.columns) & DROPPED)
    return train, evaluate, x_train, x_eval, split


def huber_impute(train: pd.DataFrame, evaluate: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    medians = {}
    for name in FEATURES:
        values = train[name].to_numpy(dtype="float64")
        finite = values[np.isfinite(values)]
        assert len(finite) > 0, f"no training median exists for feature {name}"
        medians[name] = float(np.median(finite))
    x_train = train[FEATURES].fillna(pd.Series(medians)).astype("float64")
    x_eval = evaluate[FEATURES].fillna(pd.Series(medians)).astype("float64")
    assert list(x_train.columns) == list(x_eval.columns) == FEATURES
    assert np.isfinite(x_train.to_numpy()).all() and np.isfinite(x_eval.to_numpy()).all()
    assert x_train.shape[1] == 25 and x_eval.shape[1] == 25
    return x_train, x_eval, medians


def model_paths(paths: dict[str, Path], fold: int, arm: str) -> tuple[Path, Path]:
    label = ARM_LABELS[arm]
    return (
        paths["weights"] / f"ACT037_F{fold:02d}_{label}.joblib",
        paths["execution"] / f"ACT037_SCORE_F{fold:02d}_{label}.parquet",
    )


def score_completed(paths, state, evaluate, fold: int, arm: str) -> pd.DataFrame:
    weight_path, score_path = model_paths(paths, fold, arm)
    done = state["FIT_COMPLETED"]
    checked_identity(weight_path, {
        "bytes": done["weight_bytes"],
        "sha256": done["weight_sha256"],
    })
    checked_identity(score_path, {
        "bytes": done["prediction_bytes"],
        "sha256": done["prediction_sha256"],
    })
    score = pd.read_parquet(score_path)
    assert list(score.columns) == [*KEY, "score"]
    assert score[KEY].reset_index(drop=True).equals(evaluate[KEY].reset_index(drop=True))
    assert np.isfinite(score.score.to_numpy(dtype="float64")).all()
    return score


def fit_one(ctx, paths, events_path, fold: int, arm: str, threads: int,
            binding_hash: str, states):
    train, evaluate, x_train, x_eval, split = feature_matrices(ctx, fold)
    model_label = ARM_LABELS[arm]
    medians = None
    if model_label == "E4C":
        x_train, x_eval, medians = huber_impute(x_train, x_eval)
    target = train[TARGET].to_numpy(dtype="float64")
    assert np.isfinite(target).all()
    fit_target = np.clip(target, -10.0, 10.0) if model_label == "E4A" else target.copy()
    clip_low_count = int((target < -10.0).sum()) if model_label == "E4A" else 0
    clip_high_count = int((target > 10.0).sum()) if model_label == "E4A" else 0
    assert len(fit_target) == len(x_train)
    scope = ctx["outer"]
    model = make_model(model_label, scope, threads)
    weight_path, score_path = model_paths(paths, fold, arm)
    assert not weight_path.exists() and not score_path.exists(), (
        f"unbound checkpoint exists for FIT {fold}/{arm}"
    )
    completed_started = [
        item for item in read_events(events_path) if item["state"] == "FIT_STARTED"
    ]
    assert len(completed_started) < 36
    assert (fold, arm) not in states
    expected_oos_keys = evaluate[KEY].reset_index(drop=True)
    assert expected_oos_keys.equals(expected_oos_keys.sort_values(KEY, kind="mergesort"))
    fit_id = hashlib.sha256(
        f"{binding_hash}|{fold}|{arm}".encode("utf-8")
    ).hexdigest()
    append_event(
        events_path, "FIT_STARTED",
        fit_id=fit_id, ordinal=len(completed_started) + 1, fold=fold, arm=arm,
        model_class=type(model).__name__, train_rows=len(train), core_oos_rows=len(evaluate),
        train_first_D=int(train.D.min()), train_last_D=int(train.D.max()),
        fit_data_cutoff=int(split.fit_data_cutoff), first_test_D=int(split.test_first_D),
        feature_names=list(FEATURES), missing_indicators=0,
        train_medians=medians,
        target_clip={"minimum": -10.0, "maximum": 10.0, "fit_only": True}
        if model_label == "E4A" else None,
        target_clip_counts={"below_minus_10": clip_low_count,
                            "above_plus_10": clip_high_count},
        params=model.get_params(deep=False),
        input_binding_sha256=binding_hash, runner_sha256=sha256(Path(__file__)),
    )
    started = time.perf_counter()
    try:
        model.fit(x_train, fit_target)
        predicted_before = np.asarray(model.predict(x_eval), dtype="float64")
        assert predicted_before.shape == (len(evaluate),)
        assert np.isfinite(predicted_before).all()
        if model_label == "E4A":
            booster_params = model.booster_.params
            assert booster_params.get("objective") == "huber", booster_params
            assert float(booster_params.get("alpha")) == 2.0, booster_params
        elif model_label == "E4B":
            assert model.booster_.params.get("objective") == "regression_l1"
        else:
            assert type(model).__name__ == "HuberRegressor"
            assert len(model.coef_) == 25 and model.n_features_in_ == 25
            assert not any(name.endswith("_isna") for name in FEATURES)

        weight_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_weight = weight_path.with_suffix(weight_path.suffix + ".tmp")
        import joblib
        model_artifact = (
            {
                "model": model,
                "feature_names": list(FEATURES),
                "train_medians": medians,
                "fold": fold,
                "arm": arm,
            }
            if model_label == "E4C" else model
        )
        joblib.dump(model_artifact, temporary_weight, compress=3)
        with temporary_weight.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_weight, weight_path)
        restored_artifact = joblib.load(weight_path)
        if model_label == "E4C":
            assert restored_artifact["feature_names"] == FEATURES
            assert restored_artifact["fold"] == fold and restored_artifact["arm"] == arm
            assert restored_artifact["train_medians"] == medians
            restored = restored_artifact["model"]
        else:
            restored = restored_artifact
        assert type(restored) is type(model)
        predicted_after = np.asarray(restored.predict(x_eval), dtype="float64")
        assert predicted_after.shape == predicted_before.shape
        max_abs_diff = (
            float(np.max(np.abs(predicted_after - predicted_before)))
            if len(predicted_before) else 0.0
        )
        assert max_abs_diff == 0.0 and np.array_equal(predicted_after, predicted_before)

        if model_label in ("E4A", "E4B"):
            gain = model.booster_.feature_importance(importance_type="gain")
            split = model.booster_.feature_importance(importance_type="split")
            assert model.booster_.feature_name() == FEATURES
            assert len(gain) == len(split) == 25
            assert np.isfinite(gain).all() and (gain >= 0).all() and (split >= 0).all()
            importance = {
                feature: {
                    "gain": float(gain[index]),
                    "gain_share": float(gain[index] / gain.sum()) if gain.sum() > 0 else None,
                    "split": int(split[index]),
                    "split_share": float(split[index] / split.sum()) if split.sum() > 0 else None,
                }
                for index, feature in enumerate(FEATURES)
            }
            coefficients = None
        else:
            importance = None
            coefficients = {
                feature: float(coefficient)
                for feature, coefficient in zip(FEATURES, restored.coef_, strict=True)
            }
        score = evaluate[KEY].reset_index(drop=True).copy()
        score["score"] = predicted_after
        atomic_parquet(score, score_path)
        reread = pd.read_parquet(score_path)
        assert reread[KEY].equals(score[KEY])
        assert np.array_equal(reread.score.to_numpy(dtype="float64"), predicted_after)
        weight_id = identity(weight_path)
        score_id = identity(score_path)
        append_event(
            events_path, "FIT_COMPLETED",
            fit_id=fit_id, fold=fold, arm=arm,
            elapsed_s=round(time.perf_counter() - started, 4),
            weight_file=str(weight_path), weight_bytes=weight_id["bytes"],
            weight_sha256=weight_id["sha256"],
            prediction_file=str(score_path), prediction_bytes=score_id["bytes"],
            prediction_sha256=score_id["sha256"],
            prediction_calls=2, model_load_calls=1,
            model_reload_prediction_max_abs_diff=max_abs_diff,
            target_clip_counts={"below_minus_10": clip_low_count,
                                "above_plus_10": clip_high_count},
            importance=importance, huber_coefficients=coefficients,
            runner_sha256=sha256(Path(__file__)),
        )
    except BaseException as error:
        append_event(
            events_path, "FIT_FAILED", fit_id=fit_id, fold=fold, arm=arm,
            error_type=type(error).__name__, error=str(error)[:1000],
            runner_sha256=sha256(Path(__file__)),
        )
        raise
    return score


def collect_completed_scores(ctx, paths, events):
    states = event_states(events)
    rows = []
    for fold in range(1, 13):
        _, evaluate, _, _, _ = feature_matrices(ctx, fold)
        fold_scores = {}
        for arm in ARMS:
            state = states.get((fold, arm))
            assert state and "FIT_COMPLETED" in state, f"missing completed fold {fold} arm {arm}"
            score = score_completed(paths, state, evaluate, fold, arm)
            fold_scores[arm] = score.rename(columns={"score": SCORES[arm]})
        rows.append(wide_fold_scores(evaluate, fold, fold_scores))
    return states, pd.concat(rows, ignore_index=True)


def wide_fold_scores(evaluate: pd.DataFrame, fold: int,
                     fold_scores: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join each arm by its already-validated exact key order into one OOS row."""
    expected_keys = evaluate[KEY].reset_index(drop=True)
    assert not expected_keys.duplicated(KEY).any()
    result = expected_keys.copy()
    result["fold"] = int(fold)
    for arm in ARMS:
        score = fold_scores[arm]
        score_keys = score[KEY].reset_index(drop=True)
        assert score_keys.equals(expected_keys), f"{arm} keys/order differ in fold {fold}"
        column = SCORES[arm]
        assert list(score.columns) == [*KEY, column]
        values = score[column].to_numpy(dtype="float64")
        assert len(values) == len(result)
        assert np.isfinite(values).all()
        result[column] = values
    assert len(result) == len(evaluate) and not result.duplicated(KEY).any()
    assert list(result.columns) == [*KEY, "fold", *(SCORES[arm] for arm in ARMS)]
    return result


def run(args) -> None:
    paths = runtime_paths(args.batch_root, args.source_root)
    ctx = load_context(paths)
    paths["execution"].mkdir(parents=True, exist_ok=True)
    events_path = paths["execution"] / "ACT037_EVENTS.jsonl"
    binding_path = paths["execution"] / "ACT037_INPUT_BINDING.json"
    binding = ctx["binding"]
    binding_hash = hashlib.sha256(json.dumps(
        binding, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")).hexdigest()
    if binding_path.exists():
        old = json.loads(binding_path.read_text(encoding="utf-8"))
        assert old["binding"] == binding and old["binding_sha256"] == binding_hash
    else:
        atomic_json(binding_path, {"binding": binding, "binding_sha256": binding_hash})

    lock_path = paths["execution"] / "RUN.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        events = read_events(events_path)
        acknowledged = args.acknowledge_failed_fit
        states = event_states(events, acknowledged)
        if acknowledged is not None:
            assert states[FAILED_CANARY_KEY]["FIT_STARTED"]["input_binding_sha256"] == binding_hash
            assert not any(path.exists() for path in model_paths(paths, *FAILED_CANARY_KEY))
        done_folds = {
            fold for fold in range(1, 13)
            if all((fold, arm) in states for arm in ARMS)
        }
        partial_folds = {
            fold for fold in range(1, 13)
            if any((fold, arm) in states for arm in ARMS) and fold not in done_folds
        }
        if partial_folds and acknowledged is None:
            raise RuntimeError(f"partial fold checkpoints block new FITs: {sorted(partial_folds)}")
        remaining = [fold for fold in range(1, 13) if fold not in done_folds]
        if args.max_folds is not None:
            assert args.max_folds > 0
            remaining = remaining[:args.max_folds]
        for fold in remaining:
            for arm in ARMS:
                events = read_events(events_path)
                states = event_states(events, acknowledged)
                if (fold, arm) in states:
                    continue
                fit_one(
                    ctx, paths, events_path, fold, arm, args.threads,
                    binding_hash, states,
                )
        events = read_events(events_path)
        states = event_states(events, acknowledged)
        complete = len([event for event in events if event["state"] == "FIT_COMPLETED"])
        started = len([event for event in events if event["state"] == "FIT_STARTED"])
        failed = int(acknowledged is not None)
        assert complete + failed == started <= 36
        if complete < 36:
            status = ("FIT_BUDGET_EXHAUSTED_MISSING_F01_E4A"
                      if started == 36 else "PARTIAL_CANARY")
            print(json.dumps({
                "status": status,
                "action_id": "ACT-037",
                "fit_started": started,
                "fit_completed": complete,
                "fit_failed": failed,
                "failed_fit_id": acknowledged,
                "fit_limit": 36,
                "completed_folds": [
                    fold for fold in range(1, 13)
                    if all("FIT_COMPLETED" in states.get((fold, arm), {}) for arm in ARMS)
                ],
                "simulation": 0,
            }, ensure_ascii=False, sort_keys=True), flush=True)
            return
        assert complete == 36 and len(states) == 36
        _states, prediction = collect_completed_scores(ctx, paths, events)
        final = assemble_core_output(ctx, prediction)
        daily, paired = all_metrics(ctx, final)
        weights = weight_summary(states, scope=ctx["outer"])
        paths["delivery"].mkdir(parents=True, exist_ok=True)
        oos_path = paths["delivery"] / "ACT037_E4_OOS_CORE.parquet"
        metrics_path = paths["delivery"] / "ACT037_E4_METRICS.csv"
        weights_path = paths["delivery"] / "ACT037_E4_WEIGHT_SUMMARY.csv"
        for output_path in (oos_path, metrics_path, weights_path):
            assert not output_path.exists(), f"refusing to overwrite existing result {output_path}"
        atomic_parquet(final, oos_path)
        atomic_csv(pd.concat([daily, paired], ignore_index=True), metrics_path)
        atomic_csv(weights, weights_path)
        verify_final_artifacts(ctx, final, daily, paired, weights, paths)
        receipt = make_receipt(ctx, states, events_path, binding_hash, paths,
                               final, daily, paired, weights)
        receipt_path = paths["delivery"] / "ACT037_RUN_AND_CLEANUP_RECEIPT.json"
        assert not receipt_path.exists()
        atomic_json(receipt_path, receipt)
        print(json.dumps({
            "status": "PASS_RUN_PACK",
            "action_id": "ACT-037",
            "fit_completed": complete,
            "core_oos_keys": len(final),
            "sessions": final.D.nunique(),
            "low_absorb_keys": int(final.is_low_absorb.sum()),
            "max_reload_abs_diff": max(
                event["model_reload_prediction_max_abs_diff"]
                for event in events if event["state"] == "FIT_COMPLETED"
            ),
            "delivery_files": {
                path.name: identity(path) for path in (oos_path, metrics_path, weights_path, receipt_path)
            },
            "simulation": 0,
            "flags": ctx["outer"]["flags"],
        }, ensure_ascii=False, sort_keys=True, allow_nan=False), flush=True)


def assemble_core_output(ctx, prediction: pd.DataFrame) -> pd.DataFrame:
    core = ctx["core_oos"].merge(
        ctx["baseline"][KEY + list(BASELINE_SCORES.values())],
        on=KEY, how="left", validate="one_to_one",
    )
    core = core.merge(
        prediction[KEY + [SCORES[arm] for arm in ARMS]],
        on=KEY, how="left", validate="one_to_one",
    )
    assert len(core) == EXPECTED_CORE_OOS and core.fold.notna().all()
    assert core[[SCORES[arm] for arm in ARMS]].notna().all().all()
    assert core[list(BASELINE_SCORES.values())].notna().all().all()
    assert core.core_mask.astype(bool).all()
    core = core.sort_values(KEY, kind="mergesort").reset_index(drop=True)
    columns = [
        "D", "ts_code", "fold", "core_mask", "relevance",
        "score_e4a", "score_e4b", "score_e4c",
        "score_e2a", "score_e2b", "score_e3l2",
        "is_low_absorb", TARGET, CLEAN, TAIL, "regime",
        "days_since_20d_vol_peak", "amount_ratio_20",
    ]
    core = core[columns]
    assert list(core.columns) == columns and not core.duplicated(KEY).any()
    assert core.D.nunique() == EXPECTED_SESSIONS
    assert int(core.is_low_absorb.sum()) == EXPECTED_LOW_ABSORB
    return core


def dcg(relevance: np.ndarray, k: int = 10) -> float:
    gains = np.asarray([0.0, 1.0, 3.0, 7.0], dtype="float64")[relevance.astype(int)]
    gains = gains[:k]
    return float(np.sum(gains / np.log2(np.arange(2, len(gains) + 2)))) if len(gains) else 0.0


def rank_ic(target: pd.Series, score: pd.Series) -> float | None:
    target = pd.to_numeric(target, errors="coerce")
    score = pd.to_numeric(score, errors="coerce")
    valid = (
        target.notna() & score.notna()
        & np.isfinite(target.to_numpy(dtype="float64"))
        & np.isfinite(score.to_numpy(dtype="float64"))
    )
    target = target.loc[valid]
    score = score.loc[valid]
    assert target.index.equals(score.index)
    if len(target) < 2:
        return None
    value = target.corr(score, method="spearman")
    return float(value) if pd.notna(value) else None


def historical_core_rank_ic(
    core_oos: pd.DataFrame, baseline: pd.DataFrame, expected: dict[str, float]
) -> dict[str, float]:
    # This reversed-order witness guards the common error of sorting scores for
    # ranking and then pairing them positionally with the unsorted target.
    witness_target = pd.Series([1.0, 2.0, 3.0])
    witness_score = pd.Series([3.0, 2.0, 1.0])
    assert rank_ic(witness_target, witness_score) == -1.0

    merged = core_oos.merge(
        baseline[KEY + ["score_e2b", "score_e3l2"]],
        on=KEY, how="left", validate="one_to_one",
    )
    result = {}
    for name, column in (("E2B", "score_e2b"), ("E3L2", "score_e3l2")):
        values = [
            rank_ic(group[TARGET], group[column])
            for _, group in merged.groupby("D", sort=True)
        ]
        finite = [value for value in values if value is not None and np.isfinite(value)]
        assert len(finite) == EXPECTED_SESSIONS
        mean = float(np.mean(finite))
        assert math.isclose(mean, expected[name], abs_tol=0.00001), (
            f"CORE rank-IC implementation no longer matches frozen ACT-030/034 "
            f"baseline for {name}: {mean}"
        )
        result[name] = mean
    return result


def daily_metrics(group: pd.DataFrame, arm: str, scope: str, day: int,
                  fold: int, regime: str) -> dict[str, Any]:
    score_col = SCORES.get(arm, BASELINE_SCORES.get(arm))
    assert score_col is not None
    valid = np.isfinite(group[score_col].to_numpy(dtype="float64"))
    selected = group.loc[valid].copy()
    selected["_score"] = selected[score_col].to_numpy(dtype="float64")
    selected = selected.sort_values(
        ["_score", "ts_code"], ascending=[False, True], kind="mergesort"
    )
    n = len(selected)
    row = {
        "row_type": "DAILY", "eval_scope": scope, "arm": arm,
        "comparison_baseline": "", "D": day, "fold": fold, "regime": regime,
        "candidate_count": n, "sessions": 1,
    }
    if n == 0:
        row.update({metric: None for metric in METRICS})
        return row
    ic = rank_ic(group.loc[valid, TARGET], group.loc[valid, score_col])
    grades = selected.relevance.to_numpy(dtype="int64")
    denominator = dcg(np.sort(grades)[::-1], 10)
    row["rank_ic"] = ic
    row["ndcg10"] = float(dcg(grades, 10) / denominator) if denominator > 0 else None
    for k in (5, 10, 20):
        top = selected.head(min(k, n))
        row[f"t2_top{k}"] = float(top[TARGET].mean())
        row[f"precision_top{k}"] = float(top.relevance.ge(2).mean())
        row[f"clean_top{k}"] = float(top[CLEAN].mean())
        row[f"pure_tail_trap_top{k}"] = float(top[TAIL].mean())
    return row


def group_summary(rows: pd.DataFrame, group_cols: list[str], level: str) -> list[dict[str, Any]]:
    id_cols = {"row_type", "eval_scope", "arm", "comparison_baseline",
               "D", "fold", "regime", "candidate_count", "sessions"}
    output = []
    grouped = rows.groupby(group_cols, dropna=False, sort=True) if group_cols else [((), rows)]
    for key, part in grouped:
        values = {}
        if group_cols:
            key = key if isinstance(key, tuple) else (key,)
            values = dict(zip(group_cols, key))
        row = {
            "row_type": level, **values,
            "candidate_count": float(part.candidate_count.mean()),
            "candidate_count_total": int(part.candidate_count.sum()),
            "sessions": int(part.D.nunique()),
        }
        for metric in METRICS:
            sample = pd.to_numeric(part[metric], errors="coerce").dropna()
            row[metric] = float(sample.mean()) if len(sample) else None
            row[f"{metric}_defined_days"] = int(len(sample))
        if "rank_ic" in METRICS:
            sample = pd.to_numeric(part["rank_ic"], errors="coerce").dropna().to_numpy()
            sd = sample.std(ddof=1) if len(sample) > 1 else np.nan
            row["rank_ic_ir"] = float(sample.mean() / sd) if np.isfinite(sd) and sd > 0 else None
        output.append(row)
    return output


def all_metrics(ctx, final: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(ctx["test_dates"])
    regime_by_day = ctx["raw"].drop_duplicates("D").set_index("D").regime.to_dict()
    fold_by_day = {}
    for split in ctx["splits"].itertuples(index=False):
        for day in map(int, str(split.test_Ds).split("|")):
            assert day not in fold_by_day
            fold_by_day[day] = int(split.fold)
    assert set(dates) == set(fold_by_day) == set(regime_by_day).intersection(dates)
    daily_records = []
    for scope in ("CORE", "CORE_LOW_ABSORB"):
        pool = final if scope == "CORE" else final.loc[final.is_low_absorb.astype(bool)]
        for day in dates:
            group = pool.loc[pool.D.eq(day)]
            for arm in (*ARMS, *BASELINE_SCORES.keys()):
                daily_records.append(daily_metrics(
                    group, arm, scope, day, fold_by_day[day], str(regime_by_day[day])
                ))
    daily = pd.DataFrame(daily_records)
    summary = []
    for scope in ("CORE", "CORE_LOW_ABSORB"):
        part = daily.loc[daily.eval_scope.eq(scope)]
        keys = ["eval_scope", "arm"]
        summary.extend(group_summary(part, keys, "ALL_120D"))
        summary.extend(group_summary(part, [*keys, "fold"], "FOLD"))
        summary.extend(group_summary(part, [*keys, "regime"], "REGIME"))
    rows = [*daily.to_dict("records"), *summary]
    direct = pd.DataFrame(rows)
    paired = paired_metrics(daily)
    return direct, paired


def paired_metrics(daily: pd.DataFrame) -> pd.DataFrame:
    daily_records = daily.to_dict("records")
    lookup = {
        (str(row["eval_scope"]), str(row["arm"]), int(row["D"])): row
        for row in daily_records
    }
    pair_rows = []
    for scope in ("CORE", "CORE_LOW_ABSORB"):
        for arm in ARMS:
            for baseline in BASELINE_SCORES:
                for day in sorted(
                    int(value) for value in daily.loc[daily.eval_scope.eq(scope), "D"].unique()
                ):
                    left = lookup[(scope, arm, day)]
                    right = lookup[(scope, baseline, day)]
                    deltas = {
                        metric: (
                            float(left[metric]) - float(right[metric])
                            if pd.notna(left.get(metric)) and pd.notna(right.get(metric)) else None
                        )
                        for metric in METRICS
                    }
                    pair_rows.append({
                        "row_type": "PAIRED_DAILY", "eval_scope": scope, "arm": arm,
                        "comparison_baseline": baseline, "D": day,
                        "fold": int(left["fold"]), "regime": str(left["regime"]),
                        "candidate_count": int(left["candidate_count"]),
                        "baseline_candidate_count": int(right["candidate_count"]),
                        "sessions": 1, **deltas,
                    })
    paired_daily = pd.DataFrame(pair_rows)
    result = [*pair_rows]
    for scope in ("CORE", "CORE_LOW_ABSORB"):
        scoped = paired_daily.loc[paired_daily.eval_scope.eq(scope)]
        groups = [
            ("PAIRED_ALL_120D", ["eval_scope", "arm", "comparison_baseline"]),
            ("PAIRED_FOLD", ["eval_scope", "arm", "comparison_baseline", "fold"]),
            ("PAIRED_REGIME", ["eval_scope", "arm", "comparison_baseline", "regime"]),
        ]
        for level, keys in groups:
            for group_key, part in scoped.groupby(keys, sort=True, dropna=False):
                group_key = group_key if isinstance(group_key, tuple) else (group_key,)
                row = {"row_type": level, **dict(zip(keys, group_key))}
                row["candidate_count"] = float(part.candidate_count.mean())
                row["sessions"] = int(part.D.nunique())
                for metric in METRICS:
                    sample = pd.to_numeric(part[metric], errors="coerce").dropna()
                    row[metric] = float(sample.mean()) if len(sample) else None
                    row[f"{metric}_defined_days"] = int(len(sample))
                if level == "PAIRED_ALL_120D" or level == "PAIRED_REGIME":
                    fold_deltas = part.groupby("fold").t2_top10.mean()
                    row["top10_win_folds"] = int(fold_deltas.gt(0).sum())
                    row["fold_denominator"] = int(len(fold_deltas))
                elif level == "PAIRED_FOLD":
                    row["top10_win_folds"] = int(float(row["t2_top10"] or 0) > 0)
                    row["fold_denominator"] = 1
                result.append(row)
    return pd.DataFrame(result)


def weight_summary(states, scope) -> pd.DataFrame:
    records = []
    for fold in range(1, 13):
        for arm in ARMS:
            event = states[(fold, arm)]["FIT_COMPLETED"]
            imp = event.get("importance")
            coefs = event.get("huber_coefficients")
            assert set(imp or coefs or {}) == set(FEATURES)
            for feature in FEATURES:
                row = {
                    "row_type": "FOLD", "fold": fold, "arm": arm,
                    "feature": feature, "feature_count": 25,
                    "missing_indicators": 0, "dropped_features_leaked": False,
                    "huber_coefficient": None, "gain": None, "gain_share": None,
                    "split": None, "split_share": None,
                }
                if coefs is not None:
                    row["huber_coefficient"] = float(coefs[feature])
                else:
                    row.update(imp[feature])
                records.append(row)
    folds = pd.DataFrame(records)
    aggregated = []
    for arm in ARMS:
        for feature in FEATURES:
            group = folds.loc[folds.arm.eq(arm) & folds.feature.eq(feature)]
            row = {
                "row_type": "MEAN_12_FOLDS", "fold": 0, "arm": arm,
                "feature": feature, "feature_count": 25, "missing_indicators": 0,
                "dropped_features_leaked": False,
            }
            for column in ("huber_coefficient", "gain", "gain_share", "split", "split_share"):
                values = pd.to_numeric(group[column], errors="coerce").dropna()
                row[column] = float(values.mean()) if len(values) else None
            values = pd.to_numeric(group.huber_coefficient, errors="coerce").dropna()
            row["coefficient_same_sign_folds"] = (
                int(np.sign(values).eq(np.sign(values.mean())).sum()) if len(values) else None
            )
            aggregated.append(row)
    result = pd.concat([folds, pd.DataFrame(aggregated)], ignore_index=True)
    assert len(result) == 13 * 25 * 3
    assert set(result.feature) == set(FEATURES)
    assert not (set(result.feature) & DROPPED)
    return result


def verify_final_artifacts(ctx, final, daily, paired, weights, paths):
    assert len(final) == EXPECTED_CORE_OOS and final.D.nunique() == EXPECTED_SESSIONS
    assert not final.duplicated(KEY).any()
    assert final[["score_e4a", "score_e4b", "score_e4c",
                  "score_e2a", "score_e2b", "score_e3l2"]].notna().all().all()
    assert final.core_mask.astype(bool).all() and final.relevance.notna().all()
    assert int(final.is_low_absorb.sum()) == EXPECTED_LOW_ABSORB
    assert set(daily.eval_scope.unique()) == {"CORE", "CORE_LOW_ABSORB"}
    assert set(daily.arm.unique()) == {*ARMS, *BASELINE_SCORES}
    assert set(paired.comparison_baseline.unique()) == set(BASELINE_SCORES)
    assert len(weights) == 975
    assert not (set(weights.feature) & DROPPED)
    assert weights.loc[weights.row_type.eq("FOLD"), "missing_indicators"].eq(0).all()
    assert weights.loc[weights.row_type.eq("FOLD"), "feature_count"].eq(25).all()
    assert set(paths["outer"]["drop"] if "outer" in paths else DROPPED) == DROPPED


def make_receipt(ctx, states, events_path, binding_hash, paths,
                 final, daily, paired, weights):
    events = read_events(events_path)
    starts = [event for event in events if event["state"] == "FIT_STARTED"]
    completed = [event for event in events if event["state"] == "FIT_COMPLETED"]
    assert len(starts) == len(completed) == 36
    assert len({(event["fold"], event["arm"]) for event in starts}) == 36
    assert len({(event["fold"], event["arm"]) for event in completed}) == 36
    weight_records = []
    started_by_key = {
        (int(event["fold"]), str(event["arm"])): event for event in starts
    }
    for fold in range(1, 13):
        for arm in ARMS:
            event = states[(fold, arm)]["FIT_COMPLETED"]
            weight_records.append({
                "fold": fold, "arm": arm, "weight_file": event["weight_file"],
                "bytes": event["weight_bytes"], "sha256": event["weight_sha256"],
                "reload_max_abs_diff": event["model_reload_prediction_max_abs_diff"],
                "reload_exact": event["model_reload_prediction_max_abs_diff"] == 0.0,
                "train_rows": started_by_key[(fold, arm)]["train_rows"],
                "core_oos_rows": started_by_key[(fold, arm)]["core_oos_rows"],
            })
    assert all(row["reload_exact"] for row in weight_records)
    clip_counts = {
        str(fold): states[(fold, "E4A_LGBM_HUBER")]["FIT_COMPLETED"]["target_clip_counts"]
        for fold in range(1, 13)
    }
    medians = {
        str(fold): started_by_key[(fold, "E4C_HUBER_CLEAN")]["train_medians"]
        for fold in range(1, 13)
    }
    assert all(set(value) == set(FEATURES) for value in medians.values())
    artifacts = {}
    for filename in (
        "ACT037_E4_OOS_CORE.parquet", "ACT037_E4_METRICS.csv", "ACT037_E4_WEIGHT_SUMMARY.csv",
    ):
        artifact = paths["delivery"] / filename
        artifacts[filename] = identity(artifact)
    flags = ctx["outer"]["flags"]
    return {
        "action_id": "ACT-037",
        "status": "PASS_LOCAL_E4_PACKED_PENDING_DRIVE",
        "actual_fit": {"total": 36, "E4A_LGBM_HUBER": 12,
                       "E4B_LGBM_L1": 12, "E4C_HUBER_CLEAN": 12},
        "baseline_refit": 0, "additional_fit": 0,
        "prediction": "OOF scoring of the 36 fitted fold models only",
        "simulation": 0,
        "production_allowed": False, "orders_sent": False, "buy_gate_updated": False,
        "research_only": True, "strict_pit": 0, "train_admitted": 0,
        "no_go_blocked": True, "knowledge_base_training_complete": False,
        "input_binding_sha256": binding_hash,
        "input_binding": ctx["binding"],
        "current_pointer_observed": ctx["current_pointer_observation"],
        "runtime": ctx["runtime"],
        "folds": ctx["by_fold"],
        "weights": weight_records,
        "E4A_training_target_clip_counts_by_fold": clip_counts,
        "E4C_training_medians_by_fold": medians,
        "ACT030_E2B_ACT034_E3L2_core_rank_ic_mean": ctx["baseline_rank_ic_mean"],
        "all_36_weight_sha_verified": len(weight_records) == 36,
        "all_36_reload_max_abs_diff_zero": all(row["reload_exact"] for row in weight_records),
        "core_oos_keys": len(final), "sessions": final.D.nunique(),
        "regimes": final.groupby("regime").D.nunique().to_dict(),
        "low_absorb": {
            "keys": int(final.is_low_absorb.sum()),
            "daily_mean": float(final.is_low_absorb.sum() / EXPECTED_SESSIONS),
            "daily_min": int(ctx["low_counts"].min()),
            "daily_max": int(ctx["low_counts"].max()),
        },
        "feature_count": 25, "feature_names": FEATURES,
        "dropped_features": sorted(DROPPED),
        "constant_columns_excluded": ctx["const_evidence"],
        "missing_indicators": 0,
        "metrics_rows": int(len(daily) + len(paired)),
        "weight_summary_rows": int(len(weights)),
        "ledger": identity(events_path),
        "delivery_files": artifacts,
        "cleanup": {
            "items": [
                {"path": str(paths["batch"] / "work" / "lightgbm_runtime"),
                 "owner": "ACT-037", "status": "PENDING_PARENT_AFTER_ALL_PROCESSES_EXIT",
                 "reason": "shared library runtime needed for model reload validation"},
                {"path": str(paths["execution"]),
                 "owner": "ACT-037", "status": "RETAIN_AS_FIT_LEDGER_AND_RELOAD_EVIDENCE",
                 "reason": "required for model audit and idempotent run recovery"},
            ],
            "removed_bytes": 0,
            "status": "RUNTIME_CLEANUP_PENDING",
        },
        "flags": flags,
        "ACT037_scope_sha256": sha256(paths["scope"]),
        "runner_sha256": sha256(Path(__file__)),
        "time_beijing": datetime.now().astimezone().isoformat(),
    }


def synthetic_pack_check(outer: dict[str, Any]) -> dict[str, Any]:
    dates = [20260601, 20260602, 20260603, 20260604]
    regimes = ["ICE", "ICE", "RANGE", "REBOUND"]
    rows = []
    score_columns = [*SCORES.values(), *BASELINE_SCORES.values()]
    for day_index, (day, regime) in enumerate(zip(dates, regimes, strict=True)):
        for rank in range(10):
            row = {
                "D": day,
                "ts_code": f"{rank:06d}.SZ",
                "fold": 1 if day_index < 2 else 2,
                "regime": regime,
                "relevance": 3 if rank == 0 else 2 if rank < 3 else 1 if rank < 9 else 0,
                TARGET: float(10 - rank),
                CLEAN: rank == 0,
                TAIL: rank == 9,
                "is_low_absorb": rank < 3,
            }
            for score_index, column in enumerate(score_columns):
                row[column] = float(10 - rank) + score_index * 0.001
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame.loc[frame.D.eq(dates[0]) & frame.ts_code.eq("000009.SZ"), "score_e4a"] = np.nan
    assert rank_ic(pd.Series([1.0, 2.0, 3.0]), pd.Series([3.0, 2.0, 1.0])) == -1.0
    context = {
        "test_dates": dates,
        "splits": pd.DataFrame({
            "fold": [1, 2],
            "test_Ds": [f"{dates[0]}|{dates[1]}", f"{dates[2]}|{dates[3]}"],
        }),
        "raw": pd.DataFrame({"D": dates, "regime": regimes}),
    }
    daily, paired = all_metrics(context, frame)
    assert set(daily.eval_scope.unique()) == {"CORE", "CORE_LOW_ABSORB"}
    assert set(daily.arm.unique()) == {*ARMS, *BASELINE_SCORES}
    assert set(paired.comparison_baseline.unique()) == set(BASELINE_SCORES)
    assert len(daily.loc[daily.row_type.eq("DAILY")]) == len(dates) * 2 * 6
    assert len(paired.loc[paired.row_type.eq("PAIRED_DAILY")]) == len(dates) * 2 * 3 * 3

    # Exercise the same one-row-per-key wide aggregation used after all 36
    # completed checkpoints are read. Three long score frames would duplicate
    # keys and fail both this row count and the unique-key assertion.
    witness_evaluate = frame.loc[frame.D.eq(dates[1]), KEY].reset_index(drop=True)
    witness_scores = {
        arm: pd.concat([
            witness_evaluate,
            frame.loc[frame.D.eq(dates[1]), SCORES[arm]].reset_index(drop=True),
        ], axis=1)
        for arm in ARMS
    }
    witness_wide = wide_fold_scores(witness_evaluate, 1, witness_scores)
    assert len(witness_wide) == len(witness_evaluate) == 10
    assert not witness_wide.duplicated(KEY).any()
    for arm in ARMS:
        expected = frame.loc[frame.D.eq(dates[1]), SCORES[arm]].to_numpy(dtype="float64")
        assert np.array_equal(witness_wide[SCORES[arm]].to_numpy(dtype="float64"), expected)

    states = {}
    for fold in range(1, 13):
        for arm in ARMS:
            if arm == "E4C_HUBER_CLEAN":
                coefficients = {feature: (index + 1) / 100.0 for index, feature in enumerate(FEATURES)}
                importance = None
            else:
                coefficients = None
                importance = {
                    feature: {
                        "gain": 1.0, "gain_share": 1.0 / len(FEATURES),
                        "split": 1, "split_share": 1.0 / len(FEATURES),
                    }
                    for feature in FEATURES
                }
            states[(fold, arm)] = {
                "FIT_STARTED": {
                    "train_rows": 16000 + fold,
                    "core_oos_rows": 3000 + fold,
                    "train_medians": (
                        {feature: 0.5 for feature in FEATURES}
                        if arm == "E4C_HUBER_CLEAN" else None
                    ),
                },
                "FIT_COMPLETED": {
                    "weight_file": f"ACT037_F{fold:02d}_{ARM_LABELS[arm]}.joblib",
                    "weight_bytes": 1,
                    "weight_sha256": hashlib.sha256(f"{fold}|{arm}".encode()).hexdigest(),
                    "model_reload_prediction_max_abs_diff": 0.0,
                    "train_rows": 16000 + fold,
                    "core_oos_rows": 3000 + fold,
                    "target_clip_counts": {"below_minus_10": 1, "above_plus_10": 2},
                    "importance": importance,
                    "huber_coefficients": coefficients,
                },
            }
    summary = weight_summary(states, outer)
    assert len(summary) == 975 and not (set(summary.feature) & DROPPED)

    with tempfile.TemporaryDirectory(prefix="act037_zero_fit_check_") as temporary:
        scratch = Path(temporary)
        (scratch / "scope.json").write_text("{}", encoding="utf-8")
        delivery = scratch / "delivery"
        delivery.mkdir()
        for filename in (
            "ACT037_E4_OOS_CORE.parquet",
            "ACT037_E4_METRICS.csv",
            "ACT037_E4_WEIGHT_SUMMARY.csv",
        ):
            (delivery / filename).write_bytes(b"synthetic-check-only\n")
        events_path = scratch / "ACT037_EVENTS.jsonl"
        events = []
        for fold in range(1, 13):
            for arm in ARMS:
                fit_id = f"synthetic-{fold}-{arm}"
                start = states[(fold, arm)]["FIT_STARTED"]
                done = states[(fold, arm)]["FIT_COMPLETED"]
                events.append({
                    "action_id": "ACT-037", "state": "FIT_STARTED",
                    "fold": fold, "arm": arm, "fit_id": fit_id, **start,
                })
                events.append({
                    "action_id": "ACT-037", "state": "FIT_COMPLETED",
                    "fold": fold, "arm": arm, "fit_id": fit_id, **done,
                })
        events_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )
        scope_path = scratch / "scope.json"
        scratch_paths = {
            "batch": scratch,
            "scope": scope_path,
            "execution": scratch / "execution",
            "delivery": delivery,
        }
        receipt_context = {
            "outer": {"flags": outer["flags"]},
            "binding": {"synthetic_check": True},
            "current_pointer_observation": {"synthetic_check": True},
            "runtime": {"synthetic_check": True},
            "baseline_rank_ic_mean": {"E2B": -0.015492, "E3L2": -0.007336},
            "const_evidence": {
                "hold_rise_base_low": {"unique_values": 1, "value": 0.0, "rows": 4},
                "prior5_highvol_bear_unrecovered": {
                    "unique_values": 1, "value": 0.0, "rows": 4,
                },
            },
            "by_fold": {
                fold: {"train_rows": 16000 + fold, "core_oos_rows": 3000 + fold}
                for fold in range(1, 13)
            },
            "low_counts": pd.Series([151] * EXPECTED_SESSIONS),
        }
        receipt_final = pd.DataFrame({
            "D": dates,
            "regime": regimes,
            "is_low_absorb": [True, False, True, False],
        })
        receipt = make_receipt(
            receipt_context, states, events_path, "0" * 64, scratch_paths,
            receipt_final, daily, paired, summary,
        )
        assert receipt["actual_fit"]["total"] == 36
        assert receipt["all_36_weight_sha_verified"]
        assert receipt["all_36_reload_max_abs_diff_zero"]
        assert len(receipt["E4C_training_medians_by_fold"]) == 12
    return {
        "status": "PASS",
        "fit": 0,
        "prediction": 0,
        "simulation": 0,
        "daily_metric_rows": int(len(daily.loc[daily.row_type.eq("DAILY")])),
        "paired_daily_rows": int(len(paired.loc[paired.row_type.eq("PAIRED_DAILY")])),
        "weight_summary_rows": len(summary),
        "synthetic_receipt_fit_entries": receipt["actual_fit"]["total"],
        "temporary_files_removed": True,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True,
                        help="ACT-024/030/034/036 research_batches parent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="verify pinned source, keys and ranks without fitting")
    run_parser = subparsers.add_parser("run", help="run E4 fits and pack at most 36 weights")
    run_parser.add_argument("--threads", type=int, default=1)
    run_parser.add_argument("--max-folds", type=int)
    run_parser.add_argument("--acknowledge-failed-fit", choices=(FAILED_CANARY_FIT_ID,),
                            help="count and skip the known failed F01 E4A attempt")
    args = parser.parse_args()
    if args.command == "run":
        assert 1 <= args.threads <= 4
        assert args.max_folds is None or 1 <= args.max_folds <= 12
    return args


def main():
    args = parse_args()
    args.batch_root = args.batch_root.resolve()
    args.source_root = args.source_root.resolve()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "run":
        run(args)
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    main()
