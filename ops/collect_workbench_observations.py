"""Dated workbench projection of existing read-only quote clients. No account API."""
from __future__ import annotations
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
import re
from html.parser import HTMLParser
from pathlib import Path
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from infrastructure.research_workbench_host import FLAGS, checked

SH = ZoneInfo('Asia/Shanghai')
JP = ZoneInfo('Asia/Tokyo')
NY = ZoneInfo('America/New_York')
US_INDICES = (('.DJI','道指','道琼斯指数','https://www.futunn.com/index/.DJI-US'),
              ('.SPX','标普500','标普500指数','https://www.futunn.com/index/.SPX-US'),
              ('.IXIC','纳指','纳斯达克综合指数','https://www.futunn.com/index/.IXIC-US?security_id=23'))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def put(path,value):
    """fsync bytes before replacing the date pointer; readers never see half JSON."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest())


def number(value):
    try:v=float(value)
    except (ValueError,TypeError):return None
    return v if math.isfinite(v) else None


def missing(symbol,reason,**extra):
    return dict(symbol=symbol,price=None,change_percent_source=None,amount_source=None,source_asof=None,currency='CNY',status='SOURCE_ERROR',error=reason,percent_change_rank_eligible=False,volume_rank_eligible=False,comparable_volume_shares=None,**extra)


def official_close(day,symbols,input_ref,recorded):
    """Project the original owner's saved daily package; never download it."""
    import struct
    import zipfile
    from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage
    package=OfficialDailyPackage(input_ref,int(day.replace('-','')))
    rows=[];blocks={}
    with zipfile.ZipFile(package.package_path) as archive:
        for symbol in symbols:
            market={'SH':1,'SZ':0,'BJ':2}[symbol[-2:]];entry=package.rows.get((market,symbol[:6]))
            if entry is None:rows.append(missing(symbol,'OFFICIAL_DAILY_SYMBOL_MISSING'));continue
            bar,lineage,shares=entry;name=lineage['md1_member']['name']
            if name not in blocks:blocks[name]=archive.read(name)
            prev=struct.unpack_from('<d',blocks[name],lineage['md1_byte_offset']+4)[0]
            if prev<=0 or bar['close']<=0 or bar['amount']<0:rows.append(missing(symbol,'OFFICIAL_DAILY_PRICE_OR_AMOUNT_INVALID'));continue
            rows.append(dict(symbol=symbol,price=bar['close'],prev_close=prev,change_percent_source=round((bar['close']/prev-1)*100,4),amount_source=bar['amount'],source_date=day,source_asof=None,source_asof_precision='DATE_ONLY',observed_at_upper_bound=recorded.isoformat(),currency='CNY',status='DATED_DAILY_ARCHIVE',capture_kind='OFFICIAL_DAILY_ARCHIVE',percent_change_rank_eligible=True,volume_rank_eligible=True,comparable_volume_shares=shares,units=dict(price='CNY',amount='CNY',volume='SHARES'),error=None,source='TDX_OFFICIAL_G4DAY',source_ref=package.lineage(market,symbol[:6])))
    return rows,dict(input_ref=input_ref,package=package.package_ref,source_time='UNKNOWN_DATE_ONLY')


def korea(day,now,read=None,clock=None,symbols=('^KS11','^KQ11')):
    clock=clock or (lambda:datetime.now(SH))
    read=read or (lambda url:urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=15).read())
    indices=[]
    for symbol in symbols:
        url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?interval=1d&range=5d'
        row=dict(symbol=symbol,source_url=url,provider='YAHOO_FINANCE',value=None,change_pct=None,source_asof=None,delay='UNKNOWN',status='UNKNOWN')
        try:
            raw=read(url);value=json.loads(raw);meta=value['chart']['result'][0]['meta']
            stamp=datetime.fromtimestamp(meta['regularMarketTime'],ZoneInfo('Asia/Seoul'))
            if meta.get('symbol')!=symbol or meta.get('instrumentType')!='INDEX' or meta.get('exchangeTimezoneName')!='Asia/Seoul':raise ValueError('KR_INDEX_IDENTITY_CONFLICT')
            if stamp.date().isoformat()!=day:raise ValueError('KR_SOURCE_DATE_MISMATCH')
            received=clock()
            if stamp>received:raise ValueError('KR_SOURCE_TIME_FUTURE')
            price=number(meta['regularMarketPrice']);prev=number(meta.get('chartPreviousClose'))
            # chartPreviousClose is the baseline before range, not yesterday.
            # Use the aligned prior daily close for this exact source session.
            result=value['chart']['result'][0];closes=result['indicators']['quote'][0]['close']
            prior=sorted((t,number(c)) for t,c in zip(result['timestamp'],closes) if datetime.fromtimestamp(t,ZoneInfo('Asia/Seoul')).date()<stamp.date())
            prev=prior[-1][1] if prior else None
            if price is None or price<=0 or prev is None or prev<=0:raise ValueError('KR_PRICE_BASELINE_MISSING')
            row.update(previous_close=prev,previous_observed_session=datetime.fromtimestamp(prior[-1][0],ZoneInfo('Asia/Seoul')).date().isoformat(),baseline_source='ALIGNED_PREVIOUS_DAILY_RECORD',value=price,change_pct=round((price/prev-1)*100,4),source_asof=stamp.isoformat(),exchangeTimezoneName=meta['exchangeTimezoneName'],instrument_name=meta.get('shortName'),status='DATED_INDEX_OBSERVATION',raw_sha256=hashlib.sha256(raw).hexdigest(),raw_response=value)
        except Exception as error:row['error']=type(error).__name__+': '+str(error)
        indices.append(row)
    return dict(status='PARTIAL' if any(r['value'] is None for r in indices) else 'DATED_INDEX_OBSERVATION',indices=indices,request_started_at=now.isoformat(),recorded_at=clock().isoformat(),limitation='Yahoo两主指数；供应商延迟未知；后到观察不回写08:00原节点',**FLAGS)


def japan(day,clock,quote_factory=None,prior=None):
    """One quote-only context per capture; reuse only a successful same-slot view."""
    if (prior and prior.get('status')=='DATED_INDEX_OBSERVATION' and prior.get('observation_date')==day
            and prior.get('symbol')=='JP..N225' and prior.get('raw_ref')):
        checked(prior['raw_ref'])
        return dict(prior,reused_same_slot=True),{}
    started=clock();quote=None;raw={}
    result=dict(schema='V4_WORKBENCH_JAPAN_V1',status='SOURCE_ERROR',observation_date=day,symbol='JP..N225',name='日经225',
                provider='Futu OpenD',timezone='Asia/Tokyo',value=None,previous_close=None,change_pct=None,source_asof=None,
                source_code_authority='https://www.futunn.com/index/.N225-JP',late_observation=True,
                limitation='后到观察；不回写08:00原节点；不是实时成交保证',**FLAGS)
    try:
        if quote_factory is None:
            from futu import OpenQuoteContext
            quote_factory=OpenQuoteContext
        quote=quote_factory();ret,frame=quote.get_market_snapshot(['JP..N225'])
        if ret!=0:raise ValueError('FUTU_JP_SNAPSHOT_FAILED:'+str(frame))
        # SDK dataframe JSON changes NaN to null, retaining the complete response.
        records=json.loads(frame.to_json(orient='records',force_ascii=False))
        raw=dict(symbols=['JP..N225'],records=records,encoding='SDK_DATAFRAME_JSON_NONFINITE_AS_NULL')
        if len(records)!=1:raise ValueError('JP_SNAPSHOT_ROW_COUNT')
        row=records[0];price=number(row.get('last_price'));prev=number(row.get('prev_close_price'))
        if (row.get('code')!='JP..N225' or row.get('index_valid') is not True or row.get('name')!='日经225'
                or price is None or price<=0 or prev is None or prev<=0):raise ValueError('JP_INDEX_IDENTITY_OR_PRICE')
        stamp=datetime.strptime(row['update_time'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=JP)
        received=clock()
        if stamp.date().isoformat()!=day or stamp>received:raise ValueError('JP_SOURCE_DATE_OR_FUTURE')
        result.update(status='DATED_INDEX_OBSERVATION',value=price,previous_close=prev,change_pct=round((price/prev-1)*100,4),
                      source_asof=stamp.isoformat(),raw_sha256=digest(records),recorded_at=received.isoformat(),error=None)
    except Exception as error:result['error']=type(error).__name__+': '+str(error)
    finally:
        if quote is not None:quote.close()
    result.setdefault('recorded_at',clock().isoformat());result['request_started_at']=started.isoformat()
    return result,raw


class _FutuIndexPage(HTMLParser):
    """Read the actual quote DOM, never CSS marker text or search snippets."""
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self):
        super().__init__();self.stack=[];self.values={'title':[],'price':[],'ratio':[],'status':[]};self.canonical=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);classes=set(attrs.get('class','').split())
        if tag=='link' and attrs.get('rel')=='canonical':self.canonical.append(attrs.get('href'))
        if tag in self.VOID:return
        key='title' if tag=='title' else 'price' if 'price' in classes and any('price-current' in item[1] for item in self.stack) else 'ratio' if 'change-ratio' in classes and any('price-current' in item[1] for item in self.stack) else 'status' if tag=='div' and 'status' in classes else None
        self.stack.append((tag,classes,key,[]))
    def handle_data(self,data):
        for _,_,key,parts in self.stack:
            if key:parts.append(data)
    def handle_endtag(self,tag):
        index=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if index is None:return
        frames=self.stack[index:];del self.stack[index:]
        for _,_,key,parts in frames:
            if key:self.values[key].append(' '.join(''.join(parts).split()))


def parse_us_index(raw,code,name,expected_name,url,session,received):
    html=raw.decode('utf-8');page=_FutuIndexPage();page.feed(html)
    marker='window.__INITIAL_STATE__='
    if html.count(marker)!=1:raise ValueError('US_INDEX_STATE_IDENTITY')
    state,_=json.JSONDecoder().raw_decode(html.split(marker,1)[1]);info=state['stock_info']
    canonical='https://www.futunn.com/index/'+code+'-US'
    if (page.canonical!=[canonical] or len(page.values['title'])!=1 or expected_name+'('+code+')' not in page.values['title'][0]
            or info.get('stockCode')!=code or info.get('name')!=expected_name or info.get('marketLabel')!='US'
            or info.get('instrumentType')!=6 or info.get('isPlate') is not False):raise ValueError('US_INDEX_PAGE_CODE_OR_TITLE')
    if any(len(page.values[key])!=1 for key in ('price','ratio','status')):raise ValueError('US_INDEX_QUOTE_DOM_AMBIGUOUS')
    price=number(page.values['price'][0].replace(',',''));previous=number(info.get('priceLastClose'));state_price=number(info.get('priceNominal'))
    ratio=page.values['ratio'][0]
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?%',ratio):raise ValueError('US_INDEX_PERCENT_INVALID')
    change=number(ratio[:-1]);epoch=number(info.get('exchangeDataTimeMs'))
    if price is None or price<=0 or previous is None or previous<=0 or state_price is None or abs(price-state_price)>.001 or change is None or epoch is None:raise ValueError('US_INDEX_PRICE_INVALID')
    stamp=datetime.fromtimestamp(epoch/1000,NY)
    expected_status='收盘价 '+session[4:6]+'/'+session[6:]+' 16:00 (美东)'
    if (stamp.strftime('%Y%m%d')!=session or stamp.hour!=16 or stamp.minute!=0 or stamp.second!=0
            or stamp>received or page.values['status'][0]!=expected_status):raise ValueError('US_INDEX_NOT_EXPECTED_SESSION_CLOSE')
    if abs((price/previous-1)*100-change)>.015:raise ValueError('US_INDEX_CHANGE_BASELINE_CONFLICT')
    return dict(symbol=code,name=name,value=price,previous_close=previous,change_pct=change,source_asof=stamp.isoformat(),
                timezone='America/New_York',session_date=session,source_url=url,read_at=received.isoformat(),raw_sha256=hashlib.sha256(raw).hexdigest(),status='DATED_CLOSE')


def us_benchmarks(day,clock,read=None,prior=None):
    read=read or (lambda url:urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=15).read())
    result=dict(schema='V4_WORKBENCH_US_BENCHMARKS_V1',observation_date=day,status='SOURCE_ERROR',rows=[],recorded_at=clock().isoformat(),provider='Futu official website',**FLAGS);raw={}
    try:
        api='http://127.0.0.1:8873/api/v4/research/us-market?research_date='+day.replace('-','')
        oracle_raw=read(api);oracle=json.loads(oracle_raw);session=oracle.get('us_session_date')
        if (oracle.get('schema_version')!='v3_5.global_industries.v2' or oracle.get('research_date')!=day.replace('-','')
                or any(oracle.get(k)!=v for k,v in FLAGS.items()) or oracle.get('write_policy')!='read_only'
                or not isinstance(session,str) or not re.fullmatch(r'\d{8}',session)
                or oracle.get('capture_session_date')!=session or oracle.get('capture_phase')!='POST_CLOSE'
                or any(not isinstance(oracle.get(key),dict) or not re.fullmatch(r'[a-f0-9]{64}',oracle[key].get('sha256','')) for key in ('artifact','manifest','receipt'))):raise ValueError('US_SESSION_ORACLE_UNCONFIRMED')
        oracle_ref=dict(url=api,research_date=day.replace('-',''),response_sha256=hashlib.sha256(oracle_raw).hexdigest(),session_date=session,artifact=oracle['artifact'],manifest=oracle['manifest'],receipt=oracle['receipt'])
        if (prior and prior.get('schema')==result['schema'] and prior.get('observation_date')==day
                and prior.get('status')=='DATED_US_BENCHMARKS' and prior.get('us_session_date')==session
                and prior.get('raw_ref') and {row.get('symbol') for row in prior.get('rows',[])}=={row[0] for row in US_INDICES}):
            checked(prior['raw_ref'])
            return dict(prior,reused_completed_session=True,oracle=oracle_ref,cache_checked_at=clock().isoformat()),{}
        rows=[];pages={}
        for code,name,expected_name,url in US_INDICES:
            try:
                page_raw=read(url);received=clock();pages[code]=dict(url=url,html=page_raw.decode('utf-8'),sha256=hashlib.sha256(page_raw).hexdigest(),read_at=received.isoformat())
                rows.append(parse_us_index(page_raw,code,name,expected_name,url,session,received))
            except Exception as error:rows.append(dict(symbol=code,name=name,value=None,change_pct=None,status='SOURCE_ERROR',error=type(error).__name__+': '+str(error)))
        result.update(rows=rows,us_session_date=session,oracle=oracle_ref,status='DATED_US_BENCHMARKS' if all(row['status']=='DATED_CLOSE' for row in rows) else 'PARTIAL',recorded_at=clock().isoformat())
        raw=dict(pages=pages,oracle=oracle_ref)
    except Exception as error:result['error']=type(error).__name__+': '+str(error)
    return result,raw


def collect(day,slot,identity,symbols,*,now=None,kr_read=None,official_input=None,clock=None,prior_snapshot=None,prior_korea=None,foreign_context=None,quote_factory=None,us_read=None):
    clock=clock or (lambda:datetime.now(SH));started=now or clock();rows=[];raw={}
    all_symbols=list(symbols);retained={r['symbol']:r for r in (prior_snapshot or {}).get('rows',[]) if not r.get('error')}
    symbols=[s for s in all_symbols if s not in retained]
    if not symbols:rows=[];raw=dict(reused_completed_symbols=list(retained))
    elif official_input and started.hour>=15:
        try:rows,raw=official_close(day,symbols,official_input,clock())
        except (ValueError,OSError,KeyError,TypeError) as error:rows=[missing(s,'OFFICIAL_DAILY_'+type(error).__name__+': '+str(error)) for s in symbols]
    else:
        # The actual shared connector probe and native source-date gap are
        # preserved by Root. A timer must not repeat a known 80-host failure.
        rows=[missing(s,'CANNOT_CONFIRM_INTRADAY_SOURCE: original owner has no date-certified cumulative quote; shared_pytdx_hq minute turnover cannot substitute') for s in symbols]
    new_rows={r['symbol']:r for r in rows};rows=[retained[s] if s in retained else new_rows[s] for s in all_symbols]
    finished=clock();archive=bool(rows) and all(r.get('capture_kind')=='OFFICIAL_DAILY_ARCHIVE' for r in rows)
    snapshot=dict(schema='OBSERVATION_SNAPSHOT_VIEW_V1',source_date=identity['source_date'],observation_date=day,parent_admission_sha256=identity['generation'],source_generation=identity['generation'],input_sha256=identity['input_sha256'],daily_contract_sha256=digest(sorted(all_symbols)),analysis_admission='NOT_GRANTED',formula_review='PENDING',slot=slot,rows=rows,request_started_at=started.isoformat(),recorded_at=finished.isoformat(),capture_kind='OFFICIAL_DAILY_ARCHIVE' if archive else 'INTRADAY_UNVERIFIED',source_asof_min=None,source_asof_max=None,observed_upper_bound_max=finished.isoformat(),**FLAGS)
    kr_retained={r['symbol']:r for r in (prior_korea or {}).get('indices',[]) if r.get('value') is not None}
    missing_kr=[s for s in ('^KS11','^KQ11') if s not in kr_retained]
    kr=korea(day,finished,kr_read,clock=clock,symbols=missing_kr)
    new_kr={r['symbol']:r for r in kr['indices']};kr['indices']=[kr_retained[s] if s in kr_retained else new_kr[s] for s in ('^KS11','^KQ11')]
    kr['status']='PARTIAL' if any(r.get('value') is None for r in kr['indices']) else 'DATED_INDEX_OBSERVATION'
    jp,jp_raw=japan(day,clock,quote_factory,prior=(prior_snapshot or {}).get('context',{}).get('japan'))
    us,us_raw=us_benchmarks(day,clock,us_read,prior=(foreign_context or (prior_snapshot or {}).get('context',{})).get('us_benchmarks'))
    snapshot['context']=dict(japan=jp,us_benchmarks=us);raw.update(japan=jp_raw,us_benchmarks=us_raw)
    snapshot['recorded_at']=clock().isoformat();snapshot['snapshot_sha256']=digest(snapshot)
    return snapshot,kr,raw


def publish(root,snapshot,kr,raw):
    day=snapshot['observation_date'];slot=snapshot['slot'];run=root/day/slot
    run=run/digest(dict(snapshot=snapshot,korea=kr))
    raw_ref=put(run/'raw.json',dict(original_owner=raw,korea=kr))
    for key in ('japan','us_benchmarks'):
        view=snapshot.get('context',{}).get(key)
        if view is not None and not view.get('raw_ref'):view['raw_ref']=raw_ref
    snapshot.pop('snapshot_sha256',None);snapshot['snapshot_sha256']=digest(snapshot)
    kr_public={**kr,'indices':[{k:v for k,v in row.items() if k!='raw_response'} for row in kr['indices']]}
    snapshot_ref=put(run/'snapshot.json',snapshot);kr_ref=put(run/'korea.json',kr_public)
    receipt=put(run/'receipt.json',dict(status='COMMITTED',snapshot=snapshot_ref,korea=kr_ref,raw=raw_ref,recorded_at=snapshot['recorded_at'],**FLAGS))
    pointer=dict(schema='V4_WORKBENCH_OBSERVATION_COMMIT_V1',snapshot=snapshot_ref,korea=kr_ref,receipt=receipt,**FLAGS)
    pointer['recorded_at']=snapshot['recorded_at']
    with (root/'.publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=root/day/'latest.json'
        previous=json.loads(old.read_text()) if old.exists() else None
        if previous and datetime.fromisoformat(previous.get('recorded_at',snapshot['recorded_at']))>datetime.fromisoformat(snapshot['recorded_at']):raise ValueError('WORKBENCH_OUT_OF_ORDER_COMPLETION')
        put(root/day/'latest.json',pointer)
    return pointer
