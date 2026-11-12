"""Exact-date, read-only consumer for ``HK_CLOSE_REVIEW_V1`` artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

try:
    from .pool_store import PoolStore, StoreError
except ImportError:  # direct focused invocation from review_core/
    from pool_store import PoolStore, StoreError


HK_CLOSE_REVIEW_V1 = "HK_CLOSE_REVIEW_V1"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / ".runtime"


def _data_root(data_root: Path | str | None) -> Path:
    if data_root is not None:
        return Path(data_root).absolute()
    configured = str(os.environ.get("REVIEW_CORE_DATA_ROOT") or "").strip()
    return (Path(configured) if configured else DEFAULT_DATA_ROOT).absolute()


def _error_dto(trade_date: Any, root: Path, reason: str) -> dict[str, Any]:
    flags = {name: False for name in SAFETY_FLAGS}
    paths = {name: "" for name in ("artifact", "manifest", "receipt", "current")}
    return {
        "status": "CANNOT_CONFIRM",
        "trade_date": trade_date,
        "role": HK_CLOSE_REVIEW_V1,
        "data_root": str(root),
        "artifact": None,
        "run_id": "",
        "artifact_sha256": "",
        "manifest_sha256": "",
        "receipt_sha256": "",
        "paths": paths,
        "row_counts": {},
        "kpi": {},
        "cannot_confirm": [reason],
        "source_merge_role": "",
        "stage_selection_eligible": False,
        **flags,
        "safety_flags": flags,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StoreError(message)


def _validate_review(verified: Mapping[str, Any], trade_date: str) -> Mapping[str, Any]:
    _require(verified.get("trade_date") == trade_date, "HK review trade_date mismatch")
    _require(verified.get("role") == HK_CLOSE_REVIEW_V1, "HK review role mismatch")
    artifact = verified.get("artifact")
    _require(isinstance(artifact, Mapping), "HK review artifact must be an object")
    for key, expected in (
        ("schema_version", HK_CLOSE_REVIEW_V1),
        ("role", HK_CLOSE_REVIEW_V1),
        ("trade_date", trade_date),
    ):
        _require(artifact.get(key) == expected, f"HK review {key} mismatch")

    manifest = verified.get("manifest")
    receipt = verified.get("receipt")
    current = verified.get("current")
    for name, metadata in (("manifest", manifest), ("receipt", receipt), ("current", current)):
        _require(isinstance(metadata, Mapping), f"HK review {name} metadata missing")
        _require(metadata.get("trade_date") == trade_date, f"HK review {name} date mismatch")
        _require(metadata.get("role") == HK_CLOSE_REVIEW_V1, f"HK review {name} role mismatch")
        for flag in SAFETY_FLAGS:
            _require(metadata.get(flag) is False, f"HK review {name} safety flag is not false")
    for flag in SAFETY_FLAGS:
        _require(artifact.get(flag) is False, f"HK review artifact safety flag is not false")

    _require(artifact.get("status") == receipt.get("status"), "HK review status mismatch")
    _require(artifact.get("stage_selection_eligible") is False, "HK review stage selection is not eligible")
    _require(artifact.get("source_merge_role") == "SOURCE_ONLY", "HK review source merge role mismatch")
    _require(isinstance(artifact.get("row_counts"), Mapping), "HK review row_counts missing")
    kpi = artifact.get("kpi", artifact.get("KPI"))
    _require(isinstance(kpi, Mapping), "HK review kpi missing")
    _require(isinstance(artifact.get("cannot_confirm"), list), "HK review cannot_confirm missing")
    return artifact


def read_exact_hk_close_review(
    trade_date: str, data_root: Path | str | None = None
) -> dict[str, Any]:
    """Read and semantically validate one exact-date HK close review.

    ``PoolStore.read_verified`` remains the sole artifact/manifest/receipt/SHA
    verifier.  This function only checks the review contract and maps its
    verified result to a stable, string-path DTO.
    """

    root = _data_root(data_root)
    store = PoolStore(root)
    try:
        verified = store.read_verified(trade_date, HK_CLOSE_REVIEW_V1)
    except StoreError:
        raise
    except Exception as error:
        raise StoreError(f"HK review read failed: {type(error).__name__}: {error}") from error
    if not isinstance(verified, Mapping):
        raise StoreError("HK review verified result must be an object")
    artifact = _validate_review(verified, trade_date)
    kpi = artifact.get("kpi", artifact.get("KPI"))
    paths = {
        "artifact": str(verified["artifact_path"]),
        "manifest": str(verified["manifest_path"]),
        "receipt": str(verified["receipt_path"]),
        "current": str(store.current_path(trade_date, HK_CLOSE_REVIEW_V1)),
    }
    result = {
        "status": artifact.get("status"),
        "trade_date": trade_date,
        "role": HK_CLOSE_REVIEW_V1,
        "data_root": str(root),
        "artifact": dict(artifact),
        "run_id": verified["run_id"],
        "artifact_sha256": verified["artifact_sha256"],
        "manifest_sha256": verified["manifest_sha256"],
        "receipt_sha256": verified["receipt_sha256"],
        "paths": paths,
        "row_counts": dict(artifact["row_counts"]),
        "kpi": dict(kpi),
        "cannot_confirm": list(artifact["cannot_confirm"]),
        "source_merge_role": artifact["source_merge_role"],
        "stage_selection_eligible": False,
        **{flag: False for flag in SAFETY_FLAGS},
        "safety_flags": {flag: False for flag in SAFETY_FLAGS},
    }
    return result


def load_hk_close_review(
    trade_date: str, data_root: Path | str | None = None
) -> dict[str, Any]:
    """Return the exact-date DTO, mapping every verification failure closed."""

    root = _data_root(data_root)
    try:
        return read_exact_hk_close_review(trade_date, root)
    except Exception as error:
        return _error_dto(trade_date, root, f"{type(error).__name__}: {error}")


__all__ = [
    "HK_CLOSE_REVIEW_V1",
    "SAFETY_FLAGS",
    "read_exact_hk_close_review",
    "load_hk_close_review",
]
