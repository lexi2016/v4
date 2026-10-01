"""Stage-independent increments owned by ManagerResearchJobService.

New writes use the original store transaction/atomic publication and the same
HKEX provider and MaterialStore. GET reparses recorded directory/PDF bytes;
there is no collection, cache repair, historical timestamp backfill or order.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .announcement_source import (read_response,query_request,directory_entries,
    classify_pages,extract_pdf_pages,safe_reason,MAX_BYTES,MAX_DOCUMENTS,PARSER_VERSION,window)
from .workspace_projection import FLAGS, date_token,digest,timestamp,canonical_symbol
from .workspace_plan import plan_context

SCHEMA='v4.manager_research.announcement_scan.v2'
OWNER='ManagerResearchJobService.refresh_announcements'
BATCH_SIZE=3
EASTMONEY_SCHEMA='v4.manager_research.eastmoney_hk_announcement_batch.v2'
EASTMONEY_SCOPE='EASTMONEY_HK'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


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
    if (not isinstance(codes,list) or not codes or codes!=sorted(set(codes))
            or any(canonical_symbol(c)!=c for c in codes)
            or type(index) is not int or not 0<=index<=len(codes)
            or not isinstance(value.get('queries'),list) or not isinstance(value.get('documents'),list)
            or not isinstance(value.get('pending_documents'),list)
            or value.get('scope_identity')!=digest([value['identity_witness'],codes])
            or not isinstance(value.get('scan_order',codes),list)
            or sorted(value.get('scan_order',codes))!=codes
            or [r.get('code') for r in value['queries']]!=value.get('scan_order',codes)[:index]):
        raise ValueError('ANNOUNCEMENT_PRODUCT_SCOPE_OR_CURSOR_INVALID')
    window(value['context'])
    if value['context'].get('plan_trade_date')!=date or timestamp(value['context']['research_cutoff'])>timestamp(value['generated_at']):
        raise ValueError('ANNOUNCEMENT_PRODUCT_TIME_INVALID')
    return deepcopy(dict(value))


def _check_sources(service: Any, product: Mapping[str,Any], *, validation_cache: dict | None=None) -> dict:
    """Verify the original owner identity plus every retained source binding."""
    from .hkex_provider import ACTIVE_STOCK_LIST_URL
    from .eastmoney_run_history import read_retained_response as read_eastmoney_response
    import json
    names,witness=_master(service,product['context'])
    if witness!=product['identity_witness'] or sorted(names)!=product['scope']:
        raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_CHANGED')
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
        since,as_of=window(product['context'])
        if mapping_ref['request']!=dict(url=ACTIVE_STOCK_LIST_URL,method='GET',
                context=dict(since=since.isoformat(),as_of=as_of.isoformat())) or mapping_ref['http_status']!=200:
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
            request=query_request(q['official_issuer'],product['context'])
            if q['prime_ref']['request']!=dict(url=request['referer'],method='GET',context=request['context'],cache_policy='SESSION_PRIME'):
                raise ValueError('ANNOUNCEMENT_QUERY_PRIME_MISMATCH')
        if q.get('directory_ref'):
            ref=q['directory_ref'];raw=checked(ref)
            if ref['request']!=query_request(q['official_issuer'],product['context']):
                raise ValueError('ANNOUNCEMENT_QUERY_WINDOW_OR_ISSUER_MISMATCH')
            if q['status']=='OBSERVED':
                entries,rejected,reason=directory_entries(raw,q['code'],product['context'])
                if (entries!=q['entries'] or rejected!=q['rejected'] or reason!=q['reason']
                        or not 200<=ref['http_status']<300):
                    raise ValueError('ANNOUNCEMENT_DIRECTORY_DERIVATION_MISMATCH')
            elif 200<=ref['http_status']<300:
                try:
                    directory_entries(raw,q['code'],product['context'])
                except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
                    if q['reason']!=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED'):
                        raise ValueError('ANNOUNCEMENT_FAILED_QUERY_REASON_MISMATCH') from exc
                else:
                    raise ValueError('ANNOUNCEMENT_FAILED_QUERY_HAS_DERIVABLE_DIRECTORY')
            elif q['reason']!='ANNOUNCEMENT_DIRECTORY_HTTP_FAILED':
                raise ValueError('ANNOUNCEMENT_FAILED_QUERY_REASON_MISMATCH')
        elif q['status']=='OBSERVED':
            raise ValueError('ANNOUNCEMENT_DIRECTORY_RAW_MISSING')
        elif q.get('official_issuer'):
            request=query_request(q['official_issuer'],product['context'])
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
                cache['pdf_reparses']=cache.get('pdf_reparses',0)+1
                try:
                    parsed_documents[ref['blob_sha256']]=extract_pdf_pages(raw,max_bytes=MAX_BYTES,
                        max_pages=40,max_text_characters=240000,timeout_seconds=10)
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
            source_scope: str | None=None, issuer_code: str | None=None) -> dict:
    if source_scope is not None:
        if source_scope != EASTMONEY_SCOPE or resume or schedule is not None:
            raise ValueError('ANNOUNCEMENT_SOURCE_SCOPE_INVALID')
        return refresh_eastmoney_hk(service,date,issuer_code=issuer_code)
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
                product=validate_product(previous,date);_check_sources(service,product)
                if product['next_index']==len(product['scope']) and not product['pending_documents']:
                    raise ValueError('ANNOUNCEMENT_SCAN_DRAINED_START_NEW_CURRENT_WINDOW')
                # Scope/window are immutable throughout this manual scan session.
                names,witness=_master(service,product['context'])
                product['revision']+=1
            else:
                context=plan_context(date,now=timestamp(attempt['started_at']))
                names,witness=_master(service,context)
                codes=sorted(names)
                product=dict(schema_version=SCHEMA,owner=OWNER,target_trade_date=date,run_id=uuid4().hex,
                    revision=1,context=context,identity_witness=witness,scope=codes,
                    scope_identity=digest([witness,codes]),next_index=0,queries=[],documents=[],pending_documents=[],**FLAGS)
            start=product['next_index']
            stop=start if product['pending_documents'] else min(len(product['scope']),start+BATCH_SIZE)
            issuers=[dict(code=c,name=names[c]['name']) for c in product['scope'][start:stop]]
            batch=service.source_provider.collect_announcement_batch(context=product['context'],issuers=issuers,
                pending_documents=product['pending_documents'])
            product['queries'].extend(batch['queries']);product['documents'].extend(batch['documents'])
            product.update(next_index=stop,pending_documents=batch['pending_documents'],generated_at=_now(),
                parser_revision=PARSER_VERSION,execution_kind='MANUAL_REFRESH',natural_run_verified=False)
            product=_seal(product);validate_product(product,date);_check_sources(service,product)
            service.store._write_atomic(root/product['run_id']/(str(product['revision'])+'.json'),product)
            service.store._write_atomic(root/'latest.json',product)
            from .announcement_autorun import retain_manual_product
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
        return read(service,date,plan_context(date,now=timestamp(_now())))


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
        _eastmoney_display_time,MAX_BYTES,
        MAX_EASTMONEY_CONTENT_PAGES,MAX_EASTMONEY_BODY_CHARACTERS)
    from .eastmoney_run_history import read_retained_response as read_eastmoney_response
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
        from .eastmoney_run_history import (committed_products,next_sweep,
            retain_index_observations,PROTOCOL,MAX_RUNS)
        previous,history_rejections,history_gaps=committed_products(service,date)
        if len(previous)>=MAX_RUNS:raise ValueError('EASTMONEY_HK_HISTORY_RUN_BUDGET')
        # Preserve still-verifiable legacy index metadata BEFORE force-fetch.
        if service._material_store is None:
            raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
        sweep=None
        if issuer_code is not None:
            symbol=canonical_symbol(issuer_code)
            if symbol!=issuer_code or symbol not in names:
                raise ValueError('EASTMONEY_HK_ISSUER_NOT_IN_VERIFIED_MASTER')
            codes=[symbol]
        else:
            codes,sweep=next_sweep(previous,names,witness,BATCH_SIZE)
        retention_products=list(previous)
        for capture_date in context.get('source_dates',[]):
            if capture_date==date:continue
            older,_,missing=committed_products(service,capture_date)
            retention_products.extend(older);history_gaps.extend(missing)
        retention_gaps=retain_index_observations(service._material_store,
            [p for p in retention_products if set(p['scope']).intersection(codes)])
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
            # The provider can stop at its existing request/time budget. Keep
            # unrequested issuers explicit rather than imply a successful scan.
            queried={q['code'] for q in batch['queries']}
            for code in codes:
                if code not in queried:
                    batch['queries'].append(dict(code=code,name=names[code]['name'],status='FAILED',
                        listing_ref=None,entries=[],reason='EASTMONEY_HK_NOT_REQUESTED_BUDGET'))
            batch['queries'].sort(key=lambda q:q['code'])
            if sweep is not None:
                sweep['successful_query_count']+=sum(q['status']=='OBSERVED' for q in batch['queries'])
                sweep['failed_query_count']+=sum(q['status']!='OBSERVED' for q in batch['queries'])
                sweep['visited_issuer_count']+=sum(isinstance(q.get('listing_ref'),Mapping) for q in batch['queries'])
                sweep['all_issuers_visited']=sweep['visited_issuer_count']==len(names)
                sweep['all_issuer_queries_succeeded']=sweep['successful_query_count']==len(names)
            product=dict(schema_version=EASTMONEY_SCHEMA,owner=OWNER,target_trade_date=date,source='EASTMONEY_HK',
                source_scope=batch['source_scope'],
                run_id=uuid4().hex,attempt_run_id=attempt['run_id'],commit_protocol=PROTOCOL,
                sweep=sweep,context=context,identity_witness=witness,scope=codes,
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
            retention=retain_index_observations(service._material_store,[product])
            if retention:raise ValueError('EASTMONEY_HK_CURRENT_INDEX_RETENTION_FAILED')
            attempt.update(state='PARTIAL',finished_at=_now(),last_success_at=product['generated_at'],
                input_identity=product['scope_identity'],product_run_id=product['run_id'],
                product_sha256=product['sha256'],failure_reasons=sorted(set(
                    product['gaps']+history_gaps+retention_gaps)),
                input_coverage=dict(master_count=len(names),queried_issuer_count=len(codes),
                    successful_issuer_count=sum(q['status']=='OBSERVED' for q in product['queries']),
                    document_count=len(product['documents']),pending_document_count=len(product['pending_documents']),
                    full_market_exhaustion='NOT_CLAIMED'))
            journal()
            # Named immutable product is the commit point, written LAST.
            # Latest alone cannot expose an unfinished new-protocol run.
            service.store._write_atomic(root/'latest.json',product)
            from .contracts import canonical_json
            service.store._io.write_bytes(str((root/(product['run_id']+'.json')).relative_to(service.store.root)),
                canonical_json(product),require_absent=True)
        except Exception as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=[safe_reason(exc,'EASTMONEY_HK_OWNER_FAILED')])
            journal()
            raise
    return read(service,date,plan_context(date,now=timestamp(_now())))


def read(service: Any,date: str,context: Mapping[str,Any] | None=None) -> dict:
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
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result.update(status='READBACK_FAILED',gaps=[safe_reason(exc,'ANNOUNCEMENT_SOURCE_READBACK_FAILED')],
                      positive_observations=[],risk_alerts=[],clarifications=[],pending_review=[],official_documents=[])
    if (result.get('attempt') or {}).get('state') in {'FAILED','RUNNING'}:
        result['previous_product_retained']=bool((result.get('product_identity') or {}).get('consumed'))
        result['status']=result['attempt']['state']
        result['gaps']=sorted(set(result['gaps']+result['attempt']['failure_reasons']))
    from .eastmoney_run_history import read_history
    try:
        history=read_history(service,date,context or plan_context(date,now=timestamp(_now())))
        result.update(eastmoney_hk_attempt=history['attempt'],
            eastmoney_hk_captures=history['captures'],eastmoney_hk_coverage=history['coverage'],
            eastmoney_hk_capture=(history['captures'][-1] if history['captures'] else None),
            eastmoney_hk_documents=[row['document'] for row in history['documents']],
            eastmoney_hk_selection_rejections=history['rejections'],eastmoney_hk_gaps=history['gaps'])
        if history['captures']:result['eastmoney_hk_status']='PARTIAL'
        elif history['attempt'] and history['attempt']['state'] in {'FAILED','RUNNING'}:
            result['eastmoney_hk_status']=history['attempt']['state']
        elif history['gaps']:result['eastmoney_hk_status']='READBACK_FAILED'
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
        result['eastmoney_hk_status']='READBACK_FAILED'
        result['eastmoney_hk_gaps']=[safe_reason(exc,'EASTMONEY_HK_SOURCE_READBACK_FAILED')]
    return result


def _project_eastmoney_hk(product: Mapping[str,Any],context: Mapping[str,Any], *, rejection_audit: list[dict] | None=None) -> tuple[list[dict],list[str]]:
    from .announcement_source import _eastmoney_display_time
    since,cutoff=window(context)
    capture_date=product['target_trade_date']
    source_dates=context.get('source_dates')
    if context.get('plan_trade_date')!=capture_date and (
            not isinstance(source_dates,list) or len(source_dates)>31 or capture_date not in source_dates
            or capture_date>str(context.get('plan_trade_date') or '')):
        raise ValueError('EASTMONEY_HK_CONSUMER_TARGET_MISMATCH')
    out=[];gaps=[]
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
        out.append(dict(schema_version='v4.manager_research.eastmoney_hk_document.v2',
            # Stable document instance: repeat captures share ID; issuer/body revisions do not.
            symbol=doc['code'],name=doc['name'],
            event_id=digest([doc['source'],doc['code'],row['art_code'],doc['body_sha256']]),
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
        if publication is None or available is None or publication>available or available>cutoff or publication>cutoff or publication<=since:
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
        if published is None or available is None or not since < published <= cutoff or published > available or available > cutoff:
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
            query_cutoff=product['context']['research_cutoff'],**FLAGS))
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
    cutoff_recorded=product['context']['research_cutoff']
    gaps=['OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED','TARGET_DATE_HK_CONNECT_ELIGIBILITY_NOT_CHECKED',
        'CURRENT_FRONTEND_RISK_RENDERING_NOT_VERIFIED']
    if timestamp(cutoff_recorded)<cutoff:gaps.append('SOURCE_QUERY_CUTOFF_PRECEDES_CURRENT_PLAN_CUTOFF')
    if product['context']['focus_window_start']!=context['focus_window_start']:gaps.append('SAVED_SCAN_WINDOW_DIFFERS_FROM_CURRENT_PLAN')
    if failed:gaps.append('ISSUER_QUERY_FAILURES')
    if unread:gaps.append('DOCUMENT_BODY_NOT_PARSED')
    return dict(status='PARTIAL',official_documents=official,positive_observations=positive,risk_alerts=risks,clarifications=clarifications,
        pending_review=pending,query_rejections=rejected,gaps=gaps,
        product_identity=dict(run_id=product['run_id'],revision=product['revision'],sha256=product['sha256'],
            generated_at=product['generated_at'],query_since=product['context']['focus_window_start'],query_as_of=cutoff_recorded,
            consumer_cutoff=context['research_cutoff'],consumed=True),
        coverage=dict(native_master_count=len(product['scope']),queried_issuer_count=product['next_index'],
            queried_issuers=product['scope'][:product['next_index']],pending_issuers=product['scope'][product['next_index']:],
            pending_document_count=len(product['pending_documents']),failed_issuers=failed,
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
    materials=[];rejected=[];gaps=[];captures=[];seen={}
    for day in dates:
        checkpoint()
        try:
            # Read all committed runs even when a caller supplies an older
            # latest-only projection. GET never fetches or migrates history.
            from .eastmoney_run_history import read_history
            history=read_history(service,day,context)
            captures.extend(deepcopy(history['captures']))
            rejected.extend(history['rejections']);gaps.extend(history['gaps'])
            for row in history['documents']:
                doc=row['document'];cap=row['capture']
                checkpoint()
                try:
                    m=mirror_material(doc,cap)
                    role=mirror_role(m,since,cutoff)
                    if role!=CURRENT_ROLE:raise ValueError('ANNOUNCEMENT_SELECTION_'+role)
                    identity=(m['document_issuer_symbol'],m['art_code'],m['body_sha256'])
                    if identity in seen:
                        materials[seen[identity]]['capture_occurrences'].extend(deepcopy(row['occurrences']))
                        continue
                    if len(materials)>=128:raise ValueError('ANNOUNCEMENT_SELECTION_DOCUMENT_BUDGET')
                    seen[identity]=len(materials)
                    m['capture_occurrences']=deepcopy(row['occurrences'])
                    materials.append(m)
                except (ValueError,TypeError,KeyError) as exc:
                    rejected.append(dict(symbol=doc.get('symbol'),name=doc.get('name'),art_code=doc.get('art_code'),
                        body_sha256=doc.get('body_sha256'),reason=safe_reason(exc,'ANNOUNCEMENT_SELECTION_ADMISSION_FAILED')))
        except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError) as exc:
            reason=safe_reason(exc,'ANNOUNCEMENT_SELECTION_OWNER_READBACK_FAILED')
            gaps.append(reason)
            rejected.append(dict(capture_trade_date=day,reason=reason,source='EASTMONEY_HK'))
    if not captures and not gaps:
        gaps.append('ANNOUNCEMENT_SELECTION_NO_VERIFIED_CAPTURE_IN_WINDOW')
    return dict(materials=materials,rejections=rejected,gaps=sorted(set(gaps)),captures=captures,
        status=('CANNOT_CONFIRM' if gaps==['ANNOUNCEMENT_SELECTION_NO_VERIFIED_CAPTURE_IN_WINDOW']
                else 'PARTIAL' if gaps else 'READY' if materials else 'READY_EMPTY'),
        input_identity=digest([[(c.get('target_trade_date'),c.get('run_id'),c.get('sha256')) for c in captures],
            [(m['material_id'],m['body_sha256']) for m in materials],rejected]),**FLAGS)
