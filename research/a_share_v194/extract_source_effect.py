"""Describe a registered, saved repaired-source run. Never fit or alter inputs."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

SOURCES = ("source_fupan", "source_stage7", "source_research")
STATES = ("hit", "confirmed_absent", "unknown")
FLAGS = dict(research_only=True, production_allowed=False,
             buy_gate_updated=False, orders_sent=False)


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(row):
    return row["target_date"], row["code"]


def unique(rows):
    result = {key(row): row for row in rows}
    assert len(result) == len(rows), "DUPLICATE_KEY"
    return result


def states(rows, source):
    assert all(row[source] in STATES for row in rows), "INVALID_SOURCE_STATE"
    return {state: dict(rows=sum(row[source] == state for row in rows),
                        dates=len({row["target_date"] for row in rows
                                   if row[source] == state})) for state in STATES}


def feature(row, name, technical):
    source, suffix = name.split("__", 1)
    assert source in SOURCES
    if suffix == "technical_resonance":
        return int(row[source] == "hit" and any(float(row[c]) for c in technical))
    assert suffix in STATES
    return int(row[source] == suffix)


def extract(manifest_path, expected_sha, run_dir, old_run_dir, old_manifest_path):
    assert sha(manifest_path) == expected_sha, "MANIFEST_DRIFT"
    manifest = load(manifest_path)
    item = manifest["files"]["candidates"]
    candidate_path = Path(item["path"])
    if not candidate_path.is_absolute():
        candidate_path = Path(manifest_path).parent / candidate_path
    assert sha(candidate_path) == item["sha256"], "CANDIDATE_DRIFT"
    with candidate_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_key = unique(rows)
    run_dir, old_run_dir = Path(run_dir), Path(old_run_dir)
    freeze = load(run_dir / "RUN_FREEZE.json")
    assert freeze["identity"]["manifest_sha256"] == expected_sha
    technical = manifest["technical_features"]
    folds, coefficients, daily = [], [], []
    for split in freeze["splits"]:
        folder = run_dir / split["id"]
        train_keys = load(folder / "train_keys.json")
        train = [by_key[key(row)] for row in train_keys]
        prediction = {arm: unique(load(folder / (arm + "_predictions.json")))
                      for arm in ("baseline", "candidate")}
        assert prediction["baseline"].keys() == prediction["candidate"].keys()
        evaluation = [by_key[k] for k in prediction["baseline"]]
        model = load(folder / "candidate_model.json")
        feature_rows = []
        for j, name in enumerate(model["features"]):
            if j < len(technical):
                continue
            values = Counter(feature(row, name, technical) for row in train)
            record = dict(fold=split["id"], feature=name,
                          train_zero=values[0], train_one=values[1],
                          train_constant=len(values) <= 1,
                          mean=model["mean"][j], scale=model["scale"][j],
                          coefficient=model["coef"][j],
                          coefficient_nonzero=model["coef"][j] != 0)
            coefficients.append(record)
            feature_rows.append(record)
        folds.append(dict(fold=split["id"], train_rows=len(train),
                          evaluation_rows=len(evaluation),
                          source_coverage={source: dict(train=states(train, source),
                                                       evaluation=states(evaluation, source))
                                           for source in SOURCES},
                          nonconstant_source_features=sum(not r["train_constant"] for r in feature_rows),
                          nonzero_source_coefficients=sum(r["coefficient_nonzero"] for r in feature_rows)))
        picks = {arm: load(folder / (arm + "_top50.json"))
                 for arm in ("baseline", "candidate")}
        for date in split["evaluation_target_dates"]:
            ks = [k for k in prediction["baseline"] if k[0] == date]
            deltas = [prediction["candidate"][k]["score"] -
                      prediction["baseline"][k]["score"] for k in ks]
            ordered = {arm: [r["code"] for r in sorted(
                (r for r in picks[arm] if r["target_date"] == date),
                key=lambda r: r["rank"])] for arm in picks}
            b, c = ordered["baseline"], ordered["candidate"]
            full_orders = {arm: [k[1] for k in sorted(
                ks, key=lambda k: (-prediction[arm][k]["score"], k[1]))]
                           for arm in prediction}
            daily.append(dict(fold=split["id"], target_date=date,
                              prediction_rows=len(ks),
                              probability_changed_rows=sum(delta != 0 for delta in deltas),
                              max_abs_probability_delta=max(map(abs, deltas), default=0),
                              full_order_position_changes=sum(
                                  a != b for a, b in zip(full_orders["baseline"],
                                                        full_orders["candidate"])),
                              top50_set_symmetric_difference=len(set(b) ^ set(c)),
                              top50_order_equal=b == c,
                              baseline_only_codes=sorted(set(b) - set(c)),
                              candidate_only_codes=sorted(set(c) - set(b))))
    old_freeze = load(old_run_dir / "RUN_FREEZE.json")
    old_manifest = load(old_manifest_path)
    return dict(schema="V194_REPAIRED_SOURCE_EFFECT_DESCRIPTION_R1",
                input_manifest_sha256=expected_sha, folds=folds,
                source_feature_coefficients=coefficients, daily_prediction_differences=daily,
                daily_hits=load(run_dir / "OOF_METRICS.json")["daily"],
                cohort_boundary=dict(old_eligible_dates=old_freeze["eligible_target_dates"],
                                     new_eligible_dates=freeze["eligible_target_dates"],
                                     old_model_candidate_rows=old_manifest.get("candidate_rows"),
                                     new_model_candidate_rows=len(rows),
                                     new_raw_candidate_union_rows=manifest.get("raw_candidate_union_rows"),
                                     old_new_total_hits_are_not_same_sample_winner_comparison=True),
                no_extra_fits=True, ablation_performed=False,
                originals_modified=False, **FLAGS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("manifest", "manifest-sha256", "run-dir", "old-run-dir", "old-manifest", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = extract(args.manifest, args.manifest_sha256, args.run_dir,
                     args.old_run_dir, args.old_manifest)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
