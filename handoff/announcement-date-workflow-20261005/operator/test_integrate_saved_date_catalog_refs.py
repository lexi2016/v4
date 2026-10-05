from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name('integrate_saved_date_catalog_refs.py')


def load_script():
    spec = importlib.util.spec_from_file_location('integrate_saved_refs_tested', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def apply_main(tmp_path: Path, *, drift: bool = False) -> tuple[int | None, list[str]]:
    module = load_script()
    names = {
        'HK.00001': {
            'captured_at': '2026-10-02T14:03:06+08:00', 'code': 'HK.00001',
            'name': '长和', 'source': 'native', 'status': 'NORMAL',
        },
        'HK.00002': {
            'captured_at': '2026-10-02T14:03:06+08:00', 'code': 'HK.00002',
            'name': '中电控股', 'source': 'native', 'status': 'NORMAL',
        },
    }
    witness = {'source_date': '2026-09-30', 'snapshot_sha256': 'a' * 64}
    master = {'names': names, 'identity_witness': witness}
    master_path = tmp_path / 'master.json'
    master_path.write_text(json.dumps(master), encoding='utf-8')
    module.MASTER_SNAPSHOT = master_path
    module.load_refs = lambda: {1: {'saved': True}}

    accepted: list[str] = []
    catalog = types.ModuleType('v4.manager_research.announcement_catalog')
    catalog.collect_date_scoped_catalog = lambda *a, **k: {
        'status': 'COMPLETE', 'total_hits': 744, 'manager_consumer_row_count': 234,
        'captured_page_count': 39, 'unique_art_code_count': 744, 'gaps': [],
    }
    catalog.validate_product = lambda product, **_k: product
    catalog.verify_product_sources = lambda *_a: None

    materials_module = types.ModuleType('v4.manager_research.materials')
    materials_module.MaterialStore = lambda _root: object()

    service_module = types.ModuleType('v4.manager_research.service')
    class FakeService:
        def __init__(self, *_a, **_k):
            self.read_count = 0

        def get_announcement_date_catalog(self, *_a):
            self.read_count += 1
            if self.read_count == 1:
                return {'catalog': None, 'readback_status': 'NOT_RUN'}
            return {'catalog': {'run_id': 'owner-run'}, 'readback_status': 'VERIFIED'}

        def accept_saved_date_catalog_refs(self, *_a):
            accepted.append('accept')
            return {'status': 'COMPLETE', 'readback_status': 'VERIFIED', 'catalog': {
                'run_id': 'owner-run', 'capture_mode': 'SAVED_REFERENCE_IMPORT',
                'total_hits': 744, 'manager_consumer_row_count': 234, 'page_receipts': [],
            }}

        def refresh_announcements(self, *_a, **_k):
            accepted.append('refresh')
            return {'catalog': {'run_id': 'owner-run'}}

        def close(self):
            pass

    service_module.ManagerResearchJobService = FakeService
    store_module = types.ModuleType('v4.manager_research.store')
    store_module.ManagerResearchStore = lambda _root: object()
    workspace_announcements = types.ModuleType('v4.manager_research.workspace_announcements')
    active = {code: dict(row) for code, row in names.items()}
    if drift:
        active['HK.00001']['name'] = '真实漂移'
    workspace_announcements._master = lambda *_a, **_k: (active, witness)
    workspace_announcements._now = lambda: '2026-10-05T00:00:00+00:00'
    workspace_plan = types.ModuleType('v4.manager_research.workspace_plan')
    workspace_plan.plan_context = lambda *_a, **_k: {}
    workspace_projection = types.ModuleType('v4.manager_research.workspace_projection')
    workspace_projection.timestamp = lambda value: value

    modules = {
        'v4.manager_research.announcement_catalog': catalog,
        'v4.manager_research.materials': materials_module,
        'v4.manager_research.service': service_module,
        'v4.manager_research.store': store_module,
        'v4.manager_research.workspace_announcements': workspace_announcements,
        'v4.manager_research.workspace_plan': workspace_plan,
        'v4.manager_research.workspace_projection': workspace_projection,
    }
    argv = [str(SCRIPT), '--apply', '--state-root', str(tmp_path / 'state'),
            '--master-root', str(tmp_path / 'master-root')]
    with patch.dict(sys.modules, modules), patch.object(sys, 'argv', argv):
        try:
            return module.main(), accepted
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else None, accepted


def test_apply_preflight_accepts_full_native_snapshot_without_owner_writes(tmp_path):
    code, calls = apply_main(tmp_path)
    assert code == 0
    assert calls == ['accept', 'refresh']


def test_name_only_projection_is_the_prior_false_drift_condition():
    full_rows = {
        'HK.00001': {'code': 'HK.00001', 'name': '长和', 'captured_at': '2026-10-02T14:03:06+08:00'},
    }
    old_projection = {code: {'name': row['name']} for code, row in full_rows.items()}
    assert old_projection != full_rows
    module = load_script()
    module.verify_master_snapshot(full_rows, {'source_date': '2026-09-30'}, {
        'names': full_rows, 'identity_witness': {'source_date': '2026-09-30'},
    })


def test_apply_preflight_rejects_real_master_drift_before_owner_writes(tmp_path):
    code, calls = apply_main(tmp_path, drift=True)
    assert code is None
    assert calls == []
