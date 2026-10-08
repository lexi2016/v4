from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPAIR_APP = ROOT / "release" / "api_app"
C1_APP = ROOT.parent / "c1" / "release" / "api_app"
SOURCE_EVIDENCE = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/"
    "daily_runs/20261007_20261006/evidence"
)
TARGET = "20261007"
PUBLICATION = "2026-10-06"
RUN_ID = "e" * 32


def _load_repair_modules():
    if str(C1_APP) not in sys.path:
        sys.path.insert(0, str(C1_APP))
    importlib.import_module("v4.manager_research")
    workspace_path = REPAIR_APP / "v4" / "manager_research" / "workspace_announcements.py"
    name = "v4.manager_research.workspace_announcements"
    spec = importlib.util.spec_from_file_location(name, workspace_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    cli_spec = importlib.util.spec_from_file_location(
        "c1_repair_run_manager_daily_announcement",
        REPAIR_APP / "ops" / "run_manager_daily_announcement.py",
    )
    assert cli_spec is not None and cli_spec.loader is not None
    cli = importlib.util.module_from_spec(cli_spec)
    cli_spec.loader.exec_module(cli)
    return cli, module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_handoff(root: Path, *, wrapped: bool):
    cli, _ = _load_repair_modules()
    catalog_read = json.loads((SOURCE_EVIDENCE / "candidate_api_catalog_get.json").read_text())
    evidence = root / "announcement_agent_runs" / RUN_ID / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "catalog_read.json").write_text(json.dumps(catalog_read, ensure_ascii=False))
    (evidence / "body_corpus.json").write_bytes(
        (SOURCE_EVIDENCE / "analysis_body_corpus_20261007_v2.json").read_bytes()
    )
    catalog = catalog_read["catalog"]
    body_sha = _sha(evidence / "body_corpus.json")
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
        "body_corpus_manifest_sha256": _sha(evidence / "body_corpus_manifest.json"),
    }))
    def sha(name: str) -> str:
        return _sha(evidence / name)
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
    build_args = SimpleNamespace(target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(evidence / "catalog_read.json"), semantic_catalog=str(semantic_path),
        body_corpus=str(evidence / "body_corpus.json"), out=None, decisions=None, review_receipt=None)
    base = cli._build(build_args, reviewed=False, include_product=True)["product"]
    records = base["records"]
    eligible = next(row for row in records if isinstance(row.get("issuer_codes"), list) and row["issuer_codes"])
    selected_art_code = eligible["art_code"]
    decisions = []
    for record in records:
        selected = record["art_code"] == selected_art_code
        decisions.append({
            "art_code": record["art_code"],
            "issuer_codes": [issuer["code"] for issuer in record["issuer_codes"]],
            "security_scope": record.get("security_scope"),
            "semantic_record_sha256": record.get("semantic_record_sha256"),
            "body_record_sha256": record.get("body_record_sha256"),
            "disposition": "CONDITIONAL_WATCH" if selected else "NOT_SELECTED",
            "selection_basis": "CONDITIONAL_WATCH" if selected else "NOT_SELECTED",
            "reason": "synthetic explicit regression fixture disposition",
            "risk_notes": [],
        })
    decisions.sort(key=lambda item: item["art_code"])
    decision_payload = {"article_decisions": decisions} if wrapped else decisions
    decisions_path = root / "decisions_input.json"
    decisions_path.write_text(json.dumps(decision_payload, ensure_ascii=False, sort_keys=True))
    semantic_sha = _sha(semantic_path)
    reviewer_path = root / "reviewer_input.json"
    reviewer_path.write_text(json.dumps({
        "schema_version": "v4.manager_research.announcement_agent_review.v1",
        "review_conclusion": "PASS", "target_trade_date": TARGET,
        "publication_date": PUBLICATION, "evidence_run_id": RUN_ID,
        "decision_status": "EXPLICIT_DISPOSITIONS", "decision_payload_sha256": cli.digest(decisions),
        "reader_identity": "synthetic-reader-fixture", "reviewer_identity": "synthetic-reviewer-fixture",
        "reviewed_at": "2026-10-08T00:00:00+08:00",
        "catalog_product_sha256": catalog["sha256"],
        "semantic_catalog_sha256": semantic_sha, "body_corpus_sha256": body_sha,
    }, ensure_ascii=False, sort_keys=True))
    args = SimpleNamespace(
        evidence_run_id=RUN_ID, research_state_root=str(root), target_date=TARGET,
        publication_date=PUBLICATION, semantic_catalog=str(semantic_path),
        reviewer_output=str(reviewer_path), decisions=str(decisions_path),
        parent_task_id="synthetic-regression-fixture",
        reader_identity="synthetic-reader-fixture", reviewer_identity="synthetic-reviewer-fixture",
    )
    registered = cli._register_handoff(args)
    repeated = cli._register_handoff(args)
    assert repeated["handoff_manifest_sha256"] == registered["handoff_manifest_sha256"]
    assert repeated["product_sha256"] == registered["product_sha256"]
    conflict_path = root / "decisions_conflict_input.json"
    conflict_path.write_text(json.dumps(decision_payload, ensure_ascii=False, indent=2))
    conflict_args = SimpleNamespace(**vars(args))
    conflict_args.decisions = str(conflict_path)
    with pytest.raises(ValueError, match="OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"):
        cli._register_handoff(conflict_args)
    return cli, catalog_read, registered, selected_art_code


@pytest.mark.parametrize("wrapped", [False, True], ids=["raw-list", "article-decisions-wrapper"])
def test_explicit_selected_watch_import_readback_plan_and_cutoff(tmp_path: Path, wrapped: bool):
    cli, catalog_read, registered, selected_art_code = _fixture_handoff(tmp_path, wrapped=wrapped)
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.workspace_announcements import read_reviewed_analysis_references
    from v4.manager_research.workspace_projection import digest
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    service = ManagerResearchJobService(ManagerResearchStore(tmp_path), None, None)
    service.get_announcement_date_catalog = lambda target, publication: catalog_read
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    client = TestClient(app)
    envelope = {
        "schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
        "evidence_run_id": RUN_ID,
        "handoff_manifest_sha256": registered["handoff_manifest_sha256"],
        "product_sha256": registered["product_sha256"],
    }
    response = client.post(
        "/api/v4/manager/research/announcements/analysis/import",
        headers={"Origin": "http://testserver"}, json=envelope,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis"]["product_sha256"] == registered["product_sha256"]
    assert result["owner_import_receipt"]["status"] == "VERIFIED"
    repeated_import = client.post(
        "/api/v4/manager/research/announcements/analysis/import",
        headers={"Origin": "http://testserver"}, json=envelope,
    )
    assert repeated_import.status_code == 200, repeated_import.text
    assert repeated_import.json()["analysis"]["product_sha256"] == registered["product_sha256"]

    available = datetime.fromisoformat(result["owner_import_receipt"]["available_at"])
    context = {"plan_trade_date": TARGET, "source_dates": [TARGET],
               "research_cutoff": (available + timedelta(seconds=1)).isoformat()}
    plan = read_reviewed_analysis_references(service, context)
    assert plan["products"][0]["status"] == "CONSUMED"
    assert plan["research_references"]
    assert any(
        ref.get("research_status") == "CONDITIONAL_WATCH"
        and any(article.get("art_code") == selected_art_code for article in ref.get("article_refs", []))
        for ref in plan["research_references"]
    )

    late_context = {**context, "research_cutoff": (available - timedelta(seconds=1)).isoformat()}
    late_plan = read_reviewed_analysis_references(service, late_context)
    assert late_plan["products"][0]["status"] == "NOT_CONSUMED_AFTER_CUTOFF"
    assert late_plan["research_references"] == []
    assert late_plan["input_identity"] == digest([])

    evidence = tmp_path / "announcement_agent_runs" / RUN_ID / "evidence"
    reviewer_path = evidence / "reviewer_output.json"
    reviewer_path.write_bytes(b"tampered registered reviewer bytes")
    invalid_plan = read_reviewed_analysis_references(service, context)
    assert invalid_plan["products"][0]["status"] == "NOT_CONSUMED_INVALID"
    assert any("HANDOFF" in gap for gap in invalid_plan["gaps"])


def test_decision_wrapper_rejects_unbound_extra_fields(tmp_path: Path):
    _, _, registered, _ = _fixture_handoff(tmp_path, wrapped=True)
    from types import SimpleNamespace
    from v4.manager_research.workspace_announcements import validate_registered_handoff
    from v4.manager_research.workspace_projection import digest

    evidence = tmp_path / "announcement_agent_runs" / RUN_ID / "evidence"
    decisions_path = evidence / "article_decisions.json"
    decision_document = json.loads(decisions_path.read_text())
    decision_document["unbound_extra"] = True
    raw = json.dumps(decision_document, ensure_ascii=False, sort_keys=True).encode()
    decisions_path.write_bytes(raw)
    manifest_path = evidence / "handoff_manifest.v1.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["article_decisions.json"] = hashlib.sha256(raw).hexdigest()
    manifest.pop("sha256", None)
    manifest["sha256"] = digest(manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    with pytest.raises(ValueError, match="HANDOFF_DECISIONS_INVALID"):
        validate_registered_handoff(SimpleNamespace(root=tmp_path), RUN_ID,
            manifest["sha256"], registered["product_sha256"])
