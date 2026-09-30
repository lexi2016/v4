"""Synthetic market inputs; real public dispatcher, runner, selectors and stores.
No network, real authorization, live slot, or local Mac acceptance.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from ops import run_stage_center_nodes as nodes
from ops._run_stage_center_nodes_parts import node_entry as entry
from stage_center import runner as runtime
from stage_center.acquisition import SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.consumer import StageSelectionConsumer
from stage_center.contracts import SAFETY_FLAGS
from stage_center.raw_store import RAW_FIELDS, RawStore, publish_raw_artifact
from stage_center.selection import SelectionStore, select_a_0925_auction, select_hk_0925_second_filter

DATE='20260930'; STAGE='STAGE_0925'
NOW=datetime(2026,9,30,14,3,tzinfo=ZoneInfo('Asia/Shanghai'))

def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def sha(b): return hashlib.sha256(b).hexdigest()

def row(market, i=1):
    start,end=('09:20:00','09:25:00') if market=='A_SHARE' else ('09:15:00','09:20:00')
    return dict(batch_index=0,code=f'A.{600000+i:06}' if market=='A_SHARE' else f'HK.{i:05}',
        name='SYNTHETIC',update_time=f'2026-09-30 {end}',last_price=10.5,open_price=10.0,
        high_price=10.6,low_price=10.0,prev_close_price=10.0,turnover=30000000.0,
        volume=1000,bid_price=10.4,ask_price=10.5,bid_vol=100,ask_vol=100,
        window_start=f'2026-09-30 {start}',window_end=f'2026-09-30 {end}',bar_count=1,temporal_cutoff_safe=True,
        price=10.5,auction_score=75,rank=i,time=end,trade_date=DATE,
        source_mode='SYNTHETIC_NOT_REAL_MARKET')

def build(source,plan,raw,market):
    common=dict(source_status=source.status,requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,cannot_confirm=source.cannot_confirm,
        source_evidence=(*source.source_evidence,'selection_contract=V3_TOP10_RECOMMENDATION'))
    fn=select_a_0925_auction if market=='A_SHARE' else select_hk_0925_second_filter
    return fn(source.rows,plan.trade_date,raw['artifact_sha256'],**common)

def files(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

@pytest.fixture
def case(tmp_path,monkeypatch):
    cfg={k:str(tmp_path/k) for k in ('candidate_acquisition_root','raw_root','selection_root','receipt_root')}
    cfg.update(node_max_attempts=3,node_retry_backoff_seconds=0,safety=dict(SAFETY_FLAGS),
        a_0925_recovery_authorization={'review_status':'PENDING','fixture':'SYNTHETIC'},
        a_0925_recovery_authorization_sha256='f'*64)
    candidate=CandidateInput(Path(cfg['candidate_acquisition_root']),DATE,'current.json','d'*64,
        'SYNTHETIC',tuple(f'A.{600001+i:06}' for i in range(205)),'a'*64,'b'*64,'c'*64,'e'*64,())
    monkeypatch.setattr(runtime,'read_candidate_input',lambda *a,**kw:candidate)
    monkeypatch.setattr('stage_center.candidate_input.read_candidate_input',lambda *a,**kw:candidate)
    monkeypatch.setattr(runtime,'_stage_markets_for_date',lambda *a:('A_SHARE','HK_CONNECT'))
    monkeypatch.setattr(runtime,'_validate_exact_selection_inputs',lambda *a,**kw:('SYNTHETIC_EXACT_INPUT_BOUNDARY',))
    monkeypatch.setattr(nodes,'_calendar_gate',lambda *a,**kw:{'status':'ELIGIBLE'})
    monkeypatch.setattr(nodes,'_rearm_wall_now',lambda:NOW)
    collectors={};calls=[];builders={}
    for m in ('A_SHARE','HK_CONNECT'):
        def collect(plan,market,m=m):
            calls.append(m)
            return SourceResult('synthetic_'+m,'READY',tuple(row(m,i) for i in range(1,13)),
                requested_rows=12,source_evidence=('SYNTHETIC',))
        collectors[m]=collect
        builders[m]=lambda src,plan,raw,m=m:build(src,plan,raw,m)
    run=runtime.StageCenterRunner(runtime.RunnerConfig(**{k:Path(cfg[k]) for k in
        ('candidate_acquisition_root','raw_root','selection_root','receipt_root')},selection_builders=builders),
        collectors=collectors)
    path=run._receipt_path(DATE,STAGE);path.parent.mkdir(parents=True)
    decision=SimpleNamespace(trade_date=DATE,stage_id=STAGE,status='LATE_CATCHUP_REPLAY',
        scheduled_at=NOW.replace(hour=9,minute=25),reason='SYNTHETIC')
    run.due_decisions=lambda *a,**kw:(decision,)
    arows=tuple(row('A_SHARE',i) for i in range(1,13))
    raw=publish_raw_artifact(run.config.raw_root,trade_date=DATE,stage_id=STAGE,market='A_SHARE',
        source_id='synthetic_A',source_status='READY',rows=tuple({f:r[f] for f in RAW_FIELDS} for r in arows),
        source_evidence=('candidate_current_sha256='+'d'*64,),requested_rows=12,
        window='09:20:00-09:25:00',cutoff_at='09:25:05')
    a=build(SourceResult('synthetic_A','READY',arows,requested_rows=12,source_evidence=('candidate_current_sha256='+'d'*64,)),
        SimpleNamespace(trade_date=DATE),raw,'A_SHARE')
    SelectionStore(run.config.selection_root).publish(a,market='A_SHARE')
    old=dict(schema_version='stage_center.runner.receipt.v1',runner='stage_center',trade_date=DATE,
        stage_id=STAGE,node_id=STAGE,dispatch_mode='RECOVERY',status='PARTIAL_WITH_ROWS',
        node_outcome='SETTLED_PARTIAL',node_attempt_count=1,retry_exhausted=False,
        candidate_current_sha256='d'*64,candidate_run_id=candidate.run_id,
        source_evidence=['SYNTHETIC_ORIGINAL'],markets={'A_SHARE':a,'HK_CONNECT':dict(
            market='HK_CONNECT',status='CANNOT_CONFIRM',selection_status='CANNOT_CONFIRM',
            source_status='CANNOT_CONFIRM',selected_rows=0,write_performed=False,
            cannot_confirm=['HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE'])},**SAFETY_FLAGS)
    path.write_bytes(canonical(old))
    return SimpleNamespace(root=tmp_path,cfg=cfg,runner=run,path=path,old=old,candidate=candidate,
        calls=calls,builders=builders,collectors=collectors,marker=path.parent/entry._ISSUE11_MARKER)

def invoke(c,when=NOW):
    return nodes.run_nodes(c.cfg,trade_date=DATE,evaluated_at=when,explicit_node=STAGE,runner=c.runner)

def assert_a_preserved(c,before):
    actual=json.loads(c.path.read_bytes())
    assert actual['markets']['A_SHARE']==c.old['markets']['A_SHARE']
    assert all((c.root/p).read_bytes()==b for p,b in before.items()
        if '/A_SHARE_' in p)
    for filename in ('latest.json', 'selection_latest.json'):
        root = c.runner.config.raw_root if filename == 'latest.json' else c.runner.config.selection_root
        key = str((root/filename).relative_to(c.root))
        old_index = json.loads(before[key])
        new_index = json.loads((root/filename).read_bytes())
        slot = f'{DATE}/{STAGE}/A_SHARE'
        assert new_index['entries'][slot] == old_index['entries'][slot]
    assert SelectionStore(c.runner.config.selection_root).read_verified(DATE,STAGE,'A_SHARE')==c.old['markets']['A_SHARE']

@pytest.mark.parametrize('auth', [True,False])
def test_hk_public_retry_reaches_original_selector_and_consumer_without_a_work(case,monkeypatch,auth):
    if not auth:
        case.cfg.pop('a_0925_recovery_authorization');case.cfg.pop('a_0925_recovery_authorization_sha256')
    monkeypatch.setattr(entry,'_a_0925_repair_authority',lambda *a,**kw:pytest.fail('HK borrowed A authorization'))
    before=files(case.root);cfg=deepcopy(case.cfg)
    out=invoke(case)['nodes'][0]
    assert case.calls==['HK_CONNECT']
    assert out['node_attempt_count']==2
    assert_a_preserved(case,before)
    view=StageSelectionConsumer(case.runner.config.selection_root).get(DATE,STAGE)
    assert len(view['markets']['A_SHARE']['rows'])==len(view['markets']['HK_CONNECT']['rows'])==10
    assert set(RawStore(case.runner.config.raw_root).read_verified_bundle(DATE,STAGE)['receipt']['markets'])=={'A_SHARE','HK_CONNECT'}
    assert case.cfg==cfg and not case.marker.exists()
    invoke(case)
    assert case.calls==['HK_CONNECT']

@pytest.mark.parametrize('failure', ['collector','source_empty','builder','unexpected','publish','receipt','crash'])
def test_all_hk_failure_paths_preserve_a_and_debit_shared_attempt(case,monkeypatch,failure):
    before=files(case.root)
    if failure in ('collector','source_empty'):
        def collect(*args):
            case.calls.append('HK_CONNECT')
            if failure=='collector':raise RuntimeError('SYNTHETIC_COLLECTOR')
            return SourceResult('synthetic_HK','CANNOT_CONFIRM',cannot_confirm=('SYNTHETIC_EMPTY',),requested_rows=12)
        case.runner.collectors['HK_CONNECT']=collect
    else:
        original=case.builders['HK_CONNECT']
        def build_failure(src,plan,raw):
            if failure=='builder':raise ValueError('SYNTHETIC_BUILDER')
            if failure=='unexpected':raise RuntimeError('SYNTHETIC_UNEXPECTED')
            if failure=='crash':raise KeyboardInterrupt('SYNTHETIC_CRASH')
            return original(src,plan,raw)
        case.builders['HK_CONNECT']=build_failure
    if failure=='publish':
        original_publish=SelectionStore.publish
        def publish(self,env,*,market):
            if market=='HK_CONNECT':raise OSError('SYNTHETIC_DISK')
            return original_publish(self,env,market=market)
        monkeypatch.setattr(SelectionStore,'publish',publish)
    if failure=='receipt':
        original=runtime._atomic_json
        count=[0]
        def write(path,payload):
            count[0]+=1
            if count[0]>1:raise OSError('SYNTHETIC_RECEIPT_DISK')
            return original(path,payload)
        monkeypatch.setattr(runtime,'_atomic_json',write)
    try: invoke(case)
    except (KeyboardInterrupt,OSError): pass
    assert case.calls==['HK_CONNECT']
    assert_a_preserved(case,before)
    persisted=json.loads(case.path.read_bytes())
    assert persisted['node_attempt_count']==2
    assert not case.marker.exists()
    assert all(persisted[k] is False for k in SAFETY_FLAGS)

@pytest.mark.parametrize('unsafe', ['cap','expired','future','unsafe','marker','bad_count'])
def test_no_borrowing_or_reset_of_shared_budget(case,monkeypatch,unsafe):
    when=NOW
    if unsafe=='cap':case.old['node_attempt_count']=3
    elif unsafe=='bad_count':case.old['node_attempt_count']=True
    elif unsafe=='expired':monkeypatch.setattr(nodes,'_rearm_wall_now',lambda:NOW.replace(month=10,day=1))
    elif unsafe=='future':when=NOW.replace(hour=15)
    elif unsafe=='unsafe':case.cfg['safety']['orders_sent']=True
    elif unsafe=='marker':case.marker.write_bytes(canonical({'original_attempt_count':3,'additional_attempts':1}))
    case.path.write_bytes(canonical(case.old));before=files(case.root)
    invoke(case,when)
    assert case.calls==[]
    assert files(case.root)==before


def test_unexpected_hk_failure_remains_retryable_only_with_original_remaining_budget(case, monkeypatch):
    builds=[]
    def fail(*args):
        builds.append(1)
        raise RuntimeError('SYNTHETIC_TRANSIENT')
    case.builders['HK_CONNECT']=fail
    case.cfg['node_retry_backoff_seconds']=60
    invoke(case)
    reserved=files(case.root)
    assert invoke(case)['nodes'][0]['status']=='SKIPPED_RETRY_BACKOFF'
    assert files(case.root)==reserved
    later=NOW+timedelta(seconds=60)
    monkeypatch.setattr(nodes, '_rearm_wall_now', lambda:later)
    invoke(case,later)
    invoke(case,later)
    assert builds==[1,1]
    assert case.calls==['HK_CONNECT']  # Sealed raw is reused; no duplicate collection.
    assert json.loads(case.path.read_bytes())['node_attempt_count']==3
    assert not case.marker.exists()


@pytest.mark.parametrize('outcome', ['success','exception'])
def test_a_one_shot_uses_only_a_lane_and_preserves_hk(case, monkeypatch, tmp_path, outcome):
    from dataclasses import replace
    import base64
    case.runner.config=replace(case.runner.config, raw_root=tmp_path/'only_a_raw',
                               selection_root=tmp_path/'only_a_selection')
    case.cfg['raw_root']=str(case.runner.config.raw_root)
    case.cfg['selection_root']=str(case.runner.config.selection_root)
    hk_rows=tuple(row('HK_CONNECT',i) for i in range(1,13))
    raw=publish_raw_artifact(case.runner.config.raw_root,trade_date=DATE,stage_id=STAGE,market='HK_CONNECT',
        source_id='synthetic_HK',source_status='READY',rows=tuple({f:r[f] for f in RAW_FIELDS} for r in hk_rows),
        source_evidence=('candidate_current_sha256='+'d'*64,),requested_rows=12,
        window='09:15:00-09:20:00',cutoff_at='09:20:05')
    hk=build(SourceResult('synthetic_HK','READY',hk_rows,requested_rows=12),
        SimpleNamespace(trade_date=DATE),raw,'HK_CONNECT')
    SelectionStore(case.runner.config.selection_root).publish(hk,market='HK_CONNECT')
    old=dict(schema_version='stage_center.runner.receipt.v1',trade_date=DATE,stage_id=STAGE,
        status='CANNOT_CONFIRM',node_attempt_count=3,retry_exhausted=True,
        error="TypeError: can't compare offset-naive and offset-aware datetimes",
        markets={'A_SHARE':{'selected_rows':0},'HK_CONNECT':hk},**SAFETY_FLAGS)
    saved=canonical(old)+b'\n';case.path.write_bytes(saved)
    attempts={}
    for num in range(1,4):
        for event in ('START','RETURN'):
            rel=f'attempt_evidence/SYNTHETIC-{num}/{event}.json'
            p=case.path.parent/rel;p.parent.mkdir(parents=True,exist_ok=True)
            data=canonical(dict(trade_date=DATE,stage_id=STAGE,attempt_number=num,event=event,detail={}))
            p.write_bytes(data);attempts[rel]=sha(data)
    expected={'stage_center._live_collectors_parts.a_auction':'1'*64,
              'infrastructure.tdx_minute_replay_provider':'2'*64}
    monkeypatch.setattr(entry,'_ISSUE11_RECEIPT_SHA',sha(saved))
    monkeypatch.setattr(entry,'_ISSUE11_CANDIDATE_SHA',case.candidate.artifact_sha256)
    monkeypatch.setattr(entry,'_ISSUE11_CODES_SHA',sha(canonical(list(case.candidate.codes))))
    monkeypatch.setattr(entry,'_issue11_loaded_repair_identity',lambda:expected)
    auth=dict(schema_version='stage_center.a_auction_recovery_authorization.v1',issue=11,
        trade_date=DATE,stage_id=STAGE,market='A_SHARE',mode='RECOVERY',additional_attempts=1,
        approval_id='SYNTHETIC-NOT-A-LIVE-GRANT',writer_id='synthetic-w',reviewer_id='synthetic-r',
        review_status='APPROVED',original_receipt_sha256=sha(saved),
        candidate_artifact_sha256=case.candidate.artifact_sha256,codes_sha256=entry._ISSUE11_CODES_SHA,
        candidate_count=205,fixed_modules=expected,original_attempts=attempts,**SAFETY_FLAGS)
    case.cfg['a_0925_recovery_authorization']=auth
    case.cfg['a_0925_recovery_authorization_sha256']=sha(canonical(auth))
    def collect(plan,market):
        assert len(plan.codes_for('A_SHARE'))==205 and plan.markets==('A_SHARE',)
        case.calls.append(market)
        return SourceResult('SYNTHETIC_A','READY',tuple(row('A_SHARE',i) for i in range(1,206)),
                            requested_rows=205,source_evidence=('SYNTHETIC',))
    case.runner.collectors['A_SHARE']=collect
    if outcome=='exception':
        def failure(*args): raise RuntimeError('SYNTHETIC_A_BUILDER')
        case.builders['A_SHARE']=failure
    before=files(case.root)
    out=invoke(case)['nodes'][0]
    assert out['node_attempt_count']==4 and case.calls==['A_SHARE']
    assert json.loads(case.path.read_bytes())['markets']['HK_CONNECT']==hk
    assert SelectionStore(case.runner.config.selection_root).read_verified(DATE,STAGE,'HK_CONNECT')==hk
    assert all((case.root/p).read_bytes()==b for p,b in before.items() if '/HK_CONNECT_' in p
               or 'attempt_evidence/SYNTHETIC-' in p)
    audit=json.loads(case.marker.read_bytes())
    assert base64.b64decode(audit['original_receipt_base64'])==saved
    assert audit['candidate_count']==205
    assert invoke(case)['nodes'][0]['status']=='SKIPPED_REPAIR_RECOVERY_CONSUMED'
    assert case.calls==['A_SHARE']
    if outcome=='success':
        assert len(StageSelectionConsumer(case.runner.config.selection_root).get(DATE,STAGE)
                   ['markets']['A_SHARE']['rows'])==10
