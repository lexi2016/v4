"""Read-only Stage A resources nested under the existing research API."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from infrastructure.wechat_research_archive import ArchiveError, WechatResearchArchive

READ_HEADERS = {'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'}
FILE_HEADERS = {**READ_HEADERS, 'Content-Security-Policy':"sandbox; default-src 'none'; frame-ancestors 'none'"}


def create_wechat_research_router(reader: WechatResearchArchive) -> APIRouter:
    router=APIRouter(prefix='/wechat',tags=['research-wechat'])

    def call(fn):
        try:
            return JSONResponse(fn(),headers=READ_HEADERS)
        except ArchiveError as exc:
            raise HTTPException(status_code=exc.status_code,detail={'code':exc.code},headers=READ_HEADERS) from exc

    @router.get('/materials')
    def materials(date: str | None = None, date_basis: str = 'article',
                  q: str = Query('',max_length=500), cursor: str | None = Query(None,max_length=4000),
                  limit: int = Query(20,ge=1,le=50)):
        return call(lambda:reader.list_materials(date=date,date_basis=date_basis,q=q,cursor=cursor,limit=limit))

    # Keep this route before /materials/{record_id}; "mentions" is a bounded
    # read-only projection over the selected article-date archive, not a
    # material record id.
    @router.get('/materials/mentions')
    def mentions(date: str | None = None, date_basis: str = 'article',
                 market: str | None = Query(None, max_length=3),
                 q: str = Query('', max_length=500), cursor: str | None = Query(None, max_length=4000),
                 limit: int = Query(50, ge=1, le=100)):
        return call(lambda:reader.list_mentions(date=date,date_basis=date_basis,market=market,
                                                 q=q,cursor=cursor,limit=limit))

    @router.get('/materials/{record_id}')
    def material(record_id: str):
        return call(lambda:reader.detail(record_id))

    @router.get('/materials/{record_id}/mentions')
    def record_mentions(record_id: str, market: str | None = Query(None, max_length=3),
                        q: str = Query('', max_length=500), cursor: str | None = Query(None, max_length=4000),
                        limit: int = Query(50, ge=1, le=100)):
        return call(lambda:reader.list_mentions(record_id=record_id, date_basis='article', market=market,
                                                 q=q,cursor=cursor,limit=limit))

    @router.get('/materials/{record_id}/artifacts/{artifact_id}')
    def artifact(record_id: str, artifact_id: str):
        try:
            data,name,mime=reader.artifact(record_id,artifact_id)
            return Response(data,media_type=mime,headers={**FILE_HEADERS,
                            'Content-Disposition':f'attachment; filename="{name}"'})
        except ArchiveError as exc:
            raise HTTPException(status_code=exc.status_code,detail={'code':exc.code},headers=READ_HEADERS) from exc

    return router
