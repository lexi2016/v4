from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from infrastructure.stage_quote_provider import NativeAOpeningSnapshotProvider
from infrastructure.futu_quote_provider import FutuQuoteProvider, to_futu_symbol
from infrastructure.tdx_minute_replay_provider import _market_and_code

EDGE = datetime(2026, 10, 27, 9, 25, tzinfo=ZoneInfo('Asia/Shanghai'))
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def row(code, *, future=False, price=13):
    # Original df0a4f0e…: representative000995/600048 carried09:30
    # while actually captured09:25:00.x. Never rewrite the provider timestamp.
    return dict(symbol=code, last_price=price, source_update_time='2026-10-27 09:30:00' if future else '2026-10-27 09:25:00')


def primary(rows, *, after=None):
    def snapshot(codes, **kwargs):
        if after:after()
        return dict(rows=rows, raw_rows=rows, trade_date='20261027', stage_id='STAGE_0925',
                    source='FUTU_OPEND_READ_ONLY_SNAPSHOT', capture_started_at=(EDGE+timedelta(seconds=1)).isoformat(),
                    captured_at=(EDGE+timedelta(seconds=1)).isoformat(), **FLAGS)
    return SimpleNamespace(snapshot=snapshot)


def fallback(calls, *, at=1):
    def snapshot(codes, **kwargs):
        calls.append(tuple(codes))
        return dict(rows=[dict(row(c),capture_started_at=(EDGE+timedelta(seconds=at)).isoformat(),
                             captured_at=(EDGE+timedelta(seconds=at)).isoformat()) for c in codes],
                    source='PYTDX_HQ_READ_ONLY_QUOTES', **FLAGS)
    return SimpleNamespace(snapshot=snapshot)


def test_invalid_primary_reaches_original_fallback_without_overwriting_valid_primary():
    raw=[row('A.000995',future=True),row('A.600048',future=True),row('A.920575',price=0),row('A.000001')]
    calls=[];provider=NativeAOpeningSnapshotProvider(primary=primary(raw),fallback=fallback(calls),now=lambda:EDGE+timedelta(seconds=1))
    result=provider.snapshot(tuple(r['symbol'] for r in raw),trade_date='20261027')
    assert calls==[('A.000995','A.600048')]
    assert {r['symbol'] for r in result['rows']}=={'A.000995','A.600048','A.000001'}
    assert next(r for r in result['rows'] if r['symbol']=='A.000001')['source_method']=='get_market_snapshot'
    assert result['missing_symbols']==['A.920575']
    assert raw[0]['source_update_time']=='2026-10-27 09:30:00'
    assert any(r['symbol']=='A.000995' for r in result['rejected_rows'])


def test_no_fallback_request_after_actual_cutoff():
    clock=[EDGE+timedelta(seconds=1)];calls=[]
    provider=NativeAOpeningSnapshotProvider(primary=primary([row('A.000995',future=True)],after=lambda:clock.__setitem__(0,EDGE+timedelta(seconds=6))),
        fallback=fallback(calls),now=lambda:clock[0])
    result=provider.snapshot(('A.000995',),trade_date='20261027')
    assert not calls and not result['rows'] and result['temporal_cutoff_safe'] is False


def test_fallback_capture_and_source_clocks_stay_strict():
    calls=[];provider=NativeAOpeningSnapshotProvider(primary=primary([row('A.000995',future=True)]),
        fallback=fallback(calls,at=6),now=lambda:EDGE+timedelta(seconds=1))
    result=provider.snapshot(('A.000995',),trade_date='20261027')
    assert calls and not result['rows'] and result['missing_symbols']==['A.000995']


@pytest.mark.parametrize('code',['A.920575','A.920627','A.920779','A.833575','A.430001'])
def test_unproven_bj_quote_market_never_maps_to_sh_or_sz(code):
    with pytest.raises(ValueError,match='BJ_QUOTE_MARKET_UNSUPPORTED'):to_futu_symbol(code)
    with pytest.raises(ValueError,match='BJ_QUOTE_MARKET_UNSUPPORTED'):_market_and_code(code)


def test_futu_mixed_batch_isolates_bj_and_wrong_exchange_without_losing_success():
    calls=[]
    raw=[dict(code='SZ.000995',last_price=13,update_time='2026-10-27 09:25:00'),
         dict(code='SH.000995',last_price=13),dict(code='SH.920575',last_price=0)]
    class Frame:
        def to_dict(self,**kwargs):return raw
    class Context:
        def get_market_snapshot(self,codes):calls.append(codes);return 0,Frame()
        def close(self):pass
    p=FutuQuoteProvider(context_factory=Context,now=lambda:EDGE)
    result=p.snapshot(('A.000995','A.920575'),trade_date='20261027',stage_id='STAGE_0925',cutoff_at=(EDGE+timedelta(seconds=5)).isoformat())
    assert calls==[['SZ.000995']]
    assert [r['symbol'] for r in result['rows']]==['A.000995']
    assert result['raw_rows']==raw and len(result['rejected_rows'])==3
