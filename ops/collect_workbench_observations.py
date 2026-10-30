"""Dated workbench projection of existing read-only quote clients. No account API."""
from __future__ import annotations
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from infrastructure.research_workbench_host import FLAGS, checked

SH = ZoneInfo('Asia/Shanghai')


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


def collect(day,slot,identity,symbols,*,now=None,kr_read=None,official_input=None,clock=None,prior_snapshot=None,prior_korea=None):
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
    snapshot['recorded_at']=clock().isoformat();snapshot['snapshot_sha256']=digest(snapshot)
    return snapshot,kr,raw


def publish(root,snapshot,kr,raw):
    day=snapshot['observation_date'];slot=snapshot['slot'];run=root/day/slot
    run=run/digest(dict(snapshot=snapshot,korea=kr))
    raw_ref=put(run/'raw.json',dict(original_owner=raw,korea=kr))
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
