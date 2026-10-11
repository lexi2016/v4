"""Independent read-only candidate review; all fixtures are synthetic."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path

import pytest

from test_manager_three_lane_history_r1 import DATE, stored, hashes
from v4.manager_research import workspace_history as history
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import digest


def overwrite_synthetic(store, product, *, latest=False, workspace_first=False):
    product = deepcopy(product)
    product['sha256'] = digest({k:v for k,v in product.items() if k != 'sha256'})
    if workspace_first:
        value = {'workspace': product['workspace'], **{k:v for k,v in product.items() if k != 'workspace'}}
    else:
        value = product
    raw = json.dumps(value, ensure_ascii=False, sort_keys=not workspace_first, separators=(',', ':')).encode()
    path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
    path.write_bytes(raw)
    if latest:
        (path.parent/'latest.json').write_bytes(raw)
    return product, raw


def missing_journal(store, attempt):
    (store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')).unlink()


def test_multibyte_utf8_cut_at_probe_end_does_not_force_full_late_body(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 7):
        product, attempt = stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000)
        missing_journal(store, attempt)
        for offset in range(3):
            product['workspace']['announcement_review'] = {'label': 'x'*offset+'研'*6000}
            product, raw = overwrite_synthetic(store, product, latest=n == 6)
            try:
                raw[:history._MAX_HEADER_BYTES].decode('utf-8')
            except UnicodeDecodeError:
                break
        else:
            pytest.fail('test must end its fixed-size probe in a partial codepoint')
        assert history._exclusion_header(store, DATE, product['run_id']+'.json') is not None
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    before = hashes(store.root)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) is None
    assert hashes(store.root) == before


def test_unknown_layout_really_reads_and_validates_the_complete_early_product(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-09T09:28:00+08:00', padding=20000)
    missing_journal(store, attempt)
    expected, raw = overwrite_synthetic(store, product, workspace_first=True)
    assert history._exclusion_header(store, DATE, product['run_id']+'.json') is None
    reads = []
    original = store._io.read_bytes
    def read(path, **kwargs):
        result = original(path, **kwargs)
        reads.append((path, len(result)))
        return result
    monkeypatch.setattr(store._io, 'read_bytes', read)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == expected
    assert (f"workspace_plans/{DATE}/{product['run_id']}.json", len(raw)) in reads


@pytest.mark.parametrize('mutation', ['sha', 'run', 'safety', 'cutoff'])
def test_top_level_metadata_never_admits_a_corrupt_or_inconsistent_candidate(tmp_path, mutation):
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-09T09:28:00+08:00')
    missing_journal(store, attempt)
    if mutation == 'sha':
        product['workspace']['summary']['changed'] = True
        path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
        path.write_text(json.dumps(product, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    elif mutation == 'run':
        original_run = product['run_id']
        product['run_id'] = 'f'*32
        product, raw = overwrite_synthetic(store, product)
        (store.root/'workspace_plans'/DATE/(original_run+'.json')).write_bytes(raw)
    elif mutation == 'safety':
        product['workspace']['production_allowed'] = True
        overwrite_synthetic(store, product)
    else:
        product['workspace']['plan_context']['research_cutoff'] = '2026-10-09T09:31:00+08:00'
        overwrite_synthetic(store, product)
    with pytest.raises((ValueError, OSError)):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_forged_latest_alias_sha_does_not_stand_in_for_immutable_bytes(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    late, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00', latest=True)
    missing_journal(store, attempt)
    forged = deepcopy(late)
    forged['generated_at'] = '2026-10-09T09:28:00+08:00'
    from v4.manager_research.workspace_plan import plan_context
    forged['workspace']['plan_context'] = plan_context(DATE, now=datetime.fromisoformat(forged['generated_at']))
    # Retain the latest document's claimed SHA, but write different immutable bytes.
    (store.root/'workspace_plans'/DATE/(forged['run_id']+'.json')).write_text(
        json.dumps(forged, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    with pytest.raises(ValueError, match='HISTORY_PLAN_IDENTITY_INVALID'):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_same_cutoff_and_generation_with_different_valid_products_remains_ambiguous(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    for n in (1, 2):
        _, attempt = stored(store, n, '2026-10-09T09:28:00+08:00')
        missing_journal(store, attempt)
    with pytest.raises(ValueError, match='HISTORY_SAVED_PLAN_AMBIGUOUS'):
        history.select_plan(store, DATE, history.boundary_context(DATE))


@pytest.mark.parametrize('kind', ['latest_symlink', 'ancestor_symlink', 'latest_fifo'])
def test_probe_rejects_unsafe_paths_before_candidate_classification(tmp_path, kind):
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00', latest=True)
    missing_journal(store, attempt)
    folder = store.root/'workspace_plans'/DATE
    if kind == 'latest_symlink':
        external = tmp_path/'outside.json'; external.write_bytes((folder/'latest.json').read_bytes())
        (folder/'latest.json').unlink(); (folder/'latest.json').symlink_to(external)
    elif kind == 'ancestor_symlink':
        external = tmp_path/'outside'; folder.rename(external); folder.symlink_to(external, target_is_directory=True)
    else:
        (folder/'latest.json').unlink(); os.mkfifo(folder/'latest.json')
    with pytest.raises((ValueError, OSError)):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_exact_boundary_still_performs_product_checksum_validation(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-09T09:30:00+08:00', latest=True)
    missing_journal(store, attempt)
    path = store.root/'workspace_plans'/DATE/'latest.json'
    product['workspace']['summary']['tampered'] = True
    path.write_text(json.dumps(product, sort_keys=True, separators=(',', ':')))
    with pytest.raises(ValueError, match='HISTORY_PLAN_IDENTITY_INVALID'):
        history.select_plan(store, DATE, history.boundary_context(DATE))
