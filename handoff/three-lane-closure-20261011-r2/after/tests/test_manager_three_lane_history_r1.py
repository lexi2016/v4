"""Isolated real store/history behavior. Synthetic plans are not market evidence."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest

from v4.manager_research import workspace as w
from v4.manager_research import workspace_history as history
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import SCHEMA, FLAGS, HK, digest, build_workspace

DATE = '20261009'
OWNER = 'ManagerResearchJobService.refresh_workspace_plan'


def stored(store, number, generated, *, started=None, finished=None, padding=0, latest=False, workspace_body=None):
    run = f'{number:032x}'
    at = datetime.fromisoformat(generated)
    body = dict(schema_version=SCHEMA, target_trade_date=DATE,
        semantic_version='three-lane-history-fixture', stocks=[], themes=[], materials=[],
        company_events=[], focus_symbols=[], rejected_relations=[], briefing={}, summary={},
        market_screen={}, announcement_review={}, plan_context=plan_context(DATE, now=at),
        input_identity='e' * 64, gaps=[], synthetic_padding='x' * padding, **FLAGS)
    if workspace_body is not None:
        body = deepcopy(workspace_body)
    product = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=DATE, run_id=run,
        generated_at=generated, owner=OWNER, execution_kind='MANUAL_REFRESH',
        input_identity=body['input_identity'], workspace=body, **FLAGS)
    product['sha256'] = digest(product)
    store._write_atomic(store.root/'workspace_plans'/DATE/(run+'.json'), product)
    if latest:
        store._write_atomic(store.root/'workspace_plans'/DATE/'latest.json', product)
    attempt = w.seal_attempt(dict(schema_version=w.ATTEMPT_SCHEMA, target_trade_date=DATE,
        run_id=run, owner=OWNER, state='SUCCEEDED_EMPTY', execution_kind='MANUAL_REFRESH',
        started_at=started or generated, finished_at=finished or generated,
        last_success_at=generated, input_identity=body['input_identity'],
        input_coverage={}, summary={}, failure_reasons=[], **FLAGS))
    w.validate_attempt(attempt, DATE)
    store._write_atomic(store.root/'workspace_plan_runs'/DATE/(run+'.json'), attempt)
    return product, attempt


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*.json')}


def test_many_large_retrospective_runs_use_same_owner_journals_without_scan_overflow(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 7):
        stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000, latest=n == 6)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    before = hashes(store.root)
    reads = []
    original = store._io.read_bytes
    def read(path, **kw):
        data = original(path, **kw)
        reads.append((path, len(data)))
        return data
    monkeypatch.setattr(store._io, 'read_bytes', read)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) is None
    assert sum(size for path, size in reads if path.startswith('workspace_plans/')) < 65536
    assert any(path.startswith('workspace_plan_runs/') for path, _ in reads)
    assert hashes(store.root) == before


def test_late_journals_do_not_mask_one_valid_earlier_plan(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    expected, _ = stored(store, 1, '2026-10-09T09:28:00+08:00', padding=18000)
    for n in range(2, 7):
        stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000, latest=n == 6)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    got = history.select_plan(store, DATE, history.boundary_context(DATE))
    assert got == expected


def test_start_before_cutoff_finish_after_cutoff_is_not_pruned(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    expected, _ = stored(store, 1, '2026-10-09T09:28:00+08:00',
        started='2026-10-09T09:27:00+08:00', finished='2026-10-09T09:31:00+08:00')
    stored(store, 2, '2026-10-10T10:00:00+08:00', latest=True)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == expected


@pytest.mark.parametrize('corrupt', ['sha', 'owner', 'run', 'date'])
def test_invalid_journal_cannot_authorize_exclusion(tmp_path, corrupt):
    store = ManagerResearchStore(tmp_path/'store')
    _, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00')
    stored(store, 2, '2026-10-10T10:01:00+08:00', latest=True)
    changed = deepcopy(attempt)
    if corrupt == 'sha':
        changed['sha256'] = '0' * 64
    else:
        changed[{'owner': 'owner', 'run': 'run_id', 'date': 'target_trade_date'}[corrupt]] = {
            'owner': 'another-owner', 'run': 'f' * 32, 'date': '20261008'}[corrupt]
        changed = w.seal_attempt(changed)
    store._write_atomic(store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json'), changed)
    with pytest.raises(ValueError):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_missing_journal_falls_back_to_full_verified_product(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    expected, attempt = stored(store, 1, '2026-10-09T09:28:00+08:00')
    (store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')).unlink()
    stored(store, 2, '2026-10-10T10:00:00+08:00', latest=True)
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) == expected


def test_eligible_product_still_checks_full_product_sha(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    product, _ = stored(store, 1, '2026-10-09T09:28:00+08:00')
    path = store.root/'workspace_plans'/DATE/(product['run_id']+'.json')
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"gaps":[]', b'"gaps":["tampered"]', 1))
    stored(store, 2, '2026-10-10T10:00:00+08:00', latest=True)
    with pytest.raises(ValueError, match='HISTORY_PLAN_IDENTITY_INVALID'):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_same_run_journal_symlink_is_not_followed(tmp_path):
    store = ManagerResearchStore(tmp_path/'store')
    _, attempt = stored(store, 1, '2026-10-10T10:00:00+08:00')
    stored(store, 2, '2026-10-10T10:01:00+08:00', latest=True)
    path = store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')
    other = tmp_path/'outside.json'
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    with pytest.raises((ValueError, OSError)):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_remaining_body_budget_is_enforced_before_read(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path/'store')
    for n in range(1, 5):
        product, attempt = stored(store, n, f'2026-10-10T10:0{n}:00+08:00', padding=18000, latest=n == 4)
        (store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json')).unlink()
        # R2 excludes canonical late envelopes before loading bodies. Keep this
        # original budget assertion on a genuine UNKNOWN legacy layout instead.
        legacy = {'workspace': product['workspace'], **{k:v for k,v in product.items() if k != 'workspace'}}
        raw = json.dumps(legacy).encode()
        (store.root/'workspace_plans'/DATE/(product['run_id']+'.json')).write_bytes(raw)
        if n == 4:
            (store.root/'workspace_plans'/DATE/'latest.json').write_bytes(raw)
    monkeypatch.setattr(history, '_MAX_SCAN_BYTES', 65536)
    reads = []
    original = store._io.read_bytes
    def read(path, **kw):
        data = original(path, **kw)
        reads.append((path, len(data)))
        return data
    monkeypatch.setattr(store._io, 'read_bytes', read)
    with pytest.raises(ValueError):
        history.select_plan(store, DATE, history.boundary_context(DATE))
    assert sum(size for path, size in reads if path.startswith('workspace_plans/')) <= 65536


def test_saved_owner_readback_preserves_execution_context_and_rejects_mismatch(tmp_path):
    from ops.run_manager_announcement_cycle import _saved_owner_readback
    from v4.manager_research.workspace_plan_autorun import owner_plan_readback
    store = ManagerResearchStore(tmp_path/'store')
    product, attempt = stored(store, 1, '2026-10-09T10:00:01+08:00',
        started='2026-10-09T10:00:00+08:00', finished='2026-10-09T10:00:02+08:00')
    execution = dict(trigger_kind='SCHEDULED', timing='LATE_CATCHUP',
        scheduled_for='2026-10-09T10:00:00+08:00', started_at=attempt['started_at'],
        finished_at=attempt['finished_at'], natural_run_verified=False)
    product['execution_context'] = deepcopy(execution)
    product['sha256'] = digest({k: v for k, v in product.items() if k != 'sha256'})
    attempt['execution_context'] = deepcopy(execution)
    attempt = w.seal_attempt(attempt)
    store._write_atomic(store.root/'workspace_plan_runs'/DATE/(attempt['run_id']+'.json'), attempt)
    service = SimpleNamespace(store=store)
    got = _saved_owner_readback(service, DATE, product)
    result = owner_plan_readback(got, DATE, expected_kind='MANUAL_REFRESH')
    assert result['status'] == 'MATERIALIZED'
    assert result['execution_context'] == execution
    got['plan_product']['execution_context']['timing'] = 'UNCLASSIFIED'
    with pytest.raises(ValueError, match='PLAN_OWNER_PRODUCT_ATTEMPT_READBACK_MISMATCH'):
        owner_plan_readback(got, DATE, expected_kind='MANUAL_REFRESH')
    assert product['execution_context'] == execution


def frozen_workspace(global_manifest):
    from v4.manager_research.existing_materials import project_archive
    payload = dict(archive_date='20261008', articles=[dict(article_id='synthetic-frozen-ref',
        source_title='Synthetic research fixture', body='Same article and acquisition clocks.',
        themes=['DATA_CENTER'], published_at='2026-10-08T12:00:00+08:00',
        retrieved_at='2026-10-08T12:01:00+08:00', available_at='2026-10-08T12:02:00+08:00')])
    receipt = dict(synthetic_fixture=True, payload_sha256=digest(payload))
    binding = dict(source_id='V35_RESEARCH_DATA_ROOT', status='VERIFIED',
        source_root='/synthetic/research', source_date='20261008', slot='', mode='LIVE',
        manifest_path='manifest.json', write_policy='read_only', recommendation_status='RESEARCH_ONLY',
        production_allowed=False, buy_gate_updated=False, orders_sent=False,
        payload_path='research/archives/20261008.json',
        receipt_path='receipts/research/archives/20261008.json',
        payload_sha256=digest(payload), receipt_sha256=digest(receipt),
        manifest_entry_sha256=digest(payload), manifest_sha256=global_manifest)
    materials, gaps = project_archive(payload, binding, '20261008')
    return build_workspace(DATE,
        catalyst=dict(target_trade_date=DATE, status='NOT_MATERIALIZED', cards=[], gaps=[]),
        materials=materials,
        plan_context=plan_context(DATE, now=datetime.fromisoformat('2026-10-09T09:28:00+08:00')),
        source_gaps=gaps)


def read_frozen_workspace(tmp_path, monkeypatch, before, after):
    """Real history/store gates; only original owner I/O is a synthetic boundary."""
    store = ManagerResearchStore(tmp_path/'store')
    stored(store, 1, '2026-10-09T09:28:00+08:00', latest=True, workspace_body=before)
    def recompute(service, date, *, include_saved, context):
        assert date == DATE and include_saved is False
        assert context == before['plan_context']
        return deepcopy(after)
    monkeypatch.setattr(w, '_compute_workspace', recompute)
    before_files = hashes(store.root)
    result = history.read_history(SimpleNamespace(store=store), DATE)
    assert hashes(store.root) == before_files
    return result


def test_history_accepts_same_semantics_after_global_registry_only_change(tmp_path, monkeypatch):
    before, after = frozen_workspace('e'*64), frozen_workspace('f'*64)
    assert before['input_identity'] == after['input_identity']
    assert before['materials'] != after['materials']
    result = read_frozen_workspace(tmp_path, monkeypatch, before, after)
    assert result['plan_product']['consumed'] is True
    assert result['plan_product']['status'] == 'CURRENT'
    assert result['read_context']['mode'] == 'HISTORICAL_AS_OF'
    assert result['materials'] == after['materials']


@pytest.mark.parametrize('change', ['payload', 'receipt', 'date', 'path', 'pit', 'raw_source', 'other_manifest'])
def test_frozen_field_gate_still_rejects_semantic_changes_even_if_component_hash_were_equal(tmp_path, monkeypatch, change):
    before, after = frozen_workspace('e'*64), frozen_workspace('f'*64)
    row = after['materials'][0]
    ref = row['source_refs'][0]
    if change in {'payload','receipt','date','path'}:
        key = {'payload':'payload_sha256','receipt':'receipt_sha256',
               'date':'source_date','path':'payload_path'}[change]
        ref[key] = {'payload':'a'*64,'receipt':'b'*64,'date':'20261007',
                    'path':'research/archives/20261007.json'}[change]
    elif change == 'pit':
        row['available_at'] = '2026-10-09T10:00:00+08:00'
    elif change == 'raw_source':
        row['source_row']['manifest_sha256'] = 'a'*64
    else:
        row['source_refs'].append(dict(owner='HK_PANEL_OWNER', manifest_sha256='a'*64))
    # Deliberately hold the outer prehash equal: frozen-field validation is an
    # independent guard and must not be disabled by semantic normalization.
    assert before['input_identity'] == after['input_identity']
    result = read_frozen_workspace(tmp_path, monkeypatch, before, after)
    assert result['plan_product']['consumed'] is False
    assert 'HISTORY_FROZEN_PROJECTION_CHANGED' in result['gaps']
