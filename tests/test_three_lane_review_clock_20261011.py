"""Real saved plan bytes; clock/context routing with a source-reader seam."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import pytest

from v4.manager_research import workspace as w
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import FLAGS, build_workspace, digest


@pytest.mark.parametrize('saved_attempt', [False, True])
def test_explicit_current_review_advances_clock_but_auto_preserves_saved_asof(tmp_path, monkeypatch, saved_attempt):
    target = '20261012'
    saved_clock = datetime.fromisoformat('2026-10-11T10:00:00+08:00')
    read_clock = datetime.fromisoformat('2026-10-11T12:00:00+08:00')
    context = plan_context(target, now=saved_clock)
    bindings = dict(plan_date=target, selection_date=target, announcement_date='20261009')
    value = build_workspace(target, catalyst=dict(status='READY_EMPTY', cards=[], gaps=[]), plan_context=context)
    value['date_bindings'] = bindings
    product = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=target,
        run_id='1'*32, owner='ManagerResearchJobService.refresh_workspace_plan',
        execution_kind='MANUAL_REFRESH', generated_at=saved_clock.isoformat(),
        input_identity=value['input_identity'], workspace=value, **FLAGS)
    product['sha256'] = digest(product)
    store = ManagerResearchStore(tmp_path / 'state')
    path = store.root / 'workspace_plans' / target / 'latest.json'
    store._write_atomic(path, product)
    if saved_attempt:
        attempt = w.seal_attempt(dict(schema_version=w.ATTEMPT_SCHEMA, target_trade_date=target,
            owner=product['owner'], run_id=product['run_id'], execution_kind='MANUAL_REFRESH',
            input_identity=product['input_identity'], state='PARTIAL', failure_reasons=['SOURCE_GAPS'],
            started_at='2026-10-11T09:59:00+08:00', finished_at='2026-10-11T10:01:00+08:00', **FLAGS))
        for name in (product['run_id'], 'latest'):
            store._write_atomic(store.root / 'workspace_plan_runs' / target / (name+'.json'), attempt)
    original = path.read_bytes()
    calls = []
    def read_sources(service, date, *, include_saved, context, **kwargs):
        calls.append(deepcopy(context))
        return build_workspace(date, catalyst=dict(status='READY_EMPTY', cards=[], gaps=[]), plan_context=context)
    monkeypatch.setattr(w, '_compute_workspace', read_sources)
    service = SimpleNamespace(store=store)
    current = w.get_workspace(service, target, view='dynamic', now=read_clock)
    automatic = w.get_workspace(service, target, view='auto', now=read_clock)
    assert current['read_context']['mode'] == 'CURRENT_DYNAMIC_PREVIEW'
    assert current['read_context']['as_of'] == read_clock.isoformat()
    assert calls[0]['research_cutoff'] == read_clock.isoformat()
    assert calls[1]['research_cutoff'] == saved_clock.isoformat()
    assert automatic['read_context']['as_of'] == saved_clock.isoformat()
    assert path.read_bytes() == original
    assert current['plan_product']['consumed'] is saved_attempt  # Missing exact attempt cannot be hidden.
