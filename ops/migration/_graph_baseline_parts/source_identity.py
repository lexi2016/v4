"""ops.migration.graph_baseline: source_identity (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __source_owner_body(_v4_scope, /, source, previous):
    if previous and _v4_global(_v4_scope, 'isinstance')(previous.get("target_owner"), _v4_global(_v4_scope, 'str')):
        return _v4_global(_v4_scope, 'str')(previous["target_owner"])
    path = _v4_global(_v4_scope, 'str')(source["path"]).casefold()
    language = _v4_global(_v4_scope, 'str')(source.get("language", "")).casefold()
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


def __entrypoint_owner_body(_v4_scope, /, kind, previous):
    if previous and _v4_global(_v4_scope, 'isinstance')(previous.get("target_owner"), _v4_global(_v4_scope, 'str')):
        return _v4_global(_v4_scope, 'str')(previous["target_owner"])
    try:
        return {
            "cli_script": "ops",
            "windows_task": "ops",
            "html_page": "apps/web",
            "python_entry_candidate": "apps/api",
        }[kind]
    except _v4_global(_v4_scope, 'KeyError') as error:
        raise _v4_global(_v4_scope, 'GraphBaselineError')(f"unknown entrypoint kind: {kind}") from error


def __evidence_body(_v4_scope, /, value):
    output: list[dict[str, Any]] = []
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        if _v4_global(_v4_scope, 'isinstance')(value.get("path"), _v4_global(_v4_scope, 'str')):
            item: dict[str, Any] = {
                "path": _v4_global(_v4_scope, '_relative_path')(value["path"], context="source evidence")
            }
            if _v4_global(_v4_scope, 'isinstance')(value.get("line"), _v4_global(_v4_scope, 'int')) and value["line"] > 0:
                item["line"] = value["line"]
            output.append(item)
        for nested in value.values():
            output.extend(_v4_global(_v4_scope, '_evidence')(nested))
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        for nested in value:
            output.extend(_v4_global(_v4_scope, '_evidence')(nested))
    unique = {(row["path"], row.get("line")): row for row in output}
    return [unique[key] for key in _v4_global(_v4_scope, 'sorted')(unique)]


def __graph_index_body(_v4_scope, /, runtime_graph):
    graph = runtime_graph.get("graph")
    if not _v4_global(_v4_scope, 'isinstance')(graph, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(graph.get("nodes"), _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("runtime graph nodes are missing")
    node_ids: set[str] = _v4_global(_v4_scope, 'set')()
    by_path: dict[str, list[str]] = {}
    for node in graph["nodes"]:
        if not _v4_global(_v4_scope, 'isinstance')(node, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(node.get("id"), _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid runtime graph node")
        node_id = _v4_global(_v4_scope, 'str')(node["id"])
        if node_id in node_ids:
            raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate runtime graph node")
        node_ids.add(node_id)
        path = node.get("path")
        if _v4_global(_v4_scope, 'isinstance')(path, _v4_global(_v4_scope, 'str')):
            if node.get("kind") in {"api_route", "frontend_api_ref"}:
                route = _v4_global(_v4_scope, 'PurePosixPath')(path)
                if (
                    not path.startswith("/")
                    or "\\" in path
                    or _v4_global(_v4_scope, 'any')(part in {".", ".."} for part in route.parts)
                ):
                    raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid runtime API path")
                continue
            normalized = _v4_global(_v4_scope, '_relative_path')(path, context="runtime graph node")
            by_path.setdefault(normalized, []).append(node_id)
    return node_ids, {key: _v4_global(_v4_scope, 'sorted')(values) for key, values in _v4_global(_v4_scope, 'sorted')(by_path.items())}


def __validate_graph_inputs_body(_v4_scope, /, atlas_path, runtime_graph_path, inventory_v1_path):
    validation = _v4_global(_v4_scope, '_load_json')(atlas_path / "validation.json")
    if not _v4_global(_v4_scope, 'isinstance')(validation, _v4_global(_v4_scope, 'Mapping')) or validation.get("status") != "PASS":
        raise _v4_global(_v4_scope, 'GraphBaselineError')("static Atlas PASS status is required")
    if not _v4_global(_v4_scope, '_is_sha256')(validation.get("semantic_hash")):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid Atlas semantic hash")
    runtime_graph = _v4_global(_v4_scope, '_load_json')(runtime_graph_path)
    if (
        not _v4_global(_v4_scope, 'isinstance')(runtime_graph, _v4_global(_v4_scope, 'Mapping'))
        or runtime_graph.get("schema_version") != _v4_global(_v4_scope, 'RUNTIME_GRAPH_SCHEMA')
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unsupported runtime graph schema")
    counts = runtime_graph.get("counts")
    if not _v4_global(_v4_scope, 'isinstance')(counts, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("runtime graph counts are missing")
    if counts.get("python_parse_errors") != 0:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("runtime graph has parse errors")
    _v4_global(_v4_scope, '_graph_index')(runtime_graph)
    inventory_v1 = _v4_global(_v4_scope, '_load_json')(inventory_v1_path)
    if (
        not _v4_global(_v4_scope, 'isinstance')(inventory_v1, _v4_global(_v4_scope, 'Mapping'))
        or inventory_v1.get("schema_version") != "v3_5.replacement_inventory.v1"
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unsupported inventory v1 schema")
    return _v4_global(_v4_scope, 'dict')(validation), _v4_global(_v4_scope, 'dict')(runtime_graph), _v4_global(_v4_scope, 'dict')(inventory_v1)
