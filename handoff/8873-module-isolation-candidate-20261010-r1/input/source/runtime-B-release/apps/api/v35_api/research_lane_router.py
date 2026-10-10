"""Research decision-desk API served from V3.5-owned research archives.

The lane, dates, and events endpoints are mounted exclusively from
``ResearchArchiveStore(data_root)`` verified archives plus a validated
V3.5-owned event artifact under ``data_root``. No V3 research-module or
assistant-run-log read exists here, and no event is ever synthesized.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from domains.report_subjects import project_report_roles
from domains.research_day_product import consume_authoritative_research_day
from infrastructure.data_store import _date, _sha256
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_peripheral_store import (
    CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP,
    ResearchPeripheralStore,
)
from infrastructure.research_store import ResearchArchiveStore
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader


GLOBAL_INDUSTRY_PROXY_MAP = CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP
GLOBAL_INDUSTRY_SCHEMA_VERSION = "v3_5.global_industries.v1"
GLOBAL_INDUSTRY_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1"
MARKET_SNAPSHOT_SCHEMA_VERSION = "v3_5.us_market_snapshot.v1"
LATE_CAPTURE_MODE = "CONTROLLED_LATE_POST_CLOSE"
LATE_CAPTURE_REASON = "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY"


def _is_late_capture_identity(value: Any) -> bool:
    """Return whether one payload/snapshot carries the controlled-late marker."""

    return isinstance(value, Mapping) and (
        value.get("late") is True
        or value.get("capture_mode") == LATE_CAPTURE_MODE
    )


_CAPTURE_IDENTITY_FIELDS = (
    "capture_id",
    "run_id",
    "capture_origin",
    "original_time_capture",
    "late",
    "capture_mode",
    "reason",
    "capture_reason",
    "natural_capture_window_start",
    "natural_capture_window_end",
    "allowed_recovery_window_start",
    "allowed_recovery_window_end",
)


def _capture_identity_failure(
    *,
    payload: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    reason: str,
    research_date: str,
    store: ResearchPeripheralStore,
) -> dict[str, Any]:
    """Keep a failed identity typed while retaining exact artifact lineage."""

    result = _global_industry_missing(research_date=research_date, reason=reason)
    result["artifact_trade_date"] = str(payload.get("trade_date") or research_date)
    session_date = str(snapshot.get("capture_session_date") or "")
    result["source_date"] = session_date
    result["us_session_date"] = session_date
    result["capture_session_date"] = session_date
    result["capture_phase"] = str(snapshot.get("capture_phase") or "POST_CLOSE")
    result["artifact"] = _global_industry_lineage(store, research_date, payload)
    return result


def _bound_capture_for_snapshot(
    *,
    payload: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    research_date: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Bind one snapshot to one explicit payload capture identity.

    The store already validates the individual artifact.  This consumer-level
    check additionally prevents a valid snapshot from being paired with an
    unrelated, stale, or ambiguous capture when target and US session dates
    differ.
    """

    session_date = str(snapshot.get("capture_session_date") or "")
    provider_dates = snapshot.get("provider_session_dates")
    if not isinstance(provider_dates, list):
        return None, "MARKET_SNAPSHOT_PROVIDER_SESSION_DATES_UNBOUND"
    normalized_provider_dates = [str(value) for value in provider_dates]
    if (
        len(normalized_provider_dates) != 1
        or normalized_provider_dates[0] != session_date
    ):
        return None, "MARKET_SNAPSHOT_PROVIDER_SESSION_DATE_UNIQUE_REQUIRED"

    captures = payload.get("us_session_captures")
    if not isinstance(captures, list):
        return None, "MARKET_SNAPSHOT_CAPTURE_IDENTITY_UNBOUND"
    snapshot_late = _is_late_capture_identity(snapshot)
    snapshot_phase = str(snapshot.get("capture_phase") or "")
    matches: list[dict[str, Any]] = []
    for value in captures:
        if not isinstance(value, Mapping):
            continue
        capture = dict(value)
        if (
            capture.get("us_session_date") != session_date
            or capture.get("capture_phase") != snapshot_phase
            or capture.get("original_time_capture") is not True
            or capture.get("capture_origin") != "ORIGINAL_TIME_CAPTURE"
            or _is_late_capture_identity(capture) != snapshot_late
            or (
                snapshot_late and capture.get("late") is not True
            )
            or (
                not snapshot_late and capture.get("late", False) is not False
            )
        ):
            continue
        if any(
            field in snapshot
            and snapshot.get(field) is not None
            and capture.get(field) != snapshot.get(field)
            for field in _CAPTURE_IDENTITY_FIELDS
        ):
            continue
        receipt = snapshot.get("provider_receipt")
        if isinstance(receipt, Mapping) and any(
            field in receipt
            and receipt.get(field) is not None
            and capture.get(field) != receipt.get(field)
            for field in _CAPTURE_IDENTITY_FIELDS
        ):
            continue
        matches.append(capture)

    if len(matches) != 1:
        return None, "MARKET_SNAPSHOT_CAPTURE_IDENTITY_AMBIGUOUS_OR_UNBOUND"
    capture = matches[0]
    for field in _CAPTURE_IDENTITY_FIELDS:
        if (
            field in payload
            and payload.get(field) is not None
            and payload.get(field) != capture.get(field)
        ):
            return None, "MARKET_SNAPSHOT_PAYLOAD_CAPTURE_IDENTITY_MISMATCH"

    if snapshot_phase != "POST_CLOSE":
        return None, "MARKET_SNAPSHOT_NOT_POST_CLOSE"
    if snapshot_late:
        if (
            capture.get("capture_mode") != LATE_CAPTURE_MODE
            or capture.get("reason") != LATE_CAPTURE_REASON
            or capture.get("capture_reason") not in (None, LATE_CAPTURE_REASON)
        ):
            return None, "MARKET_SNAPSHOT_LATE_CAPTURE_IDENTITY_INVALID"
        if session_date != research_date:
            # A late cross-date projection is accepted only for the directly
            # preceding calendar date.  Without a bound US holiday calendar,
            # any other date remains CANNOT_CONFIRM rather than being treated
            # as a valid old-session fallback.
            try:
                expected_previous = (
                    datetime.strptime(research_date, "%Y%m%d") - timedelta(days=1)
                ).strftime("%Y%m%d")
            except ValueError:
                return None, "MARKET_SNAPSHOT_TARGET_DATE_INVALID"
            if session_date != expected_previous:
                return None, "MARKET_SNAPSHOT_CAPTURE_DATE_NOT_BOUND_TO_TARGET"
    elif session_date != research_date:
        return None, "MARKET_SNAPSHOT_CROSS_DATE_REQUIRES_LATE_CAPTURE"
    return capture, None


def _global_industry_rows(reason: str) -> list[dict[str, Any]]:
    return [
        {
            "label": str(mapping["label"]),
            "group": str(mapping["group"]),
            "mapping_type": str(mapping["mapping_type"]),
            "proxy_symbols": list(mapping["proxy_symbols"]),
            "available_symbols": [],
            "missing_symbols": list(mapping["proxy_symbols"]),
            "requested_symbol_count": len(mapping["proxy_symbols"]),
            "available_symbol_count": 0,
            "coverage": {"available": 0, "requested": len(mapping["proxy_symbols"])},
            "coverage_pct": 0.0,
            "change_pct": None,
            "pct_change": None,
            "direction": "CANNOT_CONFIRM",
            "status": "CANNOT_CONFIRM",
            "quote_session_dates": [],
            "quote_session_times": [],
            "cannot_confirm": [reason],
        }
        for mapping in GLOBAL_INDUSTRY_PROXY_MAP
    ]


def _global_industry_missing(*, research_date: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": GLOBAL_INDUSTRY_SCHEMA_VERSION,
        "status": "CANNOT_CONFIRM",
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": "",
        "artifact_trade_date": "",
        "us_session_date": "",
        "capture_session_date": "",
        "provider": "Tencent qt.gtimg.cn",
        "provider_receipt": None,
        "provider_session_dates": [],
        "provider_session_times": [],
        "source_response_sha256": "",
        "capture_phase": "POST_CLOSE",
        "captured_at": "",
        "generated_at": "",
        "mapping_version": GLOBAL_INDUSTRY_MAPPING_VERSION,
        "requested_symbol_count": len({
            symbol for mapping in GLOBAL_INDUSTRY_PROXY_MAP for symbol in mapping["proxy_symbols"]
        }),
        "available_symbol_count": 0,
        "rows": _global_industry_rows(reason),
        "quotes": [],
        "cannot_confirm": [reason],
        "artifact": None,
        "manifest": None,
        "receipt": None,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _global_industry_lineage(
    store: ResearchPeripheralStore,
    research_date: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    artifact_path = store.root / "research" / "peripherals" / research_date / "external_finance.json"
    receipt_path = store.root / "receipts" / "research" / "peripherals" / research_date / "external_finance.json"
    manifest_path = store.root / "research" / "peripherals" / "manifest.json"
    result: dict[str, Any] = {"path": str(artifact_path), "sha256": _sha256(payload)}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result["receipt"] = {"path": str(receipt_path), "sha256": _sha256(receipt)}
        result["manifest"] = {"path": str(manifest_path), "sha256": _sha256(manifest)}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        result["lineage_status"] = "CANNOT_CONFIRM"
    return result


def _project_global_industries(
    *,
    store: ResearchPeripheralStore,
    research_date: str,
) -> dict[str, Any]:
    try:
        payload = store.read_exact(research_date, "external_finance")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _global_industry_missing(
            research_date=research_date,
            reason=f"EXACT_EXTERNAL_FINANCE_INVALID:{type(error).__name__}",
        )
    if payload is None:
        return _global_industry_missing(
            research_date=research_date,
            reason="EXACT_EXTERNAL_FINANCE_NOT_MATERIALIZED",
        )
    snapshot = payload.get("market_snapshot")
    if not isinstance(snapshot, Mapping):
        result = _global_industry_missing(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_NOT_MATERIALIZED",
        )
        result["source_date"] = str(payload.get("trade_date") or "")
        result["artifact"] = _global_industry_lineage(store, research_date, payload)
        result["cannot_confirm"] = sorted(
            set(result["cannot_confirm"]) | set(payload.get("cannot_confirm") or [])
        )
        return result
    if (
        snapshot.get("schema_version") != MARKET_SNAPSHOT_SCHEMA_VERSION
        or snapshot.get("mapping_version") != GLOBAL_INDUSTRY_MAPPING_VERSION
    ):
        result = _global_industry_missing(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_CANONICAL_VERSION_INVALID",
        )
        result["source_date"] = str(payload.get("trade_date") or "")
        result["artifact"] = _global_industry_lineage(store, research_date, payload)
        return result
    if any(
        snapshot.get(field) != expected
        for field, expected in {
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "RESEARCH_ONLY": True,
        }.items()
    ):
        result = _global_industry_missing(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_SAFETY_BOUNDARY_INVALID",
        )
        result["source_date"] = str(payload.get("trade_date") or "")
        result["artifact"] = _global_industry_lineage(store, research_date, payload)
        return result
    capture, identity_error = _bound_capture_for_snapshot(
        payload=payload,
        snapshot=snapshot,
        research_date=research_date,
    )
    if identity_error is not None or capture is None:
        return _capture_identity_failure(
            payload=payload,
            snapshot=snapshot,
            reason=identity_error or "MARKET_SNAPSHOT_CAPTURE_IDENTITY_UNBOUND",
            research_date=research_date,
            store=store,
        )
    session_date = str(snapshot.get("capture_session_date") or "")
    rows = list(snapshot.get("rows") or [])
    canonical_rows = list(CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP)
    if len(rows) != 24 or any(
        not isinstance(row, Mapping)
        or row.get("label") != mapping["label"]
        or row.get("group") != mapping["group"]
        or row.get("mapping_type") != mapping["mapping_type"]
        or row.get("proxy_symbols") != list(mapping["proxy_symbols"])
        for row, mapping in zip(rows, canonical_rows)
    ):
        result = _global_industry_missing(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_ROW_COUNT_INVALID",
        )
        result["source_date"] = str(payload.get("trade_date") or "")
        result["artifact"] = _global_industry_lineage(store, research_date, payload)
        return result
    lineage = _global_industry_lineage(store, research_date, payload)
    provider_dates = sorted({
        str(item) for item in snapshot.get("provider_session_dates") or [] if str(item).strip()
    })
    cannot_confirm = sorted(
        set(payload.get("cannot_confirm") or []) | set(snapshot.get("cannot_confirm") or [])
    )
    result: dict[str, Any] = {
        "schema_version": GLOBAL_INDUSTRY_SCHEMA_VERSION,
        "status": str(snapshot.get("status") or "CANNOT_CONFIRM"),
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": session_date,
        "artifact_trade_date": str(payload.get("trade_date") or research_date),
        "us_session_date": session_date,
        "provider": str(snapshot.get("provider") or snapshot.get("source") or "Tencent qt.gtimg.cn"),
        "provider_url": str(snapshot.get("provider_url") or "https://qt.gtimg.cn/q="),
        "provider_session_dates": provider_dates,
        "provider_session_times": sorted({
            str(item) for item in snapshot.get("provider_session_times") or [] if str(item).strip()
        }),
        "source_response_sha256": str(snapshot.get("source_response_sha256") or ""),
        "quotes": list(snapshot.get("quotes") or []),
        "provider_receipt": (
            dict(snapshot["provider_receipt"])
            if isinstance(snapshot.get("provider_receipt"), Mapping)
            else None
        ),
        "capture_phase": str(snapshot.get("capture_phase") or "POST_CLOSE"),
        "capture_session_date": session_date,
        "captured_at": str(snapshot.get("captured_at") or ""),
        "bound_capture_captured_at": capture.get("captured_at"),
        "generated_at": str(snapshot.get("generated_at") or snapshot.get("captured_at") or ""),
        "mapping_version": str(snapshot.get("mapping_version") or ""),
        "requested_symbol_count": int(snapshot.get("requested_symbol_count") or 0),
        "available_symbol_count": int(snapshot.get("available_symbol_count") or 0),
        "rows": rows,
        "cannot_confirm": cannot_confirm,
        "artifact": lineage,
        "manifest": lineage.get("manifest"),
        "receipt": lineage.get("receipt"),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field in (
        "capture_id",
        "run_id",
        "capture_origin",
        "original_time_capture",
        "late",
        "capture_mode",
        "reason",
        "capture_reason",
        "session_timezone",
        "capture_window_start",
        "capture_window_end",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if field in capture:
            result[field] = capture[field]
    if result["capture_phase"] != "POST_CLOSE":
        result["status"] = "CANNOT_CONFIRM"
        result["cannot_confirm"] = sorted(
            set(cannot_confirm) | {"MARKET_SNAPSHOT_NOT_POST_CLOSE"}
        )
    if result["status"] != "CANNOT_CONFIRM" and len(provider_dates) > 1:
        result["status"] = "PARTIAL"
        result["cannot_confirm"] = sorted(set(cannot_confirm) | {"QUOTE_SESSION_DATE_MIXED"})
    return result


def _is_verifiable_close_snapshot(result: Mapping[str, Any]) -> bool:
    """Return whether a projected snapshot can anchor the market-date picker.

    The date discovery endpoint also sees generic ``external_finance``
    articles.  Reuse the normal projection above so manifest, receipt, row
    shape, and capture identity checks remain the single validation path.  A
    projected snapshot is eligible only when its close phase, session date,
    provider-date binding, and raw provider response evidence are present.
    ``PARTIAL`` remains eligible: date discovery must not turn an explicitly
    partial close into a missing date merely because some quotes are absent.
    """

    if result.get("status") not in {"READY", "PARTIAL"}:
        return False
    if result.get("capture_phase") != "POST_CLOSE":
        return False
    source_date = str(result.get("source_date") or "")
    if not source_date:
        return False
    provider_dates = result.get("provider_session_dates")
    if provider_dates != [source_date]:
        return False
    source_response_sha256 = result.get("source_response_sha256")
    if (
        not isinstance(source_response_sha256, str)
        or len(source_response_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in source_response_sha256)
    ):
        return False
    return True


def _verifiable_market_snapshot_dates(
    store: ResearchPeripheralStore,
) -> list[str]:
    """List exact external-finance dates with a verifiable close snapshot."""

    eligible: list[str] = []
    for trade_date in store.list_dates("external_finance"):
        projection = _project_global_industries(
            store=store,
            research_date=trade_date,
        )
        if _is_verifiable_close_snapshot(projection):
            eligible.append(trade_date)
    return sorted(set(eligible), reverse=True)



def _with_us_market_freshness(
    projection: Mapping[str, Any], *, observed: datetime,
) -> dict[str, Any]:
    """Separate stored quality from read-time freshness using the owned 2026 NYSE calendar.

    This remains read-only and keeps the existing capture-window, provider-date,
    raw-response, receipt and manifest checks.  Calendar certification only
    determines which completed US session may be called current.
    """
    result = dict(projection)
    diagnostic: dict[str, Any] = {
        "state": "CANNOT_CONFIRM",
        "observed_at": observed.isoformat(),
        "captured_at": projection.get("captured_at") or "",
        "source_date": projection.get("source_date") or "",
        "basis": "BOUND_PROVIDER_SESSION_AND_OFFICIAL_NYSE_2026_CALENDAR",
        "exchange_calendar_status": "CANNOT_CONFIRM",
        "latest_exchange_session_verified": False,
        "new_capture_performed": False,
        "cannot_confirm": [],
    }
    result.update(display_status="CANNOT_CONFIRM", freshness=diagnostic)
    if not _is_verifiable_close_snapshot(projection):
        diagnostic["cannot_confirm"] = ["VERIFIABLE_CLOSE_SNAPSHOT_REQUIRED"]
        return result

    def timestamp(value: Any) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError("CAPTURE_TIMESTAMP_MISSING")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("CAPTURE_TIMESTAMP_INVALID") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("CAPTURE_TIMESTAMP_TIMEZONE_REQUIRED")
        return parsed

    try:
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("OBSERVATION_TIMEZONE_REQUIRED")
        from contracts.us_equity_calendar import latest_completed_session
        ny_zone = ZoneInfo("America/New_York")
        official_latest = latest_completed_session(observed)
        session = datetime.strptime(str(projection["source_date"]), "%Y%m%d").date()
        captured = timestamp(projection.get("captured_at"))
        bound = timestamp(projection.get("bound_capture_captured_at"))
        generated = timestamp(projection.get("generated_at"))
        if captured != bound:
            raise ValueError("SNAPSHOT_CAPTURE_TIME_BINDING_MISMATCH")
        if captured > observed or generated > observed or generated < captured:
            raise ValueError("SNAPSHOT_CAPTURE_OR_GENERATION_TIME_INVALID")
        start = datetime.combine(session, time(16, 15), tzinfo=ny_zone)
        end = datetime.combine(session, time(16, 20), tzinfo=ny_zone)
        if (timestamp(projection.get("capture_window_start")) != start
                or timestamp(projection.get("capture_window_end")) != end):
            raise ValueError("CAPTURE_WINDOW_BINDING_MISMATCH")
        if _is_late_capture_identity(projection):
            recovery_end = datetime.combine(session, time(20), tzinfo=ny_zone)
            if (projection.get("late") is not True
                    or projection.get("capture_mode") != LATE_CAPTURE_MODE
                    or timestamp(projection.get("allowed_recovery_window_start")) != start
                    or timestamp(projection.get("allowed_recovery_window_end")) != recovery_end):
                raise ValueError("LATE_CAPTURE_WINDOW_BINDING_MISMATCH")
            end = recovery_end
        if not start <= captured < end:
            raise ValueError("CAPTURE_OUTSIDE_ORIGINAL_BOUND_WINDOW")
        latest_date = datetime.strptime(official_latest.session_date, "%Y%m%d").date()
        diagnostic.update(
            latest_exchange_session=official_latest.session_date,
            latest_scheduled_capture_date=official_latest.session_date,
            expected_session_close_at=(official_latest.close_at.isoformat() if official_latest.close_at else None),
            exchange_calendar_source_url=official_latest.source_url,
            exchange_calendar_status="VERIFIED_NYSE_2026",
            latest_exchange_session_verified=True,
            capture_age_seconds=(observed - captured).total_seconds(),
        )
        if session > latest_date:
            raise ValueError("SOURCE_AFTER_LATEST_COMPLETED_EXCHANGE_SESSION")
        if session < latest_date:
            diagnostic.update(state="STALE_EXCHANGE_SESSION", cannot_confirm=[
                "SOURCE_OLDER_THAN_LATEST_COMPLETED_EXCHANGE_SESSION"])
            result["display_status"] = "STALE"
        else:
            diagnostic["state"] = "RECENT_BOUND_CAPTURE"
            # Preserve PARTIAL and all provider/session conflicts.  Calendar
            # verification never upgrades data quality by itself.
            result["display_status"] = projection["status"]
            if len(projection.get("provider_session_times") or []) != 1:
                result["display_status"] = "PARTIAL"
                diagnostic["cannot_confirm"] = ["QUOTE_SESSION_TIME_MIXED_OR_MISSING"]
    except (ValueError, TypeError, KeyError) as error:
        diagnostic["state"] = "CANNOT_CONFIRM"
        diagnostic["cannot_confirm"] = [str(error)]
        result["display_status"] = "CANNOT_CONFIRM"
    return result


def _missing(*, research_date: str, reason: str, identity: str, endpoint_mode: str) -> dict:
    return {
        "schema_version": "v3_5.research_lane.v1",
        "status": "NOT_MATERIALIZED",
        "research_date": research_date,
        "endpoint_mode": endpoint_mode,
        "reason": reason,
        "cannot_confirm": [f"RESEARCH_LANE_NOT_MATERIALIZED:{identity}"],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _status_only_lane_response(
    status_lane: Mapping[str, Any],
    *,
    research_date: str,
    endpoint_mode: str,
    page_trade_date: str | None,
    source_binding: Mapping[str, Any] | None = None,
    morning_news: Mapping[str, Any] | None = None,
    peripherals: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Project dispatcher receipts without inventing an archive/feed."""

    timeline = dict(status_lane)
    zsxq = dict(timeline.pop("zsxq_hourly", {}))
    cannot_confirm = [f"RESEARCH_ARCHIVE_NOT_MATERIALIZED:{research_date}"]
    cannot_confirm.extend(
        item
        for row in timeline.get("slots", [])
        for item in (row.get("cannot_confirm") or [])
        if isinstance(item, str)
    )
    if zsxq.get("scheduled_0830", {}).get("status") not in {"READY", "SUCCEEDED"}:
        cannot_confirm.extend(item for item in zsxq.get("cannot_confirm", []) if isinstance(item, str))
    quality = {
        "raw_item_count": 0,
        "research_item_count": 0,
        "stock_evidence_count": 0,
        "stock_daily_count": 0,
        "l2_medium_count": 0,
        "l3_strong_count": 0,
        "source_counts": {},
        "source_schema_version": "v3_5.research_status_only.v1",
        "source_generated_at": "",
    }
    exact_peripherals = dict(peripherals or {})
    has_partial_content = morning_news is not None or any(
        payload is not None for payload in exact_peripherals.values()
    )
    status = "LIVE_PERIPHERAL_ONLY" if has_partial_content else "NOT_MATERIALIZED"
    projection_mode = (
        "STATUS_WITH_PERIPHERALS" if has_partial_content else "STATUS_ONLY"
    )
    return {
        "schema_version": "v3_5.research_lane.v1",
        "status": status,
        "projection_mode": projection_mode,
        "reason": (
            "RESEARCH_ARCHIVE_NOT_MATERIALIZED_WITH_PERIPHERALS"
            if has_partial_content
            else "RESEARCH_LANE_SNAPSHOT_NOT_FOUND"
        ),
        "research_date": research_date,
        "trade_date": research_date,
        "intelligence_date": research_date,
        "source_binding": dict(source_binding or {}),
        "page_trade_date": page_trade_date,
        "date_binding_policy": "explicit_research_date_with_page_context",
        "endpoint_mode": endpoint_mode,
        "stock_research_daily": [],
        "stock_research_timeline": [],
        "research_pool_bridge": [],
        "research_quality_summary": quality,
        "morning_news": _morning_news_response(morning_news),
        "zsxq_hourly": zsxq,
        "external_finance": _peripheral_response(
            "external_finance", exact_peripherals.get("external_finance")
        ),
        "ai_news": _peripheral_response(
            "ai_news", exact_peripherals.get("ai_news")
        ),
        "ocr_ingestion": {
            "status": "NOT_MATERIALIZED",
            "items": [],
            "cannot_confirm": ["OCR_INGESTION_NOT_MATERIALIZED"],
        },
        "news_workbench": {
            "schema_version": "v3_5.news_workbench.v1",
            "status": "READ_ONLY_EMPTY",
            "action_rows": [],
            "cannot_confirm": ["LANE_NEWS_WORKBENCH_ACTIONS_NOT_MATERIALIZED"],
        },
        "key_investment_messages": [],
        "research_intelligence_timeline": timeline,
        "hourly_research": {
            "schema_version": "v3_5.hourly_research_status_only.v1",
            "status": "STATUS_ONLY",
            "slot_count": timeline.get("slot_count", 0),
            "latest_slot": timeline.get("latest_slot", ""),
            "source_schema_version": timeline.get("schema_version", ""),
            "source_generated_at": "",
            "source_counts": {},
            "cannot_confirm": ["HOURLY_RESEARCH_ARCHIVE_NOT_MATERIALIZED"],
        },
        "cannot_confirm": sorted(set(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _no_event(reason: str) -> dict:
    return {
        "ok": True,
        "status": reason,
        "schema_version": "v3_5.research_publish.v1",
        "module_id": "research_intelligence",
        "event_id": "",
        "write_policy": "read_only",
        "default_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _quality_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    articles = payload["articles"]
    stock_pool = payload["stock_pool"]
    evidence_levels: dict[str, int] = {}
    for article in articles:
        level = str(article.get("evidence_level") or "UNKNOWN")
        evidence_levels[level] = evidence_levels.get(level, 0) + 1
    return {
        "raw_item_count": int(payload["article_count"]),
        "research_item_count": int(payload["article_count"]),
        "stock_evidence_count": int(payload["article_count"]),
        "stock_daily_count": int(payload["stock_pool_count"]),
        "l2_medium_count": evidence_levels.get("L2_MEDIUM", 0),
        "l3_strong_count": evidence_levels.get("L3_STRONG", 0),
        "source_counts": dict(payload["source_counts"]),
        "source_schema_version": payload["source_schema_version"],
        "source_generated_at": payload["source_generated_at"],
    }


def _lane_response(
    archive: Mapping[str, Any],
    *,
    research_date: str,
    endpoint_mode: str,
    daily_archive: Mapping[str, Any] | None = None,
    hourly_slot: str = "",
    hourly_slot_count: int = 0,
    source_binding: Mapping[str, Any] | None = None,
    morning_news: Mapping[str, Any] | None = None,
    peripherals: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> dict:
    articles = list(archive["articles"])
    timeline = [
        {
            **article,
            "evidence_id": article["article_id"],
            "event_id": article["article_id"],
            "event_time": article["published_at"],
        }
        for article in articles
    ]
    pool = list(archive["stock_pool"])
    cannot_confirm = list(archive["cannot_confirm"])
    zsxq_articles = [
        article
        for article in articles
        if hourly_slot
        and str(article.get("source_type") or "").strip().lower() == "zsxq"
    ]
    available_peripheral = {"zsxq_hourly"} if zsxq_articles else set()
    available_peripheral.update(
        name
        for name, peripheral in (peripherals or {}).items()
        if peripheral is not None
    )
    missing_peripheral = [
        name
        for name in (
            "zsxq_hourly",
            "external_finance",
            "ai_news",
            "key_investment_messages",
            "ocr_ingestion",
        )
        if name not in archive and name not in available_peripheral
    ]
    cannot_confirm.extend(
        f"LANE_PERIPHERAL_NOT_MATERIALIZED:{name}" for name in missing_peripheral
    )
    key_investment_messages = archive.get("key_investment_messages")
    if not isinstance(key_investment_messages, list):
        key_investment_messages = []
    if not hourly_slot:
        cannot_confirm.append("HOURLY_SLOT_ARTIFACTS_NOT_IN_ARCHIVE")
    zsxq_hourly = {
        "schema_version": "v3_5.zsxq_hourly_projection.v1",
        "status": "LIVE_HOURLY" if hourly_slot else "ARCHIVE_ONLY",
        "items": zsxq_articles,
        "item_count": len(zsxq_articles),
        "topic_count": len(zsxq_articles),
        "latest_slot": hourly_slot,
        "slot_count": hourly_slot_count,
        "source_schema_version": archive["source_schema_version"],
        "source_generated_at": archive["source_generated_at"],
        "cannot_confirm": (
            []
            if zsxq_articles
            else ["ZSXQ_HOURLY_ITEMS_NOT_MATERIALIZED"]
        ),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    is_hourly = bool(hourly_slot)
    daily_archive_ready = (
        isinstance(daily_archive, Mapping)
        and daily_archive.get("status") == "READY"
        and daily_archive.get("authoritative") is True
    )
    daily_archive_status = "READY" if daily_archive_ready else "NOT_MATERIALIZED"
    if not daily_archive_ready:
        cannot_confirm.extend(
            item
            for item in (daily_archive or {}).get("cannot_confirm", [])
            if isinstance(item, str)
        )
    lane_status = "LIVE_HOURLY" if is_hourly else "DAILY_ARCHIVE"
    return project_report_roles({
        "schema_version": "v3_5.research_lane.v1",
        # Keep READY for archive consumers, but never let an hourly snapshot
        # masquerade as a daily archive at the top level.
        "status": "LIVE_HOURLY" if is_hourly else "READY",
        "lane_status": lane_status,
        "daily_archive_status": daily_archive_status,
        "research_date": research_date,
        "source_binding": dict(source_binding or {}),
        "endpoint_mode": endpoint_mode,
        "stock_research_daily": pool,
        "stock_research_timeline": timeline,
        "research_pool_bridge": pool,
        "research_quality_summary": _quality_summary(archive),
        "morning_news": _morning_news_response(morning_news),
        "zsxq_hourly": zsxq_hourly,
        "external_finance": _peripheral_response(
            "external_finance", (peripherals or {}).get("external_finance")
        ),
        "ai_news": _peripheral_response(
            "ai_news", (peripherals or {}).get("ai_news")
        ),
        "key_investment_messages": key_investment_messages,
        "news_workbench": {
            "schema_version": "v3_5.news_workbench.v1",
            "status": "READ_ONLY_EMPTY",
            "action_rows": [],
            "cannot_confirm": [
                "LANE_NEWS_WORKBENCH_ACTIONS_NOT_MATERIALIZED"
            ],
        },
        "hourly_research": {
            "schema_version": "v3_5.hourly_research.v1",
            "status": "LIVE_HOURLY" if hourly_slot else "ARCHIVE_ONLY",
            "slot_count": hourly_slot_count,
            "latest_slot": hourly_slot,
            "source_schema_version": archive["source_schema_version"],
            "source_generated_at": archive["source_generated_at"],
            "source_counts": dict(archive["source_counts"]),
            "cannot_confirm": (
                [] if hourly_slot else ["HOURLY_SLOT_ARTIFACTS_NOT_IN_ARCHIVE"]
            ),
            "daily_archive_status": daily_archive_status,
            "source_binding": dict(source_binding or {}),
        },
        "cannot_confirm": sorted(set(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    })


def _morning_news_response(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "status": "NOT_MATERIALIZED",
            "articles": [],
            "articles_count": 0,
            "stock_mentions_count": 0,
            "cannot_confirm": ["MORNING_NEWS_SEPARATE_SOURCE_NOT_MATERIALIZED"],
        }
    return {
        "status": str(payload.get("status") or "CANNOT_CONFIRM"),
        "articles": list(payload.get("articles") or []),
        "articles_count": int(payload.get("article_count") or 0),
        "stock_mentions_count": int(payload.get("mention_count") or 0),
        "required_news_contract": dict(payload.get("required_news_contract") or {}),
        "cannot_confirm": list(payload.get("cannot_confirm") or []),
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
    }


def _peripheral_response(
    source: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        return {
            "schema_version": "v3_5.research_peripheral.v1",
            "source": source,
            "status": "NOT_MATERIALIZED",
            "source_url": "",
            "fetched_at": "",
            "raw_item_count": 0,
            "item_count": 0,
            "overview": [],
            "details": [],
            "items": [],
            "feed_receipts": [],
            "us_session_captures": [],
            "cannot_confirm": [
                f"{source.upper()}_PERIPHERAL_NOT_MATERIALIZED"
            ],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    response = {
        "schema_version": str(payload["schema_version"]),
        "source": source,
        "status": str(payload["status"]),
        "source_url": str(payload["source_url"]),
        "fetched_at": str(payload["fetched_at"]),
        "raw_item_count": int(payload["raw_item_count"]),
        "item_count": int(payload["item_count"]),
        "overview": list(payload["overview"]),
        "details": list(payload["details"]),
        "items": list(payload["items"]),
        "feed_receipts": list(payload.get("feed_receipts") or []),
        "us_session_captures": list(payload.get("us_session_captures") or []),
        "cannot_confirm": list(payload["cannot_confirm"]),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field in ("capture_origin", "original_time_capture"):
        if field in payload:
            response[field] = payload[field]
    return response


def create_research_lane_router(
    data_root: Path,
    *,
    shared_data_root: Path | str | None = None,
    morning_news_data_root: Path | str | None = None,
    ledger_root: Path | None = None,
    us_market_data_root: Path | str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v3/research", tags=["research-lane"])
    source = ResearchLaneSource(data_root, ledger_root=ledger_root)
    daily_store = ResearchArchiveStore(data_root)
    peripheral_source = ResearchPeripheralStore(data_root)
    # A bounded consumer binding; no data copying and no fallback across roots.
    market_source = ResearchPeripheralStore(
        Path(us_market_data_root) if us_market_data_root is not None else data_root
    )
    market_binding = {
        "source_root": str(market_source.root),
        "source": "external_finance",
        "read_policy": "EXACT_MANIFEST_RECEIPT_VERIFIED",
        "write_policy": "read_only",
    }
    resolved_morning_news_root = (
        morning_news_data_root
        if morning_news_data_root is not None
        else shared_data_root
    )
    morning_source = (
        SharedMorningNewsReader(resolved_morning_news_root)
        if resolved_morning_news_root is not None
        else None
    )

    def read_morning(selected: str) -> dict[str, Any] | None:
        return morning_source.read(selected) if morning_source else None

    def read_peripherals(selected: str) -> dict[str, dict[str, Any] | None]:
        return {
            "external_finance": peripheral_source.read_exact(
                selected, "external_finance"
            ),
            "ai_news": peripheral_source.read_exact(selected, "ai_news"),
        }

    def read_daily_archive(selected: str) -> dict[str, Any]:
        """Consume only an exact-date, authoritative full-day product."""
        try:
            product = daily_store.read_day_exact(selected)
        except ValueError as error:
            consumed = consume_authoritative_research_day(
                None,
                requested_date=selected,
            )
            consumed["cannot_confirm"] = sorted(
                set(consumed.get("cannot_confirm") or [])
                | {f"RESEARCH_DAY_PRODUCT_READ_FAILED:{error}"}
            )
            return consumed
        return consume_authoritative_research_day(
            product,
            requested_date=selected,
        )

    def resolve_requested_date(
        research_date: str,
        date: str | None,
    ) -> str | None:
        """Resolve the exact-date compatibility alias without latest fallback."""

        primary = str(research_date or "").strip()
        alias = str(date or "").strip()
        if primary and alias and primary != alias:
            raise HTTPException(
                status_code=422,
                detail="research_date and date must identify the same exact date",
            )
        selected = primary or alias
        if not selected:
            return None
        if not (len(selected) == 8 and selected.isdigit()):
            raise HTTPException(status_code=422, detail="research_date must use YYYYMMDD")
        try:
            return _date(selected)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="research_date must be a real calendar date",
            ) from error

    def _read_lane(
        research_date: str = Query(default=""),
        date: str | None = Query(default=None),
    ) -> dict:
        selected = resolve_requested_date(research_date, date)
        if selected is None:
            payload, hourly_slot, hourly_slot_count = source.read_latest_lane()
            if payload is None:
                return _missing(
                    research_date="",
                    reason="NO_RESEARCH_ARCHIVE_LATEST",
                    identity="LATEST",
                    endpoint_mode="LATEST",
                )
            source_binding = source.artifact_binding(
                str(payload["archive_date"]),
                slot=hourly_slot,
            )
            return _lane_response(
                payload,
                research_date=str(payload["archive_date"]),
                endpoint_mode="LATEST",
                daily_archive=read_daily_archive(str(payload["archive_date"])),
                hourly_slot=hourly_slot,
                hourly_slot_count=hourly_slot_count,
                source_binding=source_binding,
                morning_news=read_morning(str(payload["archive_date"])),
                peripherals=read_peripherals(str(payload["archive_date"])),
            )
        payload, hourly_slot, hourly_slot_count = source.read_exact_lane(selected)
        if payload is None:
            status_lane = source.read_status_lane(selected)
            if status_lane is not None:
                return _status_only_lane_response(
                    status_lane,
                    research_date=selected,
                    endpoint_mode="EXACT",
                    page_trade_date=None,
                    source_binding={
                        **source.binding(),
                        "status": "STATUS_ONLY",
                        "source_date": selected,
                        "slot": "",
                        "mode": "LIVE",
                    },
                    morning_news=read_morning(selected),
                    peripherals=read_peripherals(selected),
                )
            return _missing(
                research_date=selected,
                reason="RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
                identity=selected,
                endpoint_mode="EXACT",
            )
        source_binding = source.artifact_binding(selected, slot=hourly_slot)
        return _lane_response(
            payload,
            research_date=selected,
            endpoint_mode="EXACT",
            daily_archive=read_daily_archive(selected),
            hourly_slot=hourly_slot,
            hourly_slot_count=hourly_slot_count,
            source_binding=source_binding,
            morning_news=read_morning(selected),
            peripherals=read_peripherals(selected),
        )

    @router.get("/lane")
    def research_lane(research_date: str = Query(default=""), date: str | None = Query(default=None)) -> dict:
        result = _read_lane(research_date, date)
        resolved = str(result.get("research_date") or "")
        if resolved:
            result["update_diagnostic"] = source.update_diagnostic(
                resolved, artifact_verified=result.get("status") in {"READY", "LIVE_HOURLY"})
        return result

    @router.get("/dates")
    def research_dates() -> dict:
        peripheral_dates = peripheral_source.list_dates("external_finance")
        snapshot_dates = _verifiable_market_snapshot_dates(market_source)
        # Market CLOCK only: no US holiday/early-close calendar is supplied.
        # Missing previous completed-session evidence is independent of whether
        # today's regular-close clock has passed. Never invent a source date.
        from infrastructure.research_lane_source import shanghai_now
        observed = shanghai_now()
        ny = observed.astimezone(ZoneInfo("America/New_York"))
        phase = ("WEEKEND_CLOCK" if ny.weekday() >= 5 else
                 "BEFORE_REGULAR_CLOSE" if ny.strftime("%H%M") < "1600" else "AFTER_REGULAR_CLOSE")
        proxies = {symbol for mapping in GLOBAL_INDUSTRY_PROXY_MAP for symbol in mapping["proxy_symbols"]}
        latest = _with_us_market_freshness(
            _project_global_industries(store=market_source, research_date=max(snapshot_dates)),
            observed=observed,
        ) if snapshot_dates else None
        return {
            "schema_version": "v3_5.research_lane_dates.v1",
            "research_dates": sorted(set(source.list_dates()) | set(peripheral_dates)),
            "research_source": source.binding(),
            "external_finance_dates": peripheral_dates,
            "market_snapshot_dates": snapshot_dates,
            "market_source": market_binding,
            "us_close_availability": {
                "state": "VERIFIED_DATE_AVAILABLE" if snapshot_dates else "NO_VERIFIED_COMPLETED_SESSION",
                "latest_verified_artifact_date": max(snapshot_dates) if snapshot_dates else "",
                "latest_verified_source_date": str(latest.get("source_date") or "") if latest else "",
                "display_status": latest["display_status"] if latest else "CANNOT_CONFIRM",
                "freshness": latest["freshness"] if latest else None,
                "shanghai_time": observed.isoformat(), "new_york_time": ny.isoformat(),
                "clock_phase": phase, "exchange_calendar_status": "CANNOT_CONFIRM",
                "configured_proxy_count": len(proxies),
                "message": "已完成场次的可核验数据与当前市场时钟分开判断；无来源日时不推算交易日或涨跌。",
            },
            "today": source.today_date(),
            "status_date": source.today_date(),
            "status_dates": [source.today_date()],
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/us-market")
    def us_market(research_date: str = Query(default=""), response: Response = None) -> dict:
        """Project one exact stored US close snapshot; never fetch on demand."""
        if response is not None:
            response.headers["Cache-Control"] = "no-store"
        if not research_date:
            return _global_industry_missing(research_date="", reason="RESEARCH_DATE_REQUIRED")
        if not (len(research_date) == 8 and research_date.isdigit()):
            raise HTTPException(status_code=422, detail="research_date must use YYYYMMDD")
        try:
            selected = _date(research_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="research_date must be a real calendar date") from error
        from infrastructure.research_lane_source import shanghai_now
        result = _with_us_market_freshness(
            _project_global_industries(store=market_source, research_date=selected),
            observed=shanghai_now(),
        )
        result["market_source"] = dict(market_binding)
        return result


    @router.get("/latest-event")
    def research_latest_event() -> dict:
        try:
            event = source.read_latest_event()
        except ValueError:
            return {
                **_no_event("CANNOT_CONFIRM"),
                "reason": "OWNED_RESEARCH_EVENT_INVALID",
            }
        if event is None:
            return _no_event("NO_RESEARCH_EVENT")
        return {
            **event,
            "schema_version": "v3_5.research_publish.v1",
            "write_policy": "read_only",
            "default_status": "RESEARCH_ONLY",
            "buy_gate_effect": "none",
            "live_order_effect": "none",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/events")
    async def research_events(request: Request) -> StreamingResponse:
        async def event_stream():
            last_event_id = str(request.query_params.get("since") or "")
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    event = await run_in_threadpool(source.read_latest_event)
                except ValueError:
                    event = None
                event_id = str((event or {}).get("event_id") or "")
                if event_id and event_id != last_event_id:
                    last_event_id = event_id
                    payload = {
                        **(event or {}),
                        "ok": True,
                        "schema_version": "v3_5.research_publish.v1",
                        "module_id": "research_intelligence",
                        "write_policy": "read_only",
                        "default_status": "RESEARCH_ONLY",
                        "buy_gate_effect": "none",
                        "live_order_effect": "none",
                        "production_allowed": False,
                        "buy_gate_updated": False,
                        "orders_sent": False,
                    }
                    yield f"id: {event_id}\nevent: research_generation_completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router


__all__ = ["create_research_lane_router"]
