from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api.manager_research_router import create_manager_research_router
from ops import manager_announcement_body_batch as body_batch
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_announcements import (
    read_reviewed_analysis_references,
    validate_terminal_body_capture,
)
from v4.manager_research.workspace_projection import digest


APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
CLI_PATH = APP_ROOT / "ops/run_manager_daily_announcement.py"
FORMAL_STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
FORMAL_EVIDENCE = FORMAL_STATE / "announcement_agent_runs/3f9d37a643060b57992167f3df05d987/evidence"
RUN_ID = "3f9d37a643060b57992167f3df05d987"
TARGET = "20261008"
PUBLICATION = "2026-10-07"


def _cli():
    spec = importlib.util.spec_from_file_location("terminal_body_capture_cli_test", CLI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_evidence(state_root: Path) -> Path:
    evidence = state_root / "announcement_agent_runs" / RUN_ID / "evidence"
    evidence.mkdir(parents=True)
    for name in ("catalog_read.json", "body_corpus.json", "body_corpus_manifest.json",
                 "body_batch_receipt.json", "capture_receipt.json"):
        shutil.copyfile(FORMAL_EVIDENCE / name, evidence / name)
    shutil.copytree(FORMAL_EVIDENCE / "body_batch" / "bodies",
                    evidence / "body_batch" / "bodies")
    return evidence


def _semantic_fixture(catalog_read: dict, body: dict) -> dict:
    rows = catalog_read["catalog"]["manager_consumer_rows"]
    return {
        "schema": "v4.announcement-semantic-catalog.v2",
        "status": "PASS_TEST_FIXTURE_ONLY",
        "target_research_date": TARGET,
        "target_notice_date": PUBLICATION,
        "row_count": len(rows),
        "records": [
            {"art_code": row["art_code"], "title": row["title"],
             "issuer_codes": [{"code": issuer["code"]} for issuer in row["source_issuer_codes"]]}
            for row in rows
        ],
    }


def _fixture_files(evidence: Path, tmp_path: Path) -> tuple[Path, Path, dict]:
    catalog_read = json.loads((evidence / "catalog_read.json").read_text(encoding="utf-8"))
    body = json.loads((evidence / "body_corpus.json").read_text(encoding="utf-8"))
    semantic = _semantic_fixture(catalog_read, body)
    semantic_path = tmp_path / "semantic_catalog.test_fixture.json"
    semantic_path.write_text(json.dumps(semantic, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    terminal = validate_terminal_body_capture(evidence, catalog_read, TARGET, PUBLICATION,
        expected_run_id=RUN_ID)
    return semantic_path, evidence / "body_corpus.json", terminal


def _seed_owner_state(state_root: Path, catalog_read: dict) -> None:
    catalog = catalog_read["catalog"]
    publication_token = PUBLICATION.replace("-", "")
    for relative in (
        Path("workspace_announcements") / TARGET / "eastmoney_date_catalog" / publication_token,
        Path("workspace_announcement_runs") / TARGET / "eastmoney_date_catalog" / publication_token,
    ):
        shutil.copytree(FORMAL_STATE / relative, state_root / relative)
    material_cls = body_batch.imports()["MaterialStore"]
    source = material_cls(FORMAL_STATE / "materials")
    destination = material_cls(state_root / "materials")
    for page in catalog["page_receipts"]:
        ref = page["source_ref"]
        blob_rel = source._blob_relative(ref["blob_sha256"])
        index_rel = source._index_relative(ref["source_key"])
        destination._io.write_bytes(blob_rel, source._io.read_bytes(blob_rel))
        destination._io.write_bytes(index_rel, source._io.read_bytes(index_rel))


def _write_minimal_complete_evidence(state_root: Path) -> Path:
    evidence = state_root / "announcement_agent_runs" / RUN_ID / "evidence"
    bodies = evidence / "body_batch" / "bodies"
    bodies.mkdir(parents=True)
    art_code = "AN202610071234567890"
    title = "Single complete test notice"
    listing_sha = "a" * 64
    listing_ref = {"request": {"url": "https://np-anotice-stock.eastmoney.com/api/security/ann?date=2026-10-07"},
        "blob_sha256": "b" * 64, "body_sha256": "c" * 64,
        "retrieved_at": "2026-10-07T21:00:00+00:00"}
    body_text = "One complete captured page."
    body_text_sha = hashlib.sha256(body_text.encode()).hexdigest()
    body_raw_sha = "d" * 64
    body_ref = {"request": {"url": f"https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code={art_code}&client_source=web&page_index=1"},
        "blob_sha256": "e" * 64, "body_sha256": body_raw_sha,
        "retrieved_at": "2026-10-07T21:01:00+00:00"}
    issuer = {"code": "HK.01234", "source_stock_code": "01234", "market_code": "116",
        "ann_type": "H", "name": "Test issuer"}
    listing = {"art_code": art_code, "title": title, "page_index": 1, "item_index": 0,
        "notice_date": "2026-10-07 00:00:00", "display_time": "2026-10-07 09:00:00:000",
        "raw_body_sha256": listing_sha, "source_ref": listing_ref,
        "source_issuer_codes": [issuer]}
    catalog = {"target_trade_date": TARGET, "publication_date": PUBLICATION,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "connect_eligibility_status": "NOT_ASSESSED", "hkex_first_publication_verified": False,
        "captured_row_count": 1, "captured_page_count": 1, "manager_consumer_row_count": 1,
        "manager_source_identity_count": 1, "manager_source_codes": [issuer["code"]],
        "run_id": RUN_ID, "manager_consumer_rows": [listing]}
    catalog["sha256"] = digest(catalog)
    catalog_read = {"schema_version": "v4.manager_research.eastmoney_hk_date_catalog_read.v1",
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "source_scope": "EASTMONEY_HK_DATE_CATALOG", "status": "COMPLETE",
        "readback_status": "VERIFIED", "catalog": catalog}
    catalog_path = evidence / "catalog_read.json"
    catalog_path.write_text(json.dumps(catalog_read, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")

    article_receipt = {"schema": "v4.manager_research.source_bound_announcement_body.v1",
        "art_code": art_code, "target_trade_date": TARGET, "publication_date": PUBLICATION,
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
        "pages": [{"page_index": 1, "page_total": 1, "notice_date": "2026-10-07 00:00:00",
            "text": body_text, "text_sha256": body_text_sha, "raw_body_sha256": body_raw_sha,
            "source_ref": body_ref}], "attachment_url": None, "pdf_sha256": None,
        "transport_body_status": "COMPLETE_CONTENT_API_BODY"}
    identity_material = {"target_trade_date": TARGET, "publication_date": PUBLICATION,
        "catalog_run_id": RUN_ID, "catalog_sha256": catalog["sha256"],
        "article_ids": [art_code], "listing_body_sha256s": [listing_sha]}
    input_identity = hashlib.sha256((json.dumps(identity_material, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    body_manifest = {"schema": "v4.manager_research.source_bound_announcement_body_corpus.v1",
        "target_trade_date": TARGET, "publication_date": PUBLICATION, "catalog_run_id": RUN_ID,
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
        "target_notice_date": PUBLICATION, "article_count": 1, "rows": [body_row],
        "input_identity_sha256": input_identity, "source_manifest_sha256": manifest_sha,
        "transport_complete_body_count": 1}
    body_path = evidence / "body_corpus.json"
    body_path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest()
    batch = {"schema": "v4.manager_research.announcement_body_batch_receipt.v1",
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS", "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "catalog_run_id": RUN_ID,
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
        "status": batch["status"], "evidence_run_id": RUN_ID,
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "catalog_run_id": RUN_ID, "catalog_product_sha256": catalog["sha256"],
        "catalog_read_file_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "body_corpus_file_sha256": body_sha,
        "body_corpus_manifest_file_sha256": manifest_sha,
        "body_batch_receipt_sha256": batch_sha,
        "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    (evidence / "capture_receipt.json").write_text(json.dumps(capture, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return evidence


def test_real_613_partial_capture_projects_failures_as_unassessed_and_imports_via_owner(tmp_path):
    assert FORMAL_EVIDENCE.is_dir()
    state_root = tmp_path / "isolated-manager-state"
    evidence = _copy_evidence(state_root)
    catalog_read = json.loads((evidence / "catalog_read.json").read_text(encoding="utf-8"))
    body = json.loads((evidence / "body_corpus.json").read_text(encoding="utf-8"))
    semantic_path, body_path, terminal = _fixture_files(evidence, tmp_path)
    assert terminal["body_status_counts"] == {
        "COMPLETE_CONTENT_API_BODY": 608, "BODY_CAPTURE_FAILED": 5,
    }
    failed = {row["art_code"] for row in terminal["failed_articles"]}
    semantic_fixture = json.loads(semantic_path.read_text(encoding="utf-8"))
    content_gap_code = next(row["art_code"] for row in semantic_fixture["records"]
                            if row["art_code"] not in failed)
    content_gap_fact = next(row for row in semantic_fixture["records"]
                            if row["art_code"] == content_gap_code)
    content_gap_fact["factual_summary"] = "Preserved fact from the readable portion before the source gap."
    content_gap_fact["evidence"] = {"reader_fact_record": {
        "body_read_complete": False,
        "source_content_gap": True,
        "partial_fact": "Preserved reader fact from the available body pages.",
        "validation": {"source_content_gap": True},
    }}
    semantic_path.write_text(json.dumps(semantic_fixture, ensure_ascii=False,
        sort_keys=True) + "\n", encoding="utf-8")

    cli = _cli()
    prep_args = SimpleNamespace(target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(evidence / "catalog_read.json"), semantic_catalog=str(semantic_path),
        body_corpus=str(body_path), body_capture_evidence_root=str(evidence),
        decisions=None, out=None, review_receipt=None)
    prepared_process = subprocess.run([
        sys.executable, str(CLI_PATH), "prepare", "--target-date", TARGET,
        "--publication-date", PUBLICATION, "--catalog-read", str(evidence / "catalog_read.json"),
        "--semantic-catalog", str(semantic_path), "--body-corpus", str(body_path),
        "--body-capture-evidence-root", str(evidence),
    ], cwd="/", capture_output=True, text=True, check=False)
    assert prepared_process.returncode == 0, prepared_process.stderr[:500]
    prepared_summary = json.loads(prepared_process.stdout)
    assert prepared_summary["body_capture_failed_article_count"] == 5
    assert prepared_summary["body_capture_status"] == "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    prepared = cli._build(prep_args, reviewed=False, include_product=True)
    product = prepared["product"]
    projected = {row["art_code"]: row for row in product["records"]}
    assert len(projected) == 613
    assert product["summary"]["complete_api_bodies"] == 607
    assert product["summary"]["text_insufficient_unassessed"] == 6
    for code in failed:
        assert projected[code]["body_status"] == "BODY_CAPTURE_FAILED"
        assert projected[code]["analysis_kind"] == "TEXT_INSUFFICIENT_UNASSESSED"
        assert projected[code]["selection_status"] == "NOT_ASSESSED"
        assert projected[code]["body_capture_failure"]["error_code"]
        assert projected[code]["body_capture_failure"]["receipt_sha256"]
        assert projected[code]["body_page_count"] is None
        assert projected[code]["body_text_sha256"] is None
        assert projected[code]["body_page_citations"] == []
    reader_gap = projected[content_gap_code]
    assert reader_gap["body_status"] == "COMPLETE_CONTENT_API_BODY"
    assert reader_gap["analysis_kind"] == "TEXT_INSUFFICIENT_UNASSESSED"
    assert reader_gap["selection_status"] == "NOT_ASSESSED"
    assert reader_gap["factual_summary"] == "Preserved fact from the readable portion before the source gap."
    assert reader_gap["evidence"]["reader_fact_record"]["partial_fact"] == \
        "Preserved reader fact from the available body pages."
    # Convert test decision rows to the exact base-product hashes, retaining one
    # good article as the only selected test row and the 5 failures unassessed.
    from v4.manager_research.announcement_selection import make_extension
    base_args = SimpleNamespace(**{**vars(prep_args), "decisions": None})
    base = cli._build(base_args, reviewed=False, include_product=True)["product"]
    unassessed = failed | {content_gap_code}
    first_good = next(row["art_code"] for row in base["records"]
                      if row["art_code"] not in unassessed)
    decisions = []
    for row in base["records"]:
        code = row["art_code"]
        decisions.append({
            "art_code": code,
            "issuer_codes": [item["code"] for item in row["issuer_codes"]],
            "security_scope": row["security_scope"],
            "semantic_record_sha256": row["semantic_record_sha256"],
            "body_record_sha256": row["body_record_sha256"],
            "disposition": "NOT_ASSESSED" if code in unassessed else
                "SELECTED_EVENT" if code == first_good else "NOT_SELECTED",
            "selection_basis": "NOT_ASSESSED" if code in unassessed else
                "OPERATING_EVENT" if code == first_good else "NOT_SELECTED",
            "reason": "test-only explicit disposition",
            "risk_notes": [],
        })
    decisions_path = tmp_path / "article_decisions.test_fixture.json"
    decisions_path.write_text(json.dumps({"article_decisions": decisions}, ensure_ascii=False,
        sort_keys=True), encoding="utf-8")
    from v4.manager_research.announcement_selection import attach_extension
    from v4.manager_research.announcement_analysis import validate_product
    product = attach_extension(base, make_extension(base, decisions))
    assert all(row["disposition"] == "NOT_ASSESSED"
               for row in product["stock_selection"]["article_decisions"]
               if row["art_code"] in unassessed)
    validate_product(product, target_trade_date=TARGET, publication_date=PUBLICATION,
                     catalog=catalog_read["catalog"])
    forged = copy.deepcopy(decisions)
    gap_decision = next(row for row in forged if row["art_code"] == content_gap_code)
    gap_decision["disposition"] = "SELECTED_EVENT"
    gap_decision["selection_basis"] = "OPERATING_EVENT"
    forged_product = attach_extension(base, make_extension(base, forged))
    with pytest.raises(ValueError, match="UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED"):
        validate_product(forged_product, target_trade_date=TARGET,
            publication_date=PUBLICATION, catalog=catalog_read["catalog"])
    bad_decisions_path = tmp_path / "article_decisions.reader_gap_selected.test_fixture.json"
    bad_decisions_path.write_text(json.dumps({"article_decisions": forged}, ensure_ascii=False,
        sort_keys=True), encoding="utf-8")
    bad_args = SimpleNamespace(**{**vars(prep_args), "decisions": str(bad_decisions_path)})
    with pytest.raises(ValueError, match="UNASSESSED_CONTENT_SELECTION_MUST_BE_NOT_ASSESSED"):
        cli._build(bad_args, reviewed=False, include_product=True)

    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic_sha = hashlib.sha256(semantic_path.read_bytes()).hexdigest()
    body_sha = hashlib.sha256(body_path.read_bytes()).hexdigest()
    decision_sha = digest(decisions)
    reviewer = {
        "schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "decision_status": "EXPLICIT_DISPOSITIONS",
        "decision_payload_sha256": decision_sha, "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "evidence_run_id": RUN_ID,
        "reader_identity": "test-reader", "reviewer_identity": "test-reviewer",
        "reviewed_at": now, "catalog_product_sha256": catalog_read["catalog"]["sha256"],
        "semantic_catalog_sha256": semantic_sha, "body_corpus_sha256": body_sha,
    }
    reviewer_path = tmp_path / "reviewer_output.test_fixture.json"
    reviewer_path.write_text(json.dumps(reviewer, sort_keys=True), encoding="utf-8")
    registration_process = subprocess.run([
        sys.executable, str(CLI_PATH), "register-handoff", "--evidence-run-id", RUN_ID,
        "--research-state-root", str(state_root), "--target-date", TARGET,
        "--publication-date", PUBLICATION, "--semantic-catalog", str(semantic_path),
        "--reviewer-output", str(reviewer_path), "--decisions", str(decisions_path),
        "--parent-task-id", "test-parent", "--reader-identity", "test-reader",
        "--reviewer-identity", "test-reviewer",
    ], cwd="/", capture_output=True, text=True, check=False)
    assert registration_process.returncode == 0, registration_process.stderr[:500]
    registration = json.loads(registration_process.stdout)
    assert registration["status"] == "OUTPUT_BOUND_HANDOFF_REGISTERED"
    assert registration["decision_status"] == "EXPLICIT_DISPOSITIONS"

    _seed_owner_state(state_root, catalog_read)
    manager_store = ManagerResearchStore(state_root)
    material_cls = body_batch.imports()["MaterialStore"]
    service = ManagerResearchJobService(manager_store, None, None,
        material_store=material_cls(state_root / "materials"))
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    envelope = {"schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
        "evidence_run_id": RUN_ID,
        "handoff_manifest_sha256": registration["handoff_manifest_sha256"],
        "product_sha256": registration["product_sha256"]}
    with TestClient(app) as client:
        imported = client.post("/api/v4/manager/research/announcements/analysis/import",
            headers={"Origin": "http://testserver"}, json=envelope)
        assert imported.status_code == 200, imported.text[:500]
        assert imported.json()["analysis"]["status"] == "VERIFIED"
        assert imported.json()["owner_import_receipt"]["product_sha256"] == registration["product_sha256"]
        readback = client.get("/api/v4/manager/research/announcements/analysis",
            params={"date": TARGET, "publication_date": PUBLICATION.replace("-", "")})
        assert readback.status_code == 200, readback.text[:500]
        assert readback.json()["analysis"]["product_sha256"] == registration["product_sha256"]
        assert readback.json()["owner_import_receipt"]["status"] == "VERIFIED"

    owner_available = datetime.fromisoformat(readback.json()["owner_import_receipt"]["available_at"])
    before_cutoff = read_reviewed_analysis_references(service, {
        "plan_trade_date": TARGET, "source_dates": [TARGET],
        "research_cutoff": (owner_available - timedelta(seconds=1)).isoformat(),
    })
    assert before_cutoff["products"][0]["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
    assert before_cutoff["research_references"] == []
    after_cutoff = read_reviewed_analysis_references(service, {
        "plan_trade_date": TARGET, "source_dates": [TARGET],
        "research_cutoff": (owner_available + timedelta(seconds=2)).isoformat(),
    })
    assert after_cutoff["products"][0]["status"] == "CONSUMED"
    referenced_articles = {ref["art_code"] for item in after_cutoff["research_references"]
                           for ref in item["article_refs"]}
    assert referenced_articles == {first_good}
    assert not referenced_articles.intersection(failed)


def test_terminal_partial_rejects_a_missing_body_row_even_when_batch_receipt_is_resealed(tmp_path):
    state_root = tmp_path / "state"
    evidence = _copy_evidence(state_root)
    body_path = evidence / "body_corpus.json"
    body = json.loads(body_path.read_text(encoding="utf-8"))
    body["rows"].pop()
    body["article_count"] -= 1
    body["transport_complete_body_count"] -= 1
    body_raw = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    body_path.write_bytes(body_raw)
    body_sha = hashlib.sha256(body_raw).hexdigest()
    batch_path = evidence / "body_batch_receipt.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    batch["body_corpus_sha256"] = body_sha
    batch_raw = (json.dumps(batch, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    batch_path.write_bytes(batch_raw)
    capture_path = evidence / "capture_receipt.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["body_corpus_file_sha256"] = body_sha
    capture["body_batch_receipt_sha256"] = hashlib.sha256(batch_raw).hexdigest()
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n", encoding="utf-8")
    catalog_read = json.loads((evidence / "catalog_read.json").read_text(encoding="utf-8"))
    try:
        validate_terminal_body_capture(evidence, catalog_read, TARGET, PUBLICATION,
            expected_run_id=RUN_ID)
    except ValueError as exc:
        assert str(exc) == "ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_SET_INCOMPLETE"
    else:
        raise AssertionError("a partial terminal set with a missing article was accepted")


def test_terminal_partial_rejects_unknown_status_fake_complete_and_unbound_failure_bytes(tmp_path):
    state_root = tmp_path / "state"
    evidence = _copy_evidence(state_root)
    catalog_read = json.loads((evidence / "catalog_read.json").read_text(encoding="utf-8"))
    paths = {name: evidence / name for name in (
        "body_corpus.json", "body_corpus_manifest.json", "body_batch_receipt.json", "capture_receipt.json",
    )}
    original_bytes = {name: path.read_bytes() for name, path in paths.items()}
    failed_manifest_row = next(row for row in json.loads(original_bytes["body_corpus_manifest.json"])["article_receipts"]
                               if row["body_status"] == "BODY_CAPTURE_FAILED")
    failed_artifact = evidence / "body_batch" / failed_manifest_row["body_path"]
    original_failed_artifact = failed_artifact.read_bytes()

    def restore():
        for name, raw in original_bytes.items():
            paths[name].write_bytes(raw)
        failed_artifact.write_bytes(original_failed_artifact)

    def reseal(*, body: dict, manifest: dict, batch: dict, capture: dict):
        def raw(value):
            return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        manifest_raw = raw(manifest)
        paths["body_corpus_manifest.json"].write_bytes(manifest_raw)
        manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
        body["source_manifest_sha256"] = manifest_sha
        body_raw = raw(body)
        paths["body_corpus.json"].write_bytes(body_raw)
        body_sha = hashlib.sha256(body_raw).hexdigest()
        batch["body_corpus_sha256"] = body_sha
        batch["body_corpus_manifest_sha256"] = manifest_sha
        batch_raw = raw(batch)
        paths["body_batch_receipt.json"].write_bytes(batch_raw)
        capture["body_corpus_file_sha256"] = body_sha
        capture["body_corpus_manifest_file_sha256"] = manifest_sha
        capture["body_batch_receipt_sha256"] = hashlib.sha256(batch_raw).hexdigest()
        paths["capture_receipt.json"].write_bytes(raw(capture))

    mutations = (
        ("reordered_rows", "ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_SET_MISMATCH"),
        ("duplicate_row", "ANNOUNCEMENT_BODY_CAPTURE_TERMINAL_SET_INCOMPLETE"),
        ("unknown_status", "ANNOUNCEMENT_BODY_CAPTURE_NONTERMINAL_STATUS"),
        ("fake_complete", "ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_SOURCE_BINDING_INVALID"),
        ("missing_error", "ANNOUNCEMENT_BODY_CAPTURE_FAILURE_RECEIPT_INVALID"),
    )
    for case, expected_error in mutations:
        restore()
        body = json.loads(original_bytes["body_corpus.json"])
        manifest = json.loads(original_bytes["body_corpus_manifest.json"])
        batch = json.loads(original_bytes["body_batch_receipt.json"])
        capture = json.loads(original_bytes["capture_receipt.json"])
        if case == "reordered_rows":
            body["rows"][0], body["rows"][1] = body["rows"][1], body["rows"][0]
        elif case == "duplicate_row":
            body["rows"].append(copy.deepcopy(body["rows"][0]))
            body["article_count"] += 1
            if body["rows"][-1]["body_status"] == "COMPLETE_CONTENT_API_BODY":
                body["transport_complete_body_count"] += 1
        elif case == "unknown_status":
            next(row for row in manifest["article_receipts"]
                 if row["body_status"] == "BODY_CAPTURE_FAILED")["body_status"] = "IN_PROGRESS"
        elif case == "fake_complete":
            failed_code = failed_manifest_row["art_code"]
            row = next(row for row in body["rows"] if row["art_code"] == failed_code)
            row["body_status"] = "COMPLETE_CONTENT_API_BODY"
            row["transport_body_status"] = "COMPLETE_CONTENT_API_BODY"
            body["transport_complete_body_count"] += 1
        else:
            next(row for row in manifest["article_receipts"]
                 if row["body_status"] == "BODY_CAPTURE_FAILED")["error_code"] = None
        reseal(body=body, manifest=manifest, batch=batch, capture=capture)
        with pytest.raises(ValueError, match=expected_error):
            validate_terminal_body_capture(evidence, catalog_read, TARGET, PUBLICATION,
                expected_run_id=RUN_ID)
    restore()
    failed_artifact.write_bytes(original_failed_artifact + b" ")
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_ARTICLE_SOURCE_BINDING_INVALID"):
        validate_terminal_body_capture(evidence, catalog_read, TARGET, PUBLICATION,
            expected_run_id=RUN_ID)


def test_exact_complete_pass_terminal_capture_remains_accepted(tmp_path):
    evidence = _write_minimal_complete_evidence(tmp_path / "state")
    catalog_read = json.loads((evidence / "catalog_read.json").read_text(encoding="utf-8"))
    terminal = validate_terminal_body_capture(evidence, catalog_read, TARGET, PUBLICATION,
        expected_run_id=RUN_ID)
    assert terminal["status"] == "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS"
    assert terminal["body_status_counts"] == {"COMPLETE_CONTENT_API_BODY": 1}
    assert terminal["failed_articles"] == []


def test_prepare_cli_binds_capture_run_id_under_nonhex_evidence_parent(tmp_path):
    state_root = tmp_path / "isolated-state"
    source_evidence = _copy_evidence(state_root)
    evidence = tmp_path / "nonhex-container" / "evidence"
    shutil.copytree(source_evidence, evidence)
    catalog_read = json.loads((source_evidence / "catalog_read.json").read_text(encoding="utf-8"))
    catalog = catalog_read["catalog"]
    expected_run_id = hashlib.sha256(json.dumps({
        "target_trade_date": TARGET,
        "publication_date": PUBLICATION,
        "catalog_run_id": catalog["run_id"],
        "catalog_product_sha256": catalog["sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    assert expected_run_id == RUN_ID

    semantic_path = tmp_path / "semantic_catalog.test_fixture.json"
    semantic = _semantic_fixture(catalog_read,
        json.loads((source_evidence / "body_corpus.json").read_text(encoding="utf-8")))
    semantic_path.write_text(json.dumps(semantic, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")

    def prepare(evidence_root: Path):
        return subprocess.run([
            sys.executable, str(CLI_PATH), "prepare", "--target-date", TARGET,
            "--publication-date", PUBLICATION, "--catalog-read", str(evidence_root / "catalog_read.json"),
            "--semantic-catalog", str(semantic_path), "--body-corpus", str(evidence_root / "body_corpus.json"),
            "--body-capture-evidence-root", str(evidence_root),
        ], cwd="/", capture_output=True, text=True, check=False)

    correctly_bound = prepare(source_evidence)
    assert correctly_bound.returncode == 0, correctly_bound.stderr[:500]
    assert json.loads(correctly_bound.stdout)["status"] == "PREPARED_EXACT_INPUTS"

    capture_path = evidence / "capture_receipt.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    capture["evidence_run_id"] = "0" * 32
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    mismatched = prepare(evidence)
    assert mismatched.returncode == 2
    failure = json.loads(mismatched.stdout)
    assert failure["status"] == "FAILED"
    assert failure["reason"] == "ANNOUNCEMENT_BODY_CAPTURE_RUN_ID_MISMATCH"
