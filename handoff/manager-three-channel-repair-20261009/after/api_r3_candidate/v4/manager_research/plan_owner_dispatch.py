"""Bounded loopback RPC to the API's fully injected ManagerResearch owner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlencode

from infrastructure.owned_io import SafeRoot
from .workspace_projection import HK, FLAGS, date_token

APP_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "v4.manager_research.bound_plan_cycle.v1"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
PARENT_TRIGGER_SCHEMA = "v4.manager_research.bound_plan_cycle_trigger.v1"
DISPATCH_SCHEMA = "v4.manager_research.plan_dispatch_attempt.v1"
MAX_DISPATCH_RECEIPTS = 2048
MAX_FAILED_DISPATCHES = 3
MAX_RESPONSE_BYTES = 256 * 1024
KNOWN_RPC_HTTP_ERROR_DETAILS = frozenset({"SCHEDULED_WORKSPACE_OWNER_FAILED"})
REJECTION_SCHEMA = "v4.manager_research.plan_owner_rejection.v1"
# Only this bounded vocabulary crosses the API error boundary. A matching
# exception string after admission is never evidence the owner was not called.
PLAN_OWNER_GATE_CODES = frozenset({
    "PLAN_OWNER_SERVER_BINDING_NOT_CONFIGURED", "PLAN_OWNER_BINDING_PATH_NOT_EXACT",
    "PLAN_OWNER_BINDING_UNAVAILABLE", "PLAN_OWNER_BINDING_SHA_MISMATCH",
    "PLAN_OWNER_BINDING_JSON_INVALID", "PLAN_OWNER_BINDING_DISABLED",
    "PLAN_OWNER_DAILY_BINDING_DISABLED", "PLAN_OWNER_STATE_OR_MASTER_ROOT_MISMATCH",
    "PLAN_OWNER_BINDING_API_ROOT_MISMATCH", "PLAN_OWNER_BINDING_CONTRACT_INVALID",
    "PLAN_OWNER_BINDING_ROOTS_OVERLAP", "PLAN_OWNER_BINDING_ROOT_MISSING",
    "PLAN_OWNER_BINDING_INVENTORY_INVALID", "PLAN_OWNER_BINDING_CLOSED_INVENTORY_MISMATCH",
    "PLAN_OWNER_BINDING_REQUIRES_PLAN_ONLY_MODE", "PLAN_OWNER_ADMISSION_FAILED",
    "PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH", "PLAN_OWNER_CLOCK_MUST_BE_AWARE",
    "ANNOUNCEMENT_BINDING_CONTRACT_INVALID", "ANNOUNCEMENT_BINDING_CWD_MISMATCH",
    "ANNOUNCEMENT_BINDING_PATH_INVALID", "ANNOUNCEMENT_BINDING_PATH_NOT_EXACT",
    "ANNOUNCEMENT_BINDING_ROOTS_OVERLAP", "ANNOUNCEMENT_BINDING_ROOT_MISSING",
    "ANNOUNCEMENT_BINDING_INVENTORY_INVALID", "ANNOUNCEMENT_BINDING_CLOSED_INVENTORY_MISMATCH",
    "ANNOUNCEMENT_BINDING_INTERPRETER_SHA_MISMATCH", "ANNOUNCEMENT_BINDING_SOURCE_SYMLINK",
    "ANNOUNCEMENT_BINDING_SOURCE_ROOT_MISSING", "ANNOUNCEMENT_BINDING_SOURCE_BYTE_BUDGET",
    "ANNOUNCEMENT_BINDING_INVENTORY_TOO_LARGE", "PLAN_MATERIAL_REFRESH_ONLY_CONFIG_INVALID",
    "PLAN_REFRESH_CANARY_REQUIRED", "PLAN_REFRESH_CANARY_SHA_MISMATCH",
    "PLAN_REFRESH_CANARY_OWNER_IDENTITY_MISMATCH", "PLAN_REFRESH_CANARY_CONTRACT_INVALID",
    "PLAN_REFRESH_CANARY_SOURCE_MIGRATION_UNEXPECTED", "PLAN_REFRESH_CANARY_RESPONSE_INVALID",
    "PLAN_REFRESH_CANARY_RESPONSE_SHA_MISMATCH", "PLAN_REFRESH_CANARY_RESPONSE_READBACK_MISMATCH",
    "PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID", "PLAN_REFRESH_CANNOT_REUSE_ANNOUNCEMENT_RECEIPT",
})
RPC_FAILURE_CODES = frozenset({
    "PLAN_OWNER_RPC_FAILED", "PLAN_OWNER_RPC_TRANSPORT_FAILED", "PLAN_OWNER_RPC_RESPONSE_TOO_LARGE",
    "PLAN_OWNER_RPC_CONTENT_TYPE_INVALID", "PLAN_OWNER_RPC_RESPONSE_JSON_INVALID",
    "PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID", "SCHEDULED_WORKSPACE_OWNER_FAILED",
}) | PLAN_OWNER_GATE_CODES | frozenset(f"PLAN_OWNER_RPC_HTTP_{status}" for status in range(100, 600))
OWNER_FAILURE_CODES = frozenset({
    "PLAN_OWNER_EXECUTION_FAILED", "PLAN_OWNER_EXECUTION_TIMEOUT",
    "PLAN_OWNER_PARENT_TRIGGER_BRANCH_READBACK_MISMATCH", "PLAN_OWNER_PRODUCT_READBACK_INVALID",
    "PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION", "PLAN_OWNER_EVENING_TARGET_MISMATCH",
})


class PlanOwnerAdmissionError(ValueError):
    """Raised only within the read-only gate, before either research owner."""
    def __init__(self, reason: str):
        self.reason = reason if reason in PLAN_OWNER_GATE_CODES else "PLAN_OWNER_ADMISSION_FAILED"
        super().__init__(self.reason)

    def detail(self, target_date: str, binding_sha256: str) -> dict[str, Any]:
        return {"schema_version": REJECTION_SCHEMA, "status": "GATE_REJECTED",
            "owner": OWNER, "reason": self.reason, "failure_stage": "ADMISSION",
            "owner_execution_status": "OWNER_NOT_CALLED", "target_trade_date": target_date,
            "binding_sha256": binding_sha256, **FLAGS}


def local_admission_failure(exc: Exception) -> dict[str, Any]:
    """For the worker's binding load, before constructing an RPC connection."""
    reason = "PLAN_OWNER_BINDING_UNAVAILABLE" if isinstance(exc, OSError) else str(exc)
    error = PlanOwnerAdmissionError(reason)
    return {"status": "FAILED", "reason": error.reason, "failure_stage": "ADMISSION",
        "owner_execution_status": "OWNER_NOT_CALLED", "network_requests": 0, "state_writes": 0, **FLAGS}


def rpc_call_failure(exc: Exception) -> dict[str, Any]:
    """A caller exception is not proof of remote non-execution."""
    reason = str(exc)
    return {"status": "FAILED", "reason": reason if reason in RPC_FAILURE_CODES else "PLAN_OWNER_RPC_FAILED",
        "failure_stage": "READBACK", "owner_execution_status": "CANNOT_CONFIRM",
        "outcome": "OWNER_READBACK_REQUIRED_NO_RETRY", **FLAGS}


def clock_now() -> datetime:
    return datetime.now(HK)


def _raw_binding(path: str | Path) -> bytes:
    value = Path(path).expanduser()
    if not value.is_absolute() or ".." in value.parts or value.resolve() != value:
        raise ValueError("PLAN_OWNER_BINDING_PATH_NOT_EXACT")
    return SafeRoot(value.parent).read_bytes(value.name, max_bytes=1024 * 1024)


def _expected_target(binding: Mapping[str, Any], now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    from ops.run_manager_announcement_cycle import scheduled_cycle_target
    return scheduled_cycle_target(source_date, now=now,
        plan_config=binding.get("plan_material_refresh"),
        preopen_config=binding.get("preopen_plan"),
        morning_plan_config=binding.get("morning_plan")) or ""


def _expected_branch(binding: Mapping[str, Any], now: datetime) -> str | None:
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    from ops.run_manager_announcement_cycle import scheduled_cycle_branch
    return scheduled_cycle_branch(now.astimezone(HK).strftime("%Y%m%d"), now=now,
        plan_config=binding.get("plan_material_refresh"),
        preopen_config=binding.get("preopen_plan"), morning_plan_config=binding.get("morning_plan"))


def _parent_trigger_identity(source_date: str, target_date: str, branch: str,
                             binding_sha256: str, *, scheduled_slot: str | None = None) -> dict[str, str]:
    source = date_token(source_date)
    target = date_token(target_date)
    if branch not in {"MORNING", "PREOPEN", "EVENING_NEXT_SESSION", "SAME_DAY_CATCHUP"}:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BRANCH_INVALID")
    if (branch in {"MORNING", "PREOPEN", "SAME_DAY_CATCHUP"}) != (source == target):
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_DATE_BRANCH_MISMATCH")
    if not re.fullmatch(r"[0-9a-f]{64}", str(binding_sha256 or "")):
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BINDING_SHA_INVALID")
    identity = {
        "schema_version": PARENT_TRIGGER_SCHEMA,
        "trigger_kind": "BOUND_SCHEDULED_PLAN_CYCLE",
        "source_trade_date": source,
        "target_trade_date": target,
        "branch": branch,
        "binding_sha256": binding_sha256,
    }
    if branch in {"MORNING", "SAME_DAY_CATCHUP"}:
        if not isinstance(scheduled_slot, str) or not re.fullmatch(source + r"T\d{4}", scheduled_slot):
            raise ValueError("PLAN_OWNER_PARENT_TRIGGER_SLOT_INVALID")
        identity["scheduled_slot"] = scheduled_slot
    elif scheduled_slot is not None:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_SLOT_UNEXPECTED")
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return {**identity, "trigger_id": hashlib.sha256(canonical).hexdigest()}


def _parent_trigger_receipt(identity: Mapping[str, str], *, now: datetime,
                            result: Mapping[str, Any]) -> dict[str, Any]:
    plan = result.get("plan_result")
    plan = plan if isinstance(plan, Mapping) else {}
    status = result.get("status")
    if status not in {"SUCCEEDED", "PARTIAL", "FAILED"}:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_RESULT_STATUS_INVALID")
    plan_status = plan.get("status")
    from ops.run_manager_announcement_cycle import valid_owner_plan_result
    owner_readback = "VERIFIED" if (valid_owner_plan_result(plan, str(identity.get("branch")))
        and plan.get("target_trade_date") == identity.get("target_trade_date")) else "UNVERIFIED"
    existing_statuses = {
        "ALREADY_CURRENT", "ALREADY_MATERIALIZED", "PRESERVED_SCHEDULED_PREOPEN",
    }
    identity_source = plan.get("execution_kind_source")
    if identity_source != "OWNER_READBACK":
        identity_source = "NOT_REPORTED"
    branch_execution_kind = {
        "MORNING": "SCHEDULED_MORNING",
        "PREOPEN": "SCHEDULED_PREOPEN",
        "EVENING_NEXT_SESSION": "MANUAL_REFRESH",
        "SAME_DAY_CATCHUP": "MANUAL_REFRESH",
    }.get(str(identity.get("branch")))
    return {
        **dict(identity),
        "triggered_at": now.isoformat(),
        "status": status,
        "owner": OWNER,
        "owner_readback_status": owner_readback,
        "owner_execution_kind": plan.get("execution_kind"),
        "owner_execution_kind_source": identity_source,
        "branch_execution_kind": branch_execution_kind,
        "owner_attempt_state": plan.get("owner_attempt_state"),
        "owner_attempt_run_id": plan.get("owner_attempt_run_id"),
        "owner_attempt_sha256": plan.get("owner_attempt_sha256"),
        "owner_run_id": plan.get("run_id"),
        "owner_product_sha256": plan.get("product_sha256") or plan.get("sha256"),
        "owner_input_identity": plan.get("input_identity"),
        "owner_failure_reasons": plan.get("failure_reasons"),
        "idempotency_status": (
            "OWNER_RETURNED_EXISTING_RUN" if plan.get("owner_product_status", plan_status) in existing_statuses
            else "OWNER_RESULT_RETURNED" if plan else "OWNER_RESULT_MISSING"
        ),
    }


def _rpc_failure_receipt(identity: Mapping[str, str], *, now: datetime,
                          code: str, http_status: int | None = None,
                          admission_rejected: bool = False) -> dict[str, Any]:
    safe_code = code if code in RPC_FAILURE_CODES else "PLAN_OWNER_RPC_FAILED"
    rejected = admission_rejected and safe_code in PLAN_OWNER_GATE_CODES
    outcome = "OWNER_NOT_CALLED" if rejected else "CANNOT_CONFIRM"
    phase = "ADMISSION" if rejected else "TRANSPORT" if safe_code == "PLAN_OWNER_RPC_TRANSPORT_FAILED" else "READBACK"
    receipt = {
        **dict(identity),
        "triggered_at": now.isoformat(),
        "status": "FAILED",
        "owner": OWNER,
        "owner_readback_status": "NOT_CONFIRMED",
        "failure_code": safe_code,
        "failure_stage": phase,
        "owner_execution_status": outcome,
        "request_count": 1,
        "idempotency_status": "NEXT_TRIGGER_RECONCILES_EXISTING_OWNER_LEDGER",
    }
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        receipt["http_status"] = http_status
    return {
        "schema_version": SCHEMA,
        "status": "FAILED",
        "owner": OWNER,
        "binding_sha256": identity["binding_sha256"],
        "target_trade_date": identity["target_trade_date"],
        "failure_stage": phase,
        "owner_execution_status": outcome,
        "parent_trigger_receipt": receipt,
        **FLAGS,
    }


def compact_cycle_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            out[key] = compact_cycle_receipt(item)
        elif isinstance(item, list) and len(item) > 32:
            raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            out[key] = item[:16]
            out[f"{key}_count"] = len(item)
            out[f"{key}_truncated"] = True
            out[f"{key}_sha256"] = hashlib.sha256(raw).hexdigest()
        else:
            out[key] = item
    return out


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def _us_mapping_dispatch_status(service: Any, date: str) -> dict[str, Any]:
    """Report preparation admission; the plan owner reads existing US material.

    The original US refresh API has no independently bounded execution hook in
    this source closure. Calling it here could exhaust the plan RPC's 30-second
    cooperative budget or opening window. Do not start it before or after the
    plan, or invent a replacement worker. Its original owner remains separate.
    """
    gaps = []
    if getattr(service, "_workspace_us_market_reader", None) is None:
        gaps.append("US_MARKET_READER_UNAVAILABLE")
    if not callable(getattr(service, "refresh_us_mapping_research", None)):
        gaps.append("US_MAPPING_DAILY_OWNER_UNAVAILABLE")
    status = "CANNOT_CONFIRM" if gaps else "NOT_ATTEMPTED"
    return {"status": status, "target_trade_date": date, "matches": None,
            "preparation_status": "NOT_ATTEMPTED", "assessment_status": "NOT_EVALUATED",
            "execution_attempted": False,
            "gaps": gaps or ["US_MAPPING_REQUIRES_INDEPENDENT_OWNER_DISPATCH"], **FLAGS}


def _seal_dispatch(value: Mapping[str, Any]) -> dict[str, Any]:
    body = {key: item for key, item in value.items() if key != "sha256"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "sha256": hashlib.sha256(encoded).hexdigest()}


def _dispatch_history(service: Any, identity: Mapping[str, str]) -> list[dict[str, Any]]:
    directory = (service.store.root / "workspace_plan_dispatch" / identity["target_trade_date"]
                 / identity["trigger_id"])
    paths = list(directory.glob("*.json")) if directory.is_dir() else []
    if len(paths) > MAX_DISPATCH_RECEIPTS:
        raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_BOUND_EXCEEDED")
    rows = []
    for sequence, path in enumerate(sorted(paths), 1):
        row = service.store._read(path)
        if (path.name != f"{sequence:04d}.json" or not isinstance(row, Mapping)
                or row.get("schema_version") != DISPATCH_SCHEMA
                or row.get("sha256") != _seal_dispatch(row)["sha256"]
                or row.get("parent_trigger_identity") != dict(identity)
                or row.get("sequence") != sequence or row.get("state") not in {"RUNNING", "COMPLETED"}
                or any(row.get(key) is not flag for key, flag in FLAGS.items())
                or _aware_timestamp(row.get("started_at")) is None
                or (row.get("state") == "COMPLETED" and (
                    _aware_timestamp(row.get("finished_at")) is None
                    or not isinstance(row.get("response"), Mapping)
                    or row["response"].get("status") not in {"SUCCEEDED", "PARTIAL", "FAILED"}))):
            raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_INVALID")
        rows.append(dict(row))
    return rows


def _receipt_reference(identity: Mapping[str, str], row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": (f"workspace_plan_dispatch/{identity['target_trade_date']}/"
                 f"{identity['trigger_id']}/{row['sequence']:04d}.json"),
        "sha256": row["sha256"], "status": "READBACK_VERIFIED",
    }


def _dispatch_outcome(result: Mapping[str, Any]) -> str:
    plan = result.get("plan_result")
    if not isinstance(plan, Mapping):
        return "CANNOT_CONFIRM"
    # Use an explicit owner status, never infer missing inputs from empty rows
    # or from the absence of a product/run. Preserve the original input reason.
    if not isinstance(plan.get("status"), str):
        return "CANNOT_CONFIRM"
    if plan["status"] in {"CANNOT_CONFIRM", "INPUT_MISSING", "INPUTS_NOT_READY"}:
        return "INPUT_NOT_READY"
    reasons = plan.get("failure_reasons")
    if isinstance(reasons, list) and "PLAN_OWNER_EXECUTION_TIMEOUT" in reasons:
        return "CANNOT_CONFIRM"
    if plan.get("status") == "FAILED":
        return "OWNER_FAILED"
    from ops.run_manager_announcement_cycle import valid_owner_plan_result
    if valid_owner_plan_result(plan, str(result.get("branch"))):
        return "OWNER_RESULT"
    return "CANNOT_CONFIRM"


def _cycle_result(identity: Mapping[str, str], now: datetime, result: Mapping[str, Any]) -> dict[str, Any]:
    return {**compact_cycle_receipt(result), "schema_version": SCHEMA, "owner": OWNER,
            "binding_sha256": identity["binding_sha256"], "target_trade_date": identity["target_trade_date"],
            "dispatch_outcome": _dispatch_outcome(result),
            "parent_trigger_receipt": _parent_trigger_receipt(identity, now=now, result=result), **FLAGS}


def _blocked_dispatch(identity: Mapping[str, str], now: datetime, reason: str,
                      prior: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = _cycle_result(identity, now, {
        "status": "FAILED", "branch": identity["branch"], "failure_reasons": [reason],
        "plan_result": {"status": reason, "target_trade_date": identity["target_trade_date"],
                        "failure_reasons": [reason]},
    })
    if prior is not None:
        result["dispatch_receipt"] = _receipt_reference(identity, prior)
    return result


def _daily_catchup_attempt_count(service: Any, date: str) -> int:
    """Count only durable SAME_DAY_CATCHUP dispatch attempts for this date."""
    base = f"workspace_plan_dispatch/{date}"
    try:
        with service.store._io.directory(base) as fd:
            names = sorted(os.listdir(fd))
    except FileNotFoundError:
        return 0
    if len(names) > 2048:
        raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_BOUND_EXCEEDED")
    count = 0
    files_seen = 0
    for trigger_id in names:
        if not re.fullmatch(r"[0-9a-f]{64}", trigger_id):
            raise ValueError("PLAN_OWNER_DISPATCH_TRIGGER_DIRECTORY_INVALID")
        rel = f"{base}/{trigger_id}"
        try:
            with service.store._io.directory(rel) as fd:
                entries = sorted(os.listdir(fd))
        except FileNotFoundError:
            continue
        files_seen += len(entries)
        if files_seen > MAX_DISPATCH_RECEIPTS:
            raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_BOUND_EXCEEDED")
        for name in entries:
            if not re.fullmatch(r"\d{4}\.json", name):
                raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_NAME_INVALID")
            row = service.store._read(service.store.root / rel / name)
            identity = row.get("parent_trigger_identity") if isinstance(row, Mapping) else None
            if (not isinstance(row, Mapping) or not isinstance(identity, Mapping)
                    or row.get("schema_version") != DISPATCH_SCHEMA
                    or row.get("sha256") != _seal_dispatch(row)["sha256"]
                    or row.get("target_trade_date", identity.get("target_trade_date")) != date
                    or row.get("sequence") != int(name[:4])
                    or row.get("state") not in {"RUNNING", "COMPLETED"}
                    or identity.get("trigger_id") != trigger_id
                    or identity.get("target_trade_date") != date
                    or any(row.get(key) is not flag for key, flag in FLAGS.items())):
                raise ValueError("PLAN_OWNER_DISPATCH_RECEIPT_INVALID")
            if identity.get("branch") == "SAME_DAY_CATCHUP":
                count += 1
    return count


def _run_owner_branches(service: Any, binding: Mapping[str, Any], identity: Mapping[str, str], *,
                        daily_mode: bool = False,
                        us_mapping_result: Mapping[str, Any] | None = None,
                        us_market_request_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    date, branch = identity["target_trade_date"], identity["branch"]
    # Recheck the actual API clock immediately before calling the plan owner.
    # No unrelated mutable source preparation may consume this legal window.
    execution_now = clock_now()
    if daily_mode:
        from ops.run_manager_announcement_cycle import daily_admitted_branch_is_live
        admitted_live=daily_admitted_branch_is_live(identity["source_trade_date"],date,branch,
            scheduled_slot=identity.get("scheduled_slot"),now=execution_now,
            plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
    else:
        expected_branch, expected_slot = _expected_branch(binding,execution_now), None
        expected_target = _expected_target(binding,execution_now)
        admitted_live=(expected_target == date and expected_branch == branch)
    if not admitted_live:
        result = {"status": "FAILED", "branch": branch,
                  "failure_reasons": ["PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION"],
                  "plan_result": {"status": "EXPIRED_NO_BACKFILL", "target_trade_date": date}}
    else:
        from ops.run_manager_announcement_cycle import run_scheduled_plan_target
        result = run_scheduled_plan_target(service, date, identity["source_trade_date"],
            now=execution_now, plan_config=binding.get("plan_material_refresh"),
            preopen_config=binding.get("preopen_plan"), morning_plan_config=binding.get("morning_plan"),
            daily_config=binding.get("daily_automation") if daily_mode else None,
            daily_branch=branch if daily_mode else None,
            scheduled_slot=identity.get("scheduled_slot"),trigger_id=identity["trigger_id"],
            us_market_request_context=us_market_request_context)
    if result.get("branch") != branch:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BRANCH_READBACK_MISMATCH")
    daily = (dict(us_mapping_result) if us_mapping_result is not None else
             _us_mapping_dispatch_status(service, date) if branch in {"MORNING", "PREOPEN"}
             else {"status": "NOT_DUE_US_SESSION_NOT_CLOSED", "target_trade_date": date,
                   "source_date": identity["source_trade_date"], "execution_attempted": False, **FLAGS})
    result = {**result, "us_mapping_research": compact_cycle_receipt(daily)}
    if (us_mapping_result is not None or branch in {"MORNING", "PREOPEN"}) and daily.get("status") not in {"COMPLETED", "VALID_EMPTY"}:
        result["status"] = "FAILED" if result.get("status") == "FAILED" else "PARTIAL"
    return result


def _recover_interrupted_daily_owner(service: Any, identity: Mapping[str, str], *,
                                     prior: Mapping[str, Any], now: datetime,
                                     us_mapping_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Recover only the exact daily owner product committed by this trigger.

    The owner product and its immutable terminal attempt are the evidence. We
    read the original latest product once, then the exact run journal through
    the original workspace readback helpers. No source projection, directory
    scan, owner call, or product write occurs during reconciliation.
    """
    branch = str(identity.get("branch"))
    if (branch not in {"MORNING", "SAME_DAY_CATCHUP"}
            or not isinstance(us_mapping_result, Mapping)
            or prior.get("state") != "RUNNING"
            or prior.get("parent_trigger_identity") != dict(identity)):
        return None
    date = str(identity.get("target_trade_date") or "")
    expected_kind = "SCHEDULED_MORNING" if branch == "MORNING" else "MANUAL_REFRESH"
    expected_timing = "ON_TIME" if branch == "MORNING" else "LATE_CATCHUP"
    slot = identity.get("scheduled_slot")
    try:
        if not isinstance(slot, str) or not re.fullmatch(date + r"T\d{4}", slot):
            return None
        expected_scheduled = datetime.strptime(slot, "%Y%m%dT%H%M").replace(tzinfo=HK)
        from .workspace import _read_plan, verified_plan_attempt
        from .workspace_plan_autorun import owner_plan_readback
        saved = _read_plan(service.store, date)
        if not isinstance(saved, Mapping):
            return None
        execution_context = saved.get("execution_context")
        workspace = saved.get("workspace")
        if not isinstance(execution_context, Mapping) or not isinstance(workspace, Mapping):
            return None
        workspace_context = workspace.get("execution_context")
        scheduled_for = _aware_timestamp(execution_context.get("scheduled_for"))
        dispatch_started = _aware_timestamp(prior.get("started_at"))
        owner_started = _aware_timestamp(execution_context.get("started_at"))
        generated_at = _aware_timestamp(saved.get("generated_at"))
        if (saved.get("target_trade_date") != date
                or saved.get("owner") != OWNER
                or saved.get("execution_kind") != expected_kind
                or execution_context.get("trigger_kind") != "SCHEDULED"
                or execution_context.get("timing") != expected_timing
                or execution_context.get("natural_run_verified") is not False
                or execution_context.get("trigger_id") != identity.get("trigger_id")
                or scheduled_for is None
                or scheduled_for.astimezone(HK) != expected_scheduled
                or dispatch_started is None or owner_started is None or generated_at is None
                or owner_started.astimezone(timezone.utc) < dispatch_started.astimezone(timezone.utc)
                or generated_at.astimezone(timezone.utc) < dispatch_started.astimezone(timezone.utc)
                or not isinstance(workspace_context, Mapping)
                or dict(workspace_context) != dict(execution_context)
                or saved.get("input_identity") != workspace.get("input_identity")):
            return None
        attempt = verified_plan_attempt(service.store, saved)
        if not isinstance(attempt, Mapping):
            return None
        product = {
            "status": "CURRENT", "consumed": True, "run_id": saved.get("run_id"),
            "sha256": saved.get("sha256"), "generated_at": saved.get("generated_at"),
            "execution_kind": expected_kind, "original_owner": saved.get("owner"),
            "execution_context": dict(execution_context),
        }
        plan = owner_plan_readback({
            "target_trade_date": date, "input_identity": saved.get("input_identity"),
            "plan_product": product, "workspace_plan_attempt": dict(attempt),
        }, date, expected_kind=expected_kind)
        from ops.run_manager_announcement_cycle import valid_owner_plan_result
        if (plan.get("target_trade_date") != date
                or plan.get("execution_context", {}).get("trigger_id") != identity.get("trigger_id")
                or not valid_owner_plan_result(plan, branch)):
            return None
        status = "PARTIAL" if plan.get("owner_attempt_state") == "PARTIAL" else "SUCCEEDED"
        if us_mapping_result.get("status") not in {"COMPLETED", "VALID_EMPTY"}:
            status = "PARTIAL"
        return {
            "status": status, "branch": branch, "target_trade_date": date,
            "plan_result": plan,
            "us_mapping_research": compact_cycle_receipt(us_mapping_result),
            "failure_reasons": list(plan.get("failure_reasons") or []),
            "reconciliation_status": "EXACT_OWNER_PRODUCT_AND_ATTEMPT_READBACK",
            "reconciled_at": now.isoformat(),
            "owner": OWNER, "policy_status": "PROPOSAL_ONLY",
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError):
        # Any evidence ambiguity remains a blocked RUNNING receipt.
        return None


def _daily_trigger_digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _daily_us_failure(date: str, now: datetime, execution_context: Mapping[str, Any], code: str) -> dict[str, Any]:
    from .us_mapping_research import DAILY_SCHEMA, _execution_metadata
    finished = max(datetime.now(now.tzinfo), now)
    context = _execution_metadata(dict(execution_context), target=date,
        started_at=now, finished_at=finished,
        research_cutoff_policy="TARGET_DATE_END_OF_DAY_RETROSPECTIVE"
            if now.astimezone(HK).strftime("%Y%m%d") > date else "ACTUAL_OWNER_EXECUTION_CUTOFF")
    return {
        "schema_version": DAILY_SCHEMA, "status": "FAILED", "target_trade_date": date,
        "run_id": None, "generated_at": None, "us_session_date": None,
        "research_cutoff": None,
        "coverage": {"reviewed_us_symbol_count": 4, "matched_us_symbol_count": None,
            "matched_hk_relation_count": None, "configured_us_universe_count": None,
            "available_us_universe_count": None, "full_market_coverage": False},
        "matches": [], "execution_status": code, "execution_context": context,
        "gaps": [code], **FLAGS,
    }


def _admit_bound_cycle(service: Any, target_date: str, binding_sha256: str, *,
                       daily_mode: bool) -> tuple[dict[str, Any], dict[str, str], datetime]:
    """Shared read-only admission, kept entirely before US/plan/store dispatch."""
    try:
        return _validate_bound_cycle(service, target_date, binding_sha256, daily_mode=daily_mode)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        reason = "PLAN_OWNER_BINDING_UNAVAILABLE" if isinstance(exc, OSError) else str(exc)
        raise PlanOwnerAdmissionError(reason) from exc


def _validate_bound_cycle(service: Any, target_date: str, binding_sha256: str, *,
                          daily_mode: bool) -> tuple[dict[str, Any], dict[str, str], datetime]:
    binding_path = os.environ.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH", "").strip()
    if not binding_path:
        raise ValueError("PLAN_OWNER_SERVER_BINDING_NOT_CONFIGURED")
    raw = _raw_binding(binding_path)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(binding_sha256 or "")) or actual_sha != binding_sha256:
        raise ValueError("PLAN_OWNER_BINDING_SHA_MISMATCH")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID") from exc
    from infrastructure.scheduling.manager_announcement_supervisor import (
        daily_automation_config, validate_binding,
    )
    binding = validate_binding(value, expected_owner_app=APP_ROOT)
    daily_config = daily_automation_config(binding.get("daily_automation"))
    if not binding.get("enabled") or (daily_mode and not daily_config["enabled"]):
        raise ValueError("PLAN_OWNER_DAILY_BINDING_DISABLED" if daily_mode else "PLAN_OWNER_BINDING_DISABLED")
    state_root = Path(str(binding.get("manager_state_root") or "")).resolve()
    master_root = Path(str(binding.get("security_master_root") or "")).resolve()
    service_master = getattr(service, "_workspace_security_master_root", None)
    if (Path(service.store.root).resolve() != state_root or service_master is None
            or Path(service_master).resolve() != master_root):
        raise ValueError("PLAN_OWNER_STATE_OR_MASTER_ROOT_MISMATCH")
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    if daily_mode:
        from ops.run_manager_announcement_cycle import daily_cycle_branch, daily_cycle_target
        branch, scheduled_slot = daily_cycle_branch(source_date, now=now,
            plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
        expected_target = daily_cycle_target(source_date,now=now,
            plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
    else:
        branch, scheduled_slot = _expected_branch(binding, now), None
        expected_target = _expected_target(binding, now)
    if not branch or expected_target != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    slot = scheduled_slot if branch == "SAME_DAY_CATCHUP" else (
        now.astimezone(HK).strftime("%Y%m%dT%H%M") if branch == "MORNING" else None)
    identity = _parent_trigger_identity(source_date,date,branch,actual_sha,scheduled_slot=slot)
    return binding, identity, now


def execute_bound_daily_cycle(service: Any, target_date: str, binding_sha256: str) -> dict[str, Any]:
    """Run the US owner first, then one independent original plan RPC budget."""
    binding, identity, now = _admit_bound_cycle(service,target_date,binding_sha256,daily_mode=True)
    from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
    daily_config = daily_automation_config(binding.get("daily_automation"))
    date, branch, actual_sha = identity["target_trade_date"], identity["branch"], identity["binding_sha256"]
    slot = scheduled_slot = identity.get("scheduled_slot")

    us_result = None
    request_context = None
    if branch in {"MORNING", "SAME_DAY_CATCHUP"}:
        owner_started = clock_now()
        if owner_started.tzinfo is None or owner_started.astimezone(HK).strftime("%Y%m%d") != date:
            raise ValueError("US_MAPPING_DAILY_OWNER_CLOCK_INVALID")
        if branch == "MORNING":
            from v4.manager_research.workspace_plan_autorun import morning_window
            scheduled_for = datetime.strptime(str(slot), "%Y%m%dT%H%M").replace(tzinfo=HK)
            # One immutable attempt belongs to one already-admitted morning
            # slot. Reusing a day-wide trigger would replay an early missing
            # input forever, even after the original exact-session source arrives.
            phase_id = "MORNING_US:" + str(slot)
            timing = "ON_TIME"
        else:
            scheduled_for = datetime.strptime(str(scheduled_slot), "%Y%m%dT%H%M").replace(tzinfo=HK)
            phase_id = "CATCHUP_US:" + str(scheduled_slot)
            timing = "LATE_CATCHUP"
        us_trigger = _daily_trigger_digest(date,actual_sha,phase_id)
        us_context = {"trigger_kind":"SCHEDULED","timing":timing,
            "scheduled_for":scheduled_for.isoformat(),"trigger_id":us_trigger,
            "natural_run_verified":False}
        if callable(getattr(service,"refresh_us_mapping_research",None)):
            try:
                us_result = service.refresh_us_mapping_research(date,now=owner_started,
                    timeout_seconds=float(daily_config["us_mapping_budget_seconds"]),
                    execution_context=us_context)
            except (OSError,TimeoutError,ValueError,KeyError,TypeError,RuntimeError) as exc:
                code = "US_MAPPING_OWNER_CALL_FAILED:" + type(exc).__name__
                us_result = _daily_us_failure(date,owner_started,us_context,code)
        else:
            us_result = _daily_us_failure(date,owner_started,us_context,"US_MAPPING_DAILY_OWNER_UNAVAILABLE")
        if (us_result.get("status") == "FAILED"
                and us_result.get("execution_status") in {"US_MAPPING_OWNER_READ_TIMEOUT","US_MAPPING_OWNER_READ_BUSY"}):
            request_context = {"target_trade_date":date,
                "execution_status":us_result["execution_status"],"bypass_reader":True}
    return service._workspace_reads.run(
        (date,"SCHEDULED_DAILY_OWNER",identity["trigger_id"]),
        lambda: _execute_serialized_cycle(service,binding,identity,daily_mode=True,
            us_mapping_result=us_result,us_market_request_context=request_context),seconds=30.0)


def _execute_serialized_cycle(service: Any, binding: Mapping[str, Any], identity: Mapping[str, str], *,
                              daily_mode: bool = False,
                              us_mapping_result: Mapping[str, Any] | None = None,
                              us_market_request_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    date = identity["target_trade_date"]
    # The existing store supplies the process lock and no-follow atomic I/O.
    # These are dispatch receipts only; all research products retain their owner.
    with service.store._transaction(date, "workspace-plan-bound-dispatch"):
        now = clock_now()
        if daily_mode:
            from ops.run_manager_announcement_cycle import daily_admitted_branch_is_live
            admitted_live=daily_admitted_branch_is_live(identity["source_trade_date"],date,
                identity["branch"],scheduled_slot=identity.get("scheduled_slot"),now=now,
                plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
                morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
        else:
            expected_branch, expected_slot = _expected_branch(binding,now), None
            expected_target = _expected_target(binding,now)
            admitted_live=(expected_target == date and expected_branch == identity["branch"])
        if not admitted_live:
            return _blocked_dispatch(identity, now, "PLAN_OWNER_WINDOW_EXPIRED_DURING_ADMISSION")
        history = _dispatch_history(service, identity)
        prior = history[-1] if history else None
        if prior is not None and prior["state"] == "RUNNING":
            recovered = (_recover_interrupted_daily_owner(service, identity, prior=prior,
                now=now, us_mapping_result=us_mapping_result) if daily_mode else None)
            if recovered is None:
                return _blocked_dispatch(identity, now, "PLAN_OWNER_RECONCILIATION_REQUIRED", prior)
            response = _cycle_result(identity, now, recovered)
            completed = _seal_dispatch({**prior, "state": "COMPLETED",
                "finished_at": now.isoformat(), "response": response})
            path = (service.store.root / "workspace_plan_dispatch" / date / identity["trigger_id"]
                    / f"{prior['sequence']:04d}.json")
            service.store._write_atomic(path, completed)
            if service.store._read(path) != completed:
                raise ValueError("PLAN_OWNER_DISPATCH_RECONCILIATION_READBACK_FAILED")
            return {**response, "dispatch_receipt": _receipt_reference(identity, completed)}
        if (prior is not None and prior["state"] == "COMPLETED"
                and prior["response"].get("status") in {"SUCCEEDED", "PARTIAL"}):
            return {**dict(prior["response"]),
                "dispatch_receipt": _receipt_reference(identity, prior)}
        if daily_mode and identity["branch"] == "SAME_DAY_CATCHUP":
            from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
            if _daily_catchup_attempt_count(service, date) >= daily_automation_config(
                    binding.get("daily_automation"))["max_attempts_per_target_date"]:
                return _blocked_dispatch(identity, now, "PLAN_OWNER_CATCHUP_RETRY_LIMIT_REACHED", prior)
        failures = [row for row in history if row["response"].get("status") == "FAILED"]
        if len(failures) >= MAX_FAILED_DISPATCHES or len(history) >= MAX_DISPATCH_RECEIPTS:
            return _blocked_dispatch(identity, now, "PLAN_OWNER_RETRY_LIMIT_REACHED", prior)
        if prior is not None and prior["response"].get("status") == "FAILED":
            from ops.run_manager_announcement_cycle import _plan_refresh_config
            backoff = (_plan_refresh_config(binding.get("plan_material_refresh"))["retry_backoff_seconds"]
                       if identity["branch"] == "EVENING_NEXT_SESSION" else 60)
            if (now - _aware_timestamp(prior["finished_at"])).total_seconds() < backoff:
                return _blocked_dispatch(identity, now, "PLAN_OWNER_RETRY_BACKOFF", prior)
        sequence = len(history) + 1
        path = (service.store.root / "workspace_plan_dispatch" / date / identity["trigger_id"]
                / f"{sequence:04d}.json")
        started = _seal_dispatch({"schema_version": DISPATCH_SCHEMA, "state": "RUNNING",
            "parent_trigger_identity": dict(identity), "sequence": sequence,
            "target_trade_date": date,
            "started_at": now.isoformat(), **FLAGS})
        service.store._write_atomic(path, started)
        if service.store._read(path) != started:
            raise ValueError("PLAN_OWNER_DISPATCH_START_READBACK_FAILED")
        try:
            result = _run_owner_branches(service, binding, identity,daily_mode=daily_mode,
                us_mapping_result=us_mapping_result,
                us_market_request_context=us_market_request_context)
        except Exception as exc:
            reason = "PLAN_OWNER_EXECUTION_TIMEOUT" if isinstance(exc, TimeoutError) else str(exc)
            if reason not in OWNER_FAILURE_CODES:
                reason = "PLAN_OWNER_EXECUTION_FAILED"
            result = {"status": "FAILED", "branch": identity["branch"],
                      "failure_reasons": [reason], "plan_result": {"status": "FAILED",
                      "target_trade_date": date, "failure_reasons": [reason]}}
        response = _cycle_result(identity, now, result)
        completed = _seal_dispatch({**started, "state": "COMPLETED",
            "finished_at": clock_now().isoformat(), "response": response})
        service.store._write_atomic(path, completed)
        if service.store._read(path) != completed:
            raise ValueError("PLAN_OWNER_DISPATCH_TERMINAL_READBACK_FAILED")
        return {**response, "dispatch_receipt": _receipt_reference(identity, completed)}


def execute_bound_plan_cycle(service: Any, target_date: str, binding_sha256: str) -> dict[str, Any]:
    binding, parent_identity, _now = _admit_bound_cycle(service,target_date,binding_sha256,daily_mode=False)
    date = parent_identity["target_trade_date"]
    return service._workspace_reads.run(
        (date, "SCHEDULED_PLAN_OWNER", parent_identity["trigger_id"]),
        lambda: _execute_serialized_cycle(service, binding, parent_identity), seconds=30.0)


def request_bound_plan_cycle(binding_path: str | Path, target_date: str) -> dict[str, Any]:
    return _request_bound_cycle(binding_path,target_date,daily_mode=False)


def request_bound_daily_cycle(binding_path: str | Path, target_date: str) -> dict[str, Any]:
    return _request_bound_cycle(binding_path,target_date,daily_mode=True)


def _verified_admission_rejection(detail: Any, *, date: str, sha: str) -> bool:
    return (isinstance(detail, dict)
        and set(detail) == {"schema_version", "status", "owner", "reason", "failure_stage",
                           "owner_execution_status", "target_trade_date", "binding_sha256", *FLAGS}
        and detail.get("schema_version") == REJECTION_SCHEMA and detail.get("status") == "GATE_REJECTED"
        and detail.get("owner") == OWNER and isinstance(detail.get("reason"), str)
        and detail["reason"] in PLAN_OWNER_GATE_CODES
        and detail.get("failure_stage") == "ADMISSION"
        and detail.get("owner_execution_status") == "OWNER_NOT_CALLED"
        and detail.get("target_trade_date") == date and detail.get("binding_sha256") == sha
        and all(detail.get(key) is flag for key, flag in FLAGS.items()))


def _request_bound_cycle(binding_path: str | Path, target_date: str, *, daily_mode: bool) -> dict[str, Any]:
    """One fixed loopback request with no proxy, redirect, retry, or fallback."""
    raw_binding = _raw_binding(binding_path)
    sha = hashlib.sha256(raw_binding).hexdigest()
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    binding = json.loads(raw_binding)
    if not isinstance(binding, Mapping):
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID")
    if daily_mode:
        from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
        from ops.run_manager_announcement_cycle import daily_cycle_branch,daily_cycle_target
        if not daily_automation_config(binding.get("daily_automation"))["enabled"]:
            raise ValueError("PLAN_OWNER_DAILY_BINDING_DISABLED")
        branch,scheduled_slot=daily_cycle_branch(source_date,now=now,
            plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
        expected_target=daily_cycle_target(source_date,now=now,
            plan_config=binding.get("plan_material_refresh"),preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),daily_config=binding.get("daily_automation"))
    else:
        expected_target,branch=_expected_target(binding,now),_expected_branch(binding,now)
        scheduled_slot=None
    if not branch or expected_target != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    parent_identity = _parent_trigger_identity(source_date, date, branch, sha,
        scheduled_slot=(scheduled_slot if branch=="SAME_DAY_CATCHUP" else
            now.astimezone(HK).strftime("%Y%m%dT%H%M") if branch=="MORNING" else None))
    # The daily server path may spend its fixed 5s US preparation budget and
    # then the existing 30s plan-owner budget. Preserve the legacy transport
    # contract while leaving bounded readback headroom below the parent cap.
    connection = http.client.HTTPConnection("127.0.0.1", 8873,
        timeout=40.0 if daily_mode else 35.0)
    try:
        endpoint="/api/v4/manager/research/workspace/daily-cycle" if daily_mode else "/api/v4/manager/research/workspace/scheduled-cycle"
        path = endpoint + "?" + urlencode(
            {"date": date, "binding_sha256": sha})
        try:
            connection.request("POST", path, body=b"", headers={"Content-Length": "0", "Accept": "application/json"})
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "").split(";", 1)[0]
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, TimeoutError, http.client.HTTPException):
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_TRANSPORT_FAILED")
        if len(raw) > MAX_RESPONSE_BYTES:
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_RESPONSE_TOO_LARGE",
                                        http_status=response.status)
        if response.status != 200 or content_type != "application/json":
            code = f"PLAN_OWNER_RPC_HTTP_{response.status}"
            if content_type == "application/json":
                try:
                    error_body = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error_body = None
                detail = error_body.get("detail") if isinstance(error_body, dict) else None
                if response.status == 409 and _verified_admission_rejection(detail,date=date,sha=sha):
                    return _rpc_failure_receipt(parent_identity,now=now,code=detail["reason"],
                        http_status=response.status,admission_rejected=True)
                if isinstance(detail, str) and detail in KNOWN_RPC_HTTP_ERROR_DETAILS:
                    code = detail
            elif response.status == 200:
                code = "PLAN_OWNER_RPC_CONTENT_TYPE_INVALID"
            return _rpc_failure_receipt(parent_identity, now=now, code=code,
                                        http_status=response.status)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_RESPONSE_JSON_INVALID",
                                        http_status=response.status)
        server_trigger = value.get("parent_trigger_receipt") if isinstance(value, dict) else None
        server_status = value.get("status") if isinstance(value, dict) else None
        owner_readback_status = (server_trigger.get("owner_readback_status")
                                 if isinstance(server_trigger, dict) else None)
        plan = value.get("plan_result") if isinstance(value, dict) else None
        plan = plan if isinstance(plan, Mapping) else {}
        from ops.run_manager_announcement_cycle import valid_owner_plan_result
        owner_identity_verified = (
            isinstance(server_trigger, dict)
            and valid_owner_plan_result(plan, branch)
            and plan.get("target_trade_date") == date
            and server_trigger.get("owner_run_id") == plan.get("run_id")
            and server_trigger.get("owner_product_sha256") == plan.get("product_sha256")
            and server_trigger.get("owner_input_identity") == plan.get("input_identity")
            and server_trigger.get("owner_execution_kind") == plan.get("execution_kind")
            and server_trigger.get("owner_execution_kind_source") == "OWNER_READBACK"
            and server_trigger.get("owner_attempt_state") == plan.get("owner_attempt_state")
            and server_trigger.get("owner_attempt_run_id") == plan.get("run_id")
            and server_trigger.get("owner_attempt_sha256") == plan.get("owner_attempt_sha256")
        )
        dispatch_ref = value.get("dispatch_receipt") if isinstance(value, dict) else None
        receipt_verified = (isinstance(dispatch_ref, Mapping)
            and dispatch_ref.get("status") == "READBACK_VERIFIED"
            and re.fullmatch(r"[0-9a-f]{64}", str(dispatch_ref.get("sha256") or "")) is not None
            and re.fullmatch(r"workspace_plan_dispatch/" + date + "/" + parent_identity["trigger_id"]
                             + r"/\d{4}\.json", str(dispatch_ref.get("path") or "")) is not None)
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
                or value.get("owner") != OWNER or value.get("target_trade_date") != date
                or value.get("binding_sha256") != sha
                or value.get("branch") != branch
                or ("dispatch_outcome" in value and value["dispatch_outcome"] != _dispatch_outcome(value))
                or any(value.get(key) is not flag for key, flag in FLAGS.items())
                or value.get("status") not in {"SUCCEEDED", "PARTIAL", "FAILED"}
                or not isinstance(server_trigger, dict)
                or server_trigger.get("schema_version") != PARENT_TRIGGER_SCHEMA
                or server_trigger.get("trigger_id") != parent_identity["trigger_id"]
                or server_trigger.get("trigger_kind") != "BOUND_SCHEDULED_PLAN_CYCLE"
                or server_trigger.get("source_trade_date") != source_date
                or server_trigger.get("target_trade_date") != date
                or server_trigger.get("branch") != branch
                or server_trigger.get("binding_sha256") != sha
                or any(server_trigger.get(key) != item for key, item in parent_identity.items())
                or server_trigger.get("owner") != OWNER
                or server_trigger.get("status") != server_status
                or owner_readback_status not in {"VERIFIED", "UNVERIFIED"}
                or (owner_readback_status == "VERIFIED" and (not owner_identity_verified or not receipt_verified))
                or (server_status == "SUCCEEDED" and (
                    owner_readback_status != "VERIFIED" or not owner_identity_verified
                    or plan.get("owner_attempt_state") not in {"SUCCEEDED", "SUCCEEDED_EMPTY"}
                ))
                or (owner_readback_status == "UNVERIFIED" and server_status not in {"PARTIAL", "FAILED"})):
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID",
                                        http_status=response.status)
        return value
    finally:
        connection.close()


__all__ = ["APP_ROOT", "OWNER", "SCHEMA", "compact_cycle_receipt", "execute_bound_plan_cycle",
           "execute_bound_daily_cycle", "request_bound_plan_cycle", "request_bound_daily_cycle"]
