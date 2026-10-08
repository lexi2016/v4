"""Publishing-plan boundary checks using synthetic candidate trees only."""
from __future__ import annotations

from pathlib import Path
import plistlib
import pytest

from ops import prepare_api_only_cutover as prepare
from test_api_release_integration import _integrated_candidate


def _args(active, candidate, root):
    manifest = candidate / 'release-manifest.json'
    return dict(source_plist_path=Path(active['api_plist']), candidate_root=candidate,
        release_id=candidate.name, manifest_path=manifest,
        manifest_sha256=prepare.sha256_file(manifest),
        current_manager_state_root=Path(active['manager_root']), source_root=root/'source')


def test_prepare_rejects_release_id_different_from_verified_manifest(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    args = _args(active, candidate, tmp_path)
    args['release_id'] = 'wrong-release'
    with pytest.raises(ValueError):
        prepare.render_cutover(**args)
    assert not (candidate/'config/com.lexi.v35.api-only.plist').exists()


def test_prepare_rejects_pointer_change_after_initial_verification(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    pointer = Path(active['api_plist'])
    original = prepare.verify_api_release_candidate
    def drift(**kwargs):
        result = original(**kwargs)
        payload = plistlib.loads(pointer.read_bytes())
        payload['ProgramArguments'].insert(1, 'V35_DATA_ROOT=/synthetic/new-data')
        pointer.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
        return result
    monkeypatch.setattr(prepare, 'verify_api_release_candidate', drift)
    with pytest.raises(ValueError):
        prepare.render_cutover(**_args(active, candidate, tmp_path))
    assert not (candidate/'config/com.lexi.v35.api-only.plist').exists()


def test_prepare_rejects_state_directory_symlink_before_writing(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    outside = tmp_path/'outside-state'
    outside.mkdir()
    (candidate/'state').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare.render_cutover(**_args(active, candidate, tmp_path))
    assert not list(outside.iterdir())


def test_prepare_config_swap_after_rewrite_cannot_write_outside(tmp_path, monkeypatch):
    active, candidate, _ = _integrated_candidate(tmp_path)
    outside = tmp_path/'outside-config'
    outside.mkdir()
    original = prepare.rewrite_api_only_plist
    def swap(*args, **kwargs):
        result = original(*args, **kwargs)
        config = candidate/'config'
        if config.exists():
            config.rename(candidate/'parked-config')
        config.symlink_to(outside, target_is_directory=True)
        return result
    monkeypatch.setattr(prepare, 'rewrite_api_only_plist', swap)
    with pytest.raises(ValueError):
        prepare.render_cutover(**_args(active, candidate, tmp_path))
    assert not list(outside.iterdir())


def test_prepare_plan_has_no_unguarded_launchctl_or_copy_path(tmp_path):
    active, candidate, _ = _integrated_candidate(tmp_path)
    plan = prepare.render_cutover(**_args(active, candidate, tmp_path))
    assert 'future_commands' not in plan
    assert plan['activation_protocol']['shared_lock_required'] is True
    assert plan['activation_protocol']['integration_revalidation_required'] is True
    assert plan['activation_protocol']['automatic_activation'] is False
