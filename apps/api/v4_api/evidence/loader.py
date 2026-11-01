"""Load pinned evidence datasets that ship with the API release.

Each dataset is frozen: the manifest pins its SHA-256, key type and entry
count, and this loader restores the exact in-memory shape the callers use
(tuples, never lists, for tuple-keyed maps). Loaders decode data; they never
re-run the append/revoke logic that produced the final values.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EVIDENCE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVIDENCE_DIR / "manifest.json"
MANIFEST_SCHEMA = "v4.evidence_manifest.v1"
DATASET_SCHEMA = "v4.evidence_dataset.v1"

_manifest_cache: dict[str, Mapping[str, Any]] | None = None


class EvidenceDatasetError(RuntimeError):
    """Raised when a pinned dataset is missing, stale or malformed."""


def _load_manifest() -> dict[str, Mapping[str, Any]]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceDatasetError("EVIDENCE_MANIFEST_INVALID:unreadable") from error
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise EvidenceDatasetError("EVIDENCE_MANIFEST_INVALID:schema")
    entries = payload.get("datasets")
    if not isinstance(entries, list):
        raise EvidenceDatasetError("EVIDENCE_MANIFEST_INVALID:datasets")
    by_name: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise EvidenceDatasetError("EVIDENCE_MANIFEST_INVALID:entry")
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise EvidenceDatasetError("EVIDENCE_MANIFEST_INVALID:name")
        by_name[name] = entry
    return by_name


def _manifest() -> dict[str, Mapping[str, Any]]:
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = _load_manifest()
    return _manifest_cache


def _read_dataset(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    name = str(entry["name"])
    path = EVIDENCE_DIR / str(entry.get("path"))
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:missing") from error
    if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:sha256")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:json") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != DATASET_SCHEMA:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:schema")
    if payload.get("name") != name:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:name_mismatch")
    return payload


def tuple_keyed(name: str) -> dict[tuple[str, ...], str]:
    """Return a ``{tuple_key: str}`` map for a pinned ``tuple2`` dataset."""
    entry = _manifest().get(name)
    if entry is None:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:not_in_manifest")
    if entry.get("key_type") != "tuple2":
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:key_type")
    payload = _read_dataset(entry)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:rows")
    if entry.get("entry_count") != len(rows):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:entry_count")
    result: dict[tuple[str, ...], str] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:row_shape")
        key = (str(row[0]), str(row[1]))
        value = row[2]
        if not isinstance(value, str) or key in result:
            raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:row_value")
        result[key] = value
    return result
