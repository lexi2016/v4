"""ops.migration.graph_baseline: graph_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_graph_baseline_body(_v4_scope, /, baseline):
    _validate_graph_baseline_header_phase(_v4_scope, baseline)
    _validate_graph_baseline_input_snapshot_phase(_v4_scope, baseline)
    inventory_v2_counts, static_counts, runtime_graph = _validate_graph_baseline_static_inventory_phase(_v4_scope, baseline)
    _validate_graph_baseline_snapshot_registry_safety_phase(
        _v4_scope, baseline, inventory_v2_counts, static_counts, runtime_graph
    )


def _validate_graph_baseline_header_phase(_v4_scope, /, baseline):
    if not _v4_global(_v4_scope, 'isinstance')(baseline, _v4_global(_v4_scope, 'Mapping')) or baseline.get("schema_version") != _v4_global(_v4_scope, 'BASELINE_SCHEMA'):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unknown graph baseline schema")
    semantic_hash = baseline.get("semantic_hash")
    if not _v4_global(_v4_scope, '_is_sha256')(semantic_hash):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid graph baseline semantic hash")
    unhashed = {key: _v4_global(_v4_scope, 'deepcopy')(value) for key, value in baseline.items() if key != "semantic_hash"}
    if _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(unhashed)) != semantic_hash:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("graph baseline semantic hash mismatch")
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
    missing_sections = _v4_global(_v4_scope, 'sorted')(required_sections - baseline.keys())
    if missing_sections:
        raise _v4_global(_v4_scope, 'GraphBaselineError')(
            f"graph baseline missing required section: {missing_sections[0]}"
        )
    if not _v4_global(_v4_scope, 'isinstance')(baseline.get("legacy_root_name"), _v4_global(_v4_scope, 'str')) or not baseline[
        "legacy_root_name"
    ]:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid legacy_root_name")


def _validate_graph_baseline_input_snapshot_phase(_v4_scope, /, baseline):
    input_snapshot = baseline.get("input_snapshot")
    if (
        not _v4_global(_v4_scope, 'isinstance')(input_snapshot, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(input_snapshot)
        != {"mode", "reproducible", "snapshot_id", "semantic_hash", "file_count"}
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid input_snapshot section")
    if input_snapshot.get("mode") == "FROZEN_RAW_BYTES":
        if (
            input_snapshot.get("reproducible") is not True
            or not _v4_global(_v4_scope, 'isinstance')(input_snapshot.get("snapshot_id"), _v4_global(_v4_scope, 'str'))
            or not input_snapshot["snapshot_id"]
            or not _v4_global(_v4_scope, '_is_sha256')(input_snapshot.get("semantic_hash"))
            or not _v4_global(_v4_scope, 'isinstance')(input_snapshot.get("file_count"), _v4_global(_v4_scope, 'int'))
            or input_snapshot["file_count"] <= 0
        ):
            raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid frozen input_snapshot section")
    elif input_snapshot != {
        "mode": "LIVE_READ_NOT_PRESERVED",
        "reproducible": False,
        "snapshot_id": None,
        "semantic_hash": None,
        "file_count": 0,
    }:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid live input_snapshot section")


def _validate_graph_baseline_static_inventory_phase(_v4_scope, /, baseline):
    static_atlas = baseline.get("static_atlas")
    static_counts = static_atlas.get("counts") if _v4_global(_v4_scope, 'isinstance')(static_atlas, _v4_global(_v4_scope, 'Mapping')) else None
    static_artifacts = (
        static_atlas.get("artifact_sha256")
        if _v4_global(_v4_scope, 'isinstance')(static_atlas, _v4_global(_v4_scope, 'Mapping'))
        else None
    )
    if (
        not _v4_global(_v4_scope, 'isinstance')(static_atlas, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(static_atlas)
        != {
            "snapshot_id",
            "semantic_hash",
            "validation_status",
            "counts",
            "artifact_sha256",
        }
        or not _v4_global(_v4_scope, 'isinstance')(static_atlas.get("snapshot_id"), _v4_global(_v4_scope, 'str'))
        or not static_atlas["snapshot_id"]
        or not _v4_global(_v4_scope, '_is_sha256')(static_atlas.get("semantic_hash"))
        or static_atlas.get("validation_status") != "PASS"
        or not _v4_global(_v4_scope, 'isinstance')(static_counts, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(static_counts) != {"sources", "entrypoints", "parse_failures"}
        or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0 for value in static_counts.values())
        or static_counts["parse_failures"] != 0
        or not _v4_global(_v4_scope, 'isinstance')(static_artifacts, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(static_artifacts)
        != {"validation.json", "files.jsonl", "entrypoints.json"}
        or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, '_is_sha256')(value) for value in static_artifacts.values())
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid static_atlas section")
    runtime_graph = baseline.get("runtime_graph")
    if (
        not _v4_global(_v4_scope, 'isinstance')(runtime_graph, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(runtime_graph)
        != {"snapshot_id", "generated_at", "status", "sha256", "counts", "finding_count"}
        or not _v4_global(_v4_scope, 'isinstance')(runtime_graph.get("snapshot_id"), _v4_global(_v4_scope, 'str'))
        or not runtime_graph["snapshot_id"]
        or not _v4_global(_v4_scope, 'isinstance')(runtime_graph.get("generated_at"), _v4_global(_v4_scope, 'str'))
        or not runtime_graph["generated_at"]
        or not _v4_global(_v4_scope, 'isinstance')(runtime_graph.get("status"), _v4_global(_v4_scope, 'str'))
        or not runtime_graph["status"]
        or not _v4_global(_v4_scope, '_is_sha256')(runtime_graph.get("sha256"))
        or not _v4_global(_v4_scope, 'isinstance')(runtime_graph.get("counts"), _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'type')(runtime_graph["counts"].get("python_parse_errors")) is not _v4_global(_v4_scope, 'int')
        or runtime_graph["counts"]["python_parse_errors"] != 0
        or _v4_global(_v4_scope, 'type')(runtime_graph["counts"].get("findings")) is not _v4_global(_v4_scope, 'int')
        or runtime_graph["counts"]["findings"] < 0
        or _v4_global(_v4_scope, 'type')(runtime_graph["counts"].get("graph_nodes")) is not _v4_global(_v4_scope, 'int')
        or runtime_graph["counts"]["graph_nodes"] < 0
        or _v4_global(_v4_scope, 'type')(runtime_graph.get("finding_count")) is not _v4_global(_v4_scope, 'int')
        or runtime_graph["finding_count"] < 0
        or runtime_graph["counts"]["findings"] != runtime_graph["finding_count"]
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid runtime_graph section")
    inventory_v1 = baseline.get("inventory_v1")
    previous_counts = (
        inventory_v1.get("counts") if _v4_global(_v4_scope, 'isinstance')(inventory_v1, _v4_global(_v4_scope, 'Mapping')) else None
    )
    if (
        not _v4_global(_v4_scope, 'isinstance')(inventory_v1, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(inventory_v1)
        != {"semantic_hash", "sha256", "counts", "source_status"}
        or not _v4_global(_v4_scope, '_is_sha256')(inventory_v1.get("semantic_hash"))
        or not _v4_global(_v4_scope, '_is_sha256')(inventory_v1.get("sha256"))
        or inventory_v1.get("source_status") != "HISTORICAL_ORPHANED_ATLAS"
        or not _v4_global(_v4_scope, 'isinstance')(previous_counts, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(previous_counts) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_GROUPS'))
        or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0 for value in previous_counts.values())
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid inventory_v1 section")
    inventory_v2_counts = baseline.get("inventory_v2_counts")
    if (
        not _v4_global(_v4_scope, 'isinstance')(inventory_v2_counts, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(inventory_v2_counts) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_GROUPS'))
        or _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0
            for value in inventory_v2_counts.values()
        )
        or inventory_v2_counts["sources"] != static_counts["sources"]
        or inventory_v2_counts["entrypoints"] != static_counts["entrypoints"]
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid inventory_v2_counts section")
    return inventory_v2_counts, static_counts, runtime_graph


def _validate_graph_baseline_snapshot_registry_safety_phase(_v4_scope, /, baseline, inventory_v2_counts, static_counts, runtime_graph):
    current_source_snapshot = baseline.get("current_source_snapshot")
    state_counts = (
        current_source_snapshot.get("state_counts")
        if _v4_global(_v4_scope, 'isinstance')(current_source_snapshot, _v4_global(_v4_scope, 'Mapping'))
        else None
    )
    if (
        not _v4_global(_v4_scope, 'isinstance')(current_source_snapshot, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(current_source_snapshot) != {"aggregate_sha256", "state_counts"}
        or not _v4_global(_v4_scope, '_is_sha256')(current_source_snapshot.get("aggregate_sha256"))
        or not _v4_global(_v4_scope, 'isinstance')(state_counts, _v4_global(_v4_scope, 'Mapping'))
        or not _v4_global(_v4_scope, 'set')(state_counts).issubset(_v4_global(_v4_scope, '_SOURCE_STATES'))
        or _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0 for value in state_counts.values())
        or _v4_global(_v4_scope, 'sum')(state_counts.values()) != inventory_v2_counts["sources"]
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid current_source_snapshot section")
    registry = baseline.get("graph_node_registry")
    registered_ids = registry.get("ids") if _v4_global(_v4_scope, 'isinstance')(registry, _v4_global(_v4_scope, 'Mapping')) else None
    if (
        not _v4_global(_v4_scope, 'isinstance')(registered_ids, _v4_global(_v4_scope, 'list'))
        or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value for value in registered_ids)
        or registered_ids != _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(registered_ids))
        or not _v4_global(_v4_scope, '_is_sha256')(registry.get("sha256"))
        or registry["sha256"] != _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(registered_ids))
        or not _v4_global(_v4_scope, 'isinstance')(registry.get("counts"), _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(registry["counts"]) != {"atlas", "runtime", "total"}
        or _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0
            for value in registry["counts"].values()
        )
        or registry["counts"]["atlas"]
        != static_counts["sources"] + static_counts["entrypoints"]
        or registry["counts"]["runtime"] != runtime_graph["counts"]["graph_nodes"]
        or registry["counts"]["total"]
        != registry["counts"]["atlas"] + registry["counts"]["runtime"]
        or registry["counts"]["total"] != _v4_global(_v4_scope, 'len')(registered_ids)
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid graph_node_registry section")
    reconciliation = baseline.get("reconciliation")
    if (
        not _v4_global(_v4_scope, 'isinstance')(reconciliation, _v4_global(_v4_scope, 'Mapping'))
        or _v4_global(_v4_scope, 'set')(reconciliation)
        != {
            "atlas_only_sources",
            "inventory_v1_only_sources",
            "atlas_only_entrypoints",
            "inventory_v1_only_entrypoints",
            "unexplained_differences",
        }
        or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(reconciliation[name], _v4_global(_v4_scope, 'list')) for name in reconciliation)
    ):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid graph reconciliation")
    if reconciliation["unexplained_differences"]:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("graph baseline has unexplained differences")
    expected_status = (
        _v4_global(_v4_scope, '_STATIC_PASS_WITH_RUNTIME_GAPS')
        if runtime_graph["status"] != "PASS" or runtime_graph["finding_count"]
        else _v4_global(_v4_scope, '_STATIC_PASS')
    )
    if baseline.get("status") != expected_status:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("graph baseline did not pass")
    acceptance = baseline.get("acceptance")
    if acceptance != {
        "scope": _v4_global(_v4_scope, '_STATIC_ACCEPTANCE_SCOPE'),
        "static_reconciliation_accepted": True,
        "runtime_accepted": False,
        "deployment_accepted": False,
    }:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid graph baseline acceptance scope")
    safety = baseline.get("safety")
    if safety != {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("unsafe graph baseline")

