"""Bounded scheduled materialization of the existing Manager workspace plan.

This module does not collect data and does not own a scheduler.  The existing
announcement worker may call it during a narrow pre-open window.  Late calls
fail closed instead of backfilling a product that could be mistaken for a
pre-open plan.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Mapping

from .workspace_projection import HK, date_token, timestamp

DEFAULT_CONFIG = {
    "enabled": True,
    "lead_seconds": 180,
    "status": "PROPOSAL_ONLY",
}


def _config(value: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(DEFAULT_CONFIG)
    if isinstance(value, Mapping):
        if "enabled" in value:
            result["enabled"] = value["enabled"]
        if "lead_seconds" in value:
            result["lead_seconds"] = value["lead_seconds"]
    if type(result["enabled"]) is not bool:
        raise ValueError("PREOPEN_PLAN_ENABLED_INVALID")
    lead = result["lead_seconds"]
    if isinstance(lead, bool) or not isinstance(lead, int) or not 1 <= lead <= 300:
        raise ValueError("PREOPEN_PLAN_LEAD_SECONDS_INVALID")
    result["status"] = "PROPOSAL_ONLY"
    return result


def preopen_window(target_trade_date: str, *, lead_seconds: int = 60) -> tuple[datetime, datetime]:
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState

    date = date_token(target_trade_date)
    config = _config({"lead_seconds": lead_seconds})
    calendar = load_market_calendar()
    state = resolve_market_states(calendar, date)["hk_securities"]
    if state not in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
        raise ValueError("PREOPEN_PLAN_TARGET_NOT_HK_TRADING_SESSION")
    # The Manager plan is consumed immediately before the first continuous
    # Stage window, not before the 09:00 auction session.  Reuse the existing
    # frozen Stage contract so this boundary is not a new guessed market clock.
    from contracts.stages import STAGE_DEFINITIONS, STAGE_MARKET_SCOPES
    stage = STAGE_DEFINITIONS.get("STAGE_0930_0935")
    scopes = STAGE_MARKET_SCOPES.get("STAGE_0930_0935", ())
    start_value = str((stage or {}).get("start", ""))
    if "HK" not in scopes or len(start_value) < 5:
        raise ValueError("PREOPEN_PLAN_STAGE_BOUNDARY_UNAVAILABLE")
    hhmm = start_value[:5].replace(":", "")
    if len(hhmm) != 4 or not hhmm.isdigit():
        raise ValueError("PREOPEN_PLAN_STAGE_BOUNDARY_INVALID")
    opening = datetime.strptime(date + hhmm, "%Y%m%d%H%M").replace(tzinfo=HK)
    return opening - timedelta(seconds=config["lead_seconds"]), opening


def run_scheduled_preopen_plan(
    service: Any,
    target_trade_date: str,
    *,
    now: datetime,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _config(config)
    if now.tzinfo is None:
        raise ValueError("PREOPEN_PLAN_CLOCK_MUST_BE_AWARE")
    local = now.astimezone(HK)
    if not cfg["enabled"]:
        return {"status": "DISABLED", "policy_status": "PROPOSAL_ONLY"}
    start, opening = preopen_window(target_trade_date, lead_seconds=cfg["lead_seconds"])
    if local < start:
        return {"status": "NOT_DUE", "window_start": start.isoformat(), "window_end": opening.isoformat(), "policy_status": "PROPOSAL_ONLY"}
    if local >= opening:
        return {"status": "EXPIRED_NO_BACKFILL", "window_start": start.isoformat(), "window_end": opening.isoformat(), "policy_status": "PROPOSAL_ONLY"}
    # Identity and duplicate publication are checked together by the original
    # owner under its transaction. Timestamp-only fast paths retain stale plans.
    value = service.refresh_workspace_plan(
        date_token(target_trade_date), execution_kind="SCHEDULED_PREOPEN", now=local, deadline=opening
    )
    product = value.get("plan_product") if isinstance(value, Mapping) else None
    if isinstance(product,Mapping) and product.get("status")=="ALREADY_MATERIALIZED":
        return {"status":"ALREADY_MATERIALIZED","run_id":product.get("run_id"),
            "generated_at":product.get("generated_at"),"policy_status":"PROPOSAL_ONLY"}
    generated = timestamp(product.get("generated_at")) if isinstance(product, Mapping) else None
    if generated is None or generated >= opening:
        return {
            "status": "MISSED_COMPLETION_BOUNDARY",
            "run_id": product.get("run_id") if isinstance(product, Mapping) else None,
            "generated_at": product.get("generated_at") if isinstance(product, Mapping) else None,
            "policy_status": "PROPOSAL_ONLY",
        }
    return {
        "status": "MATERIALIZED",
        "run_id": product.get("run_id") if isinstance(product, Mapping) else None,
        "generated_at": product.get("generated_at") if isinstance(product, Mapping) else None,
        "research_cutoff": value.get("plan_context", {}).get("research_cutoff") if isinstance(value, Mapping) else None,
        "policy_status": "PROPOSAL_ONLY",
    }


def run_scheduled_preopen_plan_safe(
    service: Any,
    target_trade_date: str,
    *,
    now: datetime,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Isolate plan-freeze failure from the announcement owner execution."""
    try:
        return run_scheduled_preopen_plan(service, target_trade_date, now=now, config=config)
    except Exception as exc:  # bounded worker records the class; never the message/secrets
        return {
            "status": "FAILED",
            "reason": type(exc).__name__,
            "blocks_announcement": False,
            "policy_status": "PROPOSAL_ONLY",
        }


MORNING_DEFAULT_CONFIG = {"enabled": False, "interval_seconds": 300, "status": "PROPOSAL_ONLY"}


def morning_config(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config = dict(MORNING_DEFAULT_CONFIG)
    if value is not None:
        if not isinstance(value, Mapping) or set(value) - set(config):
            raise ValueError("MORNING_PLAN_CONFIG_INVALID")
        config.update(value)
    if (type(config["enabled"]) is not bool
            or type(config["interval_seconds"]) is not int
            or config["interval_seconds"] not in {300, 600, 900}
            or config["status"] != "PROPOSAL_ONLY"):
        raise ValueError("MORNING_PLAN_CONFIG_INVALID")
    return config


def morning_window(target_trade_date: str) -> tuple[datetime, datetime]:
    """Return the bounded plan window, ending before the existing pre-open owner."""
    freeze, _ = preopen_window(target_trade_date, lead_seconds=300)
    return freeze.replace(hour=7, minute=0, second=0, microsecond=0), freeze


def run_scheduled_morning_plan(
    service: Any,
    target_trade_date: str,
    *,
    now: datetime,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = morning_config(config)
    if now.tzinfo is None:
        raise ValueError("MORNING_PLAN_CLOCK_MUST_BE_AWARE")
    if not cfg["enabled"]:
        return {"status": "DISABLED", "policy_status": "PROPOSAL_ONLY"}
    date = date_token(target_trade_date)
    local = now.astimezone(HK)
    if local.strftime("%Y%m%d") != date:
        raise ValueError("MORNING_PLAN_DATE_CLOCK_MISMATCH")
    start, freeze = morning_window(date)
    if local < start:
        return {"status": "NOT_DUE", "target_trade_date": date, "policy_status": "PROPOSAL_ONLY"}
    if local >= freeze:
        return {"status": "EXPIRED_NO_BACKFILL", "target_trade_date": date, "policy_status": "PROPOSAL_ONLY"}
    if (local.hour * 60 + local.minute) % (cfg["interval_seconds"] // 60):
        return {"status": "INTERVAL_NOT_DUE", "target_trade_date": date, "policy_status": "PROPOSAL_ONLY"}

    value = service.refresh_workspace_plan(
        date, execution_kind="SCHEDULED_MORNING", now=local, deadline=freeze
    )
    product = value.get("plan_product") if isinstance(value, Mapping) else None
    attempt = value.get("workspace_plan_attempt") if isinstance(value, Mapping) else None
    product = product if isinstance(product, Mapping) else {}
    attempt = attempt if isinstance(attempt, Mapping) else {}
    state = attempt.get("state")
    status = product.get("status")
    if status == "CURRENT":
        status = "PARTIAL" if state == "PARTIAL" else "MATERIALIZED"
    if status not in {"MATERIALIZED", "PARTIAL", "ALREADY_MATERIALIZED", "PRESERVED_SCHEDULED_PREOPEN"}:
        raise ValueError("MORNING_PLAN_OWNER_READBACK_INVALID")
    if not re.fullmatch(r"[0-9a-f]{32}", str(product.get("run_id") or "")):
        raise ValueError("MORNING_PLAN_RUN_ID_INVALID")
    return {
        "status": status,
        "target_trade_date": date,
        "run_id": product.get("run_id"),
        "product_sha256": product.get("sha256"),
        "input_identity": value.get("input_identity") if isinstance(value, Mapping) else None,
        "generated_at": product.get("generated_at"),
        "owner": "ManagerResearchJobService.refresh_workspace_plan",
        "policy_status": "PROPOSAL_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


__all__ = [
    "DEFAULT_CONFIG",
    "MORNING_DEFAULT_CONFIG",
    "morning_config",
    "morning_window",
    "preopen_window",
    "run_scheduled_morning_plan",
    "run_scheduled_preopen_plan",
    "run_scheduled_preopen_plan_safe",
]
