"""Read-only V3.5 projection of the trusted Review Core fupan pool."""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from infrastructure.isolated_package_loader import load_isolated_package_module


D1_FUPAN_REVIEW_POOL_V1 = "D1_FUPAN_REVIEW_POOL_V1"
POOL_ID = "a_d1_fupan_watchlist_pool"
DISPLAY_NAME = "A股 D-1 复盘继续观察池"
_PACKAGE_ENV = "REVIEW_CORE_PACKAGE_ROOT"
_DATA_ENV = "REVIEW_CORE_FUPAN_POOL_ROOT"
_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_PATHS = ("artifact", "manifest", "receipt", "current")
_IMPORT_LOCK = threading.RLock()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
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
    if configured:
        return Path(configured).expanduser().resolve()
    return (package_root / ".runtime" / "fupan_pools").resolve()


def _consumer(package_root: Path) -> Callable[[str, Path], Mapping[str, Any]]:
    with _IMPORT_LOCK:
        module = load_isolated_package_module(
            package_root.parent,
            package_directory="review_core",
            module_leaf="fupan_pool",
            namespace_prefix="v35_review_core_fupan",
        )
        loader = getattr(module, "read_fupan_review_pool", None)
        if not callable(loader):
            raise ImportError("Review Core fupan consumer is unavailable")
        return loader


def _empty(target: str, root: Path, reason: str, signal: str = "") -> dict[str, Any]:
    return {
        "pool_id": POOL_ID, "display_name": DISPLAY_NAME, "market": "A",
        "status": "CANNOT_CONFIRM", "rows": [], "pool_size": 0,
        "returned_rows": 0, "row_count": 0, "artifact_role": D1_FUPAN_REVIEW_POOL_V1,
        "artifact_version": "V1", "signal_date": signal, "target_date": target,
        "source_run_id": "", "source_sha256": "", "source_manifest_sha256": "",
        "source_receipt_sha256": "", "public_fupan_run_id": "",
        "public_fupan_manifest_sha256": "", "public_fupan_plate_sha256": "",
        "public_fupan_plate_path": "", "source_paths": {}, "source_path": "",
        "source_refs": [], "provenance": {}, "consumer_run_id": "",
        "consumer_artifact_sha256": "", "consumer_manifest_sha256": "",
        "consumer_receipt_sha256": "", "consumer_paths": {key: "" for key in _PATHS},
        "video_status": "CANNOT_CONFIRM", "data_root": str(root),
        "cannot_confirm": [reason], "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False, "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": target, "producer_id": "review_core.fupan_pool.read_fupan_review_pool",
        "source_role": "VERIFIED_D1_FUPAN_REVIEW", "recommendation_status": "RESEARCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE", "write_policy": "RESEARCH_ONLY",
        **{name: False for name in _FLAGS},
        "safety_flags": {name: False for name in _FLAGS},
    }


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
    return value


def _safe(value: Mapping[str, Any], label: str) -> None:
    if any(name not in value or value.get(name) is not False for name in _FLAGS):
        raise ValueError(f"{label} safety flags are not exactly false")
    flags = value.get("safety_flags")
    if not isinstance(flags, Mapping) or any(name not in flags or flags.get(name) is not False for name in _FLAGS):
        raise ValueError(f"{label} safety_flags are not exactly false")


def _paths(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(not isinstance(value.get(key), str) or not value.get(key).strip() for key in _PATHS):
        raise ValueError("Review Core consumer paths are incomplete")
    return {key: value[key] for key in _PATHS}


def _project(target: str, root: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    artifact = result.get("artifact")
    if not isinstance(artifact, Mapping) or result.get("role") != D1_FUPAN_REVIEW_POOL_V1:
        raise ValueError("Review Core fupan artifact or role is invalid")
    if artifact.get("artifact_role") != D1_FUPAN_REVIEW_POOL_V1 or artifact.get("artifact_version") != "V1":
        raise ValueError("Review Core fupan artifact identity is invalid")
    if result.get("target_date") != target or artifact.get("target_date") != target:
        raise ValueError("Review Core fupan exact target date mismatch")
    status = str(result.get("status") or "").upper()
    if status not in {"READY", "PARTIAL", "CANNOT_CONFIRM"} or artifact.get("status") != status:
        raise ValueError("Review Core fupan status mismatch")
    _safe(result, "consumer")
    _safe(artifact, "artifact")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or artifact.get("row_count") != len(rows) or result.get("row_count") != len(rows):
        raise ValueError("Review Core fupan row count mismatch")
    if artifact.get("source_merge_role") != "SOURCE_ONLY" or artifact.get("stage_selection_eligible") is not False:
        raise ValueError("Review Core fupan artifact source/stage contract mismatch")
    if status == "CANNOT_CONFIRM" and rows:
        raise ValueError("Review Core CANNOT_CONFIRM fupan contains rows")
    signal = artifact.get("signal_date", "")
    if status != "CANNOT_CONFIRM":
        signal = _date(signal, "signal_date")
        source = {key: _text(artifact.get(key), key) for key in (
            "source_run_id", "source_sha256", "source_manifest_sha256", "source_receipt_sha256",
            "public_fupan_run_id", "public_fupan_manifest_sha256", "public_fupan_plate_sha256", "public_fupan_plate_path",
        )}
        consumer = {
            "consumer_run_id": _text(result.get("run_id"), "consumer_run_id"),
            "consumer_artifact_sha256": _text(result.get("artifact_sha256"), "consumer_artifact_sha256"),
            "consumer_manifest_sha256": _text(result.get("manifest_sha256"), "consumer_manifest_sha256"),
            "consumer_receipt_sha256": _text(result.get("receipt_sha256"), "consumer_receipt_sha256"),
        }
        consumer_paths = _paths(result.get("paths"))
        for index, row in enumerate(rows, 1):
            if not isinstance(row, Mapping) or row.get("rank") != index:
                raise ValueError("Review Core fupan row identity is invalid")
            if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
                raise ValueError("Review Core fupan row source/stage contract mismatch")
            _safe(row, f"row {index}")
    else:
        source = {key: str(artifact.get(key) or "") for key in (
            "source_run_id", "source_sha256", "source_manifest_sha256", "source_receipt_sha256",
            "public_fupan_run_id", "public_fupan_manifest_sha256", "public_fupan_plate_sha256", "public_fupan_plate_path",
        )}
        consumer = {key: str(result.get(key.removeprefix("consumer_")) or "") for key in (
            "consumer_run_id", "consumer_artifact_sha256", "consumer_manifest_sha256", "consumer_receipt_sha256",
        )}
        consumer_paths = {key: str((result.get("paths") or {}).get(key) or "") for key in _PATHS} if isinstance(result.get("paths"), Mapping) else {key: "" for key in _PATHS}
    source_paths = artifact.get("source_paths")
    provenance = artifact.get("provenance")
    source_refs = artifact.get("source_refs")
    if not isinstance(source_paths, Mapping) or not isinstance(provenance, Mapping) or not isinstance(source_refs, list):
        raise ValueError("Review Core fupan provenance is incomplete")
    cannot = result.get("cannot_confirm")
    cannot = list(cannot) if isinstance(cannot, list) else []
    video = artifact.get("video")
    return {
        "pool_id": POOL_ID, "display_name": DISPLAY_NAME, "market": "A", "status": status,
        "rows": [] if status == "CANNOT_CONFIRM" else copy.deepcopy(rows),
        "pool_size": 0 if status == "CANNOT_CONFIRM" else len(rows),
        "returned_rows": 0 if status == "CANNOT_CONFIRM" else len(rows),
        "row_count": 0 if status == "CANNOT_CONFIRM" else len(rows),
        "artifact_role": artifact["artifact_role"], "artifact_version": artifact["artifact_version"],
        "signal_date": signal, "target_date": target, **source,
        "source_paths": copy.deepcopy(dict(source_paths)), "source_path": str(source_paths.get("bundle") or ""),
        "source_refs": copy.deepcopy(source_refs), "provenance": copy.deepcopy(dict(provenance)),
        **consumer, "consumer_paths": consumer_paths,
        "video_status": str(video.get("status") or "CANNOT_CONFIRM") if isinstance(video, Mapping) else "CANNOT_CONFIRM",
        "data_root": str(root), "cannot_confirm": cannot, "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False, "schema_version": "v3_5.preselection_pool.v1", "trade_date": target,
        "producer_id": "review_core.fupan_pool.read_fupan_review_pool", "source_role": "VERIFIED_D1_FUPAN_REVIEW",
        "recommendation_status": "RESEARCH_ONLY", "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
        "write_policy": "RESEARCH_ONLY", **{name: False for name in _FLAGS},
        "safety_flags": {name: False for name in _FLAGS},
    }


def load_review_core_fupan_pool(target_date: str, data_root: Path | str | None = None) -> dict[str, Any]:
    """Read one exact target-date pool through the trusted Review Core reader."""
    root: Path | None = None
    try:
        package_root = _package_root()
        root = _data_root(package_root, data_root)
        result = _consumer(package_root)(target_date, root)
        if not isinstance(result, Mapping):
            raise TypeError("Review Core fupan consumer returned a non-object")
        return _project(target_date, root, result)
    except Exception as error:
        if root is None:
            try:
                root = _data_root(_package_root(), data_root)
            except Exception:
                root = Path(data_root).expanduser().resolve() if data_root is not None else Path()
        return _empty(target_date, root, f"REVIEW_CORE_FUPAN_POOL_UNAVAILABLE:{type(error).__name__}:{error}")


__all__ = ["D1_FUPAN_REVIEW_POOL_V1", "DISPLAY_NAME", "POOL_ID", "load_review_core_fupan_pool"]
