"""Synthetic original-owner DTOs; no provider calls, Mac service or real plans.

The CLI supplies fresh Python-produced workspaces to the unchanged Mac API
validator in the TypeScript regression. It does not fabricate an accepted US
mapping or substitute HK Connect counts for US relationships.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from v4.manager_research import workspace
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS


MAPPING_MODULE = 'v4.manager_research.us_mapping_research'


def failed_mapping_module(kind: str):
    if kind == 'missing_module':
        return None
    module = ModuleType(MAPPING_MODULE)

    def read_workspace_mapping(*_args, **_kwargs):
        raise RuntimeError('synthetic original US reader failure')

    module.read_workspace_mapping = read_workspace_mapping
    return module


def owner_workspace_fixture(date: str, kind: str) -> dict:
    """Use the existing manager GET owner and an isolated unavailable US reader."""
    iso = f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    with TemporaryDirectory(prefix='issue29-us-dto-') as directory:
        service = ManagerResearchJobService(ManagerResearchStore(Path(directory) / 'manager'), None, None)
        try:
            with patch.dict(sys.modules, {MAPPING_MODULE: failed_mapping_module(kind)}):
                before = {str(p.relative_to(service.store.root)): p.read_bytes()
                          for p in service.store.root.rglob('*') if p.is_file()}
                value = service.get_workspace(date, view='dynamic',
                    now=datetime.fromisoformat(iso + 'T08:30:00+08:00'))
                after = {str(p.relative_to(service.store.root)): p.read_bytes()
                         for p in service.store.root.rglob('*') if p.is_file()}
            assert after == before, 'GET must not create or overwrite US/plan artifacts'
            return value
        finally:
            service.close()


@pytest.mark.parametrize('date', ['20260930', '20261008'])
@pytest.mark.parametrize('kind', ['missing_module', 'reader_failed'])
def test_us_failure_retains_the_original_mac_dto_and_unknown_counts(date, kind):
    value = owner_workspace_fixture(date, kind)
    mapping = value['us_mapping_research']
    assert mapping['schema_version'] == 'v4.manager_research.us_mapping_research.v1'
    assert mapping['target_trade_date'] == date
    daily = mapping['daily_run']
    assert daily['schema_version'] == 'v4.manager_research.us_mapping_daily_run.v1'
    assert daily['target_trade_date'] == date
    # A failed reader cannot prove that the original owner never ran.
    assert daily['status'] == 'CANNOT_CONFIRM'
    assert daily['matches'] == []
    assert all(daily[key] is None for key in
               ['run_id', 'generated_at', 'us_session_date', 'research_cutoff',
                'source_identity', 'input_identity', 'artifact_sha256'])
    assert daily['coverage']['full_market_coverage'] is False
    assert all(daily['coverage'][key] is None for key in
               ['reviewed_us_symbol_count', 'matched_us_symbol_count',
                'matched_hk_relation_count', 'configured_us_universe_count',
                'available_us_universe_count'])
    for data in [mapping, daily]:
        assert all(data[key] is expected for key, expected in FLAGS.items())
    assert daily['gaps'][0].startswith('US_MAPPING_READER_UNAVAILABLE:')
    reference = value['owner_chain']['us_mapping_daily_plan_reference']
    assert reference['status'] == 'NOT_CONSUMED' and reference['matches'] is None
    assert reference['run_id'] is None and reference['artifact_sha256'] is None
    assert value['daily_channels']['channels'][0]['channel'] == 'ANNOUNCEMENT'
    assert value['daily_channels']['channels'][1]['channel'] == 'HK_CONNECT'
    assert value['daily_channels']['channels'][2]['channel'] == 'OVERSOLD'


@pytest.mark.parametrize('date', ['20260930', '20261008'])
def test_reviewed_reference_failure_is_date_scoped_and_not_an_empty_success(date):
    mapping = owner_workspace_fixture(date, 'reader_failed')['us_mapping_research']
    reviewed = mapping['reviewed_research']
    if date == '20260930':
        assert reviewed['schema_version'] == 'v4.manager_research.us_mapping_reviewed.v1'
        assert reviewed['target_trade_date'] == date
        assert reviewed['status'] == 'CANNOT_CONFIRM'
        assert reviewed['reviewed_at'] is None and reviewed['cards'] == []
        assert reviewed['gaps'] == mapping['daily_run']['gaps']
        assert all(reviewed[key] is expected for key, expected in FLAGS.items())
    else:
        assert reviewed is None


def test_successful_original_owner_reference_and_cutoff_are_unchanged(monkeypatch):
    date = '20261008'
    original = dict(schema_version='v4.manager_research.us_mapping_research.v1',
        target_trade_date=date, reviewed_research=None, daily_run=dict(
            status='COMPLETED', target_trade_date=date, generated_at='2026-10-08T08:00:00+08:00',
            artifact_sha256='a' * 64, run_id='synthetic-us-run', matches=[{'reason': 'original relation'}]), **FLAGS)
    source_copy = deepcopy(original)
    module = ModuleType(MAPPING_MODULE)
    module.read_workspace_mapping = lambda _service, target: deepcopy(original)
    monkeypatch.setitem(sys.modules, MAPPING_MODULE, module)
    read, reference, identities = workspace._daily_mapping_plan_reference(
        SimpleNamespace(), date, {'research_cutoff': '2026-10-08T08:30:00+08:00'})
    assert read == source_copy and original == source_copy
    assert reference['status'] == 'CONSUMED' and identities == ['a' * 64]
    assert reference['matches'] == original['daily_run']['matches']
    _, late, identities = workspace._daily_mapping_plan_reference(
        SimpleNamespace(), date, {'research_cutoff': '2026-10-08T07:30:00+08:00'})
    assert late['status'] == 'NOT_CONSUMED_AFTER_CUTOFF' and identities == []
    assert original == source_copy


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--fixture' or sys.argv[2] not in {'20260930', '20261008'} or sys.argv[3] not in {'missing_module', 'reader_failed'}:
        raise SystemExit('Usage: test_manager_us_mapping_isolation_20261008.py --fixture <20260930|20261008> <missing_module|reader_failed>')
    print(json.dumps(owner_workspace_fixture(sys.argv[2], sys.argv[3]), ensure_ascii=False, allow_nan=False))
