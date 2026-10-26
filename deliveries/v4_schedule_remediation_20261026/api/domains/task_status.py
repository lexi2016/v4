"""Truthful task identity and same-date execution status projection."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import re
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
from infrastructure.scheduling.execution_ledger import ExecutionLedger, _ledger_digest
from infrastructure.owned_io import SafeRoot
from infrastructure.interprocess_lock import _pid_is_alive as _scheduler_pid_alive
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
        "hk_securities": states.get("hk_securities"),
    }
    if policy is RunPolicy.A_SHARE_TRADE_DAY:
        return eligible["a_share"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
    if policy is RunPolicy.HK_CONNECT_TRADE_DAY:
        return eligible["hk_connect"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
    if policy is RunPolicy.HK_SECURITIES_TRADE_DAY:
        return eligible["hk_securities"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
    if policy is RunPolicy.A_OR_HK_CONNECT_TRADE_DAY:
        return any(
            state not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
            for state in (eligible["a_share"], eligible["hk_connect"])
        )
    if policy is RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY:
        return any(
            state not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}
            for state in (eligible["a_share"], eligible["hk_securities"])
        )
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


def _closing_task_projection(
    item: dict[str, Any], receipt: dict[str, Any] | None,
    dispatch: dict[str, Any] | None, *, business_date: str,
    receipt_path: str | None, chain_verified: bool, not_due: bool,
    workload: WorkloadDefinition | None = None,
) -> dict[str, Any]:
    """Project business state, retaining gaps in legacy execution bindings.

    Dispatch success is only an execution fact. READY additionally needs an
    exact business receipt bound to that dispatch's workload result and run.
    """
    result: dict[str, Any] = {
        "business_date": business_date, "task_state": "CANNOT_CONFIRM",
        "binding_status": "CANNOT_CONFIRM", "run_id": None,
        "business_run_id": receipt.get("run_id") if receipt else None,
        "receipt_sha256": None,
    }
    if receipt is None:
        if not_due:
            result["task_state"] = "PLANNED"
        return result
    raw_status = str(receipt.get("status") or "CANNOT_CONFIRM").upper()
    is_dispatch = "selected_workload_ids" in receipt
    dates = [receipt.get(key) for key in ("business_date", "date", "trade_date") if key in receipt]
    identity_valid = bool(dates) and all(value == business_date for value in dates)
    identity_valid = identity_valid and (
        item.get("workload_id") in (receipt.get("selected_workload_ids") or [])
        if is_dispatch else receipt.get("node_id") == item["node_id"]
    )
    identity_valid = identity_valid and receipt.get("owner_id", item["owner_id"]) == item["owner_id"]
    if not identity_valid:
        result["binding_reason"] = "BUSINESS_RECEIPT_DATE_OR_NODE_MISMATCH"
        return result
    # Reuse the dispatcher's date-role resolver. The dispatch target is a
    # request context (possibly the next session), not every node's business
    # target. Unknown roles or a contradictory declared resolution cannot
    # establish READY.
    resolved_dates: dict[str, str] | None = None
    if workload is not None:
        if (workload.workload_id != item.get("workload_id")
                or workload.owner_id != item["owner_id"]
                or any(role not in {"BUSINESS_DATE", "SCHEDULED_DATE", "TARGET_DATE"}
                       for role in (workload.scheduled_date_role, workload.signal_date_role, workload.target_date_role))):
            result["binding_reason"] = "BUSINESS_DATE_ROLE_UNCONFIRMED"
            return result
        if dispatch is not None:
            try:
                from contracts.runtime_tasks import DispatchMode, DispatchRequest
                from infrastructure.scheduling.dispatcher import _resolved_dates
                request = DispatchRequest(
                    scheduled_date=dispatch["scheduled_date"],
                    business_date=dispatch["business_date"],
                    target_date=dispatch["target_date"],
                    slot=dispatch.get("slot") or item["planned_slot"],
                    mode=DispatchMode(str(dispatch["mode"]).upper()),
                )
                if request.mode is not DispatchMode.LIVE:
                    raise ValueError("closing status requires LIVE date roles")
                resolved_dates = _resolved_dates(workload, request)
                declared = dispatch.get("resolved_dates", {})
                if (not isinstance(declared, dict)
                        or (workload.workload_id in declared and declared[workload.workload_id] != resolved_dates)):
                    raise ValueError("declared workload date roles conflict")
            except (KeyError, ValueError, TypeError, AttributeError):
                resolved_dates = None
    if not is_dispatch:
        date_fields = ("scheduled_date", "signal_date", "target_date")
        if (any(key in receipt and (resolved_dates is None or receipt[key] != resolved_dates[key]) for key in date_fields)
                or (workload is not None and workload.target_date_role == "TARGET_DATE" and "target_date" not in receipt)):
            result["binding_reason"] = "BUSINESS_RECEIPT_DATE_ROLE_MISMATCH_OR_UNCONFIRMED"
            return result
    if receipt_path:
        try:
            path = Path(receipt_path)
            raw = path.read_bytes()
            if path.is_symlink() or json.loads(raw) != receipt:
                raise ValueError("receipt changed")
            result["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, UnicodeError):
            # Aggregate receipts may carry a relative receipt_path. Their
            # integrity comes from the ledger chain below, never this path.
            if not is_dispatch:
                result["binding_reason"] = "BUSINESS_RECEIPT_CHANGED_OR_UNREADABLE"
                return result
    workload_results = (dispatch or {}).get("workload_results")
    matches = [row for row in (workload_results if isinstance(workload_results, list) else [])
               if isinstance(row, dict) and row.get("workload_id") == item.get("workload_id")]
    dispatch_valid = bool(
        dispatch and chain_verified and resolved_dates is not None
        and all(dispatch.get(key) == business_date for key in ("business_date", "scheduled_date"))
        and str(dispatch.get("mode") or "").upper() == "LIVE"
        and dispatch.get("owner_id", item["owner_id"]) == item["owner_id"]
        and isinstance(dispatch.get("run_id"), str) and dispatch.get("run_id") and not dispatch.get("_task_status_result_code")
        and item.get("workload_id") in (dispatch.get("selected_workload_ids") or [])
        and len(matches) == 1
        and all(dispatch.get(flag) is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    )
    if dispatch_valid:
        result["dispatch_run_id"] = dispatch["run_id"]
        if is_dispatch and receipt.get("run_id") == dispatch["run_id"]:
            result["run_id"] = dispatch["run_id"]
            result["binding_status"] = "DISPATCH_RUN_VERIFIED"
    if is_dispatch:
        # Aggregate status includes unrelated workloads in the same batch.
        # Only this node's unique, verified workload result can classify it.
        raw_status = (str(matches[0].get("status") or "CANNOT_CONFIRM").upper()
                      if dispatch_valid and receipt == dispatch else "CANNOT_CONFIRM")
    if raw_status in {"FAILED", "FAIL", "ERROR", "EXPIRED", "CALENDAR_BLOCKED"}:
        result["task_state"] = "FAILED"
    elif raw_status.startswith("PARTIAL"):
        result["task_state"] = "PARTIAL"
    elif raw_status in {"QUEUED", "QUEUED_BEHIND", "RUNNING", "LATE_RUNNING", "WAITING_DEPENDENCY", "WAITING_SOURCE", "WAITING_SOURCE_UPDATE", "UPSTREAM_NOT_READY", "BLOCKED"}:
        result["task_state"] = (
            "QUEUED" if raw_status.startswith("QUEUED") else "RUNNING" if raw_status in {"RUNNING", "LATE_RUNNING"} else "WAITING_DEPENDENCY"
        )
    business_bound = False
    if (dispatch_valid and not is_dispatch and receipt.get("run_id")
            and matches[0].get("status") in {"SUCCEEDED", "ALREADY_EXISTS"}):
        # Existing native runners print their business receipt as JSON. A
        # truncated stdout or absent run identity cannot bind that receipt.
        try:
            output = json.loads(str(matches[0].get("stdout") or ""))
        except (ValueError, TypeError):
            output = None
        business_bound = isinstance(output, dict) and output == receipt
    if (business_bound and all(receipt.get(flag) is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
            and raw_status in {"READY", "READY_EMPTY", "READY_WITH_ROWS", "READY_WITH_REVIEW_BOUNDARY", "SUCCESS"}):
        result.update(task_state="READY", run_id=dispatch["run_id"], binding_status="BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN")
    if result["task_state"] == "CANNOT_CONFIRM":
        result["binding_reason"] = "BUSINESS_RESULT_OR_RUN_BINDING_UNCONFIRMED"
    return result


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
    chain_verified: bool = False,
) -> dict[str, Any]:
    workload_id = item.get("workload_id")
    workload = next(
        (row for row in catalog.workloads if row.workload_id == workload_id), None
    )
    if (item["node_id"] == "hkconnect_model_selection_review"
            and workload is not None and workload.slots):
        # The visible trigger follows the active workload. Keep the older
        # timeline contract slot as provenance; do not rewrite either contract.
        contract_slot = item["planned_slot"]
        scheduled_slot = workload.slots[0]
        item = {
            **item,
            "planned_slot": scheduled_slot,
            "label": item["label"].replace(_display_slot(contract_slot), _display_slot(scheduled_slot), 1),
            "contract_planned_slot": contract_slot,
            "planned_time_source": "WORKLOAD_CATALOG",
        }
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
        if receipt is None and workload is not None:
            # Scheduler results are useful for failures/in-flight state, but
            # their success cannot stand in for a missing business receipt.
            receipt = _latest_receipt(workload, receipts, business_date)
            receipt_path = str((receipt or {}).get("receipt_path") or "") or None
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
    row = {
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
    if int(item["position"]) > 8:
        dispatch = _latest_receipt(workload, receipts, business_date) if workload is not None else None
        row.update(_closing_task_projection(
            item, receipt, dispatch, business_date=business_date,
            receipt_path=receipt_path, chain_verified=chain_verified,
            not_due=_timeline_not_due(item, business_date, now),
            workload=workload,
        ))
        if row.get("binding_reason"):
            row["reason"] = f"{row['reason']} · {row['binding_reason']}"
    return row



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


# Process observations are a bounded, separate lens over existing catalog slots.
# They never enter the dispatch chain or the business READY verifier.
_SCHEDULER_OBSERVATION_MAX_FILES = 512
_SCHEDULER_OBSERVATION_MAX_BYTES = 16384
_SCHEDULER_OBSERVATION_STATES = {
    "QUEUED", "QUEUED_BEHIND", "RUNNING", "RUNNING_CANNOT_CONFIRM",
    "FINISHED", "FINISHED_CANNOT_CONFIRM", "EXPIRED", "CHILD_START_FAILED",
    "CLAIM_OR_RECEIPT_BLOCKED",
}


def _observation_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("OBSERVATION_TIMESTAMP_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("OBSERVATION_TIMESTAMP_NAIVE")
    return parsed


def _latest_slot_observation(values: list[dict[str, Any]]) -> dict[str, Any]:
    # UUID order/mtime are not event order. queued_at distinguishes episodes.
    key = max((_observation_time(v["observed_at"]), _observation_time(v["queued_at"])) for v in values)
    tied = {v["ledger_sha256"]: v for v in values
            if (_observation_time(v["observed_at"]), _observation_time(v["queued_at"])) == key}
    if len(tied) == 1:
        return next(iter(tied.values()))
    states = {v["status"] for v in tied.values()}
    queues = {"QUEUED", "QUEUED_BEHIND"}
    # Writer enqueue -> start -> finish are causal transitions even when the
    # pulse clock is identical. Conflicting same-phase facts remain unknown.
    if len(states & queues) > 1:
        raise ValueError("AMBIGUOUS_OBSERVATION_TIE")
    later = states - queues
    if later <= {"RUNNING", "FINISHED", "FINISHED_CANNOT_CONFIRM"}:
        if {"FINISHED", "FINISHED_CANNOT_CONFIRM"} <= later:
            raise ValueError("AMBIGUOUS_OBSERVATION_TIE")
        selected = "FINISHED" if "FINISHED" in later else "FINISHED_CANNOT_CONFIRM" if "FINISHED_CANNOT_CONFIRM" in later else "RUNNING"
        process = [v for v in tied.values() if v["status"] not in queues]
        if len({(v.get("pid"), v.get("actual_started_at")) for v in process}) != 1:
            raise ValueError("AMBIGUOUS_OBSERVATION_PROCESS")
    elif len(later) == 1 and later <= {"CHILD_START_FAILED", "CLAIM_OR_RECEIPT_BLOCKED"}:
        selected = next(iter(later))
    else:
        raise ValueError("AMBIGUOUS_OBSERVATION_TIE")
    winners = [v for v in tied.values() if v["status"] == selected]
    if len(winners) != 1:
        raise ValueError("AMBIGUOUS_OBSERVATION_TIE")
    return winners[0]


def _load_scheduler_slot_observations(
    ledger: ExecutionLedger, catalog: RuntimeCatalog, business_date: str, now: datetime,
) -> dict[str, dict[str, Any]]:
    slots = sorted({slot for workload in catalog.workloads if workload.enabled for slot in workload.slots})
    io = SafeRoot(ledger.root)
    prefix = f"scheduler_observations/live/{business_date}"
    result: dict[str, dict[str, Any]] = {}
    count = 0
    for slot in slots:
        values: list[dict[str, Any]] = []
        observation_seen = False
        try:
            with io.directory(f"{prefix}/{slot}") as directory:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if not entry.name.endswith(".observation.json"):
                            continue  # atomic writer temporary files are not observations
                        observation_seen = True
                        count += 1
                        if count > _SCHEDULER_OBSERVATION_MAX_FILES:
                            return {s: {"status": "CANNOT_CONFIRM", "reason": "OBSERVATION_FILE_BUDGET_EXCEEDED"} for s in slots}
                        if not re.fullmatch(r"[0-9a-f]{32}\.observation\.json", entry.name):
                            raise ValueError("OBSERVATION_FILENAME_INVALID")
                        relative = f"{prefix}/{slot}/{entry.name}"
                        value = json.loads(io.read_bytes(relative, max_bytes=_SCHEDULER_OBSERVATION_MAX_BYTES))
                        if (not isinstance(value, dict) or value.get("schema_version") != "v4.scheduler_observation.v1"
                                or value.get("business_date") != business_date or value.get("slot") != slot
                                or value.get("status") not in _SCHEDULER_OBSERVATION_STATES
                                or value.get("lane") != ("A_LONG" if slot == "1700" else "DEFAULT")
                                or value.get("prev_ledger_sha256") != ""
                                or any(value.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
                                or value.get("ledger_sha256") != _ledger_digest(value)):
                            raise ValueError("OBSERVATION_IDENTITY_OR_HASH_INVALID")
                        planned, queued, observed, cutoff = (_observation_time(value.get(key)) for key in ("planned_at", "queued_at", "observed_at", "cutoff_at"))
                        if (planned.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H%M%S%f") != business_date + slot + "00000000"
                                or not planned <= queued <= observed <= now or cutoff < planned):
                            raise ValueError("OBSERVATION_TIME_ORDER_INVALID")
                        state = value["status"]
                        if state in {"QUEUED", "QUEUED_BEHIND"} and observed > cutoff:
                            raise ValueError("QUEUED_OBSERVATION_PAST_CUTOFF")
                        if state == "EXPIRED" and (observed <= cutoff or value.get("reason") not in {"ORIGINAL_SLOT_CUTOFF_PASSED", "QUEUED_PAST_ORIGINAL_CUTOFF"}):
                            raise ValueError("EXPIRED_OBSERVATION_TIME_INVALID")
                        if state in {"RUNNING", "FINISHED", "FINISHED_CANNOT_CONFIRM"}:
                            started = _observation_time(value.get("actual_started_at"))
                            if (not queued <= started <= observed or started > cutoff
                                    or type(value.get("pid")) is not int or value["pid"] <= 0):
                                raise ValueError("OBSERVATION_PROCESS_INVALID")
                        values.append({**value, "observation_path": relative})
            if values:
                result[slot] = _latest_slot_observation(values)
        except FileNotFoundError:
            if observation_seen:
                result[slot] = {"status": "CANNOT_CONFIRM", "reason": "OBSERVATION_DISAPPEARED_DURING_READ"}
            continue  # legacy ledger has no observation namespace
        except (OSError, ValueError, TypeError, KeyError) as error:
            result[slot] = {"status": "CANNOT_CONFIRM", "reason": str(error) or type(error).__name__}
    return result


def _observation_process_state(
    observation: dict[str, Any], workload: WorkloadDefinition, ledger: ExecutionLedger,
    business_date: str, receipts: tuple[dict[str, Any], ...], now: datetime,
) -> tuple[str, str | None, str]:
    if (observation.get("workload_id", workload.workload_id) != workload.workload_id
            or observation.get("owner_id", workload.owner_id) != workload.owner_id):
        return "CANNOT_CONFIRM", None, "OBSERVATION_CATALOG_IDENTITY_MISMATCH"
    state = observation.get("status")
    if state in {"QUEUED", "QUEUED_BEHIND"}:
        if now > _observation_time(observation["cutoff_at"]):
            return "CANNOT_CONFIRM", None, "STALE_QUEUE_OBSERVATION_PAST_CUTOFF"
        return "QUEUED", None, "CATALOG_DATE_SLOT_ONLY"
    if state in {"EXPIRED", "CHILD_START_FAILED"}:
        return "FAILED", None, "SCHEDULER_SLOT_OBSERVATION_ONLY"
    if state != "RUNNING":
        return "CANNOT_CONFIRM", None, str(observation.get("reason") or "PROCESS_OBSERVATION_NOT_BUSINESS_RESULT")
    try:
        slot = observation["slot"]
        io = SafeRoot(ledger.root)
        dispatch = json.loads(io.read_bytes(f"claims/live/{business_date}/{slot}/dispatch.claim.json", max_bytes=16384))
        claim = json.loads(io.read_bytes(f"workloads/live/{business_date}/{slot}/{workload.workload_id}.workload-claim.json", max_bytes=16384))
        for value, schema in ((dispatch, "v3_5.dispatch_claim.v1"), (claim, "v3_5.workload_claim.v1")):
            if (not isinstance(value, dict) or value.get("schema_version") != schema
                    or any(value.get(key) != expected for key, expected in (("business_date", business_date), ("scheduled_date", business_date), ("slot", slot), ("mode", "LIVE"), ("pid", observation["pid"])))
                    or type(value.get("pid")) is not int
                    or value.get("owner_id", workload.owner_id) != workload.owner_id
                    or not isinstance(value.get("run_id"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value["run_id"])
                    or not isinstance(value.get("target_date"), str) or not re.fullmatch(r"[0-9]{8}", value["target_date"])
                    or not _observation_time(observation["actual_started_at"]) <= _observation_time(value.get("created_at")) <= now):
                raise ValueError("OBSERVATION_CLAIM_IDENTITY_MISMATCH")
            datetime.strptime(value["target_date"], "%Y%m%d")
        if (claim.get("workload_id") != workload.workload_id
                or claim["run_id"] != dispatch["run_id"] or claim.get("target_date") != dispatch.get("target_date")
                or any(r.get("run_id") == claim["run_id"] for r in receipts)
                or not _scheduler_pid_alive(observation["pid"])):
            raise ValueError("OBSERVATION_CLAIM_NOT_RUNNING")
        return "RUNNING", claim["run_id"], "EXACT_WORKLOAD_CLAIM_PID"
    except (OSError, ValueError, TypeError, KeyError) as error:
        return "CANNOT_CONFIRM", None, str(error) or type(error).__name__


def _apply_scheduler_slot_observation(
    row: dict[str, Any], workload: WorkloadDefinition, observations: dict[str, dict[str, Any]],
    ledger: ExecutionLedger, business_date: str, receipts: tuple[dict[str, Any], ...], now: datetime,
    *, timeline: bool = False,
) -> dict[str, Any]:
    if not workload.enabled:
        return row
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from domains.runtime_policy import evaluate_run_policy
    from infrastructure.scheduling.dispatcher import _cadence_eligible
    candidates = []
    for slot in workload.slots:
        if slot not in observations:
            continue
        decision = evaluate_run_policy(workload.run_policy, business_date, slot,
                                       market_scope=workload.market_scope,
                                       session_requirement=workload.session_requirement)
        # These existing filters define which workloads a slot can select.
        # Target does not participate in either eligibility/cadence decision.
        request = DispatchRequest(business_date, business_date, business_date, slot, DispatchMode.LIVE)
        if decision.eligible and _cadence_eligible(workload, request):
            candidates.append(observations[slot])
    if not candidates:
        return row
    invalid = [value for value in candidates if value.get("status") == "CANNOT_CONFIRM"]
    if invalid:
        observation = invalid[0]
    else:
        newest = max(_observation_time(value["observed_at"]) for value in candidates)
        tied = [value for value in candidates if _observation_time(value["observed_at"]) == newest]
        observation = tied[0] if len(tied) == 1 else {"status": "CANNOT_CONFIRM", "reason": "AMBIGUOUS_WORKLOAD_SLOT_OBSERVATIONS"}
    state, run_id, binding = _observation_process_state(observation, workload, ledger, business_date, receipts, now)
    detail = {**observation, "task_state": state, "binding_status": binding,
              "workload_id": workload.workload_id, "owner_id": workload.owner_id,
              "run_id": run_id, "business_ready": False, "process_liveness": "VERIFIED_CLAIM_PID" if state == "RUNNING" else "CANNOT_CONFIRM"}
    result = {**row, "scheduler_execution": detail}
    # Never erase a verified business READY or a newer terminal receipt.
    if row.get("task_state") == "READY":
        return result
    if row.get("last_run"):
        try:
            last_result = _observation_time(row["last_run"])
            if (state == "CANNOT_CONFIRM" or "observed_at" not in observation
                    or last_result >= _observation_time(observation["observed_at"])):
                return result
        except ValueError:
            pass
    result["reason"] = str(observation.get("reason") or observation.get("status"))
    if timeline:
        result.update(task_state=state, binding_status=binding, run_id=run_id)
    else:
        result["status"] = str(observation["status"]) if state != "CANNOT_CONFIRM" else "CANNOT_CONFIRM"
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
    scheduler_observation = _scheduler_observation(ledger, business_date, receipts)
    # An unrelated workload's semantic date mismatch must not erase a valid
    # closing workload. Verify the ledger, then bind each closing receipt's
    # own date/owner/run independently below.
    try:
        closing_chain_verified, _ = ledger.verify_receipt_chain(business_date, mode="LIVE")
    except (OSError, ValueError, TypeError, KeyError):
        closing_chain_verified = False
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
            chain_verified=closing_chain_verified,
        )
        for item in CLOSE_TIMELINE
    ]
    slot_observations = _load_scheduler_slot_observations(ledger, catalog, business_date, current_time)
    workloads_by_id = {workload.workload_id: workload for workload in catalog.workloads}
    logical = [
        _apply_scheduler_slot_observation(row, workloads_by_id[row["workload_id"]], slot_observations,
                                          ledger, business_date, receipts, current_time)
        for row in logical
    ]
    timeline_nodes = [
        _apply_scheduler_slot_observation(row, workloads_by_id[row["workload_id"]], slot_observations,
                                          ledger, business_date, receipts, current_time, timeline=True)
        if int(row["position"]) > 8 and row.get("workload_id") in workloads_by_id else row
        for row in timeline_nodes
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
        "scheduler_observation": scheduler_observation,
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
