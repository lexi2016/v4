"""Synthetic archives; executes the real SafeRoot, store and history selector."""
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path

import pytest

from v4.manager_research.store import ManagerResearchStore
from v4.manager_research import workspace as w
from v4.manager_research import workspace_history as history
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import FLAGS, build_workspace, digest

DATE = '20261009'
OWNER = 'ManagerResearchJobService.refresh_workspace_plan'


def _plan(run, generated='2026-10-10T10:00:00+08:00', padding=0):
    context = plan_context(DATE, now=datetime.fromisoformat(generated))
    body = build_workspace(DATE, catalyst=dict(status='READY_EMPTY', cards=[], gaps=[]),
                           plan_context=context)
    body['synthetic_test_padding'] = 'x' * padding
    row = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=DATE,
        run_id=run, owner=OWNER, execution_kind='MANUAL_REFRESH', generated_at=generated,
        input_identity=body['input_identity'], workspace=body, **FLAGS)
    return dict(row, sha256=digest(row))


def _attempt(run, started='2026-10-10T09:59:00+08:00', *, state='SUCCEEDED', **extra):
    row = dict(schema_version=w.ATTEMPT_SCHEMA, target_trade_date=DATE, run_id=run,
        owner=OWNER, state=state, execution_kind='MANUAL_REFRESH', started_at=started,
        finished_at='2026-10-10T10:01:00+08:00', failure_reasons=[], **FLAGS)
    row.update(extra)
    return w.seal_attempt(row)


def _save(store, row, attempt=None, *, latest=False):
    directory = store.root / 'workspace_plans' / DATE
    store._write_atomic(directory / (row['run_id'] + '.json'), row)
    if latest:
        store._write_atomic(directory / 'latest.json', row)
    if attempt is not None:
        store._write_atomic(store.root / 'workspace_plan_runs' / DATE /
                            (row['run_id'] + '.json'), attempt)


def _archive_hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / 'workspace_plans' / DATE).iterdir()}


def test_late_seven_large_archives_do_not_exhaust_scan_or_change_bytes(tmp_path):
    store = ManagerResearchStore(tmp_path / 'synthetic-state')
    for index in range(6):
        run = f'{index + 1:032x}'
        _save(store, _plan(run, padding=21 * 1024 * 1024), _attempt(run), latest=index == 5)
    before = _archive_hashes(store.root)
    assert sum(p.stat().st_size for p in (store.root / 'workspace_plans' / DATE).iterdir()) > history._MAX_SCAN_BYTES
    assert history.select_plan(store, DATE, history.boundary_context(DATE)) is None
    assert _archive_hashes(store.root) == before
    assert history._MAX_SCAN_BYTES == 64 * 1024 * 1024
    assert history._MAX_PLAN_BYTES == 32 * 1024 * 1024


@pytest.mark.parametrize('started', ['2026-10-09T09:29:00+08:00', '2026-10-09T09:30:00+08:00'])
def test_early_or_exact_boundary_start_is_not_excluded_by_late_finish(tmp_path, started):
    store = ManagerResearchStore(tmp_path / 'state')
    run = 'a' * 32
    row = _plan(run, '2026-10-09T09:30:00+08:00')
    _save(store, row, _attempt(run, started))
    selected = history.select_plan(store, DATE, history.boundary_context(DATE))
    assert selected['sha256'] == row['sha256']


def test_missing_journal_uses_original_body_validation(tmp_path):
    store = ManagerResearchStore(tmp_path / 'state')
    row = _plan('b' * 32, '2026-10-09T09:29:00+08:00')
    _save(store, row)
    assert history.select_plan(store, DATE, history.boundary_context(DATE))['sha256'] == row['sha256']
    # The selector does not authorize consumption; the original owner gate remains.
    with pytest.raises(ValueError, match='WORKSPACE_PLAN_ATTEMPT_MISSING'):
        w.verified_plan_attempt(store, row)


@pytest.mark.parametrize('mutation', ['sha', 'owner', 'run', 'date'])
def test_invalid_journal_never_proves_historical_absence(tmp_path, mutation):
    store = ManagerResearchStore(tmp_path / 'state')
    run = 'c' * 32
    row = _plan(run, '2026-10-09T09:29:00+08:00')
    attempt = _attempt(run)
    if mutation == 'sha':
        attempt['sha256'] = '0' * 64
    else:
        attempt[{'owner': 'owner', 'run': 'run_id', 'date': 'target_trade_date'}[mutation]] = {
            'owner': 'OTHER_OWNER', 'run': 'd' * 32, 'date': '20261008'}[mutation]
        attempt = w.seal_attempt(attempt)
    _save(store, row, attempt)
    with pytest.raises(ValueError, match='HISTORY_PLAN_ATTEMPT'):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_valid_postcutoff_receipt_cannot_bypass_latest_checksum(tmp_path):
    store = ManagerResearchStore(tmp_path / 'state')
    run = 'e' * 32
    row = _plan(run)
    _save(store, row, _attempt(run), latest=True)
    bad = deepcopy(row)
    bad['sha256'] = '0' * 64
    store._write_atomic(store.root / 'workspace_plans' / DATE / 'latest.json', bad)
    with pytest.raises(ValueError, match='HISTORY_PLAN_IDENTITY_INVALID'):
        history.select_plan(store, DATE, history.boundary_context(DATE))


def test_later_attempt_latest_does_not_hide_preserved_early_plan(tmp_path):
    store = ManagerResearchStore(tmp_path / 'state')
    run = 'f' * 32
    row = _plan(run, '2026-10-09T09:29:00+08:00')
    _save(store, row, latest=True)
    store._write_atomic(store.root / 'workspace_plan_runs' / DATE / 'latest.json',
                        _attempt('1' * 32, state='FAILED'))
    assert history.select_plan(store, DATE, history.boundary_context(DATE))['sha256'] == row['sha256']


def test_journal_symlink_does_not_authorize_exclusion(tmp_path):
    store = ManagerResearchStore(tmp_path / 'state')
    run = '2' * 32
    _save(store, _plan(run))
    folder = store.root / 'workspace_plan_runs' / DATE
    folder.mkdir(parents=True)
    outside = tmp_path / 'outside.json'
    import json
    outside.write_text(json.dumps(_attempt(run)))
    (folder / (run + '.json')).symlink_to(outside)
    with pytest.raises((OSError, ValueError)):
        history.select_plan(store, DATE, history.boundary_context(DATE))
