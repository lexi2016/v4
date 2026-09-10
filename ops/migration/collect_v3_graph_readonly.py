"""Read-only adapter for the authoritative V3 graph builder.

The legacy builder is intentionally imported from its original path: copying it
would change its V3_ROOT/import semantics.  Its only legacy write, topology
publication, is replaced in-memory by an auditable sink.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGACY_ROOT = Path(r"C:\Users\huang\Desktop\学习\v3_system")
DEFAULT_TASK2_EVIDENCE_ROOT = WORKSPACE_ROOT / ".runtime" / "evidence" / "task2"
EXPECTED_BUILDER_SHA256 = "c96e2d340b880c8e2e810f5ad3bf1651963dbc4bf0e3f12eddaca8e8f1ce9a60"


class LegacyGraphSafetyError(RuntimeError):
    """Raised when a no-write collection cannot prove legacy safety."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sentinel(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "sha256": None, "bytes": None}
    if not path.is_file():
        # The topology surface is a directory.  Its deterministic listing is
        # enough to detect any old-V3 mutation without traversing unrelated V3.
        entries = [
            {"path": item.relative_to(path).as_posix(), "sha256": _sha256(item)}
            for item in sorted(path.rglob("*"))
            if item.is_file()
        ]
        return {
            "path": str(path),
            "exists": True,
            "kind": "directory",
            "entries": entries,
            "semantic_hash": _canonical_sha256(entries),
        }
    return {"path": str(path), "exists": True, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _snapshot_sentinels(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    return {str(path.resolve()): _sentinel(path) for path in paths}


def _atlas_sources(atlas_root: Path, legacy_root: Path) -> tuple[list[Path], list[Path], str]:
    files_path = atlas_root / "files.jsonl"
    validation_path = atlas_root / "validation.json"
    entrypoints_path = atlas_root / "entrypoints.json"
    if not all(path.is_file() for path in (files_path, validation_path, entrypoints_path)):
        raise LegacyGraphSafetyError("ATLAS_AUTHORITY_MISSING")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if validation.get("status") != "PASS" or validation.get("semantic_hash") != "912718015fba24d47dcac919b5720139666e3b5dfdf8e72a2236019badcdd033":
        raise LegacyGraphSafetyError("ATLAS_AUTHORITY_INVALID")
    sources: list[Path] = []
    for line in files_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("scan_mode") == "included":
            source = legacy_root / record["path"]
            if not source.is_file():
                raise LegacyGraphSafetyError(f"ATLAS_SOURCE_MISSING:{record['path']}")
            sources.append(source)
    if len(sources) != 336 or len({path.resolve() for path in sources}) != 336:
        raise LegacyGraphSafetyError("ATLAS_SOURCE_IDENTITY_INVALID")
    return sources, [files_path, validation_path, entrypoints_path], validation["semantic_hash"]


def _load_builder(builder_path: Path, legacy_root: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"v3_graph_builder_{uuid.uuid4().hex}", builder_path)
    if spec is None or spec.loader is None:
        raise LegacyGraphSafetyError("BUILDER_IMPORT_SPEC_INVALID")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(legacy_root))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    if not callable(getattr(module, "main", None)) or not callable(getattr(module, "publish_runtime_topology", None)):
        raise LegacyGraphSafetyError("BUILDER_CALLABLE_MISSING")
    return module


def _graph_node_ids(graph: dict[str, Any]) -> list[str]:
    nodes = (graph.get("graph") or {}).get("nodes") or []
    ids = [node.get("id") for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)]
    if len(ids) != len(nodes) or len(ids) != len(set(ids)):
        raise LegacyGraphSafetyError("GRAPH_NODE_IDENTITIES_INVALID")
    return ids


def collect_graph_readonly(
    *,
    legacy_root: Path,
    builder_path: Path,
    output_dir: Path,
    date: str,
    atlas_source_paths: Iterable[Path],
    expected_builder_sha256: str,
    atlas_authority_paths: Iterable[Path] = (),
    evidence_root: Path | None = None,
    api_base: str = "http://127.0.0.1:8771",
) -> dict[str, Any]:
    """Run the original builder with a no-write topology sink and verify sentinels."""
    legacy_root, builder_path, output_dir = legacy_root.resolve(), builder_path.resolve(), output_dir.resolve()
    evidence_root = (evidence_root or DEFAULT_TASK2_EVIDENCE_ROOT).resolve()
    if not _inside(output_dir, evidence_root):
        raise LegacyGraphSafetyError("OUTPUT_OUTSIDE_TASK2_EVIDENCE")
    if output_dir.exists():
        raise LegacyGraphSafetyError("OUTPUT_DIR_NOT_FRESH")
    if not _inside(builder_path, legacy_root) or not builder_path.is_file():
        raise LegacyGraphSafetyError("BUILDER_PATH_INVALID")
    if not isinstance(expected_builder_sha256, str) or len(expected_builder_sha256) != 64 or _sha256(builder_path) != expected_builder_sha256:
        raise LegacyGraphSafetyError("BUILDER_SHA256_INVALID")
    source_paths = [Path(path).resolve() for path in atlas_source_paths]
    if not source_paths or len(source_paths) != len(set(source_paths)) or any(not _inside(path, legacy_root) or not path.is_file() for path in source_paths):
        raise LegacyGraphSafetyError("ATLAS_SOURCE_PATHS_INVALID")
    authority_paths = [Path(path).resolve() for path in atlas_authority_paths]
    if any(not path.is_file() for path in authority_paths):
        raise LegacyGraphSafetyError("ATLAS_AUTHORITY_PATHS_INVALID")
    topology = legacy_root / ".runtime" / "v3_runtime_graph" / "topology"
    watched = [*source_paths, *authority_paths, builder_path, topology]
    before = _snapshot_sentinels(watched)
    output_dir.mkdir(parents=True, exist_ok=True)
    sink: dict[str, Any] = {"invoked": False, "calls": []}

    def publish_sink(payload: dict[str, Any], runtime_root: Path, **kwargs: Any) -> dict[str, Any]:
        sink["invoked"] = True
        sink["calls"].append(
            {
                "would_be_runtime_root": str(runtime_root),
                "payload_semantic_hash": _canonical_sha256(payload),
                "payload_keys": sorted(payload) if isinstance(payload, dict) else [],
            }
        )
        return {"status": "SUNK_NO_LEGACY_WRITE"}

    argv_before = sys.argv[:]
    bytecode_before = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        module = _load_builder(builder_path, legacy_root)
        module.publish_runtime_topology = publish_sink
        sys.argv = [str(builder_path), "--date", date, "--api-base", api_base, "--output-dir", str(output_dir)]
        result = module.main()
    finally:
        sys.argv = argv_before
        sys.dont_write_bytecode = bytecode_before
    after = _snapshot_sentinels(watched)
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise LegacyGraphSafetyError("LEGACY_SENTINEL_CHANGED:" + ",".join(changed))
    if result not in (None, 0) or not sink["invoked"]:
        raise LegacyGraphSafetyError("BUILDER_OR_TOPOLOGY_SINK_FAILED")
    graph_path = output_dir / f"v3_current_script_task_graph_{date}.json"
    required = [graph_path, output_dir / f"v3_current_script_task_graph_{date}.mmd", output_dir / f"V3_CURRENT_SCRIPT_TASK_GRAPH_{date}.md"]
    if any(not path.is_file() for path in required):
        raise LegacyGraphSafetyError("BUILDER_ARTIFACT_MISSING")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if graph.get("schema_version") != "v3_current_script_task_graph.v1":
        raise LegacyGraphSafetyError("GRAPH_SCHEMA_INVALID")
    _graph_node_ids(graph)
    if (graph.get("counts") or {}).get("python_parse_errors") != 0:
        raise LegacyGraphSafetyError("GRAPH_PARSE_ERRORS")
    receipt = {
        "schema_version": "task2_v3_graph_collection_receipt.v1",
        "success": True,
        "collector": "ops/migration/collect_v3_graph_readonly.py",
        "command": [str(builder_path), "--date", date, "--api-base", api_base, "--output-dir", str(output_dir)],
        "graph": {"path": str(graph_path), "raw_sha256": _sha256(graph_path), "schema_version": graph["schema_version"], "counts": graph.get("counts"), "findings": graph.get("findings") or []},
        "topology_sink": sink,
        "legacy_sentinels": {"before": before, "after": after, "unchanged": True},
        "safety": {"legacy_write_detected": False, "windows_tasks_mutated": False, "bytecode_writes_disabled": True, "http_method": "GET_ONLY_BY_LEGACY_BUILDER", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    _atomic_json(output_dir / "collection_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the V3 graph without writing legacy V3.")
    parser.add_argument("--date", default="20260802")
    parser.add_argument("--api-base", default="http://127.0.0.1:8771")
    parser.add_argument("--legacy-root", default=str(DEFAULT_LEGACY_ROOT))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    legacy_root = Path(args.legacy_root)
    atlas_root = legacy_root / "90_ops" / "status" / "v3_full_program_atlas_012"
    sources, authorities, atlas_semantic_hash = _atlas_sources(atlas_root, legacy_root)
    receipt = collect_graph_readonly(
        legacy_root=legacy_root,
        builder_path=legacy_root / "_ops" / "build_v3_current_script_task_graph.py",
        output_dir=Path(args.output_dir),
        date=args.date,
        api_base=args.api_base,
        atlas_source_paths=sources,
        atlas_authority_paths=authorities,
        expected_builder_sha256=EXPECTED_BUILDER_SHA256,
    )
    receipt["atlas"] = {"path": str(atlas_root), "semantic_hash": atlas_semantic_hash, "included_sources": len(sources)}
    _atomic_json(Path(args.output_dir) / "collection_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
