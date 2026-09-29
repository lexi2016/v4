from __future__ import annotations
import copy, json, runpy, threading
from pathlib import Path
import pytest
from v4.manager_research.contracts import normalise_observation_input
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore, StoreConflict, StoreError
FIXTURE = runpy.run_path(str(Path(__file__).parents[1] / 'test_manager_research_catalyst_service.py'))
DATE = '20260908'

def raw():
    return dict(
        target_trade_date=DATE,
        stage_id='STAGE_0935_0940',
        market='HK_CONNECT',
        status='READY',
        rows=[FIXTURE['observation']()],
    )

def built():
    inp = normalise_observation_input(raw())
    return (
        inp,
        ManagerResearchJobService._build_product(
            inp,
            inp['rows'],
            {inp['rows'][0]['code']: FIXTURE['Provider']().collect()},
        ),
    )

def job_for(inp, service):
    return dict(
        job_id=service._job_id(inp),
        target_trade_date=DATE,
        input_identity=inp['input_identity'],
        status='QUEUED',
        attempt=1,
        generation='test-generation',
    )

def test_declared_research_labels_are_not_order_capability(tmp_path):
    inp, p = built()
    store = ManagerResearchStore(tmp_path)
    store.write_product(p)
    assert store.read_product(DATE, inp['input_identity'])['status'] == 'READY'

def test_research_context_does_not_exempt_nested_trade_flags(tmp_path):
    _, p = built()
    p['rows'][0]['research_recommendation']['investment_advice']['nested'] = {'orders_sent': True}
    with pytest.raises((ValueError, StoreError)):
        ManagerResearchStore(tmp_path).write_product(p)

def test_arbitrary_buy_action_is_not_research_label(tmp_path):
    _, p = built()
    p['rows'][0]['observation']['action'] = 'BUY'
    with pytest.raises((ValueError, StoreError)):
        ManagerResearchStore(tmp_path).write_product(p)

def test_get_cache_migration_never_changes_bytes(tmp_path):
    inp, p = built()
    p.pop('recommendation_summary', None)
    for row in p['rows']:
        row.pop('research_recommendation', None)
    store = ManagerResearchStore(tmp_path)
    store.write_product(p)
    before = {str(x.relative_to(tmp_path)): x.read_bytes() for x in tmp_path.rglob('*') if x.is_file()}
    svc = ManagerResearchJobService(store, lambda _: raw(), None)
    try:
        assert svc.get(DATE)['product'] is not None
    finally:
        svc.close()
    after = {str(x.relative_to(tmp_path)): x.read_bytes() for x in tmp_path.rglob('*') if x.is_file()}
    assert after == before

@pytest.mark.parametrize(
    'field,value',
    [
        ('target_trade_date', '20260907'),
        ('market', 'A_SHARE'),
        ('stage_id', 'STAGE_0925'),
        ('input_identity', 'wrong'),
        ('input_source_sha256', 'b' * 64),
        ('input_row_count', 2),
    ],
)
def test_exact_cache_metadata_is_revalidated(tmp_path, field, value):
    inp, p = built()
    p[field] = value
    store = ManagerResearchStore(tmp_path)
    path = store._product_path(DATE, inp['input_identity'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p))
    svc = ManagerResearchJobService(store, lambda _: raw(), None)
    try:
        result = svc.get(DATE)
        assert result['status'] == 'CANNOT_CONFIRM'
        assert result['product'] is None
    finally:
        svc.close()

def test_same_key_concurrent_writes_conflict_instead_of_overwrite(tmp_path):
    a = ManagerResearchStore(tmp_path)
    b = ManagerResearchStore(tmp_path)
    go = threading.Barrier(2)
    out = []

    def put(s, tag):
        go.wait(2)
        try:
            s.write_product(dict(target_trade_date=DATE, input_identity='key', writer=tag))
            out.append('ok')
        except StoreConflict:
            out.append('conflict')
    threads = [threading.Thread(target=put, args=(a, 'a')), threading.Thread(target=put, args=(b, 'b'))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
        assert not t.is_alive()
    assert sorted(out) == ['conflict', 'ok']

def test_receipt_failure_cannot_publish_new_ready_product(tmp_path, monkeypatch):
    inp, _ = built()
    store = ManagerResearchStore(tmp_path)
    svc = ManagerResearchJobService(store, lambda _: raw(), FIXTURE['Provider']())
    monkeypatch.setattr(svc, '_collect_events', lambda *a, **kw: None)

    def fail(*a, **kw):
        raise OSError('simulated receipt failure')
    monkeypatch.setattr(store, 'write_receipt', fail)
    try:
        svc._run_job(inp, job_for(inp, svc))
        r = svc.get(DATE)
        assert r['status'] != 'READY'
        assert r['product'] is None
        assert r['job']['status'] == 'FAILED'
    finally:
        svc.close()

def test_cancelled_generation_cannot_write_late_progress_or_commit(tmp_path):
    inp, p = built()
    store = ManagerResearchStore(tmp_path)
    svc = ManagerResearchJobService(store, lambda _: raw(), None)
    j = job_for(inp, svc)
    store.write_job(j)
    svc.cancel(j['job_id'], DATE)
    try:
        with pytest.raises(StoreConflict):
            store.write_job({**j, 'status': 'RUNNING'})
        with pytest.raises(StoreConflict):
            store.commit_result(
                {**j, 'status': 'READY'},
                p,
                {'job_id': j['job_id'], 'target_trade_date': DATE, 'input_identity': inp['input_identity']},
            )
        assert store.read_job(j['job_id'])['status'] == 'CANCELLED'
        assert store.read_product(DATE, inp['input_identity']) is None
    finally:
        svc.close()

def test_event_refresh_merges_into_latest_financial_product(tmp_path, monkeypatch):
    inp, p = built()
    store = ManagerResearchStore(tmp_path)
    store.write_product(p)
    provider = FIXTURE['Provider']()
    svc = ManagerResearchJobService(store, lambda _: raw(), provider)

    def collect(*args, **kwargs):
        new = copy.deepcopy(p)
        new['rows'][0]['thesis_cn'] = 'NEW_FINANCIAL_FACTS'
        store.replace_product(new)
        return provider.collect_events(observations=inp['rows'])
    monkeypatch.setattr(svc, '_collect_events', collect)
    j = job_for(inp, svc)
    j['job_id'] = svc._event_job_id(inp)
    try:
        svc._run_event_refresh_job(inp, j, p)
        assert store.read_product(
            DATE,
            inp['input_identity'],
        )['rows'][0]['thesis_cn'] == 'NEW_FINANCIAL_FACTS'
    finally:
        svc.close()

def test_commit_atomically_binds_product_receipt_and_job(tmp_path):
    inp, p = built()
    store = ManagerResearchStore(tmp_path)
    svc = ManagerResearchJobService(store, lambda _: raw(), None)
    j = job_for(inp, svc)
    store.write_job(j)
    receipt = {
        'job_id': j['job_id'],
        'target_trade_date': DATE,
        'input_identity': inp['input_identity'],
        'status': 'READY',
    }
    try:
        store.commit_result({**j, 'status': 'READY'}, p, receipt)
        assert store.read_job(j['job_id'])['status'] == 'READY'
        assert store.read_product(DATE, inp['input_identity']) == p
        assert store.read_receipt(DATE, j['job_id']) == receipt
        with pytest.raises(StoreConflict):
            store.write_job({**j, 'status': 'RUNNING'})
    finally:
        svc.close()

def test_two_instances_cannot_admit_same_attempt(tmp_path):
    inp, _ = built()
    a = ManagerResearchStore(tmp_path)
    b = ManagerResearchStore(tmp_path)
    j = dict(
        job_id='job',
        target_trade_date=DATE,
        input_identity=inp['input_identity'],
        status='QUEUED',
        attempt=1,
        generation='A',
    )
    a.admit_job(j)
    with pytest.raises(StoreConflict):
        b.admit_job({**j, 'generation': 'B'})

def test_exception_text_does_not_leak_secret_to_product(tmp_path):

    class Provider:

        def collect(self, **kw):
            raise RuntimeError('Authorization: Bearer FAKE_SECRET_FOR_TEST')
    svc = ManagerResearchJobService(ManagerResearchStore(tmp_path), lambda _: raw(), Provider())
    try:
        result = svc._collect_one(DATE, '2026-09-08T09:40:00+08:00', raw()['rows'][0])
        assert 'FAKE_SECRET_FOR_TEST' not in json.dumps(result)
        assert result['reason'] == 'SOURCE_PROVIDER_FAILED'
    finally:
        svc.close()
