from copy import deepcopy
from types import SimpleNamespace

import pytest

from v4.manager_research import store as s
from v4.manager_research import workspace as w


DATE = '20261002'
RUN = 'a' * 32
TIME = '2026-10-03T00:00:00+00:00'


def _current():
    component = w.identity_component({'source': 'issue35-readback-commit-order'})
    components = {'fixture_source': component}
    return dict(target_trade_date=DATE,
        input_identity=w.digest([component['sha256']]),
        input_identity_schema=w.INPUT_IDENTITY_SCHEMA,
        input_identity_components=components,
        date_bindings={'selection_date': DATE, 'announcement_date': DATE},
        semantic_version='issue35-commit-order-fixture',
        plan_context={'research_cutoff': TIME}, gaps=[], stocks=[],
        existing_material_coverage={}, summary={}, lanes=[],
        **w.FLAGS)


def _latest_plan(store):
    return store.root/'workspace_plans'/DATE/'latest.json'


def _latest_attempt(store):
    return store.root/'workspace_plan_runs'/DATE/'latest.json'


def _run_attempt(store):
    return store.root/'workspace_plan_runs'/DATE/(RUN+'.json')


def _refresh(store):
    return w.refresh_workspace_plan(SimpleNamespace(store=store), DATE)


def _pin_run(monkeypatch):
    monkeypatch.setattr(w, '_now', lambda: TIME)
    monkeypatch.setattr(w, 'uuid4', lambda: SimpleNamespace(hex=RUN))
    monkeypatch.setattr(w, 'get_workspace', lambda *args, **kwargs: _current())


def test_rejected_candidate_readback_never_publishes_latest_or_success(tmp_path, monkeypatch):
    store = s.ManagerResearchStore(tmp_path)
    _pin_run(monkeypatch)
    read = store._read
    write = store._write_atomic
    writes = []

    def recording_write(path, value):
        if 'workspace_plan_runs' in path.parts:
            writes.append(deepcopy(dict(value)))
        return write(path, value)

    monkeypatch.setattr(store, '_write_atomic', recording_write)

    def wrong_readback(view, date, current):
        # The commit view contains the candidate for this private check, while
        # the actual public pointer and owner lifecycle remain unpublished.
        assert view._read(_latest_plan(view))['run_id'] == RUN
        assert read(_latest_plan(store)) is None
        running = read(_latest_attempt(store))
        assert running['state'] == 'RUNNING'
        assert running['input_identity'] == current['input_identity']
        return {**current, 'plan_product': {
            'status': 'CURRENT', 'run_id': RUN, 'sha256': '0' * 64, 'consumed': True}}

    monkeypatch.setattr(w, '_readback_plan', wrong_readback)
    with pytest.raises(ValueError, match='WORKSPACE_PLAN_SAVE_READBACK_FAILED'):
        _refresh(store)

    assert not _latest_plan(store).exists()
    assert {row['state'] for row in writes} <= {'RUNNING', 'FAILED'}
    assert read(_latest_attempt(store))['state'] == 'FAILED'


def test_mismatched_running_owner_attempt_blocks_success_commit(tmp_path, monkeypatch):
    store = s.ManagerResearchStore(tmp_path)
    _pin_run(monkeypatch)
    read = store._read
    latest_attempt_path = _latest_attempt(store)

    def mismatched_running_read(path):
        row = read(path)
        if (path == latest_attempt_path and isinstance(row, dict)
                and row.get('state') == 'RUNNING' and row.get('input_identity')):
            changed = deepcopy(row)
            changed['input_identity'] = 'f' * 64
            changed['sha256'] = w.digest({k: v for k, v in changed.items() if k != 'sha256'})
            return changed
        return row

    monkeypatch.setattr(store, '_read', mismatched_running_read)
    writes = []
    write = store._write_atomic

    def recording_write(path, value):
        if 'workspace_plan_runs' in path.parts:
            writes.append(deepcopy(dict(value)))
        return write(path, value)

    monkeypatch.setattr(store, '_write_atomic', recording_write)
    with pytest.raises(ValueError, match='WORKSPACE_PLAN_ATTEMPT_READBACK_FAILED'):
        _refresh(store)

    assert not _latest_plan(store).exists()
    assert {row['state'] for row in writes} <= {'RUNNING', 'FAILED'}
    assert read(_latest_attempt(store))['state'] == 'FAILED'
