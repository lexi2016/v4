"""Build approved non-dispatchable task registrations from Phase-5 evidence."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from contracts.runtime_tasks import APPROVED_TASK_REGISTRATION_SEMANTIC_HASH


SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
APPROVED_DISPOSITION = "USER_APPROVED_DISABLED_CANNOT_CONFIRM"
EXPECTED_REGISTRATION_COUNT = 34


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validated_audit(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("invalid Phase-5 audit")
    body = dict(value)
    claimed = body.pop("semantic_hash", None)
    if not isinstance(claimed, str) or hashlib.sha256(
        _canonical_bytes(body)
    ).hexdigest() != claimed:
        raise ValueError("Phase-5 audit semantic hash mismatch")
    if value.get("safety") != SAFETY:
        raise ValueError("unsafe Phase-5 audit")
    return value


def build_task_spec_registrations(audit: Any) -> list[dict[str, Any]]:
    source = _validated_audit(audit)
    canonical_tasks = source.get("canonical_tasks")
    if not isinstance(canonical_tasks, list):
        raise ValueError("invalid Phase-5 canonical tasks")
    registrations: list[dict[str, Any]] = []
    for item in canonical_tasks:
        if not isinstance(item, Mapping):
            raise ValueError("invalid Phase-5 canonical task")
        if item.get("mapping_status") != "CANNOT_CONFIRM_CATALOG_OWNER":
            continue
        if item.get("catalog_workload_ids") != []:
            raise ValueError("unresolved task unexpectedly has a catalog workload")
        legacy_task_id = item.get("legacy_task_id")
        graph_task_spec_id = item.get("graph_task_spec_id")
        if (
            not isinstance(legacy_task_id, str)
            or graph_task_spec_id != f"task_spec:{legacy_task_id}"
        ):
            raise ValueError("invalid unresolved task graph identity")
        registrations.append(
            {
                "actual_windows_task_ids": deepcopy(
                    item.get("actual_windows_task_ids")
                ),
                "disposition": APPROVED_DISPOSITION,
                "enabled": False,
                "execution_allowed": False,
                "graph_task_spec_id": graph_task_spec_id,
                "legacy_launcher_paths": deepcopy(
                    item.get("legacy_launcher_paths")
                ),
                "legacy_task_id": legacy_task_id,
                "safety": dict(SAFETY),
                "status": "CANNOT_CONFIRM",
                "timeline_node_ids": deepcopy(item.get("timeline_node_ids")),
            }
        )
    registrations.sort(key=lambda row: row["legacy_task_id"])
    if len(registrations) != EXPECTED_REGISTRATION_COUNT:
        raise ValueError("approved unresolved registration count mismatch")
    return registrations


def build_catalog_with_task_registrations(
    catalog: Any,
    audit: Any,
) -> dict[str, Any]:
    if not isinstance(catalog, Mapping):
        raise ValueError("invalid runtime catalog")
    allowed = {
        "schema_version",
        "workloads",
        "task_registrations",
        "task_registration_semantic_hash",
        "retired_owners",
        "safety",
    }
    if set(catalog) - allowed or catalog.get("safety") != SAFETY:
        raise ValueError("invalid runtime catalog source")
    if catalog.get("schema_version") not in {
        "v3_5.runtime_workloads.v1",
        "v3_5.runtime_workloads.v2",
    }:
        raise ValueError("unsupported runtime catalog source")
    result = deepcopy(dict(catalog))
    result["schema_version"] = "v3_5.runtime_workloads.v2"
    result["task_registrations"] = build_task_spec_registrations(audit)
    registration_hash = hashlib.sha256(
        _canonical_bytes(result["task_registrations"])
    ).hexdigest()
    if registration_hash != APPROVED_TASK_REGISTRATION_SEMANTIC_HASH:
        raise ValueError("generated task registrations do not match approved contract")
    result["task_registration_semantic_hash"] = registration_hash
    return result


__all__ = [
    "APPROVED_DISPOSITION",
    "EXPECTED_REGISTRATION_COUNT",
    "build_catalog_with_task_registrations",
    "build_task_spec_registrations",
]
