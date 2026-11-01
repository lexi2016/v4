import math
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

from ops import research_panel_qfq as qfq
from ops.kb_signal_authority import append_kb_signals, _strict_fanbao


def _bars(n=150, code='000001.SZ', downward=False):
    close = 100 - np.arange(n) * 0.1 if downward else np.full(n, 100.0)
    previous = np.r_[np.nan, close[:-1]]
    return pd.DataFrame(dict(ts_code=code, trade_date=[f'{20170000 + i:08d}' for i in range(1, n+1)],
        open=close, high=close + 1, low=close - 1, close=close,
        vol=10000 - np.arange(n), pre_close=previous,
        pct_chg=np.r_[np.nan, (close[1:] / close[:-1] - 1) * 100], user_v1_B1=0))


def test_b1_three_of_four_and_short_history_unknown_preserve_old_columns():
    frame = _bars(15)
    out = append_kb_signals(frame)
    assert out.loc[7, 'kb_b1'] is None
    assert bool(out.loc[8, 'kb_b1']) and out.loc[8, 'kb_b1_score'] == 3
    assert out.loc[8, 'kb_b1_j'] == 50
    pd.testing.assert_frame_equal(frame, out[frame.columns])
    assert out.loc[11, 'kb_b2'] is None
    assert out.loc[12, 'kb_b2'] is False or out.loc[12, 'kb_b2'] == False


def test_macd_veto_requires_known_divergence_and_prefix_is_causal():
    frame = _bars(150, downward=True)
    result = append_kb_signals(frame)
    assert result.loc[29, 'kb_macd_dif_positive'] == False
    assert pd.isna(result.loc[29, 'kb_macd_veto'])
    assert not pd.isna(result.loc[84, 'kb_macd_bottom_divergence'])
    prefix = append_kb_signals(frame.iloc[:120])
    for col in qfq.KB_FIELDS:
        pd.testing.assert_series_equal(prefix[col].reset_index(drop=True), result[col].iloc[:120].reset_index(drop=True), check_dtype=False)


def test_fanbao_boundary_is_strict_integer_cents():
    assert not _strict_fanbao(10.00, 4.00, 8.00)
    assert _strict_fanbao(10.00, 4.00, 8.01)
    assert not _strict_fanbao(10.00, 4.00, 3.99)


def test_missing_and_invalid_inputs_remain_unknown_and_hk_is_never_a():
    broken = _bars(150)
    broken.loc[3, 'low'] = math.nan
    result = append_kb_signals(broken)
    assert pd.isna(result.loc[149, 'kb_b1'])
    assert pd.isna(result.loc[149, 'kb_fanbao'])
    hk = append_kb_signals(_bars(150, code='00700.HK'))
    assert hk[list(qfq.KB_FIELDS)].isna().all().all()


def test_rebuild_stays_unknown_even_with_sufficient_history():
    result = append_kb_signals(_bars(150))
    assert result['kb_rebuild'].isna().all()
    assert result['kb_b3'].notna().any()
    root = Path(qfq.__file__).resolve().parents[1]
    spec = json.loads((root / 'contracts/a_share_kb_fields_v1.json').read_text())
    field = next(item for item in spec['fields'] if item['name'] == 'kb_rebuild')
    assert field['status'] == 'SOURCE_IMPLEMENTATION_DEFECT'
    assert all(term in field['unknown_reason'] for term in ('5日', '10日', 'MA14/28/57/114'))


def test_schema_and_arrow_nulls_survive_original_driver_defaults():
    source = _bars(15)
    frame = append_kb_signals(source)
    old = pa.schema([pa.field('trade_date', pa.string()), pa.field('ts_code', pa.string()), pa.field('user_v1_B1', pa.int8())])
    schema = qfq.kb_schema(old)
    assert schema.names[:len(old)] == old.names
    assert len(schema) == len(old) + 57
    assert not qfq.KB_FIELDS & qfq.LEGACY_AUX_FIELDS

    class Driver:
        @staticmethod
        def build_table_for_schema(data, expected, role):
            arrays=[]
            for field in expected:
                values=data[field.name]
                if field.name in qfq.KB_FIELDS:
                    if pa.types.is_boolean(field.type): values=values.fillna(False)
                    elif pa.types.is_integer(field.type): values=values.fillna(0)
                    elif pa.types.is_string(field.type): values=values.fillna('')
                arrays.append(pa.Array.from_pandas(values,type=field.type))
            return pa.Table.from_arrays(arrays,schema=expected), {}
    table=qfq._table(frame,schema,Driver(),'backtest')
    assert table['kb_b1'][0].as_py() is None
    assert table['kb_b1_score'][0].as_py() is None
    assert table['kb_bull_rope_status'][0].as_py() is None
    assert table['kb_b1'][8].as_py() is True
    assert table['user_v1_B1'].to_pylist() == [0] * 15


def test_identity_binds_authority_and_field_contract(tmp_path):
    dummy = tmp_path/'input'; dummy.write_text('unchanged')
    ident=qfq.generation_identity({'asof_date':20261030},dummy,dummy,dummy)
    root=Path(qfq.__file__).resolve().parents[1]
    assert ident['kb_authority_sha256'] == qfq.sha(root/'ops/kb_signal_authority.py')
    assert ident['kb_field_contract_sha256'] == qfq.sha(root/'contracts/a_share_kb_fields_v1.json')
    assert ident['driver_sha256'] == qfq.sha(dummy)
