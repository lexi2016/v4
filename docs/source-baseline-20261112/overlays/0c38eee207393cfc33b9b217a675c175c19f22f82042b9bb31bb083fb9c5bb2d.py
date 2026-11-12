"""Truthful task identity and same-date execution status projection."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import (
    RuntimeCatalog,
    TaskSpecRegistration,
    WorkloadDefinition,
)
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from contracts.close_timeline import CLOSE_TIMELINE
from stage_center.consumer import StageSelectionConsumer


FAILURE_STATUSES = {"FAILED", "DUPLICATE_WORKLOAD_SKIPPED"}


def _display_slot(slot: str) -> str:
    return f"{slot[:2]}:{slot[2:]}"


def _latest_receipt(
    workload: WorkloadDefinition,
    receipts: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    candidates = [
        receipt
        for receipt in receipts
        if str(receipt.get("mode") or "").upper() == "LIVE"
        and (
            workload.workload_id in receipt.get("selected_workload_ids", [])
        or (
            receipt.get("status")
            in {
                "NON_TRADING_DAY",
                "NON_TRADING_DAY_CADENCE",
                "NO_ELIGIBLE_WORKLOADS",
            }
            and receipt.get("slot") in workload.slots
        )
        )
    ]
    if not candidates:
        return None
    timestamped: list[tuple[datetime, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    for receipt in candidates:
        value = receipt.get("finished_at")
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            invalid.append(receipt)
            continue
        if parsed.tzinfo is None:
            invalid.append(receipt)
            continue
        timestamped.append((parsed, receipt))
    if timestamped:
        return max(
            timestamped,
            key=lambda item: (item[0], str(item[1].get("run_id") or "")),
        )[1]
    invalid_receipt = dict(invalid[-1])
    invalid_receipt.update(
        {
            "status": "CANNOT_CONFIRM",
            "finished_at": None,
            "_task_status_result_code": "EXECUTION_RECEIPT_FINISHED_AT_INVALID",
        }
    )
    return invalid_receipt


def _logical_row(
    workload: WorkloadDefinition,
    receipt: dict[str, Any] | None,
    business_date: str,
    now: datetime,
) -> dict[str, Any]:
    external_stage_authority = workload.workload_id == "stage_workbench"
    if external_stage_authority:
        status = "EXTERNAL_AUTHORITY"
        result_code = "STAGE_CENTER_EXTERNAL_AUTHORITY"
    elif receipt is None:
        not_due = (
            workload.enabled
            and bool(workload.slots)
            and (
                business_date > now.strftime("%Y%m%d")
                or (
                    business_date == now.strftime("%Y%m%d")
                    and now.strftime("%H%M") < min(workload.slots)
                )
            )
        )
        if not workload.enabled:
            status = "DEFERRED"
            result_code = "PHASE_DEFERRED"
        elif not_due:
            status = "PENDING_NOT_DUE"
            result_code = "NOT_DUE"
        else:
            status = "CANNOT_CONFIRM"
            result_code = "EXECUTION_RECEIPT_MISSING"
    else:
        status = str(receipt.get("status") or "CANNOT_CONFIRM")
        result_code = str(receipt.get("_task_status_result_code") or status)
    row = {
        "workload_id": workload.workload_id,
        "enabled": workload.enabled,
        "status": status,
        "last_run": receipt.get("finished_at") if receipt else None,
        "next_due": _display_slot(workload.slots[0]) if workload.slots else None,
        "duration_ms": receipt.get("duration_ms") if receipt else None,
        "result_code": result_code,
        "freshness": (
            "CURRENT"
            if receipt
            else "NOT_DUE"
            if status == "PENDING_NOT_DUE"
            else "NOT_OBSERVED"
        ),
        "receipt_path": receipt.get("receipt_path") if receipt else None,
    }
    if external_stage_authority:
        row.update({"authority": "STAGE_CENTER", "owner_kind": "EXTERNAL_AUTHORITY"})
    return row


def _registration_row(registration: TaskSpecRegistration) -> dict[str, Any]:
    return {
        "graph_task_spec_id": registration.graph_task_spec_id,
        "legacy_task_id": registration.legacy_task_id,
        "timeline_node_ids": list(registration.timeline_node_ids),
        "legacy_launcher_paths": list(registration.legacy_launcher_paths),
        "actual_windows_task_ids": list(registration.actual_windows_task_ids),
        "enabled": registration.enabled,
        "execution_allowed": registration.execution_allowed,
        "status": registration.status,
        "disposition": registration.disposition,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _timeline_not_due(item: dict[str, Any], business_date: str, now: datetime) -> bool:
    today = now.strftime("%Y%m%d")
    if business_date > today:
        return True
    return business_date == today and now.strftime("%H%M") < str(item["planned_slot"])


def _timeline_receipt(
    item: dict[str, Any],
    *,
    catalog: RuntimeCatalog,
    ledger: ExecutionLedger,
    receipts: tuple[dict[str, Any], ...],
    business_date: str,
    data_root: Path | None,
    stage_selection_root: Path | None,
    now: datetime,
) -> dict[str, Any]:
    workload_id = item.get("workload_id")
    workload = next(
        (row for row in catalog.workloads if row.workload_id == workload_id), None
    )
    receipt: dict[str, Any] | None = None
    receipt_path: str | None = None
    reason = ""
    result_code = ""
    if item["owner_kind"] == "STAGE_CENTER":
        if _timeline_not_due(item, business_date, now):
            status = "PENDING_NOT_DUE"
            reason = "NOT_DUE"
        elif stage_selection_root is None:
            status = "CANNOT_CONFIRM"
            reason = "STAGE_CENTER_SELECTION_ROOT_NOT_CONFIGURED"
        else:
            try:
                selection = StageSelectionConsumer(stage_selection_root).get(
                    business_date, str(item["stage_id"])
                )
                status = str(selection.get("status") or "CANNOT_CONFIRM")
                reason = str((selection.get("cannot_confirm") or [""])[0] or "")
                result_code = status
                pointer = stage_selection_root / "selection_latest.json"
                receipt_path = str(pointer) if pointer.is_file() else None
            except (OSError, TypeError, ValueError):
                status = "CANNOT_CONFIRM"
                reason = "STAGE_CENTER_SELECTION_UNREADABLE"
        if not reason and status not in {"READY", "READY_EMPTY"}:
            reason = "STAGE_CENTER_SELECTION_CANNOT_CONFIRM"
    elif item["node_id"] in {"hkconnect_model_selection_review", "FUPAN_A_SHARE_STRUCTURE"} and workload is not None:
        receipt = _latest_receipt(workload, receipts)
        if receipt is not None:
            status = str(receipt.get("status") or "CANNOT_CONFIRM")
            reason = str(receipt.get("stderr") or receipt.get("reason") or "")
            result_code = str(receipt.get("_task_status_result_code") or status)
            receipt_path = str(receipt.get("receipt_path") or "") or None
        else:
            if _timeline_not_due(item, business_date, now):
                status = "PENDING_NOT_DUE"
                reason = "NOT_DUE"
                result_code = reason
            elif item["node_id"] == "FUPAN_A_SHARE_STRUCTURE" and data_root is not None:
                artifact = None
                artifact_invalid = False
                try:
                    artifact = AShareReviewStore(Path(data_root)).read_review(business_date)
                except (OSError, TypeError, ValueError, KeyError):
                    artifact_invalid = True
                if (
                    isinstance(artifact, dict)
                    and artifact.get("source_role") == "V3_5_NATIVE_CLOSE_MODEL"
                ):
                    status = "BACKFILLED_ARTIFACT_READY"
                    reason = "EXACT_DATE_A_SHARE_REVIEW_VERIFIED"
                    result_code = status
                    receipt_path = f"a_share_reviews/receipts/{business_date}.json"
                else:
                    status = "CANNOT_CONFIRM"
                    reason = (
                        "A_SHARE_REVIEW_ARTIFACT_INVALID"
                        if artifact_invalid
                        else f"EXECUTION_RECEIPT_MISSING:{workload.workload_id}"
                    )
                    result_code = reason
            else:
                status = "CANNOT_CONFIRM"
                reason = f"EXECUTION_RECEIPT_MISSING:{workload.workload_id}"
                result_code = reason
    else:
        root = data_root
        if root is None:
            root = ledger.root.parent
        fixed_path = (
            Path(root)
            / "runtime_graph"
            / "evidence"
            / "scheduler_status"
            / business_date
            / f"{item['node_id']}.json"
        )
        receipt = _read_json(fixed_path)
        receipt_path = str(fixed_path)
        if receipt is None:
            status = "PENDING_NOT_DUE" if _timeline_not_due(item, business_date, now) else "CANNOT_CONFIRM"
            reason = "NOT_DUE" if status == "PENDING_NOT_DUE" else f"EXECUTION_RECEIPT_MISSING:{item['node_id']}"
            result_code = reason
        else:
            status = str(receipt.get("status") or "CANNOT_CONFIRM")
            reason = str(receipt.get("reason") or "")
            result_code = str(receipt.get("result_code") or receipt.get("status") or "CANNOT_CONFIRM")
    last_run = None
    if receipt is not None:
        last_run = receipt.get("finished_at") or receipt.get("completed_at")
    return {
        **item,
        "status": status,
        "reason": reason or result_code or status,
        "result_code": result_code or status,
        "planned_time": item["planned_slot"],
        "actual_receipt_path": receipt_path,
        "receipt_path": receipt_path,
        "last_run": last_run,
        "freshness": "CURRENT" if receipt is not None or status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "READY_WITH_REVIEW_BOUNDARY", "SUCCESS", "SUCCEEDED", "ACTION_RAN_WITH_CANNOT_CONFIRM", "BACKFILLED_ARTIFACT_READY"} else "NOT_DUE" if status == "PENDING_NOT_DUE" else "NOT_OBSERVED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_task_status(
    catalog: RuntimeCatalog,
    ledger: ExecutionLedger,
    business_date: str,
    *,
    now: datetime | None = None,
    data_root: Path | None = None,
    stage_selection_root: Path | None = None,
) -> dict[str, Any]:
    datetime.strptime(business_date, "%Y%m%d")
    current_time = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    receipts = ledger.list_receipts(business_date, mode="LIVE")
    logical = [
        _logical_row(
            workload,
            _latest_receipt(workload, receipts),
            business_date,
            current_time,
        )
        for workload in catalog.workloads
    ]
    active_owners = [
        {
            "owner_id": workload.owner_id,
            "workload_id": workload.workload_id,
            "status": "ACTIVE",
        }
        for workload in catalog.workloads
        if workload.enabled
    ]
    aliases = [
        {
            "alias": alias,
            "workload_id": workload.workload_id,
            "status": "ALIAS_ONLY",
        }
        for workload in catalog.workloads
        for alias in workload.aliases
    ]
    retired = [
        {
            "owner_id": owner.owner_id,
            "replacement_workload_id": owner.replacement_workload_id,
            "status": owner.status,
        }
        for owner in catalog.retired_owners
    ]
    registrations = [
        _registration_row(registration)
        for registration in catalog.task_registrations
    ]
    cannot_confirm_registrations = [
        row for row in registrations if row["status"] == "CANNOT_CONFIRM"
    ]
    retired_registrations = [
        row
        for row in registrations
        if row["status"] == "RETIRED_BY_EXACT_CATALOG_OWNER"
    ]
    timeline_nodes = [
        _timeline_receipt(
            item,
            catalog=catalog,
            ledger=ledger,
            receipts=receipts,
            business_date=business_date,
            data_root=data_root,
            stage_selection_root=stage_selection_root,
            now=current_time,
        )
        for item in CLOSE_TIMELINE
    ]
    cannot_confirm = [
        f"EXECUTION_RECEIPT_MISSING:{row['workload_id']}"
        for row in logical
        if row["enabled"] and row["status"] == "CANNOT_CONFIRM"
    ]
    if cannot_confirm_registrations:
        cannot_confirm.append(
            "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:"
            f"{len(cannot_confirm_registrations)}"
        )
    cannot_confirm.extend(
        str(row["reason"])
        for row in timeline_nodes
        if row["status"] == "CANNOT_CONFIRM" and row.get("reason")
    )
    return {
        "schema_version": "v3_5.task_status.v2",
        "business_date": business_date,
        "logical_workload_count": len(logical),
        "active_owner_count": len(active_owners),
        "alias_count": len(aliases),
        "retired_owner_count": len(retired),
        "task_registration_count": len(registrations),
        "cannot_confirm_task_registration_count": len(cannot_confirm_registrations),
        "retired_task_registration_count": len(retired_registrations),
        "groups": {
            "logical": logical,
            "active_owners": active_owners,
            "aliases": aliases,
            "retired": retired,
            "registrations": registrations,
        },
        "timeline_nodes": timeline_nodes,
        "cannot_confirm": cannot_confirm,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
