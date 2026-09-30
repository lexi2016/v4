"""Bounded loopback RPC to the existing, fully injected V4 plan owner."""
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
MAX_RESPONSE_BYTES = 256 * 1024


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

    return scheduled_cycle_target(
        source_date,
        now=now,
        plan_config=binding.get("plan_material_refresh"),
        preopen_config=binding.get("preopen_plan"),
        morning_plan_config=binding.get("morning_plan"),
    ) or ""


def execute_bound_plan_cycle(service: Any, target_date: str, binding_sha256: str) -> dict[str, Any]:
    """Run one exact-date branch through the API router's existing service object."""
    binding_path = os.environ.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH", "").strip()
    if not binding_path:
        raise ValueError("PLAN_OWNER_SERVER_BINDING_NOT_CONFIGURED")
    raw = _raw_binding(binding_path)
    actual_sha = hashlib.sha256(raw).hexdigest()
    if (not re.fullmatch(r"[0-9a-f]{64}", str(binding_sha256 or ""))
            or actual_sha != binding_sha256):
        raise ValueError("PLAN_OWNER_BINDING_SHA_MISMATCH")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PLAN_OWNER_BINDING_JSON_INVALID") from exc
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding

    binding = validate_binding(value, expected_app=APP_ROOT)
    if not binding.get("enabled"):
        raise ValueError("PLAN_OWNER_BINDING_DISABLED")
    store_root = Path(service.store.root).resolve()
    state_root = Path(str(binding.get("manager_state_root") or "")).resolve()
    master_value = getattr(service, "_workspace_security_master_root", None)
    master_root = Path(master_value).resolve() if master_value is not None else None
    expected_master = Path(str(binding.get("security_master_root") or "")).resolve()
    if store_root != state_root or master_root != expected_master:
        raise ValueError("PLAN_OWNER_STATE_OR_MASTER_ROOT_MISMATCH")
    if (getattr(service, "_existing_research_source", None) is None
            or getattr(service, "_workspace_us_market_reader", None) is None):
        raise ValueError("PLAN_OWNER_FULL_READERS_REQUIRED")
    date = date_token(target_date)
    now = clock_now()
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    if _expected_target(binding, now) != date:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")

    from ops.run_manager_announcement_cycle import run_scheduled_plan_target

    result = service._workspace_reads.run(
        (date, "SCHEDULED_PLAN_OWNER", actual_sha),
        lambda: run_scheduled_plan_target(
            service,
            date,
            now.astimezone(HK).strftime("%Y%m%d"),
            now=now,
            plan_config=binding.get("plan_material_refresh"),
            preopen_config=binding.get("preopen_plan"),
            morning_plan_config=binding.get("morning_plan"),
        ),
        seconds=30.0,
    )
    return {
        **compact_cycle_receipt(result),
        "schema_version": SCHEMA,
        "owner": OWNER,
        "binding_sha256": actual_sha,
        "target_trade_date": date,
        **FLAGS,
    }


def compact_cycle_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Bound RPC output while retaining a hash/count for long failure lists."""
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == "failure_reasons" and isinstance(item, list):
            out["failure_reason_count"] = len(item)
            out["failure_reasons"] = item[:16]
            out["failure_reasons_truncated"] = len(item) > 16
            out["failure_reasons_sha256"] = hashlib.sha256(
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        elif isinstance(item, Mapping):
            out[key] = compact_cycle_receipt(item)
        else:
            out[key] = item
    return out


def request_bound_plan_cycle(binding_path: str | Path, target_date: str) -> dict[str, Any]:
    """One fixed-loopback POST with no proxy, redirect, retry, or narrow-service fallback."""
    raw_binding = _raw_binding(binding_path)
    sha = hashlib.sha256(raw_binding).hexdigest()
    date = date_token(target_date)
    connection = http.client.HTTPConnection("127.0.0.1", 8873, timeout=35.0)
    try:
        path = "/api/v4/manager/research/workspace/scheduled-cycle?" + urlencode(
            {"date": date, "binding_sha256": sha}
        )
        connection.request(
            "POST", path, body=b"", headers={"Content-Length": "0", "Accept": "application/json"}
        )
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "").split(";", 1)[0]
        if response.status != 200 or content_type != "application/json":
            raise ValueError("PLAN_OWNER_RPC_HTTP_OR_CONTENT_TYPE_FAILED")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("PLAN_OWNER_RPC_RESPONSE_TOO_LARGE")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("PLAN_OWNER_RPC_RESPONSE_JSON_INVALID") from exc
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
                or value.get("owner") != OWNER or value.get("target_trade_date") != date
                or value.get("binding_sha256") != sha
                or any(value.get(key) is not flag for key, flag in FLAGS.items())
                or value.get("status") not in {"SUCCEEDED", "PARTIAL", "FAILED"}):
            raise ValueError("PLAN_OWNER_RPC_READBACK_INVALID")
        return value
    finally:
        connection.close()


__all__ = [
    "APP_ROOT",
    "OWNER",
    "SCHEMA",
    "compact_cycle_receipt",
    "execute_bound_plan_cycle",
    "request_bound_plan_cycle",
]
