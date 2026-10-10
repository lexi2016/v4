"""Exact-date owner flow and idempotency across daily target/publication pairs."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research import announcement_source
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore


class _MaterialStore:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}


class _Provider:
    def __init__(self, store):
        self._material_store = store


def _listing_response(page: int, publication: str, rows: list[dict]) -> bytes:
    return json.dumps({"success": 1, "data": {"page_index": page, "page_size": 20,
        "total_hits": 1, "list": rows}}).encode()


def _row(publication: str) -> dict:
    return {"art_code": "AN" + publication.replace("-", "") + "1234567890",
        "title": "Daily source-bound test notice", "notice_date": publication + " 00:00:00",
        "display_time": publication + " 09:00:00:000",
        "codes": [{"market_code": "116", "stock_code": "00001", "ann_type": "H",
            "short_name": "Fixture Issuer"}]}


def _install_capture(monkeypatch, store, calls):
    def capture(provider, url, *, force=False):
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        publication = (query["begin_time"][0])
        page = int(query["page_index"][0])
        calls.append((publication, page, force))
        rows = [_row(publication)] if page == 1 else []
        raw = _listing_response(page, publication, rows)
        body_sha = sha256(raw).hexdigest()
        blob_sha = sha256(b"material:" + raw).hexdigest()
        store.blobs[blob_sha] = raw
        return {"request": {"source": "EASTMONEY_HK", "method": "GET", "url": url},
            "source_key": "fixture:" + blob_sha, "blob_sha256": blob_sha,
            "body_sha256": body_sha, "retrieved_at": "2026-10-07T01:00:00+00:00",
            "http_status": 200, "final_url": url, "from_cache": False}

    def read(store_arg, ref):
        raw = store_arg.blobs[ref["blob_sha256"]]
        assert sha256(raw).hexdigest() == ref["body_sha256"]
        return raw

    monkeypatch.setattr(announcement_source, "capture_eastmoney", capture)
    monkeypatch.setattr(announcement_source, "read_eastmoney_response", read)


def test_daily_owner_captures_two_date_pairs_without_master_and_reuses_them(tmp_path: Path, monkeypatch):
    materials = _MaterialStore()
    provider = _Provider(materials)
    calls = []
    _install_capture(monkeypatch, materials, calls)
    state_root = tmp_path / "owner-state"
    service = ManagerResearchJobService(ManagerResearchStore(state_root), None, provider,
        material_store=materials, workspace_security_master_root=None)
    date_pairs = [("20260930", "2026-09-29"), ("20261007", "2026-10-06")]
    try:
        for target, publication in date_pairs:
            result = service.refresh_announcements(target, source_scope="EASTMONEY_HK_DATE_CATALOG",
                publication_date=publication)
            assert result["status"] == "COMPLETE"
            assert result["readback_status"] == "VERIFIED"
            assert result["catalog"]["target_trade_date"] == target
            assert result["catalog"]["publication_date"] == publication
            assert result["catalog"]["manager_consumer_row_count"] == 1
            assert result["catalog"]["manager_source_codes"] == ["HK.00001"]
            assert result["catalog"]["manager_matched_master_codes"] == []
            assert result["catalog"]["master_enrichment_status"] == "NOT_ATTEMPTED"
            assert result["catalog"]["connect_eligibility_status"] == "NOT_ASSESSED"
            assert result["catalog"]["source_rows"][0]["source_ref"]["retrieved_at"] == "2026-10-07T01:00:00+00:00"
            assert service.get_announcement_analysis(target, publication)["analysis"]["status"] == "NOT_IMPORTED"
        request_count = len(calls)
        for target, publication in date_pairs:
            again = service.refresh_announcements(target, source_scope="EASTMONEY_HK_DATE_CATALOG",
                publication_date=publication)
            assert again["readback_status"] == "VERIFIED"
        assert len(calls) == request_count

        app = FastAPI()
        app.include_router(create_manager_research_router(service))
        with TestClient(app) as client:
            response = client.get("/api/v4/manager/research/announcements/analysis", params={
                "date": "20261007", "publication_date": "2026-10-06"})
        assert response.status_code == 200
        body = response.json()
        assert body["target_trade_date"] == "20261007"
        assert body["publication_date"] == "2026-10-06"
        assert body["source_catalog"]["manager_announcement_count"] == 1
        assert body["source_catalog"]["manager_issuer_count"] is None
        assert body["source_catalog"]["distinct_manager_source_code_count"] == 1
        assert body["source_catalog"]["manager_source_identity_association_count"] == 1
        assert body["source_catalog"]["unknown_issuer_count"] is None
        assert body["source_catalog"]["issuer_count_status"] == "CANNOT_CONFIRM"
        assert body["analysis"]["status"] == "NOT_IMPORTED"
        assert body["analysis"]["stock_selection"]["selected_stock_count"] is None
    finally:
        service.close()
