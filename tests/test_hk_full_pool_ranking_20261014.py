"""Full fixed-D1 membership is scored; strong conditions remain truthful labels."""
import sys
from types import SimpleNamespace
import pytest
from stage_center.acquisition import SourceResult
import stage_center.live_collectors as live
import stage_center.selection as selection

@pytest.mark.parametrize('active_count', [0, 4, 100])
def test_all_100_score_with_real_ratios_tags_and_top10(monkeypatch, tmp_path, active_count):
    import stage_center.hk_stage8 as api
    codes = [f'HK.{i:05d}' for i in range(1,101)]
    quotes = [dict(code=c,prev_close_price=10,last_price=11,turnover=30_000_000 if i<active_count else 1_000_000,
        volume_ratio=2+i/100,order_book={'Bid':[[10.9,200]],'Ask':[[11.1,300]]},
        order_book_requested_at='2026-10-14T09:34:10+08:00',order_book_received_at='2026-10-14T09:34:11+08:00') for i,c in enumerate(codes)]
    monkeypatch.setattr(api,'load_hk_active_snapshot',lambda *a,**kw:dict(status='READY',rows=quotes,source_evidence=[]))
    source=SourceResult('futu','READY',rows=tuple(dict(code=c,last_price=11,prev_close_price=10,open_price=10.5,high_price=11,low_price=10,turnover=1_000_000) for c in codes),requested_rows=100)
    enriched=live.refresh_hk_active_lanes(source,codes=codes,python_path=sys.executable,shared_root=tmp_path,snapshot_root=tmp_path,
        process_runner=lambda *a,**kw:pytest.fail('persisted only'),trade_date='20261014',stage_id='STAGE_0930_0935',cutoff_at='09:35:05',pool_artifact_sha256='a'*64)
    assert not enriched.cannot_confirm
    assert len(enriched.rows)==100
    assert sum(bool(r['candidate_lanes']) for r in enriched.rows)==active_count
    assert [r['volume_ratio'] for r in enriched.rows]==[r['volume_ratio'] for r in quotes]
    scored=[]
    original=selection.hk_four_lane_score
    def tracked(row,*args,**kwargs):
        scored.append(row['code']); return original(row,*args,**kwargs)
    monkeypatch.setattr(selection,'hk_four_lane_score',tracked)
    raw=dict(status='READY',artifact_sha256='b'*64,requested_rows=100,missing_symbols=[],cannot_confirm=[],source_evidence=[],cutoff_at='09:35:05')
    out=live.production_selection_builders('STAGE_0930_0935')['HK_CONNECT'](enriched,SimpleNamespace(trade_date='20261014',stage_id='STAGE_0930_0935'),raw)
    assert scored==codes
    assert len(out['rows'])==10
    assert not out['missing_symbols']
    assert out['selection_status']=='READY'
    assert out['algorithm_sha256']==selection.HK_FULL_POOL_ALGORITHM_SHA256
    assert all(r['action_level']=='NO_BUY' and not r['formal_eligible'] for r in out['rows'])
    if active_count==0: assert all(not r['candidate_lanes'] for r in out['rows'])
    store=selection.SelectionStore(tmp_path/'selection'); store.publish(out,market='HK_CONNECT')
    assert store.read_verified('20261014','STAGE_0930_0935','HK_CONNECT')['rows']==out['rows']


def test_source_gaps_are_preserved_in_full_pool_mode():
    source=SourceResult('futu','PARTIAL_WITH_ROWS',rows=({'code':'HK.00001','last_price':11,'prev_close_price':10},),requested_rows=100,missing_symbols=('HK.00002',),cannot_confirm=('REAL_SOURCE_GAP',))
    raw=dict(status='PARTIAL_WITH_ROWS',artifact_sha256='b'*64,requested_rows=100,missing_symbols=['HK.00002'],cannot_confirm=['REAL_SOURCE_GAP'],source_evidence=[])
    out=live.production_selection_builders('STAGE_0930_0935')['HK_CONNECT'](source,SimpleNamespace(trade_date='20261014',stage_id='STAGE_0930_0935'),raw)
    assert out['selection_status']=='PARTIAL_WITH_ROWS'
    assert out['missing_symbols']==['HK.00002']
    assert 'REAL_SOURCE_GAP' in out['cannot_confirm']


def test_stage8_zero_strong_still_requests_full_100(monkeypatch, tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import stage_center.hk_stage8.rtdata as rt
    codes=tuple(f'HK.{i:05d}' for i in range(1,101))
    quotes=[dict(code=c,prev_close_price=10,last_price=9,turnover=1_000_000,volume_ratio=0.5) for c in codes]
    monkeypatch.setattr(rt,'load_hk_active_snapshot',lambda *a,**kw:dict(status='READY',rows=quotes,source_evidence=[]))
    import json
    path=rt._snapshot_path(tmp_path,'20261014','STAGE_1545_1555')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'source_role':'FUTU_HKCONNECT_FULL_SCAN'}))
    calls=[]
    def provider(requested,**kwargs):
        calls.append(tuple(requested))
        return dict(rows=[dict(code=c,time='2026-10-14 15:50:00',cur_price=9,last_close=10,turnover=1_000_000,volume=100,high=9,low=9) for c in requested],errors=(),cleanup_warnings=())
    plan=SimpleNamespace(trade_date='20261014',stage_id='STAGE_1545_1555',universe_bindings={'HK_CONNECT':SimpleNamespace(sha256='a'*64)})
    result=rt._collect_hk_stage8_natural(plan,codes=codes,snapshot_root=tmp_path,rtdata_provider=provider,natural_now=datetime(2026,10,14,15,56,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert calls==[codes]
    assert result.status=='READY' and result.requested_rows==len(result.rows)==100
    assert all(not r['candidate_lanes'] for r in result.rows)
