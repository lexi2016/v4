"""Synthetic archives through original SafeRoot; never historical market proof."""
from copy import deepcopy
import json

import pytest

from test_manager_three_lane_history_r1 import DATE, stored, hashes
from v4.manager_research import workspace_history as history
from v4.manager_research.store import ManagerResearchStore


def no_journal(store, attempt):
    (store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')).unlink()


def test_missing_journals_do_not_force_large_late_bodies_through_pit_budget(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 7):
        _, attempt = stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000, latest=n == 6)
        no_journal(store, attempt)
    before = hashes(store.root)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) is None
    assert hashes(store.root) == before


def test_utf8_character_cut_at_probe_limit_does_not_force_late_body_read(tmp_path, monkeypatch):
    from v4.manager_research.workspace_projection import digest
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 7):
        product, attempt = stored(store, n, f'2026-10-10T10:0{n}:00+08:00')
        no_journal(store, attempt)
        for offset in range(3):
            product['workspace']['synthetic_padding'] = 'a' * offset + '中' * 12000
            product['sha256'] = digest({k:v for k,v in product.items() if k != 'sha256'})
            raw = json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            try:
                raw[:history._MAX_HEADER_BYTES].decode('utf-8')
            except UnicodeDecodeError:
                break
        else:
            pytest.fail('Fixture must cut inside one complete valid UTF-8 character')
        raw.decode('utf-8')  # The whole original document is valid.
        (store.root/'workspace_plans'/DATE/(product['run_id']+'.json')).write_bytes(raw)
        if n == 6:
            (store.root/'workspace_plans'/DATE/'latest.json').write_bytes(raw)
    before = hashes(store.root)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) is None
    assert hashes(store.root) == before


def test_late_latest_and_its_alias_do_not_hide_early_legacy_plan(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    _, late_attempt = stored(store, 1, '2026-10-10T10:00:00+08:00', padding=24000, latest=True)
    early, early_attempt = stored(store, 2, '2026-10-09T09:28:00+08:00', padding=20000)
    no_journal(store, late_attempt)
    no_journal(store, early_attempt)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 50000)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == early


def test_exact_boundary_is_not_excluded(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    expected, attempt = stored(store, 1, '2026-10-09T09:30:00+08:00', latest=True)
    no_journal(store, attempt)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == expected


def test_nested_late_timestamp_cannot_replace_top_level_early_time(tmp_path):
    from v4.manager_research.workspace_projection import digest
    store = ManagerResearchStore(tmp_path/'store')
    expected, attempt = stored(store, 1, '2026-10-09T09:28:00+08:00')
    no_journal(store, attempt)
    expected['workspace']['generated_at'] = '2026-10-10T10:00:00+08:00'
    expected['sha256'] = digest({k:v for k,v in expected.items() if k != 'sha256'})
    path = store.root/'workspace_plans'/DATE/(expected['run_id']+'.json')
    # A noncanonical legacy document must take the original full-object gate.
    payload = {'workspace': expected['workspace'], **{k:v for k,v in expected.items() if k != 'workspace'}}
    path.write_text(json.dumps(payload))
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == expected


def test_unknown_prefix_still_obeys_full_body_budget(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 5):
        product, attempt = stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000, latest=n == 4)
        no_journal(store, attempt)
        payload = {'workspace': product['workspace'], **{k:v for k,v in product.items() if k != 'workspace'}}
        raw = json.dumps(payload).encode()
        (store.root/'workspace_plans'/DATE/(product['run_id']+'.json')).write_bytes(raw)
        if n == 4:
            (store.root/'workspace_plans'/DATE/'latest.json').write_bytes(raw)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    with pytest.raises(ValueError):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_late_missing_journal_symlink_never_qualifies_for_prefix_exclusion(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00')
    no_journal(store, attempt)
    path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
    external = tmp_path/'external.json'
    external.write_bytes(path.read_bytes())
    path.unlink(); path.symlink_to(external)
    with pytest.raises((ValueError, OSError)):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_wrong_date_header_does_not_silently_hide_invalid_archive(tmp_path):
    from v4.manager_research.workspace_projection import digest
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00')
    no_journal(store, attempt)
    product['target_trade_date'] = '20261008'
    product['sha256'] = digest({k:v for k,v in product.items() if k != 'sha256'})
    path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
    path.write_text(json.dumps(product, sort_keys=True, separators=(',', ':')))
    with pytest.raises(ValueError, match='HISTORY_PLAN_IDENTITY_INVALID'):
        history.select_plan(store, DATE, history.boundary_context(DATE))
