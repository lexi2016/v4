import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as physical
import pytest

from ops import research_panel_logical as logical
from ops.research_panel_delta import changed_rows, key_index


def make(tmp_path, old, updates, *, projection=None, excluded=()):
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
    anchor.write_bytes(logical.anchor_bytes(old.schema,blocks,rows=sum(c not in excluded for c,d in keys),
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
