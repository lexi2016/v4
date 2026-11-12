"""Original HKEX provider's executed-directory adapter, with conservative pagination.

The uploaded HTTP200 pages are JS search shells, not executed zero-result pages.
A fallback is permitted only after the same official transport retrieves the
research script actually referenced by the shell and its source binds the
allowlisted GET servlet. No JS is executed; no third-party endpoint, challenge
bypass or new HTTP client is used. JSON positive fixtures are synthetic;
native protocol acceptance is a Mac gate.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from html import unescape
from typing import Mapping, Any, Callable
from urllib.parse import urlencode, urljoin, urlparse, unquote
import json
import re

LEGACY_PROTOCOL='HKEX_SERVLET_CUMULATIVE_V1'
PROTOCOL='HKEX_SERVLET_ALL_SELECTION_V2'
SELECTION_SCRIPT_URL='https://www1.hkexnews.hk/ncms/js/titlesearch.js'
# Reviewed official source: ALL -> ResetDocumentTypeDDL/ResetHeadlineDDL.
# New/changed source must be reviewed; a syntactically valid script is not enough.
SELECTION_SCRIPT_SHA256='abba9c4103523220e47ba1436487872b0069d487ee3e3cb12ae7d909303a4817'
RESEARCH_SCRIPT_PATH='/ncms/js/titlesearch_research.js'
RESEARCH_SCRIPT_URL='https://www1.hkexnews.hk'+RESEARCH_SCRIPT_PATH
SERVLET_URL='https://www1.hkexnews.hk/search/titleSearchServlet.do'
RANGES=(100,300,600,1000,2000)
HK=timezone(timedelta(hours=8))


def is_search_shell(raw: bytes) -> bool:
    from html.parser import HTMLParser
    from .hkex_provider import TITLE_SEARCH_URL
    class Shell(HTMLParser):
        def __init__(self):
            super().__init__(); self.empty_flag=False; self.forms=[]; self.config=False; self.result_cell=False; self.scripts=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='input' and a.get('id')=='displayResultTable':
                self.empty_flag=a.get('value','')==''
            if tag=='form':
                # Match literal endpoints, not a normalized path or arbitrary suffix.
                # The optional session token is routing metadata, never a new URL.
                action=a.get('action') or ''
                endpoint=any(re.fullmatch(re.escape(base)+r'(?:;jsessionid=[-A-Za-z0-9][A-Za-z0-9._-]{0,255})?',action)
                             for base in (urlparse(TITLE_SEARCH_URL).path,TITLE_SEARCH_URL))
                self.forms.append(bool(endpoint and len(attrs)==len(a) and a.get('id')
                                       and a.get('name')==a['id'] and (a.get('method') or '').lower()=='post'))
            if tag=='script' and a.get('src'):
                self.scripts.append(a['src'])
                if a.get('src')=='/ncms/eds/titlesearch/config.js':self.config=True
            if tag=='td' and 'release-time' in str(a.get('class','')).split():self.result_cell=True
    p=Shell();p.feed(raw.decode('utf-8',errors='replace'))
    research_scripts=[urljoin(TITLE_SEARCH_URL,src) for src in p.scripts
                      if urlparse(urljoin(TITLE_SEARCH_URL,src)).path==RESEARCH_SCRIPT_PATH]
    return (p.empty_flag and p.forms==[True] and p.config and not p.result_cell
            and research_scripts==[RESEARCH_SCRIPT_URL])


def research_script_request(page: bytes,context: Mapping[str,Any]) -> dict:
    """Bind a GET to the one research script named by the captured search page."""
    from html.parser import HTMLParser
    from .hkex_provider import TITLE_SEARCH_URL
    class Scripts(HTMLParser):
        def __init__(self):super().__init__();self.sources=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script':
                src=dict(attrs).get('src')
                if src:self.sources.append(src)
    parser=Scripts();parser.feed(page.decode('utf-8',errors='replace'))
    urls=[urljoin(TITLE_SEARCH_URL,src) for src in parser.sources
          if urlparse(urljoin(TITLE_SEARCH_URL,src)).path==RESEARCH_SCRIPT_PATH]
    if urls!=[RESEARCH_SCRIPT_URL]:raise ValueError('HKEX_OFFICIAL_RESEARCH_SCRIPT_UNCONFIRMED')
    start,end=_aware(context['focus_window_start']),_aware(context['research_cutoff'])
    return dict(url=urls[0],method='GET',referer=TITLE_SEARCH_URL,
                context=dict(since=start.isoformat(),as_of=end.isoformat()))


def selection_script_request(page: bytes, context: Mapping[str,Any]) -> dict:
    """Bind ALL-selection semantics to the main script referenced by this page."""
    from html.parser import HTMLParser
    from .hkex_provider import TITLE_SEARCH_URL
    class Scripts(HTMLParser):
        def __init__(self):super().__init__();self.sources=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script' and dict(attrs).get('src'):
                self.sources.append(urljoin(TITLE_SEARCH_URL,dict(attrs)['src']))
    parser=Scripts();parser.feed(page.decode('utf-8',errors='strict'))
    urls=[url for url in parser.sources if urlparse(url).path=='/ncms/js/titlesearch.js']
    if urls!=[SELECTION_SCRIPT_URL]:raise ValueError('HKEX_OFFICIAL_SELECTION_SCRIPT_UNCONFIRMED')
    start,end=_aware(context['focus_window_start']),_aware(context['research_cutoff'])
    return dict(url=urls[0],method='GET',referer=TITLE_SEARCH_URL,
                context=dict(since=start.isoformat(),as_of=end.isoformat()))


def attest_selection_script(raw: bytes) -> None:
    from hashlib import sha256
    if sha256(raw).hexdigest()!=SELECTION_SCRIPT_SHA256:
        raise ValueError('HKEX_ALL_SELECTION_SCRIPT_CHANGED')


def _protocol(q: Mapping[str,Any]) -> str:
    value=q.get('directory_protocol')
    if value not in (PROTOCOL,LEGACY_PROTOCOL):
        raise ValueError('HKEX_DIRECTORY_PROTOCOL_INVALID')
    if value==LEGACY_PROTOCOL and (q.get('selection_script_ref') is not None or q.get('form_directory_ref') is not None):
        raise ValueError('HKEX_LEGACY_SELECTION_REFERENCE_UNEXPECTED')
    return value


def servlet_from_research_script(raw: bytes) -> str:
    if len(raw)>2_000_000: raise ValueError('HKEX_PROTOCOL_SCRIPT_TOO_LARGE')
    text=raw.decode('utf-8',errors='strict')
    route=re.search(r"\bthis\.titleSearchServletPath\s*=\s*(['\"])titleSearchServlet\.do\1\s*;",text)
    ajax=re.search(r"\$\s*\.\s*ajax\s*\(\s*\{(.*?)\}\s*\)\s*;?",text,re.S)
    if not route or not ajax:
        raise ValueError('HKEX_OFFICIAL_SEARCH_PROTOCOL_UNCONFIRMED')
    request=ajax.group(1)
    if not re.search(r"\btype\s*:\s*(['\"])GET\1",request) or not re.search(r"\burl\s*:\s*titleSearchServletPath\b",request):
        raise ValueError('HKEX_OFFICIAL_SEARCH_PROTOCOL_UNCONFIRMED')
    data=re.search(r"\bdata\s*:\s*\{(.*?)\}",request,re.S)
    expected=(('sortDir','sortDir'),('sortByOptions','sortBy'),('category','category'),
        ('market','market'),('stockId','stockId'),('documentType','documentType'),
        ('fromDate','fromDate'),('toDate','toDate'),('title','title'),('searchType','searchType'),
        ('t1code','t1code'),('t2Gcode','t2Gcode'),('t2code','t2code'),
        ('rowRange','currLoadRecordCnt'),('lang','lang'))
    if not data or any(not re.search(r'\b'+key+r'\s*:\s*'+value+r'\b',data.group(1)) for key,value in expected):
        raise ValueError('HKEX_OFFICIAL_SEARCH_PROTOCOL_UNCONFIRMED')
    return SERVLET_URL


def _aware(value: str) -> datetime:
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('HKEX_QUERY_CLOCK_TIMEZONE_REQUIRED')
    return dt.astimezone(HK)


def _query_bounds(issuer,context,limit):
    stock_id=str(issuer.get('stock_id',''))
    if not re.fullmatch(r'[1-9][0-9]*',stock_id) or limit not in RANGES:
        raise ValueError('HKEX_SERVLET_QUERY_ID_OR_LIMIT_INVALID')
    start,end=_aware(context['focus_window_start']),_aware(context['research_cutoff'])
    if not start < end or (end-start).days>370:raise ValueError('HKEX_SERVLET_QUERY_WINDOW_INVALID')
    return stock_id,start,end


def servlet_request(issuer: Mapping[str,Any],context: Mapping[str,Any],limit: int, *,
                    protocol: str = PROTOCOL, form_raw: bytes | None = None) -> dict:
    from .hkex_provider import TITLE_SEARCH_URL
    stock_id,start,end=_query_bounds(issuer,context,limit)
    if protocol not in (PROTOCOL,LEGACY_PROTOCOL):raise ValueError('HKEX_DIRECTORY_PROTOCOL_INVALID')
    criteria=dict(category=0,stockId=stock_id,documentType=-1,
        fromDate=start.strftime('%Y%m%d'),toDate=end.strftime('%Y%m%d'),title='',searchType=0,
        t1code=-2,t2Gcode=-2,t2code=-2,lang='E')
    if protocol==PROTOCOL:
        if not isinstance(form_raw,bytes):raise ValueError('HKEX_ALL_FORM_ECHO_REQUIRED')
        echo=attest_form_echo(form_raw,issuer,context)
        # Official getTitleSearchCriteria reads these returned IDs, NOT the POST.
        criteria=dict(category=echo['selectedSecurities'],stockId=echo['stockId'],
            documentType=echo['selectedDocType'],fromDate=echo['startDate'].replace('-',''),
            toDate=echo['endDate'].replace('-',''),title=echo['newsTitle'],searchType=echo['searchTypeInt'],
            t1code=echo['tierOneId'],t2Gcode=echo['tierTwoGpId'],t2code=echo['tierTwoId'],lang=echo['lang'])
    # Preserve the original parameter order, including immutable legacy requests.
    query=urlencode(dict(sortDir=0,sortByOptions='DateTime',category=criteria['category'],market='SEHK',
        stockId=criteria['stockId'],documentType=criteria['documentType'],fromDate=criteria['fromDate'],
        toDate=criteria['toDate'],title=criteria['title'],searchType=criteria['searchType'],
        t1code=criteria['t1code'],t2Gcode=criteria['t2Gcode'],t2code=criteria['t2code'],rowRange=limit,lang=criteria['lang']))
    return dict(url=SERVLET_URL+'?'+query,method='GET',referer=TITLE_SEARCH_URL,
                context=dict(since=start.isoformat(),as_of=end.isoformat()),protocol=protocol)


def _pairs(pairs):
    out={}
    for k,v in pairs:
        if k in out:raise ValueError('HKEX_DIRECTORY_DUPLICATE_JSON_KEY')
        out[k]=v
    return out


def decode_page(raw: bytes,symbol: str,context: Mapping[str,Any],limit: int) -> dict:
    from .hkex_provider import _safe_official_url
    if len(raw)>8_000_000:raise ValueError('HKEX_DIRECTORY_BYTES_EXCEEDED')
    if not re.fullmatch(r'HK\.\d{5}',symbol) or limit not in RANGES:
        raise ValueError('HKEX_DIRECTORY_ID_INVALID')
    try:
        obj=json.loads(raw,object_pairs_hook=_pairs)
        if (not isinstance(obj,dict) or type(obj.get('hasNextRow')) is not bool
                or type(obj.get('rowRange')) is not int or obj['rowRange']!=limit or obj.get('lang')!='E'):
            raise ValueError('HKEX_DIRECTORY_EXECUTED_ENVELOPE_UNVERIFIED')
        if any(type(obj.get(key)) is not int or obj[key]<0 for key in ('loadedRecord','recordCnt')):
            raise ValueError('HKEX_DIRECTORY_COUNTERS_INVALID')
        result=obj.get('result')
        if not isinstance(result,str):raise ValueError('HKEX_DIRECTORY_RESULT_JSON_STRING_REQUIRED')
        rows=json.loads(result,object_pairs_hook=_pairs)
        if not isinstance(rows,list) or len(rows)>limit:
            raise ValueError('HKEX_DIRECTORY_ROW_COUNT_INVALID')
        if not rows and (obj['hasNextRow'] or obj['loadedRecord']!=0 or obj['recordCnt']!=0):
            raise ValueError('HKEX_DIRECTORY_EMPTY_RESPONSE_COUNTER_MISMATCH')
    except (UnicodeError,json.JSONDecodeError,TypeError) as exc:
        raise ValueError('HKEX_DIRECTORY_JSON_INVALID') from exc
    start,end=_aware(context['focus_window_start']),_aware(context['research_cutoff'])
    normalized=[];ids=set();urls=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('HKEX_DIRECTORY_ROW_INVALID')
        news=str(row.get('NEWS_ID',''))
        if not re.fullmatch(r'\d+',news) or news in ids:raise ValueError('HKEX_DIRECTORY_NEWS_ID_INVALID_OR_DUPLICATE')
        codes=[s for s in re.split(r'<br\s*/?>|\s+|,',str(row.get('STOCK_CODE',''))) if s]
        if not codes or any(not re.fullmatch(r'\d{5}',c) for c in codes) or symbol[3:] not in codes or len(codes)!=len(set(codes)):
            raise ValueError('HKEX_DIRECTORY_ISSUER_MISMATCH')
        href=row.get('FILE_LINK')
        if not isinstance(href,str):raise ValueError('HKEX_DIRECTORY_DOCUMENT_URL_INVALID')
        url=urljoin(SERVLET_URL,unescape(href));parts=urlparse(url);path=unquote(parts.path)
        if (not _safe_official_url(url) or not path.startswith('/listedco/listconews/')
                or '..' in path.split('/') or parts.query or url in urls):
            raise ValueError('HKEX_DIRECTORY_DOCUMENT_URL_INVALID_OR_DUPLICATE')
        try:
            published=datetime.strptime(str(row.get('DATE_TIME','')),'%d/%m/%Y %H:%M').replace(tzinfo=HK)
        except ValueError as exc:raise ValueError('HKEX_DIRECTORY_PUBLICATION_INVALID') from exc
        if not start.date() <= published.date() <= end.date():raise ValueError('HKEX_DIRECTORY_DATE_RANGE_MISMATCH')
        title=row.get('TITLE');name=row.get('STOCK_NAME')
        if not isinstance(title,str) or not title.strip() or not isinstance(name,str) or not name.strip():
            raise ValueError('HKEX_DIRECTORY_TITLE_OR_NAME_INVALID')
        ids.add(news);urls.add(url)
        normalized.append(dict(published_at=published.isoformat(timespec='minutes'),release_time=row['DATE_TIME'],
            stock_code=symbol[3:],stock_name=unescape(name),source_stock_codes=codes,news_id=news,
            headline=unescape(str(row.get('LONG_TEXT',''))),document_title=unescape(title),url=url))
    # Cumulative query is frozen to an immutable cutoff; stable order/prefix is checked between requests.
    return {'rows':normalized,'has_next':obj['hasNextRow'],'row_range':limit}


def filter_rows(rows,symbol,context):
    start,end=_aware(context['focus_window_start']),_aware(context['research_cutoff'])
    retained=[];rejected=[]
    for row in rows:
        published=_aware(row['published_at'])
        reason=('AT_OR_BEFORE_WINDOW_START' if published<=start else
                'PUBLICATION_AFTER_QUERY_CUTOFF' if published>end else None)
        if reason:rejected.append({'reason':reason,'row':row})
        else:retained.append(row)
    return sorted(retained,key=lambda x:(x['published_at'],x['url'])),rejected,(
        'OBSERVED_DIRECTORY_ROWS' if rows else 'NO_ROWS_IN_OBSERVED_RESPONSE')


def _captured_form_raw(q,context,read):
    if _protocol(q)==LEGACY_PROTOCOL:return None
    ref=q.get('form_directory_ref')
    if (not isinstance(ref,dict) or ref.get('http_status')!=200
            or ref.get('request')!=all_form_request(q['official_issuer'],context)):
        raise ValueError('HKEX_ALL_FORM_REQUEST_BINDING_INVALID')
    return read(ref)


def _state_from_pages(q,context,read:Callable) -> tuple[list, bool]:
    pages=q.get('directory_pages');previous=[];terminal=False
    if not isinstance(pages,list) or not 1<=len(pages)<=len(RANGES):
        raise ValueError('HKEX_DIRECTORY_PAGE_CHAIN_INVALID')
    form_raw=_captured_form_raw(q,context,read)
    for index,ref in enumerate(pages):
        if terminal:raise ValueError('HKEX_DIRECTORY_PAGE_AFTER_TERMINAL')
        limit=RANGES[index]
        if ref['request']!=servlet_request(q['official_issuer'],context,limit,protocol=_protocol(q),form_raw=form_raw):
            raise ValueError('HKEX_DIRECTORY_REQUEST_BINDING_MISMATCH')
        raw=read(ref)
        if ref['http_status']!=200:raise ValueError('ANNOUNCEMENT_DIRECTORY_HTTP_FAILED')
        page=decode_page(raw,q['code'],context,limit);rows=page['rows']
        if rows[:len(previous)]!=previous:raise ValueError('HKEX_DIRECTORY_CUMULATIVE_PREFIX_CHANGED')
        if index and page['has_next'] and len(rows)<=len(previous):
            raise ValueError('HKEX_DIRECTORY_PAGINATION_NO_PROGRESS')
        # At an exact range boundary confirm again at a larger range, even if hasNextRow says false.
        terminal=not page['has_next'] and len(rows)<limit
        previous=rows
    return previous,terminal


def all_form_request(issuer, context):
    """Actual TitleSearchPanel ALL form, attested by the pinned official script.

    The posted form and server's echoed criteria are separate evidence. Never
    assume the browser's reset values were echoed without checking the HTML.
    """
    from .hkex_provider import TITLE_SEARCH_URL
    # Same identity/range checks, without inventing an echo for a not-yet-posted form.
    _,since,as_of=_query_bounds(issuer,context,RANGES[0])
    form=urlencode(dict(lang='EN',category='0',market='SEHK',searchType='0',
        documentType='',t1code='',t2Gcode='',t2code='',stockId=issuer['stock_id'],
        **{'from':since.strftime('%Y%m%d'),'to':as_of.strftime('%Y%m%d')},title=''))
    from base64 import b64encode
    return dict(url=TITLE_SEARCH_URL+'?lang=en',method='POST',body_b64=b64encode(form.encode('ascii')).decode(),referer=TITLE_SEARCH_URL,
                context=dict(since=since.isoformat(),as_of=as_of.isoformat()))


def attest_form_echo(raw, issuer, context):
    """Require actual server echoes, not an invented intermediate browser DOM."""
    from html.parser import HTMLParser
    expected={'stockId':str(issuer['stock_id']), 'searchTypeInt':'0','selectedSecurities':'0',
       'selectedDocType':'','tierOneId':'','tierTwoGpId':'','tierTwoId':'','newsTitle':'','lang':'E',
       'startDate':_aware(context['focus_window_start']).strftime('%Y-%m-%d'),
       'endDate':_aware(context['research_cutoff']).strftime('%Y-%m-%d')}
    class Inputs(HTMLParser):
        def __init__(self):super().__init__();self.values={}
        def handle_starttag(self,tag,attrs):
            a=dict(attrs);key=a.get('id')
            if tag=='input' and any(k=='id' and v in expected for k,v in attrs):
                if len(attrs)!=len(a) or a.get('type')!='hidden':
                    raise ValueError('HKEX_FORM_ECHO_AMBIGUOUS_INPUT')
                if key in self.values:raise ValueError('HKEX_FORM_ECHO_DUPLICATE')
                # HTML input.value is empty when the value attribute is absent.
                # The input element itself must still exist exactly once.
                self.values[key]=a.get('value','')
    p=Inputs();p.feed(raw.decode('utf-8',errors='strict'))
    # Keep the complete unnormalized representation for compatibility; the new
    # complete sentinel vector is witnessed in the immutable HK.00002/3 POSTs.
    # Never accept per-field mixtures, arbitrary filters, or a different scope.
    normalized={**expected,'selectedDocType':'-1','tierOneId':'-2','tierTwoGpId':'-2','tierTwoId':'-2'}
    if p.values not in (expected,normalized):raise ValueError('HKEX_ALL_FORM_ECHO_MISMATCH')
    return p.values


def capture_servlet_query(provider,q:dict,context,budget=None):
    """Capture witnessed ALL form, validate returned criteria, then execute GET."""
    from .announcement_source import capture,read_response
    q.update(directory_protocol=PROTOCOL,directory_pages=[],directory_exhaustion_verified=False,
             legacy_directory_ref=q.get('directory_ref'),directory_ref=None,protocol_ref=None,
             selection_script_ref=None,form_directory_ref=None)
    page_raw=read_response(provider._material_store,q['legacy_directory_ref'])
    def acquire(field,request,http_error):
        q['pending_protocol_request']=request
        q[field]=capture(provider,request,budget=budget)
        q.pop('pending_protocol_request',None)
        if q[field]['http_status']!=200:raise ValueError(http_error)
        return read_response(provider._material_store,q[field])
    main=acquire('selection_script_ref',selection_script_request(page_raw,context),'HKEX_SELECTION_SCRIPT_HTTP_FAILED')
    attest_selection_script(main)
    form_raw=acquire('form_directory_ref',all_form_request(q['official_issuer'],context),'HKEX_ALL_FORM_HTTP_FAILED')
    attest_form_echo(form_raw,q['official_issuer'],context)
    script=acquire('protocol_ref',research_script_request(form_raw,context),'HKEX_PROTOCOL_SCRIPT_HTTP_FAILED')
    servlet_from_research_script(script)
    previous=[];terminal=False
    for limit in RANGES:
        request=servlet_request(q['official_issuer'],context,limit,form_raw=form_raw)
        q['pending_protocol_request']=request
        ref=capture(provider,request,budget=budget)
        q.pop('pending_protocol_request',None)
        q['directory_pages'].append(ref);q['directory_ref']=ref
        rows,terminal=_state_from_pages(q,context,lambda r:read_response(provider._material_store,r))
        previous=rows
        if terminal:break
    entries,rejected,reason=filter_rows(previous,q['code'],context)
    q.update(entries=entries,rejected=rejected,reason=reason,status='OBSERVED',directory_exhaustion_verified=terminal)


def _attest_query_sources(q,context,checked,legacy_raw):
    """Return first uncaptured request; a missing step cannot be jumped over."""
    if _protocol(q)==LEGACY_PROTOCOL:
        steps=[('protocol_ref',lambda:research_script_request(legacy_raw,context),
                servlet_from_research_script,'HKEX_PROTOCOL_SCRIPT_HTTP_FAILED')]
    else:
        state={}
        def form_check(raw):
            attest_form_echo(raw,q['official_issuer'],context);state['form_raw']=raw
        steps=[('selection_script_ref',lambda:selection_script_request(legacy_raw,context),
                attest_selection_script,'HKEX_SELECTION_SCRIPT_HTTP_FAILED'),
               ('form_directory_ref',lambda:all_form_request(q['official_issuer'],context),
                form_check,'HKEX_ALL_FORM_HTTP_FAILED'),
               ('protocol_ref',lambda:research_script_request(state['form_raw'],context),
                servlet_from_research_script,'HKEX_PROTOCOL_SCRIPT_HTTP_FAILED')]
    for index,(key,expected_fn,attest,http_error) in enumerate(steps):
        expected=expected_fn();ref=q.get(key)
        if ref is None:
            if any(q.get(later[0]) is not None for later in steps[index+1:]) or q.get('directory_pages'):
                raise ValueError('HKEX_PROTOCOL_SOURCE_SEQUENCE_INVALID')
            return expected
        if ref.get('request')!=expected:raise ValueError('HKEX_PROTOCOL_SCRIPT_BINDING_INVALID')
        raw=checked(ref)
        if ref.get('http_status')!=200:raise ValueError(http_error)
        attest(raw)
    return None


def revalidate_servlet_query(q,context,checked):
    """Re-read current and historical captures without network or clock rewrite.

    Legacy acceptance means stored-request integrity only, NOT evidence that
    its -1/-2 filters were equivalent to the official ALL query.
    """
    from .announcement_source import query_request,safe_reason
    protocol=_protocol(q)
    legacy=q.get('legacy_directory_ref')
    expected_shell=query_request(q['official_issuer'],context)
    if protocol==PROTOCOL:
        expected_shell=dict(url=expected_shell['referer'],method='GET',
                            context=expected_shell['context'],cache_policy='SESSION_PRIME')
        if legacy!=q.get('prime_ref'):raise ValueError('HKEX_DIRECTORY_SHELL_BINDING_INVALID')
    if not legacy or legacy['request']!=expected_shell or legacy['http_status']!=200:
        raise ValueError('HKEX_DIRECTORY_SHELL_BINDING_INVALID')
    legacy_raw=checked(legacy)
    if not is_search_shell(legacy_raw):raise ValueError('HKEX_DIRECTORY_SHELL_NOT_REPRODUCIBLE')
    pages=q.get('directory_pages')
    if not isinstance(pages,list) or q.get('directory_ref') != (pages[-1] if pages else None):
        raise ValueError('HKEX_DIRECTORY_LAST_PAGE_BINDING_MISMATCH')
    failure=q.get('capture_failure')
    if failure is not None:
        if (not isinstance(failure,dict)
                or set(failure)!={'request','reason','exception_type','outcome'}
                or not isinstance(failure.get('request'),dict)
                or not isinstance(failure.get('reason'),str)
                or failure['reason']!=q.get('reason')
                or not re.fullmatch(r'[A-Z][A-Z0-9_]{3,100}(?::[A-Za-z][A-Za-z0-9_]{0,80})?',str(failure.get('reason','')))
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}',str(failure.get('exception_type','')))):
            raise ValueError('HKEX_CAPTURE_FAILURE_WITNESS_INVALID')
        if (q.get('status')!='FAILED' or q.get('entries') or q.get('rejected')
                or q.get('directory_exhaustion_verified') is not False):
            raise ValueError('HKEX_BUDGET_PARTIAL_QUERY_INVALID')
        budget_reasons={'ANNOUNCEMENT_TIME_BUDGET_EXHAUSTED','ANNOUNCEMENT_REQUEST_BUDGET_EXHAUSTED'}
        if failure.get('outcome')=='BUDGET_REFUSED_BEFORE_PROVIDER_CALL':
            if failure['exception_type']!='CaptureBudgetExpired' or failure['reason'] not in budget_reasons:
                raise ValueError('HKEX_CAPTURE_FAILURE_WITNESS_INVALID')
        elif (failure.get('outcome')!='NO_RESPONSE_REFERENCE_RETURNED'
                or failure['exception_type']=='CaptureBudgetExpired' or failure['reason'] in budget_reasons):
            raise ValueError('HKEX_CAPTURE_FAILURE_WITNESS_INVALID')
        pending=_attest_query_sources(q,context,checked,legacy_raw)
        if pending is None:
            if pages:
                _,terminal=_state_from_pages(q,context,checked)
                if terminal or len(pages)>=len(RANGES):raise ValueError('HKEX_BUDGET_PARTIAL_AFTER_TERMINAL_PAGE')
            pending=servlet_request(q['official_issuer'],context,RANGES[len(pages)],protocol=protocol,
                                    form_raw=_captured_form_raw(q,context,checked))
        if failure['request']!=pending:raise ValueError('HKEX_CAPTURE_FAILURE_REQUEST_MISMATCH')
        return
    try:
        if _attest_query_sources(q,context,checked,legacy_raw) is not None:
            raise ValueError('HKEX_PROTOCOL_SCRIPT_BINDING_INVALID')
        rows,terminal=_state_from_pages(q,context,checked)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
        if (q.get('status')!='FAILED' or q.get('reason')!=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED')
                or q.get('entries') or q.get('rejected') or q.get('directory_exhaustion_verified') is not False):
            raise ValueError('HKEX_FAILED_DIRECTORY_DERIVATION_MISMATCH') from exc
        return
    entries,rejected,reason=filter_rows(rows,q['code'],context)
    if (q.get('status')!='OBSERVED' or q.get('entries')!=entries or q.get('rejected')!=rejected
            or q.get('reason')!=reason or q.get('directory_exhaustion_verified') is not terminal):
        raise ValueError('HKEX_DIRECTORY_DERIVATION_MISMATCH')
