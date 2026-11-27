"""Numeric adapters and weight-only scoring without access to training code."""

import os
import pickle
import subprocess

import numpy as np

from .contracts import FEATURE_SETS, read_json


def normalizer(values, feature_set):
    x = np.asarray(values, dtype=np.float64)
    if not x.size or np.any(np.all(np.isnan(x), axis=0)):
        raise ValueError("empty TRAIN or all-NA TRAIN feature")
    median_values = np.nanmedian(x, axis=0)
    imputed = np.where(np.isnan(x), median_values, x)
    mean_values = imputed.mean(axis=0)
    scale = imputed.std(axis=0, ddof=0)
    scale[scale == 0] = 1
    return {
        "median": median_values.tolist(), "mean": mean_values.tolist(),
        "scale": scale.tolist(), "features": list(FEATURE_SETS[feature_set]),
    }


def transform(values, metadata):
    x = np.asarray(values, dtype=np.float64)
    count = len(metadata["features"])
    if x.ndim != 2 or x.shape[1] != count:
        raise ValueError("feature-width disagreement")
    out = (np.where(np.isnan(x), metadata["median"], x) - metadata["mean"]) / metadata["scale"]
    if not np.isfinite(out).all():
        raise ValueError("nonfinite normalized features")
    return out


def mps_call(python, command, *, log):
    env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    with log.open("xb") as output:
        subprocess.run([str(python), "-m", "ops.pft_act080_p2.mps_worker", *command],
                       env=env, stdout=output, stderr=subprocess.STDOUT, check=True)


def sklearn_safety(model, normalized_values):
    if tuple(model.classes_) != (0, 1):
        raise ValueError("estimator class axis not binary 0/1")
    if model.__class__.__name__ != "ExtraTreesClassifier":
        return 1 - model.predict_proba(normalized_values)[:, 1]
    # Tree building remains 18-way. Ordered single-thread reduction makes readback bit-exact.
    threads = model.n_jobs
    model.n_jobs = 1
    try:
        return 1 - model.predict_proba(normalized_values)[:, 1]
    finally:
        model.n_jobs = threads


def replay_scores(model_dir, metadata, values, python, output_folder, suffix):
    spec = read_json(model_dir / "normalizer.json")
    order = metadata["feature_set"]
    if spec["features"] != list(FEATURE_SETS[order]):
        raise ValueError("selected whitelist order differs from seal")
    normalized = transform(values[:, :len(spec["features"])], spec)
    if metadata["family"] == "MLP_MPS":
        matrix = output_folder / f"_{suffix}_MPS_INPUT.npz"
        scored = output_folder / f"_{suffix}_MPS_SCORES.npz"
        receipt = output_folder / f"{suffix}_mps_device_receipt.json"
        np.savez_compressed(matrix, values=normalized)
        mps_call(python, ["score", str(model_dir / "weight.pt"), str(matrix), str(scored), str(receipt)],
                 log=output_folder / f"{suffix}_mps.log")
        with np.load(scored, allow_pickle=False) as sample:
            scores = sample["scores"]
        matrix.unlink()
        scored.unlink()
    else:
        from threadpoolctl import threadpool_limits

        with (model_dir / "weight.pkl").open("rb") as fh:
            model = pickle.load(fh)
        with threadpool_limits(limits=1, user_api="blas"), threadpool_limits(limits=18, user_api="openmp"):
            scores = sklearn_safety(model, normalized)
    if scores.shape != (len(values),) or not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
        raise ValueError("invalid sealed-model score array")
    return scores
