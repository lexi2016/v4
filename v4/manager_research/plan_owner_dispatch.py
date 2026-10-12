"""Bounded loopback RPC to the API's fully injected ManagerResearch owner."""
from __future__ import annotations

from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Mapping
from urllib.parse import urlencode

from infrastructure.owned_io import SafeRoot
from .workspace_projection import HK, FLAGS, date_token

APP_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "v4.manager_research.bound_plan_cycle.v1"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
ANNOUNCEMENT_REFRESH_SCHEMA = "v4.manager_research.bound_hkex_announcement_refresh.v1"
ANNOUNCEMENT_OWNER = "ManagerResearchJobService.refresh_announcements"
PARENT_TRIGGER_SCHEMA = "v4.manager_research.bound_plan_cycle_trigger.v1"
MAX_RESPONSE_BYTES = 256 * 1024
KNOWN_RPC_HTTP_ERROR_DETAILS = frozenset({"SCHEDULED_WORKSPACE_OWNER_FAILED"})



RPC_FAILURE_CODES = frozenset({
    "PLAN_OWNER_RPC_FAILED", "PLAN_OWNER_RPC_TRANSPORT_FAILED", "PLAN_OWNER_RPC_RESPONSE_TOO_LARGE",
    "PLAN_OWNER_RPC_CONTENT_TYPE_INVALID", "PLAN_OWNER_RPC_RESPONSE_JSON_INVALID",
    "PLAN_OWNER_RPC_PARENT_TRIGGER_READBACK_INVALID", "PLAN_OWNER_RPC_DEADLINE_EXCEEDED",
    "PLAN_OWNER_CHILD_DEADLINE_EXCEEDED", "SCHEDULED_WORKSPACE_OWNER_FAILED",
}) | frozenset(f"PLAN_OWNER_RPC_HTTP_{status}" for status in range(100, 600))


def rpc_call_failure(exc: Exception) -> dict[str, Any]:
    """A caller exception is not proof of remote non-execution."""
    reason = str(exc)
    safe_reason = reason if reason in RPC_FAILURE_CODES else "PLAN_OWNER_RPC_FAILED"
    phase = "TRANSPORT" if safe_reason in {"PLAN_OWNER_RPC_TRANSPORT_FAILED",
        "PLAN_OWNER_RPC_DEADLINE_EXCEEDED", "PLAN_OWNER_CHILD_DEADLINE_EXCEEDED"} else "READBACK"
    result = {"status": "FAILED", "reason": safe_reason, "failure_stage": phase,
        "owner_execution_status": "CANNOT_CONFIRM",
        "outcome": "OWNER_READBACK_REQUIRED_NO_RETRY", **FLAGS}
    if safe_reason in {"PLAN_OWNER_RPC_DEADLINE_EXCEEDED", "PLAN_OWNER_CHILD_DEADLINE_EXCEEDED"}:
        result["deadline_exceeded"] = True
    return result

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
                          code: str, http_status: int | None = None,
                          deadline_seconds: float | None = None,
                          elapsed_seconds: float | None = None) -> dict[str, Any]:
    safe_code = code if code in RPC_FAILURE_CODES else "PLAN_OWNER_RPC_FAILED"
    phase = "TRANSPORT" if safe_code in {"PLAN_OWNER_RPC_TRANSPORT_FAILED",
        "PLAN_OWNER_RPC_DEADLINE_EXCEEDED", "PLAN_OWNER_CHILD_DEADLINE_EXCEEDED"} else "READBACK"
    receipt = {
        **dict(identity), "triggered_at": now.isoformat(), "status": "FAILED",
        "owner": OWNER, "owner_readback_status": "NOT_CONFIRMED",
        "failure_code": safe_code, "failure_stage": phase,
        "owner_execution_status": "CANNOT_CONFIRM",
        "outcome": "OWNER_READBACK_REQUIRED_NO_RETRY",
        "request_count": 1, "idempotency_status": "NO_RETRY_OWNER_READBACK_REQUIRED",
    }
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        receipt["http_status"] = http_status
    if isinstance(deadline_seconds, (int, float)) and not isinstance(deadline_seconds, bool):
        receipt["deadline_seconds"] = float(deadline_seconds)
    if isinstance(elapsed_seconds, (int, float)) and not isinstance(elapsed_seconds, bool):
        receipt["elapsed_seconds"] = max(0.0, float(elapsed_seconds))
    return {
        "schema_version": SCHEMA, "status": "FAILED", "owner": OWNER,
        "binding_sha256": identity["binding_sha256"],
        "target_trade_date": identity["target_trade_date"],
        "failure_stage": phase, "owner_execution_status": "CANNOT_CONFIRM",
        "outcome": "OWNER_READBACK_REQUIRED_NO_RETRY",
        "deadline_exceeded": safe_code in {"PLAN_OWNER_RPC_DEADLINE_EXCEEDED", "PLAN_OWNER_CHILD_DEADLINE_EXCEEDED"},
        "parent_trigger_receipt": receipt, **FLAGS,
    }


class PlanOwnerRpcDeadlineExceeded(TimeoutError):
    def __init__(self, deadline_seconds: float, elapsed_seconds: float):
        self.deadline_seconds = float(deadline_seconds)
        self.elapsed_seconds = max(0.0, float(elapsed_seconds))
        super().__init__("PLAN_OWNER_RPC_DEADLINE_EXCEEDED")


def _post_loopback_with_deadline(connection: Any, path: str, *, deadline_seconds: float,
                                 deadline_at: float | None = None, monotonic=None) -> tuple[int, str, bytes, float]:
    """POST once and bound connect, request, headers, and every response read."""
    clock = monotonic or time.monotonic
    started = clock()
    deadline = started + float(deadline_seconds) if deadline_at is None else float(deadline_at)

    def remaining() -> float:
        seconds = deadline - clock()
        if seconds <= 0:
            raise PlanOwnerRpcDeadlineExceeded(deadline_seconds, clock() - started)
        return seconds

    def set_socket_timeout() -> None:
        seconds = remaining()
        sock = getattr(connection, "sock", None)
        if sock is not None:
            sock.settimeout(seconds)

    try:
        connection.timeout = remaining()
        connection.connect()
        set_socket_timeout()
        connection.request("POST", path, body=b"",
            headers={"Content-Length": "0", "Accept": "application/json"})
        set_socket_timeout()
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "").split(";", 1)[0]
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_RESPONSE_BYTES:
            set_socket_timeout()
            chunk = response.read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        elapsed = clock() - started
        if elapsed >= deadline_seconds:
            raise PlanOwnerRpcDeadlineExceeded(deadline_seconds, elapsed)
        return response.status, content_type, b"".join(chunks), max(0.0, elapsed)
    except PlanOwnerRpcDeadlineExceeded:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise PlanOwnerRpcDeadlineExceeded(deadline_seconds, clock() - started) from exc


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



def _announcement_owner_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep owner status and provenance while excluding raw rows and bodies."""
    attempt = value.get("attempt")
    attempt_keys = ("state", "run_id", "started_at", "finished_at", "last_success_at",
                    "failure_reasons", "input_identity", "input_coverage")
    coverage = value.get("coverage")
    coverage_keys = ("publication_date", "observed_document_count", "observed_count_is_not_market_total",
                     "source_coverage_cutoff", "queried_issuer_count", "successfully_observed_issuer_count",
                     "failed_issuers", "pending_document_count", "directory_exhaustion",
                     "all_official_announcements_captured")
    captures = value.get("capture_runs")
    capture_keys = ("capture_trade_date", "run_id", "revision", "sha256", "generated_at",
                    "query_since", "query_cutoff", "scope_count", "scope_identity",
                    "observed_for_publication_date")
    network_requests = value.get("network_requests")
    return {
        "status": value.get("status") if isinstance(value.get("status"), str) else "CANNOT_CONFIRM",
        "target_trade_date": value.get("target_trade_date"),
        "daily_publication_date": value.get("daily_publication_date"),
        "publication_timezone": value.get("publication_timezone"),
        "count_known": value.get("count_known") if type(value.get("count_known")) is bool else None,
        "gaps": list(value.get("gaps")) if isinstance(value.get("gaps"), list) else None,
        "attempt": ({key: attempt[key] for key in attempt_keys if key in attempt}
                    if isinstance(attempt, Mapping) else None),
        "coverage": ({key: coverage[key] for key in coverage_keys if key in coverage}
                     if isinstance(coverage, Mapping) else None),
        "capture_runs": ([{key: row[key] for key in capture_keys if key in row}
                          for row in captures if isinstance(row, Mapping)]
                         if isinstance(captures, list) else None),
        "network_requests": (network_requests if type(network_requests) is int and network_requests >= 0 else None),
        "network_requests_status": ("REPORTED_BY_ANNOUNCEMENT_OWNER"
            if type(network_requests) is int and network_requests >= 0 else "NOT_REPORTED_BY_ANNOUNCEMENT_OWNER"),
    }


def _refresh_bound_hkex_announcements(service: Any, binding: Mapping[str, Any],
                                      identity: Mapping[str, str], *,
                                      daily_mode: bool = False) -> dict[str, Any]:
    """Use the existing schedule-aware HKEX owner once before plan reads."""
    if type(daily_mode) is not bool:
        raise ValueError("ANNOUNCEMENT_DAILY_MODE_INVALID")
    source_date = str(identity.get("source_trade_date") or "")
    plan_date = str(identity.get("target_trade_date") or "")
    branch = str(identity.get("branch") or "")
    result: dict[str, Any] = {
        "schema_version": ANNOUNCEMENT_REFRESH_SCHEMA,
        "owner": ANNOUNCEMENT_OWNER,
        "branch": branch,
        "capture_target_date": source_date,
        "plan_target_date": plan_date,
        "owner_execution_status": "OWNER_NOT_CALLED",
        "outcome": "OWNER_NOT_CALLED",
        "status": "CANNOT_CONFIRM",
        "network_requests": None,
        "network_requests_status": "NOT_REPORTED_BY_ANNOUNCEMENT_OWNER",
        "retry_status": "NO_AUTOMATIC_RETRY",
        **FLAGS,
    }
    owner_started = False
    try:
        source_date = date_token(source_date)
        plan_date = date_token(plan_date)
        now = clock_now()
        if (now.tzinfo is None or now.astimezone(HK).strftime("%Y%m%d") != source_date
                or _expected_target(binding, now) != plan_date
                or _scheduled_branch(binding, source_date, plan_date, now) != branch):
            result["failure_reasons"] = ["PLAN_OWNER_WINDOW_EXPIRED_BEFORE_ANNOUNCEMENT_REFRESH"]
            return result
        policy = binding.get("policy")
        priorities = binding.get("priority_codes")
        if policy not in {"BALANCED_V1", "LOW_LOAD_V1"} or not isinstance(priorities, list):
            result["failure_reasons"] = ["ANNOUNCEMENT_SCHEDULE_POLICY_INVALID"]
            return result
        from .announcement_autorun import policy_due
        policy_open = policy_due(now, policy)
        if policy_open is not True:
            result["failure_reasons"] = ["ANNOUNCEMENT_POLICY_WINDOW_NOT_DUE"]
            return result
        refresh = getattr(service, "refresh_announcements", None)
        if not callable(refresh):
            result["failure_reasons"] = ["ANNOUNCEMENT_OWNER_REFRESH_UNAVAILABLE"]
            return result
        schedule = {
            "policy": policy,
            "now": now.isoformat(),
            "priority_codes": list(priorities),
            "execution_identity": {
                "source_trade_date": source_date,
                "plan_target_date": plan_date,
                "plan_branch": branch,
                "plan_trigger_id": identity.get("trigger_id"),
                "plan_binding_sha256": identity.get("binding_sha256"),
            },
        }
        if daily_mode:
            schedule["capture_mode"] = "HK_CALENDAR_DAY_V1"
        owner_started = True
        owner_value = refresh(source_date, schedule=schedule)
        if not isinstance(owner_value, Mapping):
            result.update(owner_execution_status="CANNOT_CONFIRM",
                outcome="OWNER_READBACK_REQUIRED_NO_RETRY",
                failure_reasons=["ANNOUNCEMENT_OWNER_REFRESH_RESPONSE_INVALID"])
            return result
        summary = _announcement_owner_summary(owner_value)
        if summary.get("target_trade_date") != source_date:
            result.update(owner_execution_status="CANNOT_CONFIRM",
                outcome="OWNER_READBACK_REQUIRED_NO_RETRY",
                failure_reasons=["ANNOUNCEMENT_OWNER_TARGET_DATE_MISMATCH"], owner_response=summary)
            return result
        result.update(owner_execution_status="OWNER_RESPONSE_RECEIVED",
            outcome="OWNER_RESPONSE_RECEIVED", status=summary["status"],
            owner_response=summary, failure_reasons=summary.get("gaps") or [])
        result["network_requests"] = summary.get("network_requests")
        result["network_requests_status"] = summary.get("network_requests_status")
        return result
    except Exception as exc:
        result.update(owner_execution_status="CANNOT_CONFIRM",
            outcome=("OWNER_READBACK_REQUIRED_NO_RETRY" if owner_started else "OWNER_NOT_CALLED"),
            failure_reasons=["ANNOUNCEMENT_OWNER_REFRESH_EXCEPTION" if owner_started
                else "ANNOUNCEMENT_OWNER_ADMISSION_UNVERIFIED"],
            exception_type=type(exc).__name__)
        return result

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
    announcement_refresh = _refresh_bound_hkex_announcements(service, binding, parent_identity)
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
    from infrastructure.scheduling.manager_announcement_supervisor import PLAN_OWNER_WORKSPACE_READBACK_BUDGET_SECONDS
    result = service._workspace_reads.run(
        (date, "SCHEDULED_PLAN_OWNER", parent_identity["trigger_id"]),
        lambda: run_scheduled_plan_target(service, date, now.astimezone(HK).strftime("%Y%m%d"),
            now=now, plan_config=binding.get("plan_material_refresh"),
            preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan")),
        seconds=PLAN_OWNER_WORKSPACE_READBACK_BUDGET_SECONDS)
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
        "hkex_announcement_refresh": announcement_refresh,
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
    from infrastructure.scheduling.manager_announcement_supervisor import PLAN_OWNER_RPC_TIMEOUT_SECONDS
    rpc_deadline_seconds = PLAN_OWNER_RPC_TIMEOUT_SECONDS
    rpc_started = time.monotonic()
    rpc_deadline_at = rpc_started + rpc_deadline_seconds
    connection = http.client.HTTPConnection("127.0.0.1", 8873, timeout=rpc_deadline_seconds)
    try:
        path = "/api/v4/manager/research/workspace/scheduled-cycle?" + urlencode(
            {"date": date, "binding_sha256": sha})
        try:
            http_status, content_type, raw, _rpc_elapsed = _post_loopback_with_deadline(
                connection, path, deadline_seconds=rpc_deadline_seconds, deadline_at=rpc_deadline_at)
        except PlanOwnerRpcDeadlineExceeded as exc:
            return _rpc_failure_receipt(parent_identity, now=now,
                code="PLAN_OWNER_RPC_DEADLINE_EXCEEDED", deadline_seconds=rpc_deadline_seconds,
                elapsed_seconds=exc.elapsed_seconds)
        except (OSError, TimeoutError, http.client.HTTPException):
            return _rpc_failure_receipt(parent_identity, now=now,
                code="PLAN_OWNER_RPC_TRANSPORT_FAILED", deadline_seconds=rpc_deadline_seconds,
                elapsed_seconds=time.monotonic()-rpc_started)
        network_elapsed = time.monotonic()-rpc_started
        if network_elapsed >= rpc_deadline_seconds:
            return _rpc_failure_receipt(parent_identity, now=now,
                code="PLAN_OWNER_RPC_DEADLINE_EXCEEDED", deadline_seconds=rpc_deadline_seconds,
                elapsed_seconds=network_elapsed)
        if len(raw) > MAX_RESPONSE_BYTES:
            return _rpc_failure_receipt(parent_identity, now=now,
                code="PLAN_OWNER_RPC_RESPONSE_TOO_LARGE", http_status=http_status,
                deadline_seconds=rpc_deadline_seconds, elapsed_seconds=network_elapsed)
        if http_status != 200 or content_type != "application/json":
            code = f"PLAN_OWNER_RPC_HTTP_{http_status}"
            if content_type == "application/json":
                try:
                    error_body = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error_body = None
                detail = error_body.get("detail") if isinstance(error_body, dict) else None
                if isinstance(detail, str) and detail in KNOWN_RPC_HTTP_ERROR_DETAILS:
                    code = detail
            elif http_status == 200:
                code = "PLAN_OWNER_RPC_CONTENT_TYPE_INVALID"
            return _rpc_failure_receipt(parent_identity, now=now, code=code, http_status=http_status,
                                        deadline_seconds=rpc_deadline_seconds,
                                        elapsed_seconds=time.monotonic()-rpc_started)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _rpc_failure_receipt(parent_identity, now=now,
                                        code="PLAN_OWNER_RPC_RESPONSE_JSON_INVALID",
                                        http_status=http_status, deadline_seconds=rpc_deadline_seconds,
                                        elapsed_seconds=time.monotonic()-rpc_started)
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
                                        http_status=http_status, deadline_seconds=rpc_deadline_seconds,
                                        elapsed_seconds=time.monotonic()-rpc_started)
        rpc_elapsed = time.monotonic()-rpc_started
        if rpc_elapsed >= rpc_deadline_seconds:
            return _rpc_failure_receipt(parent_identity, now=now,
                code="PLAN_OWNER_RPC_DEADLINE_EXCEEDED", deadline_seconds=rpc_deadline_seconds,
                elapsed_seconds=rpc_elapsed)
        return value
    finally:
        connection.close()


__all__ = ["APP_ROOT", "OWNER", "SCHEMA", "compact_cycle_receipt", "execute_bound_plan_cycle",
           "PlanOwnerRpcDeadlineExceeded", "_post_loopback_with_deadline", "request_bound_plan_cycle", "rpc_call_failure"]
