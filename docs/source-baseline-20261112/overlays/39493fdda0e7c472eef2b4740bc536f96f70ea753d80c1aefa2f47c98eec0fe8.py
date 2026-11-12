from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from infrastructure.futu_quote_provider import FutuQuoteProvider
from infrastructure.stage_quote_provider import (
    NativeAOpeningSnapshotProvider, read_native_a_opening_snapshot,
    write_native_a_opening_snapshot, precapture_native_a_opening,
)
from stage_center.candidate_input import CandidateInput
from stage_center.acquisition import build_plan
from stage_center.live_collectors import collect_a_share_auction, production_selection_builders
from stage_center.raw_store import RAW_FIELDS, validate_rows

TZ=ZoneInfo('Asia/Shanghai')
DATE='20261027'
EDGE=datetime(2026,10,27,9,25,tzinfo=TZ)
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


def candidate(root,codes=('A.000001',)):
    return CandidateInput(root=root,trade_date=DATE,current_relative='current.json',current_sha256='c'*64,
        run_id='candidate-fixture',codes=codes,artifact_sha256='a'*64,manifest_sha256='b'*64,
        receipt_sha256='d'*64,source_projection_sha256='e'*64,source_evidence=())


def row(code='A.000001'):
    return dict(symbol=code,name='fixture',last_price=11,open_price=11,prev_close_price=10,
        high_price=11,low_price=11,turnover=100000000,volume=100000,
        bid_price1=11,ask_price1=11.01,bid_vol1=600,ask_vol1=400,
        source_update_time=EDGE.strftime('%Y-%m-%d %H:%M:%S'))


class Primary:
    def __init__(self, rows=None, *, at=EDGE+timedelta(seconds=1)):
        self.rows=rows if rows is not None else [row()]
        self.at=at;self.calls=[];self.prepared=False;self.closed=False
    def prepare(self):self.prepared=True
    def close(self):self.closed=True
    def snapshot(self,symbols,**kwargs):
        self.calls.append(tuple(symbols))
        return dict(trade_date=DATE,stage_id='STAGE_0925',rows=self.rows,
            raw_rows=self.rows,source='FUTU_OPEND_READ_ONLY_SNAPSHOT',capture_started_at=self.at.isoformat(),
            captured_at=self.at.isoformat(),**FLAGS)


class NoFallback:
    def snapshot(self,*args,**kwargs):raise AssertionError('fallback must not run')


def payload(rows=None,at=EDGE+timedelta(seconds=1)):
    return NativeAOpeningSnapshotProvider(primary=Primary(rows,at=at),fallback=NoFallback(),now=lambda:at).snapshot(
        ('A.000001',),trade_date=DATE)


def test_futu_true_clock_handles_real_aware_cutoff_and_preserves_source_clock():
    class Frame:
        def to_dict(self,**kwargs):return [dict(code='SZ.000001',update_time='2026-10-27 09:25:00',last_price=11)]
    class Context:
        def get_market_snapshot(self,codes):return 0,Frame()
        def close(self):pass
    result=FutuQuoteProvider(context_factory=Context,now=lambda:EDGE.replace(tzinfo=None)).snapshot(
        ('A.000001',),trade_date=DATE,stage_id='STAGE_0925',cutoff_at=(EDGE+timedelta(seconds=5)).isoformat())
    assert result['temporal_cutoff_safe'] is True
    assert result['capture_started_at'].endswith('+08:00')
    assert result['rows'][0]['source_update_time']=='2026-10-27 09:25:00'


def test_primary_first_no_transaction_or_minute_rpc_and_bad_rows_isolated():
    primary=Primary([row(),{**row('A.000002'),'last_price':-1}])
    p=NativeAOpeningSnapshotProvider(primary=primary,fallback=NoFallback(),now=lambda:EDGE+timedelta(seconds=1))
    result=p.snapshot(('A.000001','A.000002'),trade_date=DATE)
    assert primary.calls==[('A.000001','A.000002')]
    assert [r['symbol'] for r in result['rows']]==['A.000001']
    assert result['missing_symbols']==['A.000002'] and result['rejected_rows']
    assert result['data_level'].endswith('NOT_L2_NOT_TRANSACTION')


def test_late_true_capture_cannot_be_replaced_by_old_source_timestamp(tmp_path):
    late=EDGE+timedelta(seconds=5,microseconds=1)
    times=iter([EDGE,EDGE,late])
    result=NativeAOpeningSnapshotProvider(primary=Primary(at=late),fallback=NoFallback(),now=lambda:next(times)).snapshot(
        ('A.000001',),trade_date=DATE)
    assert not result['temporal_cutoff_safe'] and result['rows']==[]
    with pytest.raises(ValueError,match='real timely capture'):
        write_native_a_opening_snapshot(tmp_path,result,candidate(tmp_path))


def test_immutable_commit_bound_to_exact_candidate_and_raw_sha(tmp_path):
    c=candidate(tmp_path);p=payload()
    write_native_a_opening_snapshot(tmp_path,p,c)
    assert read_native_a_opening_snapshot(tmp_path,c)[0]==p
    with pytest.raises(FileExistsError):write_native_a_opening_snapshot(tmp_path,p,c)
    with pytest.raises(ValueError):read_native_a_opening_snapshot(tmp_path,SimpleNamespace(**{**c.__dict__,'current_sha256':'f'*64}))
    path=tmp_path/'native_opening'/DATE/'STAGE_0925'/'snapshot.json'
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):read_native_a_opening_snapshot(tmp_path,c)


def test_consumer_missing_cache_never_calls_late_network_or_transaction(monkeypatch,tmp_path):
    import infrastructure.tdx_minute_replay_provider as replay
    monkeypatch.setattr(replay,'TdxMinuteReplayProvider',lambda:pytest.fail('transaction RPC forbidden'))
    c=candidate(tmp_path);plan=build_plan(tmp_path,DATE,'STAGE_0925',candidate=c)
    result=collect_a_share_auction(plan,codes=c.codes,python_path='/unused',shared_root=tmp_path,auction_root=tmp_path)
    assert result.status=='CANNOT_CONFIRM' and not result.rows
    assert any('late_snapshot_query_forbidden=true'==e for e in result.source_evidence)


def test_native_cache_to_original_builder_keeps_real_score_inputs_and_truthful_type(monkeypatch,tmp_path):
    import stage_center.selection as selection
    original_score=selection.live_stage_quality_score
    score_inputs=[]
    def score(qmt,*args):
        score_inputs.append(qmt)
        return original_score(qmt,*args)
    monkeypatch.setattr(selection,'live_stage_quality_score',score)
    c=candidate(tmp_path);p=payload();write_native_a_opening_snapshot(tmp_path,p,c)
    plan=build_plan(tmp_path,DATE,'STAGE_0925',candidate=c)
    source=collect_a_share_auction(plan,codes=c.codes,python_path='/unused',shared_root=tmp_path,auction_root=tmp_path)
    assert source.status=='READY' and source.rows[0]['is_open_call_auction_match'] is False
    projection=[{key:r.get(key,'') for key in RAW_FIELDS} for r in source.rows]
    checked,issues=validate_rows(projection,trade_date=DATE,stage_id='STAGE_0925',market='A_SHARE')
    assert len(checked)==1 and not issues
    raw=dict(artifact_sha256='a'*64,status=source.status,requested_rows=1,missing_symbols=(),
        cannot_confirm=source.cannot_confirm,source_evidence=source.source_evidence,cutoff_at='09:25:05')
    result=production_selection_builders('STAGE_0925')['A_SHARE'](source,plan,raw)
    selected=result['rows'][0]
    assert selected['prev_close_price']==10 and selected['qmt_gap_pct']==10
    from stage_center.selection import live_stage_quality_score
    expected=live_stage_quality_score(dict(open=11,lastPrice=11,lastClose=10,high=11,low=11,
        amount=100000000,bidVol=600,askVol=400),{'score':None},'STAGE_0925')
    assert selected['score']==round(max(0,min(100,expected)),6)
    assert score_inputs[0]['lastClose']==10 and score_inputs[0]['bidVol']==600 and score_inputs[0]['askVol']==400
    assert selected['source_mode']=='A_SHARE_NATIVE_QUOTE_SNAPSHOT_STAGE_0925'
    assert 'A_SHARE_EXACT_DATE_AUCTION_TRANSACTION' not in selected['lane_evidence']
    assert selected['formal_eligible'] is False and selected['trade_status']=='WATCH_ONLY'


def test_native_builder_only_extra_fields_do_not_change_old_projection(monkeypatch,tmp_path):
    import stage_center.selection as selection
    from stage_center.acquisition import SourceResult
    captured=[]
    monkeypatch.setattr(selection,'select_a_0925_auction',lambda rows,*a,**k:captured.extend(rows) or {})
    source=SourceResult('a_share_auction','READY',rows=({'code':'A.000001','update_time':'2026-10-27 09:25:00',
        'last_price':11,'prev_close_price':10,'bid_vol':600},),requested_rows=1)
    plan=build_plan(tmp_path,DATE,'STAGE_0925',candidate=candidate(tmp_path))
    production_selection_builders('STAGE_0925')['A_SHARE'](source,plan,dict(artifact_sha256='a'*64,status='READY',
        requested_rows=1,missing_symbols=(),cannot_confirm=(),source_evidence=(),cutoff_at='09:25:05'))
    assert 'native_quote_snapshot' not in captured[0] and 'prev_close_price' not in captured[0]


def test_new_native_node_is_explicit_only_and_never_due_late(tmp_path):
    import ops.run_stage_center_nodes as nodes
    at=EDGE-timedelta(seconds=30)
    explicit=nodes._node_candidates(DATE,at,explicit_node='PRECAPTURE_A_0925',config={})
    assert len(explicit)==1
    normal=nodes._node_candidates(DATE,at,explicit_node=None,config={'receipt_root':str(tmp_path)})
    assert all(n.node_id!='PRECAPTURE_A_0925' for n in normal)
    assert nodes._node_candidates(DATE,EDGE+timedelta(seconds=6),explicit_node='PRECAPTURE_A_0925',config={})==()


def test_precapture_uses_owner_lock_waits_real_boundary_and_saves_only_native(monkeypatch,tmp_path):
    import stage_center.candidate_input as inputs
    c=candidate(tmp_path);monkeypatch.setattr(inputs,'read_candidate_input',lambda *a,**k:c)
    clock=[EDGE-timedelta(seconds=.25)]
    def sleep(seconds):clock[0]+=timedelta(seconds=seconds)
    primary=Primary(at=EDGE)
    p=NativeAOpeningSnapshotProvider(primary=primary,fallback=NoFallback(),now=lambda:clock[0])
    result=precapture_native_a_opening(dict(a_auction_root=str(tmp_path),candidate_acquisition_root=str(tmp_path),safety=FLAGS),
        DATE,sleep=sleep,now=lambda:clock[0],provider=p)
    assert result['status']=='READY' and primary.prepared and primary.closed
    assert clock[0]>=EDGE and len(primary.calls)==1
    assert read_native_a_opening_snapshot(tmp_path,c)[1]['candidate_run_id']==c.run_id
    assert not (tmp_path/'selection_latest.json').exists()


def test_precapture_late_payload_retains_partial_evidence_without_commit(monkeypatch,tmp_path):
    import stage_center.candidate_input as inputs
    c=candidate(tmp_path);monkeypatch.setattr(inputs,'read_candidate_input',lambda *a,**k:c)
    class Late:
        def prepare(self):pass
        def close(self):pass
        def snapshot(self,*a,**k):return dict(temporal_cutoff_safe=False,raw_batches=[{'partial':'preserved'}])
    result=precapture_native_a_opening(dict(a_auction_root=str(tmp_path),candidate_acquisition_root=str(tmp_path),safety=FLAGS),
        DATE,sleep=lambda _:None,now=lambda:EDGE,provider=Late())
    assert result['status']=='CANNOT_CONFIRM'
    evidence=json.loads(Path(result['attempt_evidence']).read_text())
    assert evidence['payload']['raw_batches']==[{'partial':'preserved'}]
    assert not (tmp_path/'native_opening'/DATE/'STAGE_0925'/'manifest.json').exists()


def test_all_missing_quotes_fail_closed_and_bad_previous_close_is_not_invented(tmp_path):
    c=candidate(tmp_path)
    p=payload([{**row(),'prev_close_price':None}])
    write_native_a_opening_snapshot(tmp_path,p,c)
    plan=build_plan(tmp_path,DATE,'STAGE_0925',candidate=c)
    source=collect_a_share_auction(plan,codes=c.codes,python_path='/unused',shared_root=tmp_path,auction_root=tmp_path)
    assert source.status=='CANNOT_CONFIRM' and not source.rows


def test_native_owner_lock_rejects_second_caller_before_quote(monkeypatch,tmp_path):
    import stage_center.candidate_input as inputs
    from stage_center.runner import SlotLock
    monkeypatch.setattr(inputs,'read_candidate_input',lambda *a,**k:candidate(tmp_path))
    lock=SlotLock(tmp_path/'native_opening'/DATE/'STAGE_0925'/'capture.lock')
    assert lock.acquire()
    try:
        result=precapture_native_a_opening(dict(a_auction_root=str(tmp_path),candidate_acquisition_root=str(tmp_path),safety=FLAGS),
            DATE,sleep=lambda _:pytest.fail('second caller cannot wait'),now=lambda:EDGE,
            provider=SimpleNamespace(prepare=lambda:pytest.fail('second caller cannot quote')))
        assert result['status']=='SKIPPED_SLOT_LOCKED'
    finally:lock.release()


def test_reader_rejects_late_row_even_with_recomputed_file_hash(tmp_path):
    c=candidate(tmp_path);p=payload();write_native_a_opening_snapshot(tmp_path,p,c)
    root=tmp_path/'native_opening'/DATE/'STAGE_0925'
    p['rows'][0]['captured_at']=(EDGE+timedelta(seconds=6)).isoformat()
    raw=json.dumps(p,sort_keys=True,separators=(',',':')).encode()
    (root/'snapshot.json').write_bytes(raw)
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['artifact_sha256']=hashlib.sha256(raw).hexdigest()
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='clock rejected'):read_native_a_opening_snapshot(tmp_path,c)


def test_precapture_futu_prepare_failure_reaches_quote_fallback_with_evidence(monkeypatch,tmp_path):
    import stage_center.candidate_input as inputs
    c=candidate(tmp_path);monkeypatch.setattr(inputs,'read_candidate_input',lambda *a,**k:c)
    clock=[EDGE-timedelta(seconds=.25)]
    events=[]
    def sleep(seconds):clock[0]+=timedelta(seconds=seconds)
    class BrokenPrimary:
        def prepare(self):
            events.append('futu_prepare')
            raise ConnectionError('fixture OpenD context unavailable')
        def snapshot(self,*a,**k):pytest.fail('known preparation failure must not be retried')
        def close(self):events.append('futu_close')
    class Fallback:
        def prepare(self):events.append('tdx_prepare')
        def snapshot(self,*a,**k):
            events.append('get_security_quotes')
            assert EDGE<=clock[0]<=EDGE+timedelta(seconds=5)
            stamp=clock[0].isoformat()
            return dict(source='PYTDX_HQ_READ_ONLY_QUOTES',rows=[{**row(),
                'capture_started_at':stamp,'query_started_at':stamp,'returned_at':stamp,'captured_at':stamp}],
                raw_rows=[{'fixture':'native quote response'}],**FLAGS)
        def close(self):events.append('tdx_close')
    provider=NativeAOpeningSnapshotProvider(primary=BrokenPrimary(),fallback=Fallback(),now=lambda:clock[0])
    result=precapture_native_a_opening(dict(a_auction_root=str(tmp_path),candidate_acquisition_root=str(tmp_path),safety=FLAGS),
        DATE,sleep=sleep,now=lambda:clock[0],provider=provider)
    assert result['status']=='READY' and events==['futu_prepare','tdx_prepare','get_security_quotes','futu_close','tdx_close']
    captured,_=read_native_a_opening_snapshot(tmp_path,c)
    assert captured['rows'][0]['source_method']=='get_security_quotes'
    assert any(e.startswith('FUTU_PREPARE:ConnectionError:fixture') for e in captured['errors'])
    evidence=json.loads(next((tmp_path/'native_opening'/DATE/'STAGE_0925'/'attempts').glob('*.json')).read_text())
    assert evidence['payload']['errors']==captured['errors']


def test_real_raw_roundtrip_rehydrates_exact_native_score_and_fails_closed_on_drift(tmp_path):
    from dataclasses import replace
    import stage_center.runner as runner
    from stage_center.raw_store import publish_raw_artifact,RawStore
    from stage_center._runner_parts.slot_execution import _rehydrate_native_a_0925_raw_source
    auction=tmp_path/'auction';raw_root=tmp_path/'raw';c=candidate(tmp_path)
    original_row={**row(),'last_price':10.1,'open_price':10.1,'high_price':10.1,'low_price':10.1,'turnover':1_000_000}
    write_native_a_opening_snapshot(auction,payload([original_row]),c)
    plan=build_plan(tmp_path,DATE,'STAGE_0925',candidate=c)
    fresh=collect_a_share_auction(plan,codes=c.codes,python_path='/unused',shared_root=tmp_path,auction_root=auction)
    published=publish_raw_artifact(raw_root,trade_date=DATE,stage_id='STAGE_0925',market='A_SHARE',
        source_id=fresh.source_id,source_status=fresh.status,
        rows=runner._project_raw_rows(fresh.rows,trade_date=DATE,stage_id='STAGE_0925',market='A_SHARE'),
        source_evidence=fresh.source_evidence,cannot_confirm=fresh.cannot_confirm,requested_rows=1,
        window='09:20-09:30',cutoff_at='09:25:05')
    verified=RawStore(raw_root).verify_run(DATE,'STAGE_0925','A_SHARE',published['run_id'])
    restored19=runner._read_verified_raw_source(raw_root,verified)
    assert len(restored19.rows)==1 and 'native_quote_snapshot' not in restored19.rows[0]
    builder=production_selection_builders('STAGE_0925')['A_SHARE']
    with pytest.raises(ValueError,match='verified native rehydration'):
        builder(restored19,plan,verified)
    config=SimpleNamespace(a_auction_root=auction,python_path='/unused',shared_data_root=tmp_path)
    restored=_rehydrate_native_a_0925_raw_source(vars(runner),restored19,plan,config)
    assert restored.rows[0]['native_quote_snapshot'] is True
    before=builder(fresh,plan,verified)['rows'][0]
    after=builder(restored,plan,verified)['rows'][0]
    assert after==before
    assert after['prev_close_price']==10 and after['qmt_gap_pct']==1 and after['score']==61.225
    assert after['source_mode']=='A_SHARE_NATIVE_QUOTE_SNAPSHOT_STAGE_0925'
    legacy=replace(restored19,source_evidence=tuple(e for e in restored19.source_evidence if not e.startswith('native_snapshot_contract=')))
    assert _rehydrate_native_a_0925_raw_source(vars(runner),legacy,plan,config) is legacy
    changed=replace(restored19,rows=({**restored19.rows[0],'prev_close_price':11},))
    rejected=_rehydrate_native_a_0925_raw_source(vars(runner),changed,plan,config)
    assert rejected.status=='CANNOT_CONFIRM' and not rejected.rows
    snapshot=auction/'native_opening'/DATE/'STAGE_0925'/'snapshot.json'
    snapshot.write_bytes(snapshot.read_bytes()+b' ')
    rejected=_rehydrate_native_a_0925_raw_source(vars(runner),restored19,plan,config)
    assert rejected.status=='CANNOT_CONFIRM' and not rejected.rows
    assert any(e.startswith('NATIVE_RAW_REHYDRATION_ERROR:') for e in rejected.cannot_confirm)
