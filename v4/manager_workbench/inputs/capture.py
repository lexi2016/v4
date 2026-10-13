"""The existing HKEX full-market directory/body source, after exclusive cutover.

This callable is dormant. The supervisor must supply an exclusive owner lease;
without it no HTTP request or cache write is possible. It never changes shared
HK prices, eligibility, Stage or the old research plan. Mirror bodies remain a
separate native corpus input, never claimed as official publication time.
"""
from __future__ import annotations
from datetime import datetime
import json
from urllib.parse import urlencode,urljoin,urlsplit
import requests
from ..contracts import Coverage,EvidenceRef,Lane,HK
from .validation import batch,raw_sha,symbol,time_value

ENDPOINT="https://www1.hkexnews.hk/search/titleSearchServlet.do"


def _official(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname not in {'www1.hkexnews.hk','www.hkexnews.hk'} or parts.username or parts.password:
        raise ValueError('HKEX_SOURCE_URL_INVALID')
    return url


def capture_announcements(context, request, cache):
    """Fetch full observed directory pages, then all bounded bodies with gaps.

    cache supplies assert_exclusive_owner(owner), read_response(url), and
    save_response(url, body, captured_at); optional parse_pdf(body) must return
    every page with complete=True. Transport may be injected for isolated tests.
    """
    owner='v4.manager_workbench.capture_announcements'
    if not callable(getattr(cache,'assert_exclusive_owner',None)):
        raise ValueError('ANNOUNCEMENT_EXCLUSIVE_OWNER_NOT_BOUND')
    cache.assert_exclusive_owner(owner)
    start=request.get('from_date');end=request.get('to_date')
    from ..contracts import validate_date
    validate_date(start);validate_date(end)
    cutoff=time_value(context.cutoff)
    if start>end or end>cutoff.astimezone(HK).strftime('%Y%m%d'):
        raise ValueError('ANNOUNCEMENT_CAPTURE_WINDOW_INVALID')
    max_pages=request.get('max_pages',24);max_bodies=request.get('max_bodies',1000)
    if type(max_pages) is not int or not 1<=max_pages<=100 or type(max_bodies) is not int or not 0<=max_bodies<=5000:
        raise ValueError('ANNOUNCEMENT_CAPTURE_BUDGET_INVALID')
    session=request.get('transport') or requests.Session()
    def read(url):
        _official(url)
        cached=cache.read_response(url)
        if cached is not None:return cached
        cache.assert_exclusive_owner(owner)
        response=session.get(url,timeout=(5,20),allow_redirects=False)
        if response.status_code!=200:raise ValueError('HKEX_HTTP_UNAVAILABLE')
        raw=response.content
        if len(raw)>48*1024*1024:raise ValueError('HKEX_RESPONSE_TOO_LARGE')
        captured=datetime.now(HK).isoformat()
        cache.save_response(url,raw,captured)
        return raw,captured
    observed={};refs=[];gaps=[];scope_count=None;exhausted=False
    for page in range(max_pages):
        query=dict(sortDir=0,sortByOptions='DateTime',category=0,market='SEHK',stockId='',documentType=-1,
            fromDate=start,toDate=end,title='',searchType=0,t1code=-2,t2Gcode=-2,t2code=-2,rowRange=page*100,lang='ZH')
        url=ENDPOINT+'?'+urlencode(query)
        try:
            raw,captured=read(url);data=json.loads(raw);rows=data.get('result',[])
            if isinstance(rows,str):rows=json.loads(rows)
            if not isinstance(rows,list):raise ValueError('HKEX_DIRECTORY_SHAPE_INVALID')
            total=int(data.get('recordCnt',data.get('recordCount',rows[0].get('TOTAL_COUNT') if rows else 0)))
            if scope_count is not None and total!=scope_count:gaps.append('HKEX_DIRECTORY_COUNT_DRIFT')
            scope_count=total
            sha=raw_sha(raw);ref=EvidenceRef(evidence_id='HKEX_DIRECTORY:'+sha,owner=owner,role='FULL_MARKET_DIRECTORY_PAGE',
                source_date=end,sha256=sha,available_at=captured,captured_at=captured,source_url=url,
                artifact_ref='cached-http:'+sha,verification='VERIFIED')
            refs.append(ref)
            prior=len(observed)
            for row in rows:
                event=str(row.get('NEWS_ID') or '')
                if not event.isascii() or not event.isdigit():gaps.append('HKEX_DIRECTORY_EVENT_ID_INVALID');continue
                if event in observed:
                    if observed[event]['raw']!=row:gaps.append('HKEX_DIRECTORY_EVENT_CONFLICT')
                    continue
                observed[event]={'raw':row,'directory_evidence_id':ref.evidence_id}
            if len(observed)==scope_count:exhausted=True;break
            if len(observed)==prior:gaps.append('HKEX_DIRECTORY_PAGINATION_NOT_ADVANCING');break
        except (OSError,ValueError,requests.RequestException):
            gaps.append('HKEX_DIRECTORY_PAGE_UNAVAILABLE');break
    if not exhausted:gaps.append('HKEX_DIRECTORY_COVERAGE_UNVERIFIED')
    records=[]
    for index,(event,item) in enumerate(observed.items()):
        raw=item['raw'];url=urljoin('https://www1.hkexnews.hk',str(raw.get('FILE_LINK') or ''))
        symbols=[symbol(s.strip()) for s in str(raw.get('STOCK_CODE') or '').split(',')]
        pages=[];available=None;source_sha=None;body_gaps=[]
        if index>=max_bodies:body_gaps.append('ANNOUNCEMENT_BODY_CAPTURE_PENDING')
        else:
            try:
                body,available=read(url);source_sha=raw_sha(body)
                parser=getattr(cache,'parse_pdf',None)
                if not body.startswith(b'%PDF') or not callable(parser):raise ValueError('PDF_PARSER_UNAVAILABLE')
                parsed=parser(body)
                if parsed.get('complete') is not True or len(parsed.get('pages',[]))!=parsed.get('page_count'):
                    raise ValueError('PDF_PAGE_COVERAGE_UNKNOWN')
                pages=parsed['pages']
            except (ValueError,OSError,requests.RequestException):body_gaps.append('ANNOUNCEMENT_BODY_UNAVAILABLE_OR_UNPARSED')
        text='\n'.join(p.get('text','') for p in pages)
        if source_sha:
            ref=EvidenceRef(evidence_id='HKEX_BODY:'+source_sha,owner=owner,role='ANNOUNCEMENT_BODY',
                source_date=end,sha256=source_sha,available_at=available,source_url=url,artifact_ref='cached-http:'+source_sha,
                verification='VERIFIED' if not body_gaps else 'CANNOT_CONFIRM',gaps=body_gaps)
            refs.append(ref)
        for sym in symbols:
            if not sym:continue
            records.append(dict(market='HK_CONNECT',target_date=context.target_date,symbol=sym,name=raw.get('STOCK_NAME'),
                owner=owner,article_id='HKEX:'+event+':'+sym,body=text,body_sha256=raw_sha(text.encode()) if text else None,
                source_sha256=source_sha,available_at=available,observed_at=available,source_url=url,
                body_complete=bool(pages) and not body_gaps,is_pdf=True,source_pages_complete=bool(pages) and not body_gaps,
                source_page_count=len(pages),segments=[dict(index=i,count=len(pages),page_number=i+1,
                    text=p['text']+('\n' if i+1<len(pages) else '')) for i,p in enumerate(pages)],
                membership=None,evidence_ids=[item['directory_evidence_id']]+(['HKEX_BODY:'+source_sha] if source_sha else []),
                gaps=body_gaps,published_at=raw.get('DATE_TIME'),title=raw.get('TITLE')))
    gaps.append('MONTHLY_CONNECT_MEMBERSHIP_MUST_BE_BOUND_BY_NATIVE_ADAPTER')
    return batch(context,Lane.ANNOUNCEMENT,records,refs,'Original HKEX official full-market observed directory source',
        Coverage(scope_count=scope_count,observed_count=len(observed),gaps=gaps),gaps,'HKEX_CAPTURE:'+end)
