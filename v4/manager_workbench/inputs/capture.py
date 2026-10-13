"""Dormant exclusive capture: approved Eastmoney date catalogue/body protocol.

Only source facts are captured. Membership, model interpretation and selection
belong to later adapters/engines. HKEX is an explicit auxiliary protocol only;
it is never added to the fresh EASTMONEY_ONLY workflow implicitly.
"""
from __future__ import annotations
from datetime import datetime, time, timedelta
import html
import json
import math
import re
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import uuid4
from ..contracts import Coverage, EvidenceRef, Lane, HK, validate_date
from .validation import batch, raw_sha, time_value
from .capture_store import CaptureStore, OWNER, encoded, sha
from .pdf_pages import extract_pdf_pages

LIST_URL='https://np-anotice-stock.eastmoney.com/api/security/ann'
CONTENT_URL='https://np-cnotice-stock.eastmoney.com/api/content/ann'
HKEX_URL='https://www1.hkexnews.hk/search/titleSearchServlet.do'
PAGE_SIZE=20
MAX_CATALOG_PAGES=1000
MAX_BODY_PAGES=150
MAX_BODY_CHARACTERS=1_000_000


def _date(value):
    if not isinstance(value,str): raise ValueError('CAPTURE_DATE_INVALID')
    token=value.replace('-','')
    validate_date(token)
    return datetime.strptime(token,'%Y%m%d').date()


def resolve_publication_window(context, *, publication_date=None, calendar=None):
    """Reimplement the original calendar-owned two-completed-session window."""
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState, CALENDAR_PATH
    cutoff=time_value(context.cutoff)
    if cutoff is None: raise ValueError('CAPTURE_CUTOFF_INVALID')
    cutoff=cutoff.astimezone(HK); target=_date(context.target_date)
    cal=calendar or load_market_calendar()
    active={TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}
    if resolve_market_states(cal,context.target_date)['hk_securities'] not in active:
        raise ValueError('CAPTURE_TARGET_NOT_HK_TRADING_SESSION')
    if context.phase.value=='NEXT_DAY':
        following=cutoff.date()+timedelta(days=1)
        while following.year==cal.year and resolve_market_states(cal,following.strftime('%Y%m%d'))['hk_securities'] not in active:
            following+=timedelta(days=1)
        if target!=following: raise ValueError('CAPTURE_NEXT_DAY_TARGET_INVALID')
    if publication_date is not None:
        day=_date(publication_date)
        if day>cutoff.date(): raise ValueError('CAPTURE_FUTURE_PUBLICATION_DATE_NOT_ALLOWED')
        start=datetime.combine(day,time.min,HK); end=min(start+timedelta(days=1),cutoff+timedelta(microseconds=1))
        mode='HK_CALENDAR_DAY_V1'; inclusive=True
    else:
        cursor=min(target-timedelta(days=1),cutoff.date()); completed=[]
        while cursor.year==cal.year and len(completed)<2:
            state=resolve_market_states(cal,cursor.strftime('%Y%m%d'))['hk_securities']
            if state in active:
                field='full_day_close' if state==TradingDayState.FULL_TRADING_DAY else 'half_day_close'
                hhmm=cal.markets['hk_securities'].get(field)
                if not isinstance(hhmm,str) or not re.fullmatch('[0-9]{4}',hhmm):
                    raise ValueError('CAPTURE_SESSION_CLOSE_UNAVAILABLE')
                finish=datetime.combine(cursor,time(int(hhmm[:2]),int(hhmm[2:])),HK)
                if finish<=cutoff: completed.append(finish)
            cursor-=timedelta(days=1)
        if len(completed)!=2: raise ValueError('CAPTURE_TWO_COMPLETED_HK_SESSIONS_UNAVAILABLE')
        start=completed[-1]; end=cutoff; mode='TWO_COMPLETED_HK_SESSIONS_POST_CLOSE_WINDOW';inclusive=False
        day=start.date()
    if end<start or (end-start).days>30: raise ValueError('CAPTURE_PUBLICATION_WINDOW_INVALID')
    last=(end-timedelta(microseconds=1)).date() if inclusive else end.date()
    dates=[(day+timedelta(days=n)).isoformat() for n in range((last-day).days+1)]
    return dict(target_trade_date=context.target_date,publication_dates=dates,publication_window_start=start.isoformat(),
        publication_window_end=end.isoformat(),left_inclusive=inclusive,right_inclusive=not inclusive,
        publication_window_mode=mode,research_cutoff=cutoff.isoformat(),timezone='Asia/Hong_Kong',
        calendar_owner='contracts.trading_calendar / hk_securities',calendar_sha256=sha(CALENDAR_PATH.read_bytes()))


def _source_window_status(listing, window):
    """Mirror display time bounds consumption; never assert HKEX publication PIT."""
    value=time_value(listing['display_time'])
    start=time_value(window['publication_window_start']);end=time_value(window['publication_window_end'])
    if value<start or (value==start and not window['left_inclusive']):return 'OUTSIDE_LEFT_BOUNDARY'
    if value>end or (value==end and not window['right_inclusive']):return 'OUTSIDE_RIGHT_BOUNDARY'
    return 'INSIDE_SOURCE_DISPLAY_WINDOW'


def date_scoped_url(publication_date, page_index):
    if type(page_index) is not int or not 1<=page_index<=MAX_CATALOG_PAGES+1: raise ValueError('CATALOG_PAGE_INDEX_INVALID')
    day=_date(publication_date).isoformat()
    return LIST_URL+'?'+urlencode((('ann_type','H'),('client_source','web'),('f_node','0'),
        ('begin_time',day),('end_time',day),('page_size',str(PAGE_SIZE)),('page_index',str(page_index))))


def content_url(article, page_index):
    if not isinstance(article,str) or not re.fullmatch('AN[A-Z0-9]{8,32}',article): raise ValueError('BODY_ARTICLE_ID_INVALID')
    if type(page_index) is not int or not 1<=page_index<=MAX_BODY_PAGES: raise ValueError('BODY_PAGE_INDEX_INVALID')
    return CONTENT_URL+'?'+urlencode(dict(art_code=article,client_source='web',page_index=page_index))


def _payload(raw):
    data=json.loads(raw.decode('utf-8'))
    if not isinstance(data,dict) or type(data.get('success')) is not int or data['success']!=1 or not isinstance(data.get('data'),dict):
        raise ValueError('EASTMONEY_RESPONSE_INVALID')
    return data['data']


def _source_identity(raw):
    if not isinstance(raw,str): return None
    raw=raw.strip().upper()
    if re.fullmatch('[0-9]{1,5}',raw): return 'HK.'+raw.zfill(5),raw
    if re.fullmatch('H[0-9]{4}',raw): return raw,raw
    return None


def _notice_date(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}',value):
        raise ValueError('CATALOG_NOTICE_DATE_INVALID')
    return datetime.strptime(value,'%Y-%m-%d %H:%M:%S').date().isoformat()


def _listing(row, publication):
    if not isinstance(row,dict): raise ValueError('CATALOG_ROW_INVALID')
    article=row.get('art_code')
    content_url(article,1)
    if _notice_date(row.get('notice_date'))!=publication: raise ValueError('CATALOG_NOTICE_DATE_MISMATCH')
    title=row.get('title')
    if not isinstance(title,str) or not title.strip(): raise ValueError('CATALOG_TITLE_MISSING')
    display=row.get('display_time')
    if not isinstance(display,str): raise ValueError('CATALOG_DISPLAY_TIME_INVALID')
    match=re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})(?::([0-9]{3}))?',display)
    if match is None:raise ValueError('CATALOG_DISPLAY_TIME_INVALID')
    observed=datetime.strptime(match.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=HK,
        microsecond=int(match.group(2) or '0')*1000)
    identities=[]
    for code in row.get('codes',[]):
        if not isinstance(code,dict) or code.get('market_code')!='116' or code.get('ann_type')!='H': continue
        identity=_source_identity(code.get('stock_code'))
        if identity is None: raise ValueError('CATALOG_HK_116_H_IDENTITY_INVALID')
        identities.append(dict(code=identity[0],source_stock_code=identity[1],market_code='116',ann_type='H',name=code.get('short_name')))
    if not identities: raise ValueError('CATALOG_HK_116_H_IDENTITY_MISSING')
    return dict(art_code=article,title=title.strip(),publication_date=publication,source_issuer_codes=identities,
        display_time=observed.isoformat(),source_display_time_raw=display,display_notice_date_mismatch=observed.date().isoformat()!=publication,raw_row=row)


def _catalog_page(raw, publication, page, expected_total):
    data=_payload(raw); total=data.get('total_hits'); rows=data.get('list')
    if type(total) is not int or total<0: raise ValueError('CATALOG_TOTAL_HITS_INVALID')
    if data.get('page_index')!=page or type(data.get('page_index')) is not int or type(data.get('page_size')) is not int or data['page_size']!=PAGE_SIZE:
        raise ValueError('CATALOG_PAGE_IDENTITY_MISMATCH')
    if expected_total is not None and total!=expected_total: raise ValueError('CATALOG_TOTAL_HITS_DRIFT')
    if math.ceil(total/PAGE_SIZE)>MAX_CATALOG_PAGES: raise ValueError('CATALOG_PAGE_LIMIT_EXCEEDED')
    if not isinstance(rows,list) or len(rows)!=min(PAGE_SIZE,max(0,total-(page-1)*PAGE_SIZE)):
        raise ValueError('CATALOG_PAGE_ROW_COUNT_MISMATCH')
    for row in rows: _listing(row,publication)
    return data


def _body_page(raw, listing, page, total):
    data=_payload(raw)
    if (data.get('art_code')!=listing['art_code'] or data.get('notice_title')!=listing['title']
            or not isinstance(data.get('notice_date'),str)
            or re.match(r'^\s*([0-9]{4}-[0-9]{2}-[0-9]{2})',data['notice_date']) is None
            or re.match(r'^\s*([0-9]{4}-[0-9]{2}-[0-9]{2})',data['notice_date']).group(1)!=listing['publication_date']):
        raise ValueError('BODY_ARTICLE_TITLE_OR_DATE_MISMATCH')
    expected=data.get('page_size')  # original endpoint means total pages
    if type(expected) is not int or not 1<=expected<=MAX_BODY_PAGES: raise ValueError('BODY_PAGE_TOTAL_INVALID')
    if total is not None and expected!=total: raise ValueError('BODY_PAGE_TOTAL_DRIFT')
    if page>expected: raise ValueError('BODY_PAGE_INDEX_EXCEEDS_TOTAL')
    matched=[]
    for security in data.get('security',[]):
        if not isinstance(security,dict) or str(security.get('market_uni'))!='116': continue
        identity=_source_identity(security.get('stock'))
        if identity and any((identity[0],identity[1])==(item['code'],item['source_stock_code']) for item in listing['source_issuer_codes']):matched.append(identity[0])
    if not matched: raise ValueError('BODY_116_H_ISSUER_IDENTITY_MISMATCH')
    if not isinstance(data.get('notice_content'),str) or not data['notice_content'].strip(): raise ValueError('BODY_TEXT_MISSING')
    return data,sorted(set(matched))


def _ref(receipt, role, publication, owner='EASTMONEY_MIRROR'):
    return dict(evidence_id=role+':'+receipt['request_sha256']+':'+receipt['sha256'],owner=owner,role=role,source_date=publication.replace('-',''),
        sha256=receipt['sha256'],available_at=receipt['available_at'],captured_at=receipt['captured_at'],
        source_url=receipt['request']['url'],artifact_ref=receipt['artifact_ref'],verification='VERIFIED')


def capture_window(context, request, store: CaptureStore):
    store.assert_exclusive_owner(OWNER)
    if store.source!='EASTMONEY_HK': raise ValueError('CAPTURE_FRESH_SOURCE_MUST_BE_EASTMONEY_ONLY')
    window=resolve_publication_window(context,publication_date=request.get('publication_date'))
    transport=request.get('transport'); receipts=[]; articles=[]; refs=[]; gaps=[]; catalogues=[]
    # Frozen observation identity prevents another day's/latest catalogue reuse.
    scope=dict(window=window,protocol='EASTMONEY_HK_DATE_AND_BODY_V1')
    max_bodies=request.get('max_bodies',20000)
    if type(max_bodies) is not int or not 0<=max_bodies<=20000: raise ValueError('BODY_CAPTURE_BUDGET_INVALID')
    for publication in window['publication_dates']:
        rows=[]; total=None; terminal=False; pages=[]; day_gaps=[]; seen=set(); page=1
        while page<=MAX_CATALOG_PAGES+1:
            url=date_scoped_url(publication,page)
            validate=lambda raw,p=page,t=total: _catalog_page(raw,publication,p,t)
            try:
                raw,receipt=store.fetch(url,scope=dict(scope,publication_date=publication),transport=transport,validate=validate)
                data=validate(raw);total=data['total_hits'];pages.append(receipt);refs.append(_ref(receipt,'FULL_DATE_DIRECTORY_PAGE',publication))
                for row in data['list']:
                    listing=_listing(row,publication); article=listing['art_code']
                    listing['publication_window_status']=_source_window_status(listing,window)
                    listing['window_consumption_status']='ELIGIBLE_SOURCE_TIME' if listing['publication_window_status']=='INSIDE_SOURCE_DISPLAY_WINDOW' else 'EXCLUDED_OUTSIDE_WINDOW'
                    listing['publication_time_basis']='EASTMONEY_MIRROR_DISPLAY_TIME_NOT_OFFICIAL_HKEX_PIT'
                    if article in seen: day_gaps.append('CATALOG_DUPLICATE_ARTICLE');continue
                    seen.add(article);listing['listing_source_ref']=_ref(receipt,'FULL_DATE_DIRECTORY_PAGE',publication);rows.append(listing)
                if page>math.ceil(total/PAGE_SIZE): terminal=True;break
            except Exception as exc:
                store.assert_exclusive_owner(OWNER);day_gaps.append(str(exc))
                # Repair can reuse existing successes and request only this hole.
                if total is None or page>math.ceil(total/PAGE_SIZE):break
            page+=1
        if not terminal:day_gaps.append('CATALOG_TERMINAL_EMPTY_PAGE_MISSING')
        if total is None or len(rows)!=total:day_gaps.append('CATALOG_COMPLETE_UNIQUE_COUNT_UNPROVEN')
        catalogues.append(dict(publication_date=publication,total_hits=total,observed_count=len(rows),
            terminal_empty_seen=terminal,page_receipts=pages,gaps=sorted(set(day_gaps))))
        gaps.extend(day_gaps)
        for listing in rows:
            body_pages=[]; expected=None; body_gaps=[];text_characters=0
            outside=listing['window_consumption_status']=='EXCLUDED_OUTSIDE_WINDOW'
            if outside: body_gaps.append('ANNOUNCEMENT_OUTSIDE_PUBLICATION_WINDOW')
            elif len(articles)>=max_bodies: body_gaps.append('ANNOUNCEMENT_BODY_CAPTURE_PENDING')
            else:
                body_scope=dict(protocol='EASTMONEY_CONTENT_V1',publication_date=publication,
                    listing_sha256=sha(encoded(listing['raw_row'])))
                index=1
                while index<=MAX_BODY_PAGES:
                    url=content_url(listing['art_code'],index)
                    validate=lambda raw,p=index,t=expected: _body_page(raw,listing,p,t)
                    try:
                        raw,receipt=store.fetch(url,scope=body_scope,transport=transport,validate=validate)
                        data,matched=validate(raw);expected=data['page_size'];text=data['notice_content']
                        body_pages.append(dict(page_number=index,page_total=expected,text=text,text_sha256=sha(text.encode()),
                            source_ref=_ref(receipt,'CONTENT_API_PAGE',publication),matched_source_issuer_codes=matched))
                        text_characters+=len(text)
                        if text_characters>MAX_BODY_CHARACTERS:
                            body_gaps.append('BODY_CONTENT_TEXT_LIMIT_EXCEEDED');break
                    except Exception as exc:
                        store.assert_exclusive_owner(OWNER);body_gaps.append(str(exc))
                        if expected is None:break
                    if expected is not None and index==expected:break
                    index+=1
            complete=expected is not None and len(body_pages)==expected and not body_gaps
            text='\n\n'.join(p['text'] for p in body_pages) if complete else None
            value=dict(listing,owner='EASTMONEY_MIRROR',body_status=('NOT_REQUESTED_OUTSIDE_RESEARCH_WINDOW' if outside else 'COMPLETE_CONTENT_API_BODY' if complete else 'BODY_CAPTURE_FAILED'),
                text_characters=text_characters,text_character_limit=MAX_BODY_CHARACTERS,
                body_text=text,body_text_sha256=sha(text.encode()) if text else None,pages=body_pages,
                content_page_count=expected,body_complete=complete,semantic_status='NOT_REVIEWED',
                first_hkex_publication_time='CANNOT_CONFIRM',original_point_in_time_availability='CANNOT_CONFIRM',
                gaps=sorted(set(body_gaps)))
            value['available_at']=max((p['source_ref']['available_at'] for p in body_pages),default=None)
            artifact=store.save_product(value);value['source_sha256']=artifact['sha256'];value['body_artifact_ref']=artifact['artifact_ref']
            if value['available_at']:
                refs.append(dict(evidence_id='ANNOUNCEMENT_BODY:'+artifact['sha256'],owner='EASTMONEY_MIRROR',role='ANNOUNCEMENT_BODY',
                    source_date=publication.replace('-',''),sha256=artifact['sha256'],available_at=value['available_at'],
                    artifact_ref=artifact['artifact_ref'],source_url=content_url(listing['art_code'],1),
                    verification='VERIFIED' if complete else 'CANNOT_CONFIRM',gaps=value['gaps']))
            articles.append(value);gaps.extend(body_gaps)
    if any(time_value(ref['available_at'])>time_value(context.cutoff) for ref in refs):
        gaps.append('CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF')
    product=dict(schema_version='mwb.capture.window.v1',owner=OWNER,source='EASTMONEY_HK',source_scope='EASTMONEY_ONLY',
        run_id=uuid4().hex,target_trade_date=context.target_date,window=window,catalogues=catalogues,
        rows=articles,source_variants=articles,evidence_refs=refs,gaps=sorted(set(gaps)),
        scope_count=sum(c['total_hits'] or 0 for c in catalogues),observed_count=len(articles),
        coverage_status='PARTIAL' if gaps else 'COMPLETE_OBSERVED_EASTMONEY_DATE_CATALOG',
        market='HK_CONNECT',connect_eligibility_status='NOT_ASSESSED',semantic_status='NOT_REVIEWED',
        production_allowed=False,buy_gate_updated=False,orders_sent=False)
    product['saved_ref']=store.save_product(product)
    return product


def capture_announcements(context, request, cache):
    """Capture facts and expose the frozen public InputBatch to later engines."""
    if not callable(getattr(cache,'assert_exclusive_owner',None)):
        raise ValueError('ANNOUNCEMENT_EXCLUSIVE_OWNER_NOT_BOUND')
    cache.assert_exclusive_owner(OWNER)
    if request.get('source')=='HKEX_OFFICIAL': return _capture_hkex(context,request,cache)
    product=capture_window(context,request,cache); records=[]
    for article in product['rows']:
        if article['window_consumption_status']=='EXCLUDED_OUTSIDE_WINDOW':continue
        for issuer in article['source_issuer_codes']:
            if not issuer['code'].startswith('HK.'):continue
            pages=article['pages'];text=article['body_text'];publication=article['publication_date']
            records.append(dict(market='HK_CONNECT',target_date=context.target_date,symbol=issuer['code'],name=issuer['name'],
                article_id='EASTMONEY:'+article['art_code']+':'+issuer['code'],owner=article['owner'],body=text,
                body_sha256=article['body_text_sha256'],source_sha256=article['source_sha256'],
                body_complete=article['body_complete'],is_pdf=False,source_pages_complete=article['body_complete'],
                source_page_count=article['content_page_count'],segments=[dict(index=p['page_number']-1,count=p['page_total'],
                    page_number=p['page_number'],text=p['text']+('\n\n' if p['page_number']<p['page_total'] else '')) for p in pages],
                source_url=content_url(article['art_code'],1),available_at=article['available_at'],observed_at=article['available_at'],
                publication_date=publication,published_at=None,publication_time_status='CANNOT_CONFIRM',membership=None,
                title=article['title'],gaps=article['gaps'],evidence_ids=[article['listing_source_ref']['evidence_id'],
                    'ANNOUNCEMENT_BODY:'+article['source_sha256']]))
    gaps=product['gaps']+['MONTHLY_CONNECT_MEMBERSHIP_MUST_BE_BOUND_BY_NATIVE_ADAPTER']
    return batch(context,Lane.ANNOUNCEMENT,records,product['evidence_refs'],'Existing Eastmoney full-date observed catalogue, mirror body source',
        Coverage(scope_count=product['scope_count'],observed_count=product['observed_count'],gaps=product['gaps']),gaps,
        product['saved_ref']['artifact_ref'])


def hkex_directory_url(start,end,row_range):
    if type(row_range) is not int or row_range<100 or row_range%100: raise ValueError('HKEX_ROW_RANGE_INVALID')
    validate_date(start);validate_date(end)
    return HKEX_URL+'?'+urlencode(dict(sortDir=0,sortByOptions='DateTime',category=0,market='SEHK',stockId='',documentType=-1,
        fromDate=start,toDate=end,title='',searchType=0,t1code=-2,t2Gcode=-2,t2code=-2,rowRange=row_range,lang='ZH'))


def _official(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in {'www1.hkexnews.hk','www.hkexnews.hk'} or p.username or p.password or p.port not in (None,443):
        raise ValueError('HKEX_SOURCE_URL_INVALID')
    return url


def _hkex_page(raw,row_range,total):
    value=json.loads(raw);rows=value.get('result')
    if isinstance(rows,str):rows=json.loads(rows)
    count=value.get('recordCnt');loaded=value.get('loadedRecord')
    if (type(count) is not int or count<0 or type(loaded) is not int or not isinstance(rows,list) or loaded!=len(rows)
            or value.get('rowRange')!=row_range or loaded!=min(count,row_range)
            or type(value.get('hasNextRow')) is not bool or value['hasNextRow']!=(loaded<count)):
        raise ValueError('HKEX_DIRECTORY_CUMULATIVE_CONTRACT_INVALID')
    if total is not None and count!=total: raise ValueError('HKEX_DIRECTORY_COUNT_DRIFT')
    return value,rows


def _capture_hkex(context,request,cache):
    if not isinstance(cache,CaptureStore) or cache.source!='HKEX_OFFICIAL':raise ValueError('HKEX_AUXILIARY_SOURCE_LEASE_REQUIRED')
    start=request.get('from_date');end=request.get('to_date');validate_date(start);validate_date(end)
    if start>end or end>time_value(context.cutoff).astimezone(HK).strftime('%Y%m%d'):raise ValueError('ANNOUNCEMENT_CAPTURE_WINDOW_INVALID')
    max_pages=request.get('max_pages',100);max_bodies=request.get('max_bodies',20000)
    if type(max_pages) is not int or not 1<=max_pages<=100 or type(max_bodies) is not int or not 0<=max_bodies<=20000:raise ValueError('ANNOUNCEMENT_CAPTURE_BUDGET_INVALID')
    total=None;observed={};refs=[];gaps=[];exhausted=False;scope=dict(from_date=start,to_date=end,cutoff=context.cutoff)
    for number in range(1,max_pages+1):
        url=hkex_directory_url(start,end,number*100);validate=lambda raw,n=number*100,t=total:_hkex_page(raw,n,t)
        try:
            raw,receipt=cache.fetch(url,scope=scope,transport=request.get('transport'),validate=validate)
            value,rows=validate(raw);total=value['recordCnt'];ref=_ref(receipt,'FULL_MARKET_DIRECTORY_PAGE',end,'HKEX_OFFICIAL');refs.append(ref)
            seen=set()
            for row in rows:
                event=str(row.get('NEWS_ID') or '')
                if not re.fullmatch('[0-9]+',event) or event in seen:raise ValueError('HKEX_DIRECTORY_EVENT_ID_INVALID_OR_DUPLICATE')
                seen.add(event)
                if event in observed and observed[event]['raw']!=row:raise ValueError('HKEX_DIRECTORY_EVENT_CONFLICT')
                observed.setdefault(event,dict(raw=row,directory_evidence_id=ref['evidence_id']))
            if len(observed)!=len(rows):raise ValueError('HKEX_DIRECTORY_CUMULATIVE_PREFIX_CHANGED')
            if not value['hasNextRow']:exhausted=True;break
        except Exception as exc:cache.assert_exclusive_owner(OWNER);gaps.append(str(exc));break
    if not exhausted:gaps.append('HKEX_DIRECTORY_COVERAGE_UNVERIFIED')
    records=[]
    for index,(event,item) in enumerate(observed.items()):
        row=item['raw'];codes=re.split(r'<br\s*/?>|[\r\n]+',str(row.get('STOCK_CODE') or ''),flags=re.I)
        codes=[html.unescape(re.sub('<[^>]*>','',code)).strip() for code in codes]
        codes=[code for code in codes if re.fullmatch('[0-9]{5}',code)]
        body_gaps=[];parsed=None;receipt=None;url=urljoin('https://www1.hkexnews.hk',str(row.get('FILE_LINK') or ''))
        if index>=max_bodies:body_gaps.append('ANNOUNCEMENT_BODY_CAPTURE_PENDING')
        else:
            try:
                _official(url)
                raw,receipt=cache.fetch(url,scope=scope,transport=request.get('transport'),validate=lambda raw:extract_pdf_pages(raw))
                parsed=extract_pdf_pages(raw)
                if not parsed['complete']:body_gaps.extend(parsed['gaps'])
                refs.append(_ref(receipt,'ANNOUNCEMENT_BODY',end,'HKEX_OFFICIAL'))
            except Exception as exc:cache.assert_exclusive_owner(OWNER);body_gaps.append(str(exc))
        pages=parsed['pages'] if parsed else [];text='\n'.join(p['text'] or '' for p in pages)
        for code in codes:
            records.append(dict(market='HK_CONNECT',target_date=context.target_date,symbol='HK.'+code,name=row.get('STOCK_NAME'),
                owner='HKEX_OFFICIAL',article_id='HKEX:'+event+':HK.'+code,body=text,body_sha256=raw_sha(text.encode()) if text else None,
                source_sha256=receipt['sha256'] if receipt else None,available_at=receipt['available_at'] if receipt else None,
                observed_at=receipt['available_at'] if receipt else None,source_url=url,body_complete=bool(parsed and parsed['complete']),is_pdf=True,
                source_pages_complete=bool(parsed and parsed['complete']),source_page_count=parsed['page_count'] if parsed else None,
                segments=[dict(index=p['page_number']-1,count=p['page_total'],page_number=p['page_number'],text=(p['text'] or '')+('\n' if p['page_number']<p['page_total'] else '')) for p in pages],
                membership=None,evidence_ids=[item['directory_evidence_id']]+([_ref(receipt,'ANNOUNCEMENT_BODY',end,'HKEX_OFFICIAL')['evidence_id']] if receipt else []),
                gaps=body_gaps,published_at=row.get('DATE_TIME'),title=row.get('TITLE')))
    return batch(context,Lane.ANNOUNCEMENT,records,refs,'Explicit auxiliary original HKEX observed directory',
        Coverage(scope_count=total,observed_count=len(observed),gaps=gaps),gaps+['MONTHLY_CONNECT_MEMBERSHIP_MUST_BE_BOUND_BY_NATIVE_ADAPTER'],'HKEX_CAPTURE:'+end)
