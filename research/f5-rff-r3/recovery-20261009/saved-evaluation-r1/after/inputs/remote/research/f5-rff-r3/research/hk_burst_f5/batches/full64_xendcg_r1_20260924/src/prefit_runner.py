#!/usr/bin/env python3
"""Parent-release-gated, zero-fit prefit for the full-history XENDCG route.

This is a file-backed entry point. It appends the official no-fit RUN_STARTED
event before a spawned worker opens any frozen fold input. The worker checks
input identities, train row/key/label alignment, deterministic groups, and
train-only LightGBM Dataset reference inheritance; it never fits or predicts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[5]
BATCH_ROOT = PROJECT_ROOT / "research/hk_burst_f5/batches/full64_xendcg_r1_20260924"
RUN_SPEC_PATH = BATCH_ROOT / "contracts/RUN_SPEC.json"
INPUT_BINDING_PATH = BATCH_ROOT / "contracts/INPUT_BINDING.json"
PLAN_PACKAGE_BINDING_PATH = BATCH_ROOT / "input_refs/PLAN_PACKAGE_BINDING.json"
PLAN_PATH = BATCH_ROOT / "input_refs/plan_package/TRAINING_PLAN.json"
PREFIT_RELEASE_PATH = BATCH_ROOT / "input_refs/PREFIT_PARENT_ROW_READ_RELEASE.json"
PREFIT_REVIEW_RECEIPT_PATH = PROJECT_ROOT / "handoffs/F5_FULL64_XENDCG_R1_20260924/PREFIT_ENTRY_REVIEW_TRANSCRIPT.json"
PREFIT_DIR = BATCH_ROOT / "prefit"
RESULT_PATH = PREFIT_DIR / "PREFIT_RESULT_RECEIPT.json"
RUN_RECEIPT_PATH = PREFIT_DIR / "PREFIT_RUN_RECEIPT.json"
WORKER_STATUS_PATH = PREFIT_DIR / "PREFIT_WORKER_STATUS.json"
WORKER_START_PATH = PREFIT_DIR / "PREFIT_WORKER_START_RECEIPT.json"
INPUT_HASH_PATH = PREFIT_DIR / "PREFIT_INPUT_HASH_RECEIPT.json"
TRAIN_LABEL_READ_START_PATH = PREFIT_DIR / "TRAIN_LABEL_READ_START_RECEIPT.json"
RESOURCE_TRACE_PATH = PREFIT_DIR / "PREFIT_RESOURCE_TRACE.json"

ROUTE_ID = "F5_FULL64_XENDCG_R1_20260924"
EXECUTION_ID = "F5_FULL64_XENDCG_R1_20260924_PREFIT"
OFFICIAL_REGISTRY_PATH = PROJECT_ROOT / "contracts/EXPERIMENT_REGISTRY.jsonl"
RESOURCE_TREE_PATH = PROJECT_ROOT / "research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/src/resource_tree.py"
NATIVE_RUNTIME_PATH = PROJECT_ROOT / "research/hk_burst_f5/batches/factory_pilot_20260920/train_resume_20260921/src/f5_native_runtime.py"
NATIVE_REFERENCE_CONTRACT_PATH = PROJECT_ROOT / "research/hk_burst_f5/batches/meta2023_baseplus64_r1_20260923/calendar_adapter_20260924/contracts/contract.json"

OFFICIAL_HELPERS = {
    "execution_guard": PROJECT_ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/execution_guard_core.py",
    "registry_adapter": PROJECT_ROOT / "workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity/registry_adapter.py",
    "builder": PROJECT_ROOT / "contracts/build_experiment_registry_backfill_20260821.py",
    "validator": PROJECT_ROOT / "contracts/validate_experiment_registry_append_compatibility_v1.py",
}

RESOURCE_CAPS = {
    "wall_seconds_max": 600,
    "aggregate_process_tree_rss_bytes_max": 3221225472,
    "cpu_threads": 4,
    "sampling_interval_seconds": 0.05,
    "workers": 1,
}


class PrefitError(RuntimeError):
    """A frozen identity, scope, or prefit invariant failed."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrefitError(f"JSON_READ_FAILED:{Path(path).name}") from exc
    if not isinstance(value, dict):
        raise PrefitError(f"JSON_NOT_OBJECT:{Path(path).name}")
    return value


def read_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    """Parse one byte snapshot and retain its digest for the start guard."""
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrefitError(f"JSON_SNAPSHOT_READ_FAILED:{Path(path).name}") from exc
    if not isinstance(value, dict):
        raise PrefitError(f"JSON_NOT_OBJECT:{Path(path).name}")
    return value, sha256_bytes(raw)


def _verify_code_binding(code_files: Mapping[str, Any], expected_code_sha256: str) -> None:
    """Verify the canonical source manifest and each current source byte file."""
    code_payload = json.dumps(dict(code_files), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if sha256_bytes(code_payload) != expected_code_sha256:
        raise PrefitError("CODE_BINDING_CANONICAL_SHA_MISMATCH")
    _verify_file_bindings(code_files, error_prefix="BOUND_CODE_SHA_MISMATCH")


def _verify_file_bindings(files: Mapping[str, Any], *, error_prefix: str) -> None:
    for name, item in files.items():
        path = Path(str(item["path"]))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise PrefitError(f"{error_prefix}:{name}")


def _executable_helper_bindings(binding: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    files = {str(name): dict(item) for name, item in binding["official_helpers"].items()}
    files.update({
        "resource_tree": {"path": str(binding["resource_tree_path"]), "sha256": str(binding["resource_tree_sha256"])},
        "native_runtime": {"path": str(binding["native_runtime_path"]), "sha256": str(binding["native_runtime_sha256"])},
        "native_reference_contract": {
            "path": str(binding["native_reference_contract_path"]),
            "sha256": str(binding["native_reference_contract_sha256"]),
        },
    })
    return files


def _verify_start_snapshots(
    *,
    release_path: Path,
    expected_release_sha256: str,
    reviewer_receipt_path: Path,
    expected_reviewer_receipt_sha256: str,
    run_spec_path: Path,
    expected_run_spec_sha256: str,
    input_binding_path: Path,
    expected_input_binding_sha256: str,
    code_files: Mapping[str, Any],
    expected_code_sha256: str,
    executable_helpers: Mapping[str, Any],
) -> None:
    """Recheck the parent authorization and source identity at durable start."""
    for path, expected, error in (
        (release_path, expected_release_sha256, "PARENT_PREFIT_RELEASE_CHANGED_BEFORE_RUN_STARTED"),
        (reviewer_receipt_path, expected_reviewer_receipt_sha256, "PREFIT_REVIEW_RECEIPT_CHANGED_BEFORE_RUN_STARTED"),
        (run_spec_path, expected_run_spec_sha256, "RUN_SPEC_CHANGED_BEFORE_RUN_STARTED"),
        (input_binding_path, expected_input_binding_sha256, "INPUT_BINDING_CHANGED_BEFORE_RUN_STARTED"),
    ):
        path = Path(path)
        if not path.is_file() or sha256_file(path) != expected:
            raise PrefitError(error)
    _verify_code_binding(code_files, expected_code_sha256)
    _verify_file_bindings(executable_helpers, error_prefix="EXECUTABLE_HELPER_SHA_MISMATCH")


def _read_verified_prefit_review_receipt(
    receipt_path: Path,
    *,
    run_spec_sha256: str,
    input_binding_sha256: str,
    source_code_sha256: str,
) -> tuple[dict[str, Any], str]:
    resolved = Path(receipt_path).resolve()
    receipt, receipt_sha = read_json_snapshot(resolved)
    expected_receipt = {
        "schema": "F5_FULL64_XENDCG_PREFIT_ENTRY_REVIEW_TRANSCRIPT_V1",
        "reviewer_agent": "/root/xendcg_review",
        "reviewer_verdict": "PASS",
        "route_id": ROUTE_ID,
        "execution_id": EXECUTION_ID,
        "run_spec_sha256": run_spec_sha256,
        "input_binding_sha256": input_binding_sha256,
        "source_code_sha256": source_code_sha256,
    }
    for key, value in expected_receipt.items():
        if receipt.get(key) != value:
            raise PrefitError(f"PREFIT_REVIEW_RECEIPT_MISMATCH:{key}")
    return receipt, receipt_sha


def _validate_resource_caps(run_spec: Mapping[str, Any], binding: Mapping[str, Any]) -> None:
    expected_run_resources = {
        "aggregate_process_tree_rss_bytes_max": RESOURCE_CAPS["aggregate_process_tree_rss_bytes_max"],
        "cpu_threads": RESOURCE_CAPS["cpu_threads"],
        "hard_peak_guarantee": False,
        "sampling_interval_seconds": RESOURCE_CAPS["sampling_interval_seconds"],
        "wall_seconds_max": RESOURCE_CAPS["wall_seconds_max"],
        "workers": RESOURCE_CAPS["workers"],
    }
    if run_spec.get("resources") != expected_run_resources or binding.get("resource_caps") != RESOURCE_CAPS:
        raise PrefitError("PREFIT_RESOURCE_CAPS_DIFFERS_FROM_EXECUTOR")


def durable_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, path)
        os.unlink(temp_name)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def durable_npy_exclusive(path: Path, array: Any) -> None:
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.save(stream, array, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_static_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read only frozen small metadata; this never opens a fold input."""
    run_spec = read_json(RUN_SPEC_PATH)
    binding = read_json(INPUT_BINDING_PATH)
    plan_binding = read_json(PLAN_PACKAGE_BINDING_PATH)
    run_sha = sha256_file(RUN_SPEC_PATH)
    binding_sha = sha256_file(INPUT_BINDING_PATH)
    if run_spec.get("route_id") != ROUTE_ID or binding.get("route_id") != ROUTE_ID:
        raise PrefitError("ROUTE_ID_MISMATCH")
    if run_spec.get("input_binding_path") != str(INPUT_BINDING_PATH.resolve()) or run_spec.get("prefit_parent_release_path") != str(PREFIT_RELEASE_PATH.resolve()):
        raise PrefitError("RUN_SPEC_STAGE_PATHS_MISMATCH")
    if binding.get("run_spec_path") != str(RUN_SPEC_PATH.resolve()) or binding.get("run_spec_sha256") != run_sha:
        raise PrefitError("RUN_SPEC_BINDING_MISMATCH")
    if binding.get("plan_package_binding_sha256") != sha256_file(PLAN_PACKAGE_BINDING_PATH):
        raise PrefitError("PLAN_PACKAGE_BINDING_SHA_MISMATCH")
    for name, item in plan_binding.get("payloads", {}).items():
        path = BATCH_ROOT / "input_refs/plan_package" / name
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get("sha256"):
            raise PrefitError(f"PLAN_PACKAGE_PAYLOAD_SHA_MISMATCH:{name}")
    if binding.get("parent_plan_sha256") != run_spec.get("parent_plan_sha256"):
        raise PrefitError("PARENT_PLAN_SHA_MISMATCH")
    if binding.get("frozen_input_sha256") != run_spec.get("frozen_input_sha256"):
        raise PrefitError("INPUT_MANIFEST_DIFFERS_FROM_RUN_SPEC")
    if binding.get("execution_id") != EXECUTION_ID or run_spec.get("execution_id") != EXECUTION_ID:
        raise PrefitError("PREFIT_EXECUTION_ID_MISMATCH")
    plan = read_json(PLAN_PATH)
    source_facts = read_json(BATCH_ROOT / "input_refs/plan_package/SOURCE_FACTS.json")
    learner_params = read_json(BATCH_ROOT / "input_refs/plan_package/FROZEN_LEARNER_PARAMS.json")
    if binding.get("feature_names") != plan.get("training", {}).get("features"):
        raise PrefitError("FROZEN_FEATURE_ORDER_MISMATCH")
    expected_training_contract = {
        "expected_rows": plan["training"]["expected_rows"],
        "feature_count": plan["training"]["feature_count"],
        "expected_feature_dtype": run_spec["data_contract"]["expected_feature_dtype"],
        "expected_label_dtype": run_spec["data_contract"]["expected_label_dtype"],
        "expected_positive_rows": plan["training"]["expected_positive_rows"],
        "expected_groups": plan["training"]["expected_sessions_from_historical_receipt"],
        "cutoff_ns": plan["training"]["cutoff_ns"],
        "purge_label_end_strictly_before": source_facts["frozen_2024_fold"]["purge_label_end_strictly_before"],
    }
    if binding.get("training_contract") != expected_training_contract:
        raise PrefitError("TRAINING_CONTRACT_DIFFERS_FROM_FROZEN_PLAN")
    _validate_resource_caps(run_spec, binding)
    expected_dataset_params = {
        "bin_construct_sample_cnt": learner_params["bin_construct_sample_cnt"],
        "data_random_seed": learner_params["data_random_seed"],
        "feature_pre_filter": True,
        "max_bin": learner_params["max_bin"],
        "min_data_in_leaf": learner_params["min_data_in_leaf"],
        "use_missing": learner_params["use_missing"],
        "zero_as_missing": learner_params["zero_as_missing"],
    }
    if binding.get("dataset_params") != expected_dataset_params:
        raise PrefitError("DATASET_PARAMS_DIFFERS_FROM_FROZEN_LEARNER")

    if not isinstance(binding.get("code_sha256"), str) or len(binding["code_sha256"]) != 64:
        raise PrefitError("CODE_BINDING_SHA_MISSING")
    _verify_code_binding(binding.get("code_files", {}), binding["code_sha256"])
    for name, item in binding.get("official_helpers", {}).items():
        path = Path(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise PrefitError(f"OFFICIAL_HELPER_SHA_MISMATCH:{name}")
    for path_key, sha_key, path in (
        ("resource_tree_path", "resource_tree_sha256", RESOURCE_TREE_PATH),
        ("native_runtime_path", "native_runtime_sha256", NATIVE_RUNTIME_PATH),
        ("native_reference_contract_path", "native_reference_contract_sha256", NATIVE_REFERENCE_CONTRACT_PATH),
    ):
        if binding.get(path_key) != str(path.resolve()) or binding.get(sha_key) != sha256_file(path):
            raise PrefitError(f"NATIVE_HELPER_IDENTITY_MISMATCH:{path_key}")

    files = binding.get("input_files")
    if not isinstance(files, dict) or set(files) != set(run_spec.get("frozen_input_sha256", {})):
        raise PrefitError("INPUT_FILE_MANIFEST_KEYS_MISMATCH")
    for name, expected_sha in run_spec["frozen_input_sha256"].items():
        item = files[name]
        if item.get("path") != str((Path(run_spec["source_data_root"]) / name).resolve()) or item.get("sha256") != expected_sha:
            raise PrefitError(f"INPUT_FILE_BINDING_MISMATCH:{name}")

    params = binding.get("dataset_params")
    if not isinstance(params, dict) or params.get("max_bin") != 63 or params.get("bin_construct_sample_cnt") != 200000:
        raise PrefitError("DATASET_BIN_PARAMS_NOT_FROZEN")
    if params.get("data_random_seed") != 42 or params.get("min_data_in_leaf") != 50:
        raise PrefitError("DATASET_RANDOM_OR_PREFILTER_PARAMS_NOT_FROZEN")
    if params.get("use_missing") is not True or params.get("zero_as_missing") is not False:
        raise PrefitError("DATASET_MISSING_VALUE_PARAMS_NOT_FROZEN")

    if binding.get("official_registry_path") != str(OFFICIAL_REGISTRY_PATH.resolve()):
        raise PrefitError("OFFICIAL_REGISTRY_PATH_MISMATCH")
    expected_outputs = {
        "root": str(PREFIT_DIR.resolve()),
        "result": str(RESULT_PATH.resolve()),
        "run_receipt": str(RUN_RECEIPT_PATH.resolve()),
        "resource_trace": str(RESOURCE_TRACE_PATH.resolve()),
        "worker_status": str(WORKER_STATUS_PATH.resolve()),
        "worker_start": str(WORKER_START_PATH.resolve()),
        "input_hash_receipt": str(INPUT_HASH_PATH.resolve()),
        "train_label_read_start": str(TRAIN_LABEL_READ_START_PATH.resolve()),
        "permutation": str((PREFIT_DIR / "TRAIN_PERMUTATION.npy").resolve()),
        "inverse_permutation": str((PREFIT_DIR / "TRAIN_INVERSE_PERMUTATION.npy").resolve()),
        "group_sizes": str((PREFIT_DIR / "TRAIN_GROUP_SIZES.npy").resolve()),
        "group_binding": str((PREFIT_DIR / "GROUP_BINDING.json").resolve()),
        "preprocessing": str((PREFIT_DIR / "PREPROCESSING.json").resolve()),
    }
    if binding.get("prefit_output_paths") != expected_outputs:
        raise PrefitError("PREFIT_OUTPUT_PATH_BINDING_MISMATCH")
    reviewer_receipt_path = Path(binding["engineering_canary_review_receipt_path"])
    if not reviewer_receipt_path.is_file() or sha256_file(reviewer_receipt_path) != binding["engineering_canary_review_receipt_sha256"]:
        raise PrefitError("ENGINEERING_REVIEW_RECEIPT_SHA_MISMATCH")
    native_canary_path = Path(binding["native_startup_canary_receipt_path"])
    if not native_canary_path.is_file() or sha256_file(native_canary_path) != binding["native_startup_canary_receipt_sha256"]:
        raise PrefitError("NATIVE_STARTUP_CANARY_RECEIPT_SHA_MISMATCH")
    native_trace_path = Path(binding["native_resource_trace_path"])
    if not native_trace_path.is_file() or sha256_file(native_trace_path) != binding["native_resource_trace_sha256"]:
        raise PrefitError("NATIVE_RESOURCE_TRACE_SHA_MISMATCH")
    return run_spec, binding, plan_binding


def validate_prefit_release(
    release: Mapping[str, Any],
    *,
    run_spec: Mapping[str, Any],
    binding: Mapping[str, Any],
    run_spec_sha256: str,
    input_binding_sha256: str,
    official_registry_sha256: str,
    reviewer_receipt_path: Path = PREFIT_REVIEW_RECEIPT_PATH,
) -> None:
    """Fail closed unless this exact parent release permits this no-fit stage."""
    _receipt, reviewer_receipt_sha256 = _read_verified_prefit_review_receipt(
        reviewer_receipt_path,
        run_spec_sha256=run_spec_sha256,
        input_binding_sha256=input_binding_sha256,
        source_code_sha256=str(binding["code_sha256"]),
    )
    expected = {
        "schema": "F5_FULL64_XENDCG_PREFIT_PARENT_ROW_READ_RELEASE_V1",
        "active": True,
        "route_id": ROUTE_ID,
        "execution_id": EXECUTION_ID,
        "stage": "INCREMENTAL_PREFIT",
        "run_spec_sha256": run_spec_sha256,
        "input_binding_sha256": input_binding_sha256,
        "parent_plan_sha256": binding["parent_plan_sha256"],
        "source_code_sha256": binding["code_sha256"],
        "official_registry_path": str(OFFICIAL_REGISTRY_PATH.resolve()),
        "official_registry_sha256_before_start": official_registry_sha256,
        "input_files_authorized": sorted(binding["input_files"]),
        "training_rows_decode_authorized": ["X_train.npy", "y_train.npy", "train_keys.csv.gz"],
        "eval_input_hash_only": ["X_eval.npy", "eval_calendar.csv.gz", "eval_meta.csv.gz"],
        "eval_label_values_decode_authorized": False,
        "fit_calls_authorized": 0,
        "predict_calls_authorized": 0,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "resource_caps": RESOURCE_CAPS,
        "reviewer_agent": "/root/xendcg_review",
        "reviewer_verdict": "PASS",
        "reviewer_receipt_path": str(Path(reviewer_receipt_path).resolve()),
        "reviewer_receipt_sha256": reviewer_receipt_sha256,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for key, value in expected.items():
        if release.get(key) != value:
            raise PrefitError(f"PARENT_PREFIT_RELEASE_MISMATCH:{key}")
    if not isinstance(release.get("parent_authorization_id"), str) or not release["parent_authorization_id"].strip():
        raise PrefitError("PARENT_AUTHORIZATION_ID_MISSING")
    if run_spec.get("authorization", {}).get("candidate_fit") != "NOT_AUTHORIZED_UNTIL_PARENT_CANDIDATE_RELEASE":
        raise PrefitError("RUN_SPEC_CANDIDATE_SCOPE_CHANGED")


def validate_training_rows(
    features: Any,
    labels: Any,
    keys: Any,
    *,
    expected_rows: int,
    expected_features: int,
    expected_positive_rows: int,
    expected_groups: int,
    expected_label_dtype: str,
    cutoff_ns: int,
    purge_label_end_strictly_before: int,
    grouping_module: Any,
) -> tuple[Any, dict[str, Any]]:
    """Validate exact full-fold rows and derive the session-list permutation."""
    import numpy as np
    import pandas as pd

    x = np.asarray(features)
    y = np.asarray(labels)
    if not isinstance(keys, pd.DataFrame):
        raise PrefitError("TRAIN_KEYS_NOT_DATAFRAME")
    required = {"code", "session_id", "market_date", "label_end", "label_mature_ns", "y"}
    if not required.issubset(keys.columns):
        raise PrefitError("TRAIN_KEYS_SCHEMA_MISMATCH")
    if x.shape != (expected_rows, expected_features) or x.dtype != np.dtype("float32"):
        raise PrefitError("TRAIN_FEATURE_SHAPE_OR_DTYPE_MISMATCH")
    if y.shape != (expected_rows,) or y.dtype != np.dtype(expected_label_dtype) or not np.isfinite(y).all() or not np.isin(y, (0.0, 1.0)).all():
        raise PrefitError("TRAIN_LABEL_SHAPE_OR_DOMAIN_MISMATCH")
    if np.isinf(x).any():
        raise PrefitError("TRAIN_FEATURE_INFINITY_FORBIDDEN")
    if len(keys) != expected_rows:
        raise PrefitError("TRAIN_KEYS_ROW_COUNT_MISMATCH")
    if keys["code"].isna().any():
        raise PrefitError("TRAIN_KEYS_CODE_MISSING")
    raw_codes = keys["code"].astype(str)
    if raw_codes.eq("").any() or raw_codes.ne(raw_codes.str.strip()).any():
        raise PrefitError("TRAIN_KEYS_CODE_NOT_CANONICAL")

    try:
        session_series = pd.to_numeric(keys["session_id"], errors="raise")
        key_labels = pd.to_numeric(keys["y"], errors="raise").to_numpy(dtype=np.float64)
        label_end_series = pd.to_numeric(keys["label_end"], errors="raise")
        label_mature_series = pd.to_numeric(keys["label_mature_ns"], errors="raise")
        codes = keys["code"].astype("string").to_numpy(dtype=str)
    except Exception as exc:
        raise PrefitError("TRAIN_KEYS_VALUE_PARSE_FAILED") from exc
    if not all(pd.api.types.is_integer_dtype(series.dtype) for series in (session_series, label_end_series, label_mature_series)):
        raise PrefitError("TRAIN_KEYS_INTEGER_METADATA_INVALID")
    key_sessions = session_series.to_numpy(dtype=np.int64)
    label_end = label_end_series.to_numpy(dtype=np.int64)
    label_mature = label_mature_series.to_numpy(dtype=np.int64)
    if not np.array_equal(y.astype(np.float64, copy=False), key_labels):
        raise PrefitError("TRAIN_Y_DOES_NOT_MATCH_ROW_KEY_LABELS")
    positives = int(y.sum(dtype=np.float64))
    if positives != expected_positive_rows or int(np.count_nonzero(y == 0)) != expected_rows - expected_positive_rows:
        raise PrefitError("TRAIN_LABEL_COUNTS_MISMATCH")
    if not np.all(label_end < int(purge_label_end_strictly_before)):
        raise PrefitError("TRAIN_LABEL_END_PURITY_CUTOFF_MISMATCH")
    if not np.all(label_mature < int(cutoff_ns)):
        raise PrefitError("TRAIN_LABEL_MATURITY_CUTOFF_MISMATCH")
    market_dates = pd.to_datetime(keys["market_date"], errors="coerce")
    if market_dates.isna().any():
        raise PrefitError("TRAIN_KEY_MARKET_DATE_INVALID")

    plan = grouping_module.build_grouping_plan(
        x,
        y,
        key_sessions,
        codes,
        expected_features=expected_features,
        expected_rows=expected_rows,
        expected_groups=expected_groups,
        require_original_code_session_order=True,
    )
    if int(plan.group_sizes.sum(dtype=np.int64)) != expected_rows:
        raise PrefitError("TRAIN_GROUP_SIZES_DO_NOT_COVER_ALL_ROWS")
    if not np.array_equal(plan.grouped_labels_int32, y[plan.permutation].astype(np.int32)):
        raise PrefitError("GROUPED_LABEL_VIEW_MISMATCH")
    return plan, {
        "rows": expected_rows,
        "features": expected_features,
        "positive_rows": positives,
        "negative_rows": expected_rows - positives,
        "sessions": expected_groups,
        "market_date_first": market_dates.min().strftime("%Y-%m-%d"),
        "market_date_last": market_dates.max().strftime("%Y-%m-%d"),
        "label_end_min": int(label_end.min()),
        "label_end_max": int(label_end.max()),
        "label_mature_ns_min": int(label_mature.min()),
        "label_mature_ns_max": int(label_mature.max()),
        "features_nan_count": int(np.isnan(x).sum()),
        "features_nan_preserved_by_inverse": True,
        "scoreable_eval_rows_decoded": False,
        "eval_label_values_decoded": False,
    }


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PrefitError(f"MODULE_LOAD_SPEC_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _input_snapshot_and_dataset(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Worker only: called after official RUN_STARTED, reads bound bytes once."""
    _verify_code_binding(payload["code_files"], str(payload["source_code_sha256"]))
    _verify_file_bindings(
        {"native_runtime": {"path": payload["native_runtime_path"], "sha256": payload["native_runtime_sha256"]}},
        error_prefix="EXECUTABLE_HELPER_SHA_MISMATCH",
    )
    import io

    runtime = _load_module(Path(payload["native_runtime_path"]), "f5_xendcg_native_runtime_prefit")
    identities = runtime.verify_child_launch_environment(payload["native_spec"])
    import lightgbm
    import lightgbm.libpath
    import numpy as np
    import pandas as pd

    native = payload["native_spec"]
    library_path = Path(lightgbm.libpath._LIB._name).resolve()
    if lightgbm.__version__ != native["lightgbm_version"] or str(library_path) != str(Path(native["lightgbm_library_path"]).resolve()):
        raise PrefitError("LIGHTGBM_NATIVE_IDENTITY_MISMATCH")
    if sha256_file(library_path) != native["lightgbm_library_sha256"]:
        raise PrefitError("LIGHTGBM_NATIVE_LIBRARY_SHA_MISMATCH")
    identities.update({
        "lightgbm_version": lightgbm.__version__,
        "lightgbm_library_path": str(library_path),
        "lightgbm_library_sha256": sha256_file(library_path),
        "lightgbm_train_calls": 0,
        "lightgbm_predict_calls": 0,
    })

    durable_json_exclusive(WORKER_START_PATH, {
        "schema": "F5_FULL64_XENDCG_PREFIT_WORKER_START_V1",
        "status": "WORKER_STARTED_AFTER_PARENT_RELEASE_AND_OFFICIAL_RUN_STARTED",
        "execution_id": EXECUTION_ID,
        "parent_release_sha256": payload["parent_release_sha256"],
        "source_code_sha256": payload["source_code_sha256"],
        "worker_pid": os.getpid(),
        "worker_parent_pid": os.getppid(),
        "real_input_bytes_read": False,
        "fit_calls": 0,
        "predict_calls": 0,
    })

    snapshots: dict[str, bytes] = {}
    input_sha: dict[str, str] = {}
    for name, item in payload["input_files"].items():
        path = Path(item["path"])
        if not path.is_file():
            raise PrefitError(f"BOUND_INPUT_MISSING:{name}")
        data = path.read_bytes()
        digest = sha256_bytes(data)
        if digest != item["sha256"]:
            raise PrefitError(f"BOUND_INPUT_SHA_MISMATCH:{name}:{digest}")
        snapshots[name] = data
        input_sha[name] = digest

    durable_json_exclusive(INPUT_HASH_PATH, {
        "schema": "F5_FULL64_XENDCG_PREFIT_INPUT_HASH_RECEIPT_V1",
        "execution_id": EXECUTION_ID,
        "input_sha256": input_sha,
        "all_six_frozen_inputs_verified": True,
        "eval_input_hash_only": ["X_eval.npy", "eval_calendar.csv.gz", "eval_meta.csv.gz"],
        "eval_label_values_decoded": False,
    })

    durable_json_exclusive(TRAIN_LABEL_READ_START_PATH, {
        "schema": "F5_FULL64_XENDCG_PREFIT_TRAIN_LABEL_READ_START_V1",
        "execution_id": EXECUTION_ID,
        "training_label_inputs_about_to_be_decoded": ["y_train.npy", "train_keys.csv.gz"],
        "evaluation_label_values_decoded": False,
        "fit_calls": 0,
        "predict_calls": 0,
    })
    x = np.load(io.BytesIO(snapshots["X_train.npy"]), allow_pickle=False)
    y = np.load(io.BytesIO(snapshots["y_train.npy"]), allow_pickle=False)
    try:
        keys = pd.read_csv(
            io.BytesIO(snapshots["train_keys.csv.gz"]),
            compression="gzip",
            usecols=["code", "session_id", "market_date", "label_end", "label_mature_ns", "y"],
            dtype={"code": "string"},
        )
        keys = keys.loc[:, ["code", "session_id", "market_date", "label_end", "label_mature_ns", "y"]]
    except Exception as exc:
        raise PrefitError(f"TRAIN_KEYS_GZIP_PARSE_FAILED:{type(exc).__name__}") from exc
    del snapshots["X_train.npy"], snapshots["y_train.npy"], snapshots["train_keys.csv.gz"]

    _verify_code_binding(payload["code_files"], str(payload["source_code_sha256"]))
    grouping_module = _load_module(Path(payload["grouping_path"]), "f5_full64_xendcg_grouping_prefit")
    stats = payload["training_contract"]
    plan, row_evidence = validate_training_rows(
        x,
        y,
        keys,
        expected_rows=int(stats["expected_rows"]),
        expected_features=int(stats["feature_count"]),
        expected_positive_rows=int(stats["expected_positive_rows"]),
        expected_groups=int(stats["expected_groups"]),
        expected_label_dtype=str(stats["expected_label_dtype"]),
        cutoff_ns=int(stats["cutoff_ns"]),
        purge_label_end_strictly_before=int(stats["purge_label_end_strictly_before"]),
        grouping_module=grouping_module,
    )

    dataset_params = dict(payload["dataset_params"])
    reference, grouped, dataset_evidence = grouping_module.build_reference_datasets(
        lightgbm,
        x,
        y,
        plan,
        dataset_params=dataset_params,
    )
    if reference.num_data() != len(x) or grouped.num_data() != len(x) or reference.num_feature() != x.shape[1] or grouped.num_feature() != x.shape[1]:
        raise PrefitError("LIGHTGBM_DATASET_SHAPE_MISMATCH")
    if not np.array_equal(reference.get_label(), y.astype(np.float32)):
        raise PrefitError("REFERENCE_DATASET_LABEL_ORDER_MISMATCH")
    if not np.array_equal(grouped.get_label(), plan.grouped_labels_int32.astype(np.float32)):
        raise PrefitError("GROUPED_DATASET_LABEL_ORDER_MISMATCH")

    key_digest = hashlib.sha256()
    for session_id, code in zip(keys["session_id"].to_numpy(), keys["code"].astype("string").to_numpy(dtype=str)):
        key_digest.update(str(int(session_id)).encode("ascii"))
        key_digest.update(b"\t")
        key_digest.update(code.encode("utf-8"))
        key_digest.update(b"\n")

    durable_npy_exclusive(PREFIT_DIR / "TRAIN_PERMUTATION.npy", plan.permutation)
    durable_npy_exclusive(PREFIT_DIR / "TRAIN_INVERSE_PERMUTATION.npy", plan.inverse_permutation)
    durable_npy_exclusive(PREFIT_DIR / "TRAIN_GROUP_SIZES.npy", plan.group_sizes)
    group_binding = {
        "schema": "F5_FULL64_XENDCG_GROUP_BINDING_V1",
        "route_id": ROUTE_ID,
        "execution_id": EXECUTION_ID,
        "input_sha256": input_sha,
        "ordered_session_code_sha256": key_digest.hexdigest(),
        "group_contract": {
            "groups": int(len(plan.group_sizes)),
            "rows": int(plan.group_sizes.sum(dtype=np.int64)),
            "all_negative_and_singleton_groups_retained": True,
            "group_sizes_sha256": sha256_file(PREFIT_DIR / "TRAIN_GROUP_SIZES.npy"),
            "permutation_sha256": sha256_file(PREFIT_DIR / "TRAIN_PERMUTATION.npy"),
            "inverse_permutation_sha256": sha256_file(PREFIT_DIR / "TRAIN_INVERSE_PERMUTATION.npy"),
            "permutation_bijective": True,
            "inverse_restores_features_labels_and_keys": True,
            "one_contiguous_block_per_session": True,
        },
        "dataset_reference": dataset_evidence,
        "feature_order": list(payload["feature_names"]),
        "fit_calls": 0,
        "predict_calls": 0,
        "eval_input_hash_only": ["X_eval.npy", "eval_calendar.csv.gz", "eval_meta.csv.gz"],
        "eval_label_values_decoded": False,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    durable_json_exclusive(PREFIT_DIR / "GROUP_BINDING.json", group_binding)
    preprocessing = {
        "schema": "F5_FULL64_XENDCG_PREFIT_PREPROCESSING_V1",
        "input_sha256": input_sha,
        "source_dtype": "float32",
        "feature_order": list(payload["feature_names"]),
        "features": row_evidence,
        "dataset_params": dataset_params,
        "dataset_reference": dataset_evidence,
        "scaler": None,
        "imputer": None,
        "binning": "original_order_train_only_reference_then_grouped_dataset_inherits_exact_reference",
        "fit_calls": 0,
        "predict_calls": 0,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "eval_label_values_decoded": False,
        "native_environment": identities,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    durable_json_exclusive(PREFIT_DIR / "PREPROCESSING.json", preprocessing)

    artifacts = [
        PREFIT_DIR / "TRAIN_PERMUTATION.npy",
        PREFIT_DIR / "TRAIN_INVERSE_PERMUTATION.npy",
        PREFIT_DIR / "TRAIN_GROUP_SIZES.npy",
        PREFIT_DIR / "GROUP_BINDING.json",
        PREFIT_DIR / "PREPROCESSING.json",
    ]
    result = {
        "schema": "F5_FULL64_XENDCG_PREFIT_RESULT_V1",
        "status": "PREFIT_COMPLETED_AWAITING_INDEPENDENT_DELTA_REVIEW_AND_CANDIDATE_RELEASE",
        "route_id": ROUTE_ID,
        "execution_id": EXECUTION_ID,
        "parent_authorization_id": payload["parent_authorization_id"],
        "parent_release_sha256": payload["parent_release_sha256"],
        "run_spec_sha256": payload["run_spec_sha256"],
        "input_binding_sha256": payload["input_binding_sha256"],
        "source_code_sha256": payload["source_code_sha256"],
        "input_sha256": input_sha,
        "training_rows": row_evidence,
        "group_binding_sha256": sha256_file(PREFIT_DIR / "GROUP_BINDING.json"),
        "preprocessing_sha256": sha256_file(PREFIT_DIR / "PREPROCESSING.json"),
        "artifacts": {str(path.resolve()): sha256_file(path) for path in artifacts},
        "fit_calls": 0,
        "predict_calls": 0,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "evaluation_label_values_decoded": False,
        "truth_access": "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED",
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    durable_json_exclusive(RESULT_PATH, result)
    durable_json_exclusive(WORKER_STATUS_PATH, {"status": "COMPLETED", "fit_calls": 0, "predict_calls": 0, "real_input_rows_read": int(len(keys)), "result_receipt_sha256": sha256_file(RESULT_PATH)})
    return result


def _prefit_worker(payload: Mapping[str, Any]) -> None:
    try:
        _input_snapshot_and_dataset(payload)
    except BaseException as exc:
        try:
            durable_json_exclusive(WORKER_STATUS_PATH, {
                "status": "FAILED",
                "fit_calls": 0,
                "predict_calls": 0,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
        except FileExistsError:
            pass
        raise


def _native_spec(binding: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    _verify_file_bindings(
        _executable_helper_bindings(binding),
        error_prefix="EXECUTABLE_HELPER_SHA_MISMATCH",
    )
    runtime = _load_module(NATIVE_RUNTIME_PATH, "f5_full64_xendcg_native_runtime_parent")
    old_contract = read_json(NATIVE_REFERENCE_CONTRACT_PATH)
    native_spec = runtime.native_spec_from_contract(old_contract)
    if Path(sys.executable).resolve() != Path(native_spec["python_executable_path"]).resolve():
        raise PrefitError("LOCKED_PYTHON_EXECUTABLE_MISMATCH")
    observed = runtime.validate_native_files(native_spec)
    if observed != binding.get("native_environment"):
        raise PrefitError("LOCKED_NATIVE_ENVIRONMENT_DIFFERS_FROM_ENGINEERING_CANARY")
    canary_path = Path(binding["native_startup_canary_receipt_path"])
    if not canary_path.is_file() or sha256_file(canary_path) != binding["native_startup_canary_receipt_sha256"]:
        raise PrefitError("NATIVE_STARTUP_CANARY_RECEIPT_SHA_MISMATCH")
    canary = read_json(canary_path)
    if canary.get("status") != "NATIVE_IMPORT_PASS_SYNTHETIC_ONLY" or canary.get("fit_calls") != 0 or canary.get("predict_calls") != 0:
        raise PrefitError("NATIVE_STARTUP_CANARY_NOT_ZERO_FIT_PASS")
    if sha256_file(RESOURCE_TREE_PATH) != binding["resource_tree_sha256"]:
        raise PrefitError("RESOURCE_TREE_HELPER_SHA_MISMATCH")
    return native_spec, NATIVE_RUNTIME_PATH


def _official_guard(
    binding: Mapping[str, Any],
    *,
    run_spec_sha: str,
    input_binding_sha: str,
    expected_registry_sha256: str,
    expected_release_sha256: str,
    expected_reviewer_receipt_sha256: str,
    expected_source_code_sha256: str,
):
    guard_path = Path(binding["official_helpers"]["execution_guard"]["path"])
    adapter_path = Path(binding["official_helpers"]["registry_adapter"]["path"])
    executable_helpers = _executable_helper_bindings(binding)
    _verify_file_bindings(executable_helpers, error_prefix="EXECUTABLE_HELPER_SHA_MISMATCH")
    if str(guard_path.parent) not in sys.path:
        sys.path.insert(0, str(guard_path.parent))
    guard_module = _load_module(guard_path, "f5_full64_xendcg_execution_guard")
    adapter_module = _load_module(adapter_path, "f5_full64_xendcg_registry_adapter")

    class RouteRegistryAdapter(adapter_module.OfficialRegistryAdapter):
        def claim_run_started(self, event: Mapping[str, Any], *, max_real_fit_debits: int) -> None:
            # Hold the official registry lock across the release-snapshot check
            # and append. The materializer, validator, flush, and fsync remain
            # the project's existing official adapter path.
            with self._locked():
                raw, events = self._read_validated()
                if sha256_bytes(raw) != expected_registry_sha256:
                    raise PrefitError("OFFICIAL_REGISTRY_CHANGED_AFTER_PARENT_RELEASE")
                _verify_start_snapshots(
                    release_path=PREFIT_RELEASE_PATH,
                    expected_release_sha256=expected_release_sha256,
                    reviewer_receipt_path=PREFIT_REVIEW_RECEIPT_PATH,
                    expected_reviewer_receipt_sha256=expected_reviewer_receipt_sha256,
                    run_spec_path=RUN_SPEC_PATH,
                    expected_run_spec_sha256=run_spec_sha,
                    input_binding_path=INPUT_BINDING_PATH,
                    expected_input_binding_sha256=input_binding_sha,
                    code_files=binding["code_files"],
                    expected_code_sha256=expected_source_code_sha256,
                    executable_helpers=executable_helpers,
                )
                if any(row.get("experiment_id") == ROUTE_ID for row in events):
                    raise PrefitError("ROUTE_ALREADY_REGISTERED_NO_PREFIT_REENTRY")
                if any(str(row.get("execution_id")) == EXECUTION_ID for row in events):
                    raise PrefitError("PREFIT_EXECUTION_ID_ALREADY_REGISTERED")
                if max_real_fit_debits != 1 or event.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY":
                    raise PrefitError("PREFIT_REQUIRES_ZERO_DEBIT_NO_FIT_GUARD")
                if (
                    event.get("experiment_id") != ROUTE_ID
                    or event.get("execution_id") != EXECUTION_ID
                    or event.get("contract_sha256") != run_spec_sha
                    or event.get("input_binding_sha256") != input_binding_sha
                ):
                    raise PrefitError("PREFIT_RUN_STARTED_IDENTITY_MISMATCH")
                if event.get("real_fit_budget_debit") != 0 or event.get("planned_real_fit_count") != 0:
                    raise PrefitError("PREFIT_RUN_STARTED_MUST_DEBIT_ZERO_FITS")
                self._append_unlocked(raw, events, self._event_spec(event, event_type="RUN_STARTED"))

        def _event_spec(self, event: Mapping[str, Any], *, event_type: str) -> dict[str, Any]:
            spec = super()._event_spec(event, event_type=event_type)
            spec["runtime"] = {
                "python": str(Path(sys.executable).resolve()),
                "python_version": sys.version.split()[0],
            }
            spec["code_sha256"] = expected_source_code_sha256
            if event_type == "TERMINAL":
                if RESULT_PATH.is_file():
                    spec["truth_access"] = "TRAIN_LABELS_READ_EVAL_LABELS_NOT_DECODED"
                elif TRAIN_LABEL_READ_START_PATH.is_file():
                    spec["truth_access"] = "TRAIN_LABEL_READ_STARTED_EVAL_LABELS_NOT_DECODED"
                elif INPUT_HASH_PATH.is_file():
                    spec["truth_access"] = "FROZEN_INPUT_BYTES_HASHED_TRAIN_LABELS_NOT_DECODED"
                else:
                    spec["truth_access"] = "NO_TRAIN_LABEL_DECODE_MARKER"
                spec["sealed_status"] = "EXPOSED_2024_LABELS_NOT_DECODED"
            return spec

    code_paths = [Path(item["path"]) for item in binding["code_files"].values()]
    artifact_paths = [
        RUN_SPEC_PATH,
        INPUT_BINDING_PATH,
        PLAN_PACKAGE_BINDING_PATH,
        PREFIT_RELEASE_PATH,
        *code_paths,
        RESOURCE_TREE_PATH,
        NATIVE_RUNTIME_PATH,
        NATIVE_REFERENCE_CONTRACT_PATH,
        *[Path(item["path"]) for item in binding["official_helpers"].values()],
    ]
    profile = {
        "track_id": "HK_BURST_F5_FULL_HISTORY_RESEARCH",
        "route_id": ROUTE_ID,
        "registration_mode": "LIVE_EXECUTION",
        "start_stage": "INCREMENTAL_PREFIT_RUN_STARTED",
        "terminal_stage": "INCREMENTAL_PREFIT_TERMINAL",
        "occurred_at_reason": "LIVE_EXECUTION_UTC",
        "baseline_id": "F5_FULL64_ORIGINAL_PLUS_PATH_BINARY_2024",
        "one_variable": "binary_BCE_to_native_rank_xendcg",
        "signal_scope": "ORIGINAL_2018_TO_2023_TRAINING_FOLD",
        "target_scope": "EXPOSED_2024_DEVELOPMENT_EVALUATION_NOT_DECODED_DURING_PREFIT",
        "device": "CPU_RESEARCH_ONLY",
        "evidence_level": "ENGINEERING_CANARY_ONLY",
    }
    adapter = RouteRegistryAdapter(
        registry_path=OFFICIAL_REGISTRY_PATH,
        contract_path=RUN_SPEC_PATH,
        input_binding_path=INPUT_BINDING_PATH,
        artifact_paths=artifact_paths,
        builder_path=Path(binding["official_helpers"]["builder"]["path"]),
        validator_path=Path(binding["official_helpers"]["validator"]["path"]),
        event_profile=profile,
    )
    guard = guard_module.ExecutionGuard(adapter, experiment_id=ROUTE_ID, max_real_fit_debits=1)
    return guard, adapter


def _resource_tree_module(binding: Mapping[str, Any]):
    if sha256_file(RESOURCE_TREE_PATH) != binding["resource_tree_sha256"]:
        raise PrefitError("RESOURCE_TREE_HELPER_SHA_MISMATCH")
    if str(RESOURCE_TREE_PATH.parent) not in sys.path:
        sys.path.insert(0, str(RESOURCE_TREE_PATH.parent))
    return _load_module(RESOURCE_TREE_PATH, "f5_full64_xendcg_resource_tree")


def run_prefit() -> dict[str, Any]:
    run_spec, binding, _plan_binding = load_static_contract()
    run_spec_sha = sha256_file(RUN_SPEC_PATH)
    input_binding_sha = sha256_file(INPUT_BINDING_PATH)
    release, release_sha = read_json_snapshot(PREFIT_RELEASE_PATH)
    if not OFFICIAL_REGISTRY_PATH.is_file():
        raise PrefitError("OFFICIAL_REGISTRY_MISSING")
    registry_sha = sha256_file(OFFICIAL_REGISTRY_PATH)
    validate_prefit_release(
        release,
        run_spec=run_spec,
        binding=binding,
        run_spec_sha256=run_spec_sha,
        input_binding_sha256=input_binding_sha,
        official_registry_sha256=registry_sha,
        reviewer_receipt_path=PREFIT_REVIEW_RECEIPT_PATH,
    )
    if PREFIT_DIR.exists():
        raise PrefitError("PREFIT_OUTPUTS_ALREADY_EXIST_NO_REENTRY")
    if RUN_RECEIPT_PATH.exists() or RESULT_PATH.exists() or RESOURCE_TRACE_PATH.exists() or WORKER_STATUS_PATH.exists():
        raise PrefitError("PREFIT_RECEIPT_ALREADY_EXISTS_NO_REENTRY")

    guard, adapter = _official_guard(
        binding,
        run_spec_sha=run_spec_sha,
        input_binding_sha=input_binding_sha,
        expected_registry_sha256=registry_sha,
        expected_release_sha256=release_sha,
        expected_reviewer_receipt_sha256=str(release["reviewer_receipt_sha256"]),
        expected_source_code_sha256=binding["code_sha256"],
    )
    if guard.accounting().run_started_count != 0:
        raise PrefitError("ROUTE_ALREADY_HAS_REGISTERED_EXECUTION_NO_REENTRY")
    claim = guard.claim_no_fit(
        execution_id=EXECUTION_ID,
        arm="INCREMENTAL_PREFIT_FULL_TRAIN_ONLY_NO_FIT_NO_PREDICT",
        contract_sha256=run_spec_sha,
        input_binding_sha256=input_binding_sha,
    )

    status = "CANNOT_CONFIRM"
    error_type: str | None = None
    monitor: dict[str, Any] | None = None
    try:
        PREFIT_DIR.mkdir(parents=True, exist_ok=False)
        native_spec, native_runtime_path = _native_spec(binding)
        resource_tree = _resource_tree_module(binding)
        expected_training = binding["training_contract"]
        payload = {
            "input_files": binding["input_files"],
            "native_spec": native_spec,
            "native_runtime_path": str(native_runtime_path),
            "grouping_path": str(Path(binding["code_files"]["grouping"]["path"])),
            "dataset_params": binding["dataset_params"],
            "training_contract": expected_training,
            "feature_names": binding["feature_names"],
            "parent_authorization_id": release["parent_authorization_id"],
            "parent_release_sha256": release_sha,
            "run_spec_sha256": run_spec_sha,
            "input_binding_sha256": input_binding_sha,
            "code_files": binding["code_files"],
            "source_code_sha256": binding["code_sha256"],
            "native_runtime_sha256": binding["native_runtime_sha256"],
        }
        monitor = resource_tree.run_spawn_monitored(
            _prefit_worker,
            payload,
            native_spec=native_spec,
            native_runtime_helper_path=native_runtime_path,
            wall_seconds_max=RESOURCE_CAPS["wall_seconds_max"],
            rss_bytes_max=RESOURCE_CAPS["aggregate_process_tree_rss_bytes_max"],
            threads=RESOURCE_CAPS["cpu_threads"],
            resource_trace_path=RESOURCE_TRACE_PATH,
            sample_seconds=RESOURCE_CAPS["sampling_interval_seconds"],
        )
        worker_status = read_json(WORKER_STATUS_PATH) if WORKER_STATUS_PATH.is_file() else {}
        if monitor.get("terminal_reason") is None and monitor.get("worker_exitcode") == 0 and worker_status.get("status") == "COMPLETED":
            result = read_json(RESULT_PATH)
            if result.get("fit_calls") == 0 and result.get("predict_calls") == 0 and result.get("evaluation_label_values_decoded") is False:
                status = "COMPLETED"
            else:
                error_type = "PREFIT_RESULT_SCOPE_VIOLATION"
        else:
            error_type = str(monitor.get("terminal_reason") or worker_status.get("error_type") or "PREFIT_WORKER_FAILED")
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        run_doc = {
            "schema": "F5_FULL64_XENDCG_PREFIT_RUN_RECEIPT_V1",
            "execution_id": EXECUTION_ID,
            "route_id": ROUTE_ID,
            "parent_authorization_id": release["parent_authorization_id"],
            "parent_release_sha256": release_sha,
            "run_spec_sha256": run_spec_sha,
            "input_binding_sha256": input_binding_sha,
            "prefit_result_sha256": sha256_file(RESULT_PATH) if RESULT_PATH.is_file() else None,
            "worker_status_sha256": sha256_file(WORKER_STATUS_PATH) if WORKER_STATUS_PATH.is_file() else None,
            "worker_start_receipt_sha256": sha256_file(WORKER_START_PATH) if WORKER_START_PATH.is_file() else None,
            "input_hash_receipt_sha256": sha256_file(INPUT_HASH_PATH) if INPUT_HASH_PATH.is_file() else None,
            "train_label_read_start_receipt_sha256": sha256_file(TRAIN_LABEL_READ_START_PATH) if TRAIN_LABEL_READ_START_PATH.is_file() else None,
            "resource_trace_path": str(RESOURCE_TRACE_PATH.resolve()),
            "resource_monitor": {key: monitor.get(key) for key in ("elapsed_seconds", "peak_aggregate_tree_rss_bytes", "wall_seconds_max", "aggregate_rss_bytes_max", "threads", "sample_interval_seconds", "hard_peak_memory_guarantee", "monitor_scope", "terminal_reason", "worker_exitcode", "worker_termination", "post_trace_fsync_terminal_check", "final_post_fsync_check")} if monitor else None,
            "worker_started_after_parent_release_and_official_run_started": WORKER_START_PATH.is_file(),
            "all_input_hashes_verified": INPUT_HASH_PATH.is_file(),
            "train_label_decode_started": TRAIN_LABEL_READ_START_PATH.is_file(),
            "evaluation_label_values_decoded": False,
            "fit_calls": 0,
            "predict_calls": 0,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        try:
            if not RUN_RECEIPT_PATH.exists():
                durable_json_exclusive(RUN_RECEIPT_PATH, run_doc)
        except BaseException as receipt_exc:
            status = "CANNOT_CONFIRM"
            error_type = error_type or type(receipt_exc).__name__
        existing = list(adapter.artifact_paths)
        produced = [RESULT_PATH, RUN_RECEIPT_PATH, WORKER_STATUS_PATH, WORKER_START_PATH, INPUT_HASH_PATH, TRAIN_LABEL_READ_START_PATH, RESOURCE_TRACE_PATH]
        for name in ("TRAIN_PERMUTATION.npy", "TRAIN_INVERSE_PERMUTATION.npy", "TRAIN_GROUP_SIZES.npy", "GROUP_BINDING.json", "PREPROCESSING.json"):
            produced.append(PREFIT_DIR / name)
        adapter.artifact_paths = tuple(existing + [path for path in produced if path.is_file()])
        try:
            guard.append_terminal(
                claim,
                terminal_status=status,
                fit_call_entered=False,
                real_fit_returned_count=0,
                error_type=error_type,
            )
        except BaseException as terminal_exc:
            if error_type is None:
                error_type = type(terminal_exc).__name__
            raise
    return {
        "terminal_status": status,
        "result_path": str(RESULT_PATH),
        "result_sha256": sha256_file(RESULT_PATH) if RESULT_PATH.is_file() else None,
        "run_receipt_path": str(RUN_RECEIPT_PATH),
        "run_receipt_sha256": sha256_file(RUN_RECEIPT_PATH) if RUN_RECEIPT_PATH.is_file() else None,
        "resource_trace_sha256": sha256_file(RESOURCE_TRACE_PATH) if RESOURCE_TRACE_PATH.is_file() else None,
        "fit_calls": 0,
        "predict_calls": 0,
    }


def main() -> int:
    print(json.dumps(run_prefit(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
