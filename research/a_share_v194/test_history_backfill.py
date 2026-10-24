"""Only new isolated-ops routing, source selection and checkpoint boundaries."""
import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))
from ops import a_share_daily_sync as entry
from ops import a_share_history_backfill as backfill


def bar(day, value):
    return dict(ts_code="000001.SZ", trade_date=day, **{field: value for field in backfill.RAW})


def test_backfill_cli_routes_without_network_and_blocks_unbound_full_qfq(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(entry, "run", lambda _args: pytest.fail("network daily sync was entered"))
    monkeypatch.setattr(backfill, "run_config", lambda path, value: seen.append((path, value)) or {})
    assert entry.main(["--history-backfill-config", str(tmp_path / "config.json"),
                       "--history-backfill-config-sha256", "a" * 64]) == 0
    assert seen == [(tmp_path / "config.json", "a" * 64)]
    with pytest.raises(SystemExit):
        entry.parse_args([])
    monkeypatch.undo()
    config = tmp_path / "full.json"
    config.write_text(json.dumps(dict(schema="V194_EXISTING_PRODUCER_HISTORY_BACKFILL_V1",
                                     safety_flags=backfill.FLAGS, mode="full",
                                     status="FROZEN_READY_FOR_REGISTERED_CANARY", code_bindings=[])))
    with pytest.raises(ValueError, match="FULL_HISTORY_REQUIRES_SEPARATELY_VERIFIED_SHARED_QFQ"):
        backfill.run_config(config, backfill.sha(config))


def test_backfill_archive_primary_complete_bars_tail_and_gap_report():
    policy = dict(name="ARCHIVE_PRIMARY_NATIVE_TAIL_V1")
    archive = [bar(20261016, 10), bar(20261019, 11)]
    native = [bar(20261015, 900), bar(20261016, 901), bar(20261020, 12)]
    selected, conflicts, provenance, gaps = backfill.resolved_rows(
        dict(archive=archive, native=native), policy, "000001.SZ", 20261023)
    assert selected == archive + [native[-1]]
    assert conflicts[0]["source_values"]["native"]["vol"] == 901
    assert conflicts[0]["source_values"]["archive"]["vol"] == 10
    assert [row["selected_source"] for row in provenance] == ["archive", "archive", "native"]
    assert gaps[0]["trade_date"] == 20261015


def test_backfill_explicit_nullable_is_null_and_undeclared_missing_field_stops():
    import pandas as pd
    import pyarrow as pa

    class PureProducer:
        def compute_formula_features(self, frame, cutoff, static, logger, *, emit_all_rows, xdxr_events):
            assert emit_all_rows is True and static == {} and cutoff == 0
            return frame.copy()

        def append_backtest_provenance_and_tradeability(self, frame, path):
            return frame

        def build_table_for_schema(self, frame, schema, role):
            # The real inherited integer coercer can fill None with zero.
            # The explicit-null contract must override that behavior.
            values = {name: frame[name].fillna(0).tolist() for name in schema.names}
            return pa.Table.from_pydict(values, schema=schema), dict(default_filled_columns_count=0)

    schema = pa.schema([pa.field("close", pa.float32()), pa.field("legacy_meta", pa.int8(), nullable=True)])
    config = dict(schema_source=dict(path="frozen.parquet"), schema_restoration=None,
                  nullable_historical_fields=dict(legacy_meta="No source-bound historical definition; not consumed by model"))
    table, info = backfill.rebuild_table([bar(20261019, 12)], config, PureProducer(), schema, None, backfill.Logger())
    assert table.column("close").to_pylist() == [12.0]
    assert table.column("legacy_meta").to_pylist() == [None]
    assert info["null_rows_by_column"]["legacy_meta"] == 1
    with pytest.raises(ValueError, match="BACKTEST_FIELDS_NOT_COMPUTED:legacy_meta"):
        backfill.rebuild_table([bar(20261019, 12)], {**config, "nullable_historical_fields": {}},
                              PureProducer(), schema, None, backfill.Logger())


def test_backfill_checkpoint_reuse_requires_identity_and_all_artifact_hashes(tmp_path):
    original = tmp_path / "original_source_bytes"
    original.mkdir()
    raw = original / "archive.day"
    raw.write_bytes(b"preserved-byte-evidence")
    identity = dict(input_sha256="bound-source-hash")
    receipt = dict(identity=identity, files={"original_source_bytes/archive.day": backfill.sha(raw)})
    backfill.save(tmp_path / "STOCK_CHECKPOINT.json", receipt)
    assert backfill.verify_checkpoint(tmp_path, identity) == receipt
    with pytest.raises(ValueError, match="STOCK_CHECKPOINT_IDENTITY_DRIFT"):
        backfill.verify_checkpoint(tmp_path, dict(input_sha256="changed-source-hash"))
    raw.write_bytes(b"changed")
    with pytest.raises(ValueError, match="STOCK_CHECKPOINT_ARTIFACT_DRIFT"):
        backfill.verify_checkpoint(tmp_path, identity)


def test_backfill_raw_projection_never_calls_formula_or_qfq_and_preserves_uint(monkeypatch):
    monkeypatch.setattr(backfill, "producer_module", lambda _config: pytest.fail("formula producer was called"))
    monkeypatch.setattr(backfill, "rebuild_table", lambda *_args: pytest.fail("formula rebuild was called"))
    rows = [bar(20261019, 11.27)]
    rows[0]["vol"] = 79881986
    table, info = backfill.materialize_rows(rows, dict(stage="RAW_PROJECTION"), backfill.Logger())
    assert table.column("vol").to_pylist() == [79881986]
    assert str(table.schema.field("vol").type) == "uint64"
    assert table.column("close").to_pylist() == [11.27]
    assert len(table.schema.names) == 8
    assert info["price_or_volume_conversion"] == "NONE"
