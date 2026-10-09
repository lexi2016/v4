"""Exact ownership proposal for the original shared release owner, not a bypass."""
from pathlib import Path
import importlib.util
import os
import pytest

SOURCE = Path(os.environ['V4_R3_POLICY_SOURCE'])
spec = importlib.util.spec_from_file_location('r3_policy_under_review', SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

REQUIRED_SHARED = (
    'infrastructure/_research_peripheral_store_parts/_namespace.py',
    'infrastructure/scheduling/manager_announcement_supervisor.py',
    'ops/render_manager_announcement_binding.py',
    'ops/run_manager_announcement_cycle.py',
    'v3_shared_data/shared_data/hk_daily_supplement.py',
)


def test_manager_delta_requires_and_accepts_exact_reviewed_shared_paths():
    scope = policy.module_scope('manager', REQUIRED_SHARED)
    paths = ['v4/manager_research/workspace_daily_channels.py', *REQUIRED_SHARED]
    assert policy._validate_module_scope(scope, paths) == scope
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_SHARED_PATHS_NOT_EXACT'):
        policy._validate_module_scope(policy.module_scope('manager'), paths)
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_SHARED_PATHS_NOT_EXACT'):
        policy._validate_module_scope(scope, paths[:-1])


@pytest.mark.parametrize('path', [
    'ops/daily_materialize.py', 'ops/run_v35_macos_scheduler_daemon.py',
    'stage_center/runner.py', 'v3_shared_data/shared_data/hk_0_2.py',
    'infrastructure/owned_io.py', 'ops/ensure_hk_security_master.py',
])
def test_unreviewed_neighbor_and_other_owner_paths_still_rejected(path):
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_SHARED_PATH_NOT_ALLOWED'):
        policy.module_scope('manager', [path])
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_PATH_NOT_OWNED'):
        policy._validate_module_scope(policy.module_scope('manager'), [path])


def test_preselection_does_not_gain_manager_dependency_ownership():
    for path in REQUIRED_SHARED:
        with pytest.raises(ValueError, match='API_RELEASE_MODULE_SHARED_PATH_NOT_ALLOWED'):
            policy.module_scope('preselection', [path])


def test_existing_shared_app_declaration_and_policy_pin_still_required():
    app = 'apps/api/v35_api/app.py'
    scope = policy.module_scope('manager', [app])
    assert policy._validate_module_scope(scope, [app]) == scope
    damaged = {**scope, 'policy_sha256': '0' * 64}
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_SCOPE_POLICY_MISMATCH'):
        policy._validate_module_scope(damaged, [app])
    with pytest.raises(ValueError, match='API_RELEASE_MODULE_SHARED_PATHS_NOT_EXACT'):
        policy._validate_module_scope(policy.module_scope('manager'), [app])
