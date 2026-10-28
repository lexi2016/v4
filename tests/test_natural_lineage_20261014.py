"""Clock resolution and receipt lineage, without retroactive natural attestation."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import pytest
from stage_center.scheduler import evaluate_due

@pytest.mark.parametrize("clock,expected", [
    ("10:29:59.999999", "NOT_DUE"), ("10:30:00", "DUE"),
    ("10:30:02.499705", "DUE"), ("10:30:59.999999", "DUE"),
    ("10:31:00", "LATE_CATCHUP_REPLAY")])
def test_launchd_minute_resolution(clock, expected):
    at = datetime.fromisoformat("2026-10-14T" + clock).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    assert evaluate_due("STAGE_0945_1030", "20261014", at).status == expected

def test_cutoff_and_backfill_not_relaxed():
    at = datetime(2026,10,14,9,35,4,tzinfo=ZoneInfo("Asia/Shanghai"))
    assert evaluate_due("STAGE_0930_0935", "20261014", at).status == "NOT_DUE"
    assert evaluate_due("STAGE_0930_0935", "20261014", at, historical_backfill=True).status == "HISTORICAL_BACKFILL"


def _published(tmp_path):
    from stage_center.selection import SelectionStore, select_hk_four_lane
    store = SelectionStore(tmp_path / 'selection')
    result = select_hk_four_lane([dict(code='HK.00001', last_price=11, prev_close_price=10,
        turnover=1000000, volume_ratio=1.5)], '20261014', 'STAGE_0945_1030', 'b'*64)
    store.publish(result, market='HK_CONNECT')
    lane = store.read_verified('20261014', 'STAGE_0945_1030', 'HK_CONNECT')
    lane["status"] = lane["selection_status"]
    return store, lane


def _receipt(lane):
    return dict(schema_version='stage_center.runner.receipt.v1', runner='stage_center',
                trade_date='20261014', stage_id='STAGE_0945_1030', dispatch_mode='NATURAL',
                due_status='DUE', production_allowed=False, buy_gate_updated=False, orders_sent=False,
                markets={'HK_CONNECT': lane})


def test_actual_owner_writer_binds_large_receipt_and_selection(tmp_path):
    from types import SimpleNamespace
    from stage_center.runner import StageCenterRunner
    from stage_center.execution_evidence import read_stage_execution
    store, lane = _published(tmp_path)
    root = tmp_path / 'receipts'
    runner = object.__new__(StageCenterRunner)
    runner.config = SimpleNamespace(receipt_root=root, selection_root=store.root, backfill_run_id=None)
    payload = _receipt(lane)
    payload['large_source_evidence'] = 'x' * 1_280_000
    first = runner._write_receipt(payload, '20261014', 'STAGE_0945_1030')
    assert first['RESEARCH_ONLY'] is True
    assert first['production_allowed'] is False
    assert first['buy_gate_updated'] is False
    assert first['orders_sent'] is False
    out = read_stage_execution(root, '20261014', 'STAGE_0945_1030', {'HK_CONNECT':lane}, selection_store=store)
    assert out['receipt_history_binding'] == 'OWNER_HISTORY_SHA_BOUND'
    assert out['selection_artifact_bindings']['HK_CONNECT']['status'] == 'BOUND_TO_VERIFIED_SELECTION_TRIO'
    assert out['status'] == 'OWNER_RECEIPT_SELECTION_TRIOS_BOUND_EXECUTION_UNVERIFIED'
    assert out['natural_verified'] is False and out['execution_verified'] is False
    first_raw = (root / first['receipt_history']['relative_path']).read_bytes()
    assert json.loads(first_raw)['RESEARCH_ONLY'] is True
    second = runner._write_receipt(first, '20261014', 'STAGE_0945_1030')
    assert second['recorded_at'] != first['recorded_at']
    assert (root / first['receipt_history']['relative_path']).read_bytes() == first_raw
    assert second['receipt_history'] != first['receipt_history']
    # A changed immutable owner copy must fail closed.
    (root / second['receipt_history']['relative_path']).write_bytes(b'{}')
    out = read_stage_execution(root, '20261014', 'STAGE_0945_1030', {'HK_CONNECT':lane}, selection_store=store)
    assert out['receipt_history_binding'] == 'OWNER_HISTORY_CONFLICT'
    assert out['natural_verified'] is False


def test_owner_writer_rejects_explicit_research_only_false_before_binding(tmp_path):
    from types import SimpleNamespace
    from stage_center.runner import RunnerError, StageCenterRunner
    store, lane = _published(tmp_path)
    root = tmp_path / 'receipts'
    runner = object.__new__(StageCenterRunner)
    runner.config = SimpleNamespace(receipt_root=root, selection_root=store.root, backfill_run_id=None)
    payload = _receipt(lane)
    payload['RESEARCH_ONLY'] = False

    with pytest.raises(RunnerError, match='RESEARCH_ONLY'):
        runner._write_receipt(payload, '20261014', 'STAGE_0945_1030')

    assert not root.exists()


def test_mismatched_selection_is_not_bound(tmp_path):
    from stage_center.receipt_lineage import bind_owner_receipt
    store, lane = _published(tmp_path)
    lane['raw_artifact_sha256'] = 'a'*64
    out = bind_owner_receipt(_receipt(lane), receipt_root=tmp_path/'receipts', selection_root=store.root,
                             trade_date='20261014', stage_id='STAGE_0945_1030')
    assert out['selection_artifacts']['HK_CONNECT']['status'] == 'SELECTION_TRIO_NOT_BOUND_AT_OWNER_WRITE'


def test_legacy_clock_explained_without_rewriting_or_promoting_receipt(tmp_path):
    from stage_center.execution_evidence import read_stage_execution
    slot = tmp_path/'20261014/STAGE_0945_1030'; slot.mkdir(parents=True)
    aid = 'a'*32
    relative = f'attempt_evidence/{aid}/001_START.json'
    path = slot/relative; path.parent.mkdir(parents=True)
    start = dict(schema='stage.attempt_diagnostic.v1',event='START',attempt_id=aid,
                 trade_date='20261014',stage_id='STAGE_0945_1030',attempt_number=1,
                 evaluated_at='2026-10-14T10:30:02.499705+08:00', observed_at='2026-10-14T10:30:05.313517+08:00')
    path.write_text(json.dumps(start))
    receipt = _receipt({});receipt['markets']={}
    receipt.update(due_status='LATE_CATCHUP_REPLAY',node_attempt_count=1,
                   attempt_diagnostic=dict(attempt_id=aid, relative_paths=[relative]))
    raw=json.dumps(receipt).encode(); (slot/'receipt.json').write_bytes(raw)
    out=read_stage_execution(tmp_path,'20261014','STAGE_0945_1030',{})
    assert out['schedule_observation']['legacy_exact_second_misclassification'] is True
    assert out['schedule_observation']['delay_seconds'] == 2.499705
    assert out['due_status']=='LATE_CATCHUP_REPLAY' and out['natural_verified'] is False
    assert out['receipt_history_binding']=='OWNER_HISTORY_NOT_RECORDED'
    assert (slot/'receipt.json').read_bytes()==raw
    start['stage_id']='STAGE_0930_0935';path.write_text(json.dumps(start))
    assert read_stage_execution(tmp_path,'20261014','STAGE_0945_1030',{})['schedule_observation']['status']=='ATTEMPT_CLOCK_CONFLICT'
