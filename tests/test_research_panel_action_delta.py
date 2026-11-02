import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_action_delta as delta
from ops import research_panel_qfq as q


def _fixture(tmp_path):
    rows = []
    for code, date, sell in [('000001.SZ', 20261029, 1.0), ('000001.SZ', 20261030, 0.0),
                             ('00085.HK', 20261030, None)]:
        row = {name: None for name in q.SINGLE_ACTION_INPUTS}
        row.update(ts_code=code, trade_date=date, user_v1_sell_signal_daily=sell,
            kb_b1=False, kb_b2=False, kb_b3=False, kb_white_cross_down=False,
            kb_macd_veto=False, kb_brick_flip_green=False, kb_bull_rope_status='牵牛',
            kb_brick_action='持有', kb_hold_score_min=4, kb_hold_score_max=5)
        row.update(kb_action_no_position='等回调', kb_action_no_position_status='OBSERVED_NO_BUY_SIGNAL',
            kb_action_with_position='持有', kb_action_with_position_status='OBSERVED_SCORE_HOLD_CONDITIONAL',
            kb_action_reasons='old', kb_action_rule_sha256='rule', retained=float('nan'))
        rows.append(row)
    frame = pa.Table.from_pylist(rows)
    source = frame.slice(0, 1)
    columns = {'ts_code': source['ts_code'], 'trade_date': source['trade_date']}
    for field in q.SINGLE_ACTION_INPUTS:
        columns['input__' + field] = source[field]
    for field in delta.ACTION_FIELDS:
        columns['old__' + field] = source[field]
        value = 'CONFLICTING_OBSERVATIONS' if field == 'kb_action_with_position_status' else 'new' if field == 'kb_action_reasons' else source[field][0].as_py()
        columns['new__' + field] = pa.array([value], type=pa.string())
    overlay = pa.table(columns).replace_schema_metadata({b'scope': b'ACTION_DELTA_NOT_A_PANEL',
        b'old_candidate_generation': b'oldgen', b'old_action_authority_sha256': b'oldauth',
        b'new_action_authority_sha256': b'newauth'})
    path = tmp_path / 'delta.parquet'; pq.write_table(overlay, path)
    index = {'000001.SZ': {'affected_rows': 1, 'overlay': {'path': str(path), 'sha256': q.sha(path)}}}
    def applier():
        return delta.DeltaApplier(index, q=q, old_generation='oldgen', old_authority='oldauth',
                                  new_authority='newauth', expected_rows=1)
    return frame.to_batches()[0], applier


def test_only_action_values_change_and_unchanged_columns_keep_null_and_nan(tmp_path):
    before, create = _fixture(tmp_path); a = create(); after = a.apply(before)
    assert a.finish() == {'applied_rows': 1, 'affected_stocks': 1}
    assert after.column(after.schema.get_field_index('kb_action_with_position_status')).to_pylist() == [
        'CONFLICTING_OBSERVATIONS', 'OBSERVED_SCORE_HOLD_CONDITIONAL', 'OBSERVED_SCORE_HOLD_CONDITIONAL']
    assert after.column(after.schema.get_field_index('kb_action_reasons')).to_pylist() == ['new', 'old', 'old']
    for field in set(before.schema.names) - set(delta.ACTION_FIELDS):
        assert delta.exact_values(before.column(before.schema.get_field_index(field)),
                                  after.column(after.schema.get_field_index(field)))


def test_wrong_input_old_value_duplicate_and_missing_keys_fail_closed(tmp_path):
    batch, create = _fixture(tmp_path)
    pos = batch.schema.get_field_index('user_v1_sell_signal_daily')
    wrong_input = batch.set_column(pos, batch.schema.field(pos), pa.array([0.0, 0.0, None]))
    with pytest.raises(q.QfqGateError, match='ACTION_DELTA_INPUT_MISMATCH'):
        create().apply(wrong_input)
    pos = batch.schema.get_field_index('kb_action_reasons')
    wrong_old = batch.set_column(pos, batch.schema.field(pos), pa.array(['different', 'old', 'old']))
    with pytest.raises(q.QfqGateError, match='ACTION_DELTA_OLD_VALUE_MISMATCH'):
        create().apply(wrong_old)
    applier = create(); applier.apply(batch)
    with pytest.raises(q.QfqGateError, match='ACTION_DELTA_DUPLICATE_KEY'):
        applier.apply(batch)
    with pytest.raises(q.QfqGateError, match='ACTION_DELTA_MISSING_KEYS'):
        create().finish()


def test_exact_values_distinguishes_null_nan_and_signed_zero():
    assert delta.exact_values(pa.array([None, float('nan'), -0.0]), pa.array([None, float('nan'), -0.0]))
    assert not delta.exact_values(pa.array([None, float('nan')]), pa.array([float('nan'), None]))
    assert not delta.exact_values(pa.array([-0.0]), pa.array([0.0]))
    left=pa.DictionaryArray.from_arrays(pa.array([0,1],type=pa.int8()),pa.array(['a','b']))
    right=pa.DictionaryArray.from_arrays(pa.array([1,0],type=pa.int8()),pa.array(['b','a']))
    assert delta.exact_values(left,right)


def test_role_write_and_disk_readback_preserve_non_action_fields(tmp_path):
    batch, create = _fixture(tmp_path)
    source, target = tmp_path / 'old.parquet', tmp_path / 'new.parquet'
    pq.write_table(pa.Table.from_batches([batch]), source, row_group_size=2)
    budget_calls = []
    written = delta.write_role(source, target, batch.schema, create(), budget=lambda: budget_calls.append(1))
    proof = delta.verify_role(source, target, create())
    assert written['rows'] == proof['rows'] == 3
    assert proof['status'] == 'PASS' and proof['applied_rows'] == 1 and len(budget_calls) == 3
    bad = pq.read_table(target)
    position = bad.schema.get_field_index('retained')
    bad = bad.set_column(position, 'retained', pa.array([0.0, float('nan'), float('nan')]))
    pq.write_table(bad, tmp_path / 'bad.parquet', row_group_size=2)
    with pytest.raises(q.QfqGateError, match='ACTION_DELTA_READBACK_VALUE:0:retained'):
        delta.verify_role(source, tmp_path / 'bad.parquet', create())
