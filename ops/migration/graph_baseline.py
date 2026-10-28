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

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[2]))



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
    from ops.migration._graph_baseline_parts.source_identity import __source_owner_body as _v4_impl
    return _v4_impl(globals(), source, previous)


def _entrypoint_owner(kind: str, previous: Mapping[str, Any] | None) -> str:
    from ops.migration._graph_baseline_parts.source_identity import __entrypoint_owner_body as _v4_impl
    return _v4_impl(globals(), kind, previous)


def _evidence(value: Any) -> list[dict[str, Any]]:
    from ops.migration._graph_baseline_parts.source_identity import __evidence_body as _v4_impl
    return _v4_impl(globals(), value)


def _entrypoint_path(entrypoint: Mapping[str, Any]) -> str:
    path = entrypoint.get("path")
    if isinstance(path, str):
        return _relative_path(path, context="Atlas entrypoint")
    evidence = _evidence(entrypoint.get("evidence", entrypoint.get("source_evidence", [])))
    if not evidence:
        raise GraphBaselineError("entrypoint has no source path evidence")
    return str(evidence[0]["path"])


def _graph_index(runtime_graph: Mapping[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    from ops.migration._graph_baseline_parts.source_identity import __graph_index_body as _v4_impl
    return _v4_impl(globals(), runtime_graph)


def _validate_graph_inputs(
    atlas_path: Path,
    runtime_graph_path: Path,
    inventory_v1_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from ops.migration._graph_baseline_parts.source_identity import __validate_graph_inputs_body as _v4_impl
    return _v4_impl(globals(), atlas_path, runtime_graph_path, inventory_v1_path)


def _snapshot_input_paths(
    *, atlas_path: Path, inventory_v1: Mapping[str, Any]
) -> list[str]:
    from ops.migration._graph_baseline_parts.input_snapshot import __snapshot_input_paths_body as _v4_impl
    return _v4_impl(globals(), atlas_path=atlas_path, inventory_v1=inventory_v1)


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
    from ops.migration._graph_baseline_parts.input_snapshot import __validate_input_snapshot_body as _v4_impl
    return _v4_impl(globals(), snapshot_root)


def _difference_rows(
    atlas_by_id: Mapping[str, Mapping[str, Any]],
    previous_by_id: Mapping[str, Mapping[str, Any]],
    *,
    atlas_id_field: str,
    atlas_path_field: str,
    previous_path_field: str,
    legacy_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    from ops.migration._graph_baseline_parts.cli_primitives import __difference_rows_body as _v4_impl
    return _v4_impl(globals(), atlas_by_id, previous_by_id, atlas_id_field=atlas_id_field, atlas_path_field=atlas_path_field, previous_path_field=previous_path_field, legacy_root=legacy_root)


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
    from ops.migration._graph_baseline_parts.graph_assembly import _build_graph_bundle_body as _v4_impl
    return _v4_impl(globals(), atlas_path=atlas_path, runtime_graph_path=runtime_graph_path, inventory_v1_path=inventory_v1_path, legacy_root=legacy_root, _input_snapshot=_input_snapshot, _legacy_root_name=_legacy_root_name)


def build_graph_bundle_from_snapshot(
    snapshot_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild a bundle only after every preserved input byte is revalidated."""
    from ops.migration._graph_baseline_parts.graph_assembly import _build_graph_bundle_from_snapshot_body as _v4_impl
    return _v4_impl(globals(), snapshot_root)


def validate_graph_baseline(baseline: Mapping[str, Any]) -> None:
    from ops.migration._graph_baseline_parts.graph_validation import _validate_graph_baseline_body as _v4_impl
    return _v4_impl(globals(), baseline)


def _validate_lifecycle(record: Mapping[str, Any], context: str) -> None:
    from ops.migration._graph_baseline_parts.lifecycle import __validate_lifecycle_body as _v4_impl
    return _v4_impl(globals(), record, context)


def validate_inventory_v2(
    inventory: Mapping[str, Any], *, baseline: Mapping[str, Any]
) -> None:
    from ops.migration._graph_baseline_parts.inventory_validation import _validate_inventory_v2_body as _v4_impl
    return _v4_impl(globals(), inventory, baseline=baseline)


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
    from ops.migration._graph_baseline_parts.filesystem_io import _write_graph_bundle_body as _v4_impl
    return _v4_impl(globals(), atlas_path=atlas_path, runtime_graph_path=runtime_graph_path, inventory_v1_path=inventory_v1_path, legacy_root=legacy_root, baseline_output=baseline_output, inventory_output=inventory_output, freeze_input_dir=freeze_input_dir)


def main() -> None:
    from ops.migration._graph_baseline_parts.cli_primitives import _main_body as _v4_impl
    return _v4_impl(globals())


if __name__ == "__main__":
    main()
