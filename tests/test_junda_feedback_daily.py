import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pathlib import Path
import json

from ops import research_panel_qfq as q
from ops.kb_hold_score import score_history


def sample():
    bars = [{'ts_code': '002865.SZ', 'trade_date': 20200000 + i, 'close': 20 + i / 10, 'high': 21 + i / 10, 'low': 19 + i / 10}
            for i in range(1, 31)]
    for row, score in zip(bars, score_history(bars)):
        row['kb_b1_j'] = score['kb_hold_j']
    return pd.DataFrame(bars)


def test_daily_qfq_uses_same_single_projection_on_append_and_revision():
    bars = sample()
    first = q._single_feedback_daily('002865.SZ', bars.iloc[:-1])
    extended = q._single_feedback_daily('002865.SZ', bars)
    assert set(q.SINGLE_FEEDBACK_FIELDS) <= set(extended.columns)
    assert first['kb_hold_score_min'].tolist() == extended['kb_hold_score_min'].tolist()[:-1]
    assert extended.iloc[-1]['kb_hold_score'] is None
    assert extended.iloc[-1]['kb_hold_score_min'] == 3
    assert extended.iloc[-1]['kb_s1'] is None
    revised = bars.copy()
    revised.loc[revised.index[-1], 'close'] = bars.iloc[-2]['close'] - 0.05
    revised.loc[revised.index[-1], 'kb_b1_j'] = score_history(revised.to_dict('records'))[-1]['kb_hold_j']
    assert not q._single_feedback_daily('002865.SZ', revised).iloc[-1]['kb_hold_close_up']
    assert q._single_feedback_daily('000001.SZ', bars) is bars


def feedback_schema():
    fields = [pa.field('trade_date', pa.int32()), pa.field('ts_code', pa.string())]
    for name in sorted(q.SINGLE_FEEDBACK_FIELDS):
        typ = (pa.string() if name.endswith('_reason') or name == 'kb_hold_score_status' else
               pa.int8() if name in {'kb_hold_score', 'kb_hold_score_min', 'kb_hold_score_max'} else
               pa.float64() if name in {'kb_hold_bbi', 'kb_hold_k', 'kb_hold_d'} else pa.bool_())
        fields.append(pa.field(name, typ))
    return pa.schema(fields)


def test_daily_write_path_rejects_field_loss_and_preserves_nulls(tmp_path):
    driver = q._load(Path(q.__file__).parent/'vendor/data_layer_daily_formula_increment_update_v1.py',
                     q.DRIVER_SHA, 'feedback_daily_test_vendor')
    legacy_schema = pa.schema([pa.field('trade_date', pa.int32()), pa.field('ts_code', pa.string())])
    full_schema = feedback_schema()
    assert q._single_feedback_pair_mode({'selector': legacy_schema, 'backtest': legacy_schema}) is False
    assert q._single_feedback_pair_mode({'selector': full_schema, 'backtest': full_schema}) is True
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_ROLE_SCHEMA_MISMATCH'):
        q._single_feedback_pair_mode({'selector': full_schema, 'backtest': legacy_schema})
    declared_but_missing=legacy_schema.with_metadata({q.META_KEY:json.dumps({'single_feedback_enabled':True}).encode()})
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_SCHEMA_MISSING'):
        q._single_feedback_pair_mode({'selector':declared_but_missing,'backtest':declared_but_missing})
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_PARTIAL_SCHEMA'):
        q._validate_single_feedback_schema(pa.schema([pa.field('kb_s1', pa.bool_())]))
    source = sample()
    raw = tmp_path/'raw.parquet';pq.write_table(pa.Table.from_pandas(source,preserve_index=False),raw)
    recovered = {'002865.SZ': {'artifact': {'path':str(raw),'sha256':q.sha(raw)}}}
    legacy_parts=tmp_path/'legacy';legacy_parts.mkdir()
    _,legacy_path=q._symbol_checkpoint('002865.SZ',{},20261030,{},legacy_parts,recovered,driver)
    legacy=pq.read_table(legacy_path).to_pandas()
    assert not (set(legacy.columns)&q.SINGLE_FEEDBACK_FIELDS)
    assert len(q._table(legacy,legacy_schema,driver,'backtest'))==len(source)
    enabled_parts=tmp_path/'enabled';enabled_parts.mkdir()
    _,enabled_path=q._symbol_checkpoint('002865.SZ',{},20261030,{'single_feedback_enabled':True},
                                        enabled_parts,recovered,driver,True)
    computed=pq.read_table(enabled_path).to_pandas()
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_OUTPUT_WOULD_DROP_FIELDS'):
        q._table(computed,legacy_schema,driver,'backtest')
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_SCHEMA_MISSING'):
        q._table(legacy,legacy_schema,driver,'backtest',single_feedback_enabled=True)
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_TARGET_FIELDS_MISSING'):
        q._table(legacy,full_schema,driver,'backtest',single_feedback_enabled=True)
    partial=pa.schema(list(full_schema)[:-1])
    with pytest.raises(q.QfqGateError, match='SINGLE_FEEDBACK_OUTPUT_WOULD_DROP_FIELDS|SINGLE_FEEDBACK_PARTIAL_SCHEMA'):
        q._table(computed,partial,driver,'backtest',single_feedback_enabled=True)
    actual=q._table(computed,full_schema,driver,'backtest',single_feedback_enabled=True)
    output=tmp_path/'candidate.parquet';pq.write_table(actual,output);read=pq.read_table(output)
    assert set(q.SINGLE_FEEDBACK_FIELDS)<=set(read.column_names)
    assert read['kb_hold_score_min'][-1].as_py()==3
    assert read['kb_hold_score'][-1].as_py() is None
    assert read['kb_hold_trend_up'][-1].as_py() is None
    assert read['kb_s1'][-1].as_py() is None


def test_process_backend_carries_explicit_feedback_mode(tmp_path,monkeypatch):
    seen=[]
    def checkpoint(*args):
        seen.append(args[-1])
        return '002865.SZ',tmp_path/'result.parquet'
    monkeypatch.setattr(q,'_symbol_checkpoint',checkpoint)
    assert q._symbol_process_task(('002865.SZ',{},20261030,{'single_feedback_enabled':True},str(tmp_path),{},True))[0]=='002865.SZ'
    assert seen==[True]
