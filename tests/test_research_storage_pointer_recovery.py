from __future__ import annotations

import base64
import json

import pyarrow as pa
import pytest

from ops import research_panel_logical as logical
from ops import research_panel_qfq as owner
from ops import research_storage_pair as pair
from ops import research_storage_retention as retention


@pytest.fixture
def published_pair(tmp_path, monkeypatch):
    data = tmp_path.resolve()
    root = data / "paired"
    monkeypatch.setenv("V4_STORAGE_PAIR_ROOT", str(root))
    monkeypatch.setenv("V4_STORAGE_PAIR_DATA_ROOT", str(data))
    pointers = pair.pointers(data)
    journal = data / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"

    def generation(name, day):
        directory = data / name
        directory.mkdir()
        receipt = directory / "candidate_receipt.json"
        table = pa.table({"ts_code": ["000001.SZ"], "trade_date": [day]})
        block = directory / "block.parquet"
        logical.physical.write_table(table, block)
        contract = dict(generation_id=name, input_sha256="1" * 64, snapshot_file_sha256="2" * 64,
                        schema="a_share_qfq_panel_v1", asof_date=day, generation_manifest_path=str(receipt))
        schema = table.schema.with_metadata({pair.META: json.dumps(contract).encode()})
        paths = {role: directory / f"{role}.parquet" for role in pointers}
        for path in paths.values():
            path.write_bytes(logical.anchor_bytes(schema, [logical.descriptor(block)], rows=1))
        retention.atomic_json(receipt, dict(generation_id=name, input_sha256="1" * 64,
            candidates={role: str(path) for role, path in paths.items()},
            candidate_sha256={role: retention.digest(path) for role, path in paths.items()}))
        return paths

    older = generation("old", 20261112)
    current = generation("new", 20261113)
    before = {role: (str(path) + "\n").encode() for role, path in older.items()}
    for role, path in pointers.items():
        path.parent.mkdir()
        path.write_bytes(before[role])
    with owner.publication_lock(data):
        owner.publish_pair(pointers, current, before, journal)
        pair.commit(root, data, current, keep_completed=1)
    expected = {role: p.read_bytes() for role, p in pointers.items()}
    return data, root, pointers, journal, expected, older, current


def test_authority_recovers_missing_pointer_without_legacy_seed(published_pair, monkeypatch):
    from ops import macos_research_panel_daily_authority as authority

    data, root, pointers, journal, expected, _, current = published_pair
    journal_preimage = journal.read_bytes()
    pair_preimage = (root / "current.json").read_bytes()
    pointers["selector"].unlink()
    surviving = pointers["backtest"].stat()

    def downstream(rebuild, **kwargs):
        assert rebuild is owner.run_daily_rebuild
        assert kwargs["storage_layout"] == "arrow_blocks_v1"
        assert kwargs["publish"] is True
        assert {role: pointer.read_bytes() for role, pointer in kwargs["pointers"].items()} == expected
        return {**current, "authority": {}, "counts": {}}

    monkeypatch.setattr(retention, "run_with_retention", downstream)
    result = authority.run_windows_a_formula_authority(data / "legacy_driver.py",
        tdx_root=data, data_root=data, selector_pointer=pointers["selector"], backtest_pointer=pointers["backtest"],
        selector_seed=pointers["selector"], backtest_seed=pointers["backtest"],
        contract_csv=data / "contract.csv", canonical_formula_path=data / "formula.py",
        return_root=data / "returns", target_date="20261116")
    assert result["selector"] == str(current["selector"])
    assert pointers["backtest"].stat().st_ino == surviving.st_ino
    assert pointers["backtest"].stat().st_mtime_ns == surviving.st_mtime_ns
    assert journal.read_bytes() == journal_preimage
    assert (root / "current.json").read_bytes() == pair_preimage


@pytest.mark.parametrize("status", ["COMMITTED", "ROLLED_BACK", "ROLLED_BACK_AFTER_INTERRUPTION"])
def test_recover_both_to_exact_terminal_publication(published_pair, status):
    data, root, pointers, journal, expected, older, _ = published_pair
    if status != "COMMITTED":
        record = retention.read_json(journal)
        expected = {role: b"\xef\xbb\xbf" + value for role, value in expected.items()}
        record.update(status=status,
                      before_base64={role: base64.b64encode(value).decode() for role, value in expected.items()},
                      after={role: str(path) + "\n" for role, path in older.items()})
        retention.atomic_json(journal, record)
    journal_preimage = journal.read_bytes()
    pair_preimage = (root / "current.json").read_bytes()
    for path in pointers.values():
        path.unlink()
    assert pair.restore_compatibility_pointers(data, pointers) == {"selector", "backtest"}
    assert {role: path.read_bytes() for role, path in pointers.items()} == expected
    assert pair.restore_compatibility_pointers(data, pointers) == set()
    assert journal.read_bytes() == journal_preimage
    assert (root / "current.json").read_bytes() == pair_preimage


@pytest.mark.parametrize(("fault", "error"), [
    ("no_pair", "MISSING_PATH"),
    ("journal_ahead", "PAIR_RECOVERY_JOURNAL_DRIFT"),
    ("journal_rollback", "PAIR_RECOVERY_JOURNAL_DRIFT"),
    ("journal_prepared", "PAIR_RECOVERY_JOURNAL_NOT_TERMINAL"),
    ("stale_pointer", "PAIR_RECOVERY_POINTER_CONFLICT"),
    ("anchor_drift", "PAIR_BOUND_ARTIFACT_CHANGED"),
    ("pointer_symlink", "SYMLINK_PATH"),
])
def test_recovery_refuses_unverified_inputs(published_pair, fault, error):
    data, root, pointers, journal, _, older, current = published_pair
    pointers["selector"].unlink()
    if fault == "no_pair":
        (root / "current.json").unlink()
    elif fault in {"journal_ahead", "journal_rollback", "journal_prepared"}:
        record = retention.read_json(journal)
        if fault == "journal_ahead":
            record["after"]["selector"] = str(older["selector"]) + "\n"
        else:
            record["status"] = "ROLLED_BACK" if fault == "journal_rollback" else "PREPARED"
        retention.atomic_json(journal, record)
    elif fault == "stale_pointer":
        pointers["backtest"].write_text(str(older["backtest"]) + "\n")
    elif fault == "anchor_drift":
        current["selector"].write_bytes(current["selector"].read_bytes() + b"\n")
    elif fault == "pointer_symlink":
        pointers["selector"].symlink_to(data / "missing")
    surviving = pointers["backtest"].read_bytes()
    with pytest.raises(retention.RetentionError, match=error):
        pair.restore_compatibility_pointers(data, pointers)
    assert not pointers["selector"].exists()
    assert (fault == "pointer_symlink") == pointers["selector"].is_symlink()
    assert pointers["backtest"].read_bytes() == surviving


def test_recovery_honors_qfq_publisher_lock(published_pair):
    data, _, pointers, _, _, _, _ = published_pair
    pointers["selector"].unlink()
    with owner.publication_lock(data):
        with pytest.raises(owner.QfqGateError, match="QFQ_OWNER_ALREADY_ACTIVE"):
            pair.restore_compatibility_pointers(data, pointers)
    assert not pointers["selector"].exists()


def test_exclusive_pointer_publish_preserves_concurrent_bytes(published_pair, monkeypatch):
    data, _, pointers, _, _, _, _ = published_pair
    selector = pointers["selector"]
    selector.unlink()
    original = pair._write_missing_pointer

    def racing_write(pointer, value):
        pointer.write_bytes(b"concurrent writer\n")
        original(pointer, value)

    monkeypatch.setattr(pair, "_write_missing_pointer", racing_write)
    with pytest.raises(retention.RetentionError, match="PAIR_RECOVERY_POINTER_CONFLICT:selector"):
        pair.restore_compatibility_pointers(data, pointers)
    assert selector.read_bytes() == b"concurrent writer\n"
    assert not list(selector.parent.glob(".pointer-recovery-*"))


def test_partial_restore_is_idempotent_after_first_write(published_pair, monkeypatch):
    data, _, pointers, _, expected, _, _ = published_pair
    for pointer in pointers.values():
        pointer.unlink()
    original = pair._write_missing_pointer

    def interrupted_write(pointer, value):
        original(pointer, value)
        raise InterruptedError("first durable pointer written")

    with monkeypatch.context() as simulated:
        simulated.setattr(pair, "_write_missing_pointer", interrupted_write)
        with pytest.raises(InterruptedError):
            pair.restore_compatibility_pointers(data, pointers)
    first = pointers["selector"]
    assert first.read_bytes() == expected["selector"] and first.stat().st_nlink == 1
    assert not pointers["backtest"].exists()
    assert pair.restore_compatibility_pointers(data, pointers) == {"backtest"}
    assert {role: pointer.read_bytes() for role, pointer in pointers.items()} == expected
