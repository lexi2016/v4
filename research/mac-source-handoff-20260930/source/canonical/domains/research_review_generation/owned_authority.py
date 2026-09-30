"""One explicit fetch owner for the preserved Vibe calculations.

This is the migrated fetchers' IO boundary, not an independent scheduler or a
second producer. All calculations in one review share success AND failure raw
responses. Serialized SDK frames are identified as SDK_RETURN_FRAME, not as
wire bytes. No environment, HOME, socket or module monkeypatch is used.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any

from infrastructure.owned_io import SafeRoot
from ._cache import OwnedCache, encoded, digest, explicit_root
from ._owned_io import BoundaryError


class SourceUnavailable(RuntimeError):
    """Sanitized transport failure; credentials/response bodies never in errors."""


class RawResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content=content;self.status_code=status_code
    def json(self):
        return json.loads(self.content)
    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise SourceUnavailable('HTTP status '+str(self.status_code))
    def read(self):
        return self.content


class LiveTransport:
    """Original SDK and HTTP providers; explicit proxy route, no global changes."""
    def __init__(self, *, market_proxy: str | None = None, iwencai_client=None):
        self.market_proxy=market_proxy;self.iwencai_client=iwencai_client
    def ak(self, endpoint, **params):
        import akshare
        allowed={'stock_zt_pool_em','stock_zt_pool_zbgc_em','stock_zt_pool_dtgc_em',
                 'stock_zt_pool_previous_em','stock_lhb_detail_em','stock_zh_a_hist_tx'}
        if endpoint not in allowed:
            raise SourceUnavailable('unapproved SDK endpoint')
        return getattr(akshare,endpoint)(**params)
    def http_get(self,url,**params):
        import requests
        with requests.Session() as session:
            session.trust_env=False
            if self.market_proxy:
                session.proxies={'https':self.market_proxy,'http':self.market_proxy}
            with session.get(url,stream=True,allow_redirects=False,**params) as response:
                response.raise_for_status()
                if 300 <= response.status_code <400:
                    raise SourceUnavailable('redirect forbidden')
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>32*1024*1024:
                        raise SourceUnavailable('raw response exceeds bound')
                    chunks.append(chunk)
                return RawResponse(b''.join(chunks),response.status_code)
    def iwencai_query(self,query,**params):
        if self.iwencai_client is None:
            raise SourceUnavailable('explicit Iwencai client not supplied')
        return self.iwencai_client.query(query,**params)


def _plain(value, *, raw_missing: bool = True):
    """Encode missing raw SDK scalars; never repair nonfinite calculations."""
    if isinstance(value,dict):return {str(k):_plain(v, raw_missing=raw_missing) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_plain(v, raw_missing=raw_missing) for v in value]
    if hasattr(value,'item'):
        try:value=value.item()
        except (ValueError,TypeError):pass
    if isinstance(value,float):
        import math
        if not math.isfinite(value):
            if not raw_missing: raise BoundaryError('nonfinite computed value')
            return None
        return value
    if isinstance(value,(str,int,bool)) or value is None:return value
    if isinstance(value,datetime) or hasattr(value,'isoformat'):return value.isoformat()
    raise BoundaryError('unsupported raw SDK value type: '+type(value).__name__)


class VibeDataAuthority:
    def __init__(self, *, state_root: Path, cache_root: Path, cache_manifest_path: Path,
                 cache_manifest_sha256: str, target_date: str, now: datetime | None = None,
                 transport=None, fuyao_key: str | None = None, news_binding: dict | None = None):
        self.state_root=explicit_root(state_root)
        cache_root = explicit_root(cache_root)
        if cache_root == self.state_root or self.state_root not in cache_root.parents:
            raise BoundaryError('cache must be inside the explicit owned state root')
        self.io=SafeRoot(self.state_root);self.io.ensure_directory()
        self.cache=OwnedCache(cache_root,manifest_path=cache_manifest_path,
                              manifest_sha256=cache_manifest_sha256)
        self.target_date=target_date
        if datetime.strptime(target_date,'%Y-%m-%d').strftime('%Y-%m-%d') != target_date:
            raise BoundaryError('invalid exact target date')
        self.now=(now or datetime.now(timezone(timedelta(hours=8)))).astimezone(timezone(timedelta(hours=8)))
        if now is not None and now.tzinfo is None:
            raise BoundaryError('authority clock must be aware')
        self.transport=transport or LiveTransport()
        self.fuyao_key=fuyao_key or ''
        self.news_binding=news_binding
        self.memo={};self.lock=threading.RLock();self._raw={};self._counts=Counter();self.records={}
        self.reason_metadata={}
        self.fatal=[]

    def _request(self,provider,endpoint,params,loader,*,attempts=1,retry_delay=0.0,session=None):
        requested=session or params.get('date') or params.get('end_date') or self.target_date
        if isinstance(requested,str) and re.fullmatch(r'\d{8}',requested):
            requested=f'{requested[:4]}-{requested[4:6]}-{requested[6:8]}'
        identity={'provider':provider,'endpoint':endpoint,'session':requested,'params':_plain(params)}
        key=digest(encoded(identity))
        with self.lock:
            if self.fatal or self.cache.failures:
                raise BoundaryError('known authority boundary failure; additional requests refused')
            if key in self._raw:
                self._counts['reused_raw_requests']+=1
                value=self._raw[key]
                if isinstance(value,Exception):raise SourceUnavailable('previous raw request failed')
                return deepcopy(value)
            self._counts['distinct_raw_requests']+=1
            outcome=None
            for attempt in range(attempts):
                self._counts['physical_transport_calls']+=1
                try:
                    outcome=loader()
                    # Validate response before recording success; keep retries at this owner.
                    packed=self._pack(outcome)
                    break
                except Exception:
                    if attempt+1<attempts:
                        if retry_delay:time.sleep(retry_delay)
                    else:
                        outcome=SourceUnavailable('raw source unavailable: '+provider)
                        packed={'kind':'FAILURE','error_code':'SOURCE_UNAVAILABLE'}
            if isinstance(outcome,Exception):self._counts['failed_requests']+=1
            raw=encoded({'schema':'v4.vibe_raw.v1','identity':identity,
                         'review_target_date':self.target_date,'acquired_at':self.now.isoformat(),
                         'attempts':attempts if isinstance(outcome,Exception) else attempt+1,
                         'result':packed})
            ref={'path':'raw/'+digest(raw)+'.json','bytes':len(raw),'sha256':digest(raw),
                 'session':requested,'kind':packed['kind']}
            try:
                try:
                    self.io.write_bytes(ref['path'],raw,require_absent=True)
                except FileExistsError:
                    if self.io.read_bytes(ref['path'])!=raw:raise BoundaryError('raw collision')
            except (OSError, ValueError) as exc:
                self.fatal.append(type(exc).__name__)
                raise BoundaryError('owned raw publication refused') from exc
            self.records[key]=ref
            self._raw[key]=deepcopy(outcome)
            if isinstance(outcome,Exception):raise outcome
            return deepcopy(outcome)

    @staticmethod
    def _pack(value):
        import pandas as pd
        if isinstance(value,pd.DataFrame):
            return {'kind':'SDK_RETURN_FRAME','columns':[str(c) for c in value.columns],
                    'rows':_plain(value.to_dict('records'))}
        if hasattr(value,'content'):
            content=bytes(value.content)
            if len(content)>32*1024*1024:raise SourceUnavailable('raw response exceeds bound')
            return {'kind':'HTTP_BYTES','status_code':int(getattr(value,'status_code',200)),
                    'content_base64':base64.b64encode(content).decode('ascii')}
        return {'kind':'SDK_RETURN_JSON','value':_plain(value)}

    def ak_call(self,endpoint,**params):
        import pandas as pd
        pool={'stock_zt_pool_em':'zt','stock_zt_pool_zbgc_em':'zb','stock_zt_pool_dtgc_em':'dt'}
        if endpoint in pool and 'date' in params:
            d=str(params['date']);d=f'{d[:4]}-{d[4:6]}-{d[6:8]}' if len(d)==8 else d
            try:
                cached=self.cache.read_json('cache/market_facts/'+d+'.json')
            except FileNotFoundError:
                cached=None
            if cached is not None and cached.get('schema')==3 and cached.get('date')==d:
                raws=cached.get('pools',{}).get('raw',{})
                if pool[endpoint] in raws:
                    self._counts['imported_raw_cache_hits']+=1
                    rows=deepcopy(raws[pool[endpoint]])
                    # Empty raw arrays have no columns; original readers only count zb/dt.
                    return pd.DataFrame(rows)
        return self._request('akshare',endpoint,params,lambda:self.transport.ak(endpoint,**params))

    def http_get(self,url,*,attempts=1,retry_delay=0.0,validate_json=False,**params):
        u=urlsplit(url)
        if u.scheme not in ('http','https') or u.username or u.password:
            raise BoundaryError('unapproved HTTP URL')
        allowed={'push2delay.eastmoney.com','qt.gtimg.cn','api.fuyaoshuju.com'}
        # The Fuyao host is read from the original endpoint constant below.
        from .data_core.fuyao_sources import BASE_URL
        allowed.add(urlsplit(BASE_URL).hostname)
        if u.hostname not in allowed or u.port not in (None,80,443):
            raise BoundaryError('unapproved provider host')
        query=dict(parse_qsl(u.query,keep_blank_values=True))
        semantic=dict(params.get('params') or {})
        query.update(semantic);query.pop('_',None)
        # Tencent symbol list is an unkeyed q= value; URL path/query remain semantic.
        endpoint=urlunsplit((u.scheme,u.netloc,u.path,'',''))
        keyparams={'query':query}
        def load():
            response=self.transport.http_get(url,**params)
            if hasattr(response,'raise_for_status'):response.raise_for_status()
            if validate_json:response.json()
            return RawResponse(bytes(response.content),getattr(response,'status_code',200))
        requested_session = self.target_date
        if u.hostname == urlsplit(BASE_URL).hostname and 'date_ms' in query:
            try:
                requested_session = datetime.fromtimestamp(
                    int(query['date_ms']) / 1000, timezone(timedelta(hours=8))).date().isoformat()
            except (TypeError, ValueError, OverflowError) as exc:
                raise BoundaryError('invalid explicit Fuyao requested session') from exc
        return self._request(u.hostname,endpoint,keyparams,load,attempts=attempts,
                             retry_delay=retry_delay,session=requested_session)

    def iwencai_query(self,query,**params):
        return self._request('iwencai','query',{'query':query,**params},
                             lambda:self.transport.iwencai_query(query,**params))

    def request_counts(self):
        return {**dict(self._counts),
                'sdk_internal_http_calls':'CANNOT_CONFIRM_NOT_INSTRUMENTED',
                'scope':'one generation owner raw boundary, not SDK internal HTTP'}

    def assert_clean(self):
        self.cache.assert_clean()
        if self.fatal:raise BoundaryError('authority input boundary failed')

    def materialize(self, *, implementation_sha256: str, data_as_of: str,
                    assembly_config_sha256: str) -> tuple[dict,str]:
        """Original calculations -> one immutable input, under generation's lock.

        An existing exact input is revalidated and reused, including failures.
        Intentional new acquisition requires an explicit reviewed state/version,
        not deletion of caches or an implicit live fallback.
        """
        from ._evidence import seal_snapshot,verify_evidence,put_content,read_bound
        from ._owned_io import directory,records
        from ._snapshot import FUNCTIONS,SECTIONS,SOURCE_ROLE,timestamp
        from .owned_runtime import verify_owned_sources
        from .data_core import data,trade_calendar
        verify_owned_sources(implementation_sha256)
        timestamp(data_as_of,self.target_date,now=self.now)
        self.cache.io.ensure_directory('reflections')
        # All visible historical records remain available to the scoreboard.
        for name in self.cache.files('reflections'):
            self.cache.read_json('reflections/'+name)
        with directory(self.cache.root/'reflections') as fd:
            _,reflection_manifest,_=records(fd)
        try:
            previous_raw=self.io.read_bytes('inputs/'+self.target_date+'.json',max_bytes=16*1024*1024)
        except FileNotFoundError:
            previous_raw=None
        if previous_raw is not None:
            previous=json.loads(previous_raw)
            if previous.get('assembly_config_sha256')!=assembly_config_sha256:
                raise BoundaryError('existing input belongs to another approved configuration')
            verify_evidence(state_root=self.state_root,payload=previous,
                implementation_sha256=implementation_sha256,reflection_manifest=reflection_manifest)
            self.assert_clean()
            return previous,digest(previous_raw)
        settled=trade_calendar.is_settled(self.target_date,ctx=self)
        # Original calendar is_settled accepts earlier weekdays; the public
        # materializer additionally binds a positive actual-session observation.
        actual_sessions=trade_calendar._ref_dates(self.target_date,self.target_date,ctx=self)
        if not settled or self.target_date not in actual_sessions:
            raise BoundaryError('exact target session lacks positive settled calendar evidence')
        values={}
        for name in FUNCTIONS:
            value=getattr(data,name)(self.target_date,ctx=self)
            values[name]=_plain(value, raw_missing=False)
        # Missing optional sections get an explicit unavailable envelope only;
        # never derive substitutes from another formula/panel or fill zeros.
        for section in SECTIONS:
            parent,child=section.split('.')
            container=values['get_'+parent][1]
            if child not in container:
                container[child]={'available':False,'reason':'original calculation did not produce this section'}
        def meta(value,*,section=False):
            text=value[0] if isinstance(value,list) else value
            okay=(value.get('available') is True) if section else (isinstance(text,str) and bool(text) and not text.lstrip().startswith('[⚠️'))
            result={'status':'READY' if okay else 'CANNOT_CONFIRM','source_id':'V4_OWNED_ORIGINAL_VIBE_DATA',
                    'target_date':self.target_date,'data_as_of':data_as_of,'temporal_basis':'TARGET_SESSION',
                    'source_sha256':'0'*64}
            if not okay:result['reason']=value.get('reason','original section unavailable') if section else 'original source returned a degraded or empty result'
            return result
        sources={name:meta(value) for name,value in values.items()}
        for section in SECTIONS:
            parent,child=section.split('.')
            sources[section]=meta(values['get_'+parent][1][child],section=True)
        query=f'{self.target_date} A股 今日 涨停 热门题材 板块 龙头 复盘'
        if self.news_binding is not None:
            news_doc,news_bytes=read_bound(self.io,self.news_binding,prefixes=('news/',))
            if (news_doc.get('schema')!='v4.vibe_news.v1' or news_doc.get('target_date')!=self.target_date or
                news_doc.get('query')!=query or not isinstance(news_doc.get('text'),str)):
                raise BoundaryError('shared news exact-date/query contract mismatch')
            timestamp(news_doc.get('data_as_of'),self.target_date,now=self.now)
            news={'query':query,'text':news_doc['text']}
            news_status=news_doc.get('status')
            if news_status not in {'READY','CANNOT_CONFIRM'}:
                raise BoundaryError('shared news status missing')
            news_meta=meta(news['text'])
            news_meta['status']=news_status
            news_meta['source_id']=str(news_doc.get('source_id') or 'APPROVED_SHARED_NEWS')
            if news_status=='CANNOT_CONFIRM':news_meta['reason']=str(news_doc.get('reason') or 'shared news unavailable')
            original={'schema':'v4.vibe_raw.v1','review_target_date':self.target_date,
                      'identity':{'provider':'shared_news','endpoint':'exact_snapshot','session':self.target_date,
                                  'params':{'query':query}},
                      'result':{'kind':'SDK_RETURN_JSON','value':news_doc},
                      'original_input_sha256':digest(news_bytes),'original_input_bytes':len(news_bytes)}
            ref=put_content(self.io,'raw',encoded(original));ref.update(session=self.target_date,kind='SDK_RETURN_JSON')
            self.records['news']=ref
        else:
            news={'query':query,'text':''}
            news_meta=meta('');news_meta['reason']='no exact-date shared news input was supplied; no extra search started'
        sources['news']=news_meta
        self.assert_clean()
        cache_refs=[]
        for name,binding in sorted(self.cache.used.items()):
            raw=self.cache.io.read_bytes(name)
            if digest(raw)!=binding['sha256']:raise BoundaryError('cache changed during calculation')
            wrapper={'schema':'v4.vibe_cache_evidence.v1','review_target_date':self.target_date,
                     'session':binding['session'],'original_relative_path':name,
                     'original_sha256':digest(raw),'original_bytes':len(raw),
                     'content_base64':base64.b64encode(raw).decode('ascii'),'origin':binding['origin']}
            ref=put_content(self.io,'cache_evidence',encoded(wrapper));ref['session']=binding['session'];cache_refs.append(ref)
        payload={'schema_version':'v4.vibe_review_inputs.v1','source_role':SOURCE_ROLE,
                 'trade_date':self.target_date,'target_date':self.target_date,'data_as_of':data_as_of,
                 'authority_id':'V4_OWNED_VIBE_SINGLE_FETCH_OWNER','assembly_config_sha256':assembly_config_sha256,
                 'calendar':{**meta('settled'), 'settled':True},'functions':values,'sources':sources,'news':news,
                 'provider_counts':self.request_counts(),
                 'acquired_at':self.now.isoformat(),'review_scope':'POSTHOC_REVIEW_NOT_PIT_FORECAST'}
        return seal_snapshot(state_root=self.state_root,payload=payload,
            raw_refs=[self.records[k] for k in sorted(self.records)],cache_refs=cache_refs,
            reflection_manifest=reflection_manifest,implementation_sha256=implementation_sha256)
