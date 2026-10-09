"""Synthetic exact-source preparation tests, never evidence of real October 9 readiness."""
import inspect
import json
from datetime import datetime

import pytest

from hk_prepare_support import (
    SyntheticStoreError, file_bytes, load_ensure, load_master, publish, rows, sha256_json,
)


@pytest.fixture(params=["actual", "canonical"])
def owner(request):
    return request.param


def restore(master, source, target):
    action = getattr(master, "restore_verified_hk_security_master", None)
    assert callable(action), "actual owner lacks its existing canonical exact-source restore path"
    return action(source, target, trade_date="20261008")


def test_missing_exact_entry_names_date_without_falling_back(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    publish(master, tmp_path, trade_date="20260930", captured_at="2026-09-30T17:30:00+08:00")
    before = file_bytes(tmp_path)
    with pytest.raises(SyntheticStoreError, match="HK_SECURITY_MASTER_EXACT_DATE_MISSING.*20261008.*20260930"):
        master.load_verified_hk_security_master(tmp_path, "20261008")
    assert file_bytes(tmp_path) == before


def test_exact_restore_preserves_trio_bytes_other_dates_and_source(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    expected = publish(master, source)
    publish(master, target, trade_date="20260930", captured_at="2026-09-30T17:30:00+08:00")
    source_before, target_before = file_bytes(source), file_bytes(target)
    outcome = restore(master, source, target)
    values, manifest = master.load_verified_hk_security_master(target, "20261008")
    assert outcome["status"] == "READY"
    assert manifest == expected["manifest"]
    assert values["HK.00001"]["captured_at"] == "2026-10-08T17:30:00+08:00"
    assert file_bytes(source) == source_before
    for relative, encoded in source_before.items():
        if "/runs/" in relative:
            assert (target / relative).read_bytes() == encoded
    for relative, encoded in target_before.items():
        if "/runs/" in relative:
            assert (target / relative).read_bytes() == encoded
    assert set(json.loads((target / "assets/hk_security_master/latest.json").read_text())["entries"]) == {"20260930", "20261008"}


def test_restore_same_root_and_repeated_copy_are_idempotent(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    source_before = file_bytes(source)
    assert restore(master, source, source)["already_exists"] is True
    assert file_bytes(source) == source_before
    restore(master, source, target)
    before = file_bytes(target)
    assert restore(master, source, target)["already_exists"] is True
    assert file_bytes(target) == before


def test_corrupt_source_cannot_write_target(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    data = publish(master, source)
    artifact = source / "assets/hk_security_master" / data["manifest"]["artifact_relative"]
    artifact.write_bytes(artifact.read_bytes() + b"CORRUPTED\n")
    with pytest.raises(SyntheticStoreError, match="checksum"):
        restore(master, source, target)
    assert not target.exists()


def test_restore_does_not_overwrite_different_target_run(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    publish(master, target, name="OTHER SYNTHETIC MASTER")
    before = file_bytes(target)
    with pytest.raises(SyntheticStoreError, match="different run"):
        restore(master, source, target)
    assert file_bytes(target) == before


@pytest.mark.parametrize("capture", ["2026-10-09T00:01:00+08:00", "2026-10-08T10:00:00", "2026-09-30T17:00:00+08:00"])
def test_restore_rejects_later_old_or_naive_snapshot_capture(tmp_path, monkeypatch, owner, capture):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source, captured_at=capture)
    with pytest.raises(SyntheticStoreError, match="capture"):
        restore(master, source, target)
    assert not target.exists()


def test_receipt_wrong_date_fails_exact_source_verification(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    publish(master, tmp_path)
    receipt = next(tmp_path.rglob("receipt.json"))
    payload = json.loads(receipt.read_text())
    payload["trade_date"] = "20260930"
    receipt.write_text(json.dumps(payload))
    with pytest.raises(SyntheticStoreError, match="identity"):
        master.load_verified_hk_security_master(tmp_path, "20261008")


def test_ensure_restores_verified_source_without_current_collection(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    expected = publish(master, source)
    ensure = load_ensure(monkeypatch, owner, master)
    action = ensure.ensure_hk_security_master
    assert "verified_source_store_root" in inspect.signature(action).parameters, "ensure has no explicit exact-source preparation path"
    result = action(
        store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
        trade_date="20261008", futu_python=tmp_path / "must-not-run-python",
        reuse_only=True, verified_source_store_root=source,
    )
    assert result["ok"] is True and result["status"] == "READY"
    assert result["restored_from_verified_source"] is True
    assert result["security_master_run_id"] == expected["run_id"]
    assert result["security_master_artifact_sha256"] == expected["artifact_sha256"]
    assert result["security_master_manifest_sha256"] == sha256_json(expected["manifest"])
    assert all(result[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_ensure_reuse_missing_returns_actionable_date_reason(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    ensure = load_ensure(monkeypatch, owner, master)
    with pytest.raises(SyntheticStoreError, match="HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE.*20261008"):
        ensure.ensure_hk_security_master(
            store_root=tmp_path / "missing", universe_root=tmp_path / "universe",
            shared_package_root=tmp_path, trade_date="20261008",
            futu_python=tmp_path / "must-not-run-python", reuse_only=True,
        )


def test_ensure_source_universe_mismatch_cannot_publish(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    ensure = load_ensure(monkeypatch, owner, master, codes=["HK.00002"])
    assert "verified_source_store_root" in inspect.signature(ensure.ensure_hk_security_master).parameters
    with pytest.raises((ValueError, SyntheticStoreError), match="universe|coverage"):
        ensure.ensure_hk_security_master(
            store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date="20261008", futu_python=tmp_path / "must-not-run-python", reuse_only=True,
            verified_source_store_root=source,
        )
    assert not target.exists()


def freeze_ensure_clock(monkeypatch, ensure, observations):
    class Clock(datetime):
        remaining = [datetime.fromisoformat(value) for value in observations]

        @classmethod
        def now(cls, tz=None):
            value = cls.remaining.pop(0) if len(cls.remaining) > 1 else cls.remaining[0]
            return value.astimezone(tz) if tz is not None else value

    monkeypatch.setattr(ensure, "datetime", Clock)


@pytest.mark.parametrize("requested_date", ["20261008", "20261010"])
def test_live_prepare_blocks_noncurrent_source_day_without_collection(tmp_path, monkeypatch, owner, requested_date):
    master = load_master(monkeypatch, owner)
    ensure = load_ensure(monkeypatch, owner, master)
    freeze_ensure_clock(monkeypatch, ensure, ["2026-10-09T08:00:00+08:00"])
    target = tmp_path / "target"
    with pytest.raises(SyntheticStoreError, match="HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE.*" + requested_date):
        ensure.ensure_hk_security_master(
            store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date=requested_date, futu_python=tmp_path / "must-not-run-python",
        )
    assert not target.exists()


def test_live_prepare_rechecks_date_after_collection_before_publication(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    ensure = load_ensure(monkeypatch, owner, master, collector=lambda *args: rows())
    freeze_ensure_clock(monkeypatch, ensure, ["2026-10-08T23:59:59+08:00", "2026-10-09T00:00:01+08:00"])
    target = tmp_path / "target"
    with pytest.raises(SyntheticStoreError, match="HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE.*20261008"):
        ensure.ensure_hk_security_master(
            store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date="20261008", futu_python=tmp_path / "synthetic-collector",
        )
    assert not target.exists()


def test_live_prepare_current_source_day_preserves_observed_capture(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    ensure = load_ensure(monkeypatch, owner, master, collector=lambda *args: rows())
    freeze_ensure_clock(monkeypatch, ensure, ["2026-10-08T17:30:00+08:00", "2026-10-08T17:30:02+08:00"])
    target = tmp_path / "target"
    result = ensure.ensure_hk_security_master(
        store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
        trade_date="20261008", futu_python=tmp_path / "synthetic-collector",
    )
    assert result["ok"] is True and result["status"] == "READY"
    values, manifest = master.load_verified_hk_security_master(target, "20261008")
    assert manifest["captured_at"] == "2026-10-08T17:30:02+08:00"
    assert values["HK.00001"]["captured_at"] == manifest["captured_at"]


def test_cli_explicit_prepare_can_restore_original_source(tmp_path, monkeypatch, capsys, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    ensure = load_ensure(monkeypatch, owner, master)
    try:
        code = ensure.main([
            "--store-root", str(target), "--universe-root", str(tmp_path / "universe"),
            "--shared-package-root", str(tmp_path), "--trade-date", "20261008",
            "--futu-python", str(tmp_path / "must-not-run-python"),
            "--prepare-exact-date", "--verified-source-store-root", str(source),
        ])
    except SystemExit as error:
        code = error.code
    assert code == 0, "explicit guarded preparation CLI is unavailable or failed"
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "READY" and result["restored_from_verified_source"] is True


def test_interrupted_copy_preserves_latest_and_can_resume(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    publish(master, target, trade_date="20260930", captured_at="2026-09-30T17:30:00+08:00")
    pointer = target / "assets/hk_security_master/latest.json"
    before = pointer.read_bytes()
    original_copy = master._copy_exact_verified_file

    def interrupted(source_path, destination):
        if source_path.name == "manifest.json":
            raise OSError("synthetic interrupted copy")
        return original_copy(source_path, destination)

    monkeypatch.setattr(master, "_copy_exact_verified_file", interrupted)
    with pytest.raises(OSError, match="interrupted copy"):
        restore(master, source, target)
    assert pointer.read_bytes() == before
    with pytest.raises(SyntheticStoreError, match="EXACT_DATE_MISSING"):
        master.load_verified_hk_security_master(target, "20261008")
    monkeypatch.setattr(master, "_copy_exact_verified_file", original_copy)
    assert restore(master, source, target)["status"] == "READY"


def test_cli_guard_failure_is_failed_json_with_safe_flags(tmp_path, monkeypatch, capsys, owner):
    master = load_master(monkeypatch, owner)
    ensure = load_ensure(monkeypatch, owner, master)
    freeze_ensure_clock(monkeypatch, ensure, ["2026-10-09T08:00:00+08:00"])
    target = tmp_path / "target"
    code = ensure.main([
        "--store-root", str(target), "--universe-root", str(tmp_path / "universe"),
        "--shared-package-root", str(tmp_path), "--trade-date", "20261008",
        "--futu-python", str(tmp_path / "must-not-run-python"), "--prepare-exact-date",
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result["status"] == "FAILED" and result["ok"] is False
    assert "HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE" in result["error"]
    assert "20261008" in result["error"]
    assert all(result[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert not target.exists()


def test_live_prepare_must_read_back_published_trio_before_ready(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    original_publish = master.publish_hk_security_master

    def interrupted_publish(*args, **kwargs):
        result = original_publish(*args, **kwargs)
        next(args[0].rglob("receipt.json")).unlink()
        return result

    monkeypatch.setattr(master, "publish_hk_security_master", interrupted_publish)
    ensure = load_ensure(monkeypatch, owner, master, collector=lambda *args: rows())
    freeze_ensure_clock(monkeypatch, ensure, ["2026-10-08T17:30:00+08:00", "2026-10-08T17:30:02+08:00"])
    with pytest.raises(SyntheticStoreError, match="metadata|receipt"):
        ensure.ensure_hk_security_master(
            store_root=tmp_path / "target", universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date="20261008", futu_python=tmp_path / "synthetic-collector",
        )


def test_restore_immutable_create_cannot_replace_intervening_file(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    original_link = master.os.link
    conflicts = []

    def concurrent_create(source_path, destination, *args, **kwargs):
        if destination.name == "artifact.csv":
            destination.write_bytes(b"SYNTHETIC CONCURRENT IMMUTABLE FILE")
            conflicts.append(destination)
        return original_link(source_path, destination, *args, **kwargs)

    monkeypatch.setattr(master.os, "link", concurrent_create)
    with pytest.raises(SyntheticStoreError, match="conflict"):
        restore(master, source, target)
    assert len(conflicts) == 1
    assert conflicts[0].read_bytes() == b"SYNTHETIC CONCURRENT IMMUTABLE FILE"
    assert not (target / "assets/hk_security_master/latest.json").exists()


def test_restore_rejects_source_pointer_change_after_verification(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    original_load = master.load_verified_hk_security_master
    changed = False

    def changed_pointer(root, trade_date):
        nonlocal changed
        result = original_load(root, trade_date)
        if not changed and root == source:
            changed = True
            publish(master, source, name="SYNTHETIC CHANGED SOURCE")
        return result

    monkeypatch.setattr(master, "load_verified_hk_security_master", changed_pointer)
    with pytest.raises(SyntheticStoreError, match="source.*identity|source.*changed"):
        restore(master, source, target)
    assert not target.exists()


def test_restore_rejects_malformed_target_entry_as_store_error(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    pointer = target / "assets/hk_security_master/latest.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"schema_version": master.LATEST_SCHEMA_VERSION, "entries": {"20261008": []}}))
    before = file_bytes(target)
    with pytest.raises(SyntheticStoreError, match="target.*invalid"):
        restore(master, source, target)
    assert file_bytes(target) == before


def test_restore_detects_observed_target_pointer_update_without_lost_date(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    source, target = tmp_path / "source", tmp_path / "target"
    publish(master, source)
    original_copy = master._copy_exact_verified_file
    changed = False

    def changed_pointer(source_path, destination):
        nonlocal changed
        result = original_copy(source_path, destination)
        if not changed:
            changed = True
            publish(master, target, trade_date="20261001", captured_at="2026-10-01T17:30:00+08:00")
        return result

    monkeypatch.setattr(master, "_copy_exact_verified_file", changed_pointer)
    with pytest.raises(SyntheticStoreError, match="target.*changed"):
        restore(master, source, target)
    entries = json.loads((target / "assets/hk_security_master/latest.json").read_text())["entries"]
    assert set(entries) == {"20261001"}


@pytest.mark.parametrize("capture", ["2026-10-09T00:01:00+08:00", "2026-09-30T17:00:00+08:00", "2026-10-08T10:00:00"])
def test_existing_exact_master_reuse_rejects_wrong_capture_date(tmp_path, monkeypatch, owner, capture):
    master = load_master(monkeypatch, owner)
    target = tmp_path / "target"
    publish(master, target, captured_at=capture)
    before = file_bytes(target)
    ensure = load_ensure(monkeypatch, owner, master)
    with pytest.raises(ValueError, match="capture"):
        ensure.ensure_hk_security_master(
            store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date="20261008", futu_python=tmp_path / "must-not-run-python", reuse_only=True,
        )
    assert file_bytes(target) == before


def test_existing_exact_master_reuse_rejects_row_capture_mismatch(tmp_path, monkeypatch, owner):
    import hashlib

    master = load_master(monkeypatch, owner)
    target = tmp_path / "target"
    publish(master, target)
    artifact = next(target.rglob("artifact.csv"))
    artifact.write_bytes(artifact.read_bytes().replace(b"2026-10-08T17:30:00+08:00", b"2026-10-08T18:30:00+08:00"))
    manifest_path = next(target.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    receipt_path = next(target.rglob("receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    receipt["artifact_sha256"] = manifest["artifact_sha256"]
    receipt["manifest_sha256"] = sha256_json(manifest)
    receipt_path.write_text(json.dumps(receipt))
    # Checksums and manifest date alone still verify this deliberately bad fixture.
    master.load_verified_hk_security_master(target, "20261008")
    before = file_bytes(target)
    ensure = load_ensure(monkeypatch, owner, master)
    with pytest.raises(ValueError, match="capture"):
        ensure.ensure_hk_security_master(
            store_root=target, universe_root=tmp_path / "universe", shared_package_root=tmp_path,
            trade_date="20261008", futu_python=tmp_path / "must-not-run-python", reuse_only=True,
        )
    assert file_bytes(target) == before


def test_same_root_restore_preserves_unchanged_pointer_bytes(tmp_path, monkeypatch, owner):
    master = load_master(monkeypatch, owner)
    publish(master, tmp_path)
    pointer = tmp_path / "assets/hk_security_master/latest.json"
    pointer.write_text(json.dumps(json.loads(pointer.read_text()), indent=4) + "\n")
    before = file_bytes(tmp_path)
    assert restore(master, tmp_path, tmp_path)["already_exists"] is True
    assert file_bytes(tmp_path) == before
