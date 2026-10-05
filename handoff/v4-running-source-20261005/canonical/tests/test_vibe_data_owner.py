"""Raw-boundary fixtures; never substitute the calculation functions."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from collections import Counter
import pandas as pd
import pytest

DATE = '2026-09-11'
RAW_ZT = [{'代码':'000001','名称':'合成一','连板数':2,'所属行业':'电子','首次封板时间':'093100',
           '最后封板时间':'093100','涨跌幅':10.0,'成交额':1000000.0,'换手率':3.0,'封板资金':30000.0,
           '炸板次数':0,'涨停统计':'2/2'},
          {'代码':'300001','名称':'合成二','连板数':1,'所属行业':'机械','首次封板时间':'100000',
           '最后封板时间':'100000','涨跌幅':20.0,'成交额':1200000.0,'换手率':4.0,'封板资金':40000.0,
           '炸板次数':1,'涨停统计':'1/1'}]

class RawTransport:
    def __init__(self, fail=False):
        self.calls = Counter(); self.fail = fail
    def ak(self, endpoint, **params):
        self.calls[(endpoint, tuple(sorted(params.items())))] += 1
        if self.fail:
            raise RuntimeError('fixture endpoint failure')
        if endpoint == 'stock_zt_pool_em':
            return pd.DataFrame(deepcopy(RAW_ZT))
        if endpoint in {'stock_zt_pool_zbgc_em', 'stock_zt_pool_dtgc_em'}:
            return pd.DataFrame(columns=['代码','名称'])
        if endpoint == 'stock_zh_a_hist_tx':
            return pd.DataFrame({'date':['2026-09-09','2026-09-10',DATE]})
        if endpoint == 'stock_zt_pool_previous_em':
            return pd.DataFrame([{'代码':'000001','名称':'合成一','涨跌幅':10.,'昨日连板数':1,
                                  '昨日封板时间':'093000','所属行业':'电子','最新价':11.,'涨停价':11.}])
        raise RuntimeError('fixture has no endpoint: '+endpoint)
    def http_get(self, url, **params):
        self.calls[(url, 'http')] += 1
        raise RuntimeError('fixture HTTP unavailable')


def make_owner(tmp_path, *, fail=False, prefilled=None):
    from domains.research_review_generation.owned_authority import VibeDataAuthority
    root=tmp_path/'state'; root.mkdir(parents=True)
    cache=root/'data'; cache.mkdir()
    files={}
    for name,obj in (prefilled or {}).items():
        raw=(json.dumps(obj,ensure_ascii=False,sort_keys=True)+'\n').encode()
        p=cache/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        files[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    manifest={'schema':'v4.vibe_cache_inventory.v1','files':files}
    path=root/'cache-inventory.json';raw=json.dumps(manifest,sort_keys=True).encode();path.write_bytes(raw)
    tr=RawTransport(fail=fail)
    owner=VibeDataAuthority(state_root=root, cache_root=cache, cache_manifest_path=path,
        cache_manifest_sha256=hashlib.sha256(raw).hexdigest(), target_date=DATE,
        now=datetime.fromisoformat('2026-09-13T20:00:00+08:00'), transport=tr)
    return owner,tr


def test_three_high_level_readers_share_each_raw_pool_request(tmp_path):
    from domains.research_review_generation.data_core import data, market_facts, emotion_metrics
    ctx,tr=make_owner(tmp_path)
    text=data.get_sentiment_data(DATE,ctx=ctx)
    pools=market_facts.pools(DATE,ctx=ctx)
    emotion=emotion_metrics._zt_pool(DATE,ctx=ctx)
    assert '涨停 2 家' in text
    assert len(pools['zt'])==2 and len(emotion['zt'])==2
    assert sum(n for (name,_),n in tr.calls.items() if name.startswith('stock_zt_pool_')) == 3


def test_failed_raw_request_is_reused_not_refetched(tmp_path):
    from domains.research_review_generation.data_core import data, market_facts
    ctx,tr=make_owner(tmp_path,fail=True)
    assert data.get_sentiment_data(DATE,ctx=ctx).startswith('[⚠️')
    assert market_facts.pools(DATE,ctx=ctx) is None
    assert all(n==1 for n in tr.calls.values())
    assert ctx.request_counts()['failed_requests'] >= 1


def test_dates_and_parameters_are_distinct_raw_identities(tmp_path):
    ctx,tr=make_owner(tmp_path)
    for d in ['20260910','20260911','20260910']:
        ctx.ak_call('stock_zt_pool_em',date=d)
    assert sum(tr.calls.values())==2
    ctx.ak_call('stock_zh_a_hist_tx',symbol='sh600000',start_date='20260901',end_date='20260911')
    ctx.ak_call('stock_zh_a_hist_tx',symbol='sh600000',start_date='20260902',end_date='20260911')
    assert sum(tr.calls.values())==4


def test_imported_full_raw_cache_satisfies_pool_without_transport(tmp_path):
    from domains.research_review_generation.data_core import data
    cached={'schema':3,'date':DATE,'pools':{'zt':[],'zb':[],'dt':[],
                       'raw':{'zt':RAW_ZT,'zb':[],'dt':[]}}}
    ctx,tr=make_owner(tmp_path,prefilled={f'cache/market_facts/{DATE}.json':cached})
    assert '涨停 2 家' in data.get_sentiment_data(DATE,ctx=ctx)
    assert not tr.calls


def test_cache_bytes_drift_or_unowned_path_refused(tmp_path):
    from domains.research_review_generation._owned_io import BoundaryError
    ctx,tr=make_owner(tmp_path,prefilled={f'cache/zt_summary/{DATE}.json':{'schema':1,'date':DATE,'summary':{}}})
    with pytest.raises((ValueError,OSError)):
        ctx.cache.write_json('../outside.json',{})
    p=ctx.cache.root/f'cache/zt_summary/{DATE}.json';p.write_text('{}')
    with pytest.raises(BoundaryError):
        ctx.cache.read_json(f'cache/zt_summary/{DATE}.json')
    assert not tr.calls


def test_same_raw_request_is_single_flight_across_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ctx,tr=make_owner(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values=list(pool.map(lambda _:ctx.ak_call('stock_zt_pool_em',date='20260911'),range(16)))
    assert len(values)==16 and sum(tr.calls.values())==1


def test_cache_embedded_date_rejected_even_with_matching_file_hash(tmp_path):
    from domains.research_review_generation.data_core import market_facts
    from domains.research_review_generation._owned_io import BoundaryError
    ctx,tr=make_owner(tmp_path,prefilled={f'cache/market_facts/{DATE}.json':{'date':'2026-09-10','schema':3,'pools':{}}})
    with pytest.raises(BoundaryError):ctx.cache.read_json(f'cache/market_facts/{DATE}.json')
    with pytest.raises(BoundaryError):ctx.assert_clean()
    assert not tr.calls


def test_explicit_old_vibe_root_is_not_accepted(tmp_path):
    from domains.research_review_generation._cache import explicit_root
    from domains.research_review_generation._owned_io import BoundaryError
    with pytest.raises(BoundaryError):explicit_root(tmp_path/'.duanxian-agents')


def test_fuyao_keeps_bounded_pagination_and_no_iwencai_fallback(tmp_path):
    from domains.research_review_generation.data_core.fuyao_sources import fetch_limit_up_reasons,FuyaoConfigError
    with pytest.raises(FuyaoConfigError):fetch_limit_up_reasons('20260911',api_key='SYNTHETIC')


def test_http_retry_budget_is_owned_once_then_failure_is_reused(tmp_path):
    ctx,tr=make_owner(tmp_path)
    with pytest.raises(RuntimeError):ctx.http_get('https://push2delay.eastmoney.com/api/qt/clist/get',params={'fid':'f62'},attempts=3,retry_delay=0,timeout=1)
    with pytest.raises(RuntimeError):ctx.http_get('https://push2delay.eastmoney.com/api/qt/clist/get',params={'fid':'f62'},attempts=3,retry_delay=0,timeout=1)
    assert sum(tr.calls.values())==3
    assert ctx.request_counts()['physical_transport_calls']==3
    assert ctx.request_counts()['reused_raw_requests']==1


@pytest.mark.parametrize('bad_date',[False,True])
def test_actual_fuyao_pages_validate_and_share_raw_requests(tmp_path,bad_date):
    from domains.research_review_generation.data_core.fuyao_sources import fetch_limit_up_reasons,FuyaoSchemaError
    from domains.research_review_generation.owned_authority import RawResponse
    ctx,_=make_owner(tmp_path)
    class Pages:
        calls=0
        def http_get(self,url,**kwargs):
            self.calls+=1;page=kwargs['params']['page']
            code=f'{page:06d}'
            value={'code':0,'data':{'trade_date':'20260910' if bad_date else '20260911',
                'pagination':{'total':2,'pages':2,'size':1,'page':page},
                'item':[{'ticker':code,'thscode':code+'.SZ','name':'合成样本',
                         'limit_up_reason':'合成题材','limit_up_time':'09:31:00'}]}}
            return RawResponse(json.dumps(value).encode(),200)
    pages=Pages();ctx.transport=pages
    if bad_date:
        with pytest.raises(FuyaoSchemaError):fetch_limit_up_reasons('20260911',api_key='SYNTHETIC',page_size=1,http_get=ctx.http_get)
        assert pages.calls==1
        return
    first=fetch_limit_up_reasons('20260911',api_key='SYNTHETIC',page_size=1,http_get=ctx.http_get)
    second=fetch_limit_up_reasons('20260911',api_key='SYNTHETIC',page_size=1,http_get=ctx.http_get)
    assert first.reasons==second.reasons=={'000001':'合成题材','000002':'合成题材'}
    assert first.metadata['response_explicit_date_validated'] is True
    assert pages.calls==2 and ctx.request_counts()['reused_raw_requests']==2
    assert b'SYNTHETIC' not in b''.join((ctx.state_root/r['path']).read_bytes() for r in ctx.records.values())


def test_fuyao_raw_identity_keeps_requested_historical_session(tmp_path):
    from domains.research_review_generation.data_core.fuyao_sources import requested_date_ms,BASE_URL,ENDPOINT
    from domains.research_review_generation.owned_authority import RawResponse
    ctx,_=make_owner(tmp_path)
    class Response:
        def http_get(self,url,**kwargs):return RawResponse(b'{}')
    ctx.transport=Response()
    ctx.http_get(BASE_URL+ENDPOINT,params={'date_ms':requested_date_ms('20260910'),'page':1,'size':200})
    ref=list(ctx.records.values())[0]
    assert ref['session']=='2026-09-10'
    obj=json.loads((ctx.state_root/ref['path']).read_bytes())
    assert obj['identity']['session']=='2026-09-10'
    assert obj['review_target_date']==DATE
