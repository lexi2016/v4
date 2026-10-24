"""Actual tiny Parquet -> scan_panel -> NPZ dtype/value preservation only."""
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import long_data194 as data


def test_raw8_real_parquet_cache_preserves_float64_uint64_and_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EXECUTION_ID", "SYNTHETIC_RAW_DTYPE_FIXTURE")
    for label, price_type, volume_type in (("raw8", pa.float64(), pa.uint64()), ("legacy", pa.float32(), pa.float32())):
        root = tmp_path / label
        root.mkdir()
        prices = [11.270000000001, 11.280000000001]
        volumes = [79881986, 2**53 + 1] if label == "raw8" else [float(np.float32(79881986)), 12345.0]
        schema = pa.schema([pa.field("ts_code", pa.string()), pa.field("trade_date", pa.int32()),
                            *(pa.field(name, price_type) for name in ("open", "high", "low", "close", "amount")),
                            pa.field("vol", volume_type)])
        table = pa.Table.from_pydict({"ts_code": ["000001.SZ"] * 2, "trade_date": [20261014, 20261015],
            **{name: prices for name in ("open", "high", "low", "close", "amount")}, "vol": volumes}, schema=schema)
        panel = root / "panel.parquet"
        pq.write_table(table, panel)
        receipt = data.scan_panel(dict(target=panel, initial_panel_stat=data.panel_stat(panel)),
                                  ["000001.SZ", "600519.SH"], root / "cache", root / "SCAN.json", {"fixture": label})
        with np.load(root / "cache/000001_SZ.npz", allow_pickle=False) as cache:
            assert cache["close"].dtype == np.dtype("float64" if label == "raw8" else "float32")
            assert cache["volume"].dtype == np.dtype("uint64" if label == "raw8" else "float32")
            np.testing.assert_array_equal(cache["close"], table.column("close").to_numpy())
            np.testing.assert_array_equal(cache["volume"], table.column("vol").to_numpy())
            if label == "raw8":
                assert int(cache["volume"][1]) == 2**53 + 1
                assert cache["close"][0] != np.float32(cache["close"][0])
                with pytest.raises(ValueError, match="INTEGER_TO_MODEL_FLOAT64_PRECISION_LOSS:volume"):
                    data._model_float64(cache["volume"], "volume")
                assert data._model_float64(cache["volume"][:1], "volume")[0] == 79881986
        with np.load(root / "cache/600519_SH.npz", allow_pickle=False) as empty:
            assert empty["volume"].dtype == np.dtype("uint64" if label == "raw8" else "float32")
            assert len(empty["volume"]) == 0
        assert receipt["pool_rows_retained"] == 2 and receipt["per_code_rows"]["600519.SH"] == 0
