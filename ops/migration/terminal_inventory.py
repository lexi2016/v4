"""Build an evidence-bound terminal overlay without rewriting frozen inventory v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ops.migration.graph_baseline import (
    GraphBaselineError,
    validate_inventory_v2,
)


SCHEMA_VERSION = "v3_5.replacement_inventory.v3"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
GROUPS = ("sources", "entrypoints", "runtime_tasks", "features")
DEFAULT_BASE = Path("contracts/migration/v35_replacement_inventory_v2.json")
DEFAULT_GRAPH = Path("contracts/migration/v3_graph_baseline_v2.json")
DEFAULT_PHASE4 = Path("contracts/migration/phase4_feature_disposition_v1.json")
DEFAULT_PHASE5 = Path(
    "contracts/migration/phase5_runtime_governance_audit_v1.json"
)
DEFAULT_OUTPUT = Path(
    "contracts/migration/v35_replacement_inventory_v3.json"
)


class TerminalInventoryError(ValueError):
    """Terminal inventory is inconsistent with its frozen authorities."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_semantic(payload: Mapping[str, Any], field: str) -> None:
    claimed = payload.get(field)
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise TerminalInventoryError(f"invalid {field}")
    body = {key: deepcopy(value) for key, value in payload.items() if key != field}
    if semantic_hash(body) != claimed:
        raise TerminalInventoryError(f"{field} mismatch")


def _reference(
    repo_root: Path,
    relative: str,
    *,
    kind: str,
    semantic_field: str,
) -> dict[str, str]:
    payload = json.loads((repo_root / relative).read_text(encoding="utf-8"))
    return {
        "kind": kind,
        "path": relative,
        "raw_sha256": _raw_sha(repo_root / relative),
        "semantic_hash": str(payload[semantic_field]),
    }


def _base_record_sha(record: Mapping[str, Any]) -> str:
    return semantic_hash(record)


def _common_record(
    record: Mapping[str, Any],
    *,
    disposition: str,
    terminal_class: str,
    cannot_confirm: list[str],
    target_modules: list[str],
    gap_evidence: list[dict[str, str]],
) -> dict[str, Any]:
    if not cannot_confirm:
        raise TerminalInventoryError("terminal gap requires reason")
    return {
        "base_record_sha256": _base_record_sha(record),
        "graph_node_ids": deepcopy(record["graph_node_ids"]),
        "target_owner": record["target_owner"],
        "target_modules": sorted(set(target_modules)),
        "disposition": disposition,
        "status": "CANNOT_CONFIRM",
        "terminal_class": terminal_class,
        "cannot_confirm": sorted(set(cannot_confirm)),
        "gap_evidence": deepcopy(gap_evidence),
        "replacement_evidence": [],
    }


def _source_records(
    records: list[Mapping[str, Any]],
    *,
    base_reference: dict[str, str],
    graph_reference: dict[str, str],
) -> list[dict[str, Any]]:
    output = []
    for record in records:
        output.append(
            {
                "atlas_file_id": record["atlas_file_id"],
                "old_source": record["old_source"],
                "source_sha256": record["sha256"],
                "source_state": record["source_state"],
                **_common_record(
                    record,
                    disposition="REWRITE",
                    terminal_class="CANNOT_CONFIRM",
                    cannot_confirm=["NO_RECORD_LEVEL_REPLACEMENT_EVIDENCE"],
                    target_modules=[],
                    gap_evidence=[base_reference, graph_reference],
                ),
            }
        )
    return output


def _entrypoint_records(
    records: list[Mapping[str, Any]],
    *,
    phase5_audit: Mapping[str, Any],
    base_reference: dict[str, str],
    phase5_reference: dict[str, str],
) -> list[dict[str, Any]]:
    mappings = {
        item["atlas_entrypoint_id"]: item
        for item in phase5_audit["entrypoints"]
    }
    if set(mappings) != {record["atlas_entrypoint_id"] for record in records}:
        raise TerminalInventoryError("phase5 entrypoint mapping is incomplete")
    output = []
    for record in records:
        mapping = mappings[record["atlas_entrypoint_id"]]
        mapping_status = str(mapping["mapping_status"])
        target_modules = (
            ["contracts/runtime_workloads.json", "ops/run_hourly_research.py"]
            if mapping_status == "EXACT_CATALOG_IDENTITY"
            else ["contracts/runtime_workloads.json"]
            if mapping_status == "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
            else []
        )
        output.append(
            {
                "atlas_entrypoint_id": record["atlas_entrypoint_id"],
                "catalog_workload_ids": deepcopy(
                    mapping["catalog_workload_ids"]
                ),
                "kind": record["kind"],
                "legacy_task_ids": deepcopy(mapping["legacy_task_ids"]),
                "mapping_status": mapping_status,
                **_common_record(
                    record,
                    disposition="REWRITE",
                    terminal_class="CANNOT_CONFIRM",
                    cannot_confirm=[
                        f"PHASE5_{mapping_status}",
                        "NO_PASSING_ARTIFACT_API_PAGE_PARITY_RECEIPT",
                    ],
                    target_modules=target_modules,
                    gap_evidence=[base_reference, phase5_reference],
                ),
            }
        )
    return output


def _runtime_mappings(
    record: Mapping[str, Any],
    canonical_tasks: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    matches = []
    for task in canonical_tasks:
        if record["record_type"] == "windows_task":
            matched = record["task_name"] == task["legacy_task_id"]
        else:
            matched = record.get("node_id") in task["timeline_node_ids"]
        if matched:
            matches.append(task)
    if not matches:
        raise TerminalInventoryError("phase5 runtime mapping is incomplete")
    return sorted(matches, key=lambda item: str(item["legacy_task_id"]))


def _runtime_records(
    records: list[Mapping[str, Any]],
    *,
    phase5_audit: Mapping[str, Any],
    base_reference: dict[str, str],
    phase5_reference: dict[str, str],
) -> list[dict[str, Any]]:
    canonical_tasks = phase5_audit["canonical_tasks"]
    output = []
    for record in records:
        mappings = _runtime_mappings(record, canonical_tasks)
        mapping_statuses = sorted(
            {str(mapping["mapping_status"]) for mapping in mappings}
        )
        target_modules = ["contracts/runtime_workloads.json"]
        if "EXACT_CATALOG_IDENTITY_RUNNER_AVAILABLE" in mapping_statuses:
            target_modules.append("ops/run_hourly_research.py")
        output.append(
            {
                "catalog_workload_ids": sorted(
                    {
                        workload_id
                        for mapping in mappings
                        for workload_id in mapping["catalog_workload_ids"]
                    }
                ),
                "legacy_task_ids": [
                    str(mapping["legacy_task_id"]) for mapping in mappings
                ],
                "record_type": record["record_type"],
                "task_name": record["task_name"],
                "node_id": record.get("node_id"),
                "mapping_statuses": mapping_statuses,
                **_common_record(
                    record,
                    disposition="REWRITE",
                    terminal_class="CANNOT_CONFIRM",
                    cannot_confirm=[
                        *(f"PHASE5_{status}" for status in mapping_statuses),
                        "NO_EXECUTION_AND_PAGE_PARITY_RECEIPT",
                    ],
                    target_modules=target_modules,
                    gap_evidence=[base_reference, phase5_reference],
                ),
            }
        )
    return output


def _feature_records(
    records: list[Mapping[str, Any]],
    *,
    phase4_contract: Mapping[str, Any],
    base_reference: dict[str, str],
    phase4_reference: dict[str, str],
) -> list[dict[str, Any]]:
    decisions = {item["feature_id"]: item for item in phase4_contract["features"]}
    if set(decisions) != {record["feature_id"] for record in records}:
        raise TerminalInventoryError("phase4 feature mapping is incomplete")
    output = []
    for record in records:
        decision = decisions[record["feature_id"]]
        disposition = str(decision["proposed_disposition"])
        terminal_class = (
            "COMPAT"
            if disposition == "COMPAT"
            else "REMOVE_PROPOSED"
            if disposition == "REMOVE"
            else "CANNOT_CONFIRM"
        )
        reasons = list(decision["cannot_confirm"])
        reasons.append("NO_PASSING_ARTIFACT_API_PAGE_PARITY_RECEIPT")
        if terminal_class == "REMOVE_PROPOSED":
            reasons.append("REMOVE_NOT_EXECUTED")
        output.append(
            {
                "feature_id": record["feature_id"],
                "phase4_decision_status": decision["decision_status"],
                **_common_record(
                    record,
                    disposition=disposition,
                    terminal_class=terminal_class,
                    cannot_confirm=reasons,
                    target_modules=list(decision["replacement_paths"]),
                    gap_evidence=[base_reference, phase4_reference],
                ),
            }
        )
    return output


def build_terminal_inventory(
    *,
    base_inventory: Mapping[str, Any],
    graph_baseline: Mapping[str, Any],
    phase4_contract: Mapping[str, Any],
    phase5_audit: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    repo_root = Path(repo_root)
    try:
        validate_inventory_v2(base_inventory, baseline=graph_baseline)
    except GraphBaselineError as error:
        raise TerminalInventoryError(str(error)) from error
    _validate_semantic(phase4_contract, "semantic_hash")
    _validate_semantic(phase5_audit, "semantic_hash")
    base_reference = _reference(
        repo_root,
        DEFAULT_BASE.as_posix(),
        kind="frozen_inventory_v2",
        semantic_field="inventory_semantic_hash",
    )
    graph_reference = _reference(
        repo_root,
        DEFAULT_GRAPH.as_posix(),
        kind="graph_baseline",
        semantic_field="semantic_hash",
    )
    phase4_reference = _reference(
        repo_root,
        DEFAULT_PHASE4.as_posix(),
        kind="phase4_feature_disposition",
        semantic_field="semantic_hash",
    )
    phase5_reference = _reference(
        repo_root,
        DEFAULT_PHASE5.as_posix(),
        kind="phase5_runtime_audit",
        semantic_field="semantic_hash",
    )
    sources = _source_records(
        base_inventory["sources"],
        base_reference=base_reference,
        graph_reference=graph_reference,
    )
    entrypoints = _entrypoint_records(
        base_inventory["entrypoints"],
        phase5_audit=phase5_audit,
        base_reference=base_reference,
        phase5_reference=phase5_reference,
    )
    runtime_tasks = _runtime_records(
        base_inventory["runtime_tasks"],
        phase5_audit=phase5_audit,
        base_reference=base_reference,
        phase5_reference=phase5_reference,
    )
    features = _feature_records(
        base_inventory["features"],
        phase4_contract=phase4_contract,
        base_reference=base_reference,
        phase4_reference=phase4_reference,
    )
    all_records = [*sources, *entrypoints, *runtime_tasks, *features]
    terminal_classes: dict[str, int] = {}
    for record in all_records:
        terminal_class = str(record["terminal_class"])
        terminal_classes[terminal_class] = terminal_classes.get(terminal_class, 0) + 1
    body = {
        "schema_version": SCHEMA_VERSION,
        "base_inventory_v2": base_reference,
        "graph_baseline": graph_reference,
        "phase4_feature_disposition": phase4_reference,
        "phase5_runtime_governance": phase5_reference,
        "counts": deepcopy(base_inventory["counts"]),
        "terminal_counts": {
            "total": len(all_records),
            "complete": sum(record["status"] == "COMPLETE" for record in all_records),
            "by_status": {"CANNOT_CONFIRM": len(all_records)},
            "by_terminal_class": dict(sorted(terminal_classes.items())),
        },
        "sources": sources,
        "entrypoints": entrypoints,
        "runtime_tasks": runtime_tasks,
        "features": features,
        "claims": {
            "inventory_accounting_complete": True,
            "business_parity_verified": False,
            "deployed": False,
            "ui_verified": False,
            "ready_to_replace": False,
        },
        "safety": deepcopy(SAFETY),
    }
    return {**body, "terminal_semantic_hash": semantic_hash(body)}


def validate_terminal_inventory(
    terminal: Mapping[str, Any],
    *,
    base_inventory: Mapping[str, Any],
    graph_baseline: Mapping[str, Any],
    phase4_contract: Mapping[str, Any],
    phase5_audit: Mapping[str, Any],
    repo_root: Path,
) -> None:
    if not isinstance(terminal, Mapping):
        raise TerminalInventoryError("terminal inventory must be an object")
    expected = build_terminal_inventory(
        base_inventory=base_inventory,
        graph_baseline=graph_baseline,
        phase4_contract=phase4_contract,
        phase5_audit=phase5_audit,
        repo_root=repo_root,
    )
    if terminal != expected:
        raise TerminalInventoryError("terminal inventory does not match authorities")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    load = lambda relative: json.loads(
        (root / relative).read_text(encoding="utf-8")
    )
    terminal = build_terminal_inventory(
        base_inventory=load(DEFAULT_BASE),
        graph_baseline=load(DEFAULT_GRAPH),
        phase4_contract=load(DEFAULT_PHASE4),
        phase5_audit=load(DEFAULT_PHASE5),
        repo_root=root,
    )
    output = args.output if args.output.is_absolute() else root / args.output
    _atomic_json(output, terminal)
    print(
        json.dumps(
            {
                "status": "PASS_WITH_TERMINAL_CANNOT_CONFIRM",
                "output": output.relative_to(root).as_posix(),
                "terminal_semantic_hash": terminal["terminal_semantic_hash"],
                "terminal_counts": terminal["terminal_counts"],
                "safety": terminal["safety"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TerminalInventoryError",
    "build_terminal_inventory",
    "semantic_hash",
    "validate_terminal_inventory",
]
