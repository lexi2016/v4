"""Immutable exact-date D-1 Stage7 replay pool producer and reader."""
from __future__ import annotations
import copy
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
try:
    from .pool_store import PoolStore, StoreError
    from .stage7_sources import SAFETY_FLAGS, SOURCE_ROLE, load_stage7_source
except ImportError:  # focused invocation from review_core/
    from pool_store import PoolStore, StoreError
    from stage7_sources import SAFETY_FLAGS, SOURCE_ROLE, load_stage7_source
D1_STAGE7_REPLAY_POOL_V1 = "D1_STAGE7_REPLAY_POOL_V1"
POOL_SCHEMA = D1_STAGE7_REPLAY_POOL_V1
POOL_ROLE = D1_STAGE7_REPLAY_POOL_V1
ARTIFACT_VERSION = "V1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^(?:A\.)?(\d{6})$", re.I)
_FORBIDDEN_KEYS = frozenset(
    {
        "buy", "buy_signal", "primary_buy_signal", "secondary_buy_signal",
        "recommendation", "recommendation_status", "formal_recommendation",
        "trade_status", "selected", "stage_selected", "selection_status",
    }
)
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
    return {name: "" for name in ("current", "artifact", "manifest", "receipt")}
def _error(signal_date: Any, target_date: Any, reason: str) -> dict[str, Any]:
    flags = _flags()
    return {
        "schema": POOL_SCHEMA,
        "schema_version": POOL_SCHEMA,
        "artifact_role": POOL_SCHEMA,
        "role": POOL_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "signal_date": signal_date,
        "target_date": target_date,
        "source_role": SOURCE_ROLE,
        "source_run_id": "",
        "source_sha256": "",
        "source_artifact_sha256": "",
        "source_manifest_sha256": "",
        "source_receipt_sha256": "",
        "source_artifact_path": "",
        "source_manifest_path": "",
        "source_receipt_path": "",
        "source_paths": _empty_paths(),
        "source_refs": [],
        "provenance": {},
        "status": "CANNOT_CONFIRM",
        "cannot_confirm": [reason],
        "row_count": 0,
        "rows": [],
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        **flags,
        "safety_flags": flags,
    }
def _forbidden_key(key: Any) -> bool:
    text = str(key).strip().lower()
    return text in _FORBIDDEN_KEYS or ("recommend" in text and text != "recommendation_source")
def _row_code(value: Any) -> str:
    match = _CODE_RE.fullmatch(str(value or "").strip().upper())
    return match.group(1) if match else ""
def _validated_rows(value: Any, signal: str, target: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("SOURCE_ROWS_INVALID")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, source in enumerate(value, 1):
        if not isinstance(source, Mapping):
            raise ValueError("SOURCE_ROW_INVALID")
        if any(_forbidden_key(key) for key in source):
            raise ValueError("SOURCE_ROW_BUY_OR_RECOMMENDATION_FIELD")
        if source.get("signal_date") != signal:
            raise ValueError("SOURCE_ROW_SIGNAL_DATE_MISMATCH")
        source_target = source.get("target_date")
        if source_target not in (None, "", target):
            raise ValueError("SOURCE_ROW_TARGET_DATE_MISMATCH")
        code = _row_code(source.get("code"))
        if not code or code in seen:
            raise ValueError("SOURCE_ROW_CODE_INVALID_OR_DUPLICATE")
        seen.add(code)
        row = copy.deepcopy(dict(source))
        row.update(
            {
                "rank": index,
                "market": "A",
                "code": code,
                "symbol": f"A.{code}",
                "signal_date": signal,
                "target_date": target,
                "source_merge_role": "SOURCE_ONLY",
                "stage_selection_eligible": False,
                **_flags(),
            }
        )
        result.append(row)
    return result
def build_stage7_replay_pool(
    signal_date: str, target_date: str, shared_store_root: Path | str | None = None
) -> dict[str, Any]:
    """Build one target-date Stage7 pool from only the verified shared run."""
    try:
        signal = _date8(signal_date, "signal_date")
        target = _date8(target_date, "target_date")
    except StoreError as error:
        return _error(signal_date, target_date, f"DATE_INVALID:{error}")
    try:
        source = load_stage7_source(signal, target, shared_store_root)
    except Exception as error:
        return _error(signal, target, f"SOURCE_LOAD_FAILED:{type(error).__name__}:{error}")
    if not isinstance(source, Mapping):
        return _error(signal, target, "SOURCE_LOAD_FAILED:NON_OBJECT")
    cannot = source.get("cannot_confirm")
    cannot_list = [str(item) for item in cannot] if isinstance(cannot, list) else ([str(cannot)] if cannot else [])
    status = str(source.get("status") or "CANNOT_CONFIRM").upper()
    rows: list[dict[str, Any]] = []
    if status == "READY":
        try:
            if source.get("signal_date") != signal or source.get("target_date") != target:
                raise ValueError("SOURCE_DATE_MISMATCH")
            if source.get("source_role") != SOURCE_ROLE:
                raise ValueError("SOURCE_ROLE_MISMATCH")
            if source.get("source_merge_role") != "SOURCE_ONLY" or source.get("stage_selection_eligible") is not False:
                raise ValueError("SOURCE_SELECTION_BOUNDARY_INVALID")
            for name in SAFETY_FLAGS:
                if source.get(name) is not False:
                    raise ValueError(f"SOURCE_UNSAFE_FLAG:{name}")
            nested_flags = source.get("safety_flags")
            if not isinstance(nested_flags, Mapping) or any(nested_flags.get(name) is not False for name in SAFETY_FLAGS):
                raise ValueError("SOURCE_UNSAFE_FLAG:nested")
            rows = _validated_rows(source.get("rows"), signal, target)
            if not rows:
                raise ValueError("SOURCE_ROWS_EMPTY")
        except Exception as error:
            status = "CANNOT_CONFIRM"
            rows = []
            cannot_list.append(str(error))
    else:
        status = "CANNOT_CONFIRM"
        if not cannot_list:
            cannot_list.append(f"SOURCE_STATUS_NOT_READY:{status}")
    cannot_list = list(dict.fromkeys(item for item in cannot_list if item))
    flags = _flags()
    paths = copy.deepcopy(source.get("source_paths") if isinstance(source.get("source_paths"), Mapping) else _empty_paths())
    artifact = {
        "schema": POOL_SCHEMA,
        "schema_version": POOL_SCHEMA,
        "artifact_role": POOL_SCHEMA,
        "role": POOL_ROLE,
        "artifact_version": ARTIFACT_VERSION,
        "signal_date": signal,
        "target_date": target,
        "source_role": SOURCE_ROLE,
        "source_run_id": str(source.get("source_run_id") or ""),
        "source_sha256": str(source.get("source_sha256") or source.get("source_artifact_sha256") or ""),
        "source_artifact_sha256": str(source.get("source_artifact_sha256") or source.get("source_sha256") or ""),
        "source_manifest_sha256": str(source.get("source_manifest_sha256") or ""),
        "source_receipt_sha256": str(source.get("source_receipt_sha256") or ""),
        "source_artifact_path": str(paths.get("artifact") or ""),
        "source_manifest_path": str(paths.get("manifest") or ""),
        "source_receipt_path": str(paths.get("receipt") or ""),
        "source_paths": paths,
        "source_refs": copy.deepcopy(source.get("source_refs") if isinstance(source.get("source_refs"), list) else []),
        "provenance": copy.deepcopy(source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}),
        "status": status,
        "cannot_confirm": cannot_list,
        "row_count": len(rows),
        "rows": rows,
        "source_merge_role": "SOURCE_ONLY",
        "stage_selection_eligible": False,
        **flags,
        "safety_flags": flags,
    }
    return artifact
def publish_stage7_replay_pool(
    store_root: Path | str,
    signal_date: str,
    target_date: str,
    shared_store_root: Path | str | None = None,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Publish one immutable target-date Stage7 pool through PoolStore."""
    target = _date8(target_date, "target_date")
    artifact = build_stage7_replay_pool(signal_date, target, shared_store_root)
    return PoolStore(store_root).publish(
        target,
        POOL_ROLE,
        artifact,
        run_id=run_id,
        row_count=int(artifact.get("row_count") or 0),
        status=str(artifact.get("status") or "CANNOT_CONFIRM"),
    )
def _validate_artifact(verified: Mapping[str, Any], target: str) -> Mapping[str, Any]:
    if verified.get("trade_date") != target or verified.get("role") != POOL_ROLE:
        raise StoreError("D1 Stage7 pool verified identity mismatch")
    artifact = verified.get("artifact")
    if not isinstance(artifact, Mapping):
        raise StoreError("D1 Stage7 pool artifact missing")
    for key, expected in (
        ("schema", POOL_SCHEMA),
        ("schema_version", POOL_SCHEMA),
        ("artifact_role", POOL_SCHEMA),
        ("role", POOL_ROLE),
        ("artifact_version", ARTIFACT_VERSION),
        ("target_date", target),
        ("source_role", SOURCE_ROLE),
        ("source_merge_role", "SOURCE_ONLY"),
    ):
        if artifact.get(key) != expected:
            raise StoreError(f"D1 Stage7 pool {key} mismatch")
    signal = artifact.get("signal_date")
    _date8(signal, "signal_date")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or artifact.get("row_count") != len(rows):
        raise StoreError("D1 Stage7 pool row count mismatch")
    status = artifact.get("status")
    if status not in {"READY", "CANNOT_CONFIRM"}:
        raise StoreError("D1 Stage7 pool status mismatch")
    if status == "CANNOT_CONFIRM" and rows:
        raise StoreError("D1 Stage7 cannot-confirm artifact contains rows")
    if artifact.get("stage_selection_eligible") is not False:
        raise StoreError("D1 Stage7 pool stage selection must be false")
    for name in SAFETY_FLAGS:
        if artifact.get(name) is not False:
            raise StoreError(f"D1 Stage7 pool safety flag is not false: {name}")
    nested = artifact.get("safety_flags")
    if not isinstance(nested, Mapping) or any(nested.get(name) is not False for name in SAFETY_FLAGS):
        raise StoreError("D1 Stage7 pool nested safety flags mismatch")
    if status == "READY":
        for key in ("source_run_id", "source_sha256", "source_artifact_sha256", "source_manifest_sha256", "source_receipt_sha256"):
            if not isinstance(artifact.get(key), str) or not artifact.get(key):
                raise StoreError(f"D1 Stage7 source provenance missing: {key}")
            if key.endswith("sha256") and not _SHA_RE.fullmatch(str(artifact[key]).lower()):
                raise StoreError(f"D1 Stage7 source provenance SHA invalid: {key}")
        paths = artifact.get("source_paths")
        if not isinstance(paths, Mapping) or any(not str(paths.get(name) or "") for name in ("artifact", "manifest", "receipt")):
            raise StoreError("D1 Stage7 source paths missing")
        for field, name in (("source_artifact_path", "artifact"), ("source_manifest_path", "manifest"), ("source_receipt_path", "receipt")):
            if artifact.get(field) != paths.get(name):
                raise StoreError(f"D1 Stage7 source path mismatch: {field}")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise StoreError("D1 Stage7 pool row must be an object")
        code = _row_code(row.get("code"))
        if not code or row.get("market") != "A" or row.get("symbol") != f"A.{code}":
            raise StoreError("D1 Stage7 pool row A-share identity mismatch")
        if row.get("rank") != index or row.get("signal_date") != signal or row.get("target_date") != target:
            raise StoreError("D1 Stage7 pool row date/rank mismatch")
        if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
            raise StoreError("D1 Stage7 pool row selection boundary mismatch")
        if any(row.get(name) is not False for name in SAFETY_FLAGS):
            raise StoreError("D1 Stage7 pool row safety flag mismatch")
        if any(_forbidden_key(key) for key in row):
            raise StoreError("D1 Stage7 pool row has BUY/recommendation field")
    return artifact
def read_stage7_replay_pool(target_date: str, store_root: Path | str) -> dict[str, Any]:
    """Read and semantically validate one exact target-date Stage7 pool."""
    target = _date8(target_date, "target_date")
    store = PoolStore(store_root)
    verified = store.read_verified(target, POOL_ROLE)
    artifact = _validate_artifact(verified, target)
    flags = _flags()
    return {
        "status": artifact.get("status"),
        "trade_date": target,
        "target_date": target,
        "signal_date": artifact.get("signal_date"),
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
        **flags,
        "safety_flags": flags,
    }
__all__ = [
    "D1_STAGE7_REPLAY_POOL_V1",
    "build_stage7_replay_pool",
    "publish_stage7_replay_pool",
    "read_stage7_replay_pool",
]
