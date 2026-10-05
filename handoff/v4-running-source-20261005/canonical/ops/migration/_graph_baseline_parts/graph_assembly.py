"""ops.migration.graph_baseline: graph_assembly (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_graph_bundle_body(_v4_scope, /, *, atlas_path, runtime_graph_path, inventory_v1_path, legacy_root, _input_snapshot, _legacy_root_name):
    """Return a deterministic composite baseline and its initial v2 inventory."""

    state = _prepare_graph_bundle_inputs_phase(
        _v4_scope, atlas_path=atlas_path, runtime_graph_path=runtime_graph_path,
        inventory_v1_path=inventory_v1_path, legacy_root=legacy_root,
        _input_snapshot=_input_snapshot, _legacy_root_name=_legacy_root_name,
    )
    state.update(_reconcile_graph_inventory_phase(_v4_scope, state))
    state.update(_build_graph_inventory_rows_phase(_v4_scope, state))
    state.update(_build_graph_reconciliation_phase(_v4_scope, state))
    state["baseline_without_hash"] = _compose_graph_baseline_phase(_v4_scope, state)
    return _finalize_graph_bundle_phase(_v4_scope, state)


def _prepare_graph_bundle_inputs_phase(_v4_scope, /, *, atlas_path, runtime_graph_path, inventory_v1_path, legacy_root, _input_snapshot, _legacy_root_name):
    atlas_path = _v4_global(_v4_scope, 'Path')(atlas_path)
    runtime_graph_path = _v4_global(_v4_scope, 'Path')(runtime_graph_path)
    inventory_v1_path = _v4_global(_v4_scope, 'Path')(inventory_v1_path)
    legacy_root = _v4_global(_v4_scope, 'Path')(legacy_root)
    validation, runtime_graph, inventory_v1 = _v4_global(_v4_scope, '_validate_graph_inputs')(
        atlas_path, runtime_graph_path, inventory_v1_path
    )
    node_ids, graph_ids_by_path = _v4_global(_v4_scope, '_graph_index')(runtime_graph)
    atlas_sources = [
        row
        for row in _v4_global(_v4_scope, '_load_jsonl')(atlas_path / "files.jsonl")
        if row.get("scan_mode", "included") == "included"
    ]
    atlas_entrypoints = _v4_global(_v4_scope, '_load_json')(atlas_path / "entrypoints.json")
    if not _v4_global(_v4_scope, 'isinstance')(atlas_entrypoints, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("Atlas entrypoints must be an array")
    atlas_sources_by_id = {_v4_global(_v4_scope, 'str')(row["id"]): row for row in atlas_sources}
    atlas_entrypoints_by_id = {_v4_global(_v4_scope, 'str')(row["id"]): row for row in atlas_entrypoints}
    if _v4_global(_v4_scope, 'len')(atlas_sources_by_id) != _v4_global(_v4_scope, 'len')(atlas_sources):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate Atlas source identity")
    if _v4_global(_v4_scope, 'len')(atlas_entrypoints_by_id) != _v4_global(_v4_scope, 'len')(atlas_entrypoints):
        raise _v4_global(_v4_scope, 'GraphBaselineError')("duplicate Atlas entrypoint identity")
    previous_sources = {
        _v4_global(_v4_scope, 'str')(row["atlas_file_id"]): row for row in inventory_v1.get("sources", [])
    }
    previous_entrypoints = {
        _v4_global(_v4_scope, 'str')(row["atlas_entrypoint_id"]): row
        for row in inventory_v1.get("entrypoints", [])
    }
    return {
        "atlas_path": atlas_path,
        "runtime_graph_path": runtime_graph_path,
        "inventory_v1_path": inventory_v1_path,
        "legacy_root": legacy_root,
        "_input_snapshot": _input_snapshot,
        "_legacy_root_name": _legacy_root_name,
        "validation": validation,
        "runtime_graph": runtime_graph,
        "inventory_v1": inventory_v1,
        "node_ids": node_ids,
        "graph_ids_by_path": graph_ids_by_path,
        "atlas_sources": atlas_sources,
        "atlas_entrypoints": atlas_entrypoints,
        "atlas_sources_by_id": atlas_sources_by_id,
        "atlas_entrypoints_by_id": atlas_entrypoints_by_id,
        "previous_sources": previous_sources,
        "previous_entrypoints": previous_entrypoints,
    }


def _reconcile_graph_inventory_phase(_v4_scope, /, state):
    atlas_sources_by_id, previous_sources, atlas_entrypoints_by_id, previous_entrypoints, legacy_root = (
        state['atlas_sources_by_id'],
        state['previous_sources'],
        state['atlas_entrypoints_by_id'],
        state['previous_entrypoints'],
        state['legacy_root'],
    )
    atlas_only_sources, v1_only_sources, unexplained_sources = _v4_global(_v4_scope, '_difference_rows')(
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
    for identity in _v4_global(_v4_scope, 'sorted')(atlas_entrypoints_by_id.keys() - previous_entrypoints.keys()):
        row = atlas_entrypoints_by_id[identity]
        atlas_only_entrypoints.append(
            {
                "atlas_entrypoint_id": identity,
                "path": _v4_global(_v4_scope, '_entrypoint_path')(row),
                "reason": "ADDED_AFTER_ORPHANED_INVENTORY",
            }
        )
    for identity in _v4_global(_v4_scope, 'sorted')(previous_entrypoints.keys() - atlas_entrypoints_by_id.keys()):
        evidence = previous_entrypoints[identity].get("source_evidence", [])
        path = _v4_global(_v4_scope, 'str')(evidence[0].get("path")) if evidence else ""
        if not path:
            unexplained_entrypoints.append(f"MISSING_ENTRYPOINT_PATH:{identity}")
            continue
        v1_only_entrypoints.append(
            {
                "atlas_entrypoint_id": identity,
                "path": path,
                "reason": (
                    "REMOVED_FROM_CURRENT_ATLAS_BUT_PRESENT_ON_DISK"
                    if _v4_global(_v4_scope, '_legacy_file')(legacy_root, path).is_file()
                    else "REMOVED_FROM_CURRENT_ATLAS_AND_DISK"
                ),
            }
        )
    for identity in _v4_global(_v4_scope, 'sorted')(atlas_entrypoints_by_id.keys() & previous_entrypoints.keys()):
        atlas_path_value = _v4_global(_v4_scope, '_entrypoint_path')(atlas_entrypoints_by_id[identity])
        evidence = previous_entrypoints[identity].get("source_evidence", [])
        previous_path_value = _v4_global(_v4_scope, 'str')(evidence[0].get("path")) if evidence else ""
        if not previous_path_value:
            unexplained_entrypoints.append(f"MISSING_ENTRYPOINT_PATH:{identity}")
        elif atlas_path_value != previous_path_value:
            unexplained_entrypoints.append(
                "IDENTITY_PATH_MISMATCH:"
                f"{identity}:{atlas_path_value}:{previous_path_value}"
            )
    return {
        "atlas_only_sources": atlas_only_sources,
        "v1_only_sources": v1_only_sources,
        "unexplained_sources": unexplained_sources,
        "atlas_only_entrypoints": atlas_only_entrypoints,
        "v1_only_entrypoints": v1_only_entrypoints,
        "unexplained_entrypoints": unexplained_entrypoints,
    }


def _build_graph_inventory_rows_phase(_v4_scope, /, state):
    atlas_sources, atlas_entrypoints, inventory_v1, graph_ids_by_path, legacy_root, node_ids, previous_sources, previous_entrypoints = (
        state['atlas_sources'],
        state['atlas_entrypoints'],
        state['inventory_v1'],
        state['graph_ids_by_path'],
        state['legacy_root'],
        state['node_ids'],
        state['previous_sources'],
        state['previous_entrypoints'],
    )
    source_rows: list[dict[str, Any]] = []
    for source in _v4_global(_v4_scope, 'sorted')(atlas_sources, key=lambda row: _v4_global(_v4_scope, 'str')(row["id"])):
        identity = _v4_global(_v4_scope, 'str')(source["id"])
        path = _v4_global(_v4_scope, '_relative_path')(source["path"], context="Atlas source")
        target = _v4_global(_v4_scope, '_legacy_file')(legacy_root, path)
        current_sha = _v4_global(_v4_scope, '_digest_file')(target) if target.is_file() else None
        atlas_sha = source.get("sha256")
        if not _v4_global(_v4_scope, '_is_sha256')(atlas_sha):
            raise _v4_global(_v4_scope, 'GraphBaselineError')(f"invalid Atlas source SHA: {identity}")
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
                "language": _v4_global(_v4_scope, 'str')(source.get("language") or "unknown"),
                "layer": _v4_global(_v4_scope, '_source_layer')(path, previous),
                "authority": _v4_global(_v4_scope, 'str')(source.get("authority") or "CANNOT_CONFIRM"),
                "atlas_sha256": atlas_sha,
                "sha256": current_sha,
                "source_state": state,
                "graph_node_ids": [f"atlas:{identity}", *graph_ids_by_path.get(path, [])],
                "target_owner": _v4_global(_v4_scope, '_source_owner')(source, previous),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
        )

    entrypoint_rows: list[dict[str, Any]] = []
    for entrypoint in _v4_global(_v4_scope, 'sorted')(atlas_entrypoints, key=lambda row: _v4_global(_v4_scope, 'str')(row["id"])):
        identity = _v4_global(_v4_scope, 'str')(entrypoint["id"])
        path = _v4_global(_v4_scope, '_entrypoint_path')(entrypoint)
        previous = previous_entrypoints.get(identity)
        source_evidence = _v4_global(_v4_scope, '_evidence')(entrypoint.get("evidence", {}))
        if not source_evidence:
            source_evidence = [{"path": path, "line": 1}]
        graph_node_ids = [f"atlas:{identity}", *graph_ids_by_path.get(path, [])]
        if entrypoint.get("kind") == "windows_task" and _v4_global(_v4_scope, 'isinstance')(
            entrypoint.get("name"), _v4_global(_v4_scope, 'str')
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
                "kind": _v4_global(_v4_scope, 'str')(entrypoint["kind"]),
                "name": entrypoint.get("name"),
                "source_evidence": source_evidence,
                "source_status": _v4_global(_v4_scope, 'str')(entrypoint.get("status") or "CANNOT_CONFIRM"),
                "graph_node_ids": _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(graph_node_ids)),
                "target_owner": _v4_global(_v4_scope, '_entrypoint_owner')(_v4_global(_v4_scope, 'str')(entrypoint["kind"]), previous),
                "disposition": "REWRITE",
                "status": "PENDING",
                "replacement_evidence": [],
            }
        )

    runtime_rows: list[dict[str, Any]] = []
    feature_graph_ids: dict[str, set[str]] = {}
    for previous in inventory_v1.get("runtime_tasks", []):
        row = _v4_global(_v4_scope, 'deepcopy')(previous)
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
        row["graph_node_ids"] = _v4_global(_v4_scope, 'sorted')(candidate for candidate in candidates if candidate in node_ids)
        for feature_id in row.get("feature_ids", []):
            feature_graph_ids.setdefault(_v4_global(_v4_scope, 'str')(feature_id), _v4_global(_v4_scope, 'set')()).update(row["graph_node_ids"])
        runtime_rows.append(row)

    feature_rows: list[dict[str, Any]] = []
    for previous in inventory_v1.get("features", []):
        row = _v4_global(_v4_scope, 'deepcopy')(previous)
        row["disposition"] = "REWRITE"
        row["status"] = "PENDING"
        row["replacement_evidence"] = []
        feature_id = _v4_global(_v4_scope, 'str')(row["feature_id"])
        row["graph_node_ids"] = _v4_global(_v4_scope, 'sorted')(feature_graph_ids.get(feature_id, _v4_global(_v4_scope, 'set')()))
        gaps = {_v4_global(_v4_scope, 'str')(value) for value in row.get("source_gaps", [])}
        if not row["graph_node_ids"]:
            gaps.add("GRAPH_NODE_NOT_RECONCILED")
        gaps.add("ORIGINAL_ATLAS_038_NOT_PRESENT")
        row["source_gaps"] = _v4_global(_v4_scope, 'sorted')(gaps)
        feature_rows.append(row)
    return {
        "source_rows": source_rows,
        "entrypoint_rows": entrypoint_rows,
        "runtime_rows": runtime_rows,
        "feature_rows": feature_rows,
    }


def _build_graph_reconciliation_phase(_v4_scope, /, state):
    source_rows, entrypoint_rows, runtime_rows, feature_rows, atlas_only_sources, v1_only_sources, unexplained_sources, atlas_only_entrypoints, v1_only_entrypoints, unexplained_entrypoints, atlas_sources_by_id, atlas_entrypoints_by_id, node_ids, runtime_graph = (
        state['source_rows'],
        state['entrypoint_rows'],
        state['runtime_rows'],
        state['feature_rows'],
        state['atlas_only_sources'],
        state['v1_only_sources'],
        state['unexplained_sources'],
        state['atlas_only_entrypoints'],
        state['v1_only_entrypoints'],
        state['unexplained_entrypoints'],
        state['atlas_sources_by_id'],
        state['atlas_entrypoints_by_id'],
        state['node_ids'],
        state['runtime_graph'],
    )
    counts = {
        "sources": _v4_global(_v4_scope, 'len')(source_rows),
        "entrypoints": _v4_global(_v4_scope, 'len')(entrypoint_rows),
        "runtime_tasks": _v4_global(_v4_scope, 'len')(runtime_rows),
        "features": _v4_global(_v4_scope, 'len')(feature_rows),
    }
    reconciliation = {
        "atlas_only_sources": atlas_only_sources,
        "inventory_v1_only_sources": v1_only_sources,
        "atlas_only_entrypoints": atlas_only_entrypoints,
        "inventory_v1_only_entrypoints": v1_only_entrypoints,
        "unexplained_differences": _v4_global(_v4_scope, 'sorted')(
            [*unexplained_sources, *unexplained_entrypoints]
        ),
    }
    atlas_node_ids = {
        *(f"atlas:{identity}" for identity in atlas_sources_by_id),
        *(f"atlas:{identity}" for identity in atlas_entrypoints_by_id),
    }
    registered_graph_node_ids = _v4_global(_v4_scope, 'sorted')(atlas_node_ids | node_ids)
    runtime_has_findings = (
        runtime_graph.get("status") != "PASS"
        or _v4_global(_v4_scope, 'bool')(runtime_graph.get("findings", []))
    )
    return {
        "counts": counts,
        "reconciliation": reconciliation,
        "atlas_node_ids": atlas_node_ids,
        "registered_graph_node_ids": registered_graph_node_ids,
        "runtime_has_findings": runtime_has_findings,
    }


def _compose_graph_baseline_phase(_v4_scope, /, state):
    atlas_path, runtime_graph_path, inventory_v1_path, legacy_root, _input_snapshot, _legacy_root_name, validation, runtime_graph, inventory_v1, source_rows, entrypoint_rows, atlas_node_ids, registered_graph_node_ids, runtime_has_findings, counts, reconciliation, node_ids = (
        state['atlas_path'],
        state['runtime_graph_path'],
        state['inventory_v1_path'],
        state['legacy_root'],
        state['_input_snapshot'],
        state['_legacy_root_name'],
        state['validation'],
        state['runtime_graph'],
        state['inventory_v1'],
        state['source_rows'],
        state['entrypoint_rows'],
        state['atlas_node_ids'],
        state['registered_graph_node_ids'],
        state['runtime_has_findings'],
        state['counts'],
        state['reconciliation'],
        state['node_ids'],
    )
    baseline_without_hash: dict[str, Any] = {
        "schema_version": _v4_global(_v4_scope, 'BASELINE_SCHEMA'),
        "status": (
            _v4_global(_v4_scope, '_STATIC_PASS_WITH_RUNTIME_GAPS')
            if not reconciliation["unexplained_differences"] and runtime_has_findings
            else _v4_global(_v4_scope, '_STATIC_PASS')
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
                "file_count": _v4_global(_v4_scope, 'len')(_input_snapshot["files"]),
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
                "sources": _v4_global(_v4_scope, 'len')(source_rows),
                "entrypoints": _v4_global(_v4_scope, 'len')(entrypoint_rows),
                "parse_failures": _v4_global(_v4_scope, 'int')(
                    validation.get("counts", {}).get("parse_gaps", 0)
                ),
            },
            "artifact_sha256": {
                name: _v4_global(_v4_scope, '_digest_file')(atlas_path / name)
                for name in ("validation.json", "files.jsonl", "entrypoints.json")
            },
        },
        "runtime_graph": {
            "snapshot_id": runtime_graph_path.stem,
            "generated_at": runtime_graph.get("generated_at"),
            "status": runtime_graph.get("status"),
            "sha256": _v4_global(_v4_scope, '_digest_file')(runtime_graph_path),
            "counts": _v4_global(_v4_scope, 'deepcopy')(runtime_graph.get("counts", {})),
            "finding_count": _v4_global(_v4_scope, 'len')(runtime_graph.get("findings", [])),
        },
        "inventory_v1": {
            "semantic_hash": inventory_v1.get("atlas", {}).get("semantic_hash"),
            "sha256": _v4_global(_v4_scope, '_digest_file')(inventory_v1_path),
            "counts": {
                group: _v4_global(_v4_scope, 'len')(inventory_v1.get(group, [])) for group in _v4_global(_v4_scope, '_GROUPS')
            },
            "source_status": "HISTORICAL_ORPHANED_ATLAS",
        },
        "current_source_snapshot": {
            "aggregate_sha256": _v4_global(_v4_scope, '_digest_bytes')(
                _v4_global(_v4_scope, '_canonical_bytes')(
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
            "state_counts": _v4_global(_v4_scope, 'dict')(
                _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'Counter')(row["source_state"] for row in source_rows).items())
            ),
        },
        "graph_node_registry": {
            "ids": registered_graph_node_ids,
            "sha256": _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(registered_graph_node_ids)),
            "counts": {
                "atlas": _v4_global(_v4_scope, 'len')(atlas_node_ids),
                "runtime": _v4_global(_v4_scope, 'len')(node_ids),
                "total": _v4_global(_v4_scope, 'len')(registered_graph_node_ids),
            },
        },
        "inventory_v2_counts": counts,
        "reconciliation": reconciliation,
        "acceptance": {
            "scope": _v4_global(_v4_scope, '_STATIC_ACCEPTANCE_SCOPE'),
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
    return baseline_without_hash


def _finalize_graph_bundle_phase(_v4_scope, /, state):
    baseline_without_hash, counts, source_rows, entrypoint_rows, runtime_rows, feature_rows = (
        state['baseline_without_hash'],
        state['counts'],
        state['source_rows'],
        state['entrypoint_rows'],
        state['runtime_rows'],
        state['feature_rows'],
    )
    baseline = {
        **baseline_without_hash,
        "semantic_hash": _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(baseline_without_hash)),
    }
    inventory_without_hash = {
        "schema_version": _v4_global(_v4_scope, 'INVENTORY_SCHEMA'),
        "graph_baseline_semantic_hash": baseline["semantic_hash"],
        "counts": counts,
        "sources": source_rows,
        "entrypoints": entrypoint_rows,
        "runtime_tasks": _v4_global(_v4_scope, 'sorted')(
            runtime_rows,
            key=lambda row: (_v4_global(_v4_scope, 'str')(row.get("record_type")), _v4_global(_v4_scope, 'str')(row.get("task_name"))),
        ),
        "features": _v4_global(_v4_scope, 'sorted')(feature_rows, key=lambda row: _v4_global(_v4_scope, 'str')(row.get("feature_id"))),
        "safety": _v4_global(_v4_scope, 'deepcopy')(baseline["safety"]),
    }
    inventory = {
        **inventory_without_hash,
        "inventory_semantic_hash": _v4_global(_v4_scope, '_digest_bytes')(_v4_global(_v4_scope, '_canonical_bytes')(inventory_without_hash)),
    }
    _v4_global(_v4_scope, 'validate_graph_baseline')(baseline)
    _v4_global(_v4_scope, 'validate_inventory_v2')(inventory, baseline=baseline)
    return baseline, inventory



def _build_graph_bundle_from_snapshot_body(_v4_scope, /, snapshot_root):
    """Rebuild a bundle only after every preserved input byte is revalidated."""

    snapshot_root = _v4_global(_v4_scope, 'Path')(snapshot_root)
    manifest = _v4_global(_v4_scope, '_validate_input_snapshot')(snapshot_root)
    atlas_relative = _v4_global(_v4_scope, '_relative_path')(
        manifest.get("atlas_relative_dir"), context="snapshot Atlas directory"
    )
    runtime_relative = _v4_global(_v4_scope, '_relative_path')(
        manifest.get("runtime_graph_relative_path"),
        context="snapshot runtime graph",
    )
    inventory_relative = _v4_global(_v4_scope, '_relative_path')(
        manifest.get("inventory_v1_relative_path"),
        context="snapshot inventory v1",
    )
    legacy_relative = _v4_global(_v4_scope, '_relative_path')(
        manifest.get("legacy_sources_relative_dir"),
        context="snapshot legacy sources",
    )
    legacy_root_name = manifest.get("legacy_root_name")
    if not _v4_global(_v4_scope, 'isinstance')(legacy_root_name, _v4_global(_v4_scope, 'str')) or not legacy_root_name:
        raise _v4_global(_v4_scope, 'GraphBaselineError')("invalid snapshot legacy root name")
    return _v4_global(_v4_scope, 'build_graph_bundle')(
        atlas_path=_v4_global(_v4_scope, '_snapshot_file')(snapshot_root, atlas_relative),
        runtime_graph_path=_v4_global(_v4_scope, '_snapshot_file')(snapshot_root, runtime_relative),
        inventory_v1_path=_v4_global(_v4_scope, '_snapshot_file')(snapshot_root, inventory_relative),
        legacy_root=_v4_global(_v4_scope, '_snapshot_file')(snapshot_root, legacy_relative),
        _input_snapshot=manifest,
        _legacy_root_name=legacy_root_name,
    )
