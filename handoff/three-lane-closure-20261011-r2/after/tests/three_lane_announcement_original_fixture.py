"""Synthetic source fixtures; real import/GET routes, store and consumer validation.

No original announcement bytes, live owner state, network fetch or trading
operation are used. The clock and source catalog read are injected; product,
handoff, receipt, workspace and HTTP consumer checks use the application code.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import manager_research_router as api
from ops import run_manager_daily_announcement as cli
from v4.manager_research import announcement_analysis as analysis
from v4.manager_research import announcement_selection as selection
from v4.manager_research import workspace_announcements as consumer
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace_projection import FLAGS, digest

TARGET = "20261008"
PUBLICATION = "2026-10-07"
NOW = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)


class _FixtureService(ManagerResearchJobService):
    def __init__(self, root):
        super().__init__(ManagerResearchStore(root), None, None)
        self.catalogs = {}

    def get_announcement_date_catalog(self, target, publication):
        if (target, publication) in self.catalogs:
            return deepcopy(self.catalogs[(target, publication)])
        return {"target_trade_date": target, "publication_date": publication,
            "status": "NOT_RUN", "readback_status": "NOT_RUN", "catalog": None,
            "source_scope": "EASTMONEY_HK_DATE_CATALOG", "gaps": []}

    def get_announcement_analysis(self, target, publication=None):
        return analysis.read(self, target, publication)

    def import_announcement_analysis(self, product):
        return analysis.import_product(self, product)

    def get_workspace(self, target, **kwargs):
        kwargs.setdefault("now", NOW)
        return super().get_workspace(target, **kwargs)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(api, "datetime", Clock)
    monkeypatch.setattr(consumer, "_now", lambda: NOW.isoformat())
    service = _FixtureService(tmp_path / "research-state")
    monkeypatch.setattr(service, 'refresh_announcements',
        lambda *args, **kwargs: pytest.fail('GET started announcement capture'))
    monkeypatch.setattr(service, 'refresh_workspace_plan',
        lambda *args, **kwargs: pytest.fail('GET materialized a plan'))
    yield service
    service.close()


def _write_complete_evidence(state_root: Path, target: str, publication: str,
                             run_id: str, *, listing_at: str, body_at: str) -> Path:
    evidence = state_root / "announcement_agent_runs" / run_id / "evidence"
    bodies = evidence / "body_batch" / "bodies"
    bodies.mkdir(parents=True)
    art_code = "AN" + publication.replace("-", "") + "1234567890"
    title = "Single complete test notice"
    listing_sha = "a" * 64
    listing_ref = {"request": {"url": f"https://np-anotice-stock.eastmoney.com/api/security/ann?date={publication}"},
        "blob_sha256": "b" * 64, "body_sha256": "c" * 64,
        "retrieved_at": listing_at}
    body_text = "One complete captured page."
    body_text_sha = hashlib.sha256(body_text.encode()).hexdigest()
    body_raw_sha = "d" * 64
    body_ref = {"request": {"url": f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art_code}&client_source=web&page_index=1"},
        "blob_sha256": "e" * 64, "body_sha256": body_raw_sha,
        "retrieved_at": body_at}
    issuer = {"code": "HK.01234", "source_stock_code": "01234", "market_code": "116",
        "ann_type": "H", "name": "Test issuer"}
    listing = {"art_code": art_code, "title": title, "page_index": 1, "item_index": 0,
        "notice_date": publication + " 00:00:00", "display_time": publication + " 09:00:00:000",
        "raw_body_sha256": listing_sha, "source_ref": listing_ref,
        "source_issuer_codes": [issuer]}
    catalog = {"target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "connect_eligibility_status": "NOT_ASSESSED", "hkex_first_publication_verified": False,
        "captured_row_count": 1, "captured_page_count": 1, "manager_consumer_row_count": 1,
        "manager_source_identity_count": 1, "manager_source_codes": [issuer["code"]],
        "run_id": run_id, "manager_consumer_rows": [listing]}
    catalog["sha256"] = digest(catalog)
    catalog_read = {"schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": target, "publication_date": publication,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "readback_status": "VERIFIED", "catalog": catalog}
    catalog_path = evidence / "catalog_read.json"
    catalog_path.write_text(json.dumps(catalog_read, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")

    article_receipt = {"schema": "v4.manager_research.source_bound_announcement_body.v1",
        "art_code": art_code, "target_trade_date": target, "publication_date": publication,
        "body_status": "COMPLETE_CONTENT_API_BODY", "listing_source_ref": listing_ref,
        "listing_raw_body_sha256": listing_sha, "source_issuer_codes": [issuer],
        "body_text": body_text, "body_text_sha256": body_text_sha,
        "content_api_pages": [{"page_index": 1}], "pdf": None,
        "semantic_status": "NOT_REVIEWED", "first_hkex_publication_time": "CANNOT_CONFIRM",
        "original_point_in_time_availability": "CANNOT_CONFIRM"}
    article_path = bodies / f"{art_code}.json"
    article_path.write_text(json.dumps(article_receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    article_sha = hashlib.sha256(article_path.read_bytes()).hexdigest()
    body_row = {"art_code": art_code, "title": title, "body_status": "COMPLETE_CONTENT_API_BODY",
        "content_page_count": 1, "body_text": body_text, "body_text_sha256": body_text_sha,
        "capture_receipt_sha256": article_sha,
        "pages": [{"page_index": 1, "page_total": 1, "notice_date": publication + " 00:00:00",
            "text": body_text, "text_sha256": body_text_sha, "raw_body_sha256": body_raw_sha,
            "source_ref": body_ref}], "attachment_url": None, "pdf_sha256": None,
        "transport_body_status": "COMPLETE_CONTENT_API_BODY"}
    identity_material = {"target_trade_date": target, "publication_date": publication,
        "catalog_run_id": run_id, "catalog_sha256": catalog["sha256"],
        "article_ids": [art_code], "listing_body_sha256s": [listing_sha]}
    input_identity = hashlib.sha256((json.dumps(identity_material, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    body_manifest = {"schema": "v4.manager_research.source_bound_announcement_body_corpus.v1",
        "target_trade_date": target, "publication_date": publication, "catalog_run_id": run_id,
        "catalog_sha256": catalog["sha256"], "input_identity_sha256": input_identity,
        "body_status_counts": {"COMPLETE_CONTENT_API_BODY": 1},
        "article_receipts": [{"art_code": art_code, "status": "COMPLETE_CONTENT_API_BODY",
            "body_status": "COMPLETE_CONTENT_API_BODY", "body_path": f"bodies/{art_code}.json",
            "body_file_sha256": article_sha, "content_api_pages_captured": 1,
            "error_code": None, "listing_raw_body_sha256": listing_sha,
            "listing_source_ref": listing_ref, "source_issuer_codes": [issuer]}]}
    manifest_path = evidence / "body_corpus_manifest.json"
    manifest_path.write_text(json.dumps(body_manifest, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    body = {"schema": "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3",
        "target_notice_date": publication, "article_count": 1, "rows": [body_row],
        "input_identity_sha256": input_identity, "source_manifest_sha256": manifest_sha,
        "transport_complete_body_count": 1}
    body_path = evidence / "body_corpus.json"
    body_path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest()
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1",
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS", "target_trade_date": target,
        "publication_date": publication, "catalog_run_id": run_id,
        "catalog_sha256": catalog["sha256"], "input_identity_sha256": input_identity,
        "article_rows": 1, "terminal_article_receipts": 1,
        "body_corpus": "body_corpus.json", "body_corpus_manifest": "body_corpus_manifest.json",
        "body_corpus_sha256": body_sha, "body_corpus_manifest_sha256": manifest_sha,
        "body_status_counts": {"COMPLETE_CONTENT_API_BODY": 1}}
    batch_path = evidence / "body_batch_receipt.json"
    batch_path.write_text(json.dumps(batch, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    batch_sha = hashlib.sha256(batch_path.read_bytes()).hexdigest()
    capture = {"schema_version": "v4.manager_research.announcement_daily_capture.v1",
        "status": batch["status"], "evidence_run_id": run_id,
        "target_trade_date": target, "publication_date": publication,
        "catalog_run_id": run_id, "catalog_product_sha256": catalog["sha256"],
        "catalog_read_file_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "body_corpus_file_sha256": body_sha,
        "body_corpus_manifest_file_sha256": manifest_sha,
        "body_batch_receipt_sha256": batch_sha,
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    (evidence / "capture_receipt.json").write_text(json.dumps(capture, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return evidence


def _fixture(service, *, target=TARGET, publication=PUBLICATION, run_id='1' * 32,
             reviewed=True, listing_at='2026-10-07T21:00:00+00:00',
             body_at='2026-10-07T21:01:00+00:00', reviewed_at='2026-10-08T00:00:00+00:00',
             reader_gap=False, no_decisions=False, disposition='SELECTED_EVENT'):
    root = service.store.root
    evidence = _write_complete_evidence(root, target, publication, run_id,
        listing_at=listing_at, body_at=body_at)
    catalog_read = json.loads((evidence / 'catalog_read.json').read_text())
    service.catalogs[(target, publication)] = catalog_read
    listing = catalog_read['catalog']['manager_consumer_rows'][0]
    semantic = {'schema': 'v4.announcement-semantic-catalog.v2',
        'status': 'PASS_SYNTHETIC_FIXTURE_ONLY', 'target_research_date': target,
        'target_notice_date': publication, 'row_count': 1, 'records': [{
            'art_code': listing['art_code'], 'title': listing['title'],
            'issuer_codes': [{'code': row['code']} for row in listing['source_issuer_codes']],
            'security_scope': 'HK_LISTED',
        }]}
    if reader_gap:
        semantic['records'][0]['evidence'] = {'reader_fact_record': {
            'body_read_complete': False, 'source_content_gap': True}}
    semantic_path = root / ('semantic_' + target + '.json')
    semantic_path.write_text(json.dumps(semantic, sort_keys=True))
    args = SimpleNamespace(target_date=target, publication_date=publication,
        catalog_read=str(evidence / 'catalog_read.json'), semantic_catalog=str(semantic_path),
        body_corpus=str(evidence / 'body_corpus.json'), decisions=None, review_receipt=None, out=None)
    base = cli._build(args, reviewed=False, include_product=True)['product']
    if reader_gap and not reviewed:
        # R3 legacy products recorded NOT_ASSESSED only in the extension.
        base['records'][0].pop('selection_status')
        base['sha256'] = digest({key: value for key, value in base.items() if key != 'sha256'})
    row = base['records'][0]
    decisions = [{'art_code': row['art_code'],
        'issuer_codes': [item['code'] for item in row['issuer_codes']],
        'security_scope': row['security_scope'],
        'semantic_record_sha256': row['semantic_record_sha256'],
        'body_record_sha256': row['body_record_sha256'],
        'disposition': 'NOT_ASSESSED' if reader_gap else disposition,
        'selection_basis': 'NOT_ASSESSED' if reader_gap else ('OPERATING_EVENT' if disposition=='SELECTED_EVENT' else disposition),
        'reason': 'Synthetic fixture disposition only.', 'risk_notes': []}]
    if not reviewed:
        product = selection.attach_extension(base, selection.make_extension(base, decisions))
        analysis.validate_product(product, target_trade_date=target,
                                  publication_date=publication, catalog=catalog_read['catalog'])
        return product, None
    decisions_path = root / ('decisions_' + target + '.json')
    decisions_path.write_text(json.dumps({'article_decisions': decisions}, sort_keys=True))
    reviewer = {'schema_version': 'v4.manager_research.announcement_agent_review.v1',
        'review_conclusion': 'PASS', 'decision_status': 'NOT_ASSESSED' if no_decisions else 'EXPLICIT_DISPOSITIONS',
        'decision_payload_sha256': None if no_decisions else digest(decisions), 'target_trade_date': target,
        'publication_date': publication, 'evidence_run_id': run_id,
        'reader_identity': 'synthetic-reader', 'reviewer_identity': 'synthetic-reviewer',
        'reviewed_at': reviewed_at, 'catalog_product_sha256': catalog_read['catalog']['sha256'],
        'semantic_catalog_sha256': hashlib.sha256(semantic_path.read_bytes()).hexdigest(),
        'body_corpus_sha256': hashlib.sha256((evidence / 'body_corpus.json').read_bytes()).hexdigest()}
    reviewer_path = root / ('reviewer_' + target + '.json')
    reviewer_path.write_text(json.dumps(reviewer, sort_keys=True))
    registration = cli._register_handoff(SimpleNamespace(target_date=target,
        publication_date=publication, evidence_run_id=run_id, research_state_root=str(root),
        semantic_catalog=str(semantic_path), reviewer_output=str(reviewer_path),
        decisions=None if no_decisions else str(decisions_path), parent_task_id='synthetic-parent',
        reader_identity='synthetic-reader', reviewer_identity='synthetic-reviewer'))
    return json.loads((evidence / 'analysis_product.json').read_text()), registration


def _client(service):
    app = FastAPI()
    app.include_router(api.create_manager_research_router(service))
    return TestClient(app)


def _import(client, registration):
    response = client.post('/api/v4/manager/research/announcements/analysis/import',
        headers={'Origin': 'http://testserver'}, json={
            'schema_version': 'v4.manager_research.announcement_analysis_import_ref.v1',
            'evidence_run_id': registration['evidence_run_id'],
            'handoff_manifest_sha256': registration['handoff_manifest_sha256'],
            'product_sha256': registration['product_sha256']})
    assert response.status_code == 200, response.text
    return response.json()


def _snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_import_analysis_get_and_real_workspace_get_share_exact_product(owner):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        imported = _import(client, registered)
        assert imported['consumption_validation']['validation_status'] == 'VERIFIED'
        initial = _snapshot(owner.store.root)
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 200, response.text
        readback = response.json()
        response = client.get('/api/v4/manager/research/workspace',
            params={'date': TARGET, 'view': 'dynamic', 'announcement_date': '20261007',
                    'selection_date': '20261007'})
        assert response.status_code == 200, response.text
        workspace = response.json()
        consumed = workspace['announcement_reviewed_analysis']['products'][0]
        expected = {
            'product_sha256': product['sha256'],
            'source_manifest_sha256': product['source_manifest_sha256'],
            'evidence_run_id': registered['evidence_run_id'],
            'handoff_manifest_sha256': registered['handoff_manifest_sha256'],
            'owner_import_receipt_sha256': readback['owner_import_receipt']['sha256'],
        }
        for key, value in expected.items():
            assert imported['consumption_validation'][key] == value
            assert readback['consumption_validation'][key] == value
            assert consumed[key] == value
        assert consumed['status'] == 'CONSUMED'
        assert consumed['failure_stage'] is None
        assert consumed['research_references'][0]['stock_code'] == 'HK.01234'
        assert workspace['plan_context']['plan_trade_date'] == TARGET
        assert workspace['plan_context']['announcement_publication_date'] == PUBLICATION
        assert workspace['date_bindings']['selection_date'] == '20261007'
        assert _snapshot(owner.store.root) == initial


@pytest.mark.parametrize('fixture_options,pending', [({'reader_gap': True}, 1), ({'no_decisions': True}, None)])
def test_imported_unassessed_research_is_pending_not_successful_empty(owner, fixture_options, pending):
    _, registered = _fixture(owner, **fixture_options)
    with _client(owner) as client:
        imported = _import(client, registered)
        assert imported['consumption_validation']['not_assessed_stock_count'] == pending
        initial = _snapshot(owner.store.root)
        response = client.get('/api/v4/manager/research/workspace',
            params={'date': TARGET, 'view': 'dynamic', 'announcement_date': '20261007'})
        assert response.status_code == 200, response.text
        channel = response.json()['daily_channels']['channels'][0]
        assert channel['status'] == 'PARTIAL'
        assert channel['candidate_count'] is None
        assert channel['pending_count'] == pending
        assert channel['rows'] == []
        assert 'ANNOUNCEMENT_SELECTION_NOT_ASSESSED' in channel['gaps']
        assert _snapshot(owner.store.root) == initial


def test_explicit_not_selected_is_successful_empty(owner):
    _, registered = _fixture(owner, disposition='NOT_SELECTED')
    with _client(owner) as client:
        _import(client, registered)
        channel = client.get('/api/v4/manager/research/workspace',
            params={'date': TARGET, 'view': 'dynamic', 'announcement_date': '20261007'}).json()['daily_channels']['channels'][0]
        assert channel['status'] == 'READY_EMPTY'
        assert channel['candidate_count'] == 0
        assert channel['pending_count'] == 0


def test_evening_default_reads_same_target_publication_as_explicit(owner, monkeypatch):
    from v4.manager_research import workspace
    evening = datetime.fromisoformat('2026-10-08T18:10:00+08:00')
    monkeypatch.setattr(consumer, '_now', lambda: evening.isoformat())
    _, registered = _fixture(owner,target='20261009',publication='2026-10-08',
        listing_at='2026-10-08T08:00:00+00:00',body_at='2026-10-08T08:01:00+00:00',
        reviewed_at='2026-10-08T10:00:00+00:00')
    with _client(owner) as client:
        _import(client, registered)
    default = workspace.get_workspace(owner,'20261009',now=evening,include_saved=False)
    explicit = workspace.get_workspace(owner,'20261009',now=evening,include_saved=False,announcement_date='20261008')
    assert default['date_bindings'] == explicit['date_bindings']
    assert default['daily_channels']['channels'][0]['status'] == 'READY'
    assert default['daily_channels']['channels'][0]['rows'] == explicit['daily_channels']['channels'][0]['rows']


@pytest.mark.parametrize('failure', [RuntimeError, ImportError])
def test_us_reader_failure_does_not_hide_consumed_announcement(owner, failure):
    from v4.manager_research import workspace
    _, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
    def unavailable(*args, **kwargs):
        raise failure('Synthetic US reader unavailable')
    owner._workspace_us_market_reader = SimpleNamespace(read_exact_session=unavailable)
    value = workspace.get_workspace(owner,TARGET,now=NOW,include_saved=False,announcement_date='20261007')
    assert value['daily_channels']['channels'][0]['status'] == 'READY'
    assert value['us_market_attention']['status'] == 'SOURCE_FAILED'
    assert 'US_MARKET_READER_FAILED:'+failure.__name__ in value['us_market_attention']['gaps']


def test_missing_original_archive_is_not_empty_connect_selection(owner, monkeypatch):
    from v4.manager_research import workspace, connect_selection
    codes=['HK.00001']
    scope=dict(status='OWNER_VERIFIED',gaps=[],codes=codes,target_trade_date=TARGET,
        membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
        source=dict(market='HK_CONNECT',role='HK_CONNECT_FULL_MARKET_AUTHORITY',source_date=TARGET,sha256='f'*64),
        identity=digest([TARGET,codes,'f'*64]))
    monkeypatch.setattr(connect_selection,'read_scope',lambda _:scope)
    monkeypatch.setattr(consumer,'read_selection_inputs',lambda *a,**k:dict(
        materials=[],rejections=[],gaps=[],captures=[dict(target_trade_date=TARGET,run_id='d'*32,
            sha256='e'*64,readback_status='VERIFIED',source='HKEX_OFFICIAL')],status='READY_EMPTY',
        input_identity='c'*64,reviewed_analysis={},**FLAGS))
    value=workspace.get_workspace(owner,TARGET,now=NOW,include_saved=False)
    assert value['selection_diagnostics']['status']=='READY'
    channel=value['daily_channels']['channels'][1]
    assert channel['status']=='PARTIAL'
    assert channel['candidate_count'] is None
    assert 'RESEARCH_ARCHIVE_READER_NOT_BOUND' in channel['gaps']


def test_valid_current_product_isolated_from_invalid_legacy_window_neighbor(owner):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        legacy, _ = _fixture(owner, target='20261007', publication='2026-10-06',
            run_id='2' * 32, reviewed=False,
            listing_at='2026-10-06T21:00:00+00:00', body_at='2026-10-06T21:01:00+00:00')
        path = analysis.product_path(owner.store, '20261007', '2026-10-06')
        owner.store._write_atomic(path, legacy)
        before = path.read_bytes()
        old = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': '20261007', 'publication_date': '2026-10-06'}).json()
        assert old['analysis']['status'] == 'VERIFIED'
        assert old['analysis']['product_sha256'] == legacy['sha256']
        assert old['owner_import_receipt'] is None
        result = consumer.read_reviewed_analysis_references(owner, plan_context(TARGET, now=NOW))
        assert result['status'] == 'PARTIAL'
        current = next(row for row in result['products'] if row['target_trade_date'] == TARGET)
        rejected = next(row for row in result['products'] if row['target_trade_date'] == '20261007')
        assert current['status'] == 'CONSUMED'
        assert current['product_sha256'] == product['sha256']
        assert rejected['product_sha256'] == legacy['sha256']
        assert rejected['source_manifest_sha256'] == legacy['source_manifest_sha256']
        assert rejected['publication_date'] == '2026-10-06'
        assert rejected['failure_stage'] == 'JUDGMENT_RECEIPT'
        assert rejected['status'] == 'NOT_CONSUMED_INVALID'
        assert 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID' in rejected['gaps']
        assert result['consumed_product_sha256s'] == [product['sha256']]
        assert path.read_bytes() == before


def test_resealed_owner_parent_run_mismatch_rejected_by_shared_read(owner):
    _, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        path = analysis.product_path(owner.store, TARGET, PUBLICATION).with_name('owner_import_receipt.v1.json')
        receipt = owner.store._read(path)
        receipt['parent_run_id'] = '3' * 32
        receipt['sha256'] = digest({key: value for key, value in receipt.items() if key != 'sha256'})
        owner.store._write_atomic(path, receipt)
        result = consumer.read_reviewed_analysis_references(owner, {
            **plan_context(TARGET, now=NOW), 'announcement_publication_date': PUBLICATION})
        rejected = result['products'][0]
        assert rejected['status'] == 'NOT_CONSUMED_INVALID'
        assert rejected['failure_stage'] == 'OWNER_IMPORT_RECEIPT'
        assert rejected['gaps'] == ['ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_PARENT_BINDING_INVALID']
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 409


def _store_product(service, product):
    """Reseal synthetic mutations while preserving a valid selection extension."""
    product = deepcopy(product)
    extension = product.pop('stock_selection', None)
    product.pop('sha256', None)
    product['sha256'] = digest(product)
    if extension is not None:
        product = selection.attach_extension(product,
            selection.make_extension(product, extension['article_decisions']))
    service.store._write_atomic(analysis.product_path(service.store, TARGET, PUBLICATION), product)
    return product


def _exact_context():
    return {**plan_context(TARGET, now=NOW), 'announcement_publication_date': PUBLICATION}


@pytest.mark.parametrize('mutation,reason', [
    ('target', 'ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID'),
    ('publication', 'ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID'),
    ('source_sha', 'ANNOUNCEMENT_ANALYSIS_MANIFEST_SHA_MISMATCH'),
    ('catalog_sha', 'ANNOUNCEMENT_ANALYSIS_SOURCE_BINDING_MISMATCH'),
])
def test_source_or_date_drift_preserves_rejected_pair_and_sha(owner, mutation, reason):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        if mutation == 'target':
            product['target_trade_date'] = '20261009'
        elif mutation == 'publication':
            product['publication_date'] = '2026-10-06'
        elif mutation == 'source_sha':
            product['source_manifest_sha256'] = 'f' * 64
        else:
            product['source_manifest']['catalog_product_sha256'] = 'f' * 64
            product['source_manifest_sha256'] = digest(product['source_manifest'])
        changed = _store_product(owner, product)
        result = consumer.read_reviewed_analysis_references(owner, _exact_context())['products'][0]
        assert result['status'] == 'NOT_CONSUMED_INVALID'
        assert result['failure_stage'] == 'SOURCE_READBACK'
        assert result['gaps'] == [reason]
        assert result['product_sha256'] == changed['sha256']
        assert result['target_trade_date'] == TARGET
        assert result['publication_date'] == PUBLICATION
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 409


@pytest.mark.parametrize('mutation,reason', [
    ('missing', 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID'),
    ('schema', 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID'),
    ('sha', 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID'),
    ('same_reviewer', 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID'),
    ('review_failed', 'ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID'),
    ('decisions', 'ANNOUNCEMENT_AGENT_JUDGMENT_DECISION_BINDING_INVALID'),
])
def test_invalid_judgment_is_never_consumed(owner, mutation, reason):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
    receipt = product['agent_judgment_receipt']
    if mutation == 'missing':
        product.pop('agent_judgment_receipt')
    elif mutation == 'schema':
        receipt['schema_version'] = 'fixture.invalid.v1'
    elif mutation == 'sha':
        receipt['sha256'] = 'f' * 64
    elif mutation == 'same_reviewer':
        receipt['reviewer_identity'] = receipt['reader_identity']
    elif mutation == 'review_failed':
        receipt['reviewer_conclusion'] = 'FAIL'
    else:
        receipt['decision_payload_sha256'] = 'f' * 64
    changed = _store_product(owner, product)
    result = consumer.read_reviewed_analysis_references(owner, _exact_context())['products'][0]
    assert result['status'] == 'NOT_CONSUMED_INVALID'
    assert result['failure_stage'] == 'JUDGMENT_RECEIPT'
    assert result['gaps'] == [reason]
    assert result['product_sha256'] == changed['sha256']
    assert not result['consumed'] and result['research_references'] == []


@pytest.mark.parametrize('mutation,reason', [
    ('reviewer_bytes', 'ANNOUNCEMENT_AGENT_HANDOFF_OUTPUT_SHA_MISMATCH'),
    ('manifest_identity', 'ANNOUNCEMENT_AGENT_HANDOFF_MANIFEST_INVALID'),
    ('owner_expected_manifest', 'ANNOUNCEMENT_AGENT_HANDOFF_MANIFEST_INVALID'),
])
def test_api_and_workspace_share_handoff_rejection(owner, mutation, reason):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        evidence = owner.store.root / 'announcement_agent_runs' / registered['evidence_run_id'] / 'evidence'
        if mutation == 'reviewer_bytes':
            path = evidence / 'reviewer_output.json'
            path.write_bytes(path.read_bytes() + b' ')
        elif mutation == 'manifest_identity':
            path = evidence / 'handoff_manifest.v1.json'
            value = json.loads(path.read_text())
            value['source_run_id'] = '3' * 32
            value['sha256'] = digest({key: item for key, item in value.items() if key != 'sha256'})
            path.write_text(json.dumps(value))
        else:
            path = analysis.product_path(owner.store, TARGET, PUBLICATION).with_name('owner_import_receipt.v1.json')
            value = owner.store._read(path)
            value['handoff_manifest_sha256'] = 'f' * 64
            value['sha256'] = digest({key: item for key, item in value.items() if key != 'sha256'})
            owner.store._write_atomic(path, value)
        before = _snapshot(owner.store.root)
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['analysis']['status'] == 'VERIFIED'
        assert body['analysis']['product_sha256'] == product['sha256']
        result = consumer.read_reviewed_analysis_references(owner, _exact_context())['products'][0]
        assert body['consumption_validation']['status'] == result['status'] == 'NOT_CONSUMED_INVALID'
        assert body['consumption_validation']['gaps'] == result['gaps'] == [reason]
        assert result['failure_stage'] == 'REGISTERED_HANDOFF'
        assert result['research_references'] == []
        assert _snapshot(owner.store.root) == before


@pytest.mark.parametrize('time_field', ['listing', 'body', 'review', 'owner'])
def test_each_source_review_or_owner_time_must_precede_plan_cutoff(owner, time_field):
    late = (NOW + timedelta(seconds=1)).isoformat()
    kwargs = {key: late for name, key in (
        ('listing', 'listing_at'), ('body', 'body_at'), ('review', 'reviewed_at'))
        if name == time_field}
    _, registered = _fixture(owner, **kwargs)
    with _client(owner) as client:
        _import(client, registered)
    if time_field == 'owner':
        path = analysis.product_path(owner.store, TARGET, PUBLICATION).with_name('owner_import_receipt.v1.json')
        receipt = owner.store._read(path)
        receipt['available_at'] = late
        receipt['sha256'] = digest({key: value for key, value in receipt.items() if key != 'sha256'})
        owner.store._write_atomic(path, receipt)
    item = consumer.read_reviewed_analysis_references(owner, _exact_context())['products'][0]
    assert item['status'] == 'NOT_CONSUMED_AFTER_CUTOFF'
    assert item['validation_status'] == 'VERIFIED'
    assert item['failure_stage'] == 'CUTOFF'
    assert item['gaps'] == ['ANNOUNCEMENT_ANALYSIS_NOT_AVAILABLE_AT_PLAN_CUTOFF']
    assert not item['consumed'] and item['research_references'] == []


def test_cutoff_equality_passes_and_invalid_cutoff_does_not(owner):
    _, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
    exact = consumer.read_analysis_consumption(owner, TARGET, PUBLICATION, cutoff=NOW.isoformat())
    assert exact['status'] == 'CONSUMED'
    assert datetime.fromisoformat(exact['latest_source_or_review_at']) == NOW
    invalid = consumer.read_analysis_consumption(owner, TARGET, PUBLICATION, cutoff='not-a-time')
    assert invalid['status'] == 'NOT_CONSUMED_INVALID'
    assert invalid['failure_stage'] == 'CUTOFF'
    assert invalid['research_references'] == []


def test_legacy_v1_owner_receipt_read_does_not_migrate_or_invent_handoff_binding(owner):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        path = analysis.product_path(owner.store, TARGET, PUBLICATION).with_name('owner_import_receipt.v1.json')
        receipt = owner.store._read(path)
        for key in ('source_manifest_sha256', 'evidence_run_id',
                    'handoff_manifest_sha256', 'agent_judgment_receipt_sha256'):
            receipt.pop(key)
        receipt['sha256'] = digest({key: value for key, value in receipt.items() if key != 'sha256'})
        owner.store._write_atomic(path, receipt)
        before = _snapshot(owner.store.root)
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 200, response.text
        item = consumer.read_reviewed_analysis_references(owner, _exact_context())['products'][0]
        assert item['status'] == 'CONSUMED'
        assert item['product_sha256'] == product['sha256']
        assert item['owner_handoff_binding_status'] == 'LEGACY_PRODUCT_PARENT_ONLY_CURRENT_HANDOFF_VERIFIED'
        assert _snapshot(owner.store.root) == before


def test_explicit_missing_publication_does_not_fall_back_to_another_pair(owner):
    _, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        result = client.get('/api/v4/manager/research/workspace', params={
            'date': TARGET, 'view': 'dynamic', 'announcement_date': '2026-10-06',
            'selection_date': '20261007'})
        assert result.status_code == 200, result.text
        read = result.json()['announcement_reviewed_analysis']
        assert read['research_references'] == []
        assert len(read['products']) == 1
        item = read['products'][0]
        assert (item['target_trade_date'], item['publication_date']) == (TARGET, '2026-10-06')
        assert item['status'] == 'NOT_IMPORTED' and item['product_sha256'] is None


def test_r3_legacy_reader_gap_remains_readable_without_rewriting_product(owner):
    product, _ = _fixture(owner, reviewed=False, reader_gap=True)
    path = analysis.product_path(owner.store, TARGET, PUBLICATION)
    owner.store._write_atomic(path, product)
    before = path.read_bytes()
    with _client(owner) as client:
        response = client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION})
        assert response.status_code == 200, response.text
        value = response.json()
        assert value['analysis']['status'] == 'VERIFIED'
        assert value['analysis']['product_sha256'] == product['sha256']
        assert value['analysis']['stock_selection']['article_decisions'][0]['disposition'] == 'NOT_ASSESSED'
        assert value['consumption_validation']['status'] == 'NOT_CONSUMED_INVALID'
        assert value['consumption_validation']['failure_stage'] == 'JUDGMENT_RECEIPT'
        assert 'selection_status' not in value['analysis']['records'][0]
        assert path.read_bytes() == before


@pytest.mark.parametrize('mutation,reason', [
    ('sha', 'ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_BINDING_INVALID'),
    ('evidence_run', 'ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID'),
    ('partial_identity_group', 'ANNOUNCEMENT_OWNER_IMPORT_RECEIPT_HANDOFF_BINDING_INVALID'),
])
def test_owner_receipt_digest_and_evidence_binding_rejected(owner, mutation, reason):
    _, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
        path = analysis.product_path(owner.store, TARGET, PUBLICATION).with_name('owner_import_receipt.v1.json')
        receipt = owner.store._read(path)
        if mutation == 'sha':
            receipt['sha256'] = 'f' * 64
        else:
            if mutation == 'evidence_run':
                receipt['evidence_run_id'] = '3' * 32
            else:
                receipt.pop('agent_judgment_receipt_sha256')
            receipt['sha256'] = digest({key: value for key, value in receipt.items() if key != 'sha256'})
        owner.store._write_atomic(path, receipt)
        item = consumer.read_analysis_consumption(owner, TARGET, PUBLICATION, cutoff=NOW.isoformat())
        assert item['status'] == 'NOT_CONSUMED_INVALID'
        assert item['failure_stage'] == 'OWNER_IMPORT_RECEIPT'
        assert item['gaps'] == [reason]
        assert item['owner_import_receipt_sha256'] == receipt['sha256']
        assert client.get('/api/v4/manager/research/announcements/analysis',
            params={'date': TARGET, 'publication_date': PUBLICATION}).status_code == 409


def test_product_digest_mismatch_retains_observed_identity_and_cannot_consume(owner):
    product, registered = _fixture(owner)
    with _client(owner) as client:
        _import(client, registered)
    product['sha256'] = 'f' * 64
    owner.store._write_atomic(analysis.product_path(owner.store, TARGET, PUBLICATION), product)
    item = consumer.read_analysis_consumption(owner, TARGET, PUBLICATION, cutoff=NOW.isoformat())
    assert item['status'] == 'NOT_CONSUMED_INVALID'
    assert item['product_sha256'] == 'f' * 64
    assert item['gaps'] == ['ANNOUNCEMENT_ANALYSIS_PRODUCT_SHA_MISMATCH']
    assert item['research_references'] == []


def test_missing_acquisition_time_rejected_before_owner_import(owner):
    with pytest.raises(ValueError, match='ANNOUNCEMENT_ANALYSIS_SOURCE_OR_REVIEW_TIME_MISSING'):
        _fixture(owner, listing_at=None)
    assert owner.store._read(analysis.product_path(owner.store, TARGET, PUBLICATION)) is None
    assert owner.store._read(analysis.product_path(owner.store, TARGET, PUBLICATION).with_name(
        'owner_import_receipt.v1.json')) is None


@pytest.mark.parametrize('params', [
    {'announcement_date': '20260230'},
    {'announcement_date': '2026/10/07'},
    {'selection_date': '2026-10-07'},
])
def test_workspace_rejects_invalid_independent_date_syntax(owner, params):
    with _client(owner) as client:
        response = client.get('/api/v4/manager/research/workspace',
            params={'date': TARGET, 'view': 'dynamic', **params})
    assert response.status_code == 422

