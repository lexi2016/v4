"""Research decision-desk API served from V3.5-owned research archives.

The lane, dates, and events endpoints are mounted exclusively from
``ResearchArchiveStore(data_root)`` verified archives plus a validated
V3.5-owned event artifact under ``data_root``. No V3 research-module or
assistant-run-log read exists here, and no event is ever synthesized.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from infrastructure.data_store import _date
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader


def _missing(*, research_date: str, reason: str, identity: str) -> dict:
    return {
        "schema_version": "v3_5.research_lane.v1",
        "status": "NOT_MATERIALIZED",
        "research_date": research_date,
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
    daily_archive_status = "READY" if daily_archive is not None else "NOT_MATERIALIZED"
    lane_status = "LIVE_HOURLY" if is_hourly else "DAILY_ARCHIVE"
    return {
        "schema_version": "v3_5.research_lane.v1",
        # Keep READY for archive consumers, but never let an hourly snapshot
        # masquerade as a daily archive at the top level.
        "status": "LIVE_HOURLY" if is_hourly else "READY",
        "lane_status": lane_status,
        "daily_archive_status": daily_archive_status,
        "research_date": research_date,
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
        },
        "cannot_confirm": sorted(set(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


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
            "cannot_confirm": [
                f"{source.upper()}_PERIPHERAL_NOT_MATERIALIZED"
            ],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    return {
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
        "cannot_confirm": list(payload["cannot_confirm"]),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def create_research_lane_router(
    data_root: Path,
    *,
    shared_data_root: Path | str | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v3/research", tags=["research-lane"])
    source = ResearchLaneSource(data_root)
    peripheral_source = ResearchPeripheralStore(data_root)
    morning_source = (
        SharedMorningNewsReader(shared_data_root)
        if shared_data_root is not None
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

    def read_daily_archive(selected: str, *, is_hourly: bool) -> dict[str, Any] | None:
        """Return the independently verified daily archive, if present."""
        if not is_hourly:
            return {"archive_date": selected}  # payload is already verified
        return source.read_exact_archive(selected)

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

    @router.get("/lane")
    def research_lane(
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
                )
            return _lane_response(
                payload,
                research_date=str(payload["archive_date"]),
                endpoint_mode="LATEST",
                daily_archive=read_daily_archive(
                    str(payload["archive_date"]), is_hourly=bool(hourly_slot)
                ),
                hourly_slot=hourly_slot,
                hourly_slot_count=hourly_slot_count,
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
                    morning_news=read_morning(selected),
                    peripherals=read_peripherals(selected),
                )
            return _missing(
                research_date=selected,
                reason="RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
                identity=selected,
            )
        return _lane_response(
            payload,
            research_date=selected,
            endpoint_mode="EXACT",
            daily_archive=read_daily_archive(selected, is_hourly=bool(hourly_slot)),
            hourly_slot=hourly_slot,
            hourly_slot_count=hourly_slot_count,
            morning_news=read_morning(selected),
            peripherals=read_peripherals(selected),
        )

    @router.get("/dates")
    def research_dates() -> dict:
        return {
            "schema_version": "v3_5.research_lane_dates.v1",
            "research_dates": source.list_dates(),
            "today": source.today_date(),
            "status_date": source.today_date(),
            "status_dates": [source.today_date()],
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

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
