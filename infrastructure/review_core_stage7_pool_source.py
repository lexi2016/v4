"""Read-only V3.5 projection of the trusted Review Core Stage7 pool."""
from __future__ import annotations

import copy
import os
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from infrastructure.isolated_package_loader import load_isolated_package_module

ROLE = "D1_STAGE7_REPLAY_POOL_V1"
POOL_ID = "a_d1_stage7_fenshi_review_pool"
DISPLAY_NAME = "A股 D-1 Stage7/分时复盘池"
SOURCE_ROLE = "VERIFIED_D1_STAGE7_REPLAY"
UPSTREAM_SOURCE_ROLE = "A_SHARE_1MIN_STAGE_1445_1500"
_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_PATHS = ("current", "artifact", "manifest", "receipt")
_PACKAGE_ENV = "REVIEW_CORE_PACKAGE_ROOT"
_DATA_ENV = "REVIEW_CORE_STAGE7_POOL_ROOT"
_IMPORT_LOCK = threading.RLock()

def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True

def _package_root() -> Path:
    configured = str(os.environ.get(_PACKAGE_ENV) or "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
        if root.name == "review_core" and (root / "__init__.py").is_file():
            return root
        nested = root / "review_core"
        if (nested / "__init__.py").is_file():
            return nested.resolve()
        raise ImportError(f"configured Review Core package is missing: {root}")
    for ancestor in Path(__file__).resolve().parents:
        if ancestor.name == "v3.5":
            sibling = (ancestor.parent / "review_core").resolve()
            if (sibling / "__init__.py").is_file():
                return sibling
    raise ImportError("workspace sibling review_core package is missing")


def _data_root(package_root: Path, explicit: Path | str | None) -> Path:
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    configured = str(os.environ.get(_DATA_ENV) or "").strip()
    return (Path(configured) if configured else package_root / ".runtime" / "stage7_pools").expanduser().resolve()


def _consumer(package_root: Path) -> Callable[[str, Path], Mapping[str, Any]]:
    with _IMPORT_LOCK:
        module = load_isolated_package_module(
            package_root.parent,
            package_directory="review_core",
            module_leaf="stage7_pool",
            namespace_prefix="v35_review_core_stage7",
        )
        loader = getattr(module, "read_stage7_replay_pool", None)
        if not callable(loader):
            raise ImportError("Review Core Stage7 consumer is unavailable")
        return loader


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be a real calendar date") from error
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing")
    return value.strip()


def _flags(value: Mapping[str, Any], label: str, *, nested_required: bool = True) -> None:
    if any(name not in value or value.get(name) is not False for name in _FLAGS):
        raise ValueError(f"{label} safety flags are not exactly false")
    nested = value.get("safety_flags")
    if nested is not None and (not isinstance(nested, Mapping) or any(nested.get(name) is not False for name in _FLAGS)):
        raise ValueError(f"{label} safety_flags are not exactly false")
    if nested_required and nested is None:
        raise ValueError(f"{label} safety_flags are missing")


def _paths(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(key), str) or not value.get(key).strip() for key in _PATHS
    ):
        raise ValueError(f"{label} paths are incomplete")
    return {key: str(value[key]) for key in _PATHS}


def _empty(target: Any, root: Path, reason: str) -> dict[str, Any]:
    flags = {name: False for name in _FLAGS}
    return {
        "pool_id": POOL_ID, "display_name": DISPLAY_NAME, "market": "A", "status": "CANNOT_CONFIRM",
        "rows": [], "pool_size": 0, "returned_rows": 0, "row_count": 0,
        "artifact_role": ROLE, "artifact_version": "V1", "signal_date": "", "target_date": str(target),
        "trade_date": str(target), "source_role": SOURCE_ROLE, "producer_id": "review_core.stage7_pool.read_stage7_replay_pool",
        "source_run_id": "", "source_sha256": "", "source_artifact_sha256": "",
        "source_manifest_sha256": "", "source_receipt_sha256": "", "source_paths": {}, "source_path": "",
        "source_refs": [], "consumer_run_id": "", "consumer_artifact_sha256": "",
        "consumer_manifest_sha256": "", "consumer_receipt_sha256": "",
        "consumer_paths": {key: "" for key in _PATHS}, "data_root": str(root),
        "cannot_confirm": [reason], "source_merge_role": "SOURCE_ONLY", "stage_selection_eligible": False,
        "schema_version": "v3_5.preselection_pool.v1", "recommendation_status": "WATCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE", "write_policy": "RESEARCH_ONLY",
        **flags, "safety_flags": flags,
    }


def _project(target: str, root: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    artifact = result.get("artifact")
    if not isinstance(artifact, Mapping) or result.get("role") != ROLE:
        raise ValueError("Review Core Stage7 artifact or role is invalid")
    if artifact.get("artifact_role") != ROLE or artifact.get("artifact_version") != "V1":
        raise ValueError("Review Core Stage7 artifact identity is invalid")
    if artifact.get("source_role") != UPSTREAM_SOURCE_ROLE:
        raise ValueError("Review Core Stage7 upstream source role is invalid")
    if result.get("trade_date") != target or result.get("target_date") != target or artifact.get("target_date") != target:
        raise ValueError("Review Core Stage7 exact target date mismatch")
    status = str(result.get("status") or "").upper()
    if status not in {"READY", "CANNOT_CONFIRM"} or artifact.get("status") != status:
        raise ValueError("Review Core Stage7 status mismatch")
    _flags(result, "consumer")
    _flags(artifact, "artifact")
    if result.get("source_merge_role") != "SOURCE_ONLY" or result.get("stage_selection_eligible") is not False:
        raise ValueError("Review Core Stage7 consumer source/stage contract mismatch")
    rows = artifact.get("rows")
    result_rows = result.get("rows")
    if not isinstance(rows, list) or not isinstance(result_rows, list) or result_rows != rows:
        raise ValueError("Review Core Stage7 rows mismatch")
    if artifact.get("row_count") != len(rows) or result.get("row_count") != len(rows):
        raise ValueError("Review Core Stage7 row count mismatch")
    if artifact.get("source_merge_role") != "SOURCE_ONLY" or artifact.get("stage_selection_eligible") is not False:
        raise ValueError("Review Core Stage7 artifact source/stage contract mismatch")
    if status == "CANNOT_CONFIRM" and rows:
        raise ValueError("Review Core CANNOT_CONFIRM Stage7 contains rows")
    if status == "READY" and not rows:
        raise ValueError("Review Core READY Stage7 contains no rows")
    signal = _date(artifact.get("signal_date"), "signal_date") if status == "READY" else str(artifact.get("signal_date") or "")
    if result.get("signal_date") not in (None, "", signal):
        raise ValueError("Review Core Stage7 signal date mismatch")
    if status == "CANNOT_CONFIRM":
        source = {key: str(artifact.get(key) or "") for key in (
            "source_run_id", "source_sha256", "source_artifact_sha256", "source_manifest_sha256", "source_receipt_sha256",
        )}
        consumer = {key: str(result.get(key.removeprefix("consumer_")) or "") for key in (
            "consumer_run_id", "consumer_artifact_sha256", "consumer_manifest_sha256", "consumer_receipt_sha256",
        )}
        source_paths = {key: str((artifact.get("source_paths") or {}).get(key) or "") for key in _PATHS} if isinstance(artifact.get("source_paths"), Mapping) else {}
        consumer_paths = {key: str((result.get("paths") or {}).get(key) or "") for key in _PATHS} if isinstance(result.get("paths"), Mapping) else {key: "" for key in _PATHS}
        cannot = list(result.get("cannot_confirm") or []) if isinstance(result.get("cannot_confirm"), list) else ["Review Core Stage7 source unavailable"]
        return _dto(target, root, signal, rows, source, source_paths, consumer, consumer_paths, cannot, status)
    source = {
        "source_run_id": _text(artifact.get("source_run_id"), "source_run_id"),
        "source_sha256": _text(artifact.get("source_sha256") or artifact.get("source_artifact_sha256"), "source_sha256"),
        "source_artifact_sha256": _text(artifact.get("source_artifact_sha256") or artifact.get("source_sha256"), "source_artifact_sha256"),
        "source_manifest_sha256": _text(artifact.get("source_manifest_sha256"), "source_manifest_sha256"),
        "source_receipt_sha256": _text(artifact.get("source_receipt_sha256"), "source_receipt_sha256"),
    }
    source_paths = _paths(artifact.get("source_paths"), "Review Core Stage7 source")
    consumer = {
        "consumer_run_id": _text(result.get("run_id"), "consumer_run_id"),
        "consumer_artifact_sha256": _text(result.get("artifact_sha256"), "consumer_artifact_sha256"),
        "consumer_manifest_sha256": _text(result.get("manifest_sha256"), "consumer_manifest_sha256"),
        "consumer_receipt_sha256": _text(result.get("receipt_sha256"), "consumer_receipt_sha256"),
    }
    consumer_paths = _paths(result.get("paths"), "Review Core Stage7 consumer")
    projected_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping) or row.get("rank") != index:
            raise ValueError("Review Core Stage7 row identity is invalid")
        if row.get("market") != "A" or row.get("signal_date") != signal or row.get("target_date") != target:
            raise ValueError("Review Core Stage7 row date/market mismatch")
        if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
            raise ValueError("Review Core Stage7 row source/stage contract mismatch")
        _flags(row, f"row {index}", nested_required=False)
        projected = copy.deepcopy(dict(row))
        projected.update({"pool_id": POOL_ID, "pool_rank": index, "recommendation_status": "WATCH_ONLY"})
        projected_rows.append(projected)
    cannot = list(result.get("cannot_confirm") or []) if isinstance(result.get("cannot_confirm"), list) else []
    return _dto(target, root, signal, projected_rows, source, source_paths, consumer, consumer_paths, cannot, status, artifact)


def _dto(
    target: str, root: Path, signal: str, rows: list[Mapping[str, Any]], source: dict[str, str],
    source_paths: dict[str, str], consumer: dict[str, str], consumer_paths: dict[str, str],
    cannot: list[Any], status: str, artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flags = {name: False for name in _FLAGS}
    refs = artifact.get("source_refs") if isinstance(artifact, Mapping) else []
    return {
        "pool_id": POOL_ID, "display_name": DISPLAY_NAME, "market": "A", "status": status,
        "rows": copy.deepcopy(list(rows)), "pool_size": len(rows), "returned_rows": len(rows), "row_count": len(rows),
        "artifact_role": ROLE, "artifact_version": "V1", "signal_date": signal, "target_date": target,
        "trade_date": target, "source_role": SOURCE_ROLE, "producer_id": "review_core.stage7_pool.read_stage7_replay_pool",
        **source, "source_paths": copy.deepcopy(source_paths), "source_path": str(source_paths.get("artifact") or ""),
        "source_refs": copy.deepcopy(refs) if isinstance(refs, list) else [], **consumer,
        "consumer_paths": copy.deepcopy(consumer_paths), "data_root": str(root), "cannot_confirm": [str(x) for x in cannot],
        "source_merge_role": "SOURCE_ONLY", "stage_selection_eligible": False,
        "schema_version": "v3_5.preselection_pool.v1", "recommendation_status": "WATCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE", "write_policy": "RESEARCH_ONLY",
        **flags, "safety_flags": flags,
    }


def load_review_core_stage7_pool(target_date: str, data_root: Path | str | None = None) -> dict[str, Any]:
    """Read one exact target-date Stage7 pool through the trusted Review Core reader."""
    root: Path | None = None
    try:
        target = _date(target_date, "target_date")
        package_root = _package_root()
        root = _data_root(package_root, data_root)
        result = _consumer(package_root)(target, root)
        if not isinstance(result, Mapping):
            raise TypeError("Review Core Stage7 consumer returned a non-object")
        return _project(target, root, result)
    except Exception as error:
        if root is None:
            try:
                root = _data_root(_package_root(), data_root)
            except Exception:
                root = Path(data_root).expanduser().resolve() if data_root is not None else Path()
        return _empty(target_date, root, f"REVIEW_CORE_STAGE7_POOL_UNAVAILABLE:{type(error).__name__}:{error}")

__all__ = ["load_review_core_stage7_pool"]
