"""Storage-only packing and partial-member recovery; no formula replacement."""
import copy
import hashlib
import json
import struct
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from test_delta_owner import fixture
from ops import research_panel_delta as delta
from ops import research_panel_logical as logical
from ops import research_panel_qfq as owner


def one_bucket(f):
    f.q['_bucket'] = lambda code: 0
    def spool(path, *args):
        index=delta.key_index(path)
        groups={g:[c for c,ids in index.items() if g in ids] for g in {g for ids in index.values() for g in ids}}
        return {0:SimpleNamespace(read=lambda:logical.physical.read_table(path),groups=groups)}
    f.q['spool_current']=spool
    return f


def add_bj(f):
    code = '920001.BJ'
    f.raw[code] = f.raw['688053.SH'].copy()
    f.raw[code]['ts_code'] = code
    f.c['snapshot']['symbols'][code] = copy.deepcopy(f.c['snapshot']['symbols']['688053.SH'])
    refresh_snapshot(f)


def refresh_snapshot(f):
    owner._json(f.c['snapshot_file'], f.c['snapshot'])
    ref = dict(path=str(f.c['snapshot_file']), sha256=owner.sha(f.c['snapshot_file']))
    f.c['identity']['input_sha256'] = owner.canonical_sha(f.c['snapshot'])
    f.c['meta'].update(input_sha256=f.c['identity']['input_sha256'], adjustment_snapshot=ref)


def exact(left, right):
    assert left.schema.equals(right.schema, check_metadata=False)
    def ordered(table):
        codes=table['ts_code'].to_pylist();days=table['trade_date'].to_pylist()
        positions=sorted(range(len(table)),key=lambda i:(codes[i]is None,codes[i]or'',days[i]))
        return table.take(pa.array(positions,type=pa.int64()))
    left,right=ordered(left),ordered(right)
    for name in left.column_names:
        assert left[name].is_null().equals(right[name].is_null())
    pd.testing.assert_frame_equal(left.to_pandas(), right.to_pandas(), check_exact=True)


def test_packed_three_markets_exact_and_single_physical_reference(fixture):
    f = one_bucket(fixture); add_bj(f)
    result = delta.run_delta(f.q, f.c)
    assert result['status'] == 'CANDIDATE_READY'
    for role, path in f.c['candidates'].items():
        blocks = logical.closure(path)
        assert len(blocks) == 2
        assert len({b['path'] for b in blocks}) == len(blocks)
        assert blocks[1]['symbols'] == ['000001.SZ', '002152.SZ', '688053.SH', '920001.BJ']
        expected = [row for code in f.raw for row in f.compute(code, None, 3, None).to_dict('records')]
        expected += [dict(ts_code='00005.HK', trade_date=2, close=None, signal=None, name='HK')]
        expected = pa.Table.from_pylist(expected, schema=f.schema)
        actual = logical.parquet.read_table(path)
        exact(actual, expected)
        streamed = pa.Table.from_batches(list(logical.parquet.ParquetFile(path).iter_batches(batch_size=2)))
        exact(streamed, expected)
        for code in ['000001.SZ', '688053.SH', '920001.BJ']:
            got = logical.parquet.read_table(path, filters=[('ts_code', '=', code)])
            exact(got, expected.filter(pc.equal(expected['ts_code'], code)))
    assert len(list((f.c['run_dir'] / 'delta_batch_seals').glob('*.json'))) == 1
    index = json.loads(next((f.c['run_dir']/'delta_checkpoints').glob('000001.SZ.*.json')).read_text())
    assert index['batch_seal'] and 'block' not in index['roles']['selector']
    calls = list(f.calls)
    again = delta.run_delta(f.q, f.c)
    assert f.calls == calls and again['new_delta_file_bytes'] == 0
    assert again['reused_delta_checkpoints'] == 5


def test_no_member_checkpoint_before_both_roles_are_durable(fixture, monkeypatch):
    f = one_bucket(fixture)
    original = f.q['_write']
    def fail(path, payload):
        if 'backtest/delta_blocks/batch.' in str(path):
            raise OSError('INJECTED_SECOND_BATCH_ROLE')
        return original(path, payload)
    f.q['_write']=fail
    pointers = {r:p.read_bytes() for r,p in f.pointers.items()}
    with pytest.raises(OSError, match='SECOND_BATCH_ROLE'):
        delta.run_delta(f.q, f.c)
    assert not list((f.c['run_dir']/'delta_batch_seals').glob('*.json'))
    for code in ['000001.SZ', '002152.SZ', '688053.SH']:
        assert not list((f.c['run_dir']/'delta_checkpoints').glob(code+'.*.json'))
    assert pointers == {r:p.read_bytes() for r,p in f.pointers.items()}
    f.q['_write']=original
    result = delta.run_delta(f.q, f.c)
    assert result['status'] == 'CANDIDATE_READY'


def test_atomic_seal_restores_missing_index_without_recalculation(fixture):
    f = one_bucket(fixture); original = f.q['_json']
    def fail(path, value):
        if Path(path).parent.name == 'delta_checkpoints' and Path(path).name.startswith('688053.SH.'):
            raise OSError('INJECTED_MEMBER_INDEX')
        return original(path, value)
    f.q['_json'] = fail
    with pytest.raises(OSError, match='MEMBER_INDEX'):
        delta.run_delta(f.q, f.c)
    assert list((f.c['run_dir']/'delta_batch_seals').glob('*.json'))
    calls = list(f.calls); f.q['_json'] = original
    result = delta.run_delta(f.q, f.c)
    assert f.calls == calls and result['new_delta_file_bytes'] == 0
    assert result['reused_delta_checkpoints'] == 4
    assert list((f.c['run_dir']/'delta_checkpoints').glob('688053.SH.*.json'))


def resumed_only_a(f):
    cp = next((f.c['run_dir']/'delta_checkpoints').glob('000001.SZ.*.json'))
    c = {**f.c, 'run_dir':f.tmp/'resumed', 'run_id':'resumed',
        'candidates':{r:f.tmp/('resumed_'+r)/'current.logical' for r in f.c['candidates']}}
    c['run_dir'].mkdir()
    c['meta'] = {**f.c['meta'], 'generation_id':'resumed', 'generation_manifest_path':str(c['run_dir']/'candidate_receipt.json')}
    c['recovered'] = {'000001.SZ':dict(checkpoint=dict(path=str(cp),sha256=owner.sha(cp)),
        read_only_delta=True, source_generation=f.c['run_id'], source_run=str(f.c['run_dir']),
        source_candidates={r:str(p) for r,p in f.c['candidates'].items()})}
    return c


@pytest.mark.parametrize('other', ['revision', 'quarantine', 'no_target'])
def test_partial_batch_member_recovery_never_imports_other_members(fixture, other):
    f = one_bucket(fixture)
    if other == 'quarantine':
        f.c['snapshot']['original_quarantine_eligible'] = {'002152.SZ':'fixture'}
        refresh_snapshot(f)
    delta.run_delta(f.q, f.c)
    c = resumed_only_a(f)
    if other == 'revision':
        f.raw['002152.SZ']['close'] += 7
    if other == 'no_target':
        f.raw['002152.SZ'].drop(f.raw['002152.SZ'].index[-1], inplace=True)
    if other == 'quarantine':
        original = f.q['rebuild_symbol']
        def rebuild(code, *args):
            if code == '002152.SZ':
                raise owner.QfqGateError('ORIGINAL_RAW_FIELD_SIGNATURE_QUARANTINED:002152.SZ:[3]')
            return original(code, *args)
        f.q['rebuild_symbol'] = rebuild
    delta.run_delta(f.q, c)
    for path in c['candidates'].values():
        blocks = logical.closure(path)
        shared = next(b for b in blocks if 'batch.' in b['path'] and str(f.c['candidates']['selector'].parent) in b['path']) if path == c['candidates']['selector'] else next(b for b in blocks if str(f.c['candidates']['backtest'].parent) in b['path'] and 'batch.' in b['path'])
        assert shared['symbols'] == ['000001.SZ']
        assert set(shared['key_rows']) == {'000001.SZ'}
        actual = logical.parquet.read_table(path)
        streamed = pa.Table.from_batches(list(logical.parquet.ParquetFile(path).iter_batches(batch_size=2)))
        exact(actual, streamed)
        got = logical.parquet.read_table(path, filters=[('ts_code','=','002152.SZ')])
        if other == 'quarantine':
            assert len(got) == 0
        else:
            expected = pa.Table.from_pandas(f.compute('002152.SZ',None,3,None),schema=f.schema,preserve_index=False)
            exact(got, expected)
            if other == 'no_target': assert 3 not in got['trade_date'].to_pylist()


def bind_missing_old_raw(f, links):
    old_ref = f.c['contracts']['selector']['adjustment_snapshot']
    snapshot_path = Path(old_ref['path'])
    old = json.loads(snapshot_path.read_text())
    for code, path in links.items():
        old['symbols'][code]['raw_files'] = [
            dict(path=str(path), sha256=hashlib.sha256(b'fixture old raw').hexdigest())]
    owner._json(snapshot_path, old)
    old_ref['sha256'] = owner.sha(snapshot_path)


def test_unresolved_old_stock_does_not_prevent_late_healthy_checkpoints(fixture):
    f = one_bucket(fixture)
    f.c.update(workers=1, resource_plan={'max_pending': 1}, publish=True)
    accepted, eligible, last = '000001.SZ', '002152.SZ', '688053.SH'
    accepted_path, eligible_path = f.tmp / 'old-accepted.day', f.tmp / 'old-eligible.day'
    bind_missing_old_raw(f, {accepted: accepted_path, eligible: eligible_path})
    original_status = {'reason_code': 'FIXTURE_POLICY_EVIDENCE'}
    f.c['snapshot']['original_quarantine_eligible'] = {eligible: original_status}
    refresh_snapshot(f)
    original = f.q['resolved_raw_history']
    attempts = []

    def raw(code, item, *args):
        if item['raw_kind'] == 'new':
            attempts.append(code)
        for ref in item.get('raw_files', []):
            owner._source(ref, owner=code)
        return original(code, item, *args)

    f.q['resolved_raw_history'] = raw
    pointers = {role: path.read_bytes() for role, path in f.pointers.items()}
    with pytest.raises(owner.QfqGateError, match='DELTA_OLD_BASELINE_STOCKS_UNRESOLVED:1'):
        delta.run_delta(f.q, f.c)

    assert attempts == [accepted, eligible, '002717.SZ', last]
    assert f.calls == [last]
    failed = {accepted: f'SOURCE_BINDING_FAILED:{accepted}:{accepted_path}'}
    run = f.c['run_dir']
    status = json.loads((run / 'stage_status.json').read_text())
    progress = json.loads((run / 'progress.json').read_text())
    for state in [status, progress]:
        assert state['failed_stocks'] == failed and state['failed_stock_count'] == 1
    assert status['status'] == 'FAILED'
    assert progress['stage'] == 'BASELINE_STOCKS_UNRESOLVED' and progress['completed'] == 3
    assert not any(path.exists() for path in f.c['candidates'].values())
    assert pointers == {role: path.read_bytes() for role, path in f.pointers.items()}
    cp_dir = run / 'delta_checkpoints'
    assert {path.name.split('.')[0] for path in cp_dir.glob('*.json')} == {'002717', '688053'}
    record = delta._load_checkpoint(f.q, next(cp_dir.glob(last + '.*.json')), last)
    assert set(record['roles']) == set(f.pointers)

    accepted_path.write_bytes(b'fixture old raw')
    result = delta.run_delta(f.q, f.c)
    assert result['status'] == 'READY' and result['reused_delta_checkpoints'] == 2
    assert f.calls == [last, accepted]
    assert result['dependency_classifications'][eligible] == 'ORIGINAL_QUARANTINE_ELIGIBLE_FAILURE'
    manifest = json.loads(Path(result['quarantine_manifest']['path']).read_text())
    assert manifest['reasons'] == {eligible: dict(
        reason=f'SOURCE_BINDING_FAILED:{eligible}:{eligible_path}', original_status=original_status)}
    assert all(f.pointers[role].read_text().strip() == str(path) for role, path in f.c['candidates'].items())


@pytest.mark.parametrize('failure_kind', ['current_raw', 'eligible_current_raw',
    'eligible_current_reread', 'eligible_current_format', 'shared_old_raw', 'shared_old_alias',
    'other_old_owner', 'checkpoint'])
def test_unclassified_worker_failure_stops_pending_submissions(fixture, failure_kind):
    f = one_bucket(fixture)
    f.c.update(workers=1, resource_plan={'max_pending': 1}, publish=True)
    first = '000001.SZ'
    path = f.tmp / 'missing.day'
    if failure_kind == 'shared_old_alias':
        alias = f.tmp / 'alias.day'
        alias.symlink_to(path.name)
        assert alias.is_symlink() and not alias.exists()
        bind_missing_old_raw(f, {first: alias, '002152.SZ': path})
    elif failure_kind in {'shared_old_raw', 'other_old_owner'}:
        links = {first: path}
        if failure_kind == 'shared_old_raw':
            links['002152.SZ'] = path
        bind_missing_old_raw(f, links)
    eligibility = {first: {'reason_code': 'FIXTURE'}}
    if failure_kind == 'shared_old_alias':
        eligibility['002152.SZ'] = {'reason_code': 'FIXTURE'}
        f.c['snapshot']['accepted_target_date_floor'] = 1
    eligible = failure_kind.startswith('eligible_') or failure_kind in {'shared_old_raw', 'shared_old_alias', 'checkpoint'}
    if eligible:
        f.c['snapshot']['original_quarantine_eligible'] = eligibility
        refresh_snapshot(f)
    if failure_kind == 'checkpoint':
        f.c['recovered'] = {first: dict(read_only_delta=True, checkpoint=dict(path=str(path), sha256='0' * 64))}
    original = f.q['resolved_raw_history']
    attempts = []

    def raw(code, item, *args):
        if item['raw_kind'] == 'new':
            attempts.append(code)
            if failure_kind in {'current_raw', 'eligible_current_raw'}:
                owner._source(dict(path=str(path), sha256='0' * 64), owner=code)
            if failure_kind == 'eligible_current_format':
                raise owner.QfqGateError(f'RAW_TRAILING_BYTES:{code}:{path}')
        else:
            for ref in item.get('raw_files', []):
                owner._source(ref, owner='different owner' if failure_kind == 'other_old_owner' else code)
        return original(code, item, *args)

    f.q['resolved_raw_history'] = raw
    if failure_kind == 'eligible_current_reread':
        def rebuild(code, *args):
            owner._source(dict(path=str(path), sha256='0' * 64), owner=code)
        f.q['rebuild_symbol'] = rebuild
    expected = 'RAW_TRAILING_BYTES' if failure_kind == 'eligible_current_format' else 'SOURCE_BINDING_FAILED'
    with pytest.raises(owner.QfqGateError, match=expected):
        delta.run_delta(f.q, f.c)
    assert attempts == [first]
    status = json.loads((f.c['run_dir'] / 'stage_status.json').read_text())
    progress = json.loads((f.c['run_dir'] / 'progress.json').read_text())
    assert status['failed_stocks'] == {} and status['failed_stock_count'] == 0
    if failure_kind == 'shared_old_alias':
        assert status['error'] == f'SOURCE_BINDING_FAILED:{first}:{alias}'
    assert progress['stage'] == 'DRAINED'
    assert not any(path.exists() for path in f.c['candidates'].values())


@pytest.mark.parametrize('first_proven', [True, False], ids=['first-proven', 'neither-proven'])
def test_prefix_failure_for_stock_with_shared_raw_source_is_fatal(fixture, first_proven):
    f = one_bucket(fixture)
    f.c.update(target=20261117, workers=1, resource_plan={'max_pending': 1}, publish=True)
    first, second = '000001.SZ', '002152.SZ'
    record = struct.Struct('<I28s')
    f.c['driver'].DAY_STRUCT = record

    def bind(name, before, current):
        path = f.tmp / name
        path.write_bytes(current)
        return [dict(path=str(path), sha256=hashlib.sha256(payload).hexdigest())
                for payload in (before, current)]

    prefix = record.pack(20261112, b'a' * 28)
    tail = record.pack(20261117, b'b' * 28)
    first_current = prefix if first_proven else record.pack(20261112, b'd' * 28)
    old_a, new_a = bind('first-private.day', prefix, first_current + tail)
    old_b, new_b = bind('later-shared.day', prefix, record.pack(20261112, b'c' * 28) + tail)
    old_ref = f.c['contracts']['selector']['adjustment_snapshot']
    path = Path(old_ref['path'])
    snapshot = json.loads(path.read_text())
    snapshot['asof_date'] = 20261116
    snapshot['symbols'][first]['raw_files'] = [old_a, old_b]
    snapshot['symbols'][second]['raw_files'] = [old_b]
    owner._json(path, snapshot)
    old_ref['sha256'] = owner.sha(path)

    f.c['snapshot']['symbols'][first]['raw_files'] = [new_a, new_b]
    f.c['snapshot']['original_quarantine_eligible'] = {first: {'reason_code': 'FIXTURE'}}
    refresh_snapshot(f)
    attempts = []
    original = f.q['resolved_raw_history']

    def raw(code, item, *args):
        if item['raw_kind'] == 'new':
            attempts.append(code)
        for ref in item.get('raw_files', ()):
            owner._source(ref, owner=code)
        return original(code, item, *args)

    f.q['resolved_raw_history'] = raw
    pointers = {role: path.read_bytes() for role, path in f.pointers.items()}
    failed = old_b if first_proven else old_a
    reason = f"SOURCE_BINDING_FAILED:{first}:{failed['path']}"
    with pytest.raises(owner.QfqGateError) as caught:
        delta.run_delta(f.q, f.c)
    assert str(caught.value) == reason
    assert str(caught.value.__cause__) == f"SOURCE_BINDING_FAILED:{first}:{old_a['path']}"
    assert attempts == [first]
    status = json.loads((f.c['run_dir'] / 'stage_status.json').read_text())
    assert status['error'] == reason and status['failed_stock_count'] == 0
    assert not any(path.exists() for path in f.c['candidates'].values())
    assert pointers == {role: path.read_bytes() for role, path in f.pointers.items()}


def _old_reference_failure_in_spawn_worker(ref):
    delta.baseline_raw_history(vars(owner), '000001.SZ', {'raw_files': [ref]},
        {'raw_files': []}, 20261116, 20261117, None)


def test_old_reference_failure_preserves_original_reason_across_spawn(tmp_path):
    import multiprocessing
    import sys
    from concurrent.futures import ProcessPoolExecutor

    path = tmp_path / 'missing.day'
    ref = dict(path=str(path), sha256='0' * 64)
    multiprocessing.set_executable(sys.executable)
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        future = pool.submit(_old_reference_failure_in_spawn_worker, ref)
        with pytest.raises(delta._OldBaselineSourceBindingError) as caught:
            future.result()
    assert str(caught.value) == f'SOURCE_BINDING_FAILED:000001.SZ:{path}'
    assert caught.value.source_path == path


def test_checkpoint_and_shared_file_sha_drift_fail_closed(fixture):
    f = one_bucket(fixture); delta.run_delta(f.q,f.c)
    cp = next((f.c['run_dir']/'delta_checkpoints').glob('000001.SZ.*.json'))
    row = json.loads(cp.read_text()); row['logical_rows']['selector'] += 1; cp.write_text(json.dumps(row))
    with pytest.raises(ValueError,match='INDEX_DRIFT'):
        delta.run_delta(f.q,f.c)


def test_empty_and_none_symbol_scope_are_distinct(tmp_path):
    table = pa.table(dict(ts_code=['000001.SZ','600001.SH','000001.SZ','600001.SH'],
        trade_date=[1,1,2,2], close=[1.,2.,3.,4.]))
    source = tmp_path/'shared.parquet'; logical.physical.write_table(table,source,row_group_size=1)
    for scope, count in [(None,4),([],0),(['000001.SZ'],2)]:
        block=logical.descriptor(source,key_rows=delta.key_index(source),symbols=scope)
        if scope is not None:block['key_rows']={c:block['key_rows'][c]for c in scope}
        anchor=tmp_path/('scope_'+str(count)+'.logical');anchor.write_bytes(logical.anchor_bytes(table.schema,[block],rows=count))
        assert len(logical.parquet.read_table(anchor))==count
        streamed=pa.Table.from_batches(list(logical.parquet.ParquetFile(anchor).iter_batches(batch_size=1)),schema=table.schema)
        assert len(streamed)==count
        if scope is not None:assert len(logical.parquet.read_table(anchor,filters=[('ts_code','=','600001.SH')]))==0


def test_unscoped_overlay_keys_never_shadow_base_or_leak(tmp_path):
    base=pa.table(dict(ts_code=['000001.SZ','600001.SH'],trade_date=[1,1],close=[10.,20.]))
    update=pa.table(dict(ts_code=['000001.SZ','600001.SH','600001.SH'],trade_date=[2,1,2],close=[11.,-999.,-999.]))
    paths=[]
    for name,table in [('base',base),('overlay',update)]:
        p=tmp_path/(name+'.parquet');logical.physical.write_table(table,p,row_group_size=1);paths.append(p)
    blocks=[logical.descriptor(paths[0],key_rows=delta.key_index(paths[0])),logical.descriptor(paths[1],symbols=['000001.SZ'],key_rows={'000001.SZ':[0]})]
    a=tmp_path/'current.logical';a.write_bytes(logical.anchor_bytes(base.schema,blocks,rows=3))
    expected=pa.concat_tables([base,update.slice(0,1)])
    exact(logical.parquet.read_table(a),expected)
    exact(pa.Table.from_batches(list(logical.parquet.ParquetFile(a).iter_batches(batch_size=1))),expected)
    assert logical.parquet.read_table(a,filters=[('ts_code','=','600001.SH')])['close'].to_pylist()==[20.]


def test_packing_bound_and_stop_drain_preserve_sealed_members(fixture):
    f=one_bucket(fixture);f.c['workers']=1;f.c['resource_plan']={'job_budget_bytes':64*1024**2}
    assert delta._packing_limits(f.c)==dict(max_bytes=1024**2,max_symbols=2)
    original=f.q['rebuild_symbol']
    def stop(*args):
        (f.c['run_dir']/'STOP_REQUESTED').touch()
        return original(*args)
    f.q['rebuild_symbol']=stop
    with pytest.raises(InterruptedError,match='STOP_REQUESTED_DRAINED'):
        delta.run_delta(f.q,f.c)
    cps=list((f.c['run_dir']/'delta_checkpoints').glob('*.json'));assert cps
    for cp in cps:
        row=delta._load_checkpoint(f.q,cp,cp.name.split('.')[0]+'.'+cp.name.split('.')[1])
        for value in row['roles'].values():assert owner.sha(Path(value['artifact']['path']))==value['artifact']['sha256']
    calls=list(f.calls);(f.c['run_dir']/'STOP_REQUESTED').unlink();f.q['rebuild_symbol']=original
    delta.run_delta(f.q,f.c)
    assert all(f.calls.count(code)==calls.count(code)for code in calls)
    for p in (f.c['run_dir']/'delta_batch_seals').glob('*.json'):
        assert len(json.loads(p.read_text())['records'])<=2


def test_shared_block_hash_corruption_is_rejected(fixture):
    f=one_bucket(fixture);delta.run_delta(f.q,f.c)
    path=Path(logical.closure(f.c['candidates']['selector'])[1]['path'])
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(owner.QfqGateError,match='SOURCE_BINDING_FAILED'):
        delta.run_delta(f.q,f.c)


@pytest.mark.parametrize('change',['date','symbol','future_key'])
def test_packed_semantic_identity_checks_survive_matching_file_hashes(fixture,change):
    f=one_bucket(fixture);delta.run_delta(f.q,f.c)
    cp=next((f.c['run_dir']/'delta_checkpoints').glob('000001.SZ.*.json'))
    saved=delta._load_checkpoint(f.q,cp,'000001.SZ');value=saved['roles']['selector'];path=Path(value['artifact']['path'])
    table=logical.physical.read_table(path);metadata=dict(table.schema.metadata);footer=json.loads(metadata[delta.BATCH_META])
    if change=='date':footer['asof_date']=4
    if change=='symbol':table=table.set_column(table.schema.get_field_index('ts_code'),'ts_code',pa.array(['999999.SH']+table['ts_code'].to_pylist()[1:]))
    if change=='future_key':table=table.set_column(table.schema.get_field_index('trade_date'),'trade_date',pa.array([4]+table['trade_date'].to_pylist()[1:]))
    metadata[delta.BATCH_META]=json.dumps(footer,sort_keys=True).encode();table=table.replace_schema_metadata(metadata)
    newpath=delta._batch_path(f.q,f.c,'selector',footer);logical.physical.write_table(table,newpath,compression='zstd')
    block=logical.descriptor(newpath,symbols=footer['members'],key_rows=delta.key_index(newpath));seal_path=Path(saved['batch_seal']['path']);seal=json.loads(seal_path.read_text());seal['blocks']['selector']=block;owner._json(seal_path,seal)
    ref=dict(path=str(seal_path),sha256=owner.sha(seal_path));saved['batch_seal']=ref;value.update(artifact=dict(path=str(newpath),sha256=block['sha256']),block={**block,'metadata_refs':[ref]})
    with pytest.raises(ValueError,match='DELTA_(BATCH_ARTIFACT_IDENTITY|CHECKPOINT_KEYS)'):
        delta._validate_persisted_patch(f.q,f.c,'000001.SZ',saved['dependency'],saved,'selector',value,f.schema)


def test_closed_packed_run_recovers_missing_member_index_without_old_writes(fixture,monkeypatch):
    f=one_bucket(fixture);data=f.tmp/'state/workspace/data';data.mkdir(parents=True)
    snapshot=f.c['snapshot'];mutable=owner.input_path(data);owner._json(mutable,snapshot)
    immutable=mutable.parent/'adjustment_snapshots'/(owner.sha(mutable)+'.json');owner._write(immutable,mutable.read_bytes());snapshot_ref=dict(path=str(immutable),sha256=owner.sha(immutable))
    identity={**f.c['identity'],'adapter_sha256':owner.sha(Path(owner.__file__)),'delta_owner_sha256':owner.sha(Path(delta.__file__)),'logical_reader_sha256':owner.sha(Path(logical.__file__)),
        'input_adapter_sha256':'fixture','factor_cache_sha256':'fixture','tdx_adapter_sha256':'fixture'}
    generation=owner.canonical_sha(dict(target=3,baseline_panel_sha256=f.c['baseline_hashes'],**identity))
    run=data.parents[1]/'research_panel_daily/a_formula_runs'/('qfq_'+generation[:20]);run.mkdir(parents=True)
    f.c.update(data_root=data,run_dir=run,run_id=generation,snapshot_file=mutable,identity=identity)
    f.c['meta'].update(identity);f.c['meta'].update(generation_id=generation,generation_manifest_path=str(run/'candidate_receipt.json'),adjustment_snapshot=snapshot_ref)
    f.q['generation_identity']=lambda s,*a:{**{k:v for k,v in identity.items()if k!='turnover_input_sha256'},'input_sha256':owner.canonical_sha(s)}
    delta.run_delta(f.q,f.c)
    status=json.loads((run/'stage_status.json').read_text());status['status']='FAILED';owner._json(run/'stage_status.json',status)
    missing=next((run/'delta_checkpoints').glob('688053.SH.*.json'));missing.unlink()
    entries=[dict(owner='main',target_relative='ops/'+name,target=str(Path(owner.__file__).with_name(name)),before_sha256=owner.sha(Path(owner.__file__).with_name(name)),after_sha256=owner.sha(Path(owner.__file__).with_name(name)))for name in ['research_panel_qfq.py','research_panel_delta.py','research_panel_logical.py']]
    binding=f.tmp/'fixture-binding.json';owner._json(binding,dict(items=entries,fixture_only=True));review=f.tmp/'fixture-review.json';owner._json(review,dict(verdict='REVIEWED/PASS',reviewer='independent-fixture',writer='fixture-writer',source_binding=dict(path=str(binding),sha256=owner.sha(binding)),not_live_acceptance=True))
    monkeypatch.setattr(owner,'factor_cache_identity',lambda *a:'fixture factor');monkeypatch.setattr(owner,'load_snapshot',lambda *a:copy.deepcopy(snapshot))
    body=delta.prepare_delta_resume(source_run=run,target_core=Path(owner.__file__),target_delta=Path(delta.__file__),independent_review=dict(path=str(review),sha256=owner.sha(review)),data_root=data)
    assert body['chunks']['688053.SH']['member']=='688053.SH' and body['completed_count']==4
    restored=delta.load_delta_recovery(vars(owner),body,snapshot,identity,f.c['baseline_hashes'],data)
    before={p:p.read_bytes()for p in run.rglob('*')if p.is_file()};calls=list(f.calls)
    c={**f.c,'run_dir':f.tmp/'newrun','run_id':'fixture-new-release','recovered':restored}
    c['run_dir'].mkdir();c['candidates']={r:f.tmp/('new_'+r)/'current.logical'for r in f.c['candidates']};c['meta']={**f.c['meta'],'generation_id':c['run_id'],'generation_manifest_path':str(c['run_dir']/'candidate_receipt.json')}
    result=delta.run_delta(f.q,c)
    assert result['reused_delta_checkpoints']==4 and result['new_delta_file_bytes']==0 and f.calls==calls
    assert not missing.exists() and all(p.read_bytes()==raw for p,raw in before.items())
    assert all(len(logical.parquet.read_table(p))==12 for p in c['candidates'].values())


def test_scope_preserves_dictionary_null_nan_and_negative_zero(tmp_path):
    codes=pa.array(['000001.SZ','600001.SH','000001.SZ',None]).dictionary_encode().cast(pa.dictionary(pa.int16(),pa.string()))
    table=pa.table(dict(ts_code=codes,trade_date=[1,1,2,3],close=pa.array([None,float('nan'),-0.,1.5],from_pandas=False)))
    p=tmp_path/'dictionary.parquet';logical.physical.write_table(table,p)
    for scope,count in [(None,4),([],0),(['000001.SZ'],2)]:
        block=logical.descriptor(p,symbols=scope,key_rows={k:v for k,v in delta.key_index(p).items()if k is not None});anchor=tmp_path/('dictionary'+str(count)+'.logical');anchor.write_bytes(logical.anchor_bytes(table.schema,[block],rows=count))
        actual=logical.parquet.read_table(anchor)
        streamed=pa.Table.from_batches(list(logical.parquet.ParquetFile(anchor).iter_batches(batch_size=1)),schema=table.schema)
        expected=table if scope is None else table.filter(pc.is_in(pc.cast(table['ts_code'],pa.string()),value_set=pa.array(scope,type=pa.string())))
        exact(actual,expected);exact(streamed,expected)
        assert actual['ts_code'].type==table['ts_code'].type


@pytest.mark.parametrize('deny',[False,True])
def test_batch_atomic_payloads_use_original_owner_storage_guard(fixture,deny):
    from ops import research_storage_governance as governance
    SpaceBlocked=governance.SpaceBlocked
    f=fixture
    class Claim:
        def __init__(self):self.watched=set();self.observed=set();self.incoming=[]
        def watch(self,path):self.watched.add(Path(path))
        def checkpoint(self,*,incoming=0):
            self.incoming.append(incoming)
            if deny and incoming:raise SpaceBlocked('TEST_ORIGINAL_BUDGET_REFUSED')
        def observe(self,path):self.observed.add(Path(path))
    claim=Claim();token=governance._ACTIVE.set(claim)
    try:
        with governance.qfq_write_seams(owner,claim):
            q=dict(vars(owner));packer=delta._PackedWrites(q,f.c)
            for i,code in enumerate(['000001.SZ','600001.SH']):
                table=pa.Table.from_pylist([dict(ts_code=code,trade_date=3,close=1.,signal=1,name=None)],schema=f.schema)
                record=dict(dependency=str(i)*64,classification='STORAGE_ONLY_TEST',roles={r:dict(appended_rows=1,revised_rows=0)for r in f.c['schemas']},logical_rows={r:1 for r in f.c['schemas']},has_target={r:True for r in f.c['schemas']})
                packer.add(dict(code=code,dependency=record['dependency'],checkpoint=f.c['run_dir']/'delta_checkpoints'/(code+'.'+record['dependency']+'.json'),kind=record['classification'],record=record,patches={r:table for r in f.c['schemas']}))
            if deny:
                with pytest.raises(SpaceBlocked,match='ORIGINAL_BUDGET_REFUSED'):packer.flush()
                assert not list(f.c['run_dir'].glob('delta_batch_seals/*.json'))
                assert not list(f.tmp.glob('*/delta_blocks/*.parquet'))
            else:
                packer.flush()
                files={p for p in f.tmp.rglob('*')if p.is_file()and (p.parent.name in ['delta_blocks','delta_batch_seals','delta_checkpoints'])}
                assert files==claim.observed and files<=claim.watched
                assert sum(value>0 for value in claim.incoming)==5
    finally:governance._ACTIVE.reset(token)
