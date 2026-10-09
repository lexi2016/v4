"""Issue #24: real temporary SafeRoot I/O; synthetic owners; no live POST/data.

Run natively from the active application root on Mac. Full 333 MB probes are
separate commands; these tests do not invoke unrelated collection/owner suites.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from infrastructure.owned_io import SafeRoot
from v4.manager_research import store as s
from v4.manager_research import workspace as w

DATE = '20261002'
RUN = 'a' * 32
TIME = '2026-10-03T00:00:00+00:00'
LIMIT = 320 * 1024 * 1024


def current(body=''):
    return dict(target_trade_date=DATE, input_identity='d'*64,
                semantic_version='issue24-fixture', plan_context={'research_cutoff': TIME},
                gaps=[], stocks=[], existing_material_coverage={}, summary={}, lanes=[],
                authoritative_evidence={'body': body}, **w.FLAGS)


def plan(body='', *, run=RUN):
    row = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=DATE, run_id=run,
               generated_at=TIME, owner='ManagerResearchJobService.refresh_workspace_plan',
               execution_kind='MANUAL_REFRESH', input_identity='d'*64,
               workspace=current(body), read_contract_sha256='c'*64, **w.FLAGS)
    row['sha256'] = w.digest(row)
    return row


def latest(store):
    return store.root/'workspace_plans'/DATE/'latest.json'


def put_legacy(store, row):
    store._io.write_bytes(str(latest(store).relative_to(store.root)), s.canonical_json(row))


def seal(row):
    row = deepcopy(row)
    row['sha256'] = w.digest({k:v for k,v in row.items() if k!='sha256'})
    return row


def test_legacy_over_64_mib_is_read_losslessly_without_rewrite(tmp_path):
    store = s.ManagerResearchStore(tmp_path)
    row = plan('e' * (64 * 1024 * 1024))
    put_legacy(store, row)
    before = latest(store).stat()
    got = w._read_plan(store, DATE)
    assert got == row
    after = latest(store).stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)
    assert w._readback_plan(store, DATE, current())['plan_product']['status'] == 'CURRENT'


def test_ordinary_store_and_shared_reader_keep_64_mib_limit(tmp_path):
    store=s.ManagerResearchStore(tmp_path)
    paths=['products/'+DATE+'/ordinary.json','workspace_plan_runs/'+DATE+'/latest.json',
           'workspace_plans_extra/'+DATE+'/latest.json','workspace_plans/'+DATE+'/other.json']
    for relative in paths:
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('wb') as f:f.truncate(64*1024*1024+1)
        with pytest.raises(s.StoreError,match='STORE_READ_BOUNDARY_FAILED'):
            store._read(p)
    p=latest(store);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('wb') as f:f.truncate(64*1024*1024+1)
    with pytest.raises(ValueError,match='OWNED_FILE_TOO_LARGE'):
        SafeRoot(tmp_path).read_bytes(str(p.relative_to(tmp_path)))


def test_plan_above_cap_rejected_before_json_decode(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path);p=latest(store);p.parent.mkdir(parents=True)
    with p.open('wb') as f:f.truncate(LIMIT+1)
    monkeypatch.setattr(s.json,'loads',lambda *a,**k:pytest.fail('must reject at fstat, before JSON allocation'))
    with pytest.raises(s.StoreError,match='STORE_READ_BOUNDARY_FAILED'):
        store._read(p)


def test_writer_rejects_over_budget_before_any_publication(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path);row=plan('large')
    put_legacy(store,plan('preserve'))
    before=latest(store).read_bytes()
    monkeypatch.setattr(s,'WORKSPACE_PLAN_MAX_BYTES',len(s.canonical_json(row))-1,raising=False)
    with pytest.raises(s.StoreError,match='WORKSPACE_PLAN_TOO_LARGE'):
        store._write_atomic(latest(store),row)
    assert latest(store).read_bytes()==before
    with pytest.raises(s.StoreError,match='WORKSPACE_PLAN_TOO_LARGE'):
        store._write_atomic(latest(store).with_name(RUN+'.json'),row)
    assert not latest(store).with_name(RUN+'.json').exists()


def test_exact_cap_supported_and_writer_bytes_unchanged(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path);row=plan('核验😀\\\"\n\t')
    expected=s.canonical_json(row)
    monkeypatch.setattr(s,'WORKSPACE_PLAN_MAX_BYTES',len(expected),raising=False)
    store._write_atomic(latest(store).with_name(RUN+'.json'),row)
    store._write_atomic(latest(store),row)
    assert latest(store).read_bytes()==expected
    assert store._read(latest(store))==row


def test_immutable_run_cannot_be_overwritten(tmp_path):
    store=s.ManagerResearchStore(tmp_path);p=latest(store).with_name(RUN+'.json')
    store._write_atomic(p,plan('original'))
    before=p.read_bytes()
    with pytest.raises((s.StoreConflict,FileExistsError)):
        store._write_atomic(p,plan('changed'))
    assert p.read_bytes()==before


@pytest.mark.parametrize('kind',['run','attempt'])
def test_run_collision_does_not_overwrite_any_prior_run(tmp_path,monkeypatch,kind):
    store=s.ManagerResearchStore(tmp_path)
    if kind=='run':
        p=latest(store).with_name(RUN+'.json');store._write_atomic(p,plan('keep'))
    else:
        p=store.root/'workspace_plan_runs'/DATE/(RUN+'.json')
        store._write_atomic(p,{'retained':'original audit'})
    before=p.read_bytes()
    monkeypatch.setattr(w,'uuid4',lambda:SimpleNamespace(hex=RUN))
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current())
    monkeypatch.setattr(w,'_now',lambda:TIME)
    with pytest.raises((ValueError,s.StoreConflict),match='RUN_ALREADY_EXISTS'):
        w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert p.read_bytes()==before


@pytest.mark.parametrize('mutator',[
    lambda r:r.update(target_trade_date='20261001'),
    lambda r:r['workspace'].update(target_trade_date='20261001'),
    lambda r:r.update(input_identity='e'*64),
    lambda r:r.update(run_id='not-a-run'),
    lambda r:r.update(execution_kind='INVALID'),
    lambda r:r.update(generated_at='invalid'),
    lambda r:r.update(schema_version='wrong'),
])
def test_existing_plan_identity_validators_remain_fail_closed(tmp_path,mutator):
    store=s.ManagerResearchStore(tmp_path);row=plan();mutator(row);put_legacy(store,seal(row))
    with pytest.raises(ValueError,match='WORKSPACE_STORED_PLAN_INVALID'):
        w._read_plan(store,DATE)


def test_tampered_sha_is_not_accepted(tmp_path):
    store=s.ManagerResearchStore(tmp_path);row=plan();row['workspace']['authoritative_evidence']['body']='tampered'
    put_legacy(store,row)
    assert w._readback_plan(store,DATE,current())['plan_product']['status']=='READBACK_FAILED'


def test_legacy_manual_plan_without_execution_kind_remains_valid(tmp_path):
    store=s.ManagerResearchStore(tmp_path);row=plan();row.pop('execution_kind');put_legacy(store,seal(row))
    assert w._read_plan(store,DATE)['run_id']==RUN


def test_cutoff_and_stale_identity_still_control_consumption(tmp_path):
    store=s.ManagerResearchStore(tmp_path);put_legacy(store,plan())
    earlier=current();earlier['plan_context']['research_cutoff']='2026-10-02T00:00:00+00:00'
    assert w._readback_plan(store,DATE,earlier)['plan_product']['status']=='PLAN_AFTER_READ_CUTOFF'
    changed=current();changed['input_identity']='f'*64
    assert w._readback_plan(store,DATE,changed)['plan_product']['status']=='STALE_INPUTS_CHANGED'


@pytest.mark.parametrize('status',['READBACK_FAILED','STALE_INPUTS_CHANGED','NOT_MATERIALIZED','CURRENT_WRONG_RUN','CURRENT_WRONG_SHA','CURRENT_NOT_CONSUMED'])
def test_failed_save_readback_never_gets_success_journal(tmp_path,monkeypatch,status):
    store=s.ManagerResearchStore(tmp_path);seen=[]
    write=store._write_atomic
    def recording(path,value):
        if 'workspace_plan_runs' in path.parts:seen.append(deepcopy(dict(value)))
        write(path,value)
    monkeypatch.setattr(store,'_write_atomic',recording)
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'uuid4',lambda:SimpleNamespace(hex=RUN))
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current())
    def bad_readback(store,date,value):
        saved=store._read(latest(store))
        return {**value,'plan_product':dict(status='CURRENT' if status.startswith('CURRENT_') else status,
            run_id='b'*32 if status=='CURRENT_WRONG_RUN' else RUN,
            sha256='0'*64 if status=='CURRENT_WRONG_SHA' else saved['sha256'],
            consumed=status!='CURRENT_NOT_CONSUMED')}
    monkeypatch.setattr(w,'_readback_plan',bad_readback)
    with pytest.raises(ValueError,match='WORKSPACE_PLAN_SAVE_READBACK_FAILED'):
        w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert {r['state'] for r in seen}<={'RUNNING','FAILED'}
    terminal=store._read(store.root/'workspace_plan_runs'/DATE/'latest.json')
    assert terminal['state']=='FAILED'
    assert terminal['last_success_at'] is None
    assert 'success_scope' not in terminal


def test_success_returns_read_back_terminal_attempt(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path)
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current('全量证据'))
    result=w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert result['plan_product']['status']=='CURRENT'
    assert result['workspace_plan_attempt']['state']=='SUCCEEDED_EMPTY'
    attempt=store._read(store.root/'workspace_plan_runs'/DATE/'latest.json')
    assert result['workspace_plan_attempt']==attempt
    assert result['authoritative_evidence']['body']=='全量证据'


def test_symlink_boundary_is_not_weakened(tmp_path):
    store=s.ManagerResearchStore(tmp_path/'root');other=tmp_path/'outside.json';other.write_text('{}')
    p=latest(store);p.parent.mkdir(parents=True);p.symlink_to(other)
    with pytest.raises(s.StoreError,match='STORE_READ_BOUNDARY_FAILED'):store._read(p)
    with pytest.raises((OSError,ValueError,s.StoreError)):store._write_atomic(p,plan())
    assert other.read_text()=='{}'


def test_future_oversize_refresh_preserves_old_plan_and_records_failure(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path);put_legacy(store,plan('old'))
    original=latest(store).read_bytes()
    monkeypatch.setattr(s,'WORKSPACE_PLAN_MAX_BYTES',len(original),raising=False)
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current('z'*4096))
    with pytest.raises(s.StoreError,match='WORKSPACE_PLAN_TOO_LARGE'):
        w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert latest(store).read_bytes()==original
    assert sorted(p.name for p in latest(store).parent.iterdir())==['latest.json']
    assert store._read(store.root/'workspace_plan_runs'/DATE/'latest.json')['state']=='FAILED'


def test_terminal_attempt_read_failure_cannot_return_saved_success(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path)
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current())
    read=store._read
    def faulty_read(path):
        row=read(path)
        if 'workspace_plan_runs' in path.parts and row and row.get('state')=='SUCCEEDED_EMPTY':
            raise s.StoreError('injected terminal read failure')
        return row
    monkeypatch.setattr(store,'_read',faulty_read)
    with pytest.raises(s.StoreError,match='injected terminal read failure'):
        w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    terminal=read(store.root/'workspace_plan_runs'/DATE/'latest.json')
    assert terminal['state']=='FAILED'
    assert terminal['last_success_at'] is None
    assert 'success_scope' not in terminal


def test_latest_plan_write_failure_leaves_prior_plan_and_no_success(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path);put_legacy(store,plan('existing'))
    before=latest(store).read_bytes()
    write=store._write_atomic
    def fail_latest(path,value):
        if path==latest(store):raise OSError('injected latest publication failure')
        return write(path,value)
    monkeypatch.setattr(store,'_write_atomic',fail_latest)
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:current())
    with pytest.raises(OSError,match='injected latest publication failure'):
        w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert latest(store).read_bytes()==before
    assert store._read(store.root/'workspace_plan_runs'/DATE/'latest.json')['state']=='FAILED'
    # A completed immutable run may remain for audit; never delete it to hide a failure.
    assert len(list(latest(store).parent.glob('*.json')))==2


def test_missing_plan_has_no_writes_and_is_not_success(tmp_path):
    store=s.ManagerResearchStore(tmp_path)
    before=set(tmp_path.rglob('*'))
    assert w._read_plan(store,DATE) is None
    got=w._readback_plan(store,DATE,current())
    assert got['plan_product']['status']=='NOT_MATERIALIZED'
    assert set(tmp_path.rglob('*'))==before


def test_null_and_insufficient_evidence_survive_lossless_save(tmp_path,monkeypatch):
    store=s.ManagerResearchStore(tmp_path)
    value=current()
    value['us_market_attention']={'status':'CANNOT_CONFIRM','mapping_diagnostics':{
        'assessment_state':'NOT_EVALUATED','accepted_hk_mapping_count':None,
        'assessment_reasons':['US_MARKET_SNAPSHOT_NOT_READY'],
        'relation_gate':'TWO_SOURCE_PIT_VERIFIED_REQUIRED'}}
    value['gaps']=['US_MARKET_SNAPSHOT_NOT_READY']
    monkeypatch.setattr(w,'_now',lambda:TIME)
    monkeypatch.setattr(w,'get_workspace',lambda *a,**k:deepcopy(value))
    got=w.refresh_workspace_plan(SimpleNamespace(store=store),DATE)
    assert got['workspace_plan_attempt']['state']=='PARTIAL'
    assert got['us_market_attention']==value['us_market_attention']
    assert w._read_plan(store,DATE)['workspace']['us_market_attention']==value['us_market_attention']
