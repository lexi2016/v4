"""A candidate builder may not erase aliases or publish a stale completion."""
from pathlib import Path
import plistlib
import sys
import pytest

from test_build_release_candidate import (
    BUILDER, _git_source, _write_active_release, _scheduler_plist, _write_delta_receipt,
)


def _build_args(tmp_path):
    source = _git_source(tmp_path)
    formal = tmp_path/'formal-releases'
    formal.mkdir()
    app = tmp_path/'active-release/app'
    api = tmp_path/'LaunchAgents/com.lexi.v35.api-only.plist'
    api.parent.mkdir()
    scheduler = tmp_path/'scheduler.plist'
    _write_active_release(api, app, {'apps/api/v35_api/app.py': b'VALUE = 0\n'})
    _scheduler_plist(scheduler, app)
    delta = _write_delta_receipt(tmp_path/'delta.json', api_plist=api,
        source_root=source, relative_paths=['apps/api/v35_api/app.py'])
    return dict(source_root=source, candidate_root=tmp_path/'candidate',
        api_plist_path=api, scheduler_plist_path=scheduler, python=Path(sys.executable),
        release_id='candidate', api_integration_delta_receipt_path=delta,
        formal_release_root=formal, dependency_names=())


@pytest.mark.parametrize('aliased', ['source_root', 'api_plist_path', 'api_integration_delta_receipt_path'])
def test_builder_does_not_erase_supplied_aliases(tmp_path, aliased):
    args = _build_args(tmp_path)
    original = args[aliased]
    alias = tmp_path/'alias'/original.name
    alias.parent.mkdir()
    alias.symlink_to(original, target_is_directory=original.is_dir())
    args[aliased] = alias
    with pytest.raises(ValueError):
        BUILDER.build_candidate(**args)
    assert not args['candidate_root'].exists()


def test_builder_rechecks_active_after_staging_before_marking_complete(tmp_path, monkeypatch):
    args = _build_args(tmp_path)
    pointer = args['api_plist_path']
    original = BUILDER._stage_scheduler_identity
    def drift(**kwargs):
        result = original(**kwargs)
        payload = plistlib.loads(pointer.read_bytes())
        payload['ProgramArguments'].insert(1, 'V35_DATA_ROOT=/synthetic/new-source')
        pointer.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
        return result
    monkeypatch.setattr(BUILDER, '_stage_scheduler_identity', drift)
    with pytest.raises(ValueError):
        BUILDER.build_candidate(**args)
    assert (args['candidate_root']/'.candidate-build-in-progress').exists()
