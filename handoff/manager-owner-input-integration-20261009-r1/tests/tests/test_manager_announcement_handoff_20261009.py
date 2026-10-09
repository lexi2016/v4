"""Synthetic regressions for the existing announcement owner chain.

The catalog/body producer, local owner API, handoff/import and workspace
consumer are real application code. Only source transport and the wall clock
are replaced. Every byte is generated below pytest's temporary directory; no
real announcement, shared state, scheduler, service or trade is touched.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import manager_research_router as api
from ops import manager_announcement_body_batch as body_batch
from ops import run_manager_daily_announcement as cli
from v4.manager_research import workspace_announcements as consumer
from v4.manager_research.announcement_catalog import PAGE_SIZE
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, digest

# Existing frozen synthetic evidence builder isolates readback from the fresh
# capture regression. It creates no production Reader or Reviewer evidence.
import test_manager_announcement_parity_20261008 as parity
from test_manager_us_mapping_three_channel_20261009 import owner as us_missing_owner

TARGET = "20261009"
PUBLICATION = "2026-10-08"
NOW = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
ARTICLE = "AN202610081234567890"
TITLE = "Synthetic complete announcement fixture"


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body_batch.json_bytes(value))


def _sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path):
    return {str(path.relative_to(root)): _sha(path)
            for path in root.rglob("*") if path.is_file()}


def _clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(api, "datetime", Clock)
    monkeypatch.setattr(consumer, "_now", lambda: NOW.isoformat())


def _bind_cli_transport(monkeypatch, client):
    calls = []

    def request(api_base, path, *, method="GET", payload=None):
        cli._local_api(api_base)
        calls.append((method, path))
        headers = {"Origin": "http://testserver"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        response = client.request(method, path, content=payload, headers=headers)
        if response.status_code not in {200, 201}:
            raise ValueError("ANNOUNCEMENT_IMPORT_API_HTTP_ERROR_" + str(response.status_code))
        return response.json()

    monkeypatch.setattr(cli, "_request", request)
    return calls


class _SourceService(ManagerResearchJobService):
    def get_workspace(self, target, **kwargs):
        kwargs.setdefault("now", NOW)
        return super().get_workspace(target, **kwargs)


@pytest.fixture
def source_lane(tmp_path, monkeypatch):
    _clock(monkeypatch)
    source_calls = []

    def forbidden_transport(*args, **kwargs):
        pytest.fail("Unexpected non-fixture source transport")

    def source_transport(url, *, timeout, method="GET", body=None, headers=None):
        source_calls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert method == "GET"
        if parsed.hostname == "np-anotice-stock.eastmoney.com":
            assert query["begin_time"] == [PUBLICATION]
            assert query["end_time"] == [PUBLICATION]
            page = int(query["page_index"][0])
            assert page in {1, 2}
            row = {"art_code": ARTICLE, "title": TITLE,
                "notice_date": PUBLICATION + " 00:00:00",
                "display_time": PUBLICATION + " 09:00:00:000",
                "codes": [{"market_code": "116", "stock_code": "01234",
                           "ann_type": "H", "short_name": "Synthetic issuer"}]}
            value = {"success": 1, "data": {"list": [row] if page == 1 else [],
                "page_index": page, "page_size": PAGE_SIZE, "total_hits": 1}}
            acquired_at = "2026-10-08T21:00:00+00:00"
        elif parsed.hostname == "np-cnotice-stock.eastmoney.com":
            assert query["art_code"] == [ARTICLE]
            assert query["page_index"] == ["1"]
            value = {"success": 1, "data": {"art_code": ARTICLE,
                "notice_title": TITLE, "notice_date": PUBLICATION + " 00:00:00",
                "page_size": 1, "notice_content": "One complete synthetic announcement body.",
                "security": [{"market_uni": "116", "stock": "01234"}]}}
            acquired_at = "2026-10-08T21:01:00+00:00"
        else:
            pytest.fail("Unexpected synthetic source URL: " + url)
        return SourceResponse(url=url, final_url=url, status_code=200, headers={},
            body=body_batch.json_bytes(value), retrieved_at=acquired_at)

    def provider_factory(*, material_store, timeout):
        return HkexOfficialProvider(transport=forbidden_transport,
            eastmoney_transport=source_transport, material_store=material_store, timeout=timeout)

    root = tmp_path / "synthetic-research-state"
    materials = MaterialStore(root / "materials")
    provider = provider_factory(material_store=materials, timeout=5)
    service = _SourceService(ManagerResearchStore(root), None, provider,
        material_store=materials, workspace_ledger_root=tmp_path / "synthetic-ledger",
        workspace_security_master_root=tmp_path / "synthetic-master",
        workspace_screen_authority_root=tmp_path / "synthetic-screen-authority",
        catalyst_data_root=tmp_path / "synthetic-catalyst-data",
        catalyst_news_owner_root=tmp_path / "synthetic-news-owner")
    real_imports = body_batch.imports

    def fixture_imports():
        return {**real_imports(), "HkexOfficialProvider": provider_factory}

    monkeypatch.setattr(body_batch, "imports", fixture_imports)
    app = FastAPI()
    app.include_router(api.create_manager_research_router(service))
    with TestClient(app) as client:
        cli_calls = _bind_cli_transport(monkeypatch, client)
        yield SimpleNamespace(root=root, service=service, client=client,
            source_calls=source_calls, cli_calls=cli_calls)
    service.close()


def _register_captured_fixture(lane, capture, *, reader_identity="synthetic-reader",
                             reviewer_identity="synthetic-reviewer"):
    run_id = capture["evidence_run_id"]
    evidence = lane.root / "announcement_agent_runs" / run_id / "evidence"
    catalog_read = json.loads((evidence / "catalog_read.json").read_text())
    semantic = {"schema": "v4.announcement-semantic-catalog.v2",
        "status": "PASS_SYNTHETIC_FIXTURE_ONLY", "target_research_date": TARGET,
        "target_notice_date": PUBLICATION, "row_count": 1, "records": [{
            "art_code": ARTICLE, "title": TITLE, "security_scope": "HK_LISTED",
            "issuer_codes": [{"code": "HK.01234"}]}]}
    reader_path = lane.root / "synthetic-reader-input.json"
    _write_json(reader_path, semantic)
    prepared = cli._build(SimpleNamespace(target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(evidence / "catalog_read.json"), semantic_catalog=str(reader_path),
        body_corpus=str(evidence / "body_corpus.json"), body_capture_evidence_root=str(evidence),
        decisions=None, review_receipt=None, out=None), reviewed=False, include_product=True)
    row = prepared["product"]["records"][0]
    decisions = [{"art_code": row["art_code"],
        "issuer_codes": [item["code"] for item in row["issuer_codes"]],
        "security_scope": row["security_scope"],
        "semantic_record_sha256": row["semantic_record_sha256"],
        "body_record_sha256": row["body_record_sha256"],
        "disposition": "SELECTED_EVENT", "selection_basis": "OPERATING_EVENT",
        "reason": "Synthetic fixture disposition only.", "risk_notes": []}]
    decision_path = lane.root / "synthetic-decisions.json"
    _write_json(decision_path, {"article_decisions": decisions})
    reviewer_path = lane.root / "synthetic-reviewer-input.json"
    _write_json(reviewer_path, {
        "schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "decision_status": "EXPLICIT_DISPOSITIONS",
        "decision_payload_sha256": digest(decisions), "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "evidence_run_id": run_id,
        "reader_identity": reader_identity, "reviewer_identity": reviewer_identity,
        "reviewed_at": "2026-10-09T00:00:00+00:00",
        "catalog_product_sha256": catalog_read["catalog"]["sha256"],
        "semantic_catalog_sha256": _sha(reader_path),
        "body_corpus_sha256": _sha(evidence / "body_corpus.json")})
    return cli._register_handoff(SimpleNamespace(target_date=TARGET,
        publication_date=PUBLICATION, evidence_run_id=run_id,
        research_state_root=str(lane.root), semantic_catalog=str(reader_path),
        reviewer_output=str(reviewer_path), decisions=str(decision_path),
        parent_task_id="synthetic-parent", reader_identity=reader_identity,
        reviewer_identity=reviewer_identity))


def test_original_fresh_capture_preserves_bound_bytes_then_imports_to_workspace(source_lane):
    lane = source_lane
    capture = cli._capture(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873", research_state_root=str(lane.root)))
    evidence = lane.root / "announcement_agent_runs" / capture["evidence_run_id"] / "evidence"
    for source_name, fixed_name in [("body_corpus.json", "body_corpus.json"),
            ("body_corpus_manifest.json", "body_corpus_manifest.json"),
            ("batch_receipt.json", "body_batch_receipt.json")]:
        assert (evidence / fixed_name).read_bytes() == (evidence / "body_batch" / source_name).read_bytes(), (
            "Original capture reformatted a producer artifact whose exact bytes are SHA-bound: " + fixed_name)
    catalog = json.loads((evidence / "catalog_read.json").read_text())
    terminal = consumer.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION,
        expected_run_id=capture["evidence_run_id"])
    assert terminal["status"] == "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS"
    registered = _register_captured_fixture(lane, capture)
    imported = cli._import(SimpleNamespace(evidence_run_id=registered["evidence_run_id"],
        research_state_root=str(lane.root), api_base="http://127.0.0.1:8873"))
    assert imported["product_sha256"] == registered["product_sha256"]
    snapshot = _snapshot(lane.root)
    source_calls = list(lane.source_calls)
    readback = lane.client.get("/api/v4/manager/research/announcements/analysis",
        params={"date": TARGET, "publication_date": "20261008"})
    assert readback.status_code == 200, readback.text
    consumption = readback.json()["consumption_validation"]
    assert consumption["validation_status"] == "VERIFIED"
    response = lane.client.get("/api/v4/manager/research/workspace", params={
        "date": TARGET, "view": "dynamic", "announcement_date": "20261008",
        "selection_date": "20261008"})
    assert response.status_code == 200, response.text
    consumed = response.json()["announcement_reviewed_analysis"]["products"][0]
    assert consumed["status"] == "CONSUMED"
    assert consumed["product_sha256"] == registered["product_sha256"]
    assert consumed["handoff_manifest_sha256"] == registered["handoff_manifest_sha256"]
    assert consumed["research_references"][0]["stock_code"] == "HK.01234"
    assert all(consumed[key] is expected for key, expected in FLAGS.items())
    assert _snapshot(lane.root) == snapshot
    assert lane.source_calls == source_calls
    assert len(source_calls) == 3  # Listing, terminal empty page and one body; synthetic only.
    assert lane.cli_calls[0][0] == "POST"
    assert "publication_date=20261008" in lane.cli_calls[0][1]


@pytest.fixture
def imported_lane(tmp_path, monkeypatch):
    _clock(monkeypatch)
    service = parity._FixtureService(tmp_path / "synthetic-imported-state")
    product, registered = parity._fixture(service, target=TARGET, publication=PUBLICATION,
        listing_at="2026-10-08T21:00:00+00:00", body_at="2026-10-08T21:01:00+00:00",
        reviewed_at="2026-10-09T00:00:00+00:00")
    with parity._client(service) as client:
        imported = parity._import(client, registered)
        _bind_cli_transport(monkeypatch, client)
        yield SimpleNamespace(service=service, client=client, product=product,
            registered=registered, imported=imported, root=service.store.root)
    service.close()


def test_cli_readback_accepts_exact_bound_owner_import_without_fabricating_product(imported_lane):
    lane = imported_lane
    before = _snapshot(lane.root)
    result = cli._readback(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873"))
    assert result["status"] == "OWNER_READBACK_VERIFIED"
    assert result["product_sha256"] == lane.product["sha256"]
    assert result["owner_receipt_sha256"] == lane.imported["owner_import_receipt"]["sha256"]
    assert _snapshot(lane.root) == before


@pytest.mark.parametrize("mutation", ["missing_chain", "unverified_chain", "product_sha",
    "source_manifest_sha", "evidence_run_id", "handoff_sha", "judgment_sha", "owner_receipt_sha"])
def test_cli_readback_rejects_unverified_or_mismatched_complete_chain(imported_lane, monkeypatch, mutation):
    readback = imported_lane.client.get("/api/v4/manager/research/announcements/analysis",
        params={"date": TARGET, "publication_date": "20261008"}).json()
    if mutation == "missing_chain":
        readback.pop("consumption_validation")
    elif mutation == "unverified_chain":
        readback["consumption_validation"]["validation_status"] = "CANNOT_CONFIRM"
    else:
        fields = {"product_sha": "product_sha256", "source_manifest_sha": "source_manifest_sha256",
            "evidence_run_id": "evidence_run_id", "handoff_sha": "handoff_manifest_sha256",
            "judgment_sha": "agent_judgment_receipt_sha256", "owner_receipt_sha": "owner_import_receipt_sha256"}
        readback["consumption_validation"][fields[mutation]] = "f" * (32 if mutation == "evidence_run_id" else 64)
    monkeypatch.setattr(cli, "_request", lambda *args, **kwargs: deepcopy(readback))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_CHAIN_INVALID"):
        cli._readback(SimpleNamespace(target_date=TARGET, publication_date="20261008",
            api_base="http://127.0.0.1:8873"))


@pytest.mark.parametrize("reader_identity", [None, "", "   "])
def test_formal_reader_identity_cannot_be_missing_from_bound_judgment(imported_lane, reader_identity):
    product = deepcopy(imported_lane.product)
    receipt = product["agent_judgment_receipt"]
    receipt["reader_identity"] = reader_identity
    receipt["sha256"] = digest({key: value for key, value in receipt.items() if key != "sha256"})
    with pytest.raises(ValueError, match="ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID"):
        consumer.validate_agent_judgment_receipt(receipt, product)


def test_whitespace_equivalent_reader_reviewer_cannot_register_a_distinct_review(source_lane):
    lane = source_lane
    capture = cli._capture(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873", research_state_root=str(lane.root)))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_HANDOFF_REVIEW_OUTPUT_INVALID"):
        _register_captured_fixture(lane, capture, reader_identity="synthetic-reader",
            reviewer_identity=" synthetic-reader ")
    evidence = lane.root / "announcement_agent_runs" / capture["evidence_run_id"] / "evidence"
    assert not (evidence / "analysis_product.json").exists()
    assert not (evidence / "handoff_manifest.v1.json").exists()


def test_whitespace_equivalent_reader_reviewer_cannot_validate_saved_judgment(imported_lane):
    product = deepcopy(imported_lane.product)
    receipt = product["agent_judgment_receipt"]
    receipt["reader_identity"] = " " + receipt["reviewer_identity"] + " "
    receipt["sha256"] = digest({key: value for key, value in receipt.items() if key != "sha256"})
    with pytest.raises(ValueError, match="ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_BINDING_INVALID"):
        consumer.validate_agent_judgment_receipt(receipt, product)


@pytest.mark.parametrize("missing", ["capture_receipt.json", "reader_output.json", "reviewer_output.json"])
def test_import_requires_saved_capture_reader_and_reviewer_before_owner_post(imported_lane, monkeypatch, missing):
    lane = imported_lane
    run_id = lane.registered["evidence_run_id"]
    evidence = lane.root / "announcement_agent_runs" / run_id / "evidence"
    (evidence / missing).unlink()
    snapshot = _snapshot(lane.root)

    def forbidden_post(*args, **kwargs):
        pytest.fail("Incomplete evidence reached owner import POST")

    monkeypatch.setattr(cli, "_request", forbidden_post)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_AGENT_HANDOFF_OUTPUT_MISSING"):
        cli._import(SimpleNamespace(evidence_run_id=run_id,
            research_state_root=str(lane.root), api_base="http://127.0.0.1:8873"))
    assert _snapshot(lane.root) == snapshot


def test_cli_readback_keeps_legacy_receipt_bytes_when_current_handoff_verifies(imported_lane):
    lane = imported_lane
    path = parity.analysis.product_path(lane.service.store, TARGET, PUBLICATION).with_name("owner_import_receipt.v1.json")
    receipt = json.loads(path.read_text())
    for key in ("source_manifest_sha256", "evidence_run_id", "handoff_manifest_sha256", "agent_judgment_receipt_sha256"):
        receipt.pop(key)
    receipt["sha256"] = digest({key: value for key, value in receipt.items() if key != "sha256"})
    _write_json(path, receipt)
    before = _snapshot(lane.root)
    readback = cli._readback(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873"))
    assert readback["owner_receipt_sha256"] == receipt["sha256"]
    assert _snapshot(lane.root) == before


def test_imported_announcement_survives_workspace_refresh_with_missing_us_input(source_lane, us_missing_owner):
    lane = source_lane
    us_service, _source, _client, us_clock = us_missing_owner
    # Reuse the US regression's real-schema synthetic relation files and its
    # original missing-source adapter; no absent runtime JSON is invented.
    us_clock["now"] = NOW
    lane.service._workspace_us_market_reader = us_service._workspace_us_market_reader
    capture = cli._capture(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873", research_state_root=str(lane.root)))
    registered = _register_captured_fixture(lane, capture)
    cli._import(SimpleNamespace(evidence_run_id=registered["evidence_run_id"],
        research_state_root=str(lane.root), api_base="http://127.0.0.1:8873"))
    evidence = lane.root / "announcement_agent_runs" / capture["evidence_run_id"] / "evidence"
    product_path = parity.analysis.product_path(lane.service.store, TARGET, PUBLICATION)
    source_snapshot = _snapshot(evidence)
    imported_bytes = product_path.read_bytes()
    source_calls = list(lane.source_calls)

    response = lane.client.post("/api/v4/manager/research/workspace/refresh", params={
        "date": TARGET, "announcement_date": "20261008", "selection_date": "20261008"},
        headers={"Origin": "http://testserver"}, content=b"")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["us_mapping_preparation"]["status"] == "INPUT_MISSING"
    assert value["us_mapping_research"]["daily_run"]["status"] == "INPUT_MISSING"
    assert value["owner_chain"]["us_mapping_daily_plan_reference"]["status"] == "INPUT_MISSING"
    consumed = value["announcement_reviewed_analysis"]["products"][0]
    assert consumed["status"] == "CONSUMED"
    assert consumed["product_sha256"] == registered["product_sha256"]
    assert consumed["handoff_manifest_sha256"] == registered["handoff_manifest_sha256"]
    assert consumed["research_references"][0]["stock_code"] == "HK.01234"
    announcement_channel = next(item for item in value["daily_channels"]["channels"]
        if item["channel"] == "ANNOUNCEMENT")
    assert announcement_channel["status"] == "READY"
    assert announcement_channel["candidate_count"] == 1
    saved = lane.service.get_workspace_plan(TARGET)
    assert saved["sha256"] == value["plan_product"]["sha256"]
    assert saved["workspace"]["announcement_reviewed_analysis"]["products"][0]["product_sha256"] == registered["product_sha256"]
    assert _snapshot(evidence) == source_snapshot
    assert product_path.read_bytes() == imported_bytes
    assert lane.source_calls == source_calls
    assert all(value[key] is expected for key, expected in FLAGS.items())
