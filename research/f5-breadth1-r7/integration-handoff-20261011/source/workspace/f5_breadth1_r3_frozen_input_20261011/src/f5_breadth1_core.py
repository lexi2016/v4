"""Frozen PLUS64+BREADTH1 identities and byte-exact artifact primitives."""
from __future__ import annotations

from hashlib import sha256
import gzip
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


ROUTE_ID = "F5_PLUS64_BREADTH1_R3_FROZEN_INPUT_20261011"
TRACK_ID = "HK_SPIKE_F5_FIXED_TOP20_RESEARCH"
EXPERIMENT_ID = ROUTE_ID
ARM = "PLUS64_BREADTH1"
FEATURE_NAME = "breadth1_positive_finite_share"
FROZEN_METRICS_SHA256 = "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763"
FROZEN_METRICS_ROOT = Path(__file__).resolve().parents[3] / "handoffs" / "BREADTH1_ADMISSION_MATERIALS_20261010" / "sources" / "f5"
CANDIDATE_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# One authoritative source inventory shared by the registered runner and real
# action adapter. Contract maps must bind this exact set, not an arbitrary
# subset of files selected by a caller.
CODE_BINDINGS = {
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/__init__.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_budget.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_inputs.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_core.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_worker.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/f5_breadth1_evaluate.py": None,
    "workspace/f5_breadth1_r3_frozen_input_20261011/src/run_f5_breadth1.py": None,
}

FROZEN_METRICS_DEPENDENCIES = {
    "spike5/metrics.py": "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763",
    "spike5/settings.py": "702c374612806e45647b8cdb8cb345736b6cac689f23df352c00d08735bfb4fc",
    "spike5/common.py": "affff27d758d73fdbde3da21af59b94b265d4072cf83036475cd06b0941a4097",
    "spike5/features.py": "947e8d9a2f2b36e44ecfc8d713e0c492670039838dcf3e5abb9396f17a637c38",
    "config/contract.json": "17ecffd1304e152da4f611b3ffc4b5e92633fac20d528b93ce9b6f8714b1c4bb",
    "config/base_features.json": "6284bfe3609ec9f220b4f4baef6e0cb4d3190529830fbcb0d8ff435c0859c7af",
    "config/feature_order_64.json": "0188d530e6aca9ba29d2a40b7dcb730bc45cd5528e2b1bd0eb609ae83de0ffc3",
}

FEATURES64 = (
    "ret_1d", "ret_3d", "ret_5d", "ret_20d", "ret_60d", "ret_120d",
    "dist_hi20", "dist_hi60", "dist_hi120", "pos20", "pos60", "pos120",
    "vol5", "vol20", "vol60", "vol_ratio", "vr5", "vr5_20", "vr5_60", "vr20_60",
    "vol_up5", "shrink5", "vmax20", "cp", "ls", "us", "body", "gap", "rng",
    "op250", "op60", "days_since_big", "rel_1d", "rel_20d",
    "path_displacement_10", "path_displacement_20", "path_displacement_60",
    "path_close_range_10", "path_close_range_20", "path_close_range_60",
    "path_drawdown_20", "path_drawdown_60", "path_efficiency_20", "path_efficiency_60",
    "path_compression_10v20", "path_activity_10v20", "path_peak_activity_share_30",
    "path_range_location_30", "path_rebound_from_trough_60", "path_below_peak_60",
    "path_max_return_60", "path_min_return_60", "path_pulse_activity_ratio",
    "path_pulse_age_60", "path_pulse_return", "path_pulse_retention",
    "path_pulse_cooling_5", "path_lower_reclaim_depth_mean_30",
    "path_upper_rejection_depth_mean_30", "path_low_slope_20",
    "path_volatility_10v20", "path_down_up_activity_30",
    "path_lower_reclaim_fraction_30", "path_upper_rejection_fraction_30",
)
if len(FEATURES64) != 64 or len(set(FEATURES64)) != 64:
    raise RuntimeError("FROZEN_FEATURE64_IDENTITY_INVALID")

FROZEN_BCE_PARAMS = {
    "objective": "binary", "metric": "binary_logloss", "boosting_type": "gbdt",
    "learning_rate": 0.05, "num_leaves": 15, "max_depth": 4,
    "min_data_in_leaf": 50, "lambda_l2": 1.0, "lambda_l1": 0.0,
    "min_sum_hessian_in_leaf": 0.001, "max_bin": 63,
    "bin_construct_sample_cnt": 200000, "feature_fraction": 1.0,
    "bagging_fraction": 1.0, "bagging_freq": 0, "is_unbalance": False,
    "scale_pos_weight": 1.0, "boost_from_average": True, "use_missing": True,
    "zero_as_missing": False, "seed": 42, "data_random_seed": 42,
    "feature_fraction_seed": 42, "bagging_seed": 42, "deterministic": True,
    "force_col_wise": True, "num_threads": 4, "device_type": "cpu", "verbosity": -1,
}
FROZEN_ROUNDS = 200
GATES = {
    "paired_lower_vs_PLUS_PATH": ">0",
    "paired_lower_vs_BASE34": ">=0.03",
}


class ArtifactContractError(ValueError):
    pass


class FrozenMetricsSourceError(RuntimeError):
    pass


def verify_candidate_code_bindings(expected: Mapping[str, Any]) -> dict[str, str]:
    """Verify the complete frozen code set against the loaded candidate root."""

    if not isinstance(expected, Mapping) or set(expected) != set(CODE_BINDINGS):
        raise ArtifactContractError("CONTRACT_CODE_PATH_SET_MISMATCH")
    if len(expected) != len(CODE_BINDINGS):
        raise ArtifactContractError("CONTRACT_CODE_PATH_ALIAS_OR_DUPLICATE")

    project_root = CANDIDATE_PROJECT_ROOT.resolve()
    candidate_root = (project_root / "workspace" / "f5_breadth1_r3_frozen_input_20261011").resolve()
    actual: dict[str, str] = {}
    expected_paths: dict[str, Path] = {}
    for relative, digest in expected.items():
        if not isinstance(relative, str) or not relative:
            raise ArtifactContractError("CONTRACT_CODE_PATH_INVALID")
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or relative != path.as_posix()
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ArtifactContractError("CONTRACT_CODE_PATH_OR_SHA_INVALID")
        resolved = (project_root / path).resolve()
        try:
            resolved.relative_to(candidate_root)
        except ValueError as exc:
            raise ArtifactContractError("CONTRACT_CODE_PATH_ESCAPES_CANDIDATE_ROOT") from exc
        if not resolved.is_file():
            raise ArtifactContractError(f"CONTRACT_CODE_PATH_MISSING:{relative}")
        expected_paths[relative] = resolved

    # If candidate modules have been loaded, they must come from this exact
    # code root. Hashing a same-named file elsewhere cannot stand in for the
    # module that supplied the running implementation.
    for relative, resolved in expected_paths.items():
        path = Path(relative)
        if path.suffix != ".py" or path.stem == "__init__":
            continue
        module = sys.modules.get(path.stem)
        loaded_from = getattr(module, "__file__", None) if module is not None else None
        if loaded_from is not None and Path(loaded_from).resolve() != resolved:
            raise ArtifactContractError(f"LOADED_CANDIDATE_MODULE_PATH_MISMATCH:{path.stem}")

    runner_path = expected_paths.get("workspace/f5_breadth1_r3_frozen_input_20261011/src/run_f5_breadth1.py")
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if runner_path is not None and main_file is not None:
        if Path(main_file).name == runner_path.name and Path(main_file).resolve() != runner_path:
            raise ArtifactContractError("LOADED_CANDIDATE_ENTRYPOINT_PATH_MISMATCH:run_f5_breadth1")

    for relative, resolved in expected_paths.items():
        actual[relative] = sha256_file(resolved)
        if actual[relative] != expected[relative]:
            raise ArtifactContractError(f"CONTRACT_CODE_SHA_MISMATCH:{relative}")
    return actual


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def npy_array_sha256(array: np.ndarray) -> str:
    if not isinstance(array, np.ndarray):
        raise ArtifactContractError("bound array must be a numpy ndarray")
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return sha256_bytes(buffer.getvalue())


def row_keys_sha256(row_keys: pd.DataFrame) -> str:
    _require_frame_columns(row_keys, ("code", "session_id"), "row_keys")
    keys = row_keys.loc[:, ["code", "session_id"]].copy()
    if keys.isna().any().any():
        raise ArtifactContractError("row key snapshot contains null values")
    keys["code"] = keys["code"].astype(str)
    keys["session_id"] = strict_integer_values(keys["session_id"], "row_keys.session_id")
    if keys["code"].eq("").any() or keys["code"].isin({"nan", "None"}).any():
        raise ArtifactContractError("row key snapshot contains an empty code")
    return sha256_bytes(csv_gzip_bytes(keys))


def write_text_exclusive(text: str, path: Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256_bytes(path.read_bytes())


def require_strict_positive_int(value: Any, label: str, *, maximum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ArtifactContractError(f"{label} must be a strict integer in [1, {maximum}]")
    return value


def require_strict_nonnegative_int(value: Any, label: str, *, maximum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ArtifactContractError(f"{label} must be a strict integer in [0, {maximum}]")
    return value


def load_frozen_metrics(root: Path = FROZEN_METRICS_ROOT) -> ModuleType:
    """Load the exact archived helper and verify every imported settings dependency."""

    # The source handoff is read-only; importing its modules must not create
    # __pycache__ files beside the frozen evidence.
    sys.dont_write_bytecode = True
    root = Path(root).resolve()
    for relative, expected in FROZEN_METRICS_DEPENDENCIES.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise FrozenMetricsSourceError(f"FROZEN_METRICS_DEPENDENCY_MISMATCH:{relative}")
    package_name = "_f5_breadth1_frozen_spike5"
    package = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec(package_name, loader=None, is_package=True)
    )
    package.__path__ = [str(root / "spike5")]
    sys.modules[package_name] = package
    for name in ("common", "features", "settings", "metrics"):
        full_name = f"{package_name}.{name}"
        path = root / "spike5" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(full_name, path)
        if spec is None or spec.loader is None:
            raise FrozenMetricsSourceError(f"FROZEN_METRICS_IMPORT_FAILED:{name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package_name}.metrics"]


def csv_gzip_bytes(frame: pd.DataFrame) -> bytes:
    text = frame.to_csv(index=False, float_format="%.17g", lineterminator="\n")
    return gzip.compress(text.encode("utf-8"), mtime=0)


def persist_csv_snapshot(frame: pd.DataFrame, path: Path) -> tuple[pd.DataFrame, str, int]:
    """Persist exclusively, then hash and parse one read-back byte snapshot."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = csv_gzip_bytes(frame)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    snapshot = path.read_bytes()
    digest = sha256_bytes(snapshot)
    dtype = {"code": str} if "code" in frame.columns else None
    parsed = pd.read_csv(
        io.BytesIO(snapshot), compression="gzip", dtype=dtype, float_precision="round_trip"
    )
    return parsed, digest, len(snapshot)


def load_csv_snapshot(path: Path, expected_sha256: str | None = None) -> tuple[pd.DataFrame, str, int]:
    snapshot = Path(path).read_bytes()
    digest = sha256_bytes(snapshot)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ArtifactContractError(f"ARTIFACT_SHA_MISMATCH:{Path(path).name}")
    parsed = pd.read_csv(
        io.BytesIO(snapshot), compression="gzip", dtype={"code": str}, float_precision="round_trip"
    )
    return parsed, digest, len(snapshot)


def load_bound_csv_snapshot(
    path: Path,
    expected_sha256: str,
    *,
    dtype: Mapping[str, Any] | None = None,
    usecols: Sequence[str] | None = None,
    float_precision: str | None = None,
) -> tuple[pd.DataFrame, str, int]:
    """Hash and parse one exact control/calendar snapshot with bound parser options."""

    snapshot = Path(path).read_bytes()
    digest = sha256_bytes(snapshot)
    if not isinstance(expected_sha256, str) or digest != expected_sha256:
        raise ArtifactContractError(f"ARTIFACT_SHA_MISMATCH:{Path(path).name}")
    compression = "gzip" if Path(path).name.endswith(".gz") else None
    parsed = pd.read_csv(
        io.BytesIO(snapshot),
        compression=compression,
        dtype=dict(dtype or {}),
        usecols=list(usecols) if usecols is not None else None,
        float_precision=float_precision,
    )
    return parsed, digest, len(snapshot)


def persist_npy_snapshot(array: np.ndarray, path: Path) -> tuple[np.ndarray, str, int]:
    if not isinstance(array, np.ndarray) or array.dtype != np.float32 or array.ndim != 2:
        raise ArtifactContractError("matrix artifact must be two-dimensional float32")
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(buffer.getvalue())
        handle.flush()
        os.fsync(handle.fileno())
    snapshot = path.read_bytes()
    parsed = np.load(io.BytesIO(snapshot), allow_pickle=False)
    if parsed.dtype != np.float32 or parsed.shape != array.shape:
        raise ArtifactContractError("NPY round-trip dtype/shape changed")
    if not np.array_equal(parsed.view(np.uint32), array.view(np.uint32)):
        raise ArtifactContractError("NPY round-trip float32 bits changed")
    return parsed, sha256_bytes(snapshot), len(snapshot)


def persist_mask_snapshot(mask: np.ndarray, path: Path) -> tuple[np.ndarray, str, int]:
    if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.ndim != 1:
        raise ArtifactContractError("original mask artifact must be one-dimensional bool")
    buffer = io.BytesIO()
    np.save(buffer, mask, allow_pickle=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(buffer.getvalue())
        handle.flush()
        os.fsync(handle.fileno())
    snapshot = path.read_bytes()
    parsed = np.load(io.BytesIO(snapshot), allow_pickle=False)
    if parsed.dtype != np.bool_ or not np.array_equal(parsed, mask):
        raise ArtifactContractError("original boolean mask did not survive NPY round-trip")
    return parsed, sha256_bytes(snapshot), len(snapshot)


def persist_probability_snapshot(array: np.ndarray, path: Path) -> tuple[np.ndarray, str, int]:
    if not isinstance(array, np.ndarray) or array.dtype != np.float64 or array.ndim != 1:
        raise ArtifactContractError("probability vector must be one-dimensional float64")
    if not np.isfinite(array).all() or np.any((array < 0.0) | (array > 1.0)):
        raise ArtifactContractError("probability vector contains invalid values")
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(buffer.getvalue())
        handle.flush()
        os.fsync(handle.fileno())
    snapshot = path.read_bytes()
    parsed = np.load(io.BytesIO(snapshot), allow_pickle=False)
    if parsed.dtype != np.float64 or parsed.shape != array.shape or not np.array_equal(parsed, array):
        raise ArtifactContractError("float64 probability vector did not survive NPY round-trip")
    return parsed, sha256_bytes(snapshot), len(snapshot)


def write_json_exclusive(value: Any, path: Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(_json_clean(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256_bytes(path.read_bytes())


def _json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_clean(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def validate_exact_top3(
    selected: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    expected_sessions: Sequence[int] | None = None,
) -> None:
    if not {"session_id", "market_date"} <= set(calendar.columns):
        raise ArtifactContractError("calendar is missing session/date identity")
    required = {"session_id", "code", "probability"}
    if not required <= set(selected.columns):
        raise ArtifactContractError(f"Top3 missing fields: {sorted(required - set(selected.columns))}")
    calendar_sessions = strict_integer_values(calendar["session_id"], "calendar.session_id")
    if len(set(calendar_sessions)) != len(calendar_sessions):
        raise ArtifactContractError("calendar has duplicate session_id")
    date_values = calendar["market_date"]
    if date_values.isna().any():
        raise ArtifactContractError("market_date contains null values")
    date_strings = date_values.astype(str)
    if date_strings.eq("").any() or date_strings.duplicated().any():
        raise ArtifactContractError("market_date does not map to a unique session")
    if pd.to_datetime(date_strings, errors="coerce").isna().any():
        raise ArtifactContractError("market_date contains an invalid calendar date")
    sessions = tuple(calendar_sessions)
    if expected_sessions is not None and sessions != tuple(strict_integer_values(pd.Series(expected_sessions), "expected_sessions")):
        raise ArtifactContractError("Top3 calendar session identity/order mismatch")
    selected = selected.copy()
    selected["session_id"] = strict_integer_values(selected["session_id"], "Top3.session_id")
    selected["code"] = selected["code"].astype(str)
    if selected["code"].eq("").any() or selected["code"].isin({"nan", "None"}).any():
        raise ArtifactContractError("Top3 contains an empty code key")
    if selected.duplicated(["session_id", "code"]).any():
        raise ArtifactContractError("duplicate code in Top3 session")
    counts = selected.groupby("session_id").size().to_dict()
    if set(counts) != set(sessions) or any(counts.get(day) != 3 for day in sessions):
        raise ArtifactContractError("Top3 must contain exactly three distinct codes per calendar session")
    probabilities = pd.to_numeric(selected["probability"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(probabilities).all() or np.any((probabilities < 0) | (probabilities > 1)):
        raise ArtifactContractError("Top3 contains invalid probability")


def validate_top3_scores(selected: pd.DataFrame, scores: pd.DataFrame) -> None:
    _require_frame_columns(selected, ("session_id", "code", "probability"), "selected")
    _require_frame_columns(scores, ("session_id", "code", "probability"), "scores")
    selected_keys = selected.loc[:, ["session_id", "code"]].copy()
    score_keys = scores.loc[:, ["session_id", "code"]].copy()
    selected_keys["session_id"] = strict_integer_values(selected_keys["session_id"], "selected.session_id")
    score_keys["session_id"] = strict_integer_values(score_keys["session_id"], "scores.session_id")
    selected_keys["code"] = selected_keys["code"].astype(str)
    score_keys["code"] = score_keys["code"].astype(str)
    if selected_keys.duplicated(["session_id", "code"]).any() or score_keys.duplicated(["session_id", "code"]).any():
        raise ArtifactContractError("selected or score rows contain duplicate keys")
    score_prob = pd.to_numeric(scores["probability"], errors="raise").to_numpy(dtype=np.float64)
    selected_prob = pd.to_numeric(selected["probability"], errors="raise").to_numpy(dtype=np.float64)
    if np.isinf(score_prob).any() or not np.isfinite(selected_prob).all():
        raise ArtifactContractError("score probabilities contain infinity or selected probabilities are non-finite")
    score_map = dict(zip(zip(score_keys.session_id, score_keys.code), score_prob))
    for key, probability in zip(zip(selected_keys.session_id, selected_keys.code), selected_prob):
        if key not in score_map or probability != score_map[key]:
            raise ArtifactContractError(f"Top3 score/key missing from frozen score artifact: {key}")


def validate_saved_top3_keys(
    selected: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    expected_sessions: Sequence[int] | None = None,
) -> None:
    """Check frozen control membership from a key-only saved Top3 parse."""

    _require_frame_columns(selected, ("session_id", "code"), "saved_control_top3")
    sessions = tuple(strict_integer_values(calendar["session_id"], "calendar.session_id"))
    if expected_sessions is not None and sessions != tuple(strict_integer_values(expected_sessions, "expected_sessions")):
        raise ArtifactContractError("saved control Top3 calendar session identity/order mismatch")
    keys = selected.loc[:, ["session_id", "code"]].copy()
    keys["session_id"] = strict_integer_values(keys["session_id"], "saved_control_top3.session_id")
    keys["code"] = keys["code"].astype(str)
    if keys["code"].eq("").any() or keys["code"].isin({"nan", "None"}).any():
        raise ArtifactContractError("saved control Top3 contains an empty code key")
    if keys.duplicated(["session_id", "code"]).any():
        raise ArtifactContractError("saved control Top3 contains a duplicate code/session key")
    counts = keys.groupby("session_id").size().to_dict()
    if set(counts) != set(sessions) or any(counts.get(day) != 3 for day in sessions):
        raise ArtifactContractError("saved control Top3 must contain exactly three distinct codes per calendar session")


def score_to_top3(scores: pd.DataFrame, metrics: ModuleType) -> pd.DataFrame:
    selected = metrics.select_top3(scores)
    if "rank" not in selected.columns:
        raise ArtifactContractError("frozen selector omitted rank")
    return selected.loc[:, ["session_id", "code", "probability", "rank"]].reset_index(drop=True)


def attach_truth(selected: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    keys = ["session_id", "code"]
    if truth.duplicated(keys).any() or selected.duplicated(keys).any():
        raise ArtifactContractError("truth/top3 key is not unique")
    result = selected.merge(truth, on=keys, how="left", validate="one_to_one", sort=False)
    if len(result) != len(selected) or result["y"].isna().all():
        raise ArtifactContractError("synthetic truth failed to bind to saved Top3")
    return result


def validate_calendar_date_map(calendar: pd.DataFrame) -> dict[int, str]:
    if not {"session_id", "market_date"} <= set(calendar.columns):
        raise ArtifactContractError("calendar is missing session/date identity")
    sessions = strict_integer_values(calendar["session_id"], "calendar.session_id")
    if len(set(sessions)) != len(sessions):
        raise ArtifactContractError("calendar session_id is duplicated")
    if calendar["market_date"].isna().any():
        raise ArtifactContractError("calendar market_date is null")
    dates = calendar["market_date"].astype(str)
    if dates.eq("").any() or dates.duplicated().any():
        raise ArtifactContractError("calendar market_date must map uniquely")
    if pd.to_datetime(dates, errors="coerce").isna().any():
        raise ArtifactContractError("calendar contains an invalid market_date")
    return {int(session): str(date) for session, date in zip(sessions, dates)}


def _require_frame_columns(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ArtifactContractError(f"{label} missing columns: {missing}")


def strict_integer_values(values: Sequence[Any] | pd.Series, label: str) -> list[int]:
    output: list[int] = []
    for value in values:
        if isinstance(value, (bool, np.bool_)):
            raise ArtifactContractError(f"{label} contains a boolean instead of an integer")
        if isinstance(value, (int, np.integer)):
            output.append(int(value))
            continue
        if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer():
            output.append(int(value))
            continue
        if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
            output.append(int(value))
            continue
        raise ArtifactContractError(f"{label} must contain exact integer values")
    return output

