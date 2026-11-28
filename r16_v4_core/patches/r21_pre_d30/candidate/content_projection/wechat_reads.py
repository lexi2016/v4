"""Keep r21's WeChat reads on the registered, receipt-bound Stage A archive."""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from starlette.responses import JSONResponse, Response

from v4_core.decoupled.wechat_archive import ArchiveError, WechatResearchArchive

from .formal_admission_reads import exact_date

WECHAT_PREFIX = "/api/v4/research/wechat/materials"
AUTHORITY = Path.home() / "Library/Application Support/com.lexi.v4.local"
DATA = AUTHORITY / "state/data/research"
READ_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
FILE_HEADERS = {
    **READ_HEADERS, "Content-Security-Policy": "sandbox; default-src 'none'; frame-ancestors 'none'",
}


def compact(date):
    parsed = exact_date(date)
    return parsed.strftime("%Y%m%d") if parsed else date


class WechatReads:
    def __init__(self):
        reader = WechatResearchArchive(DATA / "wechat_archive/articles", DATA / "wechat_materials")
        self.app = app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

        def call(method, *args, **kwargs):
            try:
                return getattr(reader, method)(*args, **kwargs)
            except ArchiveError as exc:
                raise HTTPException(exc.status_code, {"code": exc.code}, headers=READ_HEADERS) from exc

        @app.get(WECHAT_PREFIX)
        def materials(date: str | None = None, date_basis: str = "article",
                      q: str = Query("", max_length=500), cursor: str | None = Query(None, max_length=4000),
                      limit: int = Query(20, ge=1, le=50)):
            value = call("list_materials", date=compact(date), date_basis=date_basis, q=q, cursor=cursor, limit=limit)
            return JSONResponse(value, headers=READ_HEADERS)

        @app.get(WECHAT_PREFIX + "/mentions")
        def mentions(date: str | None = None, date_basis: str = "article",
                     market: str | None = Query(None, max_length=3), q: str = Query("", max_length=500),
                     cursor: str | None = Query(None, max_length=4000), limit: int = Query(50, ge=1, le=100)):
            value = call("list_mentions", date=compact(date), date_basis=date_basis, market=market,
                         q=q, cursor=cursor, limit=limit)
            return JSONResponse(value, headers=READ_HEADERS)

        @app.get(WECHAT_PREFIX + "/{record_id}")
        def material(record_id: str):
            return JSONResponse(call("detail", record_id), headers=READ_HEADERS)

        @app.get(WECHAT_PREFIX + "/{record_id}/mentions")
        def record_mentions(record_id: str, market: str | None = Query(None, max_length=3),
                            q: str = Query("", max_length=500), cursor: str | None = Query(None, max_length=4000),
                            limit: int = Query(50, ge=1, le=100)):
            value = call("list_mentions", record_id=record_id, date_basis="article", market=market,
                         q=q, cursor=cursor, limit=limit)
            return JSONResponse(value, headers=READ_HEADERS)

        @app.get(WECHAT_PREFIX + "/{record_id}/artifacts/{artifact_id}")
        def artifact(record_id: str, artifact_id: str):
            data, name, mime = call("artifact", record_id, artifact_id)
            return Response(data, media_type=mime, headers={
                **FILE_HEADERS, "Content-Disposition": f'attachment; filename="{name}"',
            })

    async def __call__(self, scope, receive, send):
        if scope["method"] == "HEAD":
            async def head(message):
                if message["type"] == "http.response.body":
                    message = {**message, "body": b""}
                await send(message)

            return await self.app({**scope, "method": "GET"}, receive, head)
        return await self.app(scope, receive, send)
