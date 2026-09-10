"""Typed runtime workload and dispatch contracts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from contracts.trading_calendar import MarketScope, RunPolicy, SessionRequirement


APPROVED_TASK_REGISTRATION_SEMANTIC_HASH = (
    "0c2a0040dee4f225ecc8099f2213f4e78eb687f1b030a55d810ad99fdb6f0e30"
)


class DispatchMode(StrEnum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"
    BACKFILL = "BACKFILL"


@dataclass(frozen=True)
class SafetyBoundary:
    production_allowed: bool
    buy_gate_updated: bool
    orders_sent: bool


@dataclass(frozen=True)
class WorkloadDefinition:
    workload_id: str
    owner_id: str
    run_policy: RunPolicy
    market_scope: MarketScope
    session_requirement: SessionRequirement
    slots: tuple[str, ...]
    command: tuple[str, ...]
    aliases: tuple[str, ...]
    enabled: bool
    scheduled_date_role: str
    signal_date_role: str
    target_date_role: str
    safety: SafetyBoundary
    non_trading_day_slots: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetiredOwner:
    owner_id: str
    replacement_workload_id: str
    status: str


@dataclass(frozen=True)
class TaskSpecRegistration:
    graph_task_spec_id: str
    legacy_task_id: str
    timeline_node_ids: tuple[str, ...]
    legacy_launcher_paths: tuple[str, ...]
    actual_windows_task_ids: tuple[str, ...]
    enabled: bool
    execution_allowed: bool
    status: str
    disposition: str
    safety: SafetyBoundary


@dataclass(frozen=True)
class RuntimeCatalog:
    schema_version: str
    workloads: tuple[WorkloadDefinition, ...]
    task_registrations: tuple[TaskSpecRegistration, ...]
    retired_owners: tuple[RetiredOwner, ...]
    safety: SafetyBoundary
    _source_payload: dict[str, Any]

    @property
    def source_payload(self) -> dict[str, Any]:
        return deepcopy(self._source_payload)


@dataclass(frozen=True)
class DispatchRequest:
    scheduled_date: str
    business_date: str
    target_date: str
    slot: str
    mode: DispatchMode

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", DispatchMode(self.mode))
        for field in ("scheduled_date", "business_date", "target_date"):
            value = getattr(self, field)
            if len(value) != 8 or not value.isdigit():
                raise ValueError(f"{field} must use YYYYMMDD")
            try:
                datetime.strptime(value, "%Y%m%d")
            except ValueError as error:
                raise ValueError(f"{field} must be a real date") from error
        if len(self.slot) != 4 or not self.slot.isdigit():
            raise ValueError("slot must use HHMM")
        hour, minute = int(self.slot[:2]), int(self.slot[2:])
        if hour > 23 or minute > 59:
            raise ValueError("slot must be a real time")
        if self.mode is DispatchMode.LIVE and self.scheduled_date != self.business_date:
            raise ValueError("LIVE mode requires scheduled_date == business_date")


__all__ = [
    "APPROVED_TASK_REGISTRATION_SEMANTIC_HASH",
    "DispatchMode",
    "DispatchRequest",
    "MarketScope",
    "RetiredOwner",
    "RunPolicy",
    "RuntimeCatalog",
    "SafetyBoundary",
    "SessionRequirement",
    "TaskSpecRegistration",
    "WorkloadDefinition",
]
