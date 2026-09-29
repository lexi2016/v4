"""Bounded helpers for the EXISTING HkexOfficialProvider, not a new fetcher.

The same MaterialStore retains exact POST directory bytes as well as the
original cached PDFs. Exhaustion of HKEX server-side pagination is deliberately
UNVERIFIED: draining a native-master cursor is not proof of all announcements.
"""
from __future__ import annotations

from base64 import b64encode, b64decode
from copy import deepcopy
from dataclasses import dataclass, field
from time import monotonic, sleep
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from .contracts import canonical_json
from .material_transport import _encode_envelope, _decode_envelope
from .pdf_parser import extract_pdf_pages
from .workspace_projection import timestamp, canonical_symbol, digest

PARSER_VERSION = '20260922.official-subject-polarity.v1'
MAX_DOCUMENTS = 4
MAX_DIRECTORY_ROWS = 2000
MAX_BYTES = 8_000_000



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
    requests: int = 0
    _start: float = field(default_factory=lambda: monotonic())
    _last: float | None = None

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

def _time(value: str) -> datetime:
    dt = timestamp(value)
    if dt is None:
        raise ValueError('ANNOUNCEMENT_TIME_WITH_TIMEZONE_REQUIRED')
    return dt


def window(context: Mapping[str, Any]) -> tuple[datetime, datetime]:
    since, as_of = _time(context['focus_window_start']), _time(context['research_cutoff'])
    if since >= as_of or (as_of - since).days > 31:
        raise ValueError('ANNOUNCEMENT_WINDOW_INVALID')
    return since, as_of


def query_request(issuer: Mapping[str, Any], context: Mapping[str, Any]) -> dict:
    from .hkex_provider import TITLE_SEARCH_URL
    since, as_of = window(context)
    form = urlencode(dict(lang='EN', category='0', market='SEHK', searchType='0',
        documentType='-1', t1code='-2', t2Gcode='-2', t2code='-2', stockId=issuer['stock_id'],
        **{'from': since.strftime('%Y%m%d'), 'to': as_of.strftime('%Y%m%d')}, title=''))
    return dict(url=TITLE_SEARCH_URL, method='POST', body_b64=b64encode(form.encode('ascii')).decode(),
        referer=TITLE_SEARCH_URL+'?'+form, context=dict(since=since.isoformat(),as_of=as_of.isoformat()))


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


def directory_entries(raw: bytes, symbol: str, context: Mapping[str, Any]) -> tuple[list[dict],list[dict],str]:
    from .hkex_provider import parse_title_rows
    since, as_of=window(context)
    parsed=parse_title_rows(raw)
    if len(parsed)>MAX_DIRECTORY_ROWS:
        raise ValueError('ANNOUNCEMENT_DIRECTORY_ROW_BUDGET_EXCEEDED')
    retained=[]; rejected=[]; seen=set()
    for row in parsed:
        published=_time(row['published_at'])
        reason=None
        if row['stock_code']!=symbol.split('.')[1]:reason='DIRECTORY_ISSUER_MISMATCH'
        elif published<=since:reason='AT_OR_BEFORE_WINDOW_START'
        elif published>as_of:reason='PUBLICATION_AFTER_QUERY_CUTOFF'
        key=(row['stock_code'],row['url'])
        if reason is None and key in seen:reason='SAME_OFFICIAL_URL_DUPLICATE'
        if reason:rejected.append(dict(reason=reason,row=row));continue
        seen.add(key);retained.append(row)
    text=raw.decode('utf-8',errors='replace')
    # A parser-empty challenge/login/unknown layout is NOT zero announcements.
    explicit_empty=bool(re.search(r'titlesearch',text,re.I) and re.search(
        r'no (?:records|matching records) found|沒有相關資料|没有相关资料',text,re.I))
    if not parsed and not explicit_empty:
        raise ValueError('ANNOUNCEMENT_DIRECTORY_LAYOUT_OR_EMPTY_UNVERIFIED')
    return sorted(retained,key=lambda x:(x['published_at'],x['url'])),rejected,(
        'NO_ROWS_IN_OBSERVED_RESPONSE' if explicit_empty and not parsed else 'OBSERVED_DIRECTORY_ROWS')


def collect_batch(provider: Any, *, context: Mapping[str,Any], issuers: Sequence[Mapping[str,Any]],
                  pending_documents: Sequence[Mapping[str,Any]]=(), max_issuers: int = 3,
                  max_documents: int = MAX_DOCUMENTS, budget: CaptureBudget | None = None) -> dict:
    """One bounded increment. Neither Stage nor the positive-event title filter is used."""
    from .hkex_provider import ACTIVE_STOCK_LIST_URL
    if provider._material_store is None or provider._material_transport is None:
        raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_REQUIRED')
    window(context)
    if (type(max_issuers) is not int or not 1 <= max_issuers <= 24
            or type(max_documents) is not int or not 0 <= max_documents <= MAX_DOCUMENTS
            or len(issuers)>max_issuers or len(pending_documents)>10000):
        raise ValueError('ANNOUNCEMENT_BATCH_BOUND_INVALID')
    queries=[];todo=deepcopy(list(pending_documents));docs=[]
    if issuers:
        since,as_of=window(context)
        mapping_ref=capture(provider,dict(url=ACTIVE_STOCK_LIST_URL,method='GET',
            context=dict(since=since.isoformat(),as_of=as_of.isoformat())), budget=budget)
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
                # A current JS shell is not a submitted form. Use its witnessed
                # research GET with the official ALL-selection contract directly;
                # do not send the old -1/-2 form filters and trust an empty result.
                from .hkex_directory_protocol import is_search_shell, capture_servlet_query
                prime_raw=read_response(provider._material_store,q['prime_ref'])
                if q['prime_ref']['http_status']==200 and is_search_shell(prime_raw):
                    q['directory_ref']=q['prime_ref']
                    capture_servlet_query(provider,q,context,budget)
                    ref=q['directory_ref'];found=q['entries']
                else:
                    # Preserve the pre-JS HTML path; an unrecognized response
                    # still cannot become an empty-success result.
                    ref=capture(provider,req,budget=budget);q['directory_ref']=ref
                    raw=read_response(provider._material_store,ref)
                    if not 200<=ref['http_status']<300:raise ValueError('ANNOUNCEMENT_DIRECTORY_HTTP_FAILED')
                    if is_search_shell(raw):raise ValueError('HKEX_PRIME_SEARCH_SHELL_UNCONFIRMED')
                    found,rejected,reason=directory_entries(raw,symbol,context)
                    q.update(status='OBSERVED',entries=found,rejected=rejected,reason=reason)
                for row in found:todo.append(dict(code=symbol,name=issuer['name'],row=row,
                    directory_ref=ref,mapping_ref=mapping_ref,official_issuer=match))
            except CaptureBudgetExpired as exc:
                # Keep this issuer's actual partial refs. The caller advances
                # only through recorded query rows, leaving later issuers pending.
                reason=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED')
                request=q.pop('pending_protocol_request',None)
                has_issuer_refs=any(q.get(k) for k in ('prime_ref','directory_ref','protocol_ref','directory_pages'))
                if request is None and not has_issuer_refs:
                    # The next issuer has no returned source ref; keep it at
                    # the cursor so a later bounded resume can attempt it.
                    break
                if request is not None:
                    q['capture_failure']=dict(request=deepcopy(request),reason=reason,
                        exception_type=type(exc).__name__,outcome='BUDGET_REFUSED_BEFORE_PROVIDER_CALL')
                q['reason']=reason
                queries.append(q)
                break
            except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
                reason=safe_reason(exc,'ANNOUNCEMENT_ISSUER_QUERY_FAILED')
                request=q.pop('pending_protocol_request',None)
                if request is not None:
                    q['capture_failure']=dict(request=deepcopy(request),reason=reason,
                        exception_type=type(exc).__name__,outcome='NO_RESPONSE_REFERENCE_RETURNED')
                q['reason']=reason
            queries.append(q)
    for item in todo[:max_documents]:
        doc={**item,'body_ref':None,'parse_status':'FAILED','reason':None}
        try:
            ref=capture(provider,dict(url=item['row']['url'],method='GET'),budget=budget);doc['body_ref']=ref
            raw=read_response(provider._material_store,ref)
            if not 200<=ref['http_status']<300:raise ValueError('ANNOUNCEMENT_DOCUMENT_HTTP_FAILED')
            pages=extract_pdf_pages(raw,max_bytes=MAX_BYTES,max_pages=40,max_text_characters=240000,timeout_seconds=10)
            # Use the original parser, including its missing-dependency/failure boundary.
            doc.update(parse_status='BODY_PARSED' if pages else 'BODY_UNREADABLE',reason=None if pages else 'NO_READABLE_PDF_BODY')
        except CaptureBudgetExpired:
            break
        except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
            doc['reason']=safe_reason(exc,'ANNOUNCEMENT_DOCUMENT_PARSE_FAILED')
        docs.append(doc)
    return dict(queries=queries,documents=docs,pending_documents=todo[len(docs):])


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
