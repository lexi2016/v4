"""Bounded loopback RPC to the API's fully injected ManagerResearch owner."""
from __future__ import annotations

from datetime import datetime
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
    if branch not in {"MORNING", "PREOPEN", "EVENING_NEXT_SESSION"}:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BRANCH_INVALID")
    if (branch in {"MORNING", "PREOPEN"}) != (source == target):
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
    if branch == "MORNING":
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
                          code: str, http_status: int | None = None) -> dict[str, Any]:
    safe_code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", str(code or "")) else "PLAN_OWNER_RPC_FAILED"
    receipt = {
        **dict(identity),
        "triggered_at": now.isoformat(),
        "status": "FAILED",
        "owner": OWNER,
        "owner_readback_status": "NOT_CONFIRMED",
        "failure_code": safe_code,
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


def _cycle_result(identity: Mapping[str, str], now: datetime, result: Mapping[str, Any]) -> dict[str, Any]:
    return {**compact_cycle_receipt(result), "schema_version": SCHEMA, "owner": OWNER,
            "binding_sha256": identity["binding_sha256"], "target_trade_date": identity["target_trade_date"],
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


def _run_owner_branches(service: Any, binding: Mapping[str, Any], identity: Mapping[str, str]) -> dict[str, Any]:
    date, branch = identity["target_trade_date"], identity["branch"]
    # Recheck the actual API clock immediately before calling the plan owner.
    # No unrelated mutable source preparation may consume this legal window.
    execution_now = clock_now()
    if (_expected_target(binding, execution_now) != date
            or _expected_branch(binding, execution_now) != branch
            or (branch == "MORNING"
                and identity["scheduled_slot"] != execution_now.astimezone(HK).strftime("%Y%m%dT%H%M"))):
        result = {"status": "FAILED", "branch": branch,
                  "failure_reasons": ["PLAN_OWNER_WINDOW_EXPIRED_BEFORE_EXECUTION"],
                  "plan_result": {"status": "EXPIRED_NO_BACKFILL", "target_trade_date": date}}
    else:
        from ops.run_manager_announcement_cycle import run_scheduled_plan_target
        result = run_scheduled_plan_target(service, date, identity["source_trade_date"],
            now=execution_now, plan_config=binding.get("plan_material_refresh"),
            preopen_config=binding.get("preopen_plan"), morning_plan_config=binding.get("morning_plan"))
    if result.get("branch") != branch:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BRANCH_READBACK_MISMATCH")
    daily = (_us_mapping_dispatch_status(service, date) if branch in {"MORNING", "PREOPEN"}
             else {"status": "NOT_DUE_US_SESSION_NOT_CLOSED", "target_trade_date": date,
                   "source_date": identity["source_trade_date"], "execution_attempted": False, **FLAGS})
    result = {**result, "us_mapping_research": compact_cycle_receipt(daily)}
    if branch in {"MORNING", "PREOPEN"} and daily.get("status") not in {"COMPLETED", "VALID_EMPTY"}:
        result["status"] = "FAILED" if result.get("status") == "FAILED" else "PARTIAL"
    return result


def _execute_serialized_cycle(service: Any, binding: Mapping[str, Any], identity: Mapping[str, str]) -> dict[str, Any]:
    date = identity["target_trade_date"]
    # The existing store supplies the process lock and no-follow atomic I/O.
    # These are dispatch receipts only; all research products retain their owner.
    with service.store._transaction(date, "workspace-plan-bound-dispatch"):
        now = clock_now()
        if (_expected_target(binding, now) != date or _expected_branch(binding, now) != identity["branch"]
                or (identity["branch"] == "MORNING"
                    and identity["scheduled_slot"] != now.astimezone(HK).strftime("%Y%m%dT%H%M"))):
            return _blocked_dispatch(identity, now, "PLAN_OWNER_WINDOW_EXPIRED_DURING_ADMISSION")
        history = _dispatch_history(service, identity)
        prior = history[-1] if history else None
        if prior is not None and prior["state"] == "RUNNING":
            # A terminated API may have committed the owner product before its
            # response. Do not issue an unbounded duplicate after that ambiguity.
            return _blocked_dispatch(identity, now, "PLAN_OWNER_RECONCILIATION_REQUIRED", prior)
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
            "started_at": now.isoformat(), **FLAGS})
        service.store._write_atomic(path, started)
        if service.store._read(path) != started:
            raise ValueError("PLAN_OWNER_DISPATCH_START_READBACK_FAILED")
        try:
            result = _run_owner_branches(service, binding, identity)
        except Exception as exc:
            reason = str(exc)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", reason):
                reason = "PLAN_OWNER_FAILED:" + type(exc).__name__
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
    binding_path = os.environ.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH", "").strip()
    if not binding_path:
        raise ValueError("PLAN_OWNER_SERVER_BINDING_NOT_CONFIGURED")
    raw = _raw_binding(binding_path)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", str(binding_sha256 or "")) or actual_sha != binding_sha256:
        raise ValueError("PLAN_OWNER_BINDING_SHA_MISMATCH")
    try:
        binding_value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID") from exc
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    binding = validate_binding(binding_value, expected_app=APP_ROOT)
    if not binding.get("enabled"):
        raise ValueError("PLAN_OWNER_BINDING_DISABLED")
    state_root = Path(str(binding.get("manager_state_root") or "")).resolve()
    master_root = Path(str(binding.get("security_master_root") or "")).resolve()
    service_master = getattr(service, "_workspace_security_master_root", None)
    if Path(service.store.root).resolve() != state_root or service_master is None or Path(service_master).resolve() != master_root:
        raise ValueError("PLAN_OWNER_STATE_OR_MASTER_ROOT_MISMATCH")
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None or _expected_target(binding, now) != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    branch = _expected_branch(binding, now)
    parent_identity = _parent_trigger_identity(source_date, date, branch, actual_sha,
        scheduled_slot=now.astimezone(HK).strftime("%Y%m%dT%H%M") if branch == "MORNING" else None)
    return service._workspace_reads.run(
        (date, "SCHEDULED_PLAN_OWNER", parent_identity["trigger_id"]),
        lambda: _execute_serialized_cycle(service, binding, parent_identity), seconds=30.0)


def request_bound_plan_cycle(binding_path: str | Path, target_date: str) -> dict[str, Any]:
    """One fixed loopback request with no proxy, redirect, retry, or fallback."""
    raw_binding = _raw_binding(binding_path)
    sha = hashlib.sha256(raw_binding).hexdigest()
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    binding = json.loads(raw_binding)
    if not isinstance(binding, Mapping) or _expected_target(binding, now) != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    branch = _expected_branch(binding, now)
    parent_identity = _parent_trigger_identity(source_date, date, branch, sha,
        scheduled_slot=now.astimezone(HK).strftime("%Y%m%dT%H%M") if branch == "MORNING" else None)
    connection = http.client.HTTPConnection("127.0.0.1", 8873, timeout=35.0)
    try:
        path = "/api/v4/manager/research/workspace/scheduled-cycle?" + urlencode(
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


__all__ = ["APP_ROOT", "OWNER", "SCHEMA", "compact_cycle_receipt", "execute_bound_plan_cycle", "request_bound_plan_cycle"]
