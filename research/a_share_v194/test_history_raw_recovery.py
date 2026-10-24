"""Only R2 missing-bar selection, compatibility reuse and launch evidence."""
from concurrent.futures import Future
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops import a_share_history_backfill as backfill


def bar(day, value=10, volume=79881986):
    return dict(ts_code="301139.SZ", trade_date=day, open=value, high=value + 2,
                low=value - 1, close=value + 1, amount=123456.125, vol=volume)


def policy_file(path, name):
    value = dict(status="FROZEN_BY_ROOT", name=name, price_or_volume_conversion="NONE",
                 selection_unit="COMPLETE_SOURCE_BAR",
                 conflict_action="KEEP_ALL_SOURCE_BYTES_AND_VALUES_SELECT_FROZEN_PRIORITY")
    backfill.save(path, value)
    return dict(path=str(path), sha256=backfill.sha(path))


def test_recovery_native_internal_gap_is_complete_original_bar():
    archive = [bar(20260828), bar(20260903)]
    native = [bar(20260828, 90), bar(20260831, 20), bar(20260904, 30)]
    selected, conflicts, provenance, gaps = backfill.resolved_rows(
        dict(archive=archive, native=native), dict(name="ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"), "301139.SZ", 20261023)
    assert selected == [archive[0], native[1], archive[1], native[2]]
    assert gaps == [] and conflicts[0]["source_values"]["archive"]["close"] == archive[0]["close"]
    assert provenance[1] == dict(code="301139.SZ", trade_date=20260831, selected_source="native",
                                disposition="NATIVE_INTERNAL_ARCHIVE_GAP_FILL")
    assert provenance[-1]["disposition"] == "NATIVE_TAIL_AFTER_ARCHIVE_LAST"
    bad = {**native[1], "high": 1}
    with pytest.raises(ValueError, match="SELECTED_SOURCE_BAR_INVALID"):
        backfill.resolved_rows(dict(archive=archive, native=[bad]),
                               dict(name="ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"), "301139.SZ", 20261023)
    assert backfill.resolved_rows(dict(archive=[], native=[]),
        dict(name="ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"), "301139.SZ", 20261023)[-1]


def test_recovery_zero_gap_checkpoint_compatibility_and_source_drift(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    previous_policy = policy_file(tmp_path / "old_policy.json", "ARCHIVE_PRIMARY_NATIVE_TAIL_V1")
    current_policy = policy_file(tmp_path / "new_policy.json", "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2")
    helper = tmp_path / "old_helper.py"
    helper.write_bytes(b"accepted immutable previous helper")
    original = tmp_path / "captured.day"
    original.write_bytes(b"same original raw bytes")
    binding = dict(name="archive", kind="day_bytes", path=str(original), sha256=backfill.sha(original))
    stock = dict(code="301139.SZ", sources=[binding])
    config = dict(stage="RAW_PROJECTION", last_panel_date=20261023, checkpoint_root=str(tmp_path / "checkpoints"),
                  resolution_policy=current_policy, compatibility_previous_policy=previous_policy,
                  compatibility_previous_helper=dict(path=str(helper), sha256=backfill.sha(helper)))
    identity = backfill.stock_identity(stock, config)
    previous_identity = {**identity, "helper_sha256": backfill.sha(helper),
                         "sources": {**identity["sources"], "resolution_policy": previous_policy}}
    old = Path(config["checkpoint_root"]) / stock["code"] / backfill.digest(previous_identity)
    old.mkdir(parents=True)
    backfill.save(old / "SOURCE_COVERAGE_GAPS.json", [])
    backfill.save(old / "SELECTED_BAR_PROVENANCE.json", [dict(code=stock["code"], trade_date=20261019, selected_source="archive")])
    (old / "original_source_bytes").mkdir()
    (old / "original_source_bytes/archive.day").write_bytes(original.read_bytes())
    pq.write_table(pa.Table.from_pylist([bar(20261019)], schema=backfill.raw_schema()), old / "backtest_stock.parquet")
    files = {name: backfill.sha(old / name) for name in ("SOURCE_COVERAGE_GAPS.json", "SELECTED_BAR_PROVENANCE.json",
                                                       "original_source_bytes/archive.day", "backtest_stock.parquet")}
    receipt = dict(identity=previous_identity, code=stock["code"], files=files, rows=1,
                   source_receipts=[dict(name="archive", binding=binding, invalid_ohlc_rows=0)],
                   source_resolution_policy=backfill.load(previous_policy["path"]), worker_peak_rss_bytes=100,
                   formula_evaluations=0, model_fits=0, labels_computed=0, pointer_writes=0)
    backfill.save(old / "STOCK_CHECKPOINT.json", receipt)
    before = backfill.sha(old / "STOCK_CHECKPOINT.json")
    config["compatibility_checkpoints"] = {stock["code"]: dict(directory=str(old), receipt_sha256=before)}
    monkeypatch.setattr(backfill, "runtime_adapter", lambda config: None)
    monkeypatch.setattr(backfill, "read_sources", lambda *args: pytest.fail("reused stock raw sources were decoded again"))
    monkeypatch.setattr(backfill, "materialize_rows", lambda *args: pytest.fail("reused stock rows were recomputed"))
    result = backfill.process_stock(stock, config)
    new = Path(result["checkpoint"])
    assert result["reused"] and result["compatibility_reused"] and new != old
    assert backfill.sha(new / "backtest_stock.parquet") == files["backtest_stock.parquet"]
    assert backfill.sha(old / "STOCK_CHECKPOINT.json") == before
    proof = backfill.load(new / "COMPATIBILITY_REUSE.json")
    assert proof["status"] == "REUSED_NOT_RECOMPUTED" and proof["raw_rows_recomputed"] == 0
    assert backfill.load(new / "SELECTED_BAR_PROVENANCE.json")[0]["disposition"] == "ARCHIVE_PRIMARY"
    changed = tmp_path / "changed.day"
    changed.write_bytes(b"different valid source identity")
    with pytest.raises(ValueError, match="COMPATIBILITY_SOURCE_IDENTITY_DRIFT"):
        backfill.process_stock({**stock, "sources": [{**binding, "path": str(changed), "sha256": backfill.sha(changed)}]}, config)


def test_recovery_failed_stock_captured_bytes_reused_without_archive_reopen(tmp_path, monkeypatch):
    archive = tmp_path / "old.zip"
    archive.write_bytes(b"not reopened by this fixture")
    captured = tmp_path / "archive.day"
    captured.write_bytes(b"already captured immutable member bytes")
    ref = dict(path=str(captured), sha256=backfill.sha(captured))
    stock = dict(code="301139.SZ", sources=[dict(name="archive", kind="archive_member", path=str(archive),
                 stat=backfill.stat(archive), member="301139.day", member_sha256=ref["sha256"])])
    probe = SimpleNamespace(decode_day=lambda payload, code: [bar(20260828)], coverage=lambda rows: dict(rows=len(rows), invalid_ohlc_rows=0))
    monkeypatch.setattr(backfill, "source_module", lambda *args: probe)
    monkeypatch.setattr(backfill.zipfile, "ZipFile", lambda *args: pytest.fail("archive was reopened"))
    config = dict(source_probe={}, source_payload_cache={stock["code"]: {"archive": ref}})
    values, receipts = backfill.read_sources(stock, config, tmp_path / "new_evidence")
    assert values["archive"] == [bar(20260828)]
    assert receipts[0]["binding"] == stock["sources"][0] and receipts[0]["payload_reuse_binding"] == ref
    captured.write_bytes(b"drift")
    with pytest.raises(ValueError, match="BOUND_SHA_DRIFT"):
        backfill.read_sources(stock, config, tmp_path / "rejected")


def test_recovery_actual_selection_header_survives_worker_failure(tmp_path, monkeypatch):
    policy = policy_file(tmp_path / "policy.json", "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2")
    profile = tmp_path / "profile.json"
    backfill.save(profile, dict(status="ISOLATED_RAW_HISTORY_STAGING_READY_FOR_REVIEW", maximum_worker_peak_rss_bytes=140591104))
    selection = dict(requested_workers=12, actual_workers=2, available_memory_bytes=600000000)
    adapter = SimpleNamespace(select_safe_fit_workers=lambda **kwargs: selection,
                              runtime_snapshot=lambda: dict(available_memory_bytes=600000000))
    monkeypatch.setattr(backfill, "runtime_adapter", lambda config: adapter)
    class Pool:
        def __init__(self, **kwargs):
            assert kwargs["max_workers"] == 2
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def submit(self, *args):
            future = Future()
            future.set_exception(ValueError("EXPECTED_WORKER_FAILURE"))
            return future
    monkeypatch.setattr(backfill, "ProcessPoolExecutor", Pool)
    config = dict(schema="V194_EXISTING_PRODUCER_HISTORY_BACKFILL_V1", safety_flags=backfill.FLAGS,
                  status="FROZEN_READY_FOR_REGISTERED_CANARY", code_bindings=[], mode="full", stage="RAW_PROJECTION",
                  last_panel_date=20261023, latest_training_target_date=20261022, resolution_policy=policy,
                  stocks=[dict(code="301139.SZ")], protected_pointers=[],
                  runtime=dict(requested_workers=12, total_thread_budget=12, memory_safety_fraction=.5),
                  worker_resource_profile=dict(path=str(profile), sha256=backfill.sha(profile)), output_dir=str(tmp_path / "run"))
    path = tmp_path / "config.json"
    backfill.save(path, config)
    with pytest.raises(ValueError, match="EXPECTED_WORKER_FAILURE"):
        backfill.run_config(path, backfill.sha(path))
    header = backfill.load(tmp_path / "run/LAUNCH_RESOURCE_HEADER.json")
    assert header["actual_workers"] == 2 and header["worker_selection"] == selection
    assert header["runtime_snapshot"]["available_memory_bytes"] == 600000000
