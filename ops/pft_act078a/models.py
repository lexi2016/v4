"""ACT-078A fixed estimators, chronological group OOF and Val rank lock."""

import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from data import FEATURES, OOT_START, VAL_START, require

FIT_CAP = 24
ESTIMATOR_THREADS = 4
SEED = 20261127
FAMILY_NAMES = ("safe_l2", "safe_extra_trees", "return_ridge", "return_extra_trees")
FAMILY_CONFIG = {
    "safe_l2": {"C": 0.1, "solver": "lbfgs", "max_iter": 2000, "random_state": SEED},
    "safe_extra_trees": {
        "n_estimators": 128, "max_depth": 3, "min_samples_leaf": 16, "max_features": 0.75,
        "random_state": SEED, "n_jobs": ESTIMATOR_THREADS,
    },
    "return_ridge": {"alpha": 20.0, "solver": "lsqr"},
    "return_extra_trees": {
        "n_estimators": 128, "max_depth": 3, "min_samples_leaf": 16, "max_features": 0.75,
        "random_state": SEED, "n_jobs": ESTIMATOR_THREADS,
    },
}
V21_A = "A级_多头知识库优选"
V21_POSITIVE = (V21_A, "B1级_底部粘合观察(W<=Y)", "B2级_多头中位观察")
V22_POSITIVE = ("A", "B")
SCORE_COLUMNS = (*FAMILY_NAMES, "safety_axis", "net_return_axis", "safety_rank_val", "returns_rank_val", "score")


def estimator(name):
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    constructors = {
        "safe_l2": LogisticRegression, "safe_extra_trees": ExtraTreesClassifier,
        "return_ridge": Ridge, "return_extra_trees": ExtraTreesRegressor,
    }
    model = constructors[name](**FAMILY_CONFIG[name])
    if name in ("safe_l2", "return_ridge"):
        return make_pipeline(imputer, StandardScaler(), model)
    return make_pipeline(imputer, model)


def target(rows, family):
    if family.startswith("safe_"):
        return rows.tail_std.eq(0).astype(int)
    return (rows.t2_net+rows.t5_net)/2


def journal_append(path, record):
    event = {"utc": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def budgeted_fit(name, fit_id, rows, journal):
    with journal.open("r", encoding="utf-8") as stream:
        spent = [record for line in stream if (record := json.loads(line))["event"] == "FIT_STARTED"]
    require(len(spent) < FIT_CAP and all(x["fit_id"] != fit_id for x in spent), f"FIT budget or duplicate {fit_id}")
    model = estimator(name)
    y = target(rows, name)
    require(len(rows) > 0 and y.notna().all(), f"Bad targets in {fit_id}")
    if name.startswith("safe_"):
        require(y.nunique() == 2, f"One class in {fit_id}")
    journal_append(journal, {"event": "FIT_STARTED", "fit_id": fit_id, "family": name, "rows": len(rows)})
    try:
        model.fit(rows[list(FEATURES)], y)
    except BaseException as error:
        journal_append(journal, {"event": "FIT_FAILED", "fit_id": fit_id, "error": repr(error)})
        raise
    journal_append(journal, {"event": "FIT_COMPLETED", "fit_id": fit_id, "family": name, "rows": len(rows)})
    return model


def first_eligible(rows, period, before):
    return rows.trigger_role.eq("FIRST") & rows.period.eq(period) & rows.maturity_5_D.lt(before).fillna(False)


def build_folds(data):
    train = data[data.period.eq("TRAIN") & data.trigger_role.eq("FIRST")]
    unique_days = sorted(train.D.unique())
    blocks = np.array_split(np.array(unique_days), 6)
    require(all(len(block) >= 2 for block in blocks), "Insufficient time blocks for five folds")
    definitions = []
    for fold, days in enumerate(blocks[1:], start=1):
        start, end = map(str, (days[0], days[-1]))
        eligible_fit = first_eligible(data, "TRAIN", start)
        heldout = train.D.between(start, end)
        training = data[eligible_fit]
        heldout_groups = train.loc[heldout, "structure_episode_id"]
        # Scoring includes confirmations of a held-out group for exact-date
        # case review. Only its first row enters independent-wave metrics.
        score_mask = data.period.eq("TRAIN") & data.structure_episode_id.isin(heldout_groups)
        require(len(training) and heldout.any(), f"Empty fold {fold}")
        require(training.D.lt(start).all() and training.maturity_5_D.lt(start).all(), f"Maturity/time leak fold {fold}")
        require(set(training.structure_episode_id).isdisjoint(heldout_groups), f"Group leak fold {fold}")
        eval_mature = train.loc[heldout, "maturity_5_D"].lt(VAL_START).sum()
        definitions.append({
            "fold": fold, "start": start, "end": end, "fit_mask": eligible_fit, "score_mask": score_mask,
            "fit_rows": len(training), "fit_groups": training.structure_episode_id.nunique(),
            "fit_label_last_D": str(training.maturity_5_D.max()),
            "holdout_groups": int(heldout.sum()), "holdout_target_mature_before_val_n": int(eval_mature),
            "holdout_scored_first_rows": int(heldout.sum()), "holdout_scored_total_rows": int(score_mask.sum()),
            "fit_purged_n": int((train.D.lt(start)).sum() - len(training)),
            "group_overlap_n": 0,
        })
    require(sum(x["holdout_groups"] for x in definitions) + int(train.D.isin(blocks[0]).sum()) == len(train),
            "OOF group coverage")
    return definitions, {"first_D": str(blocks[0][0]), "last_D": str(blocks[0][-1]),
                         "first_rows": int(train.D.isin(blocks[0]).sum())}


def predictions(models, rows):
    out = pd.DataFrame(index=rows.index, columns=list(FAMILY_NAMES), dtype=float)
    inputs = rows[list(FEATURES)]
    if not rows.empty:
        for name, model in models.items():
            out[name] = model.predict_proba(inputs)[:, 1] if name.startswith("safe_") else model.predict(inputs)
    out["safety_axis"] = out[["safe_l2", "safe_extra_trees"]].mean(axis=1)
    out["net_return_axis"] = out[["return_ridge", "return_extra_trees"]].mean(axis=1)
    return out


def score_axes(predicted, lock):
    ranked = predicted.copy()
    for metric, dest in (("safety_axis", "safety_rank_val"), ("net_return_axis", "returns_rank_val")):
        ref = np.asarray(lock[metric+"_val_sorted"])
        values = ranked[metric].to_numpy()
        # Mid-ECDF, with score 0/1 outside the frozen Val reference range.
        left = np.searchsorted(ref, values, side="left")
        right = np.searchsorted(ref, values, side="right")
        ranked[dest] = np.where(np.isfinite(values), (left+right)/(2*len(ref)), np.nan)
    ranked["score"] = (ranked.safety_rank_val+ranked.returns_rank_val)/2
    return ranked


def rank_key(score, D, security_id):
    return (-float(score), str(D), str(security_id))


def freeze_rank_lock(predicted, validation):
    require(len(validation) > 0 and validation.maturity_5_D.lt(OOT_START).all(), "Val rank criteria")
    require(validation.period.eq("VAL").all() and validation.trigger_role.eq("FIRST").all(), "Val-only independent groups")
    require(predicted.index.equals(validation.index) and predicted.notna().all().all(), "Missing Val prediction")
    lock = {
        "safety_axis_val_sorted": sorted(predicted.safety_axis.tolist()),
        "net_return_axis_val_sorted": sorted(predicted.net_return_axis.tolist()),
        "rank_rule": "equal family means; equal Val mid-ECDF ranks of two axes",
        "cutoff_rule": "fixed Val V2.1 A and A+B coverage; descending score, then ascending D and security_id ties",
        "val_first_mature_n": len(validation),
        "val_label_last_D": str(validation.maturity_5_D.max()),
    }
    ranked = score_axes(predicted, lock)
    ordered = sorted(rank_key(s, d, k) for s, d, k in zip(ranked.score, validation.D, validation.security_id))
    a = int(validation.visual_tier.eq(V21_A).sum())
    b = int(validation.visual_tier.isin(V21_POSITIVE).sum())
    require(0 < a < b < len(ordered), "Degenerate Val quota")
    lock.update(val_a_n=a, val_a_or_b_n=b, cutoff_A=list(ordered[a-1]), cutoff_B=list(ordered[b-1]))
    return lock


def tiered(rows, predicted, lock):
    out = rows.join(score_axes(predicted, lock), validate="one_to_one")
    tiers = []
    for row in out.itertuples(index=False):
        if not np.isfinite(row.score):
            tiers.append("UNSCORED")
            continue
        key = rank_key(row.score, row.D, row.security_id)
        tiers.append("A" if key <= tuple(lock["cutoff_A"]) else "B" if key <= tuple(lock["cutoff_B"]) else "C")
    out["candidate_tier"] = tiers
    return out


def save_refit(weights, family, model):
    path = weights / (family+".joblib")
    require(not path.exists(), f"Unexpected prior weights {path.name}")
    joblib.dump(model, path, compress=3)
    return path
