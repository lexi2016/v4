"""Native fallback connects before the edge; only live quote RPCs use the slot."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pytest

from infrastructure.stage_quote_provider import NativeAOpeningSnapshotProvider, TdxOpeningQuoteProvider

EDGE=datetime(2026,10,28,9,25,tzinfo=ZoneInfo('Asia/Shanghai'))
DATE='20261028'
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


def sdk_row():
    return dict(code='600000',servertime='09:25:00',price=10,open=10,last_close=9,
        high=10,low=10,amount=100000,vol=100,bid1=10,ask1=10.01,bid_vol1=50,ask_vol1=40)


def fake_sdk(monkeypatch,clock,*,healthy=8,fail_quote=False,advance=None,quote_advance=None,host_count=12):
    import pytdx.config.hosts,pytdx.hq
    events=[]
    class Api:
        def __init__(self,**kwargs):self.index=None
        def connect(self,host,port,**kwargs):
            self.index=int(host.rsplit('-',1)[1])
            events.append(('connect',self.index,clock[0],kwargs['time_out']))
            if advance:advance()
            return self if self.index==healthy else False
        def disconnect(self):events.append(('disconnect',self.index))
        def get_security_quotes(self,symbols):
            events.append(('quotes',self.index,clock[0],symbols))
            if fail_quote:raise ConnectionError('quote transport failed')
            if quote_advance:quote_advance()
            return [sdk_row()]
    monkeypatch.setattr(pytdx.hq,'TdxHq_API',Api)
    monkeypatch.setattr(pytdx.config.hosts,'hq_hosts',[(f'host{i}',f'fixture-{i}',7709) for i in range(host_count)])
    return events


def test_primary_ready_still_prepares_fallback_without_a_quote_rpc():
    events=[]
    primary=SimpleNamespace(prepare=lambda:events.append('primary_prepare'))
    fallback=SimpleNamespace(prepare=lambda:events.append('fallback_prepare'))
    provider=NativeAOpeningSnapshotProvider(primary=primary,fallback=fallback,now=lambda:EDGE-timedelta(seconds=20))
    provider.prepare()
    assert events==['primary_prepare','fallback_prepare']


def test_dead_first_eight_are_cleaned_and_later_connection_is_reused_at_edge(monkeypatch):
    clock=[EDGE-timedelta(seconds=30)]
    events=fake_sdk(monkeypatch,clock)
    provider=TdxOpeningQuoteProvider(now=lambda:clock[0])
    provider.prepare()
    assert len([e for e in events if e[0]=='connect'])==9
    assert not any(e[0]=='quotes' for e in events)
    assert len([e for e in events if e[0]=='disconnect'])==8
    clock[0]=EDGE+timedelta(seconds=1)
    result=provider.snapshot(('A.600000',),trade_date=DATE,stage_id='STAGE_0925',cutoff_at=(EDGE+timedelta(seconds=5)).isoformat())
    assert result['rows'][0]['source_update_time']=='2026-10-28 09:25:00'
    assert len([e for e in events if e[0]=='connect'])==9
    assert [e[1] for e in events if e[0]=='quotes']==[8]
    provider.close();provider.close()
    assert len([e for e in events if e[0]=='disconnect' and e[1]==8])==1


@pytest.mark.parametrize('when',[EDGE-timedelta(microseconds=1),EDGE+timedelta(seconds=5,microseconds=1)])
def test_prepared_socket_does_not_allow_early_or_late_quote_rpc(monkeypatch,when):
    clock=[EDGE-timedelta(seconds=20)]
    events=fake_sdk(monkeypatch,clock,healthy=0)
    provider=TdxOpeningQuoteProvider(now=lambda:clock[0]);provider.prepare()
    clock[0]=when
    try:
        with pytest.raises(ValueError,match='window'):
            provider.snapshot(('A.600000',),trade_date=DATE,stage_id='STAGE_0925',cutoff_at=(EDGE+timedelta(seconds=5)).isoformat())
        assert not any(e[0]=='quotes' for e in events)
    finally:provider.close()
    assert events[-1]==('disconnect',0)


def test_preparation_stops_at_real_edge_and_disconnects_failed_hosts(monkeypatch):
    clock=[EDGE-timedelta(seconds=1)]
    def advance():clock[0]+=timedelta(seconds=.5)
    events=fake_sdk(monkeypatch,clock,healthy=10,advance=advance)
    provider=TdxOpeningQuoteProvider(now=lambda:clock[0])
    with pytest.raises(ConnectionError,match='TDX_NATIVE_PREPARE'):
        provider.prepare()
    assert len([e for e in events if e[0]=='connect'])==2
    assert len([e for e in events if e[0]=='disconnect'])==2
    assert not any(e[0]=='quotes' for e in events)
    provider.close()


def test_quote_failure_closes_prepared_connection_without_reconnecting(monkeypatch):
    clock=[EDGE-timedelta(seconds=20)]
    events=fake_sdk(monkeypatch,clock,healthy=0,fail_quote=True)
    provider=TdxOpeningQuoteProvider(now=lambda:clock[0]);provider.prepare()
    clock[0]=EDGE
    with pytest.raises(ConnectionError,match='quote transport failed'):
        provider.snapshot(('A.600000',),trade_date=DATE,stage_id='STAGE_0925',cutoff_at=(EDGE+timedelta(seconds=5)).isoformat())
    provider.close()
    assert len([e for e in events if e[0]=='connect'])==1
    assert len([e for e in events if e[0]=='disconnect'])==1


def test_future_primary_is_rejected_and_prewarmed_tdx_keeps_true_clock(monkeypatch):
    clock=[EDGE-timedelta(seconds=20)]
    events=fake_sdk(monkeypatch,clock,healthy=0)
    class Primary:
        def prepare(self):pass
        def close(self):pass
        def snapshot(self,*args,**kwargs):
            return dict(trade_date=DATE,stage_id='STAGE_0925',source='FUTU',
                capture_started_at=clock[0].isoformat(),captured_at=clock[0].isoformat(),
                rows=[dict(symbol='A.600000',last_price=10,source_update_time='2026-10-28 09:30:00')],**FLAGS)
    provider=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=TdxOpeningQuoteProvider(now=lambda:clock[0]),now=lambda:clock[0])
    provider.prepare()
    assert not any(e[0]=='quotes' for e in events)
    clock[0]=EDGE+timedelta(seconds=1)
    try:result=provider.snapshot(('A.600000',),trade_date=DATE)
    finally:provider.close()
    assert result['rejected_rows'] and len(result['rows'])==1
    assert result['rows'][0]['source_method']=='get_security_quotes'
    assert result['rows'][0]['source_update_time']=='2026-10-28 09:25:00'
    assert result['temporal_cutoff_safe'] is True
    assert events[-1]==('disconnect',0)


def test_monotonic_budget_bounds_prepare_with_a_stalled_wall_clock(monkeypatch):
    import time
    clock=[EDGE.replace(hour=8)]
    elapsed=[0.0]
    def advance():elapsed[0]+=1
    events=fake_sdk(monkeypatch,clock,healthy=100,advance=advance,host_count=80)
    monkeypatch.setattr(time,'monotonic',lambda:elapsed[0])
    provider=TdxOpeningQuoteProvider(now=lambda:clock[0])
    with pytest.raises(ConnectionError,match='TDX_NATIVE_PREPARE'):
        provider.prepare()
    assert len([e for e in events if e[0]=='connect'])==45
    assert len([e for e in events if e[0]=='disconnect'])==45
    assert not any(e[0]=='quotes' for e in events)


def test_failed_fallback_prepare_remains_visible_without_blocking_valid_primary():
    clock=[EDGE-timedelta(seconds=20)]
    class Fallback:
        def prepare(self):raise ConnectionError('all quote hosts unavailable')
        def snapshot(self,*args,**kwargs):pytest.fail('known preparation failure cannot retry')
        def close(self):pass
    class Primary:
        def prepare(self):pass
        def close(self):pass
        def snapshot(self,*args,**kwargs):
            return dict(trade_date=DATE,stage_id='STAGE_0925',source='FUTU',
                capture_started_at=clock[0].isoformat(),captured_at=clock[0].isoformat(),
                rows=[dict(symbol='A.600000',last_price=10,source_update_time='2026-10-28 09:25:00')],**FLAGS)
    provider=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=Fallback(),now=lambda:clock[0])
    provider.prepare();clock[0]=EDGE
    try:result=provider.snapshot(('A.600000',),trade_date=DATE)
    finally:provider.close()
    assert len(result['rows'])==1
    assert any('TDX_PREPARE:ConnectionError:all quote hosts unavailable' in e for e in result['errors'])


def test_tdx_return_after_cutoff_keeps_true_clock_and_cannot_be_published(monkeypatch):
    clock=[EDGE-timedelta(seconds=20)]
    def late_return():clock[0]=EDGE+timedelta(seconds=5,microseconds=1)
    events=fake_sdk(monkeypatch,clock,healthy=0,quote_advance=late_return)
    class Primary:
        def prepare(self):raise ConnectionError('primary unavailable')
        def close(self):pass
    provider=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=TdxOpeningQuoteProvider(now=lambda:clock[0]),now=lambda:clock[0])
    provider.prepare();clock[0]=EDGE
    try:result=provider.snapshot(('A.600000',),trade_date=DATE)
    finally:provider.close()
    assert result['rows']==[] and result['temporal_cutoff_safe'] is False
    assert result['raw_batches'][0]['rows'][0]['captured_at']==clock[0].isoformat()
    assert result['rejected_rows']
    assert events[-1]==('disconnect',0)
