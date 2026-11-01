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


def row_dicts(name: str) -> tuple[dict[str, Any], ...]:
    """Return a ``tuple[dict]`` table for a pinned ``row_dicts`` dataset.

    Columns named in ``tuple_columns`` are restored to tuples; JSON can only
    carry arrays there and the callers compare tuples.
    """
    entry = _manifest().get(name)
    if entry is None:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:not_in_manifest")
    if entry.get("key_type") != "row_dicts":
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:key_type")
    payload = _read_dataset(entry)
    columns = payload.get("columns")
    tuple_columns = payload.get("tuple_columns") or []
    rows = payload.get("rows")
    if not isinstance(columns, list) or not columns or len(set(columns)) != len(columns):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:columns")
    if not isinstance(tuple_columns, list) or not set(tuple_columns) <= set(columns):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:tuple_columns")
    if not isinstance(rows, list):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:rows")
    if entry.get("entry_count") != len(rows):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:entry_count")
    tuple_names = set(tuple_columns)
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(columns):
            raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:row_columns")
        item: dict[str, Any] = {}
        for column in columns:
            value = row[column]
            if column in tuple_names:
                if not isinstance(value, list):
                    raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:tuple_column")
                value = tuple(value)
            item[column] = value
        result.append(item)
    return tuple(result)


def _decode_tagged(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    kind = value.get("__type__")
    if kind is None:
        return value
    items = value.get("items")
    if kind == "tuple":
        return tuple(_decode_tagged(item) for item in items)
    if kind == "list":
        return [_decode_tagged(item) for item in items]
    if kind == "set":
        return {_decode_tagged(item) for item in items}
    if kind == "dict":
        result: dict[Any, Any] = {}
        for pair in items:
            key = _decode_tagged(pair[0])
            if key in result:
                raise EvidenceDatasetError("EVIDENCE_DATASET_INVALID:tagged:duplicate_key")
            result[key] = _decode_tagged(pair[1])
        return result
    raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:tagged:unknown_type:{kind}")


def tagged_value(name: str) -> Any:
    """Return the exact Python value of a ``tagged`` dataset.

    Used for the small evidence constants whose shape is not a plain table
    (mappings with tuple keys, sets, nested tuples). The type tags make the
    restoration explicit instead of guessing from JSON's array syntax.
    """
    entry = _manifest().get(name)
    if entry is None:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:not_in_manifest")
    if entry.get("key_type") != "tagged":
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:key_type")
    payload = _read_dataset(entry)
    if "value" not in payload:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:value")
    return _decode_tagged(payload["value"])


def tuple_rows(name: str) -> tuple[tuple[Any, ...], ...]:
    """Return a ``tuple[tuple]`` table for a pinned ``tuple_rows`` dataset.

    Rows are positional and have no column names in the source, so the
    dataset declares only the arity. Values must be JSON scalars; nested
    structures would need their own restoration rule.
    """
    entry = _manifest().get(name)
    if entry is None:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:not_in_manifest")
    if entry.get("key_type") != "tuple_rows":
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:key_type")
    payload = _read_dataset(entry)
    arity = payload.get("arity")
    rows = payload.get("rows")
    if not isinstance(arity, int) or isinstance(arity, bool) or arity <= 0:
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:arity")
    if not isinstance(rows, list):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:rows")
    if entry.get("entry_count") != len(rows):
        raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:entry_count")
    result: list[tuple[Any, ...]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != arity:
            raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:row_arity")
        if any(not isinstance(value, (str, int, float, bool)) and value is not None for value in row):
            raise EvidenceDatasetError(f"EVIDENCE_DATASET_INVALID:{name}:row_scalar")
        result.append(tuple(row))
    return tuple(result)


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
