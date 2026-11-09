from __future__ import annotations

from pathlib import Path

import pytest

from ops.prepare_daily_materials_release import validate_runtime_locations


def _locations():
    base = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates'
    root = base / 'v4-v192-group-release-fixture'
    old = base / 'v4-daily-materials-20261109-r4'
    services = {}
    for role in ('api', 'main', 'stage'):
        app = (root if role == 'api' else old) / (role + '/app')
        services[role] = dict(app_root=str(app), manifest=str(app.parent / 'release-manifest.json'),
                              manifest_sha256='1' * 64, old_app_root=str(app),
                              old_manifest_sha256='1' * 64, draft_plist=str(root / (role + '.plist')))
    return dict(runtime_candidate_root=str(root), services=services,
                preserved_service_roles=['main', 'stage'],
                policy={'path': str(root / 'policy.json')}, pins={'path': str(root / 'pins.json')},
                static={'root': str(root / 'static'), 'manifest': str(root / 'assets.json')})


def test_api_only_packet_reuses_exact_main_stage_library_identities():
    validate_runtime_locations(_locations())


@pytest.mark.parametrize('field,value', [('app_root', '/tmp/changed-main/app'),
                                        ('manifest_sha256', '2' * 64)])
def test_preserved_main_cannot_hide_business_release_change(field, value):
    packet = _locations()
    packet['services']['main'][field] = value
    with pytest.raises(ValueError, match='PRESERVED_SERVICE_IDENTITY_CHANGED'):
        validate_runtime_locations(packet)


def test_new_api_cannot_be_declared_preserved_to_escape_batch_root():
    packet = _locations()
    packet['preserved_service_roles'].append('api')
    with pytest.raises(ValueError, match='PRESERVED_SERVICE_SCOPE_INVALID'):
        validate_runtime_locations(packet)


def test_prepare_rejects_main_producer_delta_before_creating_candidate(tmp_path):
    import json
    from ops.prepare_v192_group_release import prepare
    delta = tmp_path / 'forbidden-main.json'
    delta.write_text(json.dumps({'entries': [{'scope': 'main', 'target': 'ops/research_panel_daily_product.py'}]}))
    output = Path.home() / 'Library/Application Support/com.lexi.v4.local/candidates/v4-v192-forbidden-main-test'
    assert not output.exists()
    with pytest.raises(ValueError, match='API_STATIC_DELTA_ONLY'):
        prepare(delta_path=delta, output=output, r4_packet=tmp_path / 'not-read.json')
    assert not output.exists()
