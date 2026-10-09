"""R2 app-wired announcement consumption with synthetic, source-bound files.

This uses the package's R2 create_app/service/router/consumer. The original
capture/register/import runner is the separately identified, previously
delivered support dependency. All sources and distinct Reader/Reviewer
outputs are test fixtures; no Mac, live API or original owner run is claimed.
Only source transport and the clock are replaced, never the validators.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import app as app_module
from apps.api.v35_api import manager_research_router as api
from ops import manager_announcement_body_batch as body_batch
from ops import run_manager_daily_announcement as cli
from v4.manager_research.announcement_catalog import PAGE_SIZE
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.ports import SourceResponse
from v4.manager_research.workspace_projection import FLAGS, digest

TARGET = "20261009"
PUBLICATION = "2026-10-08"
NOW = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
ARTICLE = "AN202610081234567890"
TITLE = "Offline synthetic reviewed announcement"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body_batch.json_bytes(value))


def _snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): _sha(path)
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def app_lane(tmp_path, monkeypatch):
    """Use create_app's real private-package manager injection and readers."""
    clock = {"now": NOW}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = clock["now"]
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(api, "datetime", Clock)
    source_calls = []

    def forbidden_transport(*args, **kwargs):
        pytest.fail("Non-fixture announcement transport was attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden_transport)

    def source_transport(url, *, timeout, method="GET", body=None, headers=None,
                         response_type=SourceResponse):
        source_calls.append(url)
        parsed, query = urlparse(url), parse_qs(urlparse(url).query)
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
                "page_size": 1, "notice_content": "Complete synthetic source text for tests.",
                "security": [{"market_uni": "116", "stock": "01234"}]}}
            acquired_at = "2026-10-08T21:01:00+00:00"
        else:
            pytest.fail("Unrecognized synthetic source URL: " + url)
        return response_type(url=url, final_url=url, status_code=200, headers={},
            body=body_batch.json_bytes(value), retrieved_at=acquired_at)

    def provider_factory(*, material_store, timeout):
        return HkexOfficialProvider(transport=forbidden_transport,
            eastmoney_transport=source_transport, material_store=material_store, timeout=timeout)

    root = tmp_path / "synthetic-manager-state"
    # Keep every create_app authority root inside this synthetic fixture.
    for name, suffix in (("V4_MANAGER_SECURITY_MASTER_ROOT", "master"),
                         ("V4_MANAGER_SCREEN_AUTHORITY_ROOT", "screen"),
                         ("V4_MANAGER_NEWS_DATA_ROOT", "news"),
                         ("V4_MANAGER_NEWS_OWNER_ROOT", "news-owner"),
                         ("V4_MANAGER_UNIVERSE_ROOT", "universe"),
                         ("V4_MANAGER_UNIVERSE_OWNER_ROOT", "universe-owner"),
                         ("V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT", "capture-receipts"),
                         ("V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT", "dispatch-receipts")):
        monkeypatch.setenv(name, str(tmp_path / suffix))
    monkeypatch.delenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", raising=False)
    app = app_module.create_app(data_root=tmp_path / "native",
        shared_data_root=tmp_path / "shared", ledger_root=tmp_path / "ledger",
        stage_center_selection_root=tmp_path / "stage",
        manager_research_state_root=root, current_date=TARGET,
        research_data_root=tmp_path / "research",
        research_ledger_root=tmp_path / "research-ledger",
        morning_news_data_root=tmp_path / "morning-news",
        preselection_source_root=tmp_path / "preselection")
    service = app.state.manager_research_service
    # Preserve create_app's actual provider/MaterialStore object identity.
    # Only the provider's network boundary is supplied by this fixture.
    runtime = type(service).__module__.rsplit(".", 1)[0]
    response_type = importlib.import_module(runtime + ".ports").SourceResponse
    monkeypatch.setattr(service.source_provider, "_eastmoney_transport",
        lambda *args, **kwargs: source_transport(*args, **kwargs, response_type=response_type))
    runtime_consumer = importlib.import_module(runtime + ".workspace_announcements")
    runtime_workspace = importlib.import_module(runtime + ".workspace")
    monkeypatch.setattr(runtime_consumer, "_now", lambda: clock["now"].isoformat())
    monkeypatch.setattr(runtime_workspace, "datetime", Clock)
    real_imports = body_batch.imports
    monkeypatch.setattr(body_batch, "imports",
        lambda: {**real_imports(), "HkexOfficialProvider": provider_factory})
    with TestClient(app) as client:
        cli_calls = []

        def request(api_base, path, *, method="GET", payload=None):
            cli._local_api(api_base)
            cli_calls.append((method, path))
            headers = {"Origin": "http://testserver"}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            response = client.request(method, path, content=payload, headers=headers)
            if response.status_code not in {200, 201}:
                raise ValueError("ANNOUNCEMENT_IMPORT_API_HTTP_ERROR_" + str(response.status_code)
                                 + ":" + response.text)
            return response.json()

        monkeypatch.setattr(cli, "_request", request)
        yield SimpleNamespace(root=root, app=app, service=service, client=client,
            source_calls=source_calls, cli_calls=cli_calls, clock=clock)
    service.close()


def _capture(lane):
    return cli._capture(SimpleNamespace(target_date=TARGET, publication_date="20261008",
        api_base="http://127.0.0.1:8873", research_state_root=str(lane.root)))


def _register(lane, capture, *, disposition="SELECTED_EVENT",
              reader_identity="offline-fixture-reader",
              reviewer_identity="offline-fixture-independent-reviewer"):
    """Author explicit synthetic decisions; original CLI validates and binds."""
    run_id = capture["evidence_run_id"]
    evidence = lane.root / "announcement_agent_runs" / run_id / "evidence"
    catalog_read = json.loads((evidence / "catalog_read.json").read_text())
    semantic = {"schema": "v4.announcement-semantic-catalog.v2",
        "status": "PASS_OFFLINE_SYNTHETIC_ONLY", "target_research_date": TARGET,
        "target_notice_date": PUBLICATION, "row_count": 1, "records": [{
            "art_code": ARTICLE, "title": TITLE, "security_scope": "HK_LISTED",
            "issuer_codes": [{"code": "HK.01234"}]}]}
    reader_path = lane.root / "offline-reader-input.json"
    _write(reader_path, semantic)
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
        "disposition": disposition,
        "selection_basis": "OPERATING_EVENT" if disposition == "SELECTED_EVENT" else disposition,
        "reason": "Explicit offline fixture disposition; no security recommendation.",
        "risk_notes": []}]
    decision_path = lane.root / "offline-decisions.json"
    _write(decision_path, {"article_decisions": decisions})
    reviewer_path = lane.root / "offline-reviewer-input.json"
    _write(reviewer_path, {
        "schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "decision_status": "EXPLICIT_DISPOSITIONS",
        "decision_payload_sha256": digest(decisions), "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "evidence_run_id": run_id,
        "reader_identity": reader_identity, "reviewer_identity": reviewer_identity,
        "reviewed_at": "2026-10-09T00:00:00+00:00",
        "catalog_product_sha256": catalog_read["catalog"]["sha256"],
        "semantic_catalog_sha256": _sha(reader_path),
        "body_corpus_sha256": _sha(evidence / "body_corpus.json")})
    registered = cli._register_handoff(SimpleNamespace(target_date=TARGET,
        publication_date=PUBLICATION, evidence_run_id=run_id,
        research_state_root=str(lane.root), semantic_catalog=str(reader_path),
        reviewer_output=str(reviewer_path), decisions=str(decision_path),
        parent_task_id="offline-fixture-parent", reader_identity=reader_identity,
        reviewer_identity=reviewer_identity))
    return registered


def _import(lane, registered):
    return cli._import(SimpleNamespace(evidence_run_id=registered["evidence_run_id"],
        research_state_root=str(lane.root), api_base="http://127.0.0.1:8873"))


def _workspace(lane, *, publication="20261008"):
    response = lane.client.get("/api/v4/manager/research/workspace", params={
        "date": TARGET, "view": "dynamic", "announcement_date": publication,
        "selection_date": TARGET})
    assert response.status_code == 200, response.text
    value = response.json()
    channel = next(item for item in value["daily_channels"]["channels"]
                   if item["channel"] == "ANNOUNCEMENT")
    return value, channel


@pytest.mark.parametrize("disposition, expected_status, expected_count", [
    ("SELECTED_EVENT", "READY", 1), ("NOT_SELECTED", "READY_EMPTY", 0)])
def test_r2_create_app_consumes_exact_registered_owner_result(app_lane,
        disposition, expected_status, expected_count):
    lane = app_lane
    missing_value, missing_channel = _workspace(lane)
    assert missing_channel["status"] == "CANNOT_CONFIRM"
    assert missing_channel["candidate_count"] is None
    registered = _register(lane, _capture(lane), disposition=disposition)
    imported = _import(lane, registered)
    before, source_calls = _snapshot(lane.root), list(lane.source_calls)
    value, channel = _workspace(lane)
    assert channel["status"] == expected_status
    assert channel["candidate_count"] == expected_count
    assert channel["pending_count"] == 0
    assert len(channel["rows"]) == expected_count
    assert channel["selection_date"] == TARGET
    assert channel["announcement_date"] == "20261008"
    checked = channel["product_checks"][0]
    assert checked["status"] == "CONSUMED"
    assert checked["stock_count"] == 1
    assert checked["not_selected_stock_count"] == 1 - expected_count
    assert checked["cutoff_status"] == "SATISFIED"
    assert checked["product_sha256"] == registered["product_sha256"]
    assert checked["handoff_manifest_sha256"] == registered["handoff_manifest_sha256"]
    assert checked["evidence_run_id"] == registered["evidence_run_id"]
    assert checked["owner_import_receipt_sha256"] == imported["owner_receipt_sha256"]
    assert value["input_identity"] != missing_value["input_identity"]
    assert all(value[key] is flag and channel[key] is flag for key, flag in FLAGS.items())
    assert channel["natural_run_verified"] is False
    assert _snapshot(lane.root) == before
    assert lane.source_calls == source_calls
    assert len(source_calls) == 3


def test_r2_create_app_missing_owner_artifacts_stays_unconfirmed_without_capture(app_lane):
    lane = app_lane
    before = _snapshot(lane.root)
    value, channel = _workspace(lane)
    assert channel["status"] == "CANNOT_CONFIRM"
    assert channel["candidate_count"] is None
    assert channel["rows"] == []
    assert "ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED" in channel["gaps"]
    assert value["announcement_review"]["status"] == "NOT_RUN"
    assert lane.source_calls == []
    assert _snapshot(lane.root) == before


@pytest.mark.parametrize("artifact", ["reader_output.json", "reviewer_output.json"])
def test_r2_create_app_rejects_changed_original_review_artifact(app_lane, artifact):
    lane = app_lane
    registered = _register(lane, _capture(lane))
    _import(lane, registered)
    evidence = lane.root / "announcement_agent_runs" / registered["evidence_run_id"] / "evidence"
    path = evidence / artifact
    path.write_bytes(path.read_bytes() + b" ")
    before, source_calls = _snapshot(lane.root), list(lane.source_calls)
    value, channel = _workspace(lane)
    assert channel["status"] == "CANNOT_CONFIRM"
    assert channel["candidate_count"] is None
    assert channel["rows"] == []
    checked = channel["product_checks"][0]
    assert checked["consumed"] is False
    assert checked["validation_status"] == "CANNOT_CONFIRM"
    assert checked["failure_stage"] == "REGISTERED_HANDOFF"
    assert checked["gaps"] == ["ANNOUNCEMENT_AGENT_HANDOFF_OUTPUT_SHA_MISMATCH"]
    assert checked["product_sha256"] == registered["product_sha256"]
    assert value["announcement_reviewed_analysis"]["research_references"] == []
    assert _snapshot(lane.root) == before
    assert lane.source_calls == source_calls


def test_r2_create_app_never_substitutes_neighbor_publication(app_lane):
    lane = app_lane
    registered = _register(lane, _capture(lane))
    _import(lane, registered)
    before, source_calls = _snapshot(lane.root), list(lane.source_calls)
    _value, channel = _workspace(lane, publication="20261007")
    assert channel["status"] == "CANNOT_CONFIRM"
    assert channel["candidate_count"] is None
    assert channel["rows"] == []
    checked = channel["product_checks"][0]
    assert checked["publication_date"] == "2026-10-07"
    assert checked["status"] == "NOT_IMPORTED"
    assert checked["product_sha256"] is None
    assert _snapshot(lane.root) == before
    assert lane.source_calls == source_calls


def test_r2_create_app_does_not_consume_import_available_after_cutoff(app_lane):
    lane = app_lane
    registered = _register(lane, _capture(lane))
    _import(lane, registered)
    lane.clock["now"] = datetime(2026, 10, 9, 0, 30, tzinfo=timezone.utc)
    before, source_calls = _snapshot(lane.root), list(lane.source_calls)
    _value, channel = _workspace(lane)
    assert channel["status"] == "CANNOT_CONFIRM"
    assert channel["candidate_count"] is None
    assert channel["rows"] == []
    checked = channel["product_checks"][0]
    assert checked["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
    assert checked["validation_status"] == "VERIFIED"
    assert checked["cutoff_status"] == "AFTER_CUTOFF"
    assert checked["consumed"] is False
    assert checked["product_sha256"] == registered["product_sha256"]
    assert _snapshot(lane.root) == before
    assert lane.source_calls == source_calls


def test_original_handoff_requires_distinct_reader_and_reviewer(app_lane):
    lane = app_lane
    capture = _capture(lane)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_HANDOFF_REVIEW_OUTPUT_INVALID"):
        _register(lane, capture, reader_identity="offline-fixture-reader",
                  reviewer_identity=" offline-fixture-reader ")
    evidence = lane.root / "announcement_agent_runs" / capture["evidence_run_id"] / "evidence"
    assert not (evidence / "analysis_product.json").exists()
    assert not (evidence / "handoff_manifest.v1.json").exists()
