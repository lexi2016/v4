from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def reader(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "upstreams/v3_shared_data/shared_data/selector_data_layer_interface.py"
    spec = importlib.util.spec_from_file_location("qfq_selector_reader_test", source)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    monkeypatch.setattr(reader, "POINTER_FILE", tmp_path / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt")
    monkeypatch.setattr(reader._read_pointer, "__defaults__", (reader.POINTER_FILE,))
    return reader


def qfq_panel(tmp_path, reader):
    selector, backtest = tmp_path / "selector.parquet", tmp_path / "backtest.parquet"
    manifest = tmp_path / "generation.json"
    contract = dict(schema="a_share_qfq_panel_v1", price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME",
                    amount_basis="RAW_TURNOVER", generation_id="fixture-generation", input_sha256="1" * 64,
                    snapshot_file_sha256="2" * 64, asof_date=20261023, convention="FIXTURE_PROVIDER_CONVENTION",
                    price_provider="TDX_DAY", adjustment_provider_contract="SH_SZ_FUTU_BJ_TDX", generation_manifest_path=str(manifest))
    frame = pd.DataFrame(dict(ts_code=["001283.SZ"], trade_date=["20261023"], close=[63.06796489999999], volume=[13067464.35562]))
    schema = pa.Table.from_pandas(frame, preserve_index=False).schema.with_metadata({b"a_share_qfq_contract_v1": json.dumps(contract).encode()})
    for path in (selector, backtest):
        pq.write_table(pa.Table.from_pandas(frame, schema=schema, preserve_index=False), path)
    manifest.write_text(json.dumps(dict(**contract, candidates=dict(selector=str(selector), backtest=str(backtest)))))
    pointer = reader.POINTER_FILE
    pointer.parent.mkdir(parents=True)
    pointer.write_text(str(selector))
    backtest_pointer = tmp_path / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
    backtest_pointer.parent.mkdir()
    backtest_pointer.write_text(str(backtest))
    journal = tmp_path / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
    journal.parent.mkdir(parents=True)
    journal.write_text('{"status":"COMMITTED"}')
    return selector, manifest, journal, frame


def test_default_current_reports_actual_qfq_generation_without_network(tmp_path, reader, monkeypatch):
    selector, _, _, expected = qfq_panel(tmp_path, reader)
    def forbidden(*args, **kwargs):
        raise AssertionError("canonical reader must not request quotes or a legacy projection")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(reader, "_load_futu_projection_module", forbidden)
    meta = reader.get_panel_meta(include_dates=False)
    assert meta["price_basis"] == "QFQ_ASOF"
    assert meta["price_adjustment_asof"] == "20261023"
    assert meta["price_provider"] == "TDX_DAY"
    assert meta["historical_pit_certified"] is False
    actual = reader.load_selector_ready()
    pd.testing.assert_frame_equal(actual, expected)
    assert actual.attrs["panel_metadata"]["generation_id"] == "fixture-generation"
    assert str(selector) == meta["panel_path"]


def test_explicit_raw_never_returns_current_qfq_or_uncertified_prices(tmp_path, reader):
    qfq_panel(tmp_path, reader)
    with pytest.raises(ValueError, match="RAW_PROFILE_NOT_AVAILABLE_FOR_CURRENT_BASIS"):
        reader.load_selector_ready(profile="RAW")
    with pytest.raises(ValueError, match="RAW_PROFILE_NOT_AVAILABLE_FOR_CURRENT_BASIS"):
        reader.get_panel_meta(include_dates=False, profile="RAW")
    legacy = tmp_path / "legacy.parquet"
    pd.DataFrame(dict(ts_code=["001283.SZ"], trade_date=["20261023"], close=[64.])).to_parquet(legacy)
    meta = reader.get_panel_meta(panel_path=legacy, include_dates=False)
    assert meta["price_basis"] == "UNKNOWN_UNCERTIFIED"
    with pytest.raises(ValueError, match="UNKNOWN_UNCERTIFIED"):
        reader.load_selector_ready(panel_path=legacy, profile="RAW")


def test_manifest_conflict_pending_pair_and_safe_rollback_are_distinct(tmp_path, reader):
    selector, manifest, journal, _ = qfq_panel(tmp_path, reader)
    journal.write_text('{"status":"PREPARED"}')
    with pytest.raises(RuntimeError, match="paired CURRENT"):
        reader.load_selector_ready()
    journal.write_text('{"status":"ROLLED_BACK"}')
    assert reader.get_panel_meta(include_dates=False)["price_basis"] == "QFQ_ASOF"
    value = json.loads(manifest.read_text())
    value["generation_id"] = "wrong-generation"
    manifest.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="generation identity conflict"):
        reader.get_panel_meta(include_dates=False)


def test_explicit_legacy_two_stock_profile_retains_source_sha_failure(tmp_path, reader, monkeypatch):
    qfq_panel(tmp_path, reader)
    def denied(*args, **kwargs):
        raise RuntimeError("SOURCE_PANEL_SHA256_MISMATCH")
    monkeypatch.setattr(reader, "_load_futu_projection_module", lambda: SimpleNamespace(validate_profile_for_panel=denied))
    with pytest.raises(RuntimeError, match="SOURCE_PANEL_SHA256_MISMATCH"):
        reader.load_selector_ready(profile="FUTU_QFQ_ASOF", asof="20261023")
