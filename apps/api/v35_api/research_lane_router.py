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

from domains.research_day_product import consume_authoritative_research_day
from infrastructure.data_store import _date, _sha256
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.zsxq_pdf_ingestion import ZsxqPdfError, read_pdf_document_detail, read_pdf_ingestion_projection
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
    from apps.api.v35_api._research_lane_router_parts.capture_identity import __capture_identity_failure_body as _v4_impl
    return _v4_impl(globals(), payload=payload, snapshot=snapshot, reason=reason, research_date=research_date, store=store)


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
    from apps.api.v35_api._research_lane_router_parts.capture_identity import __bound_capture_for_snapshot_body as _v4_impl
    return _v4_impl(globals(), payload=payload, snapshot=snapshot, research_date=research_date)


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
    from apps.api.v35_api._research_lane_router_parts.response_primitives import __is_verifiable_close_snapshot_body as _v4_impl
    return _v4_impl(globals(), result)


def _verifiable_market_snapshot_dates(
    store: ResearchPeripheralStore,
) -> list[str]:
    """List exact external-finance dates with a verifiable close snapshot."""
    from apps.api.v35_api._research_lane_router_parts.market_freshness import __verifiable_market_snapshot_dates_body as _v4_impl
    return _v4_impl(globals(), store)



def _with_us_market_freshness(
    projection: Mapping[str, Any], *, observed: datetime,
) -> dict[str, Any]:
    """Separate stored quality from read-time freshness using the owned 2026 NYSE calendar.

    This remains read-only and keeps the existing capture-window, provider-date,
    raw-response, receipt and manifest checks.  Calendar certification only
    determines which completed US session may be called current.
    """
    from apps.api.v35_api._research_lane_router_parts.market_freshness import __with_us_market_freshness_body as _v4_impl
    return _v4_impl(globals(), projection, observed=observed)


def _missing(*, research_date: str, reason: str, identity: str, endpoint_mode: str) -> dict:
    from apps.api.v35_api._research_lane_router_parts.response_primitives import __missing_body as _v4_impl
    return _v4_impl(globals(), research_date=research_date, reason=reason, identity=identity, endpoint_mode=endpoint_mode)


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
    from apps.api.v35_api._research_lane_router_parts.status_response import __status_only_lane_response_body as _v4_impl
    return _v4_impl(globals(), status_lane, research_date=research_date, endpoint_mode=endpoint_mode, page_trade_date=page_trade_date, source_binding=source_binding, morning_news=morning_news, peripherals=peripherals)


def _no_event(reason: str) -> dict:
    from apps.api.v35_api._research_lane_router_parts.response_primitives import __no_event_body as _v4_impl
    return _v4_impl(globals(), reason)


def _quality_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.response_primitives import __quality_summary_body as _v4_impl
    return _v4_impl(globals(), payload)


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
    from apps.api.v35_api._research_lane_router_parts.lane_response import __lane_response_body as _v4_impl
    return _v4_impl(globals(), archive, research_date=research_date, endpoint_mode=endpoint_mode, daily_archive=daily_archive, hourly_slot=hourly_slot, hourly_slot_count=hourly_slot_count, source_binding=source_binding, morning_news=morning_news, peripherals=peripherals)


def _morning_news_response(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.peripheral_response import __morning_news_response_body as _v4_impl
    return _v4_impl(globals(), payload)


def _peripheral_response(
    source: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from apps.api.v35_api._research_lane_router_parts.peripheral_response import __peripheral_response_body as _v4_impl
    return _v4_impl(globals(), source, payload)


def create_research_lane_router(
    data_root: Path,
    *,
    shared_data_root: Path | str | None = None,
    morning_news_data_root: Path | str | None = None,
    ledger_root: Path | None = None,
    us_market_data_root: Path | str | None = None,
) -> APIRouter:
    from apps.api.v35_api._research_lane_router_parts.http_routes import _build_research_lane_route_context

    context = _build_research_lane_route_context(
        globals(),
        data_root,
        shared_data_root=shared_data_root,
        morning_news_data_root=morning_news_data_root,
        ledger_root=ledger_root,
        us_market_data_root=us_market_data_root,
    )
    router = context["router"]
    source = context["source"]
    peripheral_source = context["peripheral_source"]
    market_source = context["market_source"]
    market_binding = context["market_binding"]
    _read_lane = context["read_lane"]

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
