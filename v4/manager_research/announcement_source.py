"""Bounded helpers for the EXISTING HkexOfficialProvider, not a new fetcher.

The same MaterialStore retains exact POST directory bytes as well as the
original cached PDFs. Exhaustion of HKEX server-side pagination is deliberately
UNVERIFIED: draining a native-master cursor is not proof of all announcements.
"""
from __future__ import annotations

from base64 import b64encode, b64decode
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from time import monotonic, sleep
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

from .contracts import canonical_json
from .material_transport import _encode_envelope, _decode_envelope
from .pdf_parser import PdfParseError, extract_pdf_pages
from .workspace_projection import timestamp, canonical_symbol, date_token, digest

PARSER_VERSION = '20260922.official-subject-polarity.v1'
MAX_DOCUMENTS = 4
MAX_DIRECTORY_ROWS = 2000
MAX_BYTES = 8_000_000
_PDF_PAGE_CACHE_LOCK = RLock()
_PDF_PAGE_CACHE = OrderedDict()
_PDF_PAGE_CACHE_TEXT_CHARS = 0
_PDF_PAGE_CACHE_MAX_ENTRIES = 2048
_PDF_PAGE_CACHE_MAX_TEXT_CHARS = 32_000_000
_PDF_CACHEABLE_FAILURES = frozenset({
    'PDF_BYTE_BUDGET_EXCEEDED', 'PDF_PAGE_BUDGET_EXCEEDED', 'PDF_TEXT_BUDGET_EXCEEDED',
})


@dataclass(frozen=True)
class _CachedPdfParseFailure:
    reason: str


def _remember_pdf_parse(key: tuple, value: Any, text_characters: int) -> None:
    """Retain successful pages and deterministic budget failures under the same bounded LRU."""
    global _PDF_PAGE_CACHE_TEXT_CHARS
    if text_characters > _PDF_PAGE_CACHE_MAX_TEXT_CHARS:
        return
    retained = deepcopy(value) if isinstance(value, list) else value
    with _PDF_PAGE_CACHE_LOCK:
        old = _PDF_PAGE_CACHE.pop(key, None)
        if old is not None:
            _PDF_PAGE_CACHE_TEXT_CHARS -= old[1]
        _PDF_PAGE_CACHE[key] = (retained, text_characters)
        _PDF_PAGE_CACHE_TEXT_CHARS += text_characters
        while (_PDF_PAGE_CACHE and
               (len(_PDF_PAGE_CACHE) > _PDF_PAGE_CACHE_MAX_ENTRIES or
                _PDF_PAGE_CACHE_TEXT_CHARS > _PDF_PAGE_CACHE_MAX_TEXT_CHARS)):
            _, (_, removed_size) = _PDF_PAGE_CACHE.popitem(last=False)
            _PDF_PAGE_CACHE_TEXT_CHARS -= removed_size
MAX_EASTMONEY_CONTENT_PAGES = 20
MAX_EASTMONEY_BODY_CHARACTERS = 120_000
MAX_EASTMONEY_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_EASTMONEY_TOTAL_RESPONSE_BYTES = 64 * 1024 * 1024
EASTMONEY_LIST_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
EASTMONEY_CONTENT_URL = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'
EASTMONEY_SOURCE = 'EASTMONEY_HK'
EASTMONEY_REQUEST_PREFIX = 'eastmoney-hk-announcement-request:'
_HK_TZ = timezone(timedelta(hours=8))
HKEX_MARKET_DIRECTORY_URL = 'https://www1.hkexnews.hk/search/titleSearchServlet.do'
HKEX_MARKET_PAGE_SIZE = 100
MAX_HKEX_MARKET_DIRECTORY_PAGES = 200
MAX_HKEX_MARKET_DIRECTORY_ROWS = 20_000
HKEX_MARKET_DIRECTORY_SCHEMA = 'v4.manager_research.hkex_market_directory.v1'



class CaptureBudgetExpired(RuntimeError):
    pass


@dataclass
class CaptureBudget:
    """Per invocation cooperative request budget; the process has a hard deadline.

    Counts calls made at the original provider boundary, NOT physical HTTP
    hops: cache reuse can reduce them, original redirects can add hops.
    """
    seconds: float = 45.0
    max_requests: int = 57
    interval: float = 0.5
    max_response_bytes: int | None = None
    requests: int = 0
    response_bytes: int = 0
    _start: float = field(default_factory=lambda: monotonic())
    _last: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0,monotonic()-self._start)

    def check(self) -> None:
        if monotonic() - self._start >= self.seconds:
            raise CaptureBudgetExpired('ANNOUNCEMENT_TIME_BUDGET_EXHAUSTED')

    def before_request(self) -> None:
        self.check()
        if self.requests >= self.max_requests:
            raise CaptureBudgetExpired('ANNOUNCEMENT_REQUEST_BUDGET_EXHAUSTED')
        if self._last is not None:
            wait = max(0.0, self.interval - (monotonic() - self._last))
            if wait:
                sleep(wait)
        self.check()
        self.requests += 1
        self._last = monotonic()

    def record_response_bytes(self, size: int) -> None:
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError('ANNOUNCEMENT_RESPONSE_SIZE_INVALID')
        self.check()
        if (self.max_response_bytes is not None and
                self.response_bytes + size > self.max_response_bytes):
            raise CaptureBudgetExpired('ANNOUNCEMENT_TOTAL_RESPONSE_BYTES_BUDGET_EXHAUSTED')
        self.response_bytes += size

def _time(value: str) -> datetime:
    dt = timestamp(value)
    if dt is None:
        raise ValueError('ANNOUNCEMENT_TIME_WITH_TIMEZONE_REQUIRED')
    return dt


def window(context: Mapping[str, Any]) -> tuple[datetime, datetime]:
    since, as_of = _time(context['focus_window_start']), _time(context['research_cutoff'])
    equal_daily_boundary = (since == as_of and context.get('publication_window_mode') == 'HK_CALENDAR_DAY_V1')
    if (since > as_of or (since == as_of and not equal_daily_boundary)
            or ((as_of - since).days > 31 and context.get('publication_window_mode') != 'HK_CALENDAR_DAY_V1')):
        raise ValueError('ANNOUNCEMENT_WINDOW_INVALID')
    return since, as_of


def publication_window(context: Mapping[str, Any]) -> tuple[datetime, datetime, bool]:
    """Return the publication interval and whether its left edge is inclusive.

    Legacy scans keep their close-to-cutoff open interval. Explicit daily scans
    carry a Hong Kong calendar-day interval separately from the honest retrieval
    cutoff, which may be later than midnight when reading a historical day.
    """
    if context.get('publication_window_mode') == 'HK_CALENDAR_DAY_V1':
        start = _time(context.get('publication_window_start'))
        end = _time(context.get('publication_window_end_exclusive'))
        day = context.get('publication_date')
        if (not isinstance(day, str) or not re.fullmatch(r'\d{8}', day)
                or start.strftime('%Y%m%d') != day
                or start.hour or start.minute or start.second or start.microsecond
                or end <= start or end > start + timedelta(days=1)):
            raise ValueError('ANNOUNCEMENT_DAILY_PUBLICATION_WINDOW_INVALID')
        return start, end, True
    start, end = window(context)
    return start, end, False


def request_context(context: Mapping[str, Any]) -> dict[str, str]:
    """Canonical query identity; daily retrieval cutoffs remain cache-distinct."""
    start, end, _inclusive = publication_window(context)
    inclusive_end = end - timedelta(microseconds=1) if context.get('publication_window_mode') == 'HK_CALENDAR_DAY_V1' else end
    result = dict(since=start.isoformat(), as_of=inclusive_end.isoformat())
    if context.get('publication_window_mode') == 'HK_CALENDAR_DAY_V1':
        result.update(publication_window_mode='HK_CALENDAR_DAY_V1',
                      query_cutoff=_time(context['research_cutoff']).isoformat())
    return result


def publication_in_window(value: datetime, context: Mapping[str, Any]) -> bool:
    start, end, left_inclusive = publication_window(context)
    return start <= value < end if left_inclusive else start < value <= end


def query_request(issuer: Mapping[str, Any], context: Mapping[str, Any]) -> dict:
    from .hkex_provider import TITLE_SEARCH_URL
    request_window = request_context(context)
    since = _time(request_window['since'])
    as_of = _time(request_window['as_of'])
    form = urlencode(dict(lang='EN', category='0', market='SEHK', searchType='0',
        documentType='-1', t1code='-2', t2Gcode='-2', t2code='-2', stockId=issuer['stock_id'],
        **{'from': since.strftime('%Y%m%d'), 'to': as_of.strftime('%Y%m%d')}, title=''))
    return dict(url=TITLE_SEARCH_URL, method='POST', body_b64=b64encode(form.encode('ascii')).decode(),
        referer=TITLE_SEARCH_URL+'?'+form, context=request_window)


def official_market_directory_request(*, from_date: str, to_date: str,
                                      row_range: int, context: Mapping[str, Any]) -> dict:
    """Build the official all-market query used by HKEX's current title-search UI."""
    from .hkex_provider import _safe_official_url
    start=date_token(from_date);end=date_token(to_date)
    if (start>end or type(row_range) is not int or row_range<HKEX_MARKET_PAGE_SIZE
            or row_range%HKEX_MARKET_PAGE_SIZE):
        raise ValueError('HKEX_MARKET_DIRECTORY_REQUEST_INVALID')
    params=(('sortDir','0'),('sortByOptions','DateTime'),('category','0'),('market','SEHK'),
        ('stockId',''),('documentType','-1'),('fromDate',start),('toDate',end),('title',''),
        ('searchType','0'),('t1code','-2'),('t2Gcode','-2'),('t2code','-2'),
        ('rowRange',str(row_range)),('lang','ZH'))
    url=HKEX_MARKET_DIRECTORY_URL+'?'+urlencode(params)
    if not _safe_official_url(url):
        raise ValueError('HKEX_MARKET_DIRECTORY_REQUEST_NOT_OFFICIAL')
    request_context={key:context[key] for key in (
        'target_trade_date','publication_window_start','research_cutoff','window_mode')
        if key in context}
    request_context.update(from_date=start,to_date=end,row_range=row_range,
        source_scope='HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1')
    return dict(url=url,method='GET',context=request_context)


def _parse_official_market_page(raw: bytes, *, requested_row_range: int) -> dict:
    """Parse one cumulative titleSearchServlet response without assuming a total."""
    try:
        payload=json.loads(raw.decode('utf-8'))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('HKEX_MARKET_DIRECTORY_RESPONSE_JSON_INVALID') from exc
    if not isinstance(payload,Mapping):
        raise ValueError('HKEX_MARKET_DIRECTORY_RESPONSE_SHAPE_INVALID')
    result=payload.get('result')
    if isinstance(result,str):
        try:rows=json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError('HKEX_MARKET_DIRECTORY_RESULT_JSON_INVALID') from exc
    else:
        rows=result
    if not isinstance(rows,list):
        raise ValueError('HKEX_MARKET_DIRECTORY_RESULT_LIST_INVALID')
    record_count=payload.get('recordCnt');loaded=payload.get('loadedRecord')
    response_range=payload.get('rowRange');has_next=payload.get('hasNextRow')
    if any(type(value) is not int or value<0 for value in (record_count,loaded,response_range)):
        raise ValueError('HKEX_MARKET_DIRECTORY_COUNT_FIELD_INVALID')
    if type(has_next) is not bool:
        raise ValueError('HKEX_MARKET_DIRECTORY_HAS_NEXT_INVALID')
    issues=[]
    if response_range!=requested_row_range:
        issues.append('HKEX_MARKET_DIRECTORY_ROW_RANGE_MISMATCH')
    if loaded!=len(rows):
        issues.append('HKEX_MARKET_DIRECTORY_LOADED_RECORD_MISMATCH')
    if loaded>record_count or loaded>requested_row_range:
        issues.append('HKEX_MARKET_DIRECTORY_LOADED_RECORD_OUT_OF_RANGE')
    if loaded!=min(record_count,requested_row_range):
        issues.append('HKEX_MARKET_DIRECTORY_PAGE_SIZE_OR_COMPLETENESS_MISMATCH')
    if has_next!=(loaded<record_count):
        issues.append('HKEX_MARKET_DIRECTORY_HAS_NEXT_CONTRADICTS_COUNTS')
    return dict(record_count=record_count,loaded_record=loaded,row_range=response_range,
        has_next_row=has_next,raw_rows=rows,issues=issues)


def _market_text(value: Any) -> str:
    if not isinstance(value,str):return ''
    value=re.sub(r'<br\s*/?>',' ',value,flags=re.IGNORECASE)
    value=re.sub(r'<[^>]*>',' ',value)
    return re.sub(r'\s+',' ',value.replace('\xa0',' ')).strip()


def _market_parts(value: Any) -> list[str]:
    if not isinstance(value,str):return []
    return [item.strip() for item in re.split(r'<br\s*/?>|[\r\n]+',value,flags=re.IGNORECASE)
            if item.strip()]


def _normalize_official_market_row(value: Any, *, page_index: int,
                                   item_index: int) -> tuple[dict | None,str | None]:
    from .hkex_provider import _safe_official_url
    if not isinstance(value,Mapping):return None,'HKEX_MARKET_ROW_INVALID'
    news_id=value.get('NEWS_ID')
    if isinstance(news_id,bool) or not isinstance(news_id,(str,int)) or not str(news_id).strip():
        return None,'HKEX_MARKET_NEWS_ID_INVALID'
    release=_market_text(value.get('DATE_TIME'))
    try:published=datetime.strptime(release,'%d/%m/%Y %H:%M').replace(tzinfo=_HK_TZ)
    except (TypeError,ValueError):return None,'HKEX_MARKET_RELEASE_TIME_INVALID'
    codes=[]
    for part in _market_parts(value.get('STOCK_CODE')):
        token=_market_text(part)
        if re.fullmatch(r'\d{5}',token) and token not in codes:codes.append(token)
    names=[_market_text(part) for part in _market_parts(value.get('STOCK_NAME'))]
    names=[name for name in names if name]
    if not codes:return None,'HKEX_MARKET_STOCK_CODE_MISSING_OR_INVALID'
    if not isinstance(value.get('TITLE'),str) or not _market_text(value.get('TITLE')):
        return None,'HKEX_MARKET_TITLE_MISSING'
    link=value.get('FILE_LINK')
    if not isinstance(link,str) or not link.strip():return None,'HKEX_MARKET_FILE_LINK_MISSING'
    url=urljoin('https://www1.hkexnews.hk',link.strip())
    if not _safe_official_url(url):return None,'HKEX_MARKET_FILE_LINK_NOT_OFFICIAL'
    return dict(news_id=str(news_id).strip(),stock_codes=codes,stock_names=names,
        title=_market_text(value.get('TITLE')),published_at=published.isoformat(timespec='minutes'),
        publication_date=published.strftime('%Y%m%d'),release_time=release,url=url,
        file_type=_market_text(value.get('FILE_TYPE')).upper(),file_info=_market_text(value.get('FILE_INFO')),
        page_index=page_index,item_index=item_index,raw_row=deepcopy(dict(value))),None


def collect_official_market_batch(provider: Any, *, context: Mapping[str,Any],
                                  from_date: str, to_date: str,
                                  publication_window_start: str, window_mode: str,
                                  priority_codes: Sequence[str]=(), priority_news_ids: Sequence[str]=(),
                                  max_documents: int=4,
                                  budget: CaptureBudget | None=None) -> dict:
    """Capture HKEX's full-market listing and selected PDF bodies in its original store."""
    if provider._material_store is None or provider._material_transport is None:
        raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_REQUIRED')
    start=date_token(from_date);end=date_token(to_date)
    start_at=_time(publication_window_start);cutoff=_time(context['research_cutoff'])
    if (start>end or cutoff.strftime('%Y%m%d')<end or start_at>cutoff
            or not isinstance(window_mode,str) or not window_mode
            or type(max_documents) is not int or not 0<=max_documents<=MAX_DOCUMENTS
            or len(priority_codes)>24 or len(set(priority_codes))!=len(priority_codes)
            or any(canonical_symbol(code)!=code for code in priority_codes)
            or not isinstance(priority_news_ids,(list,tuple))
            or len(priority_news_ids)>MAX_DOCUMENTS or len(set(priority_news_ids))!=len(priority_news_ids)
            or any(not isinstance(news_id,str) or not re.fullmatch(r'\d{5,20}',news_id)
                for news_id in priority_news_ids)):
        raise ValueError('HKEX_MARKET_DIRECTORY_WINDOW_OR_BOUND_INVALID')
    query_context=dict(target_trade_date=date_token(context['plan_trade_date']),
        publication_window_start=start_at.isoformat(),research_cutoff=cutoff.isoformat(),window_mode=window_mode)
    pages=[];errors=[];expected_total=None;accepted_raw_rows=[];accepted_page=None;previous_ids=[];previous_rows=[]
    previous_loaded=0;exhausted=False;identity_drift=False
    for page_number in range(1,MAX_HKEX_MARKET_DIRECTORY_PAGES+1):
        requested=page_number*HKEX_MARKET_PAGE_SIZE
        request=official_market_directory_request(from_date=start,to_date=end,row_range=requested,context=query_context)
        receipt=dict(page_number=page_number,requested_row_range=requested,capture_status='FAILED',
            source_ref=None,record_count=None,loaded_record=None,response_row_range=None,
            has_next_row=None,result_row_count=None,news_id_sha256=None,issues=[],reason=None)
        try:
            ref=capture(provider,request,budget=budget);receipt['source_ref']=ref
            raw=read_response(provider._material_store,ref)
            receipt.update(retrieved_at=ref['retrieved_at'],http_status=ref['http_status'],
                raw_body_sha256=ref['body_sha256'])
            if not 200<=ref['http_status']<300:raise ValueError('HKEX_MARKET_DIRECTORY_HTTP_FAILED')
            parsed=_parse_official_market_page(raw,requested_row_range=requested)
            raw_rows=parsed['raw_rows'];ids=[];row_issues=list(parsed['issues'])
            for index,row in enumerate(raw_rows,1):
                normalized,issue=_normalize_official_market_row(row,page_index=page_number,item_index=index)
                if issue:row_issues.append(issue);ids.append('INVALID:'+str(index))
                else:ids.append(normalized['news_id'])
            if parsed['record_count']>MAX_HKEX_MARKET_DIRECTORY_ROWS:
                row_issues.append('HKEX_MARKET_DIRECTORY_ROW_BUDGET_EXCEEDED')
            if expected_total is None:expected_total=parsed['record_count']
            elif parsed['record_count']!=expected_total:row_issues.append('HKEX_MARKET_DIRECTORY_RECORD_COUNT_DRIFT')
            if page_number>1 and (ids[:len(previous_ids)]!=previous_ids
                    or raw_rows[:len(previous_rows)]!=previous_rows):
                row_issues.append('HKEX_MARKET_DIRECTORY_PAGE_IDENTITY_DRIFT');identity_drift=True
            if len(ids)!=len(set(ids)):row_issues.append('HKEX_MARKET_DIRECTORY_DUPLICATE_NEWS_ID')
            previous_page_loaded=previous_loaded
            receipt.update(record_count=parsed['record_count'],loaded_record=parsed['loaded_record'],
                response_row_range=parsed['row_range'],has_next_row=parsed['has_next_row'],
                result_row_count=len(raw_rows),news_id_sha256=digest(ids),issues=sorted(set(row_issues)),
                capture_status='PASS' if not row_issues else 'PARTIAL')
            pages.append(receipt)
            if identity_drift:
                errors.extend(row_issues)
                break
            # Keep only the last fully validated cumulative page. A malformed
            # or drifting page is evidence of a partial scan, not a new trusted
            # row set, even when HKEX says it is the terminal page.
            if row_issues:
                errors.extend(row_issues)
                break
            accepted_raw_rows=raw_rows;accepted_page=receipt;previous_ids=ids;previous_rows=raw_rows
            previous_loaded=parsed['loaded_record']
            if parsed['has_next_row'] is False:
                exhausted=(not row_issues and parsed['loaded_record']==parsed['record_count']
                    and len(raw_rows)==parsed['record_count'])
                if not exhausted:errors.append('HKEX_MARKET_DIRECTORY_TERMINAL_COUNTS_UNVERIFIED')
                break
            if parsed['loaded_record']<=previous_page_loaded:
                errors.append('HKEX_MARKET_DIRECTORY_PAGINATION_DID_NOT_ADVANCE');break
        except CaptureBudgetExpired as exc:
            receipt['reason']=safe_reason(exc,'HKEX_MARKET_DIRECTORY_CAPTURE_BUDGET_EXHAUSTED')
            receipt['capture_status']='PARTIAL';pages.append(receipt);errors.append(receipt['reason']);break
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            receipt['reason']=safe_reason(exc,'HKEX_MARKET_DIRECTORY_PAGE_FAILED')
            receipt['capture_status']=('FAILED' if receipt.get('source_ref') is not None
                and not 200<=receipt.get('http_status',0)<300 else 'PARTIAL')
            pages.append(receipt);errors.append(receipt['reason']);break
    else:
        errors.append('HKEX_MARKET_DIRECTORY_PAGE_LIMIT_EXCEEDED')
    if not exhausted and not errors:
        errors.append('HKEX_MARKET_DIRECTORY_SERVER_PAGINATION_UNEXHAUSTED')
    entries=[];rejected=[];seen=set()
    final_ref=(accepted_page or {}).get('source_ref') if accepted_page else None
    accepted_page_number=(accepted_page or {}).get('page_number',0)
    for index,row in enumerate(accepted_raw_rows,1):
        normalized,issue=_normalize_official_market_row(row,page_index=accepted_page_number,item_index=index)
        if issue:
            rejected.append(dict(item_index=index,reason=issue,raw_row=deepcopy(row)));continue
        if normalized['news_id'] in seen:
            rejected.append(dict(item_index=index,news_id=normalized['news_id'],
                reason='HKEX_MARKET_DIRECTORY_DUPLICATE_NEWS_ID',raw_row=deepcopy(row)));continue
        seen.add(normalized['news_id'])
        if final_ref is not None:normalized['directory_ref']=deepcopy(final_ref)
        entries.append(normalized)
    if rejected and exhausted:
        exhausted=False;errors.append('HKEX_MARKET_DIRECTORY_ROWS_REJECTED')
    market=dict(schema_version=HKEX_MARKET_DIRECTORY_SCHEMA,source_scope='HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1',
        target_trade_date=query_context['target_trade_date'],query_context=query_context,
        from_date=start,to_date=end,window_mode=window_mode,publication_window_start=start_at.isoformat(),
        query_cutoff=cutoff.isoformat(),page_size=HKEX_MARKET_PAGE_SIZE,record_count=expected_total,
        priority_codes=list(priority_codes),priority_news_ids=list(priority_news_ids),
        body_retry_identity=cutoff.isoformat() if priority_news_ids else None,document_budget=max_documents,
        loaded_record=previous_loaded,has_next_row=(pages[-1].get('has_next_row') if pages else None),
        pages=pages,rows=entries,rejected_rows=rejected,expected_page_count=(
            max(1,(expected_total+HKEX_MARKET_PAGE_SIZE-1)//HKEX_MARKET_PAGE_SIZE)
            if type(expected_total) is int else None),
        captured_page_count=len(pages),captured_row_count=len(accepted_raw_rows),
        accepted_page_number=accepted_page_number,
        unique_news_id_count=len(entries),directory_exhaustion='VERIFIED' if exhausted else 'UNVERIFIED',
        status='COMPLETE' if exhausted else 'PARTIAL' if pages else 'FAILED',gaps=sorted(set(errors)))
    eligible=[];release_time_conflicts=[]
    for row in entries:
        published=timestamp(row['published_at']);available=timestamp((row.get('directory_ref') or {}).get('retrieved_at'))
        if (published is None or published<start_at or published>cutoff
                or available is None):
            continue
        if published>available:
            release_time_conflicts.append(row['news_id'])
            continue
        eligible.append(row)
    market['release_time_conflict_news_ids']=sorted(release_time_conflicts)
    market['body_gaps']=[]
    if release_time_conflicts:
        market['gaps']=sorted(set(market['gaps']+['HKEX_MARKET_RELEASE_AFTER_DIRECTORY_CAPTURE']))
        if market['status']=='COMPLETE':market['status']='PARTIAL'
    priorities=set(priority_codes);priority_order={news_id:index for index,news_id in enumerate(priority_news_ids)}
    eligible_news_ids={row['news_id'] for row in eligible}
    retry_missing=[news_id for news_id in priority_news_ids if news_id not in eligible_news_ids]
    market['body_retry_missing_news_ids']=retry_missing
    if retry_missing:
        market['body_gaps'].append('HKEX_MARKET_BODY_RETRY_ROWS_NOT_IN_DIRECTORY')
    eligible.sort(key=lambda row:(priority_order.get(row['news_id'],len(priority_order)),
        not bool(priorities.intersection('HK.'+code for code in row['stock_codes'])),
        -int(timestamp(row['published_at']).timestamp()),row['news_id']))
    candidates=[row for row in eligible if row.get('file_type')=='PDF' or row['url'].lower().endswith('.pdf')]
    market_documents=[];attempted=set()
    for row in candidates[:max_documents]:
        symbol='HK.'+row['stock_codes'][0]
        codes=[('HK.'+code) for code in row['stock_codes']]
        code_names={('HK.'+code):row['stock_names'][i] for i,code in enumerate(row['stock_codes'])
            if i<len(row['stock_names'])}
        doc=dict(news_id=row['news_id'],code=symbol,codes=codes,name=code_names.get(symbol) or '',
            code_names=code_names,row=deepcopy(row),directory_ref=deepcopy(row['directory_ref']),
            body_ref=None,body_status='BODY_FETCH_FAILED',reason=None)
        attempted.add(row['news_id'])
        try:
            request=dict(url=row['url'],method='GET')
            if row['news_id'] in priority_order:
                # A cutoff-bound retry identity bypasses a cached failed
                # response while successful first-capture PDF bytes stay reusable.
                request.update(retry_identity=cutoff.isoformat(),news_id=row['news_id'])
            body_ref=capture(provider,request,budget=budget)
            doc['body_ref']=body_ref
            body=read_response(provider._material_store,body_ref)
            if not 200<=body_ref['http_status']<300:
                doc.update(body_status='BODY_FETCH_FAILED',reason='HKEX_MARKET_DOCUMENT_HTTP_FAILED')
            elif not body.startswith(b'%PDF'):
                doc.update(body_status='BODY_UNREADABLE',reason='HKEX_MARKET_DOCUMENT_NOT_PDF')
            else:
                doc.update(body_status='BODY_CAPTURED_UNASSESSED',reason='SEMANTIC_ANALYSIS_NOT_RUN')
        except CaptureBudgetExpired as exc:
            doc.update(body_status='BODY_FETCH_FAILED',reason=safe_reason(exc,'ANNOUNCEMENT_REQUEST_BUDGET_EXHAUSTED'))
            market_documents.append(doc);market['body_gaps'].append(doc['reason']);break
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            doc.update(body_status='BODY_FETCH_FAILED',reason=safe_reason(exc,'HKEX_MARKET_DOCUMENT_CAPTURE_FAILED'))
        market_documents.append(doc)
    pending=[]
    for row in eligible:
        if row['news_id'] in attempted:continue
        symbol='HK.'+row['stock_codes'][0]
        code_names={('HK.'+code):row['stock_names'][i] for i,code in enumerate(row['stock_codes'])
            if i<len(row['stock_names'])}
        is_pdf=row.get('file_type')=='PDF' or row['url'].lower().endswith('.pdf')
        pending.append(dict(news_id=row['news_id'],code=symbol,codes=['HK.'+c for c in row['stock_codes']],
            name=code_names.get(symbol) or '',code_names=code_names,row=deepcopy(row),
            directory_ref=deepcopy(row['directory_ref']),body_ref=None,
            body_status='BODY_NOT_CAPTURED' if is_pdf else 'BODY_FORMAT_UNSUPPORTED',
            reason='BODY_CAPTURE_QUEUED' if is_pdf else 'OFFICIAL_FILE_TYPE_NOT_SUPPORTED_BY_PDF_BODY_READER'))
    market['gaps']=sorted(set(market['gaps']+errors))
    if errors and market['status']=='COMPLETE':
        market['status']='PARTIAL';market['directory_exhaustion']='UNVERIFIED'
    market['body_gaps']=sorted(set(market['body_gaps']))
    return dict(market_directory=market,market_documents=market_documents,
        market_pending_documents=pending)


def verify_official_market_directory(store: Any, market: Mapping[str,Any], *,
                                     owner_generated_at: str) -> bool:
    """Re-derive every cumulative page and row from MaterialStore before trust."""
    if (not isinstance(market,Mapping) or market.get('schema_version')!=HKEX_MARKET_DIRECTORY_SCHEMA
            or market.get('source_scope')!='HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1'
            or not isinstance(market.get('pages'),list) or not market['pages']
            or market.get('status') not in {'COMPLETE','PARTIAL'}):return False
    context=market.get('query_context')
    if not isinstance(context,Mapping):return False
    try:
        start=date_token(market.get('from_date'));end=date_token(market.get('to_date'))
        query_cutoff=_time(context.get('research_cutoff'))
        window_start=_time(context.get('publication_window_start'))
        generated=_time(owner_generated_at)
    except (ValueError,TypeError,KeyError):return False
    if (start>end or context.get('target_trade_date')!=market.get('target_trade_date')
            or market.get('target_trade_date')!=context.get('target_trade_date')
            or market.get('window_mode')!=context.get('window_mode')
            or market.get('publication_window_start')!=context.get('publication_window_start')
            or market.get('query_cutoff')!=context.get('research_cutoff')
            or query_cutoff>generated or window_start>query_cutoff
            or market.get('page_size')!=HKEX_MARKET_PAGE_SIZE):return False
    accepted_rows=[];accepted_page=None;record_count=None;loaded_before=0;terminal=False
    observed_gaps=[];all_rows_by_page=[]
    for index,page in enumerate(market['pages'],1):
        if not isinstance(page,Mapping) or page.get('page_number')!=index:return False
        ref=page.get('source_ref')
        if ref is None:
            reason=page.get('reason')
            if (page.get('capture_status')!='PARTIAL' or not isinstance(reason,str)
                    or not re.fullmatch(r'[A-Za-z0-9_:.]{1,160}',reason)
                    or any(page.get(key) is not None for key in (
                        'record_count','loaded_record','response_row_range','has_next_row',
                        'result_row_count','news_id_sha256','raw_body_sha256'))):return False
            observed_gaps.append(reason)
            if index!=len(market['pages']):return False
            break
        if not isinstance(ref,Mapping):return False
        request=official_market_directory_request(from_date=start,to_date=end,
            row_range=index*HKEX_MARKET_PAGE_SIZE,context=context)
        try:
            retrieved=_time(ref['retrieved_at'])
            raw=read_response(store,ref)
        except (ValueError,RuntimeError,OSError,KeyError,TypeError):return False
        if ref.get('request')!=request or retrieved>generated or sha256(raw).hexdigest()!=page.get('raw_body_sha256'):
            return False
        if not 200<=ref.get('http_status',0)<300:
            if (page.get('capture_status')!='FAILED' or page.get('reason')!='HKEX_MARKET_DIRECTORY_HTTP_FAILED'
                    or page.get('result_row_count') is not None or index!=len(market['pages'])):return False
            observed_gaps.append('HKEX_MARKET_DIRECTORY_HTTP_FAILED')
            break
        try:parsed=_parse_official_market_page(raw,requested_row_range=index*HKEX_MARKET_PAGE_SIZE)
        except ValueError as exc:
            reason=safe_reason(exc,'HKEX_MARKET_DIRECTORY_RESPONSE_INVALID')
            if (page.get('capture_status')!='PARTIAL' or page.get('reason')!=reason
                    or page.get('result_row_count') is not None or index!=len(market['pages'])):
                return False
            observed_gaps.append(reason)
            break
        raw_rows=parsed['raw_rows'];row_issues=list(parsed['issues']);ids=[]
        if record_count is None:record_count=parsed['record_count']
        elif parsed['record_count']!=record_count:row_issues.append('HKEX_MARKET_DIRECTORY_RECORD_COUNT_DRIFT')
        if index>1 and raw_rows[:len(accepted_rows)]!=accepted_rows:
            row_issues.append('HKEX_MARKET_DIRECTORY_PAGE_IDENTITY_DRIFT')
        for item_index,row in enumerate(raw_rows,1):
            normalized,issue=_normalize_official_market_row(row,page_index=index,item_index=item_index)
            if issue:row_issues.append(issue);ids.append('INVALID:'+str(item_index))
            else:ids.append(normalized['news_id'])
        if parsed['record_count']>MAX_HKEX_MARKET_DIRECTORY_ROWS:
            row_issues.append('HKEX_MARKET_DIRECTORY_ROW_BUDGET_EXCEEDED')
        if len(ids)!=len(set(ids)):row_issues.append('HKEX_MARKET_DIRECTORY_DUPLICATE_NEWS_ID')
        unique_issues=sorted(set(row_issues))
        expected_status='PASS' if not unique_issues else 'PARTIAL'
        if (page.get('record_count')!=parsed['record_count'] or page.get('loaded_record')!=parsed['loaded_record']
                or page.get('response_row_range')!=parsed['row_range'] or page.get('has_next_row')!=parsed['has_next_row']
                or page.get('result_row_count')!=len(raw_rows) or page.get('news_id_sha256')!=digest(ids)
                or page.get('issues')!=unique_issues or page.get('capture_status')!=expected_status
                or page.get('reason') is not None):return False
        if index>1 and parsed['loaded_record']<=loaded_before:row_issues.append('HKEX_MARKET_DIRECTORY_PAGINATION_DID_NOT_ADVANCE')
        if 'HKEX_MARKET_DIRECTORY_PAGE_IDENTITY_DRIFT' in unique_issues:
            observed_gaps.extend(unique_issues);all_rows_by_page.append(raw_rows)
            break
        if unique_issues:
            observed_gaps.extend(unique_issues);all_rows_by_page.append(raw_rows)
            break
        accepted_rows=raw_rows;accepted_page=page;loaded_before=parsed['loaded_record'];all_rows_by_page.append(raw_rows)
        if not parsed['has_next_row']:
            terminal=(parsed['loaded_record']==parsed['record_count']==len(raw_rows))
            if index!=len(market['pages']):return False
            break
    if record_count is not None and record_count>MAX_HKEX_MARKET_DIRECTORY_ROWS:
        observed_gaps.append('HKEX_MARKET_DIRECTORY_ROW_BUDGET_EXCEEDED')
    if not terminal and not observed_gaps:
        if len(market['pages'])>=MAX_HKEX_MARKET_DIRECTORY_PAGES:
            observed_gaps.append('HKEX_MARKET_DIRECTORY_PAGE_LIMIT_EXCEEDED')
        else:
            observed_gaps.append('HKEX_MARKET_DIRECTORY_SERVER_PAGINATION_UNEXHAUSTED')
    if not terminal and market.get('status')=='COMPLETE':return False
    if accepted_page is None:
        expected_rows=[];expected_rejected=[];accepted_page_number=0;accepted_ref=None
    else:
        expected_rows=[];expected_rejected=[];accepted_page_number=accepted_page['page_number'];accepted_ref=accepted_page['source_ref']
        seen=set()
        for index,row in enumerate(accepted_rows,1):
            item,issue=_normalize_official_market_row(row,page_index=accepted_page_number,item_index=index)
            if issue:
                expected_rejected.append(dict(item_index=index,reason=issue,raw_row=deepcopy(row)));continue
            if item['news_id'] in seen:
                expected_rejected.append(dict(item_index=index,news_id=item['news_id'],
                    reason='HKEX_MARKET_DIRECTORY_DUPLICATE_NEWS_ID',raw_row=deepcopy(row)));continue
            seen.add(item['news_id']);item['directory_ref']=deepcopy(dict(accepted_ref));expected_rows.append(item)
    if expected_rejected and terminal:
        terminal=False;observed_gaps.append('HKEX_MARKET_DIRECTORY_ROWS_REJECTED')
    release_conflicts=[]
    for row in expected_rows:
        published=timestamp(row.get('published_at'))
        available=timestamp((row.get('directory_ref') or {}).get('retrieved_at'))
        if (published is not None and window_start<=published<=query_cutoff
                and available is not None and published>available):
            release_conflicts.append(row['news_id'])
    if release_conflicts:
        observed_gaps.append('HKEX_MARKET_RELEASE_AFTER_DIRECTORY_CAPTURE')
    if market.get('release_time_conflict_news_ids')!=sorted(release_conflicts):return False
    expected_status='COMPLETE' if terminal and not observed_gaps else 'PARTIAL' if market['pages'] else 'FAILED'
    expected_exhaustion='VERIFIED' if terminal else 'UNVERIFIED'
    expected_pages=(max(1,(record_count+HKEX_MARKET_PAGE_SIZE-1)//HKEX_MARKET_PAGE_SIZE)
        if type(record_count) is int else None)
    priorities=market.get('priority_codes');document_budget=market.get('document_budget')
    if (not isinstance(priorities,list) or len(priorities)>24 or priorities!=list(dict.fromkeys(priorities))
            or any(canonical_symbol(code)!=code for code in priorities)
            or type(document_budget) is not int or not 0<=document_budget<=MAX_DOCUMENTS
            or market.get('accepted_page_number')!=accepted_page_number or market.get('record_count')!=record_count
            or market.get('loaded_record')!=loaded_before or market.get('has_next_row')!=(market['pages'][-1].get('has_next_row') if market['pages'] else None)
            or market.get('captured_page_count')!=len(market['pages']) or market.get('captured_row_count')!=len(accepted_rows)
            or market.get('expected_page_count')!=expected_pages or market.get('unique_news_id_count')!=len(expected_rows)
            or market.get('rows')!=expected_rows or market.get('rejected_rows')!=expected_rejected
            or market.get('status')!=expected_status or market.get('directory_exhaustion')!=expected_exhaustion
            or market.get('gaps')!=sorted(set(observed_gaps))):return False
    return query_cutoff<=generated




class _HkexEmptyDirectoryParser(HTMLParser):
    """Extract the small set of server-rendered fields proving an empty result.

    This intentionally does not treat a bare "no matches" phrase as a
    successful directory response. It requires the native title-search form,
    its frozen query identity fields, the result-count panel, and the native
    no-results node.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.form_identity = False
        self.form_count = 0
        self.inputs: dict[str, list[str]] = {}
        self.panel_counts: dict[str, int] = {}
        self.count_text: list[str] = []
        self.empty_text: list[str] = []
        self._text_targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or '') for key, value in attrs}
        action_path = urlsplit(values.get('action', '')).path
        if tag.lower() == 'form' and (
            values.get('id') == 'j_idt10'
            and values.get('name') == 'j_idt10'
            and values.get('method', '').lower() == 'post'
            and action_path == '/search/titlesearch.xhtml'
        ):
            self.form_identity = True
            self.form_count += 1
        if tag.lower() == 'input' and values.get('type', '').lower() == 'hidden':
            key = values.get('id') or values.get('name')
            if key in {'startDate', 'endDate', 'stockId', 'stockCode', 'searchTypeInt',
                       'selectedDocType', 'selectedSecurities'}:
                self.inputs.setdefault(key, []).append(values.get('value', ''))
        if tag.lower() == 'div':
            ident = values.get('id')
            classes = set(values.get('class', '').split())
            if ident in {'recordCountPanel', 'titleSearchResultPanel'}:
                self.panel_counts[ident] = self.panel_counts.get(ident, 0) + 1
            if 'total-records' in classes:
                self._text_targets.append('count')
            elif 'result_norecords' in classes:
                self._text_targets.append('empty')
            else:
                self._text_targets.append('')

    def handle_data(self, data: str) -> None:
        if 'count' in self._text_targets:
            self.count_text.append(data)
        if 'empty' in self._text_targets:
            self.empty_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == 'div' and self._text_targets:
            self._text_targets.pop()


def _verified_empty_directory(raw: bytes, symbol: str, context: Mapping[str, Any],
                              expected_stock_id: str | None) -> bool:
    if not expected_stock_id or not re.fullmatch(r'\d+', str(expected_stock_id)):
        return False
    since, as_of, _inclusive = publication_window(context)
    if context.get('publication_window_mode') == 'HK_CALENDAR_DAY_V1':
        as_of -= timedelta(microseconds=1)
    parser = _HkexEmptyDirectoryParser()
    try:
        parser.feed(raw.decode('utf-8', errors='replace'))
        parser.close()
    except Exception:
        return False
    expected_inputs = {
        'startDate': since.astimezone(_HK_TZ).strftime('%Y-%m-%d'),
        'endDate': as_of.astimezone(_HK_TZ).strftime('%Y-%m-%d'),
        'stockId': str(expected_stock_id),
        'searchTypeInt': '0',
        'selectedDocType': '-1',
        'selectedSecurities': '0',
    }
    if (not parser.form_identity or parser.form_count != 1
            or parser.panel_counts != {'recordCountPanel': 1, 'titleSearchResultPanel': 1}):
        return False
    if any(parser.inputs.get(key) != [value] for key, value in expected_inputs.items()):
        return False
    stock_codes = parser.inputs.get('stockCode', [])
    stock_code = stock_codes[0].split(maxsplit=1)[0] if len(stock_codes) == 1 else ''
    if stock_code != symbol.split('.')[1]:
        return False
    count = re.sub(r'\s+', ' ', ''.join(parser.count_text)).strip()
    empty = re.sub(r'\s+', ' ', ''.join(parser.empty_text)).strip()
    return count == 'Total records found: 0' and empty == 'No matches found'


def capture(provider: Any, request: Mapping[str, Any], *, budget: CaptureBudget | None = None) -> dict:
    """Persist the actual response (including HTTP failures) in the SAME store.

    GET invokes the existing MaterialTransport and reuses immutable PDF bytes.
    POST uses the existing cookie/allowlist transport, with the exact form body
    retained in the receipt. Its key includes the frozen actual query cutoff.
    """
    from .hkex_provider import _safe_official_url
    req = deepcopy(dict(request))
    if not _safe_official_url(req['url']) or req['method'] not in {'GET','POST'}:
        raise ValueError('ANNOUNCEMENT_REQUEST_NOT_OFFICIAL')
    key = 'hkex-announcement-request:' + digest(req)
    def fetch(_url):
        if budget is not None:
            budget.before_request()
        response=provider._request(req['url'],method=req['method'],
            body=b64decode(req['body_b64']) if req.get('body_b64') else None,
            headers={'Content-Type':'application/x-www-form-urlencoded','Referer':req['referer']} if req['method']=='POST' else ({'Referer':req['referer']} if req.get('referer') else None),
            cache_response=req.get('cache_policy')!='SESSION_PRIME')
        _time(response.retrieved_at)
        return dict(body=_encode_envelope(response),retrieved_at=response.retrieved_at,
                    content_type='application/vnd.v4.source-envelope+json')
    material=provider._material_store.fetch(key,url=req['url'],ttl_seconds=None,transport=fetch)
    status, final_url, body=_decode_envelope(material.body)
    return dict(request=req,source_key=key,blob_sha256=material.sha256,
        body_sha256=sha256(body).hexdigest(),retrieved_at=material.retrieved_at,
        http_status=status,final_url=final_url,from_cache=material.from_cache)


def read_response(store: Any, ref: Mapping[str, Any]) -> bytes:
    """Read-only provenance check; never repairs/refetches a missing blob."""
    from .hkex_provider import _safe_official_url
    request=ref.get('request',{})
    if (request.get('method') not in {'GET','POST'} or not _safe_official_url(str(request.get('url','')))
            or ref.get('source_key') != 'hkex-announcement-request:'+digest(request)
            or not re.fullmatch(r'[a-f0-9]{64}',str(ref.get('blob_sha256','')))):
        raise ValueError('ANNOUNCEMENT_REFERENCE_INVALID')
    raw=store._io.read_bytes(store._blob_relative(ref['blob_sha256']),max_bytes=48*1024*1024)
    if sha256(raw).hexdigest()!=ref['blob_sha256']:
        raise ValueError('ANNOUNCEMENT_RAW_HASH_MISMATCH')
    index=store.stat_source(ref['source_key'])
    if not index or any(index.get(k)!=v for k,v in dict(sha256=ref['blob_sha256'],url=request['url'],retrieved_at=ref['retrieved_at']).items()):
        raise ValueError('ANNOUNCEMENT_RAW_INDEX_MISMATCH')
    status, final_url, body=_decode_envelope(raw)
    if (status!=ref['http_status'] or final_url!=ref.get('final_url')
            or (final_url and not _safe_official_url(final_url)) or sha256(body).hexdigest()!=ref['body_sha256']):
        raise ValueError('ANNOUNCEMENT_RESPONSE_BINDING_MISMATCH')
    _time(ref['retrieved_at'])
    return body


def _cached_extract_pdf_pages(body: bytes, *, max_bytes: int = MAX_BYTES,
                              max_pages: int = 40, max_text_characters: int = 240000,
                              timeout_seconds: float = 10.0,
                              cache_stats: dict | None = None) -> list[dict[str, Any]]:
    """Reuse a successful extraction only after callers revalidate source bytes.

    This bounded process-local memo is keyed by parser contract, active limits,
    and the exact PDF body hash. Owner reads revalidate each immutable
    blob/index/envelope before consulting it. Deterministic byte/page/text
    budget failures are reused; time-budget failures and other errors retry.
    """
    global _PDF_PAGE_CACHE_TEXT_CHARS
    key=(PARSER_VERSION,max_bytes,max_pages,max_text_characters,timeout_seconds,sha256(body).hexdigest())
    with _PDF_PAGE_CACHE_LOCK:
        if key in _PDF_PAGE_CACHE:
            cached,size=_PDF_PAGE_CACHE.pop(key)
            _PDF_PAGE_CACHE[key]=(cached,size)
            if cache_stats is not None:
                cache_stats['pdf_parse_cache_hits']=cache_stats.get('pdf_parse_cache_hits',0)+1
            if isinstance(cached,_CachedPdfParseFailure):
                raise PdfParseError(cached.reason)
            return deepcopy(cached)
    if cache_stats is not None:
        cache_stats['pdf_reparses']=cache_stats.get('pdf_reparses',0)+1
    try:
        pages=extract_pdf_pages(body,max_bytes=max_bytes,max_pages=max_pages,
            max_text_characters=max_text_characters,timeout_seconds=timeout_seconds)
    except (ValueError,RuntimeError) as exc:
        reason=safe_reason(exc,'PDF_PARSE_FAILED')
        if reason in _PDF_CACHEABLE_FAILURES:
            _remember_pdf_parse(key,_CachedPdfParseFailure(reason),0)
        raise
    size=sum(len(str(page.get('text',''))) for page in pages)
    _remember_pdf_parse(key,pages,size)
    return pages


def directory_entries(raw: bytes, symbol: str, context: Mapping[str, Any], *,
                      expected_stock_id: str | None = None) -> tuple[list[dict],list[dict],str]:
    from .hkex_provider import parse_title_rows
    since, as_of, left_inclusive=publication_window(context)
    parsed=parse_title_rows(raw)
    if len(parsed)>MAX_DIRECTORY_ROWS:
        raise ValueError('ANNOUNCEMENT_DIRECTORY_ROW_BUDGET_EXCEEDED')
    retained=[]; rejected=[]; seen=set()
    for row in parsed:
        published=_time(row['published_at'])
        reason=None
        if row['stock_code']!=symbol.split('.')[1]:reason='DIRECTORY_ISSUER_MISMATCH'
        elif (published<since if left_inclusive else published<=since):reason='AT_OR_BEFORE_WINDOW_START'
        elif (published>=as_of if left_inclusive else published>as_of):reason='PUBLICATION_AFTER_QUERY_CUTOFF'
        key=(row['stock_code'],row['url'])
        if reason is None and key in seen:reason='SAME_OFFICIAL_URL_DUPLICATE'
        if reason:rejected.append(dict(reason=reason,row=row));continue
        seen.add(key);retained.append(row)
    # An empty result is accepted only when the original request's official
    # stock id, exact frozen date window, and native HKEX result structure all
    # agree. The callers also bind that request to the official active list.
    explicit_empty = _verified_empty_directory(raw, symbol, context, expected_stock_id)
    if not parsed and not explicit_empty:
        raise ValueError('ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED')
    return sorted(retained,key=lambda x:(x['published_at'],x['url'])),rejected,(
        'NO_ROWS_IN_OBSERVED_RESPONSE' if explicit_empty and not parsed else 'OBSERVED_DIRECTORY_ROWS')


def collect_batch(provider: Any, *, context: Mapping[str,Any], issuers: Sequence[Mapping[str,Any]],
                  pending_documents: Sequence[Mapping[str,Any]]=(), max_issuers: int = 3,
                  max_documents: int = MAX_DOCUMENTS, budget: CaptureBudget | None = None,
                  reusable_documents: Mapping[tuple[str, str], Mapping[str, Any]] | None = None) -> dict:
    """One bounded increment. Neither Stage nor the positive-event title filter is used."""
    from .hkex_provider import ACTIVE_STOCK_LIST_URL
    if provider._material_store is None or provider._material_transport is None:
        raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_REQUIRED')
    window(context)
    if (type(max_issuers) is not int or not 1 <= max_issuers <= 24
            or type(max_documents) is not int or not 0 <= max_documents <= MAX_DOCUMENTS
            or len(issuers)>max_issuers or len(pending_documents)>10000
            or (reusable_documents is not None and len(reusable_documents)>20000)):
        raise ValueError('ANNOUNCEMENT_BATCH_BOUND_INVALID')
    queries=[];todo=deepcopy(list(pending_documents));docs=[]
    if issuers:
        since,as_of=window(context)
        mapping_ref=capture(provider,dict(url=ACTIVE_STOCK_LIST_URL,method='GET',
            context=request_context(context)), budget=budget)
        raw=read_response(provider._material_store,mapping_ref)
        if mapping_ref['http_status']!=200:raise ValueError('ANNOUNCEMENT_ACTIVE_LIST_HTTP_FAILED')
        entries=json.loads(raw)
        if not isinstance(entries,list):raise ValueError('ANNOUNCEMENT_ACTIVE_LIST_INVALID')
        mapping={}
        for x in entries:
            if isinstance(x,dict) and re.fullmatch(r'\d{5}',str(x.get('c',''))) and str(x.get('i','')).isdigit() and x.get('n'):
                if x['c'] in mapping:raise ValueError('ANNOUNCEMENT_ACTIVE_LIST_DUPLICATE')
                mapping[x['c']]=dict(stock_id=str(x['i']),issuer=x['n'])
        for issuer in issuers:
            if budget is not None:
                try:
                    budget.check()
                except CaptureBudgetExpired:
                    break
            symbol=issuer['code'];q=dict(code=symbol,name=issuer['name'],mapping_ref=mapping_ref,
                status='FAILED',entries=[],rejected=[],directory_ref=None,reason=None)
            try:
                if canonical_symbol(symbol)!=symbol:raise ValueError('ANNOUNCEMENT_NATIVE_SYMBOL_INVALID')
                match=mapping.get(symbol.split('.')[1])
                if match is None:raise ValueError('ANNOUNCEMENT_ISSUER_NOT_IN_ACTIVE_LIST')
                q['official_issuer']=match
                req=query_request(match,context)
                # Preserve the existing cookie/form priming flow, and its raw bytes.
                q['prime_ref']=capture(provider,dict(url=req['referer'],method='GET',context=req['context'],cache_policy='SESSION_PRIME'), budget=budget)
                from .hkex_directory_protocol import is_search_shell, capture_servlet_query
                prime_raw=read_response(provider._material_store,q['prime_ref'])
                # Only the explicit issuer-subset contract opts into this adapter.
                # Existing daily and Eastmoney owners retain their current paths.
                if (context.get('targeted_source_window') and q['prime_ref']['http_status']==200
                        and is_search_shell(prime_raw)):
                    q['directory_ref']=q['prime_ref']
                    capture_servlet_query(provider,q,context,budget)
                    ref=q['directory_ref'];found=q['entries']
                else:
                    ref=capture(provider,req,budget=budget);q['directory_ref']=ref
                    raw=read_response(provider._material_store,ref)
                    if not 200<=ref['http_status']<300:raise ValueError('ANNOUNCEMENT_DIRECTORY_HTTP_FAILED')
                    found,rejected,reason=directory_entries(
                        raw, symbol, context,
                        expected_stock_id=q['official_issuer']['stock_id'],
                    )
                    q.update(status='OBSERVED',entries=found,rejected=rejected,reason=reason)
                for row in found:todo.append(dict(code=symbol,name=issuer['name'],row=row,
                    directory_ref=ref,mapping_ref=mapping_ref,official_issuer=match))
            except CaptureBudgetExpired as exc:
                request=q.pop('pending_protocol_request',None)
                if request is None:break
                q['reason']=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED')
                q['capture_failure']=dict(request=deepcopy(request),reason=q['reason'],
                    exception_type=type(exc).__name__,outcome='BUDGET_REFUSED_BEFORE_PROVIDER_CALL')
                queries.append(q)
                break
            except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
                q['reason']=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED')
                request=q.pop('pending_protocol_request',None)
                if request is not None:
                    q['capture_failure']=dict(request=deepcopy(request),reason=q['reason'],
                        exception_type=type(exc).__name__,outcome='NO_RESPONSE_REFERENCE_RETURNED')
            queries.append(q)
    reusable_documents = reusable_documents or {}
    for item in todo[:max_documents]:
        doc={**item,'body_ref':None,'parse_status':'FAILED','reason':None}
        try:
            prior = reusable_documents.get((item['code'], item['row']['url']))
            if isinstance(prior, Mapping) and prior.get('body_ref') and prior.get('parse_status') in {'BODY_PARSED','BODY_UNREADABLE'}:
                body_ref = deepcopy(dict(prior['body_ref']))
                if body_ref.get('request') != dict(url=item['row']['url'], method='GET'):
                    raise ValueError('ANNOUNCEMENT_REUSED_BODY_IDENTITY_MISMATCH')
                # The previous product is source-verified before the owner
                # invokes this function. Re-read its immutable MaterialStore
                # reference and reuse the parser outcome for the same event;
                # _check_sources still re-derives it on subsequent reads.
                read_response(provider._material_store, body_ref)
                doc.update(body_ref=body_ref, parse_status=prior['parse_status'], reason=prior.get('reason'))
                docs.append(doc)
                continue
            ref=capture(provider,dict(url=item['row']['url'],method='GET'),budget=budget);doc['body_ref']=ref
            raw=read_response(provider._material_store,ref)
            if not 200<=ref['http_status']<300:raise ValueError('ANNOUNCEMENT_DOCUMENT_HTTP_FAILED')
            pages=_cached_extract_pdf_pages(raw,max_bytes=MAX_BYTES,max_pages=40,
                max_text_characters=240000,timeout_seconds=10)
            # Use the original parser, including its missing-dependency/failure boundary.
            doc.update(parse_status='BODY_PARSED' if pages else 'BODY_UNREADABLE',reason=None if pages else 'NO_READABLE_PDF_BODY')
        except CaptureBudgetExpired:
            break
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            doc['reason']=safe_reason(exc,'ANNOUNCEMENT_DOCUMENT_PARSE_FAILED')
        docs.append(doc)
    return dict(queries=queries,documents=docs,pending_documents=todo[len(docs):])


def _safe_eastmoney_url(url: str) -> bool:
    from .hkex_provider import _safe_eastmoney_hk_url
    return _safe_eastmoney_hk_url(url)


def eastmoney_list_url(stock_code: str, *, page_index: int = 1, page_size: int = 5) -> str:
    if not re.fullmatch(r'\d{5}', str(stock_code)) or page_index < 1 or not 1 <= page_size <= 20:
        raise ValueError('EASTMONEY_HK_QUERY_BOUND_INVALID')
    query = urlencode(dict(ann_type='H', client_source='web', stock_list=stock_code,
        page_index=page_index, page_size=page_size, sr=-1))
    return EASTMONEY_LIST_URL + '?' + query


def eastmoney_content_url(art_code: str, *, page_index: int = 1) -> str:
    if not re.fullmatch(r'AN[A-Z0-9]{8,32}', str(art_code)) or page_index < 1:
        raise ValueError('EASTMONEY_HK_ARTICLE_ID_INVALID')
    query = urlencode(dict(art_code=art_code, client_source='web', page_index=page_index))
    return EASTMONEY_CONTENT_URL + '?' + query


def capture_eastmoney(provider: Any, url: str, *, budget: CaptureBudget | None = None,
                      force: bool = False) -> dict:
    """Capture an Eastmoney response into the existing shared MaterialStore."""
    if provider._material_store is None or not _safe_eastmoney_url(url):
        raise ValueError('EASTMONEY_HK_SHARED_STORE_OR_URL_INVALID')
    req = dict(source=EASTMONEY_SOURCE, method='GET', url=url)
    key = EASTMONEY_REQUEST_PREFIX + digest(req)

    def fetch(_url):
        if budget is not None:
            budget.before_request()
        request_timeout=(max(0.001,budget.seconds-budget.elapsed_seconds) if budget is not None
            else provider._timeout)
        response = provider._request_eastmoney_hk(url,timeout=request_timeout)
        _time(response.retrieved_at)
        if budget is not None:budget.check()
        if len(response.body)>MAX_EASTMONEY_RESPONSE_BYTES:
            raise ValueError('EASTMONEY_HK_RESPONSE_SIZE_BUDGET_EXCEEDED')
        if not _safe_eastmoney_url(response.final_url or url):
            raise ValueError('EASTMONEY_HK_FINAL_URL_INVALID')
        return dict(body=_encode_envelope(response), retrieved_at=response.retrieved_at,
                    content_type='application/vnd.v4.source-envelope+json')

    ttl = 300.0 if urlsplit(url).hostname == 'np-anotice-stock.eastmoney.com' else None
    material = provider._material_store.fetch(key, url=url, ttl_seconds=ttl,
        transport=fetch, force=force)
    status, final_url, body = _decode_envelope(material.body)
    return dict(request=req, source_key=key, blob_sha256=material.sha256,
        body_sha256=sha256(body).hexdigest(), retrieved_at=material.retrieved_at,
        http_status=status, final_url=final_url, from_cache=material.from_cache)


def read_eastmoney_response(store: Any, ref: Mapping[str, Any]) -> bytes:
    """Verify exact Eastmoney response bytes from the original shared store."""
    request = ref.get('request', {})
    if (request.get('source') != EASTMONEY_SOURCE or request.get('method') != 'GET'
            or not _safe_eastmoney_url(str(request.get('url', '')))
            or ref.get('source_key') != EASTMONEY_REQUEST_PREFIX + digest(request)
            or not re.fullmatch(r'[a-f0-9]{64}', str(ref.get('blob_sha256', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(ref.get('body_sha256', '')))):
        raise ValueError('EASTMONEY_HK_REFERENCE_INVALID')
    raw = store._io.read_bytes(store._blob_relative(ref['blob_sha256']), max_bytes=48 * 1024 * 1024)
    if sha256(raw).hexdigest() != ref['blob_sha256']:
        raise ValueError('EASTMONEY_HK_RAW_HASH_MISMATCH')
    index = store.stat_source(ref['source_key'])
    if not index or any(index.get(k) != v for k, v in dict(
            sha256=ref['blob_sha256'], url=request['url'], retrieved_at=ref['retrieved_at']).items()):
        raise ValueError('EASTMONEY_HK_RAW_INDEX_MISMATCH')
    status, final_url, body = _decode_envelope(raw)
    if (status != ref['http_status'] or final_url != ref.get('final_url')
            or (final_url and not _safe_eastmoney_url(final_url))
            or sha256(body).hexdigest() != ref['body_sha256']):
        raise ValueError('EASTMONEY_HK_RESPONSE_BINDING_MISMATCH')
    _time(ref['retrieved_at'])
    return body


def _eastmoney_display_time(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3}', value):
        raise ValueError('EASTMONEY_HK_DISPLAY_TIME_INVALID')
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S:%f').replace(tzinfo=_HK_TZ)


def _eastmoney_notice_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} 00:00:00', value):
        raise ValueError('EASTMONEY_HK_NOTICE_DATE_INVALID')
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').date().isoformat()


def _eastmoney_codes(row: Mapping[str, Any]) -> list[dict]:
    codes = row.get('codes')
    if not isinstance(codes, list):
        return []
    return [dict(market_code=str(item.get('market_code', '')), stock_code=str(item.get('stock_code', '')),
            ann_type=str(item.get('ann_type', '')), short_name=item.get('short_name'))
        for item in codes if isinstance(item, Mapping)]


def collect_eastmoney_hk_batch(provider: Any, *, context: Mapping[str, Any],
                               issuers: Sequence[Mapping[str, Any]], max_issuers: int = 3,
                               max_documents: int = MAX_DOCUMENTS,
                               budget: CaptureBudget | None = None) -> dict:
    """Query a small master-owned HK issuer batch; never scans or claims HKEX proof."""
    if provider._material_store is None or provider._material_transport is None:
        raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_REQUIRED')
    since, cutoff = window(context)
    if (type(max_issuers) is not int or not 1 <= max_issuers <= 24
            or type(max_documents) is not int or not 0 <= max_documents <= MAX_DOCUMENTS
            or len(issuers) > max_issuers or len(issuers) > 24):
        raise ValueError('EASTMONEY_HK_BATCH_BOUND_INVALID')
    queries = []
    documents = []
    pending = []
    seen_issuers = set()
    for issuer in issuers:
        symbol = canonical_symbol(issuer.get('code'))
        name = str(issuer.get('name') or '').strip()
        if not symbol or symbol != issuer.get('code') or not name or symbol in seen_issuers:
            raise ValueError('EASTMONEY_HK_ISSUER_IDENTITY_INVALID')
        seen_issuers.add(symbol)
        stock_code = symbol.split('.')[1]
        q = dict(code=symbol, name=name, status='FAILED', listing_ref=None, entries=[], reason=None)
        try:
            listing_ref = capture_eastmoney(provider, eastmoney_list_url(stock_code), budget=budget, force=True)
            q['listing_ref'] = listing_ref
            raw = read_eastmoney_response(provider._material_store, listing_ref)
            if budget is not None:budget.record_response_bytes(len(raw))
            if listing_ref['http_status'] != 200:
                raise ValueError('EASTMONEY_HK_LIST_HTTP_FAILED')
            try:
                payload = json.loads(raw.decode('utf-8'))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError('EASTMONEY_HK_LIST_JSON_INVALID') from exc
            data = payload.get('data') if isinstance(payload, Mapping) else None
            rows = data.get('list') if isinstance(data, Mapping) else None
            if (not isinstance(payload, Mapping) or payload.get('success') != 1
                    or not isinstance(rows, list) or not isinstance(data.get('page_index'), int)
                    or data.get('page_index') != 1):
                raise ValueError('EASTMONEY_HK_LIST_CONTRACT_INVALID')
            retained = []
            rejected = []
            for row in rows:
                if not isinstance(row, Mapping):
                    rejected.append(dict(reason='EASTMONEY_HK_LIST_ROW_INVALID'))
                    continue
                code_rows = _eastmoney_codes(row)
                target_codes = [item for item in code_rows if item['stock_code'] == stock_code
                    and item['market_code'] == '116' and item['ann_type'] == 'H']
                if len(target_codes) != 1:
                    rejected.append(dict(reason='EASTMONEY_HK_ISSUER_OR_MARKET_UNMATCHED',
                        art_code=row.get('art_code')))
                    continue
                art_code = row.get('art_code')
                title = row.get('title')
                display = row.get('display_time')
                notice_date = row.get('notice_date')
                if not re.fullmatch(r'AN[A-Z0-9]{8,32}', str(art_code)) or not isinstance(title, str) or not title.strip():
                    rejected.append(dict(reason='EASTMONEY_HK_LIST_ARTICLE_IDENTITY_INVALID'))
                    continue
                display_dt = _eastmoney_display_time(display)
                date_only = _eastmoney_notice_date(notice_date)
                if display_dt <= since or display_dt > cutoff:
                    rejected.append(dict(reason='OUTSIDE_EASTMONEY_DISPLAY_TIME_WINDOW', art_code=art_code,
                        notice_date=notice_date, display_time=display))
                    continue
                retained.append(dict(art_code=art_code, title=title, notice_date=notice_date,
                    display_time=display, display_time_iso=display_dt.isoformat(),
                    source_notice_date=date_only, source_codes=code_rows,
                    market_code='116', stock_code=stock_code, ann_type='H',
                    short_name=target_codes[0].get('short_name'), listing_ref=listing_ref))
            retained.sort(key=lambda item: (item['display_time_iso'], item['art_code']), reverse=True)
            q.update(status='OBSERVED', entries=retained, rejected=rejected,
                total_hits=data.get('total_hits'), page_size=data.get('page_size'),
                reason='ONE_PAGE_OBSERVED_NOT_EXHAUSTIVE')
            queries.append(q)
            for row in retained:
                if len(documents) >= max_documents:
                    pending.append(dict(code=symbol, name=name, row=row))
                    continue
                try:
                    content_refs=[];body_pages=[];body_chars=0;detail=None;page_total=None
                    for page_index in range(1,MAX_EASTMONEY_CONTENT_PAGES+1):
                        content_ref=capture_eastmoney(provider,
                            eastmoney_content_url(row['art_code'],page_index=page_index),budget=budget)
                        content_raw=read_eastmoney_response(provider._material_store,content_ref)
                        if budget is not None:budget.record_response_bytes(len(content_raw))
                        if content_ref['http_status']!=200:
                            raise ValueError('EASTMONEY_HK_CONTENT_HTTP_FAILED')
                        content_payload=json.loads(content_raw.decode('utf-8'))
                        page_detail=content_payload.get('data') if isinstance(content_payload,Mapping) else None
                        if (not isinstance(content_payload,Mapping) or content_payload.get('success')!=1
                                or not isinstance(page_detail,Mapping) or page_detail.get('art_code')!=row['art_code']
                                or page_detail.get('notice_title')!=row['title']
                                or page_detail.get('notice_date')!=row['notice_date']):
                            raise ValueError('EASTMONEY_HK_CONTENT_IDENTITY_MISMATCH')
                        total=page_detail.get('page_size')
                        if type(total) is not int or not 1<=total<=MAX_EASTMONEY_CONTENT_PAGES:
                            raise ValueError('EASTMONEY_HK_CONTENT_PAGE_COUNT_INVALID')
                        if page_total is None:page_total=total;detail=page_detail
                        elif total!=page_total:raise ValueError('EASTMONEY_HK_CONTENT_PAGE_COUNT_CHANGED')
                        securities=page_detail.get('security')
                        matches=[item for item in securities if isinstance(item,Mapping)
                            and str(item.get('market_uni',''))=='116'
                            and str(item.get('stock',''))==stock_code] if isinstance(securities,list) else []
                        if not matches:raise ValueError('EASTMONEY_HK_CONTENT_SECURITY_MISMATCH')
                        page_text=page_detail.get('notice_content')
                        if not isinstance(page_text,str) or not page_text.strip():
                            raise ValueError('EASTMONEY_HK_CONTENT_PAGE_TEXT_MISSING')
                        body_chars+=len(page_text)
                        if body_chars>MAX_EASTMONEY_BODY_CHARACTERS:
                            raise ValueError('EASTMONEY_HK_CONTENT_TEXT_BUDGET_EXCEEDED')
                        body_pages.append(dict(page_index=page_index,text=page_text,
                            text_sha256=sha256(page_text.encode('utf-8')).hexdigest(),source_ref=content_ref))
                        content_refs.append(content_ref)
                        if page_index==page_total:break
                    if page_total is None or detail is None or len(body_pages)!=page_total:
                        raise ValueError('EASTMONEY_HK_CONTENT_PAGES_INCOMPLETE')
                    pdf_url = detail.get('attach_url_web')
                    if not _safe_eastmoney_url(str(pdf_url)) or f'AN{row["art_code"][2:]}_1.pdf' not in urlsplit(pdf_url).path:
                        raise ValueError('EASTMONEY_HK_PDF_URL_MISMATCH')
                    pdf_ref = capture_eastmoney(provider, str(pdf_url), budget=budget)
                    pdf_raw = read_eastmoney_response(provider._material_store, pdf_ref)
                    if budget is not None:budget.record_response_bytes(len(pdf_raw))
                    if pdf_ref['http_status'] != 200 or not pdf_raw.startswith(b'%PDF'):
                        raise ValueError('EASTMONEY_HK_FULL_PDF_UNAVAILABLE')
                    pages = extract_pdf_pages(pdf_raw, max_bytes=MAX_BYTES, max_pages=40,
                        max_text_characters=240000, timeout_seconds=10)
                    if not pages:
                        raise ValueError('EASTMONEY_HK_PDF_HAS_NO_READABLE_PAGES')
                    refs = [listing_ref, *content_refs, pdf_ref]
                    available = max(ref['retrieved_at'] for ref in refs)
                    body_text='\n\n'.join(page['text'] for page in body_pages)
                    doc = dict(code=symbol, name=name, source='EASTMONEY_HK', row=row,
                        content_refs=content_refs, body_pages=body_pages, body_text=body_text,
                        body_sha256=sha256(body_text.encode('utf-8')).hexdigest(),
                        body_status='FULL_CONTENT_API_TEXT_VERIFIED',
                        body_source='EASTMONEY_CONTENT_API_PAGES',
                        content_page_count=page_total, pdf_ref=pdf_ref, pdf_page_count=len(pages),
                        pdf_extracted_pages=pages,
                        pdf_extracted_pages_sha256=digest(pages),
                        pdf_text_extraction_status='UNVERIFIED_ENCODING',
                        pdf_bytes=len(pdf_raw), full_pdf_stored=True,
                        content_notice_date=detail.get('notice_date'), content_display_time=detail.get('eitime'),
                        document_sha256=pdf_ref['body_sha256'], available_at=available,
                        publication_status='CANNOT_CONFIRM_FIRST_PUBLICATION')
                    documents.append(doc)
                except CaptureBudgetExpired:
                    pending.append(dict(code=symbol, name=name, row=row,
                        reason='EASTMONEY_HK_CAPTURE_BUDGET_EXHAUSTED'))
                    break
                except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                    pending.append(dict(code=symbol, name=name, row=row,
                        reason=safe_reason(exc, 'EASTMONEY_HK_DOCUMENT_CAPTURE_FAILED')))
        except CaptureBudgetExpired:
            q['reason'] = 'ANNOUNCEMENT_TIME_OR_REQUEST_BUDGET_EXHAUSTED'
            queries.append(q)
            break
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            q['reason'] = safe_reason(exc, 'EASTMONEY_HK_ISSUER_QUERY_FAILED')
            queries.append(q)
    return dict(queries=queries, documents=documents, pending_documents=pending,
        queried_issuer_count=len(queries), source=EASTMONEY_SOURCE,
        source_scope='MASTER_OWNED_BOUNDED_HK_ISSUERS_NOT_FULL_MARKET')


def safe_reason(exc: Exception, fallback: str) -> str:
    # Keep explicit contract reasons, never paths, raw exception text or credentials.
    text=str(exc)
    return text if re.fullmatch(r'[A-Z][A-Z0-9_]{3,100}',text) else fallback+':'+type(exc).__name__


_NEG=re.compile(r'否认|否認|不涉及|不曾|并未|並未|没有|沒有|尚未|未获|未獲|未|不(?:构成|構成)|\b(?:not|never|denies|deny|denied|hasn.t|haven.t)\b',re.I)
_UNCERTAIN=re.compile(r'如果|倘若|可能|风险|風險|有望|拟|擬|预计|預計|\b(?:if|may|might|would|proposed|expects?|subject to|risk of)\b',re.I)
_ADVERSE=re.compile(r'终止|終止|取消|撤回|撤销|撤銷|违约|違約|无法偿还|無法償還|亏损|虧損|盈利下降|盈警|\b(?:terminated|cancelled|canceled|defaulted|default|withdrawn|profit warning|loss)\b',re.I)
_POSITIVE=re.compile(r'^(?:(?:现|現|已|正式|宣布|宣佈|公告|表示|确认|確認|取得|获得|獲得|并|並)\s*){0,4}(?:签署|簽署|达成|達成|完成|交付|获批|獲批|批准|取得批准|获得批准|獲得批准|收到.{0,15}积极意见|收到.{0,15}積極意見)|^(?:(?:hereby|today|has|have|had|is|was|now|announces|announced|confirms|confirmed|that|it)\s+){0,8}(?:signed|entered into|completed|delivered|obtained|received|secured)\b',re.I)
_ANCHOR_RE=re.compile(r'合作|协议|協議|合同|订单|訂單|批准|许可|許可|交付|临床|臨床|主要终点|主要終點|\b(?:agreement|contract|orders?|approval|licen[cs]e|delivery|endpoint|opinion|CHMP)\b',re.I)


def classify_pages(pages: Sequence[Mapping[str,Any]], *, symbol: str, name: str) -> list[dict]:
    """Conservative official-issuer actions, never a title or industry sentiment.

    Raw offsets remain in each original page. An explicit issuer subject (or
    the document's bound 'the Company') is required. Relative clauses, peers,
    conditional risks and unresolved pronouns stay in the audit/index lane.
    Negative disclosure is retained separately, not inverted into a catalyst.
    """
    subject=re.compile(r'^\s*('+re.escape(name)+r'|本公司|本集团|本集團|the company|the group)(?=$|[^A-Za-z])',re.I)
    out=[]
    for page in pages:
        text=str(page['text'])
        # Periods preceding a capital start a new English sentence; decimals do not.
        sentence_re=re.compile(r'.+?(?:[。；;!?！？]|\.(?=\s+[A-Z]|$)|(?=\n(?:The Company|The Group|本公司|本集团|本集團|'+re.escape(name)+r'))|$)',re.S)
        for sentence in sentence_re.finditer(text):
            sentence_text=sentence.group()
            # Explicit contrast permits independent positive and negative actions.
            for chunk in re.finditer(r'[^，,]+',sentence_text):
                raw=chunk.group();trim=re.match(r'\s*(?:(?:但是|但|but|however)\s*)?',raw,re.I).end()
                start=sentence.start()+chunk.start()+trim;end=sentence.start()+chunk.end()
                quote=text[start:end].strip();end=start+len(quote)
                if not quote:continue
                match=subject.match(quote)
                action=quote[match.end():].lstrip(' ：:，,') if match else quote
                disposition='PENDING_REVIEW';reason='NO_RELIABLE_ISSUER_ACTION';polarity='UNRESOLVED'
                if match:
                    flattened=re.sub(r'\s+', ' ',action)
                    local=re.sub(r'^(?:(?:hereby|today|has|have|had|is|was|now|announces|announced|confirms|confirmed|that|it)\s+|(?:现|現|已|正式|宣布|宣佈|公告|表示|确认|確認)[\s：:]*){0,8}', '',flattened,flags=re.I)
                    if re.search(r'并非没有|並非沒有|不是没有|否认.{0,12}(?:没有|未)|\bnot\s+(?:un|without)|\bdenies?\b.{0,25}\bnot\b',action,re.I):
                        reason='DOUBLE_NEGATION_SCOPE_UNRESOLVED'
                    elif _UNCERTAIN.search(action):reason='CONDITIONAL_OR_EXPECTATION_NOT_OBSERVED'
                    elif re.match(r"(?:['’]s\s|的|客户|客戶|参股|參股|投资|投資|invested|investment|and\b|its\s|the\s+(?:customer|supplier|partner|subsidiary))",local,re.I):
                        reason='RELATED_PARTY_OR_COMPOUND_SUBJECT_ACTION_UNRESOLVED'
                    elif re.search(r'前者|后者|後者|the latter|the former',action,re.I):reason='PRONOUN_ACTION_UNRESOLVED'
                    elif _NEG.search(flattened):
                        disposition='CLARIFICATION';reason='NEGATED_OR_NOT_YET_DISCLOSURE';polarity='NEGATED'
                    elif _ADVERSE.match(local):
                        disposition='RISK_REVIEW';reason='ISSUER_ADVERSE_OR_TERMINATION_STATEMENT';polarity='AFFIRMED'
                    elif re.match(r'is pleased to announce that the Committee for Medicinal Products for Human Use \(CHMP\) of the European Medicines Agency \(EMA\) has adopted a positive opinion',flattened,re.I) and not re.search(r'\b(?:customer|client|peer)\b',flattened,re.I):
                        disposition='POSITIVE_OBSERVATION';reason='ISSUER_REGULATORY_OPINION_DISCLOSURE_NOT_FINAL_APPROVAL';polarity='AFFIRMED'
                    elif _POSITIVE.search(flattened) and _ANCHOR_RE.search(flattened):
                        disposition='POSITIVE_OBSERVATION';reason='ISSUER_LOCAL_ACTION_NOT_PRICE_IMPACT';polarity='AFFIRMED'
                out.append(dict(disposition=disposition,reason=reason,polarity=polarity,
                    action_subject=symbol if match and disposition!='PENDING_REVIEW' else None,
                    page=page['page'],source_field='pdf_page_text',quote=quote,start=start,end=end,
                    subject_quote=match.group().strip() if match else None,
                    action_quote=action,context_quote=sentence_text,
                    context_start=sentence.start(),context_end=sentence.end(),parser_revision=PARSER_VERSION))
    return out
