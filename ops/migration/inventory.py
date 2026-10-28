"""Build and validate the checked-in, Atlas-derived replacement inventory.

This module only reads an Atlas passed explicitly at generation time.  V4
runtime code never imports it or reads Atlas data.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any


FROZEN_SEMANTIC_HASH = "4123dfbecd2fb3ac9074209786e3a773608edb01df2215a1271fa122d0f22390"
FROZEN_COUNTS = {"sources": 335, "entrypoints": 89, "runtime_tasks": 69, "features": 11}
FROZEN_ENTRYPOINT_KINDS = {
    "cli_script": 45,
    "windows_task": 35,
    "html_page": 8,
    "python_entry_candidate": 1,
}
FROZEN_RUNTIME_TASK_TYPES = {"timeline_node": 34, "windows_task": 35}
FROZEN_FEATURE_IDS = frozenset(
    {
        "navigation.dates",
        "orphan.loadConsole",
        "orphan.loadMorningLane",
        "orphan.loadWechatLane",
        "preselection.pools",
        "research.desk",
        "review.close",
        "runtime.status",
        "stage.model_review_close",
        "stage.workbench",
        "tasks.registry",
    }
)
ALLOWED_DISPOSITIONS = frozenset({"REWRITE", "REPLACE", "ARCHIVE_DATA_ONLY", "APPROVED_REMOVE"})
ALLOWED_STATUSES = frozenset({"PENDING", "IN_PROGRESS", "COMPLETE"})
ALLOWED_RUNTIME_RECORD_TYPES = frozenset(FROZEN_RUNTIME_TASK_TYPES)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2})")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ENTRYPOINT_KINDS = frozenset(FROZEN_ENTRYPOINT_KINDS)
_ALLOWED_OWNERS = frozenset({"apps/web", "apps/api", "contracts", "ops"})
_ALLOWED_OWNER_PREFIXES = ("domains/", "infrastructure/", "tests/")


class InventoryValidationError(ValueError):
    """Raised when an inventory cannot prove its frozen planning boundary."""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _source_owner(record: Mapping[str, Any]) -> str:
    path = str(record["path"]).casefold()
    language = str(record["language"]).casefold()
    if path.startswith("10_contracts/"):
        return "contracts"
    if language in {"html", "javascript", "typescript"} or "/frontend/" in path:
        return "apps/web"
    if path.startswith("_ops/") or "timeline_scheduler" in path:
        return "ops"
    if "/tests/" in path or path.startswith("tests/"):
        return "tests/migration"
    if path.startswith("30_runtime/"):
        return "apps/api"
    return "domains/migration"


def _entrypoint_owner(kind: str) -> str:
    return {
        "cli_script": "ops",
        "windows_task": "ops",
        "html_page": "apps/web",
        "python_entry_candidate": "apps/api",
    }[kind]


def _feature_owner(feature_id: str) -> str:
    if feature_id.startswith(("navigation.", "orphan.")):
        return "apps/web"
    if feature_id == "preselection.pools":
        return "domains/preselection"
    if feature_id == "research.desk":
        return "domains/research"
    if feature_id == "review.close":
        return "domains/review"
    if feature_id == "runtime.status":
        return "infrastructure/runtime"
    if feature_id.startswith("stage."):
        return "domains/stage"
    if feature_id == "tasks.registry":
        return "infrastructure/tasks"
    return "domains/migration"


def _relative_evidence(value: Any) -> list[dict[str, Any]]:
    """Keep only portable path/line evidence from nested Atlas evidence objects."""
    evidence: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        path = value.get("path")
        if isinstance(path, str):
            item: dict[str, Any] = {"path": path}
            if isinstance(value.get("line"), int):
                item["line"] = value["line"]
            evidence.append(item)
        for nested in value.values():
            evidence.extend(_relative_evidence(nested))
    elif isinstance(value, list):
        for nested in value:
            evidence.extend(_relative_evidence(nested))
    unique = {(item["path"], item.get("line")): item for item in evidence}
    return [unique[key] for key in sorted(unique)]


def _normalize_feature_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split()
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return sorted({str(item) for item in values if item})


def _normalized_runtime_tasks(features: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for feature in features:
        for raw in feature.get("runtime_tasks", []):
            record_type = raw["record_type"]
            task_name = raw["task_name"]
            key = (record_type, task_name)
            item = by_key.setdefault(
                key,
                {
                    "record_type": record_type,
                    "task_name": task_name,
                    "node_id": raw.get("node_id"),
                    "feature_ids": set(),
                    "source_evidence": [],
                    "target_owner": "ops",
                    "disposition": "REWRITE",
                    "status": "PENDING",
                    "replacement_evidence": [],
                },
            )
            item["feature_ids"].update(_normalize_feature_ids(raw.get("feature_ids")))
            if not item["node_id"] and raw.get("node_id"):
                item["node_id"] = raw["node_id"]
            item["source_evidence"].extend(_relative_evidence(raw.get("evidence", {})))
    output: list[dict[str, Any]] = []
    for key in sorted(by_key):
        item = by_key[key]
        item["feature_ids"] = sorted(item["feature_ids"])
        item["source_evidence"] = _deduplicate_evidence(item["source_evidence"])
        output.append(item)
    return output


def _deduplicate_evidence(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique = {(str(item["path"]), item.get("line")): dict(item) for item in items}
    return [unique[key] for key in sorted(unique)]


def build_inventory(atlas_path: Path, *, expected_counts: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Create a deterministic replacement plan from a read-only Atlas directory."""
    atlas_path = Path(atlas_path)
    validation = _load_json(atlas_path / "validation.json")
    if validation.get("semantic_hash") != FROZEN_SEMANTIC_HASH:
        raise InventoryValidationError("unexpected Atlas semantic hash")
    source_records = [
        record
        for record in _load_jsonl(atlas_path / "files.jsonl")
        if record.get("scan_mode", "included") == "included"
    ]
    raw_entrypoints = _load_json(atlas_path / "entrypoints.json")
    raw_features = _load_json(atlas_path / "feature_ledger.json")["features"]

    inventory = {
        "schema_version": "v3_5.replacement_inventory.v1",
        "atlas": {"semantic_hash": FROZEN_SEMANTIC_HASH},
        "sources": [
            {
                "atlas_file_id": source["id"],
                "old_source": source["path"],
                "language": source["language"],
                "layer": source["layer"],
                "authority": source["authority"],
                "sha256": source["sha256"],
                "target_owner": _source_owner(source),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
            for source in sorted(source_records, key=lambda record: record["id"])
        ],
        "entrypoints": [
            {
                "atlas_entrypoint_id": entrypoint["id"],
                "kind": entrypoint["kind"],
                "name": entrypoint.get("name"),
                "source_evidence": _relative_evidence(entrypoint.get("evidence", {})),
                "source_status": entrypoint["status"],
                "target_owner": _entrypoint_owner(entrypoint["kind"]),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
            for entrypoint in sorted(raw_entrypoints, key=lambda record: record["id"])
        ],
        "runtime_tasks": _normalized_runtime_tasks(raw_features),
        "features": [
            {
                "feature_id": feature["id"],
                "source_gaps": feature.get("gaps", []),
                "target_owner": _feature_owner(feature["id"]),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
            for feature in sorted(raw_features, key=lambda record: record["id"])
        ],
    }
    if expected_counts is None:
        validate_initial_snapshot(inventory)
    else:
        validate_inventory(inventory, expected_counts=expected_counts)
    return inventory


def _is_allowed_owner(owner: Any) -> bool:
    if not _is_normalized_relative_posix_path(owner):
        return False
    return owner in _ALLOWED_OWNERS or owner.startswith(_ALLOWED_OWNER_PREFIXES)


def _is_normalized_relative_posix_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or _ABSOLUTE_PATH.match(value):
        return False
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return False
    return PurePosixPath(value).as_posix() == value


def _assert_relative_posix_path(value: Any, context: str) -> None:
    if isinstance(value, str) and _ABSOLUTE_PATH.match(value):
        raise InventoryValidationError(f"absolute path in {context}: {value}")
    if not _is_normalized_relative_posix_path(value):
        raise InventoryValidationError(f"invalid relative path in {context}")


def _assert_unique(records: Iterable[Mapping[str, Any]], field: str) -> None:
    values = [record.get(field) for record in records]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise InventoryValidationError(f"duplicate or missing {field}")


def _required_string(record: Mapping[str, Any], field: str, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise InventoryValidationError(f"missing or invalid {field} in {context}")
    return value


def _required_list(record: Mapping[str, Any], field: str, context: str) -> list[Any]:
    value = record.get(field)
    if not isinstance(value, list):
        raise InventoryValidationError(f"missing or invalid {field} in {context}")
    return value


def _assert_source_evidence(value: Any, context: str) -> None:
    if not isinstance(value, list):
        raise InventoryValidationError(f"missing or invalid source_evidence in {context}")
    if not value:
        raise InventoryValidationError(f"source_evidence must not be empty in {context}")
    for evidence in value:
        if not isinstance(evidence, Mapping):
            raise InventoryValidationError(f"invalid source_evidence shape in {context}")
        _assert_relative_posix_path(evidence.get("path"), context)
        if "line" in evidence and (not isinstance(evidence["line"], int) or evidence["line"] < 1):
            raise InventoryValidationError(f"invalid source_evidence line in {context}")


def _assert_replacement_evidence(value: Any, context: str) -> None:
    if not isinstance(value, list):
        raise InventoryValidationError(f"missing or invalid replacement_evidence in {context}")
    for evidence in value:
        if not isinstance(evidence, Mapping):
            raise InventoryValidationError(f"invalid replacement_evidence shape in {context}")
        _required_string(evidence, "kind", f"replacement_evidence in {context}")
        _assert_relative_posix_path(evidence.get("path"), context)
        if "line" in evidence and (not isinstance(evidence["line"], int) or evidence["line"] < 1):
            raise InventoryValidationError(f"invalid replacement_evidence line in {context}")


def _assert_record_policy(record: Mapping[str, Any], context: str) -> None:
    if not _is_allowed_owner(record.get("target_owner")):
        raise InventoryValidationError(f"invalid target owner in {context}")
    if record.get("disposition") not in ALLOWED_DISPOSITIONS:
        raise InventoryValidationError(f"unknown disposition in {context}")
    if record.get("status") not in ALLOWED_STATUSES:
        raise InventoryValidationError(f"unknown status in {context}")
    if record.get("disposition") == "APPROVED_REMOVE" and (
        not isinstance(record.get("approval_metadata"), Mapping) or not record["approval_metadata"]
    ):
        raise InventoryValidationError(f"APPROVED_REMOVE requires approval metadata in {context}")
    replacement_evidence = record.get("replacement_evidence")
    _assert_replacement_evidence(replacement_evidence, context)
    if record.get("status") == "PENDING" and replacement_evidence:
        raise InventoryValidationError(f"PENDING record requires empty replacement evidence in {context}")
    if record.get("status") == "COMPLETE" and not replacement_evidence:
        raise InventoryValidationError(f"complete record requires machine evidence in {context}")


def _assert_sources(records: list[Any]) -> None:
    _assert_unique(records, "atlas_file_id")
    for record in records:
        if not isinstance(record, Mapping):
            raise InventoryValidationError("invalid source record")
        _required_string(record, "atlas_file_id", "sources")
        _assert_relative_posix_path(record.get("old_source"), "sources")
        for field in ("language", "layer", "authority"):
            _required_string(record, field, "sources")
        sha256 = _required_string(record, "sha256", "sources")
        if not _SHA256.fullmatch(sha256):
            raise InventoryValidationError("invalid sha256 in sources")
        _assert_record_policy(record, "sources")


def _assert_entrypoints(records: list[Any]) -> None:
    _assert_unique(records, "atlas_entrypoint_id")
    for record in records:
        if not isinstance(record, Mapping):
            raise InventoryValidationError("invalid entrypoint record")
        _required_string(record, "atlas_entrypoint_id", "entrypoints")
        if record.get("kind") not in _ALLOWED_ENTRYPOINT_KINDS:
            raise InventoryValidationError("unknown entrypoint kind")
        if record.get("name") is not None and not isinstance(record["name"], str):
            raise InventoryValidationError("invalid entrypoint name")
        _required_string(record, "source_status", "entrypoints")
        _assert_source_evidence(record.get("source_evidence"), "entrypoints")
        _assert_record_policy(record, "entrypoints")


def _assert_features(records: list[Any]) -> set[str]:
    _assert_unique(records, "feature_id")
    feature_ids: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise InventoryValidationError("invalid feature record")
        feature_ids.add(_required_string(record, "feature_id", "features"))
        _required_list(record, "source_gaps", "features")
        _assert_record_policy(record, "features")
    return feature_ids


def _assert_runtime_tasks(records: list[Any], feature_ids: set[str]) -> None:
    runtime_keys: list[tuple[Any, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise InventoryValidationError("invalid runtime task record")
        runtime_keys.append((record.get("record_type"), record.get("task_name")))
    if any(not isinstance(record_type, str) or not task_name for record_type, task_name in runtime_keys) or len(runtime_keys) != len(set(runtime_keys)):
        raise InventoryValidationError("duplicate or missing runtime task key")
    for record in records:
        if record.get("record_type") not in ALLOWED_RUNTIME_RECORD_TYPES:
            raise InventoryValidationError("unknown runtime record type")
        _required_string(record, "task_name", "runtime_tasks")
        if record.get("node_id") is not None and (not isinstance(record["node_id"], str) or not record["node_id"]):
            raise InventoryValidationError("invalid node_id in runtime_tasks")
        task_feature_ids = _required_list(record, "feature_ids", "runtime_tasks")
        if not task_feature_ids or any(not isinstance(feature_id, str) or not feature_id for feature_id in task_feature_ids):
            raise InventoryValidationError("invalid feature_ids in runtime_tasks")
        if len(task_feature_ids) != len(set(task_feature_ids)):
            raise InventoryValidationError("duplicate feature_ids in runtime_tasks")
        if not set(task_feature_ids).issubset(feature_ids):
            raise InventoryValidationError("unknown feature id in runtime_tasks")
        _assert_source_evidence(record.get("source_evidence"), "runtime_tasks")
        _assert_record_policy(record, "runtime_tasks")


def validate_inventory(inventory: Mapping[str, Any], *, expected_counts: Mapping[str, int] | None = None) -> None:
    """Validate generic replacement schema, lifecycle, ownership, and evidence."""
    if not isinstance(inventory, Mapping):
        raise InventoryValidationError("inventory must be an object")
    if inventory.get("schema_version") != "v3_5.replacement_inventory.v1":
        raise InventoryValidationError("unknown inventory schema")
    atlas = inventory.get("atlas")
    if not isinstance(atlas, Mapping) or not isinstance(atlas.get("semantic_hash"), str) or not _SHA256.fullmatch(atlas["semantic_hash"]):
        raise InventoryValidationError("wrong semantic hash")
    groups = ("sources", "entrypoints", "runtime_tasks", "features")
    for group in groups:
        if not isinstance(inventory.get(group), list):
            raise InventoryValidationError(f"missing or invalid {group}")
    if expected_counts is not None:
        for group, expected in expected_counts.items():
            if not isinstance(expected, int) or len(inventory[group]) != expected:
                raise InventoryValidationError(f"wrong {group} count")

    sources = inventory["sources"]
    entrypoints = inventory["entrypoints"]
    runtime_tasks = inventory["runtime_tasks"]
    features = inventory["features"]
    _assert_sources(sources)
    _assert_entrypoints(entrypoints)
    feature_ids = _assert_features(features)
    _assert_runtime_tasks(runtime_tasks, feature_ids)


def validate_initial_snapshot(inventory: Mapping[str, Any]) -> None:
    """Apply the frozen Atlas 038 and Task 2 initial-state locks only."""
    validate_inventory(inventory, expected_counts=FROZEN_COUNTS)
    if inventory["atlas"]["semantic_hash"] != FROZEN_SEMANTIC_HASH:
        raise InventoryValidationError("wrong frozen semantic hash")
    if {record["feature_id"] for record in inventory["features"]} != FROZEN_FEATURE_IDS:
        raise InventoryValidationError("omission of frozen feature")
    if _counts(inventory["entrypoints"], "kind") != FROZEN_ENTRYPOINT_KINDS:
        raise InventoryValidationError("wrong entrypoint kinds")
    if _counts(inventory["runtime_tasks"], "record_type") != FROZEN_RUNTIME_TASK_TYPES:
        raise InventoryValidationError("wrong runtime task types")
    for group in ("sources", "entrypoints", "runtime_tasks", "features"):
        for record in inventory[group]:
            if record["disposition"] != "REWRITE" or record["status"] != "PENDING" or record["replacement_evidence"]:
                raise InventoryValidationError(f"initial snapshot requires PENDING REWRITE with empty evidence in {group}")


def _counts(records: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record[field])
        counts[value] = counts.get(value, 0) + 1
    return counts


def write_inventory(atlas_path: Path, output_path: Path) -> dict[str, Any]:
    inventory = build_inventory(atlas_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the V4 replacement inventory from a read-only Atlas.")
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_inventory(args.atlas, args.output)


if __name__ == "__main__":
    main()
