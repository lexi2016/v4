"""Deterministic V4 overlay bound to the frozen and fresh V3 runtime graphs."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

try:  # Supports both package import in tests and direct script invocation.
    from ops.migration.graph_baseline import validate_graph_baseline
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI entrypoint
    from graph_baseline import validate_graph_baseline


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COUNTS = {"sources": 336, "entrypoints": 90, "runtime_tasks": 69, "features": 11}
EXPECTED_INVENTORY_V3_TERMINAL_HASH = "d358d64aadbefb64da8123f893c84b84999d78ffa6330fd892ce09c0be05fc22"
EXPECTED_BASELINE_V2_SEMANTIC_HASH = "8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7"
EXPECTED_PREVIOUS_GRAPH_RAW_SHA256 = "2b64aeb6277dcbf17b649fd2ee2e98cefacc2397b4a3e77d0b745eac619e586b"
EXPECTED_ATLAS_AUTHORITY_RAW_SHA256 = {
    "validation.json": "26317d26f33f8c4f42d1c16481b684585525ba5d2c4bdd14418244edcba8fc89",
    "files.jsonl": "7b0924089cad8bcc34ecacbb2182272cd5b43a7070d4c99eca9443bf3f0c435f",
    "entrypoints.json": "012d2ae8ea11376e83fb6e68d021733e74a36e4e4fa7d4a13041e98740a712be",
}
EXPECTED_TEST_NODE = "file:_ops/test_hkconnect_segment_continuity.py"
EXPECTED_TEST_SOURCE_SHA256 = "79a9bb8f8186a98491617e4322ae210d4e0e0260bbdd81450d67ee43f3cf6f9e"
EXPECTED_TEST_EDGES = {
    json.dumps({"kind": "imports", "line": 6, "module": "hk_connect_formal_panel_daily_update_v3", "source": EXPECTED_TEST_NODE, "target": "file:_ops/hk_connect_formal_panel_daily_update_v3.py"}, sort_keys=True, separators=(",", ":")),
    json.dumps({"kind": "imports", "line": 7, "module": "wq101_hkconnect_bridge", "source": EXPECTED_TEST_NODE, "target": "file:_ops/wq101_hkconnect_bridge.py"}, sort_keys=True, separators=(",", ":")),
}
VOLATILE_FIELDS = {"generated_at", "state", "last_task_result", "last_result", "last_run_time", "next_run_time", "probe_timestamp", "probed_at"}


class GraphInventoryError(RuntimeError):
    pass


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialized_raw_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).replace("\n", os.linesep).encode("utf-8")).hexdigest()


def _atomic_json_pair(
    first_path: Path,
    first_payload: dict[str, Any],
    second_path: Path,
    second_payload: dict[str, Any],
    *,
    replace_fn: Callable[[Path, Path], None] | None = None,
) -> None:
    """Publish both contracts or restore the exact original bytes/absence."""
    replace = replace_fn or (lambda source, destination: os.replace(source, destination))
    original = {path: path.read_bytes() if path.exists() else None for path in (first_path, second_path)}
    staged: list[tuple[Path, Path]] = []
    try:
        for path, payload in ((first_path, first_payload), (second_path, second_payload)):
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            staged.append((temp, path))
        for temp, path in staged:
            replace(temp, path)
    except Exception:
        for path, content in original.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    finally:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)


def _identity(record: dict[str, Any], group: str) -> str:
    fields = {"sources": ("atlas_file_id", "old_source"), "entrypoints": ("atlas_entrypoint_id",), "runtime_tasks": ("node_id", "task_name"), "features": ("feature_id", "name", "id")}[group]
    values = [str(record[field]) for field in fields if record.get(field) not in (None, "")]
    if not values:
        raise GraphInventoryError(f"RECORD_IDENTITY_MISSING:{group}")
    return "|".join(values)


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_inventory_and_baseline(inventory: dict[str, Any], baseline: dict[str, Any]) -> None:
    inventory_unhashed = {key: value for key, value in inventory.items() if key != "terminal_semantic_hash"}
    if (
        inventory.get("schema_version") != "v3_5.replacement_inventory.v3"
        or inventory.get("terminal_semantic_hash") != EXPECTED_INVENTORY_V3_TERMINAL_HASH
        or _canonical_sha256(inventory_unhashed) != inventory.get("terminal_semantic_hash")
    ):
        raise GraphInventoryError("INVENTORY_V3_TERMINAL_SEMANTIC_INVALID")
    try:
        validate_graph_baseline(baseline)
    except Exception as exc:
        raise GraphInventoryError("BASELINE_V2_SEMANTIC_CONTRACT_INVALID") from exc
    if baseline.get("semantic_hash") != EXPECTED_BASELINE_V2_SEMANTIC_HASH:
        raise GraphInventoryError("BASELINE_V2_SEMANTIC_CONTRACT_INVALID")
    if inventory.get("counts") != EXPECTED_COUNTS:
        raise GraphInventoryError("INVENTORY_V3_COUNT_DRIFT")
    for group, expected in EXPECTED_COUNTS.items():
        records = inventory.get(group)
        if not isinstance(records, list) or len(records) != expected:
            raise GraphInventoryError(f"INVENTORY_V3_RECORD_COUNT_DRIFT:{group}")
        identities = [_identity(record, group) for record in records]
        if len(identities) != len(set(identities)):
            raise GraphInventoryError(f"DUPLICATE_RECORD_IDENTITY:{group}")


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items()) if key.lower() not in VOLATILE_FIELDS}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _runtime_structure(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    if graph.get("schema_version") != "v3_current_script_task_graph.v1" or (graph.get("counts") or {}).get("python_parse_errors") != 0:
        raise GraphInventoryError("RUNTIME_GRAPH_INVALID")
    nodes = (graph.get("graph") or {}).get("nodes") or []
    edges = (graph.get("graph") or {}).get("edges") or []
    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node["id"] in node_map:
            raise GraphInventoryError("GRAPH_NODE_IDENTITIES_INVALID")
        node_map[node["id"]] = _normalize(node)
    edge_set = {json.dumps(_normalize(edge), ensure_ascii=False, sort_keys=True, separators=(",", ":")) for edge in edges if isinstance(edge, dict)}
    if len(edge_set) != len(edges):
        raise GraphInventoryError("GRAPH_EDGE_IDENTITIES_INVALID")
    return node_map, edge_set


def _reconcile(
    previous_graph: dict[str, Any],
    fresh_graph: dict[str, Any],
    *,
    atlas_source_paths: set[str],
    test_source_sha256: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    previous_nodes, previous_edges = _runtime_structure(previous_graph)
    fresh_nodes, fresh_edges = _runtime_structure(fresh_graph)
    gained_nodes = sorted(set(fresh_nodes) - set(previous_nodes))
    lost_nodes = sorted(set(previous_nodes) - set(fresh_nodes))
    changed_nodes = sorted(node_id for node_id in set(previous_nodes) & set(fresh_nodes) if previous_nodes[node_id] != fresh_nodes[node_id])
    gained_edges, lost_edges = sorted(fresh_edges - previous_edges), sorted(previous_edges - fresh_edges)
    exact_exception = (
        gained_nodes == [EXPECTED_TEST_NODE]
        and not lost_nodes and not changed_nodes and not lost_edges
        and set(gained_edges) == EXPECTED_TEST_EDGES
        and test_source_sha256 == EXPECTED_TEST_SOURCE_SHA256
        and EXPECTED_TEST_NODE.removeprefix("file:") not in atlas_source_paths
    )
    rows: list[dict[str, Any]] = []
    if exact_exception:
        rows.append({
            "kind": "exact_observed_test_only_addition",
            "node_id": EXPECTED_TEST_NODE,
            "fresh_node": fresh_nodes[EXPECTED_TEST_NODE],
            "fresh_edges": [json.loads(edge) for edge in gained_edges],
            "source_raw_sha256": test_source_sha256,
            "previous_absent": True,
            "atlas_absent": True,
            "classification": "TEST_ONLY_NO_INVENTORY_PROMOTION",
        })
        unexplained: list[dict[str, Any]] = []
    else:
        rows = [{"kind": "gained_node", "node_id": node, "fresh_node": fresh_nodes[node]} for node in gained_nodes]
        rows += [{"kind": "lost_node", "node_id": node, "previous_node": previous_nodes[node]} for node in lost_nodes]
        rows += [{"kind": "changed_node", "node_id": node, "previous_node": previous_nodes[node], "fresh_node": fresh_nodes[node]} for node in changed_nodes]
        rows += [{"kind": "gained_edge", "edge": json.loads(edge)} for edge in gained_edges]
        rows += [{"kind": "lost_edge", "edge": json.loads(edge)} for edge in lost_edges]
        unexplained = copy.deepcopy(rows)
    return {
        "volatile_fields": sorted(VOLATILE_FIELDS),
        "previous_normalized_structural_hash": _canonical_sha256({"nodes": previous_nodes, "edges": sorted(previous_edges)}),
        "fresh_normalized_structural_hash": _canonical_sha256({"nodes": fresh_nodes, "edges": sorted(fresh_edges)}),
        "gained_node_ids": gained_nodes,
        "lost_node_ids": lost_nodes,
        "changed_node_ids": changed_nodes,
        "gained_edges": [json.loads(edge) for edge in gained_edges],
        "lost_edges": [json.loads(edge) for edge in lost_edges],
        "difference_rows": rows,
    }, unexplained


def build_inventory_v4(
    inventory_v3: dict[str, Any], baseline_v2: dict[str, Any], fresh_graph: dict[str, Any], *, previous_graph: dict[str, Any], graph_raw_sha256: str,
    atlas_semantic_hash: str, previous_graph_raw_sha256: str = "0" * 64, inventory_v3_raw_sha256: str | None = None,
    baseline_v2_raw_sha256: str | None = None, atlas_authority_sha256: dict[str, str] | None = None, builder_raw_sha256: str = "0" * 64,
    atlas_source_paths: set[str] | None = None, test_source_sha256: str | None = None,
) -> dict[str, Any]:
    _validate_inventory_and_baseline(inventory_v3, baseline_v2)
    sha_values = [graph_raw_sha256, previous_graph_raw_sha256, atlas_semantic_hash, builder_raw_sha256, inventory_v3_raw_sha256, baseline_v2_raw_sha256]
    if not all(value is None or _valid_sha(value) for value in sha_values):
        raise GraphInventoryError("AUTHORITY_SHA_INVALID")
    if previous_graph_raw_sha256 != EXPECTED_PREVIOUS_GRAPH_RAW_SHA256:
        raise GraphInventoryError("PREVIOUS_GRAPH_SHA_INVALID")
    authority_hashes = atlas_authority_sha256 or {"files.jsonl": "0" * 64, "entrypoints.json": "0" * 64, "validation.json": "0" * 64}
    if set(authority_hashes) != {"files.jsonl", "entrypoints.json", "validation.json"} or not all(_valid_sha(value) for value in authority_hashes.values()):
        raise GraphInventoryError("ATLAS_AUTHORITY_SHA_INVALID")
    reconciliation, unexplained = _reconcile(previous_graph, fresh_graph, atlas_source_paths=atlas_source_paths or set(), test_source_sha256=test_source_sha256)
    if unexplained:
        raise GraphInventoryError("UNEXPLAINED_STRUCTURAL_DIFFERENCE")
    result = {
        "schema_version": "v35_replacement_inventory.v4",
        "base_inventory_v3": {"path": "contracts/migration/v35_replacement_inventory_v3.json", "raw_sha256": inventory_v3_raw_sha256, "semantic_hash": inventory_v3["terminal_semantic_hash"]},
        "graph_baseline_v2": {"path": "contracts/migration/v3_graph_baseline_v2.json", "raw_sha256": baseline_v2_raw_sha256, "semantic_hash": baseline_v2["semantic_hash"]},
        "atlas": {"semantic_hash": atlas_semantic_hash, "included_sources": 336, "authority_files_raw_sha256": authority_hashes},
        "legacy_builder": {"path": "_ops/build_v3_current_script_task_graph.py", "raw_sha256": builder_raw_sha256},
        "previous_runtime_graph": {"raw_sha256": previous_graph_raw_sha256, "normalized_structural_hash": reconciliation["previous_normalized_structural_hash"]},
        "fresh_runtime_graph": {"schema_version": fresh_graph["schema_version"], "raw_sha256": graph_raw_sha256, "normalized_structural_hash": reconciliation["fresh_normalized_structural_hash"], "counts": copy.deepcopy(fresh_graph.get("counts") or {}), "findings": copy.deepcopy(fresh_graph.get("findings") or [])},
        "counts": copy.deepcopy(EXPECTED_COUNTS), "sources": copy.deepcopy(inventory_v3["sources"]), "entrypoints": copy.deepcopy(inventory_v3["entrypoints"]), "runtime_tasks": copy.deepcopy(inventory_v3["runtime_tasks"]), "features": copy.deepcopy(inventory_v3["features"]),
        "claims": {**copy.deepcopy(inventory_v3.get("claims") or {}), "business_parity_verified": False, "ready_to_replace": False},
        "safety": {**copy.deepcopy(inventory_v3.get("safety") or {}), "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        "reconciliation": reconciliation, "unexplained_differences": unexplained, "classification": "ENGINEERING_GRAPH_BASELINE_ONLY",
    }
    semantic = copy.deepcopy(result); semantic["semantic_hash"] = None; result["semantic_hash"] = _canonical_sha256(semantic)
    return result


def _atlas_authority(atlas_root: Path) -> tuple[dict[str, str], set[str]]:
    files = {name: atlas_root / name for name in ("files.jsonl", "entrypoints.json", "validation.json")}
    if any(not path.is_file() for path in files.values()):
        raise GraphInventoryError("ATLAS_AUTHORITY_MISSING")
    raw_hashes = {name: _raw_sha256(path) for name, path in files.items()}
    if raw_hashes != EXPECTED_ATLAS_AUTHORITY_RAW_SHA256:
        raise GraphInventoryError("ATLAS_AUTHORITY_RAW_SHA_DRIFT")
    try:
        validation = json.loads(files["validation.json"].read_text(encoding="utf-8"))
        records = [json.loads(line) for line in files["files.jsonl"].read_text(encoding="utf-8").splitlines() if line.strip()]
        entrypoints = json.loads(files["entrypoints.json"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphInventoryError("ATLAS_VALIDATION_INVALID") from exc
    counts = validation.get("counts") or {}
    if (
        validation.get("schema_version") != "v3_program_atlas.validation.v1"
        or validation.get("status") != "PASS"
        or validation.get("semantic_hash") != "912718015fba24d47dcac919b5720139666e3b5dfdf8e72a2236019badcdd033"
        or {key: counts.get(key) for key in ("included_files", "entrypoints", "parse_gaps")} != {"included_files": 336, "entrypoints": 90, "parse_gaps": 0}
        or not isinstance(entrypoints, list)
    ):
        raise GraphInventoryError("ATLAS_VALIDATION_INVALID")
    included = [record for record in records if record.get("scan_mode") == "included"]
    sources = {record.get("path") for record in included}
    entrypoint_ids = [record.get("id") for record in entrypoints]
    if len(included) != 336 or len(sources) != 336 or None in sources or len(entrypoints) != 90 or len(entrypoint_ids) != len(set(entrypoint_ids)) or None in entrypoint_ids:
        raise GraphInventoryError("ATLAS_IDENTITY_INVALID")
    return raw_hashes, sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic V3.5 replacement inventory v4.")
    parser.add_argument("--inventory-v3", default=str(WORKSPACE_ROOT / "contracts/migration/v35_replacement_inventory_v3.json"))
    parser.add_argument("--baseline-v2", default=str(WORKSPACE_ROOT / "contracts/migration/v3_graph_baseline_v2.json"))
    parser.add_argument("--previous-graph", default=str(WORKSPACE_ROOT / ".runtime/evidence/phase0/v3_current_script_task_graph_20260801/v3_current_script_task_graph_20260801.json"))
    parser.add_argument("--fresh-graph", required=True); parser.add_argument("--atlas-root", required=True)
    parser.add_argument("--output", default=str(WORKSPACE_ROOT / "contracts/migration/v35_replacement_inventory_v4.json")); parser.add_argument("--receipt", default=str(WORKSPACE_ROOT / "docs/evidence/task2-graph-lineage-20260802.json"))
    args = parser.parse_args()
    inventory_path, baseline_path, previous_path, graph_path = map(Path, (args.inventory_v3, args.baseline_v2, args.previous_graph, args.fresh_graph))
    collector_path = graph_path.parent / "collection_receipt.json"
    collector = json.loads(collector_path.read_text(encoding="utf-8"))
    if not collector.get("success") or not collector.get("legacy_sentinels", {}).get("unchanged") or not collector.get("safety", {}).get("bytecode_writes_disabled"):
        raise GraphInventoryError("COLLECTOR_SAFETY_RECEIPT_INVALID")
    if collector.get("graph", {}).get("raw_sha256") != _raw_sha256(graph_path): raise GraphInventoryError("COLLECTOR_GRAPH_SHA_MISMATCH")
    atlas_root = Path(args.atlas_root); atlas_hashes, atlas_sources = _atlas_authority(atlas_root)
    builder_path = Path(collector["command"][0]); test_source = builder_path.parents[1] / "_ops" / "test_hkconnect_segment_continuity.py"
    output = build_inventory_v4(json.loads(inventory_path.read_text(encoding="utf-8")), json.loads(baseline_path.read_text(encoding="utf-8")), json.loads(graph_path.read_text(encoding="utf-8")), previous_graph=json.loads(previous_path.read_text(encoding="utf-8")), graph_raw_sha256=_raw_sha256(graph_path), previous_graph_raw_sha256=_raw_sha256(previous_path), atlas_semantic_hash="912718015fba24d47dcac919b5720139666e3b5dfdf8e72a2236019badcdd033", inventory_v3_raw_sha256=_raw_sha256(inventory_path), baseline_v2_raw_sha256=_raw_sha256(baseline_path), atlas_authority_sha256=atlas_hashes, builder_raw_sha256=_raw_sha256(builder_path), atlas_source_paths=atlas_sources, test_source_sha256=_raw_sha256(test_source))
    receipt = {"schema_version": "task2_graph_lineage_receipt.v2", "classification": "ENGINEERING_GRAPH_BASELINE_ONLY", "inventory": {"path": str(args.output), "raw_sha256": _serialized_raw_sha256(output), "semantic_hash": output["semantic_hash"], "counts": output["counts"]}, "authorities": {key: output[key] for key in ("base_inventory_v3", "graph_baseline_v2", "atlas", "legacy_builder", "previous_runtime_graph", "fresh_runtime_graph")}, "collection": {"receipt_path": str(collector_path), "command": collector["command"], "legacy_sentinels": collector["legacy_sentinels"], "topology_sink": collector["topology_sink"]}, "reconciliation": output["reconciliation"], "unexplained_differences": output["unexplained_differences"], "safety": output["safety"]}
    _atomic_json_pair(Path(args.output), output, Path(args.receipt), receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
