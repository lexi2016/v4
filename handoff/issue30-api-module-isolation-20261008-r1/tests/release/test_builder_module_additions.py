"""Explicit additions are allowed only within the declared module."""
from pathlib import Path
import sys
from test_build_release_candidate import BUILDER, _git_source, _write_active_release, _scheduler_plist, _write_delta_receipt


def test_preselection_delta_adds_only_its_reviewed_router_and_service(tmp_path):
    source = _git_source(tmp_path)
    paths = ['apps/api/v35_api/preselection_router.py', 'apps/api/v35_api/preselection_service.py']
    for path in paths:
        (source/path).write_text('REVIEWED_MODULE = True\n')
    (source/'apps/api/v35_api/unreviewed.py').write_text('UNREVIEWED = True\n')
    formal = tmp_path/'formal';formal.mkdir()
    api = tmp_path/'com.lexi.v35.api-only.plist'; app = tmp_path/'active/app'
    _write_active_release(api,app,{'apps/api/v35_api/app.py':b'VALUE = 0\n','manager_preserved.py':b'MANAGER = True\n'})
    scheduler = tmp_path/'scheduler.plist';_scheduler_plist(scheduler,app)
    delta = _write_delta_receipt(tmp_path/'delta.json',api_plist=api,source_root=source,
        relative_paths=['apps/api/v35_api/app.py',*paths])
    candidate = tmp_path/'candidate'
    receipt = BUILDER.build_candidate(source_root=source,candidate_root=candidate,
        api_plist_path=api,scheduler_plist_path=scheduler,python=Path(sys.executable),
        release_id='candidate',api_integration_delta_receipt_path=delta,
        formal_release_root=formal,dependency_names=(),include_untracked_paths=paths)
    assert receipt['activation_status'] == 'NOT_ACTIVATED'
    assert (candidate/'app/manager_preserved.py').read_bytes() == b'MANAGER = True\n'
    assert all((candidate/'app'/path).read_bytes() == b'REVIEWED_MODULE = True\n' for path in paths)
    assert not (candidate/'app/apps/api/v35_api/unreviewed.py').exists()
