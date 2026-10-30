"""Cached metadata retains the original selector query and stock validation."""
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from ops import research_panel_daily_product as product


class OriginalQuery:
    def __init__(self):
        self.calls = 0
        self.allow = True

    def load_selector_ready(self, *, columns, filters, panel_path, profile):
        self.calls += 1
        assert profile is None
        if not self.allow:
            raise RuntimeError("original paired basis guard failed")
        return pd.read_parquet(panel_path, columns=list(dict.fromkeys(["trade_date", "ts_code", *columns])), filters=filters).reset_index(drop=True)


def make_context(tmp_path, *, duplicate=False, price_type=pa.float64(), date_type=pa.string()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    pointer = data / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"
    backpointer = data / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
    panel = tmp_path / "selector.parquet"
    back = tmp_path / "backtest.parquet"
    rows = [("000001.SZ", "20261028", "旧名", "SZ"), ("000001.SZ", "20261030", "新名", "SZ"),
            ("000001.SZ", "20261031", "未来不读", "SZ"), ("600001.SH", "20261029", "甲", "SH"),
            ("600001.SH", "20261030", " ", "SH")]
    if duplicate:
        rows.append(rows[1])
    values = dict(ts_code=pa.array([r[0] for r in rows]), trade_date=pa.array([r[1] for r in rows], type=date_type),
        name=pa.array([r[2] for r in rows]), market_type=pa.array(["A_SHARE"] * len(rows)), exchange=pa.array([r[3] for r in rows]))
    for column in ("open", "high", "low", "close", "volume"):
        values[column] = pa.array([float(i + 10) for i in range(len(rows))], type=price_type)
    pq.write_table(pa.table(values), panel, row_group_size=2)
    back.write_bytes(b"original backtest binding")
    for p, target in ((pointer, panel), (backpointer, back)):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(target) + "\n")
    journal = data / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps(dict(status="COMMITTED")))
    receipt = tmp_path / "candidate_receipt.json"
    receipt.write_text("original generation manifest")
    reader_file = tmp_path / "reader.py"
    reader_file.write_text("# unchanged original reader identity")
    context = product.SourceContext.__new__(product.SourceContext)
    context.data_root, context.target, context.panel = data, 20261030, panel
    context.pointer, context.backpointer = pointer, backpointer
    context.pointer_bytes, context.back_bytes = pointer.read_bytes(), backpointer.read_bytes()
    context.panel_stat = panel.stat()
    context.receipt_ref, context.reader_ref = product.reference(receipt), product.reference(reader_file)
    context.reader = OriginalQuery()
    return context


@pytest.mark.parametrize("price_type", [pa.float32(), pa.float64()])
@pytest.mark.parametrize("date_type", [pa.string(), pa.large_string()])
def test_original_values_dtypes_dates_and_filters_reused(tmp_path, monkeypatch, price_type, date_type):
    context = make_context(tmp_path, price_type=price_type, date_type=date_type)
    datasets = []
    original = ds.dataset
    def create(*args, **options):
        datasets.append(args)
        return original(*args, **options)
    monkeypatch.setattr(ds, "dataset", create)
    # First empty read still passes the original profile/basis reader guard.
    assert context.read("000016.SZ") == ([], None)
    for code in ("000001.SZ", "600001.SH", "000001.SZ"):
        columns = ["ts_code", "trade_date", "name", "market_type", "exchange", "open", "high", "low", "close", "volume"]
        expected = OriginalQuery().load_selector_ready(columns=columns,
            filters=[("ts_code", "=", code), ("trade_date", "<=", "20261030")], panel_path=context.panel, profile=None)
        actual = context._read_frame(code)
        pd.testing.assert_frame_equal(actual, expected, check_dtype=True, check_exact=True)
        bars, name = context.read(code)
        assert [b["trade_date"] for b in bars] == [int(d) for d in expected.trade_date]
        assert all(b["trade_date"] <= 20261030 for b in bars)
        assert name == ("新名" if code == "000001.SZ" else "甲")
    assert context.reader.calls == 1 and len(datasets) == 1


def test_original_duplicate_validation_retained_after_cache_warmup(tmp_path):
    context = make_context(tmp_path, duplicate=True)
    assert context.read("000016.SZ") == ([], None)
    with pytest.raises(ValueError, match="DAILY_SYMBOL_PREFIX_CONFLICT"):
        context.read("000001.SZ")


def test_original_basis_guard_must_pass_before_cache_creation(tmp_path):
    context = make_context(tmp_path)
    context.reader.allow = False
    with pytest.raises(RuntimeError, match="original paired basis guard failed"):
        context.read("000001.SZ")
    assert not hasattr(context, "_selector_read_cache")


@pytest.mark.parametrize("changed", ["selector", "backtest", "manifest", "reader", "journal", "selector_pointer", "backtest_pointer"])
def test_changed_original_binding_never_uses_cached_metadata(tmp_path, changed):
    context = make_context(tmp_path)
    context.read("000016.SZ")
    cache = context._selector_read_cache
    paths = dict(selector=context.panel, backtest=Path(context.back_bytes.decode().strip()),
        manifest=Path(context.receipt_ref["path"]), reader=Path(context.reader_ref["path"]), journal=cache["journal"],
        selector_pointer=context.pointer, backtest_pointer=context.backpointer)
    with paths[changed].open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="DAILY_(GENERATION_CHANGED|READ_BINDING_CHANGED|READ_PUBLICATION_JOURNAL_CHANGED)"):
        context.read("000001.SZ")
