"""Current owner integration; captured positives are external local fixtures.

No test makes a network request. Fixture time/window changes are synthetic and
do not replace the separately reviewed real positive-control capture.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import os
import socket
import sys
import hashlib
import importlib.util
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from v4.manager_research import announcement_source as source
from v4.manager_research import workspace_announcements as owner
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.hkex_runtime import assemble_hkex_announcements_api, create_hkex_service
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS

PREFIX = '/api/v4/manager/research/announcements'
NATIVE_MASTER = owner._master


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('NETWORK_NOT_ALLOWED_IN_ADAPTER_TEST')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)


@pytest.fixture
def setup_owner(tmp_path, monkeypatch):
    evidence = Path(os.environ.get('HKEX_EVIDENCE_ROOT', '/not-configured'))
    receipt = evidence / 'positive-control-00002-20260901-20260928/original_owner_attempt.json'
    if not receipt.is_file():
        pytest.skip('Set HKEX_EVIDENCE_ROOT to the frozen local evidence root')
    saved = json.loads(receipt.read_bytes())
    original_store = MaterialStore(receipt.parent / 'materials')
    q = saved['result']['queries'][0]
    mapping = source.read_response(original_store, q['mapping_ref'])
    html = source.read_response(original_store, q['directory_ref'])
    pdfs = {d['row']['url']: source.read_response(original_store, d['body_ref'])
            for d in saved['result']['documents']}
    state = {'mode': 'html', 'calls': []}

    def transport(url, **kwargs):
        state['calls'].append((url, kwargs.get('method', 'GET')))
        if 'activestock_sehk_e.json' in url:
            raw = mapping
        elif url in pdfs:
            raw = pdfs[url]
        elif state['mode'] == 'modern':
            if url.endswith('/ncms/js/titlesearch.js'):
                raw = (evidence / 'saved/selection_script_ref.js').read_bytes()
            elif url.endswith('/ncms/js/titlesearch_research.js'):
                raw = (evidence / 'saved/protocol_ref.js').read_bytes()
            elif 'titleSearchServlet.do' in url:
                raw = (evidence / 'saved/directory_ref.json').read_bytes()
            else:
                raw = (evidence / 'saved/form_directory_ref.html').read_bytes()
                raw = raw.replace(b'2026-09-24', b'2026-09-25')
        else:
            raw = html
        return SourceResponse(url=url, final_url=url, status_code=200, body=raw,
                              headers={}, retrieved_at='2026-10-23T14:47:30+00:00')

    class FixtureProvider(HkexOfficialProvider):
        def collect_announcement_batch(self, **kwargs):
            return source.collect_batch(self, budget=source.CaptureBudget(interval=0), **kwargs)

    materials = MaterialStore(tmp_path / 'state/materials')
    provider = FixtureProvider(transport=transport, material_store=materials)
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'state'), None, provider,
        material_store=materials, workspace_security_master_root=tmp_path / 'master')
    monkeypatch.setattr(owner, '_now', lambda: '2026-10-23T15:00:00+00:00')
    names = {'HK.00002': {'name': 'CLP HOLDINGS'}}
    witness = {'owner': 'TEST_VERIFIED_MASTER', 'source_date': '20260922', 'artifact_sha256': 'a' * 64}
    monkeypatch.setattr(owner, '_master', lambda *_: (deepcopy(names), deepcopy(witness)))

    def plan(date, now=None):
        previous = '20260925' if date == '20260928' else '20260922'
        close = f'{previous[:4]}-{previous[4:6]}-{previous[6:]}T16:10:00+08:00'
        return dict(plan_trade_date=date, market_session=previous, market_session_close=close,
                    focus_window_start=close, research_cutoff=now.isoformat(), **FLAGS)
    monkeypatch.setattr(owner, 'plan_context', plan)
    app = FastAPI()
    assemble_hkex_announcements_api(app, manager_root=tmp_path / 'state',
                                    security_master_root=tmp_path / 'master', service=service)
    with TestClient(app) as client:
        yield client, service, state, tmp_path
    assert service._closed


def refresh(client, date='20260923'):
    response = client.post(PREFIX + '/refresh', params={'target_trade_date': date, 'issuer_codes': 'HK.00002'})
    assert response.status_code == 200, response.text
    return response.json()


def test_factory_same_original_store_and_shutdown(tmp_path):
    service = create_hkex_service(manager_root=tmp_path / 'state', security_master_root=tmp_path / 'master')
    assert service.observation_reader is None
    assert service._material_store is service.source_provider._material_store
    assert not service._active
    service.close()
    assert service._closed


def test_targeted_provider_uses_original_default_budget_only(monkeypatch):
    received = []
    monkeypatch.setattr(source, 'collect_batch', lambda *a, **kw: received.append(kw))
    provider = HkexOfficialProvider(transport=lambda *a, **kw: None)
    provider.collect_announcement_batch(context={'targeted_source_window': {'start': 'frozen'}}, issuers=[])
    budget = received[-1]['budget']
    assert (budget.seconds, budget.max_requests, budget.interval) == (45, 57, 0.5)
    explicit = source.CaptureBudget(seconds=1, max_requests=1)
    provider.collect_announcement_batch(context={'targeted_source_window': {}}, issuers=[], budget=explicit)
    assert received[-1]['budget'] is explicit
    provider.collect_announcement_batch(context={}, issuers=[])
    assert received[-1]['budget'] is None


@pytest.mark.parametrize('captured,accepted', [('2026-10-23T15:00:00+00:00', True),
                                             ('2026-10-23T15:00:01+00:00', False)])
def test_native_master_capture_cutoff_is_preserved(tmp_path, monkeypatch, captured, accepted):
    from types import SimpleNamespace
    from upstreams.v3_shared_data.shared_data import hk_security_master
    names = {'HK.00002': {'name': 'CLP HOLDINGS', 'captured_at': captured}}
    monkeypatch.setattr(hk_security_master, 'load_verified_hk_security_master',
                        lambda *a: (names, {'artifact_sha256': 'a' * 64}))
    service = SimpleNamespace(_workspace_security_master_root=tmp_path / 'master')
    context = {'market_session': '20260922', 'research_cutoff': '2026-10-23T15:00:00+00:00'}
    if accepted:
        assert NATIVE_MASTER(service, context)[0] == names
    else:
        with pytest.raises(ValueError, match='MASTER_IDENTITY_OR_TIME_INVALID'):
            NATIVE_MASTER(service, context)


def test_html_refresh_directory_body_and_late_acquisition_readonly(setup_owner):
    client, service, state, _ = setup_owner
    result = refresh(client)
    assert result['source_scope'] == 'HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET'
    assert result['coverage']['observed_document_count'] == 1
    rows = result['official_documents']
    assert len(rows) == 1 and rows[0]['body_status'] == 'BODY_PARSED'
    assert rows[0]['late_acquisition'] is True
    assert rows[0]['published_at'].startswith('2026-09-23')
    assert rows[0]['retrieved_at'].startswith('2026-10-23')
    calls = deepcopy(state['calls'])
    query = {'target_trade_date': '20260923', 'scope_id': result['scope_id']}
    readback = client.get(PREFIX, params=query).json()
    assert readback['product_identity'] == result['product_identity']
    body = client.get(PREFIX + '/body', params={**query,
        'product_sha256': result['product_identity']['sha256'], 'event_id': rows[0]['event_id']})
    assert body.status_code == 200, body.text
    value = body.json()
    assert value['status'] == 'BODY_PARSED'
    assert sum(len(p['text']) for p in value['pages']) > 100
    assert value['document_sha256'] == rows[0]['document_sha256']
    assert state['calls'] == calls


@pytest.mark.parametrize('attack', ['product', 'event', 'scope', 'date', 'arbitrary-url'])
def test_body_requires_exact_consumed_product_and_event(setup_owner, attack):
    client, service, state, _ = setup_owner
    result = refresh(client)
    query = dict(target_trade_date='20260923', scope_id=result['scope_id'],
        product_sha256=result['product_identity']['sha256'], event_id=result['official_documents'][0]['event_id'])
    if attack == 'product': query['product_sha256'] = 'b' * 64
    elif attack == 'event': query['event_id'] = 'c' * 64
    elif attack == 'scope': query['scope_id'] = 'd' * 64
    elif attack == 'date': query['target_trade_date'] = '20260924'
    else: query['url'] = 'https://evil.test/a.pdf'
    calls = deepcopy(state['calls'])
    assert client.get(PREFIX + '/body', params=query).status_code in {404, 409, 422}
    assert state['calls'] == calls


@pytest.mark.parametrize('attack', ['cross-origin', 'fetch-site', 'json-body', 'extra-query', 'duplicate-issuer', 'foreign-code', 'too-many'])
def test_refresh_rejects_unsafe_or_unbounded_request_before_provider(setup_owner, attack):
    client, _, state, _ = setup_owner
    params = [('target_trade_date', '20260923'), ('issuer_codes', 'HK.00002')]
    headers = {}; kwargs = {}
    if attack == 'cross-origin': headers['Origin'] = 'https://evil.test'
    elif attack == 'fetch-site': headers['Sec-Fetch-Site'] = 'cross-site'
    elif attack == 'json-body': kwargs['json'] = {'url': 'https://evil.test/a.pdf'}
    elif attack == 'extra-query': params.append(('blob', 'a' * 64))
    elif attack == 'duplicate-issuer': params.append(('issuer_codes', 'HK.00002'))
    elif attack == 'foreign-code': params[1] = ('issuer_codes', 'US.AAPL')
    else: params = [('target_trade_date', '20260923')] + [('issuer_codes', f'HK.{n:05d}') for n in range(1, 26)]
    assert client.post(PREFIX + '/refresh', params=params, headers=headers, **kwargs).status_code in {400, 403, 422}
    assert state['calls'] == []


def test_master_failure_is_not_bypassed(setup_owner, monkeypatch):
    client, _, state, _ = setup_owner
    def failed(*_): raise ValueError('ANNOUNCEMENT_NATIVE_MASTER_IDENTITY_OR_TIME_INVALID')
    monkeypatch.setattr(owner, '_master', failed)
    response = client.post(PREFIX + '/refresh', params={'target_trade_date': '20260923', 'issuer_codes': 'HK.00002'})
    assert response.status_code == 409
    assert 'MASTER' in response.text and state['calls'] == []


def test_modern_targeted_empty_and_tampered_query_revalidation(setup_owner):
    client, service, state, _ = setup_owner
    state['mode'] = 'modern'
    result = refresh(client, '20260928')
    assert result['coverage']['failed_issuers'] == []
    assert result['official_documents'] == []
    path = service.store.root / 'workspace_announcements/20260928/issuer_subsets' / result['scope_id'] / 'latest.json'
    product = service.store._read(path)
    assert product['queries'][0]['directory_protocol'] == 'HKEX_SERVLET_ALL_SELECTION_V2'
    assert product['queries'][0]['directory_exhaustion_verified'] is True
    product['queries'][0]['directory_pages'][0]['request']['url'] += '&stockId=3'
    service.store._write_atomic(path, owner._seal(product))
    calls = deepcopy(state['calls'])
    readback = client.get(PREFIX, params={'target_trade_date': '20260928', 'scope_id': result['scope_id']}).json()
    assert readback['status'] == 'READBACK_FAILED'
    assert state['calls'] == calls


def test_tampered_original_pdf_fails_closed_without_repair(setup_owner):
    client, service, state, tmp_path = setup_owner
    result = refresh(client)
    path = service.store.root / 'workspace_announcements/20260923/issuer_subsets' / result['scope_id'] / 'latest.json'
    product = service.store._read(path)
    blob = product['documents'][0]['body_ref']['blob_sha256']
    (tmp_path / 'state/materials/blobs' / blob).write_bytes(b'altered source')
    calls = deepcopy(state['calls'])
    value = client.get(PREFIX, params={'target_trade_date': '20260923', 'scope_id': result['scope_id']}).json()
    assert value['status'] == 'READBACK_FAILED'
    assert state['calls'] == calls


@pytest.fixture
def deployment(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'ops/deploy_hkex_announcements_bounded.py'
    spec = importlib.util.spec_from_file_location('test_bounded_hkex_deployment', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = tmp_path / 'old'
    (old / 'app').mkdir(parents=True)
    plist = tmp_path / 'api.plist'
    plist.write_bytes(b'active-original')
    pre = dict(parent=str(old), candidate=str(tmp_path / 'new'), api_plist=str(plist),
        runtime_python=sys.executable, runtime_pid=123, workbench_store_root=str(tmp_path / 'workbench'),
        api_plist_sha256=hashlib.sha256(plist.read_bytes()).hexdigest())
    (tmp_path / 'DEPLOYMENT_PRECONDITIONS.json').write_text(json.dumps(pre))
    return module.Deployment(tmp_path), plist


def test_deployment_stale_active_release_fails_inside_both_locks_before_copy(deployment, monkeypatch):
    deploy, plist = deployment
    held = []
    @contextmanager
    def lock(name):
        held.append(name)
        yield
    helper = SimpleNamespace(
        shared_api_release_lock=lambda *a, **kw: lock('api'),
        announcement_flash_cutover_guard=lambda *a, **kw: lock('flash'),
        read_active_release=lambda *a: {'release_root': '/some/newer/release'},
    )
    monkeypatch.setattr(deploy, 'source_guards', lambda: None)
    monkeypatch.setattr(deploy, 'runtime', lambda *a: {'pid': 123})
    monkeypatch.setattr(deploy, 'helper', lambda: helper)
    with pytest.raises(AssertionError, match='ACTIVE_RELEASE_CHANGED'):
        deploy.prepare()
    assert held == ['api', 'flash']
    assert not deploy.new.exists() and plist.read_bytes() == b'active-original'


def test_deployment_activation_requires_review_gate_before_mutation(deployment, monkeypatch):
    deploy, plist = deployment
    monkeypatch.setattr(deploy, 'verify', lambda *a: (object(), {}, {}))
    with pytest.raises(FileNotFoundError):
        deploy.cutover()
    assert plist.read_bytes() == b'active-original'


def test_deployment_rollback_will_not_overwrite_a_newer_plist(deployment, monkeypatch):
    deploy, plist = deployment
    @contextmanager
    def lock(*a, **kw): yield
    helper = SimpleNamespace(shared_api_release_lock=lock, announcement_flash_cutover_guard=lock)
    monkeypatch.setattr(deploy, 'verify', lambda *a: (helper, {'proposed_plist_sha256': 'not-current'}, {}))
    with pytest.raises(AssertionError, match='PLIST_DRIFT_NO_OVERWRITE'):
        deploy.cutover(rollback=True)
    assert plist.read_bytes() == b'active-original'


def test_prepare_emits_sorted_delta_accepted_by_retained_helper(deployment, monkeypatch):
    from ops import api_release_integration as retained
    deploy, plist = deployment
    source_root = deploy.root / 'reviewed-source'
    source_root.mkdir()
    rows = []
    for path in ['z.py', 'a.py']:
        (source_root / path).write_text('unchanged reviewed bytes\n')
        rows.append(dict(path=path, before_sha256=None,
                         after_sha256=hashlib.sha256((source_root / path).read_bytes()).hexdigest()))
    active = dict(release_root=str(deploy.old), app_root=str(deploy.old / 'app'), release_id='old',
        release_manifest_path=str(deploy.old / 'release-manifest.json'), release_manifest_sha256='a' * 64,
        application_inventory_sha256='b' * 64, application_inventory_entry_count=1)
    deploy.pre.update(source_worktree=str(source_root), sources=rows, parent_manifest_sha256='a' * 64)
    @contextmanager
    def lock(*a, **kw): yield
    class ValidatedBeforeAnyActivation(Exception): pass
    def bounded_build(**kwargs):
        receipt = json.loads(kwargs['delta_receipt_path'].read_bytes())
        checked = retained._validate_delta_receipt(receipt, base_identity=active)
        assert [row['path'] for row in checked] == ['a.py', 'z.py']
        raise ValidatedBeforeAnyActivation()
    helper = SimpleNamespace(shared_api_release_lock=lock, announcement_flash_cutover_guard=lock,
        read_active_release=lambda *a: active, _diff_proof=retained._diff_proof,
        _base_binding=retained._base_binding, DELTA_SCHEMA_VERSION=retained.DELTA_SCHEMA_VERSION,
        build_integrated_app=bounded_build)
    monkeypatch.setattr(deploy, 'source_guards', lambda: None)
    monkeypatch.setattr(deploy, 'runtime', lambda *a: {'pid': 123})
    monkeypatch.setattr(deploy, 'helper', lambda: helper)
    with pytest.raises(ValidatedBeforeAnyActivation):
        deploy.prepare()
    assert plist.read_bytes() == b'active-original'
