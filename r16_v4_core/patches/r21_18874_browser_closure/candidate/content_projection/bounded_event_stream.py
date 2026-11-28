"""Return finite SSE replays on the HTTP/1.1-only isolated service."""

import re

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, QueryParams
from starlette.responses import Response


_RESEARCH_EVENTS = "/api/v4/research/events"
_WORKBENCH_EVENTS = re.compile(r"/api/v4/research/workbench/days/([^/]+)/events")
_FALSE_VALUES = frozenset(("0", "false", "f", "off", "no", "n"))


class BoundedIsolationEvents:
    """Retain native EventSource replay cursors without keeping sockets leased."""

    def __init__(self, app, bus):
        self.app = app
        self.bus = bus

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "GET":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        day_match = _WORKBENCH_EVENTS.fullmatch(path)
        if path != _RESEARCH_EVENTS and day_match is None:
            await self.app(scope, receive, send)
            return

        query = QueryParams(scope["query_string"])
        once = query.get("once")
        if once is not None and once.lower() not in _FALSE_VALUES:
            # Keep native single-event diagnostic and validation for the once flag.
            await self.app(scope, receive, send)
            return

        source_date = day_match[1] if day_match else None
        cursor = Headers(scope=scope).get("last-event-id")
        if source_date is None:
            cursor = cursor or query.get("since") or query.get("daily_since")
        events = await run_in_threadpool(
            self.bus._events_after, source_date=source_date, last_event_id=cursor
        )
        body = "retry: 5000\n\n"
        body += "".join(self.bus._format_sse(event) for event in events)
        body += f": connected source_date={source_date or 'global'}\n\n"
        response = Response(
            body,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        await response(scope, receive, send)
