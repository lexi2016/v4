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


