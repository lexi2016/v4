"""New history seams only. Synthetic fixtures; execute after official START."""
from __future__ import annotations

import json
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_adjustment_inputs as inputs
from ops import research_panel_qfq as qfq

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "ops/vendor/data_layer_daily_formula_increment_update_v1.py"
FORMULA = ROOT / "ops/vendor/build_canonical_formula_research_panel.py"


def ref(path):
    return dict(path=str(path), sha256=qfq.sha(path))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return ref(path)


def write_day(path, dates, closes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for index, (date, close) in enumerate(zip(dates, closes)):
            price = round(close * 100)
            handle.write(struct.pack("<IIIIIfII", int(date), price, price + 10, price - 10,
                                     price, float(1000000 + index), 10000 + index, 0))
    return ref(path)


@pytest.fixture
def driver():
    return qfq.authorities(DRIVER, FORMULA)[0]


def test_archive_priority_keeps_whole_row_internal_gap_and_tail(tmp_path, driver):
    archive = write_day(tmp_path / "archive.day", [20010102, 20010104], [10, 12])
    native = write_day(tmp_path / "native.day", [20010102, 20010103, 20010105], [99, 11, 13])
    item = dict(raw_files=[dict(**native, source_role="native"), dict(**archive, source_role="archive")],
                raw_resolution=inputs.HISTORY_RESOLUTION)
    out = qfq.resolved_raw_history("301139.SZ", item, 20010105, driver)
    assert out.trade_date.tolist() == [20010102, 20010103, 20010104, 20010105]
    assert out.close.tolist() == [10, 11, 12, 13]
    assert out.raw_source_role.tolist() == ["archive", "native", "archive", "native"]
    # Conflicting source's amount/volume must not leak into the chosen row.
    assert out.loc[0, "raw_source_ref_sha256"] == archive["sha256"]
    assert out.loc[2, "raw_source_record_index"] == 1
    assert (tmp_path / "native.day").exists()
    with pytest.raises(qfq.QfqGateError, match="RAW_SOURCE_OVERLAP_CONFLICT"):
        qfq.resolved_raw_history("301139.SZ", dict(raw_files=[archive, native]), 20010105, driver)


def test_archive_only_and_unknown_bj_are_discovered_from_bound_membership(tmp_path, monkeypatch):
    raw = write_day(tmp_path / "source.day", [19910102, 19910103], [10, 11])
    archive_path = tmp_path / "original.zip"
    with zipfile.ZipFile(archive_path, "w") as handle:
        handle.write(raw["path"], "bj/lday/bj430047.day")
    source = write_json(tmp_path / "R2.json", dict(source_resolution=inputs.HISTORY_RESOLUTION, stocks=[
        dict(code="430047.BJ", classification="UNKNOWN", sources=[dict(name="archive", kind="archive_member",
             path=str(archive_path), member="bj/lday/bj430047.day", member_sha256=raw["sha256"])])]))
    policy = write_json(tmp_path / "policy.json", dict(name=inputs.HISTORY_RESOLUTION,
        selection_unit="COMPLETE_SOURCE_BAR", price_or_volume_conversion="NONE"))
    config = dict(source_config=source, source_policy=policy, accepted_evidence=[], archive_refs=[ref(archive_path)])
    monkeypatch.setattr(inputs, "existing_day_files", lambda _: [])
    rejects_classification = SimpleNamespace(is_a_bj_ts=lambda _: False)
    result = inputs.raw_bindings(tmp_path / "empty_live", rejects_classification, tmp_path / "isolated/binding.json",
                                 target=20261023, history_extension=config)
    assert set(result) == {"430047.BJ"}
    assert result["430047.BJ"]["compute_start_date"] == 19910102
    original = result["430047.BJ"]["raw_files"][0]["original_ref"]
    assert original["member"] == "bj/lday/bj430047.day"


def test_history_merge_admits_earlier_rows_but_daily_clipping_is_unchanged():
    old = pd.DataFrame(dict(trade_date=[20261022], close=[20.], name=["dated name"], bars_since_list=[44]))
    rebuilt = pd.DataFrame(dict(trade_date=[19910102, 20261022, 20261023], close=[10., 21., 22.],
                                bars_since_list=[None] * 3, name=["current static"] * 3))
    stub = SimpleNamespace(CONTRACT_PROVENANCE_FIELD_DEFAULTS={"field_contract_version": "original"})
    daily = qfq.merge_rebuilt(old, rebuilt, role="selector", driver=stub)
    history = qfq.merge_rebuilt(old, rebuilt, role="selector", driver=stub, history_extension=True)
    assert daily.trade_date.tolist() == [20261022, 20261023]
    assert history.trade_date.tolist() == [19910102, 20261022, 20261023]
    assert history.loc[1, "name"] == "dated name"
    assert history.loc[1, "bars_since_list"] == 44
    assert history.loc[[0, 2], ["name", "bars_since_list"]].isna().all().all()
    with pytest.raises(qfq.QfqGateError, match="RAW_HISTORY_KEYS_MISSING"):
        qfq.merge_rebuilt(old, rebuilt.iloc[:1], role="backtest", driver=stub, history_extension=True)


def test_nullable_context_does_not_become_zero_and_nonnullable_fails(tmp_path):
    class LegacyBuilder:
        def build_table_for_schema(self, frame, schema, role):
            copy = frame.copy()
            copy["bars_since_list"] = copy.bars_since_list.fillna(0)
            return pa.Table.from_pandas(copy, schema=schema, preserve_index=False), {}
    frame = pd.DataFrame(dict(trade_date=[19910102], bars_since_list=[None]))
    schema = pa.schema([pa.field("trade_date", pa.int64()), pa.field("bars_since_list", pa.int64(), nullable=True)])
    out = qfq._table(frame, schema, LegacyBuilder(), "selector", history_extension=True)
    assert out["bars_since_list"].to_pylist() == [None]
    strict = pa.schema([schema[0], pa.field("bars_since_list", pa.int64(), nullable=False)])
    with pytest.raises(qfq.QfqGateError, match="HISTORY_CONTEXT_NOT_NULLABLE"):
        qfq._table(frame, strict, LegacyBuilder(), "selector", history_extension=True)


def test_history_publication_rejected_before_pointer_or_source_access(tmp_path):
    with pytest.raises(qfq.QfqGateError, match="PUBLICATION_FORBIDDEN"):
        qfq.history_extension_binding(dict(path="missing", sha256="missing"), data_root=tmp_path,
                                      return_root=tmp_path, pointers={}, publish=True)


def test_unbound_early_adjustment_coverage_is_gap_without_collection(tmp_path, monkeypatch):
    summary = write_json(tmp_path / "original_sync.json", dict(symbol_reconciliation=[], target_keys=[]))
    metadata = write_json(tmp_path / "metadata.json", dict(symbols={"430047.BJ": dict(status="EMPTY")}))
    monkeypatch.setattr(inputs, "original_sync_contract", lambda *_: (summary, {}, 1))
    monkeypatch.setattr(inputs, "raw_bindings", lambda *a, **k: {"430047.BJ": dict(history_start_date=19910102)})
    def forbidden(*args, **kwargs):
        raise AssertionError("offline history must never collect")
    monkeypatch.setattr(inputs, "collect_metadata", forbidden)
    data = tmp_path / "isolated/data"
    with pytest.raises(qfq.QfqGateError, match="HISTORY_ADJUSTMENT_COVERAGE_INCOMPLETE"):
        inputs.prepare_snapshot(tdx_root=tmp_path / "tdx", data_root=data, target=20261023,
                                driver=None, history_extension=dict(adjustment_metadata=metadata))
    gap = json.loads(qfq.input_path(data).with_name("qfq_input_gaps.json").read_text())
    assert gap["missing"] == [dict(ts_code="430047.BJ", reason="OFFLINE_ADJUSTMENT_HISTORY_COVERAGE_UNBOUND")]


def test_isolated_dual_role_history_preserves_current_keys_sidecars_and_earlier_rows(tmp_path, driver, monkeypatch):
    """Software producer canary: full original formula, no real data or network."""
    dates = pd.bdate_range("2025-01-01", periods=280).strftime("%Y%m%d").astype(int).tolist()
    target = dates[-1]
    symbols, features = {}, []
    for code in ("002612.SZ", "430047.BJ", "603007.SH"):
        raw = write_day(tmp_path / (code + ".day"), dates, 12 + np.arange(len(dates)) / 100)
        item = dict(raw_files=[dict(**raw, source_role="archive")], history_start_date=dates[0], events=[],
            event_coverage_complete=True, publish_roles=["selector", "backtest"], history_extension=True,
            raw_resolution=inputs.HISTORY_RESOLUTION)
        symbols[code] = item
        features.append(qfq.rebuild_symbol(code, item, target, driver))
    full = pd.concat(features, ignore_index=True)
    core = ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pre_close",
            "BBI", "J", "zge_white_line", "zge_yellow_line", "B1", "B2", "B3", "kdj_k", "kdj_d",
            *driver.V192_ENTRY_FIELDS, *driver.V192_INTERMEDIATE_FIELDS, "formula_source"]
    core = list(dict.fromkeys(core + [c for c in driver.CRITICAL_SELECTOR_FORMULA_COLUMNS if c in full]))
    isolation = tmp_path / "isolation"
    data, runs = isolation / "data", isolation / "runs"
    pointers, roles, old_keys, old_bytes = {}, {}, {}, {}
    for role, start in (("selector", 100), ("backtest", 150)):
        # 603007 is archive-only/new relative to both roles. Existing healthy
        # A and BJ members cannot be narrowed by the new source population.
        old = full.loc[full.ts_code.ne("603007.SH") & full.trade_date.ge(dates[start]), core].copy()
        old["name"] = "dated legacy name"
        path = tmp_path / (role + "_baseline.parquet")
        table = pa.Table.from_pandas(old, preserve_index=False).replace_schema_metadata({
            qfq.META_KEY: json.dumps(dict(generation_id="synthetic9ffd", asof_date=target)).encode()})
        pq.write_table(table, path)
        pointer = data / role / "isolated_pointer.txt"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(path))
        pointers[role] = pointer
        old_bytes[role] = pointer.read_bytes()
        old_keys[role] = set(zip(old.ts_code, old.trade_date))
        sidecar = tmp_path / (role + "_sidecar.parquet")
        side = pa.Table.from_pydict(dict(ts_code=["000999.SZ"], trade_date=[19910102])).replace_schema_metadata({
            b"quarantine_contract": json.dumps(dict(generation_id="synthetic9ffd")).encode()})
        pq.write_table(side, sidecar)
        roles[role] = dict(panel=ref(path), sidecars=[ref(sidecar)], **qfq.history_role_identity(path))
    evidence = write_json(tmp_path / "synthetic_evidence.json", dict(software_fixture=True))
    contract = write_json(isolation / "history.json", dict(schema="qfq_shared_history_extension_v1",
        historical_PIT=False, maximum_claim="DIRECTION_ONLY", isolation_root=str(isolation),
        baseline_generation_id="synthetic9ffd", roles=roles, source_policy=evidence, source_config=evidence,
        adjustment_metadata=evidence))
    snapshot = dict(schema="a_share_qfq_adjustment_input_v1", asof_date=target, coverage_end_date=target,
        price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", convention="SOFTWARE_FIXTURE",
        revision="history-fixture", observed_at="2026-10-24T00:00:00+00:00", source_files=[evidence],
        symbols=symbols, history_extension=contract)
    qfq._json(qfq.input_path(data), snapshot)
    monkeypatch.setattr(inputs, "existing_day_files", lambda _: [])
    field_contract = tmp_path / "fields.csv"
    field_contract.write_text("software fixture\n")
    result = qfq.run_daily_rebuild(driver_path=DRIVER, formula_path=FORMULA, tdx_root=tmp_path / "tdx",
        data_root=data, pointers=pointers, contract_csv=field_contract, return_root=runs,
        target=target, workers=1, history_extension=contract)
    assert result["status"] == "CANDIDATE_READY"
    assert result["pit_certified"] is False
    assert result["maximum_claim"] == "DIRECTION_ONLY"
    for role in pointers:
        actual = pq.read_table(result["candidates"][role]).to_pandas()
        keys = set(zip(actual.ts_code, actual.trade_date))
        assert old_keys[role] <= keys
        assert ("603007.SH", dates[0]) in keys
        assert ("430047.BJ", dates[0]) in keys
        assert actual.loc[actual.trade_date.eq(dates[0]), "name"].isna().all()
        assert pointers[role].read_bytes() == old_bytes[role]
        retained = result["inherited_history_sidecars"][role][0]
        assert qfq.sha(Path(retained["retained"]["path"])) == roles[role]["sidecars"][0]["sha256"]
        assert result["counts"][role]["old_key_conservation"] is True
