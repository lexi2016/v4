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
from infrastructure.zsxq_pdf_ingestion import (
    ZsxqPdfError,
    read_pdf_document_detail,
    read_pdf_ingestion_projection,
)
from infrastructure.research_peripheral_store import (
    CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP,
    ResearchPeripheralStore,
)
from infrastructure.research_store import ResearchArchiveStore
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader


GLOBAL_INDUSTRY_PROXY_MAP = CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP
GLOBAL_INDUSTRY_SCHEMA_VERSION = "v3_5.global_industries.v2"
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
        # A natural NY close is normally observed on the following Shanghai
        # research day. Bind the original capture instead of relabelling it late.
        from contracts.us_equity_calendar import session, latest_completed_session
        try:
            captured = datetime.fromisoformat(str(capture["captured_at"]).replace("Z", "+00:00"))
            snapshot_captured = datetime.fromisoformat(str(snapshot["captured_at"]).replace("Z", "+00:00"))
            start = datetime.fromisoformat(str(capture["capture_window_start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(capture["capture_window_end"]).replace("Z", "+00:00"))
            if any(value.tzinfo is None or value.utcoffset() is None for value in (captured,snapshot_captured,start,end)):
                raise ValueError("capture timezone required")
            ny = ZoneInfo("America/New_York");shanghai = ZoneInfo("Asia/Shanghai")
            calendar = session(session_date)
            if (payload.get("trade_date") != research_date or capture.get("session_timezone") != "America/New_York"
                    or captured != snapshot_captured or not start <= captured <= end or start >= end
                    or captured.astimezone(shanghai).strftime("%Y%m%d") != research_date
                    or captured.astimezone(ny).strftime("%Y%m%d") != session_date
                    or start.astimezone(ny).strftime("%Y%m%d") != session_date
                    or end.astimezone(ny).strftime("%Y%m%d") != session_date
                    or calendar.close_at is None or captured < calendar.close_at
                    or latest_completed_session(captured).session_date != session_date):
                raise ValueError("natural capture calendar/date/window mismatch")
        except (ValueError, KeyError, TypeError):
            return None, "MARKET_SNAPSHOT_NATURAL_CAPTURE_DATE_OR_CLOCK_UNBOUND"
    return capture, None


def _global_industry_rows(reason: str) -> list[dict[str, Any]]:
    from apps.api.v35_api._research_lane_router_parts.industry_projection import __global_industry_rows_body as _v4_impl
    return _v4_impl(globals(), reason)



def _global_industry_missing(*, research_date: str, reason: str) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.industry_projection import __global_industry_missing_body as _v4_impl
    return _v4_impl(globals(), research_date=research_date, reason=reason)



def _global_industry_lineage(
    store: ResearchPeripheralStore,
    research_date: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.industry_projection import __global_industry_lineage_body as _v4_impl
    return _v4_impl(globals(), store, research_date, payload)



def _project_global_industries(
    *,
    store: ResearchPeripheralStore,
    research_date: str,
) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.industry_projection import __project_global_industries_body as _v4_impl
    return _v4_impl(globals(), store=store, research_date=research_date)



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


def _futu_board_freshness_error(
    projection: Mapping[str, Any], *, source_date: str,
    captured_at: datetime, ny_zone: ZoneInfo,
) -> str | None:
    """Validate official board identity and close-time freshness only."""
    from contracts.us_equity_calendar import session as us_equity_session
    from ops._us_market_digest_parts.futu_boards import FUTU_BOARD_MAP

    metadata = projection.get("futu_board_snapshot")
    if not isinstance(metadata, Mapping):
        return "FUTU_BOARD_SNAPSHOT_MISSING"
    if any(metadata.get(key) != value for key, value in {
        "schema_version": "v3_5.futu_us_industry_snapshot.v1",
        "status": projection.get("status"),
        "provider": "Futu OpenD",
        "market": "US",
        "timezone": "America/New_York",
        "capture_session_date": source_date,
    }.items()):
        return "FUTU_BOARD_SNAPSHOT_IDENTITY_INVALID"

    digest = metadata.get("source_response_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or projection.get("source_response_sha256") != digest
    ):
        return "FUTU_BOARD_SNAPSHOT_SOURCE_HASH_INVALID"

    rows = projection.get("rows")
    if (
        not isinstance(rows, list)
        or len(rows) != len(FUTU_BOARD_MAP)
        or [row.get("label") for row in rows if isinstance(row, Mapping)]
        != [mapping["label"] for mapping in FUTU_BOARD_MAP]
    ):
        return "FUTU_BOARD_SNAPSHOT_ROWS_INVALID"

    calendar_session = us_equity_session(source_date)
    if calendar_session.close_at is None:
        return "FUTU_BOARD_SOURCE_SESSION_NOT_OPEN"

    ready_count = 0
    update_times: set[str] = set()
    for row in rows:
        board = row.get("official_board")
        if not isinstance(board, Mapping):
            return "FUTU_BOARD_ROW_INVALID"
        row_status = row.get("status")
        if row_status != board.get("status"):
            return "FUTU_BOARD_ROW_STATUS_MISMATCH"
        if row_status != "READY":
            if row.get("change_pct") is not None or board.get("change_pct") is not None:
                return "FUTU_UNCONFIRMED_BOARD_HAS_CHANGE"
            continue

        if (
            board.get("metric_kind") != "OFFICIAL_BOARD"
            or board.get("market") != "US"
            or board.get("timezone") != "America/New_York"
            or board.get("plate_valid") is not True
            or board.get("session_date") != source_date
            or row.get("quote_session_dates") != [source_date]
        ):
            return "FUTU_BOARD_READY_ROW_IDENTITY_INVALID"
        raw_update_time = board.get("update_time")
        if not isinstance(raw_update_time, str):
            return "FUTU_BOARD_UPDATE_TIME_MISSING"
        try:
            update_at = datetime.strptime(raw_update_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ny_zone)
        except ValueError:
            return "FUTU_BOARD_UPDATE_TIME_INVALID"
        if raw_update_time[:10] != f"{source_date[:4]}-{source_date[4:6]}-{source_date[6:]}":
            return "FUTU_BOARD_UPDATE_DATE_MISMATCH"
        if update_at < calendar_session.close_at:
            return "FUTU_BOARD_UPDATE_BEFORE_SESSION_CLOSE"
        if update_at > captured_at:
            return "FUTU_BOARD_UPDATE_AFTER_CAPTURE"
        ready_count += 1
        update_times.add(raw_update_time)

    expected_status = "READY" if ready_count == len(FUTU_BOARD_MAP) else "PARTIAL" if ready_count else "CANNOT_CONFIRM"
    if (
        metadata.get("status") != expected_status
        or projection.get("status") != expected_status
        or type(projection.get("requested_board_count")) is not int
        or projection.get("requested_board_count") != len(FUTU_BOARD_MAP)
        or type(projection.get("available_board_count")) is not int
        or projection.get("available_board_count") != ready_count
        or projection.get("provider_session_dates") != ([source_date] if ready_count else [])
        or projection.get("provider_session_times") != sorted(update_times)
    ):
        return "FUTU_BOARD_SNAPSHOT_COUNT_OR_SESSION_MISMATCH"
    return None



def _with_us_market_freshness(
    projection: Mapping[str, Any], *, observed: datetime,
) -> dict[str, Any]:
    """Separate stored quality from read-time freshness using the owned NYSE calendar."""
    from apps.api.v35_api._research_lane_router_parts.market_freshness import __with_us_market_freshness_body as _v4_impl
    return _v4_impl(globals(), projection, observed=observed)

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
    response = project_report_roles({
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
    if isinstance(key_investment_messages, list):
        response["key_investment_messages"] = key_investment_messages
    return response


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
        selected_pdf_date = resolved or str(research_date or date or "").strip()
        try:
            result["ocr_ingestion"] = (
                read_pdf_ingestion_projection(data_root, selected_pdf_date)
                if selected_pdf_date
                else {
                    "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                    "status": "NOT_MATERIALIZED",
                    "research_date": "",
                    "completed_count": 0,
                    "done_count": 0,
                    "partial_count": 0,
                    "failed_count": 0,
                    "pending_count": 0,
                    "cannot_confirm_count": 0,
                    "total_count": 0,
                    "items": [],
                    "cannot_confirm": ["PDF_INGESTION_RESEARCH_DATE_UNRESOLVED"],
                    "research_only": True,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
        except Exception as error:
            result["ocr_ingestion"] = {
                "schema_version": "v4.zsxq_pdf_ingestion_projection.v1",
                "status": "CANNOT_CONFIRM",
                "research_date": selected_pdf_date,
                "completed_count": 0,
                "done_count": 0,
                "partial_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "cannot_confirm_count": 1,
                "total_count": 0,
                "items": [],
                "cannot_confirm": [f"PDF_INGESTION_READ_FAILED:{type(error).__name__}"],
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        if resolved:
            result["update_diagnostic"] = source.update_diagnostic(
                resolved, artifact_verified=result.get("status") in {"READY", "LIVE_HOURLY"})
        return result

    @router.get("/pdf-documents/{document_id}")
    def research_pdf_document_detail(
        document_id: str,
        research_date: str = Query(...),
        response: Response = None,
    ) -> dict:
        if response is not None:
            response.headers["Cache-Control"] = "no-store"
        try:
            return read_pdf_document_detail(data_root, document_id, research_date)
        except ZsxqPdfError as error:
            if error.code in {"DOCUMENT_NOT_FOUND", "DOCUMENT_DATE_MISMATCH"}:
                raise HTTPException(status_code=404, detail=error.code) from error
            if error.code in {"DOCUMENT_ID_INVALID", "TRADE_DATE_INVALID"}:
                raise HTTPException(status_code=422, detail=error.code) from error
            raise HTTPException(status_code=409, detail=error.code) from error

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
