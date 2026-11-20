import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as physical
import pytest

from ops import research_panel_logical as logical
from ops.research_panel_delta import changed_rows, key_index


def make(tmp_path, old, updates, *, projection=None, excluded=(), schema=None):
    base = tmp_path/'base.parquet'
    physical.write_table(old, base, row_group_size=2)
    blocks = [logical.descriptor(base, key_rows=key_index(base))]
    for index, update in enumerate(updates):
        path=tmp_path/f'delta{index}.parquet'
        physical.write_table(update,path)
        blocks.append(logical.descriptor(path,symbols=set(update['ts_code'].to_pylist()),key_rows=key_index(path)))
    anchor=tmp_path/'current.logical'
    keys=set(zip(old['ts_code'].to_pylist(),old['trade_date'].to_pylist()))
    for update in updates:keys.update(zip(update['ts_code'].to_pylist(),update['trade_date'].to_pylist()))
    anchor.write_bytes(logical.anchor_bytes(schema if schema is not None else old.schema,blocks,rows=sum(c not in excluded for c,d in keys),
                                           projection=projection,excluded_symbols=excluded))
    return anchor


@pytest.fixture
def table():
    return pa.table(dict(ts_code=['000001.SZ','000001.SZ','00005.HK'],trade_date=[1,2,2],
        close=pa.array([10.,11.,None],type=pa.float64()),signal=pa.array([1,0,None],type=pa.int8())))


def test_legacy_compatible_and_overlay_key_filter(tmp_path,table):
    update=pa.Table.from_pylist([dict(ts_code='000001.SZ',trade_date=3,close=12.,signal=1)],schema=table.schema)
    anchor=make(tmp_path,table,[update])
    got=logical.parquet.read_table(anchor,columns=['trade_date','close'],filters=[('ts_code','=','000001.SZ'),('trade_date','<=',2)])
    assert got.to_pylist()==[dict(trade_date=1,close=10.),dict(trade_date=2,close=11.)]
    assert logical.parquet.ParquetFile(anchor).metadata.num_rows==4
    base=tmp_path/'base.parquet'
    assert logical.parquet.read_table(base).equals(table)
    with pytest.raises(pa.ArrowInvalid):physical.read_table(anchor)


def test_business_predicate_is_after_last_write_wins(tmp_path,table):
    update=pa.Table.from_pylist([dict(ts_code='000001.SZ',trade_date=1,close=2.,signal=0)],schema=table.schema)
    anchor=make(tmp_path,table,[update])
    got=logical.parquet.read_table(anchor,filters=[('ts_code','=','000001.SZ'),('close','>',5.)])
    assert got['trade_date'].to_pylist()==[2]
    streamed=pa.Table.from_batches(list(logical.parquet.ParquetFile(anchor).iter_batches(columns=['ts_code','trade_date','close'],batch_size=2)))
    assert len(streamed)==3
    assert next(r['close'] for r in streamed.to_pylist() if r['ts_code']=='000001.SZ' and r['trade_date']==1)==2.


def test_block_drift_and_quarantine_fail_closed(tmp_path,table):
    anchor=make(tmp_path,table,[],excluded=['000001.SZ'])
    assert logical.parquet.read_table(anchor)['ts_code'].to_pylist()==['00005.HK']
    base=tmp_path/'base.parquet';base.write_bytes(base.read_bytes()+b'bad')
    with pytest.raises(ValueError,match='LOGICAL_BLOCK_CHANGED'):logical.parquet.read_table(anchor)


def test_today_flags_project_without_old_row_upserts_and_preserve_hk(tmp_path):
    values=dict(ts_code=['000001.SZ','00005.HK'],trade_date=[2,2],close=[10.,10.],
        user_v1_hold_yesterday_keyline_daily=[1,None],user_v1_break_yesterday_keyline_daily=[1,None],
        user_v1_white_yellow_death_cross=[0,None],user_v1_break_prev_low=[0,None],
        user_v1_hold_yesterday_keyline_display_asof=[1,None],user_v1_break_yesterday_keyline_display_asof=[1,None],
        user_v1_sell_signal_display_asof=[1,None])
    old=pa.Table.from_pydict(values)
    fresh=old
    for field in logical.DISPLAY:
        fresh=fresh.set_column(fresh.schema.get_field_index(field),field,pa.array([0,None],type=old[field].type))
    assert len(changed_rows(old,fresh))==0
    anchor=make(tmp_path,old,[],projection=dict(asof_date=3))
    read=logical.parquet.read_table(anchor)
    assert all(read[name].to_pylist()==[0,None] for name in logical.DISPLAY)


def test_delta_null_nan_and_new_stock(tmp_path):
    old=pa.table(dict(ts_code=['000001.SZ']*3,trade_date=[1,2,3],close=pa.array([None,float('nan'),1.],from_pandas=False)))
    assert len(changed_rows(old,old))==0
    fresh=pa.concat_tables([old,pa.Table.from_pylist([dict(ts_code='000001.SZ',trade_date=4,close=2.)],schema=old.schema)])
    assert changed_rows(old,fresh)['trade_date'].to_pylist()==[4]
    assert len(changed_rows(pa.Table.from_batches([],schema=old.schema),fresh))==4
    with pytest.raises(ValueError,match='OLD_KEYS_LOST'):changed_rows(old,fresh.slice(1))


@pytest.mark.parametrize('cash',[.1,.15,.0499,.05,.198,.19853,.5,.2])
def test_actual_factor_revision_persists_affected_prefix(cash):
    old=pa.table(dict(ts_code=['002152.SZ']*3,trade_date=[1,2,3],close=[10.,11.,12.]))
    fresh=old.set_column(2,'close',pa.array([10.-cash,11.-cash,12.]))
    assert changed_rows(old,fresh)['trade_date'].to_pylist()==[1,2]


def test_legacy_float_promotion_and_new_nullable_field_are_explicit(tmp_path):
    old=pa.Table.from_pydict(dict(ts_code=['000001.SZ'],trade_date=[20261110],close=pa.array([1.25],type=pa.float32())))
    path=tmp_path/'old.parquet';logical.physical.write_table(old,path)
    schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.int64()),('close',pa.float64()),('new_context',pa.string())])
    anchor=tmp_path/'current.parquet';anchor.write_bytes(logical.anchor_bytes(schema,[logical.descriptor(path,key_rows={'000001.SZ':[0]})],rows=1))
    result=logical.parquet.read_table(anchor)
    assert result.schema.equals(schema) and result['close'].to_pylist()==[1.25] and result['new_context'].to_pylist()==[None]
    streamed=pa.Table.from_batches(list(logical.parquet.ParquetFile(anchor).iter_batches()),schema=schema)
    assert streamed.equals(result)


def test_contract_and_anchor_bytes_are_stable_across_hash_seeds(tmp_path, table):
    anchor = make(tmp_path, table, [])
    script = '''
import hashlib
import json
import sys
from pathlib import Path
import pyarrow as pa
from ops import research_panel_logical as logical
codes = {'000001.SZ', '002717.SZ', '688053.SH', '920001.BJ'}
meta = {'retained_history_asof': {code: 20261119 for code in codes}, 'RESEARCH_ONLY': True}
path = Path(sys.argv[1])
current = logical.LogicalFile(path)
raw = json.dumps(meta).encode() if sys.argv[2] == 'legacy' else logical.contract_bytes(meta)
schema = current.schema_arrow.with_metadata({logical.META: raw})
payload = logical.anchor_bytes(schema, current.blocks, rows=current.value['rows'])
if sys.argv[2] == 'legacy':
    path.write_bytes(payload)
else:
    assert logical.equivalent_anchor(path, payload)
print(hashlib.sha256(path.read_bytes()).hexdigest())
'''
    outputs = [subprocess.check_output([sys.executable, '-B', '-c', script, str(anchor), mode],
        env={**os.environ, 'PYTHONHASHSEED': seed}, text=True)
        for seed, mode in [('1', 'legacy'), ('2', 'current'), ('17', 'current')]]
    assert len(set(outputs)) == 1
    contract_script = '''
from ops.research_panel_logical import contract_bytes
print(contract_bytes({code: 20261119 for code in {'000001.SZ', '002717.SZ', '688053.SH', '920001.BJ'}}).hex())
'''
    current = [subprocess.check_output([sys.executable, '-B', '-c', contract_script],
        env={**os.environ, 'PYTHONHASHSEED': seed}) for seed in ['1', '2', '17']]
    assert len(set(current)) == 1


@pytest.mark.parametrize('change', [
    'field_type', 'field_order', 'field_metadata', 'other_metadata',
    'block_sha', 'block_scope', 'projection_lineage', 'rows_type',
    'contract_bool', 'contract_float', 'contract_list_order',
])
def test_anchor_equivalence_keeps_all_nonordering_identity_strict(tmp_path, table, change):
    contract = {'source': {'a': 1, 'b': True}, 'symbols': ['a', 'b']}
    schema = table.schema.with_metadata({logical.META: json.dumps(contract).encode(), b'other': b'fixed'})
    anchor = make(tmp_path, table, [], projection={'raw_lineage': {'code': 'original'}}, schema=schema)
    value = logical.LogicalFile(anchor)
    other = {'source': {'b': True, 'a': 1}, 'symbols': ['a', 'b']}
    candidate_schema = schema.with_metadata({logical.META: logical.contract_bytes(other), b'other': b'fixed'})
    blocks = json.loads(json.dumps(value.blocks))
    projection = value.value['projection']
    rows = value.value['rows']
    if change == 'field_type':
        candidate_schema = candidate_schema.set(1, pa.field('trade_date', pa.int32()))
    elif change == 'field_order':
        candidate_schema = pa.schema(list(reversed(candidate_schema)), metadata=candidate_schema.metadata)
    elif change == 'field_metadata':
        candidate_schema = candidate_schema.set(0, candidate_schema.field(0).with_metadata({b'new': b'value'}))
    elif change == 'other_metadata':
        candidate_schema = candidate_schema.with_metadata({**candidate_schema.metadata, b'other': b'changed'})
    elif change == 'block_sha':
        blocks[0]['sha256'] = '0' * 64
    elif change == 'block_scope':
        blocks[0]['symbols'] = ['different']
    elif change == 'projection_lineage':
        projection = {'raw_lineage': {'code': 'changed'}}
    elif change == 'rows_type':
        rows = float(rows)
    else:
        if change == 'contract_bool':
            other['source']['b'] = 1
        elif change == 'contract_float':
            other['source']['a'] = 1.0
        else:
            other['symbols'].reverse()
        candidate_schema = candidate_schema.with_metadata({**candidate_schema.metadata,
            logical.META: logical.contract_bytes(other)})
    payload = logical.anchor_bytes(candidate_schema, blocks, rows=rows, projection=projection)
    before = anchor.read_bytes()

    assert not logical.equivalent_anchor(anchor, payload)
    assert anchor.read_bytes() == before


@pytest.mark.parametrize('contract', [b'{"a":1,"a":1}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_anchor_equivalence_rejects_ambiguous_contract_json(tmp_path, table, contract):
    schema = table.schema.with_metadata({logical.META: contract})
    anchor = make(tmp_path, table, [], schema=schema)
    value = logical.LogicalFile(anchor)
    expected = schema.with_metadata({logical.META: b'{"a":1}'})
    payload = logical.anchor_bytes(expected, value.blocks, rows=value.value['rows'])
    with pytest.raises(ValueError, match='LOGICAL_(DUPLICATE_JSON_KEY|NONFINITE_JSON)'):
        logical.equivalent_anchor(anchor, payload)


def test_equivalent_legacy_contract_still_validates_physical_closure(tmp_path, table):
    schema = table.schema.with_metadata({logical.META: b'{"b":2,"a":1}'})
    anchor = make(tmp_path, table, [], schema=schema)
    value = logical.LogicalFile(anchor)
    expected = schema.with_metadata({logical.META: b'{"a":1,"b":2}'})
    payload = logical.anchor_bytes(expected, value.blocks, rows=value.value['rows'])
    before = anchor.read_bytes()
    assert logical.equivalent_anchor(anchor, payload)
    assert anchor.read_bytes() == before
    block = Path(value.blocks[0]['path'])
    block.write_bytes(block.read_bytes() + b'drift')
    with pytest.raises(ValueError, match='LOGICAL_BLOCK_CHANGED'):
        logical.equivalent_anchor(anchor, payload)
