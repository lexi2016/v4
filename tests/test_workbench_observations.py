"""Stored observation time/calendar/commit checks; no real market/network calls."""
from datetime import datetime,timedelta
import json
from pathlib import Path
import subprocess

import pytest
from ops.collect_workbench_observations import SH,korea,collect,publish,put
from ops.run_workbench_observation_slot import due,run

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
IDENTITY=dict(source_date='2026-10-29',generation='a'*64,input_sha256='b'*64)


def test_late_korea_response_uses_received_time_not_request_start_or_range_previous_close():
    seoul=__import__('zoneinfo').ZoneInfo('Asia/Seoul')
    started=datetime(2026,10,30,8,0,tzinfo=SH);completed=started+timedelta(minutes=2)
    source=started+timedelta(minutes=1)
    def read(url):
        symbol='^KS11' if 'KS11' in url else '^KQ11'
        result=dict(meta=dict(regularMarketTime=int(source.timestamp()),symbol=symbol,instrumentType='INDEX',exchangeTimezoneName='Asia/Seoul',regularMarketPrice=110,chartPreviousClose=50),timestamp=[int((source-timedelta(days=1)).timestamp()),int(source.timestamp())],indicators={'quote':[{'close':[100,110]}]})
        return json.dumps({'chart':{'result':[result]}}).encode()
    answer=korea('2026-10-30',started,read,clock=lambda:completed)
    assert all(r['change_pct']==10 for r in answer['indices'])
    assert answer['recorded_at']==completed.isoformat() and answer['request_started_at']==started.isoformat()


def test_lunch_exact_slots_weekend_and_calendar_year_fail_closed(tmp_path):
    assert due(datetime(2026,10,30,11,30,tzinfo=SH))=='1130'
    assert due(datetime(2026,10,30,12,0,tzinfo=SH)) is None
    assert due(datetime(2026,10,30,13,0,tzinfo=SH))=='1300'
    assert due(datetime(2026,10,30,9,33,tzinfo=SH)) is None
    config=dict(state_root=str(tmp_path),**FLAGS)
    assert run(config,now=datetime(2026,10,31,10,0,tzinfo=SH))['status']=='SKIP_NON_TRADING_DAY'
    assert run(config,now=datetime(2027,1,4,10,0,tzinfo=SH))['status']=='CANNOT_CONFIRM'


def test_publish_rejects_older_completion_without_replacing_current_pointer(tmp_path):
    def snapshot(stamp):return dict(observation_date='2026-10-30',slot='1500',recorded_at=stamp,rows=[],**FLAGS)
    kr=dict(indices=[],**FLAGS)
    publish(tmp_path,snapshot('2026-10-30T15:05:00+08:00'),kr,{})
    old=(tmp_path/'2026-10-30/latest.json').read_bytes()
    with pytest.raises(ValueError,match='OUT_OF_ORDER'):publish(tmp_path,snapshot('2026-10-30T15:04:00+08:00'),kr,{})
    assert (tmp_path/'2026-10-30/latest.json').read_bytes()==old


def test_date_only_official_archive_sorts_and_shows_values_without_inventing_clock(tmp_path):
    # Exercise the actual local JS adapter against its unchanged fixed module.
    import os,shutil
    dot=Path(os.environ['DOT_FRAMEWORK_SOURCE_ROOT']);root=Path(__file__).resolve().parents[1]
    shutil.copy(root/'research/stock_panel_collab_20261030/mac-host/observation-local.mjs',tmp_path)
    (tmp_path/'dot/src').mkdir(parents=True)
    shutil.copy(dot/'src/observation-view.mjs',tmp_path/'dot/src')
    node='/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    script="""import assert from 'node:assert/strict';import {rowValidity,sortStocks} from './observation-local.mjs';const row={symbol:'a',capture_kind:'OFFICIAL_DAILY_ARCHIVE',status:'DATED_DAILY_ARCHIVE',source_date:'2026-10-30',source_asof:null,source_asof_precision:'DATE_ONLY',currency:'CNY',price:12.5,amount_source:0,change_percent_source:0,percent_change_rank_eligible:true,observed_at_upper_bound:'2026-10-30T17:00:00+08:00'},snapshot={capture_kind:'OFFICIAL_DAILY_ARCHIVE',daily_contract_sha256:'a'.repeat(64),observation_date:'2026-10-30',rows:[row]};assert(rowValidity(row,snapshot,'price','2026-10-30T17:01:00+08:00').valid);assert(rowValidity(row,snapshot,'amount','2026-10-30T17:01:00+08:00').valid);assert.equal(row.source_asof,null);assert.equal(rowValidity({...row,source_date:'2026-10-29'},snapshot,'price').valid,false);assert.equal(rowValidity(row,snapshot,'price','2026-10-30T16:00:00+08:00').valid,false);assert.deepEqual(sortStocks([{symbol:'missing'},{symbol:'a'}],{snapshot,mode:'price_asc',now:'2026-10-30T17:01:00+08:00'}).map(x=>x.symbol),['a','missing']);"""
    subprocess.run([node,'--input-type=module','-e',script],cwd=tmp_path,check=True,capture_output=True)


def test_timer_retains_known_intraday_source_block_without_network_or_host_rescan():
    now=datetime(2026,10,30,10,0,tzinfo=SH)
    def no_source(url):raise AssertionError('only KR would call this; patched below')
    from unittest.mock import patch
    with patch('ops.collect_workbench_observations.korea',return_value=dict(indices=[dict(symbol='^KS11',value=1),dict(symbol='^KQ11',value=1)],status='DATED_INDEX_OBSERVATION',**FLAGS)):
        value,_,_=collect('2026-10-30','1000',IDENTITY,['601088.SH','920262.BJ'],now=now,clock=lambda:now)
    assert all(r['error'].startswith('CANNOT_CONFIRM_INTRADAY_SOURCE') for r in value['rows'])
    assert all(r['price'] is None for r in value['rows'])


def slot_fixture(tmp_path):
    root=tmp_path/'products';root.mkdir();state=tmp_path/'state'
    artifact=put(root/'product.json',dict(source_generation=IDENTITY['generation'],source_identity={'input_sha256':IDENTITY['input_sha256']},rows=[{'symbol':'601088.SH'}],**FLAGS))
    manifest=put(root/'manifest.json',dict(artifact=artifact,**FLAGS));put(root/'index.json',dict(dates={'20261029':manifest},latest_date='20261029'))
    authority=put(root/'authority.json',dict(source_date='2026-10-29',observation_date='2026-10-30'))
    binding=put(root/'binding.json',dict(observation_dates={'2026-10-29':dict(date='2026-10-30',authority=authority)},**FLAGS))
    return dict(state_root=str(state),product_root=str(root),host_binding=binding,**FLAGS)


def test_one_slot_success_is_idempotent_and_partial_failure_stops_after_two(tmp_path):
    now=datetime(2026,10,30,10,0,tzinfo=SH);config=slot_fixture(tmp_path);calls=[]
    def collector(day,slot,identity,symbols,**kwargs):
        calls.append(symbols)
        return (dict(observation_date=day,slot=slot,recorded_at=now.isoformat(),source_generation=identity['generation'],input_sha256=identity['input_sha256'],rows=[dict(symbol=s,error=None) for s in symbols],**FLAGS),dict(indices=[dict(symbol='^KS11',value=1)],**FLAGS),{})
    assert run(config,now=now,collector=collector)['status']=='COMMITTED'
    assert run(config,now=now,collector=collector)['status']=='ALREADY_COMMITTED' and len(calls)==1
    failed=tmp_path/'failed';failed.mkdir();config=slot_fixture(failed);calls.clear()
    def failure(*args,**kwargs):
        snapshot,kr,raw=collector(*args,**kwargs);snapshot['rows'][0]['error']='source failure';return snapshot,kr,raw
    assert run(config,now=now,collector=failure)['status']=='PARTIAL_STORED_INTRADAY_SOURCE_BLOCKED'
    assert run(config,now=now,collector=failure)['status']=='PARTIAL_STORED_INTRADAY_SOURCE_BLOCKED'
    assert run(config,now=now,collector=failure)['status']=='DIAGNOSIS_REQUIRED' and len(calls)==2


def test_actual_accepted_calendar_without_next_session_import_and_boundaries(tmp_path,monkeypatch):
    import copy,dataclasses,hashlib,importlib.util,sys
    from infrastructure.research_workbench_host import ResearchWorkbenchHost,next_workbench_session
    legacy=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-name-zoom-20261030-r1-main/app/contracts/trading_calendar.py')
    assert hashlib.sha256(legacy.read_bytes()).hexdigest()=='cfac1a96f92519fec24203cfbb9ade1f6d5ee378b7cb88ddfeca5a9000b77eb8'
    spec=importlib.util.spec_from_file_location('accepted_calendar_without_next',legacy)
    calendar_module=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,calendar_module);spec.loader.exec_module(calendar_module)
    assert not hasattr(calendar_module,'next_session')
    monkeypatch.setitem(sys.modules,'contracts.trading_calendar',calendar_module)
    slot_path=Path(__file__).resolve().parents[1]/'ops/run_workbench_observation_slot.py'
    spec=importlib.util.spec_from_file_location('workbench_slot_accepted_calendar',slot_path);slot=importlib.util.module_from_spec(spec);spec.loader.exec_module(slot)
    calendar=calendar_module.load_market_calendar()
    assert next_workbench_session(calendar,'20261030')=='20261102'
    markets=copy.deepcopy(calendar.markets);markets['a_share']['holiday_periods'].append(dict(name='fixture official holiday',start='20261102',end='20261102'))
    holiday_calendar=dataclasses.replace(calendar,markets=markets)
    assert next_workbench_session(holiday_calendar,'20261030')=='20261103'
    with pytest.raises(ValueError,match='NEXT_CALENDAR_YEAR_UNBOUND'):next_workbench_session(calendar,'20261231')
    with pytest.raises(ValueError,match='YEAR_UNBOUND'):next_workbench_session(calendar,'20270104')
    now=datetime(2026,10,30,19,0,tzinfo=SH);config=slot_fixture(tmp_path)
    def collector(day,at,identity,symbols,**kwargs):
        return (dict(observation_date=day,slot=at,recorded_at=now.isoformat(),source_generation=identity['generation'],input_sha256=identity['input_sha256'],rows=[dict(symbol=s,error=None) for s in symbols],**FLAGS),dict(indices=[dict(symbol='^KS11',value=1)],**FLAGS),{})
    assert slot.run(config,now=now,collector=collector)['next_slot']=='2026-11-02T08:00:00+08:00'
    # Exercise the host fallback too, without a manually pinned observation day.
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    calendar_path=legacy.with_name('market_calendar_2026.json')
    host.binding=dict(calendar=dict(path=str(calendar_path),sha256=hashlib.sha256(calendar_path.read_bytes()).hexdigest()))
    assert host._observation_date('2026-10-30')=='2026-11-02'
    monkeypatch.setattr(calendar_module,'resolve_market_states',lambda *args:{'a_share':calendar_module.TradingDayState.UNKNOWN})
    with pytest.raises(ValueError,match='STATE_UNKNOWN'):next_workbench_session(calendar,'20261030')
