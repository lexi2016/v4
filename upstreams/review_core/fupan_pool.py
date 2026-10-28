"""Immutable A-share D-1 fupan review-pool producer and consumer."""
from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from .fupan_sources import D1_FUPAN_REVIEW_POOL_V1, SAFETY_FLAGS, load_review_bundle_source
    from .pool_store import PoolStore, StoreError
except ImportError:  # pragma: no cover - direct focused invocation
    from fupan_sources import D1_FUPAN_REVIEW_POOL_V1, SAFETY_FLAGS, load_review_bundle_source
    from pool_store import PoolStore, StoreError


POOL_SCHEMA = D1_FUPAN_REVIEW_POOL_V1
POOL_ROLE = D1_FUPAN_REVIEW_POOL_V1
ARTIFACT_VERSION = "V1"


def _date8(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise StoreError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise StoreError(f"{label} must be a real calendar date") from error
    return value


def _flags() -> dict[str, bool]:
    return {name: False for name in SAFETY_FLAGS}


def _empty_paths() -> dict[str, str]:
    return {name: "" for name in ("current", "run", "bundle", "manifest", "receipt", "public_fupan_plate")}


def _error_artifact(signal_date: Any, target_date: Any, reason: str) -> dict[str, Any]:
    flags = _flags()
    return {
        "schema": POOL_SCHEMA,
        "schema_version": POOL_SCHEMA,
        "artifact_role": POOL_SCHEMA,
        "role": POOL_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "signal_date": signal_date,
        "target_date": target_date,
        "source_run_id": "",
        "source_sha256": "",
        "source_manifest_sha256": "",
        "source_receipt_sha256": "",
        "public_fupan_run_id": "",
        "public_fupan_manifest_sha256": "",
        "public_fupan_plate_sha256": "",
        "public_fupan_plate_path": "",
        "source_paths": _empty_paths(),
        "source_refs": [],
        "provenance": {},
        "status": "CANNOT_CONFIRM",
        "cannot_confirm": [reason],
        "row_count": 0,
        "rows": [],
        "video": {"status": "CANNOT_CONFIRM"},
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        **flags,
        "safety_flags": flags,
    }


def _validate_source(source: Mapping[str, Any], signal_date: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    status = str(source.get("status") or "CANNOT_CONFIRM").upper()
    if status not in {"READY", "PARTIAL", "CANNOT_CONFIRM"}:
        status = "CANNOT_CONFIRM"
    cannot = source.get("cannot_confirm")
    cannot_list = list(cannot) if isinstance(cannot, list) else ([str(cannot)] if cannot else [])
    if source.get("signal_date") != signal_date:
        cannot_list.append("SOURCE_SIGNAL_DATE_MISMATCH")
        status = "CANNOT_CONFIRM"
    rows = source.get("rows")
    normalized_rows = [copy.deepcopy(row) for row in rows] if isinstance(rows, list) else []
    if status == "CANNOT_CONFIRM":
        normalized_rows = []
    if any(not isinstance(row, Mapping) for row in normalized_rows):
        normalized_rows = []
        status = "CANNOT_CONFIRM"
        cannot_list.append("SOURCE_ROW_INVALID")
    for rank, row in enumerate(normalized_rows, 1):
        row["rank"] = rank
    if not normalized_rows and status in {"READY", "PARTIAL"}:
        status = "CANNOT_CONFIRM"
        cannot_list.append("SOURCE_ROWS_EMPTY")
    return status, normalized_rows, list(dict.fromkeys(str(item) for item in cannot_list if str(item)))


def build_fupan_review_pool(
    signal_date: str,
    target_date: str,
    bundle_root: Path | str,
    shared_store_root: Path | str,
    *,
    public_fupan_loader: Callable[[Path | str, str], Any] | None = None,
) -> dict[str, Any]:
    """Derive a pool from one exact signal-date verified ReviewBundleV1.

    ``target_date`` is intentionally explicit.  The producer never derives it
    from signal date and never consults a previous or latest source.
    """

    try:
        signal = _date8(signal_date, "signal_date")
        target = _date8(target_date, "target_date")
    except StoreError as error:
        return _error_artifact(signal_date, target_date, f"DATE_INVALID:{error}")
    try:
        source = load_review_bundle_source(
            signal,
            bundle_root,
            shared_store_root,
            public_fupan_loader=public_fupan_loader,
        )
    except Exception as error:
        return _error_artifact(signal, target, f"SOURCE_LOAD_FAILED:{type(error).__name__}:{error}")
    if not isinstance(source, Mapping):
        return _error_artifact(signal, target, "SOURCE_LOAD_FAILED:NON_OBJECT")
    status, rows, cannot = _validate_source(source, signal)
    flags = _flags()
    video = source.get("video")
    video = copy.deepcopy(dict(video)) if isinstance(video, Mapping) else {"status": source.get("video_status", "CANNOT_CONFIRM")}
    if status == "CANNOT_CONFIRM":
        rows = []
    artifact = {
        "schema": POOL_SCHEMA,
        "schema_version": POOL_SCHEMA,
        "artifact_role": POOL_SCHEMA,
        "role": POOL_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "signal_date": signal,
        "target_date": target,
        "source_run_id": str(source.get("source_run_id") or ""),
        "source_sha256": str(source.get("source_sha256") or ""),
        "source_manifest_sha256": str(source.get("source_manifest_sha256") or ""),
        "source_receipt_sha256": str(source.get("source_receipt_sha256") or ""),
        "public_fupan_run_id": str(source.get("public_fupan_run_id") or ""),
        "public_fupan_manifest_sha256": str(source.get("public_fupan_manifest_sha256") or ""),
        "public_fupan_plate_sha256": str(source.get("public_fupan_plate_sha256") or ""),
        "public_fupan_plate_path": str(source.get("public_fupan_plate_path") or ""),
        "source_paths": copy.deepcopy(source.get("source_paths") if isinstance(source.get("source_paths"), Mapping) else _empty_paths()),
        "source_refs": copy.deepcopy(source.get("source_refs") if isinstance(source.get("source_refs"), list) else []),
        "provenance": copy.deepcopy(source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}),
        "status": status,
        "cannot_confirm": cannot,
        "row_count": len(rows),
        "rows": rows,
        "video": video,
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        **flags,
        "safety_flags": flags,
    }
    return artifact


def publish_fupan_review_pool(
    store_root: Path | str,
    signal_date: str,
    target_date: str,
    bundle_root: Path | str,
    shared_store_root: Path | str,
    *,
    public_fupan_loader: Callable[[Path | str, str], Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Publish one immutable target-date pool through the shared PoolStore."""

    target = _date8(target_date, "target_date")
    artifact = build_fupan_review_pool(
        signal_date,
        target,
        bundle_root,
        shared_store_root,
        public_fupan_loader=public_fupan_loader,
    )
    return PoolStore(store_root).publish(
        target,
        POOL_ROLE,
        artifact,
        run_id=run_id,
        row_count=int(artifact.get("row_count") or 0),
        status=str(artifact.get("status") or "CANNOT_CONFIRM"),
    )


def _validate_verified(verified: Mapping[str, Any], target_date: str) -> Mapping[str, Any]:
    if verified.get("trade_date") != target_date or verified.get("role") != POOL_ROLE:
        raise StoreError("D1 fupan pool verified identity mismatch")
    artifact = verified.get("artifact")
    if not isinstance(artifact, Mapping):
        raise StoreError("D1 fupan pool artifact missing")
    for key, expected in (
        ("schema", POOL_SCHEMA),
        ("schema_version", POOL_SCHEMA),
        ("artifact_role", POOL_SCHEMA),
        ("role", POOL_ROLE),
        ("artifact_version", ARTIFACT_VERSION),
        ("target_date", target_date),
        ("source_merge_role", "SOURCE_ONLY"),
    ):
        if artifact.get(key) != expected:
            raise StoreError(f"D1 fupan pool {key} mismatch")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or artifact.get("row_count") != len(rows):
        raise StoreError("D1 fupan pool row count mismatch")
    if artifact.get("status") not in {"READY", "PARTIAL", "CANNOT_CONFIRM"}:
        raise StoreError("D1 fupan pool status mismatch")
    if artifact.get("status") == "CANNOT_CONFIRM" and rows:
        raise StoreError("D1 fupan pool cannot-confirm artifact contains rows")
    if artifact.get("status") != "CANNOT_CONFIRM":
        for key in (
            "source_run_id",
            "source_sha256",
            "source_manifest_sha256",
            "source_receipt_sha256",
            "public_fupan_run_id",
            "public_fupan_manifest_sha256",
            "public_fupan_plate_sha256",
            "public_fupan_plate_path",
        ):
            if not isinstance(artifact.get(key), str) or not artifact.get(key):
                raise StoreError(f"D1 fupan pool provenance missing: {key}")
    if artifact.get("stage_selection_eligible") is not False:
        raise StoreError("D1 fupan pool stage selection must be false")
    for name in SAFETY_FLAGS:
        if artifact.get(name) is not False:
            raise StoreError(f"D1 fupan pool safety flag is not false: {name}")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise StoreError("D1 fupan pool row must be an object")
        code = row.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise StoreError("D1 fupan pool row code mismatch")
        if row.get("market") != "A" or row.get("symbol") != f"A.{code}":
            raise StoreError("D1 fupan pool row A-share symbol mismatch")
        if row.get("exchange") not in {"SH", "SZ", "BJ"}:
            raise StoreError("D1 fupan pool row exchange mismatch")
        if row.get("rank") != index:
            raise StoreError("D1 fupan pool row rank mismatch")
        if row.get("source_merge_role") != "SOURCE_ONLY":
            raise StoreError("D1 fupan pool row source merge role mismatch")
        if row.get("stage_selection_eligible") is not False:
            raise StoreError("D1 fupan pool row stage selection must be false")
        for name in SAFETY_FLAGS:
            if row.get(name) is not False:
                raise StoreError(f"D1 fupan pool row safety flag is not false: {name}")
    return artifact


def read_fupan_review_pool(target_date: str, store_root: Path | str) -> dict[str, Any]:
    """Read and semantically validate one exact target-date stored pool."""

    target = _date8(target_date, "target_date")
    store = PoolStore(store_root)
    verified = store.read_verified(target, POOL_ROLE)
    artifact = _validate_verified(verified, target)
    return {
        "status": artifact.get("status"),
        "trade_date": target,
        "target_date": target,
        "role": POOL_ROLE,
        "artifact": dict(artifact),
        "run_id": verified["run_id"],
        "artifact_sha256": verified["artifact_sha256"],
        "manifest_sha256": verified["manifest_sha256"],
        "receipt_sha256": verified["receipt_sha256"],
        "paths": {
            "artifact": str(verified["artifact_path"]),
            "manifest": str(verified["manifest_path"]),
            "receipt": str(verified["receipt_path"]),
            "current": str(store.current_path(target, POOL_ROLE)),
        },
        "row_count": len(artifact["rows"]),
        "rows": copy.deepcopy(artifact["rows"]),
        "cannot_confirm": list(artifact.get("cannot_confirm") or []),
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        **_flags(),
        "safety_flags": _flags(),
    }


__all__ = [
    "ARTIFACT_VERSION",
    "D1_FUPAN_REVIEW_POOL_V1",
    "POOL_ROLE",
    "POOL_SCHEMA",
    "build_fupan_review_pool",
    "publish_fupan_review_pool",
    "read_fupan_review_pool",
]
