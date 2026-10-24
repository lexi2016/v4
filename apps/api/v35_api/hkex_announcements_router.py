"""Three bounded original-owner HKEX endpoints; GET never collects sources."""
from typing import Annotated
from urllib.parse import urlsplit
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from v4.manager_research.announcement_source import (
    MAX_BYTES, _cached_extract_pdf_pages, read_response, safe_reason,
)
from v4.manager_research.contracts import strict_trade_date
from v4.manager_research.workspace_announcements import TARGETED_HKEX_SCOPE, validate_product
from v4.manager_research.workspace_projection import FLAGS, digest

PREFIX = '/api/v4/manager/research/announcements'
SHA = r'^[a-f0-9]{64}$'


def _date(value):
    try:
        return strict_trade_date(value)
    except ValueError as exc:
        raise HTTPException(422, 'TARGET_TRADE_DATE_INVALID') from exc


def _keys(request, allowed):
    if set(request.query_params) - set(allowed):
        raise HTTPException(422, 'UNEXPECTED_QUERY_PARAMETER')


async def _explicit_same_origin(request: Request):
    origin = request.headers.get('origin')
    if origin:
        try:
            parsed = urlsplit(origin)
            valid = (parsed.scheme == request.url.scheme and parsed.netloc == request.url.netloc
                     and not (parsed.path or parsed.query or parsed.fragment or parsed.username))
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(403, 'SAME_ORIGIN_REQUIRED')
    if request.headers.get('sec-fetch-site') not in (None, 'same-origin', 'none'):
        raise HTTPException(403, 'SAME_ORIGIN_REQUIRED')
    if request.headers.get('transfer-encoding') or request.headers.get('content-length', '0') != '0':
        raise HTTPException(400, 'REQUEST_BODY_NOT_ALLOWED')
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(400, 'REQUEST_BODY_NOT_ALLOWED')


def _failure(exc):
    return HTTPException(409, safe_reason(exc, 'HKEX_OWNER_READBACK_FAILED'))


def create_hkex_announcements_router(service):
    router = APIRouter(tags=['hkex-announcements'])

    @router.get(PREFIX)
    def announcements(request: Request, target_trade_date: str,
                      scope_id: Annotated[str, Query(pattern=SHA)]):
        _keys(request, {'target_trade_date', 'scope_id'})
        try:
            return service.get_announcements(_date(target_trade_date), scope_id=scope_id)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            raise _failure(exc) from exc

    @router.post(PREFIX + '/refresh', dependencies=[Depends(_explicit_same_origin)])
    def refresh(request: Request, target_trade_date: str,
                issuer_codes: Annotated[list[str], Query(min_length=1, max_length=24)],
                resume: bool = False):
        _keys(request, {'target_trade_date', 'issuer_codes', 'resume'})
        if (len(set(issuer_codes)) != len(issuer_codes)
                or any(re.fullmatch(r'HK\.[0-9]{5}', code) is None for code in issuer_codes)):
            raise HTTPException(422, 'ISSUER_CODES_INVALID')
        try:
            return service.refresh_announcements(
                _date(target_trade_date), issuer_codes=issuer_codes, resume=resume)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            raise _failure(exc) from exc

    @router.get(PREFIX + '/body')
    def body(request: Request, target_trade_date: str,
             scope_id: Annotated[str, Query(pattern=SHA)],
             product_sha256: Annotated[str, Query(pattern=SHA)],
             event_id: Annotated[str, Query(pattern=SHA)]):
        _keys(request, {'target_trade_date', 'scope_id', 'product_sha256', 'event_id'})
        date = _date(target_trade_date)
        try:
            # Same owner transaction as refresh: bind projection and exact saved
            # product together; a concurrent revision cannot switch the body.
            with service.store._transaction(date, 'workspace-announcements'):
                projected = service.get_announcements(date, scope_id=scope_id)
                identity = projected.get('product_identity') or {}
                if identity.get('sha256') != product_sha256 or identity.get('consumed') is not True:
                    raise HTTPException(409, 'PRODUCT_IDENTITY_OR_CONSUMPTION_MISMATCH')
                visible = [row for row in projected.get('official_documents', [])
                           if row.get('event_id') == event_id and row.get('body_status') == 'BODY_PARSED']
                if len(visible) != 1:
                    raise HTTPException(404, 'SOURCE_VERIFIED_BODY_NOT_FOUND')
                path = (service.store.root / 'workspace_announcements' / date
                        / 'issuer_subsets' / scope_id / 'latest.json')
                product = validate_product(service.store._read(path), date)
                if (product['sha256'] != product_sha256 or product.get('scope_id') != scope_id
                        or product.get('capture_scope') != TARGETED_HKEX_SCOPE):
                    raise HTTPException(409, 'PRODUCT_BINDING_CHANGED')
                docs = [doc for doc in product['documents']
                        if digest([doc['code'], doc['row']['url']]) == event_id]
                if len(docs) != 1 or docs[0].get('parse_status') != 'BODY_PARSED':
                    raise HTTPException(404, 'SOURCE_VERIFIED_BODY_NOT_FOUND')
                doc = docs[0]
                ref = doc['body_ref']
                if ref['request'] != {'url': doc['row']['url'], 'method': 'GET'}:
                    raise ValueError('ANNOUNCEMENT_DOCUMENT_URL_MISMATCH')
                raw = read_response(service._material_store, ref)
                pages = _cached_extract_pdf_pages(raw, max_bytes=MAX_BYTES, max_pages=40,
                                                 max_text_characters=240000, timeout_seconds=10)
                if not pages or visible[0].get('document_sha256') != ref['body_sha256']:
                    raise ValueError('ANNOUNCEMENT_BODY_READABILITY_DERIVATION_MISMATCH')
                return dict(status='BODY_PARSED', target_trade_date=date, scope_id=scope_id,
                            product_sha256=product_sha256, event_id=event_id,
                            title=doc['row']['document_title'], source_url=doc['row']['url'],
                            published_at=doc['row']['published_at'], retrieved_at=ref['retrieved_at'],
                            available_at=ref['retrieved_at'], document_sha256=ref['body_sha256'],
                            query_cutoff=product['query_context']['research_cutoff'],
                            capture_cutoff=product['context']['research_cutoff'],
                            late_acquisition=visible[0].get('late_acquisition'), pages=pages, **FLAGS)
        except HTTPException:
            raise
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            raise _failure(exc) from exc

    return router
