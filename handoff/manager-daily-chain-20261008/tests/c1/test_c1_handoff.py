from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

API_ROOT = Path(__file__).resolve().parents[1] / "release" / "api_app"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ops import run_manager_daily_announcement as cli
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.workspace_announcements import (
    read_reviewed_analysis_references, validate_registered_handoff,
)
from v4.manager_research.workspace_projection import digest

SOURCE_EVIDENCE = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/"
    "daily_runs/20261007_20261006/evidence"
)
TARGET = "20261007"
PUBLICATION = "2026-10-06"
RUN_ID = "f" * 32


def _source_setup(root: Path, *, reader_identity="reader-A", reviewer_identity="reviewer-B",
                  reviewer_target=TARGET, reviewer_publication=PUBLICATION):
    catalog_read = json.loads((SOURCE_EVIDENCE / "candidate_api_catalog_get.json").read_text())
    evidence = root / "announcement_agent_runs" / RUN_ID / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "catalog_read.json").write_text(json.dumps(catalog_read, ensure_ascii=False))
    (evidence / "body_corpus.json").write_bytes(
        (SOURCE_EVIDENCE / "analysis_body_corpus_20261007_v2.json").read_bytes()
    )
    catalog = catalog_read["catalog"]
    body_sha = hashlib.sha256((evidence / "body_corpus.json").read_bytes()).hexdigest()
    (evidence / "body_corpus_manifest.json").write_text(json.dumps({
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "body_status_counts": {"COMPLETE_CONTENT_API_BODY": catalog["manager_consumer_row_count"]},
    }))
    (evidence / "body_batch_receipt.json").write_text(json.dumps({
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS",
        "article_rows": catalog["manager_consumer_row_count"],
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "catalog_run_id": catalog["run_id"], "catalog_sha256": catalog["sha256"],
        "body_corpus_sha256": body_sha,
        "body_corpus_manifest_sha256": hashlib.sha256((evidence / "body_corpus_manifest.json").read_bytes()).hexdigest(),
    }))
    def sha(name):
        return hashlib.sha256((evidence / name).read_bytes()).hexdigest()
    (evidence / "capture_receipt.json").write_text(json.dumps({
        "status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS",
        "evidence_run_id": RUN_ID, "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "catalog_product_sha256": catalog["sha256"],
        "catalog_read_file_sha256": sha("catalog_read.json"),
        "body_corpus_file_sha256": body_sha,
        "body_corpus_manifest_file_sha256": sha("body_corpus_manifest.json"),
        "body_batch_receipt_sha256": sha("body_batch_receipt.json"),
    }))
    semantic_path = SOURCE_EVIDENCE / "semantic_catalog_20261007_v3.json"
    reviewer_path = root / "reviewer_output.json"
    semantic_sha = hashlib.sha256(semantic_path.read_bytes()).hexdigest()
    reviewer = {
        "schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "target_trade_date": reviewer_target,
        "publication_date": reviewer_publication, "evidence_run_id": RUN_ID,
        "decision_status": "NOT_ASSESSED", "decision_payload_sha256": None,
        "reader_identity": reader_identity, "reviewer_identity": reviewer_identity,
        "reviewed_at": "2026-10-08T00:00:00+08:00",
        "catalog_product_sha256": catalog["sha256"],
        "semantic_catalog_sha256": semantic_sha, "body_corpus_sha256": body_sha,
    }
    reviewer_path.write_text(json.dumps(reviewer, ensure_ascii=False, sort_keys=True))
    args = SimpleNamespace(evidence_run_id=RUN_ID, research_state_root=str(root),
        target_date=TARGET, publication_date=PUBLICATION,
        semantic_catalog=str(semantic_path), reviewer_output=str(reviewer_path), decisions=None,
        parent_task_id="offline-heartbeat", reader_identity=reader_identity,
        reviewer_identity=reviewer_identity)
    result = cli._register_handoff(args)
    repeated = cli._register_handoff(args)
    assert repeated["handoff_manifest_sha256"] == result["handoff_manifest_sha256"]
    assert repeated["product_sha256"] == result["product_sha256"]
    return catalog_read, result


def test_handoff_rejects_fake_output_sha(tmp_path: Path):
    product = {
        "target_trade_date": TARGET, "publication_date": PUBLICATION,
        "source_manifest": {"semantic_catalog_sha256": "0" * 64,
            "body_corpus_sha256": "0" * 64, "catalog_product_sha256": "0" * 64},
        "agent_judgment_receipt": {
            "schema_version": "v4.manager_research.announcement_agent_judgment.v1",
            "status": "VERIFIED", "target_trade_date": TARGET,
            "publication_date": PUBLICATION, "parent_task_id": "x", "parent_run_id": "y",
            "reviewer_identity": "same", "reader_identity": "same",
            "reviewed_at": "2026-10-08T00:00:00Z", "agent_output_sha256": "0" * 64,
            "reader_output_sha256": "0" * 64, "reviewer_output_sha256": "0" * 64,
            "source_run_sha256": "0" * 64, "semantic_catalog_sha256": "0" * 64,
            "body_corpus_sha256": "0" * 64, "evidence_run_id": "0" * 32,
            "evidence_binding_status": "OUTPUT_BOUND", "external_review_status": "DECLARED",
            "reviewer_conclusion": "PASS", "reviewer_decision_payload_sha256": None,
            "decision_status": "NOT_ASSESSED", "decision_payload_sha256": None,
            "article_decision_count": 0, **{"RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False},
        },
    }
    from v4.manager_research.workspace_announcements import validate_agent_judgment_receipt
    with pytest.raises(ValueError):
        validate_agent_judgment_receipt(product["agent_judgment_receipt"], product)


def test_register_import_and_plan_are_bound_to_fixed_evidence(tmp_path: Path):
    catalog_read, registered = _source_setup(tmp_path)
    assert registered["status"] == "OUTPUT_BOUND_HANDOFF_REGISTERED"
    assert registered["external_review_status"] == "DECLARED"
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, None, None)
    service.get_announcement_date_catalog = lambda target, publication: catalog_read
    app = FastAPI()
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app.include_router(create_manager_research_router(service))
    client = TestClient(app)
    envelope = {
        "schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
        "evidence_run_id": RUN_ID,
        "handoff_manifest_sha256": registered["handoff_manifest_sha256"],
        "product_sha256": registered["product_sha256"],
    }
    response = client.post("/api/v4/manager/research/announcements/analysis/import",
        headers={"Origin": "http://testserver"}, json=envelope)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis"]["product_sha256"] == registered["product_sha256"]
    invalid = client.post("/api/v4/manager/research/announcements/analysis/import",
        headers={"Origin": "http://testserver"}, json={**envelope, "path": "/tmp/forbidden.json"})
    assert invalid.status_code == 422

    owner_available = datetime.fromisoformat(result["owner_import_receipt"]["available_at"])
    early_cutoff = (owner_available - timedelta(seconds=1)).isoformat()
    early = read_reviewed_analysis_references(service, dict(
        plan_trade_date=TARGET, source_dates=[TARGET], research_cutoff=early_cutoff))
    assert early["products"][0]["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
    assert early["input_identity"] == digest([])
    cutoff = "2099-01-01T00:00:00+08:00"
    context = dict(plan_trade_date=TARGET, source_dates=[TARGET], research_cutoff=cutoff)
    plan = read_reviewed_analysis_references(service, context)
    assert plan["products"][0]["status"] == "CONSUMED"
    assert plan["research_references"] == []

    reviewer_path = tmp_path / "announcement_agent_runs" / RUN_ID / "evidence" / "reviewer_output.json"
    reviewer_path.write_bytes(b"replaced output bytes")
    plan = read_reviewed_analysis_references(service, context)
    assert plan["products"][0]["status"] == "NOT_CONSUMED_INVALID"
    assert any("HANDOFF" in gap for gap in plan["gaps"])


def test_registration_rejects_same_identity_and_wrong_review_pair(tmp_path: Path):
    same_root = tmp_path / "same"
    same_root.mkdir()
    with pytest.raises(ValueError, match="REVIEW_OUTPUT_INVALID"):
        _source_setup(same_root, reviewer_identity="reader-A")
    wrong_date_root = tmp_path / "wrong-date"
    wrong_date_root.mkdir()
    with pytest.raises(ValueError, match="REVIEW_OUTPUT_INVALID"):
        _source_setup(wrong_date_root, reviewer_publication="2026-10-05")


def test_handoff_rejects_wrong_manifest_and_symlinked_product(tmp_path: Path):
    _, registered = _source_setup(tmp_path)
    from v4.manager_research.workspace_announcements import _handoff_root
    evidence = _handoff_root(SimpleNamespace(root=tmp_path), RUN_ID)
    with pytest.raises(ValueError):
        validate_registered_handoff(SimpleNamespace(root=tmp_path), RUN_ID,
            "0" * 64, registered["product_sha256"])
    product = evidence / "analysis_product.json"
    moved = evidence / "analysis_product_saved.json"
    product.rename(moved)
    product.symlink_to(moved)
    with pytest.raises(ValueError):
        validate_registered_handoff(SimpleNamespace(root=tmp_path), RUN_ID,
            registered["handoff_manifest_sha256"], registered["product_sha256"])
