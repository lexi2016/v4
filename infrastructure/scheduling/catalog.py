"""Strict loader for the V3.5-owned runtime workload catalog."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from contracts.runtime_tasks import (
    APPROVED_TASK_REGISTRATION_SEMANTIC_HASH,
    MarketScope,
    RetiredOwner,
    RunPolicy,
    RuntimeCatalog,
    SafetyBoundary,
    SessionRequirement,
    TaskSpecRegistration,
    WorkloadDefinition,
)


CATALOG_PATH = Path(__file__).resolve().parents[2] / "contracts" / "runtime_workloads.json"
TOP_LEVEL_FIELDS = {
    "schema_version",
    "workloads",
    "task_registrations",
    "task_registration_semantic_hash",
    "retired_owners",
    "safety",
}
WORKLOAD_FIELDS = {
    "workload_id",
    "owner_id",
    "run_policy",
    "market_scope",
    "session_requirement",
    "slots",
    "command",
    "aliases",
    "enabled",
    "scheduled_date_role",
    "signal_date_role",
    "target_date_role",
    "safety",
}
OPTIONAL_WORKLOAD_FIELDS = {"non_trading_day_slots"}
RETIRED_FIELDS = {"owner_id", "replacement_workload_id", "status"}
SAFETY_FIELDS = {"production_allowed", "buy_gate_updated", "orders_sent"}
TASK_REGISTRATION_FIELDS = {
    "graph_task_spec_id",
    "legacy_task_id",
    "timeline_node_ids",
    "legacy_launcher_paths",
    "actual_windows_task_ids",
    "enabled",
    "execution_allowed",
    "status",
    "disposition",
    "safety",
}
DATE_ROLES = {"SCHEDULED_DATE", "BUSINESS_DATE", "TARGET_DATE"}


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid {field}")
    return value.strip()


def _safety(value: Any) -> SafetyBoundary:
    if not isinstance(value, dict) or set(value) != SAFETY_FIELDS:
        raise ValueError("invalid safety fields")
    if any(type(value[field]) is not bool for field in SAFETY_FIELDS):
        raise ValueError("safety fields must be boolean")
    boundary = SafetyBoundary(**value)
    if boundary != SafetyBoundary(False, False, False):
        raise ValueError("unsafe workload boundary")
    return boundary


def _slot(value: Any) -> str:
    text = _nonempty(value, "slot")
    if len(text) != 4 or not text.isdigit():
        raise ValueError("slot must use HHMM")
    hour, minute = int(text[:2]), int(text[2:])
    if hour > 23 or minute > 59:
        raise ValueError("slot must be a real time")
    return text


def _string_tuple(value: Any, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f"invalid {field}")
    result = tuple(_nonempty(item, field) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate {field}")
    return result


def _workload(value: Any) -> WorkloadDefinition:
    if (
        not isinstance(value, dict)
        or not WORKLOAD_FIELDS.issubset(value)
        or set(value) - WORKLOAD_FIELDS != OPTIONAL_WORKLOAD_FIELDS.intersection(value)
    ):
        raise ValueError("invalid workload fields")
    if type(value["enabled"]) is not bool:
        raise ValueError("enabled must be boolean")
    slots = tuple(sorted(_slot(item) for item in _string_tuple(value["slots"], "slots", allow_empty=False)))
    command = _string_tuple(value["command"], "command", allow_empty=False)
    aliases = tuple(sorted(_string_tuple(value["aliases"], "aliases", allow_empty=True)))
    non_trading_day_slots = tuple(
        sorted(
            _slot(item)
            for item in _string_tuple(
                value.get("non_trading_day_slots", []),
                "non_trading_day_slots",
                allow_empty=True,
            )
        )
    )
    if any(slot not in slots for slot in non_trading_day_slots):
        raise ValueError("non-trading-day slot must be a workload slot")
    if non_trading_day_slots and value["run_policy"] != RunPolicy.NATURAL_DAY.value:
        raise ValueError("reduced non-trading cadence requires NATURAL_DAY")
    roles = {
        field: _nonempty(value[field], field)
        for field in ("scheduled_date_role", "signal_date_role", "target_date_role")
    }
    if any(role not in DATE_ROLES for role in roles.values()):
        raise ValueError("unsupported date role")
    return WorkloadDefinition(
        workload_id=_nonempty(value["workload_id"], "workload_id"),
        owner_id=_nonempty(value["owner_id"], "owner_id"),
        run_policy=RunPolicy(value["run_policy"]),
        market_scope=MarketScope(value["market_scope"]),
        session_requirement=SessionRequirement(value["session_requirement"]),
        slots=slots,
        command=command,
        aliases=aliases,
        enabled=value["enabled"],
        safety=_safety(value["safety"]),
        non_trading_day_slots=non_trading_day_slots,
        **roles,
    )


def _task_registration(value: Any) -> TaskSpecRegistration:
    if not isinstance(value, dict) or set(value) != TASK_REGISTRATION_FIELDS:
        raise ValueError("invalid task registration fields")
    legacy_task_id = _nonempty(value["legacy_task_id"], "legacy task id")
    graph_task_spec_id = _nonempty(
        value["graph_task_spec_id"], "graph task spec id"
    )
    if graph_task_spec_id != f"task_spec:{legacy_task_id}":
        raise ValueError("task registration graph identity mismatch")
    if value["enabled"] is not False or value["execution_allowed"] is not False:
        raise ValueError("task registration must be non-dispatchable")
    allowed_registration_states = {
        "CANNOT_CONFIRM": "USER_APPROVED_DISABLED_CANNOT_CONFIRM",
        "RETIRED_BY_EXACT_CATALOG_OWNER": "RETIRED_BY_EXACT_CATALOG_OWNER",
    }
    if value["status"] not in allowed_registration_states:
        raise ValueError("invalid task registration status")
    if value["disposition"] != allowed_registration_states[value["status"]]:
        raise ValueError("invalid task registration disposition")
    return TaskSpecRegistration(
        graph_task_spec_id=graph_task_spec_id,
        legacy_task_id=legacy_task_id,
        timeline_node_ids=tuple(
            sorted(
                _string_tuple(
                    value["timeline_node_ids"],
                    "registration timeline nodes",
                    allow_empty=False,
                )
            )
        ),
        legacy_launcher_paths=tuple(
            sorted(
                _string_tuple(
                    value["legacy_launcher_paths"],
                    "registration launcher paths",
                    allow_empty=True,
                )
            )
        ),
        actual_windows_task_ids=tuple(
            sorted(
                _string_tuple(
                    value["actual_windows_task_ids"],
                    "registration Windows task ids",
                    allow_empty=False,
                )
            )
        ),
        enabled=False,
        execution_allowed=False,
        status=value["status"],
        disposition=value["disposition"],
        safety=_safety(value["safety"]),
    )


def load_workload_catalog(path: Path | None = None) -> RuntimeCatalog:
    source_path = CATALOG_PATH if path is None else Path(path)
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("runtime workload catalog cannot be loaded") from error
    if not isinstance(payload, dict) or set(payload) != TOP_LEVEL_FIELDS:
        raise ValueError("invalid runtime workload envelope")
    if payload["schema_version"] != "v3_5.runtime_workloads.v2":
        raise ValueError("unsupported runtime workload schema")
    if not isinstance(payload["workloads"], list) or not payload["workloads"]:
        raise ValueError("runtime workloads are required")
    workloads = tuple(_workload(item) for item in payload["workloads"])
    workload_ids = [row.workload_id for row in workloads]
    owner_ids = [row.owner_id for row in workloads]
    aliases = [alias for row in workloads for alias in row.aliases]
    if len(set(workload_ids)) != len(workload_ids):
        raise ValueError("duplicate workload_id")
    if len(set(owner_ids)) != len(owner_ids):
        raise ValueError("duplicate owner_id")
    if len(set(aliases)) != len(aliases):
        raise ValueError("duplicate alias")
    if set(aliases) & (set(workload_ids) | set(owner_ids)):
        raise ValueError("alias collides with canonical identity")
    registration_source = payload["task_registrations"]
    if not isinstance(registration_source, list):
        raise ValueError("invalid task registrations")
    registration_semantic_hash = hashlib.sha256(
        json.dumps(
            registration_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        payload["task_registration_semantic_hash"]
        != APPROVED_TASK_REGISTRATION_SEMANTIC_HASH
        or registration_semantic_hash != APPROVED_TASK_REGISTRATION_SEMANTIC_HASH
    ):
        raise ValueError("task registration contract mismatch")
    task_registrations = tuple(
        _task_registration(item) for item in registration_source
    )
    registration_legacy_ids = [row.legacy_task_id for row in task_registrations]
    registration_graph_ids = [row.graph_task_spec_id for row in task_registrations]
    if len(set(registration_legacy_ids)) != len(registration_legacy_ids):
        raise ValueError("duplicate task registration identity")
    if len(set(registration_graph_ids)) != len(registration_graph_ids):
        raise ValueError("duplicate task registration graph identity")
    retired_source = payload["retired_owners"]
    if not isinstance(retired_source, list):
        raise ValueError("invalid retired owners")
    retired: list[RetiredOwner] = []
    for item in retired_source:
        if not isinstance(item, dict) or set(item) != RETIRED_FIELDS:
            raise ValueError("invalid retired owner fields")
        row = RetiredOwner(
            owner_id=_nonempty(item["owner_id"], "retired owner_id"),
            replacement_workload_id=_nonempty(
                item["replacement_workload_id"], "replacement_workload_id"
            ),
            status=_nonempty(item["status"], "retired status"),
        )
        if row.status != "RETIRED_DISABLED" or row.replacement_workload_id not in workload_ids:
            raise ValueError("invalid retired owner mapping")
        retired.append(row)
    retired_ids = [row.owner_id for row in retired]
    if len(set(retired_ids)) != len(retired_ids) or set(retired_ids) & set(owner_ids):
        raise ValueError("duplicate retired owner identity")
    return RuntimeCatalog(
        schema_version=payload["schema_version"],
        workloads=workloads,
        task_registrations=task_registrations,
        retired_owners=tuple(retired),
        safety=_safety(payload["safety"]),
        _source_payload=deepcopy(payload),
    )
