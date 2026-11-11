"""Small original full-prefix oracle, no market-wide run or live output."""
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from ops import research_panel_qfq as q
from ops import research_panel_logical as logical
from ops.research_panel_delta import changed_rows

BASE=Path(__file__).resolve().parents[1]
APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-single-generation-20261111-r1/app')
FORMULA=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py')
REVISIONS={'002152.SZ':.1,'002275.SZ':.15,'002864.SZ':.0499,'300741.SZ':.05,'301300.SZ':.198,'301529.SZ':.19853,'603279.SH':.5,'605338.SH':.2}


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize('code',['000001.SZ','002717.SZ',*REVISIONS,'688053.SH'])
def test_original_full_prefix_logical_roundtrip(tmp_path,monkeypatch,code):
    original=load(BASE/'docs/handoffs/daily_incremental_io_20261111/research_panel_qfq.before.py','delta_full_prefix_original')
    driver,_=original.authorities(APP/'ops/vendor/data_layer_daily_formula_increment_update_v1.py',FORMULA)
    dates=pd.bdate_range(end='2026-11-11',periods=90)
    if code=='002717.SZ':dates=dates[:-1]
    values=10+np.arange(len(dates))*.01+np.sin(np.arange(len(dates)))
    raw=pd.DataFrame(dict(ts_code=code,trade_date=[int(x.strftime('%Y%m%d'))for x in dates],open=values,high=values+.2,low=values-.2,close=values+.05,amount=1000000.,vol=100000.,volume=100000.))
    oldraw=raw.loc[raw.trade_date.le(20261110)].copy()
    olditem=dict(history_start_date=int(raw.trade_date.min()),events=[])
    item={**olditem,'events':[dict(ex_date=20261111,a=1.,b=-REVISIONS[code],volume_a=1.)]if code in REVISIONS else []}
    monkeypatch.setattr(original,'resolved_raw_history',lambda *args:raw.copy())
    expected=original.rebuild_symbol(code,item,20261111,driver)
    monkeypatch.setattr(q,'resolved_raw_history',lambda *args:raw.copy())
    fresh=q.rebuild_symbol(code,item,20261111,driver)
    pd.testing.assert_frame_equal(fresh,expected,check_exact=True)
    if code=='688053.SH':old=pa.Table.from_batches([],schema=pa.Table.from_pandas(fresh,preserve_index=False).schema)
    else:
        monkeypatch.setattr(original,'resolved_raw_history',lambda *args:oldraw.copy())
        before=original.rebuild_symbol(code,olditem,20261110,driver)
        schema=pa.Table.from_pandas(fresh,preserve_index=False).schema
        old=pa.Table.from_pandas(before,schema=schema,preserve_index=False)
    table=pa.Table.from_pandas(fresh,preserve_index=False)
    patch=changed_rows(old,table)
    if code=='000001.SZ':assert len(patch)==1
    if code=='002717.SZ':assert len(patch)==0
    if code in REVISIONS:assert len(patch)>1
    base=tmp_path/'base.parquet';logical.physical.write_table(old,base)
    blocks=[logical.descriptor(base,key_rows={code:[0]} if len(old) else {})]
    if len(patch):
        delta=tmp_path/'delta.parquet';logical.physical.write_table(patch,delta);blocks.append(logical.descriptor(delta,symbols=[code]))
    anchor=tmp_path/'current.parquet';anchor.write_bytes(logical.anchor_bytes(table.schema,blocks,rows=len(table),projection=dict(asof_date=20261111)))
    oracle_file=tmp_path/'full_prefix_oracle.parquet';logical.physical.write_table(table,oracle_file)
    expected_table=logical.physical.read_table(oracle_file)
    actual_table=logical.parquet.read_table(anchor)
    assert actual_table.schema.equals(expected_table.schema,check_metadata=True)
    actual=actual_table.to_pandas().sort_values('trade_date').reset_index(drop=True)
    expected_frame=expected_table.to_pandas().sort_values('trade_date').reset_index(drop=True)
    pd.testing.assert_frame_equal(actual,expected_frame,check_exact=True)
