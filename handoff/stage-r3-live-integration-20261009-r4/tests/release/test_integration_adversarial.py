"""Isolated regression probes: no services, real plists, or business data.

Every fixture lives below pytest tmp_path. These assertions describe required
refusals and intentionally fail against the exact unreviewed draft.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from ops import api_release_integration as integration
from ops.prepare_api_only_cutover import render_cutover, sha256_file
from test_api_release_integration import _write_active_release, _delta_receipt, _integrated_candidate


def _alternate_release(root: Path) -> dict:
    return _write_active_release(
        root, root / "OtherLaunchAgents" / "com.lexi.v35.api-only.plist",
        release_id="newer-accepted-release",
        files={"apps/api/v35_api/app.py": b"VALUE = 9\n", "stable-module.py": b"STABLE = True\n"},
    )


def _refresh_candidate_inventory(candidate: Path, manifest: dict) -> None:
    entries = integration.inventory_tree(candidate / "app")
    manifest["application_inventory"] = {
        "entry_count": len(entries),
        "aggregate_sha256": integration.inventory_digest(entries),
        "entries": entries,
    }
    (candidate / "release-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def test_read_active_rejects_plist_change_during_identity_read(tmp_path, monkeypatch):
    active = _write_active_release(tmp_path, tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist")
    other = _alternate_release(tmp_path)
    pointer = Path(active["api_plist"])
    replacement = Path(other["api_plist"]).read_bytes()
    original = integration._release_identity

    def change_after_identity(**kwargs):
        result = original(**kwargs)
        pointer.write_bytes(replacement)
        return result

    monkeypatch.setattr(integration, "_release_identity", change_after_identity)
    with pytest.raises(ValueError):
        integration.read_active_release(pointer)


def test_verify_rejects_active_switch_during_delta_verification(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    other = _alternate_release(tmp_path)
    pointer = Path(active["api_plist"])
    replacement = Path(other["api_plist"]).read_bytes()
    original = integration._verify_delta_files

    def change_after_delta(**kwargs):
        result = original(**kwargs)
        pointer.write_bytes(replacement)
        return result

    monkeypatch.setattr(integration, "_verify_delta_files", change_after_delta)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=pointer)


def test_build_rejects_active_switch_during_delta_verification(tmp_path, monkeypatch):
    active = _write_active_release(tmp_path, tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist")
    other = _alternate_release(tmp_path)
    pointer = Path(active["api_plist"])
    replacement = Path(other["api_plist"]).read_bytes()
    source = tmp_path / "source"
    changed = source / "apps/api/v35_api/app.py"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"VALUE = 2\n")
    receipt = _delta_receipt(active, source)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    original = integration._verify_delta_files

    def change_after_delta(**kwargs):
        result = original(**kwargs)
        pointer.write_bytes(replacement)
        return result

    monkeypatch.setattr(integration, "_verify_delta_files", change_after_delta)
    with pytest.raises(ValueError):
        integration.build_integrated_app(active_api_plist_path=pointer, source_root=source,
            candidate_root=candidate, delta_receipt_path=receipt)


def test_verify_rejects_non_delta_mutation_after_verification(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    original = integration._verify_delta_files

    def change_after_delta(**kwargs):
        result = original(**kwargs)
        (candidate / "app/stable-module.py").write_bytes(b"STABLE = False\n")
        return result

    monkeypatch.setattr(integration, "_verify_delta_files", change_after_delta)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate,
            active_api_plist_path=Path(active["api_plist"]))


def test_verify_rejects_delta_mode_not_bound_by_receipt(tmp_path):
    active, candidate, manifest = _integrated_candidate(tmp_path)
    (candidate / "app/apps/api/v35_api/app.py").chmod(0o777)
    _refresh_candidate_inventory(candidate, manifest)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate,
            active_api_plist_path=Path(active["api_plist"]))


def test_prepare_rejects_config_directory_symlink(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    outside = tmp_path / "outside-candidate"
    outside.mkdir()
    (candidate / "config").symlink_to(outside, target_is_directory=True)
    manifest = candidate / "release-manifest.json"
    with pytest.raises(ValueError):
        render_cutover(source_plist_path=Path(active["api_plist"]), candidate_root=candidate,
            release_id=candidate.name, manifest_path=manifest,
            manifest_sha256=sha256_file(manifest), current_manager_state_root=Path(active["manager_root"]),
            source_root=tmp_path / "source")
    assert not list(outside.iterdir())


def test_prepare_rejects_source_pointer_symlink(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    alias_parent = tmp_path / "AliasLaunchAgents"
    alias_parent.mkdir()
    alias = alias_parent / "com.lexi.v35.api-only.plist"
    alias.symlink_to(Path(active["api_plist"]))
    manifest = candidate / "release-manifest.json"
    with pytest.raises(ValueError):
        render_cutover(source_plist_path=alias, candidate_root=candidate,
            release_id=candidate.name, manifest_path=manifest,
            manifest_sha256=sha256_file(manifest), current_manager_state_root=Path(active["manager_root"]),
            source_root=tmp_path / "source")


def test_verify_rejects_candidate_root_replacement_during_verification(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    original = integration._verify_delta_files

    def change_after_delta(**kwargs):
        result = original(**kwargs)
        parked = tmp_path / "parked-candidate"
        candidate.rename(parked)
        shutil.copytree(parked, candidate, symlinks=True)
        return result

    monkeypatch.setattr(integration, "_verify_delta_files", change_after_delta)
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate,
            active_api_plist_path=Path(active["api_plist"]))


def test_verify_binds_exact_active_pointer_bytes(tmp_path):
    import plistlib
    active, candidate, _ = _integrated_candidate(tmp_path)
    pointer = Path(active["api_plist"])
    payload = plistlib.loads(pointer.read_bytes())
    payload["ProgramArguments"].insert(1, "V35_DATA_ROOT=/isolated/new-source")
    pointer.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    with pytest.raises(ValueError):
        integration.verify_api_release_candidate(candidate_root=candidate, active_api_plist_path=pointer)
