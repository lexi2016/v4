"""Offline SYNTHETIC fixtures through the unchanged producer/store, not market data."""
from __future__ import annotations
import ast
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import inspect
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v35_api import research_lane_router as lane
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops.us_market_digest import build_us_market_phase_payload, GLOBAL_INDUSTRY_PROXY_MAP

NOW = datetime.fromisoformat('2026-09-23T09:00:00+08:00')

def payload(session='20260922', mixed=False):
    quotes = {symbol: {'last': 101.0, 'previous_close': 100.0, 'change_pct': 1.0,
              'session_date': session, 'session_time': '16:00:00'}
              for row in GLOBAL_INDUSTRY_PROXY_MAP for symbol in row['proxy_symbols']}
    if mixed:
        quotes['NVDA']['session_time'] = '16:01:00'
    iso = f'{session[:4]}-{session[4:6]}-{session[6:]}T20:15:03Z'
    result = build_us_market_phase_payload(session, capture_phase='POST_CLOSE', fetched_at=iso,
        fetch_rss=lambda *a: b'<rss><channel></channel></rss>', fetch_quotes=lambda *a: quotes)
    # The existing materialized PARTIAL contract is explicitly simulated here.
    if mixed:
        result['status'] = 'CANNOT_CONFIRM'
        result['market_snapshot']['status'] = 'PARTIAL'
        result['market_snapshot_status'] = 'PARTIAL'
        result['market_snapshot']['cannot_confirm'] = ['QUOTE_SESSION_TIME_MIXED']
    return result

def put(root, session='20260922', mixed=False):
    value = payload(session, mixed)
    ResearchPeripheralStore(root).publish(value)
    return value

def client(tmp_path, monkeypatch, *, split=True):
    from infrastructure import research_lane_source
    monkeypatch.setattr(research_lane_source, 'shanghai_now', lambda: NOW)
    legacy, current = tmp_path/'legacy', tmp_path/'v4'
    args = {'us_market_data_root': current} if 'us_market_data_root' in inspect.signature(lane.create_research_lane_router).parameters else {}
    app=FastAPI();app.include_router(lane.create_research_lane_router(legacy if split else current, **args))
    return TestClient(app),legacy,current

def test_module_specific_wrong_root_keeps_other_dates_unchanged(tmp_path, monkeypatch):
    c,old,new=client(tmp_path, monkeypatch)
    put(old,'20260914');put(new)
    dates=c.get('/api/v3/research/dates').json()
    assert dates['external_finance_dates']==['20260914']
    assert dates['market_snapshot_dates']==['20260922'], 'US picker still uses legacy root'
    result=c.get('/api/v3/research/us-market?research_date=20260922').json()
    assert result['status']=='READY'
    assert result['market_source']['source_root']==str(new)
    assert result['artifact']['path'].startswith(str(new))

def test_app_passes_only_market_root_from_native_store():
    src=Path(lane.__file__).with_name('app.py').read_text()
    tree=ast.parse(src)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='create_research_lane_router']
    assert len(calls)==1
    assert ast.unparse(calls[0].args[0])=='resolved_research_root'
    assert any(k.arg=='us_market_data_root' and ast.unparse(k.value)=='store.root' for k in calls[0].keywords)

@pytest.mark.parametrize('session,expected', [('20260914','STALE'),('20260922','READY')])
def test_old_ready_not_current_update_and_normal_close(tmp_path, monkeypatch,session,expected):
    c,old,new=client(tmp_path,monkeypatch,split=False);put(new,session)
    r=c.get('/api/v3/research/us-market',params={'research_date':session}).json()
    assert r['status']=='READY'  # raw stored quality is retained, never relabel source bytes
    assert r.get('display_status')==expected
    assert r['freshness']['exchange_calendar_status']=='VERIFIED_NYSE_2026'
    assert r['freshness']['latest_exchange_session']=='20260922'
    assert r['freshness']['latest_exchange_session_verified'] is True
    assert r['freshness']['new_capture_performed'] is False  # read-only endpoint
    assert r['freshness']['captured_at'] == f'{session[:4]}-{session[4:6]}-{session[6:]}T20:15:03Z'
    assert r['source_date']==session and r['research_date']==session

def test_latest_partial_keeps_both_times_and_quality(tmp_path,monkeypatch):
    c,old,new=client(tmp_path,monkeypatch,split=False);put(new,'20260921');original=put(new,mixed=True)
    d=c.get('/api/v3/research/dates').json()
    assert d['market_snapshot_dates'][0]=='20260922'
    r=c.get('/api/v3/research/us-market?research_date=20260922').json()
    assert r['status']=='PARTIAL' and r.get('display_status')=='PARTIAL'
    assert 'QUOTE_SESSION_TIME_MIXED' in r['cannot_confirm']
    assert r['provider_session_times']==original['market_snapshot']['provider_session_times']
    assert r['quotes']==original['market_snapshot']['quotes']
    assert len(r['rows'])==24 and r['available_symbol_count']==33

def test_missing_exact_new_date_never_returns_old_ready(tmp_path,monkeypatch):
    c,old,new=client(tmp_path,monkeypatch,split=False);put(new,'20260914')
    r=c.get('/api/v3/research/us-market?research_date=20260923').json()
    assert r['status']=='CANNOT_CONFIRM' and r['source_date']==''
    assert r.get('display_status')=='CANNOT_CONFIRM'

def assessed(value, now=NOW):
    fn=getattr(lane,'_with_us_market_freshness',None)
    assert callable(fn), 'Separate freshness assessor is missing'
    return fn(value,observed=now)

def projected(tmp_path):
    put(tmp_path)
    return lane._project_global_industries(store=ResearchPeripheralStore(tmp_path),research_date='20260922')

@pytest.mark.parametrize('field,value',[
    ('captured_at','2026-09-23T20:15:03Z'),
    ('captured_at','2026-09-22T20:19:00Z'),
    ('captured_at','2026-09-22T20:15:03'),
    ('generated_at','2026-09-24T20:15:03Z'),
])
def test_time_identity_and_future_fail_closed(tmp_path,field,value):
    p=projected(tmp_path);p[field]=value
    r=assessed(p)
    assert r['display_status']=='CANNOT_CONFIRM'
    assert r['status']=='READY'
    assert r['freshness']['state']=='CANNOT_CONFIRM'

def test_aged_snapshot_generated_now_still_stale(tmp_path):
    put(tmp_path,'20260914')
    p=lane._project_global_industries(store=ResearchPeripheralStore(tmp_path),research_date='20260914')
    p['generated_at']=NOW.isoformat()
    assert assessed(p)['display_status']=='STALE'

def test_mixed_session_is_diagnostic_not_usable(tmp_path):
    p=projected(tmp_path)
    p['provider_session_dates']=['20260921','20260922']
    r=assessed(p)
    assert r['display_status']=='CANNOT_CONFIRM'
    assert r['provider_session_dates']==['20260921','20260922']

def test_weekend_clock_does_not_certify_previous_exchange_day(tmp_path):
    p=projected(tmp_path)
    r=assessed(p,datetime.fromisoformat('2026-09-27T10:00:00+08:00'))
    assert r['display_status']=='STALE'
    assert r['freshness']['exchange_calendar_status']=='VERIFIED_NYSE_2026'
    assert r['freshness']['latest_exchange_session']=='20260925'
    assert r['freshness']['latest_exchange_session_verified'] is True
    assert r['freshness']['new_capture_performed'] is False

def test_not_due_is_zero_capture_not_business_update(tmp_path):
    reg=FixedExecutorRegistry(tmp_path)
    def unexpected(*args,**kwargs):
        raise AssertionError('NOT_DUE attempted producer work')
    reg._run=unexpected
    r=reg._us_market_digest(SimpleNamespace(business_date='20260923',slot='0515'))
    assert r['status']=='SUCCEEDED' and r['capture_status']=='NOT_DUE'
    assert r.get('capture_performed') is False
    assert r.get('capture_artifact_verified') is False
    assert r.get('data_update_status')=='NOT_DUE_NO_UPDATE'
    assert not list(tmp_path.rglob('*.json'))

def test_noop_does_not_make_old_store_current(tmp_path,monkeypatch):
    test_not_due_is_zero_capture_not_business_update(tmp_path/'task')
    c,old,new=client(tmp_path,monkeypatch,split=False);put(new,'20260914')
    r=c.get('/api/v3/research/us-market?research_date=20260914').json()
    assert r['display_status']=='STALE'

def test_exact_artifact_does_not_prove_fresh_capture_or_new_bytes(tmp_path):
    import json
    from infrastructure.data_store import _sha256
    reg=FixedExecutorRegistry(tmp_path)
    prior=put(tmp_path)
    # Simulate the real collector's idempotent return. Its CLI drops `reused`.
    summary={'status':prior['status'],'trade_date':'20260922','source':'external_finance',
        'payload_path':'research/peripherals/20260922/external_finance.json',
        'payload_sha256':_sha256(prior),'capture_origin':prior['capture_origin'],
        'original_time_capture':prior['original_time_capture']}
    calls=[]
    def run(module,args):
        calls.append((module,args));return {'status':'SUCCEEDED','exit_code':0,'stdout':json.dumps(summary)}
    reg._run=run
    result=reg._us_market_digest(SimpleNamespace(business_date='20260923',slot='0415'))
    assert len(calls)==1 and result['capture_artifact_verified'] is True
    assert result.get('capture_performed') is None
    assert result.get('collector_invoked') is True
    assert result.get('new_capture_verified') is False
    assert result.get('data_update_status')=='EXACT_ARTIFACT_VERIFIED_UPDATE_UNCONFIRMED'

def test_reads_do_not_mutate_artifact_receipt_or_manifest(tmp_path,monkeypatch):
    import hashlib
    c,old,new=client(tmp_path,monkeypatch,split=False);put(new,mixed=True)
    def inventory():return {p.relative_to(new).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in new.rglob('*') if p.is_file()}
    before=inventory()
    for path in ['/api/v3/research/dates','/api/v3/research/us-market?research_date=20260922']:
        assert c.get(path).status_code==200
    assert inventory()==before

def test_new_root_missing_never_silently_falls_back_to_legacy(tmp_path,monkeypatch):
    c,old,new=client(tmp_path,monkeypatch);put(old,'20260922')
    assert c.get('/api/v3/research/dates').json()['market_snapshot_dates']==[]
    r=c.get('/api/v3/research/us-market?research_date=20260922').json()
    assert r['status']=='CANNOT_CONFIRM' and r['market_source']['source_root']==str(new)

@pytest.mark.parametrize('stamp', ['2026-09-22T20:14:59Z','2026-09-22T20:20:00Z'])
def test_original_capture_cutoff_not_extended(tmp_path,stamp):
    p=projected(tmp_path);p['captured_at']=p['bound_capture_captured_at']=stamp;p['generated_at']=stamp
    r=assessed(p)
    assert r['display_status']=='CANNOT_CONFIRM'
    assert 'CAPTURE_OUTSIDE_ORIGINAL_BOUND_WINDOW' in r['freshness']['cannot_confirm']




def test_saturday_before_cutoff_does_not_certify_friday_close(tmp_path, monkeypatch):
    c, _, new = client(tmp_path, monkeypatch, split=False)
    original = put(new, '20260918')
    from infrastructure import research_lane_source
    observed = datetime.fromisoformat('2026-09-19T22:00:00+08:00')
    monkeypatch.setattr(research_lane_source, 'shanghai_now', lambda: observed)
    response = c.get('/api/v3/research/us-market', params={'research_date': '20260918'})
    assert response.status_code == 200
    r = response.json()
    assert r['status'] == 'READY'
    assert r['source_date'] == '20260918'
    assert r['display_status'] == 'READY'
    assert r['freshness']['state'] == 'RECENT_BOUND_CAPTURE'
    assert r['freshness']['exchange_calendar_status'] == 'VERIFIED_NYSE_2026'
    assert r['freshness']['latest_exchange_session'] == '20260918'
    assert r['freshness']['latest_exchange_session_verified'] is True
    assert r['freshness']['new_capture_performed'] is False
    assert 'US_MARKET_WEEKEND_UNCERTIFIED' not in r['freshness']['cannot_confirm']
    assert r['quotes'] == original['market_snapshot']['quotes']
