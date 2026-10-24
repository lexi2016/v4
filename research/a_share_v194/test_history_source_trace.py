"""New trace boundary: reuse conflicting rows without inventing values."""
import pytest

import history_source_trace as trace


def row(left, right, left_value, right_value):
    return dict(code="000001.SZ", trade_date="20260819", left=left, right=right,
                **{"left_" + field: left_value for field in trace.FIELDS},
                **{"right_" + field: right_value for field in trace.FIELDS})


def test_trace_preserves_csv_strings_and_rejects_inconsistent_source_values():
    key = ("000001.SZ", 20260819)
    rows = [row("archive", "native", "11.27", "11.27"),
            row("native", "backtest", "11.27", "14.739999771118164")]
    values = trace.reused_comparisons(rows, {key})
    assert values[key]["backtest"]["close"] == "14.739999771118164"
    assert values[key]["archive"]["close"] == "11.27"
    with pytest.raises(ValueError, match="REUSED_PAIR_VALUES_DISAGREE"):
        trace.reused_comparisons(rows + [row("native", "selector", "99.0", "14.74")], {key})
    with pytest.raises(ValueError, match="TRACE_KEY_NOT_IN_REVIEWED_CONFLICT_ARTIFACT"):
        trace.reused_comparisons(rows, {key, ("000001.SZ", 20260722)})


def test_r2_typed_date_filter_runs_actual_arrow_dataset_for_int32_int64_string_and_rejects_float(tmp_path):
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq

    for dtype in (pa.int32(), pa.int64(), pa.string(), pa.float64()):
        path = tmp_path / (str(dtype) + ".parquet")
        dates = ["20260818", "20260819"] if pa.types.is_string(dtype) else [20260818, 20260819]
        table = pa.table({"ts_code": ["000001.SZ", "000001.SZ"],
                          "trade_date": pa.array(dates, type=dtype), "close": [11.0, 11.27]})
        pq.write_table(table, path)
        dataset = ds.dataset(path, format="parquet")
        if pa.types.is_floating(dtype):
            with pytest.raises(ValueError, match="TRACE_UNSUPPORTED_DATE_TYPE"):
                trace.read_panel_exact(dataset, table.schema, "000001.SZ", {20260819},
                                       table.schema.names, "YYYYMMDD")
        else:
            result = trace.read_panel_exact(dataset, table.schema, "000001.SZ", {20260819},
                                            table.schema.names, "YYYYMMDD")
            assert result.num_rows == 1
            assert result.column("close").to_pylist() == [11.27]
            assert result.schema.field("trade_date").type == dtype
