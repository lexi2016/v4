"""Research-only, fixed L2 source/resonance comparison; no data collection.

CSV rows are derived views of shared producers. Unknown flags fail closed.
All CLI executions register before reading data; models use plain JSON only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)
EXPOSED = {"2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"}
RESERVED = {"label", "label_end_date", "target_date", "return", "future_return",
            "signal_date", "signal_at", "available_at", "code"}
FIT_COUNTS = {"synthetic_fit_entered": 0, "synthetic_fit_returned": 0,
              "real_fit_entered": 0, "real_fit_returned": 0}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        f.write("\n")


def day(value):
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "DATE_NOT_ISO")
    return parsed


def instant(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "TIMEZONE_REQUIRED")
    return parsed


def number(value):
    require(value is not None and value != "", "UNKNOWN_FEATURE")
    x = float(value)
    require(math.isfinite(x), "UNKNOWN_OR_NONFINITE_FEATURE")
    return x


def validate_manifest(manifest, synthetic=False):
    require(all(manifest.get(k) is v for k, v in FLAGS.items()), "UNSAFE_FLAGS")
    if synthetic:
        require(manifest.get("dataset_kind") == "SYNTHETIC_FIXTURE", "FIXTURE_REQUIRED")
    else:
        require(manifest.get("dataset_kind") == "SHARED_PRODUCER_DERIVED_VIEW", "PRODUCER_REQUIRED")
        for key in ("lineage_review_pass", "design_review_pass", "feature_semantics_bound",
                    "historical_availability_bound", "label_maturity_bound"):
            require(manifest.get(key) is True, "CANNOT_CONFIRM:" + key)
        require(manifest.get("producer_manifest_sha256") and manifest.get("universe_scope")
                and manifest.get("label_definition"),
                "PRODUCER_AND_UNIVERSE_BINDING_REQUIRED")


def feature_names(config, arm):
    technical = config["technical_features"]
    pools = config["pool_flags"]
    sources = config["source_flags"]
    all_raw = technical + pools + sources
    require(technical and len(set(all_raw)) == len(all_raw), "FEATURES_EMPTY_OR_DUPLICATED")
    require(not set(all_raw) & RESERVED, "TARGET_OR_ID_IN_FEATURES")
    names = list(technical)
    if arm == "candidate":
        names += pools + sources + ["pool_membership_count", "source_membership_count"]
        if config.get("independent_origin_groups"):
            names += ["independent_origin_count"]
    require(len(names) == len(set(names)), "DERIVED_FEATURE_COLLISION")
    return names


def feature_values(row, config, arm):
    # Validate candidate dependencies for both arms, preserving exactly one cohort.
    values = {k: number(row.get(k)) for k in config["technical_features"]}
    for key in config["pool_flags"] + config["source_flags"]:
        value = number(row.get(key))
        require(value in (0.0, 1.0), "FLAG_NOT_BINARY:" + key)
        values[key] = value
    values["pool_membership_count"] = sum(values[k] for k in config["pool_flags"])
    values["source_membership_count"] = sum(values[k] for k in config["source_flags"])
    groups = config.get("independent_origin_groups", {})
    if groups:
        require(config.get("origin_independence_bound") is True, "ORIGIN_INDEPENDENCE_UNKNOWN")
        require(set(groups) == set(config["source_flags"]), "ORIGIN_MAPPING_INCOMPLETE")
        require(all(isinstance(v, str) and v for v in groups.values()), "ORIGIN_MAPPING_UNKNOWN")
        values["independent_origin_count"] = len({groups[k] for k in groups if values[k] == 1})
    return [values[k] for k in feature_names(config, arm)]


def validate_rows(rows, config, manifest, *, synthetic=False, labelled=True):
    validate_manifest(manifest, synthetic)
    require(config.get("top_n") == 50, "TOP_N_FROZEN_50")
    require(config.get("seed") == 194, "SEED_FROZEN_194")
    feature_names(config, "candidate")
    seen = set()
    for row in rows:
        key = (row["signal_date"], row["code"])
        require(key not in seen, "DUPLICATE_DATE_CODE")
        seen.add(key)
        require(bool(row["code"]), "CODE_EMPTY")
        if synthetic:
            require(row["code"].startswith("SYNTH"), "NON_SYNTHETIC_FIXTURE_CODE")
        day(key[0])
        signal, available = instant(row["signal_at"]), instant(row["available_at"])
        require(signal.date().isoformat() == key[0], "SIGNAL_DATE_MISMATCH")
        require(available <= signal, "FEATURE_AVAILABLE_AFTER_SIGNAL")
        feature_values(row, config, "candidate")
        if labelled:
            require(day(row["label_end_date"]) > day(key[0]), "LABEL_NOT_FUTURE")
            require(number(row.get("label")) in (0, 1), "BINARY_LABEL_REQUIRED")
    require(bool(rows), "EMPTY_DATASET")


def split_rows(rows, split, exposed=EXPOSED):
    train_end, start, end = (day(split[k]) for k in ("train_end", "eval_start", "eval_end"))
    require(train_end < start <= end, "CHRONOLOGICAL_SPLIT_REQUIRED")
    require(split["kind"] in {"oof", "final", "diagnostic"}, "UNKNOWN_SPLIT_KIND")
    evaluation = [r for r in rows if start <= day(r["signal_date"]) <= end]
    require(evaluation, "EMPTY_EVALUATION")
    if split["kind"] != "diagnostic":
        require(not exposed & {r["signal_date"] for r in evaluation}, "EXPOSED_DATE_DIAGNOSTIC_ONLY")
    # Purge even training dates before the split whose labels mature in evaluation.
    train = [r for r in rows if day(r["signal_date"]) <= train_end
             and day(r["label_end_date"]) < start]
    require(train, "EMPTY_TRAIN_AFTER_PURGE")
    require({int(float(r["label"])) for r in train} == {0, 1}, "TRAIN_REQUIRES_TWO_CLASSES")
    cutoff = day(split["truth_asof"])
    require(all(day(r["label_end_date"]) <= cutoff for r in evaluation), "EVAL_LABEL_IMMATURE")
    return train, evaluation


def fit_model(train, config, arm, *, synthetic):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    x = np.asarray([feature_values(r, config, arm) for r in train], dtype=float)
    y = np.asarray([int(float(r["label"])) for r in train])
    scaler = StandardScaler().fit(x)
    estimator = LogisticRegression(C=1.0, penalty="l2", solver="lbfgs",
                                   random_state=194, max_iter=1000, tol=1e-8)
    kind = "synthetic" if synthetic else "real"
    FIT_COUNTS[kind + "_fit_entered"] += 1
    estimator.fit(scaler.transform(x), y)
    FIT_COUNTS[kind + "_fit_returned"] += 1
    require(int(estimator.n_iter_[0]) < 1000, "FIT_NOT_CONVERGED")
    return dict(schema="V194_LOGISTIC_JSON_V1", arm=arm, features=feature_names(config, arm),
                mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                coef=estimator.coef_[0].tolist(), intercept=float(estimator.intercept_[0]),
                config=config, evidence_level="ENGINEERING_CANARY_ONLY" if synthetic else "DIRECTION_ONLY",
                **FLAGS)


def predict(model, rows):
    require(model.get("schema") == "V194_LOGISTIC_JSON_V1", "MODEL_SCHEMA")
    require(all(model.get(k) is v for k, v in FLAGS.items()), "UNSAFE_MODEL")
    config, arm = model["config"], model["arm"]
    require(model["features"] == feature_names(config, arm), "MODEL_FEATURE_ORDER_DRIFT")
    n = len(model["features"])
    require(all(len(model[k]) == n for k in ("mean", "scale", "coef")), "MODEL_SHAPE")
    require(all(number(s) > 0 for s in model["scale"]), "MODEL_SCALE")
    result = []
    for row in rows:
        x = feature_values(row, config, arm)
        z = number(model["intercept"]) + sum((v-number(m))/number(s)*number(c)
                for v, m, s, c in zip(x, model["mean"], model["scale"], model["coef"]))
        probability = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z)/(1+math.exp(z))
        result.append(dict(signal_date=row["signal_date"], code=row["code"], score=probability))
    return result


def top50(predictions):
    grouped = defaultdict(list)
    for row in predictions:
        grouped[row["signal_date"]].append(row)
    return [{**r, "rank": rank} for d in sorted(grouped)
            for rank, r in enumerate(sorted(grouped[d], key=lambda r: (-r["score"], r["code"]))[:50], 1)]


def metrics(selected, rows, truth_counts):
    truth = {(r["signal_date"], r["code"]): int(float(r["label"])) for r in rows}
    dates = sorted(truth_counts)
    require(dates and {r["signal_date"] for r in rows} <= set(dates), "FULL_UNIVERSE_TRUTH_DENOMINATORS_REQUIRED")
    daily = []
    for d in dates:
        count = truth_counts[d]
        require(isinstance(count, int) and not isinstance(count, bool) and count >= 0, "TRUTH_COUNT_INVALID")
        universe_positives = sum(v for (dt, _), v in truth.items() if dt == d)
        require(count >= universe_positives, "TRUTH_COUNT_BELOW_COHORT_POSITIVES")
        picks = [r for r in selected if r["signal_date"] == d]
        hits = sum(truth[(d, r["code"])] for r in picks)
        daily.append(dict(signal_date=d, hits=hits, selected=len(picks), selection_slots=50,
                          truth_positive_denominator=count))
    hits, slots, denominator = (sum(r[k] for r in daily) for k in
                                ("hits", "selection_slots", "truth_positive_denominator"))
    return dict(daily=daily, hits=hits, selection_slots=slots,
                actual_selected=sum(r["selected"] for r in daily),
                truth_positive_denominator=denominator,
                precision_at_50=hits/slots, recall=hits/denominator if denominator else None)


def train_run(config, manifest, rows, output, *, synthetic=False):
    validate_rows(rows, config, manifest, synthetic=synthetic)
    output = Path(output)
    require(not output.exists(), "OUTPUT_ALREADY_EXISTS")
    splits = config["splits"]
    require(splits and len({s["id"] for s in splits}) == len(splits), "SPLITS_EMPTY_OR_DUPLICATED")
    evaluated = set()
    # Validate all folds before the first fit, not after producing partial results.
    prepared = []
    for split in splits:
        train, evaluation = split_rows(rows, split)
        days = set(split["evaluation_dates"])
        require(days and all(day(split["eval_start"]) <= day(d) <= day(split["eval_end"]) for d in days),
                "EVALUATION_CALENDAR_INVALID")
        require({r["signal_date"] for r in evaluation} <= days, "EVALUATION_CALENDAR_INCOMPLETE")
        if split["kind"] != "diagnostic":
            require(not EXPOSED & days, "EXPOSED_DATE_DIAGNOSTIC_ONLY")
        require(not evaluated & days, "OVERLAPPING_EVALUATION_FOLDS")
        evaluated |= days
        counts = {d:manifest["truth_positive_counts"][d] for d in days}
        metrics([], evaluation, counts)  # Validate denominator dependencies before any fit.
        prepared.append((split, train, evaluation, counts))
    results = []
    for split, train, evaluation, counts in prepared:
        base = output / split["id"]
        save(base / "train_keys.json", [{k:r[k] for k in ("signal_date", "code", "label_end_date")} for r in train])
        for arm in ("baseline", "candidate"):
            model = fit_model(train, config, arm, synthetic=synthetic)
            model.update(train_max_signal_date=max(r["signal_date"] for r in train),
                         train_max_label_end_date=max(r["label_end_date"] for r in train),
                         evaluation_kind=split["kind"], split_id=split["id"])
            path = base / (arm + "_model.json")
            save(path, model)
            predictions = predict(model, evaluation)
            require(predictions == predict(load(path), evaluation), "SERIALIZATION_PARITY")
            picks = top50(predictions)
            save(base / (arm + "_predictions.json"), predictions)
            save(base / (arm + "_top50.json"), picks)
            result = dict(split_id=split["id"], kind=split["kind"], arm=arm,
                          metrics=metrics(picks, evaluation, counts), model_sha256=sha(path))
            save(base / (arm + "_metrics.json"), result)
            results.append(result)
    receipt = dict(status="ENGINEERING_CANARY_ONLY" if synthetic else "DIRECTION_ONLY",
                   results=results, fit_counts=dict(FIT_COUNTS), **FLAGS)
    save(output / "RESULT.json", receipt)
    return receipt


def read_csv(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("train", "predict"))
    parser.add_argument("execution_contract")
    args = parser.parse_args()
    from registry_bridge import register
    cp = Path(args.execution_contract)
    contract = load(cp)
    require(contract.get("execution_kind") == args.command.upper(), "EXECUTION_KIND_MISMATCH")
    register(cp, "RUN_STARTED", args.command.upper()+"_START", decision="RUNNING")
    try:
        run_config = Path(contract["run_config_path"])
        require(sha(run_config) == contract["run_config_sha256"], "RUN_CONFIG_DRIFT")
        cfg = load(run_config)
        for key in ("input_csv", "input_manifest"):
            require(sha(cfg[key]) == cfg[key+"_sha256"], "INPUT_DRIFT:"+key)
        manifest, rows = load(cfg["input_manifest"]), read_csv(cfg["input_csv"])
        if args.command == "train":
            result = train_run(cfg["model_config"], manifest, rows, cfg["output"])
        else:
            require(sha(cfg["model_path"]) == cfg["model_sha256"], "MODEL_DRIFT")
            model = load(cfg["model_path"])
            require(model["evidence_level"] != "ENGINEERING_CANARY_ONLY", "SYNTHETIC_MODEL_FOR_REAL_PREDICTION")
            validate_rows(rows, model["config"], manifest, labelled=False)
            require(all(day(r["signal_date"]) > day(model["train_max_label_end_date"]) for r in rows),
                    "PREDICTION_NOT_AFTER_TRAIN_LABEL_CUTOFF")
            save(cfg["output"], top50(predict(model, rows)))
            result = {"status":"RESEARCH_PREDICTION_ONLY", "fit_counts":dict(FIT_COUNTS)}
        register(cp, "TERMINAL", args.command.upper()+"_COMPLETE", [cfg["output"]] if args.command == "predict" else [str(Path(cfg["output"])/"RESULT.json")],
                 metrics=result["fit_counts"], decision=result["status"])
    except Exception as exc:
        register(cp, "TERMINAL", args.command.upper()+"_FAILED", metrics=FIT_COUNTS,
                 decision="FAILED:"+type(exc).__name__+":"+str(exc)[:250])
        raise


if __name__ == "__main__":
    # Thread limits precede NumPy/sklearn imports and remain bounded on this Mac.
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = "2"
    main()
