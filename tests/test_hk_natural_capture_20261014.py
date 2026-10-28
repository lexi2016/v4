"""Natural six-stage capture: existing clock route, original bars and book evidence."""
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(os.environ.get('V4_TEST_STAGE_APP_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'upstreams/v3_shared_data'))
from scripts.live_acquisition import futu_bridge
from shared_data.hk_auction_0920 import fetch_futu_snapshot
from ops.run_stage_center_nodes import NODE_BY_ID, _node_due
from stage_center.contracts import HK_SNAPSHOT_SCHEDULE
from stage_center.hk_stage8 import snapshot
import stage_center.live_collectors as live


def test_live_precapture_precedes_old_retries(monkeypatch):
    import ops.run_stage_center_nodes as nodes
    monkeypatch.setattr(nodes, '_read_receipt', lambda *a: None)
    due = nodes._node_candidates('20261014', datetime.fromisoformat('2026-10-14T14:59:00+08:00'),
                                explicit_node=None, config={})
    assert due[0].node_id == 'PRECAPTURE_STAGE_1445_1500'


@pytest.mark.parametrize('stage,clock', [
    ('STAGE_0930_0935','09:34:00'), ('STAGE_0935_0940','09:39:00'),
    ('STAGE_0940_0945','09:44:00'), ('STAGE_0945_1030','10:29:00'),
    ('STAGE_1300_1315','13:14:00'), ('STAGE_1445_1500','14:59:00'),
])
def test_six_precapture_nodes_have_real_pre_cutoff_windows(stage, clock):
    node = NODE_BY_ID['PRECAPTURE_' + stage]
    now = datetime.fromisoformat('2026-10-14T'+clock).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    assert HK_SNAPSHOT_SCHEDULE[stage][0] == clock
    assert _node_due(node, '20261014', now)
    assert not _node_due(node, '20261014', now.replace(hour=16))


def test_minute_provider_response_is_durable_and_sha_bound(tmp_path):
    bars = [dict(code='HK.00700',time_key=f'2026-10-14 09:{minute}:00',
                 open=10,high=12,low=9,close=11,volume=10,turnover=100,last_close=9)
            for minute in range(31,36)]
    payload = dict(rows=bars,errors=[],no_data_codes=[],captured_at='2026-10-14T09:35:06+08:00')
    def process(*args, **kwargs):
        return SimpleNamespace(returncode=0,stderr='',stdout=futu_bridge.MARKER+json.dumps(payload))
    result = futu_bridge.collect_futu_minute(sys.executable,'20261014','STAGE_0930_0935',
        ['HK.00700'],market='HK_CONNECT',process_runner=process,capture_root=tmp_path)
    row = result.rows[0]
    path = Path(row['futu_capture_path'])
    stored = json.loads(path.read_bytes())
    assert stored['rows'] == bars
    assert stored['captured_at'] == row['futu_captured_at'] == payload['captured_at']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['futu_capture_sha256']
    assert row['bar_count'] == 5


def test_book_option_is_opt_in_without_changing_auction_default():
    options=[]
    def process(*args, **kwargs):
        options.append(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0,stderr='',stdout='__FUTU_HK_AUCTION_JSON__'+json.dumps({'rows':[],'errors':[]}))
    fetch_futu_snapshot(sys.executable,['HK.00700'],process_runner=process)
    fetch_futu_snapshot(sys.executable,['HK.00700'],process_runner=process,include_order_book=True)
    assert [item['include_order_book'] for item in options] == [False,True]


@pytest.mark.parametrize('book_state', ['complete','missing','late'])
def test_persisted_book_and_provider_time_reach_stage_without_new_fetch(monkeypatch, tmp_path, book_state):
    from stage_center.acquisition import SourceResult
    import stage_center.hk_stage8 as api
    row = dict(code='HK.00700',prev_close_price=10,last_price=11,turnover=30_000_000,volume_ratio=2,
               order_book={'Bid':[[10.9,200]],'Ask':[[11.1,300]]},
               order_book_requested_at='2026-10-14T09:34:10+08:00',order_book_received_at='2026-10-14T09:34:11+08:00')
    if book_state == 'missing': row.pop('order_book')
    if book_state == 'late': row['order_book_received_at']='2026-10-14T09:36:00+08:00'
    monkeypatch.setattr(api,'load_hk_active_snapshot',lambda *a,**kw:dict(status='READY',rows=[row],source_evidence=[]))
    source=SourceResult('futu','READY',rows=({'code':'HK.00700'},),requested_rows=1)
    result=live.refresh_hk_active_lanes(source,codes=['HK.00700'],python_path=sys.executable,
        shared_root=ROOT/'upstreams/v3_shared_data',snapshot_root=tmp_path,
        process_runner=lambda *a,**kw:pytest.fail('must use persisted pre-capture'),
        trade_date='20261014',stage_id='STAGE_0930_0935',cutoff_at='09:35:05',pool_artifact_sha256='a'*64)
    if book_state == 'complete':
        assert not result.cannot_confirm
        assert result.rows[0]['bid_price'] == 10.9
        assert result.rows[0]['ask_vol'] == 300
        assert 'futu_order_book_rows=1' in result.source_evidence
    else:
        assert 'HK_STAGE_ORDERBOOK_INCOMPLETE' in result.cannot_confirm


def test_pre_capture_preserves_full_book_and_real_times(monkeypatch, tmp_path):
    now=datetime.fromisoformat('2026-10-14T09:34:10+08:00')
    row=dict(code='HK.00700',prev_close_price=10,last_price=11,turnover=30_000_000,
             volume_ratio=2,update_time='2026-10-14 09:34:09',
             order_book={'code':'HK.00700','Bid':[[10.9,200]],'Ask':[[11.1,300]]},
             order_book_requested_at=now.isoformat(),order_book_received_at=now.isoformat())
    def fetch(python_path,codes,*,process_runner,include_order_book=False):
        assert include_order_book
        process_runner(['fake'])
        return [row],[]
    monkeypatch.setattr(snapshot,'_load_shared_module',lambda *a:SimpleNamespace(fetch_futu_snapshot=fetch))
    result=snapshot.prepare_hk_active_snapshot(tmp_path,trade_date='20261014',stage_id='STAGE_0930_0935',
        codes=['HK.00700'],python_path=sys.executable,shared_root=ROOT/'upstreams/v3_shared_data',
        evaluated_at=now.isoformat(),cutoff_at='09:35:05',pool_artifact_sha256='a'*64,
        process_runner=lambda *a,**kw:None,clock=lambda:now)
    assert result['status']=='READY'
    saved=json.loads(Path(result['snapshot_path']).read_bytes())
    assert saved['rows'][0]['order_book']==row['order_book']
    assert saved['provider_started_at']==saved['provider_finished_at']==now.isoformat()
