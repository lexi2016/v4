"""Read-only preparation from the pinned Run A and official six archives."""
from __future__ import annotations

import ast
from collections import Counter
from hashlib import sha256
from importlib.metadata import distribution
from io import BytesIO
import json
from pathlib import Path
import struct
from types import ModuleType
from zipfile import ZipFile

RUN_A = "aa4de242906913e5a369b93bc304bdde64ded10de77f2d3fe67bdf20203f5fa2"
RUN_A_ARCHIVE = "3aacce2591b727061ce129142e4e943a7f95374d53996514dd9d9257aaf05454"
ORIGINAL_PRELAUNCH = "80627b6745184753e032dfbd17d01ffec305b079ef2978b4eb1455f1433d6dbc"
CANONICAL_DIRECTORY = "/working_dir/c_c0c316eeb60f3f13/work/canonical_budget_p515_pb15_r1"
TASK = "P515_GEMINI_STAGE_PB15_DEV_TRAIN_R1_V1"
COUNTS = {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2, "failed_attempts": 1}
BUDGET = {"max_preprocessing_fit": 4, "max_model_fit": 4, "max_model_api": 3, "final_dev_predict_api": 0}
LR_PARAMS = {
    "C": 0.1, "class_weight": None, "fit_intercept": True, "max_iter": 1000,
    "random_state": 0, "solver": "lbfgs", "tol": 1e-8, "warm_start": False,
}
V4_DEPS = {
    "mac_six_zip_adapter.py": "6a6f6cfc898142d6a32a60d90c83b3fb762b440240d4c32255663ac09ce2e5c8",
    "stage_pb15_feature_and_fold_contract.py": "85cfeb23e24891bfeefcba94931dda5bc1b404c30eb7332a8b7342a1662bd400",
    "stage_pb15_train_runner.py": "b43c1858eaadfffa554bdc0dae036b11dc0987d59755bbcdcfbbf6969f06ac36",
}
SKLEARN_FILES = {
    "sklearn/linear_model/_logistic.py": "683755f12d707f3109e7207c60b27aec76e9a98433bb1b02617f972ccc03edb8",
    "sklearn/preprocessing/_data.py": "f9a1f300ddc85cd4ca08e5cbcb8151b625d487ec2a6796ec2758344f20d9ce0e",
}
MATRIX_SHA = "bd862ad1f204c507284324a06033016a5dad770530cf7642c21dfbf776f65d22"
FOLDS_SHA = "bbf2a5abe9f7c9d6aee6e76b93c0fd6bcdaff53e4752480c86c3c31b919e4b62"
F2_F3 = {
    "F2": (9503, "4854d4c0d15816f76ed563ebba10c19ce7d248d78cbb7c9b93c46e64fd71efa3"),
    "F3": (5250, "11f81b9e995c60ecceedda6882a852c86ea4ba45314b2e9eef66e08328308833"),
}
SOURCE_ROLES = ("zip", "candidate_rows", "native_lifecycle", "native_daily", "screen_bars", "original_recovery")
ROLE_SUFFIX = {"zip": "RESULTS", **{r: r.upper() for r in SOURCE_ROLES if r != "zip"}}
ROLE_PREFIX = "P515_MAC_STAGE_PB15_DATA_MATERIALIZATION_R1_V1_"


class InputError(ValueError):
    """Pinned research input is absent or has a different identity."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(blob):
    return sha256(blob).hexdigest()


def need(condition, detail):
    if not condition:
        raise InputError(detail)


def read_pinned(path, expected):
    raw = Path(path).read_bytes()
    need(digest(raw) == expected, f"wrong SHA256 for {Path(path).name}")
    return raw


def unzip(path, expected):
    with ZipFile(BytesIO(read_pinned(path, expected))) as archive:
        names = archive.namelist()
        need(len(names) == len(set(names)) and archive.testzip() is None, "corrupt or duplicate archive members")
        return {name: archive.read(name) for name in names}


def verify_run_a(archive: Path, prelaunch: Path) -> dict:
    """Verify the immutable archive. Never open the canonical directory for writing."""
    run = unzip(archive, RUN_A_ARCHIVE)
    pre = unzip(prelaunch, ORIGINAL_PRELAUNCH)
    raw_identity = pre["PRELAUNCH_EXECUTION_IDENTITY.json"]
    identity = json.loads(raw_identity)
    need(digest(canonical(identity)) == RUN_A, "Run A manifest does not reproduce the original identity")
    need(json.loads(run["real_prelaunch/PRELAUNCH_EXECUTION_IDENTITY.json"]) == identity, "PRELAUNCH differs in Run A")
    need(identity["canonical_budget_dir"] == CANONICAL_DIRECTORY, "original canonical binding changed")
    need(identity["budget_caps"] == BUDGET and identity["frozen_lr_params"] == LR_PARAMS, "frozen configuration differs")
    members = {k.removeprefix("canonical_budget/"): v for k, v in run.items() if k.startswith("canonical_budget/")}
    binding = json.loads(members["CANONICAL_TASK_BINDING.json"])
    need(binding["execution_identity_sha256"] == RUN_A and binding["task_id"] == TASK, "wrong canonical task")
    ledger = members["CANONICAL_TASK_LEDGER.jsonl"]
    need(digest(ledger) == "3da0f149fadcec8bbd62897ea8107bb359e4dbeb8302970349aa5135db5a22ea", "wrong event prefix")
    events = [json.loads(line) for line in ledger.splitlines()]
    starts = [e for e in events if e["event"].endswith("_START")]
    filenames = [f'tokens/{e["unit"]}_{e["kind"]}_START.json' for e in starts]
    need(len(events) == 14 and len(starts) == 7 and len(members) == 12, "invalid historical event or member count")
    need(set(filenames) == {n for n in members if n.startswith("tokens/")}, "incomplete START token set")
    moment_key = ("started_at_beijing", "recorded_at_beijing", "ts_beijing", "created_at_beijing")
    for name, event in zip(filenames, starts):
        token = json.loads(members[name])
        if "unit" in token:
            need(token["unit"] == event["unit"], "historical START token unit mismatch")
        if "kind" in token:
            need(token["kind"] == event["kind"], "historical START token kind mismatch")
        if "started_at_beijing" in token:
            need(token["started_at_beijing"] in {event.get(k) for k in moment_key}, "historical START token time mismatch")
    need(digest(members["tokens/F1_PREPROC_FIT_START.json"]) ==
         "7135ce2016dd285de48dc48fda675e2da7d675044f10277064ad3c89b7c70c0c", "F1 failure START identity differs")
    kc = Counter(e["kind"] for e in starts)
    need(dict(kc) == {"PREPROC_FIT": 3, "MODEL_FIT": 2, "PREDICT_API": 2}, "historic budgets differ")
    f1 = json.loads(members["unit_summaries/F1_UNIT_SUMMARY.json"])
    need(f1["unit_status"] == "FAILED_ERROR" and f1["failed_stage"] == "PREPROC_FIT"
         and sum(e["event"] == "PREPROC_FIT_ERROR" and e["unit"] == "F1" for e in events) == 1, "F1 failure not retained")
    units = {"F1": {"state": "FAILED_ERROR", "identity": RUN_A, "failed_stage": f1["failed_stage"]}}
    for name, (rows, expected_sha) in F2_F3.items():
        summary = json.loads(members[f"unit_summaries/{name}_UNIT_SUMMARY.json"])
        pfx = f"real_training_outputs/raw_outputs/{name}_"
        predictions = run[pfx + "RAW_PREDICTIONS.jsonl"]
        need(summary["unit_status"] == "COMPLETED_OK" and summary["holdout_matured_rows"] == rows
             and len(predictions.splitlines()) == rows and digest(predictions) == expected_sha, f"{name} historic output differs")
        units[name] = {"state": "COMMITTED", "identity": RUN_A, "rows": rows, "sha256": expected_sha,
                       "model_scaler_sha256": digest(run[pfx + "MODEL_AND_SCALER.json"]),
                       "per_parent_metrics_sha256": digest(run[pfx + "PER_PARENT_METRICS.json"])}
    historical_files = {k: {"sha256": digest(v), "bytes": len(v)} for k, v in members.items()}
    return {
        "execution_identity_sha256": RUN_A, "counts": dict(COUNTS), "historical_units": units,
        "historical_files": historical_files, "events": 14, "start_tokens": 7,
        "historical_events": events,
        "historical_start_tokens": {name: json.loads(members[name]) for name in sorted(filenames)},
        "historical_binding": binding,
        "raw_historic_predictions": sum(row for row, _ in F2_F3.values()),
        "archive_sha256": RUN_A_ARCHIVE, "original_prelaunch_sha256": ORIGINAL_PRELAUNCH,
        "original_identity_manifest": identity,
    }


def verify_canonical_readonly(root, baseline):
    """If a live or exported canonical path is available, enforce all original archived byte identities."""
    root = Path(root)
    matches = []
    for name, identity in baseline["historical_files"].items():
        p = root / name
        if p.exists() and p.stat().st_size == identity["bytes"] and digest(p.read_bytes()) == identity["sha256"]:
            matches.append(name)
    need(len(matches) == len(baseline["historical_files"]), "original canonical history differs from archival bytes")
    lock = root / "CANONICAL_TASK.lock"
    return {"matched": sorted(matches), "matched_count": len(matches), "lock_id": digest(lock.read_bytes()) if lock.is_file() else None}


def load_pure_v4(v4_dir):
    """Execute the pinned data-only routines and leave every historical trainer function out."""
    import hashlib
    import inspect

    sklearn_dist = distribution("scikit-learn")
    need(sklearn_dist.version == "1.8.0", "frozen scikit-learn build 1.8.0 required for dependency byte verification")
    runtime = {name: Path(sklearn_dist.locate_file(name)).resolve() for name in SKLEARN_FILES}
    for name, path in runtime.items():
        read_pinned(path, SKLEARN_FILES[name])
    va = Path(v4_dir)
    names = tuple(V4_DEPS)
    sources = {name: read_pinned(va / name, V4_DEPS[name]) for name in names}
    modules = {}
    for name in names[:2]:
        path = va / name
        mod = ModuleType(path.stem)
        mod.__file__ = str(path.resolve())
        exec(compile(sources[name], mod.__file__, "exec"), mod.__dict__)
        modules[path.stem] = mod
    runner_path = va / names[2]
    tree = ast.parse(sources[names[2]])
    allowed = {"canonical_identity_sha256", "build_execution_identity_manifest", "prepare_and_verify_official_mac_six_zip"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in allowed]
    need({node.name for node in body} == allowed, "missing official read-only runner functions")
    future = next(node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "__future__")
    logistic = ModuleType("historical_logistic_source_identity")
    logistic.__file__ = str(runtime["sklearn/linear_model/_logistic.py"])
    ns = {
        "fc": modules["stage_pb15_feature_and_fold_contract"], "mac_adp": modules["mac_six_zip_adapter"],
        "__file__": str(runner_path.resolve()), "_sk_logistic": logistic,
        "hashlib": hashlib, "inspect": inspect, "Path": Path, "json": json,
        "FROZEN_LR_PARAMS": dict(LR_PARAMS), "MAX_MODEL_FIT_BUDGET": BUDGET["max_model_fit"],
        "MAX_PREPROC_FIT_BUDGET": BUDGET["max_preprocessing_fit"], "MAX_MODEL_API_BUDGET": BUDGET["max_model_api"],
    }
    exec(compile(ast.Module(body=[future, *body], type_ignores=[]), ns["__file__"], "exec"), ns)
    deps = {f"deps/v4/{name}": str((va / name).resolve()) for name in names}
    deps.update({f"deps/{name}": str(path) for name, path in runtime.items()})
    return ns["fc"], ns["prepare_and_verify_official_mac_six_zip"], deps


def fold_manifest(fc, split):
    def keys(rows):
        return [[r[k] for k in fc.ROW_KEY_FIELDS] for r in rows]

    def weights(fold):
        return [[key, round(w, 15)] for key, w in zip(keys(fold["train_rows"]), fold["train_weights"], strict=True)]

    folds = {}
    purge = {}
    for name, f in split["folds"].items():
        folds[name] = {"min_holdout_first_d": f["min_holdout_first_d"], "train_keys_and_weights": weights(f),
                       "holdout_keys": keys(f["holdout_matured_rows"])}
        purge[name] = {"purged": f["purge_audit"], "unresolved_keys": keys(f["holdout_unresolved_rows"]),
                       "holdout_matured_labels": [r["pb15_label"] for r in f["holdout_matured_rows"]]}
    folds["FINAL_DEV"] = {"train_keys_and_weights": weights(split["final_dev"]), "predict_api_cap": 0}
    need(digest(canonical(folds)) == FOLDS_SHA == fc.compute_folds_manifest_sha256(split), "exact original fold composition differs")
    return folds, purge


def prepare_official(config: dict) -> dict:
    paths = {k: Path(config[k]).resolve() for k in (
        "archive", "original_prelaunch", "v4_dir", "six_zip_dir", "mac_entry", "mac_manifest", "mac_receipt",
        "universe_csv", "frozen_calendar",
    )}
    baseline = verify_run_a(paths["archive"], paths["original_prelaunch"])
    if config.get("legacy_canonical"):
        baseline["canonical_snapshot"] = verify_canonical_readonly(config["legacy_canonical"], baseline)
    original = baseline["original_identity_manifest"]
    fc, prepare, source_paths = load_pure_v4(paths["v4_dir"])
    six = {role: paths["six_zip_dir"] / f"{ROLE_PREFIX}{ROLE_SUFFIX[role]}.zip" for role in SOURCE_ROLES}
    for role, path in six.items():
        frozen = original["mac_remote_identity"]["six_zips"][role]
        need(path.stat().st_size == frozen["expected_bytes"], f"{role} size differs")
        read_pinned(path, frozen["expected_sha256"])
    prep = prepare(
        mac_entry_path=paths["mac_entry"], mac_manifest_path=paths["mac_manifest"], mac_receipt_path=paths["mac_receipt"],
        local_zip_paths_by_role=six, d17_universe_csv_path=paths["universe_csv"],
        frozen_calendar_json_path=paths["frozen_calendar"], canonical_budget_dir=Path(CANONICAL_DIRECTORY),
    )
    actual = prep["execution_identity"]
    need(actual["execution_identity_sha256"] == RUN_A and actual["manifest"] == original, "exact V4 execution identity differs")
    split = prep["split_bundle"]
    all_rows = split["normalized_rows"]
    h = sha256()
    for row in all_rows:
        h.update(struct.pack("<10d", *row["feature_vector_10"]))
    need(len(all_rows) == 41055 and len(all_rows) * 80 == prep["matrix_bytes_len"]
         and h.hexdigest() == prep["matrix_sha256"] == MATRIX_SHA, "80-byte input matrix differs")
    folds, purge = fold_manifest(fc, split)
    f1, final = split["folds"]["F1"], split["final_dev"]
    hold = f1["holdout_matured_rows"]
    need(len(hold) == 9055 and len({r["parent_id"] for r in hold}) == 1912, "wrong F1 recovery scope")
    units = {}
    for key, f, ho in (("F1_RETRY", f1, hold), ("FINAL_DEV", final, [])):
        units[key] = {
            "train_rows": f["train_rows"], "train_weights": f["train_weights"], "holdout_rows": ho,
        }
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        if not p.name.startswith(("test_", "bench_")):
            source_paths[f"src/research/p515_recovery_v8/{p.name}"] = str(p)
    source_files = {name: digest(Path(path).read_bytes()) for name, path in source_paths.items()}
    identity = {
        "execution_identity_sha256": RUN_A, "original_prelaunch_sha256": ORIGINAL_PRELAUNCH,
        "v8_source_and_dependency_sha256": source_files, "entrypoint": "research.p515_recovery_v8.cli",
        "source_controls": original["mac_remote_identity"]["control_files"],
        "six_zip_sha256": {role: original["mac_remote_identity"]["six_zips"][role]["expected_sha256"] for role in SOURCE_ROLES},
        "frozen_sources": original["frozen_source_identities"], "feature_columns": list(fc.FEATURE_COLUMNS_10),
        "row_bytes": 80, "matrix_rows": len(all_rows), "matrix_sha256": MATRIX_SHA,
        "fold_manifest": folds, "fold_manifest_sha256": FOLDS_SHA,
        "purge_and_pending": purge, "purge_and_pending_sha256": digest(canonical(purge)),
        "lr_params": dict(LR_PARAMS), "historical_budget_caps": dict(BUDGET),
    }
    return {
        "scope": "OFFICIAL", "execution_identity_sha256": RUN_A, "baseline": baseline,
        "official_config": {key: str(Path(value).resolve()) for key, value in config.items() if value is not None},
        "identity": identity, "units": units, "source_paths": source_paths, "source_files": source_files,
        "expected_output_rows": {"F1_RETRY": 9055}, "expected_output_parents": {"F1_RETRY": 1912},
    }
