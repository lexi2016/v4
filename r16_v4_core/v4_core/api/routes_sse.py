"""Pure V4 SSE event broadcaster with cold-start SQLite workbench_completed replay & Last-Event-ID dedup."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from v4_core.api.routes_workbench import compute_observation_date, compute_workbench_lineage
from v4_core.storage.db import V4Store


class PublishEventRequest(BaseModel):
    event: str
    data: dict[str, Any]


def build_cold_start_workbench_event(store: V4Store, source_date: str) -> dict[str, Any] | None:
    """Build deterministic workbench_completed SSE event from persisted SQLite workbench_scores."""
    scores = store.get_workbench_scores(source_date)
    if not scores:
        return None
    lineage = compute_workbench_lineage(source_date, scores)
    generation = lineage["generation"]
    event_id = hashlib.sha256(
        json.dumps(
            {"event": "workbench_completed", "source_date": source_date, "generation": generation, "cold_start": True},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    has_top200 = len(store.get_top200(source_date)) > 0
    modules = {
        "qfq": "READY",
        "top200": "READY" if has_top200 else "UNKNOWN",
        "workbench": "READY",
    }
    enriched_data = {
        **lineage,
        "trade_date": source_date,
        "event_id": event_id,
        "workbench_count": len(scores),
        "cold_start_replay": True,
        "modules": modules,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return {
        "seq": 0,
        "id": event_id,
        "event": "workbench_completed",
        "source_date": source_date,
        "data": enriched_data,
    }


class EventBus:
    def __init__(self, store: V4Store | None = None) -> None:
        self._subscribers: list[tuple[str | None, asyncio.Queue[dict[str, Any]]]] = []
        self.history: list[dict[str, Any]] = []
        self._seq: int = 0
        self.store = store

    def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        source_date = payload.get("source_date") or payload.get("trade_date")
        observation_date = payload.get("observation_date") or (
            compute_observation_date(str(source_date)) if source_date else None
        )
        generation = payload.get("generation") or hashlib.sha256(
            f"{event_type}:{source_date}:{self._seq}".encode("utf-8")
        ).hexdigest()
        input_sha256 = payload.get("input_sha256") or generation

        raw_nm = payload.get("numeric_manifest")
        if isinstance(raw_nm, dict) and "path" in raw_nm and "sha256" in raw_nm:
            numeric_manifest = {"path": str(raw_nm["path"]), "sha256": str(raw_nm["sha256"])}
        else:
            numeric_manifest = {
                "path": f"v4_core://workbench/{source_date}/numeric_manifest.json",
                "sha256": generation,
            }

        raw_modules = payload.get("modules")
        if isinstance(raw_modules, dict):
            modules = raw_modules
        else:
            modules = {"qfq": "READY", "top200": "READY", "workbench": "READY"}

        event_id = hashlib.sha256(
            json.dumps(
                {"seq": self._seq, "event": event_type, "source_date": source_date, "generation": generation},
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        enriched_data = {
            **payload,
            "event_id": event_id,
            "source_date": source_date,
            "observation_date": observation_date,
            "generation": generation,
            "input_sha256": input_sha256,
            "numeric_manifest": numeric_manifest,
            "modules": modules,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        event = {
            "seq": self._seq,
            "id": event_id,
            "event": event_type,
            "source_date": source_date,
            "data": enriched_data,
        }
        self.history.append(event)
        if len(self.history) > 200:
            self.history = self.history[-200:]
        for scope_date, q in list(self._subscribers):
            if scope_date is None or scope_date == source_date:
                q.put_nowait(event)
        return event

    @staticmethod
    def _format_sse(event: dict[str, Any]) -> str:
        return (
            f"id: {event['id']}\n"
            f"event: {event['event']}\n"
            f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        )

    def _events_after(
        self,
        *,
        source_date: str | None,
        last_event_id: str | None,
        store: V4Store | None = None,
    ) -> list[dict[str, Any]]:
        active_store = store or self.store
        scoped = [e for e in self.history if source_date is None or e.get("source_date") == source_date]

        if not scoped and active_store is not None:
            target_date = source_date
            if target_date is None:
                dates = active_store.list_workbench_dates()
                target_date = dates[0] if dates else None
            if target_date:
                cold_event = build_cold_start_workbench_event(active_store, target_date)
                if cold_event is not None:
                    scoped = [cold_event]

        if not last_event_id:
            return scoped
        if last_event_id.isdigit():
            since_seq = int(last_event_id)
            return [e for e in scoped if e["seq"] > since_seq]
        for idx, e in enumerate(scoped):
            if e["id"] == last_event_id:
                return scoped[idx + 1 :]
        return scoped

    async def stream(
        self,
        *,
        source_date: str | None = None,
        last_event_id: str | None = None,
        once: bool = False,
        store: V4Store | None = None,
    ):
        pending = self._events_after(source_date=source_date, last_event_id=last_event_id, store=store)
        for past in pending:
            yield self._format_sse(past)
            if once:
                return
        if once:
            yield f": connected source_date={source_date or 'global'}\n\n"
            return

        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        entry = (source_date, q)
        self._subscribers.append(entry)
        try:
            yield f": connected source_date={source_date or 'global'}\n\n"
            while True:
                event = await q.get()
                yield self._format_sse(event)
        finally:
            if entry in self._subscribers:
                self._subscribers.remove(entry)


def build_sse_router(bus: EventBus, store: V4Store | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v4/research", tags=["research-events"])

    @router.get("/workbench/days/{source_date}/events")
    async def workbench_day_sse(
        source_date: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        once: bool = Query(default=False),
    ):
        return StreamingResponse(
            bus.stream(source_date=source_date, last_event_id=last_event_id, once=once, store=store),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/events")
    async def global_research_sse(
        since: str | None = Query(default=None),
        daily_since: str | None = Query(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        once: bool = Query(default=False),
    ):
        cursor = last_event_id or since or daily_since
        return StreamingResponse(
            bus.stream(source_date=None, last_event_id=cursor, once=once, store=store),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/latest-event")
    def latest_research_event(source_date: str | None = Query(default=None)):
        events = bus._events_after(source_date=source_date, last_event_id=None, store=store)
        latest = events[-1] if events else None
        return {
            "status": "READY" if latest else "EMPTY",
            "source_date": source_date or (latest["source_date"] if latest else None),
            "event": latest,
            "RESEARCH_ONLY": True,
        }

    @router.post("/events/publish")
    def publish_event(req: PublishEventRequest):
        return bus.publish(req.event, req.data)

    @router.get("/events/recent")
    def recent_events(source_date: str | None = Query(default=None)):
        events = bus._events_after(source_date=source_date, last_event_id=None, store=store)
        return {"events": events[-20:]}

    return router
