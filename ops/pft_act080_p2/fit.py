"""Fit eight predeclared TRAIN/VAL candidates and seal one VAL operating point."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import pickle
from time import perf_counter

import numpy as np
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from threadpoolctl import threadpool_info, threadpool_limits

from .contracts import (
    FEATURE_SETS, JUNDA, METHOD, claim, digest, read_json, seal, source_inventory, sync_directory,
    verify_payload, verify_signed, write_csv, write_json,
)
from .model_io import mps_call, normalizer, replay_scores, sklearn_safety, transform
from .prep import DEV_DIR, PREP_SEAL
from .selection import choose, threshold_rows


FIT_DIR = "fit_locked"
FIT_LOCK = "ACT080_P2_PRE_OOT_MODEL_LOCK.json"
LEDGER = "ACT080_P2_FIT_LEDGER.csv"
ATTEMPTS = "FIT_ATTEMPTS"
SKLEARN_FAMILIES = {"LOGISTIC": LogisticRegression, "HGB": HistGradientBoostingClassifier, "EXTRA_TREES": ExtraTreesClassifier}


def _attempt_name(family, features):
    return f"{METHOD['family_order'].index(family) + 1:02}_{family}__{features}"


def ledger_rows(attempts):
    rows = []
    for dispatched in sorted(attempts.glob("*_DISPATCH.json")):
        attempt = read_json(dispatched)
        identity = attempt["fit_id"]
        start_path = attempts / f"{identity}_START.json"
        end_path = attempts / f"{identity}_END.json"
        begin = read_json(start_path) if start_path.exists() else {}
        end = read_json(end_path) if end_path.exists() else {}
        rows.append({
            **attempt, "fit_invoked": int(bool(begin)),
            "start_unix_ns": begin.get("claimed_ns"), "status": end.get("status", "STARTED" if begin else "DISPATCHED"),
            "elapsed_seconds": end.get("elapsed_seconds"), "TRAIN_metrics": json.dumps(end.get("TRAIN_metrics"), sort_keys=True),
            "VAL_metrics": json.dumps(end.get("VAL_metrics"), sort_keys=True), "error": end.get("error"),
        })
    return rows


def write_ledger(attempts, out):
    rows = ledger_rows(attempts)
    if rows:
        write_csv(out, rows)
    return rows


def _labels(rows):
    return np.asarray([np.nan if r["tail_std"] is None else int(r["tail_std"]) for r in rows])


def _validate_binary(values, context):
    if set(values) != {0, 1}:
        raise ValueError(f"{context} has no complete binary class coverage")


def _metrics(labels, scores):
    kept = np.isfinite(labels)
    y = labels[kept]
    prob = 1 - np.asarray(scores, dtype=float)[kept]
    _validate_binary(y, "scored binary set")
    return {
        "mature": int(kept.sum()), "tail_positive_count": int(y.sum()),
        "tail_roc_auc": float(roc_auc_score(y, prob)),
        "tail_brier": float(brier_score_loss(y, prob)), "tail_logloss": float(log_loss(y, prob, labels=[0, 1])),
    }


def _cpu_candidate(family, model_dir, x_train, x_val, y_train, start, attempt):
    fit_rows = np.isfinite(y_train)
    _validate_binary(y_train[fit_rows], "CPU TRAIN")
    model = SKLEARN_FAMILIES[family](**METHOD["family_parameters"][family], random_state=METHOD["seed"])
    with threadpool_limits(limits=1, user_api="blas"), threadpool_limits(limits=METHOD["cpu_threads"], user_api="openmp"):
        threads = threadpool_info()
        if family == "HGB" and not any(r["user_api"] == "openmp" and r["num_threads"] == METHOD["cpu_threads"] for r in threads):
            raise RuntimeError("HGB OpenMP 18-thread runtime gate failed")
        claim(start, fit_id=attempt, family=family, invoked=True, sklearn=sklearn_version)
        started = perf_counter()
        model.fit(x_train[fit_rows], y_train[fit_rows].astype(int))
        fit_seconds = perf_counter() - started
        train_scores = sklearn_safety(model, x_train)
        val_scores = sklearn_safety(model, x_val)
    with (model_dir / "weight.pkl").open("xb") as handle:
        pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)
    write_json(model_dir / "hardware_receipt.json", {
        "sklearn": sklearn_version, "device": "CPU", "threadpools_during_fit": threads,
        "extra_trees_n_jobs": model.n_jobs if family == "EXTRA_TREES" else None, "actual_fit_seconds": fit_seconds,
    })
    return train_scores, val_scores


def _mps_candidate(model_dir, scratch, x_train, x_val, train_events, y_train, start, attempt, python):
    groups = np.asarray([r["mlp_train_partition"] for r in train_events])
    known = np.isfinite(y_train)
    gradient = (groups == "GRADIENT") & known
    early = (groups == "EARLY_STOP") & known
    _validate_binary(y_train[gradient], "MLP gradient TRAIN")
    _validate_binary(y_train[early], "MLP early-stop TRAIN")
    payload = scratch / f"{attempt}_dev_x.npz"
    scored = scratch / f"{attempt}_dev_scores.npz"
    np.savez_compressed(payload, x_gradient=x_train[gradient], y_gradient=y_train[gradient],
                        x_early=x_train[early], y_early=y_train[early], x_train=x_train, x_val=x_val)
    mps_call(python, ["train", str(payload), str(model_dir / "weight.pt"), str(scored),
                     str(model_dir / "hardware_receipt.json"), str(start), attempt],
             log=model_dir / "mps_train.log")
    with np.load(scored, allow_pickle=False) as data:
        scores = data["train_scores"], data["val_scores"]
    payload.unlink()
    scored.unlink()
    return scores


def _one(family, features, x_train, x_val, train_events, val_events, out, attempts, scratch, python):
    identity = _attempt_name(family, features)
    start = attempts / f"{identity}_START.json"
    end = attempts / f"{identity}_END.json"
    model_dir = out / "weights" / identity
    model_dir.mkdir()
    started = perf_counter()
    y_train, y_val = _labels(train_events), _labels(val_events)
    mature = np.isfinite(y_train)
    fit_population = mature if family != "MLP_MPS" else (
        mature & np.asarray([r["mlp_train_partition"] == "GRADIENT" for r in train_events])
    )
    claim(
        attempts / f"{identity}_DISPATCH.json", fit_id=identity, family=family, feature_set=features,
        params=json.dumps(METHOD["family_parameters"][family], sort_keys=True), seed=METHOD["seed"],
        fold="TRAIN_TO_VAL", TRAIN_rows=len(x_train), VAL_rows=len(x_val), gradient_or_estimator_rows=int(fit_population.sum()),
        Junda_rows=0,
    )
    failure = None
    record = {}
    try:
        scaler = normalizer(x_train[fit_population], features)
        write_json(model_dir / "normalizer.json", scaler)
        train_norm, val_norm = transform(x_train, scaler), transform(x_val, scaler)
        if family == "MLP_MPS":
            scores = _mps_candidate(model_dir, scratch, train_norm, val_norm, train_events, y_train, start, identity, python)
        else:
            scores = _cpu_candidate(family, model_dir, train_norm, val_norm, y_train, start, identity)
        train_scores, val_scores = scores
        record = {"TRAIN_metrics": _metrics(y_train, train_scores), "VAL_metrics": _metrics(y_val, val_scores)}
        np.save(model_dir / "VAL_SAFETY.npy", val_scores, allow_pickle=False)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        claim(end, status="SUCCESS" if failure is None else "FAIL",
              elapsed_seconds=perf_counter() - started, error=None if failure is None else f"{type(failure).__name__}: {failure}", **record)
        write_ledger(attempts, out.parent / LEDGER)
    return list(threshold_rows(family, features, val_scores, val_events))


def fit(run_root, python):
    signatures = verify_signed(run_root)
    prep_lock = verify_payload(run_root / PREP_SEAL, run_root / DEV_DIR)
    if prep_lock["signed"] != signatures or prep_lock["code"] != source_inventory(prep_only=True):
        raise ValueError("prepared inputs/code differ from seal")
    frozen_code = source_inventory()
    if (run_root / "OOT_OPEN_ONCE.json").exists():
        raise FileExistsError("OOT claim already exists")
    claim(run_root / "FIT_CLAIM.json", stage="FIT", OOT_OPEN_COUNT=0)
    started = perf_counter()
    attempts = run_root / ATTEMPTS
    attempts.mkdir(mode=0o700)
    out = run_root / ".fit_pending"
    out.mkdir(mode=0o700)
    (out / "weights").mkdir()
    scratch = run_root / ".fit_scratch"
    scratch.mkdir(mode=0o700)
    events = read_json(run_root / DEV_DIR / "TRAIN_VAL_EVENTS.json")
    if any(row["security_id"] == JUNDA or row["fold"] not in ("TRAIN", "VAL") for row in events):
        raise ValueError("sealed development population gate failed")
    with np.load(run_root / DEV_DIR / "TRAIN_VAL_X.npz", allow_pickle=False) as data:
        matrix = data["values"]
    if matrix.shape != (len(events), len(FEATURE_SETS["FEAT_PLUS_ANCHOR_KB"])):
        raise ValueError("sealed development matrix schema mismatch")
    on_train = np.asarray([row["fold"] == "TRAIN" for row in events])
    train_events, val_events = [r for r in events if r["fold"] == "TRAIN"], [r for r in events if r["fold"] == "VAL"]
    all_val, all_train = matrix[~on_train], matrix[on_train]
    selection = []
    for family in METHOD["family_order"]:
        for features in METHOD["feature_order"]:
            width = len(FEATURE_SETS[features])
            selection.extend(_one(family, features, all_train[:, :width], all_val[:, :width], train_events,
                                  val_events, out, attempts, scratch, python))
    rows = write_ledger(attempts, run_root / LEDGER)
    if len(rows) != 8 or any(row["status"] != "SUCCESS" or row["fit_invoked"] != 1 for row in rows):
        raise ValueError("exact eight successful FIT gate failed")
    write_csv(out / "ACT080_P2_VAL_THRESHOLD_LEDGER.csv", selection)
    selected = choose(selection)
    selected["fit_id"] = _attempt_name(selected["family"], selected["feature_set"])
    selected_model = out / "weights" / selected["fit_id"]
    frozen_val = np.load(selected_model / "VAL_SAFETY.npy", allow_pickle=False)
    readback = replay_scores(selected_model, selected, all_val, python, out, "selected_val_readback")
    if not np.array_equal(frozen_val, readback):
        raise ValueError("selected-model reload changed VAL scores")
    write_json(out / "SELECTED_MODEL.json", selected)
    write_json(out / "FIT_RECEIPT.json", {
        "elapsed_seconds": perf_counter() - started, "actual_fit_success": 8, "fit_invoked": 8,
        "fit_failed": 0, "oot_open_count": 0, "junda_dev_use_count": 0,
        "selected_reload_exact": True, "val_scores_compared": len(readback),
        "val_scores_sha256": sha256(readback.tobytes()).hexdigest(),
        "params": METHOD["family_parameters"], "seed": METHOD["seed"],
        "eligible_stock_roster_count": 40,
    })
    if source_inventory() != frozen_code:
        raise ValueError("implementation changed while fitting")
    out.rename(run_root / FIT_DIR)
    sync_directory(run_root)
    lock_sha = seal(
        run_root / FIT_LOCK, run_root / FIT_DIR, code=frozen_code,
        stage="PRE_OOT_MODEL_LOCKED", FIT=8, OOT_OPEN_COUNT=0, signed=signatures,
        fit_ledger_sha256=digest(run_root / LEDGER),
        fit_attempt_sha256={p.name: digest(p) for p in sorted(attempts.iterdir())},
        prep_seal_sha256=digest(run_root / PREP_SEAL),
    )
    scratch.rmdir()
    return {"fit_lock_sha256": lock_sha, "actual_FIT": 8, "selection": selected["fit_id"], "threshold": selected["threshold"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--mps-python", type=Path)
    parser.add_argument("--ledger-only", action="store_true")
    args = parser.parse_args()
    run_root = args.run_root.resolve(strict=True)
    if args.ledger_only:
        if (run_root / FIT_LOCK).exists():
            parser.error("sealed successful FIT ledger already exists")
        rows = write_ledger(run_root / ATTEMPTS, run_root / LEDGER)
        print({"attempts": len(rows), "FIT_invoked": sum(r["fit_invoked"] for r in rows)})
        return
    if args.mps_python is None or not args.mps_python.is_file():
        parser.error("supply verified MPS Python")
    print(fit(run_root, args.mps_python.absolute()))


if __name__ == "__main__":
    main()
