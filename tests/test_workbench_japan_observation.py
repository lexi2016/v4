"""Bounded foreign observations in the existing owner; no network in tests."""
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import pytest

OWNER = os.environ.get('V4_OBSERVATION_OWNER_APP')
if not OWNER:
    pytest.skip('Pin the existing observation owner dependency root', allow_module_level=True)
sys.path.insert(0, OWNER)
ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


c = module('ops.collect_workbench_observations', ROOT / 'ops/collect_workbench_observations.py')
runner = module('market_observation_slot_under_test', ROOT / 'ops/run_workbench_observation_slot.py')
NOW = datetime.fromisoformat('2026-11-05T11:00:00+08:00')
DAY = '2026-11-05'
IDENTITY = dict(source_date='2026-11-04', generation='a' * 64, input_sha256='b' * 64)
FIXTURES = Path(os.environ['V4_MARKET_SOURCE_FIXTURES'])


def normalize(value):
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, dict): return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list): return [normalize(v) for v in value]
    return value


def jp_record():
    return normalize(json.loads((FIXTURES / 'FUTU_N225_SNAPSHOT_PROBE.json').read_text())['rows'][0])


class Frame:
    def __init__(self, records): self.records = records
    def to_json(self, **kwargs): return json.dumps(self.records, ensure_ascii=False, allow_nan=False)


class Quote:
    def __init__(self, record): self.record, self.calls, self.closed = record, [], False
    def get_market_snapshot(self, codes): self.calls.append(codes); return 0, Frame([self.record])
    def close(self): self.closed = True


def web_reader(calls):
    oracle = (FIXTURES / 'US_SOURCE.json').read_bytes()
    def read(url):
        calls.append(url)
        if url.startswith('http://127.0.0.1:8873/'): return oracle
        code = '.DJI' if '.DJI-US' in url else '.SPX' if '.SPX-US' in url else '.IXIC'
        return (FIXTURES / ('FUTU_' + code[1:] + '_PAGE.html')).read_bytes()
    return read


def kr_read(url):
    symbol = '^KS11' if 'KS11' in url else '^KQ11'
    stamp = int(datetime.fromisoformat('2026-11-05T11:30:00+09:00').timestamp())
    prior = int(datetime.fromisoformat('2026-11-04T15:30:00+09:00').timestamp())
    return json.dumps({'chart': {'result': [dict(meta=dict(symbol=symbol,instrumentType='INDEX',exchangeTimezoneName='Asia/Seoul',regularMarketTime=stamp,regularMarketPrice=100),timestamp=[prior,stamp],indicators={'quote':[{'close':[102,100]}]})]}}).encode()


def test_actual_three_official_html_pages_parse_quote_dom_and_exact_ny_close():
    expected = {'.DJI': (53356.12,3.03), '.SPX': (7688.620,1.58), '.IXIC': (25736.513,1.44)}
    for code,name,official,url in c.US_INDICES:
        raw = (FIXTURES / ('FUTU_' + code[1:] + '_PAGE.html')).read_bytes()
        row = c.parse_us_index(raw, code, name, official, url, '20261104', NOW)
        assert (row['value'], row['change_pct']) == expected[code]
        assert row['source_asof'] == '2026-11-04T16:00:00-05:00'
        assert row['raw_sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('change', ['canonical','status','session','price','title'])
def test_us_html_wrong_identity_session_or_baseline_rejected(change):
    raw = (FIXTURES / 'FUTU_SPX_PAGE.html').read_bytes()
    session = '20261104'
    if change == 'canonical': raw = raw.replace(b'rel="canonical" href="https://www.futunn.com/index/.SPX-US"', b'rel="canonical" href="https://www.futunn.com/index/.IXIC-US"')
    elif change == 'status': raw = raw.replace('收盘价 11/04 16:00'.encode(), '收盘价 11/04 15:00'.encode())
    elif change == 'session': session = '20261103'
    elif change == 'price': raw = raw.replace(b'"priceLastClose":"7568.920"', b'"priceLastClose":"100.000"')
    elif change == 'title': raw = raw.replace('<title>标普500指数(.SPX)'.encode(), '<title>别的指数(.SPX)'.encode())
    with pytest.raises(ValueError): c.parse_us_index(raw,'.SPX','标普500','标普500指数','https://www.futunn.com/index/.SPX-US',session,NOW)


def test_japan_actual_quote_rows_tokyo_date_price_and_close_context():
    quote = Quote(jp_record());view, raw = c.japan(DAY, lambda: NOW, lambda: quote)
    assert view['status'] == 'DATED_INDEX_OBSERVATION'
    assert view['value'] == 61913.51 and view['previous_close'] == 62188.63
    assert view['change_pct'] == round((61913.51/62188.63-1)*100,4)
    assert view['source_asof'] == '2026-11-05T11:30:00+09:00'
    assert quote.closed and quote.calls == [['JP..N225']]
    assert view['raw_sha256'] == c.digest(raw['records'])


@pytest.mark.parametrize('key,value', [('code','JP.OTHER'),('index_valid',False),('prev_close_price',None),('last_price',0),('update_time','2026-11-04 11:30:00'),('update_time','2026-11-05 21:30:00')])
def test_japan_bad_quotes_remain_null_and_quote_context_closes(key,value):
    row = jp_record();row[key] = value;quote = Quote(row)
    view,_ = c.japan(DAY,lambda: NOW,lambda: quote)
    assert quote.closed and view['status'] == 'SOURCE_ERROR'
    assert view['value'] is None and view['change_pct'] is None


def test_existing_publish_binds_full_raw_foreign_context_and_reuses_only_completed_us_session(tmp_path):
    quote = Quote(jp_record());calls=[]
    snapshot,kr,raw = c.collect(DAY,'1100',IDENTITY,['000001.SZ'],now=NOW,clock=lambda: NOW,quote_factory=lambda:quote,us_read=web_reader(calls),kr_read=kr_read)
    assert snapshot['context']['us_benchmarks']['status'] == 'DATED_US_BENCHMARKS'
    assert len(calls)==4  # oracle + three webpages, once
    pointer = c.publish(tmp_path,snapshot,kr,raw)
    published = c.checked(pointer['snapshot']);receipt = c.checked(pointer['receipt']);fullraw = c.checked(receipt['raw'])
    assert published['context']['japan']['raw_ref'] == receipt['raw']
    assert published['context']['us_benchmarks']['raw_ref'] == receipt['raw']
    assert 'window.__INITIAL_STATE__' in fullraw['original_owner']['us_benchmarks']['pages']['.SPX']['html']
    assert published['rows']==snapshot['rows'] and len(published['rows'])==1
    copied = dict(published);saved_sha = copied.pop('snapshot_sha256');assert saved_sha == c.digest(copied)
    cached, cached_raw = c.us_benchmarks(DAY,lambda: NOW,web_reader(calls),prior=published['context']['us_benchmarks'])
    assert cached['reused_completed_session'] is True and cached_raw=={} and len(calls)==5
    jp,_ = c.japan(DAY,lambda: NOW,lambda:pytest.fail('same-slot Japan should reuse'),prior=published['context']['japan'])
    assert jp['reused_same_slot'] is True


def test_runner_passes_only_foreign_context_across_slots_and_preserves_schedule(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'load_market_calendar',lambda *args:object())
    monkeypatch.setattr(runner,'resolve_market_states',lambda *args:{'a_share':runner.TradingDayState.FULL_TRADING_DAY})
    monkeypatch.setattr(runner,'previous_session',lambda *args,**kwargs:'20261104')
    product_root=tmp_path/'product';state=tmp_path/'state';state.mkdir();product_root.mkdir()
    product=c.put(product_root/'product.json',dict(source_generation=IDENTITY['generation'],source_identity={'input_sha256':IDENTITY['input_sha256']},rows=[{'symbol':'000001.SZ'}]))
    manifest=c.put(product_root/'manifest.json',{'artifact':product});c.put(product_root/'index.json',{'dates':{'20261104':manifest}})
    authority=c.put(tmp_path/'authority.json',{'source':'test'})
    binding=c.put(tmp_path/'binding.json',{'observation_dates':{'2026-11-04':{'date':DAY,'authority':authority}}})
    foreign={'us_benchmarks':{'cache':'foreign-only'}}
    latest=c.put(tmp_path/'prior.json',dict(source_date=IDENTITY['source_date'],observation_date=DAY,source_generation=IDENTITY['generation'],input_sha256=IDENTITY['input_sha256'],context=foreign,rows=[{'symbol':'MUST_NOT_REUSE_A_ROWS'}]))
    c.put(state/DAY/'latest.json',{'snapshot':latest})
    seen={}
    def collector(day,slot,identity,symbols,**kwargs):
        seen.update(kwargs);return dict(observation_date=day,slot=slot,recorded_at=NOW.isoformat(),rows=[{'symbol':s,'error':'original-gap'} for s in symbols]),{'indices':[{'value':None}]},{}
    monkeypatch.setattr(runner,'publish',lambda *args:{'test_pointer':True})
    result=runner.run(dict(state_root=str(state),product_root=str(product_root),host_binding=binding),now=NOW,collector=collector,manual=True)
    assert seen['foreign_context']==foreign and seen['prior_snapshot'] is None and seen['prior_korea'] is None
    assert result['scope']==1 and len(runner.SLOTS)==35


@pytest.mark.parametrize('day,session,close_hour,offset',[
    ('2026-11-06','20261105',16,-5),('2026-11-09','20261106',16,-5),
    ('2026-10-30','20261029',16,-4),('2026-11-27','20261125',16,-5),
    ('2026-11-30','20261127',13,-5)])
def test_daily_calendar_behavior_and_synthetic_page_clocks_not_future_market_data(day,session,close_hour,offset):
    now=datetime.fromisoformat(day+'T08:00:00+08:00');completed=c.latest_completed_session(now)
    assert completed.session_date==session and completed.close_at.hour==close_hour
    assert completed.close_at.utcoffset().total_seconds()==offset*3600
    raw=(FIXTURES/'FUTU_SPX_PAGE.html').read_bytes()
    # Only the test's clock fields are changed. Prices are historical samples,
    # never claimed as quotes or execution on these future observation dates.
    raw=raw.replace(b'1793826000000',str(int(completed.close_at.timestamp()*1000)).encode())
    raw=raw.replace(b'11/04 16:00',(session[4:6]+'/'+session[6:]+' '+completed.close_at.strftime('%H:%M')).encode())
    row=c.parse_us_index(raw,'.SPX','标普500','标普500指数','https://www.futunn.com/index/.SPX-US',session,now)
    assert row['source_asof']==completed.close_at.isoformat()


def test_upstream_stale_or_missing_exact_target_is_unknown_without_page_downloads():
    calls=[]
    def read(url):
        calls.append(url)
        oracle=json.loads((FIXTURES/'US_SOURCE.json').read_bytes());
        for key in ('research_date','target_date','target_trade_date'):oracle[key]='20261106'
        return json.dumps(oracle).encode()  # old11/04 session, expected11/05
    view,_=c.us_benchmarks('2026-11-06',lambda:datetime.fromisoformat('2026-11-06T08:00:00+08:00'),read)
    assert view['status']=='SOURCE_ERROR' and 'COMPLETED_SESSION_MISMATCH' in view['error'] and len(calls)==1
    missing=lambda url:json.dumps({'research_date':'20261106','status':'CANNOT_CONFIRM'}).encode()
    view,_=c.us_benchmarks('2026-11-06',lambda:datetime.fromisoformat('2026-11-06T08:00:00+08:00'),missing)
    assert view['status']=='SOURCE_ERROR' and not view['rows']


def test_archive_external_qualified_hot_raw_with_new_receipt_preserves_old_reference(tmp_path):
    old=c.put(tmp_path/'external-qualified'/'raw.json',{'qualified':'TEST_ONLY_CANONICAL_BYTES'})
    root=tmp_path/'canonical';snapshot=dict(observation_date=DAY,slot='1100',recorded_at=NOW.isoformat(),context={'us_benchmarks':dict(status='DATED_US_BENCHMARKS',us_session_date='20261104',raw_ref=old)})
    pointer=c.publish(root,snapshot,{'indices':[]},{})
    saved=c.checked(pointer['snapshot']);view=saved['context']['us_benchmarks']
    assert Path(view['raw_ref']['path']).is_relative_to(root/'sources')
    assert view['raw_ref']['sha256']==old['sha256'] and view['archived_from']==old
    assert c.checked(old)==c.checked(view['raw_ref'])
    raw_path=Path(view['raw_ref']['path']);before=raw_path.stat().st_mtime_ns
    snapshot['slot']='1110';c.publish(root,snapshot,{'indices':[]},{})
    assert raw_path.stat().st_mtime_ns==before  # canonical immutable source unchanged


@pytest.mark.parametrize('day,expected_source',[('2026-11-06','2026-11-05'),('2026-11-09','2026-11-06')])
def test_runner_next_day_weekend_and_restart_protocol_without_future_natural_claim(tmp_path,day,expected_source):
    now=datetime.fromisoformat(day+'T10:00:00+08:00');state=tmp_path/'state';product_root=tmp_path/'products';product_root.mkdir()
    calendar_path=Path(OWNER)/'contracts/market_calendar_2026.json';calendar_ref={'path':str(calendar_path),'sha256':hashlib.sha256(calendar_path.read_bytes()).hexdigest()}
    product=c.put(product_root/'product.json',dict(source_generation=IDENTITY['generation'],source_identity={'input_sha256':IDENTITY['input_sha256']},rows=[{'symbol':'000001.SZ'}]))
    manifest=c.put(product_root/'manifest.json',{'artifact':product});c.put(product_root/'index.json',{'dates':{expected_source.replace('-',''):manifest}})
    binding=c.put(tmp_path/'binding.json',{'calendar':calendar_ref});config=dict(state_root=str(state),product_root=str(product_root),host_binding=binding,calendar=calendar_ref)
    calls=[]
    def collector(observation,slot,identity,symbols,**kwargs):
        calls.append(identity['source_date']);return dict(schema='OBSERVATION_SNAPSHOT_VIEW_V1',source_date=identity['source_date'],source_generation=identity['generation'],input_sha256=identity['input_sha256'],observation_date=observation,slot=slot,recorded_at=now.isoformat(),rows=[{'symbol':symbol,'error':'TEST_ONLY_NO_FUTURE_QUOTE'} for symbol in symbols]),{'indices':[{'value':None}]},{}
    result=runner.run(config,now=now,collector=collector);assert result['manual'] is False and calls==[expected_source]
    runner.run(config,now=now,collector=collector)
    result=runner.run(config,now=now,collector=collector);assert result['status']=='DIAGNOSIS_REQUIRED' and len(calls)==2
    c.put(product_root/'index.json',{'dates':{}});result=runner.run(config,now=now,collector=collector);assert result['error']=='PREVIOUS_SESSION_PRODUCT_MISSING'
    unknown=runner.run(config,now=datetime.fromisoformat('2027-01-04T10:00:00+08:00'),collector=collector);assert unknown['status']=='CANNOT_CONFIRM'


@pytest.mark.parametrize('day,session,capture',[('2026-11-09','20261106','20261107'),('2026-11-27','20261125','20261126'),('2026-11-30','20261127','20261128')])
def test_exact_original_close_capture_day_is_distinct_from_a_observation(day,session,capture,tmp_path):
    now=datetime.fromisoformat(day+'T08:00:00+08:00');completed=c.latest_completed_session(now);calls=[]
    oracle=json.loads((FIXTURES/'US_SOURCE.json').read_bytes())
    for key in ('research_date','target_date','target_trade_date'):oracle[key]=capture
    for key in ('source_date','us_session_date','capture_session_date'):oracle[key]=session
    oracle['provider_session_dates']=[session]
    prior=dict(schema='V4_WORKBENCH_US_BENCHMARKS_V1',observation_date=day,status='DATED_US_BENCHMARKS',us_session_date=session,raw_ref=c.put(tmp_path/'raw.json',{'TEST_ONLY':True}),rows=[dict(symbol=row[0]) for row in c.US_INDICES])
    def read(url):calls.append(url);return json.dumps(oracle).encode()
    view,raw=c.us_benchmarks(day,lambda:now,read,prior)
    assert view['status']=='DATED_US_BENCHMARKS' and view['observation_date']==day
    assert view['oracle']['research_date']==capture and view['oracle']['session_date']==session
    assert view['session_close_at']==completed.close_at.isoformat() and view['market_context']==oracle
    assert calls==['http://127.0.0.1:8873/api/v4/research/us-market?research_date='+capture] and raw=={}
    for key,value in [('capture_phase','PRE_OPEN'),('us_session_date','20261102'),('research_date',day.replace('-',''))]:
        wrong=dict(oracle);wrong[key]=value;view,_=c.us_benchmarks(day,lambda:now,lambda url:json.dumps(wrong).encode(),prior)
        assert view['status']=='SOURCE_ERROR' and not view['rows']
