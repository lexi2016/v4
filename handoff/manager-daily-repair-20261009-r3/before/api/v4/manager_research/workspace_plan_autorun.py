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
PLAN_OWNER = "ManagerResearchJobService.refresh_workspace_plan"


def owner_plan_readback(value: Any, target_trade_date: str, *, expected_kind: str,
                        allow_preserved_preopen: bool = False) -> dict[str, Any]:
    """Accept only an existing owner's exact product and same-run terminal attempt."""
    from .workspace import validate_attempt

    date = date_token(target_trade_date)
    product = value.get("plan_product") if isinstance(value, Mapping) else None
    attempt = value.get("workspace_plan_attempt") if isinstance(value, Mapping) else None
    if not isinstance(product, Mapping) or not isinstance(attempt, Mapping):
        raise ValueError("PLAN_OWNER_PRODUCT_AND_ATTEMPT_REQUIRED")
    attempt = validate_attempt(attempt, date)
    kind = product.get("execution_kind")
    product_status = product.get("status")
    preserved = (allow_preserved_preopen and product_status == "PRESERVED_SCHEDULED_PREOPEN"
                 and kind == "SCHEDULED_PREOPEN")
    if kind != expected_kind and not preserved:
        raise ValueError("PLAN_OWNER_EXECUTION_KIND_MISMATCH")
    run_id = str(product.get("run_id") or "")
    product_sha = str(product.get("sha256") or "")
    identity = str(value.get("input_identity") or "")
    generated = timestamp(product.get("generated_at"))
    if (value.get("target_trade_date") != date
            or product_status not in {"CURRENT", "ALREADY_MATERIALIZED", "PRESERVED_SCHEDULED_PREOPEN"}
            or product.get("consumed") is not True
            or product.get("original_owner") != PLAN_OWNER
            or not re.fullmatch(r"[0-9a-f]{32}", run_id)
            or not re.fullmatch(r"[0-9a-f]{64}", product_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", identity)
            or generated is None or attempt.get("run_id") != run_id
            or attempt.get("owner") != PLAN_OWNER or attempt.get("execution_kind") != kind
            or attempt.get("input_identity") != identity
            or attempt.get("state") not in {"SUCCEEDED", "SUCCEEDED_EMPTY", "PARTIAL"}
            or (attempt.get("state") == "PARTIAL") != bool(attempt.get("failure_reasons"))
            or timestamp(attempt.get("started_at")) > generated
            or timestamp(attempt.get("finished_at")) < generated):
        raise ValueError("PLAN_OWNER_PRODUCT_ATTEMPT_READBACK_MISMATCH")
    status = "PARTIAL" if attempt["state"] == "PARTIAL" else (
        "MATERIALIZED" if product_status == "CURRENT" else product_status)
    return {
        "status": status, "owner_product_status": product_status,
        "target_trade_date": date, "owner": PLAN_OWNER,
        "run_id": run_id, "product_sha256": product_sha, "input_identity": identity,
        "generated_at": product["generated_at"], "execution_kind": kind,
        "execution_kind_source": "OWNER_READBACK",
        "owner_attempt_run_id": attempt["run_id"], "owner_attempt_sha256": attempt["sha256"],
        "owner_attempt_state": attempt["state"], "owner_finished_at": attempt["finished_at"],
        "failure_reasons": list(attempt["failure_reasons"]),
        "policy_status": "PROPOSAL_ONLY",
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
    readback = owner_plan_readback(value, target_trade_date, expected_kind="SCHEDULED_PREOPEN")
    if (timestamp(readback["generated_at"]) >= opening
            or timestamp(readback["owner_finished_at"]) >= opening):
        return {
            **readback,
            "status": "MISSED_COMPLETION_BOUNDARY",
            "policy_status": "PROPOSAL_ONLY",
        }
    return {
        **readback,
        "research_cutoff": value.get("plan_context", {}).get("research_cutoff") if isinstance(value, Mapping) else None,
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
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", reason):
            reason = type(exc).__name__
        return {
            "status": "FAILED",
            "reason": reason,
            "failure_reasons": ["PREOPEN_PLAN_OWNER_FAILED:" + reason],
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
    readback = owner_plan_readback(value, date, expected_kind="SCHEDULED_MORNING",
                                  allow_preserved_preopen=True)
    if (timestamp(readback["generated_at"]) >= freeze
            or timestamp(readback["owner_finished_at"]) >= freeze):
        return {**readback, "status": "MISSED_COMPLETION_BOUNDARY"}
    return {
        **readback,
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
    "owner_plan_readback",
    "preopen_window",
    "run_scheduled_morning_plan",
    "run_scheduled_preopen_plan",
    "run_scheduled_preopen_plan_safe",
]
