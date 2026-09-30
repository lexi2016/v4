"""Immutable, exact-date Baimao research-observation sidecar store.

This module is intentionally independent from the selector/public-account pools.
It owns only artifact -> manifest -> receipt -> latest snapshots for the
BAIMAO_RESEARCH_OBSERVATION_V1 contract. Readers never fall back to a
different date and every mismatch fails closed.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from .hashing import canonical_bytes, sha256_file, sha256_json


SCHEMA_VERSION = "BAIMAO_RESEARCH_OBSERVATION_V1"
MANIFEST_SCHEMA_VERSION = "BAIMAO_RESEARCH_OBSERVATION_MANIFEST_V1"
RECEIPT_SCHEMA_VERSION = "BAIMAO_RESEARCH_OBSERVATION_RECEIPT_V1"
LATEST_SCHEMA_VERSION = "BAIMAO_RESEARCH_OBSERVATION_LATEST_V1"
ASSET_NAME = "baimao_observations"
READY = "READY"
_DATE_RE = re.compile(r"^\d{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^(?:\d{6}\.(?:SH|SZ|BJ)|\d{5,6}\.HK)$")
_STATES = {"RESEARCH_MAP", "WATCH_ONLY", "UNVERIFIED", "CANNOT_CONFIRM"}
_MARKETS = {"A/BJ", "HK"}
_ROW_FIELDS = (
    "market",
    "code",
    "name",
    "theme",
    "source_refs",
    "evidence_grade",
    "state",
    "source_attribution",
    "capture_mechanism",
    "strongest_link",
    "weakest_link",
    "upgrade_conditions",
    "invalidation_conditions",
)
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class ObservationError(ValueError):
    """Base error for malformed or unverifiable observations."""


class ObservationConflict(ObservationError):
    """Raised when an exact source date already has another artifact."""


class ObservationNotFound(ObservationError):
    """Raised when an exact source date has no verified publication."""


def _validate_date(value: Any, field: str = "source_date") -> str:
    text = str(value or "")
    if not _DATE_RE.fullmatch(text):
        raise ObservationError(f"{field} must use YYYYMMDD")
    try:
        _dt.datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise ObservationError(f"{field} must be a real calendar date") from error
    return text


def _validate_sha(value: Any, field: str) -> str:
    text = str(value or "")
    if not _SHA_RE.fullmatch(text):
        raise ObservationError(f"{field} must be a lowercase SHA-256")
    return text


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _asset_root(store_root: Path | str) -> Path:
    root = Path(store_root)
    return root if root.name == ASSET_NAME else root / ASSET_NAME


def _safe_relative(value: Any) -> str:
    text = str(value or "")
    path = Path(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in Path(text).parts)
        or text != Path(text).as_posix()
    ):
        raise ObservationError("relative path is invalid")
    return text


def _resolve_under(root: Path, relative: str) -> Path:
    _safe_relative(relative)
    candidate = root / relative
    real_root = root.resolve()
    real_candidate = candidate.resolve()
    if real_candidate != real_root and real_root not in real_candidate.parents:
        raise ObservationError("relative path escapes observation root")
    return candidate


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationError(f"{label} unreadable") from error
    if not isinstance(payload, dict):
        raise ObservationError(f"{label} must be an object")
    return payload


def _validate_row(row: Any, expected_market: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ObservationError("observation row must be an object")
    missing = [field for field in _ROW_FIELDS if field not in row]
    if missing:
        raise ObservationError("observation row fields missing: " + ",".join(missing))
    result = {field: row[field] for field in _ROW_FIELDS}
    if result["market"] != expected_market or result["market"] not in _MARKETS:
        raise ObservationError("observation market mismatch")
    if not _CODE_RE.fullmatch(str(result["code"] or "").upper()):
        raise ObservationError("observation code invalid")
    result["code"] = str(result["code"]).upper()
    for field in ("name", "theme", "evidence_grade", "source_attribution", "capture_mechanism", "strongest_link", "weakest_link"):
        if not str(result[field] or "").strip():
            raise ObservationError(f"observation {field} missing")
        result[field] = str(result[field]).strip()
    if result["state"] not in _STATES:
        raise ObservationError("observation state invalid")
    if expected_market == "HK" and result["state"] != "CANNOT_CONFIRM":
        raise ObservationError("HK observations must be CANNOT_CONFIRM")
    if not isinstance(result["source_refs"], list) or not result["source_refs"] or any(not str(item).strip() for item in result["source_refs"]):
        raise ObservationError("observation source_refs invalid")
    result["source_refs"] = [str(item).strip() for item in result["source_refs"]]
    for field in ("upgrade_conditions", "invalidation_conditions"):
        value = result[field]
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not value or any(not str(item).strip() for item in value):
            raise ObservationError(f"observation {field} invalid")
        result[field] = [str(item).strip() for item in value]
    return result


def validate_observation_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ObservationError("observation payload must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ObservationError("observation schema mismatch")
    if payload.get("source_merge_role") != "SOURCE_ONLY":
        raise ObservationError("source_merge_role must be SOURCE_ONLY")
    for key, expected in {"stage_selection_eligible": False, **_SAFETY}.items():
        if payload.get(key) is not expected:
            raise ObservationError(f"{key} safety contract invalid")
    source_date = _validate_date(payload.get("source_date"), "source_date")
    effective_date = _validate_date(payload.get("effective_trade_date"), "effective_trade_date")
    if not str(payload.get("source_run_id") or "").strip():
        raise ObservationError("source_run_id missing")
    _validate_sha(payload.get("source_report_sha256"), "source_report_sha256")
    _validate_sha(payload.get("source_artifact_sha256"), "source_artifact_sha256")
    counts = payload.get("counts")
    observations = payload.get("observations")
    if not isinstance(counts, Mapping) or not isinstance(observations, Mapping):
        raise ObservationError("counts and observations are required")
    a_raw = observations.get("a_bj")
    hk_raw = observations.get("hk")
    if not isinstance(a_raw, list) or not isinstance(hk_raw, list):
        raise ObservationError("observations must contain a_bj and hk lists")
    a_rows = [_validate_row(row, "A/BJ") for row in a_raw]
    hk_rows = [_validate_row(row, "HK") for row in hk_raw]
    expected_counts = {"a_bj": len(a_rows), "hk": len(hk_rows), "total": len(a_rows) + len(hk_rows)}
    try:
        actual_counts = {key: int(counts.get(key, -1)) for key in expected_counts}
    except (TypeError, ValueError) as error:
        raise ObservationError("observation counts invalid") from error
    if actual_counts != expected_counts:
        raise ObservationError("observation counts mismatch")
    codes = [row["code"] for row in a_rows + hk_rows]
    if len(codes) != len(set(codes)):
        raise ObservationError("duplicate observation code")
    normalized = dict(payload)
    normalized["source_date"] = source_date
    normalized["effective_trade_date"] = effective_date
    normalized["counts"] = expected_counts
    normalized["observations"] = {"a_bj": a_rows, "hk": hk_rows}
    source_identity = dict(normalized)
    source_identity.pop("source_artifact_sha256", None)
    expected_source_artifact_sha256 = sha256_json(source_identity)
    if normalized.get("source_artifact_sha256") != expected_source_artifact_sha256:
        raise ObservationError("source_artifact_sha256 mismatch")
    return normalized


def _run_id(payload: Mapping[str, Any]) -> str:
    # Include every normalized payload field so changing title, URL, dates or
    # row evidence cannot silently reuse an immutable exact-date slot.
    return sha256_json(dict(payload))[:24]


def _latest_path(asset_root: Path) -> Path:
    return asset_root / "latest.json"


def _external_relative(relative: str) -> str:
    return f"{ASSET_NAME}/{relative}"


@contextmanager
def _publish_lock(asset_root: Path):
    """Acquire one owner lock for the complete exact-date publication."""
    asset_root.mkdir(parents=True, exist_ok=True)
    lock_path = asset_root / ".publish.lock"
    descriptor = None
    try:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise ObservationConflict(f"baima observations publish lock held: {lock_path}") from error
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            finally:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass


def _load_latest(asset_root: Path) -> dict[str, Any]:
    path = _latest_path(asset_root)
    if not path.is_file():
        return {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    latest = _read_json(path, "latest")
    if latest.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(latest.get("entries"), dict):
        raise ObservationError("latest schema invalid")
    return latest


def publish_observations(store_root: Path | str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically publish one exact-date observation payload."""
    payload = validate_observation_payload(payload)
    asset_root = _asset_root(store_root)
    with _publish_lock(asset_root):
        return _publish_observations_locked(asset_root, payload)


def _publish_observations_locked(asset_root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    source_date = payload["source_date"]
    run_id = _run_id(payload)
    latest = _load_latest(asset_root)
    existing = latest["entries"].get(source_date)
    if existing is not None:
        if not isinstance(existing, Mapping) or existing.get("run_id") != run_id:
            raise ObservationConflict(f"baima observations conflict for {source_date}")
        loaded = load_verified_observations(asset_root, source_date)
        if loaded.get("source_run_id") != payload["source_run_id"]:
            raise ObservationConflict(f"baima observations identity mismatch for {source_date}")
        return {
            "status": READY,
            "reused": True,
            "run_id": run_id,
            "source_date": source_date,
            "effective_trade_date": payload["effective_trade_date"],
            "counts": payload["counts"],
            "artifact_relative": _external_relative(str(existing.get("artifact_relative") or "")),
            "artifact_sha256": existing.get("artifact_sha256"),
            **_SAFETY,
        }

    run_root = asset_root / "runs" / source_date / run_id
    if run_root.exists():
        raise ObservationConflict(f"baima observations run directory exists: {run_root}")
    run_root.mkdir(parents=True, exist_ok=False)
    artifact = run_root / "artifact.json"
    _atomic_write(artifact, canonical_bytes(payload))
    relative_root = f"runs/{source_date}/{run_id}"
    artifact_relative = f"{relative_root}/artifact.json"
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_date": source_date,
        "effective_trade_date": payload["effective_trade_date"],
        "run_id": run_id,
        "source_run_id": payload["source_run_id"],
        "source_report_sha256": payload["source_report_sha256"],
        "source_artifact_sha256": payload["source_artifact_sha256"],
        "counts": payload["counts"],
        "artifact_relative": artifact_relative,
        "artifact_sha256": sha256_file(artifact),
        **_SAFETY,
    }
    manifest_relative = f"{relative_root}/manifest.json"
    receipt_relative = f"{relative_root}/receipt.json"
    _atomic_write(run_root / "manifest.json", canonical_bytes(manifest))
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": READY,
        "source_date": source_date,
        "effective_trade_date": payload["effective_trade_date"],
        "run_id": run_id,
        "source_run_id": payload["source_run_id"],
        "source_report_sha256": payload["source_report_sha256"],
        "source_artifact_sha256": payload["source_artifact_sha256"],
        "counts": payload["counts"],
        "artifact_sha256": manifest["artifact_sha256"],
        "manifest_sha256": sha256_json(manifest),
        **_SAFETY,
    }
    _atomic_write(run_root / "receipt.json", canonical_bytes(receipt))
    latest["entries"][source_date] = {
        "run_id": run_id,
        "effective_trade_date": payload["effective_trade_date"],
        "artifact_relative": artifact_relative,
        "manifest_relative": manifest_relative,
        "receipt_relative": receipt_relative,
        "artifact_sha256": manifest["artifact_sha256"],
    }
    _atomic_write(_latest_path(asset_root), canonical_bytes(latest))
    return {
        "status": READY,
        "reused": False,
        "run_id": run_id,
        "source_date": source_date,
        "effective_trade_date": payload["effective_trade_date"],
        "counts": payload["counts"],
        "artifact_relative": _external_relative(artifact_relative),
        "manifest_relative": _external_relative(manifest_relative),
        "receipt_relative": _external_relative(receipt_relative),
        "artifact_sha256": manifest["artifact_sha256"],
        "source_artifact_sha256": payload["source_artifact_sha256"],
        **_SAFETY,
    }


def load_verified_observations(store_root: Path | str, source_date: str) -> dict[str, Any]:
    """Read exactly source_date; never substitute another latest date."""
    source_date = _validate_date(source_date, "source_date")
    asset_root = _asset_root(store_root)
    latest = _load_latest(asset_root)
    entry = latest.get("entries", {}).get(source_date)
    if not isinstance(entry, Mapping):
        raise ObservationNotFound(f"baima observations not found for {source_date}")
    try:
        manifest_path = _resolve_under(asset_root, str(entry["manifest_relative"]))
        receipt_path = _resolve_under(asset_root, str(entry["receipt_relative"]))
        manifest = _read_json(manifest_path, "manifest")
        receipt = _read_json(receipt_path, "receipt")
        artifact_path = _resolve_under(asset_root, str(manifest["artifact_relative"]))
        payload = _read_json(artifact_path, "artifact")
    except (KeyError, TypeError) as error:
        raise ObservationError("observation metadata invalid") from error
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != READY
        or manifest.get("source_date") != source_date
        or receipt.get("source_date") != source_date
        or entry.get("run_id") != manifest.get("run_id")
        or receipt.get("run_id") != manifest.get("run_id")
        or manifest.get("artifact_relative") != entry.get("artifact_relative")
        or manifest.get("artifact_sha256") != entry.get("artifact_sha256")
        or receipt.get("artifact_sha256") != manifest.get("artifact_sha256")
        or receipt.get("manifest_sha256") != sha256_json(manifest)
        or any(manifest.get(key) is not False or receipt.get(key) is not False for key in _SAFETY)
    ):
        raise ObservationError("observation identity or safety contract invalid")
    if sha256_file(artifact_path) != manifest.get("artifact_sha256"):
        raise ObservationError("observation artifact checksum mismatch")
    normalized = validate_observation_payload(payload)
    if (
        normalized.get("source_date") != source_date
        or normalized.get("source_run_id") != manifest.get("source_run_id")
        or normalized.get("effective_trade_date") != manifest.get("effective_trade_date")
        or normalized.get("counts") != manifest.get("counts")
    ):
        raise ObservationError("observation artifact metadata mismatch")
    return normalized


def verify_observations(store_root: Path | str, source_date: str) -> dict[str, Any]:
    payload = load_verified_observations(store_root, source_date)
    return {
        "status": READY,
        "source_date": payload["source_date"],
        "effective_trade_date": payload["effective_trade_date"],
        "counts": payload["counts"],
        "source_run_id": payload["source_run_id"],
        "source_report_sha256": payload["source_report_sha256"],
        "source_artifact_sha256": payload["source_artifact_sha256"],
        **_SAFETY,
    }


__all__ = [
    "ASSET_NAME",
    "SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "LATEST_SCHEMA_VERSION",
    "ObservationError",
    "ObservationConflict",
    "ObservationNotFound",
    "validate_observation_payload",
    "publish_observations",
    "load_verified_observations",
    "verify_observations",
]
