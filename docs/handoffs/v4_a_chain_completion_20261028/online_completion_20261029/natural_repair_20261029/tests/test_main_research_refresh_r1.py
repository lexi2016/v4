"""Offline regression of the installed morning-refresh path; no producer runs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

BASE = Path(__file__).resolve().parents[1]
MAIN = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-retirement-20261028-main/app')
sys.path[:0] = [str(MAIN), str(MAIN / 'upstreams')]
from infrastructure.preselection_pool_store import PreselectionPoolStore


def load_refresh(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = load_refresh(MAIN / 'ops/refresh_research_preselection.py', 'original_refresh')
NEW = load_refresh(BASE / 'sources/main/ops/refresh_research_preselection.py', 'candidate_refresh')
PLACEHOLDER = json.loads((BASE / 'tests/fixtures/research_pool_placeholder_20261029.json').read_text())
POOL = PLACEHOLDER['pool_id']


def ready(slot):
    artifact = deepcopy(PLACEHOLDER)
    artifact.update(status='RESEARCH_RECOMMENDATION_POOL_READY',
        producer_id='v3_5_hourly_research_window_v1', source_role='VERIFIED_HOURLY_RESEARCH',
        source_path=f'research/hourly/live/20261029/{slot}.json', source_sha256='a' * 64,
        rows=[{'symbol': 'A.002286', 'source_article_ids': ['offline-article']}],
        cannot_confirm=['RESEARCH_ONLY_NO_BUY_GATE'])
    return artifact


def setup_root(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    original = store.materialize(deepcopy(PLACEHOLDER))
    return store, original


@pytest.mark.parametrize('slot', ['0830', '0900'])
def test_original_fails_and_candidate_cas_recovers_exact_placeholder(tmp_path, monkeypatch, slot):
    store, original = setup_root(tmp_path)
    artifact = ready(slot)
    for module in (OLD, NEW):
        monkeypatch.setattr(module, 'build_hourly_research_pool', lambda *a, **k: deepcopy(artifact))
    with pytest.raises(ValueError, match='conflicting preselection-pool materialization'):
        OLD.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    result = NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    pub = result['publication']
    assert result['status'] == 'SUCCEEDED' and pub['recovery'] is True
    assert pub['previous_sha256'] == original['sha256']
    assert store.read_pool('20261029', POOL) == artifact
    for sha, expected in [(original['sha256'], PLACEHOLDER), (pub['sha256'], artifact)]:
        archive = store.root / 'preselection_revisions' / '20261029' / POOL / f'{sha}.json'
        assert json.loads(archive.read_text()) == expected
    before = {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob('*.json')}
    repeated = NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    assert repeated['publication']['sha256'] == pub['sha256']
    assert {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob('*.json')} == before
    assert all(result[k] is False for k in ['production_allowed', 'buy_gate_updated', 'orders_sent'])


def test_changed_verified_same_source_still_conflicts(tmp_path, monkeypatch):
    store, _ = setup_root(tmp_path)
    first = ready('0830')
    monkeypatch.setattr(NEW, 'build_hourly_research_pool', lambda *a, **k: deepcopy(first))
    NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    first['rows'][0]['source_article_ids'].append('different-content')
    first['source_sha256'] = 'b' * 64
    before = {str(p): p.read_bytes() for p in store.root.rglob('*.json')}
    with pytest.raises(ValueError, match='conflicting preselection-pool materialization'):
        NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    assert {str(p): p.read_bytes() for p in store.root.rglob('*.json')} == before


def test_malformed_expected_missing_is_not_recovered(tmp_path, monkeypatch):
    store = PreselectionPoolStore(tmp_path / 'data')
    malformed = deepcopy(PLACEHOLDER)
    malformed['producer_id'] = 'unrecognized-placeholder'
    store.materialize(malformed)
    monkeypatch.setattr(NEW, 'build_hourly_research_pool', lambda *a, **k: ready('0900'))
    with pytest.raises(ValueError, match='preimage is not exact EXPECTED_MISSING'):
        NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    assert store.read_pool('20261029', POOL) == malformed


def test_stale_cas_is_rejected_by_existing_store(tmp_path):
    store, _ = setup_root(tmp_path)
    with pytest.raises(ValueError, match='expected old SHA mismatch'):
        store.recover_expected_missing(ready('0900'), expected_old_sha256='0' * 64)
    assert store.read_pool('20261029', POOL) == PLACEHOLDER


def test_existing_verified_source_extension_still_works(tmp_path, monkeypatch):
    store = PreselectionPoolStore(tmp_path / 'data')
    artifact = ready('0830')
    store.materialize(artifact)
    artifact = deepcopy(artifact)
    artifact['source_path'] += '|research/hourly/live/20261029/0900.json'
    artifact['source_sha256'] = 'b' * 64
    monkeypatch.setattr(NEW, 'build_hourly_research_pool', lambda *a, **k: deepcopy(artifact))
    result = NEW.refresh_research_preselection(data_root=store.root, trade_date='20261029')
    assert result['status'] == 'SUCCEEDED'
    assert store.read_pool('20261029', POOL) == artifact
