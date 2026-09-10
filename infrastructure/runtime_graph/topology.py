from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .contracts import required_evidence_layers


TOPOLOGY_SCHEMA_VERSION = "v3_runtime_topology.v1"
TOPOLOGY_AUTHORITY_ROOT = "30_runtime"
EXPECTED_NODE_COUNT = 34
EXPECTED_TASK_COUNT = 35
SHARED_INTRADAY_NODE = "v3_opening_intraday_stage_select_0925_1500"
SHARED_INTRADAY_TASKS = (
    "OpeningAdvisorV3_0925_IntradayStage",
    "OpeningAdvisorV3_0935_IntradayStage",
    "OpeningAdvisorV3_0940_IntradayStage",
    "OpeningAdvisorV3_0945_IntradayStage",
    "OpeningAdvisorV3_1030_IntradayStage",
    "OpeningAdvisorV3_1315_IntradayStage",
    "OpeningAdvisorV3_1500_IntradayStageAndFupan",
)
ALLOWED_MODULES = {
    "stage_selection",
    "preselection",
    "research",
    "review",
    "tasks",
    "auxiliary",
}
VOLATILE_RAW_GRAPH_FIELDS = {
    "exists",
    "last_run_time",
    "last_task_result",
    "next_run_time",
    "state",
}
JsonWriter = Callable[[Path, dict[str, Any]], None]


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _clone_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clone_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json(item) for item in value]
    if isinstance(value, tuple):
        return [_clone_json(item) for item in value]
    return value


def _sanitize_raw_graph(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_raw_graph(item)
            for key, item in value.items()
            if str(key) not in VOLATILE_RAW_GRAPH_FIELDS
        }
    if isinstance(value, list):
        return [_sanitize_raw_graph(item) for item in value]
    return value


def _sorted_json_rows(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=_canonical_json)


def _node_id(row: Any) -> str:
    if not isinstance(row, dict):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    node_id = row.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    return node_id


def _validate_binding(binding: Any) -> str:
    if not isinstance(binding, dict):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    task_name = binding.get("task_name")
    if not isinstance(task_name, str) or not task_name:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    if not isinstance(binding.get("run_policy"), str):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    if not isinstance(binding.get("schedule"), dict):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    dependencies = binding.get("dependencies")
    if not isinstance(dependencies, list) or not all(
        isinstance(value, str) and value for value in dependencies
    ):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    timeout_seconds = binding.get("timeout_seconds")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    return task_name


def _validate_node(row: Any) -> str:
    node_id = _node_id(row)
    required_evidence_layers(row)
    if row.get("module") not in ALLOWED_MODULES:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    page_sections = row.get("page_sections")
    if not isinstance(page_sections, list) or not page_sections or not all(
        isinstance(value, str) and value for value in page_sections
    ):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    semantic_validator = row.get("semantic_validator")
    if not isinstance(semantic_validator, str) or not semantic_validator:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    receipt = row.get("page_receipt")
    if not isinstance(receipt, str) or not receipt.endswith(
        f"/{{date}}/{node_id}.json"
    ):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    bindings = row.get("task_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    task_names = [_validate_binding(binding) for binding in bindings]
    if len(task_names) != len(set(task_names)):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    if task_names != sorted(task_names):
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    if row.get("task_name") not in task_names:
        raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    return node_id


def validate_topology(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_INVALID")
    if payload.get("schema_version") != TOPOLOGY_SCHEMA_VERSION:
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_VERSION_INVALID")
    if payload.get("authority_root") != TOPOLOGY_AUTHORITY_ROOT:
        raise ValueError("RUNTIME_GRAPH_AUTHORITY_INVALID")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_NODES_INVALID")
    node_ids = [_validate_node(row) for row in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("RUNTIME_GRAPH_NODE_ID_DUPLICATE")
    if node_ids != sorted(node_ids):
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_NODES_UNSORTED")
    edges = payload.get("edges")
    if not isinstance(edges, list):
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_EDGES_INVALID")
    edge_keys: list[tuple[str, str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_EDGES_INVALID")
        key = (edge.get("source"), edge.get("target"), edge.get("kind"))
        if not all(isinstance(value, str) and value for value in key):
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_EDGES_INVALID")
        if key[0] not in node_ids or key[1] not in node_ids:
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_EDGES_INVALID")
        edge_keys.append(key)
    if edge_keys != sorted(set(edge_keys)):
        raise ValueError("RUNTIME_GRAPH_TOPOLOGY_EDGES_INVALID")
    raw_graph = payload.get("raw_graph")
    if (
        not isinstance(raw_graph, dict)
        or not isinstance(raw_graph.get("nodes"), list)
        or not isinstance(raw_graph.get("edges"), list)
    ):
        raise ValueError("RUNTIME_GRAPH_RAW_GRAPH_INVALID")


def load_runtime_timeline(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("RUNTIME_GRAPH_TIMELINE_LOAD_FAILED") from exc
    if not isinstance(payload, dict):
        raise ValueError("RUNTIME_GRAPH_TIMELINE_INVALID")
    return payload


def _normalize_task_binding(task: dict[str, Any]) -> dict[str, Any]:
    task_name = task.get("task_name")
    if not isinstance(task_name, str) or not task_name:
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
    run_policy = task.get("run_policy", "natural_day")
    schedule = task.get("schedule") or {}
    dependencies = task.get("dependencies") or []
    if not isinstance(run_policy, str):
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
    if not isinstance(schedule, dict):
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
    if not isinstance(dependencies, list) or not all(
        isinstance(value, str) and value for value in dependencies
    ):
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
    try:
        timeout_seconds = int(task.get("timeout_seconds") or 1800)
    except (TypeError, ValueError) as exc:
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID") from exc
    if timeout_seconds <= 0:
        raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
    return {
        "task_name": task_name,
        "run_policy": run_policy,
        "schedule": _clone_json(schedule),
        "dependencies": list(dependencies),
        "timeout_seconds": timeout_seconds,
    }


def derive_topology_operations(
    timeline: dict[str, Any],
) -> dict[str, Any]:
    tasks = timeline.get("windows_tasks")
    descriptors = timeline.get("nodes")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("RUNTIME_GRAPH_TIMELINE_INVALID")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("RUNTIME_GRAPH_TIMELINE_INVALID")
    descriptor_by_node: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        node_id = _node_id(descriptor)
        if node_id in descriptor_by_node:
            raise ValueError("RUNTIME_GRAPH_NODE_ID_DUPLICATE")
        descriptor_by_node[node_id] = descriptor
    bindings_by_node: dict[str, dict[str, dict[str, Any]]] = {
        node_id: {}
        for node_id in descriptor_by_node
    }
    nodes_by_task: dict[str, tuple[str, ...]] = {}
    bindings_by_task: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("RUNTIME_GRAPH_TASK_OPERATION_INVALID")
        binding = _normalize_task_binding(task)
        task_name = binding["task_name"]
        if task_name in nodes_by_task:
            raise ValueError("RUNTIME_GRAPH_PRODUCTION_TASKS_INVALID")
        node_values = task.get("nodes") or []
        if not isinstance(node_values, list) or not node_values or not all(
            isinstance(value, str) and value for value in node_values
        ):
            raise ValueError("RUNTIME_GRAPH_TASK_NODE_OWNERSHIP_UNKNOWN")
        if len(node_values) != len(set(node_values)):
            raise ValueError("RUNTIME_GRAPH_TASK_NODE_OWNERSHIP_DUPLICATE")
        unknown_nodes = set(node_values) - set(descriptor_by_node)
        if unknown_nodes:
            raise ValueError("RUNTIME_GRAPH_TASK_NODE_OWNERSHIP_UNKNOWN")
        nodes_by_task[task_name] = tuple(node_values)
        bindings_by_task[task_name] = binding
        for node_id in node_values:
            bindings_by_node[node_id][task_name] = _clone_json(binding)
    if any(not bindings for bindings in bindings_by_node.values()):
        raise ValueError("RUNTIME_GRAPH_TASK_NODE_OWNERSHIP_UNKNOWN")
    task_names = set(nodes_by_task)
    for binding in bindings_by_task.values():
        if any(
            dependency not in task_names
            for dependency in binding["dependencies"]
        ):
            raise ValueError("RUNTIME_GRAPH_DEPENDENCY_TASK_UNKNOWN")
    normalized_bindings = {
        node_id: [
            bindings[task_name]
            for task_name in sorted(bindings)
        ]
        for node_id, bindings in bindings_by_node.items()
    }
    primary_by_node: dict[str, dict[str, Any]] = {}
    for node_id, descriptor in descriptor_by_node.items():
        task_bindings = normalized_bindings[node_id]
        preferred = descriptor.get("windows_task_name")
        if preferred and preferred not in bindings_by_node[node_id]:
            raise ValueError("RUNTIME_GRAPH_PRIMARY_TASK_UNKNOWN")
        primary = next(
            (
                binding
                for binding in task_bindings
                if binding["task_name"] == preferred
            ),
            task_bindings[0],
        )
        primary_by_node[node_id] = _clone_json(primary)
    edge_keys = {
        (source_node, target_node, "node_dependency")
        for task_name, binding in bindings_by_task.items()
        for dependency in binding["dependencies"]
        for source_node in nodes_by_task[dependency]
        for target_node in nodes_by_task[task_name]
    }
    edges = [
        {
            "source": source,
            "target": target,
            "kind": kind,
        }
        for source, target, kind in sorted(edge_keys)
    ]
    return {
        "bindings_by_node": normalized_bindings,
        "primary_by_node": primary_by_node,
        "edges": edges,
        "task_names": sorted(task_names),
    }


def validate_runtime_timeline(
    timeline: dict[str, Any],
) -> dict[str, Any]:
    tasks = timeline.get("windows_tasks")
    descriptors = timeline.get("nodes")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_TASK_COUNT:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_TASK_COUNT_INVALID")
    if not isinstance(descriptors, list) or len(descriptors) != EXPECTED_NODE_COUNT:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_NODE_COUNT_INVALID")
    operations = derive_topology_operations(timeline)
    if len(operations["task_names"]) != EXPECTED_TASK_COUNT:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_TASKS_INVALID")
    shared_tasks = tuple(
        binding["task_name"]
        for binding in operations["bindings_by_node"][SHARED_INTRADAY_NODE]
    )
    if shared_tasks != SHARED_INTRADAY_TASKS:
        raise ValueError("RUNTIME_GRAPH_SHARED_NODE_BINDINGS_INVALID")
    for descriptor in descriptors:
        node_id = str(descriptor["node_id"])
        if descriptor.get("module") not in ALLOWED_MODULES:
            raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
        if not descriptor.get("page_sections"):
            raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
        if not descriptor.get("semantic_validator"):
            raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
        receipt = descriptor.get("page_receipt")
        if not isinstance(receipt, str) or not receipt.endswith(
            f"/{{date}}/{node_id}.json"
        ):
            raise ValueError("RUNTIME_GRAPH_NODE_INVALID")
    return operations


def validate_production_topology(
    payload: dict[str, Any],
    timeline: dict[str, Any],
) -> None:
    operations = validate_runtime_timeline(timeline)
    validate_topology(payload)
    nodes = payload["nodes"]
    if len(nodes) != EXPECTED_NODE_COUNT:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_NODE_COUNT_INVALID")
    actual_ids = {str(row["node_id"]) for row in nodes}
    if actual_ids != set(operations["bindings_by_node"]):
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_NODE_SET_INVALID")
    represented_tasks: set[str] = set()
    for row in nodes:
        node_id = str(row["node_id"])
        expected_bindings = operations["bindings_by_node"][node_id]
        if row["task_bindings"] != expected_bindings:
            raise ValueError("RUNTIME_GRAPH_PRODUCTION_BINDINGS_INVALID")
        task_names = [
            str(binding["task_name"])
            for binding in expected_bindings
        ]
        represented_tasks.update(task_names)
        actual_primary = {
            key: row.get(key)
            for key in (
                "task_name",
                "run_policy",
                "schedule",
                "dependencies",
                "timeout_seconds",
            )
        }
        if actual_primary != operations["primary_by_node"][node_id]:
            raise ValueError("RUNTIME_GRAPH_PRODUCTION_PRIMARY_MIRROR_INVALID")
    expected_tasks = set(operations["task_names"])
    if represented_tasks != expected_tasks:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_TASK_SET_INVALID")
    if payload["edges"] != operations["edges"]:
        raise ValueError("RUNTIME_GRAPH_PRODUCTION_EDGES_INVALID")


def stable_topology_version(payload: dict[str, Any]) -> dict[str, Any]:
    validate_topology(payload)
    stable = {
        str(key): _clone_json(value)
        for key, value in payload.items()
        if key != "generated_at"
    }
    raw_graph = _sanitize_raw_graph(payload["raw_graph"])
    raw_graph["nodes"] = _sorted_json_rows(raw_graph["nodes"])
    raw_graph["edges"] = _sorted_json_rows(raw_graph["edges"])
    stable["raw_graph"] = raw_graph
    return stable


def topology_version_sha(payload: dict[str, Any]) -> str:
    stable = stable_topology_version(payload)
    return hashlib.sha256(_canonical_json(stable)).hexdigest()


def publish_topology(
    payload: dict[str, Any],
    runtime_root: Path,
    *,
    timeline: dict[str, Any],
    writer: JsonWriter,
) -> dict[str, Any]:
    validate_production_topology(payload, timeline)
    stable = stable_topology_version(payload)
    version_sha = hashlib.sha256(_canonical_json(stable)).hexdigest()
    version_path = runtime_root / "versions" / f"{version_sha}.json"
    current_path = runtime_root / "current.json"
    if version_path.exists():
        existing = load_topology(version_path)
        if _canonical_json(existing) != _canonical_json(stable):
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_VERSION_CONFLICT")
    else:
        writer(version_path, stable)
        written = load_topology(version_path)
        if _canonical_json(written) != _canonical_json(stable):
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_VERSION_VERIFY_FAILED")
    writer(current_path, payload)
    return {
        "version_sha": version_sha,
        "version_path": version_path,
        "current_path": current_path,
    }


def load_topology(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_topology(payload)
    return payload


def index_topology(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_topology(payload)
    return {
        str(row["node_id"]): dict(row)
        for row in payload["nodes"]
    }
