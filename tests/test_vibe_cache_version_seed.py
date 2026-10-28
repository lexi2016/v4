"""Isolated filesystem tests for the pinned Vibe cache-version seeder."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from domains.research_review_generation._owned_io import BoundaryError
from ops import seed_vibe_cache_version as seed


def _make_fixture(tmp_path: Path, *, names=None):
    source = tmp_path / "source-cache"
    source.mkdir()
    names = names or [
        "cache/breadth/2026-09-04.json",
        "leaders/20260904.json",
        "reflections/2026-09-03.json",
    ]
    entries = {}
    for index, name in enumerate(names):
        raw = json.dumps({"fixture_index": index, "name": name}, sort_keys=True).encode() + b"\n"
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entries[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return source, entries


def test_actual_pinned_inventory_has_expected_shape_and_excludes_generated_files():
    entries = seed._load_pinned_manifest()
    assert len(entries) == 80
    assert sum(name.startswith("cache/") for name in entries) == 62
    assert sum(name.startswith("leaders/") for name in entries) == 10
    assert sum(name.startswith("reflections/") for name in entries) == 8
    assert "cache/zt_reasons/2026-09-24.json" not in entries
    assert ".ownership/generated-cache.json" not in entries


def test_only_manifest_listed_bytes_are_copied_and_no_generated_ledger_is_created(tmp_path):
    source, entries = _make_fixture(tmp_path)
    (source / "outside.json").write_text("unlisted")
    (source / ".ownership").mkdir()
    (source / ".ownership/generated-cache.json").write_text("generated")
    destination = tmp_path / "versions" / "iwencai-r1"

    receipt = seed._seed_from_entries(source, destination, entries)

    assert receipt["status"] == "SEEDED_UNSELECTED_VERSION"
    assert receipt["cache_files"] == len(entries)
    actual = {
        path.relative_to(destination / "cache_store").as_posix()
        for path in (destination / "cache_store").rglob("*")
        if path.is_file()
    }
    assert actual == set(entries)
    for name, info in entries.items():
        copied = (destination / "cache_store" / name).read_bytes()
        assert len(copied) == info["bytes"]
        assert hashlib.sha256(copied).hexdigest() == info["sha256"]
    assert not (destination / "cache_store/.ownership/generated-cache.json").exists()
    assert not (destination / "cache_store/cache/zt_reasons/2026-09-24.json").exists()


def test_entire_source_set_is_validated_before_any_stage_is_created(tmp_path):
    source, entries = _make_fixture(tmp_path)
    changed = source / "leaders/20260904.json"
    original = changed.read_bytes()
    changed.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    destination = tmp_path / "versions" / "must-not-exist"

    with pytest.raises(BoundaryError, match="CACHE_SEED_SOURCE_FILE_SHA_MISMATCH"):
        seed._seed_from_entries(source, destination, entries)

    assert not destination.exists()
    assert not list(destination.parent.glob(".must-not-exist.seed-stage-*"))


def test_missing_listed_source_file_fails_before_destination_creation(tmp_path):
    source, entries = _make_fixture(tmp_path)
    (source / "leaders/20260904.json").unlink()
    destination = tmp_path / "versions" / "missing-source"

    with pytest.raises(BoundaryError, match="CACHE_SEED_SOURCE_FILE_UNSAFE_OR_MISSING"):
        seed._seed_from_entries(source, destination, entries)

    assert not destination.exists()


def test_symlink_source_root_and_nested_symlink_are_refused(tmp_path):
    source, entries = _make_fixture(tmp_path)
    destination = tmp_path / "versions" / "root-link"
    root_link = tmp_path / "source-link"
    root_link.symlink_to(source, target_is_directory=True)
    with pytest.raises(BoundaryError, match="CACHE_SEED_SOURCE_ROOT_UNSAFE"):
        seed._seed_from_entries(root_link, destination, entries)
    assert not destination.exists()

    source2 = tmp_path / "source-with-nested-link"
    source2.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    file_name = "cache/breadth/2026-09-04.json"
    raw = b"{}\n"
    (outside / "2026-09-04.json").write_bytes(raw)
    (source2 / "cache").symlink_to(outside, target_is_directory=True)
    nested_entries = {file_name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}
    with pytest.raises(BoundaryError, match="CACHE_SEED_SOURCE_FILE_UNSAFE_OR_MISSING"):
        seed._seed_from_entries(source2, tmp_path / "versions" / "nested-link", nested_entries)


def test_destination_residue_is_preserved_and_refused(tmp_path):
    source, entries = _make_fixture(tmp_path)
    destination = tmp_path / "versions" / "already-selected"
    destination.mkdir(parents=True)
    marker = destination / "marker"
    marker.write_text("preserve")

    with pytest.raises(BoundaryError, match="CACHE_SEED_DESTINATION_NOT_ABSENT"):
        seed._seed_from_entries(source, destination, entries)

    assert marker.read_text() == "preserve"


def test_competing_destination_created_at_commit_is_preserved_without_replacement(tmp_path, monkeypatch):
    source, entries = _make_fixture(tmp_path)
    destination = tmp_path / "versions" / "concurrent-owner"
    owner_bytes = b"created by competing writer\n"
    injected = {"done": False}
    atomic_commit = seed._rename_stage_no_replace

    def create_destination_at_commit(stage, target):
        assert target == destination and not target.exists()
        target.mkdir()
        (target / "owner.txt").write_bytes(owner_bytes)
        injected["done"] = True
        return atomic_commit(stage, target)

    monkeypatch.setattr(seed, "_rename_stage_no_replace", create_destination_at_commit)
    with pytest.raises(BoundaryError, match="CACHE_SEED_DESTINATION_NOT_ABSENT;STAGING_QUARANTINED:") as error:
        seed._seed_from_entries(source, destination, entries)

    assert injected["done"] is True
    assert (destination / "owner.txt").read_bytes() == owner_bytes
    assert not (destination / "cache_store").exists()
    quarantined = Path(str(error.value).split("STAGING_QUARANTINED:", 1)[1])
    assert quarantined.parent == destination.parent
    assert list((quarantined / "cache_store").rglob("*.json"))
    assert not list(destination.parent.glob(".concurrent-owner.seed-stage-*"))


def test_atomic_commit_api_unavailable_fails_closed_and_does_not_publish(tmp_path, monkeypatch):
    source, entries = _make_fixture(tmp_path)
    destination = tmp_path / "versions" / "unsupported-commit"

    class MissingAtomicRename:
        pass

    monkeypatch.setattr(seed.ctypes, "CDLL", lambda *args, **kwargs: MissingAtomicRename())
    with pytest.raises(BoundaryError, match="CACHE_SEED_ATOMIC_COMMIT_UNAVAILABLE;STAGING_QUARANTINED:") as error:
        seed._seed_from_entries(source, destination, entries)

    assert not destination.exists()
    quarantined = Path(str(error.value).split("STAGING_QUARANTINED:", 1)[1])
    assert quarantined.exists()
    assert list((quarantined / "cache_store").rglob("*.json"))


def test_mid_copy_failure_keeps_stage_quarantined_and_never_publishes(tmp_path):
    source, entries = _make_fixture(tmp_path)
    destination = tmp_path / "versions" / "interrupted"
    copied = []

    def stop_after_first(name):
        copied.append(name)
        if len(copied) == 1:
            raise RuntimeError("fixture interruption")

    with pytest.raises(BoundaryError, match="STAGING_QUARANTINED") as error:
        seed._seed_from_entries(source, destination, entries, _after_copy=stop_after_first)

    assert not destination.exists()
    quarantined = Path(str(error.value).split("STAGING_QUARANTINED:", 1)[1])
    assert quarantined.exists()
    assert list((quarantined / "cache_store").rglob("*.json"))
    assert not list(destination.parent.glob(".interrupted.seed.lock"))


@pytest.mark.parametrize(
    "name",
    [
        "../escape.json",
        "/absolute.json",
        "cache/unknown/2026-09-04.json",
        "cache/breadth/nested/2026-09-04.json",
        "cache\\breadth\\2026-09-04.json",
    ],
)
def test_unsafe_manifest_paths_are_rejected(name):
    manifest = {
        "schema": seed.MANIFEST_SCHEMA,
        "source": "test",
        "files": {name: {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}},
    }
    with pytest.raises(BoundaryError, match="CACHE_SEED_MANIFEST_PATH_INVALID"):
        seed._validated_entries(manifest, require_pinned_inventory=False)


def test_generated_same_date_entry_cannot_be_added_to_a_manifest():
    name = "cache/zt_reasons/2026-09-24.json"
    manifest = {
        "schema": seed.MANIFEST_SCHEMA,
        "source": "test",
        "files": {name: {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}},
    }
    with pytest.raises(BoundaryError, match="CACHE_SEED_FORBIDDEN_GENERATED_ENTRY"):
        seed._validated_entries(manifest, require_pinned_inventory=False)
