from datetime import datetime
from zoneinfo import ZoneInfo
import copy
import json

import pytest
from domains.preselection_materializer import build_expected_missing_pool
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops import run_v35_macos_scheduler as scheduler
from ops.materialize_scheduled_preselection import publish_scheduled_artifacts

DATE = '20261014'

def pool(pool_id, role, paths):
    return dict(schema_version='v3_5.preselection_pool.v1', trade_date=DATE,
        pool_id=pool_id, display_name=pool_id, market='A', status='READY',
        producer_id='v3_5_hourly_research_window_v1', source_role=role,
        source_path=paths, source_sha256='a'*64,
        rows=[dict(symbol='A.000001',market='A',pool_id=pool_id,pool_rank=1,
            trade_date=DATE,target_date=DATE,recommendation_status='WATCH_ONLY',
            production_allowed=False,buy_gate_updated=False,orders_sent=False)],
        cannot_confirm=[],production_allowed=False,buy_gate_updated=False,orders_sent=False)

@pytest.mark.parametrize('alive', [True, False])
def test_interrupted_panel_claim_does_not_block_existing_reclaim(tmp_path, monkeypatch, alive):
    monkeypatch.setattr('infrastructure.scheduling.execution_ledger._pid_is_alive', lambda pid: alive)
    p=tmp_path/'claims/live/20261013/1700/dispatch.claim.json'
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(dict(schema_version='v3_5.dispatch_claim.v1',business_date='20261013',
        scheduled_date='20261013',target_date='20261013',slot='1700',mode='LIVE',pid=123,run_id='dead')))
    assert scheduler._slot_blocks_retry(tmp_path,'20261013','1700',
        moment=datetime(2026,10,13,19,0,tzinfo=ZoneInfo('Asia/Shanghai'))) is alive
    assert p.exists()  # due selection never mutates the claim


def test_invalid_claim_stays_blocked(tmp_path):
    p=tmp_path/'claims/live/20261013/1700/dispatch.claim.json';p.parent.mkdir(parents=True)
    p.write_text('{"pid":0}')
    assert ExecutionLedger(tmp_path).dispatch_claim_blocks_retry('20261013','1700')


def test_research_refresh_adds_hours_preserves_revision_and_rejects_shrink(tmp_path):
    s=PreselectionPoolStore(tmp_path)
    a=pool('a_share_research_recommendation_pool','VERIFIED_HOURLY_RESEARCH','research/hourly/live/20261013/1500.json')
    old=s.materialize(a)
    b=copy.deepcopy(a);b['source_path']+='|research/hourly/live/20261013/1800.json';b['source_sha256']='b'*64
    result=s.materialize(b)
    assert result['previous_sha256']==old['sha256']
    assert s.read_pool(DATE,a['pool_id'])==b
    assert (tmp_path/f"preselection_revisions/{DATE}/{a['pool_id']}/{old['sha256']}.json").exists()
    assert s.materialize(b)['sha256']==result['sha256']
    with pytest.raises(ValueError,match='conflicting'):
        s.materialize(a)
    with pytest.raises(ValueError,match='conflicting'):
        s.materialize({**b,'source_sha256':'c'*64})


def test_main_pool_recovers_only_placeholder_and_stays_immutable(tmp_path):
    s=PreselectionPoolStore(tmp_path);pid='a_d1_premarket_pool'
    missing=build_expected_missing_pool(DATE,pool_id=pid,display_name=pid,market='A',reason='A_V192_EXACT_INPUT_MISSING')
    s.materialize(missing)
    a=pool(pid,'SHARED_VERIFIED_V192','runs/exact/pool.csv')
    result=publish_scheduled_artifacts(s,[a])
    assert result[0]['recovery'] is True
    assert s.read_pool(DATE,pid)['rows']
    with pytest.raises(ValueError,match='conflicting'):
        publish_scheduled_artifacts(s,[{**a,'source_sha256':'b'*64}])
