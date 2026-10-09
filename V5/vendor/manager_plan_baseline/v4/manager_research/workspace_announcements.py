"""Stage-independent increments owned by ManagerResearchJobService.

New writes use the original store transaction/atomic publication and the same
HKEX provider and MaterialStore. GET reparses recorded directory/PDF bytes;
there is no collection, cache repair, historical timestamp backfill or order.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import os
import stat
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .announcement_source import (read_response,query_request,directory_entries,
    classify_pages,extract_pdf_pages,_cached_extract_pdf_pages,safe_reason,MAX_BYTES,MAX_DOCUMENTS,PARSER_VERSION,window,
    publication_window,publication_in_window,request_context)
from .workspace_projection import FLAGS, HK, date_token,digest,timestamp,canonical_symbol
from .workspace_plan import plan_context

SCHEMA='v4.manager_research.announcement_scan.v2'
OWNER='ManagerResearchJobService.refresh_announcements'
BATCH_SIZE=3
EASTMONEY_SCHEMA='v4.manager_research.eastmoney_hk_announcement_batch.v2'
EASTMONEY_SCOPE='EASTMONEY_HK'
EASTMONEY_DATE_CATALOG_SCOPE='EASTMONEY_HK_DATE_CATALOG'
MAX_DAILY_PARENT_PRODUCTS=2048
TARGETED_HKEX_SCOPE='HKEX_EXPLICIT_ISSUER_SUBSET_V1'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _daily_context(date: str, now: datetime | None = None) -> dict:
    """Build an HK calendar-day query while retaining a real owner cutoff."""
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState
    day=date_token(date)
    cutoff=now or timestamp(_now())
    if cutoff is None or cutoff.tzinfo is None:
        raise ValueError('ANNOUNCEMENT_DAILY_CUTOFF_TIME_REQUIRED')
    cutoff=cutoff.astimezone(HK)
    selected=datetime.strptime(day,'%Y%m%d').date()
    if selected>cutoff.date():
        raise ValueError('ANNOUNCEMENT_FUTURE_PUBLICATION_DATE_NOT_ALLOWED')
    calendar=load_market_calendar(); target=selected
    while target.year==calendar.year and resolve_market_states(calendar,target.strftime('%Y%m%d'))['hk_securities'] not in {
        TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM
    }:
        target+=timedelta(days=1)
    if target.year!=calendar.year:
        raise ValueError('ANNOUNCEMENT_DAILY_HK_CALENDAR_TARGET_UNAVAILABLE')
    # plan_context supplies the existing native calendar/master lineage. It is
    # used only to identify the prior completed HK session, not its planning
    # publication window.
    context=plan_context(target.strftime('%Y%m%d'),now=cutoff)
    start=datetime.combine(selected,time.min,HK)
    day_end=start+timedelta(days=1)
    end=min(cutoff+timedelta(microseconds=1),day_end) if selected==cutoff.date() else day_end
    context.update(plan_trade_date=day,focus_window_start=start.isoformat(),
        focus_window_basis='HK_CALENDAR_ANNOUNCEMENT_DAY',source_dates=[day],
        publication_window_mode='HK_CALENDAR_DAY_V1',publication_date=day,
        publication_window_start=start.isoformat(),publication_window_end_exclusive=end.isoformat())
    return context


def _targeted_hkex_context(date: str, now: datetime | None = None) -> tuple[dict,dict]:
    """Separate the bounded historical query end from the honest capture cutoff."""
    day=date_token(date)
    cutoff=now or timestamp(_now())
    if cutoff is None or cutoff.tzinfo is None:
        raise ValueError('ANNOUNCEMENT_TARGETED_CUTOFF_TIME_REQUIRED')
    actual=plan_context(day,now=cutoff)
    market_session=str(actual.get('market_session') or '')
    close=timestamp(actual.get('market_session_close'))
    if (not re.fullmatch(r'\d{8}',market_session) or market_session>=day or close is None
            or close.strftime('%Y%m%d')!=market_session):
        raise ValueError('ANNOUNCEMENT_TARGETED_PREVIOUS_SESSION_CLOSE_INVALID')
    selected=datetime.strptime(day,'%Y%m%d').date()
    end_exclusive=datetime.combine(selected+timedelta(days=1),time.min,HK)
    query_cutoff=min(cutoff.astimezone(HK),end_exclusive-timedelta(microseconds=1))
    if query_cutoff<close:
        raise ValueError('ANNOUNCEMENT_TARGETED_CUTOFF_BEFORE_WINDOW_START')
    source_window=dict(start=close.isoformat(),end_exclusive=end_exclusive.isoformat(),
        source_dates=[market_session,day],timezone='Asia/Hong_Kong')
    actual.update(plan_trade_date=day,focus_window_start=close.isoformat(),
        focus_window_basis='TARGETED_HKEX_PREVIOUS_SESSION_CLOSE_TO_TARGET_DAY_END',
        source_dates=[market_session,day],targeted_source_window=source_window)
    query=deepcopy(actual)
    query['research_cutoff']=query_cutoff.isoformat()
    return actual,query


def _targeted_scope_id(date: str,codes: list[str],source_window: Mapping[str,Any]) -> str:
    return digest([TARGETED_HKEX_SCOPE,date_token(date),codes,
        source_window.get('start'),source_window.get('end_exclusive')])


def _product_reference(product: Mapping[str,Any], date: str) -> dict:
    return dict(target_trade_date=date,run_id=product['run_id'],revision=product['revision'],sha256=product['sha256'])


def _load_daily_parent_products(service: Any, date: str, product: Mapping[str,Any]) -> list[dict]:
    refs=product.get('daily_parent_refs',[])
    if not isinstance(refs,list) or len(refs)>MAX_DAILY_PARENT_PRODUCTS:
        raise ValueError('ANNOUNCEMENT_DAILY_PARENT_BOUND_INVALID')
    loaded=[];seen=set()
    for ref in refs:
        if (not isinstance(ref,dict) or ref.get('target_trade_date')!=date
                or not re.fullmatch(r'[0-9a-f]{32}',str(ref.get('run_id','')))
                or type(ref.get('revision')) is not int or ref['revision']<1
                or not re.fullmatch(r'[0-9a-f]{64}',str(ref.get('sha256','')))):
            raise ValueError('ANNOUNCEMENT_DAILY_PARENT_REFERENCE_INVALID')
        key=(ref['run_id'],ref['revision'])
        if key in seen or ref['run_id']==product.get('run_id'):
            raise ValueError('ANNOUNCEMENT_DAILY_PARENT_DUPLICATE')
        seen.add(key)
        previous=service.store._read(service.store.root/'workspace_announcements'/date/ref['run_id']/(str(ref['revision'])+'.json'))
        previous=validate_product(previous,date)
        if previous['run_id']!=ref['run_id'] or previous['revision']!=ref['revision'] or previous['sha256']!=ref['sha256']:
            raise ValueError('ANNOUNCEMENT_DAILY_PARENT_BINDING_MISMATCH')
        loaded.append(previous)
    return loaded


def _daily_reuse_inventory(service: Any, date: str, previous: Mapping[str,Any] | None) -> tuple[list[dict],dict,list[str]]:
    products=[]
    if previous is not None:
        products.extend(_load_daily_parent_products(service,date,previous))
        products.append(dict(previous))
    if len(products)>MAX_DAILY_PARENT_PRODUCTS+1:
        raise ValueError('ANNOUNCEMENT_DAILY_PARENT_BOUND_INVALID')
    validation_cache={};reusable={};event_status={};query_status={}
    for product in products:
        parsed=_check_sources(service,product,validation_cache=validation_cache)
        for query in product.get('queries',[]):
            query_status[query['code']]=query['status']
        for doc in product.get('documents',[]):
            key=(doc.get('code'),doc.get('row',{}).get('url'))
            if doc.get('body_ref') and doc.get('parse_status') in {'BODY_PARSED','BODY_UNREADABLE'}:
                event_status[key]='DONE'
                if key[0] and key[1] and doc['body_ref']['blob_sha256'] in parsed:
                    reusable[key]=deepcopy(doc)
            else:
                event_status[key]='PENDING'
        for doc in product.get('pending_documents',[]):
            event_status[(doc.get('code'),doc.get('row',{}).get('url'))]='PENDING'
    retry_codes={code for (code,_url),state in event_status.items() if code and state=='PENDING'}
    retry_codes.update(code for code,state in query_status.items() if state=='FAILED')
    return products,reusable,sorted(retry_codes)


def _master(service: Any, context: Mapping[str,Any]) -> tuple[dict,dict]:
    from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
    from upstreams.v3_shared_data.shared_data.hashing import sha256_json
    configured=service._workspace_security_master_root
    if configured is None:raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_ROOT_NOT_BOUND')
    root=Path(configured).expanduser()
    if not root.is_absolute() or '..' in root.parts or root.is_symlink():
        raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_ROOT_INVALID')
    names,manifest=load_verified_hk_security_master(root,context['market_session'])
    cutoff=timestamp(context['research_cutoff'])
    if not names or any(canonical_symbol(code)!=code or not row.get('name')
        or timestamp(row.get('captured_at')) is None or timestamp(row['captured_at'])>cutoff for code,row in names.items()):
        raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_IDENTITY_OR_TIME_INVALID')
    witness=dict(owner='load_verified_hk_security_master',source_date=context['market_session'],
        root_sha256=digest(str(root.resolve())),manifest_sha256=sha256_json(manifest),
        artifact_sha256=manifest['artifact_sha256'],role='REFERENCE_IDENTITY_NOT_TARGET_CONNECT_ELIGIBILITY')
    return names,witness


def _seal(value: Mapping[str,Any]) -> dict:
    out={k:v for k,v in value.items() if k!='sha256'};out['sha256']=digest(out);return out


def validate_product(value: Mapping[str,Any],date: str) -> dict:
    if (not isinstance(value,dict) or value.get('schema_version')!=SCHEMA or value.get('owner')!=OWNER
        or value.get('target_trade_date')!=date_token(date) or value.get('sha256')!=_seal(value)['sha256']
        or any(value.get(k) is not v for k,v in FLAGS.items())
        or not re.fullmatch(r'[0-9a-f]{32}',str(value.get('run_id','')))
        or type(value.get('revision')) is not int or value['revision']<1
        or value.get('parser_revision')!=PARSER_VERSION or not timestamp(value.get('generated_at'))):
        raise ValueError('ANNOUNCEMENT_PRODUCT_IDENTITY_INVALID')
    codes=value.get('scope');index=value.get('next_index')
    targeted=value.get('capture_scope')==TARGETED_HKEX_SCOPE
    if value.get('capture_scope') is not None and not targeted:
        raise ValueError('ANNOUNCEMENT_CAPTURE_SCOPE_INVALID')
    expected_identity=(digest([TARGETED_HKEX_SCOPE,value.get('scope_id'),value.get('identity_witness'),
        value.get('master_scope_identity'),codes]) if targeted else digest([value.get('identity_witness'),codes]))
    if (not isinstance(codes,list) or not codes or codes!=sorted(set(codes))
            or any(canonical_symbol(c)!=c for c in codes)
            or type(index) is not int or not 0<=index<=len(codes)
            or not isinstance(value.get('queries'),list) or not isinstance(value.get('documents'),list)
            or not isinstance(value.get('pending_documents'),list)
            or value.get('scope_identity')!=expected_identity
            or not isinstance(value.get('scan_order',codes),list)
            or sorted(value.get('scan_order',codes))!=codes
            or [r.get('code') for r in value['queries']]!=value.get('scan_order',codes)[:index]):
        raise ValueError('ANNOUNCEMENT_PRODUCT_SCOPE_OR_CURSOR_INVALID')
    window(value['context'])
    if value['context'].get('plan_trade_date')!=date or timestamp(value['context']['research_cutoff'])>timestamp(value['generated_at']):
        raise ValueError('ANNOUNCEMENT_PRODUCT_TIME_INVALID')
    if targeted:
        query_context=value.get('query_context');source_window=value.get('source_window')
        coverage=value.get('scope_coverage')
        if (value.get('source_scope')!='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET'
                or not re.fullmatch(r'[0-9a-f]{64}',str(value.get('scope_id','')))
                or not isinstance(query_context,dict) or not isinstance(source_window,dict)
                or not isinstance(source_window.get('start'),str)
                or not isinstance(source_window.get('end_exclusive'),str)
                or not isinstance(source_window.get('source_dates'),list)
                or len(source_window.get('source_dates',[]))!=2
                or not isinstance(coverage,dict) or not isinstance(value.get('identity_witness'),dict)
                or not re.fullmatch(r'[0-9a-f]{64}',str(value.get('master_scope_identity','')))
                or type(value.get('master_scope_count')) is not int
                or value['master_scope_count']<len(codes)
                or source_window!=value['context'].get('targeted_source_window')
                or query_context.get('targeted_source_window')!=source_window
                or query_context.get('plan_trade_date')!=date
                or value['context'].get('focus_window_start')!=source_window.get('start')
                or query_context.get('focus_window_start')!=source_window.get('start')
                or _targeted_scope_id(date,codes,source_window)!=value['scope_id']):
            raise ValueError('ANNOUNCEMENT_TARGETED_SCOPE_IDENTITY_INVALID')
        query_start,query_cutoff=window(query_context)
        expected_end=datetime.combine(datetime.strptime(date,'%Y%m%d').date()+timedelta(days=1),time.min,HK)
        actual_cutoff=timestamp(value['context']['research_cutoff'])
        if (source_window.get('end_exclusive')!=expected_end.isoformat()
                or source_window.get('source_dates')!=[source_window.get('start','')[:10].replace('-',''),date]
                or source_window.get('timezone')!='Asia/Hong_Kong'
                or value['context'].get('market_session')!=source_window['source_dates'][0]
                or query_context.get('market_session')!=source_window['source_dates'][0]
                or query_start.isoformat()!=source_window.get('start')
                or query_cutoff>=expected_end or query_cutoff>actual_cutoff):
            raise ValueError('ANNOUNCEMENT_TARGETED_QUERY_WINDOW_INVALID')
        if (coverage.get('scope_id')!=value['scope_id']
                or coverage.get('scope_type')!='EXPLICIT_ISSUER_LIST'
                or coverage.get('selected_issuer_codes')!=codes
                or coverage.get('selected_issuer_count')!=len(codes)
                or coverage.get('native_master_count')!=value['master_scope_count']
                or coverage.get('native_master_identity')!=value['master_scope_identity']
                or type(coverage.get('all_master_issuers_included')) is not bool):
            raise ValueError('ANNOUNCEMENT_TARGETED_COVERAGE_INVALID')
    elif any(key in value for key in ('query_context','source_window','scope_id','scope_coverage','master_scope_identity','master_scope_count')):
        raise ValueError('ANNOUNCEMENT_TARGETED_METADATA_WITHOUT_EXPLICIT_SCOPE')
    daily=value['context'].get('publication_window_mode')=='HK_CALENDAR_DAY_V1'
    if daily:
        publication_window(value['context'])
        start=value.get('daily_cursor_start');next_cursor=value.get('daily_cursor_next')
        refs=value.get('daily_parent_refs',[]);priority=value.get('daily_priority_codes',[])
        advance=value.get('daily_cursor_advance')
        if (type(start) is not int or type(next_cursor) is not int or not 0<=start<len(codes)
                or not 0<=next_cursor<len(codes)
                or not isinstance(priority,list) or priority!=sorted(set(priority))
                or any(code not in codes for code in priority)
                or value.get('scan_order')!=priority+[code for code in codes[start:]+codes[:start] if code not in priority]
                or type(advance) is not int or not 0<=advance<=index
                or next_cursor!=(start+advance)%len(codes)
                or not isinstance(refs,list) or len(refs)>MAX_DAILY_PARENT_PRODUCTS):
            raise ValueError('ANNOUNCEMENT_DAILY_CURSOR_OR_PARENT_INVALID')
        parent_keys=[]
        for ref in refs:
            if (not isinstance(ref,dict) or ref.get('target_trade_date')!=date
                    or not re.fullmatch(r'[0-9a-f]{32}',str(ref.get('run_id','')))
                    or type(ref.get('revision')) is not int or ref['revision']<1
                    or not re.fullmatch(r'[0-9a-f]{64}',str(ref.get('sha256','')))):
                raise ValueError('ANNOUNCEMENT_DAILY_PARENT_REFERENCE_INVALID')
            parent_keys.append((ref['run_id'],ref['revision']))
        if len(parent_keys)!=len(set(parent_keys)) or any(run==value.get('run_id') for run,_rev in parent_keys):
            raise ValueError('ANNOUNCEMENT_DAILY_PARENT_DUPLICATE')
    elif any(k in value for k in ('daily_cursor_start','daily_cursor_next','daily_cursor_advance','daily_priority_codes','daily_parent_refs')):
        raise ValueError('ANNOUNCEMENT_DAILY_METADATA_WITHOUT_DAILY_WINDOW')
    return deepcopy(dict(value))


def _check_sources(service: Any, product: Mapping[str,Any], *, validation_cache: dict | None=None) -> dict:
    """Verify the original owner identity plus every retained source binding."""
    from .hkex_provider import ACTIVE_STOCK_LIST_URL
    import json
    names,witness=_master(service,product['context'])
    targeted=product.get('capture_scope')==TARGETED_HKEX_SCOPE
    if targeted:
        if (witness!=product['identity_witness'] or not set(product['scope']).issubset(names)
                or len(names)!=product.get('master_scope_count')
                or digest(sorted(names))!=product.get('master_scope_identity')
                or product.get('scope_coverage',{}).get('all_master_issuers_included')!=(product['scope']==sorted(names))
                or product.get('scope_identity')!=digest([TARGETED_HKEX_SCOPE,product['scope_id'],
                    witness,product['master_scope_identity'],product['scope']])):
            raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_CHANGED')
        query_context=product['query_context']
    else:
        if witness!=product['identity_witness'] or sorted(names)!=product['scope']:
            raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_CHANGED')
        query_context=product['context']
    store=service._material_store;listed=[];parsed_documents={}
    # Request-local only: each unique original reference is verified again on
    # the NEXT GET. Never share this with a persisted or cross-request cache.
    cache=validation_cache if validation_cache is not None else {}
    responses=cache.setdefault('responses',{});page_cache=cache.setdefault('pages',{})
    def checked(ref):
        key=digest(ref)
        body=responses.get(key)
        if body is None:
            body=read_response(store,ref)
            cache['raw_revalidations']=cache.get('raw_revalidations',0)+1
            if len(responses)<4096 and cache.get('bytes',0)+len(body)<=64*1024*1024:
                responses[key]=body;cache['bytes']=cache.get('bytes',0)+len(body)
        if timestamp(ref['retrieved_at'])>timestamp(product['generated_at']):
            raise ValueError('ANNOUNCEMENT_SOURCE_AFTER_OWNER_PUBLICATION')
        return body
    for q in product['queries']:
        if q['name']!=names[q['code']]['name']:
            raise ValueError('ANNOUNCEMENT_NAME_IDENTITY_MISMATCH')
        mapping_ref=q['mapping_ref'];mapping=checked(mapping_ref)
        since,as_of=window(query_context)
        if mapping_ref['request']!=dict(url=ACTIVE_STOCK_LIST_URL,method='GET',
                context=request_context(query_context)) or mapping_ref['http_status']!=200:
            raise ValueError('ANNOUNCEMENT_ACTIVE_LIST_REFERENCE_INVALID')
        official=[x for x in json.loads(mapping) if isinstance(x,dict)
            and re.fullmatch(r'\d{5}',str(x.get('c','')))
            and str(x.get('i','')).isdigit() and x.get('n')
            and x.get('c')==q['code'].split('.')[1]]
        if len(official)>1:
            raise ValueError('ANNOUNCEMENT_OFFICIAL_ISSUER_BINDING_INVALID')
        expected_issuer=(dict(stock_id=str(official[0]['i']),issuer=official[0]['n']) if official else None)
        if q.get('official_issuer')!=expected_issuer:
            raise ValueError('ANNOUNCEMENT_OFFICIAL_ISSUER_BINDING_INVALID')
        if q['status'] not in {'FAILED','OBSERVED'} or (q['status']=='FAILED' and (q['entries'] or q['rejected'])):
            raise ValueError('ANNOUNCEMENT_QUERY_STATUS_INVALID')
        if q.get('prime_ref'):
            checked(q['prime_ref'])
            request=query_request(q['official_issuer'],query_context)
            if q['prime_ref']['request']!=dict(url=request['referer'],method='GET',context=request['context'],cache_policy='SESSION_PRIME'):
                raise ValueError('ANNOUNCEMENT_QUERY_PRIME_MISMATCH')
        if q.get('directory_ref'):
            ref=q['directory_ref'];raw=checked(ref)
            if ref['request']!=query_request(q['official_issuer'],query_context):
                raise ValueError('ANNOUNCEMENT_QUERY_WINDOW_OR_ISSUER_MISMATCH')
            if q['status']=='OBSERVED':
                entries,rejected,reason=directory_entries(
                    raw, q['code'], query_context,
                    expected_stock_id=q['official_issuer']['stock_id'],
                )
                if (entries!=q['entries'] or rejected!=q['rejected'] or reason!=q['reason']
                        or not 200<=ref['http_status']<300):
                    raise ValueError('ANNOUNCEMENT_DIRECTORY_DERIVATION_MISMATCH')
            elif 200<=ref['http_status']<300:
                try:
                    entries, rejected, reason = directory_entries(
                        raw, q['code'], query_context,
                        expected_stock_id=q['official_issuer']['stock_id'],
                    )
                except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
                    # Preserve a faithfully recorded source failure. The narrow
                    # old-layout exception below applies only when current
                    # parsing can now prove the exact native empty response.
                    if q['reason']!=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED'):
                        raise ValueError('ANNOUNCEMENT_FAILED_QUERY_REASON_MISMATCH') from exc
                else:
                    legacy_empty = (
                        ref['http_status'] == 200
                        and q['reason'] == 'ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED'
                        and not entries and not rejected
                        and reason == 'NO_ROWS_IN_OBSERVED_RESPONSE'
                    )
                    if not legacy_empty:
                        raise ValueError('ANNOUNCEMENT_FAILED_QUERY_HAS_DERIVABLE_DIRECTORY')
                    # Keep the historical attempt's FAILED label and reason.
                    # This only allows immutable raw evidence to be revalidated
                    # and resumed; it does not rewrite the old owner product.
            elif q['reason']!='ANNOUNCEMENT_DIRECTORY_HTTP_FAILED':
                raise ValueError('ANNOUNCEMENT_FAILED_QUERY_REASON_MISMATCH')
        elif q['status']=='OBSERVED':
            raise ValueError('ANNOUNCEMENT_DIRECTORY_RAW_MISSING')
        elif q.get('official_issuer'):
            request=query_request(q['official_issuer'],query_context)
            source_key='hkex-announcement-request:'+digest(request)
            if store.stat_source(source_key) is not None:
                raise ValueError('ANNOUNCEMENT_DIRECTORY_RAW_REFERENCE_MISSING')
        for row in q['entries']:
            listed.append(dict(code=q['code'],name=q['name'],row=row,directory_ref=q['directory_ref'],
                mapping_ref=q['mapping_ref'],official_issuer=q['official_issuer']))
    # No dropped/inserted pending document can make a scan appear complete.
    consumed=[{k:v for k,v in doc.items() if k not in {'body_ref','parse_status','reason'}} for doc in product['documents']]
    if consumed+product['pending_documents']!=listed:
        raise ValueError('ANNOUNCEMENT_DOCUMENT_INVENTORY_MISMATCH')
    for doc in product['documents']:
        if doc['parse_status'] not in {'FAILED','BODY_PARSED','BODY_UNREADABLE'}:
            raise ValueError('ANNOUNCEMENT_PARSE_STATUS_INVALID')
        if doc.get('body_ref'):
            ref=doc['body_ref'];raw=checked(ref)
            if ref['request']!=dict(url=doc['row']['url'],method='GET'):
                raise ValueError('ANNOUNCEMENT_DOCUMENT_URL_MISMATCH')
            if not 200<=ref['http_status']<300:
                if doc['parse_status']!='FAILED':raise ValueError('ANNOUNCEMENT_HTTP_FAILURE_MASQUERADING_AS_BODY')
                continue
            # Re-derive readability, not just the self-hash of a status. A negative
            # PDF cannot disappear by relabelling its valid bytes as unreadable.
            if ref['blob_sha256'] in page_cache:
                parsed_documents[ref['blob_sha256']]=page_cache[ref['blob_sha256']]
            if ref['blob_sha256'] not in parsed_documents:
                try:
                    parsed_documents[ref['blob_sha256']]=_cached_extract_pdf_pages(raw,max_bytes=MAX_BYTES,
                        max_pages=40,max_text_characters=240000,timeout_seconds=10,cache_stats=cache)
                except (ValueError, RuntimeError) as exc:
                    # Recompute fixed deterministic limits from the original bytes.
                    # Wall-clock parser timeouts are NOT a reproducible unread state.
                    reason=safe_reason(exc,'ANNOUNCEMENT_DOCUMENT_PARSE_FAILED')
                    if (reason not in {'PDF_PAGE_BUDGET_EXCEEDED','PDF_BYTE_BUDGET_EXCEEDED',
                                       'PDF_TEXT_BUDGET_EXCEEDED'} or
                            doc['parse_status']!='FAILED' or doc.get('reason')!=reason):
                        raise
                    parsed_documents[ref['blob_sha256']]=reason
                pages=parsed_documents[ref['blob_sha256']]
                size=len(pages) if isinstance(pages,str) else sum(len(str(p.get('text',''))) for p in pages)
                if len(page_cache)<4096 and cache.get('text_chars',0)+size<=2_000_000:
                    page_cache[ref['blob_sha256']]=pages;cache['text_chars']=cache.get('text_chars',0)+size
            if isinstance(parsed_documents[ref['blob_sha256']],str):
                if doc['parse_status']!='FAILED' or doc.get('reason')!=parsed_documents[ref['blob_sha256']]:
                    raise ValueError('ANNOUNCEMENT_BODY_BUDGET_DERIVATION_MISMATCH')
                continue
            expected='BODY_PARSED' if parsed_documents[ref['blob_sha256']] else 'BODY_UNREADABLE'
            if doc['parse_status']!=expected:
                raise ValueError('ANNOUNCEMENT_BODY_READABILITY_DERIVATION_MISMATCH')
        elif doc['parse_status']!='FAILED':
            raise ValueError('ANNOUNCEMENT_DOCUMENT_RAW_MISSING')
        elif store.stat_source('hkex-announcement-request:'+digest(
                dict(url=doc['row']['url'],method='GET'))) is not None:
            raise ValueError('ANNOUNCEMENT_DOCUMENT_RAW_REFERENCE_MISSING')
    return parsed_documents


def refresh(service: Any,date: str,*,resume: bool=False, schedule: Mapping[str,Any] | None=None,
            source_scope: str | None=None, issuer_code: str | None=None,
            issuer_codes: list[str] | None=None, publication_date: str | None=None) -> dict:
    if source_scope == EASTMONEY_DATE_CATALOG_SCOPE:
        if schedule is not None or issuer_code is not None or issuer_codes is not None or publication_date is None:
            raise ValueError('ANNOUNCEMENT_DATE_CATALOG_ARGUMENT_INVALID')
        return refresh_eastmoney_date_catalog(service,date,publication_date,resume=resume)
    if source_scope is not None:
        if source_scope != EASTMONEY_SCOPE or resume or schedule is not None or issuer_codes is not None or publication_date is not None:
            raise ValueError('ANNOUNCEMENT_SOURCE_SCOPE_INVALID')
        return refresh_eastmoney_hk(service,date,issuer_code=issuer_code)
    if publication_date is not None:
        raise ValueError('ANNOUNCEMENT_PUBLICATION_DATE_REQUIRES_DATE_CATALOG_SCOPE')
    if issuer_codes is not None:
        if issuer_code is not None or schedule is not None:
            raise ValueError('ANNOUNCEMENT_TARGETED_SCOPE_ARGUMENT_CONFLICT')
        return _refresh_targeted_hkex(service,date,issuer_codes,resume=resume)
    if issuer_code is not None:
        raise ValueError('ANNOUNCEMENT_ISSUER_SCOPE_REQUIRES_SOURCE_SCOPE')
    if schedule is not None:
        if resume:
            raise ValueError('ANNOUNCEMENT_SCHEDULE_CANNOT_CHANGE_MANUAL_RESUME')
        from .announcement_autorun import scheduled_refresh
        return scheduled_refresh(service,date,schedule)
    from .workspace import ATTEMPT_SCHEMA,seal_attempt,validate_attempt
    date=date_token(date)
    root=service.store.root/'workspace_announcements'/date
    runroot=service.store.root/'workspace_announcement_runs'/date
    with service.store._transaction(date,'workspace-announcements'):
        prior=service.store._read(runroot/'latest.json')
        if prior is not None:prior=validate_attempt(prior,date)
        attempt=dict(schema_version=ATTEMPT_SCHEMA,target_trade_date=date,run_id=uuid4().hex,owner=OWNER,
            state='RUNNING',execution_kind='MANUAL_REFRESH',started_at=_now(),
            last_success_at=(prior or {}).get('last_success_at'),failure_reasons=[],**FLAGS)
        def journal():
            sealed=validate_attempt(seal_attempt(attempt),date)
            service.store._write_atomic(runroot/(attempt['run_id']+'.json'),sealed)
            service.store._write_atomic(runroot/'latest.json',sealed)
        journal()
        try:
            if service._material_store is None or getattr(service.source_provider,'_material_store',None) is not service._material_store:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
            if resume:
                previous=service.store._read(root/'latest.json')
                if previous is None:raise ValueError('ANNOUNCEMENT_RESUME_PRODUCT_MISSING')
                previous=validate_product(previous,date)
                if previous['context'].get('publication_window_mode')=='HK_CALENDAR_DAY_V1':
                    raise ValueError('ANNOUNCEMENT_DAILY_UPDATE_USES_FRESH_CUTOFF')
                raise ValueError('ANNOUNCEMENT_LEGACY_PRODUCT_NOT_DAILY_RESUMABLE')
            previous=service.store._read(root/'latest.json')
            if previous is not None:
                previous=validate_product(previous,date)
            context=_daily_context(date,now=timestamp(attempt['started_at']))
            names,witness=_master(service,context)
            codes=sorted(names)
            parents,reusable,retry_codes=_daily_reuse_inventory(service,date,previous)
            parent_refs=[]
            cursor=0
            if previous is not None:
                parent_refs.extend(deepcopy(previous.get('daily_parent_refs',[])))
                parent_refs.append(_product_reference(previous,date))
                if previous['context'].get('publication_window_mode')=='HK_CALENDAR_DAY_V1':
                    cursor=int(previous['daily_cursor_next'])%len(codes)
            parent_keys={(ref['run_id'],ref['revision']) for ref in parent_refs}
            if len(parent_refs)>MAX_DAILY_PARENT_PRODUCTS or len(parent_keys)!=len(parent_refs):
                raise ValueError('ANNOUNCEMENT_DAILY_PARENT_BOUND_INVALID')
            priority=sorted(set(retry_codes)&set(codes))
            rotation=codes[cursor:]+codes[:cursor]
            scan_order=priority+[code for code in rotation if code not in priority]
            product=dict(schema_version=SCHEMA,owner=OWNER,target_trade_date=date,run_id=uuid4().hex,
                revision=1,context=context,identity_witness=witness,scope=codes,scan_order=scan_order,
                scope_identity=digest([witness,codes]),next_index=0,queries=[],documents=[],pending_documents=[],
                daily_cursor_start=cursor,daily_cursor_next=cursor,daily_cursor_advance=0,
                daily_priority_codes=priority,daily_parent_refs=parent_refs,**FLAGS)
            stop=min(len(scan_order),BATCH_SIZE)
            issuers=[dict(code=c,name=names[c]['name']) for c in scan_order[:stop]]
            batch=service.source_provider.collect_announcement_batch(context=product['context'],issuers=issuers,
                pending_documents=[],reusable_documents=reusable)
            product['queries'].extend(batch['queries']);product['documents'].extend(batch['documents'])
            stop=len(batch['queries'])
            product.update(next_index=stop,pending_documents=batch['pending_documents'],
                daily_cursor_advance=sum(query['code'] not in priority for query in batch['queries']),
                daily_cursor_next=(cursor+sum(query['code'] not in priority for query in batch['queries']))%len(codes),
                generated_at=_now(),
                parser_revision=PARSER_VERSION,execution_kind='MANUAL_REFRESH',natural_run_verified=False)
            product=_seal(product);validate_product(product,date);_check_sources(service,product)
            service.store._write_atomic(root/product['run_id']/(str(product['revision'])+'.json'),product)
            service.store._write_atomic(root/'latest.json',product)
            from .announcement_autorun import retain_manual_product
            for parent in parents:
                retain_manual_product(service,date,parent)
            retain_manual_product(service,date,product)
            failed=[q['code'] for q in product['queries'] if q['status']=='FAILED']
            attempt.update(state='PARTIAL',finished_at=_now(),last_success_at=product['generated_at'],
                input_identity=product['scope_identity'],failure_reasons=['OFFICIAL_DIRECTORY_EXHAUSTION_UNVERIFIED'],
                input_coverage=dict(native_master_count=len(names),queried_count=stop,
                    pending_issuer_count=len(names)-stop,pending_document_count=len(product['pending_documents']),failed_issuers=failed),
                success_scope='BOUNDED_ORIGINAL_OWNER_SOURCE_CAPTURE_NOT_ALL_ANNOUNCEMENTS')
            journal()
        except Exception as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=[safe_reason(exc,'ANNOUNCEMENT_OWNER_FAILED')])
            journal()
            raise
        return read(service,date)


def _refresh_targeted_hkex(service: Any,date: str,issuer_codes: list[str],*,resume: bool=False) -> dict:
    from .workspace import ATTEMPT_SCHEMA,seal_attempt,validate_attempt
    date=date_token(date)
    if (not isinstance(issuer_codes,list) or not 1<=len(issuer_codes)<=24
            or len(set(issuer_codes))!=len(issuer_codes)
            or any(not isinstance(code,str) or canonical_symbol(code)!=code for code in issuer_codes)):
        raise ValueError('ANNOUNCEMENT_TARGETED_ISSUER_LIST_INVALID')
    codes=sorted(issuer_codes)
    started=_now();actual,query_context=_targeted_hkex_context(date,now=timestamp(started))
    source_window=deepcopy(actual['targeted_source_window'])
    scope_id=_targeted_scope_id(date,codes,source_window)
    product_root=service.store.root/'workspace_announcements'/date/'issuer_subsets'/scope_id
    attempt_root=service.store.root/'workspace_announcement_runs'/date/'issuer_subsets'/scope_id
    with service.store._transaction(date,'workspace-announcements'):
        prior_attempt=service.store._read(attempt_root/'latest.json')
        if prior_attempt is not None:
            prior_attempt=validate_attempt(prior_attempt,date)
        attempt=dict(schema_version=ATTEMPT_SCHEMA,target_trade_date=date,run_id=uuid4().hex,owner=OWNER,
            state='RUNNING',execution_kind='MANUAL_REFRESH',source_scope='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET',
            scope_id=scope_id,started_at=started,last_success_at=(prior_attempt or {}).get('last_success_at'),
            failure_reasons=[],input_coverage=dict(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,
                selected_issuer_codes=codes,selected_issuer_count=len(codes),native_master_count=None,
                native_master_identity=None,all_master_issuers_included=False,max_issuers=len(codes),
                source_window=source_window),**FLAGS)
        def journal():
            sealed=validate_attempt(seal_attempt(attempt),date)
            service.store._write_atomic(attempt_root/(attempt['run_id']+'.json'),sealed)
            service.store._write_atomic(attempt_root/'latest.json',sealed)
        journal()
        try:
            if service._material_store is None or getattr(service.source_provider,'_material_store',None) is not service._material_store:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
            names,witness=_master(service,actual)
            missing=sorted(set(codes)-set(names))
            if missing:
                raise ValueError('ANNOUNCEMENT_TARGETED_ISSUER_NOT_IN_VERIFIED_MASTER')
            master_identity=digest(sorted(names))
            previous=service.store._read(product_root/'latest.json')
            if previous is not None:
                previous=validate_product(previous,date)
                if previous.get('scope_id')!=scope_id or previous.get('capture_scope')!=TARGETED_HKEX_SCOPE:
                    raise ValueError('ANNOUNCEMENT_TARGETED_SCOPE_RESUME_MISMATCH')
                _check_sources(service,previous)
            if resume and previous is None:
                raise ValueError('ANNOUNCEMENT_TARGETED_RESUME_PRODUCT_MISSING')
            if resume and (previous.get('scope')!=codes
                    or previous.get('master_scope_count')!=len(names)
                    or previous.get('master_scope_identity')!=master_identity
                    or previous.get('identity_witness')!=witness):
                raise ValueError('ANNOUNCEMENT_TARGETED_SCOPE_MASTER_CHANGED')
            if resume:
                query_context=deepcopy(previous['query_context'])
                product=dict(previous)
                product.update(context=actual,query_context=query_context,
                    revision=previous['revision']+1,generated_at=None)
                queries_by_code={q['code']:deepcopy(q) for q in previous['queries']}
                documents=deepcopy(previous['documents'])
                pending_documents=deepcopy(previous['pending_documents'])
                run_id=previous['run_id']
            else:
                queries_by_code={};documents=[];pending_documents=[]
                run_id=uuid4().hex
                product=dict(schema_version=SCHEMA,owner=OWNER,target_trade_date=date,run_id=run_id,
                    revision=1,context=actual,query_context=query_context,source_window=source_window,
                    capture_scope=TARGETED_HKEX_SCOPE,source_scope='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET',
                    scope_id=scope_id,identity_witness=witness,scope=codes,scan_order=codes,
                    master_scope_count=len(names),master_scope_identity=master_identity,
                    scope_identity=digest([TARGETED_HKEX_SCOPE,scope_id,witness,master_identity,codes]),
                    scope_coverage=dict(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,
                        selected_issuer_codes=codes,selected_issuer_count=len(codes),native_master_count=len(names),
                        native_master_identity=master_identity,all_master_issuers_included=(codes==sorted(names))),
                    next_index=0,queries=[],documents=[],pending_documents=[],**FLAGS)
            retry_codes={code for code,q in queries_by_code.items() if q.get('status')=='FAILED'}
            issuer_batch=[dict(code=code,name=names[code]['name']) for code in codes
                if code not in queries_by_code or code in retry_codes]
            batch=service.source_provider.collect_announcement_batch(context=query_context,
                issuers=issuer_batch,pending_documents=pending_documents,
                max_issuers=len(codes),max_documents=MAX_DOCUMENTS)
            for query in batch['queries']:
                queries_by_code[query['code']]=query
            queries=[queries_by_code[code] for code in codes if code in queries_by_code]
            documents.extend(batch['documents'])
            pending_documents=batch['pending_documents']
            product.update(context=actual,query_context=query_context,source_window=source_window,
                capture_scope=TARGETED_HKEX_SCOPE,source_scope='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET',
                scope_id=scope_id,identity_witness=witness,scope=codes,scan_order=codes,
                master_scope_count=len(names),master_scope_identity=master_identity,
                scope_identity=digest([TARGETED_HKEX_SCOPE,scope_id,witness,master_identity,codes]),
                scope_coverage=dict(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,
                    selected_issuer_codes=codes,selected_issuer_count=len(codes),native_master_count=len(names),
                    native_master_identity=master_identity,all_master_issuers_included=(codes==sorted(names))),
                next_index=len(queries),queries=queries,documents=documents,pending_documents=pending_documents,
                generated_at=_now(),parser_revision=PARSER_VERSION,execution_kind='MANUAL_REFRESH',
                natural_run_verified=False)
            product=_seal(product);validate_product(product,date);_check_sources(service,product)
            service.store._write_atomic(product_root/product['run_id']/(str(product['revision'])+'.json'),product)
            service.store._write_atomic(product_root/'latest.json',product)
            failed=[q['code'] for q in product['queries'] if q['status']=='FAILED']
            query_cutoff=timestamp(query_context['research_cutoff'])
            late_count=sum(1 for doc in [*product['documents'],*product['pending_documents']]
                if timestamp(doc.get('directory_ref',{}).get('retrieved_at')) is not None
                and timestamp(doc.get('directory_ref',{}).get('retrieved_at'))>query_cutoff)
            attempt.update(state='PARTIAL',finished_at=_now(),last_success_at=product['generated_at'],
                input_identity=product['scope_identity'],failure_reasons=['OFFICIAL_DIRECTORY_EXHAUSTION_UNVERIFIED'],
                input_coverage=dict(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,
                    selected_issuer_codes=codes,selected_issuer_count=len(codes),native_master_count=len(names),
                    native_master_identity=master_identity,all_master_issuers_included=(codes==sorted(names)),
                    queried_count=len(queries),pending_issuer_count=len(codes)-len(queries),
                    pending_document_count=len(product['pending_documents']),failed_issuers=failed,
                    max_issuers=len(codes),source_window=source_window,
                    query_cutoff=query_context['research_cutoff'],capture_cutoff=product['context']['research_cutoff'],
                    late_acquisition_document_count=late_count),
                success_scope='BOUNDED_ORIGINAL_OWNER_EXPLICIT_SUBSET_NOT_FULL_MASTER')
            journal()
        except Exception as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=[safe_reason(exc,'ANNOUNCEMENT_OWNER_FAILED')])
            journal()
            raise
    return read(service,date,scope_id=scope_id)


def _validate_eastmoney_product(value: Mapping[str,Any],date: str) -> dict:
    from .announcement_source import (MAX_EASTMONEY_CONTENT_PAGES,
        MAX_EASTMONEY_TOTAL_RESPONSE_BYTES)
    if (not isinstance(value,dict) or value.get('schema_version')!=EASTMONEY_SCHEMA
            or value.get('owner')!=OWNER or value.get('target_trade_date')!=date_token(date)
            or value.get('source')!='EASTMONEY_HK'
            or value.get('source_scope')!='MASTER_OWNED_BOUNDED_HK_ISSUERS_NOT_FULL_MARKET'
            or value.get('sha256')!=_seal(value)['sha256']
            or any(value.get(k) is not v for k,v in FLAGS.items())
            or not re.fullmatch(r'[0-9a-f]{32}',str(value.get('run_id','')))
            or not timestamp(value.get('generated_at'))
            or not isinstance(value.get('queries'),list) or not isinstance(value.get('documents'),list)
            or not isinstance(value.get('pending_documents'),list)
            or not isinstance(value.get('capture_budget'),dict)):
        raise ValueError('EASTMONEY_HK_PRODUCT_IDENTITY_INVALID')
    budget=value['capture_budget']
    expected_requests=len(value.get('scope',[]))+MAX_DOCUMENTS*(MAX_EASTMONEY_CONTENT_PAGES+1)
    if (budget.get('max_seconds')!=45 or budget.get('max_requests')!=expected_requests
            or budget.get('max_response_bytes')!=MAX_EASTMONEY_TOTAL_RESPONSE_BYTES
            or isinstance(budget.get('elapsed_seconds'),bool)
            or not isinstance(budget.get('elapsed_seconds'),(int,float))
            or not 0<=budget['elapsed_seconds']<=45
            or type(budget.get('requests_used')) is not int or not 0<=budget['requests_used']<=expected_requests
            or type(budget.get('response_bytes_used')) is not int
            or not 0<=budget['response_bytes_used']<=MAX_EASTMONEY_TOTAL_RESPONSE_BYTES):
        raise ValueError('EASTMONEY_HK_CAPTURE_BUDGET_INVALID')
    if value.get('context',{}).get('plan_trade_date')!=date:
        raise ValueError('EASTMONEY_HK_PRODUCT_TARGET_INVALID')
    window(value['context'])
    codes=value.get('scope')
    if (not isinstance(codes,list) or not codes or codes!=sorted(set(codes))
            or any(canonical_symbol(code)!=code for code in codes)
            or value.get('scope_identity')!=digest([value.get('identity_witness'),codes])):
        raise ValueError('EASTMONEY_HK_PRODUCT_SCOPE_INVALID')
    return deepcopy(dict(value))


def _check_eastmoney_sources(service: Any,product: Mapping[str,Any]) -> dict:
    from .announcement_source import (eastmoney_list_url,eastmoney_content_url,
        read_eastmoney_response,_eastmoney_display_time,MAX_BYTES,
        MAX_EASTMONEY_CONTENT_PAGES,MAX_EASTMONEY_BODY_CHARACTERS)
    import json
    names,witness=_master(service,product['context'])
    if witness!=product.get('identity_witness') or sorted(product['scope'])!=[q.get('code') for q in product['queries']]:
        raise ValueError('EASTMONEY_HK_MASTER_IDENTITY_CHANGED')
    since,cutoff=window(product['context'])
    query_by_code={}
    for q in product['queries']:
        code=q.get('code')
        if code not in names or q.get('name')!=names[code]['name'] or code in query_by_code:
            raise ValueError('EASTMONEY_HK_QUERY_ISSUER_INVALID')
        query_by_code[code]=q
        ref=q.get('listing_ref')
        if not isinstance(ref,dict):
            if q.get('status')!='FAILED':raise ValueError('EASTMONEY_HK_LIST_REFERENCE_MISSING')
            continue
        raw=read_eastmoney_response(service._material_store,ref)
        if (ref['request']!=dict(source='EASTMONEY_HK',method='GET',url=eastmoney_list_url(code.split('.')[1]))
                or ref['http_status']!=200 or timestamp(ref['retrieved_at'])>timestamp(product['generated_at'])):
            raise ValueError('EASTMONEY_HK_LIST_REFERENCE_INVALID')
        payload=json.loads(raw.decode('utf-8'));data=payload.get('data') if isinstance(payload,dict) else None
        rows=data.get('list') if isinstance(data,dict) else None
        if not isinstance(rows,list) or payload.get('success')!=1:
            raise ValueError('EASTMONEY_HK_LIST_DERIVATION_INVALID')
        retained=[]
        for row in rows:
            if not isinstance(row,dict):continue
            code_rows=[item for item in row.get('codes',[]) if isinstance(item,dict)]
            matches=[item for item in code_rows if str(item.get('market_code'))=='116'
                and str(item.get('stock_code'))==code.split('.')[1] and item.get('ann_type')=='H']
            if len(matches)!=1:continue
            from .announcement_source import _eastmoney_notice_date
            displayed=_eastmoney_display_time(row.get('display_time'))
            _eastmoney_notice_date(row.get('notice_date'))
            if not since<displayed<=cutoff:continue
            retained.append(dict(art_code=row.get('art_code'),title=row.get('title'),
                notice_date=row.get('notice_date'),display_time=row.get('display_time'),
                display_time_iso=displayed.isoformat(),source_notice_date=row['notice_date'][:10],
                source_codes=[dict(market_code=str(item.get('market_code','')),
                    stock_code=str(item.get('stock_code','')),ann_type=str(item.get('ann_type','')),
                    short_name=item.get('short_name')) for item in code_rows],market_code='116',
                stock_code=code.split('.')[1],ann_type='H',short_name=matches[0].get('short_name'),
                listing_ref=ref))
        retained.sort(key=lambda item:(item['display_time_iso'],item['art_code']),reverse=True)
        if q.get('entries')!=retained:
            raise ValueError('EASTMONEY_HK_LIST_ROWS_CHANGED')
    docs_by_code={code:[] for code in product['scope']}
    verified={}
    for doc in product['documents']:
        code=doc.get('code');row=doc.get('row')
        if code not in query_by_code or not isinstance(row,dict) or row not in query_by_code[code].get('entries',[]):
            raise ValueError('EASTMONEY_HK_DOCUMENT_NOT_LISTED')
        content_refs=doc.get('content_refs');body_pages=doc.get('body_pages')
        if (not isinstance(content_refs,list) or not isinstance(body_pages,list)
                or not 1<=len(content_refs)<=MAX_EASTMONEY_CONTENT_PAGES
                or len(content_refs)!=len(body_pages) or doc.get('content_page_count')!=len(content_refs)
                or doc.get('body_status')!='FULL_CONTENT_API_TEXT_VERIFIED'
                or doc.get('body_source')!='EASTMONEY_CONTENT_API_PAGES'):
            raise ValueError('EASTMONEY_HK_CONTENT_PAGE_BINDING_INVALID')
        details=[];text_parts=[];text_characters=0
        from hashlib import sha256
        for page_index,(content_ref,body_page) in enumerate(zip(content_refs,body_pages),start=1):
            content_raw=read_eastmoney_response(service._material_store,content_ref)
            detail_payload=json.loads(content_raw.decode('utf-8'))
            detail=detail_payload.get('data') if isinstance(detail_payload,dict) else None
            if (content_ref.get('request')!=dict(source='EASTMONEY_HK',method='GET',
                    url=eastmoney_content_url(row['art_code'],page_index=page_index))
                    or content_ref['http_status']!=200 or not isinstance(detail,dict)
                    or detail_payload.get('success')!=1 or detail.get('art_code')!=row['art_code']
                    or detail.get('notice_title')!=row['title'] or detail.get('notice_date')!=row['notice_date']
                    or detail.get('page_size')!=len(content_refs)):
                raise ValueError('EASTMONEY_HK_CONTENT_REFERENCE_INVALID')
            matches=[item for item in detail.get('security',[]) if isinstance(item,dict)
                and str(item.get('market_uni',''))=='116' and str(item.get('stock',''))==code.split('.')[1]]
            if not matches:
                raise ValueError('EASTMONEY_HK_CONTENT_SECURITY_MISMATCH')
            page_text=detail.get('notice_content')
            if (not isinstance(page_text,str) or not page_text.strip()
                    or body_page.get('page_index')!=page_index or body_page.get('text')!=page_text
                    or body_page.get('text_sha256')!=sha256(page_text.encode('utf-8')).hexdigest()
                    or body_page.get('source_ref')!=content_ref):
                raise ValueError('EASTMONEY_HK_CONTENT_PAGE_TEXT_MISMATCH')
            text_characters+=len(page_text)
            if text_characters>MAX_EASTMONEY_BODY_CHARACTERS:
                raise ValueError('EASTMONEY_HK_CONTENT_TEXT_BUDGET_EXCEEDED')
            text_parts.append(page_text);details.append(detail)
        detail=details[0]
        body_text='\n\n'.join(text_parts)
        if (doc.get('body_text')!=body_text
                or doc.get('body_sha256')!=sha256(body_text.encode('utf-8')).hexdigest()):
            raise ValueError('EASTMONEY_HK_CONTENT_BODY_HASH_MISMATCH')
        if any(item.get('page_size')!=len(details) or item.get('attach_url_web')!=detail.get('attach_url_web')
                for item in details):
            raise ValueError('EASTMONEY_HK_CONTENT_PAGE_SET_MISMATCH')
        if doc.get('pdf_text_extraction_status')!='UNVERIFIED_ENCODING':
            raise ValueError('EASTMONEY_HK_PDF_TEXT_STATUS_INVALID')
        pdf_extracted_pages=doc.get('pdf_extracted_pages')
        if not isinstance(pdf_extracted_pages,list) or doc.get('pdf_extracted_pages_sha256')!=digest(pdf_extracted_pages):
            raise ValueError('EASTMONEY_HK_PDF_TEXT_EVIDENCE_INVALID')
        pdf_ref=doc.get('pdf_ref')
        if detail.get('attach_url_web')!=pdf_ref.get('request',{}).get('url'):
            raise ValueError('EASTMONEY_HK_PDF_REFERENCE_INVALID')
        pdf_raw=read_eastmoney_response(service._material_store,pdf_ref)
        if (pdf_ref['http_status']!=200 or not pdf_raw.startswith(b'%PDF')
                or doc.get('document_sha256')!=pdf_ref['body_sha256']
                or doc.get('pdf_bytes')!=len(pdf_raw)):
            raise ValueError('EASTMONEY_HK_FULL_PDF_BINDING_INVALID')
        pages=extract_pdf_pages(pdf_raw,max_bytes=MAX_BYTES,max_pages=40,
            max_text_characters=240000,timeout_seconds=10)
        if (not pages or doc.get('pdf_page_count')!=len(pages) or doc.get('full_pdf_stored') is not True
                or pages!=pdf_extracted_pages or digest(pages)!=doc['pdf_extracted_pages_sha256']):
            raise ValueError('EASTMONEY_HK_PDF_PAGE_READBACK_INVALID')
        refs=[row['listing_ref'],*content_refs,pdf_ref]
        available=max(ref['retrieved_at'] for ref in refs)
        if doc.get('available_at')!=available or any(timestamp(ref['retrieved_at'])>timestamp(product['generated_at']) for ref in refs):
            raise ValueError('EASTMONEY_HK_AVAILABILITY_BINDING_INVALID')
        docs_by_code[code].append(doc)
        verified[doc['document_sha256']]=dict(page_count=len(pages),pdf_bytes=len(pdf_raw))
    if any(q.get('status')=='OBSERVED' and q.get('code') not in names for q in product['queries']):
        raise ValueError('EASTMONEY_HK_QUERY_OUTSIDE_MASTER')
    return verified


def refresh_eastmoney_hk(service: Any,date: str,*,issuer_code: str | None=None) -> dict:
    """Explicit bounded mirror read for master-owned HK issuers via same owner/store."""
    from .announcement_source import (CaptureBudget,MAX_EASTMONEY_CONTENT_PAGES,
        MAX_EASTMONEY_TOTAL_RESPONSE_BYTES)
    from .workspace import ATTEMPT_SCHEMA,seal_attempt,validate_attempt
    date=date_token(date)
    root=service.store.root/'workspace_announcements'/date/'eastmoney_hk'
    runroot=service.store.root/'workspace_announcement_runs'/date/'eastmoney_hk'
    with service.store._transaction(date,'workspace-announcements'):
        start=_now();context=plan_context(date,now=timestamp(start))
        names,witness=_master(service,context)
        if issuer_code is not None:
            symbol=canonical_symbol(issuer_code)
            if symbol!=issuer_code or symbol not in names:
                raise ValueError('EASTMONEY_HK_ISSUER_NOT_IN_VERIFIED_MASTER')
            codes=[symbol]
        else:
            codes=sorted(names)[:BATCH_SIZE]
        attempt=dict(schema_version=ATTEMPT_SCHEMA,target_trade_date=date,run_id=uuid4().hex,owner=OWNER,
            state='RUNNING',execution_kind='MANUAL_REFRESH',source_scope=EASTMONEY_SCOPE,
            started_at=start,last_success_at=None,failure_reasons=[],**FLAGS)
        attempt_path=runroot/'latest.json'
        def journal():
            sealed=validate_attempt(seal_attempt(attempt),date)
            service.store._write_atomic(runroot/(attempt['run_id']+'.json'),sealed)
            service.store._write_atomic(attempt_path,sealed)
        journal()
        try:
            provider=service.source_provider
            if service._material_store is None or getattr(provider,'_material_store',None) is not service._material_store:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
            issuers=[dict(code=code,name=names[code]['name']) for code in codes]
            budget=CaptureBudget(seconds=45,
                max_requests=len(issuers)+MAX_DOCUMENTS*(MAX_EASTMONEY_CONTENT_PAGES+1),
                max_response_bytes=MAX_EASTMONEY_TOTAL_RESPONSE_BYTES,interval=0.0)
            batch=provider.collect_eastmoney_hk_batch(context=context,issuers=issuers,
                max_issuers=BATCH_SIZE,max_documents=MAX_DOCUMENTS,
                budget=budget)
            product=dict(schema_version=EASTMONEY_SCHEMA,owner=OWNER,target_trade_date=date,source='EASTMONEY_HK',
                source_scope=batch['source_scope'],
                run_id=uuid4().hex,context=context,identity_witness=witness,scope=codes,
                scope_identity=digest([witness,codes]),queries=batch['queries'],documents=batch['documents'],
                pending_documents=batch['pending_documents'],generated_at=_now(),execution_kind='MANUAL_REFRESH',
                capture_budget=dict(max_seconds=45,max_requests=budget.max_requests,
                    max_response_bytes=budget.max_response_bytes,elapsed_seconds=budget.elapsed_seconds,
                    requests_used=budget.requests,
                    response_bytes_used=budget.response_bytes),
                status='PARTIAL',gaps=['EASTMONEY_LIST_PAGE_NOT_EXHAUSTIVE','HKEX_FIRST_PUBLICATION_NOT_CONFIRMED'],
                success_scope='BOUNDED_EASTMONEY_HK_NOTICE_MIRROR_OBSERVATION_NOT_HKEX_OFFICIAL',**FLAGS)
            product=_seal(product);_validate_eastmoney_product(product,date)
            _check_eastmoney_sources(service,product)
            service.store._write_atomic(root/(product['run_id']+'.json'),product)
            service.store._write_atomic(root/'latest.json',product)
            attempt.update(state='PARTIAL',finished_at=_now(),last_success_at=product['generated_at'],
                input_identity=product['scope_identity'],failure_reasons=product['gaps'],
                input_coverage=dict(master_count=len(names),queried_issuer_count=len(codes),
                    successful_issuer_count=sum(q['status']=='OBSERVED' for q in product['queries']),
                    document_count=len(product['documents']),pending_document_count=len(product['pending_documents']),
                    full_market_exhaustion='NOT_CLAIMED'))
            journal()
        except Exception as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=[safe_reason(exc,'EASTMONEY_HK_OWNER_FAILED')])
            journal()
            raise
    return read(service,date,plan_context(date,now=timestamp(_now())))


def _catalog_attempt_seal(value: Mapping[str,Any]) -> dict:
    out={key:item for key,item in value.items() if key!='sha256'}
    out['sha256']=digest(out)
    return out


def _catalog_attempt_path(service: Any,date: str,publication_date: str,run_id: str) -> Path:
    return (service.store.root/'workspace_announcement_runs'/date/'eastmoney_date_catalog'
            /publication_date/(run_id+'.json'))


def _catalog_product_root(service: Any,date: str,publication_date: str) -> Path:
    return service.store.root/'workspace_announcements'/date/'eastmoney_date_catalog'/publication_date


def _catalog_run_root(service: Any,date: str,publication_date: str) -> Path:
    return service.store.root/'workspace_announcement_runs'/date/'eastmoney_date_catalog'/publication_date


def refresh_eastmoney_date_catalog(service: Any,date: str,publication_date: str,*,resume: bool=False,
        saved_page_refs: Mapping[int,Mapping[str,Any]]|None=None) -> dict:
    """Capture an explicit publication date through the existing shared owner."""
    from .announcement_catalog import (SOURCE_SCOPE,collect_date_scoped_catalog,
        validate_product as validate_catalog_product,verify_product_sources)
    from .announcement_source import safe_reason

    importing_saved_refs=saved_page_refs is not None
    if importing_saved_refs and (resume or not isinstance(saved_page_refs,Mapping)):
        raise ValueError('ANNOUNCEMENT_DATE_CATALOG_SAVED_REFS_INVALID')
    date=date_token(date)
    from .announcement_catalog import _date as catalog_date
    publication_iso=catalog_date(publication_date)
    publication_token=publication_iso.replace('-','')
    product_root=_catalog_product_root(service,date,publication_token)
    run_root=_catalog_run_root(service,date,publication_token)
    latest_path=product_root/'latest.json'
    latest_attempt_path=run_root/'latest.json'
    with service.store._transaction(date,'eastmoney-date-catalog-'+publication_token):
        previous=service.store._read(latest_path)
        if importing_saved_refs and previous is not None:
            raise ValueError('ANNOUNCEMENT_DATE_CATALOG_IMPORT_PRODUCT_EXISTS')
        if resume and previous is None:
            raise ValueError('ANNOUNCEMENT_DATE_CATALOG_RESUME_PRODUCT_MISSING')
        # The explicit-date Eastmoney listing supplies its own 116/H stock
        # identities. A target-date HK security master is optional reference
        # enrichment and must not gate this research catalog or imply Connect
        # eligibility.
        master_names={}
        identity_witness=None
        resume_refs={}
        provider=service.source_provider
        capture_provider=provider
        capture_mode='FRESH'
        if importing_saved_refs:
            # This internal owner entry accepts only references already saved
            # in this same MaterialStore. Passing no provider makes the
            # collector fail closed on absent/bad refs; it cannot fetch or
            # silently fall back to a fresh capture.
            resume_refs=dict(saved_page_refs)
            capture_provider=None
            capture_mode='SAVED_REFERENCE_IMPORT'
        elif previous is not None:
            previous=validate_catalog_product(previous,target_trade_date=date,publication_date=publication_iso)
            # Read and re-derive every previously retained listing page before
            # reusing its references. This is offline and makes no new request.
            verify_product_sources(previous,service._material_store)
            if resume:
                capture_mode='EXPLICIT_RESUME'
                for page in previous['page_receipts']:
                    ref=page.get('source_ref')
                    if ref is not None and page.get('capture_status')=='PASS':
                        resume_refs[page['page_index']]=ref
            else:
                # A stored exact-date source catalog is already bound to its
                # immutable Eastmoney page refs. Reuse it idempotently without
                # comparing it with a later master or recapturing the source.
                return read_date_catalog(service,date,publication_iso)
        if service._material_store is None:
            if importing_saved_refs or capture_provider is not None:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
        if capture_provider is not None and getattr(provider,'_material_store',None) is not service._material_store:
            raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
        run_id=uuid4().hex
        started_at=_now()
        attempt=dict(schema_version='v4.manager_research.eastmoney_hk_date_catalog_attempt.v1',
            owner=OWNER,target_trade_date=date,publication_date=publication_iso,
            source_scope=SOURCE_SCOPE,run_id=run_id,capture_mode=capture_mode,
            state='RUNNING',started_at=started_at,finished_at=None,
            failure_reasons=[],input_coverage={},**FLAGS)
        def journal() -> None:
            sealed=_catalog_attempt_seal(attempt)
            service.store._write_atomic(_catalog_attempt_path(service,date,publication_token,run_id),sealed)
            service.store._write_atomic(latest_attempt_path,sealed)
        journal()
        pages_root=run_root/run_id/'pages'
        def before_page(page_index: int,url: str,reused: bool) -> str:
            marker=dict(schema_version='v4.manager_research.eastmoney_hk_page_attempt.v1',
                owner=OWNER,target_trade_date=date,publication_date=publication_iso,
                source_scope=SOURCE_SCOPE,run_id=run_id,page_index=page_index,
                requested_url=url,disposition='REUSE_EXISTING_REFERENCE' if reused else 'REQUEST_STARTED',
                state='STARTED',started_at=_now(),**FLAGS)
            path=pages_root/f'page-{page_index:04d}.attempt.json'
            service.store._write_atomic(path,marker)
            return str(path.relative_to(service.store.root))
        def after_page(receipt: dict[str,Any]) -> str:
            path=pages_root/f"page-{receipt['page_index']:04d}.json"
            service.store._write_atomic(path,receipt)
            return str(path.relative_to(service.store.root))
        try:
            if capture_provider is not None and getattr(capture_provider,'_material_store',None) is not service._material_store:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
            product=collect_date_scoped_catalog(capture_provider,service._material_store,
                target_trade_date=date,publication_date=publication_iso,
                master_names=master_names,identity_witness=identity_witness,
                resume_refs=resume_refs,run_id=run_id,generated_at=_now(),
                before_page=before_page,after_page=after_page)
            # Bind the execution decision to the immutable product receipt.
            product['capture_mode']=capture_mode
            product=_seal(product)
            product=validate_catalog_product(product,target_trade_date=date,publication_date=publication_iso)
            verify_product_sources(product,service._material_store)
            service.store._write_atomic(product_root/(run_id+'.json'),product)
            service.store._write_atomic(latest_path,product)
            attempt.update(state=product['status'],finished_at=_now(),last_success_at=product['generated_at'],
                input_coverage=dict(total_hits=product['total_hits'],captured_row_count=product['captured_row_count'],
                    unique_art_code_count=product['unique_art_code_count'],captured_page_count=product['captured_page_count'],
                    manager_consumer_row_count=product['manager_consumer_row_count'],
                    manager_matched_master_code_count=len(product['manager_matched_master_codes']),
                    terminal_empty_seen=product['terminal_empty_seen']),
                failure_reasons=product['gaps'])
            journal()
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=[safe_reason(exc,'EASTMONEY_CATALOG_OWNER_FAILED')])
            journal()
            raise
    return read_date_catalog(service,date,publication_iso)


def accept_saved_date_catalog_refs(service: Any,date: str,publication_date: str,
        page_refs: Mapping[int,Mapping[str,Any]]) -> dict:
    """Import already stored listing references via the canonical owner path.

    The caller passes reference objects, never a path. Missing or invalid refs
    produce a persisted PARTIAL owner product and are never fetched here.
    """
    if not isinstance(page_refs,Mapping):
        raise ValueError('ANNOUNCEMENT_DATE_CATALOG_SAVED_REFS_INVALID')
    return refresh_eastmoney_date_catalog(service,date,publication_date,
        saved_page_refs=page_refs)


def _validate_catalog_owner_receipts(service: Any,product: Mapping[str,Any]) -> None:
    target=product['target_trade_date'];publication=product['publication_date'].replace('-','')
    for page in product['page_receipts']:
        page_index=page.get('page_index')
        if type(page_index) is not int:
            raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_INDEX_INVALID')
        for key,kind in (('owner_attempt_path','attempt'),('owner_receipt_path','receipt')):
            relative=page.get(key)
            if not isinstance(relative,str):
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_RECEIPT_MISSING')
            rel_path=Path(relative)
            if rel_path.is_absolute() or '..' in rel_path.parts:
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_PATH_INVALID')
            saved=service.store._read(service.store.root/rel_path)
            if not isinstance(saved,dict):
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_RECEIPT_MISSING')
            expected=dict(target_trade_date=target,publication_date=product['publication_date'],
                source_scope=product['source_scope'],run_id=product['run_id'],page_index=page_index)
            if any(saved.get(field)!=value for field,value in expected.items()):
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_IDENTITY_MISMATCH')
            if kind=='attempt' and (saved.get('requested_url')!=page.get('requested_url')
                    or saved.get('state')!='STARTED'):
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_ATTEMPT_MISMATCH')
            if kind=='receipt' and any(saved.get(field)!=page.get(field) for field in (
                    'requested_url','capture_status','source_ref','row_count','total_hits','contract_issues','error')):
                raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_PAGE_DERIVATION_MISMATCH')


def read_date_catalog(service: Any,date: str,publication_date: str) -> dict:
    """Read and revalidate one stored date catalog without network activity."""
    from .announcement_catalog import (SOURCE_SCOPE,validate_product as validate_catalog_product,
        verify_product_sources,_date as catalog_date)
    from .announcement_source import safe_reason

    target=date_token(date);publication_iso=catalog_date(publication_date)
    publication_token=publication_iso.replace('-','')
    result=dict(schema_version='v4.manager_research.eastmoney_hk_date_catalog_read.v1',
        owner=OWNER,target_trade_date=target,publication_date=publication_iso,
        source_scope=SOURCE_SCOPE,status='NOT_RUN',readback_status='NOT_RUN',catalog=None,
        attempt=None,gaps=[],**FLAGS)
    product_root=_catalog_product_root(service,target,publication_token)
    run_root=_catalog_run_root(service,target,publication_token)
    try:
        product=service.store._read(product_root/'latest.json')
        latest_attempt=service.store._read(run_root/'latest.json')
        if latest_attempt is not None:
            if (latest_attempt.get('schema_version')!='v4.manager_research.eastmoney_hk_date_catalog_attempt.v1'
                    or latest_attempt.get('target_trade_date')!=target
                    or latest_attempt.get('publication_date')!=publication_iso
                    or latest_attempt.get('sha256')!=_catalog_attempt_seal(latest_attempt)['sha256']
                    or any(latest_attempt.get(key) is not item for key,item in FLAGS.items())):
                raise ValueError('ANNOUNCEMENT_CATALOG_ATTEMPT_IDENTITY_INVALID')
            result['attempt']=latest_attempt
        if product is None:
            result['gaps']=['ANNOUNCEMENT_DATE_CATALOG_NOT_RUN']
            return result
        product=validate_catalog_product(product,target_trade_date=target,publication_date=publication_iso)
        if service._material_store is None:
            raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
        verify_product_sources(product,service._material_store)
        _validate_catalog_owner_receipts(service,product)
        owner_attempt=service.store._read(_catalog_attempt_path(service,target,publication_token,product['run_id']))
        if (not isinstance(owner_attempt,dict) or owner_attempt.get('run_id')!=product['run_id']
                or owner_attempt.get('source_scope')!=SOURCE_SCOPE
                or owner_attempt.get('state')!=product.get('status')):
            raise ValueError('ANNOUNCEMENT_CATALOG_OWNER_ATTEMPT_MISMATCH')
        result.update(status=product['status'],readback_status='VERIFIED',catalog=product,
            gaps=product['gaps'],attempt=latest_attempt or owner_attempt,
            readback=dict(source_page_count=len(product['page_receipts']),
                raw_reference_reads=len([page for page in product['page_receipts'] if page.get('source_ref')]),
                derivation='REPARSED_FROM_SHARED_MATERIAL_STORE'))
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result.update(status='READBACK_FAILED',readback_status='FAILED',catalog=None,
            gaps=[safe_reason(exc,'ANNOUNCEMENT_DATE_CATALOG_READBACK_FAILED')])
    return result


def _read_capture_partition(service: Any,date: str,context: Mapping[str,Any] | None=None) -> dict:
    from .workspace import validate_attempt
    date=date_token(date)
    result=dict(status='NOT_RUN',schema_version='v4.manager_research.announcement_review.v1',
        target_trade_date=date,positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],
        coverage={},gaps=[],attempt=None,product_identity=None,query_rejections=[],official_documents=[],
        eastmoney_hk_status='NOT_RUN',eastmoney_hk_documents=[],eastmoney_hk_capture=None,
        eastmoney_hk_attempt=None,eastmoney_hk_gaps=[],**FLAGS)
    try:
        attempt=service.store._read(service.store.root/'workspace_announcement_runs'/date/'latest.json')
        if attempt is not None:result['attempt']=validate_attempt(attempt,date)
        auto=service.store._read(service.store.root/'workspace_announcements'/date/'autorun.json')
        if auto is not None:
            from .announcement_autorun import read_automatic
            result.update(read_automatic(service,date,context,auto))
            product=None
        else:
            if service.store._io.files(f'workspace_announcements/{date}/_auto_commits'):
                raise ValueError('ANNOUNCEMENT_AUTORUN_INDEX_MISSING_WITH_COMMITTED_RUNS')
            product=service.store._read(service.store.root/'workspace_announcements'/date/'latest.json')
        if product is None and auto is None:
            result['gaps']=['ANNOUNCEMENT_NO_COMMITTED_PRODUCT' if result.get('attempt') else 'ANNOUNCEMENT_OWNER_NOT_RUN']
        elif product is not None:
            product=validate_product(product,date);parsed_documents=_check_sources(service,product)
            context=context or plan_context(date,now=timestamp(_now()))
            result.update(project(service,product,context,parsed_documents=parsed_documents))
            if product['context'].get('publication_window_mode')=='HK_CALENDAR_DAY_V1':
                parent_views=[];parent_cache={}
                for parent in _load_daily_parent_products(service,date,product):
                    pages=_check_sources(service,parent,validation_cache=parent_cache)
                    parent_views.append(project(service,parent,context,parsed_documents=pages))
                for key,identity in (('official_documents','event_id'),('positive_observations','proposition_id'),
                                     ('risk_alerts','proposition_id'),('clarifications','proposition_id'),
                                     ('pending_review','event_id')):
                    merged={}
                    _append_unique(merged,result.get(key,[]),identity)
                    for parent_view in parent_views:
                        _append_unique(merged,parent_view.get(key,[]),identity)
                    result[key]=list(merged.values())
                for parent_view in parent_views:
                    result['gaps']=sorted(set(result.get('gaps',[])+parent_view.get('gaps',[])))
                result['capture_runs']=[result.get('product_identity',{})]+[
                    view.get('product_identity',{}) for view in parent_views]
                result['coverage']['retained_parent_product_count']=len(parent_views)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result.update(status='READBACK_FAILED',gaps=[safe_reason(exc,'ANNOUNCEMENT_SOURCE_READBACK_FAILED')],
                      positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],official_documents=[])
    if (result.get('attempt') or {}).get('state') in {'FAILED','RUNNING'}:
        result['previous_product_retained']=bool((result.get('product_identity') or {}).get('consumed'))
        result['status']=result['attempt']['state']
        result['gaps']=sorted(set(result['gaps']+result['attempt']['failure_reasons']))
    east_attempt_path=service.store.root/'workspace_announcement_runs'/date/'eastmoney_hk'/'latest.json'
    east_product_path=service.store.root/'workspace_announcements'/date/'eastmoney_hk'/'latest.json'
    try:
        east_attempt=service.store._read(east_attempt_path)
        if east_attempt is not None:
            from .workspace import validate_attempt
            east_attempt=validate_attempt(east_attempt,date)
            if east_attempt.get('source_scope')!=EASTMONEY_SCOPE:
                raise ValueError('EASTMONEY_HK_ATTEMPT_SCOPE_INVALID')
            result['eastmoney_hk_attempt']=east_attempt
        east_product=service.store._read(east_product_path)
        if east_product is not None:
            east_product=_validate_eastmoney_product(east_product,date)
            _check_eastmoney_sources(service,east_product)
            consumer_context=context or plan_context(date,now=timestamp(_now()))
            selection_rejections=[]
            projected,projection_gaps=_project_eastmoney_hk(east_product,consumer_context,rejection_audit=selection_rejections)
            result['eastmoney_hk_selection_rejections']=selection_rejections
            result['eastmoney_hk_status']='PARTIAL'
            result['eastmoney_hk_documents']=projected
            result['eastmoney_hk_gaps']=sorted(set(east_product.get('gaps',[])+projection_gaps))
            result['eastmoney_hk_capture']=dict(source='EASTMONEY_HK',source_scope=east_product['source_scope'],
                run_id=east_product['run_id'],sha256=east_product['sha256'],generated_at=east_product['generated_at'],
                query_cutoff=east_product['context']['research_cutoff'],
                queried_issuers=east_product['scope'],document_count=len(east_product['documents']),
                source_status=east_product['status'],readback_status='VERIFIED',exhaustive=False,
                capture_budget=east_product.get('capture_budget'),
                hkex_first_publication_verified=False,**FLAGS)
        elif result['eastmoney_hk_attempt'] is not None:
            state=result['eastmoney_hk_attempt']['state']
            result['eastmoney_hk_status']=state if state in {'FAILED','RUNNING'} else 'NOT_RUN'
            result['eastmoney_hk_gaps']=list(result['eastmoney_hk_attempt'].get('failure_reasons',[]))
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result['eastmoney_hk_status']='READBACK_FAILED'
        result['eastmoney_hk_gaps']=[safe_reason(exc,'EASTMONEY_HK_SOURCE_READBACK_FAILED')]
    return result


def _announcement_capture_dates(service: Any,date: str,as_of: datetime) -> list[str]:
    """List only date partitions capable of containing the requested day."""
    start=datetime.strptime(date,'%Y%m%d').date()
    last=min(start+timedelta(days=31),as_of.astimezone(HK).date())
    names=[]
    try:
        with service.store._io.directory('workspace_announcements') as fd:
            for name in os.listdir(fd):
                if not re.fullmatch(r'\d{8}',name):
                    continue
                meta=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISDIR(meta.st_mode):
                    raise ValueError('ANNOUNCEMENT_DATE_PARTITION_NOT_DIRECTORY')
                try:
                    day=datetime.strptime(name,'%Y%m%d').date()
                except ValueError:
                    raise ValueError('ANNOUNCEMENT_DATE_PARTITION_INVALID')
                if start<=day<=last:
                    names.append(name)
    except FileNotFoundError:
        return []
    return sorted(names)


def _products_for_partition(service: Any,date: str) -> list[dict]:
    from .announcement_autorun import _valid_state,_markers,_ordered_products
    root=service.store.root/'workspace_announcements'/date
    state=service.store._read(root/'autorun.json')
    latest=service.store._read(root/'latest.json')
    products=[]
    if state is not None:
        state=_valid_state(state,date)
        if _markers(service,date)!=state['runs']:
            raise ValueError('ANNOUNCEMENT_AUTORUN_COMMIT_SET_MISMATCH')
        products.extend(_ordered_products(service,date,state))
    elif service.store._io.files(f'workspace_announcements/{date}/_auto_commits'):
        raise ValueError('ANNOUNCEMENT_AUTORUN_INDEX_MISSING_WITH_COMMITTED_RUNS')
    if latest is not None:
        latest=validate_product(latest,date)
        if not any(p['run_id']==latest['run_id'] and p['revision']==latest['revision'] for p in products):
            products.append(latest)
    expanded=[];seen=set()
    def add(product: dict) -> None:
        key=(product['run_id'],product['revision'],product['sha256'])
        if key in seen:
            return
        if len(seen)>=MAX_DAILY_PARENT_PRODUCTS:
            raise ValueError('ANNOUNCEMENT_DAILY_HISTORY_BOUND_EXCEEDED')
        for parent in _load_daily_parent_products(service,date,product):
            add(parent)
        seen.add(key);expanded.append(product)
    for product in products:
        add(product)
    return expanded


def _product_covers_publication_day(product: Mapping[str,Any],date: str) -> bool:
    context=product['context'];day_start=datetime.strptime(date,'%Y%m%d').replace(tzinfo=HK)
    day_end=day_start+timedelta(days=1)
    if context.get('publication_window_mode')=='HK_CALENDAR_DAY_V1':
        return (context.get('publication_date')==date
                and timestamp(context.get('publication_window_start'))==day_start
                and (timestamp(context.get('publication_window_end_exclusive')) or day_start)<day_end)
    start=timestamp(context.get('focus_window_start'));cutoff=timestamp(context.get('research_cutoff'))
    return bool(start and cutoff and start<day_end and cutoff>=day_start)


def _daily_projection_context(product: Mapping[str,Any],date: str,now: datetime) -> dict:
    context=deepcopy(dict(product['context']))
    day_start=datetime.strptime(date,'%Y%m%d').replace(tzinfo=HK);day_end=day_start+timedelta(days=1)
    publication_end=min(now.astimezone(HK)+timedelta(microseconds=1),day_end) if now.astimezone(HK).date()==day_start.date() else day_end
    context.update(focus_window_start=day_start.isoformat(),focus_window_basis='HK_CALENDAR_ANNOUNCEMENT_DAY_READBACK',
        research_cutoff=now.astimezone(HK).isoformat(),source_dates=[date],
        publication_window_mode='HK_CALENDAR_DAY_V1',publication_date=date,
        publication_window_start=day_start.isoformat(),publication_window_end_exclusive=publication_end.isoformat(),
        _daily_projection_readonly=True)
    return context


def _capture_projection_context(product: Mapping[str,Any],now: datetime) -> dict:
    context=deepcopy(dict(product['context']))
    context['research_cutoff']=now.astimezone(HK).isoformat()
    context['_daily_projection_readonly']=True
    return context


def _append_unique(target: dict[str,dict],rows: list[dict],key: str) -> None:
    for row in rows:
        identity=row.get(key) or digest(row)
        old=target.get(identity)
        if old is None:
            target[identity]=deepcopy(row)
        elif key=='event_id':
            seen=list(dict.fromkeys(old.get('observed_in_runs',[])+[old.get('capture_run_id'),row.get('capture_run_id')]))
            old['observed_in_runs']=[run for run in seen if run]
            if old.get('body_status')!='BODY_PARSED' and row.get('body_status')=='BODY_PARSED':
                replacement=deepcopy(row);replacement['observed_in_runs']=old['observed_in_runs'];target[identity]=replacement


def _read_daily_projection(service: Any,date: str) -> dict:
    date=date_token(date);now=timestamp(_now())
    result=dict(status='NOT_RUN',schema_version='v4.manager_research.announcement_review.v1',target_trade_date=date,
        daily_publication_date=date,publication_timezone='Asia/Hong_Kong',count_known=False,
        positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],coverage={},gaps=[],
        attempt=None,product_identity=None,query_rejections=[],official_documents=[],capture_runs=[],
        retained_cross_day=dict(counts_by_publication_date={},source_products=[]),
        eastmoney_hk_status='NOT_RUN',eastmoney_hk_documents=[],eastmoney_hk_capture=None,
        eastmoney_hk_attempt=None,eastmoney_hk_gaps=[],**FLAGS)
    if now is None:
        return dict(result,status='READBACK_FAILED',gaps=['ANNOUNCEMENT_DAILY_READ_TIME_INVALID'])
    try:
        # Reject future day selections and validate the native HK calendar while
        # retaining an explicit, non-planning publication interval.
        daily_context=_daily_context(date,now=now)
        from .workspace import validate_attempt
        exact_attempt=service.store._read(service.store.root/'workspace_announcement_runs'/date/'latest.json')
        if exact_attempt is not None:
            result['attempt']=validate_attempt(exact_attempt,date)
        official={};positive={};risks={};clarifications={};pending={};cross_day={}
        sources=[];queries={};all_gaps=set();validation_cache={};product_keys=set()
        for capture_date in _announcement_capture_dates(service,date,now):
            for product in _products_for_partition(service,capture_date):
                key=(product['run_id'],product['revision'],product['sha256'])
                if key in product_keys or not _product_covers_publication_day(product,date):
                    continue
                product_keys.add(key)
                parsed=_check_sources(service,product,validation_cache=validation_cache)
                selected_view=project(service,product,_daily_projection_context(product,date,now),parsed_documents=parsed)
                full_view=project(service,product,_capture_projection_context(product,now),parsed_documents=parsed)
                capture_summary=dict(schema_version=product['schema_version'],owner=product['owner'],
                    capture_trade_date=capture_date,run_id=product['run_id'],revision=product['revision'],
                    sha256=product['sha256'],generated_at=product['generated_at'],
                    query_since=product['context']['focus_window_start'],
                    query_cutoff=product['context']['research_cutoff'],context=deepcopy(product['context']),
                    scope_count=len(product['scope']),scope_identity=product['scope_identity'],
                    identity_witness=deepcopy(product['identity_witness']),
                    observed_for_publication_date=len(selected_view['official_documents']))
                sources.append(capture_summary);result['capture_runs'].append(capture_summary)
                all_gaps.update(selected_view.get('gaps',[]))
                for row in selected_view['official_documents']:
                    row=deepcopy(row);row['capture_trade_date']=capture_date
                    row['source_window_start']=product['context']['focus_window_start']
                    _append_unique(official,[row],'event_id')
                _append_unique(positive,selected_view.get('positive_observations',[]),'proposition_id')
                _append_unique(risks,selected_view.get('risk_alerts',[]),'proposition_id')
                _append_unique(clarifications,selected_view.get('clarifications',[]),'proposition_id')
                _append_unique(pending,selected_view.get('pending_review',[]),'event_id')
                result['query_rejections'].extend(selected_view.get('query_rejections',[]))
                for query in product.get('queries',[]):
                    queries[query['code']]=dict(symbol=query['code'],status=query['status'],
                        reason=query['reason'],query_cutoff=product['context']['research_cutoff'],
                        capture_trade_date=capture_date,capture_run_id=product['run_id'])
                for doc in full_view.get('official_documents',[]):
                    published=timestamp(doc.get('published_at'))
                    if published is not None and published.strftime('%Y%m%d')!=date:
                        identity=doc.get('event_id') or digest(doc)
                        old=cross_day.get(identity)
                        if old is None or (old.get('body_status')!='BODY_PARSED' and doc.get('body_status')=='BODY_PARSED'):
                            cross_day[identity]=dict(event_id=identity,publication_date=published.strftime('%Y%m%d'),
                                capture_trade_date=capture_date,capture_run_id=doc.get('capture_run_id'),
                                capture_revision=doc.get('capture_revision'),document_sha256=doc.get('document_sha256'),
                                body_status=doc.get('body_status'))
        result['official_documents']=list(official.values())
        result['positive_observations']=list(positive.values());result['risk_alerts']=list(risks.values())
        result['clarifications']=list(clarifications.values());result['pending_review']=list(pending.values())
        result['query_rejections']=list({digest(row):row for row in result['query_rejections']}.values())
        counts={}
        for row in cross_day.values():counts[row['publication_date']]=counts.get(row['publication_date'],0)+1
        result['retained_cross_day']=dict(counts_by_publication_date=dict(sorted(counts.items())),
            source_products=sources)
        if sources:
            cutoffs=[timestamp(s['query_cutoff']) for s in sources if timestamp(s['query_cutoff']) is not None]
            queried=sorted(queries)
            observed=sum(q['status']=='OBSERVED' for q in queries.values())
            failed=sorted(code for code,q in queries.items() if q['status']=='FAILED')
            all_gaps.add('OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED')
            if exact_attempt is None:all_gaps.add('DAILY_OWNER_NOT_RUN_FOR_SELECTED_PUBLICATION_DATE')
            result.update(status='PARTIAL',count_known=True,gaps=sorted(all_gaps),product_identity=None,
                coverage=dict(publication_date=date,observed_document_count=len(official),
                    observed_count_is_not_market_total=True,source_coverage_cutoff=max(cutoffs).isoformat() if cutoffs else None,
                    queried_issuer_count=len(queried),queried_issuers=queried,
                    successfully_observed_issuer_count=observed,failed_issuers=failed,
                    pending_document_count=len(pending),
                    directory_exhaustion='UNVERIFIED',all_official_announcements_captured=False,
                    source_products=sources,retained_cross_day_counts=dict(sorted(counts.items())),
                    source_revalidation=dict(raw_reference_reads=validation_cache.get('raw_revalidations',0),
                        pdf_reparses=validation_cache.get('pdf_reparses',0),request_local_only=True)),**FLAGS)
        else:
            result['gaps']=['ANNOUNCEMENT_OWNER_NOT_RUN','DAILY_PUBLICATION_COVERAGE_UNKNOWN']
            result['coverage']=dict(publication_date=date,observed_document_count=None,
                source_coverage_cutoff=None,coverage_status='UNKNOWN',**FLAGS)
        if exact_attempt and exact_attempt['state'] in {'FAILED','RUNNING'}:
            result['gaps']=sorted(set(result['gaps']+exact_attempt['failure_reasons']))
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result.update(status='READBACK_FAILED',count_known=False,
            gaps=[safe_reason(exc,'ANNOUNCEMENT_DAILY_SOURCE_READBACK_FAILED')],official_documents=[],
            positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],coverage={})
    return result


def _read_targeted_scope(service: Any,date: str,scope_id: str,context: Mapping[str,Any] | None=None) -> dict:
    from .workspace import validate_attempt
    date=date_token(date)
    result=dict(status='NOT_RUN',schema_version='v4.manager_research.announcement_review.v1',
        target_trade_date=date,positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],
        coverage=dict(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,all_master_issuers_included=False),
        gaps=[],attempt=None,product_identity=None,query_rejections=[],official_documents=[],
        source_scope='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET',scope_id=scope_id,scope_coverage=None,source_window=None,
        eastmoney_hk_status='NOT_RUN',eastmoney_hk_documents=[],eastmoney_hk_capture=None,
        eastmoney_hk_attempt=None,eastmoney_hk_gaps=[],**FLAGS)
    if re.fullmatch(r'[0-9a-f]{64}',scope_id) is None:
        return dict(result,status='READBACK_FAILED',gaps=['ANNOUNCEMENT_TARGETED_SCOPE_ID_INVALID'])
    attempt_path=service.store.root/'workspace_announcement_runs'/date/'issuer_subsets'/scope_id/'latest.json'
    product_path=service.store.root/'workspace_announcements'/date/'issuer_subsets'/scope_id/'latest.json'
    try:
        attempt=service.store._read(attempt_path)
        if attempt is not None:
            attempt=validate_attempt(attempt,date)
            if (attempt.get('scope_id')!=scope_id
                    or attempt.get('source_scope')!='HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET'):
                raise ValueError('ANNOUNCEMENT_TARGETED_ATTEMPT_SCOPE_MISMATCH')
            result['attempt']=attempt
        product=service.store._read(product_path)
        if product is None:
            result['gaps']=['ANNOUNCEMENT_TARGETED_SCOPE_NOT_RUN']
        else:
            product=validate_product(product,date)
            if (product.get('capture_scope')!=TARGETED_HKEX_SCOPE or product.get('scope_id')!=scope_id):
                raise ValueError('ANNOUNCEMENT_TARGETED_PRODUCT_SCOPE_MISMATCH')
            if attempt is not None:
                attempt_coverage=attempt.get('input_coverage')
                if (not isinstance(attempt_coverage,dict)
                        or attempt_coverage.get('scope_id')!=scope_id
                        or attempt_coverage.get('selected_issuer_codes')!=product['scope']
                        or attempt_coverage.get('max_issuers')!=len(product['scope'])):
                    raise ValueError('ANNOUNCEMENT_TARGETED_ATTEMPT_PRODUCT_COVERAGE_MISMATCH')
            parsed=_check_sources(service,product)
            consumer=context
            if consumer is None:
                consumer,_unused_query=_targeted_hkex_context(date,now=timestamp(_now()))
            if (consumer.get('plan_trade_date')!=date
                    or consumer.get('focus_window_start')!=product['source_window']['start']):
                raise ValueError('ANNOUNCEMENT_TARGETED_CONSUMER_WINDOW_MISMATCH')
            result.update(project(service,product,consumer,parsed_documents=parsed))
            result.update(source_scope=product['source_scope'],scope_id=scope_id,
                source_window=deepcopy(product['source_window']),scope_coverage=deepcopy(product['scope_coverage']))
            result['coverage'].update(scope_type='EXPLICIT_ISSUER_LIST',scope_id=scope_id,
                selected_issuer_codes=deepcopy(product['scope']),selected_issuer_count=len(product['scope']),
                all_master_issuers_included=product['scope_coverage']['all_master_issuers_included'])
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result.update(status='READBACK_FAILED',gaps=[safe_reason(exc,'ANNOUNCEMENT_TARGETED_SOURCE_READBACK_FAILED')],
            positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],official_documents=[])
    if (result.get('attempt') or {}).get('state') in {'FAILED','RUNNING'}:
        result['previous_product_retained']=bool((result.get('product_identity') or {}).get('consumed'))
        result['status']=result['attempt']['state']
        result['gaps']=sorted(set(result['gaps']+result['attempt']['failure_reasons']))
    return result


def read(service: Any,date: str,context: Mapping[str,Any] | None=None,*,scope_id: str | None=None) -> dict:
    """Plan callers retain their original window; the GET owner is day keyed."""
    if scope_id is not None:
        return _read_targeted_scope(service,date,scope_id,context)
    if context is not None:
        return _read_capture_partition(service,date,context)
    return _read_daily_projection(service,date)


def _project_eastmoney_hk(product: Mapping[str,Any],context: Mapping[str,Any], *, rejection_audit: list[dict] | None=None) -> tuple[list[dict],list[str]]:
    from .announcement_source import _eastmoney_display_time
    since,cutoff=window(context)
    capture_date=product['target_trade_date']
    source_dates=context.get('source_dates')
    if context.get('plan_trade_date')!=capture_date and (
            not isinstance(source_dates,list) or len(source_dates)>31 or capture_date not in source_dates
            or capture_date>str(context.get('plan_trade_date') or '')):
        raise ValueError('EASTMONEY_HK_CONSUMER_TARGET_MISMATCH')
    out=[];gaps=[];seen_instances=set()
    def reject(doc,reason):
        gaps.append(reason)
        if rejection_audit is not None:
            rejection_audit.append(dict(symbol=doc.get('code'),name=doc.get('name'),
                art_code=doc.get('row',{}).get('art_code'),title=doc.get('row',{}).get('title'),
                body_sha256=doc.get('body_sha256'),capture_trade_date=capture_date,
                display_time_iso=doc.get('row',{}).get('display_time_iso'),available_at=doc.get('available_at'),reason=reason))
    if timestamp(product['generated_at'])>cutoff:
        return [],['EASTMONEY_HK_CAPTURE_AFTER_CONSUMER_CUTOFF']
    for doc in product['documents']:
        row=doc['row'];displayed=_eastmoney_display_time(row['display_time'])
        available=timestamp(doc['available_at'])
        if displayed<=since or displayed>cutoff:
            reject(doc,'EASTMONEY_HK_DISPLAY_TIME_OUTSIDE_CONSUMER_WINDOW');continue
        if available is None or available>cutoff:
            reject(doc,'EASTMONEY_HK_CAPTURE_AFTER_CONSUMER_CUTOFF');continue
        source_refs=[row['listing_ref'],*doc['content_refs'],doc['pdf_ref']]
        if (row['market_code']!='116' or row['stock_code']!=doc['code'].split('.')[1]
                or row['ann_type']!='H' or doc.get('source')!='EASTMONEY_HK'):
            raise ValueError('EASTMONEY_HK_PROJECTED_IDENTITY_INVALID')
        # Identity is the document instance, not an acquisition or the article alone.
        # Repeat captures are idempotent; issuer/body revisions remain independent.
        event_id=digest([doc['source'],doc['code'],row['art_code'],doc['body_sha256']])
        if event_id in seen_instances:continue
        seen_instances.add(event_id)
        out.append(dict(schema_version='v4.manager_research.eastmoney_hk_document.v2',
            symbol=doc['code'],name=doc['name'],event_id=event_id,
            source='EASTMONEY_HK',source_identity='EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL',
            market_code='116',stock_code=row['stock_code'],ann_type='H',art_code=row['art_code'],
            title=row['title'],notice_date=row['notice_date'],display_time=row['display_time'],
            display_time_iso=row['display_time_iso'],content_notice_date=doc['content_notice_date'],
            content_display_time=doc['content_display_time'],available_at=doc['available_at'],
            retrieved_at=doc['available_at'],source_url=doc['pdf_ref']['request']['url'],
            content_url=doc['content_refs'][0]['request']['url'],document_sha256=doc['document_sha256'],
            pdf_bytes=doc['pdf_bytes'],pdf_page_count=doc['pdf_page_count'],
            full_pdf_stored=True,body_status=doc['body_status'],body_source=doc['body_source'],
            body_text=doc['body_text'],body_sha256=doc['body_sha256'],
            body_pages=[dict(page_index=page['page_index'],text=page['text'],
                text_sha256=page['text_sha256'],source_ref=page['source_ref']) for page in doc['body_pages']],
            content_page_count=doc['content_page_count'],
            pdf_text_extraction_status=doc['pdf_text_extraction_status'],
            source_refs=source_refs,target_trade_date=context['plan_trade_date'],capture_trade_date=capture_date,
            query_cutoff=product['context']['research_cutoff'],
            publication_status='CANNOT_CONFIRM_FIRST_PUBLICATION',hkex_first_publication_verified=False,
            fresh_catalyst_eligible=False,focus_eligible=False,buy_allowed=False,**FLAGS))
    return out,gaps


def project(service: Any,product: Mapping[str,Any],context: Mapping[str,Any],*,parsed_documents: Mapping[str,Any]|None=None) -> dict:
    since,cutoff=window(context)
    query_context=product.get('query_context') or product['context']
    query_cutoff=query_context['research_cutoff']
    if timestamp(product['generated_at'])>cutoff:
        raise ValueError('ANNOUNCEMENT_PRODUCT_AFTER_CONSUMER_CUTOFF')
    if context.get('plan_trade_date')!=product['target_trade_date']:
        raise ValueError('ANNOUNCEMENT_CONSUMER_TARGET_MISMATCH')
    groups={};rejected=[];unread=[];failed=[]
    for q in product['queries']:
        rejected.extend(dict(symbol=q['code'],**x) for x in q['rejected'])
        if q['status']=='FAILED':failed.append(dict(symbol=q['code'],reason=q['reason']))
    for doc in product['documents']:
        row=doc['row'];ref=doc.get('body_ref')
        if not ref or doc['parse_status']!='BODY_PARSED':
            unread.append(dict(symbol=doc['code'],title=row['document_title'],source_url=row['url'],
                reason=doc['reason'] or doc['parse_status'],disposition='PENDING_REVIEW',published_at=row['published_at']))
            continue
        publication=timestamp(row['published_at']);available=timestamp(ref['retrieved_at'])
        if publication is None or available is None or publication>available or available>cutoff or publication>cutoff or not publication_in_window(publication,context):
            rejected.append(dict(symbol=doc['code'],row=row,reason='OUTSIDE_CURRENT_PUBLICATION_OR_AVAILABILITY_WINDOW'));continue
        pages=(parsed_documents[ref['blob_sha256']] if parsed_documents is not None else
               extract_pdf_pages(read_response(service._material_store,ref),max_bytes=MAX_BYTES,
                   max_pages=40,max_text_characters=240000,timeout_seconds=10))
        if not pages:raise ValueError('ANNOUNCEMENT_PREVIOUSLY_PARSED_BODY_NOW_UNREADABLE')
        # Same official bytes for one issuer form one event, all appearances remain.
        group_id=digest([doc['code'],ref['body_sha256']])
        if group_id not in groups:
            claims=classify_pages(pages,symbol=doc['code'],name=doc['name'])
            groups[group_id]=dict(symbol=doc['code'],name=doc['name'],event_id=group_id,
                title=row['document_title'],published_at=row['published_at'],available_at=ref['retrieved_at'],
                retrieved_at=ref['retrieved_at'],document_sha256=ref['body_sha256'],evidence=[],claims=claims,
                connect_eligibility='TARGET_DATE_NOT_CHECKED',captured_at_target=False,**FLAGS)
        groups[group_id]['evidence'].append(dict(source_url=row['url'],published_at=row['published_at'],
            available_at=ref['retrieved_at'],body_ref=ref,directory_ref=doc['directory_ref'],mapping_ref=doc['mapping_ref']))
    official=[]
    for doc in [*product['documents'],*product['pending_documents']]:
        row=doc['row'];ref=doc.get('body_ref');directory=doc['directory_ref']
        published=timestamp(row['published_at']);available=timestamp(directory['retrieved_at'])
        if published is None or available is None or not publication_in_window(published,context) or published > available or available > cutoff:
            continue
        if ref is not None and timestamp(ref['retrieved_at']) > cutoff:
            continue
        official.append(dict(symbol=doc['code'],name=doc['name'],event_id=digest([doc['code'],row['url']]),
            title=row['document_title'],source_url=row['url'],published_at=row['published_at'],
            available_at=directory['retrieved_at'],retrieved_at=(ref or directory)['retrieved_at'],
            body_status=doc.get('parse_status','BODY_UNREAD'),body_reason=doc.get('reason'),
            document_sha256=ref['body_sha256'] if ref else None,
            source_refs=[directory,doc['mapping_ref']]+([ref] if ref else []),
            capture_run_id=product['run_id'],capture_revision=product['revision'],
            query_cutoff=query_cutoff,capture_cutoff=product['context']['research_cutoff'],
            late_acquisition=bool(timestamp((ref or directory)['retrieved_at'])>timestamp(query_cutoff)),
            scope_id=product.get('scope_id'),capture_scope=product.get('capture_scope'),**FLAGS))
    positive=[];risks=[];clarifications=[];pending=unread
    for group in groups.values():
        for claim in group['claims']:
            eid=group['event_id'];pid=digest([eid,claim])
            item={k:v for k,v in group.items() if k!='claims'}
            item.update(proposition_id=pid,evidence_id=eid,support=claim,disposition=claim['disposition'],
                numeric_trigger=None,final_close=None,event_effective_time='NOT_PARSED',
                window_role='PUBLICATION_IN_WINDOW_NOT_EVENT_OCCURRENCE',assertion='OFFICIAL_SOURCE_STATEMENT_NOT_PRICE_PREDICTION')
            if claim['disposition']=='POSITIVE_OBSERVATION':
                item['action']='WATCH_ONLY';item['research_note']='关注本条已披露动作；核对适用范围、后续履约及同期量价，未核前不追；不视为买入推荐。';positive.append(item)
            elif claim['disposition']=='RISK_REVIEW':
                item['action']='WATCH_ONLY';item['research_note']='暂停把同一事件作为正向依据；核对原文影响范围、履约或债务状态及后续更正，不推定持仓或下单。';risks.append(item)
            elif claim['disposition']=='CLARIFICATION':
                item['action']='WATCH_ONLY';item['research_note']='保留否定或未决状态；本条不是已获批、已成交或已完成。只有后续同一事项正式更正后重新审查。';clarifications.append(item)
            else:pending.append(item)
    # Mixed adverse/positive disclosure stays visible; no automatic focus promotion.
    for row in positive:
        row['focus_eligible']=False
        row['related_risk_evidence_ids']=sorted({r['evidence_id'] for r in risks+clarifications if r['symbol']==row['symbol']})
    cutoff_recorded=query_cutoff
    gaps=['OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED','TARGET_DATE_HK_CONNECT_ELIGIBILITY_NOT_CHECKED',
        'CURRENT_FRONTEND_RISK_RENDERING_NOT_VERIFIED']
    if timestamp(cutoff_recorded)<cutoff:gaps.append('SOURCE_QUERY_CUTOFF_PRECEDES_CURRENT_PLAN_CUTOFF')
    if product['context']['focus_window_start']!=context['focus_window_start']:gaps.append('SAVED_SCAN_WINDOW_DIFFERS_FROM_CURRENT_PLAN')
    if failed:gaps.append('ISSUER_QUERY_FAILURES')
    if unread:gaps.append('DOCUMENT_BODY_NOT_PARSED')
    return dict(status='PARTIAL',official_documents=official,positive_observations=positive,risk_alerts=risks,clarifications=clarifications,
        pending_review=pending,query_rejections=rejected,gaps=gaps,
        product_identity=dict(run_id=product['run_id'],revision=product['revision'],sha256=product['sha256'],
            generated_at=product['generated_at'],query_since=query_context['focus_window_start'],query_as_of=cutoff_recorded,
            capture_cutoff=product['context']['research_cutoff'],scope_id=product.get('scope_id'),consumed=True),
        coverage=dict(native_master_count=product.get('master_scope_count',len(product['scope'])),
            selected_issuer_count=len(product['scope']),scope_type=product.get('scope_coverage',{}).get('scope_type','FULL_NATIVE_MASTER'),
            scope_id=product.get('scope_id'),all_master_issuers_included=product.get('scope_coverage',{}).get('all_master_issuers_included',True),
            queried_issuer_count=product['next_index'],
            queried_issuers=product['scope'][:product['next_index']],pending_issuers=product['scope'][product['next_index']:],
            pending_document_count=len(product['pending_documents']),failed_issuers=failed,
            late_acquisition_document_count=sum(1 for doc in [*product['documents'],*product['pending_documents']]
                if timestamp(doc.get('directory_ref',{}).get('retrieved_at'))>timestamp(query_cutoff)),
            observed_document_count=len(product['documents']),event_group_count=len(groups),
            positive_observation_count=len(positive),risk_count=len(risks),clarification_count=len(clarifications),
            directory_exhaustion='UNVERIFIED',all_official_announcements_captured=False,
            can_resume=product['next_index']<len(product['scope']) or bool(product['pending_documents']),natural_run_verified=False))


def read_selection_inputs(service: Any, context: Mapping[str,Any], *, current_review: Mapping[str,Any] | None=None) -> dict:
    """Read the bounded existing capture dates, through original validators only.

    A date on the product remains its capture date. Neither the plan date nor
    the consumer's now is written into original publication/acquisition fields.
    """
    from .announcement_materials import mirror_material, mirror_role, CURRENT_ROLE
    from .workspace_read_control import checkpoint
    dates=context.get('source_dates');target=date_token(context['plan_trade_date'])
    since,cutoff=window(context)
    if (not isinstance(dates,list) or not 1<=len(dates)<=31 or dates!=sorted(set(dates))
            or any(date_token(d)!=d or d>target or d<since.strftime('%Y%m%d')
                   or d>cutoff.strftime('%Y%m%d') for d in dates)):
        raise ValueError('ANNOUNCEMENT_SELECTION_SOURCE_DATES_INVALID')
    materials=[];rejected=[];gaps=[];captures=[];seen=set()
    for day in dates:
        checkpoint()
        try:
            if day==target and current_review is not None:
                cap=current_review.get('eastmoney_hk_capture')
                if not isinstance(cap,Mapping) or cap.get('readback_status')!='VERIFIED':
                    gaps.extend(current_review.get('eastmoney_hk_gaps',[]))
                    continue
                cap={**dict(cap),'target_trade_date':day}
                docs=current_review.get('eastmoney_hk_documents',[])
                rejected.extend(deepcopy(current_review.get('eastmoney_hk_selection_rejections',[])))
                gaps.extend(current_review.get('eastmoney_hk_gaps',[]))
            else:
                path=service.store.root/'workspace_announcements'/day/'eastmoney_hk'/'latest.json'
                product=service.store._read(path)
                if product is None:continue
                product=_validate_eastmoney_product(product,day)
                _check_eastmoney_sources(service,product)
                docs,projection_gaps=_project_eastmoney_hk(product,context,rejection_audit=rejected)
                gaps.extend([*product.get('gaps',[]),*projection_gaps])
                cap=dict(source='EASTMONEY_HK',target_trade_date=day,readback_status='VERIFIED',
                    sha256=product['sha256'],run_id=product['run_id'],generated_at=product['generated_at'],
                    product_ref=f'workspace_announcements/{day}/eastmoney_hk/latest.json',
                    exhaustive=False)
            captures.append(deepcopy(cap))
            for doc in docs:
                checkpoint()
                try:
                    m=mirror_material(doc,cap)
                    role=mirror_role(m,since,cutoff)
                    if role!=CURRENT_ROLE:raise ValueError('ANNOUNCEMENT_SELECTION_'+role)
                    identity=(m['document_issuer_symbol'],m['art_code'],m['body_sha256'])
                    if identity in seen:continue
                    seen.add(identity)
                    if len(materials)>=128:raise ValueError('ANNOUNCEMENT_SELECTION_DOCUMENT_BUDGET')
                    materials.append(m)
                except (ValueError,TypeError,KeyError) as exc:
                    rejected.append(dict(symbol=doc.get('symbol'),name=doc.get('name'),art_code=doc.get('art_code'),
                        body_sha256=doc.get('body_sha256'),reason=safe_reason(exc,'ANNOUNCEMENT_SELECTION_ADMISSION_FAILED')))
        except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
            reason=safe_reason(exc,'ANNOUNCEMENT_SELECTION_OWNER_READBACK_FAILED')
            gaps.append(reason)
            rejected.append(dict(capture_trade_date=day,reason=reason,source='EASTMONEY_HK'))
    reviewed_analysis = read_reviewed_analysis_references(service, context)
    if not captures and not gaps:
        gaps.append('ANNOUNCEMENT_SELECTION_NO_VERIFIED_CAPTURE_IN_WINDOW')
    return dict(materials=materials,rejections=rejected,gaps=sorted(set(gaps)),captures=captures,
        status=('CANNOT_CONFIRM' if gaps==['ANNOUNCEMENT_SELECTION_NO_VERIFIED_CAPTURE_IN_WINDOW']
                else 'PARTIAL' if gaps else 'READY' if materials else 'READY_EMPTY'),
        reviewed_analysis=reviewed_analysis,
        analysis_gaps=deepcopy(reviewed_analysis.get('gaps', [])),
        input_identity=digest([[(c.get('target_trade_date'),c.get('run_id'),c.get('sha256')) for c in captures],
            [(m['material_id'],m['body_sha256']) for m in materials],rejected,
            reviewed_analysis.get('input_identity')]),**FLAGS)


_AGENT_JUDGMENT_SCHEMA = 'v4.manager_research.announcement_agent_judgment.v1'
_OWNER_ANALYSIS_IMPORT_SCHEMA = 'v4.manager_research.announcement_analysis_owner_import.v1'


def _signed_digest(value: Mapping[str, Any], key: str = 'sha256') -> bool:
    unsigned = {name: item for name, item in value.items() if name != key}
    return value.get(key) == digest(unsigned)


def validate_agent_judgment_receipt(receipt: Any, product: Mapping[str, Any]) -> dict[str, Any]:
    """Validate human/agent review lineage without inferring missing decisions."""
    if not isinstance(receipt, Mapping) or receipt.get('schema_version') != _AGENT_JUDGMENT_SCHEMA:
        raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID')
    manifest = product.get('source_manifest')
    if not isinstance(manifest, Mapping):
        raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_SOURCE_MANIFEST_MISSING')
    status = receipt.get('decision_status')
    extension = product.get('stock_selection')
    if status == 'NOT_ASSESSED':
        if extension is not None or receipt.get('article_decision_count') != 0 or receipt.get('decision_payload_sha256') is not None:
            raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_UNASSESSED_BINDING_INVALID')
    elif status == 'EXPLICIT_DISPOSITIONS':
        decisions = extension.get('article_decisions') if isinstance(extension, Mapping) else None
        if (not isinstance(decisions, list) or len(decisions) != receipt.get('article_decision_count')
                or receipt.get('decision_payload_sha256') != digest(decisions)):
            raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_DECISION_BINDING_INVALID')
    else:
        raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_DECISION_STATUS_INVALID')
    reviewed_at = timestamp(receipt.get('reviewed_at'))
    if (receipt.get('status') != 'VERIFIED'
            or receipt.get('target_trade_date') != product.get('target_trade_date')
            or receipt.get('publication_date') != product.get('publication_date')
            or receipt.get('semantic_catalog_sha256') != manifest.get('semantic_catalog_sha256')
            or receipt.get('body_corpus_sha256') != manifest.get('body_corpus_sha256')
            or receipt.get('catalog_product_sha256') != manifest.get('catalog_product_sha256')
            or not all(isinstance(receipt.get(key), str) and receipt[key].strip()
                       for key in ('parent_task_id', 'parent_run_id', 'reviewer_identity'))
            or receipt.get('evidence_binding_status') != 'OUTPUT_BOUND'
            or receipt.get('external_review_status') != 'DECLARED'
            or receipt.get('reader_identity') == receipt.get('reviewer_identity')
            or not all(isinstance(receipt.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', receipt.get(key, ''))
                       for key in ('agent_output_sha256', 'reader_output_sha256', 'reviewer_output_sha256',
                                   'source_run_sha256', 'semantic_catalog_sha256', 'body_corpus_sha256'))
            or not isinstance(receipt.get('evidence_run_id'), str)
            or re.fullmatch(r'[0-9a-f]{32}', receipt.get('evidence_run_id', '')) is None
            or receipt.get('reviewer_conclusion') != 'PASS'
            or receipt.get('reviewer_decision_payload_sha256') != receipt.get('decision_payload_sha256')
            or (status == 'EXPLICIT_DISPOSITIONS' and receipt.get('reviewer_decision_payload_sha256') != digest(extension.get('article_decisions', [])))
            or reviewed_at is None
            or any(receipt.get(key) is not expected for key, expected in FLAGS.items())
            or not _signed_digest(receipt)):
        raise ValueError('ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID')
    return deepcopy(dict(receipt))


_HANDOFF_FILES = ('catalog_read.json', 'body_corpus.json', 'body_corpus_manifest.json',
    'body_batch_receipt.json', 'capture_receipt.json', 'semantic_catalog.json',
    'reader_output.json', 'reviewer_output.json', 'article_decisions.json', 'analysis_product.json')


def _handoff_root(store: Any, run_id: str) -> Path:
    if not isinstance(run_id, str) or re.fullmatch(r'[0-9a-f]{32}', run_id) is None:
        raise ValueError('ANNOUNCEMENT_AGENT_EVIDENCE_RUN_ID_INVALID')
    root = Path(store.root).expanduser().resolve(strict=True)
    path = root / 'announcement_agent_runs' / run_id / 'evidence'
    cursor = root
    for part in ('announcement_agent_runs', run_id, 'evidence'):
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError('ANNOUNCEMENT_AGENT_EVIDENCE_SYMLINK_REJECTED')
    if not path.exists() or not path.is_dir() or path.resolve(strict=True).parent.parent.parent != root:
        raise ValueError('ANNOUNCEMENT_AGENT_EVIDENCE_ROOT_MISSING')
    return path


def validate_terminal_body_capture(evidence: Path, catalog_read: Mapping[str, Any],
                                   target: str, publication: str,
                                   *, expected_run_id: str | None = None) -> dict[str, Any]:
    """Validate a full, exact article terminal set, including recorded failures.

    A PARTIAL batch is usable only when every catalog article has one terminal
    complete or failed receipt and every failed receipt is bound to its saved
    original artifact bytes. This function never repairs or retries capture.
    """
    from .announcement_analysis import (
        _assert_catalog_readback, _publication_date, _verify_body_source_rows,
    )

    target = date_token(target)
    publication = _publication_date(publication)
    evidence = Path(evidence)
    catalog = _assert_catalog_readback(catalog_read, target, publication)
    if expected_run_id is not None and evidence.parent.name != expected_run_id:
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_RUN_ID_MISMATCH')
    catalog_path = evidence / 'catalog_read.json'
    body_path = evidence / 'body_corpus.json'
    body_manifest_path = evidence / 'body_corpus_manifest.json'
    batch_path = evidence / 'body_batch_receipt.json'
    capture_path = evidence / 'capture_receipt.json'
    required = (catalog_path, body_path, body_manifest_path, batch_path, capture_path)
    if any(path.is_symlink() or not path.is_file() for path in required):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTIFACT_MISSING')
    catalog_sha = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest()
    body_manifest_sha = hashlib.sha256(body_manifest_path.read_bytes()).hexdigest()
    batch_sha = hashlib.sha256(batch_path.read_bytes()).hexdigest()
    capture_sha = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    try:
        stored_catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        body = json.loads(body_path.read_text(encoding='utf-8'))
        body_manifest = json.loads(body_manifest_path.read_text(encoding='utf-8'))
        batch = json.loads(batch_path.read_text(encoding='utf-8'))
        capture = json.loads(capture_path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_JSON_INVALID') from exc
    catalog_product = catalog_read.get('catalog')
    capture_run_id = capture.get('evidence_run_id') if isinstance(capture, Mapping) else None
    if (not isinstance(capture_run_id, str)
            or re.fullmatch(r'[0-9a-f]{32}', capture_run_id) is None
            or (expected_run_id is not None and capture_run_id != expected_run_id)
            or (expected_run_id is None
                and re.fullmatch(r'[0-9a-f]{32}', evidence.parent.name or '') is not None
                and capture_run_id != evidence.parent.name)):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_RUN_ID_MISMATCH')
    if (stored_catalog != catalog_read
            or not isinstance(catalog_product, Mapping)
            or catalog_product.get('run_id') != catalog.get('run_id')
            or catalog_product.get('sha256') != catalog.get('sha256')):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_CATALOG_READBACK_INVALID')

    listing_rows = catalog.get('manager_consumer_rows')
    body_rows = body.get('rows') if isinstance(body, Mapping) else None
    article_receipts = body_manifest.get('article_receipts') if isinstance(body_manifest, Mapping) else None
    if (not isinstance(listing_rows, list) or not listing_rows
            or not isinstance(body_rows, list) or not isinstance(article_receipts, list)
            or len(listing_rows) != len(body_rows) or len(listing_rows) != len(article_receipts)):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_SET_INCOMPLETE')
    article_ids = [row.get('art_code') if isinstance(row, Mapping) else None for row in listing_rows]
    body_ids = [row.get('art_code') if isinstance(row, Mapping) else None for row in body_rows]
    receipt_ids = [row.get('art_code') if isinstance(row, Mapping) else None for row in article_receipts]
    if (any(not isinstance(code, str) or not code for code in article_ids)
            or len(set(article_ids)) != len(article_ids)
            or body_ids != article_ids or receipt_ids != article_ids):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_SET_MISMATCH')
    input_identity_material = {
        'target_trade_date': target,
        'publication_date': publication,
        'catalog_run_id': catalog.get('run_id'),
        'catalog_sha256': catalog.get('sha256'),
        'article_ids': article_ids,
        'listing_body_sha256s': [row.get('raw_body_sha256') for row in listing_rows],
    }
    input_identity = hashlib.sha256((json.dumps(input_identity_material, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')).hexdigest()
    if (any(not isinstance(row.get('raw_body_sha256'), str)
                or re.fullmatch(r'[0-9a-f]{64}', row.get('raw_body_sha256', '')) is None
                for row in listing_rows)
            or not isinstance(body_manifest, Mapping)
            or body_manifest.get('schema') != 'v4.manager_research.source_bound_announcement_body_corpus.v1'
            or body_manifest.get('target_trade_date') != target
            or body_manifest.get('publication_date') != publication
            or body_manifest.get('catalog_run_id') != catalog.get('run_id')
            or body_manifest.get('catalog_sha256') != catalog.get('sha256')
            or body_manifest.get('input_identity_sha256') != input_identity
            or not isinstance(batch, Mapping)
            or batch.get('schema') != 'v4.manager_research.announcement_body_batch_receipt.v1'
            or batch.get('target_trade_date') != target
            or batch.get('publication_date') != publication
            or batch.get('catalog_run_id') != catalog.get('run_id')
            or batch.get('catalog_sha256') != catalog.get('sha256')
            or batch.get('input_identity_sha256') != input_identity
            or batch.get('article_rows') != len(article_ids)
            or batch.get('terminal_article_receipts') != len(article_ids)
            or batch.get('body_corpus') != 'body_corpus.json'
            or batch.get('body_corpus_manifest') != 'body_corpus_manifest.json'
            or batch.get('body_corpus_sha256') != body_sha
            or batch.get('body_corpus_manifest_sha256') != body_manifest_sha
            or not isinstance(body, Mapping)
            or body.get('schema') != 'v4.manager_research.eastmoney_hk_announcement_body_corpus.v3'
            or body.get('target_notice_date') != publication
            or body.get('article_count') != len(article_ids)
            or body.get('input_identity_sha256') != input_identity
            or body.get('source_manifest_sha256') != body_manifest_sha
            or body.get('transport_complete_body_count') != sum(
                row.get('body_status') == 'COMPLETE_CONTENT_API_BODY' for row in body_rows)):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_RECEIPT_BINDING_INVALID')

    listing_by_id = {row['art_code']: row for row in listing_rows}
    body_by_id = {row['art_code']: row for row in body_rows}
    body_root = evidence / 'body_batch'
    if body_root.is_symlink() or not body_root.is_dir():
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTIFACT_ROOT_INVALID')
    bodies_dir = body_root / 'bodies'
    if bodies_dir.is_symlink() or not bodies_dir.is_dir():
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTIFACT_ROOT_INVALID')
    expected_body_files = {f'{code}.json' for code in article_ids}
    actual_body_files = {path.name for path in bodies_dir.iterdir()}
    if actual_body_files != expected_body_files:
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_ARTIFACT_SET_MISMATCH')
    counts: dict[str, int] = {}
    failures: dict[str, dict[str, str]] = {}
    for receipt in article_receipts:
        code = receipt.get('art_code')
        status = receipt.get('body_status')
        if status not in {'COMPLETE_CONTENT_API_BODY', 'BODY_CAPTURE_FAILED'}:
            raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_NONTERMINAL_STATUS')
        counts[status] = counts.get(status, 0) + 1
        listing = listing_by_id[code]
        body_row = body_by_id[code]
        relative = receipt.get('body_path')
        if (relative != f'bodies/{code}.json'
                or not isinstance(receipt.get('body_file_sha256'), str)
                or re.fullmatch(r'[0-9a-f]{64}', receipt.get('body_file_sha256', '')) is None):
            raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_PATH_INVALID')
        artifact = body_root / relative
        if (bodies_dir.is_symlink() or artifact.is_symlink() or not artifact.is_file()
                or artifact.resolve(strict=True).parent != bodies_dir.resolve(strict=True)):
            raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_ARTIFACT_MISSING')
        raw_artifact = artifact.read_bytes()
        artifact_sha = hashlib.sha256(raw_artifact).hexdigest()
        try:
            original = json.loads(raw_artifact.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_ARTIFACT_INVALID') from exc
        if (artifact_sha != receipt.get('body_file_sha256')
                or body_row.get('capture_receipt_sha256') != artifact_sha
                or receipt.get('status') != status
                or receipt.get('listing_raw_body_sha256') != listing.get('raw_body_sha256')
                or receipt.get('listing_source_ref') != listing.get('source_ref')
                or receipt.get('source_issuer_codes') != listing.get('source_issuer_codes')
                or original.get('schema') != 'v4.manager_research.source_bound_announcement_body.v1'
                or original.get('art_code') != code
                or original.get('target_trade_date') != target
                or original.get('publication_date') != publication
                or original.get('body_status') != status
                or original.get('listing_raw_body_sha256') != listing.get('raw_body_sha256')
                or original.get('listing_source_ref') != listing.get('source_ref')
                or original.get('source_issuer_codes') != listing.get('source_issuer_codes')
                or body_row.get('body_status') != status
                or body_row.get('title') != listing.get('title')):
            raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_SOURCE_BINDING_INVALID')
        if status == 'BODY_CAPTURE_FAILED':
            error_code = receipt.get('error_code')
            if (not isinstance(error_code, str) or not error_code.strip()
                    or receipt.get('content_api_pages_captured') != 0
                    or body_row.get('pages') != []
                    or body_row.get('content_page_count') is not None
                    or body_row.get('body_text') is not None
                    or body_row.get('body_text_sha256') is not None
                    or body_row.get('pdf_sha256') is not None
                    or body_row.get('transport_body_status') != status
                    or body_row.get('transport_semantic_status') != 'NOT_REVIEWED'
                    or body_row.get('transport_pit_status') != 'CANNOT_CONFIRM'
                    or body_row.get('transport_first_hkex_publication_time') != 'CANNOT_CONFIRM'
                    or original.get('body_text') is not None
                    or original.get('body_text_sha256') is not None
                    or original.get('content_api_pages') != []
                    or original.get('pdf') is not None
                    or original.get('semantic_status') != 'NOT_REVIEWED'
                    or original.get('original_point_in_time_availability') != 'CANNOT_CONFIRM'
                    or original.get('first_hkex_publication_time') != 'CANNOT_CONFIRM'):
                raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_FAILURE_RECEIPT_INVALID')
            failures[code] = {'error_code': error_code.strip(), 'receipt_sha256': artifact_sha}
        else:
            if (receipt.get('error_code') is not None
                    or not isinstance(body_row.get('pages'), list) or not body_row.get('pages')
                    or type(body_row.get('content_page_count')) is not int
                    or body_row.get('content_page_count') < 1
                    or receipt.get('content_api_pages_captured') != body_row.get('content_page_count')
                    or not isinstance(body_row.get('body_text_sha256'), str)
                    or original.get('body_text_sha256') != body_row.get('body_text_sha256')
                    or not isinstance(original.get('content_api_pages'), list)
                    or len(original.get('content_api_pages')) != receipt.get('content_api_pages_captured')
                    or not isinstance(original.get('body_text'), str)
                    or hashlib.sha256(original['body_text'].encode('utf-8')).hexdigest() != original.get('body_text_sha256')):
                raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_COMPLETE_RECEIPT_INVALID')
            _verify_body_source_rows(body_row, code, publication)

    clean_counts = {key: value for key, value in counts.items() if value}
    batch_status = batch.get('status')
    if (body_manifest.get('body_status_counts') != clean_counts
            or batch.get('body_status_counts') != clean_counts
            or (failures and batch_status != 'PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS')
            or (not failures and batch_status != 'PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS')
            or capture.get('schema_version') != 'v4.manager_research.announcement_daily_capture.v1'
            or capture.get('status') != batch_status
            or capture.get('target_trade_date') != target
            or capture.get('publication_date') != publication
            or capture.get('catalog_run_id') != catalog.get('run_id')
            or capture.get('catalog_product_sha256') != catalog.get('sha256')
            or capture.get('catalog_read_file_sha256') != catalog_sha
            or capture.get('body_corpus_file_sha256') != body_sha
            or capture.get('body_corpus_manifest_file_sha256') != body_manifest_sha
            or capture.get('body_batch_receipt_sha256') != batch_sha
            or any(capture.get(key) is not expected for key, expected in FLAGS.items())):
        raise ValueError('ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_STATUS_OR_COUNTS_INVALID')
    return {
        'schema_version': 'v4.manager_research.announcement_terminal_body_capture.v1',
        'status': batch_status, 'input_identity_sha256': input_identity,
        'article_count': len(article_ids), 'body_status_counts': clean_counts,
        'body_corpus_sha256': body_sha, 'body_corpus_manifest_sha256': body_manifest_sha,
        'body_batch_receipt_sha256': batch_sha, 'capture_receipt_sha256': capture_sha,
        'failed_articles': [
            {'art_code': code, **failures[code]} for code in article_ids if code in failures
        ],
    }


def validate_registered_handoff(store: Any, run_id: str, manifest_sha256: str,
                                product_sha256: str, product: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify fixed-path reader/reviewer bytes and bind them to an imported product.

    This proves byte identity and declared review lineage, not platform identity
    authentication or a cryptographic reviewer signature.
    """
    if not re.fullmatch(r'[0-9a-f]{64}', str(manifest_sha256)) or not re.fullmatch(r'[0-9a-f]{64}', str(product_sha256)):
        raise ValueError('ANNOUNCEMENT_AGENT_EVIDENCE_SHA_INVALID')
    evidence = _handoff_root(store, run_id)
    manifest_path = evidence / 'handoff_manifest.v1.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_MANIFEST_MISSING')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    unsigned = {key: value for key, value in manifest.items() if key != 'sha256'}
    if (manifest.get('schema_version') != 'v4.manager_research.announcement_agent_handoff.v1'
            or manifest.get('evidence_run_id') != run_id
            or digest(unsigned) != manifest.get('sha256')
            or manifest.get('sha256') != manifest_sha256):
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_MANIFEST_INVALID')
    files = manifest.get('files')
    required_files = set(_HANDOFF_FILES) - ({'article_decisions.json'} if manifest.get('decision_status') == 'NOT_ASSESSED' else set())
    if not isinstance(files, Mapping) or not required_files.issubset(files):
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_FILE_MAP_INVALID')
    paths = {}
    for name in _HANDOFF_FILES:
        if name == 'article_decisions.json' and files.get(name) is None:
            continue
        path = evidence / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_OUTPUT_MISSING')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != files.get(name):
            raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_OUTPUT_SHA_MISMATCH')
        paths[name] = path
    loaded = json.loads(paths['analysis_product.json'].read_text(encoding='utf-8'))
    chosen = dict(product) if isinstance(product, Mapping) else loaded
    if (loaded.get('sha256') != product_sha256 or chosen.get('sha256') != product_sha256
            or digest({key: value for key, value in loaded.items() if key != 'sha256'}) != product_sha256
            or chosen != loaded or manifest.get('product_sha256') != product_sha256):
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_PRODUCT_SHA_MISMATCH')
    receipt = validate_agent_judgment_receipt(chosen.get('agent_judgment_receipt'), chosen)
    reviewer = json.loads(paths['reviewer_output.json'].read_text(encoding='utf-8'))
    decision_document = json.loads(paths['article_decisions.json'].read_text(encoding='utf-8')) if files.get('article_decisions.json') else None
    if isinstance(decision_document, Mapping):
        if set(decision_document) != {'article_decisions'}:
            raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_DECISIONS_INVALID')
        decisions = decision_document.get('article_decisions')
    else:
        decisions = decision_document
    if decisions is not None and not isinstance(decisions, list):
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_DECISIONS_INVALID')
    expected_decision_sha = digest(decisions) if decisions is not None else None
    catalog = json.loads(paths['catalog_read.json'].read_text(encoding='utf-8'))
    body = json.loads(paths['body_corpus.json'].read_text(encoding='utf-8'))
    capture = json.loads(paths['capture_receipt.json'].read_text(encoding='utf-8'))
    body_manifest = json.loads(paths['body_corpus_manifest.json'].read_text(encoding='utf-8'))
    batch_receipt = json.loads(paths['body_batch_receipt.json'].read_text(encoding='utf-8'))
    semantic = json.loads(paths['semantic_catalog.json'].read_text(encoding='utf-8'))
    reader = json.loads(paths['reader_output.json'].read_text(encoding='utf-8'))
    body_target = body.get('target_trade_date')
    body_publication = body.get('publication_date') or body.get('target_notice_date')
    if isinstance(body_publication, str) and len(body_publication) == 8 and body_publication.isdigit():
        body_publication = body_publication[:4] + '-' + body_publication[4:6] + '-' + body_publication[6:8]
    terminal_capture = validate_terminal_body_capture(evidence, catalog,
        chosen.get('target_trade_date'), chosen.get('publication_date'), expected_run_id=run_id)
    if (receipt.get('evidence_run_id') != run_id
            or receipt.get('reader_output_sha256') != files.get('reader_output.json')
            or receipt.get('reviewer_output_sha256') != files.get('reviewer_output.json')
            or receipt.get('source_run_id') != catalog.get('catalog', {}).get('run_id')
            or receipt.get('source_run_sha256') != catalog.get('catalog', {}).get('sha256')
            or receipt.get('catalog_product_sha256') != catalog.get('catalog', {}).get('sha256')
            or receipt.get('semantic_catalog_sha256') != files.get('semantic_catalog.json')
            or receipt.get('body_corpus_sha256') != files.get('body_corpus.json')
            or reader != semantic
            or manifest.get('catalog_product_sha256') != catalog.get('catalog', {}).get('sha256')
            or manifest.get('source_run_id') != catalog.get('catalog', {}).get('run_id')
            or manifest.get('source_run_sha256') != catalog.get('catalog', {}).get('sha256')
            or capture.get('evidence_run_id') != run_id
            or capture.get('target_trade_date') != chosen.get('target_trade_date')
            or capture.get('publication_date') != chosen.get('publication_date')
            or capture.get('status') != terminal_capture.get('status')
            or capture.get('catalog_product_sha256') != catalog.get('catalog', {}).get('sha256')
            or capture.get('catalog_read_file_sha256') != files.get('catalog_read.json')
            or capture.get('body_corpus_file_sha256') != files.get('body_corpus.json')
            or capture.get('body_corpus_manifest_file_sha256') != files.get('body_corpus_manifest.json')
            or capture.get('body_batch_receipt_sha256') != files.get('body_batch_receipt.json')
            or body_manifest.get('target_trade_date') != chosen.get('target_trade_date')
            or body_manifest.get('publication_date') != chosen.get('publication_date')
            or body_manifest.get('catalog_run_id') != catalog.get('catalog', {}).get('run_id')
            or body_manifest.get('catalog_sha256') != catalog.get('catalog', {}).get('sha256')
            or body_manifest.get('body_status_counts') != terminal_capture.get('body_status_counts')
            or batch_receipt.get('status') != terminal_capture.get('status')
            or batch_receipt.get('article_rows') != catalog.get('catalog', {}).get('manager_consumer_row_count')
            or batch_receipt.get('target_trade_date') != chosen.get('target_trade_date')
            or batch_receipt.get('publication_date') != chosen.get('publication_date')
            or batch_receipt.get('catalog_run_id') != catalog.get('catalog', {}).get('run_id')
            or batch_receipt.get('catalog_sha256') != catalog.get('catalog', {}).get('sha256')
            or batch_receipt.get('body_corpus_sha256') != files.get('body_corpus.json')
            or batch_receipt.get('body_corpus_manifest_sha256') != files.get('body_corpus_manifest.json')
            or manifest.get('body_corpus_sha256') != files.get('body_corpus.json')
            or manifest.get('semantic_catalog_sha256') != files.get('semantic_catalog.json')
            or manifest.get('target_trade_date') != chosen.get('target_trade_date')
            or manifest.get('publication_date') != chosen.get('publication_date')
            or catalog.get('target_trade_date') != chosen.get('target_trade_date')
            or catalog.get('publication_date') != chosen.get('publication_date')
            or body_target not in {None, chosen.get('target_trade_date')}
            or body_publication != chosen.get('publication_date')
            or semantic.get('target_trade_date') not in {None, chosen.get('target_trade_date')}
            or semantic.get('publication_date') not in {None, chosen.get('publication_date')}
            or manifest.get('decision_status') != receipt.get('decision_status')
            or manifest.get('decision_payload_sha256') != expected_decision_sha
            or ((terminal_capture.get('failed_articles')
                 or chosen.get('source_manifest', {}).get('terminal_body_capture') is not None)
                and chosen.get('source_manifest', {}).get('terminal_body_capture') != terminal_capture)
            or reviewer.get('review_conclusion') != 'PASS'
            or reviewer.get('decision_status') != receipt.get('decision_status')
            or reviewer.get('reviewed_at') != receipt.get('reviewed_at')
            or manifest.get('reviewed_at') != receipt.get('reviewed_at')
            or reviewer.get('target_trade_date') != chosen.get('target_trade_date')
            or reviewer.get('publication_date') != chosen.get('publication_date')
            or reviewer.get('evidence_run_id') != run_id
            or reviewer.get('decision_payload_sha256') != expected_decision_sha
            or receipt.get('decision_payload_sha256') != expected_decision_sha
            or reviewer.get('reader_identity') != receipt.get('reader_identity')
            or reviewer.get('reviewer_identity') != receipt.get('reviewer_identity')
            or manifest.get('reader_identity') != receipt.get('reader_identity')
            or manifest.get('reviewer_identity') != receipt.get('reviewer_identity')
            or reviewer.get('catalog_product_sha256') != receipt.get('catalog_product_sha256')
            or reviewer.get('semantic_catalog_sha256') != receipt.get('semantic_catalog_sha256')
            or reviewer.get('body_corpus_sha256') != receipt.get('body_corpus_sha256')
            or reviewer.get('reader_identity') == reviewer.get('reviewer_identity')):
        raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_REVIEW_BINDING_INVALID')
    from .announcement_analysis import validate_product as validate_analysis_product
    validate_analysis_product(chosen, target_trade_date=chosen.get('target_trade_date'),
        publication_date=chosen.get('publication_date'), catalog=catalog.get('catalog'))
    # Apply the existing consumer's source-time requirement before owner
    # import can publish a receipt. Missing acquisition times are not zero.
    _source_times, source_times_complete = _analysis_time_refs(chosen)
    if not source_times_complete:
        raise ValueError('ANNOUNCEMENT_ANALYSIS_SOURCE_OR_REVIEW_TIME_MISSING')
    return {'evidence_root': evidence, 'manifest': manifest, 'product': chosen, 'receipt': receipt}


def validate_owner_analysis_import_receipt(receipt: Any, product: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or receipt.get('schema_version') != _OWNER_ANALYSIS_IMPORT_SCHEMA:
        raise ValueError('ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_INVALID')
    available_at = timestamp(receipt.get('available_at'))
    if (receipt.get('status') != 'VERIFIED'
            or receipt.get('target_trade_date') != product.get('target_trade_date')
            or receipt.get('publication_date') != product.get('publication_date')
            or receipt.get('product_sha256') != product.get('sha256')
            or not all(isinstance(receipt.get(key), str) and receipt[key].strip()
                       for key in ('parent_task_id', 'parent_run_id'))
            or receipt.get('owner') != 'ManagerResearchJobService.import_announcement_analysis'
            or available_at is None
            or any(receipt.get(key) is not expected for key, expected in FLAGS.items())
            or not _signed_digest(receipt)):
        raise ValueError('ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_BINDING_INVALID')
    judgment = product.get('agent_judgment_receipt')
    if isinstance(judgment, Mapping) and (
            receipt.get('parent_task_id') != judgment.get('parent_task_id')
            or receipt.get('parent_run_id') != judgment.get('parent_run_id')):
        raise ValueError('ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_PARENT_BINDING_INVALID')
    # Existing v1 receipts remain byte-for-byte readable. New imports bind the
    # four extra identities as a complete group; GET never upgrades old files.
    binding_keys = {'source_manifest_sha256', 'evidence_run_id',
                    'handoff_manifest_sha256', 'agent_judgment_receipt_sha256'}
    if binding_keys.intersection(receipt):
        if (not binding_keys.issubset(receipt)
                or not isinstance(judgment, Mapping)
                or receipt.get('source_manifest_sha256') != product.get('source_manifest_sha256')
                or receipt.get('evidence_run_id') != judgment.get('evidence_run_id')
                or receipt.get('agent_judgment_receipt_sha256') != judgment.get('sha256')
                or re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('handoff_manifest_sha256'))) is None):
            raise ValueError('ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID')
    return deepcopy(dict(receipt))


def _analysis_time_refs(product: Mapping[str, Any]) -> tuple[list[datetime], bool]:
    records = product.get('records')
    if not isinstance(records, list) or not records:
        return [], False
    times: list[datetime] = []
    complete = True
    for record in records:
        listing = record.get('listing_source') if isinstance(record, Mapping) else None
        listing_ref = listing.get('source_ref') if isinstance(listing, Mapping) else None
        listing_time = timestamp(listing_ref.get('retrieved_at')) if isinstance(listing_ref, Mapping) else None
        if listing_time is None:
            complete = False
        else:
            times.append(listing_time)
        citations = record.get('body_page_citations') if isinstance(record, Mapping) else None
        body_times = []
        if isinstance(citations, list):
            for citation in citations:
                source_ref = citation.get('source_ref') if isinstance(citation, Mapping) else None
                acquired = timestamp(source_ref.get('retrieved_at')) if isinstance(source_ref, Mapping) else None
                if acquired is not None:
                    body_times.append(acquired)
                elif isinstance(source_ref, Mapping):
                    complete = False
        if (not body_times and record.get('analysis_kind') != 'TEXT_INSUFFICIENT_UNASSESSED'
                and record.get('body_status') not in {'TEXT_INSUFFICIENT_UNASSESSED', 'BODY_MISSING'}):
            complete = False
        times.extend(body_times)
    return times, complete


def _analysis_pairs(context: Mapping[str, Any]) -> list[tuple[str, str]]:
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState
    dates = context.get('source_dates')
    plan_target = date_token(context.get('plan_trade_date'))
    publication = context.get('announcement_publication_date')
    if publication is not None:
        from .announcement_analysis import _publication_date
        return [(plan_target, _publication_date(publication))]
    if not isinstance(dates, list):
        raise ValueError('ANNOUNCEMENT_ANALYSIS_PLAN_SOURCE_DATES_INVALID')
    calendar = load_market_calendar()
    # Evening plans target the next HK session, which is not yet in the
    # completed source-date window. Include the same default pair as the
    # analysis API/date binding, then retain older pairs as separate checks.
    from .announcement_analysis import previous_hk_session
    default_publication = previous_hk_session(plan_target)
    pairs: list[tuple[str, str]] = [(plan_target,
        datetime.strptime(default_publication, '%Y%m%d').strftime('%Y-%m-%d'))]
    for run_day in dates:
        day = date_token(run_day)
        day_state = resolve_market_states(calendar, day)['hk_securities']
        if day_state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            target = day
        else:
            cursor = datetime.strptime(day, '%Y%m%d').date() + timedelta(days=1)
            target = None
            while cursor.year == calendar.year:
                candidate = cursor.strftime('%Y%m%d')
                state = resolve_market_states(calendar, candidate)['hk_securities']
                if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
                    target = candidate
                    break
                cursor += timedelta(days=1)
            if target is None:
                raise ValueError('ANNOUNCEMENT_ANALYSIS_NEXT_SESSION_OUTSIDE_CALENDAR')
        publication = (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        if target <= plan_target:
            pairs.append((target, publication))
    return sorted(set(pairs))


def read_analysis_consumption(service: Any, target_trade_date: str, publication_date: str,
                              *, cutoff: str | None = None,
                              analysis_readback: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one exact imported product through the same API/plan read contract.

    This is a read only projection. In particular, a legacy product may remain
    readable by the R3 analysis API while its missing judgment prevents plan
    consumption. Observed identities survive rejection so that a failed older
    pair cannot be confused with the current product.
    """
    from .announcement_analysis import _publication_date, product_path
    target = date_token(target_trade_date)
    publication = _publication_date(publication_date)
    item = dict(schema_version='v4.manager_research.announcement_analysis_consumption.v1',
        target_trade_date=target, publication_date=publication,
        status='NOT_IMPORTED', validation_status='NOT_IMPORTED', consumed=False,
        product_sha256=None, source_manifest_sha256=None, catalog_product_sha256=None,
        source_run_id=None, evidence_run_id=None, handoff_manifest_sha256=None,
        agent_judgment_receipt_sha256=None, owner_import_receipt_sha256=None,
        owner_handoff_binding_status='NOT_VERIFIED', decision_status=None,
        selection_status='NOT_ASSESSED', stock_count=None, selected_stock_count=None,
        conditional_watch_count=None, not_selected_stock_count=None,
        not_assessed_stock_count=None, reviewed_at=None, owner_available_at=None,
        latest_source_or_review_at=None, plan_cutoff=cutoff,
        cutoff_status='NOT_REQUESTED' if cutoff is None else 'NOT_EVALUATED',
        failure_stage=None, gaps=[], research_references=[], **FLAGS)
    stage = 'PRODUCT_READ'
    try:
        path = product_path(service.store, target, publication)
        product = service.store._read(path)
        if product is None:
            item.update(gaps=['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED'])
            return item
        if not isinstance(product, Mapping):
            raise ValueError('ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID')
        manifest = product.get('source_manifest')
        manifest = manifest if isinstance(manifest, Mapping) else {}
        judgment = product.get('agent_judgment_receipt')
        judgment = judgment if isinstance(judgment, Mapping) else {}
        item.update(product_sha256=product.get('sha256'),
            source_manifest_sha256=product.get('source_manifest_sha256'),
            catalog_product_sha256=manifest.get('catalog_product_sha256'),
            source_run_id=manifest.get('catalog_run_id'),
            evidence_run_id=judgment.get('evidence_run_id'),
            agent_judgment_receipt_sha256=judgment.get('sha256'))
        stage = 'SOURCE_READBACK'
        readback = (analysis_readback if analysis_readback is not None
                    else service.get_announcement_analysis(target, publication))
        analysis = readback.get('analysis') if isinstance(readback, Mapping) else None
        if (not isinstance(analysis, Mapping) or analysis.get('status') != 'VERIFIED'
                or analysis.get('product_sha256') != product.get('sha256')):
            raise ValueError('ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_INVALID')
        if (product.get('target_trade_date') != target
                or product.get('publication_date') != publication
                or readback.get('target_trade_date') != target
                or readback.get('publication_date') != publication
                or analysis.get('source_manifest_sha256') != product.get('source_manifest_sha256')
                or readback.get('source_catalog', {}).get('catalog_product_sha256') != manifest.get('catalog_product_sha256')):
            raise ValueError('ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_INVALID')
        stage = 'JUDGMENT_RECEIPT'
        agent_receipt = validate_agent_judgment_receipt(product.get('agent_judgment_receipt'), product)
        item.update(decision_status=agent_receipt['decision_status'], reviewed_at=agent_receipt['reviewed_at'])
        stage = 'OWNER_IMPORT_RECEIPT'
        owner_raw = service.store._read(path.with_name('owner_import_receipt.v1.json'))
        if isinstance(owner_raw, Mapping):
            item.update(owner_import_receipt_sha256=owner_raw.get('sha256'),
                owner_available_at=owner_raw.get('available_at'),
                handoff_manifest_sha256=owner_raw.get('handoff_manifest_sha256'))
        owner_receipt = validate_owner_analysis_import_receipt(owner_raw, product)
        stage = 'HANDOFF_MANIFEST'
        manifest_path = _handoff_root(service.store, agent_receipt['evidence_run_id']) / 'handoff_manifest.v1.json'
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError('ANNOUNCEMENT_AGENT_HANDOFF_MANIFEST_MISSING')
        handoff_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        expected_manifest_sha = owner_receipt.get('handoff_manifest_sha256') or handoff_manifest.get('sha256')
        item['handoff_manifest_sha256'] = expected_manifest_sha
        stage = 'REGISTERED_HANDOFF'
        validate_registered_handoff(service.store, agent_receipt['evidence_run_id'],
            expected_manifest_sha, product.get('sha256'), product)
        item['owner_handoff_binding_status'] = (
            'PRODUCT_PARENT_HANDOFF_BOUND' if 'handoff_manifest_sha256' in owner_receipt
            else 'LEGACY_PRODUCT_PARENT_ONLY_CURRENT_HANDOFF_VERIFIED')
        stage = 'SOURCE_TIME'
        times, sources_complete = _analysis_time_refs(product)
        review_time = timestamp(agent_receipt.get('reviewed_at'))
        import_time = timestamp(owner_receipt.get('available_at'))
        if not sources_complete or review_time is None or import_time is None:
            raise ValueError('ANNOUNCEMENT_ANALYSIS_SOURCE_OR_REVIEW_TIME_MISSING')
        latest = max([*times, review_time, import_time])
        item.update(validation_status='VERIFIED', latest_source_or_review_at=latest.isoformat(), status='VERIFIED')
        selection = None
        if agent_receipt['decision_status'] == 'EXPLICIT_DISPOSITIONS':
            from .announcement_selection import read_projection
            selection = read_projection(product)
            item.update(selection_status=selection.get('status'), stock_count=selection.get('stock_count'),
                selected_stock_count=selection.get('selected_stock_count'),
                conditional_watch_count=selection.get('conditional_watch_count'),
                not_selected_stock_count=selection.get('not_selected_stock_count'),
                not_assessed_stock_count=selection.get('not_assessed_stock_count'))
        stage = 'CUTOFF'
        if cutoff is not None:
            cutoff_time = timestamp(cutoff)
            if cutoff_time is None:
                raise ValueError('ANNOUNCEMENT_ANALYSIS_PLAN_CUTOFF_INVALID')
            if latest > cutoff_time:
                item.update(status='NOT_CONSUMED_AFTER_CUTOFF', cutoff_status='AFTER_CUTOFF',
                    failure_stage=stage, gaps=['ANNOUNCEMENT_ANALYSIS_NOT_AVAILABLE_AT_PLAN_CUTOFF'])
                return item
            item.update(status='CONSUMED', consumed=True, cutoff_status='SATISFIED')
        if selection is not None and item['consumed']:
            for stock in selection.get('stocks', []):
                if stock.get('status') not in {'SELECTED', 'CONDITIONAL_WATCH'}:
                    continue
                item['research_references'].append(dict(
                    stock_code=stock.get('stock_code'), stock_name=stock.get('stock_name'),
                    research_status=stock.get('status'), target_trade_date=target, publication_date=publication,
                    product_sha256=product['sha256'], source_manifest_sha256=product['source_manifest_sha256'],
                    evidence_run_id=item['evidence_run_id'], handoff_manifest_sha256=expected_manifest_sha,
                    owner_import_receipt_sha256=item['owner_import_receipt_sha256'],
                    reviewed_at=item['reviewed_at'], owner_available_at=item['owner_available_at'],
                    selection_reasons=deepcopy(stock.get('selection_reasons', [])),
                    risk_notes=deepcopy(stock.get('risk_notes', [])),
                    article_refs=[{key: deepcopy(article.get(key)) for key in (
                        'art_code', 'title', 'disposition', 'reason', 'risk_notes',
                        'factual_summary', 'source_sha256')}
                        for article in stock.get('articles', [])
                        if article.get('disposition') in {'SELECTED_EVENT', 'SELECTED_PERFORMANCE', 'CONDITIONAL_WATCH'}],
                    point_in_time_status=manifest.get('point_in_time_status'),
                    connect_eligibility_status=manifest.get('connect_eligibility_status'), **FLAGS))
        return item
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        detail = str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', str(exc) or '') else type(exc).__name__
        item.update(status='NOT_CONSUMED_INVALID', validation_status='CANNOT_CONFIRM',
            consumed=False, failure_stage=stage, gaps=[detail], research_references=[])
        return item


def read_reviewed_analysis_references(service: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Consume each valid pair independently and retain exact rejected identities."""
    cutoff = context.get('research_cutoff')
    if timestamp(cutoff) is None:
        return dict(status='CANNOT_CONFIRM', products=[], research_references=[],
            consumed_product_sha256s=[], gaps=['ANNOUNCEMENT_ANALYSIS_PLAN_CUTOFF_INVALID'],
            input_identity=digest([]), **FLAGS)
    products = []
    references = []
    gaps = []
    consumed = []
    explicit_pair = context.get('announcement_publication_date') is not None
    for target, publication in _analysis_pairs(context):
        item = read_analysis_consumption(service, target, publication, cutoff=cutoff)
        if item['status'] == 'NOT_IMPORTED' and not explicit_pair:
            continue
        products.append(item)
        if item['consumed']:
            consumed.append(item['product_sha256'])
            references.extend(item['research_references'])
        else:
            gaps.extend('ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:' + gap for gap in item['gaps'])
    if not products:
        gaps.append('ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED_IN_PLAN_WINDOW')
    incomplete = any(item['status'] != 'CONSUMED' for item in products)
    invalid = any(item['status'] == 'NOT_CONSUMED_INVALID' for item in products)
    status = ('PARTIAL' if consumed and incomplete else 'CANNOT_CONFIRM' if invalid
              else 'PARTIAL' if gaps or incomplete else 'READY' if references else 'READY_EMPTY')
    return dict(status=status, plan_cutoff=cutoff, products=products,
        research_references=references, gaps=sorted(set(gaps)), consumed_product_sha256s=consumed,
        input_identity=digest(consumed), **FLAGS)
