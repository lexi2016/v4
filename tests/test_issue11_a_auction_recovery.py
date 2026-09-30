"""Synthetic authorization/receipt fixtures. No market replay or Mac acceptance."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from ops import run_stage_center_nodes as nodes
from ops._run_stage_center_nodes_parts import node_entry as entry
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import SAFETY_FLAGS

DATE = '20260930'
STAGE = 'STAGE_0925'
NOW = datetime(2026, 9, 30, 14, 3, tzinfo=ZoneInfo('Asia/Shanghai'))

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

@pytest.fixture
def case(tmp_path, monkeypatch):
    cfg = {k: str(tmp_path / k) for k in ('receipt_root', 'candidate_acquisition_root', 'selection_root')}
    cfg.update(node_max_attempts=3, safety=dict(SAFETY_FLAGS))
    path = Path(cfg['receipt_root']) / DATE / STAGE / 'receipt.json'
    path.parent.mkdir(parents=True)
    old = dict(schema_version='stage_center.runner.receipt.v1', trade_date=DATE,
        stage_id=STAGE, status='CANNOT_CONFIRM', node_attempt_count=3, retry_exhausted=True,
        error="TypeError: can't compare offset-naive and offset-aware datetimes",
        markets={'A_SHARE': {'selected_rows': 0}}, **SAFETY_FLAGS)
    raw = canonical(old) + b'\n'
    path.write_bytes(raw)
    codes = tuple(f'A.{600000+i:06}' for i in range(205))
    candidate = CandidateInput(Path(cfg['candidate_acquisition_root']), DATE,
        'current.json', 'd'*64, 'synthetic-candidate', codes, 'a'*64, 'b'*64, 'c'*64, 'e'*64, ())
    # Only synthetic fixtures replace these production pins; product constants
    # themselves are separately tested against the immutable issue identifiers.
    monkeypatch.setattr(entry, '_ISSUE11_RECEIPT_SHA', digest(raw), raising=False)
    monkeypatch.setattr(entry, '_ISSUE11_CANDIDATE_SHA', candidate.artifact_sha256, raising=False)
    monkeypatch.setattr(entry, '_ISSUE11_CODES_SHA', digest(canonical(list(codes))), raising=False)
    monkeypatch.setattr(nodes, '_rearm_wall_now', lambda: NOW)
    monkeypatch.setattr('stage_center.candidate_input.read_candidate_input', lambda *a, **kw: candidate)
    pins = {'stage_center._live_collectors_parts.a_auction': '1'*64,
            'infrastructure.tdx_minute_replay_provider': '2'*64}
    # The already-fixed deployed collector/provider are absent from GitHub.
    # Model their approved loaded identities, never claim to execute that fix.
    monkeypatch.setattr(entry, '_issue11_loaded_repair_identity', lambda: pins, raising=False)
    attempts = {}
    for number in range(1, 4):
        for event in ('START', 'RETURN'):
            rel = f'attempt_evidence/synthetic-{number}/{event}.json'
            p = path.parent / rel; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(canonical(dict(trade_date=DATE, stage_id=STAGE,
                attempt_number=number, event=event, detail={})))
            attempts[rel] = digest(p.read_bytes())
    auth = dict(schema_version='stage_center.a_auction_recovery_authorization.v1', issue=11,
        trade_date=DATE, stage_id=STAGE, market='A_SHARE', mode='RECOVERY', additional_attempts=1,
        approval_id='SYNTHETIC-NOT-AN-ACTUAL-AUTHORIZATION', writer_id='writer', reviewer_id='reviewer',
        review_status='APPROVED', original_receipt_sha256=digest(raw),
        candidate_artifact_sha256=candidate.artifact_sha256, codes_sha256=digest(canonical(list(codes))),
        candidate_count=205, fixed_modules=pins, original_attempts=attempts, **SAFETY_FLAGS)
    cfg['a_0925_recovery_authorization'] = auth
    cfg['a_0925_recovery_authorization_sha256'] = digest(canonical(auth))
    # Internal explicit-request capability normally created only by run_nodes.
    cfg['_issue11_explicit_request'] = getattr(entry, '_ISSUE11_EXPLICIT', None)
    calls = []
    def write(value, date, stage):
        value = {**value, 'trade_date': date, 'stage_id': stage, **SAFETY_FLAGS}
        path.write_bytes(canonical(value)); return value
    def run(decision):
        marker = path.parent / 'a_0925_issue11_recovery.json'
        assert marker.is_file(), 'reservation must precede the only runner invocation'
        calls.append(decision)
        return {**old, 'write_performed': False}
    runner = SimpleNamespace(config=SimpleNamespace(receipt_root=Path(cfg['receipt_root'])),
        due_decisions=lambda *a, **kw: [SimpleNamespace(stage_id=STAGE, status='LATE_CATCHUP_REPLAY',
            scheduled_at=NOW.replace(hour=9,minute=25))],
        _run_one=run, _write_receipt=write, _receipt_path=lambda *a: path)
    monkeypatch.setattr(nodes, '_calendar_gate', lambda *a, **kw: {'status': 'ELIGIBLE'})
    return SimpleNamespace(cfg=cfg,path=path,old=old,raw=raw,auth=auth,candidate=candidate,
                           runner=runner,calls=calls)

def dispatch(c, **kwargs):
    return nodes._dispatch_stage(c.cfg, DATE, STAGE, NOW, mode=kwargs.pop('mode', 'RECOVERY'),
                                runner=c.runner, **kwargs)

def resign(c):
    c.cfg['a_0925_recovery_authorization_sha256'] = digest(canonical(c.auth))

def test_one_additional_budget_preserves_original_bytes_and_attempts(case):
    before = {p: p.read_bytes() for p in case.path.parent.rglob('*.json') if p != case.path}
    result = dispatch(case)
    assert len(case.calls) == 1
    assert result['node_attempt_count'] == 4
    assert result['repair_recovery_original_attempt_count'] == 3
    assert result['repair_recovery_attempt_count'] == 1
    saved = json.loads((case.path.parent/'a_0925_issue11_recovery.json').read_bytes())
    assert base64.b64decode(saved['original_receipt_base64'], validate=True) == case.raw
    assert saved['original_receipt_sha256'] == digest(case.raw)
    assert all(p.read_bytes() == b for p,b in before.items())
    assert dispatch(case)['status'] == 'SKIPPED_REPAIR_RECOVERY_CONSUMED'
    assert len(case.calls) == 1

@pytest.mark.parametrize('field,value', [('trade_date','20260929'),('stage_id','STAGE_1300_1315'),
    ('market','HK_CONNECT'),('additional_attempts',2),('additional_attempts',True),
    ('reviewer_id','writer'),('review_status','PENDING'),('candidate_count',200),
    ('production_allowed',True),('original_receipt_sha256','f'*64),('codes_sha256','f'*64)])
def test_other_scope_or_unapproved_auth_never_runs(case,field,value):
    case.auth[field] = value; resign(case)
    assert dispatch(case)['status'] == 'SKIPPED_RETRY_EXHAUSTED'
    assert case.calls == [] and case.path.read_bytes() == case.raw
    assert not (case.path.parent/'a_0925_issue11_recovery.json').exists()

@pytest.mark.parametrize('change', ['wrong_error','count','exhausted','valid_a_rows','receipt_sha','attempt_sha',
    'missing_attempt','wrong_fixed_sha','auth_sha','auto','tomorrow','natural','candidate','selection_corrupt'])
def test_invalid_evidence_refuses(case,monkeypatch,change):
    if change in ('wrong_error','count','exhausted','valid_a_rows','receipt_sha'):
        value = deepcopy(case.old)
        if change == 'wrong_error': value['error'] = 'TypeError: unrelated failure'
        if change == 'count': value['node_attempt_count'] = 2
        if change == 'exhausted': value['retry_exhausted'] = False
        if change == 'valid_a_rows': value['markets']['A_SHARE']['selected_rows'] = 10
        if change == 'receipt_sha': value['note'] = 'drift'
        raw = canonical(value); case.path.write_bytes(raw)
        if change != 'receipt_sha':
            monkeypatch.setattr(entry,'_ISSUE11_RECEIPT_SHA',digest(raw));case.auth['original_receipt_sha256']=digest(raw)
    elif change == 'attempt_sha':
        (case.path.parent / next(iter(case.auth['original_attempts']))).write_bytes(b'{}')
    elif change == 'missing_attempt': case.auth['original_attempts'].pop(next(iter(case.auth['original_attempts'])))
    elif change == 'wrong_fixed_sha': case.auth['fixed_modules'] = {'wrong.module': 'f'*64}
    elif change == 'auth_sha': case.auth['approval_id'] = 'tampered'
    elif change == 'auto': case.cfg.pop('_issue11_explicit_request')
    elif change == 'tomorrow': monkeypatch.setattr(nodes,'_rearm_wall_now',lambda:NOW.replace(day=1,month=10))
    elif change == 'candidate': monkeypatch.setattr('stage_center.candidate_input.read_candidate_input',lambda *a:None)
    elif change == 'selection_corrupt':
        p=Path(case.cfg['selection_root'])/'selection_latest.json';p.parent.mkdir();p.write_bytes(b'{}')
    if change != 'auth_sha': resign(case)
    dispatch(case,mode='NATURAL' if change == 'natural' else 'RECOVERY')
    assert case.calls == []


def test_crash_and_inner_receipt_replacement_cannot_reopen_budget(case):
    def crash(decision):
        case.runner._write_receipt({**case.old,'node_attempt_count':0},DATE,STAGE)
        raise RuntimeError('SYNTHETIC crash')
    case.runner._run_one=crash
    with pytest.raises(RuntimeError,match='SYNTHETIC'): dispatch(case)
    assert dispatch(case)['status']=='SKIPPED_REPAIR_RECOVERY_CONSUMED'


def test_same_lock_receipt_drift_cannot_reserve(case,monkeypatch):
    class Lock:
        def __init__(self,*a): pass
        def acquire(self): case.path.write_bytes(b'{}');return True
        def release(self): pass
    monkeypatch.setattr('stage_center.runner.SlotLock',Lock)
    assert dispatch(case)['status']=='SKIPPED_RECEIPT_CHANGED'
    assert not (case.path.parent/'a_0925_issue11_recovery.json').exists()


def test_symlink_reservation_is_consumed_not_followed(case,tmp_path):
    p=case.path.parent/'a_0925_issue11_recovery.json';p.symlink_to(tmp_path/'missing')
    assert dispatch(case)['status']=='SKIPPED_REPAIR_RECOVERY_CONSUMED'
    assert case.calls==[]


def test_public_nodes_require_exact_explicit_node(case):
    for explicit in (None, 'STAGE_1300_1315'):
        result=nodes.run_nodes(case.cfg,trade_date=DATE,evaluated_at=NOW,explicit_node=explicit,runner=case.runner)
        assert result['error']=='ISSUE11_REQUIRES_EXPLICIT_20260930_STAGE_0925'
        assert case.calls==[]


def test_frozen_production_scope_pins():
    assert getattr(entry,'_ISSUE11_RECEIPT_SHA',None)=='b920987cdecc63d0f7857c50404b3807c8f5212f418be304f75a11a06500a87f'
    assert entry._ISSUE11_CANDIDATE_SHA=='92023837d8709abfb46fb03dec82ee9758ff56e57615cdfebeb98926e3789d72'
    assert entry._ISSUE11_CODES_SHA=='80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69'


def test_existing_other_stage_does_not_block_missing_auction_slot(case):
    from stage_center.selection import SelectionStore, _selection_envelope
    store = SelectionStore(case.cfg['selection_root'])
    env = _selection_envelope(trade_date=DATE, stage_id='STAGE_1300_1315', market='A_SHARE',
        raw_artifact_sha256='3'*64, source_status='READY', input_rows=1,
        rows=[{'code':'A.600000','rank':1,'score':1.0,'trade_status':'NO_TRADE',
               'action_level':'NO_BUY','formal_eligible':False}],
        requested_rows=1, missing_symbols=[], cannot_confirm=[], source_evidence=[])
    store.publish(env, market='A_SHARE')
    before = {p:p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    assert dispatch(case)['node_attempt_count'] == 4
    assert len(case.calls) == 1
    assert all(p.read_bytes()==value for p,value in before.items())
    assert store.read_verified(DATE,'STAGE_1300_1315','A_SHARE') == env


def test_corrupt_exact_auction_entry_never_treated_as_absent(case):
    from stage_center.selection import SelectionStore, SELECTION_LATEST_SCHEMA_VERSION
    store = SelectionStore(case.cfg['selection_root'])
    store.root.mkdir(parents=True)
    store.latest_path.write_bytes(canonical(dict(schema_version=SELECTION_LATEST_SCHEMA_VERSION,
        owner='stage_center', entries={store._key(DATE,STAGE,'A_SHARE'):None}, **SAFETY_FLAGS)))
    dispatch(case)
    assert case.calls == []


def test_consumed_recovery_is_not_reported_as_nodes_complete(case):
    dispatch(case)
    result = nodes.run_nodes(case.cfg, trade_date=DATE, evaluated_at=NOW,
                             explicit_node=STAGE, runner=case.runner)
    assert result['status'] == 'RETRY_EXHAUSTED'
    assert len(case.calls) == 1


def test_pinned_unfixed_github_collector_cannot_be_approved_by_its_own_hash():
    with pytest.raises(ValueError, match='KNOWN_UNFIXED_AUCTION_COLLECTOR'):
        entry._issue11_loaded_repair_identity()
