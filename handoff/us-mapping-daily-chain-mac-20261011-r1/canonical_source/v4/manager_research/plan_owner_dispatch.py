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
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    from ops.run_manager_announcement_cycle import scheduled_cycle_target
    return scheduled_cycle_target(source_date, now=now,
        plan_config=binding.get("plan_material_refresh"),
        preopen_config=binding.get("preopen_plan"),
        morning_plan_config=binding.get("morning_plan")) or ""


def _scheduled_branch(binding: Mapping[str, Any], source_date: str, target_date: str,
                      now: datetime) -> str:
    """Derive only a configured, due branch; reject same-day or unknown windows."""
    source = date_token(source_date)
    target = date_token(target_date)
    if now.tzinfo is None or _expected_target(binding, now) != target:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    if target != source:
        return "EVENING_NEXT_SESSION"
    local = now.astimezone(HK)
    from v4.manager_research.workspace_plan_autorun import (
        morning_config, morning_window, preopen_window as validated_preopen_window,
    )
    morning = morning_config(binding.get("morning_plan"))
    if morning["enabled"]:
        start, freeze = morning_window(source)
        if start <= local < freeze and (local.hour * 60 + local.minute) % (morning["interval_seconds"] // 60) == 0:
            return "MORNING"
    preopen = binding.get("preopen_plan") or {"enabled": True, "lead_seconds": 180}
    start, end = validated_preopen_window(source, lead_seconds=preopen.get("lead_seconds", 180))
    if preopen.get("enabled", True) and start <= local < end:
        return "PREOPEN"
    raise ValueError("PLAN_OWNER_BRANCH_WINDOW_MISMATCH")


def _parent_trigger_identity(source_date: str, target_date: str, branch: str,
                             binding_sha256: str) -> dict[str, str]:
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
    run_id = str(plan.get("run_id") or "")
    product_sha256 = str(plan.get("product_sha256") or plan.get("sha256") or "")
    input_identity = str(plan.get("input_identity") or "")
    owner_readback = (
        "VERIFIED" if re.fullmatch(r"[0-9a-f]{32}", run_id)
        and re.fullmatch(r"[0-9a-f]{64}", product_sha256)
        and re.fullmatch(r"[0-9a-f]{64}", input_identity)
        else "UNVERIFIED"
    )
    existing_statuses = {
        "ALREADY_CURRENT", "ALREADY_MATERIALIZED", "PRESERVED_SCHEDULED_PREOPEN",
    }
    identity_source = plan.get("execution_kind_source")
    if identity_source not in {"OWNER_READBACK", "BRANCH_CONTRACT"}:
        identity_source = "OWNER_READBACK" if plan.get("execution_kind") is not None else "NOT_REPORTED"
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
        "owner_run_id": plan.get("run_id"),
        "owner_product_sha256": plan.get("product_sha256") or plan.get("sha256"),
        "owner_input_identity": plan.get("input_identity"),
        "owner_failure_reasons": plan.get("failure_reasons"),
        "idempotency_status": (
            "OWNER_RETURNED_EXISTING_RUN" if plan_status in existing_statuses
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
        "idempotency_status": "NO_RETRY_OWNER_READBACK_REQUIRED",
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


def _daily_mapping_content(value: Mapping[str, Any]) -> dict[str, Any]:
    """Ignore per-run metadata when checking whether a verified daily map can be reused."""
    return {key: value.get(key) for key in (
        "schema_version", "status", "target_trade_date", "us_session_date",
        "coverage_scope", "coverage", "matches", "source_status", "source_identity",
        "source_gaps", "input_identity", "relation_assessment_identity",
        "relation_source_identities", "relation_artifact_sha256", "target_date_eligibility", "gaps",
    )}


def _aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def _prepare_us_mapping(service: Any, date: str, now: datetime) -> dict[str, Any]:
    """Reuse byte-verified identical content; otherwise persist a fresh owner run."""
    try:
        from .us_mapping_research import _read_saved, build_daily_run
        existing = _read_saved(service.store, date)
        candidate = build_daily_run(service, date, now=now)
        available = _aware_timestamp(existing.get("generated_at")) if isinstance(existing, Mapping) else None
        prior_cutoff = _aware_timestamp(existing.get("research_cutoff")) if isinstance(existing, Mapping) else None
        if (isinstance(existing, Mapping) and existing.get("status") in {"COMPLETED", "VALID_EMPTY"}
                and available is not None and prior_cutoff is not None and available <= now and prior_cutoff <= now
                and _daily_mapping_content(existing) == _daily_mapping_content(candidate)):
            return existing
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError):
        pass
    return service.refresh_us_mapping_research(date, now=now)


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
    if (getattr(service, "_existing_research_source", None) is None
            or getattr(service, "_workspace_us_market_reader", None) is None):
        raise ValueError("PLAN_OWNER_FULL_READERS_REQUIRED")
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None or _expected_target(binding, now) != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    branch = _scheduled_branch(binding, source_date, date, now)
    parent_identity = _parent_trigger_identity(source_date, date, branch, actual_sha)
    daily = None
    if branch == "PREOPEN" and date == source_date:
        # Persist the same-date US mapping before the owner computes its plan;
        # workspace.py reads only the saved owner artifact and enforces cutoff.
        try:
            daily = _prepare_us_mapping(service, date, now)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            daily = {"status": "FAILED", "target_trade_date": date,
                     "gaps": ["US_MAPPING_DAILY_OWNER_FAILED:" + type(exc).__name__], **FLAGS}
    from ops.run_manager_announcement_cycle import run_scheduled_plan_target
    result = service._workspace_reads.run(
        (date, "SCHEDULED_PLAN_OWNER", parent_identity["trigger_id"]),
        lambda: run_scheduled_plan_target(service, date, now.astimezone(HK).strftime("%Y%m%d"),
            now=now, plan_config=binding.get("plan_material_refresh"),
            preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan")), seconds=30.0)
    if result.get("branch") != branch:
        raise ValueError("PLAN_OWNER_PARENT_TRIGGER_BRANCH_READBACK_MISMATCH")
    if branch == "PREOPEN" and date == source_date:
        daily = daily or {"status": "CANNOT_CONFIRM", "target_trade_date": date,
                          "gaps": ["US_MAPPING_DAILY_OWNER_RESULT_MISSING"], **FLAGS}
        result = {**result, "us_mapping_research": compact_cycle_receipt(daily)}
        if daily.get("status") not in {"COMPLETED", "VALID_EMPTY"}:
            result["status"] = "FAILED" if result.get("status") == "FAILED" else "PARTIAL"
    else:
        result = {**result, "us_mapping_research": {
            "status": "NOT_DUE_US_SESSION_NOT_CLOSED", "target_trade_date": date,
            "source_date": now.astimezone(HK).strftime("%Y%m%d"), **FLAGS}}
    return {
        **compact_cycle_receipt(result),
        "schema_version": SCHEMA,
        "owner": OWNER,
        "binding_sha256": actual_sha,
        "target_trade_date": date,
        "parent_trigger_receipt": _parent_trigger_receipt(parent_identity, now=now, result=result),
        **FLAGS,
    }


def request_bound_plan_cycle(binding_path: str | Path, target_date: str) -> dict[str, Any]:
    """One fixed loopback request with no proxy, redirect, retry, or fallback."""
    raw_binding = _raw_binding(binding_path)
    sha = hashlib.sha256(raw_binding).hexdigest()
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    try:
        binding_value = json.loads(raw_binding)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID") from exc
    if not isinstance(binding_value, Mapping):
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID")
    source_date = now.astimezone(HK).strftime("%Y%m%d")
    branch = _scheduled_branch(binding_value, source_date, date, now)
    parent_identity = _parent_trigger_identity(source_date, date, branch, sha)
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
        owner_identity_verified = (
            isinstance(server_trigger, dict)
            and re.fullmatch(r"[0-9a-f]{32}", str(server_trigger.get("owner_run_id") or "")) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(server_trigger.get("owner_product_sha256") or "")) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(server_trigger.get("owner_input_identity") or "")) is not None
        )
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
                or value.get("owner") != OWNER or value.get("target_trade_date") != date
                or value.get("binding_sha256") != sha
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
                or server_trigger.get("owner") != OWNER
                or server_trigger.get("status") != server_status
                or owner_readback_status not in {"VERIFIED", "UNVERIFIED"}
                or (owner_readback_status == "VERIFIED" and not owner_identity_verified)
                or (server_status == "SUCCEEDED" and (
                    owner_readback_status != "VERIFIED" or not owner_identity_verified
                ))
                or (owner_readback_status == "UNVERIFIED" and server_status not in {"PARTIAL", "FAILED"})):
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID",
                                        http_status=response.status)
        return value
    finally:
        connection.close()


__all__ = ["APP_ROOT", "OWNER", "SCHEMA", "compact_cycle_receipt", "execute_bound_plan_cycle", "request_bound_plan_cycle"]
