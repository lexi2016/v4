"""Deterministic Phase-5 identity audit over the frozen V3 task graph.

This module deliberately does not invent workload owners or date semantics.  It
only promotes mappings that are provable from a catalog alias or a graph edge;
everything else remains an explicit CANNOT_CONFIRM gap.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from contracts.runtime_tasks import DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog


SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
RUNNER_ARGUMENT_CONTRACTS = {
    "ops.run_hkconnect_0915_0920_capture": [
        "--data-root",
        "{data_root}",
        "--shared-data-root",
        "{shared_data_root}",
        "--shared-package-root",
        "{shared_package_root}",
        "--trade-date",
        "{business_date}",
        "--futu-python",
        "{shared_futu_python}",
    ],
    "ops.run_hourly_research": [
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
        "--target-date",
        "{target_date}",
        "--slot",
        "{slot}",
        "--mode",
        "{mode}",
    ],
    "ops.build_close_review": [
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
    ],
    "ops.materialize_preselection": [
        "--trade-date",
        "{business_date}",
        "--selector",
        "{selector_panel}",
        "--fupan",
        "{fupan_pool}",
        "--stage7",
        "{stage7_pool}",
        "--research-preview",
        "{research_preview}",
        "--hk",
        "{hk_pool}",
        "--wechat-rows",
        "{wechat_rows}",
        "--wechat-manifest",
        "{wechat_manifest}",
    ],
    "ops.materialize_stage_workbench": [
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
        "--stage",
        "{stage_id}",
    ],
    "ops.build_a_share_close_review": [
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
        "--panel-pointer",
        "{panel_pointer}",
    ],
}
RUNTIME_ROLE_FIELDS = (
    "market_scope",
    "session_requirement",
    "scheduled_date_role",
    "signal_date_role",
    "target_date_role",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _semantic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"invalid {context}")
    return value


def _require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"invalid {context}")
    return value


def _load_source(path: Path, context: str) -> tuple[Mapping[str, Any], str, str]:
    try:
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {context}") from error
    mapping = _require_mapping(payload, context)
    return mapping, hashlib.sha256(raw).hexdigest(), _semantic_hash(mapping)


def _runner_module_present(command: Any, repo_root: Path) -> bool:
    if not isinstance(command, list) or len(command) < 3:
        return False
    if command[0:2] != ["python", "-m"] or not isinstance(command[2], str):
        return False
    module_path = Path(*command[2].split(".")).with_suffix(".py")
    return (repo_root / module_path).is_file()


def _runner_command_complete(command: Any, repo_root: Path) -> bool:
    """Fail closed when the catalog declares no argument/date bindings."""

    if not _runner_module_present(command, repo_root) or not isinstance(command, list):
        return False
    expected = RUNNER_ARGUMENT_CONTRACTS.get(str(command[2]))
    return expected is not None and command[3:] == expected


def _task_relationships(
    task_id: str,
    edges: list[Mapping[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    outgoing = [edge for edge in edges if edge.get("source") == task_id]
    timeline_nodes = sorted(
        str(edge["target"]).removeprefix("timeline_node:")
        for edge in outgoing
        if edge.get("kind") == "runs_node"
        and str(edge.get("target", "")).startswith("timeline_node:")
    )
    launchers = sorted(
        str(edge["target"]).removeprefix("file:")
        for edge in outgoing
        if edge.get("kind") == "generated_launcher"
        and str(edge.get("target", "")).startswith("file:")
    )
    actual_tasks = sorted(
        str(edge["target"]).removeprefix("windows_task:")
        for edge in outgoing
        if edge.get("kind") == "matches_actual_task"
        and str(edge.get("target", "")).startswith("windows_task:")
    )
    return timeline_nodes, launchers, actual_tasks


def build_runtime_governance_audit(
    *,
    graph_path: Path,
    inventory_path: Path,
    catalog_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Build a self-hashed, read-only audit without resolving semantic gaps."""

    graph, graph_raw_sha, graph_payload_hash = _load_source(
        Path(graph_path), "task graph"
    )
    inventory, inventory_raw_sha, inventory_payload_hash = _load_source(
        Path(inventory_path), "migration inventory"
    )
    catalog, catalog_raw_sha, catalog_payload_hash = _load_source(
        Path(catalog_path), "runtime catalog"
    )
    validated_catalog = load_workload_catalog(Path(catalog_path))
    if validated_catalog.source_payload != catalog:
        raise ValueError("runtime catalog changed during audit")
    if inventory.get("safety") != SAFETY or catalog.get("safety") != SAFETY:
        raise ValueError("unsafe governance input")
    graph_body = _require_mapping(graph.get("graph"), "task graph body")
    nodes = [
        _require_mapping(node, "task graph node")
        for node in _require_list(graph_body.get("nodes"), "task graph nodes")
    ]
    edges = [
        _require_mapping(edge, "task graph edge")
        for edge in _require_list(graph_body.get("edges"), "task graph edges")
    ]
    task_nodes = sorted(
        (node for node in nodes if node.get("kind") == "timeline_task_spec"),
        key=lambda node: str(node.get("label") or ""),
    )
    timeline_nodes = sorted(
        str(node.get("label") or str(node.get("id", "")).removeprefix("timeline_node:"))
        for node in nodes
        if node.get("kind") == "timeline_node"
    )
    actual_tasks = sorted(
        str(node.get("label") or "")
        for node in nodes
        if node.get("kind") == "windows_task"
    )
    catalog_workloads = [
        _require_mapping(row, "catalog workload")
        for row in _require_list(catalog.get("workloads"), "catalog workloads")
    ]
    task_registrations = [
        _require_mapping(row, "task registration")
        for row in _require_list(
            catalog.get("task_registrations"), "task registrations"
        )
    ]
    workload_by_id = {
        str(row.get("workload_id")): row for row in catalog_workloads
    }
    if len(workload_by_id) != len(catalog_workloads):
        raise ValueError("duplicate catalog workload identity")
    if any(row.get("safety") != SAFETY for row in catalog_workloads):
        raise ValueError("unsafe workload boundary")
    if any(
        row.get("safety") != SAFETY
        or row.get("enabled") is not False
        or row.get("execution_allowed") is not False
        or row.get("status") != "CANNOT_CONFIRM"
        for row in task_registrations
    ):
        raise ValueError("unsafe task registration boundary")
    registration_by_task_id: dict[str, Mapping[str, Any]] = {}
    for row in task_registrations:
        legacy_task_id = row.get("legacy_task_id")
        graph_task_spec_id = row.get("graph_task_spec_id")
        if (
            not isinstance(legacy_task_id, str)
            or graph_task_spec_id != f"task_spec:{legacy_task_id}"
            or legacy_task_id in registration_by_task_id
        ):
            raise ValueError("invalid task registration identity")
        registration_by_task_id[legacy_task_id] = row
    alias_to_workload: dict[str, str] = {}
    aliases_by_workload: dict[str, set[str]] = {}
    for workload_id, row in workload_by_id.items():
        aliases = _require_list(row.get("aliases"), "catalog aliases")
        aliases_by_workload[workload_id] = set()
        for alias in aliases:
            if not isinstance(alias, str) or alias in alias_to_workload:
                raise ValueError("ambiguous catalog alias")
            alias_to_workload[alias] = workload_id
            aliases_by_workload[workload_id].add(alias)

    runner_modules_present = sorted(
        workload_id
        for workload_id, row in workload_by_id.items()
        if _runner_module_present(row.get("command"), Path(repo_root))
    )
    incomplete_runner_commands = sorted(
        workload_id
        for workload_id, row in workload_by_id.items()
        if workload_id in runner_modules_present
        and not _runner_command_complete(row.get("command"), Path(repo_root))
    )
    available_runners = sorted(
        workload_id
        for workload_id, row in workload_by_id.items()
        if _runner_command_complete(row.get("command"), Path(repo_root))
    )
    missing_runners = sorted(set(workload_by_id) - set(available_runners))

    canonical_tasks: list[dict[str, Any]] = []
    task_to_workloads: dict[str, list[str]] = {}
    missing_launcher_tasks: list[str] = []
    for node in task_nodes:
        label = str(node.get("label") or "")
        task_id = str(node.get("id") or "")
        if not label or task_id != f"task_spec:{label}":
            raise ValueError("invalid canonical task identity")
        task_timeline_nodes, launchers, matched_actual = _task_relationships(
            task_id, edges
        )
        if not launchers:
            missing_launcher_tasks.append(label)
        candidate_workloads = sorted(
            workload_id
            for workload_id, aliases in aliases_by_workload.items()
            if label in aliases
            or (
                bool(task_timeline_nodes)
                and set(task_timeline_nodes).issubset(aliases)
            )
        )
        if len(candidate_workloads) == 1:
            workload_id = candidate_workloads[0]
            mapping_status = (
                "EXACT_CATALOG_IDENTITY_RUNNER_AVAILABLE"
                if workload_id in available_runners
                else "EXACT_CATALOG_IDENTITY_RUNNER_MISSING"
            )
        elif not candidate_workloads:
            mapping_status = "CANNOT_CONFIRM_CATALOG_OWNER"
        else:
            mapping_status = "CANNOT_CONFIRM_AMBIGUOUS_CATALOG_OWNER"
        task_to_workloads[label] = candidate_workloads
        registration = registration_by_task_id.get(label)
        if registration is not None:
            if candidate_workloads:
                raise ValueError("task registration overlaps an exact workload")
            if (
                registration.get("timeline_node_ids") != task_timeline_nodes
                or registration.get("legacy_launcher_paths") != launchers
                or registration.get("actual_windows_task_ids") != matched_actual
            ):
                raise ValueError("task registration does not match frozen graph")
        schedule = node.get("schedule")
        canonical_tasks.append(
            {
                "legacy_task_id": label,
                "graph_task_spec_id": task_id,
                "schedule": schedule if isinstance(schedule, Mapping) else {},
                "timeline_node_ids": task_timeline_nodes,
                "legacy_launcher_paths": launchers,
                "actual_windows_task_ids": matched_actual,
                "actual_windows_task_present": label in matched_actual,
                "catalog_workload_ids": candidate_workloads,
                "task_registration_status": (
                    "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
                    if registration is not None
                    else None
                ),
                "mapping_status": mapping_status,
            }
        )

    canonical_task_ids = [row["legacy_task_id"] for row in canonical_tasks]
    extra_actual = sorted(set(actual_tasks) - set(canonical_task_ids))
    missing_actual = sorted(set(canonical_task_ids) - set(actual_tasks))

    inventory_entrypoints = [
        _require_mapping(row, "inventory entrypoint")
        for row in _require_list(inventory.get("entrypoints"), "inventory entrypoints")
    ]
    task_id_set = set(canonical_task_ids)
    entrypoint_rows: list[dict[str, Any]] = []
    for row in sorted(
        inventory_entrypoints,
        key=lambda item: str(item.get("atlas_entrypoint_id") or ""),
    ):
        entrypoint_id = str(row.get("atlas_entrypoint_id") or "")
        related_tasks: set[str] = set()
        name = row.get("name")
        if isinstance(name, str) and name in task_id_set:
            related_tasks.add(name)
        for node_id in _require_list(
            row.get("graph_node_ids"), "entrypoint graph nodes"
        ):
            if isinstance(node_id, str) and node_id.startswith("task_spec:"):
                candidate = node_id.removeprefix("task_spec:")
                if candidate in task_id_set:
                    related_tasks.add(candidate)
        for evidence in _require_list(
            row.get("source_evidence"), "entrypoint source evidence"
        ):
            item = _require_mapping(evidence, "entrypoint source evidence row")
            source_path = item.get("path")
            if isinstance(source_path, str):
                candidate = Path(source_path).stem
                if candidate in task_id_set:
                    related_tasks.add(candidate)
        workload_ids = sorted(
            {
                workload_id
                for task_id in related_tasks
                for workload_id in task_to_workloads[task_id]
            }
        )
        target_owner = row.get("target_owner")
        if not isinstance(target_owner, str) or not target_owner.strip():
            mapping_status = ""
        elif workload_ids:
            mapping_status = "EXACT_CATALOG_IDENTITY"
        elif related_tasks and related_tasks.issubset(registration_by_task_id):
            mapping_status = "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
        elif related_tasks:
            mapping_status = "CANNOT_CONFIRM_CATALOG_OWNER"
        else:
            mapping_status = "NON_SCHEDULED_OWNER_ONLY"
        entrypoint_rows.append(
            {
                "atlas_entrypoint_id": entrypoint_id,
                "kind": row.get("kind"),
                "target_owner": row.get("target_owner"),
                "inventory_disposition": row.get("disposition"),
                "inventory_status": row.get("status"),
                "legacy_task_ids": sorted(related_tasks),
                "catalog_workload_ids": workload_ids,
                "mapping_status": mapping_status,
            }
        )

    inventory_runtime_tasks = _require_list(
        inventory.get("runtime_tasks"), "inventory runtime tasks"
    )
    inventory_timeline_ids = sorted(
        str(row.get("node_id") or "")
        for row in inventory_runtime_tasks
        if isinstance(row, Mapping) and row.get("record_type") == "timeline_node"
    )
    inventory_windows_tasks = sorted(
        str(row.get("task_name") or "")
        for row in inventory_runtime_tasks
        if isinstance(row, Mapping) and row.get("record_type") == "windows_task"
    )
    if inventory_timeline_ids != timeline_nodes:
        raise ValueError("timeline inventory does not match frozen graph")
    if inventory_windows_tasks != canonical_task_ids:
        raise ValueError("Windows task inventory does not match frozen graph")
    counts = _require_mapping(graph.get("counts"), "task graph counts")
    exact_task_count = sum(
        bool(row["catalog_workload_ids"]) for row in canonical_tasks
    )
    unresolved_task_count = len(canonical_tasks) - exact_task_count
    registered_cannot_confirm_task_ids = sorted(registration_by_task_id)
    unresolved_task_ids = {
        row["legacy_task_id"]
        for row in canonical_tasks
        if not row["catalog_workload_ids"]
    }
    if set(registered_cannot_confirm_task_ids) - unresolved_task_ids:
        raise ValueError("task registration is not an unresolved canonical task")
    unregistered_unresolved_task_ids = sorted(
        unresolved_task_ids - set(registered_cannot_confirm_task_ids)
    )
    tasks_missing_explicit_runtime_roles = sorted(
        row["legacy_task_id"]
        for row in canonical_tasks
        if len(row["catalog_workload_ids"]) != 1
        or any(
            not isinstance(
                workload_by_id[row["catalog_workload_ids"][0]].get(field), str
            )
            or not workload_by_id[row["catalog_workload_ids"][0]][field].strip()
            for field in RUNTIME_ROLE_FIELDS
        )
    )
    cross_day_graph_node_ids = sorted(
        str(node.get("label") or str(node.get("id", "")).removeprefix("timeline_node:"))
        for node in nodes
        if node.get("kind") == "timeline_node"
        and isinstance(node.get("node_label"), str)
        and "次日" in node["node_label"]
    )
    cross_day_task_ids = sorted(
        row["legacy_task_id"]
        for row in canonical_tasks
        if set(row["timeline_node_ids"]) & set(cross_day_graph_node_ids)
    )
    cross_day_tasks_without_explicit_target_role = sorted(
        row["legacy_task_id"]
        for row in canonical_tasks
        if row["legacy_task_id"] in cross_day_task_ids
        and (
            len(row["catalog_workload_ids"]) != 1
            or not isinstance(
                workload_by_id[row["catalog_workload_ids"][0]].get(
                    "target_date_role"
                ),
                str,
            )
            or not workload_by_id[row["catalog_workload_ids"][0]][
                "target_date_role"
            ].strip()
        )
    )
    unresolved_entrypoint_ids = [
        row["atlas_entrypoint_id"]
        for row in entrypoint_rows
        if str(row["mapping_status"]).startswith("CANNOT_CONFIRM_")
    ]
    approved_registration_entrypoint_ids = [
        row["atlas_entrypoint_id"]
        for row in entrypoint_rows
        if row["mapping_status"] == "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
    ]
    unexplained_entrypoint_ids = [
        row["atlas_entrypoint_id"]
        for row in entrypoint_rows
        if not row["mapping_status"]
    ]
    artifacts = _require_mapping(graph.get("artifacts"), "task graph artifacts")
    graph_artifact = artifacts.get("json")
    if not isinstance(graph_artifact, str) or not graph_artifact:
        raise ValueError("task graph JSON identity is missing")
    graph_snapshot_id = Path(graph_artifact).stem
    registration_count = int(counts.get("registration_manifest_tasks", -1))
    enabled_workload_ids = sorted(
        workload_id
        for workload_id, row in workload_by_id.items()
        if row.get("enabled") is True
    )
    enabled_available_runners = sorted(
        set(enabled_workload_ids) & set(available_runners)
    )
    enabled_runner_modules_present = sorted(
        set(enabled_workload_ids) & set(runner_modules_present)
    )
    blocking_gaps: list[str] = []
    non_runnable_count = len(enabled_workload_ids) - len(enabled_available_runners)
    missing_runner_module_count = len(enabled_workload_ids) - len(
        enabled_runner_modules_present
    )
    if unregistered_unresolved_task_ids:
        blocking_gaps.append(
            f"{len(unregistered_unresolved_task_ids)}_CANONICAL_TASKS_HAVE_NO_PROVABLE_CATALOG_OR_APPROVED_REGISTRATION"
        )
    if non_runnable_count:
        blocking_gaps.append(
            f"{non_runnable_count}_OF_{len(enabled_workload_ids)}_ENABLED_WORKLOAD_COMMANDS_ARE_NOT_RUNNABLE"
        )
    if missing_runner_module_count:
        blocking_gaps.append(
            f"{missing_runner_module_count}_OF_{len(enabled_workload_ids)}_ENABLED_WORKLOAD_RUNNER_MODULES_ARE_MISSING"
        )
    enabled_incomplete_runner_commands = sorted(
        set(enabled_workload_ids) & set(incomplete_runner_commands)
    )
    if enabled_incomplete_runner_commands:
        blocking_gaps.append(
            f"{len(enabled_incomplete_runner_commands)}_ENABLED_RUNNER_COMMANDS_HAVE_INCOMPLETE_ARGUMENT_BINDINGS"
        )
    if unresolved_entrypoint_ids:
        blocking_gaps.append(
            f"{len(unresolved_entrypoint_ids)}_ENTRYPOINTS_HAVE_NO_PROVABLE_CATALOG_OR_TASK_REGISTRATION"
        )
    if unexplained_entrypoint_ids:
        blocking_gaps.append(
            f"{len(unexplained_entrypoint_ids)}_ENTRYPOINTS_HAVE_NO_GRAPH_BACKED_OWNER"
        )
    approved_cannot_confirm = {
        "registered_task_ids": registered_cannot_confirm_task_ids,
        "registration_entrypoint_ids": approved_registration_entrypoint_ids,
        "cross_day_task_ids": cross_day_tasks_without_explicit_target_role,
        "missing_launcher_task_ids": sorted(
            set(missing_launcher_tasks) & set(registered_cannot_confirm_task_ids)
        ),
        "extra_actual_windows_task_ids": extra_actual,
        "tasks_missing_explicit_runtime_roles": sorted(
            set(tasks_missing_explicit_runtime_roles)
            & set(registered_cannot_confirm_task_ids)
        ),
        "windows_task_registration_manifest_count": registration_count,
        "actual_windows_task_count": len(actual_tasks),
    }
    body: dict[str, Any] = {
        "schema_version": "v3_5.phase5_runtime_governance_audit.v1",
        "status": (
            "PASS" if not blocking_gaps else "BLOCKED_GRAPH_SEMANTICS_NOT_INVENTED"
        ),
        "graph_snapshot_id": graph_snapshot_id,
        "graph_generated_at": graph.get("generated_at"),
        "inventory_v2_semantic_hash": inventory.get("inventory_semantic_hash"),
        "catalog_schema_version": catalog.get("schema_version"),
        "input_raw_sha256": {
            "graph": graph_raw_sha,
            "inventory_v2": inventory_raw_sha,
            "runtime_catalog": catalog_raw_sha,
        },
        "input_payload_semantic_hash": {
            "graph": graph_payload_hash,
            "inventory_v2": inventory_payload_hash,
            "runtime_catalog": catalog_payload_hash,
        },
        "counts": {
            "actual_windows_tasks": len(actual_tasks),
            "canonical_task_specs": len(canonical_tasks),
            "catalog_workloads": len(catalog_workloads),
            "task_registrations": len(task_registrations),
            "entrypoints": len(entrypoint_rows),
            "inventory_runtime_tasks": len(inventory_runtime_tasks),
            "launcher_files": int(counts.get("launcher_files", -1)),
            "timeline_nodes": len(timeline_nodes),
        },
        "canonical_tasks": canonical_tasks,
        "timeline_node_ids": timeline_nodes,
        "entrypoints": entrypoint_rows,
        "extra_actual_windows_tasks": extra_actual,
        "missing_actual_windows_tasks": missing_actual,
        "missing_launcher_tasks": sorted(missing_launcher_tasks),
        "available_runner_workload_ids": available_runners,
        "runner_module_present_workload_ids": runner_modules_present,
        "incomplete_runner_command_workload_ids": incomplete_runner_commands,
        "missing_runner_workload_ids": missing_runners,
        "enabled_workload_ids": enabled_workload_ids,
        "enabled_available_runner_workload_ids": enabled_available_runners,
        "exact_catalog_task_count": exact_task_count,
        "unresolved_catalog_task_count": unresolved_task_count,
        "approved_task_registration_count": len(
            registered_cannot_confirm_task_ids
        ),
        "registered_cannot_confirm_task_ids": registered_cannot_confirm_task_ids,
        "unregistered_unresolved_task_ids": unregistered_unresolved_task_ids,
        "tasks_missing_explicit_runtime_roles": tasks_missing_explicit_runtime_roles,
        "cross_day_graph_node_ids": cross_day_graph_node_ids,
        "cross_day_task_ids": cross_day_task_ids,
        "cross_day_tasks_without_explicit_target_role": (
            cross_day_tasks_without_explicit_target_role
        ),
        "unresolved_entrypoint_ids": unresolved_entrypoint_ids,
        "approved_registration_entrypoint_ids": (
            approved_registration_entrypoint_ids
        ),
        "unexplained_entrypoint_ids": unexplained_entrypoint_ids,
        "dispatch_request_supports_target_date": (
            "target_date" in DispatchRequest.__dataclass_fields__
        ),
        "approved_cannot_confirm": approved_cannot_confirm,
        "blocking_gaps": blocking_gaps,
        "safety": dict(SAFETY),
    }
    return {**body, "semantic_hash": _semantic_hash(body)}


__all__ = ["build_runtime_governance_audit"]
