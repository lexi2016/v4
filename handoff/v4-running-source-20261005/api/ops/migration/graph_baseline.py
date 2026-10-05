"""Build the graph-grounded V3.5 baseline without writing to legacy V3.

The V3 Program Atlas is the static code authority.  A freshly collected
script/task graph supplies current task, API, and page identities.  The
orphaned v1 replacement inventory is retained only as reconciliation input for
feature and runtime-task records whose original Atlas directory is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any


BASELINE_SCHEMA = "v3_5.graph_baseline.v2"
INVENTORY_SCHEMA = "v3_5.replacement_inventory.v2"
RUNTIME_GRAPH_SCHEMA = "v3_current_script_task_graph.v1"
INPUT_SNAPSHOT_SCHEMA = "v3_5.graph_input_snapshot.v1"
_SHA256_LENGTH = 64
_GROUPS = ("sources", "entrypoints", "runtime_tasks", "features")
_DISPOSITIONS = frozenset({"KEEP", "REWRITE", "COMPAT", "REMOVE"})
_STATUSES = frozenset({"PENDING", "IN_PROGRESS", "COMPLETE"})
_SOURCE_STATES = frozenset({"MATCHES_ATLAS", "MODIFIED_SINCE_ATLAS", "MISSING"})
_STATIC_ACCEPTANCE_SCOPE = "STATIC_GRAPH_RECONCILIATION_ONLY"
_STATIC_PASS = "STATIC_RECONCILIATION_PASS"
_STATIC_PASS_WITH_RUNTIME_GAPS = "STATIC_RECONCILIATION_PASS_WITH_RUNTIME_GAPS"


class GraphBaselineError(ValueError):
    """Raised when a graph input or generated contract cannot be trusted."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GraphBaselineError(f"cannot read JSON: {path.name}") from error


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GraphBaselineError(f"cannot read JSONL: {path.name}") from error


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    try:
        return _digest_bytes(path.read_bytes())
    except OSError as error:
        raise GraphBaselineError(f"cannot hash file: {path.name}") from error


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _relative_path(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GraphBaselineError(f"invalid relative path in {context}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise GraphBaselineError(f"invalid relative path in {context}")
    return value


def _legacy_file(legacy_root: Path, relative: str) -> Path:
    safe = _relative_path(relative, context="legacy source")
    root = legacy_root.resolve()
    target = (root / Path(*PurePosixPath(safe).parts)).resolve(strict=False)
    if not target.is_relative_to(root):
        raise GraphBaselineError("legacy source path escapes legacy root")
    return target


def _snapshot_file(snapshot_root: Path, relative: str) -> Path:
    safe = _relative_path(relative, context="frozen input")
    root = snapshot_root.resolve()
    target = (root / Path(*PurePosixPath(safe).parts)).resolve(strict=False)
    if not target.is_relative_to(root):
        raise GraphBaselineError("frozen input path escapes snapshot root")
    return target


def _source_layer(path: str, previous: Mapping[str, Any] | None) -> str:
    if previous and isinstance(previous.get("layer"), str):
        return str(previous["layer"])
    folded = path.casefold()
    if "/tests/" in folded or folded.startswith("tests/"):
        return "tests"
    if folded.startswith("_ops/") or "timeline_scheduler" in folded:
        return "ops"
    return "live_core"


def _source_owner(source: Mapping[str, Any], previous: Mapping[str, Any] | None) -> str:
    if previous and isinstance(previous.get("target_owner"), str):
        return str(previous["target_owner"])
    path = str(source["path"]).casefold()
    language = str(source.get("language", "")).casefold()
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


def _entrypoint_owner(kind: str, previous: Mapping[str, Any] | None) -> str:
    if previous and isinstance(previous.get("target_owner"), str):
        return str(previous["target_owner"])
    try:
        return {
            "cli_script": "ops",
            "windows_task": "ops",
            "html_page": "apps/web",
            "python_entry_candidate": "apps/api",
        }[kind]
    except KeyError as error:
        raise GraphBaselineError(f"unknown entrypoint kind: {kind}") from error


def _evidence(value: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str):
            item: dict[str, Any] = {
                "path": _relative_path(value["path"], context="source evidence")
            }
            if isinstance(value.get("line"), int) and value["line"] > 0:
                item["line"] = value["line"]
            output.append(item)
        for nested in value.values():
            output.extend(_evidence(nested))
    elif isinstance(value, list):
        for nested in value:
            output.extend(_evidence(nested))
    unique = {(row["path"], row.get("line")): row for row in output}
    return [unique[key] for key in sorted(unique)]


def _entrypoint_path(entrypoint: Mapping[str, Any]) -> str:
    path = entrypoint.get("path")
    if isinstance(path, str):
        return _relative_path(path, context="Atlas entrypoint")
    evidence = _evidence(entrypoint.get("evidence", entrypoint.get("source_evidence", [])))
    if not evidence:
        raise GraphBaselineError("entrypoint has no source path evidence")
    return str(evidence[0]["path"])


def _graph_index(runtime_graph: Mapping[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    graph = runtime_graph.get("graph")
    if not isinstance(graph, Mapping) or not isinstance(graph.get("nodes"), list):
        raise GraphBaselineError("runtime graph nodes are missing")
    node_ids: set[str] = set()
    by_path: dict[str, list[str]] = {}
    for node in graph["nodes"]:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            raise GraphBaselineError("invalid runtime graph node")
        node_id = str(node["id"])
        if node_id in node_ids:
            raise GraphBaselineError("duplicate runtime graph node")
        node_ids.add(node_id)
        path = node.get("path")
        if isinstance(path, str):
            if node.get("kind") in {"api_route", "frontend_api_ref"}:
                route = PurePosixPath(path)
                if (
                    not path.startswith("/")
                    or "\\" in path
                    or any(part in {".", ".."} for part in route.parts)
                ):
                    raise GraphBaselineError("invalid runtime API path")
                continue
            normalized = _relative_path(path, context="runtime graph node")
            by_path.setdefault(normalized, []).append(node_id)
    return node_ids, {key: sorted(values) for key, values in sorted(by_path.items())}


def _validate_graph_inputs(
    atlas_path: Path,
    runtime_graph_path: Path,
    inventory_v1_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validation = _load_json(atlas_path / "validation.json")
    if not isinstance(validation, Mapping) or validation.get("status") != "PASS":
        raise GraphBaselineError("static Atlas PASS status is required")
    if not _is_sha256(validation.get("semantic_hash")):
        raise GraphBaselineError("invalid Atlas semantic hash")
    runtime_graph = _load_json(runtime_graph_path)
    if (
        not isinstance(runtime_graph, Mapping)
        or runtime_graph.get("schema_version") != RUNTIME_GRAPH_SCHEMA
    ):
        raise GraphBaselineError("unsupported runtime graph schema")
    counts = runtime_graph.get("counts")
    if not isinstance(counts, Mapping):
        raise GraphBaselineError("runtime graph counts are missing")
    if counts.get("python_parse_errors") != 0:
        raise GraphBaselineError("runtime graph has parse errors")
    _graph_index(runtime_graph)
    inventory_v1 = _load_json(inventory_v1_path)
    if (
        not isinstance(inventory_v1, Mapping)
        or inventory_v1.get("schema_version") != "v3_5.replacement_inventory.v1"
    ):
        raise GraphBaselineError("unsupported inventory v1 schema")
    return dict(validation), dict(runtime_graph), dict(inventory_v1)


def _snapshot_input_paths(
    *, atlas_path: Path, inventory_v1: Mapping[str, Any]
) -> list[str]:
    paths = {
        _relative_path(row["path"], context="Atlas snapshot source")
        for row in _load_jsonl(atlas_path / "files.jsonl")
        if row.get("scan_mode", "included") == "included"
    }
    for row in inventory_v1.get("sources", []):
        paths.add(
            _relative_path(row.get("old_source"), context="inventory snapshot source")
        )
    for row in inventory_v1.get("entrypoints", []):
        for evidence in row.get("source_evidence", []):
            if isinstance(evidence, Mapping) and isinstance(evidence.get("path"), str):
                paths.add(
                    _relative_path(
                        evidence["path"], context="entrypoint snapshot source"
                    )
                )
    return sorted(paths)


def freeze_graph_inputs(
    *,
    atlas_path: Path,
    runtime_graph_path: Path,
    inventory_v1_path: Path,
    legacy_root: Path,
    snapshot_root: Path,
) -> dict[str, Any]:
    """Copy every graph input as raw bytes into a new immutable evidence root."""

    atlas_path = Path(atlas_path)
    runtime_graph_path = Path(runtime_graph_path)
    inventory_v1_path = Path(inventory_v1_path)
    legacy_root = Path(legacy_root)
    snapshot_root = Path(snapshot_root)
    _, _, inventory_v1 = _validate_graph_inputs(
        atlas_path, runtime_graph_path, inventory_v1_path
    )
    if snapshot_root.exists():
        raise GraphBaselineError("frozen input snapshot already exists")
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = snapshot_root.with_name(
        f".{snapshot_root.name}.{os.getpid()}.tmp"
    )
    if temporary_root.exists():
        raise GraphBaselineError("frozen input temporary path already exists")
    temporary_root.mkdir()

    rows: list[dict[str, Any]] = []

    def copy_input(source: Path, relative: str, role: str) -> None:
        target = _snapshot_file(temporary_root, relative)
        try:
            content = source.read_bytes()
        except OSError as error:
            raise GraphBaselineError(f"cannot freeze graph input: {relative}") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        rows.append(
            {
                "role": role,
                "path": relative,
                "exists": True,
                "size": len(content),
                "sha256": _digest_bytes(content),
            }
        )

    for name in ("validation.json", "files.jsonl", "entrypoints.json"):
        copy_input(atlas_path / name, f"atlas/{name}", "static_atlas")
    copy_input(runtime_graph_path, "runtime_graph.json", "runtime_graph")
    copy_input(inventory_v1_path, "inventory_v1.json", "inventory_v1")
    for relative in _snapshot_input_paths(
        atlas_path=atlas_path, inventory_v1=inventory_v1
    ):
        source = _legacy_file(legacy_root, relative)
        snapshot_relative = f"legacy_sources/{relative}"
        if source.is_file():
            copy_input(source, snapshot_relative, "legacy_source")
        else:
            rows.append(
                {
                    "role": "legacy_source",
                    "path": snapshot_relative,
                    "exists": False,
                    "size": None,
                    "sha256": None,
                }
            )

    manifest_without_hash: dict[str, Any] = {
        "schema_version": INPUT_SNAPSHOT_SCHEMA,
        "snapshot_id": snapshot_root.name,
        "legacy_root_name": legacy_root.name,
        "atlas_relative_dir": "atlas",
        "runtime_graph_relative_path": "runtime_graph.json",
        "inventory_v1_relative_path": "inventory_v1.json",
        "legacy_sources_relative_dir": "legacy_sources",
        "files": sorted(rows, key=lambda row: (row["role"], row["path"])),
    }
    manifest = {
        **manifest_without_hash,
        "semantic_hash": _digest_bytes(_canonical_bytes(manifest_without_hash)),
    }
    _atomic_json(temporary_root / "snapshot_manifest.json", manifest)
    os.replace(temporary_root, snapshot_root)
    return manifest


def _validate_input_snapshot(snapshot_root: Path) -> dict[str, Any]:
    snapshot_root = Path(snapshot_root)
    manifest = _load_json(snapshot_root / "snapshot_manifest.json")
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version") != INPUT_SNAPSHOT_SCHEMA
    ):
        raise GraphBaselineError("unknown frozen input snapshot schema")
    semantic_hash = manifest.get("semantic_hash")
    if not _is_sha256(semantic_hash):
        raise GraphBaselineError("invalid frozen input snapshot semantic hash")
    unhashed = {
        key: deepcopy(value)
        for key, value in manifest.items()
        if key != "semantic_hash"
    }
    if _digest_bytes(_canonical_bytes(unhashed)) != semantic_hash:
        raise GraphBaselineError("frozen input snapshot semantic hash mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise GraphBaselineError("frozen input snapshot files are missing")
    for row in files:
        if not isinstance(row, Mapping):
            raise GraphBaselineError("invalid frozen input snapshot row")
        target = _snapshot_file(snapshot_root, row.get("path"))
        exists = target.is_file()
        if exists != row.get("exists"):
            raise GraphBaselineError("frozen input existence mismatch")
        if exists:
            if (
                not _is_sha256(row.get("sha256"))
                or _digest_file(target) != row["sha256"]
                or target.stat().st_size != row.get("size")
            ):
                raise GraphBaselineError("frozen input hash mismatch")
        elif row.get("sha256") is not None or row.get("size") is not None:
            raise GraphBaselineError("invalid missing frozen input row")
    return dict(manifest)


def _difference_rows(
    atlas_by_id: Mapping[str, Mapping[str, Any]],
    previous_by_id: Mapping[str, Mapping[str, Any]],
    *,
    atlas_id_field: str,
    atlas_path_field: str,
    previous_path_field: str,
    legacy_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    atlas_only: list[dict[str, Any]] = []
    previous_only: list[dict[str, Any]] = []
    unexplained: list[str] = []
    for identity in sorted(atlas_by_id.keys() - previous_by_id.keys()):
        record = atlas_by_id[identity]
        atlas_only.append(
            {
                atlas_id_field: identity,
                "path": str(record[atlas_path_field]),
                "reason": "ADDED_AFTER_ORPHANED_INVENTORY",
            }
        )
    for identity in sorted(previous_by_id.keys() - atlas_by_id.keys()):
        record = previous_by_id[identity]
        path = str(record[previous_path_field])
        exists = _legacy_file(legacy_root, path).is_file()
        previous_only.append(
            {
                atlas_id_field: identity,
                "path": path,
                "reason": (
                    "REMOVED_FROM_CURRENT_ATLAS_BUT_PRESENT_ON_DISK"
                    if exists
                    else "REMOVED_FROM_CURRENT_ATLAS_AND_DISK"
                ),
            }
        )
    for identity in sorted(atlas_by_id.keys() & previous_by_id.keys()):
        atlas_path_value = str(atlas_by_id[identity][atlas_path_field])
        previous_path_value = str(previous_by_id[identity][previous_path_field])
        if atlas_path_value != previous_path_value:
            unexplained.append(
                f"IDENTITY_PATH_MISMATCH:{identity}:{atlas_path_value}:{previous_path_value}"
            )
    return atlas_only, previous_only, unexplained


def build_graph_bundle(
    *,
    atlas_path: Path,
    runtime_graph_path: Path,
    inventory_v1_path: Path,
    legacy_root: Path,
    _input_snapshot: Mapping[str, Any] | None = None,
    _legacy_root_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deterministic composite baseline and its initial v2 inventory."""
    atlas_path = Path(atlas_path)
    runtime_graph_path = Path(runtime_graph_path)
    inventory_v1_path = Path(inventory_v1_path)
    legacy_root = Path(legacy_root)
    validation, runtime_graph, inventory_v1 = _validate_graph_inputs(
        atlas_path, runtime_graph_path, inventory_v1_path
    )
    node_ids, graph_ids_by_path = _graph_index(runtime_graph)
    atlas_sources = [
        row
        for row in _load_jsonl(atlas_path / "files.jsonl")
        if row.get("scan_mode", "included") == "included"
    ]
    atlas_entrypoints = _load_json(atlas_path / "entrypoints.json")
    if not isinstance(atlas_entrypoints, list):
        raise GraphBaselineError("Atlas entrypoints must be an array")
    atlas_sources_by_id = {str(row["id"]): row for row in atlas_sources}
    atlas_entrypoints_by_id = {str(row["id"]): row for row in atlas_entrypoints}
    if len(atlas_sources_by_id) != len(atlas_sources):
        raise GraphBaselineError("duplicate Atlas source identity")
    if len(atlas_entrypoints_by_id) != len(atlas_entrypoints):
        raise GraphBaselineError("duplicate Atlas entrypoint identity")
    previous_sources = {
        str(row["atlas_file_id"]): row for row in inventory_v1.get("sources", [])
    }
    previous_entrypoints = {
        str(row["atlas_entrypoint_id"]): row
        for row in inventory_v1.get("entrypoints", [])
    }

    atlas_only_sources, v1_only_sources, unexplained_sources = _difference_rows(
        atlas_sources_by_id,
        previous_sources,
        atlas_id_field="atlas_file_id",
        atlas_path_field="path",
        previous_path_field="old_source",
        legacy_root=legacy_root,
    )
    # v1 entrypoints store a source_evidence array, not a canonical path field.
    atlas_only_entrypoints = []
    v1_only_entrypoints = []
    unexplained_entrypoints = []
    for identity in sorted(atlas_entrypoints_by_id.keys() - previous_entrypoints.keys()):
        row = atlas_entrypoints_by_id[identity]
        atlas_only_entrypoints.append(
            {
                "atlas_entrypoint_id": identity,
                "path": _entrypoint_path(row),
                "reason": "ADDED_AFTER_ORPHANED_INVENTORY",
            }
        )
    for identity in sorted(previous_entrypoints.keys() - atlas_entrypoints_by_id.keys()):
        evidence = previous_entrypoints[identity].get("source_evidence", [])
        path = str(evidence[0].get("path")) if evidence else ""
        if not path:
            unexplained_entrypoints.append(f"MISSING_ENTRYPOINT_PATH:{identity}")
            continue
        v1_only_entrypoints.append(
            {
                "atlas_entrypoint_id": identity,
                "path": path,
                "reason": (
                    "REMOVED_FROM_CURRENT_ATLAS_BUT_PRESENT_ON_DISK"
                    if _legacy_file(legacy_root, path).is_file()
                    else "REMOVED_FROM_CURRENT_ATLAS_AND_DISK"
                ),
            }
        )
    for identity in sorted(atlas_entrypoints_by_id.keys() & previous_entrypoints.keys()):
        atlas_path_value = _entrypoint_path(atlas_entrypoints_by_id[identity])
        evidence = previous_entrypoints[identity].get("source_evidence", [])
        previous_path_value = str(evidence[0].get("path")) if evidence else ""
        if not previous_path_value:
            unexplained_entrypoints.append(f"MISSING_ENTRYPOINT_PATH:{identity}")
        elif atlas_path_value != previous_path_value:
            unexplained_entrypoints.append(
                "IDENTITY_PATH_MISMATCH:"
                f"{identity}:{atlas_path_value}:{previous_path_value}"
            )

    source_rows: list[dict[str, Any]] = []
    for source in sorted(atlas_sources, key=lambda row: str(row["id"])):
        identity = str(source["id"])
        path = _relative_path(source["path"], context="Atlas source")
        target = _legacy_file(legacy_root, path)
        current_sha = _digest_file(target) if target.is_file() else None
        atlas_sha = source.get("sha256")
        if not _is_sha256(atlas_sha):
            raise GraphBaselineError(f"invalid Atlas source SHA: {identity}")
        state = (
            "MISSING"
            if current_sha is None
            else "MATCHES_ATLAS"
            if current_sha == atlas_sha
            else "MODIFIED_SINCE_ATLAS"
        )
        previous = previous_sources.get(identity)
        source_rows.append(
            {
                "atlas_file_id": identity,
                "old_source": path,
                "language": str(source.get("language") or "unknown"),
                "layer": _source_layer(path, previous),
                "authority": str(source.get("authority") or "CANNOT_CONFIRM"),
                "atlas_sha256": atlas_sha,
                "sha256": current_sha,
                "source_state": state,
                "graph_node_ids": [f"atlas:{identity}", *graph_ids_by_path.get(path, [])],
                "target_owner": _source_owner(source, previous),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
        )

    entrypoint_rows: list[dict[str, Any]] = []
    for entrypoint in sorted(atlas_entrypoints, key=lambda row: str(row["id"])):
        identity = str(entrypoint["id"])
        path = _entrypoint_path(entrypoint)
        previous = previous_entrypoints.get(identity)
        source_evidence = _evidence(entrypoint.get("evidence", {}))
        if not source_evidence:
            source_evidence = [{"path": path, "line": 1}]
        graph_node_ids = [f"atlas:{identity}", *graph_ids_by_path.get(path, [])]
        if entrypoint.get("kind") == "windows_task" and isinstance(
            entrypoint.get("name"), str
        ):
            graph_node_ids.extend(
                candidate
                for candidate in (
                    f"windows_task:{entrypoint['name']}",
                    f"task_spec:{entrypoint['name']}",
                )
                if candidate in node_ids
            )
        entrypoint_rows.append(
            {
                "atlas_entrypoint_id": identity,
                "kind": str(entrypoint["kind"]),
                "name": entrypoint.get("name"),
                "source_evidence": source_evidence,
                "source_status": str(entrypoint.get("status") or "CANNOT_CONFIRM"),
                "graph_node_ids": sorted(set(graph_node_ids)),
                "target_owner": _entrypoint_owner(str(entrypoint["kind"]), previous),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
        )

    runtime_rows: list[dict[str, Any]] = []
    feature_graph_ids: dict[str, set[str]] = {}
    for previous in inventory_v1.get("runtime_tasks", []):
        row = deepcopy(previous)
        row["disposition"] = "REWRITE"
        row["status"] = "PENDING"
        row["replacement_evidence"] = []
        candidates: list[str] = []
        if row.get("record_type") == "timeline_node":
            candidates.append(f"timeline_node:{row.get('node_id') or row.get('task_name')}")
        elif row.get("record_type") == "windows_task":
            candidates.extend(
                [
                    f"windows_task:{row.get('task_name')}",
                    f"task_spec:{row.get('task_name')}",
                ]
            )
        row["graph_node_ids"] = sorted(candidate for candidate in candidates if candidate in node_ids)
        for feature_id in row.get("feature_ids", []):
            feature_graph_ids.setdefault(str(feature_id), set()).update(row["graph_node_ids"])
        runtime_rows.append(row)

    feature_rows: list[dict[str, Any]] = []
    for previous in inventory_v1.get("features", []):
        row = deepcopy(previous)
        row["disposition"] = "REWRITE"
        row["status"] = "PENDING"
        row["replacement_evidence"] = []
        feature_id = str(row["feature_id"])
        row["graph_node_ids"] = sorted(feature_graph_ids.get(feature_id, set()))
        gaps = {str(value) for value in row.get("source_gaps", [])}
        if not row["graph_node_ids"]:
            gaps.add("GRAPH_NODE_NOT_RECONCILED")
        gaps.add("ORIGINAL_ATLAS_038_NOT_PRESENT")
        row["source_gaps"] = sorted(gaps)
        feature_rows.append(row)

    counts = {
        "sources": len(source_rows),
        "entrypoints": len(entrypoint_rows),
        "runtime_tasks": len(runtime_rows),
        "features": len(feature_rows),
    }
    reconciliation = {
        "atlas_only_sources": atlas_only_sources,
        "inventory_v1_only_sources": v1_only_sources,
        "atlas_only_entrypoints": atlas_only_entrypoints,
        "inventory_v1_only_entrypoints": v1_only_entrypoints,
        "unexplained_differences": sorted(
            [*unexplained_sources, *unexplained_entrypoints]
        ),
    }
    atlas_node_ids = {
        *(f"atlas:{identity}" for identity in atlas_sources_by_id),
        *(f"atlas:{identity}" for identity in atlas_entrypoints_by_id),
    }
    registered_graph_node_ids = sorted(atlas_node_ids | node_ids)
    runtime_has_findings = (
        runtime_graph.get("status") != "PASS"
        or bool(runtime_graph.get("findings", []))
    )
    baseline_without_hash: dict[str, Any] = {
        "schema_version": BASELINE_SCHEMA,
        "status": (
            _STATIC_PASS_WITH_RUNTIME_GAPS
            if not reconciliation["unexplained_differences"] and runtime_has_findings
            else _STATIC_PASS
            if not reconciliation["unexplained_differences"]
            else "FAIL_UNEXPLAINED_DIFFERENCES"
        ),
        "legacy_root_name": _legacy_root_name or legacy_root.name,
        "input_snapshot": (
            {
                "mode": "FROZEN_RAW_BYTES",
                "reproducible": True,
                "snapshot_id": _input_snapshot["snapshot_id"],
                "semantic_hash": _input_snapshot["semantic_hash"],
                "file_count": len(_input_snapshot["files"]),
            }
            if _input_snapshot is not None
            else {
                "mode": "LIVE_READ_NOT_PRESERVED",
                "reproducible": False,
                "snapshot_id": None,
                "semantic_hash": None,
                "file_count": 0,
            }
        ),
        "static_atlas": {
            "snapshot_id": atlas_path.name,
            "semantic_hash": validation["semantic_hash"],
            "validation_status": validation["status"],
            "counts": {
                "sources": len(source_rows),
                "entrypoints": len(entrypoint_rows),
                "parse_failures": int(
                    validation.get("counts", {}).get("parse_gaps", 0)
                ),
            },
            "artifact_sha256": {
                name: _digest_file(atlas_path / name)
                for name in ("validation.json", "files.jsonl", "entrypoints.json")
            },
        },
        "runtime_graph": {
            "snapshot_id": runtime_graph_path.stem,
            "generated_at": runtime_graph.get("generated_at"),
            "status": runtime_graph.get("status"),
            "sha256": _digest_file(runtime_graph_path),
            "counts": deepcopy(runtime_graph.get("counts", {})),
            "finding_count": len(runtime_graph.get("findings", [])),
        },
        "inventory_v1": {
            "semantic_hash": inventory_v1.get("atlas", {}).get("semantic_hash"),
            "sha256": _digest_file(inventory_v1_path),
            "counts": {
                group: len(inventory_v1.get(group, [])) for group in _GROUPS
            },
            "source_status": "HISTORICAL_ORPHANED_ATLAS",
        },
        "current_source_snapshot": {
            "aggregate_sha256": _digest_bytes(
                _canonical_bytes(
                    [
                        {
                            "atlas_file_id": row["atlas_file_id"],
                            "path": row["old_source"],
                            "sha256": row["sha256"],
                            "source_state": row["source_state"],
                        }
                        for row in source_rows
                    ]
                )
            ),
            "state_counts": dict(
                sorted(Counter(row["source_state"] for row in source_rows).items())
            ),
        },
        "graph_node_registry": {
            "ids": registered_graph_node_ids,
            "sha256": _digest_bytes(_canonical_bytes(registered_graph_node_ids)),
            "counts": {
                "atlas": len(atlas_node_ids),
                "runtime": len(node_ids),
                "total": len(registered_graph_node_ids),
            },
        },
        "inventory_v2_counts": counts,
        "reconciliation": reconciliation,
        "acceptance": {
            "scope": _STATIC_ACCEPTANCE_SCOPE,
            "static_reconciliation_accepted": not reconciliation[
                "unexplained_differences"
            ],
            "runtime_accepted": False,
            "deployment_accepted": False,
        },
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    baseline = {
        **baseline_without_hash,
        "semantic_hash": _digest_bytes(_canonical_bytes(baseline_without_hash)),
    }
    inventory_without_hash = {
        "schema_version": INVENTORY_SCHEMA,
        "graph_baseline_semantic_hash": baseline["semantic_hash"],
        "counts": counts,
        "sources": source_rows,
        "entrypoints": entrypoint_rows,
        "runtime_tasks": sorted(
            runtime_rows,
            key=lambda row: (str(row.get("record_type")), str(row.get("task_name"))),
        ),
        "features": sorted(feature_rows, key=lambda row: str(row.get("feature_id"))),
        "safety": deepcopy(baseline["safety"]),
    }
    inventory = {
        **inventory_without_hash,
        "inventory_semantic_hash": _digest_bytes(_canonical_bytes(inventory_without_hash)),
    }
    validate_graph_baseline(baseline)
    validate_inventory_v2(inventory, baseline=baseline)
    return baseline, inventory


def build_graph_bundle_from_snapshot(
    snapshot_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild a bundle only after every preserved input byte is revalidated."""

    snapshot_root = Path(snapshot_root)
    manifest = _validate_input_snapshot(snapshot_root)
    atlas_relative = _relative_path(
        manifest.get("atlas_relative_dir"), context="snapshot Atlas directory"
    )
    runtime_relative = _relative_path(
        manifest.get("runtime_graph_relative_path"),
        context="snapshot runtime graph",
    )
    inventory_relative = _relative_path(
        manifest.get("inventory_v1_relative_path"),
        context="snapshot inventory v1",
    )
    legacy_relative = _relative_path(
        manifest.get("legacy_sources_relative_dir"),
        context="snapshot legacy sources",
    )
    legacy_root_name = manifest.get("legacy_root_name")
    if not isinstance(legacy_root_name, str) or not legacy_root_name:
        raise GraphBaselineError("invalid snapshot legacy root name")
    return build_graph_bundle(
        atlas_path=_snapshot_file(snapshot_root, atlas_relative),
        runtime_graph_path=_snapshot_file(snapshot_root, runtime_relative),
        inventory_v1_path=_snapshot_file(snapshot_root, inventory_relative),
        legacy_root=_snapshot_file(snapshot_root, legacy_relative),
        _input_snapshot=manifest,
        _legacy_root_name=legacy_root_name,
    )


def validate_graph_baseline(baseline: Mapping[str, Any]) -> None:
    if not isinstance(baseline, Mapping) or baseline.get("schema_version") != BASELINE_SCHEMA:
        raise GraphBaselineError("unknown graph baseline schema")
    semantic_hash = baseline.get("semantic_hash")
    if not _is_sha256(semantic_hash):
        raise GraphBaselineError("invalid graph baseline semantic hash")
    unhashed = {key: deepcopy(value) for key, value in baseline.items() if key != "semantic_hash"}
    if _digest_bytes(_canonical_bytes(unhashed)) != semantic_hash:
        raise GraphBaselineError("graph baseline semantic hash mismatch")
    required_sections = {
        "input_snapshot",
        "static_atlas",
        "runtime_graph",
        "inventory_v1",
        "current_source_snapshot",
        "graph_node_registry",
        "inventory_v2_counts",
        "reconciliation",
        "acceptance",
        "safety",
    }
    missing_sections = sorted(required_sections - baseline.keys())
    if missing_sections:
        raise GraphBaselineError(
            f"graph baseline missing required section: {missing_sections[0]}"
        )
    if not isinstance(baseline.get("legacy_root_name"), str) or not baseline[
        "legacy_root_name"
    ]:
        raise GraphBaselineError("invalid legacy_root_name")
    input_snapshot = baseline.get("input_snapshot")
    if (
        not isinstance(input_snapshot, Mapping)
        or set(input_snapshot)
        != {"mode", "reproducible", "snapshot_id", "semantic_hash", "file_count"}
    ):
        raise GraphBaselineError("invalid input_snapshot section")
    if input_snapshot.get("mode") == "FROZEN_RAW_BYTES":
        if (
            input_snapshot.get("reproducible") is not True
            or not isinstance(input_snapshot.get("snapshot_id"), str)
            or not input_snapshot["snapshot_id"]
            or not _is_sha256(input_snapshot.get("semantic_hash"))
            or not isinstance(input_snapshot.get("file_count"), int)
            or input_snapshot["file_count"] <= 0
        ):
            raise GraphBaselineError("invalid frozen input_snapshot section")
    elif input_snapshot != {
        "mode": "LIVE_READ_NOT_PRESERVED",
        "reproducible": False,
        "snapshot_id": None,
        "semantic_hash": None,
        "file_count": 0,
    }:
        raise GraphBaselineError("invalid live input_snapshot section")
    static_atlas = baseline.get("static_atlas")
    static_counts = static_atlas.get("counts") if isinstance(static_atlas, Mapping) else None
    static_artifacts = (
        static_atlas.get("artifact_sha256")
        if isinstance(static_atlas, Mapping)
        else None
    )
    if (
        not isinstance(static_atlas, Mapping)
        or set(static_atlas)
        != {
            "snapshot_id",
            "semantic_hash",
            "validation_status",
            "counts",
            "artifact_sha256",
        }
        or not isinstance(static_atlas.get("snapshot_id"), str)
        or not static_atlas["snapshot_id"]
        or not _is_sha256(static_atlas.get("semantic_hash"))
        or static_atlas.get("validation_status") != "PASS"
        or not isinstance(static_counts, Mapping)
        or set(static_counts) != {"sources", "entrypoints", "parse_failures"}
        or any(type(value) is not int or value < 0 for value in static_counts.values())
        or static_counts["parse_failures"] != 0
        or not isinstance(static_artifacts, Mapping)
        or set(static_artifacts)
        != {"validation.json", "files.jsonl", "entrypoints.json"}
        or any(not _is_sha256(value) for value in static_artifacts.values())
    ):
        raise GraphBaselineError("invalid static_atlas section")
    runtime_graph = baseline.get("runtime_graph")
    if (
        not isinstance(runtime_graph, Mapping)
        or set(runtime_graph)
        != {"snapshot_id", "generated_at", "status", "sha256", "counts", "finding_count"}
        or not isinstance(runtime_graph.get("snapshot_id"), str)
        or not runtime_graph["snapshot_id"]
        or not isinstance(runtime_graph.get("generated_at"), str)
        or not runtime_graph["generated_at"]
        or not isinstance(runtime_graph.get("status"), str)
        or not runtime_graph["status"]
        or not _is_sha256(runtime_graph.get("sha256"))
        or not isinstance(runtime_graph.get("counts"), Mapping)
        or type(runtime_graph["counts"].get("python_parse_errors")) is not int
        or runtime_graph["counts"]["python_parse_errors"] != 0
        or type(runtime_graph["counts"].get("findings")) is not int
        or runtime_graph["counts"]["findings"] < 0
        or type(runtime_graph["counts"].get("graph_nodes")) is not int
        or runtime_graph["counts"]["graph_nodes"] < 0
        or type(runtime_graph.get("finding_count")) is not int
        or runtime_graph["finding_count"] < 0
        or runtime_graph["counts"]["findings"] != runtime_graph["finding_count"]
    ):
        raise GraphBaselineError("invalid runtime_graph section")
    inventory_v1 = baseline.get("inventory_v1")
    previous_counts = (
        inventory_v1.get("counts") if isinstance(inventory_v1, Mapping) else None
    )
    if (
        not isinstance(inventory_v1, Mapping)
        or set(inventory_v1)
        != {"semantic_hash", "sha256", "counts", "source_status"}
        or not _is_sha256(inventory_v1.get("semantic_hash"))
        or not _is_sha256(inventory_v1.get("sha256"))
        or inventory_v1.get("source_status") != "HISTORICAL_ORPHANED_ATLAS"
        or not isinstance(previous_counts, Mapping)
        or set(previous_counts) != set(_GROUPS)
        or any(type(value) is not int or value < 0 for value in previous_counts.values())
    ):
        raise GraphBaselineError("invalid inventory_v1 section")
    inventory_v2_counts = baseline.get("inventory_v2_counts")
    if (
        not isinstance(inventory_v2_counts, Mapping)
        or set(inventory_v2_counts) != set(_GROUPS)
        or any(
            type(value) is not int or value < 0
            for value in inventory_v2_counts.values()
        )
        or inventory_v2_counts["sources"] != static_counts["sources"]
        or inventory_v2_counts["entrypoints"] != static_counts["entrypoints"]
    ):
        raise GraphBaselineError("invalid inventory_v2_counts section")
    current_source_snapshot = baseline.get("current_source_snapshot")
    state_counts = (
        current_source_snapshot.get("state_counts")
        if isinstance(current_source_snapshot, Mapping)
        else None
    )
    if (
        not isinstance(current_source_snapshot, Mapping)
        or set(current_source_snapshot) != {"aggregate_sha256", "state_counts"}
        or not _is_sha256(current_source_snapshot.get("aggregate_sha256"))
        or not isinstance(state_counts, Mapping)
        or not set(state_counts).issubset(_SOURCE_STATES)
        or any(type(value) is not int or value < 0 for value in state_counts.values())
        or sum(state_counts.values()) != inventory_v2_counts["sources"]
    ):
        raise GraphBaselineError("invalid current_source_snapshot section")
    registry = baseline.get("graph_node_registry")
    registered_ids = registry.get("ids") if isinstance(registry, Mapping) else None
    if (
        not isinstance(registered_ids, list)
        or any(not isinstance(value, str) or not value for value in registered_ids)
        or registered_ids != sorted(set(registered_ids))
        or not _is_sha256(registry.get("sha256"))
        or registry["sha256"] != _digest_bytes(_canonical_bytes(registered_ids))
        or not isinstance(registry.get("counts"), Mapping)
        or set(registry["counts"]) != {"atlas", "runtime", "total"}
        or any(
            type(value) is not int or value < 0
            for value in registry["counts"].values()
        )
        or registry["counts"]["atlas"]
        != static_counts["sources"] + static_counts["entrypoints"]
        or registry["counts"]["runtime"] != runtime_graph["counts"]["graph_nodes"]
        or registry["counts"]["total"]
        != registry["counts"]["atlas"] + registry["counts"]["runtime"]
        or registry["counts"]["total"] != len(registered_ids)
    ):
        raise GraphBaselineError("invalid graph_node_registry section")
    reconciliation = baseline.get("reconciliation")
    if (
        not isinstance(reconciliation, Mapping)
        or set(reconciliation)
        != {
            "atlas_only_sources",
            "inventory_v1_only_sources",
            "atlas_only_entrypoints",
            "inventory_v1_only_entrypoints",
            "unexplained_differences",
        }
        or any(not isinstance(reconciliation[name], list) for name in reconciliation)
    ):
        raise GraphBaselineError("invalid graph reconciliation")
    if reconciliation["unexplained_differences"]:
        raise GraphBaselineError("graph baseline has unexplained differences")
    expected_status = (
        _STATIC_PASS_WITH_RUNTIME_GAPS
        if runtime_graph["status"] != "PASS" or runtime_graph["finding_count"]
        else _STATIC_PASS
    )
    if baseline.get("status") != expected_status:
        raise GraphBaselineError("graph baseline did not pass")
    acceptance = baseline.get("acceptance")
    if acceptance != {
        "scope": _STATIC_ACCEPTANCE_SCOPE,
        "static_reconciliation_accepted": True,
        "runtime_accepted": False,
        "deployment_accepted": False,
    }:
        raise GraphBaselineError("invalid graph baseline acceptance scope")
    safety = baseline.get("safety")
    if safety != {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }:
        raise GraphBaselineError("unsafe graph baseline")


def _validate_lifecycle(record: Mapping[str, Any], context: str) -> None:
    if record.get("disposition") not in _DISPOSITIONS:
        raise GraphBaselineError(f"invalid disposition in {context}")
    if record.get("status") not in _STATUSES:
        raise GraphBaselineError(f"invalid status in {context}")
    evidence = record.get("replacement_evidence")
    if not isinstance(evidence, list):
        raise GraphBaselineError(f"invalid replacement evidence in {context}")
    for item in evidence:
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("kind"), str)
            or not item["kind"]
        ):
            raise GraphBaselineError(f"invalid replacement evidence in {context}")
        _relative_path(item.get("path"), context=f"replacement evidence in {context}")
        if "line" in item and (
            type(item["line"]) is not int or item["line"] < 1
        ):
            raise GraphBaselineError(f"invalid replacement evidence in {context}")
    if record.get("status") == "PENDING" and evidence:
        raise GraphBaselineError(f"PENDING record has replacement evidence in {context}")
    if record.get("status") == "COMPLETE" and not evidence:
        raise GraphBaselineError(
            f"COMPLETE record requires replacement evidence in {context}"
        )
    graph_node_ids = record.get("graph_node_ids")
    if (
        not isinstance(graph_node_ids, list)
        or any(not isinstance(value, str) or not value for value in graph_node_ids)
        or graph_node_ids != sorted(set(graph_node_ids))
    ):
        raise GraphBaselineError(f"invalid graph_node_ids in {context}")


def validate_inventory_v2(
    inventory: Mapping[str, Any], *, baseline: Mapping[str, Any]
) -> None:
    validate_graph_baseline(baseline)
    if not isinstance(inventory, Mapping) or inventory.get("schema_version") != INVENTORY_SCHEMA:
        raise GraphBaselineError("unknown inventory v2 schema")
    inventory_semantic_hash = inventory.get("inventory_semantic_hash")
    if not _is_sha256(inventory_semantic_hash):
        raise GraphBaselineError("invalid inventory semantic hash")
    unhashed = {
        key: deepcopy(value)
        for key, value in inventory.items()
        if key != "inventory_semantic_hash"
    }
    if _digest_bytes(_canonical_bytes(unhashed)) != inventory_semantic_hash:
        raise GraphBaselineError("inventory semantic hash mismatch")
    if inventory.get("graph_baseline_semantic_hash") != baseline.get("semantic_hash"):
        raise GraphBaselineError("inventory graph baseline hash mismatch")
    counts = inventory.get("counts")
    if not isinstance(counts, Mapping) or counts != baseline.get("inventory_v2_counts"):
        raise GraphBaselineError("inventory counts do not match graph baseline")
    registered_graph_nodes = set(baseline["graph_node_registry"]["ids"])
    for group in _GROUPS:
        records = inventory.get(group)
        if not isinstance(records, list) or len(records) != counts.get(group):
            raise GraphBaselineError(f"wrong {group} count")
        for record in records:
            if not isinstance(record, Mapping):
                raise GraphBaselineError(f"invalid record in {group}")
            _validate_lifecycle(record, group)
            unknown_graph_nodes = sorted(
                set(record["graph_node_ids"]) - registered_graph_nodes
            )
            if unknown_graph_nodes:
                raise GraphBaselineError(
                    f"unknown graph node in {group}: {unknown_graph_nodes[0]}"
                )
    source_ids: set[str] = set()
    for source in inventory["sources"]:
        identity = source.get("atlas_file_id")
        if not isinstance(identity, str) or identity in source_ids:
            raise GraphBaselineError("duplicate or missing atlas_file_id")
        source_ids.add(identity)
        _relative_path(source.get("old_source"), context="inventory source")
        if not _is_sha256(source.get("atlas_sha256")):
            raise GraphBaselineError("invalid Atlas SHA in inventory source")
        if source.get("source_state") not in _SOURCE_STATES:
            raise GraphBaselineError("invalid source state")
        if source["source_state"] == "MISSING":
            if source.get("sha256") is not None:
                raise GraphBaselineError("missing source has a SHA")
        elif not _is_sha256(source.get("sha256")):
            raise GraphBaselineError("invalid current source SHA")
    entrypoint_ids: set[str] = set()
    for entrypoint in inventory["entrypoints"]:
        identity = entrypoint.get("atlas_entrypoint_id")
        if not isinstance(identity, str) or identity in entrypoint_ids:
            raise GraphBaselineError("duplicate or missing atlas_entrypoint_id")
        entrypoint_ids.add(identity)
        evidence = entrypoint.get("source_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise GraphBaselineError("entrypoint source evidence is required")
        for item in evidence:
            if not isinstance(item, Mapping):
                raise GraphBaselineError("invalid entrypoint source evidence")
            _relative_path(item.get("path"), context="entrypoint evidence")
    runtime_keys: set[tuple[str, str]] = set()
    for runtime_task in inventory["runtime_tasks"]:
        key = (str(runtime_task.get("record_type")), str(runtime_task.get("task_name")))
        if not all(key) or key in runtime_keys:
            raise GraphBaselineError("duplicate or missing runtime task key")
        runtime_keys.add(key)
        if not isinstance(runtime_task.get("feature_ids"), list) or not runtime_task["feature_ids"]:
            raise GraphBaselineError("runtime task feature_ids are required")
    feature_ids: set[str] = set()
    for feature in inventory["features"]:
        feature_id = feature.get("feature_id")
        if not isinstance(feature_id, str) or not feature_id or feature_id in feature_ids:
            raise GraphBaselineError("duplicate or missing feature_id")
        feature_ids.add(feature_id)
        if not isinstance(feature.get("source_gaps"), list):
            raise GraphBaselineError("feature source_gaps are required")
    if inventory.get("safety") != baseline.get("safety"):
        raise GraphBaselineError("unsafe inventory v2")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_graph_bundle(
    *,
    atlas_path: Path,
    runtime_graph_path: Path,
    inventory_v1_path: Path,
    legacy_root: Path,
    baseline_output: Path,
    inventory_output: Path,
    freeze_input_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if freeze_input_dir is not None:
        freeze_graph_inputs(
            atlas_path=atlas_path,
            runtime_graph_path=runtime_graph_path,
            inventory_v1_path=inventory_v1_path,
            legacy_root=legacy_root,
            snapshot_root=freeze_input_dir,
        )
        baseline, inventory = build_graph_bundle_from_snapshot(freeze_input_dir)
    else:
        baseline, inventory = build_graph_bundle(
            atlas_path=atlas_path,
            runtime_graph_path=runtime_graph_path,
            inventory_v1_path=inventory_v1_path,
            legacy_root=legacy_root,
        )
    _atomic_json(Path(baseline_output), baseline)
    _atomic_json(Path(inventory_output), inventory)
    return baseline, inventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the graph-grounded V3.5 baseline v2.")
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--runtime-graph", required=True, type=Path)
    parser.add_argument("--inventory-v1", required=True, type=Path)
    parser.add_argument("--legacy-root", required=True, type=Path)
    parser.add_argument("--baseline-output", required=True, type=Path)
    parser.add_argument("--inventory-output", required=True, type=Path)
    parser.add_argument("--freeze-input-dir", type=Path)
    args = parser.parse_args()
    write_graph_bundle(
        atlas_path=args.atlas,
        runtime_graph_path=args.runtime_graph,
        inventory_v1_path=args.inventory_v1,
        legacy_root=args.legacy_root,
        baseline_output=args.baseline_output,
        inventory_output=args.inventory_output,
        freeze_input_dir=args.freeze_input_dir,
    )


if __name__ == "__main__":
    main()
