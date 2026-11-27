"""Mac-only ACT-078A driver: prep, 24 locked fits, one OOT opening."""

import argparse
import json
import os
import platform
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

import data as source
import models as model

GOVERNANCE = {
    "RESEARCH_ONLY": True, "NO_GO": True, "production_allowed": False,
    "buy_gate_updated": False, "orders_sent": 0, "P5.15": "0/0/0/0", "tuning": 0,
}
PREP_MODULES = ("data.py", "models.py")
RUN_MODULES = ("data.py", "models.py", "task.py", "evaluate.py")


def mkdir(root, name):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def code_identity(names):
    here = Path(__file__).parent
    return {name: source.sha_file(here / name) for name in names}


def write_json(path, content):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(content, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_identity(path):
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": source.sha_file(path)}


def elapsed(started):
    return round(perf_counter()-started, 6)


def profile(started, stage, substages, input_files, output_files):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "stage": stage, "wall_seconds": elapsed(started), "stage_seconds": substages,
        "pid": os.getpid(), "parent_pid": os.getppid(), "logical_cores": os.cpu_count(), "configured_tree_threads": model.ESTIMATOR_THREADS,
        "configured_blas_threads": 1,
        "peak_process_RSS_bytes": usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss*1024,
        "cpu_user_seconds": usage.ru_utime, "cpu_system_seconds": usage.ru_stime,
        "input_unique_file_bytes": sum(p.stat().st_size for p in input_files),
        "output_file_bytes_before_receipt": sum(p.stat().st_size for p in output_files),
        "input_bytes_scope": "logical unique file size, excludes repeated reads, OS cache and physical I/O",
        "upload_bytes": 0, "vm_block_reads": usage.ru_inblock, "vm_block_writes": usage.ru_oublock,
        "temporary_caches_created_n": 0, "temporary_caches_deleted_n": 0,
        "python_no_bytecode": bool(sys.dont_write_bytecode),
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                     "scikit_learn": sklearn.__version__, "joblib": joblib.__version__},
        "runtime": sys.executable,
    }


def membership_evidence(cohort):
    independent = cohort[cohort.trigger_role.eq("FIRST")]
    source.require(independent.structure_episode_id.is_unique and len(independent) == 2361, "Independent group ownership")
    source.require(independent.period.eq(independent.episode_period).all(), "First group partition mismatch")
    return {
        "by_period": {
            p: {
                "raw_frozen_triggers": int(cohort.period.eq(p).sum()),
                "independent_first_triggers": int(independent.period.eq(p).sum()),
                "confirm_triggers": int((cohort.period.eq(p) & cohort.trigger_role.eq("CONFIRM")).sum()),
                "repeat_triggers": int((cohort.period.eq(p) & cohort.trigger_role.eq("REPEAT")).sum()),
                "other_period_group_repeats": int((cohort.period.eq(p) & cohort.period.ne(cohort.episode_period)).sum()),
            }
            for p in ("TRAIN", "VAL", "OOT")
        },
        "groups_spanning_periods": int(cohort.groupby("structure_episode_id").period.nunique().gt(1).sum()),
        "cross_period_independent_group_overlap": 0,
    }


def prep(root):
    t0 = perf_counter()
    prep_dir, evidence_dir = mkdir(root, "prep"), mkdir(root, "evidence")
    sources = root / "sources"
    stage = {}
    hist = perf_counter()
    archives = source.verify_sources(sources)
    stage["zip_integrity"] = elapsed(hist)
    hist = perf_counter()
    chains, manifest = source.raw_chains(sources, source.PRE_OOT_END, archives)
    cohort, detail = source.read_frozen(sources, open_outcomes=False)
    source.require(set(cohort.security_id) == set(chains)-{"000001.SH"}, "Frozen raw roster mismatch")
    pre = cohort.loc[cohort.D.lt(source.OOT_START)]
    breadth = source.breadth_frame(chains)
    breadth_check = source.source_breadth_parity(sources, breadth, source.PRE_OOT_END)
    stage["parse_pre_oot_and_breadth"] = elapsed(hist)
    hist = perf_counter()
    features = source.feature_join(pre, chains, breadth)
    with_labels = source.outcome_join(features, chains)
    validation = source.frozen_parity(with_labels, detail, source.PRE_OOT_END)
    prefix = source.prefix_check(pre, chains, features)
    stage["features_labels_parity_prefix"] = elapsed(hist)
    hist = perf_counter()
    folds, warmup = model.build_folds(with_labels)
    evidence = membership_evidence(cohort)
    train_eligible = model.first_eligible(with_labels, "TRAIN", source.VAL_START)
    val_eligible = model.first_eligible(with_labels, "VAL", source.OOT_START)
    source.require(train_eligible.sum() > 0 and val_eligible.sum() > 0, "Empty final eligibility")
    require_target_sanity(with_labels, train_eligible, val_eligible)
    data_path = prep_dir / "pre_oot_features_labels.parquet"
    with_labels.to_parquet(data_path, index=False, compression="zstd")
    stage["fold_plan_and_write_pre_oot"] = elapsed(hist)
    receipt = {
        "status": "PREP_CANARY_PASS", "governance": GOVERNANCE, "FIT_STARTED": 0, "OOT_OPENED": False,
        "feature_dimension": len(source.FEATURES), "features": source.FEATURES, "prep_code": code_identity(PREP_MODULES),
        "pre_oot_parquet": file_identity(data_path), "sources": archives, "source_breadth_parity": breadth_check,
        "frozen_pair_parity_pre_oot": validation, "prefix_canaries": prefix,
        "roster_sha256": source.ROSTER_SHA, "frozen_cohort_last_D": source.FROZEN_END,
        "raw_source_last_D": source.RAW_ASOF, "bounded_pre_oot_cutoff": source.PRE_OOT_END,
        "stock_chains": int(manifest.security_id.ne("000001.SH").sum()),
        "raw_stock_sessions_manifest": int(manifest.loc[manifest.security_id.ne("000001.SH"), "rows_full"].sum()),
        "raw_index_sessions_manifest": int(manifest.loc[manifest.security_id.eq("000001.SH"), "rows_full"].sum()),
        "split": evidence, "oof_warmup": warmup,
        "oof_fold_plan": [{k:v for k,v in x.items() if not k.endswith("_mask")} for x in folds],
        "train_final_maturity_5d_before_val_n": int(train_eligible.sum()),
        "val_freeze_maturity_5d_before_oot_n": int(val_eligible.sum()),
        "pre_oot_feature_missing_counts": with_labels[list(source.FEATURES)].isna().sum().astype(int).to_dict(),
        "pre_oot_anchor_audit": "All frozen causal anchor dates and day lows matched stock raw",
        "first_probe_failure": "600519.SH outside the authorized roster; canary substituted real BJ boundary 920748.BJ before FIT",
        "resource": profile(t0, "prep", stage, [sources/name for name in archives], [data_path]),
    }
    write_json(evidence_dir / "prep_receipt.json", receipt)
    return {k: receipt[k] for k in ("status", "feature_dimension", "split", "oof_warmup",
                                     "train_final_maturity_5d_before_val_n", "val_freeze_maturity_5d_before_oot_n")}


def require_target_sanity(frame, train, val):
    for name, mask, date in (("Train", train, source.VAL_START), ("Val", val, source.OOT_START)):
        rows = frame[mask]
        source.require(rows.maturity_5_D.lt(date).all() and rows.tail_std.isin([0.0, 1.0]).all()
                       and rows[["t2_net", "t5_net"]].notna().all().all(),
                       f"{name} maturity or outcomes invalid")
        source.require(rows.structure_episode_id.is_unique, f"{name} group purity")


def claim(path, stage):
    with path.open("x", encoding="utf-8") as stream:
        event = {"stage": stage, "pid": os.getpid(), "utc": datetime.now(timezone.utc).isoformat()}
        json.dump(event, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def fit(root):
    started = perf_counter()
    prep_receipt_path = root / "evidence" / "prep_receipt.json"
    prep_receipt = read_json(prep_receipt_path)
    parquet_path = root / "prep" / "pre_oot_features_labels.parquet"
    source.require(prep_receipt["status"] == "PREP_CANARY_PASS" and not prep_receipt["OOT_OPENED"], "Missing prep gate")
    source.require(prep_receipt["prep_code"] == code_identity(PREP_MODULES), "Preflight definitions drifted")
    source.require(prep_receipt["pre_oot_parquet"] == file_identity(parquet_path), "Prep dataset changed")
    complete_code_identity = code_identity(RUN_MODULES)
    dataset = pd.read_parquet(parquet_path)
    source.require(dataset.D.lt(source.OOT_START).all(), "FIT parsed OOT rows")
    folds, warmup = model.build_folds(dataset)
    stages = {}
    run_dir = mkdir(root, "run")
    weights = mkdir(run_dir, "weights")
    claim(run_dir / "FIT_CLAIM.json", "24_FIXED_FITS")
    journal = run_dir / "fit_journal.jsonl"
    journal.touch(exist_ok=False)
    all_pre = pd.DataFrame(index=dataset.index)
    time_fit = perf_counter()
    for fold in folds:
        train = dataset[fold["fit_mask"]]
        selected = dataset[fold["score_mask"]]
        fold_models = {family: model.budgeted_fit(family, f"OOF-{fold['fold']}-{family}", train, journal)
                       for family in model.FAMILY_NAMES}
        predictions = model.predictions(fold_models, selected)
        for column in predictions:
            all_pre.loc[selected.index, column] = predictions[column]
        all_pre.loc[selected.index, "score_source"] = f"OOF{fold['fold']}"
    stages["5_chronological_folds_20_fits"] = elapsed(time_fit)
    time_fit = perf_counter()
    train_mask = model.first_eligible(dataset, "TRAIN", source.VAL_START)
    val_mask = model.first_eligible(dataset, "VAL", source.OOT_START)
    require_target_sanity(dataset, train_mask, val_mask)
    train, val = dataset[train_mask], dataset[val_mask]
    source.require(set(train.structure_episode_id).isdisjoint(val.structure_episode_id), "Train Val group overlap")
    refit = {family: model.budgeted_fit(family, f"REFIT-{family}", train, journal) for family in model.FAMILY_NAMES}
    weight_paths = [model.save_refit(weights, family, refit[family]) for family in model.FAMILY_NAMES]
    stages["full_train_4_refits"] = elapsed(time_fit)
    time_fit = perf_counter()
    val_score_rows = dataset[dataset.period.eq("VAL") & dataset.episode_period.eq("VAL")]
    val_pred = model.predictions(refit, val_score_rows)
    lock = model.freeze_rank_lock(val_pred.loc[val.index], val)
    tier_check = model.tiered(val, val_pred.loc[val.index], lock)
    source.require(tier_check.candidate_tier.eq("A").sum() == lock["val_a_n"]
                   and tier_check.candidate_tier.isin(model.V22_POSITIVE).sum() == lock["val_a_or_b_n"],
                   "Frozen tier counts differ from Val quota")
    for column in val_pred:
        all_pre.loc[val_score_rows.index, column] = val_pred[column]
    all_pre.loc[val_score_rows.index, "score_source"] = "VAL_FROM_TRAIN"
    score_ready = model.tiered(dataset[["security_id", "D"]], all_pre.drop(columns="score_source"), lock)
    score_ready["score_source"] = all_pre.score_source
    pre_path = run_dir / "pre_oot_scores.parquet"
    score_ready.to_parquet(pre_path, index=False, compression="zstd")
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    real_fit = sum(x["event"] == "FIT_COMPLETED" for x in events)
    source.require(len(events) == 2*model.FIT_CAP and real_fit == model.FIT_CAP, "FIT journal completion gate")
    stages["val_score_cutoff_lock"] = elapsed(time_fit)
    lock.update(
        status="TRAIN_AND_VAL_LOCKED", fit_started=model.FIT_CAP, fit_completed=real_fit, fit_after_lock=0,
        tuning=0, locked_before_oot=True, governance=GOVERNANCE,
        code_identity=complete_code_identity, prep_receipt=file_identity(prep_receipt_path), prep_source=prep_receipt["pre_oot_parquet"],
        family_configs=model.FAMILY_CONFIG, feature_order=list(source.FEATURES),
        fit_journal=file_identity(journal), pre_oot_scores=file_identity(pre_path),
        refit_weights={p.stem:file_identity(p) for p in weight_paths},
        train_shape=[len(train), len(source.FEATURES)], train_label_last_D=str(train.maturity_5_D.max()),
        target="safe: tail_std == 0; return: (t2_net + t5_net)/2 with source contract fee",
        oof_warmup=warmup, oof_group_overlap_n=0, train_val_overlap_n=0,
        resource=profile(started, "fit", stages, [prep_receipt_path, parquet_path], [journal, pre_path, *weight_paths]),
    )
    lock_path = run_dir / "FROZEN_RANK_LOCK.json"
    write_json(lock_path, lock)
    return {"status": lock["status"], "fit_completed": real_fit, "lock_sha256": source.sha_file(lock_path),
            "val_n": lock["val_first_mature_n"], "val_A": lock["val_a_n"], "val_AB": lock["val_a_or_b_n"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prep", "fit", "oot"))
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    source.require(sys.dont_write_bytecode, "Run with python -B")
    with threadpool_limits(limits=1):
        if args.phase == "prep":
            output = prep(args.artifact_root)
        elif args.phase == "fit":
            output = fit(args.artifact_root)
        else:
            from evaluate import oot
            try:
                output = oot(args.artifact_root)
            except BaseException as error:
                marker = args.artifact_root / "run" / "OOT_OPEN_CLAIM.json"
                if marker.exists() and read_json(marker)["pid"] == os.getpid():
                    write_json(marker.with_name("OOT_FAILURE.json"),
                               {"status": "OOT_FAILED_AFTER_CLAIM", "error": repr(error), "fit_after_lock": 0,
                                "detail": "Preserve this single-open claim and completed intermediate artifacts."})
                raise
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
