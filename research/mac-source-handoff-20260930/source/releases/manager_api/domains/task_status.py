"""Truthful task identity and same-date execution status projection."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import (
    RuntimeCatalog,
    RunPolicy,
    TaskSpecRegistration,
    WorkloadDefinition,
)
from contracts.trading_calendar import TradingDayState, load_market_calendar, resolve_market_states
from infrastructure.a_share_review_store import AShareReviewStore
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from contracts.close_timeline import CLOSE_TIMELINE
from stage_center.consumer import StageSelectionConsumer


FAILURE_STATUSES = {"FAILED", "DUPLICATE_WORKLOAD_SKIPPED"}


def _display_slot(slot: str) -> str:
    return f"{slot[:2]}:{slot[2:]}"


def _schedule_date_is_eligible(workload: WorkloadDefinition, date: str) -> bool:
    """Apply the existing workload policy to a candidate calendar date."""
    policy = workload.run_policy
    if policy is RunPolicy.NATURAL_DAY:
        return True
    states = resolve_market_states(load_market_calendar(), date)
    eligible = {
        "a_share": states.get("a_share"),
        # ``resolve_market_states`` exposes the derived southbound lane under
        # its runtime key ``hk_connect``; the calendar source itself names the
        # market ``hk_connect_southbound``.
        "hk_connect": states.get("hk_connect"),
    }
    if policy is RunPolicy.A_SHARE_TRADE_DAY:
        return eligible["a_share"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
    if policy is RunPolicy.HK_CONNECT_TRADE_DAY:
        return eligible["hk_connect"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
    if policy is RunPolicy.A_OR_HK_CONNECT_TRADE_DAY:
        return any(
            state not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
            for state in eligible.values()
        )
    if policy is RunPolicy.CROSS_MARKET:
        return True
    return False


def _next_due(workload: WorkloadDefinition, business_date: str, now: datetime) -> dict[str, str] | None:
    """Return the next configured slot in Shanghai time without rewriting schedules."""
    if not workload.enabled or not workload.slots:
        return None
    current = now.astimezone(ZoneInfo("Asia/Shanghai")) if now.tzinfo else now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    today = current.date()
    requested = datetime.strptime(business_date, "%Y%m%d").date()
    candidate_date = max(requested, today)
    current_hhmm = current.strftime("%H%M")
    for day_offset in range(0, 371):
        day = candidate_date.fromordinal(candidate_date.toordinal() + day_offset)
        date_text = day.strftime("%Y%m%d")
        if not _schedule_date_is_eligible(workload, date_text):
            continue
        slots = workload.slots
        if day == today and requested <= today:
            slots = tuple(slot for slot in slots if slot > current_hhmm)
        if not slots:
            continue
        slot = slots[0]
        return {
            "date": date_text,
            "slot": slot,
            "display": f"{date_text} {_display_slot(slot)}",
        }
    return None


_RECEIPT_DATE_FIELDS = ("business_date", "scheduled_date", "target_date")


def _receipt_matches_business_date(
    receipt: dict[str, Any], business_date: str, workload_id: str | None = None,
) -> bool:
    """Keep the receipt on the requested business date by workload contract."""
    if str(receipt.get("business_date") or "") != business_date:
        return False
    if workload_id != "hourly_research":
        return True
    return all(
        str(receipt.get(field) or "") == business_date
        for field in _RECEIPT_DATE_FIELDS
    )


def _latest_receipt(
    workload: WorkloadDefinition,
    receipts: tuple[dict[str, Any], ...],
    business_date: str,
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
    date_bound = [
        receipt for receipt in candidates
        if _receipt_matches_business_date(receipt, business_date, workload.workload_id)
    ]
    if not date_bound:
        invalid_receipt = dict(candidates[-1])
        invalid_receipt.update(
            {
                "status": "CANNOT_CONFIRM",
                "finished_at": None,
                "_task_status_result_code": "EXECUTION_RECEIPT_DATE_MISMATCH",
            }
        )
        return invalid_receipt
    timestamped: list[tuple[datetime, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    for receipt in date_bound:
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


def _first_breakpoint(receipt: dict[str, Any], workload_id: str) -> str:
    """Return the first semantic failure detail carried by a workload receipt."""
    results = receipt.get("workload_results")
    if isinstance(results, list):
        matching = [
            result for result in results
            if isinstance(result, dict)
            and str(result.get("workload_id") or "") == workload_id
        ]
        for result in matching:
            for key in ("reason", "failure_class"):
                value = str(result.get(key) or "").strip()
                if value:
                    return value
    for key in ("reason", "failure_class"):
        value = str(receipt.get(key) or "").strip()
        if value:
            return value
    return ""


def _business_projection(receipt: dict[str, Any] | None, workload_id: str, business_date: str) -> dict[str, Any]:
    """Project a single workload result from an already ledger-validated receipt.

    Receipt presence/freshness concerns the scheduler, never data freshness.
    Missing fields remain None; an artifact can be reused without new capture.
    """
    boolean_fields = ("capture_performed", "collector_invoked", "capture_artifact_verified", "new_capture_verified")
    result: dict[str, Any] = {key: None for key in boolean_fields}
    result.update(capture_status="CANNOT_CONFIRM", data_update_status="CANNOT_CONFIRM",
                  business_data_date=None, business_evidence_status="EXECUTION_RECEIPT_MISSING",
                  business_message="无可验证业务更新证据", business_run_id=None)
    if receipt is None:
        return result
    result["business_run_id"] = receipt.get("run_id")
    if (str(receipt.get("business_date") or "") != business_date
            or receipt.get("_task_status_result_code")):
        result["business_evidence_status"] = "BUSINESS_DATE_MISMATCH" if str(receipt.get("business_date") or "") != business_date else "EXECUTION_RECEIPT_INVALID"
        return result
    workload_results = receipt.get("workload_results")
    if workload_results is not None and not isinstance(workload_results, list):
        result["business_evidence_status"] = "WORKLOAD_RESULT_INVALID"
        return result
    matches = [item for item in (workload_results or [])
               if isinstance(item, dict) and item.get("workload_id") == workload_id]
    if len(matches) != 1:
        result["business_evidence_status"] = "WORKLOAD_RESULT_MISSING" if not matches else "WORKLOAD_RESULT_AMBIGUOUS"
        return result
    item = matches[0]
    result["business_evidence_status"] = "BUSINESS_RESULT_FIELDS_MISSING"
    if not any(key in item for key in (*boolean_fields, "capture_status", "data_update_status")):
        return result
    invalid_boolean = any(key in item and item[key] is not None and type(item[key]) is not bool for key in boolean_fields)
    not_due = item.get("capture_status") == "NOT_DUE" or item.get("data_update_status") == "NOT_DUE_NO_UPDATE"
    conflict = (
        invalid_boolean
        or (not_due and any(item.get(key) is True for key in ("capture_performed", "collector_invoked", "new_capture_verified")))
        or (not_due and item.get("data_update_status") == "UPDATED")
    )
    if item.get("new_capture_verified") is True and item.get("capture_performed") is not True:
        conflict = True
    if conflict:
        result["business_evidence_status"] = "BUSINESS_RESULT_CONFLICT"
        result["business_message"] = "业务字段冲突；不能确认采集或更新"
        for key in ("capture_status", "data_update_status"):
            if isinstance(item.get(key), str) and item[key]:
                result[key] = item[key]
        return result
    for key in boolean_fields:
        result[key] = item.get(key)
    for key in ("capture_status", "data_update_status"):
        if isinstance(item.get(key), str) and item[key]:
            result[key] = item[key]
    # Do not infer market data date from the scheduler date or an old artifact.
    result["business_data_date"] = item.get("business_data_date") or item.get("source_date") or item.get("snapshot_date")
    result["business_evidence_status"] = "WORKLOAD_RESULT_PROJECTED"
    if not_due:
        # NOT_DUE is a producer statement; keep absence of explicit booleans unknown.
        if all(item.get(k) is False for k in ("capture_performed", "collector_invoked", "new_capture_verified")):
            result["business_message"] = "未到采集时段；未调用采集；未更新"
        else:
            result["business_message"] = "未到采集时段；采集和更新字段未完整记录"
    elif result["new_capture_verified"] is True:
        result["business_message"] = "回执声明新采集已验证；来源日期与质量仍须分别核验"
    elif result["capture_artifact_verified"] is True:
        result["business_message"] = "已有精确产物已验证；不代表完成新采集"
    else:
        result["business_message"] = "调度结果不代表业务更新；见采集字段及失败原因"
    return result


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
    due = _next_due(workload, business_date, now)
    row = {
        "workload_id": workload.workload_id,
        "enabled": workload.enabled,
        "status": status,
        "last_run": receipt.get("finished_at") if receipt else None,
        "next_due": due["display"] if due else None,
        "next_due_date": due["date"] if due else None,
        "next_due_slot": _display_slot(due["slot"]) if due else None,
        "next_due_reason": (
            "DISABLED" if not workload.enabled else "NO_ELIGIBLE_SLOT"
            if due is None else "HISTORICAL_DATE_NEXT_ELIGIBLE_SLOT"
            if business_date < now.strftime("%Y%m%d") else "NEXT_ELIGIBLE_SLOT"
        ),
        "duration_ms": receipt.get("duration_ms") if receipt else None,
        "result_code": result_code,
        "freshness": (
            "CURRENT"
            if receipt and str(receipt.get("status") or "") != "CANNOT_CONFIRM"
            else "NOT_DUE"
            if status == "PENDING_NOT_DUE"
            else "NOT_OBSERVED"
        ),
        "receipt_path": receipt.get("receipt_path") if receipt else None,
    }
    row["receipt_freshness"] = row["freshness"]
    row.update(_business_projection(receipt, workload.workload_id, business_date))
    if receipt:
        breakpoint = _first_breakpoint(receipt, workload.workload_id)
        if breakpoint:
            row["breakpoint"] = breakpoint
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
        receipt = _latest_receipt(workload, receipts, business_date)
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
        "freshness": (
            "CURRENT"
            if (
                (receipt is not None and str(receipt.get("status") or "") != "CANNOT_CONFIRM")
                or status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS", "READY_WITH_REVIEW_BOUNDARY", "SUCCESS", "SUCCEEDED", "ACTION_RAN_WITH_CANNOT_CONFIRM", "BACKFILLED_ARTIFACT_READY"}
            )
            else "NOT_DUE"
            if status == "PENDING_NOT_DUE"
            else "NOT_OBSERVED"
        ),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _scheduler_observation(ledger: ExecutionLedger, business_date: str,
                           receipts: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Evidence lens only; catalog owner != installed job != live process."""
    result: dict[str, Any] = {
        "business_date": business_date, "status": "NO_SAME_DATE_RECEIPT",
        "receipt_count": len(receipts), "process_status": "CANNOT_CONFIRM",
        "catalog_scope": "CONFIGURATION_ONLY", "logical_row_evidence": "DECLARED_ONLY",
        "receipt_namespace": f"receipts/live/{business_date}",
        "message": "配置中的owner不证明进程存活；禁用图谱登记与实际调度回执分开显示。",
    }
    if not receipts:
        return result
    date_bound_receipts = tuple(
        receipt for receipt in receipts
        if _receipt_matches_business_date(
            receipt,
            business_date,
            "hourly_research"
            if "hourly_research" in (receipt.get("selected_workload_ids") or [])
            else None,
        )
    )
    if len(date_bound_receipts) != len(receipts):
        result.update(
            status="RECEIPT_DATE_MISMATCH",
            logical_row_evidence="DATE_BOUND_RECEIPT_REJECTED",
            date_bound_receipt_count=len(date_bound_receipts),
            date_binding_reason="BUSINESS_SCHEDULED_TARGET_DATE_MUST_MATCH",
        )
        return result
    try:
        valid, _ = ledger.verify_receipt_chain(business_date, mode="LIVE")
    except (OSError, ValueError, TypeError, KeyError):
        valid = False
    result["status"] = "RECEIPT_CHAIN_VERIFIED" if valid else "RECEIPT_INVALID"
    if valid:
        result.update(last_receipt_status=str(date_bound_receipts[-1].get("status") or "CANNOT_CONFIRM"),
                      last_receipt_run_id=str(date_bound_receipts[-1].get("run_id") or ""),
                      last_finished_at=str(date_bound_receipts[-1].get("finished_at") or ""),
                      logical_row_evidence="SAME_DATE_LEDGER_CHAIN")
    return result


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
            _latest_receipt(workload, receipts, business_date),
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
        "scheduler_observation": _scheduler_observation(ledger, business_date, receipts),
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
